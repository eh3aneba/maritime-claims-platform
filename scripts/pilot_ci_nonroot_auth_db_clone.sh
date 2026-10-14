#!/usr/bin/env bash
# CI-only: auth smoke on a NEW database in the ephemeral synthetic Postgres engine.
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = "true" ] && [ -n "${RUNNER_TEMP:-}" ] && [ -f .env.performance ] || exit 2
set -a
source .env.performance
set +a
[ "${APP_ENV:-}" = test ] &&
[ "${MCRI_SYNTHETIC_ONLY_CONFIRM:-}" = YES ] &&
[ "${POSTGRES_DB:-}" = mcri_performance ] &&
[ "${POSTGRES_USER:-}" = mcri_performance ] &&
[ "${AI_PROVIDER:-}" = disabled ] &&
[ "${MCRI_DEMO_ORG_SLUG:-}" = pilot ] &&
[ "${MCRI_DEMO_EMAIL:-}" = manager@demo.mcri.app ] &&
[ "${#MCRI_DEMO_PASSWORD}" -ge 12 ] || exit 2

compose() { docker compose --env-file .env.performance "$@"; }
dump="$(mktemp "$RUNNER_TEMP/mcri-db-copy.XXXXXXXX")"
scratch="$(mktemp -d "$RUNNER_TEMP/mcri-auth-scratch.XXXXXXXX")"
chmod 0600 "$dump"
sudo chown 1000:1000 "$scratch"
sudo chmod 0700 "$scratch"
clone="mcri_ci_auth_$(openssl rand -hex 8)"
[[ "$clone" =~ ^mcri_ci_auth_[0-9a-f]{16}$ ]] || exit 2
created=0
cleanup() {
  outcome=$?
  trap - EXIT
  if [ "$created" = 1 ]; then
    if ! compose exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
      -c "DROP DATABASE \"$clone\" WITH (FORCE);" >/dev/null 2>&1; then
      echo "::error::Disposable authentication database cleanup failed"
      outcome=1
    fi
  fi
  sudo rm -rf -- "$scratch"
  rm -f -- "$dump"
  exit "$outcome"
}
trap cleanup EXIT
exists="$(compose exec -T db psql -U "$POSTGRES_USER" -d postgres -At \
  -c "SELECT 1 FROM pg_database WHERE datname='$clone';")"
[ -z "$exists" ] || exit 2
before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM auth_sessions;')"
source_documents_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM documents;')"
source_jobs_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM document_processing_jobs;')"
[[ "$before" =~ ^[0-9]+$ ]] && [[ "$source_documents_before" =~ ^[0-9]+$ ]] && \
[[ "$source_jobs_before" =~ ^[0-9]+$ ]] || exit 2
compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --format=custom --no-owner --no-privileges > "$dump"
[ -s "$dump" ] || exit 2
compose exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE \"$clone\" OWNER \"$POSTGRES_USER\";" >/dev/null
created=1
compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$clone" \
  --no-owner --no-privileges --exit-on-error < "$dump"
for name in "$POSTGRES_DB" "$clone"; do
  count="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$name" -At \
    -c "SELECT COUNT(*) FROM claims WHERE external_reference='MCRI-DEMO-MT-ORION';")"
  [ "$count" = 1 ] || exit 2
done
clone_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM auth_sessions;')"
clone_documents_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM documents;')"
clone_jobs_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM document_processing_jobs;')"
[[ "$clone_before" =~ ^[0-9]+$ ]] && [[ "$clone_documents_before" =~ ^[0-9]+$ ]] && \
[[ "$clone_jobs_before" =~ ^[0-9]+$ ]] || exit 2
clone_url="${DATABASE_URL%/*}/$clone"
compose -f docker-compose.yml -f docker-compose.ci-nonroot-custody.yml \
  run --rm --no-deps -T --user 1000:1000 \
  -v "$scratch:/mnt/mcri-ci-auth-probe:rw" \
  -e "DATABASE_URL=$clone_url" -e "MCRI_CI_AUTH_DB_NAME=$clone" \
  -e MCRI_DEMO_ORG_SLUG -e MCRI_DEMO_EMAIL -e MCRI_DEMO_PASSWORD \
  -e MCRI_SYNTHETIC_ONLY_CONFIRM=YES api python - <<'PY'
