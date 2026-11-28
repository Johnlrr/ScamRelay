"""Luồng 2 — Tiếp sức, FraudOps Workspace (SPEC §7.2)."""

from fastapi import APIRouter

from app.routers import _stub
from app.schemas.rule import CompileRequest, RuleView

router = APIRouter(prefix="/v1/fraudops", tags=["Tiếp sức"])


@router.post("/rules/compile", response_model=RuleView, summary="AI biên dịch RelayRule từ sự cố đã đồng ý")
async def compile_rule(req: CompileRequest) -> RuleView:
    return _stub.rule_view()   # TODO(linh): cài đặt thật
