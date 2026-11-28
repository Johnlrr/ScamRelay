"""Test race (SPEC §7.3, §14.3): claim challenge nguyên tử và không tiêu một khoản hai lần.

Chạy trên SQLite ở máy; trên CI chạy thêm với Postgres (`TEST_DATABASE_URL`, service postgres:16).
Gọi thẳng tầng core bằng nhiều thread, mỗi thread một Session riêng, cùng xuất phát nhờ Barrier.
"""

from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

from app import config, db
from app.ai import llm_client
from app.ai.llm_client import LLMRateLimited
from app.core import gateway as gw
from app.models import Transaction, Wallet
from app.routers.errors import ApiError
from app.schemas.gateway import SubmitChallengeRequest, TransferRequest
from tests._fixtures import FakeLLM
from tests.test_api_flow import HKD_ANALYSIS, HUNG_TX, build_live_rule, login

WS = "WS-judge_01"
BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def client(request, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "JUDGE_ACCOUNTS", "judge_01:pw1")
    if request.param == "postgres":
        eng = db.make_engine(os.environ["TEST_DATABASE_URL"])
        SQLModel.metadata.drop_all(eng)
    else:
        eng = db.make_engine(f"sqlite:///{tmp_path / 'race.db'}")
    db.set_engine(eng)
    gw.clear_anchor_cache()
    llm_client.set_llm(FakeLLM(HKD_ANALYSIS, LLMRateLimited("429")))
    from app.main import app

    with TestClient(app) as c:
        yield c
    llm_client.set_llm(None)
    gw.clear_anchor_cache()
    if request.param == "postgres":
        SQLModel.metadata.drop_all(eng)
    eng.dispose()


def run_parallel(fn, n: int) -> list:
    """Chạy fn(i) ở n thread cùng lúc; trả kết quả hoặc mã lỗi ApiError."""
    barrier = threading.Barrier(n)

    def wrapped(i: int):
        barrier.wait()
        try:
            return fn(i)
        except ApiError as e:
            return e.code

    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(wrapped, range(n)))


def submit(challenge_id: str, option_id: str):
    with Session(db.get_engine(), expire_on_commit=False) as s:
        return gw.submit(s, WS, SubmitChallengeRequest(challenge_id=challenge_id, option_id=option_id)).decision


def evaluate(req: dict):
    with Session(db.get_engine(), expire_on_commit=False) as s:
        return asyncio.run(gw.evaluate(s, WS, TransferRequest(**req)))


def wallet(wallet_id: str) -> Wallet:
    with Session(db.get_engine()) as s:
        return s.get(Wallet, (WS, wallet_id))


def benign_option(c, h, rule_id: str) -> str:
    rule = c.get(f"/v1/fraudops/rules/{rule_id}", headers=h).json()["rule"]
    return next(o["id"] for o in rule["jit_purpose_question"]["options"] if o["outcome"] == "BENIGN")


def test_same_challenge_claimed_once(client):
    """8 lần gửi cùng một challenge cùng lúc: đúng 1 lần được xử lý, tiền trừ đúng 1 lần."""
    h = login(client, "judge_01", "pw1")
    _, rid = build_live_rule(client, h)
    ev = client.post("/v1/gateway/evaluate-transfer", headers=h, json=HUNG_TX).json()
    assert ev["status"] == "CHALLENGE_JIT"
    opt = benign_option(client, h, rid)

    results = run_parallel(lambda _: submit(ev["challenge"]["challenge_id"], opt), 8)

    assert results.count("ALLOW_WITH_WARNING") == 1, results
    assert results.count("CHALLENGE_USED") == 7, results
    assert wallet("W-HUNG").balance_vnd == 8_000_000 - HUNG_TX["amount_vnd"]


def test_two_challenges_cannot_overdraw(client):
    """Hai challenge cùng ví, mỗi khoản đủ tiền nhưng tổng vượt số dư: chỉ 1 khoản được trừ."""
    h = login(client, "judge_01", "pw1")
    _, rid = build_live_rule(client, h)
    big = {**HUNG_TX, "amount_vnd": 4_500_000}     # < 5 triệu: lớp đối tác không giữ
    chs = []
    for _ in range(2):
        ev = client.post("/v1/gateway/evaluate-transfer", headers=h, json=big).json()
        assert ev["status"] == "CHALLENGE_JIT", ev
        chs.append(ev["challenge"]["challenge_id"])
    opt = benign_option(client, h, rid)

    results = run_parallel(lambda i: submit(chs[i], opt), 2)

    assert sorted(results) == ["ALLOW_WITH_WARNING", "INSUFFICIENT_FUNDS"], results
    assert wallet("W-HUNG").balance_vnd == 3_500_000
    # khoản bị từ chối vẫn chờ xác nhận, challenge chưa bị dùng (rollback toàn bộ)
    with Session(db.get_engine()) as s:
        pending = [t for t in s.query(Transaction).filter_by(workspace_id=WS, status="PENDING_CHALLENGE")]
    assert len(pending) == 1


def test_parallel_allows_do_not_double_spend(client):
    """4 lần chuyển 2 triệu cho người quen từ ví 6 triệu: 3 lần qua, 1 lần thiếu tiền, số dư về 0."""
    h = login(client, "judge_01", "pw1")
    assert wallet("W-LAN").balance_vnd == 6_000_000
    req = {"wallet_id": "W-LAN", "to_account_id": "ACC-TUAN", "amount_vnd": 2_000_000,
           "transfer_note": "gui tien an trua"}

    results = run_parallel(lambda _: getattr(evaluate(req), "decision", None) or "?", 4)

    allowed = [r for r in results if r in ("ALLOW", "ALLOW_WITH_WARNING")]
    assert len(allowed) == 3 and results.count("INSUFFICIENT_FUNDS") == 1, results
    assert wallet("W-LAN").balance_vnd == 0
    assert client.get("/v1/wallets", headers=h).status_code == 200
