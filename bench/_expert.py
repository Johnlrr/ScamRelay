"""Mô phỏng thao tác sửa luật của chuyên viên FraudOps trong demo (bench/demo_rehearsal.py, bench/eval_demo_edit.py).

Cách sửa đã chốt cho demo (bao, 28/11): **thêm cụm loại trừ** vào điều kiện `NOT_CONTAINS_ANY` thay vì xóa câu mẫu.
Quy tắc tất định, chỉ dùng thứ chuyên viên thấy trên màn hình kiểm thử (mẫu sạch bị khớp, câu mẫu, biến thể);
không nhìn câu demo của chú Hùng:

- Với mỗi mẫu sạch bị khớp: xét các cụm 2–4 từ liên tiếp; chọn cụm có nhiều từ KHÔNG thuộc câu mẫu nhất,
  không bắt đầu/kết thúc bằng từ chung (tiền, phí, nộp…), dài hơn khi hòa (giữ trọn thuật ngữ)
  (vd. "phí dịch vụ kế toán hộ kinh doanh" → "dich vu ke toan").
- Bỏ cụm nằm trong câu mẫu hay trong nội dung biến thể của luật (loại trừ nó sẽ làm luật bỏ sót chính thủ đoạn).
- Không tìm được cụm phù hợp thì trả None: chuyên viên xóa câu mẫu được tô đậm cho riêng mẫu đó (cách cũ).
"""

from __future__ import annotations

import _common  # noqa: F401  (đưa backend vào sys.path)

from app.core.preprocess import norm_match

MAX_EXCLUSIONS = 10                     # V3b: NOT_CONTAINS_ANY tối đa 10 cụm
GENERIC = {"tien", "phi", "chuyen", "nop", "dong", "thanh", "cho", "cua", "va", "thang", "nam", "le", "ho", "so",
           "khoan", "ck", "thue", "kinh", "doanh", "tai", "lai", "cap", "nhat", "xac", "minh", "thuc"}


def exclusion_for(flagged_note: str, anchors: list[str], variant_notes: list[str]) -> str | None:
    words = norm_match(flagged_note).split()
    anchor_norms = [f" {norm_match(a)} " for a in anchors]
    anchor_words = {w for a in anchor_norms for w in a.split()}
    variants = [f" {norm_match(v)} " for v in variant_notes]
    best, best_key = None, None
    for n in (2, 3, 4):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            phrase = " ".join(gram)
            novel = sum(w not in anchor_words for w in gram)
            if novel == 0 or not 3 <= len(phrase) <= 40:
                continue
            if any(f" {phrase} " in s for s in anchor_norms + variants):
                continue
            edges = (gram[0] in GENERIC) + (gram[-1] in GENERIC)
            key = (novel, -edges, n)
            if best_key is None or key > best_key:
                best, best_key = phrase, key
    return best


def add_exclusions(draft: dict, flagged_notes: list[str]) -> list[str]:
    """Sửa `draft` tại chỗ: thêm cụm loại trừ cho từng mẫu sạch bị khớp. Trả các cụm đã thêm."""
    anchors = [a for c in draft["conditions"] if c["op"] == "SEMANTIC_MATCH" for a in c["anchor_phrases"]]
    variants = [v["transfer_note"] for v in draft.get("variants", [])]
    excl = next((c for c in draft["conditions"] if c["op"] == "NOT_CONTAINS_ANY"), None)
    if excl is None:
        excl = {"field": "transfer_note", "op": "NOT_CONTAINS_ANY", "value_str_list": []}
        draft["conditions"].append(excl)
    have = {norm_match(x) for x in excl["value_str_list"] or []}
    added = []
    for note in flagged_notes:
        phrase = exclusion_for(note, anchors, variants)
        if phrase and phrase not in have and len(have) < MAX_EXCLUSIONS:
            excl["value_str_list"] = [*(excl["value_str_list"] or []), phrase]
            have.add(phrase)
            added.append(phrase)
    return added
