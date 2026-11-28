"""Luồng 3 — Chặn đúng, Sandbox Payment Gateway (SPEC §7.3)."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core import gateway as gw
from app.db import get_session
from app.routers.deps import Principal, session_principal
from app.schemas.gateway import EvaluateResponse, SubmitChallengeRequest, SubmitChallengeResponse, TransferRequest

router = APIRouter(prefix="/v1/gateway", tags=["Chặn đúng"])


@router.post("/evaluate-transfer", response_model=EvaluateResponse, summary="Chấm giao dịch: baseline và ScamRelay",
             description="Mọi tín hiệu do server tự suy ra. Trả `FINAL` kèm quyết định, hoặc `CHALLENGE_JIT` kèm "
                         "câu hỏi mục đích (không có nhãn ý nghĩa). `baseline` là quyết định của lớp đối tác.")
async def evaluate_transfer(req: TransferRequest, p: Principal = Depends(session_principal),
                            s: Session = Depends(get_session)) -> EvaluateResponse:
    return await gw.evaluate(s, p.workspace_id, req)


@router.post("/submit-challenge", response_model=SubmitChallengeResponse, summary="Nhận lựa chọn mục đích",
             description="Claim nguyên tử (dùng 1 lần, hạn 5 phút), kiểm tra lại ví, StagePolicy, lấy mức nghiêm "
                         "nhất với mức sàn, ghi sổ và biên lai.")
def submit_challenge(req: SubmitChallengeRequest, p: Principal = Depends(session_principal),
                     s: Session = Depends(get_session)) -> SubmitChallengeResponse:
    return gw.submit(s, p.workspace_id, req)
