"""Assembler (SPEC §7.2c): bản nháp đã qua validator → `RelayRule` hoàn chỉnh. Tất định.

Mọi trường QUYỀN do server gắn ở đây, không bao giờ lấy từ LLM (D4, INV-02, INV-07):
`rule_id`, `version`, id phương án `o1..o4`, phương án UNCLEAR "Mục đích khác", điều kiện sàn,
`threshold`, `normalize`, dòng chống dặn trước, `stage`, `ttl_hours`, `expires_at`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core._contract_draft import (
    ANTI_COACHING_NOTICE_VI,
    DEFAULT_RULE_TTL_HOURS,
    MIN_ASK_AMOUNT_VND,
    SEMANTIC_THRESHOLD,
    Approval,
    Condition,
    JitQuestion,
    Lifecycle,
    ObservableSignals,
    PurposeOption,
    PurposeQuestion,
    RelayRule,
    RelayRuleDraft,
    RuleOption,
    Stage,
)
from app.core.validator import validate_rule

UNCLEAR_LABEL_VI = "Mục đích khác"
NORMALIZE_STEPS = ["strip_diacritics", "expand_abbreviations"]
TTL_RANGE = (1, 72)


class AssembleError(ValueError):
    """Bản nháp không hợp lệ — không được dựng thành luật."""


def guard_conditions(min_ask_amount_vnd: int = MIN_ASK_AMOUNT_VND) -> list[Condition]:
    """Điều kiện sàn (S4), giống nhau cho mọi luật."""
    return [
        Condition(field="amount_vnd", op="GTE", value_int=min_ask_amount_vnd),
        Condition(field="is_verified_biller", op="EQ", value_bool=False),
    ]


def assemble_rule(
    draft: RelayRuleDraft,
    *,
    rule_id: str,
    version: int,
    source_incident_id: str,
    ttl_hours: int = DEFAULT_RULE_TTL_HOURS,
    stage: Stage = "SHADOW_LOG",
    corroboration_count: int = 1,
    approvals: list[Approval] | None = None,
    edited_by_human: bool = False,
    now: datetime | None = None,
    threshold: float = SEMANTIC_THRESHOLD,
    min_ask_amount_vnd: int = MIN_ASK_AMOUNT_VND,
) -> RelayRule:
    if not (TTL_RANGE[0] <= ttl_hours <= TTL_RANGE[1]):
        raise AssembleError(f"ttl_hours phải trong [{TTL_RANGE[0]}; {TTL_RANGE[1]}]")
    if version < 1:
        raise AssembleError("version phải ≥ 1")

    # Chạy lại V2–V7 (rẻ, tất định): assembler không bao giờ dựng luật từ bản nháp chưa hợp lệ,
    # và luôn dùng bản đã tách điều kiện hành vi sang behavior_hints (V3).
    result = validate_rule(draft)
    if not result.ok or result.sanitized_draft is None:
        raise AssembleError("; ".join(result.errors) or "bản nháp không hợp lệ")
    d = result.sanitized_draft

    options = [RuleOption(id=f"o{i}", label_vi=o.label_vi.strip(), outcome=o.outcome)
               for i, o in enumerate(d.purpose_question.options, start=1)]
    options.append(RuleOption(id=f"o{len(options) + 1}", label_vi=UNCLEAR_LABEL_VI, outcome="UNCLEAR"))

    now = now or datetime.now(timezone.utc)
    return RelayRule(
        rule_id=rule_id,
        version=version,
        source_incident_id=source_incident_id,
        tactic_family=d.tactic_family,
        lifecycle=Lifecycle(
            stage=stage,
            ttl_hours=ttl_hours,
            expires_at=now + timedelta(hours=ttl_hours),
            corroboration_count=corroboration_count,
            approvals=list(approvals or []),
            benign_regression=None,
            variant_coverage=None,
            edited_by_human=edited_by_human,
        ),
        observable_signals=ObservableSignals(
            conditions=[c.model_copy(deep=True) for c in d.conditions],
            guard_conditions=guard_conditions(min_ask_amount_vnd),
            normalize=list(NORMALIZE_STEPS),
            threshold=threshold,
        ),
        behavior_hints=[c.model_copy(deep=True) for c in d.behavior_hints],
        jit_purpose_question=JitQuestion(
            question_vi=d.purpose_question.question_vi.strip(),
            options=options,
            tactic_alert_vi=d.purpose_question.tactic_alert_vi.strip(),
            anti_coaching_notice_vi=ANTI_COACHING_NOTICE_VI,
        ),
        variants=[v.model_copy(deep=True) for v in d.variants],
    )


def rule_to_draft(rule: RelayRule) -> RelayRuleDraft:
    """Ngược lại: lấy phần chuyên viên được sửa (PUT draft, SPEC §7.2d). Bỏ UNCLEAR và mọi trường quyền."""
    q = rule.jit_purpose_question
    return RelayRuleDraft(
        tactic_family=rule.tactic_family,
        conditions=[c.model_copy(deep=True) for c in rule.observable_signals.conditions],
        behavior_hints=[c.model_copy(deep=True) for c in rule.behavior_hints],
        purpose_question=PurposeQuestion(
            question_vi=q.question_vi,
            options=[PurposeOption(label_vi=o.label_vi, outcome=o.outcome) for o in q.options if o.outcome != "UNCLEAR"],
            tactic_alert_vi=q.tactic_alert_vi,
        ),
        variants=[v.model_copy(deep=True) for v in rule.variants],
    )
