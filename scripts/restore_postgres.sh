#!/usr/bin/env bash
set -euo pipefail
DUMP="${1:-}"
if [[ -z "$DUMP" || ! -f "$DUMP" ]]; then
  echo "Usage: MCRI_RESTORE_CONFIRM=YES $0 backups/file.dump" >&2
  exit 1
fi
if [[ "${MCRI_RESTORE_CONFIRM:-}" != "YES" ]]; then
  echo "Refusing destructive restore. Set MCRI_RESTORE_CONFIRM=YES after verifying the target environment." >&2
  exit 1
fi
POSTGRES_USER="${POSTGRES_USER:-maritime}"
POSTGRES_DB="${POSTGRES_DB:-maritime_claims}"
echo "Stopping application services before restore..."
docker compose stop api worker web || true
echo "Recreating database $POSTGRES_DB..."
docker compose exec -T db dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"
docker compose exec -T db createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
echo "Restoring $DUMP..."
cat "$DUMP" | docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges
echo "Applying current migrations..."
docker compose run --rm migrate
echo "Restore complete. Restart with: docker compose up -d"
