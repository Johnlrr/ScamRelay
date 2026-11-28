"""Luồng 3 — Gateway, ví sandbox (SPEC §6.4, §6.5, §7.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Strict

Decision = Literal["ALLOW", "ALLOW_WITH_WARNING", "HOLD_15M", "STOP_AND_EXPLAIN", "HOLD_UNTIL_VERIFIED", "BLOCK"]
PartnerDecision = Literal["ALLOW", "WARN", "BLOCK"]
TxStatus = Literal["COMMITTED", "HELD", "STOPPED", "BLOCKED", "PENDING_CHALLENGE", "EXPIRED"]


class DerivedTx(BaseModel):
    """Tín hiệu giao dịch do server tự suy ra từ sổ và seed; client không gửi được."""

    wallet_id: str
    to_account_id: str
    amount_vnd: int
    transfer_note: str
    note_norm: str                               # norm_match(transfer_note)
    recipient_is_new: bool
    recipient_account_age_days: int
    tx_count_10m: int                            # chỉ đếm COMMITTED/HELD
    is_verified_biller: bool
    is_known_contact: bool
    account_compromise_flag: bool                # = wallet.compromise_locked
    partner_risk_score: int | None = None        # điền sau khi chạy baseline


class BaselineResult(BaseModel):
    decision: PartnerDecision
    risk_score: int                              # 0–100
    reasons: list[str]


# ---------------------------------------------------------------- API /v1/gateway


class TransferRequest(Strict):
    wallet_id: str
    to_account_id: str
    amount_vnd: int = Field(gt=0, le=50_000_000)
    transfer_note: str = Field("", max_length=120)


class ChallengeOptionOut(BaseModel):
    id: str
    label_vi: str                                # KHÔNG có outcome (INV-12)


class ChallengeOut(BaseModel):
    challenge_id: str
    question_vi: str
    options: list[ChallengeOptionOut]
    anti_coaching_notice_vi: str
    expires_at: datetime


class BaselineView(BaseModel):                   # /wallet hiển thị song song
    decision: PartnerDecision
    risk_score: int
    as_final: Decision                           # ALLOW→ALLOW, WARN→HOLD_15M, BLOCK→BLOCK


class OfficialChannel(BaseModel):
    """Kênh chính thức lấy từ action_registry.json (chỉ mục đã kiểm chứng mới có contact)."""

    id: str
    title_vi: str
    contact_type: Literal["tel", "url"] | None = None
    contact_value: str | None = None
    source_url: str | None = None


class EvaluateResponse(BaseModel):
    tx_id: str
    status: Literal["FINAL", "CHALLENGE_JIT"]
    decision: Decision | None                    # None khi CHALLENGE_JIT
    challenge: ChallengeOut | None
    baseline: BaselineView
    reason_codes: list[str]
    matched_rule_id: str | None
    receipt_id: str | None
    message_vi: str | None
    official_channels: list[OfficialChannel]
    retry_after: datetime | None
    rule_active_for_seconds: int | None          # dải "Luật mới có hiệu lực X phút trước"


class SubmitChallengeRequest(Strict):
    challenge_id: str
    option_id: str


class SubmitChallengeResponse(BaseModel):
    tx_id: str
    decision: Decision
    reason_codes: list[str]
    receipt_id: str
    tactic_alert_vi: str | None                  # chỉ khi bị dừng/giữ do chọn TACTIC_MATCH
    message_vi: str | None
    official_channels: list[OfficialChannel]
    retry_after: datetime | None


# ---------------------------------------------------------------- ví sandbox


class WalletView(BaseModel):
    """Không bao giờ trả cho luồng kích hoạt hộ (INV-11); chỉ /wallet của chủ ví."""

    id: str
    label: str
    owner_name: str
    balance_vnd: int
    compromise_locked: bool
    protective_hold_notice: str | None           # đọc từ containment_policy đang bật


class AccountView(BaseModel):
    id: str
    display_name: str
    age_days: int
    is_verified_biller: bool


class WalletsResponse(BaseModel):
    wallets: list[WalletView]
    accounts: list[AccountView]                  # người nhận seed cho form chuyển tiền


class TransactionView(BaseModel):
    id: str
    wallet_id: str
    to_account_id: str
    amount_vnd: int
    transfer_note: str
    status: TxStatus
    decision: Decision | None
    reason_codes: list[str]
    partner_decision: PartnerDecision | None
    partner_risk_score: int | None
    matched_rule_id: str | None
    receipt_id: str | None
    created_at: datetime
    release_at: datetime | None
    retry_after: datetime | None
