"""SPEC §8.6 — kiểm tra câu demo trước khi làm tiếp.

In cosine giữa câu demo "xac thuc ho so cap nhat thue HKD" (trước và sau mở rộng viết tắt) và các
câu sạch dễ nhầm với bộ anchor HKD mẫu. Câu demo phải vượt ngưỡng placeholder với biên rõ ràng;
câu sạch phải nằm dưới ngưỡng.

    backend/.venv/bin/python bench/check_demo.py [--threshold 0.78]

Chỉ gọi gemini-embedding-001 (≤ 3 request, có cache tại bench/.cache/).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import _common  # noqa: F401  (sys.path + .env)

from app.core._contract_draft import SEMANTIC_THRESHOLD
from app.core.preprocess import norm, norm_match
from app.core.semantic import GeminiEmbedder, NpzEmbeddingCache, SemanticMatcher, best_cosine, best_trigram

# Bộ anchor HKD mẫu do người viết (không phải output LLM) — chỉ để kiểm tra chuẩn hóa/embedding.
HKD_ANCHORS = [
    "dong phi xac minh ho kinh doanh",
    "cap nhat thong tin thue ho kinh doanh",
    "phi kich hoat ma so thue dien tu",
    "xac thuc tai khoan thue ho kinh doanh",
    "phi dinh danh ho kinh doanh tren he thong thue",
    "nop phi mo khoa ma so thue",
]
DEMO = "xac thuc ho so cap nhat thue HKD"
BENIGN = [
    "tra tien thue nha thang 12",
    "tien thue mat bang thang 11",
    "phi dich vu ke toan cho ho kinh doanh",
    "nop thue mon bai quy 4",
    "tien hang tap hoa dot 2",
]
MARGIN = 0.05   # biên tối thiểu mong muốn so với ngưỡng


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=SEMANTIC_THRESHOLD)
    args = ap.parse_args()
    _common.load_env()

    embedder = GeminiEmbedder()
    matcher = SemanticMatcher(embedder, NpzEmbeddingCache(_common.CACHE_PATH))
    anchors = await matcher.prepare_anchors(HKD_ANCHORS)
    if anchors.vectors is None:
        print("LỖI: không gọi được API embedding (kiểm tra GEMINI_API_KEY / quota).")
        return 2

    # "trước mở rộng viết tắt": embed thẳng norm() (bỏ qua norm_match) bằng embedder
    raw_vec = (await embedder.embed_batch([norm(DEMO)]))[0]
    rows = [("DEMO (chỉ norm, chưa mở rộng)", norm(DEMO), raw_vec, True)]
    texts = [DEMO] + BENIGN
    vecs = await matcher.embed_texts(texts)
    if vecs is None:
        print("LỖI: embedding thất bại.")
        return 2
    rows.append(("DEMO (norm_match)", norm_match(DEMO), vecs[0], True))
    rows += [("SẠCH", norm_match(t), v, False) for t, v in zip(BENIGN, vecs[1:])]

    print(f"ngưỡng = {args.threshold:.2f}   biên mong muốn = {MARGIN:.2f}   anchors = {len(anchors.phrases)}")
    print(f"{'loại':32} {'cosine':>7} {'trigram':>7}  anchor gần nhất  |  câu")
    ok = True
    for kind, text, vec, is_scam in rows:
        cos, idx = best_cosine(vec, anchors.vectors)
        tri, _ = best_trigram(text, anchors.phrases)
        if is_scam and kind.startswith("DEMO (norm_match)"):
            verdict = cos >= args.threshold + MARGIN
        elif is_scam:
            verdict = True    # chỉ để so sánh tác dụng của mở rộng viết tắt
        else:
            verdict = cos < args.threshold
        ok &= verdict
        flag = "OK " if verdict else "XXX"
        print(f"{flag} {kind:28} {cos:7.3f} {tri:7.3f}  {anchors.phrases[idx][:30]:30} | {text}")
    print(f"\nrequest embedding đã gọi: {embedder.requests}")
    print("KẾT LUẬN:", "ĐẠT" if ok else "CHƯA ĐẠT — xem lại chuẩn hóa/anchor/ngưỡng")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
