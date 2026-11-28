# Một image: build frontend (nếu có) → python runtime phục vụ API + SPA tĩnh (SPEC §14.3, D1)

FROM node:20-slim AS fe
WORKDIR /src
COPY . .
# Chưa có frontend/ thì vẫn build được image (chỉ có API + /docs)
RUN if [ -f frontend/package.json ]; then \
      cd frontend && npm ci && npm run build && mkdir -p /out && cp -r dist/. /out/; \
    else \
      mkdir -p /out; \
    fi

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/data ./data
COPY --from=fe /out ./static
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips="*"
