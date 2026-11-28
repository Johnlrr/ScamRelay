import copy
import json

import pytest

from app.core.validator import validate_llm_output

VALID = {
    "tactic_family": "FAKE_HKD_TAX_VERIFICATION",
    "match_mode": "ALL",
    "conditions": [
        {
            "field": "transfer_note",
            "op": "SEMANTIC_MATCH",
            "anchor_phrases": [
                "dong phi xac minh tai khoan ho kinh doanh",
                "cap nhat thue ho kinh doanh 2026",
                "phi kich hoat ma so thue dien tu",
            ],
        },
        {"field": "transfer_note", "op": "NOT_CONTAINS_ANY", "value_str_list": ["thue nha", "thue mat bang"]},
    ],
    "purpose_question": {
        "question_vi": "Khoản chuyển này dùng để làm gì?",
        "options": [
            {"label_vi": "Mua hàng, trả tiền dịch vụ", "outcome": "BENIGN"},
            {"label_vi": "Trả tiền cho người thân, người quen", "outcome": "BENIGN"},
            {"label_vi": "Đóng phí để cơ quan hoặc tổ chức xử lý hồ sơ, tài khoản", "outcome": "TACTIC_MATCH"},
        ],
        "tactic_alert_vi": "Cơ quan thuế không yêu cầu chuyển phí vào tài khoản cá nhân để xác minh hộ kinh doanh.",
    },
    "variants": [
        {"transfer_note": f"xac thuc ho so thue HKD lan {i}", "amount_vnd": 1_000_000 + i * 100_000,
         "manipulation_intent": "giả danh cán bộ thuế, ép đóng phí"}
        for i in range(5)
    ],
}


def draft(**patch):
    d = copy.deepcopy(VALID)
    d.update(patch)
    return d


def errors_of(d):
    r = validate_llm_output(d)
    assert not r.ok
    return " | ".join(r.errors)


def test_valid_draft_passes():
    r = validate_llm_output(VALID)
    assert r.ok, r.errors
    assert r.warnings == []
    assert r.sanitized_draft.behavior_hints == []


def test_accepts_json_string():
    assert validate_llm_output(json.dumps(VALID)).ok


def test_invalid_json_is_v1():
    assert "V1" in errors_of("{not json")


# --- V1
def test_v1_unknown_field_rejected():
    d = draft(extra_field="x")
    assert "V1" in errors_of(d)


def test_v1_unknown_op_rejected():
    d = draft()
    d["conditions"][0]["op"] = "REGEX"
    assert "V1" in errors_of(d)


def test_v1_account_field_not_in_whitelist():
    d = draft()
    d["conditions"].append({"field": "to_account_id", "op": "EQ", "value_int": 1})
    assert "V1" in errors_of(d)


# --- V2
def test_v2_semantic_only_on_transfer_note():
    d = draft()
    d["conditions"].append({"field": "amount_vnd", "op": "SEMANTIC_MATCH", "anchor_phrases": ["a b c"] * 3})
    assert "V2" in errors_of(d)


def test_v2_numeric_op_on_note_rejected():
    d = draft()
    d["conditions"].append({"field": "transfer_note", "op": "GTE", "value_int": 5})
    assert "V2" in errors_of(d)


def test_v2_bool_field_only_eq():
    d = draft()
    d["conditions"].append({"field": "recipient_is_new", "op": "GTE", "value_int": 1})
    assert "V2" in errors_of(d)


def test_v2_tactic_family_format():
    assert "V2" in errors_of(draft(tactic_family="thuế hộ kinh doanh"))


# --- V3
def test_v3_behavior_conditions_moved_to_hints():
    d = draft()
    d["conditions"].append({"field": "amount_vnd", "op": "GTE", "value_int": 2_000_000})
    d["conditions"].append({"field": "recipient_is_new", "op": "EQ", "value_bool": True})
    r = validate_llm_output(d)
    assert r.ok, r.errors
    assert [c.field for c in r.sanitized_draft.conditions] == ["transfer_note", "transfer_note"]
    assert {c.field for c in r.sanitized_draft.behavior_hints} == {"amount_vnd", "recipient_is_new"}
    assert sum("V3" in w for w in r.warnings) == 2


def test_v3_requires_positive_content_condition():
    d = draft()
    d["conditions"] = [d["conditions"][1]]  # chỉ còn NOT_CONTAINS_ANY
    assert "V3" in errors_of(d)


