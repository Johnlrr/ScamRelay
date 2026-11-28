"""Kiểm thử hồi quy (SPEC §7.2e): chạy `layer1_match` — ĐÚNG HÀM gateway dùng — trên tập sạch và biến thể.

- Tập sạch `data/benign_corpus.json` (≥ 200 mẫu template + ≥ 20 ca bẫy viết tay, do bench/gen_benign.py sinh).
- Mỗi mẫu sạch bị khớp được quy về anchor cho điểm cao nhất → `flags_by_anchor` (UI tô đậm để chuyên viên xóa).
- Biến thể trong luật chỉ để tham khảo khi vận hành, KHÔNG đưa vào số liệu báo cáo.
- Embedding tập sạch đã seed sẵn vào cache lúc khởi động (`seed_benign_cache`), nên mỗi lượt chỉ tốn cosine.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.schemas.gateway import DerivedTx
from app.schemas.rule import AnchorSet, FlaggedExample, RegressionResult, RelayRule
from app.core.layer1 import layer1_explain
from app.core.preprocess import norm_match
from app.core.semantic import SemanticMatcher, get_matcher

CORPUS_PATH = Path(__file__).resolve().parents[2] / "data" / "benign_corpus.json"
MAX_EXAMPLES = 20


@lru_cache(maxsize=1)
def load_benign_corpus() -> tuple[dict, ...]:
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return tuple(data["samples"])


def _tx(note: str, amount: int, is_verified_biller: bool) -> DerivedTx:
    # Chỉ điều kiện nội dung + điều kiện sàn tham gia khớp (V3); các tín hiệu hành vi để trung tính.
    return DerivedTx(
        wallet_id="REGRESSION", to_account_id="ACC-REGRESSION", amount_vnd=amount, transfer_note=note,
        note_norm=norm_match(note), recipient_is_new=False, recipient_account_age_days=365, tx_count_10m=0,
        is_verified_biller=is_verified_biller, is_known_contact=False, account_compromise_flag=False,
    )


async def seed_benign_cache(matcher: SemanticMatcher | None = None, corpus: tuple[dict, ...] | None = None) -> bool:
    """Embed toàn bộ tập sạch vào cache (theo lô). Gọi lúc khởi động; trả False nếu API lỗi."""
    matcher = matcher or get_matcher()
    corpus = corpus if corpus is not None else load_benign_corpus()
    return await matcher.embed_texts([s["transfer_note"] for s in corpus]) is not None


async def run_regression(rule: RelayRule, anchors: AnchorSet, *, matcher: SemanticMatcher | None = None,
                         corpus: tuple[dict, ...] | list[dict] | None = None,
                         max_examples: int = MAX_EXAMPLES) -> RegressionResult:
    start = time.perf_counter()
    matcher = matcher or get_matcher()
    corpus = corpus if corpus is not None else load_benign_corpus()
    degraded = anchors.degraded or anchors.vectors is None

    notes = [s["transfer_note"] for s in corpus]
    variant_notes = [v.transfer_note for v in rule.variants]
    vecs = await matcher.embed_texts(notes + variant_notes) if anchors.vectors is not None else None
    if vecs is None:
        degraded = True

    def note_vec(i: int) -> np.ndarray | None:
        return None if vecs is None else vecs[i]

    flagged: list[FlaggedExample] = []
    by_anchor: Counter[str] = Counter()
    for i, s in enumerate(corpus):
        d = layer1_explain(rule, _tx(s["transfer_note"], int(s["amount_vnd"]), bool(s.get("is_verified_biller", False))),
                           anchors, note_vec=note_vec(i))
        degraded |= d.degraded
        if d.matched:
            flagged.append(FlaggedExample(transfer_note=s["transfer_note"], amount_vnd=int(s["amount_vnd"]),
                                          score=round(float(d.score), 4), top_anchor=d.top_anchor))
            if d.top_anchor:
                by_anchor[d.top_anchor] += 1

    missed: list[str] = []
    for j, v in enumerate(rule.variants):
        d = layer1_explain(rule, _tx(v.transfer_note, v.amount_vnd, False), anchors, note_vec=note_vec(len(notes) + j))
        degraded |= d.degraded
        if not d.matched:
            missed.append(v.transfer_note)

    flagged.sort(key=lambda f: f.score, reverse=True)
    return RegressionResult(
        rule_version=rule.version,
        benign_checked=len(corpus),
        benign_flagged=len(flagged),
        flagged_examples=flagged[:max_examples],
        flags_by_anchor=dict(by_anchor.most_common()),
        variants_checked=len(rule.variants),
        variants_triggered=len(rule.variants) - len(missed),
        variants_missed=missed,
        seconds=round(time.perf_counter() - start, 4),
        degraded=degraded,
    )
