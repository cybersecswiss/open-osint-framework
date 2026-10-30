FROM python:3.12-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only runtime code. The Telethon session, .env and test UI are
# NEVER baked into the image — the session is bind-mounted at runtime.
COPY schemas.py .
COPY labels.py .
COPY main.py .
COPY dispatch.py .
COPY scanner.py .
COPY forensics.py .
COPY operations ./operations
COPY extractors ./extractors

ENV PORT=8090
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=20s \
    CMD curl -fsS http://localhost:8090/health || exit 1

CMD ["python", "main.py"]
