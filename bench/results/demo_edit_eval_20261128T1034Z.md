# Cách sửa luật trong demo: thêm cụm loại trừ hay xóa câu mẫu (20261128T1034Z)

Offline, luật HKD đã biên dịch của tập dev (`bench/dev_compiled`), embedding thật, ngưỡng theo `config.py`.
Chuyên viên được mô phỏng bằng quy tắc tất định trong `bench/_expert.py` (không nhìn câu demo).

- Luật có khớp nhầm ở lần kiểm thử đầu: 7/9
- Câu demo khớp trước khi sửa: 9/9

| Cách sửa | Hết khớp nhầm | Câu demo của chú Hùng còn khớp |
|---|---|---|
| Thêm cụm loại trừ | 9/9 | 9/9 |
| Xóa câu mẫu được tô đậm | 8/9 | 8/9 |

| Ca | Khớp nhầm lần đầu | Loại trừ: thêm | còn nhầm / biến thể / Hùng | Xóa: bỏ | còn nhầm / biến thể / Hùng |
|---|---|---|---|---|---|
| D-01 | 1 (phí dịch vụ kế toán hộ kinh doanh) | +dich vu ke toan | 0 / 6/6 / True (0.943) | -phi xac minh thong tin ho kinh doanh | 0 / 6/6 / True (0.943) |
| D-02 | 0 () | - | 0 / 5/6 / True (0.911) | - | 0 / 5/6 / True (0.911) |
| D-03 | 1 (phí dịch vụ kế toán hộ kinh doanh) | +dich vu ke toan | 0 / 5/6 / True (0.947) | -phi xac minh thue ho kinh doanh, -nop phi ho tro ho kinh doanh | 0 / 5/6 / True (0.932) |
| D-04 | 3 (phí gia hạn hợp đồng thuê; đóng học phí lớp kế toán thuế; phí dịch vụ kế toán hộ kinh doanh) | +gia han hop dong, +hoc phi lop ke, +dich vu ke toan | 0 / 6/6 / True (0.927) | -phi xu ly ho so thue, -nop phi ho so thue | 0 / 6/6 / True (0.927) |
| D-07 | 1 (phí dịch vụ kế toán hộ kinh doanh) | +dich vu ke toan | 0 / 6/6 / True (0.927) | -phi xac minh ho kinh doanh, -phi kiem tra ho so kinh doanh, -phi ho tro dang ky ho kinh doanh, -chi phi xac thuc thue ho kinh doanh | None / None / None (None) |
| D-08 | 4 (phí dịch vụ kế toán hộ kinh doanh; thanh toan don trung; thanh toán đơn bia) | +dich vu ke toan, +toan don trung, +toan don bia, -thanh toan tien xac nhan thue | 0 / 6/6 / True (0.947) | -phi xac minh thue ho kinh doanh, -thanh toan tien xac nhan thue, -phi tham dinh ho so thue hkd | 0 / 6/6 / True (0.924) |
| D-09 | 1 (phí dịch vụ kế toán hộ kinh doanh) | +dich vu ke toan | 0 / 6/6 / True (0.926) | -phi xac minh ho kinh doanh, -phi cap nhat ho so ho kinh doanh, -chi phi xac minh thue ho kinh doanh | 0 / 6/6 / True (0.919) |
| D-10 | 0 () | - | 0 / 6/6 / True (0.914) | - | 0 / 6/6 / True (0.914) |
| D-12 | 3 (đóng học phí lớp kế toán thuế; phí công chứng hợp đồng; phí dịch vụ kế toán hộ kinh doanh) | +hoc phi lop ke, +cong chung hop, +dich vu ke toan | 0 / 5/6 / True (0.951) | -phi cap nhat thue ho kinh doanh, -nop phi ho so thue, -phi ho so thue | 0 / 4/6 / True (0.951) |
