FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schemas.py .
COPY main.py .
COPY tools ./tools
# Offline invariant suites — run with
#   docker compose exec -T module-corporate python test_<name>.py
# They are copied INTO the image on purpose, so the deployed artefact can be
# checked as it is, not only the working tree.
# One line per suite drifts: `lobbywatch`, `staatskalender` and `transport`
# were each written, run by hand, and then never copied in — so three suites
# were absent from the deployed artefact and only ever green in the working
# tree. A glob cannot forget the next one.

EXPOSE 8150

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -fsS http://localhost:8150/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8150"]
