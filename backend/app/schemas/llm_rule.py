"""LLM schema cho bản nháp RelayRule (SPEC §6.0, §6.3a).

Phẳng, chỉ dùng kiểu Gemini structured output hỗ trợ: không extra="forbid", không giới hạn độ dài.
Ràng buộc nghiệp vụ nằm ở validator.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

FieldName = Literal[
    "transfer_note", "amount_vnd", "recipient_is_new", "recipient_account_age_days",
    "tx_count_10m", "is_verified_biller", "account_compromise_flag", "partner_risk_score",
]
OpName = Literal["EQ", "LTE", "GTE", "SEMANTIC_MATCH", "CONTAINS_ANY", "NOT_CONTAINS_ANY"]
LLMOutcome = Literal["BENIGN", "TACTIC_MATCH"]   # UNCLEAR do server thêm


class ConditionLLM(BaseModel):
    field: FieldName
    op: OpName
    value_int: int | None = None
    value_bool: bool | None = None
    value_str_list: list[str] | None = None      # CONTAINS_ANY / NOT_CONTAINS_ANY
    anchor_phrases: list[str] | None = None      # SEMANTIC_MATCH


class PurposeOptionLLM(BaseModel):
    label_vi: str
    outcome: LLMOutcome


class PurposeQuestionLLM(BaseModel):
    question_vi: str
    options: list[PurposeOptionLLM]               # đúng 3: 2 BENIGN + 1 TACTIC_MATCH
    tactic_alert_vi: str


class StructuredVariantLLM(BaseModel):           # chỉ để kiểm thử, KHÔNG phải kịch bản lừa
    transfer_note: str
    amount_vnd: int
    manipulation_intent: str


class RelayRuleDraftLLM(BaseModel):
    tactic_family: str
    conditions: list[ConditionLLM]
    purpose_question: PurposeQuestionLLM
    variants: list[StructuredVariantLLM]
