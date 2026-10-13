"""Static policy coverage for selected database-only background services."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
NAMES = (
    "governance-webhook-worker",
    "external-evidence-scheduler-worker",
    "external-evidence-observation-worker",
    "external-evidence-review-projector-worker",
)

class WorkerRuntimeTests(unittest.TestCase):
    def test_selected_services_have_unprivileged_runtime(self):
        content = (ROOT / "docker-compose.yml").read_text()
        for name in NAMES:
            with self.subTest(name=name):
                section = re.split(r"(?m)^  [a-z][a-z0-9-]*:\\s*$", content.split("  " + name + ":\n", 1)[1], maxsplit=1)[0]
                self.assertIn('user: "1000:1000"', section)
                self.assertIn("cap_drop:\n      - ALL", section)
                self.assertIn("no-new-privileges:true", section)
                self.assertNotIn("local_documents:", section)

    def test_required_live_worker_checks_present(self):
        content = (ROOT / ".github/workflows/performance-smoke.yml").read_text()
        for name in NAMES:
            self.assertIn(name, content)
        for marker in ('Path("/proc/1/status")', 'pairs["NoNewPrivs"]',
                       'pairs["CapEff"]', 'SELECT 1', 'os.geteuid() == 1000'):
            self.assertIn(marker, content)

if __name__ == "__main__":
    unittest.main()
