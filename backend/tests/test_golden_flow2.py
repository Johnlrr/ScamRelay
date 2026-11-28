"""Golden test Luồng 2 (phần của bao, SPEC §15 bước 1–3) trên DỮ LIỆU THẬT, không gọi mạng.

- Output compile: bản LLM thật đã lưu trong fallback_tactics.json (LLM giả lập lỗi → CACHED_FALLBACK).
- Embedding: vector thật trong embeddings_seed.npz; embedder giả luôn lỗi, nên mọi vector phải có sẵn.
Test đỏ nghĩa là kịch bản demo (ABOUT §7) đã đổi: xem lại prompt/ngưỡng/dữ liệu trước khi demo.
"""

import asyncio

import pytest

from app.ai import llm_client
from app.ai.incident_ai import analyze_incident
from app.ai.llm_client import LLMRateLimited
from app.ai.rule_ai import compile_rule
from app.core._contract_draft import SEMANTIC_THRESHOLD
from app.core.assembler import assemble_rule, rule_to_draft
from app.core.baseline import baseline_score
from app.core.layer1 import layer1_match, semantic_phrases
from app.core.regression import run_regression
from app.core.semantic import InMemoryEmbeddingCache, SemanticMatcher, preload_seed
from app.core.validator import validate_llm_output
from tests._fixtures import HKD_ANALYSIS, FakeEmbedder, FakeLLM, make_tx

HUNG_NOTE = "xac thuc ho so cap nhat thue HKD"


def run(c):
    return asyncio.run(c)


@pytest.fixture
def matcher():
    cache = InMemoryEmbeddingCache()
    preload_seed(cache)
    return SemanticMatcher(FakeEmbedder(fail=True), cache)      # dim/model mặc định như seed


@pytest.fixture(autouse=True)
def llm_down():
    llm_client.set_llm(FakeLLM(HKD_ANALYSIS, LLMRateLimited("429")))   # analyze OK, compile gặp 429
    yield
    llm_client.set_llm(None)


def test_demo_flow2_real_output(matcher):
    assert SEMANTIC_THRESHOLD == pytest.approx(0.90)

    # 1) Khoanh vùng → 2) biên dịch (LLM 429 → output thật đã lưu)
    a = run(analyze_incident("Cán bộ thuế bảo đóng phí xác minh hộ kinh doanh", None, False, []))
    assert not a.degraded and a.analysis.tactic_family == "FAKE_HKD_TAX_VERIFICATION"
    c = run(compile_rule(a.analysis))
    assert c.source == "CACHED_FALLBACK" and c.degraded

    # 3) validator + assembler
    v = validate_llm_output(c.raw)
    assert v.ok, v.errors
    rule = assemble_rule(v.sanitized_draft, rule_id="RL-DEMO", version=1, source_incident_id="INC-LAN", ttl_hours=24)
    anchors = run(matcher.prepare_anchors(semantic_phrases(rule)))
    assert anchors.vectors is not None, "anchor chưa có trong seed — chạy bench/build_seed.py"

    # 4) regression bắt câu mẫu quá rộng → Approve bị khóa
    r1 = run(run_regression(rule, anchors, matcher=matcher))
    assert not r1.degraded and r1.benign_checked >= 220
    assert r1.benign_flagged >= 1
    broad = max(r1.flags_by_anchor, key=r1.flags_by_anchor.get)

    # 5) chuyên viên xóa anchor gây khớp nhầm → bản nháp qua lại validator → version 2
    draft = rule_to_draft(rule)
    draft.conditions[0].anchor_phrases = [x for x in draft.conditions[0].anchor_phrases if x != broad]
    v2 = validate_llm_output(draft.model_dump())
    assert v2.ok, v2.errors
    rule2 = assemble_rule(v2.sanitized_draft, rule_id="RL-DEMO", version=2, source_incident_id="INC-LAN",
                          ttl_hours=24, edited_by_human=True)
    anchors2 = run(matcher.prepare_anchors(semantic_phrases(rule2)))
    r2 = run(run_regression(rule2, anchors2, matcher=matcher))
    assert r2.rule_version == 2 and r2.benign_flagged == 0
    assert r2.variants_triggered == r2.variants_checked

    # 6) chú Hùng: lớp đối tác cho qua, luật tiếp sức khớp → sẽ bị hỏi
    hung = make_tx(HUNG_NOTE, amount=1_200_000)
    assert baseline_score(hung).decision == "ALLOW"
    vec = run(matcher.note_vector(hung.note_norm))
    score = layer1_match(rule2, hung, anchors2, note_vec=vec)
    assert score is not None and score >= SEMANTIC_THRESHOLD

    # giao dịch sạch và biller không bị hỏi
    shop = make_tx("tien hang phu tung", amount=450_000, to_account_id="ACC-SHOP")
    assert layer1_match(rule2, shop, anchors2, note_vec=run(matcher.note_vector(shop.note_norm))) is None
    tax = make_tx("nop thue mon bai 2026", amount=1_000_000, to_account_id="ACC-TAX-GOV", is_verified_biller=True)
    assert layer1_match(rule2, tax, anchors2, note_vec=None) is None
