# Tập dượt kịch bản demo (20261128T103820Z)

Server: local. Kết quả: **17/17 bước PASS**. LLM thật của server.

| Bước | Kết quả | Chi tiết |
|---|---|---|
| Lan · analyze | PASS | mode=MANIPULATION, 3 việc, FAKE_HKD_TAX_VERIFICATION, đòi 1800000, degraded=False, 1.8s |
| Lan · thông báo trên ví | PASS | Người thân đã yêu cầu tạm giữ bảo vệ các khoản chuyển tới người lạ trên ví của bạn lúc 17: |
| Lan · khoản 1,8tr bị giữ | PASS | FINAL HOLD_UNTIL_VERIFIED ['PARTNER_ALLOW', 'CONTAINMENT_MANIPULATION'] |
| Lan · hóa đơn điện 400k vẫn qua | PASS | FINAL ALLOW |
| Lan · 'Mẹ lỡ đọc OTP' → khóa cứng | PASS | mode=COMPROMISE, OTP=YES, 1.7s |
| Lan · hóa đơn điện giờ bị chặn | PASS | BLOCK |
| Hùng trước luật · baseline lọt | PASS | ScamRelay=ALLOW, baseline=ALLOW (risk 30) |
| FraudOps · compile | PASS | stage=SHADOW_LOG, source=LLM, degraded=False, 3.8s, validator errors=[] |
| FraudOps · regression lần 1 | PASS | khớp nhầm 3/265, biến thể 6/6, anchor gây nhầm {'phi ho so dang ky ho kinh doanh': 2, 'phi cap nhat thong tin thue': 1}, mẫu sạch ['phí dịch vụ kế toán hộ kinh doanh', 'phí gia hạn hợp đồng thuê', 'phí đăng ký mã vạch sản phẩm']; Approve → APPROVE_LOCKED |
| FraudOps · Approve bị khóa | PASS | APPROVE_LOCKED |
| FraudOps · chuyên viên sửa luật, chạy lại | PASS | 1 vòng: +loại trừ 'dich vu ke toan', +loại trừ 'gia han hop', +loại trừ 'ma vach san pham'; v2: khớp nhầm 0/265, biến thể 6/6 |
| FraudOps · Approve ASK_ONLY | PASS | AI 4.7s · con người 0.1s · báo cáo→hiệu lực 7.5s |
| Hùng sau luật · bị hỏi mục đích | PASS | CHALLENGE_JIT, câu hỏi: Bạn chuyển khoản số tiền này cho ai và với mục đích cụ thể nào? |
| Hùng · chọn mục đích khớp thủ đoạn → dừng, 0đ rời ví | PASS | STOP_AND_EXPLAIN, số dư 6,800,000 → 6,800,000; giải thích: Cơ quan thuế không yêu cầu chuyển tiền qua tài khoản cá nhân hay thu phí xác min |
| Hùng · mua hàng thật vẫn qua | PASS | FINAL ALLOW |
| Hùng · nộp thuế thật qua biller không bị hỏi | PASS | FINAL ALLOW |
| Biến thể · chọn mục đích lành → qua kèm cảnh báo (hoặc mức sàn đối tác) | PASS | HOLD_15M ['PARTNER_WARN', 'ANSWER_BENIGN', 'STAGE_ASK_ONLY'] |
