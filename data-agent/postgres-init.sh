#!/bin/bash
# Bootstraps the keycloak database + role inside the data-agent's
# Postgres on first init. Idempotent: re-running on an existing
# install is a no-op (the volume already has the role + db).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<EOSQL
    CREATE ROLE keycloak LOGIN PASSWORD '$POSTGRES_KEYCLOAK_PASSWORD';
    CREATE DATABASE keycloak OWNER keycloak;
    GRANT ALL PRIVILEGES ON DATABASE keycloak TO keycloak;
EOSQL
