"""ScamRelay — một service: API /v1/*, Swagger /docs, SPA tĩnh / (SPEC §2, D1)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app import config
from app.db import DbEmbeddingCache, init_db
from app.routers import fraudops, gateway, incidents, support
from app.routers.errors import install_error_handlers

log = logging.getLogger("scamrelay")


async def _seed_benign_cache() -> None:
    """Embed phần tập sạch còn thiếu (đa số đã có trong seed tính sẵn). Lỗi thì bỏ qua: regression tự fallback."""
    from app.core.regression import seed_benign_cache

    try:
        ok = await asyncio.wait_for(seed_benign_cache(), timeout=60)
        log.info("benign cache seeded: %s", ok)
    except Exception as e:  # noqa: BLE001
        log.warning("benign cache seed failed: %s", type(e).__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.core.semantic import init_matcher

    init_db()
    init_matcher(cache=DbEmbeddingCache())
    task = asyncio.create_task(_seed_benign_cache())
    yield
    task.cancel()


app = FastAPI(
    lifespan=lifespan,
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
app.include_router(support.router)


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
