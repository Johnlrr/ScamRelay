# Nháp số liệu cho slide (bao, 28/11)

**Số chính trên slide phải lấy từ lượt held-out chính thức sau freeze (01/12, PLAN §9).**
Các số dưới đây đo trên **tập dev**, là tập đã dùng để chỉnh prompt và ngưỡng, nên chỉ được đưa vào phụ lục
với nhãn "dev (đã dùng để hiệu chỉnh)". Mọi số ghi dạng x/n và lấy nguyên từ file trong `bench/results/`.

## 1. Bench dev đầu-cuối (`run_bench.py --auto`, server local, LLM thật)

| Chỉ số | `0521Z` | `0526Z` | `0826Z` | `1019Z` (code mới nhất) |
|---|---|---|---|---|
| Unsafe Allow — ScamRelay | 2/10 | 3/10 | 2/10 | 2/10 |
| Unsafe Allow — baseline hành vi | 7/10 | 7/10 | 7/10 | 7/10 |
| Legitimate Allow | 10/11 | 10/11 | 10/11 | 10/11 |
| Friction (giao dịch sạch bị hỏi) | 0/11 | 0/11 | 0/11 | 0/11 |
| Variant Trigger | 8/9 | 7/9 | 8/9 | 8/9 |
| COACHED được dừng | 1/2 | 1/2 | 1/2 | 1/2 |
| EMPTY_NOTE được dừng | 0/1 | 0/1 | 0/1 | 0/1 |
| `ai_seconds` P50 / P95 (n=12) | 4,55 / 5,75 | 6,94 / 11,18 | 5,29 / 5,5 | 5,39 / 8,69 |

Cách viết gợi ý: "Trên tập dev, ScamRelay để lọt 2/10 giao dịch lừa (3/10 ở một lượt), baseline lọt 7/10."
Không gộp 4 lượt thành một con số trung bình đẹp hơn.

**Giao dịch hợp lệ còn bị dừng (1/11):** D-06-2. Ví đang bị khoanh vùng sau khi lộ OTP, nên mọi giao dịch đi đều bị chặn. Đây là chặn đúng thiết kế, không phải báo nhầm của luật.

**Giới hạn đã biết** (nói rõ trên slide):
- COACHED D-07-1: nạn nhân bị dặn chọn "mua hàng", nên giao dịch qua với `ALLOW_WITH_WARNING`.
- COACHED D-08-1: bị giữ `HOLD_15M` nhờ mức sàn của lớp đối tác.
- EMPTY_NOTE D-09-1: nội dung chuyển khoản trống, nên luật không có tín hiệu.

## 2. Ngưỡng SEMANTIC_MATCH (`calibration_20261128T0933Z.md`)

| Ngưỡng | Biến thể dev bật câu hỏi | Cặp luật × mẫu sạch khớp nhầm |
|---|---|---|
| 0,88 | 8/9 | 51/3.191 |
| **0,90 (chọn)** | **8/9** | **14/3.191** |
| 0,92 | 7/9 | 1/3.191 |
| 0,93 | 6/9 | 0/3.191 |

Câu demo "xac thuc ho so cap nhat thue HKD" vượt 0,90 ở 9/9 luật HKD dev (cosine 0,911–0,951).

## 3. Thời gian và độ bền

- Độ trễ LLM (`latency_20261128T0044Z.md`):
  - analyze: P50 1,32 giây, P95 1,48 giây (12/12 thành công).
  - compile: P50 2,90 giây, P95 3,29 giây (12/12).
- Dự phòng bằng từ khóa khi LLM lỗi (`fallback_eval_20261128T0042Z.md`):
  - Đúng họ thủ đoạn 12/12, đúng chế độ 12/12, 0 lần kết luận "an toàn".
  - File có ghi chú vì sao số này lạc quan.
- Đồng hồ 2 mốc trong các lượt tập dượt demo (`demo_rehearsal_*`):
  - AI biên dịch và kiểm thử: 4–7 giây.
  - Từ báo cáo tới khi luật có hiệu lực: 7–9 giây.
  - Thời gian con người xem xét gần 0 vì script tự bấm. Trên video là thời gian thật của chuyên viên.

## 4. Tập dượt kịch bản demo (`demo_rehearsal_summary_20261128.md`)

- Sau khi chuyên viên xóa hết anchor gây khớp nhầm, chú Hùng vẫn bị hỏi ở **3/5 lượt live**. Trên 9 luật dev chạy offline thì 9/9.
- Các bước còn lại PASS ở mọi lượt.

## 5. Nguồn bên ngoài đã đọc bản gốc

Xem ABOUT Phụ lục B (cập nhật 28/11). Tóm tắt các số có thể đưa lên slide:

| Số | Nguồn | Ghi chú khi dùng |
|---|---|---|
| Thiệt hại do lừa đảo tại Việt Nam ước tính 391,8 nghìn tỷ đồng (16,23 tỷ USD), 3,6% GDP | [GASA, State of Scams in Vietnam 2023](https://gasa.org/knowledge-base/reports/state-of-scams-in-vietnam-report-2023), ngày 06/12/2023 | Ghi "ước tính, khảo sát 1.063 người, GASA × Chongluadao, 2023". Các tỷ lệ khác (% mất tiền, % lấy lại được) chỉ có trong bản đầy đủ dành cho hội viên, chưa đọc được nên **không dùng** |
| MoMo phát hiện khoảng 29.000 giao dịch bất thường mỗi ngày, AI chấm điểm rủi ro theo thời gian thực, phối hợp với A05 Bộ Công an | [MoMo, 09/07/2026](https://www.momo.vn/tin-tuc/thong-bao/momo-va-bo-cong-an-dong-hop-tac-day-lui-lua-dao-8893) | MoMo tự công bố, có chữ "khoảng" |
