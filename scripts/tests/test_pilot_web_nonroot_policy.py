"""Offline invariant check; real UID/filesystem behavior is proven by live smoke."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "apps" / "web" / "Dockerfile"
PERF = ROOT / ".github" / "workflows" / "performance-smoke.yml"
COMPOSE = ROOT / "docker-compose.yml"


class WebLeastPrivilegeContractTests(unittest.TestCase):
    def test_only_final_production_runner_switches_to_stable_uid_gid(self):
        source = DOCKERFILE.read_text(encoding="utf-8")
        parts = source.split("FROM node:22-alpine3.24 AS runner")
        self.assertEqual(len(parts), 2)
        runtime = parts[1]
        self.assertRegex(runtime, r"(?m)^USER 1000:1000$")
        self.assertLess(runtime.index("COPY --from=builder"), runtime.index("USER 1000:1000"))
        self.assertLess(runtime.index("USER 1000:1000"), runtime.index('CMD ["node", "server.js"]'))
        self.assertNotRegex(runtime, r"(?m)^USER (?:root|0)(?::0)?$")
        self.assertNotRegex(runtime, r"(?m)^\s*RUN.*(?:chmod 777|chmod -R 777)")
        self.assertIn("chown 1000:1000 /app/.next/cache", runtime)
        self.assertIn("chmod 0700 /app/.next/cache", runtime)
        self.assertNotIn("chown -R 1000:1000 /app", runtime)

    def test_compose_restricts_only_web_linux_privileges(self):
        source = COMPOSE.read_text(encoding="utf-8")
        before, web = source.split("\n  web:\n", 1)
        web = web.split("\n  demo-seed:\n", 1)[0]
        self.assertIn("    cap_drop:\n      - ALL\n", web)
        self.assertIn("    security_opt:\n      - no-new-privileges:true\n", web)
        # This rollout is Web-only: do not suggest other services are hardened.
        self.assertNotIn("no-new-privileges:true", before)
        self.assertNotIn("cap_drop:", before)

    def test_live_smoke_inspects_actual_main_process_privileges(self):
        source = PERF.read_text(encoding="utf-8")
        self.assertIn("CapEff:", source)
        self.assertIn("NoNewPrivs:", source)
        self.assertIn('0000000000000000', source)
        self.assertGreaterEqual(source.count("/proc/1/status"), 2)

    def test_required_live_smoke_checks_effective_uid_and_write_scope(self):
        workflow = PERF.read_text(encoding="utf-8")
        self.assertIn("Verify live Web container non-root runtime and write boundary",
                      workflow)
        self.assertIn("docker compose --env-file .env.performance exec -T web",
                      workflow)
        for bound in (
            '[ "$(id -u)" = "1000" ]',
            '[ "$(id -g)" = "1000" ]',
            "[ -w /app/.next/cache ]",
            "[ ! -w /app/server.js ]",
            "[ ! -w /app/.next/server ]",
            "[ ! -w /app/public ]",
        ):
            with self.subTest(bound=bound):
                self.assertIn(bound, workflow)


if __name__ == "__main__":
    unittest.main()
