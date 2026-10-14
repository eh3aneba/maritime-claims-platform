"""Unit-level safety checks for the read-only restored Evidence-pair gate."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from app.core.restore_pair_audit import (
    RestoreEvidenceRow, RestorePairAuditError, audit_restored_evidence_pair,
)


class RestorePairAuditTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0 or os.getegid() == 0:
            self.skipTest("Only an actual unprivileged user may validate this audit")
        self.tmp = tempfile.TemporaryDirectory(prefix="mcri-ci-restore-pair-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "evidence"
        self.root.mkdir(mode=0o700)
        self.root.chmod(0o700)
        self.uid, self.gid = os.geteuid(), os.getegid()
        self.org, self.claim = uuid4(), uuid4()
        self.doc_id, self.quarantine_id = uuid4(), uuid4()
        self.native = b"%PDF-1.4\nsynthetic restore-pair fixture\n%%EOF\n"
        self.quarantined = b"PK\x03\x04synthetic quarantine only"
        self.document = self._put(
            kind="document", record_id=self.doc_id, state="clean",
            payload=self.native, suffix=".pdf",
        )
        self.quarantine = self._put(
            kind="quarantine", record_id=self.quarantine_id, state="infected",
            payload=self.quarantined, suffix=".docx",
        )

    def _put(self, *, kind, record_id, state, payload, suffix):
        prefix = (
            [str(self.org), str(self.claim)]
            if kind == "document"
            else ["_quarantine", str(self.org), str(self.claim)]
        )
        parent = self.root
        for segment in prefix:
            parent = parent / segment
            parent.mkdir(mode=0o700, exist_ok=True)
            parent.chmod(0o700)
        path = parent / (str(record_id) + suffix)
        path.write_bytes(payload)
        path.chmod(0o600)
        return RestoreEvidenceRow(
            kind=kind, record_id=record_id,
            organization_id=self.org, claim_id=self.claim,
            storage_key=path.relative_to(self.root).as_posix(),
            file_hash=hashlib.sha256(payload).hexdigest(),
            file_size_bytes=len(payload), state=state,
        )

    def audit(self, records=None):
        return audit_restored_evidence_pair(
            self.root, [self.document, self.quarantine] if records is None else records,
            organization_id=self.org, claim_id=self.claim, uid=self.uid, gid=self.gid,
        )

    def expect_no_go(self, code, records=None):
        with self.assertRaises(RestorePairAuditError) as exc:
            self.audit(records)
        self.assertEqual(str(exc.exception), code)

    def test_admitted_and_quarantine_rows_match_private_bytes(self):
        self.assertEqual(self.audit(), 2)

    def test_same_size_tampering_detected_and_atomic_restore(self):
        path = self.root / self.document.storage_key
        known = path.read_bytes()
        backup = self.root / "isolated-ci-only-backup"
        backup.write_bytes(known)
        backup.chmod(0o600)
        path.write_bytes(b"x" * len(known))
        self.expect_no_go("digest_mismatch")
        temp = path.parent / ".private-restore"
        with temp.open("xb") as dest:
            dest.write(backup.read_bytes())
            dest.flush()
            os.fsync(dest.fileno())
        temp.chmod(0o600)
        os.replace(temp, path)
        self.assertEqual(self.audit(), 2)
        self.assertEqual(path.read_bytes(), known)
        backup.unlink()

    def test_missing_or_truncated_file_refused(self):
        path = self.root / self.document.storage_key
        path.write_bytes(self.native[:5])
        self.expect_no_go("unsafe_file")
        path.unlink()
        self.expect_no_go("evidence_unavailable")

    def test_claim_mismatch_swapped_document_or_duplicate_refused(self):
        self.expect_no_go(
            "wrong_claim_lineage", [replace(self.document, claim_id=uuid4())]
        )
        self.expect_no_go(
            "wrong_storage_lineage",
            [replace(self.document, record_id=uuid4())],
        )
        self.expect_no_go(
            "duplicate_reference", [self.document, self.document],
        )
        self.expect_no_go(
            "unsafe_evidence_state", [replace(self.document, state="infected")],
        )
        self.expect_no_go(
            "unsafe_evidence_state", [replace(self.quarantine, state="clean")],
        )

    def test_path_escape_and_symlink_refused(self):
        for key in (
            "/etc/passwd", "../escape.pdf", "a/../../escape.pdf",
            self.document.storage_key.replace("/", "//"),
            self.document.storage_key.replace("/", "\\"),
        ):
            self.expect_no_go(
                "unsafe_storage_key", [replace(self.document, storage_key=key)],
            )
        path = self.root / self.document.storage_key
        path.unlink()
        path.symlink_to(self.root / self.quarantine.storage_key)
        self.expect_no_go("unsafe_file")

    def test_unsafe_owner_or_world_writable_parent_refused(self):
        path = self.root / self.document.storage_key
        path.chmod(0o644)
        self.expect_no_go("unsafe_file")
        path.chmod(0o600)
        path.parent.chmod(0o777)
        self.expect_no_go("unsafe_directory")
        path.parent.chmod(0o700)
        with self.assertRaisesRegex(RestorePairAuditError, "unsafe_root_owner"):
            audit_restored_evidence_pair(
                self.root, [self.document], organization_id=self.org,
                claim_id=self.claim, uid=self.uid + 1, gid=self.gid,
            )

    def test_invalid_contract_and_file_hash_refused(self):
        self.expect_no_go("invalid_row", [replace(self.document, file_hash="BAD")])
        self.expect_no_go(
            "invalid_row", [replace(self.document, file_size_bytes=0)]
        )
        self.expect_no_go("invalid_contract", [])
        with self.assertRaisesRegex(RestorePairAuditError, "invalid_contract"):
            audit_restored_evidence_pair(
                Path("relative"), [self.document],
                organization_id=self.org, claim_id=self.claim,
                uid=self.uid, gid=self.gid,
            )


if __name__ == "__main__":
    unittest.main()
