#!/bin/sh
set -e

# Run schema bootstrap once before workers fork. Avoids the race where
# multiple uvicorn workers each call create_all simultaneously. It also
# stamps the alembic baseline on a database that predates migrations.
python -m app.bootstrap

# Apply any migration newer than the stamped revision. A no-op on a
# database that is already at head (the normal case) — but it is what makes
# a schema change deployable to a customer install instead of needing
# hand-run SQL, which is what docs/operations.en.md had to prescribe until now.
# Not tolerant of failure on purpose: a half-migrated schema must not serve.
alembic upgrade head

exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
