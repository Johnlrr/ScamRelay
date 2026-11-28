"""bench/_expert.py — mô phỏng chuyên viên thêm cụm loại trừ trong demo (tập dượt, đánh giá offline)."""

from __future__ import annotations

import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[2] / "bench"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

from _expert import MAX_EXCLUSIONS, add_exclusions, exclusion_for  # noqa: E402

ANCHORS = ["phi xac minh ho kinh doanh", "thanh toan phi cap nhat thue", "nop phi ho so thue"]


def test_picks_whole_legit_term_not_anchor_words():
    assert exclusion_for("phí dịch vụ kế toán hộ kinh doanh", ANCHORS, []) == "dich vu ke toan"


def test_never_excludes_text_of_rule_variants():
    # cụm nằm trong biến thể thủ đoạn thì không được loại trừ (luật sẽ bỏ sót chính thủ đoạn)
    got = exclusion_for("phí dịch vụ kế toán hộ kinh doanh", ANCHORS, ["phi dich vu ke toan ho kinh doanh 2026"])
    assert got is None or got not in "phi dich vu ke toan ho kinh doanh 2026"


def test_none_when_note_is_all_anchor_words():
    assert exclusion_for("phí xác minh hộ kinh doanh", ANCHORS, []) is None


def test_add_exclusions_appends_creates_and_caps():
    draft = {"conditions": [{"field": "transfer_note", "op": "SEMANTIC_MATCH", "anchor_phrases": ANCHORS}],
             "variants": []}
    added = add_exclusions(draft, ["phí dịch vụ kế toán hộ kinh doanh", "phí dịch vụ kế toán hộ kinh doanh"])
    excl = next(c for c in draft["conditions"] if c["op"] == "NOT_CONTAINS_ANY")
    assert added == ["dich vu ke toan"] and excl["value_str_list"] == ["dich vu ke toan"]
    excl["value_str_list"] = [f"cum {i} khac" for i in range(MAX_EXCLUSIONS)]
    assert add_exclusions(draft, ["phí gia hạn hợp đồng thuê"]) == []          # V3b: tối đa 10 cụm
