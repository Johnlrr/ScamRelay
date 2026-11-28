# Tập dượt kịch bản demo (20261128T103639Z)

Server: local. Kết quả: **17/17 bước PASS**. LLM thật của server.

| Bước | Kết quả | Chi tiết |
|---|---|---|
| Lan · analyze | PASS | mode=MANIPULATION, 3 việc, FAKE_HKD_TAX_VERIFICATION, đòi 1800000, degraded=False, 1.7s |
| Lan · thông báo trên ví | PASS | Người thân đã yêu cầu tạm giữ bảo vệ các khoản chuyển tới người lạ trên ví của bạn lúc 17: |
| Lan · khoản 1,8tr bị giữ | PASS | FINAL HOLD_UNTIL_VERIFIED ['PARTNER_ALLOW', 'CONTAINMENT_MANIPULATION'] |
| Lan · hóa đơn điện 400k vẫn qua | PASS | FINAL ALLOW |
| Lan · 'Mẹ lỡ đọc OTP' → khóa cứng | PASS | mode=COMPROMISE, OTP=YES, 1.7s |
| Lan · hóa đơn điện giờ bị chặn | PASS | BLOCK |
| Hùng trước luật · baseline lọt | PASS | ScamRelay=ALLOW, baseline=ALLOW (risk 30) |
| FraudOps · compile | PASS | stage=SHADOW_LOG, source=LLM, degraded=False, 3.6s, validator errors=[] |
| FraudOps · regression lần 1 | PASS | khớp nhầm 1/265, biến thể 5/6, anchor gây nhầm {'phi xac minh ho kinh doanh': 1}, mẫu sạch ['phí dịch vụ kế toán hộ kinh doanh']; Approve → APPROVE_LOCKED |
| FraudOps · Approve bị khóa | PASS | APPROVE_LOCKED |
| FraudOps · chuyên viên sửa luật, chạy lại | PASS | 1 vòng: +loại trừ 'dich vu ke toan'; v2: khớp nhầm 0/265, biến thể 5/6 |
| FraudOps · Approve ASK_ONLY | PASS | AI 4.0s · con người 0.1s · báo cáo→hiệu lực 6.9s |
| Hùng sau luật · bị hỏi mục đích | PASS | CHALLENGE_JIT, câu hỏi: Bạn chuyển khoản này cho mục đích gì? |
| Hùng · chọn mục đích khớp thủ đoạn → dừng, 0đ rời ví | PASS | STOP_AND_EXPLAIN, số dư 6,800,000 → 6,800,000; giải thích: Cảnh giác: Cơ quan nhà nước không thu phí xác minh qua tài khoản cá nhân. Đây có |
| Hùng · mua hàng thật vẫn qua | PASS | FINAL ALLOW |
| Hùng · nộp thuế thật qua biller không bị hỏi | PASS | FINAL ALLOW |
| Biến thể · chọn mục đích lành → qua kèm cảnh báo (hoặc mức sàn đối tác) | PASS | HOLD_15M ['PARTNER_WARN', 'ANSWER_BENIGN', 'STAGE_ASK_ONLY'] |
