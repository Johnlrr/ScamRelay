"""ScamRelay — một service: API /v1/*, Swagger /docs, SPA tĩnh / (SPEC §2, D1)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app import config
from app.routers import fraudops, gateway, incidents
from app.routers.errors import install_error_handlers

app = FastAPI(
    title="ScamRelay Incident-to-Policy API",
    version="0.1.0",
    description=(
        "Biến báo cáo lừa đảo của nạn nhân thành luật phòng vệ có kiểm thử, và chấm giao dịch "
        "cho người tiếp theo. Sandbox: VietWallet (thương hiệu trung tính), dữ liệu tổng hợp."
    ),
)
install_error_handlers(app)
app.include_router(incidents.router)
app.include_router(fraudops.router)
app.include_router(gateway.router)


@app.get("/healthz", tags=["Phụ trợ"])
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok", "llm_model": config.LLM_MODEL})


# ---- SPA tĩnh (bản build frontend). Đường dẫn lạ không thuộc API → index.html để router phía client xử lý.
_STATIC = Path(config.STATIC_DIR)
_API_PREFIXES = ("v1/", "docs", "redoc", "openapi.json", "healthz")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith(_API_PREFIXES):
        return JSONResponse({"error": {"code": "NOT_FOUND", "message_vi": "Không tìm thấy.", "details": []}},
                            status_code=404)
    file = (_STATIC / path).resolve()
    if path and file.is_file() and _STATIC.resolve() in file.parents:
        return FileResponse(file)
    index = _STATIC / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({"service": "ScamRelay API", "docs": "/docs"})
