"""Cấu hình đọc từ biến môi trường (SPEC §14.5). Giá trị mặc định dùng được cho dev local.

Hằng số ở cấp module để code của bao import trực tiếp (`from app.config import SEMANTIC_THRESHOLD`).
Secrets (`GEMINI_API_KEY`, `JWT_SECRET`, `JUDGE_ACCOUNTS`) không bao giờ được in ra log.
"""

from __future__ import annotations

import os


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


# ---- AI (SPEC §0)
LLM_MODEL = _env_str("LLM_MODEL", "gemini-3.5-flash-lite")
EMBED_MODEL = _env_str("EMBED_MODEL", "gemini-embedding-001")
EMBED_DIM = _env_int("EMBED_DIM", 768)

# ---- Ngưỡng (SPEC §8.3; bao hiệu chỉnh trên dev 28/11, bench/results/calibration_20261128T0036Z.md)
SEMANTIC_THRESHOLD = _env_float("SEMANTIC_THRESHOLD", 0.90)
TRIGRAM_THRESHOLD = _env_float("TRIGRAM_THRESHOLD", 0.60)

# ---- Chính sách (SPEC §6.3, §7.3, §9)
MIN_ASK_AMOUNT_VND = _env_int("MIN_ASK_AMOUNT_VND", 200_000)
PARTNER_WARN_SCORE = _env_int("PARTNER_WARN_SCORE", 50)
HOLD_MINUTES = _env_int("HOLD_MINUTES", 15)
STOP_COOLDOWN_MINUTES = _env_int("STOP_COOLDOWN_MINUTES", 30)
CHALLENGE_TTL_MINUTES = _env_int("CHALLENGE_TTL_MINUTES", 5)
DEFAULT_RULE_TTL_HOURS = _env_int("DEFAULT_RULE_TTL_HOURS", 24)
PUBLIC_SESSION_TTL_HOURS = _env_int("PUBLIC_SESSION_TTL_HOURS", 24)
OVERRIDE_REASON_MIN_LEN = 15

ANTI_COACHING_NOTICE_VI = (
    "Nếu có người dặn bạn chọn một đáp án cụ thể ở màn hình này, đó là dấu hiệu lừa đảo. "
    "Hãy dừng lại và gọi kênh chính thức."
)

# ---- Hạ tầng
DATABASE_URL = _env_str("DATABASE_URL", "sqlite:///./dev.db")
JWT_SECRET = _env_str("JWT_SECRET", "dev-only-secret-change-me")
JWT_TTL_HOURS = _env_int("JWT_TTL_HOURS", 12)
# "judge_01:pass1,judge_02:pass2,..." — Secret Manager khi deploy; dev có giá trị mặc định.
JUDGE_ACCOUNTS = _env_str("JUDGE_ACCOUNTS", "judge_01:dev,bench_runner:dev,smoke:dev")
STATIC_DIR = _env_str("STATIC_DIR", "static")   # bản build frontend (Dockerfile copy vào đây)
