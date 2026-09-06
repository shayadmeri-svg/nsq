FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_main.py .
COPY shared/ shared/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# --root-path /engine: the gateway serves this API under /engine/ and strips
# the prefix, so FastAPI needs to be told about it to generate correct links
# and serve /engine/docs. Routes still resolve normally on :8000 directly.
ENTRYPOINT ["uvicorn", "api_main:app", "--host", "0.0.0.0", "--port", "8000", \
    "--root-path", "/engine"]
