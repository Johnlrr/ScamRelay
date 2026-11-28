import asyncio
import re


from app.core.assembler import assemble_rule
from app.core.layer1 import semantic_phrases
from app.core.preprocess import norm_match
from app.core.regression import load_benign_corpus, run_regression
from app.core.semantic import SemanticMatcher
from app.core.validator import validate_llm_output
from tests._fixtures import FakeEmbedder, draft_dict


def run(c):
    return asyncio.run(c)


def rule_from(d=None, threshold=0.6, version=1):
    r = validate_llm_output(d or draft_dict())
    assert r.ok, r.errors
    return assemble_rule(r.sanitized_draft, rule_id="RL-1", version=version, source_incident_id="I",
                         ttl_hours=24, threshold=threshold)


CORPUS = [
    {"transfer_note": "dong phi xac minh ho kinh doanh nhe", "amount_vnd": 1_000_000, "is_verified_biller": False},
    {"transfer_note": "phi kich hoat ma so thue dien tu", "amount_vnd": 500_000, "is_verified_biller": True},
    {"transfer_note": "dong phi xac minh ho kinh doanh", "amount_vnd": 150_000, "is_verified_biller": False},
    {"transfer_note": "tra tien thue nha thang 12", "amount_vnd": 4_000_000, "is_verified_biller": False},
    {"transfer_note": "tien an trua", "amount_vnd": 300_000, "is_verified_biller": False},
]


def test_regression_counts_flags_and_attributes_to_anchor():
    rule = rule_from()
    m = SemanticMatcher(FakeEmbedder(), dim=64)
    anchors = run(m.prepare_anchors(semantic_phrases(rule)))
    r = run(run_regression(rule, anchors, matcher=m, corpus=CORPUS))
    # chỉ mẫu đầu bị khớp: biller (INV-15) và số tiền < sàn được miễn; "thuê nhà" bị NOT_CONTAINS_ANY loại
    assert (r.benign_checked, r.benign_flagged) == (5, 1)
    assert r.flagged_examples[0].transfer_note == CORPUS[0]["transfer_note"]
    # mọi anchor tự nó vượt ngưỡng đều được chỉ ra (không chỉ anchor cao nhất)
    assert r.flags_by_anchor == {"dong phi xac minh ho kinh doanh": 1, "cap nhat thue ho kinh doanh 2026": 1}
    assert r.flagged_examples[0].top_anchor in r.flags_by_anchor
    assert r.variants_checked == 5 and r.rule_version == 1 and not r.degraded


def test_removing_all_flagged_anchors_clears_in_one_round():
    """Chuyên viên xóa mọi anchor được tô đậm → chạy lại một lần là hết khớp nhầm (không phải xóa lặp)."""
    from app.core.preprocess import norm_match

    m = SemanticMatcher(FakeEmbedder(), dim=64)
    rule = rule_from()
    r = run(run_regression(rule, run(m.prepare_anchors(semantic_phrases(rule))), matcher=m, corpus=CORPUS))
    d = draft_dict()
    sem = next(c for c in d["conditions"] if c["op"] == "SEMANTIC_MATCH")
    sem["anchor_phrases"] = [a for a in sem["anchor_phrases"] if norm_match(a) not in r.flags_by_anchor]
    sem["anchor_phrases"] += ["phi kich hoat ma so thue dien tu", "le phi chuan hoa tai khoan thue",
                              "tien duy tri ma so thue ca the"]   # giữ ≥ 3 anchor (V4)
    rule2 = rule_from(d)
    r2 = run(run_regression(rule2, run(m.prepare_anchors(semantic_phrases(rule2))), matcher=m, corpus=CORPUS))
    assert r2.benign_flagged == 0


def test_regression_reports_missed_variants():
    d = draft_dict()
    d["variants"][0]["transfer_note"] = "tien an trua"
    rule = rule_from(d)
    m = SemanticMatcher(FakeEmbedder(), dim=64)
    anchors = run(m.prepare_anchors(semantic_phrases(rule)))
    r = run(run_regression(rule, anchors, matcher=m, corpus=CORPUS))
    assert "tien an trua" in r.variants_missed and r.variants_triggered == r.variants_checked - len(r.variants_missed)


def test_regression_degraded_when_embedding_fails():
    rule = rule_from()
    m = SemanticMatcher(FakeEmbedder(fail=True), dim=64)
    anchors = run(m.prepare_anchors(semantic_phrases(rule)))
    r = run(run_regression(rule, anchors, matcher=m, corpus=CORPUS))
    assert r.degraded and r.benign_checked == 5


def test_regression_uses_same_layer1_as_gateway(monkeypatch):
    # INV-14 phụ thuộc vào việc regression và gateway dùng chung một hàm
    import app.core.regression as reg

    calls = []
    real = reg.layer1_explain
    monkeypatch.setattr(reg, "layer1_explain", lambda *a, **k: calls.append(1) or real(*a, **k))
    rule = rule_from()
    m = SemanticMatcher(FakeEmbedder(), dim=64)
    run(run_regression(rule, run(m.prepare_anchors(semantic_phrases(rule))), matcher=m, corpus=CORPUS))
    assert len(calls) == len(CORPUS) + len(rule.variants)
    from app.core import layer1
    assert real is layer1.layer1_explain


# ---------------------------------------------------------------- tập sạch thật
def test_benign_corpus_meets_spec():
    s = load_benign_corpus()
    template = [x for x in s if x["source"] == "template"]
    traps = [x for x in s if x["source"] == "trap"]
    assert len(template) >= 200 and len(traps) >= 20
    normed = [norm_match(x["transfer_note"]) for x in s]
    assert len(set(normed)) == len(normed)
    thue_group = [n for n in normed if re.search(r"\bthue (nha|mat bang|xe|phong|kho|dat)\b|hop dong thue", n)]
    assert len(thue_group) >= 4
    for x in s:
        assert set(x) >= {"transfer_note", "amount_vnd", "is_verified_biller"}
        assert not re.search(r"\d{6,}", x["transfer_note"])            # không có số TK/SĐT
        assert 0 < x["amount_vnd"] <= 50_000_000
