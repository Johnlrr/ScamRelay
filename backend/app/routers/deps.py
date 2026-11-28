"""Auth, workspace và seed (SPEC §10 "Auth", "Workspace và Reset", D8).

- Giám khảo: JWT (Bearer) từ POST /v1/auth/login; workspace riêng, seed từ seed_workspace.json.
- Người dùng ẩn danh: cookie phiên `sr_session` → workspace tạm `public:<cookie>`, KHÔNG có ví.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import jwt
from fastapi import Depends, Request, Response
from sqlmodel import Session, delete, select

from app import config
from app.db import get_session
from app.models import WORKSPACE_TABLES, Account, Wallet, Workspace, utcnow
from app.routers.errors import ApiError

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "seed_workspace.json"
SESSION_COOKIE = "sr_session"
JWT_ALG = "HS256"


@dataclass(frozen=True)
class Principal:
    workspace_id: str
    username: str | None          # None: phiên ẩn danh
    session_key: str              # để tính corroboration theo phiên

    @property
    def is_judge(self) -> bool:
        return self.username is not None


# ---------------------------------------------------------------- tài khoản


def judge_accounts() -> dict[str, str]:
    out: dict[str, str] = {}
    for part in config.JUDGE_ACCOUNTS.split(","):
        if ":" in part:
            u, p = part.split(":", 1)
            if u.strip():
                out[u.strip()] = p.strip()
    return out


def check_password(username: str, password: str) -> bool:
    expected = judge_accounts().get(username)
    return expected is not None and hmac.compare_digest(expected.encode(), password.encode())


def issue_token(username: str) -> tuple[str, datetime]:
    exp = utcnow() + timedelta(hours=config.JWT_TTL_HOURS)
    token = jwt.encode({"sub": username, "exp": exp}, config.JWT_SECRET, algorithm=JWT_ALG)
    return token, exp


def _username_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        payload = jwt.decode(auth[7:].strip(), config.JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError as e:
        raise ApiError(401, "INVALID_TOKEN", "Phiên đăng nhập đã hết hạn hoặc không hợp lệ. Vui lòng đăng nhập lại.") from e
    username = payload.get("sub")
    if username not in judge_accounts():
        raise ApiError(401, "INVALID_TOKEN", "Tài khoản không còn hiệu lực.")
    return username


# ---------------------------------------------------------------- workspace và seed


def workspace_id_for(owner: str) -> str:
    if owner.startswith("public:"):
        return "WS-PUB-" + hashlib.sha256(owner.encode()).hexdigest()[:12].upper()
    return f"WS-{owner}"


@lru_cache
def load_seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def seed_workspace(s: Session, workspace_id: str) -> None:
    seed = load_seed()
    for w in seed["wallets"]:
        s.add(Wallet(workspace_id=workspace_id, id=w["id"], label=w["label"], owner_name=w["owner_name"],
                     balance_vnd=w["balance_vnd"], known_contacts=list(w["known_contacts"])))
    for a in seed["accounts"]:
        s.add(Account(workspace_id=workspace_id, id=a["id"], display_name=a["display_name"],
                      age_days=a["age_days"], is_verified_biller=a["is_verified_biller"]))


def ensure_workspace(s: Session, owner: str, *, seed: bool) -> Workspace:
    ws_id = workspace_id_for(owner)
    ws = s.get(Workspace, ws_id)
    if ws is None:
        ws = Workspace(id=ws_id, owner=owner)
        if seed:
            seed_workspace(s, ws_id)
            ws.seeded_at = utcnow()
        s.add(ws)
        s.commit()
    return ws


def reset_workspace(s: Session, ws: Workspace) -> None:
    """Xóa toàn bộ dữ liệu của workspace rồi seed lại (nút Reset). Phiên ẩn danh không có ví."""
    for table in WORKSPACE_TABLES:
        s.exec(delete(table).where(table.workspace_id == ws.id))
    if not ws.owner.startswith("public:"):
        seed_workspace(s, ws.id)
        ws.seeded_at = utcnow()
        s.add(ws)
    s.commit()


def purge_expired_public(s: Session) -> int:
    """Phiên công khai tự xóa sau PUBLIC_SESSION_TTL_HOURS (INV-05)."""
    cutoff = utcnow() - timedelta(hours=config.PUBLIC_SESSION_TTL_HOURS)
    old = s.exec(select(Workspace).where(Workspace.owner.startswith("public:"),
                                         Workspace.created_at < cutoff)).all()
    for ws in old:
        for table in WORKSPACE_TABLES:
            s.exec(delete(table).where(table.workspace_id == ws.id))
        s.delete(ws)
    if old:
        s.commit()
    return len(old)


# ---------------------------------------------------------------- dependency


def require_judge(request: Request, s: Session = Depends(get_session)) -> Principal:
    username = _username_from_request(request)
    if username is None:
        raise ApiError(401, "LOGIN_REQUIRED", "Cần đăng nhập bằng tài khoản giám khảo.")
    ws = ensure_workspace(s, username, seed=True)
    return Principal(workspace_id=ws.id, username=username, session_key=f"user:{username}")


def session_principal(request: Request, response: Response, s: Session = Depends(get_session)) -> Principal:
    """JWT nếu có; không thì workspace tạm theo cookie (tạo cookie mới nếu chưa có)."""
    username = _username_from_request(request)
    if username is not None:
        ws = ensure_workspace(s, username, seed=True)
        return Principal(workspace_id=ws.id, username=username, session_key=f"user:{username}")
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie or len(cookie) > 64:
        cookie = secrets.token_urlsafe(24)
        response.set_cookie(SESSION_COOKIE, cookie, max_age=config.PUBLIC_SESSION_TTL_HOURS * 3600,
                            httponly=True, samesite="lax", secure=request.url.scheme == "https")
        purge_expired_public(s)
    ws = ensure_workspace(s, f"public:{cookie}", seed=False)
    return Principal(workspace_id=ws.id, username=None, session_key=f"session:{ws.id}")