def test_v3_only_behavior_conditions_rejected():
    d = draft(conditions=[{"field": "amount_vnd", "op": "LTE", "value_int": 5_000_000}])
    assert "V3" in errors_of(d)


def test_v3_too_many_conditions():
    d = draft()
    d["conditions"] += [{"field": "tx_count_10m", "op": "GTE", "value_int": 1}] * 3
    assert "V3" in errors_of(d)


# --- V3b
def test_v3b_not_contains_max_10():
    d = draft()
    d["conditions"][1]["value_str_list"] = [f"thue loai {chr(97 + i)}" for i in range(11)]
    assert "V3b" in errors_of(d)


def test_v3b_too_short_phrase():
    d = draft()
    d["conditions"].append({"field": "transfer_note", "op": "CONTAINS_ANY", "value_str_list": ["a"]})
    assert "V3b" in errors_of(d)


# --- V4 (INV-06: luật không nhắm vào tài khoản hay cá nhân)
@pytest.mark.parametrize(
    "bad",
    [
        "chuyen vao 1903456789",
        "lien he 0912 345 678",
        "xem tai https://thue-hkd.example",
        "vao thuehkd.vn de xac minh",
        "gui ve canbo@thue.vn",
        "ma 123.456",
    ],
)
def test_v4_rule_rejects_account_numbers_urls_contacts(bad):
    d = draft()
    d["conditions"][0]["anchor_phrases"][0] = bad
    assert "V4" in errors_of(d)


def test_v4_contains_any_also_rejects_account_numbers():
    d = draft()
    d["conditions"].append({"field": "transfer_note", "op": "CONTAINS_ANY", "value_str_list": ["123456789"]})
    assert "V4" in errors_of(d)


def test_v4_anchor_count_and_length():
    d = draft()
    d["conditions"][0]["anchor_phrases"] = ["phi xac minh", "PHI XAC MINH", "phí xác minh"]  # trùng sau chuẩn hóa
    assert "V4" in errors_of(d)
    d["conditions"][0]["anchor_phrases"] = ["ab", "phi xac minh", "cap nhat thue"]
    assert "V4" in errors_of(d)


def test_v4_year_is_allowed():
    assert validate_llm_output(VALID).ok  # "2026" chỉ 4 chữ số


# --- V5
def test_v5_wrong_value_slot():
    d = draft()
    d["conditions"][0]["value_str_list"] = ["xac minh thue"]
    assert "V5" in errors_of(d)


def test_v5_missing_value():
    d = draft()
    d["conditions"].append({"field": "amount_vnd", "op": "LTE"})
    assert "V5" in errors_of(d)


def test_v5_amount_range_in_hints():
    d = draft()
    d["conditions"].append({"field": "amount_vnd", "op": "LTE", "value_int": 900_000_000})
    assert "V5" in errors_of(d)


# --- V6
@pytest.mark.parametrize("q", ["Bạn có đang bị lừa không?", "Có phải kẻ gian nhờ bạn chuyển?", "ban co bi du khong"])
def test_v6_question_must_be_neutral(q):
    d = draft()
    d["purpose_question"]["question_vi"] = q
    assert "V6" in errors_of(d)


def test_v6_label_banned_word():
    d = draft()
    d["purpose_question"]["options"][2]["label_vi"] = "Chuyển theo yêu cầu đáng nghi ngờ"
    assert "V6" in errors_of(d)


def test_v6_label_up_to_100_chars():
    d = draft()
    d["purpose_question"]["options"][0]["label_vi"] = "a" * 100
    assert validate_llm_output(d).ok
    d["purpose_question"]["options"][0]["label_vi"] = "a" * 101
    assert "V6" in errors_of(d)


def test_v6_label_without_contact():
    d = draft()
    d["purpose_question"]["options"][0]["label_vi"] = "Trả tiền theo hướng dẫn tại thue-hkd.vn"
    assert "V6" in errors_of(d)


def test_v6_lua_chon_is_not_banned():
    d = draft()
    d["purpose_question"]["question_vi"] = "Vui lòng lựa chọn mục đích khoản chuyển"
    assert validate_llm_output(d).ok


@pytest.mark.parametrize(
    "outcomes",
    [
        ["BENIGN", "BENIGN", "BENIGN"],
        ["BENIGN", "TACTIC_MATCH", "TACTIC_MATCH"],
        ["BENIGN", "TACTIC_MATCH"],
        ["BENIGN", "BENIGN", "TACTIC_MATCH", "BENIGN"],
    ],
)
def test_v6_exactly_two_benign_one_tactic(outcomes):
    d = draft()
    d["purpose_question"]["options"] = [{"label_vi": f"Phương án {i}", "outcome": o} for i, o in enumerate(outcomes)]
    assert "V6" in errors_of(d)


