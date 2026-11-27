"""Sinh tập sạch cho kiểm thử hồi quy (SPEC §7.2e): ≥ 200 mẫu template + ≥ 20 ca bẫy viết tay.

    backend/.venv/bin/python bench/gen_benign.py          # ghi backend/data/benign_corpus.json

Tất định (seed cố định). Không gọi API. Chỉ dữ liệu tổng hợp: tên riêng chỉ là tên gọi phổ biến,
không có số tài khoản/SĐT. Mỗi mẫu có `transfer_note`, `amount_vnd`, `is_verified_biller`.
"""

from __future__ import annotations

import json
import random
import sys

import _common

from app.core.preprocess import norm, norm_match

SEED = 20261127
N_TEMPLATE = 240
OUT = _common.BACKEND / "data" / "benign_corpus.json"

NAMES = ["Lan", "Hùng", "Tuấn", "Hoa", "Minh", "Hải", "Mai", "Nam", "Trang", "Dũng", "Linh", "Quỳnh", "Bảo", "Phương"]
ITEMS = ["gạo", "nước mắm", "mì gói", "sữa", "bánh kẹo", "nước ngọt", "dầu ăn", "trứng", "rau củ", "bia", "thuốc lá",
         "bột giặt", "phụ tùng xe", "vải", "điện thoại", "tai nghe", "áo khoác", "giày"]
COURSES = ["tiếng Anh", "toán", "đàn", "bơi", "vẽ", "lái xe", "tin học"]
MEALS = ["trưa", "tối", "lẩu", "nướng", "liên hoan", "sinh nhật"]
THINGS = ["xe máy", "phòng trọ", "căn hộ", "tiệc cưới", "lô hàng", "bàn ghế", "tour Đà Lạt"]
SERVICES = ["internet", "truyền hình cáp", "gas", "rác", "gửi xe", "điện thoại trả sau"]
PLACES = ["Đà Lạt", "Vũng Tàu", "Nha Trang", "Sapa", "Phú Quốc"]

# (mẫu, (min, max) số tiền) — slot: {m} tháng, {y} năm, {n} số đợt, {name}, {item}, {course}, {meal}, {thing}, {service}, {place}
TEMPLATES: list[tuple[str, tuple[int, int]]] = [
    ("tiền nhà tháng {m}", (1_500_000, 8_000_000)),
    ("chuyển tiền nhà T{m}", (1_500_000, 8_000_000)),
    ("tiền phòng trọ tháng {m}/{y}", (1_200_000, 4_000_000)),
    ("tiền hàng {item}", (200_000, 5_000_000)),
    ("thanh toán đơn {item}", (150_000, 3_000_000)),
    ("nhập hàng {item} đợt {n}", (500_000, 12_000_000)),
    ("trả tiền hàng cho {name}", (300_000, 6_000_000)),
    ("học phí {course} tháng {m}", (500_000, 3_000_000)),
    ("đóng học phí cho bé {name}", (800_000, 5_000_000)),
    ("chia tiền ăn {meal}", (100_000, 600_000)),
    ("tiền ăn {meal} hôm qua", (80_000, 500_000)),
    ("góp tiền {meal} nhóm", (100_000, 400_000)),
    ("trả nợ {name}", (200_000, 5_000_000)),
    ("trả {name} tiền mượn tháng trước", (300_000, 3_000_000)),
    ("gửi lại {name} tiền hôm trước", (100_000, 2_000_000)),
    ("mừng cưới {name}", (300_000, 2_000_000)),
    ("mừng sinh nhật {name}", (200_000, 1_000_000)),
    ("mừng tân gia anh {name}", (500_000, 2_000_000)),
    ("đặt cọc {thing}", (500_000, 10_000_000)),
    ("cọc tiền {thing}", (500_000, 10_000_000)),
    ("tiền điện tháng {m} gửi chủ nhà", (300_000, 1_500_000)),
    ("tiền nước tháng {m}", (100_000, 500_000)),
    ("tiền điện nước phòng {n}", (300_000, 1_200_000)),
    ("tiền {service} tháng {m}", (100_000, 600_000)),
    ("tiền sửa xe", (150_000, 2_000_000)),
    ("tiền xăng đi giao hàng", (100_000, 500_000)),
    ("gửi mẹ tiền chợ", (300_000, 3_000_000)),
    ("biếu bố mẹ tháng {m}", (1_000_000, 5_000_000)),
    ("chuyển tiền cho con đi học", (1_000_000, 6_000_000)),
    ("tiền thuốc cho {name}", (100_000, 1_500_000)),
    ("phí ship đơn hàng", (20_000, 100_000)),
    ("vé xe về quê", (200_000, 800_000)),
    ("đóng quỹ lớp", (100_000, 500_000)),
    ("tiền đi du lịch {place}", (1_000_000, 6_000_000)),
    ("lương tháng {m} cho {name}", (3_000_000, 9_000_000)),
    ("trả tiền đại lý {item}", (1_000_000, 15_000_000)),
    ("mua {item} online", (100_000, 2_000_000)),
    ("tiền công thợ sửa nhà", (500_000, 5_000_000)),
    ("tiền may đồng phục cho {name}", (200_000, 1_500_000)),
    ("góp vốn bán hàng với {name}", (2_000_000, 20_000_000)),
]
ABBREV = [("chuyển tiền", "ck"), ("tháng", "T"), ("thanh toán", "tt"), ("tiền", "tien")]

