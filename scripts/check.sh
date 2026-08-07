#!/usr/bin/env sh
set -eu

python -m compileall apps/api/app apps/api/alembic >/dev/null
(
  cd apps/api
  pytest -q
  alembic upgrade head --sql >/tmp/mcri_migration.sql
)

echo "Static checks, database metadata tests, and offline migration generation passed."
