# Docker CLI + compose plugin + python for the tiny HTTP trigger.
# Pinned by digest (docker:cli, client 29.9.2): this is the only container
# with the Docker socket, so its base image must not float.
FROM docker:cli@sha256:5e6baf67325a79f64ed3bed6863954d5e05d0f3d4e57cbdb14809346814bbfdb
RUN apk add --no-cache python3 docker-cli-compose
COPY updater.py /updater.py
EXPOSE 9999
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request;urllib.request.urlopen('http://localhost:9999/health')" || exit 1
CMD ["python3", "/updater.py"]
