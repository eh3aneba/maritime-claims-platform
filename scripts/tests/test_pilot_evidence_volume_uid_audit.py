"""Offline no-Evidence-bytes tests for the read-only UID/GID precheck."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[2] / "apps/api/app/core/evidence_volume_uid_audit.py"
spec = importlib.util.spec_from_file_location("evidence_uid_precheck", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class EvidenceUidPrecheckTests(unittest.TestCase):
    def setUp(self):
        if os.name != "posix" or os.getuid() == 0 or os.getgid() == 0:
            self.skipTest("POSIX unprivileged runner required for local ownership checks")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "evidence"
        self.root.mkdir(mode=0o700)
        self.uid, self.gid = os.getuid(), os.getgid()

    def check(self, *, root=None, limit=100):
        return audit.audit_evidence_tree(
            root or self.root, uid=self.uid, gid=self.gid,
            entry_limit=limit,
        )

    def test_compatible_directory_tree_only_reads_metadata(self):
        sub = self.root / "claim"
        sub.mkdir(mode=0o700)
        original = sub / "existing-evidence.pdf"
        original.write_bytes(b"synthetic-only-bytes")
        original.chmod(0o600)
        self.assertEqual(self.check(), 3)
        self.assertEqual(original.read_bytes(), b"synthetic-only-bytes")
        self.assertEqual(original.stat().st_mode & 0o777, 0o600)

    def test_no_go_if_owner_cannot_create_or_enter_directory(self):
        self.root.chmod(0o500)
        with self.assertRaisesRegex(
            audit.EvidencePermissionAuditError, "^directory_permissions$"
        ):
            self.check()

    def test_no_go_on_any_world_writable_evidence_subdirectory(self):
        sub = self.root / "unsafe"
        sub.mkdir()
        sub.chmod(0o777)
        with self.assertRaisesRegex(
            audit.EvidencePermissionAuditError, "^world_writable_entry$"
        ):
            self.check()

    def test_no_go_on_symlink_without_traversing_it(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("do-not-follow")
        (self.root / "alias").symlink_to(outside)
        with self.assertRaisesRegex(
            audit.EvidencePermissionAuditError, "^symlink_detected$"
        ):
            self.check()
        self.assertEqual(outside.read_text(), "do-not-follow")

    def test_no_go_for_legacy_owner_incompatible_permissions(self):
        # Simulate an existing root-owned, owner-only directory by asking
        # whether an unrelated proposed numeric UID could enter it.
        with self.assertRaisesRegex(
            audit.EvidencePermissionAuditError, "^directory_permissions$"
        ):
            audit.audit_evidence_tree(self.root, uid=60000, gid=60000)

    def test_no_go_missing_root_or_scan_limit(self):
        with self.assertRaisesRegex(
            audit.EvidencePermissionAuditError, "^metadata_unavailable$"
        ):
            self.check(root=self.root / "absent")
        for index in range(3):
            (self.root / str(index)).write_text("synthetic")
        with self.assertRaisesRegex(
            audit.EvidencePermissionAuditError, "^scan_limit_exceeded$"
        ):
            self.check(limit=2)


if __name__ == "__main__":
    unittest.main()
