"""No-Docker/secret-free regression tests of synthetic Compose empty-state guard."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_demo_empty_stack as gate  # noqa: E402


def config():
    name = "mcri_synthetic_ci"
    return {
        "name": name,
        "volumes": {key: {"name": name + "_" + key}
                    for key in gate.EXPECTED_VOLUMES},
    }


def volumes():
    return [item["name"] for item in config()["volumes"].values()]


class EmptyComposeSafetyTests(unittest.TestCase):
    def test_unused_project_passes_even_if_unrelated_volumes_exist(self):
        gate.verify(config(), [], ["unrelated_other_volume"])
        self.assertEqual(gate._parse_containers(""), [])
        self.assertEqual(gate._parse_containers("[]"), [])

    def test_existing_stopped_running_and_unknown_service_containers_block(self):
        for containers in (
            [{"Service": "db", "State": "exited"}],
            [{"Service": "api", "State": "running"}],
            [{"Service": "unexpected", "State": "created"}],
        ):
            with self.subTest(containers=containers), self.assertRaises(gate.ExistingStackError):
                gate.verify(config(), containers, [])

    def test_all_three_persistent_volumes_block_even_without_containers(self):
        for volume in volumes():
            with self.subTest(volume=volume), self.assertRaises(gate.ExistingStackError):
                gate.verify(config(), [], [volume])

    def test_untrusted_external_renamed_and_missing_volume_definitions_fail(self):
        for make_bad in (
            lambda c: c["volumes"].pop("local_documents"),
            lambda c: c["volumes"]["postgres_data"].update(external=True),
            lambda c: c["volumes"]["postgres_data"].update(name="customer_data"),
            lambda c: c["volumes"]["clamav_data"].update(name="mcri_synthetic_ci_postgres_data"),
            lambda c: c.update(name="../bad"),
            lambda c: c.update(name=""),
        ):
            c = config()
            make_bad(c)
            with self.assertRaises(gate.ExistingStackError):
                gate.verify(c, [], [])

    def test_malformed_docker_inventory_or_container_response_fails_closed(self):
        for raw in ("invalid-JSON", "[{} ,", "[null]", "[3]", "{} garbage"):
            with self.subTest(raw=raw), self.assertRaises(gate.ExistingStackError):
                gate._parse_containers(raw)
        for inventory in (None, [None], ["path/private"], [""]):
            with self.assertRaises(gate.ExistingStackError):
                gate.verify(config(), [], inventory)

    def test_readonly_observe_calls_and_untrusted_outputs_not_logged(self):
        with patch.object(gate, "render_compose", return_value=config()):
            with patch.object(gate.subprocess, "run", side_effect=[
                CompletedProcess([], 0, "[]", ""),
                CompletedProcess([], 0, "unrelated_volume\n", ""),
            ]) as proc:
                gate.observe(env_file=Path(".env.ci"))
            calls = [c.args[0] for c in proc.call_args_list]
            self.assertEqual(calls[0], ["docker", "compose", "--env-file", ".env.ci",
                                         "-f", "docker-compose.yml", "ps", "--all", "--format", "json"])
            self.assertEqual(calls[1], ["docker", "volume", "ls", "--format", "{{.Name}}"])
        with patch.object(gate, "render_compose", return_value=config()):
            with patch.object(gate.subprocess, "run", return_value=CompletedProcess(
                [], 1, "customer-claim-private", "host-private-token"
            )):
                with self.assertRaises(gate.ExistingStackError) as e:
                    gate.observe(env_file=Path(".env.ci"))
                self.assertNotIn("customer-claim-private", str(e.exception))
                self.assertNotIn("host-private-token", str(e.exception))

    def test_strict_host_inventory_checks_all_containers_and_volumes_twice(self):
        responses = [
            CompletedProcess([], 0, "", ""),  # First global docker ps
            CompletedProcess([], 0, "", ""),  # First global docker volume ls
            CompletedProcess([], 0, "[]", ""),  # Compose project ps
            CompletedProcess([], 0, "", ""),  # Compose target volumes
            CompletedProcess([], 0, "", ""),  # Second global docker ps
            CompletedProcess([], 0, "", ""),  # Second global docker volume ls
        ]
        with patch.object(gate, "render_compose", return_value=config()), \
             patch.object(gate.subprocess, "run", side_effect=responses) as proc:
            gate.observe(
                env_file=Path(".env.ci"),
                strict_empty_docker_host=True,
            )
        commands = [call.args[0] for call in proc.call_args_list]
        self.assertEqual(commands, [
            ["docker", "ps", "--all", "--quiet"],
            ["docker", "volume", "ls", "--quiet"],
            ["docker", "compose", "--env-file", ".env.ci",
             "-f", "docker-compose.yml", "ps", "--all", "--format", "json"],
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            ["docker", "ps", "--all", "--quiet"],
            ["docker", "volume", "ls", "--quiet"],
        ])
        for call in proc.call_args_list:
            self.assertTrue(call.kwargs["capture_output"])
            self.assertFalse(call.kwargs["check"])
            self.assertNotIn("up", call.args[0])
            self.assertNotIn("rm", call.args[0])

    def test_strict_host_rejects_foreign_docker_objects_before_and_after(self):
        clean = CompletedProcess([], 0, "", "")
        cases = (
            (0, "private-container-id", "pre-existing containers"),
            (1, "private-volume-name", "pre-existing volumes"),
            (4, "new-private-container", "pre-existing containers"),
            (5, "new-private-volume", "pre-existing volumes"),
        )
        for index, private, category in cases:
            responses = [
                clean, clean,
                CompletedProcess([], 0, "[]", ""),
                clean,
                clean, clean,
            ]
            responses[index] = CompletedProcess([], 0, private + "\n", "")
            with self.subTest(index=index), \
                 patch.object(gate, "render_compose", return_value=config()), \
                 patch.object(gate.subprocess, "run", side_effect=responses):
                with self.assertRaises(gate.ExistingStackError) as caught:
                    gate.observe(
                        env_file=Path(".env.ci"), strict_empty_docker_host=True
                    )
                self.assertIn(category, str(caught.exception))
                self.assertNotIn(private, str(caught.exception))

    def test_strict_cli_reports_only_inventory_state_and_limits(self):
        out = io.StringIO()
        with patch.object(gate, "observe", return_value=None) as observe:
            with contextlib.redirect_stdout(out):
                self.assertEqual(gate.main([
                    "--env-file", ".env.ci", "--strict-empty-docker-host",
                ]), 0)
            observe.assert_called_once_with(
                env_file=Path(".env.ci"), strict_empty_docker_host=True
            )
        self.assertIn("STRICT DOCKER INVENTORY EMPTY", out.getvalue())
        self.assertIn("UNVERIFIED", out.getvalue())
        self.assertNotIn("private-container-id", out.getvalue())

    def test_timeout_and_invalid_config_fail_closed(self):
        with patch.object(gate.subprocess, "run", side_effect=TimeoutExpired([], 1)):
            with self.assertRaises(gate.ExistingStackError):
                gate._command(["docker", "volume", "ls"])
        with patch.object(gate, "render_compose", side_effect=RuntimeError("secret")):
            with self.assertRaises(gate.ExistingStackError) as e:
                gate.observe(env_file=Path(".env"))
            self.assertNotIn("secret", str(e.exception))

    def test_cli_only_reports_boolean_empty_state(self):
        output = io.StringIO()
        with patch.object(gate, "observe", return_value=None):
            with contextlib.redirect_stdout(output):
                self.assertEqual(gate.main(["--env-file", ".env.ci"]), 0)
        self.assertIn("PROJECT EMPTY", output.getvalue())
        with patch.object(gate, "observe", side_effect=gate.ExistingStackError("existing")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(gate.main(["--env-file", ".env.ci"]), 2)


if __name__ == "__main__":
    unittest.main()
