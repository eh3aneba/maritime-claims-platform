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

# The early collision check is user feedback, NOT an overwrite guarantee.
# Publish with atomic same-filesystem hard links below: unlike mv, ln refuses
# an existing destination even if it appeared after the initial check.
for target in "$OUT" "$SHA_FILE" "$META_FILE"; do
  if [[ -e "$target" || -L "$target" ]]; then
    echo "Refusing to overwrite an existing backup artifact." >&2
    exit 1
  fi
done

PARTIAL_DUMP=""
PARTIAL_SHA=""
PARTIAL_META=""
PUBLISHED_SHA=false
PUBLISHED_META=false
PUBLISHED_DUMP=false
cleanup_partials() {
  local status=$?
  # If the final dump is not published, remove ONLY sidecars we created
  # during this invocation; never delete raced-in unrelated files.
  if [[ "$PUBLISHED_DUMP" != "true" ]]; then
    if [[ "$PUBLISHED_SHA" == "true" ]]; then
      rm -f -- "$SHA_FILE"
    fi
    if [[ "$PUBLISHED_META" == "true" ]]; then
      rm -f -- "$META_FILE"
    fi
  fi
  for partial in "$PARTIAL_DUMP" "$PARTIAL_SHA" "$PARTIAL_META"; do
    if [[ -n "$partial" ]]; then
      rm -f -- "$partial"
    fi
  done
  exit "$status"
}
trap cleanup_partials EXIT

# mktemp uses exclusive creation and umask 077; predictable PID-based names
# could otherwise truncate somebody else's earlier interrupted backup.
PARTIAL_DUMP="$(mktemp "${OUT}.partial.XXXXXXXX")"
PARTIAL_SHA="$(mktemp "${SHA_FILE}.partial.XXXXXXXX")"
PARTIAL_META="$(mktemp "${META_FILE}.partial.XXXXXXXX")"

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

# Same-directory hard-link creation is atomic and refuses any destination
# that already exists (including a symlink or a file raced in during pg_dump).
# Publish dump LAST: it is the completion marker for the two sidecars.
ln -- "$PARTIAL_SHA" "$SHA_FILE"
PUBLISHED_SHA=true
ln -- "$PARTIAL_META" "$META_FILE"
PUBLISHED_META=true
ln -- "$PARTIAL_DUMP" "$OUT"
PUBLISHED_DUMP=true

# Remove exclusive temp links but keep all three finished artifacts.
rm -f -- "$PARTIAL_DUMP" "$PARTIAL_SHA" "$PARTIAL_META"
trap - EXIT

cat <<EOF
Backup complete and validated:
  dump: $OUT
  sha256: $SHA_FILE
  metadata: $META_FILE

This PostgreSQL artifact is not, by itself, a complete claim-file recovery point.
A matching Evidence/storage backup is still required before Pilot v1 recovery evidence is complete.
EOF
