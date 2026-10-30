FROM python:3.12-slim

WORKDIR /app

# subfinder Go binary + system whois fallback for the python-whois lib
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates dnsutils unzip whois \
    && rm -rf /var/lib/apt/lists/* \
    && SUBFINDER_VERSION=2.6.6 \
    && curl -fsSL "https://github.com/projectdiscovery/subfinder/releases/download/v${SUBFINDER_VERSION}/subfinder_${SUBFINDER_VERSION}_linux_amd64.zip" -o /tmp/sf.zip \
    && unzip /tmp/sf.zip -d /usr/local/bin/ subfinder \
    && rm /tmp/sf.zip \
    && chmod +x /usr/local/bin/subfinder \
    && /usr/local/bin/subfinder -version

# theHarvester lives in its OWN venv — it pins its own fastapi/uvicorn/
# playwright which would otherwise clash with this module's app deps.
# We only put its CLI on PATH and call it as a subprocess.
# NOTE: the PyPI name `theHarvester` is a dead 0.0.1 placeholder — the
# real project is only released on GitHub. Pin a release tarball
# (no git needed) so builds are reproducible.
ARG THEHARVESTER_VERSION=4.11.1
RUN python -m venv /opt/theharvester \
    && /opt/theharvester/bin/pip install --no-cache-dir \
        "https://github.com/laramies/theHarvester/archive/refs/tags/${THEHARVESTER_VERSION}.tar.gz" \
    && ln -s /opt/theharvester/bin/theHarvester /usr/local/bin/theHarvester \
    && test -x /opt/theharvester/bin/theHarvester

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schemas.py .
COPY safe_fetch.py .
COPY main.py .
COPY tools ./tools

EXPOSE 8030

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -fsS http://localhost:8030/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8030"]
