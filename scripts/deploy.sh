#!/usr/bin/env bash
# Deploy lên Cloud Run (SPEC §14.4). Chỉ linh chạy, chỉ từ main, chạy tay.
# Cần trước: gcloud đã đăng nhập + chọn project; 4 secret trong Secret Manager:
#   gemini-api-key, database-url, jwt-secret, judge-accounts
set -euo pipefail

REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-scamrelay}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"     # 03/12 → 11/12: MIN_INSTANCES=1

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" != "main" ]]; then
  echo "Chỉ deploy từ main (đang ở '$branch')." >&2
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree chưa sạch; commit hoặc stash trước khi deploy." >&2
  exit 1
fi

echo "Deploy $(git rev-parse --short HEAD) → $SERVICE ($REGION), min-instances=$MIN_INSTANCES"
gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --max-instances=2 --min-instances="$MIN_INSTANCES" --memory=512Mi --cpu=1 --concurrency=40 --timeout=60 \
  --set-env-vars=LLM_MODEL=gemini-3.5-flash-lite,SEMANTIC_THRESHOLD=0.90,TRIGRAM_THRESHOLD=0.60 \
  --set-secrets=GEMINI_API_KEY=gemini-api-key:latest,DATABASE_URL=database-url:latest,JWT_SECRET=jwt-secret:latest,JUDGE_ACCOUNTS=judge-accounts:latest

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo "URL: $URL"
echo "Chạy smoke: SMOKE_PASSWORD=... scripts/smoke.sh $URL"
