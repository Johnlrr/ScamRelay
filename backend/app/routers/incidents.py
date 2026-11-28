"""Luồng 1 — Khoanh vùng (SPEC §7.1)."""

from fastapi import APIRouter

from app.routers import _stub
from app.schemas.incident import AnalyzeRequest, AnalyzeResponse

router = APIRouter(prefix="/v1/incidents", tags=["Khoanh vùng"])


@router.post("/analyze", response_model=AnalyzeResponse, summary="Phân tích đoạn chat, khoanh vùng ví")
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    return _stub.analyze_response()   # TODO(linh): cài đặt thật