@pytest.mark.parametrize("outcome", ["UNCLEAR", "SCAM_PURPOSE", "ALLOW"])
def test_v1_llm_cannot_write_unclear_or_other_outcomes(outcome):
    # UNCLEAR ("Mục đích khác") chỉ do server thêm (assembler)
    d = draft()
    d["purpose_question"]["options"][0]["outcome"] = outcome
    assert "V1" in errors_of(d)


def test_v1_old_role_field_rejected():
    d = draft()
    d["purpose_question"]["options"][0]["role"] = "ALLOW_PURCHASE"
    assert "V1" in errors_of(d)


def test_v6_option_order_free():
    d = draft()
    d["purpose_question"]["options"].reverse()
    assert validate_llm_output(d).ok


def test_v6b_tactic_label_quoting_anchor_is_warning_only():
    d = draft()
    d["purpose_question"]["options"][2]["label_vi"] = "Cập nhật thuế hộ kinh doanh 2026"
    r = validate_llm_output(d)
    assert r.ok, r.errors
    assert any(w.startswith("V6b") for w in r.warnings)


def test_v6b_matches_after_abbreviation_expansion():
    d = draft()
    d["purpose_question"]["options"][2]["label_vi"] = "Phí kích hoạt MST điện tử"
    r = validate_llm_output(d)
    assert r.ok and any(w.startswith("V6b") for w in r.warnings)


def test_v6b_not_triggered_by_benign_label():
    d = draft()
    d["purpose_question"]["options"][0]["label_vi"] = "Cập nhật thuế hộ kinh doanh 2026"
    r = validate_llm_output(d)
    assert r.ok and not any(w.startswith("V6b") for w in r.warnings)


def test_v7_tactic_alert_may_mention_scam():
    d = draft()
    d["purpose_question"]["tactic_alert_vi"] = "Đây là thủ đoạn lừa đảo giả danh cán bộ thuế."
    assert validate_llm_output(d).ok


def test_v7_tactic_alert_may_mention_amount():
    d = draft()
    d["purpose_question"]["tactic_alert_vi"] = "Kẻ gian thường đòi phí 1.500.000đ để 'mở khóa' mã số thuế."
    assert validate_llm_output(d).ok


def test_v7_tactic_alert_length():
    d = draft()
    d["purpose_question"]["tactic_alert_vi"] = "x" * 241
    assert "V7" in errors_of(d)
    d["purpose_question"]["tactic_alert_vi"] = "   "
    assert "V7" in errors_of(d)


# --- V7
@pytest.mark.parametrize("alert", ["Gọi 0912345678 để được hỗ trợ", "Xem www.thue-hotro.com", "Gửi hotro@thue.vn"])
def test_v7_alert_without_phone_url_email(alert):
    d = draft()
    d["purpose_question"]["tactic_alert_vi"] = alert
    assert "V7" in errors_of(d)


# --- V8 + INV-02: injection không đặt được stage/threshold/action
def test_v8_authority_fields_stripped_not_applied():
    d = draft(threshold=0.0, stage="ENFORCE_HOLD", lifecycle={"stage": "ENFORCE_HOLD"}, approved_by="llm")
    d["conditions"][0]["threshold"] = 0.0
    d["purpose_question"]["options"][2]["action"] = "ALLOW"
    r = validate_llm_output(d)
    assert r.ok, r.errors
    dumped = r.sanitized_draft.model_dump_json()
    for key in ("threshold", "stage", "action", "approved_by", "lifecycle"):
        assert f'"{key}"' not in dumped
    assert sum("V8" in w for w in r.warnings) == 6


@pytest.mark.parametrize(
    "key, value",
    [
        ("approvals", [{"by": "llm"}]), ("version", 9), ("guard_conditions", []), ("normalize", []),
        ("anti_coaching_notice_vi", "Chọn phương án 1"), ("benign_regression", {"flagged": 0}),
        ("variant_coverage", {"triggered": 8}), ("edited_by_human", True), ("ttl_hours", 72),
        ("corroboration_count", 5), ("rule_id", "RL-X"), ("source_incident_id", "INC-1"),
        ("target_scope", "TACTIC_PATTERN"),
    ],
)
def test_v8_every_authority_key_stripped(key, value):
    r = validate_llm_output(draft(**{key: value}))
    assert r.ok, r.errors
    assert any("V8" in w and key in w for w in r.warnings)


