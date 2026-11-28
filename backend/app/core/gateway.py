"""Sandbox Payment Gateway (SPEC §7.3). Không gọi LLM (D10); tối đa 1 lần embed mỗi giao dịch.

Quyết định cuối = mức nghiêm nhất của (lớp đối tác, khoanh vùng, luật tiếp sức) (D9, INV-13).
Hành động chỉ lấy từ StagePolicy (INV-07). Client không thấy outcome (INV-12).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update
from sqlmodel import Session, select

from app import config
from app.ai.interfaces import AnchorSet, baseline_score, layer1_match
from app.core import containment, ledger
from app.core.preprocess import norm_match
from app.core.stage_policy import LIVE_STAGES, PARTNER_MAP, SEVERITY, STAGE_RANK, Floor, max_severity, stage_action
from app.models import (
    Account,
    Challenge,
    ContainmentPolicy,
    RelayRuleRow,
    RuleEvent,
    Transaction,
    Wallet,
    new_id,
    utcnow,
)
from app.routers.errors import ApiError
from app.schemas.gateway import (
    BaselineView,
    ChallengeOptionOut,
    ChallengeOut,
    DerivedTx,
    EvaluateResponse,
    SubmitChallengeRequest,
    SubmitChallengeResponse,
    TransferRequest,
)
from app.schemas.rule import RelayRule

STOPPING = ("HOLD_15M", "STOP_AND_EXPLAIN", "HOLD_UNTIL_VERIFIED", "BLOCK")
MATCHABLE_STAGES = ("SHADOW_LOG", *LIVE_STAGES)

# ---------------------------------------------------------------- luật


def log_event(s: Session, row: RelayRuleRow, event: str, actor: str, payload: dict | None = None) -> None:
    s.add(RuleEvent(workspace_id=row.workspace_id, rule_id=row.id, version=row.version, event=event,
                    actor=actor, payload=payload or {}))


def expire_rules_lazily(s: Session, workspace_id: str) -> int:
    """Luật có expires_at < now → EXPIRED, không cần cron (SPEC §7.2g). Không commit."""
    now = utcnow()
    n = 0
    for row in s.exec(select(RelayRuleRow).where(RelayRuleRow.workspace_id == workspace_id,
                                                 RelayRuleRow.stage.in_(MATCHABLE_STAGES))).all():
        if row.expires_at is not None and row.expires_at < now:
            row.stage = "EXPIRED"
            if row.rule_json:
                row.rule_json = {**row.rule_json, "lifecycle": {**row.rule_json["lifecycle"], "stage": "EXPIRED"}}
            log_event(s, row, "EXPIRED", "system")
            s.add(row)
            n += 1
    return n


def rule_of(row: RelayRuleRow) -> RelayRule:
    return RelayRule.model_validate(row.rule_json)


_ANCHOR_CACHE: dict[tuple[str, int], AnchorSet] = {}


async def anchors_for(rule: RelayRule) -> AnchorSet:
    """AnchorSet theo (rule_id, version); embedding đã cache trong DB nên dựng lại rất rẻ."""
    from app.core.layer1 import semantic_phrases
    from app.core.semantic import get_matcher

    key = (rule.rule_id, rule.version)
    if key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[key]
    anchors = await get_matcher().prepare_anchors(semantic_phrases(rule))
    if not anchors.degraded:
        _ANCHOR_CACHE[key] = anchors
    return anchors


def clear_anchor_cache() -> None:
    _ANCHOR_CACHE.clear()


# ---------------------------------------------------------------- tín hiệu


def derive_signals(s: Session, workspace_id: str, req: TransferRequest) -> tuple[DerivedTx, Wallet, Account]:
    wallet = s.get(Wallet, (workspace_id, req.wallet_id))
    if wallet is None:
        raise ApiError(404, "WALLET_NOT_FOUND", "Không tìm thấy ví trong workspace này. Hãy đăng nhập tài khoản giám khảo.")
    acc = s.get(Account, (workspace_id, req.to_account_id))
    if acc is None:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "Không tìm thấy tài khoản nhận.")
    known = req.to_account_id in (wallet.known_contacts or [])
    paid_before = s.exec(select(Transaction.id).where(
        Transaction.workspace_id == workspace_id, Transaction.wallet_id == wallet.id,
        Transaction.to_account_id == acc.id, Transaction.status == "COMMITTED")).first() is not None
    since = utcnow() - timedelta(minutes=10)
    recent = s.exec(select(Transaction.id).where(
        Transaction.workspace_id == workspace_id, Transaction.wallet_id == wallet.id,
        Transaction.status.in_(("COMMITTED", "HELD")), Transaction.created_at >= since)).all()
    tx = DerivedTx(
        wallet_id=wallet.id, to_account_id=acc.id, amount_vnd=req.amount_vnd, transfer_note=req.transfer_note,
        note_norm=norm_match(req.transfer_note), recipient_is_new=not known and not paid_before,
        recipient_account_age_days=acc.age_days, tx_count_10m=len(recent),
        is_verified_biller=acc.is_verified_biller, is_known_contact=known,
        account_compromise_flag=wallet.compromise_locked,
    )
    return tx, wallet, acc


def _policy_refs(pol: ContainmentPolicy | None, row: RelayRuleRow | None, rule_version: int | None = None) -> list[dict]:
    refs = []
    if pol is not None:
        refs.append({"type": "containment_policy", "id": str(pol.id), "version": pol.version, "mode": pol.mode})
    if row is not None:
        refs.append({"type": "relay_rule", "id": row.id, "version": rule_version or row.version})
    return refs


def _channels(decision: str, tactic_family: str | None):
    return containment.official_channels(tactic_family) if decision in STOPPING else []


def _active_for(row: RelayRuleRow | None) -> int | None:
    if row is None or row.activated_at is None:
        return None
    return max(0, int((utcnow() - row.activated_at).total_seconds()))


# ---------------------------------------------------------------- evaluate


async def evaluate(s: Session, workspace_id: str, req: TransferRequest) -> EvaluateResponse:
    from app.core.semantic import get_matcher

    expire_rules_lazily(s, workspace_id)
    ledger.expire_challenges(s, workspace_id)
    ledger.release_holds(s, workspace_id)

    tx, wallet, _acc = derive_signals(s, workspace_id, req)
    ledger.ensure_funds(wallet, req.amount_vnd)
    base = baseline_score(tx)
    tx.partner_risk_score = base.risk_score
    floor = Floor(PARTNER_MAP[base.decision], [f"PARTNER_{base.decision}"])
    baseline = BaselineView(decision=base.decision, risk_score=base.risk_score, as_final=PARTNER_MAP[base.decision])

    row_tx = Transaction(id=new_id("TX"), workspace_id=workspace_id, wallet_id=wallet.id, to_account_id=tx.to_account_id,
                         amount_vnd=tx.amount_vnd, transfer_note=tx.transfer_note, status="PENDING_CHALLENGE",
                         partner_decision=base.decision, partner_risk_score=base.risk_score)

    # 1) khoanh vùng ví
    pol = containment.active_policy(s, workspace_id, wallet.id)
    if wallet.compromise_locked or (pol and pol.mode == "COMPROMISE"):
        floor.raise_to("BLOCK", "CONTAINMENT_COMPROMISE")
        return _final(s, row_tx, wallet, floor, baseline, pol, None, None)
    if pol and pol.mode == "MANIPULATION" and not (tx.is_verified_biller or tx.is_known_contact):
        floor.raise_to("HOLD_UNTIL_VERIFIED", "CONTAINMENT_MANIPULATION")

    # 2) luật tiếp sức; biller đã xác minh không bao giờ bị hỏi (INV-15)
    hits: list[tuple[RelayRuleRow, RelayRule, float]] = []
    if not tx.is_verified_biller:
        rows = s.exec(select(RelayRuleRow).where(RelayRuleRow.workspace_id == workspace_id,
                                                 RelayRuleRow.stage.in_(MATCHABLE_STAGES))).all()
        rows = [r for r in rows if r.rule_json]
        note_vec = None
        s.commit()   # nhả khóa ghi (SQLite) trước khi chờ embedding; object vẫn dùng được
        if rows and len(tx.note_norm) >= 4:
            note_vec = await get_matcher().note_vector(tx.note_norm)
        for r in rows:
            rule = rule_of(r)
            score = layer1_match(rule, tx, await anchors_for(rule), note_vec=note_vec)
            if score is not None:
                hits.append((r, rule, score))
    for r, _, score in hits:
        if r.stage == "SHADOW_LOG":
            log_event(s, r, "SHADOW_HIT", "gateway", {"tx_id": row_tx.id, "score": round(score, 4)})
    live = [(r, rule, sc) for r, rule, sc in hits if r.stage in LIVE_STAGES]

    # 3) chỉ hỏi khi câu trả lời còn có thể thay đổi kết quả
    if live and SEVERITY[floor.decision] < SEVERITY["STOP_AND_EXPLAIN"]:
        r, rule, _ = max(live, key=lambda x: (STAGE_RANK[x[0].stage], x[2]))
        return _issue_challenge(s, row_tx, r, rule, floor, baseline)
    matched = live[0] if live else None
    return _final(s, row_tx, wallet, floor, baseline, pol, matched[0] if matched else None,
                  matched[1] if matched else None)


def _final(s: Session, row_tx: Transaction, wallet: Wallet, floor: Floor, baseline: BaselineView,
           pol: ContainmentPolicy | None, row: RelayRuleRow | None, rule: RelayRule | None) -> EvaluateResponse:
    reasons = list(floor.reasons)
    if row is not None:
        row_tx.matched_rule_id, row_tx.matched_rule_version = row.id, row.version
        reasons.append("RULE_MATCH_FLOOR_ALREADY_STOPS")
    receipt = ledger.apply_decision(s, row_tx, wallet, floor.decision, reasons, _policy_refs(pol, row))
    s.commit()
    return EvaluateResponse(
        tx_id=row_tx.id, status="FINAL", decision=floor.decision, challenge=None, baseline=baseline,
        reason_codes=row_tx.reason_codes, matched_rule_id=row.id if row else None, receipt_id=receipt.id,
        message_vi=ledger.MESSAGE_VI[floor.decision],
        official_channels=_channels(floor.decision, rule.tactic_family if rule else None),
        retry_after=row_tx.retry_after, rule_active_for_seconds=_active_for(row),
    )


def _issue_challenge(s: Session, row_tx: Transaction, row: RelayRuleRow, rule: RelayRule, floor: Floor,
                     baseline: BaselineView) -> EvaluateResponse:
    q = rule.jit_purpose_question
    ch = Challenge(
        id=new_id("CH"), workspace_id=row_tx.workspace_id, tx_id=row_tx.id, rule_id=row.id, rule_version=row.version,
        options_json=[o.model_dump() for o in q.options], floor_decision=floor.decision,
        floor_reasons=list(floor.reasons), expires_at=utcnow() + timedelta(minutes=config.CHALLENGE_TTL_MINUTES),
    )
    row_tx.status = "PENDING_CHALLENGE"
    row_tx.matched_rule_id, row_tx.matched_rule_version = row.id, row.version
    row_tx.reason_codes = [*floor.reasons, "RULE_MATCH"]
    s.add(row_tx)
    s.add(ch)
    log_event(s, row, "CHALLENGE_ISSUED", "gateway", {"tx_id": row_tx.id, "challenge_id": ch.id})
    s.commit()
    return EvaluateResponse(
        tx_id=row_tx.id, status="CHALLENGE_JIT", decision=None,
        challenge=ChallengeOut(challenge_id=ch.id, question_vi=q.question_vi,
                               options=[ChallengeOptionOut(id=o.id, label_vi=o.label_vi) for o in q.options],
                               anti_coaching_notice_vi=q.anti_coaching_notice_vi, expires_at=ch.expires_at),
        baseline=baseline, reason_codes=list(row_tx.reason_codes), matched_rule_id=row.id, receipt_id=None,
        message_vi=None, official_channels=[], retry_after=None, rule_active_for_seconds=_active_for(row),
    )


# ---------------------------------------------------------------- submit


def submit(s: Session, workspace_id: str, req: SubmitChallengeRequest) -> SubmitChallengeResponse:
    """Toàn bộ trong MỘT transaction DB (SPEC §7.3). Lỗi ở bất kỳ bước nào → rollback, challenge chưa bị dùng."""
    from app.db import IMMEDIATE

    now = utcnow()
    s.commit()                                   # đóng transaction cũ (nếu có) của dependency
    s.connection(execution_options=IMMEDIATE)    # SQLite: BEGIN IMMEDIATE; Postgres: không ảnh hưởng
    try:
        # 1) claim nguyên tử
        res = s.execute(update(Challenge)
                     .where(Challenge.id == req.challenge_id, Challenge.workspace_id == workspace_id,
                            Challenge.used == False, Challenge.expires_at > now)  # noqa: E712
                     .values(used=True))
        if res.rowcount != 1:
            ch = s.get(Challenge, req.challenge_id)
            if ch is None or ch.workspace_id != workspace_id:
                raise ApiError(404, "CHALLENGE_NOT_FOUND", "Không tìm thấy câu hỏi xác nhận.")
            if ch.used:
                raise ApiError(409, "CHALLENGE_USED", "Câu hỏi này đã được trả lời. Hãy tạo lại giao dịch nếu cần.")
            raise ApiError(409, "CHALLENGE_EXPIRED", "Câu hỏi đã hết hạn. Giao dịch không được thực hiện; hãy tạo lại.")
        ch = s.get(Challenge, req.challenge_id)
        s.refresh(ch)

        # 2) outcome lấy từ phía server
        opt = next((o for o in ch.options_json if o["id"] == req.option_id), None)
        if opt is None:
            raise ApiError(422, "INVALID_OPTION", "Phương án không thuộc câu hỏi này.")
        outcome = opt["outcome"]

        tx = s.get(Transaction, ch.tx_id)
        if tx is None or tx.status != "PENDING_CHALLENGE":
            raise ApiError(409, "TX_NOT_PENDING", "Giao dịch không còn chờ xác nhận.")

        # 3) kiểm tra lại ví (khóa dòng ví; SQLite đã BEGIN IMMEDIATE)
        wallet = s.exec(select(Wallet).where(Wallet.workspace_id == workspace_id, Wallet.id == tx.wallet_id)
                        .with_for_update()).one()
        acc = s.get(Account, (workspace_id, tx.to_account_id))
        floor = Floor(ch.floor_decision, list(ch.floor_reasons))
        pol = containment.active_policy(s, workspace_id, wallet.id)
        if wallet.compromise_locked or (pol and pol.mode == "COMPROMISE"):
            floor.raise_to("BLOCK", "CONTAINMENT_COMPROMISE")
        elif pol and pol.mode == "MANIPULATION" and not (
                (acc and acc.is_verified_biller) or tx.to_account_id in (wallet.known_contacts or [])):
            floor.raise_to("HOLD_UNTIL_VERIFIED", "CONTAINMENT_MANIPULATION")

        # 4) đọc lại luật; 5) StagePolicy; 7) max với mức sàn
        row = s.get(RelayRuleRow, ch.rule_id)
        reasons = list(floor.reasons)
        action = stage_action(row.stage, outcome) if row is not None else None
        if action is None:
            reasons.append("RULE_NO_LONGER_ACTIVE")
            final = floor.decision
        else:
            reasons += [f"ANSWER_{outcome}", f"STAGE_{row.stage}"]
            final = max_severity(floor.decision, action)

        # 8) ghi sổ, biên lai, sự kiện
        receipt = ledger.apply_decision(s, tx, wallet, final, reasons, _policy_refs(pol, row, ch.rule_version))
        ch.answered_option_id, ch.answered_outcome = req.option_id, outcome
        s.add(ch)
        if row is not None:
            log_event(s, row, "ANSWERED", "gateway", {"tx_id": tx.id, "outcome": outcome, "decision": final})
        rule = rule_of(row) if row is not None and row.rule_json else None
        s.commit()
    except Exception:
        s.rollback()
        raise

    stopped_by_rule = action is not None and outcome == "TACTIC_MATCH" and final in STOPPING
    return SubmitChallengeResponse(
        tx_id=tx.id, decision=final, reason_codes=tx.reason_codes, receipt_id=receipt.id,
        tactic_alert_vi=rule.jit_purpose_question.tactic_alert_vi if (stopped_by_rule and rule) else None,
        message_vi=ledger.MESSAGE_VI[final],
        official_channels=_channels(final, rule.tactic_family if rule else None),
        retry_after=tx.retry_after,
    )
