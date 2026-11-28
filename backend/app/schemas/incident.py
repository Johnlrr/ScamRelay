"""Luồng 1 — Khoanh vùng (SPEC §6.1, §7.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Strict
from app.schemas.llm_incident import Provenance, TacticFamily, YesNoUnknown

Mode = Literal["MANIPULATION", "COMPROMISE", "UNCLEAR"]


class Fact(Strict):
    text: str                                    # ≤ 200 ký tự
    provenance: Provenance


class IncidentAnalysis(Strict):
    tactic_family: TacticFamily
    tactic_slug: str | None = None               # khi OTHER_NEW; ^[A-Z0-9_]{3,40}$
    tactic_summary_vi: str                       # ≤ 300 ký tự
    money_lost_vnd: int | None = None
    money_requested_vnd: int | None = None
    otp_or_password_disclosed: YesNoUnknown
    remote_app_installed: YesNoUnknown
    facts: list[Fact]                            # ≤ 12
    manipulation_cues: list[str]                 # ≤ 8


class AnalyzeResult(BaseModel):                  # kết quả của ai.analyze_incident (SPEC §6.4)
    analysis: IncidentAnalysis
    degraded: bool = False


# ---------------------------------------------------------------- API


class AnalyzeRequest(Strict):
    text: str = Field("", max_length=6000)
    image_base64: str | None = None              # có thể có; ảnh không bao giờ được lưu
    is_proxy: bool = False                       # "Tôi là người thân kích hoạt hộ"
    protect_wallet_id: str | None = None         # yêu cầu tạm giữ bảo vệ (chỉ trong workspace demo)
    consent_handoff: bool = False                # đồng ý chuyển hồ sơ sang FraudOps (§7.1c)
    followup_text: str | None = Field(None, max_length=6000)
    incident_id: str | None = None               # khi bổ sung tình tiết


class ActionCard(BaseModel):
    """Một việc cần làm. Kênh liên hệ CHỈ lấy từ action_registry.json đã kiểm chứng."""

    id: str
    title_vi: str
    detail_vi: str | None = None
    contact_type: Literal["tel", "url"] | None = None   # None khi registry chưa kiểm chứng
    contact_value: str | None = None
    source_url: str | None = None
    verified: bool = False


class ProtectiveHold(BaseModel):
    wallet_id: str
    wallet_label: str
    mode: Mode


class AnalyzeResponse(BaseModel):
    incident_id: str
    mode: Mode
    actions: list[ActionCard]                    # tối đa 3
    analysis: IncidentAnalysis                   # đã che PII; frontend dựng gói hồ sơ
    policy_summary_vi: str
    protective_hold: ProtectiveHold | None = None
    consent_handoff: bool
    degraded: bool


class IncidentSummary(BaseModel):                # hàng đợi /ops (chỉ sự cố đã đồng ý)
    incident_id: str
    submitted_at: datetime
    is_proxy: bool
    mode: Mode
    tactic_family: str
    tactic_summary_vi: str
    money_lost_vnd: int | None
    money_requested_vnd: int | None
    otp_or_password_disclosed: YesNoUnknown
    degraded: bool
    rule_id: str | None = None                   # luật mới nhất biên dịch từ sự cố này


class IncidentDetail(IncidentSummary):
    analysis: IncidentAnalysis
