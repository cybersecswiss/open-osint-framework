FROM python:3.12-slim-bookworm

WORKDIR /app

# Browsers in a fixed, world-readable path so the non-root user finds them.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

# Chromium keeps its sandbox only when it does not run as root.
RUN useradd -m -u 10001 capture
COPY safe_fetch.py main.py ./
USER capture

EXPOSE 8160

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD curl -fsS http://localhost:8160/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8160"]
