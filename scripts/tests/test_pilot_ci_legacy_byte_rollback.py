"""Fail-closed policy regression for CI-only byte-level Evidence copy rollback."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "performance-smoke.yml"
RUNBOOK = ROOT / "docs" / "operations" / "EVIDENCE_UID_MIGRATION_PRECHECK.md"


class SyntheticLegacyByteRollbackPolicy(unittest.TestCase):
    def test_legacy_source_remains_read_only_and_clone_isolated(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        section = workflow.split(
            "- name: Verify unprivileged API and OCR worker synthetic scratch custody", 1
        )[1].split(
            "- name: Verify isolated synthetic PostgreSQL clone real non-root authentication", 1
        )[0]
        for marker in (
            'legacy="$(mktemp -d "$RUNNER_TEMP/mcri-uid-legacy.',
            'scratch="$(mktemp -d "$RUNNER_TEMP/mcri-uid-scratch.',
            '-v "$legacy:/mnt/mcri-ci-legacy:ro"',
            '-v "$scratch:/mnt/mcri-ci-uid-probe:rw"',
            'assert not cloned_file.samefile(legacy_file)',
            'assert not os.access(legacy_file, os.R_OK)',
            'test "$(sudo sha256sum "$legacy/readonly-legacy.pdf" | cut -d',
            'test "$(sudo stat -c',
            'sudo rm -rf -- "$scratch" "$legacy"',
        ):
            self.assertIn(marker, section)
        self.assertNotIn('chown -R', section)
        self.assertNotIn('chmod -R', section)
        self.assertNotIn('docker volume rm', section)
        self.assertNotIn('--network host', section)

    def test_strict_corruption_detection_and_private_atomic_restore(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        section = workflow.split(
            '# CI-only byte-level corruption and atomic restoration on the', 1
        )[1].split(
            'marker = root / "cross-service-synthetic-marker"', 1
        )[0]
        for marker in (
            'cloned_file.resolve().is_relative_to(root.resolve())',
            'immutable_backup = root / "ci-legacy-byte-restore-backup"',
            'os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600',
            'immutable_backup.read_bytes() == expected',
            'cloned_file.write_bytes(b"synthetic-corrupted-copy-only")',
            'assert audit_evidence_tree(cloned_root) == 2',
            'hashlib.sha256(cloned_file.read_bytes()).hexdigest() != expected_sha',
            'hashlib.sha256(immutable_backup.read_bytes()).hexdigest() == expected_sha',
            'restore_tmp = cloned_root / ".ci-atomic-restore-pending"',
            'os.fsync(dest.fileno())',
            'os.replace(restore_tmp, cloned_file)',
            'S_IMODE(cloned_file.stat().st_mode) == 0o600',
            'cloned_file.stat().st_uid == cloned_file.stat().st_gid == 1000',
            'assert cloned_file.read_bytes() == expected',
            'hashlib.sha256(cloned_file.read_bytes()).hexdigest() == expected_sha',
            'immutable_backup.unlink()',
        ):
            self.assertIn(marker, section)
        self.assertIn('finally:', section)
        self.assertNotIn('legacy_file.write_bytes', section)
        self.assertNotIn('legacy_file.chmod', section)
        self.assertNotIn('os.replace(restore_tmp, legacy_file)', section)

    def test_runbook_does_not_claim_production_recovery(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("Synthetic byte-corruption and atomic restore rehearsal", text)
        self.assertIn("not** independent evidence-volume recovery", text)
        self.assertIn("The original root-owned source is mounted **read-only**", text)


if __name__ == "__main__":
    unittest.main()
