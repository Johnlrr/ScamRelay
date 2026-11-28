"""Luồng 3 — Chặn đúng, Sandbox Payment Gateway (SPEC §7.3)."""

from fastapi import APIRouter

from app.routers import _stub
from app.schemas.gateway import EvaluateResponse, SubmitChallengeRequest, SubmitChallengeResponse, TransferRequest

router = APIRouter(prefix="/v1/gateway", tags=["Chặn đúng"])


@router.post("/evaluate-transfer", response_model=EvaluateResponse, summary="Chấm giao dịch: baseline và ScamRelay")
async def evaluate_transfer(req: TransferRequest) -> EvaluateResponse:
    return _stub.evaluate_response()   # TODO(linh): cài đặt thật


@router.post("/submit-challenge", response_model=SubmitChallengeResponse, summary="Nhận lựa chọn mục đích")
async def submit_challenge(req: SubmitChallengeRequest) -> SubmitChallengeResponse:
    return _stub.submit_response()   # TODO(linh): cài đặt thật
