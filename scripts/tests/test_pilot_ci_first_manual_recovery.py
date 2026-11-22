"""Offline regressions for narrow first-manual hosted-recovery admission."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ci_first_manual_recovery as guard
import pilot_ci_independent_postgres as independent
import pilot_ci_lineage_reconcile as lineage
import pilot_ci_restore_probe as restore
import pilot_ci_resume_probe as resume


def env():
    return {
        "APP_ENV": "pilot",
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        guard.MARKER: "1",
        "MCRI_CI_RESTORE_PROBE": "1",
        "MCRI_CI_RESUME_PROBE": "1",
        "POSTGRES_DB": guard.DB,
        "POSTGRES_USER": guard.DB,
        "POSTGRES_PASSWORD": "fictional-ci-password",
        "DATABASE_URL": "postgresql+psycopg://mcri_performance:fictional-ci-password@db:5432/mcri_performance",
        "NEXT_PUBLIC_API_BASE_URL": "http://127.0.0.1:8000/api/v1",
        "MCRI_DEMO_ORG_SLUG": "pilot",
        "MCRI_DEMO_EMAIL": "manager@demo.mcri.app",
        "MCRI_DEMO_PASSWORD": "fictional-demo-password",
        "MCRI_SYNTHETIC_ONLY_CONFIRM": "YES",
        "AI_PROVIDER": "disabled",
        "AI_MODEL": "",
        "OPENAI_API_KEY": "",
        "ALLOW_EXTERNAL_AI_RESTRICTED": "false",
        "AI_LOCAL_EXPERIMENTAL_ENABLED": "false",
        "AI_PRODUCTION_CONTROL_PLANE_ENABLED": "false",
        "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED": "false",
        "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED": "false",
        "OCR_ENABLED": "false",
        "MALWARE_SCAN_ENABLED": "true",
        "STORAGE_BACKEND": "local",
    }


class FirstManualRecoveryTests(unittest.TestCase):
    def test_exact_ci_file_flags_and_namespace_required(self):
        values = env()
        with patch.object(guard, "load", return_value=values):
            self.assertTrue(guard.admitted_source(guard.ENV_FILE, values))
            restore.validate_guard(guard.ENV_FILE, values)
            resume.validate_guard(env_file=guard.ENV_FILE, env=values, release_sha="a" * 40)
            self.assertEqual(independent._valid_env(values, "a" * 40), values["POSTGRES_PASSWORD"])
            self.assertFalse(guard.admitted_source(".env", values))
            for key, bad in (
                ("RUNNER_ENVIRONMENT", "self-hosted"),
                ("GITHUB_ACTIONS", "false"),
                (guard.MARKER, "0"),
                ("APP_ENV", "production"),
                ("POSTGRES_DB", "customer"),
                ("OCR_ENABLED", "true"),
                ("AI_PROVIDER", "openai"),
                ("EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED", "true"),
                ("DOCKER_HOST", "tcp://foreign:2375"),
                ("COMPOSE_PROJECT_NAME", "foreign"),
                ("COMPOSE_ENV_FILES", ".env"),
            ):
                with self.subTest(key=key):
                    self.assertFalse(guard.admitted_source(guard.ENV_FILE, {**values, key: bad}))
            self.assertFalse(guard.admitted_source(guard.ENV_FILE, {
                **values, "MCRI_DEMO_PASSWORD": "changed-ambient-password",
            }))

    def test_manual_reserve_empty_and_all_other_required_families_preserved(self):
        def query(_, sql):
            return "[]" if "FROM reserve_history " in sql else '[{"id":"fictional-row"}]'
        source = lineage.collect_lineage("ci", query, first_manual=True)
        self.assertEqual(source["reserve_history"][0], 0)
        self.assertEqual(lineage.reconcile(source, source)["lineage_families_compared"], len(lineage.ALL_TABLES))
        with self.assertRaises(lineage.LineageError):
            lineage.collect_lineage("ci", query)
        with self.assertRaises(lineage.LineageError):
            lineage.collect_lineage("ci", lambda *_: '[{"id":"seeded-reserve"}]', first_manual=True)

    def test_manual_backup_cannot_export_transfer_or_touch_docker_before_admission(self):
        values = env()
        with patch.object(guard, "load", return_value=values), \
             patch.object(restore, "_run") as command:
            with self.assertRaises(restore.ProbeError):
                restore.observe(env_file=guard.ENV_FILE, env=values,
                                cross_runner_output=Path("synthetic-recovery-transfer"))
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
