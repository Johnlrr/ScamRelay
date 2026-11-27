"""DeterministicValidator cho RelayRuleDraft (SPEC §7.2b, V1–V8).

Hai cửa vào:
- `validate_llm_output(raw)`: JSON/dict thô từ Gemini → V8 (gỡ trường quyền) → V1 (parse strict)
  → `validate_rule`.
- `validate_rule(draft)`: V2–V7 trên domain model; V3 chuyển điều kiện hành vi sang
  `behavior_hints` và trả bản đã chuyển ở `sanitized_draft`. V6b chỉ cảnh báo.

Không có nhánh nào tự sửa im lặng: mọi thay đổi (V3, V8) đều ghi vào `warnings`.
Validator không bao giờ gán threshold/action/stage — đó là việc của server sau khi duyệt.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from pydantic import ValidationError

# TODO(contract-drop): đổi sang `from app.schemas.rule import ...` rồi xóa _contract_draft.py
from app.core._contract_draft import Condition, RelayRuleDraft, ValidationResult
from app.core.preprocess import _PHONE, norm, norm_match

# ---------------------------------------------------------------- hằng số

CONTENT_FIELD = "transfer_note"
CONTENT_OPS = {"SEMANTIC_MATCH", "CONTAINS_ANY", "NOT_CONTAINS_ANY"}
INT_FIELDS = {"amount_vnd", "recipient_account_age_days", "tx_count_10m", "partner_risk_score"}
BOOL_FIELDS = {"recipient_is_new", "is_verified_biller", "account_compromise_flag"}
ALLOWED_FIELDS = {CONTENT_FIELD} | INT_FIELDS | BOOL_FIELDS
ALLOWED_OPS = {"EQ", "LTE", "GTE"} | CONTENT_OPS
VALUE_SLOTS = ("value_int", "value_bool", "value_str_list", "anchor_phrases")

MAX_CONDITIONS = 4
ANCHOR_COUNT = (3, 12)
ANCHOR_LEN = (3, 80)
CONTAINS_MAX = 12
NOT_CONTAINS_MAX = 10
PHRASE_LEN = (3, 40)
AMOUNT_RANGE = (10_000, 50_000_000)
RISK_SCORE_RANGE = (0, 100)
VARIANT_COUNT = (5, 8)
QUESTION_MAX, LABEL_MAX, ALERT_MAX = 120, 100, 240
VARIANT_NOTE_MAX, VARIANT_INTENT_MAX = 60, 100
REQUIRED_OUTCOMES = ["BENIGN", "BENIGN", "TACTIC_MATCH"]   # đúng 3 phương án; UNCLEAR do server thêm
TACTIC_RE = re.compile(r"^[A-Z0-9_]{3,60}$")

# V8: trường quyền LLM không được đặt. Gỡ ở mọi cấp, ghi warning.
AUTHORITY_KEYS = {
    "threshold", "action", "stage", "ttl_hours", "corroboration_count", "approved_by",
    "approvals", "rule_id", "version", "source_incident_id", "target_scope", "lifecycle",
    "guard_conditions", "normalize", "anti_coaching_notice_vi", "id", "benign_regression",
    "variant_coverage", "edited_by_human",
}

# V6: từ cấm trong câu hỏi/nhãn. Có dấu: so trên lowercase NFC theo ranh giới từ.
# Không dấu: chỉ cụm đủ đặc hiệu ("lua" đơn lẻ trùng "lúa", "lựa").
BANNED_ACCENTED = ("lừa", "lừa đảo", "bị dụ", "kẻ gian", "nghi ngờ")
BANNED_UNACCENTED = ("lua dao", "bi du", "ke gian", "nghi ngo")

_LONG_DIGITS = re.compile(r"\d(?:[.\-]?\d){5,}")
_URL = re.compile(
    r"https?://|www\.|\b[a-z0-9-]+\.(?:com|vn|net|org|info|xyz|top|io|me|link|site|online|app|cc|biz)\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


# ---------------------------------------------------------------- helpers

def _contact_content(text: str) -> list[str]:
    """V6/V7: chữ hiển thị cho người dùng không được chứa SĐT, URL, email."""
    found = []
    if _PHONE.search(text):
        found.append("số điện thoại")
    if _URL.search(text):
        found.append("URL")
    if _EMAIL.search(text):
        found.append("email")
    return found


def _forbidden_content(text: str) -> list[str]:
    """V4: cụm chữ trong luật (anchor, CONTAINS_ANY, NOT_CONTAINS_ANY, biến thể) — thêm lệnh cấm ≥6 chữ số."""
    found = ["chuỗi ≥6 chữ số"] if _LONG_DIGITS.search(text) else []
    return found + _contact_content(text)


def _present(value: Any) -> bool:
    # Gemini đôi khi trả [] thay cho null ở trường không dùng: coi như vắng mặt.
    return value is not None and value != []


def _banned_words(text: str) -> list[str]:
    lowered = unicodedata.normalize("NFC", text).lower()
    hits = [w for w in BANNED_ACCENTED if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", lowered)]
    plain = f" {norm(text)} "
    hits += [w for w in BANNED_UNACCENTED if f" {w} " in plain]
    return hits


def _strip_authority(obj: Any, path: str, warnings: list[str]) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in AUTHORITY_KEYS:
                warnings.append(f"V8: bỏ qua trường quyền '{path}{k}' do LLM gửi; server tự gán")
                continue
            out[k] = _strip_authority(v, f"{path}{k}.", warnings)
        return out
    if isinstance(obj, list):
        return [_strip_authority(v, f"{path}{i}.", warnings) for i, v in enumerate(obj)]
    return obj


def _check_condition(c: Condition, where: str, errors: list[str]) -> None:
    # V2: whitelist + op hợp với field
    if c.field not in ALLOWED_FIELDS:
        errors.append(f"V2: {where}.field '{c.field}' không thuộc whitelist")
        return
    if c.op not in ALLOWED_OPS:
        errors.append(f"V2: {where}.op '{c.op}' không thuộc whitelist")
        return
    if c.field == CONTENT_FIELD:
        if c.op not in CONTENT_OPS:
            errors.append(f"V2: {where}: transfer_note chỉ dùng {sorted(CONTENT_OPS)}")
            return
    elif c.op in CONTENT_OPS:
        errors.append(f"V2: {where}: {c.op} chỉ áp lên transfer_note, không áp lên {c.field}")
        return
    elif c.field in BOOL_FIELDS and c.op != "EQ":
        errors.append(f"V2: {where}: trường bool {c.field} chỉ dùng EQ")
        return

    # V5: đúng một trường giá trị, đúng loại
    expected = {
        "SEMANTIC_MATCH": "anchor_phrases",
        "CONTAINS_ANY": "value_str_list",
        "NOT_CONTAINS_ANY": "value_str_list",
    }.get(c.op) or ("value_bool" if c.field in BOOL_FIELDS else "value_int")
    present = [s for s in VALUE_SLOTS if _present(getattr(c, s))]
    if present != [expected]:
        errors.append(f"V5: {where}: {c.op} trên {c.field} cần đúng một trường '{expected}', đang có {present}")
        return

    if c.field == "amount_vnd" and not (AMOUNT_RANGE[0] <= c.value_int <= AMOUNT_RANGE[1]):
        errors.append(f"V5: {where}: amount_vnd {c.value_int} ngoài [{AMOUNT_RANGE[0]}; {AMOUNT_RANGE[1]}]")
    if c.field == "partner_risk_score" and not (RISK_SCORE_RANGE[0] <= c.value_int <= RISK_SCORE_RANGE[1]):
        errors.append(f"V5: {where}: partner_risk_score {c.value_int} ngoài [{RISK_SCORE_RANGE[0]}; {RISK_SCORE_RANGE[1]}]")
    if c.field in INT_FIELDS - {"amount_vnd", "partner_risk_score"} and c.value_int < 0:
        errors.append(f"V5: {where}: {c.field} không được âm")

    if c.op == "SEMANTIC_MATCH":
        _check_anchors(c.anchor_phrases, where, errors)
    elif c.op in ("CONTAINS_ANY", "NOT_CONTAINS_ANY"):
        _check_phrase_list(c, where, errors)


def _check_anchors(anchors: list[str], where: str, errors: list[str]) -> None:
    # V4
    unique = {norm_match(a) for a in anchors if norm_match(a)}
    if not (ANCHOR_COUNT[0] <= len(unique) <= ANCHOR_COUNT[1]):
        errors.append(f"V4: {where}: cần {ANCHOR_COUNT[0]}–{ANCHOR_COUNT[1]} anchor khác nhau, đang có {len(unique)}")
    for i, a in enumerate(anchors):
        n = len(a.strip())
        if not (ANCHOR_LEN[0] <= n <= ANCHOR_LEN[1]):
            errors.append(f"V4: {where}.anchor_phrases[{i}] dài {n} ký tự, cần {ANCHOR_LEN[0]}–{ANCHOR_LEN[1]}")
        for bad in _forbidden_content(a):
            errors.append(f"V4: {where}.anchor_phrases[{i}] chứa {bad} (luật không được nhắm vào tài khoản/cá nhân)")


def _check_phrase_list(c: Condition, where: str, errors: list[str]) -> None:
    # V3b + áp chung lệnh cấm của V4 cho mọi cụm từ trong luật
    limit = NOT_CONTAINS_MAX if c.op == "NOT_CONTAINS_ANY" else CONTAINS_MAX
    phrases = c.value_str_list
    if not (1 <= len(phrases) <= limit):
        errors.append(f"V3b: {where}: {c.op} cần 1–{limit} cụm, đang có {len(phrases)}")
    for i, p in enumerate(phrases):
        n = len(norm_match(p))
        if not (PHRASE_LEN[0] <= n <= PHRASE_LEN[1]):
            errors.append(f"V3b: {where}.value_str_list[{i}] dài {n} ký tự (sau chuẩn hóa), cần {PHRASE_LEN[0]}–{PHRASE_LEN[1]}")
        for bad in _forbidden_content(p):
            errors.append(f"V4: {where}.value_str_list[{i}] chứa {bad}")


def _drop_empty(c: Condition) -> Condition:
    return c.model_copy(update={s: None for s in VALUE_SLOTS if not _present(getattr(c, s))})


# ---------------------------------------------------------------- API

def validate_rule(draft: RelayRuleDraft) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not TACTIC_RE.match(draft.tactic_family):
        errors.append(f"V2: tactic_family '{draft.tactic_family}' phải khớp {TACTIC_RE.pattern}")

    # V3: lớp 1 chỉ gồm điều kiện nội dung trên transfer_note; điều kiện hành vi → behavior_hints
    if not (1 <= len(draft.conditions) <= MAX_CONDITIONS):
        errors.append(f"V3: cần 1–{MAX_CONDITIONS} điều kiện, đang có {len(draft.conditions)}")
    filters: list[Condition] = []
    hints: list[Condition] = list(draft.behavior_hints)
    for i, c in enumerate(draft.conditions):
        _check_condition(c, f"conditions[{i}]", errors)
        if c.field == CONTENT_FIELD:
            filters.append(c)
        else:
            hints.append(c)
            warnings.append(f"V3: conditions[{i}] ({c.field} {c.op}) chuyển sang behavior_hints, không dùng để lọc")
    for i, c in enumerate(draft.behavior_hints):
        _check_condition(c, f"behavior_hints[{i}]", errors)
        if c.field == CONTENT_FIELD:
            errors.append(f"V3: behavior_hints[{i}] không được là điều kiện nội dung")
    if not any(c.op in ("SEMANTIC_MATCH", "CONTAINS_ANY") for c in filters):
        errors.append("V3: lớp 1 cần ít nhất một SEMANTIC_MATCH hoặc CONTAINS_ANY trên transfer_note")

    # V6: câu hỏi mục đích — đúng 3 phương án (2 BENIGN + 1 TACTIC_MATCH), trung lập
    q = draft.purpose_question
    outcomes = [o.outcome for o in q.options]
    if sorted(outcomes) != REQUIRED_OUTCOMES:
        errors.append(f"V6: cần đúng 3 phương án gồm 2 BENIGN + 1 TACTIC_MATCH; đang có {outcomes}")
    if not (1 <= len(q.question_vi.strip()) <= QUESTION_MAX):
        errors.append(f"V6: question_vi phải 1–{QUESTION_MAX} ký tự")
    for w in _banned_words(q.question_vi):
        errors.append(f"V6: question_vi chứa từ cấm '{w}' (câu hỏi phải trung lập)")
    for bad in _contact_content(q.question_vi):
        errors.append(f"V6: question_vi chứa {bad}")
    for i, o in enumerate(q.options):
        if not (1 <= len(o.label_vi.strip()) <= LABEL_MAX):
            errors.append(f"V6: options[{i}].label_vi phải 1–{LABEL_MAX} ký tự")
        for w in _banned_words(o.label_vi):
            errors.append(f"V6: options[{i}].label_vi chứa từ cấm '{w}'")
        for bad in _contact_content(o.label_vi):
            errors.append(f"V6: options[{i}].label_vi chứa {bad}")

    # V6b (chỉ cảnh báo): nhãn TACTIC_MATCH nêu nguyên văn anchor → dễ bị dò đáp án
    anchors = {norm_match(a) for c in filters if c.op == "SEMANTIC_MATCH" for a in (c.anchor_phrases or [])}
    for i, o in enumerate(q.options):
        if o.outcome != "TACTIC_MATCH":
            continue
        label = f" {norm_match(o.label_vi)} "
        hit = sorted(a for a in anchors if a and f" {a} " in label)
        if hit:
            warnings.append(
                f"V6b: options[{i}] (TACTIC_MATCH) chứa nguyên văn anchor '{hit[0]}'; "
                "phương án đang nêu đúng tên thủ đoạn, nên viết theo nhóm mục đích chung"
            )

    # V7: lời giải thích thủ đoạn
    if not (1 <= len(q.tactic_alert_vi.strip()) <= ALERT_MAX):
        errors.append(f"V7: tactic_alert_vi phải 1–{ALERT_MAX} ký tự")
    for bad in _contact_content(q.tactic_alert_vi):
        errors.append(f"V7: tactic_alert_vi chứa {bad} (kênh liên hệ chỉ lấy từ registry)")

    # Biến thể có cấu trúc (chỉ để kiểm thử)
    if not (VARIANT_COUNT[0] <= len(draft.variants) <= VARIANT_COUNT[1]):
        errors.append(f"VAR: cần {VARIANT_COUNT[0]}–{VARIANT_COUNT[1]} biến thể, đang có {len(draft.variants)}")
    for i, v in enumerate(draft.variants):
        if not (1 <= len(v.transfer_note.strip()) <= VARIANT_NOTE_MAX):
            errors.append(f"VAR: variants[{i}].transfer_note phải 1–{VARIANT_NOTE_MAX} ký tự")
        if len(v.manipulation_intent) > VARIANT_INTENT_MAX:
            errors.append(f"VAR: variants[{i}].manipulation_intent quá {VARIANT_INTENT_MAX} ký tự")
        if not (AMOUNT_RANGE[0] <= v.amount_vnd <= AMOUNT_RANGE[1]):
            errors.append(f"VAR: variants[{i}].amount_vnd ngoài [{AMOUNT_RANGE[0]}; {AMOUNT_RANGE[1]}]")
        for bad in _forbidden_content(v.transfer_note + " " + v.manipulation_intent):
            errors.append(f"VAR: variants[{i}] chứa {bad}")

    if errors:
        return ValidationResult(ok=False, errors=errors, warnings=warnings)
    sanitized = draft.model_copy(
        update={"conditions": [_drop_empty(c) for c in filters], "behavior_hints": [_drop_empty(c) for c in hints]},
        deep=True,
    )
    return ValidationResult(ok=True, warnings=warnings, sanitized_draft=sanitized)


def validate_llm_output(raw: str | bytes | dict) -> ValidationResult:
    """V8 rồi V1 rồi V2–V7. Dùng cho output thô của LLM (và cho test injection INV-02)."""
    warnings: list[str] = []
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            return ValidationResult(ok=False, errors=[f"V1: JSON không hợp lệ: {e.msg}"])
    if not isinstance(raw, dict):
        return ValidationResult(ok=False, errors=["V1: output phải là object JSON"])
    cleaned = _strip_authority(raw, "", warnings)
    try:
        draft = RelayRuleDraft.model_validate(cleaned)
    except ValidationError as e:
        errors = [f"V1: {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        return ValidationResult(ok=False, errors=errors, warnings=warnings)
    result = validate_rule(draft)
    result.warnings = warnings + result.warnings
    return result
