# NSQ platform API. Build context is the REPO ROOT (see docker-compose.yml)
# so the image carries core/ (domain code) and redis-loader/ (the scripts the
# admin job runner executes) without vendored copies.
FROM python:3.11-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ core/
COPY redis-loader/ redis-loader/
COPY backend/app/ backend/app/

ENV CORE_DIR=/app/core \
    LOADER_DIR=/app/redis-loader \
    DATA_DIR=/app/data \
    NSQ_SNAPSHOT=/app/data/nsq_snapshot.json.gz \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fs http://localhost:8001/api/health || exit 1
# One worker on purpose: the job runner tracks running jobs in-process.
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers", "--forwarded-allow-ips", "*"]
