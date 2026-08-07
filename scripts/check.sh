#!/usr/bin/env sh
set -eu

python -m compileall apps/api/app apps/api/alembic >/dev/null
(
  cd apps/api
  DATABASE_URL=sqlite+pysqlite:///:memory: PYTHONPATH=. pytest -q
  DATABASE_URL=postgresql://maritime:offline@localhost:5432/maritime_claims PYTHONPATH=. \
    alembic upgrade head --sql >/tmp/mcri_migration.sql
)

echo "Static checks, backend tests, document-processing tests, and offline PostgreSQL migration generation passed."
