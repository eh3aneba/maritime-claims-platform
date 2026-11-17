#!/usr/bin/env bash
set -euo pipefail

DUMP="${1:-}"
if [[ -z "$DUMP" || ! -f "$DUMP" || -L "$DUMP" ]]; then
  echo "Usage: $0 backups/file.dump" >&2
  exit 1
fi

SHA_FILE="${DUMP}.sha256"
META_FILE="${DUMP}.meta"
for required in "$SHA_FILE" "$META_FILE"; do
  if [[ ! -f "$required" || -L "$required" ]]; then
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

# This verifier is used before a potentially destructive restore. Refuse
# ambiguous metadata instead of silently trusting the first duplicate key.
# The backup writer always emits exactly these seven fixed fields.
declare -A META_FIELDS=()
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" != *=* ]]; then
    echo "Malformed backup metadata field." >&2
    exit 1
  fi
  key="${line%%=*}"
  value="${line#*=}"
  case "$key" in
    format|created_at_utc|database|git_sha|alembic_heads|dump_file|dump_sha256) ;;
    *)
      echo "Unexpected backup metadata field." >&2
      exit 1
      ;;
  esac
  if [[ -v "META_FIELDS[$key]" ]]; then
    echo "Duplicate backup metadata field." >&2
    exit 1
  fi
  META_FIELDS["$key"]="$value"
done < "$META_FILE"
if [[ "${#META_FIELDS[@]}" -ne 7 ]]; then
  echo "Incomplete backup metadata record." >&2
  exit 1
fi

FORMAT="${META_FIELDS[format]}"
META_DUMP_FILE="${META_FIELDS[dump_file]}"
META_SHA="${META_FIELDS[dump_sha256]}"
ALEMBIC_HEADS="${META_FIELDS[alembic_heads]}"
META_DB="${META_FIELDS[database]}"

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
