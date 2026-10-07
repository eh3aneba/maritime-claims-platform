#!/usr/bin/env bash
set -euo pipefail

umask 077

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-backups/mcri-${STAMP}.dump}"
POSTGRES_USER="${POSTGRES_USER:-maritime}"
POSTGRES_DB="${POSTGRES_DB:-maritime_claims}"

OUT_DIR="$(dirname "$OUT")"
mkdir -p "$OUT_DIR"

SHA_FILE="${OUT}.sha256"
META_FILE="${OUT}.meta"
PARTIAL_DUMP="${OUT}.partial.$$"
PARTIAL_SHA="${SHA_FILE}.partial.$$"
PARTIAL_META="${META_FILE}.partial.$$"

PUBLISH_STARTED=false

cleanup_partials() {
  rm -f "$PARTIAL_DUMP" "$PARTIAL_SHA" "$PARTIAL_META"
  if [[ "$PUBLISH_STARTED" == "true" && ! -e "$OUT" ]]; then
    rm -f "$SHA_FILE" "$META_FILE"
  fi
}
trap cleanup_partials EXIT

for target in "$OUT" "$SHA_FILE" "$META_FILE"; do
  if [[ -e "$target" ]]; then
    echo "Refusing to overwrite existing backup artifact: $target" >&2
    exit 1
  fi
done

read_alembic_heads() {
  docker compose exec -T db psql \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -At \
    -c 'SELECT version_num FROM alembic_version ORDER BY version_num;' \
    | paste -sd, -
}

ALEMBIC_HEADS_BEFORE="$(read_alembic_heads)"
if [[ -z "$ALEMBIC_HEADS_BEFORE" ]]; then
  echo "Could not determine Alembic revision before backup." >&2
  exit 1
fi

echo "Creating PostgreSQL custom-format backup: $OUT"
docker compose exec -T db pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -Fc > "$PARTIAL_DUMP"

if [[ ! -s "$PARTIAL_DUMP" ]]; then
  echo "Backup dump is empty; refusing publication." >&2
  exit 1
fi

echo "Validating PostgreSQL archive structure..."
if ! docker compose exec -T db pg_restore --list < "$PARTIAL_DUMP" >/dev/null; then
  echo "Backup archive validation failed; refusing publication." >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  DUMP_SHA256="$(sha256sum "$PARTIAL_DUMP" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  DUMP_SHA256="$(shasum -a 256 "$PARTIAL_DUMP" | awk '{print $1}')"
else
  echo "No SHA-256 tool available (sha256sum/shasum)." >&2
  exit 1
fi

if [[ ! "$DUMP_SHA256" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo "Backup SHA-256 calculation returned an invalid digest." >&2
  exit 1
fi

ALEMBIC_HEADS_AFTER="$(read_alembic_heads)"
if [[ -z "$ALEMBIC_HEADS_AFTER" ]]; then
  echo "Could not determine Alembic revision after backup." >&2
  exit 1
fi
if [[ "$ALEMBIC_HEADS_BEFORE" != "$ALEMBIC_HEADS_AFTER" ]]; then
  echo "Alembic revision changed during backup; refusing publication." >&2
  exit 1
fi

GIT_SHA="$(git rev-parse HEAD 2>/dev/null || true)"
if [[ ! "$GIT_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
  GIT_SHA="unknown"
fi

CREATED_AT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DUMP_BASENAME="$(basename "$OUT")"

printf '%s  %s\n' "$DUMP_SHA256" "$DUMP_BASENAME" > "$PARTIAL_SHA"
cat > "$PARTIAL_META" <<EOF
format=mcri-postgres-backup-v1
created_at_utc=$CREATED_AT_UTC
database=$POSTGRES_DB
git_sha=$GIT_SHA
alembic_heads=$ALEMBIC_HEADS_BEFORE
dump_file=$DUMP_BASENAME
dump_sha256=$DUMP_SHA256
EOF

PUBLISH_STARTED=true
mv "$PARTIAL_SHA" "$SHA_FILE"
mv "$PARTIAL_META" "$META_FILE"
mv "$PARTIAL_DUMP" "$OUT"

trap - EXIT

cat <<EOF
Backup complete and validated:
  dump: $OUT
  sha256: $SHA_FILE
  metadata: $META_FILE

This PostgreSQL artifact is not, by itself, a complete claim-file recovery point.
A matching Evidence/storage backup is still required before Pilot v1 recovery evidence is complete.
EOF
