FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias primeiro: a camada so e refeita quando o requirements.txt muda
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY scripts ./scripts

# UID/GID fixos (10001): sao os donos de ./data e ./.env no host
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /data /app/logs \
 && chown app:app /data /app/logs
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# UM unico processo (sem --workers): os schedulers do APScheduler rodam dentro do
# processo web e o SQLite nao tolera varios escritores.
# --forwarded-allow-ips=*: seguro porque a porta so e publicada em 127.0.0.1 no host
# (compose.yaml) e quem chega ate ela e o Nginx.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
