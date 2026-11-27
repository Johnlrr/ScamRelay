"""Tiện ích chung cho script trong bench/: đưa backend vào sys.path, nạp backend/.env, cache embedding file."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BENCH = ROOT / "bench"
CACHE_PATH = BENCH / ".cache" / "embeddings.npz"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_env() -> None:
    """Nạp GEMINI_API_KEY… từ backend/.env (không in giá trị)."""
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")
