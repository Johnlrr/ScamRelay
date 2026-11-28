"""Khoanh vùng tất định (SPEC §6.1, §7.1). Không gọi AI.

- `mode` tính từ IncidentAnalysis (LLM không trả mode).
- 3 việc cần làm lấy từ ACTION_MAP; chữ và kênh liên hệ lấy từ action_registry.json (quynh kiểm chứng).
  Mục chưa có `source_url` + `verified_at` vẫn hiện thẻ nhưng KHÔNG có số gọi hay link.
- Policy trên ví chỉ nâng: không có → MANIPULATION → COMPROMISE (INV-10).
"""

from __future__ import annotations

import json
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlmodel import Session, select

from app.models import ContainmentPolicy, Wallet, utcnow
from app.schemas.gateway import OfficialChannel
from app.schemas.incident import ActionCard, IncidentAnalysis, Mode

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "action_registry.json"
MODE_RANK = {"UNCLEAR": 0, "MANIPULATION": 1, "COMPROMISE": 2}
VN_TZ = timezone(timedelta(hours=7))

# Chữ mặc định khi registry chưa có mục tương ứng (không bao giờ có số điện thoại hay link ở đây).
DEFAULT_TITLES: dict[str, str] = {
    "STOP_TRANSFER": "Dừng mọi khoản chuyển theo yêu cầu của người lạ",
    "CALL_WALLET_HOTLINE_LOCK": "Gọi tổng đài ví để tạm khóa tài khoản",
    "CALL_BANK_HOTLINE": "Gọi ngân hàng liên kết để khóa thẻ và tài khoản",
    "CHANGE_PASSWORD": "Đổi mật khẩu ví và email, đăng xuất khỏi thiết bị lạ",
    "UNINSTALL_REMOTE_APP": "Gỡ ứng dụng điều khiển từ xa vừa cài theo hướng dẫn của người lạ",
    "VERIFY_TAX_OFFICIAL": "Tự kiểm tra với cơ quan thuế qua kênh chính thức",
    "REPORT_POLICE": "Trình báo công an nơi gần nhất, mang theo bộ hồ sơ",
    "REPORT_SCAM_PORTAL": "Báo cáo lừa đảo lên cổng cảnh báo chính thức",
    "KEEP_EVIDENCE": "Giữ nguyên tin nhắn, ảnh chụp làm bằng chứng",
    "NO_RECOVERY_SERVICE": "Không trả phí cho bất kỳ dịch vụ \"lấy lại tiền\" nào",
}

_DEFAULT = "_DEFAULT"
ACTION_MAP: dict[str, dict[str, list[str]]] = {
    "COMPROMISE": {
        _DEFAULT: ["CALL_WALLET_HOTLINE_LOCK", "CALL_BANK_HOTLINE", "CHANGE_PASSWORD"],
        "FAKE_SUPPORT_REMOTE_APP": ["UNINSTALL_REMOTE_APP", "CALL_WALLET_HOTLINE_LOCK", "CALL_BANK_HOTLINE"],
    },
    "MANIPULATION": {
        _DEFAULT: ["STOP_TRANSFER", "CALL_WALLET_HOTLINE_LOCK", "REPORT_POLICE"],
        "FAKE_HKD_TAX_VERIFICATION": ["STOP_TRANSFER", "VERIFY_TAX_OFFICIAL", "CALL_WALLET_HOTLINE_LOCK"],
        "RECOVERY_FEE_SCAM": ["NO_RECOVERY_SERVICE", "REPORT_POLICE", "CALL_WALLET_HOTLINE_LOCK"],
        "IMPERSONATE_AUTHORITY": ["STOP_TRANSFER", "REPORT_POLICE", "CALL_WALLET_HOTLINE_LOCK"],
    },
    # INV-03: không bao giờ kết luận "an toàn" — vẫn trả 3 việc an toàn mặc định
    "UNCLEAR": {_DEFAULT: ["KEEP_EVIDENCE", "STOP_TRANSFER", "CALL_WALLET_HOTLINE_LOCK"]},
}

# Kênh chính thức hiện khi giao dịch bị dừng/giữ (SPEC §7.3)
STOP_CHANNELS = ["CALL_WALLET_HOTLINE_LOCK", "REPORT_SCAM_PORTAL"]
TACTIC_CHANNELS = {"FAKE_HKD_TAX_VERIFICATION": ["VERIFY_TAX_OFFICIAL"]}

POLICY_SUMMARY_VI: dict[str, str] = {
    "MANIPULATION": "Dấu hiệu bị thao túng: tạm giữ các khoản chuyển tới người lạ; hóa đơn quen thuộc và người thân vẫn chuyển được.",
    "COMPROMISE": "Nghi lộ OTP hoặc mật khẩu: khóa toàn bộ giao dịch đi, kể cả hóa đơn quen thuộc.",
    "UNCLEAR": "Chưa đủ thông tin để kết luận. Hãy làm 3 việc an toàn dưới đây trước khi chuyển thêm tiền.",
}


