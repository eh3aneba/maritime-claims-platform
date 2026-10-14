"""Static guards: new restoration auditor is wired to actual CI clone rows."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "apps" / "api" / "app" / "core" / "restore_pair_audit.py"
PROBE = ROOT / "scripts" / "pilot_ci_nonroot_auth_db_clone.sh"
PRECHECK = ROOT / "docs" / "operations" / "EVIDENCE_UID_MIGRATION_PRECHECK.md"


class PairReconciliationPolicy(unittest.TestCase):
    def test_auditor_is_read_only_strict_and_no_path_leak(self):
        source = AUDIT.read_text(encoding="utf-8")
        for fragment in (
            'class RestorePairAuditError(RuntimeError)',
            'class RestoreEvidenceRow:',
            'def audit_restored_evidence_pair(',
            'record.organization_id != organization_id',
            'record.claim_id != claim_id',
            'record.kind not in {"document", "quarantine"}',
            'record.state != "clean"',
            'record.state not in {"infected", "scan_error"}',
            'pure.parts != (*prefix, f"{record.record_id}{suffix}")',
            'record.file_size_bytes <= MAX_FILE_BYTES',
            'meta.st_uid != uid or meta.st_gid != gid',
            'os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK',
            'hashlib.sha256()',
            'digest.hexdigest() != record.file_hash',
            'raise RestorePairAuditError("digest_mismatch")',
            'raise RestorePairAuditError("wrong_claim_lineage")',
        ):
            self.assertIn(fragment, source)
        for forbidden in ("os.chown(", "os.chmod(", "os.replace(", ".write_bytes(", "print("):
            self.assertNotIn(forbidden, source)

    def test_actual_postgresql_clone_rows_and_custody_files_are_checked(self):
        probe = PROBE.read_text(encoding="utf-8")
        for fragment in (
            'MCRI_SYNTHETIC_ONLY_CONFIRM:-',
            'clone="mcri_ci_auth_$(openssl rand -hex 8)"',
            'DROP DATABASE',
            'from app.core.restore_pair_audit import (',
            'RestoreEvidenceRow(',
            'state=item.malware_scan_status.value',
            'state=item.status.value',
            'for item in (native_db_row, scanned_document)',
            'for item in selected',
            'assert audit_restored_evidence_pair(',
            'file_hash="0" * 64',
            '"digest_mismatch"',
            '"wrong_claim_lineage"',
            'source_quarantine_before=',
            'source_documents_before=',
            '[ "$source_quarantine_before" = "$source_quarantine_after" ]',
            '[ "$source_documents_before" = "$source_documents_after" ]',
            'scanned_storage.unlink()',
            'for location in (infected_path, outage_path):',
        ):
            self.assertIn(fragment, probe)
        self.assertEqual(probe.count('from app.core.restore_pair_audit import ('), 2)
        for unsafe in ("docker volume rm", "chown -R", "--network host"):
            self.assertNotIn(unsafe, probe)

    def test_operator_documentation_preserves_no_go_boundary(self):
        doc = PRECHECK.read_text(encoding="utf-8")
        self.assertIn("Read-only selected-claim DB/Evidence pair audit", doc)
        self.assertIn("not a database+volume restore", doc)
        self.assertIn("independently isolated", doc)


if __name__ == "__main__":
    unittest.main()
