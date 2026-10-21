"""Always-on static protection for non-destructive Evidence volume preflight."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "apps/api/app/core/preflight.py"
TESTS = ROOT / "apps/api/tests/test_preflight_local_evidence_storage.py"
COMPOSE = ROOT / "docker-compose.yml"


class EvidencePreflightPolicy(unittest.TestCase):
    def test_probe_is_exclusive_no_fixed_overwrite_or_storage_repair(self):
        source = PREFLIGHT.read_text(encoding="utf-8")
        for marker in (
            "def _check_local_evidence_write_access(",
            "if not storage.is_absolute():",
            "if not strict:",
            "metadata = storage.lstat()",
            "not stat.S_ISDIR(metadata.st_mode)",
            "stat.S_IWOTH",
            "tempfile.NamedTemporaryFile(",
            'prefix=".mcri-preflight-"',
            "temporary.flush()",
            "_check_local_evidence_write_access(storage, strict=strict)",
            '"Local evidence storage is unavailable or unsafe"',
        ):
            self.assertIn(marker, source)
        for forbidden in (
            'storage / ".mcri-write-probe"',
            'probe.write_text("ok")',
            "probe.unlink(missing_ok=True)",
            "chown(",
            "chmod(",
            "os.system(",
            "subprocess",
            "Local evidence storage is not writable: {exc}",
        ):
            self.assertNotIn(forbidden, source)
        tests = TESTS.read_text(encoding="utf-8")
        for marker in (
            "test_strict_preflight_requires_existing_storage_root",
            "test_exclusive_probe_never_overwrites_existing_named_evidence",
            "test_symlink_root_is_rejected_without_touching_target",
            "test_world_writable_root_is_rejected",
            "test_preflight_never_emits_os_error_with_private_storage_path",
        ):
            self.assertIn(marker, tests)

    def test_deployment_uid_switch_remains_unapproved(self):
        source = COMPOSE.read_text(encoding="utf-8")
        # This commit must not flip the production API/worker UID or
        # mutate an existing Evidence mount's ownership.
        api = source.split("\n  api:\n", 1)[1].split("\n  worker:\n", 1)[0]
        worker = source.split("\n  worker:\n", 1)[1].split(
            "\n  governance-webhook-worker:\n", 1
        )[0]
        self.assertNotIn('user: "1000:1000"', api)
        self.assertNotIn('user: "1000:1000"', worker)
        self.assertNotIn("chown -R", source)
        self.assertNotIn("chmod -R", source)


if __name__ == "__main__":
    unittest.main()
