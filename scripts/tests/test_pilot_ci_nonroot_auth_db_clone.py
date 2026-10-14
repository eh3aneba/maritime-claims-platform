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
