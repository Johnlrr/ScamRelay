"""Phụ trợ: đăng nhập, ví sandbox, demo (reset, tua nhanh), healthz (SPEC §11)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session, select

from app import config
from app.core import containment, ledger
from app.db import get_engine, get_session
from app.models import Account, Transaction, Wallet, Workspace, utcnow
from app.routers.deps import Principal, check_password, ensure_workspace, issue_token, reset_workspace, session_principal
from app.routers.errors import ApiError
from app.schemas.auth import FastForwardResponse, HealthResponse, LoginRequest, LoginResponse, ResetResponse
from app.schemas.gateway import AccountView, TransactionView, WalletsResponse, WalletView

router = APIRouter(tags=["Phụ trợ"])


@router.post("/v1/auth/login", response_model=LoginResponse, summary="Đăng nhập tài khoản giám khảo")
def login(req: LoginRequest, s: Session = Depends(get_session)) -> LoginResponse:
    if not check_password(req.username, req.password):
        raise ApiError(401, "INVALID_CREDENTIALS", "Sai tên đăng nhập hoặc mật khẩu.")
    ws = ensure_workspace(s, req.username, seed=True)
    token, exp = issue_token(req.username)
    return LoginResponse(access_token=token, username=req.username, workspace_id=ws.id, expires_at=exp)


@router.get("/v1/wallets", response_model=WalletsResponse, summary="Ví sandbox của workspace",
            description="Kèm `protective_hold_notice` khi có kích hoạt hộ hoặc khoanh vùng đang bật.")
def list_wallets(p: Principal = Depends(session_principal), s: Session = Depends(get_session)) -> WalletsResponse:
    ledger.release_holds(s, p.workspace_id)
    ledger.expire_challenges(s, p.workspace_id)
    s.commit()
    wallets = s.exec(select(Wallet).where(Wallet.workspace_id == p.workspace_id).order_by(Wallet.id)).all()
    accounts = s.exec(select(Account).where(Account.workspace_id == p.workspace_id).order_by(Account.id)).all()
    return WalletsResponse(
        wallets=[WalletView(id=w.id, label=w.label, owner_name=w.owner_name, balance_vnd=w.balance_vnd,
                            compromise_locked=w.compromise_locked,
                            protective_hold_notice=containment.protective_hold_notice(
                                containment.active_policy(s, p.workspace_id, w.id)))
                 for w in wallets],
        accounts=[AccountView(id=a.id, display_name=a.display_name, age_days=a.age_days,
                              is_verified_biller=a.is_verified_biller) for a in accounts],
    )


@router.get("/v1/wallets/{wallet_id}/transactions", response_model=list[TransactionView], summary="Lịch sử giao dịch")
def list_transactions(wallet_id: str, p: Principal = Depends(session_principal),
                      s: Session = Depends(get_session)) -> list[TransactionView]:
    if s.get(Wallet, (p.workspace_id, wallet_id)) is None:
        raise ApiError(404, "WALLET_NOT_FOUND", "Không tìm thấy ví.")
    rows = s.exec(select(Transaction).where(Transaction.workspace_id == p.workspace_id,
                                            Transaction.wallet_id == wallet_id)
                  .order_by(Transaction.created_at.desc()).limit(50)).all()
    return [TransactionView(**r.model_dump(include=set(TransactionView.model_fields))) for r in rows]


@router.post("/v1/demo/reset", response_model=ResetResponse, summary="Xóa dữ liệu workspace và seed lại")
def demo_reset(p: Principal = Depends(session_principal), s: Session = Depends(get_session)) -> ResetResponse:
    from app.core.gateway import clear_anchor_cache

    ws = s.get(Workspace, p.workspace_id)
    reset_workspace(s, ws)
    clear_anchor_cache()
    return ResetResponse(workspace_id=ws.id, reset_at=utcnow())


@router.post("/v1/demo/fast-forward-holds", response_model=FastForwardResponse,
             summary="Giải phóng ngay các giao dịch HOLD_15M (chỉ HOLD_15M)")
def fast_forward(p: Principal = Depends(session_principal), s: Session = Depends(get_session)) -> FastForwardResponse:
    n = ledger.release_holds(s, p.workspace_id, force=True)
    s.commit()
    return FastForwardResponse(released=n)


@router.get("/healthz", response_model=HealthResponse, summary="Kiểm tra sức khỏe")
def healthz() -> HealthResponse:
    db_ok = True
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return HealthResponse(status="ok" if db_ok else "degraded", db=db_ok,
                          gemini_configured=bool(os.environ.get("GEMINI_API_KEY")),
                          registry_unverified=containment.registry_unverified(), llm_model=config.LLM_MODEL)
