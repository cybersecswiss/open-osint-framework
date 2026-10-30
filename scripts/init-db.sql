-- ====================================================================
-- Initial database setup for the framework's PostgreSQL instance.
-- Runs on first start of the postgres container.
-- Passwords are injected via psql -v at runtime by init-databases.sh.
-- ====================================================================

CREATE DATABASE keycloak;
CREATE DATABASE n8n;
CREATE DATABASE license;

CREATE USER keycloak     WITH PASSWORD :'KEYCLOAK_PW';
CREATE USER n8n          WITH PASSWORD :'N8N_PW';
CREATE USER license_user WITH PASSWORD :'LICENSE_PW';

GRANT ALL PRIVILEGES ON DATABASE keycloak TO keycloak;
GRANT ALL PRIVILEGES ON DATABASE n8n      TO n8n;
GRANT ALL PRIVILEGES ON DATABASE license  TO license_user;

-- Postgres 15+ requires explicit grant on the public schema
\connect keycloak
GRANT ALL ON SCHEMA public TO keycloak;
\connect n8n
GRANT ALL ON SCHEMA public TO n8n;
\connect license
GRANT ALL ON SCHEMA public TO license_user;
