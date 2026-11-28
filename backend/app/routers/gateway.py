"""Luồng 3 — Chặn đúng, Sandbox Payment Gateway (SPEC §7.3)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.core import gateway as gw
from app.core.preprocess import mask_pii
from app.db import get_session
from app.models import RelayRuleRow, RuleEvent, Transaction
from app.routers.deps import Principal, session_principal
from app.routers.errors import ApiError
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


# ---------------------------------------------------------------- "Báo nhầm" (SPEC §11, mục "có thể có")
# Schema đặt ở đây (không phải schemas/**) để không động vào file hợp đồng; vẫn hiện trong /openapi.json.

FEEDBACK_NOTE_MAX = 300


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tx_id: str
    kind: Literal["FALSE_POSITIVE"] = "FALSE_POSITIVE"
    note: str | None = Field(default=None, max_length=FEEDBACK_NOTE_MAX)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tx_id: str
    rule_id: str
    recorded: bool                       # False: giao dịch này đã được báo trước đó (không đếm hai lần)
    message_vi: str


@router.post("/feedback", response_model=FeedbackResponse, summary="Báo nhầm (luật hỏi hoặc chặn nhầm)",
             description="Ghi `rule_event FP_REPORTED` cho luật đã khớp giao dịch; FraudOps thấy trong "
                         "`/rules/{id}/stats`. Không thay đổi quyết định hay giai đoạn luật. Mỗi giao dịch đếm 1 lần.")
def feedback(req: FeedbackRequest, p: Principal = Depends(session_principal),
             s: Session = Depends(get_session)) -> FeedbackResponse:
    tx = s.get(Transaction, req.tx_id)
    if tx is None or tx.workspace_id != p.workspace_id:
        raise ApiError(404, "TX_NOT_FOUND", "Không tìm thấy giao dịch.")
    row = s.get(RelayRuleRow, tx.matched_rule_id) if tx.matched_rule_id else None
    if row is None or row.workspace_id != p.workspace_id:
        raise ApiError(409, "NO_RULE_MATCHED", "Giao dịch này không bị luật tiếp sức nào hỏi hay chặn.")

    reported = s.exec(select(RuleEvent).where(RuleEvent.workspace_id == p.workspace_id,
                                              RuleEvent.rule_id == row.id, RuleEvent.event == "FP_REPORTED")).all()
    if any((e.payload or {}).get("tx_id") == tx.id for e in reported):
        return FeedbackResponse(tx_id=tx.id, rule_id=row.id, recorded=False,
                                message_vi="Giao dịch này đã được báo nhầm trước đó. Cảm ơn bạn.")

    note = mask_pii(req.note).text.strip() if req.note else None     # che PII trước khi lưu (INV-05)
    gw.log_event(s, row, "FP_REPORTED", p.session_key,
                 {"tx_id": tx.id, "rule_version": tx.matched_rule_version, "note": note or None})
    s.commit()
    return FeedbackResponse(tx_id=tx.id, rule_id=row.id, recorded=True,
                            message_vi="Đã ghi nhận. Chuyên viên sẽ xem lại luật này; quyết định giao dịch không đổi.")
