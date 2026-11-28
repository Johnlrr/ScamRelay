# Tập dượt kịch bản demo (20261128T1007Z)

Server: local. Kết quả: **15/16 bước PASS**. LLM thật của server.

| Bước | Kết quả | Chi tiết |
|---|---|---|
| Lan · analyze | PASS | mode=MANIPULATION, 3 việc, FAKE_HKD_TAX_VERIFICATION, đòi 1800000, degraded=False, 6.5s |
| Lan · thông báo trên ví | PASS | Người thân đã yêu cầu tạm giữ bảo vệ các khoản chuyển tới người lạ trên ví của bạn lúc 17: |
| Lan · khoản 1,8tr bị giữ | PASS | FINAL HOLD_UNTIL_VERIFIED ['PARTNER_ALLOW', 'CONTAINMENT_MANIPULATION'] |
| Lan · hóa đơn điện 400k vẫn qua | PASS | FINAL ALLOW |
| Lan · 'Mẹ lỡ đọc OTP' → khóa cứng | PASS | mode=COMPROMISE, OTP=YES, 2.0s |
| Lan · hóa đơn điện giờ bị chặn | PASS | BLOCK |
| Hùng trước luật · baseline lọt | PASS | ScamRelay=ALLOW, baseline=ALLOW (risk 30) |
| FraudOps · compile | PASS | stage=SHADOW_LOG, source=LLM, degraded=False, 5.7s, validator errors=[] |
| FraudOps · regression lần 1 | PASS | khớp nhầm 1/265, biến thể 6/6, anchor gây nhầm {'phi xac minh ho kinh doanh': 1}; Approve → APPROVE_LOCKED |
| FraudOps · Approve bị khóa | PASS | APPROVE_LOCKED |
| FraudOps · xóa anchor gây nhầm, chạy lại | PASS | 2 vòng, xóa ['phi xac minh ho kinh doanh', 'le phi xac thuc thue ho kinh doanh']; v3: khớp nhầm 0/265, biến thể 5/6 |
| FraudOps · Approve ASK_ONLY | PASS | AI 6.2s · con người 0.2s · báo cáo→hiệu lực 8.6s |
| Hùng sau luật · bị hỏi mục đích | **FAIL** | FINAL, câu hỏi: - |
| Hùng · mua hàng thật vẫn qua | PASS | FINAL ALLOW |
| Hùng · nộp thuế thật qua biller không bị hỏi | PASS | FINAL HOLD_15M |
| Biến thể · chọn mục đích lành → qua kèm cảnh báo (hoặc mức sàn đối tác) | PASS | HOLD_15M ['PARTNER_WARN', 'ANSWER_BENIGN', 'STAGE_ASK_ONLY'] |
