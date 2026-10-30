# Thin wrapper over the official n8n image: auto-imports + activates the
# bundled workflows on start (see entrypoint.sh). Building FROM :latest means
# the updater sidecar's `docker compose build --pull n8n` still gets the
# newest upstream n8n.
FROM n8nio/n8n:latest
USER root
COPY entrypoint.sh /entrypoint-autoimport.sh
RUN chmod +x /entrypoint-autoimport.sh
USER node
ENTRYPOINT ["tini", "--", "/entrypoint-autoimport.sh"]
