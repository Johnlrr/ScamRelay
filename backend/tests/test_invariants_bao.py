"""Test mang đúng tên trong SPEC §10 cho phần bất biến thuộc module của bao.

Phần gateway/DB của các bất biến này (router, challenge, ledger) do linh viết test riêng.
"""

import asyncio

import numpy as np

from app.ai import llm_client
from app.ai.incident_ai import analyze_incident
from app.ai.llm_client import LLMError
from app.config import SEMANTIC_THRESHOLD
from app.schemas.rule import AnchorSet
from app.core.assembler import assemble_rule
from app.core.layer1 import layer1_match, semantic_phrases
from app.core.preprocess import mask_pii
from app.core.validator import validate_llm_output
from tests._fixtures import FakeLLM, draft_dict, make_tx


def _rule(d):
    r = validate_llm_output(d)
    assert r.ok, r.errors
    return assemble_rule(r.sanitized_draft, rule_id="RL-1", version=1, source_incident_id="I", ttl_hours=24)


def test_injection_cannot_set_stage_threshold_action():
    # INV-02
    d = draft_dict(stage="ENFORCE_HOLD", threshold=0.0, action="ALLOW", guard_conditions=[], lifecycle={"stage": "ASK_ONLY"})
    d["purpose_question"]["options"][2]["outcome"] = "TACTIC_MATCH"
    d["purpose_question"]["options"][2]["action"] = "ALLOW"
    rule = _rule(d)
    assert rule.lifecycle.stage == "SHADOW_LOG"
    assert rule.observable_signals.threshold == SEMANTIC_THRESHOLD
    assert len(rule.observable_signals.guard_conditions) == 2
    assert '"action"' not in rule.model_dump_json()


def test_llm_timeout_returns_safe_defaults():
    # INV-03: LLM lỗi → fallback, không bao giờ kết luận "an toàn"
    llm_client.set_llm(FakeLLM(LLMError("timeout"), LLMError("timeout")))
    try:
        r = asyncio.run(analyze_incident("Có người gọi bảo chuyển tiền gấp", None, False, []))
    finally:
        llm_client.set_llm(None)
    assert r.degraded
    assert r.analysis.otp_or_password_disclosed != "NO" and r.analysis.remote_app_installed != "NO"


def test_pii_masking():
    # INV-05 (phần che PII trước khi gọi LLM)
    m = mask_pii("Gọi 0912 345 678, CCCD 012345678901, STK 1903456789012, mã OTP 482913, chuyển 1.500.000đ")
    for leaked in ("0912", "012345678901", "1903456789012", "482913"):
        assert leaked not in m.text
    assert "1.500.000đ" in m.text and m.otp_mentioned


def test_rule_rejects_account_numbers():
    # INV-06
    for bad in ["chuyen vao 1903456789", "lien he 0912345678", "xem thue-hkd.vn"]:
        d = draft_dict()
        d["conditions"][0]["anchor_phrases"][0] = bad
        assert not validate_llm_output(d).ok


def test_action_from_stage_policy_only():
    # INV-07 (phía rule): luật không mang hành động nào; phương án chỉ có outcome do server gắn id
    rule = _rule(draft_dict())
    for o in rule.jit_purpose_question.options:
        assert set(o.model_dump()) == {"id", "label_vi", "outcome"}


def test_verified_biller_never_challenged():
    # INV-15 (phía layer1): biller không bao giờ khớp, kể cả khi nội dung trùng anchor
    rule = _rule(draft_dict())
    phrases = semantic_phrases(rule)
    anchors = AnchorSet(phrases=phrases, vectors=np.eye(len(phrases), 8, dtype=np.float32))
    vec = np.eye(1, 8, dtype=np.float32)[0]
    tx = make_tx(phrases[0], to_account_id="ACC-TAX-GOV", is_verified_biller=True)
    assert layer1_match(rule, tx, anchors, note_vec=vec) is None
    assert layer1_match(rule, make_tx(phrases[0]), anchors, note_vec=vec) is not None
