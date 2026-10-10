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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The pair is an artifact-integrity check, not a proof of a matching snapshot
# or completed restore. A private Pilot/production run must specify the pair
# explicitly to prevent accidentally restoring a DB without Evidence custody.
if [[ "${APP_ENV:-development}" == "pilot" || "${APP_ENV:-development}" == "production" ]]; then
  if [[ -z "${MCRI_RESTORE_PAIR_MANIFEST:-}" || -z "${MCRI_RESTORE_EVIDENCE_ARCHIVE:-}" || -z "${MCRI_RESTORE_RELEASE_SHA:-}" ]]; then
    echo "Refusing Pilot/production restore without DB/Evidence integrity pairing inputs." >&2
    exit 1
  fi
fi
if [[ -n "${MCRI_RESTORE_PAIR_MANIFEST:-}${MCRI_RESTORE_EVIDENCE_ARCHIVE:-}${MCRI_RESTORE_RELEASE_SHA:-}" ]]; then
  if [[ -z "${MCRI_RESTORE_PAIR_MANIFEST:-}" || -z "${MCRI_RESTORE_EVIDENCE_ARCHIVE:-}" || -z "${MCRI_RESTORE_RELEASE_SHA:-}" ]]; then
    echo "Incomplete DB/Evidence restore pairing inputs." >&2
    exit 1
  fi
fi

APPLICATION_SERVICES=(
  web
  api
  worker
  governance-webhook-worker
  external-evidence-scheduler-worker
  external-evidence-observation-worker
  external-evidence-review-projector-worker
  demo-seed
  preflight
  migrate
)

restore_exit() {
  local status=$?
  if (( status != 0 )); then
    echo "Restore failed. Application services remain stopped; investigate before restarting writers." >&2
  fi
  exit "$status"
}
trap restore_exit EXIT

echo "Entering restore maintenance window and stopping application services..."
docker compose stop "${APPLICATION_SERVICES[@]}"

mapfile -t running_services < <(docker compose ps --status running --services)
unexpected_services=()
db_running=false
for service in "${running_services[@]}"; do
  case "$service" in
    db)
      db_running=true
      ;;
    clamav)
      ;;
    *)
      unexpected_services+=("$service")
      ;;
  esac
done

if (( ${#unexpected_services[@]} > 0 )); then
  printf 'Refusing restore because unexpected Compose services are still running:' >&2
  printf ' %s' "${unexpected_services[@]}" >&2
  printf '\nUpdate the restore quiesce list before retrying.\n' >&2
  exit 1
fi

if [[ "$db_running" != "true" ]]; then
  echo "Starting PostgreSQL for restore..."
  docker compose up -d db
fi

echo "Waiting for PostgreSQL maintenance connection..."
ready=false
for _ in {1..30}; do
  if docker compose exec -T db pg_isready -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != "true" ]]; then
  echo "PostgreSQL did not become ready for restore." >&2
  exit 1
fi

# The database still exists here. Reject tampering, missing sidecars,
# mismatched target database and invalid pg_restore archive before ANY dropdb.
echo "Verifying PostgreSQL archive and metadata before destructive restore..."
MCRI_VERIFY_BACKUP_EXPECTED_DB="$POSTGRES_DB" \
  bash "$SCRIPT_DIR/verify_postgres_backup.sh" "$DUMP"

if [[ -n "${MCRI_RESTORE_PAIR_MANIFEST:-}" ]]; then
  echo "Verifying the bound Evidence archive against the backup record..."
  python "$SCRIPT_DIR/pilot_recovery_pair.py" verify \
    --db-dump "$DUMP" \
    --evidence-archive "$MCRI_RESTORE_EVIDENCE_ARCHIVE" \
    --release-sha "$MCRI_RESTORE_RELEASE_SHA" \
    --manifest "$MCRI_RESTORE_PAIR_MANIFEST"
fi

echo "Recreating database $POSTGRES_DB..."
docker compose exec -T db dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB"
docker compose exec -T db createdb -U "$POSTGRES_USER" "$POSTGRES_DB"

echo "Restoring $DUMP..."
cat "$DUMP" | docker compose exec -T db pg_restore \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --no-owner \
  --no-privileges

echo "Applying current migrations..."
docker compose run --rm migrate

echo "Running post-restore application preflight..."
docker compose run --rm preflight

trap - EXIT
cat <<'EOF'
Restore completed with application services still stopped.

Before reopening traffic:
  1. Confirm the expected Alembic/database revision and claim counts.
  2. Verify the evidence-file backup/volume matches the restored database.
  3. Check a known claim, evidence download, audit records, and assessment versions.
  4. Restart only after those checks pass: docker compose up -d
EOF
