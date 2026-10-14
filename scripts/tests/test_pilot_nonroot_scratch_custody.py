"""Offline policy assertions for the live synthetic-only effective UID rehearsal."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "performance-smoke.yml"


class SyntheticNonrootCustodyPolicyTests(unittest.TestCase):
    def test_live_compose_runs_restricted_api_and_ocr_on_separate_scratch(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        name = "Verify unprivileged API and OCR worker synthetic scratch custody"
        self.assertIn(name, source)
        section = source.split("- name: " + name, 1)[1].split("\n      - name:", 1)[0]
        self.assertEqual(section.count("--user 1000:1000"), 2)
        self.assertEqual(section.count("-f docker-compose.ci-nonroot-custody.yml"), 2)
        self.assertEqual(section.count('int(proc_status["CapEff"].strip(), 16) == 0'), 2)
        self.assertEqual(section.count('proc_status["NoNewPrivs"].strip() == "1"'), 2)
        self.assertEqual(section.count('-v "$scratch:/mnt/mcri-ci-uid-probe:rw"'), 2)
        self.assertIn("api python - <<'PY'", section)
        self.assertIn("worker python - <<'PY'", section)
        self.assertIn("sudo chown 1000:1000 \"$scratch\"", section)
        self.assertIn("sudo chmod 0700 \"$scratch\"", section)
        self.assertIn('trap \'sudo rm -rf -- "$scratch"\' EXIT', section)
        self.assertIn('root / "cross-service-synthetic-marker"', section)
        self.assertIn('marker.rename(moved)', section)
        self.assertIn('moved.unlink()', section)
        self.assertIn('["tesseract", str(image), "stdout", "-l", "eng+fas"]', section)
        self.assertIn('["pdftotext", "-v"]', section)
        self.assertIn('["pdftoppm", "-v"]', section)
        self.assertIn('image.unlink()', section)
        self.assertIn("LocalDocumentStorage(str(root), max_upload_bytes=1024)", section)
        self.assertIn("asyncio.run(store.save_upload(", section)
        self.assertIn('UploadFile(file=BytesIO(payload), filename="synthetic.pdf")', section)
        self.assertIn('stored.file_hash == hashlib.sha256(payload).hexdigest()', section)
        self.assertIn('from app.modules.documents.storage import LocalDocumentStorage, UploadTooLarge', section)
        self.assertIn('UploadFile(file=BytesIO(b"synthetic-collision")', section)
        self.assertIn('except FileExistsError:', section)
        self.assertIn('except UploadTooLarge:', section)
        self.assertIn('assert not (root / "_quarantine/ci/oversized.pdf").exists()', section)
        self.assertIn('glob(".mcri-upload-*.partial")', section)
        self.assertIn('store.promote(source_key, existing_key)', section)
        self.assertIn('store.promote(source_key, target_key)', section)
        self.assertIn('store.save_bytes(b"unsafe-collision", target_key)', section)
        self.assertIn('store.delete_physical(target_key)', section)
        self.assertIn('store.delete_physical(existing_key)', section)
        self.assertIn('("_quarantine/ci", "_quarantine", "tenant/claim", "tenant")', section)
        self.assertIn('sudo find "$scratch" -mindepth 1 -maxdepth 1', section)

    def test_ci_override_only_confines_disposable_api_and_worker(self):
        override = (ROOT / "docker-compose.ci-nonroot-custody.yml").read_text(encoding="utf-8")
        self.assertIn('user: "1000:1000"', override)
        self.assertEqual(override.count('user: "1000:1000"'), 2)
        self.assertEqual(override.count("cap_drop:"), 2)
        self.assertEqual(override.count("- ALL"), 2)
        self.assertEqual(override.count("no-new-privileges:true"), 2)
        self.assertNotIn("local_documents:", override)
        self.assertNotIn("/data/documents", override)
        self.assertNotIn("privileged:", override)

    def test_no_legacy_volume_mutation_or_security_bypass(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        name = "Verify unprivileged API and OCR worker synthetic scratch custody"
        section = source.split("- name: " + name, 1)[1].split("\n      - name:", 1)[0]
        self.assertNotIn(':/data/documents', section)
        self.assertNotIn('LOCAL_STORAGE_PATH=', section)
        self.assertNotIn('docker volume rm', section)
        self.assertNotIn('docker compose down -v', section)
        self.assertNotIn('chmod 777', section)
        self.assertNotIn('chown -R', section)
        self.assertIn('legacy Evidence volume migration or customer-host approval', section)
        self.assertIn('NOT a real authenticated API upload, scanner admission', section)


if __name__ == "__main__":
    unittest.main()
