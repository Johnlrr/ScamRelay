"""Tiền xử lý tất định trước khi gửi LLM (SPEC §7.1) và chuẩn hóa cho SEMANTIC_MATCH (SPEC §8).

Thứ tự che PII cố định: tiền (giữ nguyên) → SĐT → CCCD → OTP → STK.
Mỗi bước chỉ chạy trên phần văn bản chưa bị bước trước gắn nhãn: phần đã xử lý được thay
bằng token không chứa chữ số nên các regex sau không thể khớp lại vào đó.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------- chuẩn hóa đầu vào

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f​-‏ -‮⁠-⁯﻿]")


def clean_input(text: str) -> str:
    """Unicode NFC + bỏ ký tự điều khiển/vô hình (giữ \\n, \\t)."""
    return _CONTROL_CHARS.sub("", unicodedata.normalize("NFC", text))


def strip_diacritics(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


_NON_ALNUM = re.compile(r"[^0-9a-z\s]")
_SPACES = re.compile(r"\s+")


def norm(text: str) -> str:
    """Chế độ A: lowercase, bỏ dấu, đ→d, bỏ ký tự đặc biệt, gộp khoảng trắng."""
    text = strip_diacritics(clean_input(text).lower())
    text = _NON_ALNUM.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def norm_light(text: str) -> str:
    """Chế độ B (phía nội dung chuyển khoản): chỉ lowercase + gộp khoảng trắng, giữ dấu."""
    return _SPACES.sub(" ", clean_input(text).lower()).strip()


# ---------------------------------------------------------------- che PII

_LETTER_AHEAD = r"(?![^\W\d_])"  # không bị theo sau bởi chữ cái (cho phép số: "1tr8")
_LETTER_BEHIND = r"(?<![^\W\d_])"

_NUM = r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_UNIT = r"(?:vnđ|vnd|đồng|dong|triệu|trieu|tr|đ|d|k)"
_MONEY_SUFFIX = re.compile(rf"(?<![\d.,]){_NUM}\s?{_UNIT}{_LETTER_AHEAD}", re.IGNORECASE)
_MONEY_PREFIX = re.compile(
    rf"{_LETTER_BEHIND}(?:chuyển|chuyen|nạp|nap|phí|phi)\s*[:\-]?\s*({_NUM})(?![\d.,]*\d)",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<![\d+])(?:\+84[\s.]?|0)\d(?:[\s.]?\d){8}(?!\d)")
_CCCD = re.compile(r"(?<!\d)\d{12}(?!\d)")
_OTP_DIGITS = re.compile(r"(?<!\d)\d{4,8}(?!\d)")
_OTP_KEYWORD = re.compile(r"otp|mã|ma\s+xac\s+thuc", re.IGNORECASE)
_OTP_FLAG_KEYWORD = re.compile(r"otp|m[aã]\s+x[aá]c\s+th[uự]c", re.IGNORECASE)
_STK_LONG = re.compile(r"(?<!\d)\d{9,19}(?!\d)")
_STK_SHORT = re.compile(
    rf"(?:stk|số\s*tài\s*khoản|so\s*tai\s*khoan|{_LETTER_BEHIND}tk)\s*(?:là|la)?\s*[:.]?\s*(\d{{6,8}})(?!\d)",
    re.IGNORECASE,
)
OTP_WINDOW = 30

LABEL_PHONE = "[SĐT]"
LABEL_CCCD = "[CCCD]"
LABEL_OTP = "[OTP]"
LABEL_STK = "[STK]"


def _looks_like_money(num: str) -> bool:
    # Số tiền không bắt đầu bằng 0 (trừ "0" hoặc "0,5"): loại SĐT/CCCD đứng sau "chuyển".
    return not (len(num) > 1 and num[0] == "0" and num[1].isdigit())


@dataclass
class MaskResult:
    text: str
    otp_mentioned: bool
    counts: dict[str, int] = field(default_factory=dict)


class _Masker:
    """Giữ danh sách đoạn đã xử lý; thay bằng token chỉ gồm chữ để regex số không chạm lại."""

    def __init__(self, text: str):
        self.text = text
        self.slots: list[str] = []

    def _token(self, value: str) -> str:
        idx = len(self.slots)
        self.slots.append(value)
        letters = ""
        while True:
            letters = chr(ord("a") + idx % 26) + letters
            idx //= 26
            if idx == 0:
                break
        return f"\x00{letters}\x00"

    def sub(self, pattern: re.Pattern, replace, group: int = 0) -> int:
        count = 0

        def _repl(m: re.Match) -> str:
            nonlocal count
            out = replace(m, group)
            if out is None:
                return m.group(0)
            count += 1
            return out

        self.text = pattern.sub(_repl, self.text)
        return count

    def protect(self, m: re.Match, group: int) -> str | None:
        num = m.group(group) if group else re.match(_NUM, m.group(0)).group(0)
        if not _looks_like_money(num):
            return None
        if group:
            start, end = m.span(group)
            base = m.start(0)
            whole = m.group(0)
            return whole[: start - base] + self._token(num) + whole[end - base :]
        return self._token(m.group(0))

    def label(self, value: str):
        def _repl(m: re.Match, group: int) -> str:
            if group:
                start, end = m.span(group)
                base = m.start(0)
                whole = m.group(0)
                return whole[: start - base] + self._token(value) + whole[end - base :]
            return self._token(value)

        return _repl

    def restore(self) -> str:
        return re.sub(r"\x00([a-z]+)\x00", lambda m: self.slots[self._index(m.group(1))], self.text)

    @staticmethod
    def _index(letters: str) -> int:
        idx = 0
        for ch in letters:
            idx = idx * 26 + (ord(ch) - ord("a"))
        return idx


def _mask_otp(masker: _Masker) -> int:
    text = masker.text
    keywords = [m.span() for m in _OTP_KEYWORD.finditer(text)]
    if not keywords:
        return 0
    spans = []
    for m in _OTP_DIGITS.finditer(text):
        s, e = m.span()
        if any(ks - OTP_WINDOW <= e and s <= ke + OTP_WINDOW for ks, ke in keywords):
            spans.append((s, e))
    for s, e in reversed(spans):
        text = text[:s] + masker._token(LABEL_OTP) + text[e:]
    masker.text = text
    return len(spans)


def mask_pii(text: str) -> MaskResult:
    """Che PII theo đúng thứ tự SPEC §7.1. Đầu vào nên đã qua `clean_input`."""
    masker = _Masker(clean_input(text))
    masker.sub(_MONEY_SUFFIX, masker.protect)
    masker.sub(_MONEY_PREFIX, masker.protect, group=1)
    counts = {
        "phone": masker.sub(_PHONE, masker.label(LABEL_PHONE)),
        "cccd": masker.sub(_CCCD, masker.label(LABEL_CCCD)),
        "otp": _mask_otp(masker),
    }
    counts["stk"] = masker.sub(_STK_LONG, masker.label(LABEL_STK))
    counts["stk"] += masker.sub(_STK_SHORT, masker.label(LABEL_STK), group=1)
    result = masker.restore()
    otp_mentioned = counts["otp"] > 0 or bool(_OTP_FLAG_KEYWORD.search(result))
    return MaskResult(text=result, otp_mentioned=otp_mentioned, counts=counts)
