"""Rate limit endpoint gọi LLM (SPEC §10): 10 lần/phút/phiên, 200 lần/ngày/IP; 429 đúng định dạng lỗi."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from limits import parse

from app import config, db, ratelimit
from app.ai import llm_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)          # không có LLM → classifier từ khóa, không gọi mạng
    monkeypatch.setattr(config, "JUDGE_ACCOUNTS", "judge_01:pw1,judge_02:pw2")
    db.set_engine(db.make_engine(f"sqlite:///{tmp_path / 't.db'}"))
    llm_client.set_llm(None)
    from app.main import app

    with TestClient(app) as c:
        yield c


def login(c, user, pw):
    return {"Authorization": "Bearer " + c.post("/v1/auth/login", json={"username": user, "password": pw}).json()["access_token"]}


def analyze(c, h=None):
    return c.post("/v1/incidents/analyze", headers=h or {}, json={"text": "Cán bộ thuế bảo đóng phí xác minh hộ kinh doanh"})


def test_session_limit_10_per_minute(client):
    h1, h2 = login(client, "judge_01", "pw1"), login(client, "judge_02", "pw2")
    for _ in range(10):
        assert analyze(client, h1).status_code == 200
    r = analyze(client, h1)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED" and "thử lại sau" in r.json()["error"]["message_vi"]
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert analyze(client, h2).status_code == 200                   # phiên khác không bị ảnh hưởng
    # compile dùng chung hạn mức phiên (cũng gọi LLM)
    assert client.post("/v1/fraudops/rules/compile", headers=h1, json={"incident_id": "x"}).status_code == 429


def test_ip_limit_per_day(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "IP_LIMIT", parse("3/day"))
    h1, h2 = login(client, "judge_01", "pw1"), login(client, "judge_02", "pw2")
    assert [analyze(client, h).status_code for h in (h1, h2, h1)] == [200, 200, 200]
    r = analyze(client, h2)                                         # phiên mới nhưng cùng IP
    assert r.status_code == 429 and "hôm nay" in r.json()["error"]["message_vi"]


def test_other_endpoints_not_limited(client):
    h = login(client, "judge_01", "pw1")
    for _ in range(10):
        analyze(client, h)
    assert client.get("/v1/wallets", headers=h).status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.post("/v1/auth/login", json={"username": "judge_01", "password": "pw1"}).status_code == 200


def test_bad_token_counts_by_ip_and_route_still_401(client):
    r = analyze(client, {"Authorization": "Bearer hong"})
    assert r.status_code == 401


def test_counter_resets_on_startup(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(config, "JUDGE_ACCOUNTS", "judge_01:pw1")
    db.set_engine(db.make_engine(f"sqlite:///{tmp_path / 't.db'}"))
    llm_client.set_llm(None)
    from app.main import app

    for _ in range(2):                                              # 2 lần khởi động, mỗi lần đủ 10 lượt
        with TestClient(app) as c:
            h = login(c, "judge_01", "pw1")
            assert all(analyze(c, h).status_code == 200 for _ in range(10))