# Ca bẫy viết tay (bắt buộc nhóm "thuê", vì sau bỏ dấu "thuế" = "thuê"). is_verified_biller=True: kênh chính thức.
TRAPS: list[tuple[str, int, bool]] = [
    ("trả tiền thuê nhà tháng 12", 4_500_000, False),
    ("tiền thuê mặt bằng tháng 11", 6_000_000, False),
    ("tiền thuê xe du lịch", 2_500_000, False),
    ("phí gia hạn hợp đồng thuê", 1_000_000, False),
    ("tiền thuê phòng trọ quý 4", 7_500_000, False),
    ("thuê kho chứa hàng tháng 12", 3_000_000, False),
    ("tiền thuê đất trồng rau", 2_000_000, False),
    ("thue nha T12", 4_000_000, False),
    ("nộp hộ thuế môn bài cho chị Mai", 1_000_000, False),
    ("phí dịch vụ kế toán hộ kinh doanh", 800_000, False),
    ("phí làm báo cáo thuế cho cửa hàng", 1_200_000, False),
    ("hoàn tiền đơn hàng lỗi", 350_000, False),
    ("cập nhật phần mềm bán hàng", 900_000, False),
    ("phí gia hạn phần mềm quản lý cửa hàng", 1_500_000, False),
    ("phí công chứng hợp đồng", 500_000, False),
    ("tiền in hóa đơn cho cửa hàng", 400_000, False),
    ("đóng học phí lớp kế toán thuế", 2_000_000, False),
    ("phí duy trì website bán hàng", 1_000_000, False),
    ("tiền làm hồ sơ vay vốn ngân hàng", 500_000, False),
    ("phí đăng ký mã vạch sản phẩm", 1_200_000, False),
    ("xác nhận đơn hàng sỉ đợt 2", 5_000_000, False),
    ("phí kích hoạt sim mới", 250_000, False),
    ("nộp thuế môn bài quý 4", 300_000, True),
    ("nộp thuế thu nhập cá nhân năm 2026", 2_000_000, True),
    ("thanh toán tiền điện tháng 11", 650_000, True),
]


def _fill(tpl: str, rng: random.Random) -> str:
    return tpl.format(
        m=rng.randint(1, 12), y=rng.choice([2025, 2026]), n=rng.randint(1, 9), name=rng.choice(NAMES),
        item=rng.choice(ITEMS), course=rng.choice(COURSES), meal=rng.choice(MEALS), thing=rng.choice(THINGS),
        service=rng.choice(SERVICES), place=rng.choice(PLACES),
    )


def _style(text: str, rng: random.Random) -> str:
    r = rng.random()
    if r < 0.4:
        return text                                  # có dấu
    plain = norm(text)
    if r < 0.8:
        return plain                                 # không dấu, chữ thường
    out = text                                       # viết tắt kiểu người dùng
    for full, short in ABBREV:
        if full in out and rng.random() < 0.7:
            out = out.replace(full, short, 1)
    return norm(out) if rng.random() < 0.5 else out


def _amount(lo: int, hi: int, rng: random.Random) -> int:
    step = 10_000 if hi <= 1_000_000 else 50_000
    return rng.randrange(lo // step, hi // step + 1) * step


def generate() -> list[dict]:
    rng = random.Random(SEED)
    seen: set[str] = set()
    samples: list[dict] = []
    for note, amount, biller in TRAPS:
        seen.add(norm_match(note))
        samples.append({"transfer_note": note, "amount_vnd": amount, "is_verified_biller": biller, "source": "trap"})
    template_count, attempts = 0, 0
    while template_count < N_TEMPLATE:
        attempts += 1
        if attempts > 50_000:
            raise RuntimeError("không sinh đủ mẫu không trùng")
        tpl, (lo, hi) = TEMPLATES[attempts % len(TEMPLATES)]     # xoay vòng để các nhóm cân bằng
        note = _style(_fill(tpl, rng), rng)
        key = norm_match(note)
        if key in seen or len(note) > 60:
            continue
        seen.add(key)
        samples.append({"transfer_note": note, "amount_vnd": _amount(lo, hi, rng), "is_verified_biller": False,
                        "source": "template"})
        template_count += 1
    return samples


def main() -> int:
    samples = generate()
    traps = sum(s["source"] == "trap" for s in samples)
    payload = {
        "version": 1,
        "note": "Sinh bởi bench/gen_benign.py (seed cố định). Không sửa tay; sửa generator rồi chạy lại.",
        "counts": {"template": len(samples) - traps, "trap": traps},
        "samples": samples,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"ghi {OUT.relative_to(_common.ROOT)}: {len(samples) - traps} template + {traps} bẫy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
