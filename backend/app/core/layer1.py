"""Lớp 1 — `layer1_match` (SPEC §7.3). CÙNG MỘT HÀM cho regression và gateway.

Luật khớp khi MỌI `conditions` (nội dung) và `guard_conditions` (sàn, server gắn) đều thỏa.
Biller đã xác minh không bao giờ khớp (INV-15) — vừa nhờ điều kiện sàn, vừa chặn tường minh ở đây.

Hàm thuần, đồng bộ: embedding của nội dung giao dịch được tính TRƯỚC (`SemanticMatcher.note_vector`,
tối đa 1 lần/giao dịch, có cache) rồi truyền vào `note_vec`. Nếu `note_vec` hoặc `anchors.vectors`
là None (API embedding lỗi) thì SEMANTIC_MATCH dùng trigram với `TRIGRAM_THRESHOLD` và kết quả
mang `degraded=True` (xem `layer1_explain`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.config import TRIGRAM_THRESHOLD
from app.schemas.gateway import DerivedTx
from app.schemas.rule import AnchorSet, Condition, RelayRule
from app.core.preprocess import norm_match
from app.core.semantic import MIN_NOTE_LEN, trigram_cosine, trigrams


@dataclass
class Layer1Detail:
    matched: bool
    score: float | None = None            # điểm xếp hạng khi khớp (cosine; 1.0 nếu không có SEMANTIC_MATCH)
    semantic_score: float | None = None   # cosine/trigram cao nhất (kể cả khi không khớp)
    top_anchor: str | None = None         # anchor cho điểm cao nhất (quy khớp nhầm về anchor)
    degraded: bool = False                # đã dùng trigram
    failed: list[str] = field(default_factory=list)
    culprits: list[str] = field(default_factory=list)   # mọi anchor tự nó vượt ngưỡng (regression tô đậm hết)


def semantic_phrases(rule: RelayRule) -> list[str]:
    """Mọi anchor của luật ở dạng `norm_match`, không trùng, giữ thứ tự. Dùng để dựng AnchorSet."""
    out: dict[str, None] = {}
    for c in rule.observable_signals.conditions:
        if c.op == "SEMANTIC_MATCH":
            for a in c.anchor_phrases or []:
                if p := norm_match(a):
                    out[p] = None
    return list(out)


def _contains(note: str, phrases: list[str] | None) -> bool:
    padded = f" {note} "
    return any((p := norm_match(x)) and f" {p} " in padded for x in phrases or [])


def _numeric(c: Condition, tx: DerivedTx) -> bool:
    value = getattr(tx, c.field, None)
    if value is None:
        return False
    if isinstance(value, bool):
        return c.op == "EQ" and c.value_bool is not None and value == c.value_bool
    if c.value_int is None:
        return False
    return {"EQ": value == c.value_int, "LTE": value <= c.value_int, "GTE": value >= c.value_int}.get(c.op, False)


def layer1_explain(rule: RelayRule, tx: DerivedTx, anchors: AnchorSet, *,
                   note_vec: np.ndarray | None = None,
                   trigram_threshold: float = TRIGRAM_THRESHOLD) -> Layer1Detail:
    detail = Layer1Detail(matched=False)
    if tx.is_verified_biller:
        detail.failed.append("VERIFIED_BILLER")
        return detail

    note = norm_match(tx.note_norm or tx.transfer_note)
    index = {p: i for i, p in enumerate(anchors.phrases)}
    use_vectors = note_vec is not None and anchors.vectors is not None
    sem_scores: list[float] = []
    sig = rule.observable_signals

    for c in [*sig.conditions, *sig.guard_conditions]:
        ok: bool
        if c.op == "SEMANTIC_MATCH":
            phrases = [p for p in (norm_match(a) for a in c.anchor_phrases or []) if p]
            missing = [p for p in phrases if p not in index]
            if missing:
                raise ValueError(f"AnchorSet không khớp phiên bản luật: thiếu anchor {missing[:3]}")
            if len(note) < MIN_NOTE_LEN or not phrases:
                ok = False
            else:
                idxs = [index[p] for p in phrases]
                if use_vectors:
                    sims = [float(x) for x in anchors.vectors[idxs] @ note_vec]
                    threshold = sig.threshold
                else:
                    tn = trigrams(note)
                    sims = [trigram_cosine(tn, trigrams(anchors.phrases[i])) for i in idxs]
                    threshold = trigram_threshold
                    detail.degraded = True
                j = max(range(len(sims)), key=sims.__getitem__)
                s = sims[j]
                if detail.semantic_score is None or s > detail.semantic_score:
                    detail.semantic_score, detail.top_anchor = s, anchors.phrases[idxs[j]]
                detail.culprits += [anchors.phrases[i] for i, x in zip(idxs, sims) if x >= threshold]
                ok = s >= threshold
                sem_scores.append(s)
        elif c.op == "CONTAINS_ANY":
            ok = _contains(note, c.value_str_list)
        elif c.op == "NOT_CONTAINS_ANY":
            ok = not _contains(note, c.value_str_list)
        else:
            ok = _numeric(c, tx)
        if not ok:
            detail.failed.append(f"{c.field} {c.op}")

    if not detail.failed:
        detail.matched = True
        detail.score = min(sem_scores) if sem_scores else 1.0
    return detail


def layer1_match(rule: RelayRule, tx: DerivedTx, anchors: AnchorSet, *,
                 note_vec: np.ndarray | None = None,
                 trigram_threshold: float = TRIGRAM_THRESHOLD) -> float | None:
    """None nếu không khớp; nếu khớp trả điểm dùng để xếp hạng (SPEC §7.3)."""
    d = layer1_explain(rule, tx, anchors, note_vec=note_vec, trigram_threshold=trigram_threshold)
    return d.score if d.matched else None
