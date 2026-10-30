FROM python:3.12-slim

WORKDIR /app

# build-essential + libffi: some holehe deps need to compile
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schemas.py .
COPY safe_fetch.py .
COPY main.py .
COPY tools ./tools

EXPOSE 8020

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -fsS http://localhost:8020/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8020"]
