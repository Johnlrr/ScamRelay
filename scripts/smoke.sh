#!/usr/bin/env bash
# Smoke test sau mỗi lần deploy (SPEC §14.4): đăng nhập smoke → healthz → analyze → compile → regression
# → approve (ghi đè nếu cần) → evaluate → submit → reset. Cần: curl, python3 (đọc JSON).
# Dùng: SMOKE_PASSWORD=... scripts/smoke.sh https://<url>
set -euo pipefail

BASE="${1:?Cần URL, ví dụ: scripts/smoke.sh https://scamrelay-xxx.a.run.app}"
USER_NAME="${SMOKE_USER:-smoke}"
PASS="${SMOKE_PASSWORD:?Đặt biến SMOKE_PASSWORD}"

j() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
# body gửi qua stdin (UTF-8) — tránh lỗi mã hóa tham số dòng lệnh trên Windows
post() { printf '%s' "$2" | curl -fsS -X POST "$BASE$1" -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" --data-binary @-; }

echo "1) healthz";      curl -fsS "$BASE/healthz"; echo
TOKEN=""
TOKEN="$(curl -fsS -X POST "$BASE/v1/auth/login" -H "Content-Type: application/json" \
  -d "{\"username\":\"$USER_NAME\",\"password\":\"$PASS\"}" | j 'd["access_token"]')"
echo "2) reset";        post /v1/demo/reset '{}' > /dev/null
echo "3) analyze"
INC="$(post /v1/incidents/analyze '{"text":"Cán bộ thuế bảo đóng 1,8 triệu phí xác minh hộ kinh doanh","is_proxy":true,"protect_wallet_id":"W-LAN","consent_handoff":true}' | j 'd["incident_id"]+" "+d["mode"]')"
echo "   $INC"; INC_ID="${INC%% *}"
echo "4) compile"
RULE="$(post /v1/fraudops/rules/compile "{\"incident_id\":\"$INC_ID\"}" | j 'd["rule_id"]+" "+d["stage"]+" "+str(d["source"])')"
echo "   $RULE"; RID="${RULE%% *}"
echo "5) regression"
post "/v1/fraudops/rules/$RID/regression-test" '{}' | j '"benign %s/%s, variants %s/%s" % (d["benign_flagged"], d["benign_checked"], d["variants_triggered"], d["variants_checked"])'
echo "6) approve ASK_ONLY (smoke ghi đè nếu có khớp nhầm)"
post "/v1/fraudops/rules/$RID/approve" '{"stage":"ASK_ONLY","ttl_hours":1,"override_reason":"smoke: ghi đè tự động sau deploy"}' | j 'd["clock"]'
echo "7) evaluate"
EV="$(post /v1/gateway/evaluate-transfer '{"wallet_id":"W-HUNG","to_account_id":"ACC-OLD-7731","amount_vnd":1200000,"transfer_note":"xac thuc ho so cap nhat thue HKD"}')"
STATUS="$(echo "$EV" | j 'd["status"]')"; echo "   $STATUS"
if [[ "$STATUS" == "CHALLENGE_JIT" ]]; then
  CH="$(echo "$EV" | j 'd["challenge"]["challenge_id"]')"
  OPT="$(echo "$EV" | j 'd["challenge"]["options"][-1]["id"]')"
  echo "8) submit (phương án cuối: Mục đích khác)"
  post /v1/gateway/submit-challenge "{\"challenge_id\":\"$CH\",\"option_id\":\"$OPT\"}" | j 'd["decision"]'
else
  echo "   CẢNH BÁO: câu demo không bật câu hỏi (kiểm tra ngưỡng/embedding)"; exit 1
fi
echo "9) reset";        post /v1/demo/reset '{}' > /dev/null
echo "SMOKE OK"
