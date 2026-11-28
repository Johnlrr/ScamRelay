"""Luồng 1 — Khoanh vùng (SPEC §7.1). Kích hoạt hộ chỉ làm ví an toàn hơn (INV-11):
response không bao giờ có số dư hay lịch sử giao dịch, không có tham số hạ mức.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.ai.interfaces import analyze_incident
from app.core import containment
from app.core.preprocess import mask_pii
from app.db import get_session
from app.models import Incident, Wallet, new_id
from app.routers.deps import Principal, session_principal
from app.routers.errors import ApiError
from app.schemas.incident import AnalyzeRequest, AnalyzeResponse, IncidentAnalysis, ProtectiveHold

router = APIRouter(prefix="/v1/incidents", tags=["Khoanh vùng"])

MAX_IMAGE_B64 = 6_000_000      # ~4MB ảnh gốc


def family_key(a: IncidentAnalysis) -> str:
    return a.tactic_slug if a.tactic_family == "OTHER_NEW" and a.tactic_slug else a.tactic_family


@router.post("/analyze", response_model=AnalyzeResponse, summary="Phân tích đoạn chat, khoanh vùng ví",
             description="Nhận đoạn chat (đã che PII ở server), trả 3 việc cần làm và chính sách khoanh vùng. "
                         "Follow-up: gửi `incident_id` + `followup_text` (chỉ nâng mức, không hạ).")
async def analyze(req: AnalyzeRequest, p: Principal = Depends(session_principal),
                  s: Session = Depends(get_session)) -> AnalyzeResponse:
    if req.image_base64 and len(req.image_base64) > MAX_IMAGE_B64:
        raise ApiError(413, "IMAGE_TOO_LARGE", "Ảnh quá lớn (tối đa 4MB).")

    old: Incident | None = None
    history: list[IncidentAnalysis] = []
    if req.incident_id:
        old = s.get(Incident, req.incident_id)
        if old is None or old.workspace_id != p.workspace_id:
            raise ApiError(404, "INCIDENT_NOT_FOUND", "Không tìm thấy hồ sơ sự cố.")
        history = [IncidentAnalysis.model_validate(old.analysis_json)]
        raw_text = req.followup_text or req.text
    else:
        raw_text = req.text
    if not raw_text.strip() and not req.image_base64:
        raise ApiError(422, "EMPTY_EVIDENCE", "Hãy dán đoạn chat hoặc mô tả sự việc.")

    masked = mask_pii(raw_text)                       # che PII trước khi gọi LLM (INV-05)
    result = await analyze_incident(masked.text, req.image_base64, masked.otp_mentioned, history)
    analysis = result.analysis
    mode = containment.compute_mode(analysis)
    if old is not None:
        mode = containment.raise_mode(old.mode, mode)  # chỉ nâng (INV-10)

    # ví được bảo vệ: lấy từ lần trước hoặc từ yêu cầu mới (chỉ trong workspace có ví)
    wallet_id = (old.protected_wallet_id if old else None) or req.protect_wallet_id
    wallet: Wallet | None = None
    if wallet_id:
        wallet = s.get(Wallet, (p.workspace_id, wallet_id))
        if wallet is None:
            raise ApiError(404, "WALLET_NOT_FOUND",
                           "Tạm giữ bảo vệ chỉ dùng được trong workspace demo (đăng nhập tài khoản giám khảo).")

    if old is None:
        inc = Incident(id=new_id("INC"), workspace_id=p.workspace_id, is_proxy=req.is_proxy,
                       protected_wallet_id=wallet_id,
                       reporter_key=f"wallet:{wallet_id}" if wallet_id else p.session_key,
                       analysis_json=analysis.model_dump(mode="json"), tactic_family=family_key(analysis),
                       mode=mode, degraded=result.degraded, consent_handoff=req.consent_handoff)
    else:
        inc = old
        inc.analysis_json = analysis.model_dump(mode="json")
        inc.tactic_family = family_key(analysis)
        inc.mode = mode
        inc.degraded = inc.degraded or result.degraded
        inc.is_proxy = inc.is_proxy or req.is_proxy
        inc.consent_handoff = inc.consent_handoff or req.consent_handoff   # chỉ bật, không tắt
        if wallet_id and not inc.protected_wallet_id:
            inc.protected_wallet_id = wallet_id
    s.add(inc)

    hold = None
    if wallet is not None:
        pol = containment.apply_containment(s, workspace_id=p.workspace_id, wallet=wallet, incident_id=inc.id,
                                            mode=mode, by_proxy=inc.is_proxy)
        if pol is not None:
            hold = ProtectiveHold(wallet_id=wallet.id, wallet_label=wallet.label, mode=pol.mode)
    s.commit()

    return AnalyzeResponse(
        incident_id=inc.id, mode=mode, actions=containment.actions_for(mode, analysis.tactic_family),
        analysis=analysis, policy_summary_vi=containment.POLICY_SUMMARY_VI[mode], protective_hold=hold,
        consent_handoff=inc.consent_handoff, degraded=result.degraded,
    )
