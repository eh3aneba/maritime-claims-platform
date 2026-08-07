#!/usr/bin/env bash
set -euo pipefail
mkdir -p backups
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-backups/mcri-${STAMP}.dump}"
POSTGRES_USER="${POSTGRES_USER:-maritime}"
POSTGRES_DB="${POSTGRES_DB:-maritime_claims}"
echo "Creating PostgreSQL custom-format backup: $OUT"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$OUT"
test -s "$OUT"
echo "Backup complete: $OUT"
