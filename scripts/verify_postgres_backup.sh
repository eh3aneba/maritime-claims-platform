#!/usr/bin/env bash
set -euo pipefail

DUMP="${1:-}"
if [[ -z "$DUMP" || ! -f "$DUMP" ]]; then
  echo "Usage: $0 backups/file.dump" >&2
  exit 1
fi

SHA_FILE="${DUMP}.sha256"
META_FILE="${DUMP}.meta"
for required in "$SHA_FILE" "$META_FILE"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing backup integrity artifact: $required" >&2
    exit 1
  fi
done

DUMP_BASENAME="$(basename "$DUMP")"
read -r EXPECTED_SHA EXPECTED_NAME < "$SHA_FILE" || true
if [[ ! "${EXPECTED_SHA:-}" =~ ^[0-9a-fA-F]{64}$ ]]; then
  echo "Backup checksum sidecar contains an invalid SHA-256 digest." >&2
  exit 1
fi
if [[ "${EXPECTED_NAME:-}" != "$DUMP_BASENAME" ]]; then
  echo "Backup checksum sidecar is bound to a different dump filename." >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL_SHA="$(sha256sum "$DUMP" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  ACTUAL_SHA="$(shasum -a 256 "$DUMP" | awk '{print $1}')"
else
  echo "No SHA-256 tool available (sha256sum/shasum)." >&2
  exit 1
fi

if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]; then
  echo "Backup checksum mismatch." >&2
  exit 1
fi

meta_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "$META_FILE" | head -n 1
}

FORMAT="$(meta_value format)"
META_DUMP_FILE="$(meta_value dump_file)"
META_SHA="$(meta_value dump_sha256)"
ALEMBIC_HEADS="$(meta_value alembic_heads)"
META_DB="$(meta_value database)"

# Optional target-db binding, supplied by the destructive restore path.
# Standalone read-only archive verification does not require a live target.
if [[ -n "${MCRI_VERIFY_BACKUP_EXPECTED_DB:-}" && "$META_DB" != "$MCRI_VERIFY_BACKUP_EXPECTED_DB" ]]; then
  echo "Backup metadata database differs from the restore target." >&2
  exit 1
fi

if [[ "$FORMAT" != "mcri-postgres-backup-v1" ]]; then
  echo "Unsupported backup metadata format." >&2
  exit 1
fi
if [[ "$META_DUMP_FILE" != "$DUMP_BASENAME" ]]; then
  echo "Backup metadata is bound to a different dump filename." >&2
  exit 1
fi
if [[ "$META_SHA" != "$EXPECTED_SHA" ]]; then
  echo "Backup metadata digest does not match the checksum sidecar." >&2
  exit 1
fi
if [[ -z "$ALEMBIC_HEADS" ]]; then
  echo "Backup metadata does not contain an Alembic revision." >&2
  exit 1
fi

if ! docker compose exec -T db pg_restore --list < "$DUMP" >/dev/null; then
  echo "Backup archive structure validation failed." >&2
  exit 1
fi

cat <<EOF
Backup verification passed:
  dump: $DUMP
  sha256: $EXPECTED_SHA
  alembic_heads: $ALEMBIC_HEADS
EOF