# ---------------------------------------------------------------- registry


@lru_cache
def load_registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {}
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    items = data.get("actions", []) if isinstance(data, dict) else data
    return {it["id"]: it for it in items if isinstance(it, dict) and it.get("id")}


def is_verified(entry: dict) -> bool:
    contact = entry.get("contact") or {}
    return bool(entry.get("source_url") and entry.get("verified_at") and contact.get("value")
                and contact.get("type") in ("tel", "url"))


def registry_unverified() -> list[str]:
    return sorted(k for k, v in load_registry().items() if not is_verified(v))


def _resolve(action_id: str) -> tuple[str, str | None, str | None, str | None, bool]:
    entry = load_registry().get(action_id, {})
    title = entry.get("title_vi") or DEFAULT_TITLES.get(action_id, action_id)
    if is_verified(entry):
        c = entry["contact"]
        return title, c["type"], c["value"], entry["source_url"], True
    return title, None, None, None, False


def action_card(action_id: str) -> ActionCard:
    title, ctype, cvalue, src, ok = _resolve(action_id)
    entry = load_registry().get(action_id, {})
    return ActionCard(id=action_id, title_vi=title, detail_vi=entry.get("detail_vi"),
                      contact_type=ctype, contact_value=cvalue, source_url=src, verified=ok)


def official_channels(tactic_family: str | None = None) -> list[OfficialChannel]:
    ids = list(dict.fromkeys([*TACTIC_CHANNELS.get(tactic_family or "", []), *STOP_CHANNELS]))
    out = []
    for i in ids:
        title, ctype, cvalue, src, _ = _resolve(i)
        out.append(OfficialChannel(id=i, title_vi=title, contact_type=ctype, contact_value=cvalue, source_url=src))
    return out


# ---------------------------------------------------------------- mode và việc cần làm


def compute_mode(a: IncidentAnalysis) -> Mode:
    if a.otp_or_password_disclosed == "YES" or a.remote_app_installed == "YES":
        return "COMPROMISE"
    if a.money_requested_vnd or a.manipulation_cues:
        return "MANIPULATION"
    return "UNCLEAR"


def actions_for(mode: Mode, tactic_family: str) -> list[ActionCard]:
    table = ACTION_MAP[mode]
    ids = table.get(tactic_family, table[_DEFAULT])[:3]
    return [action_card(i) for i in ids]


def raise_mode(old: str | None, new: str) -> str:
    """Chỉ nâng (INV-10)."""
    if old is None:
        return new
    return new if MODE_RANK[new] > MODE_RANK[old] else old


# ---------------------------------------------------------------- policy trên ví


def active_policy(s: Session, workspace_id: str, wallet_id: str) -> ContainmentPolicy | None:
    return s.exec(select(ContainmentPolicy).where(
        ContainmentPolicy.workspace_id == workspace_id, ContainmentPolicy.wallet_id == wallet_id,
        ContainmentPolicy.active == True,  # noqa: E712
    ).order_by(ContainmentPolicy.id.desc())).first()


def apply_containment(s: Session, *, workspace_id: str, wallet: Wallet, incident_id: str, mode: Mode,
                      by_proxy: bool) -> ContainmentPolicy | None:
    """Tạo hoặc nâng policy; UNCLEAR không tạo policy. Không bao giờ hạ. Không commit."""
    if mode == "UNCLEAR":
        return active_policy(s, workspace_id, wallet.id)
    pol = active_policy(s, workspace_id, wallet.id)
    if pol is None:
        pol = ContainmentPolicy(workspace_id=workspace_id, incident_id=incident_id, wallet_id=wallet.id,
                                mode=mode, requested_by_proxy=by_proxy)
        s.add(pol)
    else:
        new_mode = raise_mode(pol.mode, mode)
        if new_mode != pol.mode:
            pol.mode, pol.version, pol.updated_at = new_mode, pol.version + 1, utcnow()
        pol.requested_by_proxy = pol.requested_by_proxy or by_proxy
        s.add(pol)
    if pol.mode == "COMPROMISE" and not wallet.compromise_locked:
        wallet.compromise_locked = True
        s.add(wallet)
    return pol


def protective_hold_notice(pol: ContainmentPolicy | None) -> str | None:
    if pol is None:
        return None
    hhmm = pol.updated_at.astimezone(VN_TZ).strftime("%H:%M")
    who = "Người thân đã yêu cầu" if pol.requested_by_proxy else "Đã bật"
    if pol.mode == "COMPROMISE":
        what = "khóa bảo vệ toàn bộ giao dịch đi (nghi lộ OTP hoặc mật khẩu)"
    else:
        what = "tạm giữ bảo vệ các khoản chuyển tới người lạ"
    return (f"{who} {what} trên ví của bạn lúc {hhmm}. "
            "Chỉ bạn mới gỡ được, bằng cách xác minh qua kênh chính thức.")
