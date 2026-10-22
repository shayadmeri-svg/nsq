# Eurveda Connect: the integration service (plants, machines, agents, live state, alarms).
FROM python:3.12-slim
WORKDIR /svc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
RUN useradd -r svc && chown -R svc /svc
USER svc
ENV PYTHONUNBUFFERED=1
EXPOSE 8020
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8020/api/connect/health', timeout=4).status == 200 else 1)"
# One worker on purpose: the live state (latest readings, batch on each machine) is kept in process.
# On stop: finish requests in flight, close event streams after 15 s (browsers reconnect after 3 s).
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020", "--proxy-headers", "--forwarded-allow-ips", "*",
            "--timeout-graceful-shutdown", "15", "--timeout-keep-alive", "75"]
