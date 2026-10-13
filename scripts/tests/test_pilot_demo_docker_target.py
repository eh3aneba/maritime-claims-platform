"""Offline tests for the local-only synthetic MT ORION Docker Engine boundary."""
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
import pilot_demo_docker_target as target  # noqa: E402


def context(host="unix:///var/run/docker.sock"):
    return [{"Name": "default", "Endpoints": {"docker": {"Host": host}}}]


class LocalDemoDockerTargetTests(unittest.TestCase):
    def test_local_unix_socket_and_desktop_pipe_are_allowed(self):
        target.verify({}, context())
        target.verify({}, context("unix:///run/user/1000/docker.sock"))
        target.verify({}, context("npipe:////./pipe/docker_engine"))

    def test_remote_daemon_types_are_rejected(self):
        for endpoint in (
            "ssh://docker-host.internal", "tcp://10.0.0.4:2376",
            "http://10.0.0.4:2375", "https://service.example:2376",
            "unix://server/share/docker.sock", "unix:///tmp/../unsafe.sock",
            "unix:///run/docker.sock?context=unsafe",
            "", "not-an-endpoint", "unix:///run/secret\nsocket",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(
                target.DockerTargetError
            ):
                target.verify({}, context(endpoint))

    def test_every_inherited_destination_override_blocks_even_if_empty(self):
        for key in target.BLOCKED:
            with self.subTest(key=key), self.assertRaises(
                target.DockerTargetError
            ):
                target.verify({key: ""}, context())
            with self.assertRaises(target.DockerTargetError):
                target.verify({key: "malicious"}, context())

    def test_invalid_context_inventory_rejected_without_crashing(self):
        for value in (None, [], {}, [None], [{}], [{"Endpoints": {}}],
                      context("unix:///var/run/docker.sock") * 2):
            with self.subTest(value=type(value).__name__), self.assertRaises(
                target.DockerTargetError
            ):
                target.verify({}, value)

    def test_observe_readonly_and_never_reports_remote_destination(self):
        private = "ssh://private-user@secret-host.invalid"
        with patch.dict(target.os.environ, {}, clear=True):
            with patch.object(target.subprocess, "run", return_value=CompletedProcess(
                [], 0, json.dumps(context(private)), ""
            )) as proc:
                with self.assertRaises(target.DockerTargetError) as caught:
                    target.observe()
                self.assertNotIn("secret-host", str(caught.exception))
                self.assertEqual(proc.call_args.args[0], [
                    "docker", "context", "inspect",
                ])
                self.assertFalse(proc.call_args.kwargs.get("shell", False))
            with patch.object(target.subprocess, "run", return_value=CompletedProcess(
                [], 0, json.dumps(context()), ""
            )):
                target.observe()

    def test_invalid_json_nonzero_exit_and_timeout_fail_closed(self):
        for case in (
            CompletedProcess([], 1, "secret-private-output", "secret"),
            CompletedProcess([], 0, '{"incomplete":', ""),
            CompletedProcess([], 0, "x" * 66000, ""),
        ):
            with patch.dict(target.os.environ, {}, clear=True):
                with patch.object(target.subprocess, "run", return_value=case):
                    with self.assertRaises(target.DockerTargetError) as caught:
                        target.observe()
                    self.assertNotIn("secret", str(caught.exception))
        with patch.dict(target.os.environ, {}, clear=True):
            with patch.object(target.subprocess, "run", side_effect=TimeoutExpired([], 1)):
                with self.assertRaises(target.DockerTargetError):
                    target.observe()

    def test_cli_has_only_bool_boundary_and_no_raw_hostname(self):
        output = io.StringIO()
        with patch.object(target, "observe", return_value=None):
            with contextlib.redirect_stdout(output):
                self.assertEqual(target.main(), 0)
            self.assertNotIn("secret", output.getvalue())
            self.assertIn("UNVERIFIED", output.getvalue())
        with patch.object(target, "observe", side_effect=target.DockerTargetError("no-go")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(target.main(), 2)


if __name__ == "__main__":
    unittest.main()
