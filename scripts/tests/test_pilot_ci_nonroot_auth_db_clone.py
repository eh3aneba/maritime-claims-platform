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
            'clean_pdf = (b"%PDF-1.4',
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
            '[ "$clone_documents_after" -eq "$((clone_documents_before + 1))" ]',
            '[ "$clone_jobs_after" -eq "$((clone_jobs_before + 1))" ]',
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
            'segment.extraction_id == extraction.id',
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
            '[ "$clone_extractions_after" -eq "$((clone_extractions_before + 1))" ]',
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
