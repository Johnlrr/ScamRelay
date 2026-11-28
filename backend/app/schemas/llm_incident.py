"""LLM schema cho trích xuất sự cố (SPEC §6.0, §6.1). Phẳng, không extra="forbid"."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

TacticFamily = Literal[
    "FAKE_HKD_TAX_VERIFICATION", "RECOVERY_FEE_SCAM", "FAKE_SUPPORT_REMOTE_APP",
    "IMPERSONATE_AUTHORITY", "JOB_TASK_SCAM", "OTHER_NEW",
]
Provenance = Literal["OBSERVED_IN_EVIDENCE", "USER_REPORTED", "INFERRED", "UNKNOWN"]
YesNoUnknown = Literal["YES", "NO", "UNKNOWN"]


class FactLLM(BaseModel):
    text: str
    provenance: Provenance


class IncidentAnalysisLLM(BaseModel):
    tactic_family: TacticFamily
    tactic_slug: str | None = None
    tactic_summary_vi: str
    money_lost_vnd: int | None = None
    money_requested_vnd: int | None = None
    otp_or_password_disclosed: YesNoUnknown
    remote_app_installed: YesNoUnknown
    facts: list[FactLLM]
    manipulation_cues: list[str]
