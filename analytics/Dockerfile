FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY shared/ shared/

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/analytics/_stcore/health || exit 1

# --server.baseUrlPath=analytics: the app is served under /analytics so the path is
# identical whether you hit the container directly
# (localhost:8501/analytics/) or go through the gateway (localhost/analytics/).
# Streamlit rewrites its own asset and websocket URLs from this, which is
# what makes sub-path proxying work at all.
# Launched through shared/streamlit_entry.py rather than the `streamlit`
# console script: it installs an asyncio exception handler that drops the
# WebSocketClosedError tracebacks Streamlit emits when a browser tab goes
# away mid-render (see the module docstring). All args pass through to the
# Streamlit CLI unchanged.
ENTRYPOINT ["python", "-u", "shared/streamlit_entry.py", "run", "app.py", \
    "--server.address=0.0.0.0", \
    "--server.port=8501", \
    "--server.headless=true", \
    "--server.baseUrlPath=analytics"]
