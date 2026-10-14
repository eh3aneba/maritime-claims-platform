"""Fail-closed policy tests for the CI-only authenticated non-root DB clone."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pilot_ci_nonroot_auth_db_clone.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "performance-smoke.yml"


class NonrootIsolatedAuthClonePolicy(unittest.TestCase):
    def test_ci_marker_and_exact_synthetic_database_guard(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            'GITHUB_ACTIONS:-', ".env.performance",
            'APP_ENV:-', 'MCRI_SYNTHETIC_ONLY_CONFIRM:-',
            'POSTGRES_DB:-', "mcri_performance",
            'POSTGRES_USER:-', "mcri_performance",
            'AI_PROVIDER:-', 'MCRI_DEMO_ORG_SLUG:-',
            'MCRI_DEMO_EMAIL:-', 'MCRI_DEMO_PASSWORD',
            'set -euo pipefail',
        ):
            self.assertIn(marker, script)

    def test_exclusive_clone_dump_restore_and_cleanup(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            'mktemp "$RUNNER_TEMP/mcri-db-copy.',
            'mktemp -d "$RUNNER_TEMP/mcri-auth-scratch.',
            'chmod 0600 "$dump"',
            'clone="mcri_ci_auth_$(openssl rand -hex 8)"',
            'if [ "$created" = 1 ]; then',
            'DROP DATABASE \\"$clone\\" WITH (FORCE);',
            'SELECT 1 FROM pg_database WHERE datname=',
            '--format=custom --no-owner --no-privileges > "$dump"',
            'CREATE DATABASE \\"$clone\\" OWNER',
            'pg_restore -U "$POSTGRES_USER" -d "$clone"',
            '--no-owner --no-privileges --exit-on-error < "$dump"',
            'rm -f -- "$dump"',
            'sudo rm -rf -- "$scratch"',
        ):
            self.assertIn(marker, script)
        self.assertEqual(script.count('created=1'), 1)
        self.assertIn('SELECT COUNT(*) FROM auth_sessions;', script)
        self.assertIn('[ "$before" = "$after" ]', script)
        self.assertNotIn('docker compose down -v', script)
        self.assertNotIn('DROP DATABASE "mcri_performance"', script)
        self.assertNotIn('docker volume rm', script)
        self.assertNotIn('chown -R', script)

    def test_actual_nonroot_api_authorized_http_read_uses_clone_only(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            '-f docker-compose.ci-nonroot-custody.yml',
            '--user 1000:1000',
            '-v "$scratch:/mnt/mcri-ci-auth-probe:rw"',
            '-e "DATABASE_URL=$clone_url"',
            'DATABASE_URL%/*',
            'os.environ["LOCAL_STORAGE_PATH"] = str(root)',
            'run_preflight(require_db=True)',
            '"--host", "127.0.0.1"',
            '"--no-access-log"',
            'base + "/auth/login"',
            '"Authorization": "Bearer " + token',
            'base + "/claims?search=MCRI-DEMO-MT-ORION&limit=20"',
            '"/documents"',
            'child["Uid"].split() == ["1000"] * 4',
            'int(child["CapEff"].strip(), 16) == 0',
            'child["NoNewPrivs"].strip() == "1"',
            'server.terminate()',
            'not any(root.iterdir())',
        ):
            self.assertIn(marker, script)
        self.assertNotIn('method="PUT"', script)
        self.assertNotIn('"/documents", data=', script)
        self.assertNotIn("--service-ports", script)
        self.assertNotIn("--network host", script)

    def test_authenticated_clean_http_upload_is_scanned_and_committed_only_to_clone(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            'source_documents_before=',
            'source_jobs_before=',
            'clone_documents_before=',
            'clone_jobs_before=',
            'clean_pdf = output.getvalue()',
            'digest = hashlib.sha256(clean_pdf).hexdigest()',
            'multipart/form-data; boundary=',
            'data=form, method="POST"',
            'assert response.status == 201',
            'admitted["malware_scan_status"] == "clean"',
            'admitted["malware_scanned_at"]',
            'from app.db import metadata as _all_model_metadata',
            'document.file_hash == digest',
            'document.malware_scan_status == DocumentMalwareScanStatus.CLEAN',
            'stat.S_IMODE(stored.stat().st_mode) == 0o600',
            'DocumentProcessingJob.document_id == document.id',
            'DocumentProcessingJob.status == ProcessingJobStatus.PENDING',
            'QuarantinedUpload.claim_id == document.claim_id',
            'QuarantinedUpload.file_hash == digest',
            'response.read() == clean_pdf',
            'assert not list(root.rglob(".mcri-upload-*.partial"))',
            'assert [p for p in root.rglob("*") if p.is_file()] == [stored]',
            'stored.unlink()',
            'directory.rmdir()',
            'clone_documents_after=',
            'clone_jobs_after=',
            'source_documents_after=',
            'source_jobs_after=',
            '[ "$clone_documents_after" -eq "$((clone_documents_before + 2))" ]',
            '[ "$clone_jobs_after" -eq "$((clone_jobs_before + 2))" ]',
            '[ "$source_documents_before" = "$source_documents_after" ]',
            '[ "$source_jobs_before" = "$source_jobs_after" ]',
        ):
            self.assertIn(marker, script)
        self.assertIn('b"\\r\\n"', script)
        self.assertNotIn('STORAGE_BACKEND=s3', script)
        self.assertNotIn('docker volume rm', script)

    def test_real_nonroot_worker_completes_exact_cloned_processing_job(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            'from pypdf import PdfWriter',
            'writer.add_blank_page(width=612, height=792)',
            'text_stream.set_data(',
            'writer.write(output)',
            'target_marker = root / "ci-processing-target.json"',
            '"job_id": processing_id',
            'target_marker.chmod(0o600)',
            '-e LOCAL_STORAGE_PATH=/mnt/mcri-ci-auth-probe',
            '-e OCR_ENABLED=true -e OCR_LANGUAGES=eng+fas',
            'MCRI_SYNTHETIC_ONLY_CONFIRM=YES worker python -',
            'assert os.geteuid() == os.getegid() == 1000',
            'proc["NoNewPrivs"].strip() == "1"',
            'from app.db import metadata as _all_model_metadata',
            'from app.modules.processing.lease_recovery import process_job_with_lease',
            'DocumentProcessingJob.id == job_id',
            'DocumentProcessingJob.document_id == doc_id',
            '.with_for_update(skip_locked=True)',
            'assert job.status == ProcessingJobStatus.PENDING',
            'job.status = ProcessingJobStatus.RUNNING',
            'job.attempt_count += 1',
            'process_job_with_lease(session, job=job, processor=process_job)',
            'job.status == ProcessingJobStatus.COMPLETED',
            'document.processing_status == DocumentProcessingStatus.PROCESSED',
            'extraction.extraction_method == "pypdf"',
            'extraction.char_count >= 60 and extraction.segment_count == 1',
            'DocumentTextSegment.extraction_id == extraction.id',
            'os.environ["MCRI_CI_AUTH_DB_NAME"] in segment.text',
            'clone_extractions_before=',
            'clone_segments_before=',
            'clone_extractions_after=',
            'clone_segments_after=',
            'source_extractions_before=',
            'source_segments_before=',
            'source_extractions_after=',
            'source_segments_after=',
            'stored.unlink()',
            'marker.unlink()',
            'assert not any(root.iterdir())',
        ):
            self.assertIn(marker, script)
        self.assertIn(
            '[ "$clone_extractions_after" -eq "$((clone_extractions_before + 2))" ]',
            script,
        )
        self.assertIn(
            '[ "$source_extractions_before" = "$source_extractions_after" ]',
            script,
        )
        self.assertIn(
            '[ "$source_segments_before" = "$source_segments_after" ]',
            script,
        )
        self.assertNotIn('docker volume rm', script)
        self.assertNotIn('chown -R', script)

    def test_worker_has_readable_font_fallback_for_scanned_pdf_fixture(self):
        dockerfile = (ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
        worker = dockerfile.split("FROM python:3.14.8-alpine3.24 AS worker\n", 1)[1].split(
            "\nFROM base AS api", 1
        )[0]
        self.assertIn("        font-liberation \\", worker)
        self.assertIn("test -r /usr/share/fonts/liberation/LiberationSans-Regular.ttf", worker)
        self.assertIn("fc-match -f '%{family}' Helvetica | grep -F 'Liberation Sans'", worker)
        self.assertIn("RUN python --version", worker)
        self.assertNotIn("font-liberation", dockerfile.split(
            "FROM python:3.14.8-alpine3.24 AS base", 1
        )[1].split("FROM python:3.14.8-alpine3.24 AS worker\n", 1)[0])

    def test_scanned_image_only_pdf_requires_genuine_tesseract_eng_fas(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            '["pdftoppm", "-f", "1", "-l", "1", "-singlefile",',
            '"-r", "200", "-gray", str(stored), str(pgm_prefix)',
            'header = re.match(rb"P5',
            'assert len(pixels) == width * height',
            'image = image.flate_encode()',
            'NameObject("/Subtype"): NameObject("/Image")',
            'NameObject("/ColorSpace"): NameObject("/DeviceGray")',
            'stream.set_data(b"q 612 0 0 792 0 0 cm /Im1 Do Q")',
            'writer.write(output)',
            'b"BT /F1 20 Tf 55 650 Td "',
            'b"0 -48 Td (nonroot worker processing) Tj "',
            'marker_text = os.environ["MCRI_CI_AUTH_DB_NAME"].encode("ascii")',
            'native = extract_document_text(scanned_pdf, enable_ocr=False)',
            'assert native.method == "pypdf" and native.requires_ocr',
            'not native.combined_text.strip()',
            'recovered = extract_document_text(',
            'enable_ocr=True, ocr_languages="eng+fas"',
            'ocr_max_pages=1, ocr_timeout_seconds=90',
            'recovered.method == "pypdf+selective-tesseract:eng+fas"',
            'if recovered.requires_ocr or len(recovered.segments) != 1:',
            'recovered.text_hash is not None',
            'recovered.segments[0].locator_value == "1"',
            '"synthetic marine claims evidence" in recovered.combined_text.casefold()',
            '"nonroot worker processing" in recovered.combined_text.casefold()',
            'source_ink = sum(pixel < 180 for pixel in pixels)',
            'ocr_source = subprocess.run(',
            'source-raster Tesseract exited nonzero',
            'roundtrip_prefix = root / "ci-scanned-roundtrip"',
            'roundtrip_ink = sum(pixel < 180 for pixel in rt_pixels)',
            'NO-GO scanned PDF image content did not survive round-trip',
            'roundtrip_pgm.unlink()',
            'scanned_pdf.unlink()',
            'pgm_path.unlink()',
            'PASS: image-only scanned PDF authenticated HTTP admission',
        ):
            self.assertIn(marker, script)
        self.assertIn('rb"P5\\s+(\\d+)\\s+(\\d+)\\s+(\\d+)\\s"', script)
        self.assertEqual(script.count("MCRI_SYNTHETIC_ONLY_CONFIRM=YES worker python -"), 1)
        self.assertNotIn('docker volume rm', script)
        self.assertNotIn('--network host', script)

    def test_scanned_pdf_authenticated_http_clamav_fenced_ocr_db_commit(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            '-e MCRI_DEMO_ORG_SLUG -e MCRI_DEMO_EMAIL -e MCRI_DEMO_PASSWORD',
            '"--host", "127.0.0.1", "--port", "18082", "--no-access-log"',
            'base + "/health/ready"',
            'base + "/auth/login"',
            'scan_blob = scanned_pdf.read_bytes()',
            'scan_hash = hashlib.sha256(scan_blob).hexdigest()',
            'b"--" + boundary + b"\\r\\n"',
            'filename="ci-scanned-only.pdf"',
            'data=body, method="POST"',
            'assert response.status == 201',
            'admitted_scan["file_hash"] == scan_hash',
            'admitted_scan["malware_scan_status"] == "clean"',
            'admitted_scan["malware_scanned_at"]',
            'response.read() == scan_blob',
            'api.terminate()',
            'scanned_document = session.get(Document, scanned_id)',
            'scanned_document.claim_id == UUID(details["claim_id"])',
            'scanned_document.organization_id == session.get(Document, doc_id).organization_id',
            'scanned_document.malware_scan_status == DocumentMalwareScanStatus.CLEAN',
            'stat.S_IMODE(scanned_storage.stat().st_mode) == 0o600',
            'QuarantinedUpload.file_hash == scan_hash',
            'DocumentProcessingJob.document_id == scanned_id',
            'DocumentProcessingJob.status == ProcessingJobStatus.PENDING',
            'scanned_job.status = ProcessingJobStatus.RUNNING',
            'scanned_job.attempt_count += 1',
            'process_job_with_lease(session, job=scanned_job, processor=process_job)',
            'scanned_job.status == ProcessingJobStatus.COMPLETED',
            'scanned_document.processing_status == DocumentProcessingStatus.PROCESSED',
            'extraction_scan.extraction_method == "pypdf+selective-tesseract:eng+fas"',
            'extraction_scan.requires_ocr is False',
            'DocumentTextSegment.document_id == scanned_id',
            'segment_scan.extraction_id == extraction_scan.id',
            'segment_scan.locator_value == "1"',
            '"synthetic marine claims evidence" in segment_scan.text.casefold()',
            'scanned_storage.unlink()',
            'assert not any(root.iterdir())',
            '[ "$clone_documents_after" -eq "$((clone_documents_before + 2))" ]',
            '[ "$clone_jobs_after" -eq "$((clone_jobs_before + 2))" ]',
            '[ "$clone_extractions_after" -eq "$((clone_extractions_before + 2))" ]',
            '[ "$clone_segments_after" -eq "$((clone_segments_before + 2))" ]',
            '[ "$source_documents_before" = "$source_documents_after" ]',
            '[ "$source_jobs_before" = "$source_jobs_after" ]',
            '[ "$source_extractions_before" = "$source_extractions_after" ]',
            '[ "$source_segments_before" = "$source_segments_after" ]',
        ):
            self.assertIn(marker, script)
        self.assertEqual(script.count('worker python -'), 1)
        self.assertNotIn('docker volume rm', script)
        self.assertNotIn('docker compose down -v', script)
        self.assertNotIn('chown -R', script)

    def test_required_live_stack_step_is_wired(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "- name: Verify isolated synthetic PostgreSQL clone real non-root authentication",
            workflow,
        )
        self.assertEqual(
            workflow.count("run: bash scripts/pilot_ci_nonroot_auth_db_clone.sh"), 1
        )


if __name__ == "__main__":
    unittest.main()
