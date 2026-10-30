FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The release this image IS (scripts/release.sh passes it). Reported by
# /health so the framework can tell the customer admin an update is due —
# version.json cannot, it is written after the image is built.
ARG AGENT_VERSION=""
ENV AGENT_VERSION=${AGENT_VERSION}

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD curl -fsS http://localhost:9000/health || exit 1

# Schema bootstrap before workers fork (same race fix as the framework backend)
CMD ["sh", "-c", "python -m app.bootstrap && exec uvicorn main:app --host 0.0.0.0 --port 9000"]
