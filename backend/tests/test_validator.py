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
            {"role": "ALLOW_PURCHASE", "label_vi": "Mua hàng / trả dịch vụ"},
            {"role": "ALLOW_KNOWN_PERSON", "label_vi": "Trả tiền người quen"},
            {"role": "SCAM_PURPOSE", "label_vi": "Đóng phí xác minh / cập nhật tài khoản thuế hộ kinh doanh"},
            {"role": "OTHER", "label_vi": "Mục đích khác"},
        ],
        "scam_alert_vi": "Cơ quan thuế không yêu cầu chuyển phí vào tài khoản cá nhân để xác minh hộ kinh doanh.",
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


def test_v6_lua_chon_is_not_banned():
    d = draft()
    d["purpose_question"]["question_vi"] = "Vui lòng lựa chọn mục đích khoản chuyển"
    assert validate_llm_output(d).ok


def test_v6_roles_exactly_once():
    d = draft()
    d["purpose_question"]["options"][3]["role"] = "ALLOW_PURCHASE"
    assert "V6" in errors_of(d)
    d = draft()
    d["purpose_question"]["options"].pop()
    assert "V6" in errors_of(d)


def test_v6_scam_alert_may_mention_scam():
    d = draft()
    d["purpose_question"]["scam_alert_vi"] = "Đây là thủ đoạn lừa đảo giả danh cán bộ thuế."
    assert validate_llm_output(d).ok


# --- V7
def test_v7_alert_without_phone_or_url():
    d = draft()
    d["purpose_question"]["scam_alert_vi"] = "Gọi 0912345678 để được hỗ trợ"
    assert "V7" in errors_of(d)
    d["purpose_question"]["scam_alert_vi"] = "Xem www.thue-hotro.com"
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


# --- biến thể
def test_variant_count():
    d = draft()
    d["variants"] = d["variants"][:4]
    assert "VAR" in errors_of(d)


def test_variant_rejects_account_numbers():
    d = draft()
    d["variants"][0]["transfer_note"] = "ck 19034567890"
    assert "VAR" in errors_of(d)
