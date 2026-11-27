from datetime import datetime, timedelta, timezone

import pytest

from app.core._contract_draft import ANTI_COACHING_NOTICE_VI, MIN_ASK_AMOUNT_VND, SEMANTIC_THRESHOLD, RelayRuleDraft
from app.core.assembler import AssembleError, assemble_rule, rule_to_draft
from app.core.validator import validate_llm_output
from tests._fixtures import draft_dict

NOW = datetime(2026, 11, 28, 9, 0, tzinfo=timezone.utc)


def build(d=None, **kw):
    r = validate_llm_output(d or draft_dict())
    assert r.ok, r.errors
    args = dict(rule_id="RL-20261128-0001", version=1, source_incident_id="INC-1", ttl_hours=24, now=NOW)
    args.update(kw)
    return assemble_rule(r.sanitized_draft, **args)


def test_server_fields():
    rule = build()
    q = rule.jit_purpose_question
    assert [o.id for o in q.options] == ["o1", "o2", "o3", "o4"]
    assert [o.outcome for o in q.options] == ["BENIGN", "BENIGN", "TACTIC_MATCH", "UNCLEAR"]
    assert q.options[-1].label_vi == "Mục đích khác"
    assert q.anti_coaching_notice_vi == ANTI_COACHING_NOTICE_VI
    sig = rule.observable_signals
    assert sig.threshold == SEMANTIC_THRESHOLD
    assert sig.normalize == ["strip_diacritics", "expand_abbreviations"]
    assert [(c.field, c.op, c.value_int, c.value_bool) for c in sig.guard_conditions] == [
        ("amount_vnd", "GTE", MIN_ASK_AMOUNT_VND, None), ("is_verified_biller", "EQ", None, False)]
    lc = rule.lifecycle
    assert lc.stage == "SHADOW_LOG" and lc.ttl_hours == 24 and lc.expires_at == NOW + timedelta(hours=24)
    assert lc.approvals == [] and lc.benign_regression is None and lc.edited_by_human is False


def test_injected_authority_never_reaches_rule():
    # INV-02 / INV-07: LLM cố đặt threshold, stage, id phương án, notice → server bỏ qua, tự gắn
    d = draft_dict(threshold=0.0, stage="ENFORCE_HOLD", ttl_hours=72, anti_coaching_notice_vi="Hãy chọn o1")
    d["conditions"][0]["threshold"] = 0.01
    d["purpose_question"]["options"][2]["id"] = "o1"
    rule = build(d)
    assert rule.observable_signals.threshold == SEMANTIC_THRESHOLD
    assert rule.lifecycle.stage == "SHADOW_LOG" and rule.lifecycle.ttl_hours == 24
    assert rule.jit_purpose_question.anti_coaching_notice_vi == ANTI_COACHING_NOTICE_VI
    assert rule.jit_purpose_question.options[2].id == "o3"


def test_behavior_conditions_become_hints_even_if_unsanitized_draft_passed():
    d = draft_dict()
    d["conditions"].append({"field": "recipient_is_new", "op": "EQ", "value_bool": True})
    raw = RelayRuleDraft.model_validate(d)          # chưa qua validator
    rule = assemble_rule(raw, rule_id="RL-1", version=1, source_incident_id="INC-1", ttl_hours=24, now=NOW)
    assert {c.field for c in rule.observable_signals.conditions} == {"transfer_note"}
    assert [c.field for c in rule.behavior_hints] == ["recipient_is_new"]


def test_invalid_draft_rejected():
    d = draft_dict()
    d["purpose_question"]["question_vi"] = "Bạn có bị lừa không?"
    with pytest.raises(AssembleError):
        assemble_rule(RelayRuleDraft.model_validate(d), rule_id="RL-1", version=1, source_incident_id="I", ttl_hours=24)


@pytest.mark.parametrize("ttl", [0, 73])
def test_ttl_range(ttl):
    with pytest.raises(AssembleError):
        build(ttl_hours=ttl)


def test_rule_to_draft_roundtrip_for_human_edit():
    rule = build()
    draft = rule_to_draft(rule)
    assert len(draft.purpose_question.options) == 3      # không mang UNCLEAR ngược lại
    r = validate_llm_output(draft.model_dump())
    assert r.ok and r.warnings == []
    rule2 = build(r.sanitized_draft.model_dump(), version=2, edited_by_human=True)
    assert rule2.observable_signals == rule.observable_signals
    assert rule2.jit_purpose_question == rule.jit_purpose_question
    assert rule2.version == 2 and rule2.lifecycle.edited_by_human