import hashlib, json, os, stat, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from app.db.session import create_session
from app.modules.documents.models import (
    Document, DocumentMalwareScanStatus, QuarantinedUpload,
)
from app.modules.processing.models import (
    DocumentProcessingJob, ProcessingJobStatus,
)
from app.core.config import get_settings
from app.core.preflight import run_preflight

assert os.geteuid() == os.getegid() == 1000
proc = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
assert int(proc["CapEff"].strip(), 16) == 0 and proc["NoNewPrivs"].strip() == "1"
assert os.environ["APP_ENV"] == "test"
assert os.environ["MCRI_SYNTHETIC_ONLY_CONFIRM"] == "YES"
assert os.environ["AI_PROVIDER"] == "disabled"
assert os.environ["DATABASE_URL"].endswith("/" + os.environ["MCRI_CI_AUTH_DB_NAME"])
root = Path("/mnt/mcri-ci-auth-probe")
assert root.is_dir() and root.stat().st_uid == 1000
os.environ["LOCAL_STORAGE_PATH"] = str(root)
get_settings.cache_clear()
errors, _ = run_preflight(require_db=True)
assert not errors and not (root / ".mcri-write-probe").exists()
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app",
     "--host", "127.0.0.1", "--port", "18081", "--no-access-log"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
base = "http://127.0.0.1:18081/api/v1"
try:
    ready = False
    for _ in range(40):
        assert server.poll() is None, "non-root API exited"
        try:
            with urllib.request.urlopen(base + "/health/ready", timeout=2) as response:
                payload = json.load(response)
                ready = response.status == 200 and payload["dependencies"]["database"] == "ok"
            break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    assert ready, "isolated auth API failed readiness"
    login = urllib.request.Request(
        base + "/auth/login",
        data=json.dumps({
            "organization_slug": os.environ["MCRI_DEMO_ORG_SLUG"],
            "email": os.environ["MCRI_DEMO_EMAIL"],
            "password": os.environ["MCRI_DEMO_PASSWORD"],
        }).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(login, timeout=10) as response:
        assert response.status == 200
        token = json.load(response)["access_token"]
    assert isinstance(token, str) and len(token) >= 32
    claims_req = urllib.request.Request(
        base + "/claims?search=MCRI-DEMO-MT-ORION&limit=20",
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(claims_req, timeout=10) as response:
        assert response.status == 200
        claims = json.load(response)
    assert claims["total"] == 1 and len(claims["items"]) == 1
    documents_req = urllib.request.Request(
        base + "/claims/" + claims["items"][0]["id"] + "/documents",
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(documents_req, timeout=10) as response:
        assert response.status == 200
        documents = json.load(response)
    assert isinstance(documents["total"], int) and isinstance(documents["items"], list)
    # Authenticated real HTTP clean PDF upload: the entire admission,
    # ClamAV verdict and DB transaction target ONLY the disposable clone.
    # Derive distinct bytes from the exclusive clone ID, avoiding seeded
    # document hash collisions without printing any contents.
    clean_pdf = (b"%PDF-1.4\n% synthetic-noncustomer-" +
                 os.environ["MCRI_CI_AUTH_DB_NAME"].encode("ascii") +
                 b"\n%%EOF\n")
    digest = hashlib.sha256(clean_pdf).hexdigest()
    boundary = b"mcri-clean-ci-upload"
    form = (
        b"--" + boundary + b"\r\n"
        + b'Content-Disposition: form-data; name="file"; filename="ci-clean.pdf"\r\n'
        + b"Content-Type: application/pdf\r\n\r\n"
        + clean_pdf + b"\r\n--" + boundary + b"--\r\n"
    )
    upload_request = urllib.request.Request(
        base + "/claims/" + claims["items"][0]["id"] + "/documents",
        data=form, method="POST", headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "multipart/form-data; boundary=" + boundary.decode(),
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(upload_request, timeout=30) as response:
        assert response.status == 201, "clean synthetic upload not admitted"
        admitted = json.load(response)
    assert admitted["file_hash"] == digest
    assert admitted["file_size_bytes"] == len(clean_pdf)
    assert admitted["malware_scan_status"] == "clean"
    assert admitted["malware_scanned_at"]
    with create_session() as session:
        document = session.get(Document, UUID(admitted["id"]))
        assert document is not None and document.claim_id == UUID(claims["items"][0]["id"])
        assert document.file_hash == digest
        assert document.file_size_bytes == len(clean_pdf)
        assert document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
        assert not document.storage_key.startswith("_quarantine/")
        stored = root / document.storage_key
        assert stored.is_file() and stored.resolve().is_relative_to(root)
        assert hashlib.sha256(stored.read_bytes()).hexdigest() == digest
        assert stat.S_IMODE(stored.stat().st_mode) == 0o600
        assert session.scalar(select(DocumentProcessingJob).where(
            DocumentProcessingJob.document_id == document.id,
            DocumentProcessingJob.status == ProcessingJobStatus.PENDING,
        )) is not None
        assert session.scalar(select(QuarantinedUpload).where(
            QuarantinedUpload.claim_id == document.claim_id,
            QuarantinedUpload.file_hash == digest,
        )) is None
    downloaded_request = urllib.request.Request(
        base + "/claims/" + claims["items"][0]["id"] +
        "/documents/" + admitted["id"] + "/download",
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(downloaded_request, timeout=10) as response:
        assert response.status == 200
        assert response.read() == clean_pdf
    assert not list(root.rglob(".mcri-upload-*.partial"))
    # Clean only the new scratch Evidence, never seeded/customer files.
    assert [p for p in root.rglob("*") if p.is_file()] == [stored]
    stored.unlink()
    for directory in sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts), reverse=True,
    ):
        directory.rmdir()
    child = dict(
        line.split(":", 1) for line in Path(f"/proc/{server.pid}/status").read_text().splitlines()
        if ":" in line
    )
    assert child["Uid"].split() == ["1000"] * 4
    assert child["Gid"].split() == ["1000"] * 4
    assert int(child["CapEff"].strip(), 16) == 0
    assert child["NoNewPrivs"].strip() == "1"
finally:
    if server.poll() is None:
        server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)
assert not any(root.iterdir()), "authenticated read polluted synthetic scratch"
print("PASS: non-root API authenticated clean HTTP upload; live scanner CLEAN; cloned DB document and pending job matched.")
print("Not an OCR completion, independent PostgreSQL engine, production user change or Pilot GO.")
PY
clone_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM auth_sessions;')"
clone_documents_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM documents;')"
clone_jobs_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM document_processing_jobs;')"
[ "$clone_after" -gt "$clone_before" ] || exit 1
[ "$clone_documents_after" -eq "$((clone_documents_before + 1))" ] || exit 1
[ "$clone_jobs_after" -eq "$((clone_jobs_before + 1))" ] || exit 1
after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM auth_sessions;')"
source_documents_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM documents;')"
source_jobs_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM document_processing_jobs;')"
[ "$before" = "$after" ] && \
[ "$source_documents_before" = "$source_documents_after" ] && \
[ "$source_jobs_before" = "$source_jobs_after" ] || {
  echo "::error::Seeded synthetic source database was unexpectedly modified"
  exit 1
}
test -z "$(sudo find "$scratch" -mindepth 1 -print -quit)"
echo "PASS: authenticated clean scan/admission + pending job committed only to disposable synthetic DB; source unchanged."
