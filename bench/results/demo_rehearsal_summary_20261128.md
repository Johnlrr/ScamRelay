# Tập dượt kịch bản demo trên server local, 28/11 (bao)

`bench/demo_rehearsal.py`, LLM và embedding thật (`gemini-3.5-flash-lite`), server local, SQLite.
Mỗi lượt biên dịch lại luật bằng LLM nên anchor khác nhau giữa các lượt.

| Lượt | Code regression | Khớp nhầm lần 1 | Sau khi xóa anchor được chỉ ra | Chú Hùng bị hỏi sau Approve |
|---|---|---|---|---|
| `1007Z` | cũ (chỉ anchor cao nhất, xóa 2 vòng) | 1/265 | 0/265, biến thể 5/6 | **không** |
| `1012Z` (2 lượt cùng phút, file giữ lượt sau) | mới (mọi anchor vượt ngưỡng, 1 vòng) | 2/265 → 1/265 | 0/265, biến thể 6/6 | có, có |
| `1013Z` | mới | 1/265 | 0/265, biến thể 5/6 | có |
| `1015Z` | mới | 5/265 | 0/265, biến thể 5/6 | **không** |

**Chú Hùng bị hỏi sau khi chuyên viên xóa hết anchor gây nhầm: 3/5 lượt.**
Các bước khác (khoanh vùng cô Lan, hóa đơn điện, lộ OTP, baseline lọt, khóa Approve, mua hàng, biller) PASS ở mọi lượt.

So sánh offline trên 9 luật HKD dev (cùng quy trình xóa, embedding thật): câu demo vẫn khớp 9/9 sau khi xóa.

**Nguyên nhân:** LLM hay sinh vài anchor chung chung ("thanh toan phi ho so thue", "phi xac minh ho kinh doanh").
Chúng vừa khớp mẫu sạch (vd. "phí dịch vụ kế toán hộ kinh doanh"), vừa là anchor giúp câu demo vượt 0,90.
Xóa chúng thì hết khớp nhầm nhưng có thể mất luôn câu demo.

**Hệ quả cho video và giám khảo tự thử:** xem phần "Cần quyết định" trong báo cáo của bao (28/11).
Lượt chọn mục đích lành ra `HOLD_15M` thay vì `ALLOW_WITH_WARNING` là đúng thiết kế: chú Hùng chuyển ≥ 3 lần
trong 10 phút nên lớp đối tác `WARN` (INV-13).
