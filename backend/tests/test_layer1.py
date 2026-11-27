import numpy as np
import pytest

from app.core._contract_draft import AnchorSet
from app.core.assembler import assemble_rule
from app.core.layer1 import layer1_explain, layer1_match, semantic_phrases
from app.core.validator import validate_llm_output
from tests._fixtures import draft_dict, make_tx


def rule_from(d=None, threshold=0.8):
    r = validate_llm_output(d or draft_dict())
    assert r.ok, r.errors
    return assemble_rule(r.sanitized_draft, rule_id="RL-1", version=1, source_incident_id="I",
                         ttl_hours=24, threshold=threshold)


def unit(*xs):
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def anchor_set(rule):
    phrases = semantic_phrases(rule)
    vecs = np.eye(len(phrases), 8, dtype=np.float32)    # anchor i ↔ trục i
    return AnchorSet(phrases=phrases, vectors=vecs)


NEAR_ANCHOR_1 = unit(0, 0.95, 0, 0, 0, 0, 0, 0.3)      # cos ≈ 0.954 với anchor thứ 2
FAR = unit(0.3, 0.3, 0.3, 0, 0, 0, 0, 1)                # cos ≈ 0.27


def test_semantic_phrases_are_norm_match_unique():
    rule = rule_from()
    assert semantic_phrases(rule) == ["dong phi xac minh ho kinh doanh", "cap nhat thue ho kinh doanh 2026",
                                      "phi kich hoat ma so thue dien tu"]


def test_match_returns_cosine_and_top_anchor():
    rule = rule_from()
    d = layer1_explain(rule, make_tx(), anchor_set(rule), note_vec=NEAR_ANCHOR_1)
    assert d.matched and d.score == pytest.approx(0.954, abs=1e-3)
    assert d.top_anchor == "cap nhat thue ho kinh doanh 2026" and not d.degraded


def test_below_threshold_no_match_but_reports_score():
    rule = rule_from()
    d = layer1_explain(rule, make_tx(), anchor_set(rule), note_vec=FAR)
    assert not d.matched and d.semantic_score == pytest.approx(0.27, abs=0.01)
    assert layer1_match(rule, make_tx(), anchor_set(rule), note_vec=FAR) is None


def test_threshold_comes_from_rule():
    rule = rule_from(threshold=0.97)
    assert layer1_match(rule, make_tx(), anchor_set(rule), note_vec=NEAR_ANCHOR_1) is None


def test_verified_biller_never_matches():
    # INV-15
    rule = rule_from()
    tx = make_tx(is_verified_biller=True, to_account_id="ACC-TAX-GOV")
    assert layer1_match(rule, tx, anchor_set(rule), note_vec=NEAR_ANCHOR_1) is None


def test_guard_min_amount():
    rule = rule_from()
    a = anchor_set(rule)
    assert layer1_match(rule, make_tx(amount=199_999), a, note_vec=NEAR_ANCHOR_1) is None
    assert layer1_match(rule, make_tx(amount=200_000), a, note_vec=NEAR_ANCHOR_1) is not None


def test_not_contains_any_excludes_rent():
    rule = rule_from()
    tx = make_tx("tra tien thuê nhà thang 12")
    d = layer1_explain(rule, tx, anchor_set(rule), note_vec=NEAR_ANCHOR_1)
    assert not d.matched and "transfer_note NOT_CONTAINS_ANY" in d.failed


def test_not_contains_is_whole_word():
    rule = rule_from()
    tx = make_tx("thue nhanh ho kinh doanh")     # "thue nha" không phải cụm nguyên vẹn trong "thue nhanh"
    assert layer1_match(rule, tx, anchor_set(rule), note_vec=NEAR_ANCHOR_1) is not None


def test_short_note_never_semantic_match():
    rule = rule_from()
    assert layer1_match(rule, make_tx("ck"), anchor_set(rule), note_vec=NEAR_ANCHOR_1) is not None  # "chuyen khoan" ≥4
    assert layer1_match(rule, make_tx("abc"), anchor_set(rule), note_vec=NEAR_ANCHOR_1) is None
    assert layer1_match(rule, make_tx(""), anchor_set(rule), note_vec=NEAR_ANCHOR_1) is None


def test_trigram_fallback_when_no_note_vector():
    rule = rule_from()
    a = anchor_set(rule)
    d = layer1_explain(rule, make_tx("dong phi xac minh HKD"), a, note_vec=None, trigram_threshold=0.5)
    assert d.matched and d.degraded and d.top_anchor == "dong phi xac minh ho kinh doanh"
    d = layer1_explain(rule, make_tx("tien an trua"), a, note_vec=None, trigram_threshold=0.5)
    assert not d.matched and d.degraded


def test_trigram_fallback_when_anchor_vectors_missing():
    rule = rule_from()
    a = AnchorSet(phrases=semantic_phrases(rule), vectors=None, degraded=True)
    d = layer1_explain(rule, make_tx("dong phi xac minh HKD"), a, note_vec=NEAR_ANCHOR_1, trigram_threshold=0.5)
    assert d.matched and d.degraded


def test_anchor_set_must_match_rule_version():
    rule = rule_from()
    a = AnchorSet(phrases=["mot cau khac"], vectors=np.eye(1, 8, dtype=np.float32))
    with pytest.raises(ValueError):
        layer1_match(rule, make_tx(), a, note_vec=NEAR_ANCHOR_1)


def test_contains_any_rule_scores_one():
    d = draft_dict()
    d["conditions"] = [{"field": "transfer_note", "op": "CONTAINS_ANY", "value_str_list": ["xac minh hkd", "kich hoat mst"]}]
    rule = rule_from(d)
    a = AnchorSet(phrases=[], vectors=None)
    assert layer1_match(rule, make_tx("Phi XÁC MINH HKD"), a) == 1.0
    assert layer1_match(rule, make_tx("tien hang"), a) is None
