# ---------------------------------------------------------------------------
# Imagem da aplicação Nova Agenda 2027 (FastAPI + Uvicorn), executada sem root
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Sao_Paulo \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /srv
COPY requirements.txt requirements-dev.txt ./
ARG INSTALAR_TESTES=0
RUN pip install -r requirements.txt \
 && if [ "$INSTALAR_TESTES" = "1" ]; then pip install -r requirements-dev.txt; fi

COPY app ./app
COPY tests ./tests

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/saude', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header", "--timeout-graceful-shutdown", "20"]
