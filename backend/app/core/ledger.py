"""Sổ giao dịch và biên lai (SPEC §7.3 "Hành động, ghi sổ và màn hình"). Không commit — người gọi commit."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from sqlmodel import Session, select

from app import config
from app.models import Challenge, Receipt, Transaction, Wallet, new_id, utcnow
from app.routers.errors import ApiError

ALLOWING = ("ALLOW", "ALLOW_WITH_WARNING")

MESSAGE_VI: dict[str, str | None] = {
    "ALLOW": "Chuyển tiền thành công.",
    "ALLOW_WITH_WARNING": "Chuyển tiền thành công. " + config.ANTI_COACHING_NOTICE_VI,
    "HOLD_15M": f"Giao dịch đang được tạm giữ {config.HOLD_MINUTES} phút để bạn kiểm tra lại. Tiền chưa rời ví.",
    "STOP_AND_EXPLAIN": (f"Giao dịch đã dừng, 0đ rời ví. Hãy kiểm tra qua kênh chính thức; "
                         f"bạn có thể tạo lại giao dịch sau {config.STOP_COOLDOWN_MINUTES} phút."),
    "HOLD_UNTIL_VERIFIED": "Giao dịch đang được giữ cho tới khi bạn xác minh qua kênh chính thức. Tiền chưa rời ví.",
    "BLOCK": "Ví đang được khóa bảo vệ. Mọi giao dịch đi đều bị chặn cho tới khi chủ ví xác minh qua kênh chính thức.",
}

STATUS_FOR = {
    "ALLOW": "COMMITTED", "ALLOW_WITH_WARNING": "COMMITTED", "HOLD_15M": "HELD",
    "STOP_AND_EXPLAIN": "STOPPED", "HOLD_UNTIL_VERIFIED": "HELD", "BLOCK": "BLOCKED",
}


def ensure_funds(wallet: Wallet, amount: int) -> None:
    if wallet.balance_vnd < amount:
        raise ApiError(409, "INSUFFICIENT_FUNDS", "Số dư không đủ để thực hiện giao dịch.")


def apply_decision(s: Session, tx: Transaction, wallet: Wallet, decision: str, reason_codes: list[str],
                   policy_refs: list[dict]) -> Receipt:
    """Ghi sổ theo hành động và tạo biên lai. ALLOW* trừ tiền ngay; các hành động khác 0đ rời ví."""
    now = utcnow()
    if decision in ALLOWING:
        ensure_funds(wallet, tx.amount_vnd)
        wallet.balance_vnd -= tx.amount_vnd
        s.add(wallet)
    tx.status = STATUS_FOR[decision]
    tx.decision = decision
    tx.reason_codes = list(dict.fromkeys(reason_codes))
    tx.release_at = now + timedelta(minutes=config.HOLD_MINUTES) if decision == "HOLD_15M" else None
    tx.retry_after = now + timedelta(minutes=config.STOP_COOLDOWN_MINUTES) if decision == "STOP_AND_EXPLAIN" else None
    receipt = make_receipt(tx, policy_refs)
    tx.receipt_id = receipt.id
    s.add(tx)
    s.add(receipt)
    return receipt


def make_receipt(tx: Transaction, policy_refs: list[dict]) -> Receipt:
    rid = new_id("RC")
    body = {
        "receipt_id": rid, "tx_id": tx.id, "wallet_id": tx.wallet_id, "to_account_id": tx.to_account_id,
        "amount_vnd": tx.amount_vnd, "decision": tx.decision, "reason_codes": tx.reason_codes,
        "policy_refs": policy_refs, "issued_at": utcnow().isoformat(),
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                            .encode("utf-8")).hexdigest()
    return Receipt(id=rid, workspace_id=tx.workspace_id, tx_id=tx.id, decision=tx.decision or "",
                   reason_codes=list(tx.reason_codes), policy_refs=policy_refs, hash=digest)


def release_holds(s: Session, workspace_id: str, *, force: bool = False) -> int:
    """Giải phóng HOLD_15M đã tới giờ (force: mọi HOLD_15M, cho nút fast-forward). Trừ tiền lúc giải phóng."""
    now = utcnow()
    q = select(Transaction).where(Transaction.workspace_id == workspace_id, Transaction.status == "HELD",
                                  Transaction.decision == "HOLD_15M")
    released = 0
    for tx in s.exec(q).all():
        if not force and (tx.release_at is None or tx.release_at > now):
            continue
        wallet = s.get(Wallet, (workspace_id, tx.wallet_id))
        if wallet is None or wallet.compromise_locked or wallet.balance_vnd < tx.amount_vnd:
            tx.status = "EXPIRED"
            tx.reason_codes = [*tx.reason_codes, "RELEASE_FAILED"]
        else:
            wallet.balance_vnd -= tx.amount_vnd
            tx.status = "COMMITTED"
            tx.reason_codes = [*tx.reason_codes, "HOLD_RELEASED"]
            s.add(wallet)
            released += 1
        tx.release_at = None
        s.add(tx)
    return released


def expire_challenges(s: Session, workspace_id: str) -> int:
    """Challenge hết hạn chưa trả lời → giao dịch EXPIRED, không trừ tiền (INV-08)."""
    now = utcnow()
    n = 0
    for ch in s.exec(select(Challenge).where(Challenge.workspace_id == workspace_id, Challenge.used == False,  # noqa: E712
                                             Challenge.expires_at <= now)).all():
        tx = s.get(Transaction, ch.tx_id)
        if tx is not None and tx.status == "PENDING_CHALLENGE":
            tx.status = "EXPIRED"
            tx.reason_codes = [*tx.reason_codes, "CHALLENGE_EXPIRED"]
            s.add(tx)
            n += 1
        ch.used = True
        s.add(ch)
    return n
