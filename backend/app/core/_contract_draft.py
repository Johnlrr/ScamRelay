"""TẠM THỜI — bản sao SPEC §6.3 để bao viết và test validator trước Contract Drop.

Khi `backend/app/schemas/rule.py` của linh lên main: đổi import trong validator.py sang
`app.schemas.rule` và xóa file này. Không import file này ở nơi nào khác.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FieldName = Literal[
    "transfer_note", "amount_vnd", "recipient_is_new",
    "recipient_account_age_days", "tx_count_10m", "is_verified_biller",
]
OpName = Literal["EQ", "LTE", "GTE", "SEMANTIC_MATCH", "CONTAINS_ANY", "NOT_CONTAINS_ANY"]
Role = Literal["ALLOW_PURCHASE", "ALLOW_KNOWN_PERSON", "SCAM_PURPOSE", "OTHER"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(_Strict):
    field: FieldName
    op: OpName
    value_int: int | None = None
    value_bool: bool | None = None
    value_str_list: list[str] | None = None
    anchor_phrases: list[str] | None = None


class PurposeOption(_Strict):
    role: Role
    label_vi: str


class PurposeQuestion(_Strict):
    question_vi: str
    options: list[PurposeOption]
    scam_alert_vi: str


class StructuredVariant(_Strict):
    transfer_note: str
    amount_vnd: int
    manipulation_intent: str


class RelayRuleDraft(_Strict):
    tactic_family: str
    match_mode: Literal["ALL"] = "ALL"
    conditions: list[Condition]
    behavior_hints: list[Condition] = []
    purpose_question: PurposeQuestion
    variants: list[StructuredVariant]


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = []
    warnings: list[str] = []          # đề xuất thêm vào hợp đồng (trường tùy chọn)
    sanitized_draft: RelayRuleDraft | None = None
