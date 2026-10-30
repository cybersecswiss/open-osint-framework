#!/bin/bash
# Runs inside postgres container at first init.
# Injects passwords from env vars into init-db.sql via psql -v.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
     -v KEYCLOAK_PW="${POSTGRES_KEYCLOAK_PASSWORD}" \
     -v N8N_PW="${POSTGRES_N8N_PASSWORD}" \
     -v LICENSE_PW="${POSTGRES_LICENSE_PASSWORD}" \
     --username "${POSTGRES_USER}" \
     --dbname "${POSTGRES_DB}" \
     -f /opt/oof-init/init-db.sql
