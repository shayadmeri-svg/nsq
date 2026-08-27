FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App entry points + tenant layer.
# App entry points + tenant + auth (sign-in gate) + diagnostics layer.
COPY app.py auth.py dashboard.py diagnostics.py diagnostics_core.py tenant_scope.py tenants.py ./
# Synced source-of-truth shared modules (see `just sync-shared`).
COPY shared/ shared/
# Figma-shaped UI layer (palette/icons/components/charts).
COPY ui/ ui/
# Neutral Figma-downloaded assets (logo, chevrons).
COPY static/ static/

EXPOSE 8503

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8503/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", \
    "--server.address=0.0.0.0", \
    "--server.port=8503", \
    "--server.headless=true"]