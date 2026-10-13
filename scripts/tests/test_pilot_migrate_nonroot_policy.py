"""Static regression for Alembic's unprivileged runtime Compose contract."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def service_section(name: str) -> str:
    source = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    tail = source.split("\n  " + name + ":\n", 1)[1]
    return re.split(r"(?m)^  [a-z][a-z0-9-]*:$", tail, maxsplit=1)[0]


class MigrationUserBoundaryTests(unittest.TestCase):
    def test_migration_service_is_nonroot_and_has_no_document_volume(self):
        section = service_section("migrate")
        self.assertIn('user: "1000:1000"', section)
        self.assertIn("cap_drop:\n      - ALL", section)
        self.assertIn("no-new-privileges:true", section)
        self.assertIn('["alembic", "upgrade", "head"]', section)
        self.assertNotIn("\n    volumes:", section)
        for name in ("preflight", "api", "worker", "demo-seed"):
            with self.subTest(name=name):
                self.assertNotIn('user: "1000:1000"', service_section(name))

    def test_real_stack_checks_effective_identity_without_migrating_twice(self):
        source = (ROOT / ".github/workflows/performance-smoke.yml").read_text()
        self.assertIn("Verify unprivileged migration image and read-only DB access", source)
        self.assertIn("run --rm --no-deps -T migrate python -", source)
        for code in ('Path("/proc/1/status")',
                     'fields["Uid"] == ["1000"] * 4',
                     'fields["Gid"] == ["1000"] * 4',
                     'fields["CapEff"] == ["0000000000000000"]',
                     'fields["NoNewPrivs"] == ["1"]',
                     'db.execute(text("SELECT 1")).scalar_one() == 1'):
            self.assertIn(code, source)


if __name__ == "__main__":
    unittest.main()
