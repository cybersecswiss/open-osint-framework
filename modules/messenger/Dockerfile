FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schemas.py .
COPY main.py .
COPY tools ./tools
# Baked-in default crime-channel list (fallback for fresh installs). In
# compose this dir is bind-mounted so operators can edit it live.
COPY config ./config

# Media downloaded by the optional Telethon path lands here (mounted as
# a named volume in compose so ZIPs survive a container restart until
# the analyst downloads them).
RUN mkdir -p /data/telegram
ENV TELEGRAM_MEDIA_DIR=/data/telegram

EXPOSE 8070

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -fsS http://localhost:8070/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8070"]
