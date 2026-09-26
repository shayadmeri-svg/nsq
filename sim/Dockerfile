# PharmaPy sidecar. PharmaPy needs assimulo 3.4.3 (SUNDIALS) and numpy<2, so it
# lives apart from the API. assimulo is built from source against Debian's SUNDIALS 6.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gfortran git curl libsundials-dev liblapack-dev libblas-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "numpy<2" "scipy<1.14" "cython<3" "setuptools<60" wheel pandas matplotlib \
        fastapi==0.115.0 "uvicorn[standard]==0.30.6"
RUN git clone --depth 1 --branch Assimulo-3.4.3 https://github.com/modelon-community/Assimulo.git /tmp/assimulo \
    && cd /tmp/assimulo \
    && SETUPTOOLS_USE_DISTUTILS=stdlib python setup.py config_fc --f77flags="-fallow-argument-mismatch" \
         --f90flags="-fallow-argument-mismatch" install --sundials-home=/usr \
         --blas-home=/usr/lib/x86_64-linux-gnu --lapack-home=/usr/lib/x86_64-linux-gnu \
    && cd / && rm -rf /tmp/assimulo
# PharmaPy (Purdue, BSD-style licence), pinned
ARG PHARMAPY_REF=97303477da1756815a34e70b8c22dd7059fa73fa
RUN git clone https://github.com/CryPTSys/PharmaPy.git /opt/PharmaPy \
    && cd /opt/PharmaPy && git checkout ${PHARMAPY_REF} && pip install --no-cache-dir --no-deps -e .
WORKDIR /app
COPY sim/app.py .
ENV MPLBACKEND=Agg
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD curl -fs http://localhost:8010/health || exit 1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8010"]
