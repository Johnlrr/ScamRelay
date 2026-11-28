"""Chặn mọi lời gọi tới Gemini trong pytest (AGENTS.md §4: LLM và embedding luôn được mock).

Chỉ chặn tên miền googleapis.com, để Postgres trong CI (test race) vẫn kết nối được.
Test nào lỡ dùng client thật (kể cả với key giả) sẽ đỏ ngay thay vì âm thầm gọi mạng.
"""

from __future__ import annotations

import socket

import pytest

_real_getaddrinfo = socket.getaddrinfo


def _guarded_getaddrinfo(host, *args, **kwargs):
    if isinstance(host, (str, bytes)) and str(host if isinstance(host, str) else host.decode()).endswith("googleapis.com"):
        raise OSError(f"pytest không được gọi Gemini thật ({host}); hãy dùng FakeLLM/FakeEmbedder")
    return _real_getaddrinfo(host, *args, **kwargs)


@pytest.fixture(autouse=True)
def _no_gemini_network(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
    for k in ("GEMINI_API_KEY", "GEMINI_API_KEYS"):
        monkeypatch.delenv(k, raising=False)
