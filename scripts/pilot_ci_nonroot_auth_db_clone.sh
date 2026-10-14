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
source_extractions_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM document_text_extractions;')"
source_segments_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM document_text_segments;')"
source_quarantine_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM quarantined_uploads;')"
[[ "$source_quarantine_before" =~ ^[0-9]+$ ]] || exit 2
[[ "$source_extractions_before" =~ ^[0-9]+$ ]] && [[ "$source_segments_before" =~ ^[0-9]+$ ]] && \
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
clone_extractions_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM document_text_extractions;')"
clone_segments_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM document_text_segments;')"
clone_quarantine_before="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM quarantined_uploads;')"
[[ "$clone_quarantine_before" =~ ^[0-9]+$ ]] || exit 2
[[ "$clone_extractions_before" =~ ^[0-9]+$ ]] && [[ "$clone_segments_before" =~ ^[0-9]+$ ]] && \
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
from io import BytesIO
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from uuid import UUID
from sqlalchemy import select
# Direct SQLAlchemy model lookups need the same complete model registry as
# Alembic/tests; otherwise Document's Organization relationship is unresolved.
from app.db import metadata as _all_model_metadata  # noqa: F401
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
    # The previous bytes were only a PDF signature, not a parseable document.
    # Create a real, one-page text PDF so the separate worker can perform
    # genuine native extraction without a mock or external fixture.
    verification_text = (
        "Synthetic marine claims evidence for isolated nonroot worker processing "
        + os.environ["MCRI_CI_AUTH_DB_NAME"]
    )
    assert verification_text.isascii()
    # Use large, centered, well-separated text lines. The former 14pt,
    # single-line fixture could run past the PDF crop boundary after
    # rasterization, producing a non-deterministic OCR acceptance result.
    marker_text = os.environ["MCRI_CI_AUTH_DB_NAME"].encode("ascii")
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): writer._add_object(font)
        }),
    })
    text_stream = DecodedStreamObject()
    text_stream.set_data(
        b"BT /F1 20 Tf 55 650 Td "
        b"(Synthetic marine claims evidence) Tj "
        b"0 -48 Td (nonroot worker processing) Tj "
        b"0 -48 Td (" + marker_text + b") Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(text_stream)
    output = BytesIO()
    writer.write(output)
    clean_pdf = output.getvalue()
    assert clean_pdf.startswith(b"%PDF-") and len(clean_pdf) < 8192
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
        pending_job = session.scalar(select(DocumentProcessingJob).where(
            DocumentProcessingJob.document_id == document.id,
            DocumentProcessingJob.status == ProcessingJobStatus.PENDING,
        ))
        assert pending_job is not None
        processing_id = str(pending_job.id)
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
    # Transfer only the synthetic document/job identifiers, not bearer tokens,
    # into a private one-shot marker shared with the separate real worker.
    assert [p for p in root.rglob("*") if p.is_file()] == [stored]
    target_marker = root / "ci-processing-target.json"
    with target_marker.open("x", encoding="utf-8") as file:
        json.dump({
            "document_id": admitted["id"],
            "job_id": processing_id,
            "claim_id": claims["items"][0]["id"],
            "file_hash": digest,
        }, file)
    target_marker.chmod(0o600)
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
assert (root / "ci-processing-target.json").is_file(), "synthetic worker handoff missing"
print("PASS: non-root API authenticated clean HTTP upload; live scanner CLEAN; pending job recorded for independent worker.")
print("Not proof of OCR completion, customer data or Pilot GO.")
PY

# The API does NOT delete the admitted synthetic PDF. The separate restricted
# OCR-capable worker must claim its exact new DB job and remove only scratch.
compose -f docker-compose.yml -f docker-compose.ci-nonroot-custody.yml \
  run --rm --no-deps -T --user 1000:1000 \
  -v "$scratch:/mnt/mcri-ci-auth-probe:rw" \
  -e "DATABASE_URL=$clone_url" -e LOCAL_STORAGE_PATH=/mnt/mcri-ci-auth-probe \
  -e "MCRI_CI_AUTH_DB_NAME=$clone" \
  -e MCRI_DEMO_ORG_SLUG -e MCRI_DEMO_EMAIL -e MCRI_DEMO_PASSWORD \
  -e OCR_ENABLED=true -e OCR_LANGUAGES=eng+fas \
  -e MCRI_SYNTHETIC_ONLY_CONFIRM=YES worker python - <<'PY'
import hashlib, json, os, re, stat, subprocess, sys, time, urllib.error, urllib.request
from io import BytesIO
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from app.db import metadata as _all_model_metadata  # noqa: F401
from app.db.session import create_session
from app.modules.processing.extractors import extract_document_text
from app.core.restore_pair_audit import (
    RestoreEvidenceRow, RestorePairAuditError, audit_restored_evidence_pair,
)
from dataclasses import replace
from app.modules.documents.models import (
    Document, DocumentMalwareScanStatus, DocumentProcessingStatus, QuarantinedUpload,
)
from app.modules.processing.models import (
    DocumentProcessingJob, DocumentTextExtraction, DocumentTextSegment,
    ProcessingJobStatus, ProcessingJobType,
)
from app.modules.processing.service import process_job
from app.modules.processing.lease_recovery import process_job_with_lease

assert os.geteuid() == os.getegid() == 1000
assert os.environ["APP_ENV"] == "test"
assert os.environ["AI_PROVIDER"] == "disabled"
assert os.environ["MCRI_SYNTHETIC_ONLY_CONFIRM"] == "YES"
assert os.environ["DATABASE_URL"].endswith("/" + os.environ["MCRI_CI_AUTH_DB_NAME"])
assert os.environ["OCR_ENABLED"].lower() == "true"
assert os.environ["OCR_LANGUAGES"] == "eng+fas"
proc = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
assert int(proc["CapEff"].strip(), 16) == 0 and proc["NoNewPrivs"].strip() == "1"
root = Path("/mnt/mcri-ci-auth-probe")
marker = root / "ci-processing-target.json"
assert marker.is_file() and stat.S_IMODE(marker.stat().st_mode) == 0o600
details = json.loads(marker.read_text(encoding="utf-8"))
assert set(details) == {"document_id", "job_id", "claim_id", "file_hash"}
doc_id, job_id = UUID(details["document_id"]), UUID(details["job_id"])
with create_session() as session:
    document = session.get(Document, doc_id)
    job = session.scalar(select(DocumentProcessingJob).where(
        DocumentProcessingJob.id == job_id,
        DocumentProcessingJob.document_id == doc_id,
    ).with_for_update(skip_locked=True))
    assert document is not None and job is not None
    assert document.claim_id == UUID(details["claim_id"])
    assert document.file_hash == details["file_hash"]
    assert job.status == ProcessingJobStatus.PENDING
    assert job.job_type == ProcessingJobType.EXTRACT_TEXT
    assert job.attempt_count == 0
    stored = root / document.storage_key
    assert stored.is_file() and stored.resolve().is_relative_to(root)
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == details["file_hash"]
    now = datetime.now(UTC)
    job.status = ProcessingJobStatus.RUNNING
    job.locked_at = now
    job.locked_by = "ci-disposable-nonroot-worker"
    job.started_at = now
    job.attempt_count += 1
    session.commit()
    session.refresh(job)
    assert process_job_with_lease(session, job=job, processor=process_job)
    session.expire_all()
    document = session.get(Document, doc_id)
    job = session.get(DocumentProcessingJob, job_id)
    assert job.status == ProcessingJobStatus.COMPLETED
    assert job.completed_at is not None and job.attempt_count == 1
    assert job.locked_at is None and job.locked_by is None
    assert document.processing_status == DocumentProcessingStatus.PROCESSED
    extraction = session.scalar(select(DocumentTextExtraction).where(
        DocumentTextExtraction.document_id == doc_id,
    ))
    assert extraction is not None and extraction.extraction_method == "pypdf"
    assert extraction.char_count >= 60 and extraction.segment_count == 1
    assert extraction.requires_ocr is False and extraction.text_hash is not None
    segment = session.scalar(select(DocumentTextSegment).where(
        DocumentTextSegment.document_id == doc_id,
        DocumentTextSegment.extraction_id == extraction.id,
    ))
    assert segment is not None and segment.locator_value == "1"
    assert "Synthetic marine claims evidence" in segment.text
    assert os.environ["MCRI_CI_AUTH_DB_NAME"] in segment.text
    assert segment.char_count == extraction.char_count
    assert job.result["method"] == "pypdf"
    assert job.result["segment_count"] == 1
    assert job.result["requires_ocr"] is False
    session.rollback()

# Real scanned-PDF OCR proof on a second **private ephemeral file**, no DB
# admission. Convert the already-admitted synthetic text PDF to a grayscale
# image and re-embed those pixels in a PDF with NO native text stream.
# This is not an OCR mock: it invokes actual Poppler and Tesseract eng+fas.
pgm_prefix = root / "ci-ocr-source"
pgm_path = pgm_prefix.with_suffix(".pgm")
scanned_pdf = root / "ci-scanned-only.pdf"
result = subprocess.run(
    ["pdftoppm", "-f", "1", "-l", "1", "-singlefile",
     "-r", "200", "-gray", str(stored), str(pgm_prefix)],
    capture_output=True, timeout=35, check=False,
)
assert result.returncode == 0 and pgm_path.is_file(), "scanner rasterization unavailable"
raster = pgm_path.read_bytes()
header = re.match(rb"P5\s+(\d+)\s+(\d+)\s+(\d+)\s", raster)
assert header is not None, "scanner raster has an unexpected PGM header"
width, height, max_value = map(int, header.groups())
assert 1000 <= width <= 2500 and 1000 <= height <= 3500 and max_value == 255
pixels = raster[header.end():]
assert len(pixels) == width * height and len(pixels) < 9_000_000
source_ink = sum(pixel < 180 for pixel in pixels)
assert source_ink > 3000, "NO-GO synthetic source page is blank"
# Before checking the PDF wrapper, prove the actual pinned ENG+FAS OCR
# engine can recognize this input raster. Never log document bytes/text.
ocr_source = subprocess.run(
    ["tesseract", str(pgm_path), "stdout", "-l", "eng+fas"],
    capture_output=True, text=True, timeout=45, check=False,
)
assert ocr_source.returncode == 0, "NO-GO source-raster Tesseract exited nonzero"
if "synthetic marine claims evidence" not in ocr_source.stdout.casefold():
    raise AssertionError(
        "NO-GO source-raster OCR did not read the synthetic phrase "
        f"(pixels={len(pixels)}, ink={source_ink}, chars={len(ocr_source.stdout)})"
    )
writer = PdfWriter()
page = writer.add_blank_page(width=612, height=792)
image = DecodedStreamObject()
image.set_data(pixels)
image = image.flate_encode()
image.update(DictionaryObject({
    NameObject("/Type"): NameObject("/XObject"),
    NameObject("/Subtype"): NameObject("/Image"),
    NameObject("/Width"): NumberObject(width),
    NameObject("/Height"): NumberObject(height),
    NameObject("/ColorSpace"): NameObject("/DeviceGray"),
    NameObject("/BitsPerComponent"): NumberObject(8),
}))
page[NameObject("/Resources")] = DictionaryObject({
    NameObject("/XObject"): DictionaryObject({
        NameObject("/Im1"): writer._add_object(image),
    }),
})
stream = DecodedStreamObject()
stream.set_data(b"q 612 0 0 792 0 0 cm /Im1 Do Q")
page[NameObject("/Contents")] = writer._add_object(stream)
with scanned_pdf.open("xb") as output:
    writer.write(output)
assert scanned_pdf.stat().st_size < 1_000_000
# Verify the image survived PDF re-embedding, not just that a pypdf
# Image XObject was present. In particular catch an empty/inverted/
# invisible PDF image before blaming the OCR engine or its language data.
roundtrip_prefix = root / "ci-scanned-roundtrip"
roundtrip_pgm = roundtrip_prefix.with_suffix(".pgm")
raster_check = subprocess.run(
    ["pdftoppm", "-f", "1", "-l", "1", "-singlefile",
     "-r", "200", "-gray", str(scanned_pdf), str(roundtrip_prefix)],
    capture_output=True, timeout=35, check=False,
)
assert raster_check.returncode == 0 and roundtrip_pgm.is_file(), (
    "NO-GO scanned PDF cannot render as a raster"
)
roundtrip = roundtrip_pgm.read_bytes()
rt_header = re.match(rb"P5\s+(\d+)\s+(\d+)\s+(\d+)\s", roundtrip)
assert rt_header is not None and tuple(map(int, rt_header.groups())) == (
    width, height, 255,
), "NO-GO scanned PDF rendered unexpected dimensions"
rt_pixels = roundtrip[rt_header.end():]
assert len(rt_pixels) == len(pixels), "NO-GO scanned PDF raster byte length changed"
roundtrip_ink = sum(pixel < 180 for pixel in rt_pixels)
if roundtrip_ink < 3000:
    raise AssertionError(
        "NO-GO scanned PDF image content did not survive round-trip "
        f"(source_ink={source_ink}, roundtrip_ink={roundtrip_ink})"
    )
native = extract_document_text(scanned_pdf, enable_ocr=False)
assert native.method == "pypdf" and native.requires_ocr
assert len(native.segments) == 1 and not native.combined_text.strip()
recovered = extract_document_text(
    scanned_pdf, enable_ocr=True, ocr_languages="eng+fas",
    ocr_max_pages=1, ocr_timeout_seconds=90,
)
assert recovered.method == "pypdf+selective-tesseract:eng+fas"
if recovered.requires_ocr or len(recovered.segments) != 1:
    # Only synthetic test data is involved; print bounded, diagnosis-only
    # outcome metadata instead of raw OCR text, image bytes or credentials.
    raise AssertionError(
        "NO-GO synthetic scanned PDF OCR unresolved "
        f"(segments={len(recovered.segments)}, chars={len(recovered.combined_text)}, "
        f"warnings={'; '.join(w[:150] for w in recovered.warnings[:3])})"
    )
assert recovered.text_hash is not None
assert recovered.segments[0].locator_type == "page"
assert recovered.segments[0].locator_value == "1"
assert "synthetic marine claims evidence" in recovered.combined_text.casefold()
assert "nonroot worker processing" in recovered.combined_text.casefold()
assert any("recovered 1" in warning for warning in recovered.warnings)
# Authenticated HTTP admission of the REAL scanned-only PDF. This starts
# a separate restricted Uvicorn process inside the disposable worker
# container, pointed to the same exclusive PostgreSQL clone and scratch.
# Its only write is a new synthetic scanned Document, security verdict and
# pending processing job. The original synthetic source DB is never used.
base = "http://127.0.0.1:18082/api/v1"
api = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app",
     "--host", "127.0.0.1", "--port", "18082", "--no-access-log"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
try:
    ready = False
    for _ in range(40):
        assert api.poll() is None, "NO-GO isolated scanned-PDF HTTP API stopped"
        try:
            with urllib.request.urlopen(base + "/health/ready", timeout=2) as response:
                ready = response.status == 200 and json.load(response)["dependencies"]["database"] == "ok"
            break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    assert ready, "NO-GO isolated scanned-PDF API unavailable"
    request = urllib.request.Request(
        base + "/auth/login",
        data=json.dumps({
            "organization_slug": os.environ["MCRI_DEMO_ORG_SLUG"],
            "email": os.environ["MCRI_DEMO_EMAIL"],
            "password": os.environ["MCRI_DEMO_PASSWORD"],
        }).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
        token = json.load(response)["access_token"]
    assert isinstance(token, str) and len(token) >= 32
    scan_blob = scanned_pdf.read_bytes()
    scan_hash = hashlib.sha256(scan_blob).hexdigest()
    assert scan_hash != details["file_hash"]
    boundary = b"mcri-scanned-ci-upload"
    body = (
        b"--" + boundary + b"\r\n"
        + b'Content-Disposition: form-data; name="file"; filename="ci-scanned-only.pdf"\r\n'
        + b"Content-Type: application/pdf\r\n\r\n"
        + scan_blob + b"\r\n--" + boundary + b"--\r\n"
    )
    request = urllib.request.Request(
        base + "/claims/" + details["claim_id"] + "/documents",
        data=body, method="POST", headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "multipart/form-data; boundary=" + boundary.decode(),
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 201, "NO-GO scanned image-only PDF was not admitted"
        admitted_scan = json.load(response)
    assert admitted_scan["id"] != details["document_id"]
    assert admitted_scan["file_hash"] == scan_hash
    assert admitted_scan["file_size_bytes"] == len(scan_blob)
    assert admitted_scan["malware_scan_status"] == "clean"
    assert admitted_scan["malware_scanned_at"]
    request = urllib.request.Request(
        base + "/claims/" + details["claim_id"] +
        "/documents/" + admitted_scan["id"] + "/download",
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        assert response.status == 200 and response.read() == scan_blob
finally:
    if api.poll() is None:
        api.terminate()
    try:
        api.wait(timeout=5)
    except subprocess.TimeoutExpired:
        api.kill()
        api.wait(timeout=5)

scanned_id = UUID(admitted_scan["id"])
with create_session() as session:
    scanned_document = session.get(Document, scanned_id)
    assert scanned_document is not None
    assert scanned_document.claim_id == UUID(details["claim_id"])
    assert scanned_document.organization_id == session.get(Document, doc_id).organization_id
    assert scanned_document.file_hash == scan_hash
    assert scanned_document.malware_scan_status == DocumentMalwareScanStatus.CLEAN
    scanned_storage = root / scanned_document.storage_key
    assert scanned_storage.is_file() and scanned_storage.resolve().is_relative_to(root)
    assert stat.S_IMODE(scanned_storage.stat().st_mode) == 0o600
    assert hashlib.sha256(scanned_storage.read_bytes()).hexdigest() == scan_hash
    assert session.scalar(select(QuarantinedUpload).where(
        QuarantinedUpload.claim_id == scanned_document.claim_id,
        QuarantinedUpload.file_hash == scan_hash,
    )) is None
    scanned_job = session.scalar(select(DocumentProcessingJob).where(
        DocumentProcessingJob.document_id == scanned_id,
        DocumentProcessingJob.status == ProcessingJobStatus.PENDING,
        DocumentProcessingJob.job_type == ProcessingJobType.EXTRACT_TEXT,
    ).with_for_update(skip_locked=True))
    assert scanned_job is not None and scanned_job.attempt_count == 0
    # Claim only this exact newly uploaded scanned Document's job, not a
    # seeded/unrelated queue entry. Use the actual lease-fenced processor.
    started = datetime.now(UTC)
    scanned_job.status = ProcessingJobStatus.RUNNING
    scanned_job.locked_at = started
    scanned_job.locked_by = "ci-disposable-scanned-ocr-worker"
    scanned_job.started_at = started
    scanned_job.attempt_count += 1
    session.commit()
    session.refresh(scanned_job)
    assert process_job_with_lease(session, job=scanned_job, processor=process_job)
    session.expire_all()
    scanned_document = session.get(Document, scanned_id)
    scanned_job = session.get(DocumentProcessingJob, scanned_job.id)
    assert scanned_job.status == ProcessingJobStatus.COMPLETED
    assert scanned_job.attempt_count == 1 and scanned_job.completed_at is not None
    assert scanned_job.locked_by is None and scanned_job.locked_at is None
    assert scanned_document.processing_status == DocumentProcessingStatus.PROCESSED
    extraction_scan = session.scalar(select(DocumentTextExtraction).where(
        DocumentTextExtraction.document_id == scanned_id,
    ))
    assert extraction_scan is not None
    assert extraction_scan.extraction_method == "pypdf+selective-tesseract:eng+fas"
    assert extraction_scan.segment_count == 1 and extraction_scan.char_count >= 50
    assert extraction_scan.requires_ocr is False
    assert extraction_scan.text_hash is not None
    segment_scan = session.scalar(select(DocumentTextSegment).where(
        DocumentTextSegment.document_id == scanned_id,
        DocumentTextSegment.extraction_id == extraction_scan.id,
    ))
    assert segment_scan is not None and segment_scan.locator_type == "page"
    assert segment_scan.locator_value == "1"
    assert "synthetic marine claims evidence" in segment_scan.text.casefold()
    assert "nonroot worker processing" in segment_scan.text.casefold()
    assert segment_scan.char_count == extraction_scan.char_count
    assert scanned_job.result["method"] == extraction_scan.extraction_method
    assert scanned_job.result["requires_ocr"] is False

    # Read-only admission/restore-pair gate over the two real DB-linked
    # Evidence files while their bytes still exist in private CI scratch.
    # The negative case corrupts ONLY the in-memory expectation, never DB
    # rows or Evidence bytes. No host volume, object store or customer paths.
    native_db_row = session.get(Document, doc_id)
    assert native_db_row is not None
    assert native_db_row.claim_id == scanned_document.claim_id
    assert native_db_row.organization_id == scanned_document.organization_id
    rows = [
        RestoreEvidenceRow(
            kind="document", record_id=item.id,
            organization_id=item.organization_id, claim_id=item.claim_id,
            storage_key=item.storage_key, file_hash=item.file_hash,
            file_size_bytes=item.file_size_bytes,
            state=item.malware_scan_status.value,
        )
        for item in (native_db_row, scanned_document)
    ]
    assert audit_restored_evidence_pair(
        root, rows, organization_id=native_db_row.organization_id,
        claim_id=native_db_row.claim_id,
    ) == 2
    try:
        audit_restored_evidence_pair(
            root, [replace(rows[0], file_hash="0" * 64), rows[1]],
            organization_id=native_db_row.organization_id,
            claim_id=native_db_row.claim_id,
        )
        raise AssertionError("NO-GO: mismatched DB/Evidence digest was accepted")
    except RestorePairAuditError as exc:
        assert str(exc) == "digest_mismatch"
    session.rollback()

# Only remove newly owned scratch artifacts; never unmount or delete the
# shared Evidence volume nor modify original synthetic source records.
scanned_storage.unlink()
scanned_pdf.unlink()
pgm_path.unlink()
roundtrip_pgm.unlink()
stored.unlink()
marker.unlink()
for directory in sorted(
    (p for p in root.rglob("*") if p.is_dir()),
    key=lambda p: len(p.parts), reverse=True,
):
    directory.rmdir()
assert not any(root.iterdir()), "restricted worker left synthetic Evidence behind"
print("PASS: restricted real worker committed a fenced processing lease, native PDF text and matching extracted DB records.")
print("PASS: image-only scanned PDF authenticated HTTP admission, CLEAN ClamAV, fenced worker Tesseract OCR and committed matching DB extraction.")
print("No customer data, real-host Evidence migration, separate database engine or Pilot GO.")
PY

# Authentic infected and scanner-outage HTTP admission tests against the
# *same disposable DB clone*, from the real restricted UID1000 API image.
# No credentials or synthetic bytes are printed. This does not alter the
# ClamAV service itself or any customer Evidence volume.
compose -f docker-compose.yml -f docker-compose.ci-nonroot-custody.yml \
  run --rm --no-deps -T --user 1000:1000 \
  -v "$scratch:/mnt/mcri-ci-auth-probe:rw" \
  -e "DATABASE_URL=$clone_url" -e "MCRI_CI_AUTH_DB_NAME=$clone" \
  -e MCRI_DEMO_ORG_SLUG -e MCRI_DEMO_EMAIL -e MCRI_DEMO_PASSWORD \
  -e LOCAL_STORAGE_PATH=/mnt/mcri-ci-auth-probe \
  -e MCRI_SYNTHETIC_ONLY_CONFIRM=YES \
  -e MALWARE_SCAN_ENABLED=true -e CLAMAV_HOST=clamav -e CLAMAV_PORT=3310 \
  api python - <<'PY'
import hashlib, json, os, stat, subprocess, sys, time
import urllib.error, urllib.request
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile
from docx import Document as OfficeDocument
from sqlalchemy import select
from app.db import metadata as _all_model_metadata  # noqa: F401
from app.db.session import create_session
from app.modules.documents.malware import MalwareScanVerdict, scan_file
from app.core.restore_pair_audit import (
    RestoreEvidenceRow, RestorePairAuditError, audit_restored_evidence_pair,
)
from dataclasses import replace
from app.modules.documents.models import Document, QuarantinedUpload, QuarantineStatus
from app.core.config import get_settings
from app.modules.claims.models import Claim

assert os.geteuid() == os.getegid() == 1000
proc = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
assert int(proc["CapEff"].strip(), 16) == 0 and proc["NoNewPrivs"].strip() == "1"
assert os.environ["APP_ENV"] == "test"
assert os.environ["MCRI_SYNTHETIC_ONLY_CONFIRM"] == "YES"
assert os.environ["AI_PROVIDER"] == "disabled"
assert os.environ["DATABASE_URL"].endswith("/" + os.environ["MCRI_CI_AUTH_DB_NAME"])
assert os.environ["MALWARE_SCAN_ENABLED"].lower() == "true"
assert os.environ["CLAMAV_HOST"] == "clamav" and os.environ["CLAMAV_PORT"] == "3310"
root = Path("/mnt/mcri-ci-auth-probe")
assert root.is_dir() and root.stat().st_uid == 1000
assert not any(root.iterdir()), "previous synthetic scratch cleanup incomplete"
get_settings.cache_clear()

with create_session() as session:
    claim = session.scalar(select(Claim).where(
        Claim.external_reference == "MCRI-DEMO-MT-ORION"
    ))
    assert claim is not None
    claim_id = claim.id

def login(base):
    req = urllib.request.Request(
        base + "/auth/login", data=json.dumps({
            "organization_slug": os.environ["MCRI_DEMO_ORG_SLUG"],
            "email": os.environ["MCRI_DEMO_EMAIL"],
            "password": os.environ["MCRI_DEMO_PASSWORD"],
        }).encode(), method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        assert response.status == 200
        token = json.load(response)["access_token"]
    assert isinstance(token, str) and len(token) >= 32
    return token

def blocked_upload(base, token, filename, raw, status_code):
    boundary = b"mcri-quarantine-ci-boundary"
    assert filename.endswith((".pdf", ".docx"))
    mime = b"application/vnd.openxmlformats-officedocument.wordprocessingml.document" if filename.endswith(".docx") else b"application/pdf"
    multipart = (
        b"--" + boundary + b"\r\n"
        + b'Content-Disposition: form-data; name="file"; filename="' +
        filename.encode("ascii") + b'"\r\n'
        + b"Content-Type: " + mime + b"\r\n\r\n"
        + raw + b"\r\n--" + boundary + b"--\r\n"
    )
    req = urllib.request.Request(
        base + "/claims/" + str(claim_id) + "/documents",
        data=multipart, method="POST", headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "multipart/form-data; boundary=" + boundary.decode(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            raise AssertionError("NO-GO quarantined upload admitted as Document")
    except urllib.error.HTTPError as response:
        assert response.code == status_code, (
            f"NO-GO unexpected blocked upload HTTP status {response.code}"
        )
        detail = json.load(response)["detail"]
        assert "quarantined" in detail.casefold()
    return hashlib.sha256(raw).hexdigest()

def verify_quarantine(digest, raw, expected_status, token, base, filename):
    with create_session() as session:
        matches = list(session.scalars(select(QuarantinedUpload).where(
            QuarantinedUpload.claim_id == claim_id,
            QuarantinedUpload.file_hash == digest,
        )))
        assert len(matches) == 1, "NO-GO durable quarantine record absent or duplicated"
        record = matches[0]
        assert record.status == expected_status and record.scanned_at is not None
        assert record.file_size_bytes == len(raw)
        assert record.quarantine_key.startswith("_quarantine/")
        assert record.quarantine_key.endswith(Path(filename).suffix)
        assert session.scalar(select(Document).where(
            Document.claim_id == claim_id,
            Document.file_hash == digest,
        )) is None, "NO-GO quarantined bytes entered admitted Evidence"
        location = root / record.quarantine_key
        assert location.is_file() and location.resolve().is_relative_to(root)
        assert stat.S_IMODE(location.stat().st_mode) == 0o600
        assert hashlib.sha256(location.read_bytes()).hexdigest() == digest
        assert location.read_bytes() == raw
        if expected_status == QuarantineStatus.INFECTED:
            assert record.threat_name and not record.scan_error
        else:
            assert record.scan_error and not record.threat_name
        document_id = str(record.id)
    req = urllib.request.Request(
        base + "/claims/" + str(claim_id) +
        "/documents/" + document_id + "/download",
        headers={"Authorization": "Bearer " + token},
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            raise AssertionError("NO-GO blocked Evidence was downloadable")
    except urllib.error.HTTPError as response:
        assert response.code == 404, "NO-GO quarantined bytes leaked through document download"
    return location

@contextmanager
def isolated_api(port, scanner_port):
    env = dict(os.environ, CLAMAV_PORT=str(scanner_port))
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host",
         "127.0.0.1", "--port", str(port), "--no-access-log"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        ready = False
        for _ in range(40):
            assert server.poll() is None, "NO-GO restricted quarantine API exited"
            try:
                with urllib.request.urlopen(base + "/health/ready", timeout=2) as response:
                    ready = response.status == 200 and json.load(response)["dependencies"]["database"] == "ok"
                break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.5)
        assert ready, "NO-GO restricted quarantine API did not become ready"
        yield base, login(base)
    finally:
        if server.poll() is None:
            server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

# Harmless industry-standard EICAR test string, NOT real malware.
eicar = (b"X5O!P%@AP[4" + bytes([92]) +
         b"PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")
assert len(eicar) == 68
# The scanner did NOT flag EICAR when it was merely appended to arbitrary
# PDF-signature bytes. Use an actual DOCX (ZIP container) and store the
# harmless test signature as a separate uncompressed ZIP member instead:
# ClamAV can inspect the archive entry, and the HTTP API validates DOCX PK.
office = OfficeDocument()
office.add_paragraph("Synthetic ClamAV archive quarantine boundary check")
buffer = BytesIO()
office.save(buffer)
with ZipFile(buffer, "a") as archive:
    archive.writestr("ci-av-test/eicar-test.txt", eicar, compress_type=ZIP_STORED)
infected_docx = buffer.getvalue()
assert infected_docx.startswith(b"PK\x03\x04")
assert eicar in infected_docx and len(infected_docx) < 100000
with ZipFile(BytesIO(infected_docx), "r") as archive:
    assert archive.read("ci-av-test/eicar-test.txt") == eicar
preflight = root / "ci-eicar-preflight.docx"
with preflight.open("xb") as handle:
    handle.write(infected_docx)
preflight.chmod(0o600)
verdict = scan_file(preflight, host="clamav", port=3310, timeout_seconds=20)
assert verdict.verdict == MalwareScanVerdict.INFECTED, "NO-GO EICAR scan fixture not detected"
preflight.unlink()
with isolated_api(18084, scanner_port=3310) as (base, token):
    infected_hash = blocked_upload(base, token, "ci-eicar.docx", infected_docx, 422)
    infected_path = verify_quarantine(
        infected_hash, infected_docx, QuarantineStatus.INFECTED, token, base, "ci-eicar.docx"
    )

# The outage is scoped to this short-lived API process only. The synthetic
# scanner stays healthy for all other CI probes. Port 1 is deliberately
# unreachable; fail-closed response is HTTP 503 and durable SCAN_ERROR.
outage_pdf = (
    b"%PDF-1.4\n% synthetic scanner-unavailable admission " +
    os.environ["MCRI_CI_AUTH_DB_NAME"].encode("ascii") +
    b"\n%%EOF\n"
)
assert hashlib.sha256(outage_pdf).hexdigest() != infected_hash
with isolated_api(18085, scanner_port=1) as (base, token):
    outage_hash = blocked_upload(base, token, "ci-scan-unavailable.pdf", outage_pdf, 503)
    outage_path = verify_quarantine(
        outage_hash, outage_pdf, QuarantineStatus.SCAN_ERROR, token, base, "ci-scan-unavailable.pdf"
    )

# Read-only post-admission reconciliation of the two actual quarantine
# rows and private files. No destructive fault injection into the source DB.
with create_session() as session:
    selected = list(session.scalars(select(QuarantinedUpload).where(
        QuarantinedUpload.claim_id == claim_id,
        QuarantinedUpload.file_hash.in_([infected_hash, outage_hash]),
    )))
    assert len(selected) == 2
    rows = [
        RestoreEvidenceRow(
            kind="quarantine", record_id=item.id,
            organization_id=item.organization_id, claim_id=item.claim_id,
            storage_key=item.quarantine_key, file_hash=item.file_hash,
            file_size_bytes=item.file_size_bytes, state=item.status.value,
        )
        for item in selected
    ]
    assert audit_restored_evidence_pair(
        root, rows, organization_id=selected[0].organization_id,
        claim_id=claim_id,
    ) == 2
    try:
        audit_restored_evidence_pair(
            root, [replace(rows[0], claim_id=selected[0].organization_id), rows[1]],
            organization_id=selected[0].organization_id,
            claim_id=claim_id,
        )
        raise AssertionError("NO-GO: mismatched quarantine claim was accepted")
    except RestorePairAuditError as exc:
        assert str(exc) == "wrong_claim_lineage"
    session.rollback()

# Delete only two newly owned quarantine files after verifying their exact
# bytes, private permissions and durable clone records. No customer volume.
assert infected_path != outage_path
for location in (infected_path, outage_path):
    location.unlink()
for directory in sorted(
    (p for p in root.rglob("*") if p.is_dir()),
    key=lambda p: len(p.parts), reverse=True,
):
    directory.rmdir()
assert not any(root.iterdir()), "NO-GO isolated quarantine Evidence residue"
print("PASS: authenticated EICAR=422 infected and scanner-unavailable=503, two durable quarantines, no admitted Evidence.")
PY

clone_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM auth_sessions;')"
clone_documents_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM documents;')"
clone_jobs_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM document_processing_jobs;')"
clone_extractions_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM document_text_extractions;')"
clone_segments_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM document_text_segments;')"
clone_quarantine_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$clone" -At \
  -c 'SELECT COUNT(*) FROM quarantined_uploads;')"
[ "$clone_quarantine_after" -eq "$((clone_quarantine_before + 2))" ] || exit 1
[ "$clone_extractions_after" -eq "$((clone_extractions_before + 2))" ] || exit 1
[ "$clone_segments_after" -eq "$((clone_segments_before + 2))" ] || exit 1
[ "$clone_after" -gt "$clone_before" ] || exit 1
[ "$clone_documents_after" -eq "$((clone_documents_before + 2))" ] || exit 1
[ "$clone_jobs_after" -eq "$((clone_jobs_before + 2))" ] || exit 1
after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM auth_sessions;')"
source_documents_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM documents;')"
source_jobs_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM document_processing_jobs;')"
source_extractions_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM document_text_extractions;')"
source_segments_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM document_text_segments;')"
source_quarantine_after="$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c 'SELECT COUNT(*) FROM quarantined_uploads;')"
[ "$source_quarantine_before" = "$source_quarantine_after" ] && \
[ "$source_extractions_before" = "$source_extractions_after" ] && \
[ "$source_segments_before" = "$source_segments_after" ] && \
[ "$before" = "$after" ] && \
[ "$source_documents_before" = "$source_documents_after" ] && \
[ "$source_jobs_before" = "$source_jobs_after" ] || {
  echo "::error::Seeded synthetic source database was unexpectedly modified"
  exit 1
}
test -z "$(sudo find "$scratch" -mindepth 1 -print -quit)"
echo "PASS: two scanned/native clean documents admitted, processed; infected/outage HTTP uploads quarantined without source DB writes."
