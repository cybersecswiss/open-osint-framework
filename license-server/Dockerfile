FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD curl -fsS http://localhost:9000/health || exit 1

# Schema bootstrap once before workers fork (same race fix as the framework backend / data agent)
CMD ["sh", "-c", "python -m app.bootstrap && exec uvicorn main:app --host 0.0.0.0 --port 9000"]
