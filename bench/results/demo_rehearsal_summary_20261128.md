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

## Sau khi chốt cách sửa mới: thêm cụm loại trừ (5 lượt, `103500Z`–`103820Z`)

Chuyên viên được mô phỏng bằng `bench/_expert.py`, chỉ nhìn ví dụ khớp nhầm, câu mẫu và biến thể; không nhìn câu demo.

| Lượt | Khớp nhầm lần 1 | Chuyên viên thêm | Sau khi sửa | Chú Hùng bị hỏi |
|---|---|---|---|---|
| `103500Z` | 1/265 (phí dịch vụ kế toán hộ kinh doanh) | loại trừ "dich vu ke toan" | 0/265, biến thể 6/6 | có |
| `103549Z` | 1/265 (phí dịch vụ kế toán hộ kinh doanh) | loại trừ "dich vu ke toan" | 0/265, biến thể 5/6 | có |
| `103639Z` | 1/265 (phí dịch vụ kế toán hộ kinh doanh) | loại trừ "dich vu ke toan" | 0/265, biến thể 5/6 | có |
| `103729Z` | 1/265 (đóng học phí lớp kế toán thuế) | loại trừ "hoc phi lop ke" | 0/265, biến thể 6/6 | có |
| `103820Z` | 3/265 (kế toán, gia hạn hợp đồng thuê, mã vạch sản phẩm) | 3 cụm loại trừ | 0/265, biến thể 6/6 | có |

**Chú Hùng bị hỏi sau khi sửa: 5/5 lượt** (so với 3/5 khi xóa câu mẫu). Mọi bước khác PASS ở cả 5 lượt.
Offline trên 9 luật HKD dev (`demo_edit_eval_20261128T1034Z.md`): thêm loại trừ cho câu demo khớp 9/9, xóa câu mẫu 8/9.
Lượt chọn mục đích lành ra `HOLD_15M` thay vì `ALLOW_WITH_WARNING` là đúng thiết kế: chú Hùng chuyển ≥ 3 lần
trong 10 phút nên lớp đối tác `WARN` (INV-13).
