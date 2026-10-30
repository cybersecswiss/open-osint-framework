FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schemas.py .
COPY verifier.py .
COPY main.py .
COPY tools ./tools

EXPOSE 8130

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -fsS http://localhost:8130/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8130"]
