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

## Khi Gemini lỗi (`105012Z`, `105019Z`)

Chạy `REHEARSAL_LLM_DOWN=1`: kỳ vọng analyze dự phòng bằng từ khóa (`degraded=true`) và compile dùng output thật đã lưu (`CACHED_FALLBACK`).

| Lượt | Server | Kết quả | Ghi chú |
|---|---|---|---|
| `105012Z` | không có key Gemini | **17/17 bước PASS** | analyze 0,0 giây; `/healthz` báo `gemini_configured=false` |
| `105019Z` | key hỏng (Gemini trả lỗi thật) | **17/17 bước PASS** | analyze 0,5 giây, compile 0,3 giây; `/healthz` vẫn báo `gemini_configured=true` vì chỉ kiểm có key |

- Cả hai lượt giống hệt luồng chính: khoanh vùng, khóa cứng khi lộ OTP, regression bắt "phí dịch vụ kế toán hộ kinh doanh",
  chuyên viên thêm loại trừ "dich vu ke toan" → 0/265, chú Hùng bị hỏi và dừng với 0đ rời ví.
  Lý do: câu demo, tập sạch và anchor của output dự phòng đều có vector tính sẵn trong `embeddings_seed.npz`, nên không cần gọi embedding.
- Trên đồng hồ, phần "AI" chỉ còn 0,1–0,3 giây vì không gọi LLM. **Video quay ở chế độ này thì không được nói là AI vừa biên dịch live.**
- **Câu mới, chưa có vector, khi embedding lỗi** (thử thêm 2 câu qua `evaluate-transfer`, cùng server key hỏng): trả lời 0,1 giây,
  không lỗi 500, nhưng luật không khớp qua trigram ở câu "nop le phi xac nhan ho so thue ca the gap" (không bật câu hỏi).
  Giao dịch vẫn bị giữ `HOLD_15M` nhờ mức sàn đối tác (ví vừa chuyển dồn dập sau lượt tập dượt). Đúng thiết kế đã ghi ở SPEC:
  khi embedding lỗi thì trigram yếu hơn cosine. Response chưa có trường `degraded` (việc của linh).
- Log server của cả ba lượt không chứa key.
- 429 / hết quota không giả lập được qua mạng thật; đường này có test đơn vị (`tests/test_keyring.py`, `test_ai.py`): ném ngay, không retry, chuyển dự phòng.