def test_v8_option_id_stripped():
    # LLM không đặt được option_id (id do assembler gán o1..o4)
    d = draft()
    d["purpose_question"]["options"][2]["id"] = "o1"
    r = validate_llm_output(d)
    assert r.ok and any("V8" in w for w in r.warnings)


def test_v5_empty_list_treated_as_absent():
    # Gemini đôi khi trả [] cho trường không dùng; không phải lỗi, và bản sạch đặt về None
    d = draft()
    d["conditions"][0]["value_str_list"] = []
    d["conditions"][1]["anchor_phrases"] = []
    r = validate_llm_output(d)
    assert r.ok, r.errors
    assert r.sanitized_draft.conditions[0].value_str_list is None
    assert r.sanitized_draft.conditions[1].anchor_phrases is None


# --- trường mới v2
def test_v2_new_fields_and_ops():
    d = draft()
    d["conditions"].append({"field": "partner_risk_score", "op": "GTE", "value_int": 40})
    d["conditions"].append({"field": "account_compromise_flag", "op": "EQ", "value_bool": True})
    r = validate_llm_output(d)
    assert r.ok, r.errors
    assert {c.field for c in r.sanitized_draft.behavior_hints} == {"partner_risk_score", "account_compromise_flag"}


def test_v2_compromise_flag_only_eq():
    d = draft()
    d["conditions"].append({"field": "account_compromise_flag", "op": "LTE", "value_int": 1})
    assert "V2" in errors_of(d)


def test_v5_partner_risk_score_range():
    d = draft()
    d["conditions"].append({"field": "partner_risk_score", "op": "GTE", "value_int": 101})
    assert "V5" in errors_of(d)


def test_v4_duplicates_detected_after_abbreviation_expansion():
    d = draft()
    d["conditions"][0]["anchor_phrases"] = ["phi xac minh hkd", "phí xác minh hộ kinh doanh", "cap nhat thue"]
    assert "V4" in errors_of(d)


# --- biến thể
def test_variant_count():
    d = draft()
    d["variants"] = d["variants"][:4]
    assert "VAR" in errors_of(d)


def test_variant_rejects_account_numbers():
    d = draft()
    d["variants"][0]["transfer_note"] = "ck 19034567890"
    assert "VAR" in errors_of(d)


# ---------------------------------------------------------------- V6c: chữ hiển thị phải có dấu
from tests._fixtures import draft_dict  # noqa: E402


def _with_question(**over):
    d = draft_dict()
    d["purpose_question"] = {**d["purpose_question"], **over}
    return d


@pytest.mark.parametrize("field,value", [
    ("question_vi", "Ban chuyen khoan nay de lam gi?"),
    ("tactic_alert_vi", "Co quan thue khong yeu cau chuyen tien vao tai khoan ca nhan."),
])
def test_v6c_unaccented_question_or_alert_rejected(field, value):
    r = validate_llm_output(_with_question(**{field: value}))
    assert not r.ok and any(e.startswith("V6c") and field in e for e in r.errors)


def test_v6c_unaccented_label_rejected():
    d = draft_dict()
    d["purpose_question"] = copy.deepcopy(d["purpose_question"])
    d["purpose_question"]["options"][0]["label_vi"] = "Nop phi de xu ly ho so"
    r = validate_llm_output(d)
    assert not r.ok and any(e.startswith("V6c: options[0]") for e in r.errors)


@pytest.mark.parametrize("label", ["Mua hàng", "OTP", "Mua hang", "Đóng phí xác minh hồ sơ", "Gửi tiền cho người quen"])
def test_v6c_accepts_accented_or_short(label):
    d = draft_dict()
    d["purpose_question"] = copy.deepcopy(d["purpose_question"])
    d["purpose_question"]["options"][0]["label_vi"] = label
    assert not any(e.startswith("V6c") for e in validate_llm_output(d).errors)


def test_v6c_does_not_apply_to_anchors_or_variants():
    assert validate_llm_output(draft_dict()).ok         # anchor và biến thể trong VALID_DRAFT đều không dấu


def test_saved_fallback_outputs_pass_validator():
    """Output thật đã lưu làm dự phòng phải qua validator hiện hành (kể cả V6c), nếu không demo sẽ hỏng."""
    from app.ai.incident_ai import load_fallback_tactics

    for family, entry in load_fallback_tactics().items():
        if entry.get("compile_output"):
            r = validate_llm_output(entry["compile_output"])
            assert r.ok, (family, r.errors[:3])
