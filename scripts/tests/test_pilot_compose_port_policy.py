"""Offline regression suite for rendered private pilot Compose host-port policy."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess, TimeoutExpired

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot_compose_port_policy import main, render_compose, verify  # noqa: E402


def safe_config():
    return {"services": {
        "db": {"ports": [{"host_ip": "127.0.0.1", "target": 5432, "published": "5432", "protocol": "tcp"}]},
        "api": {"ports": [{"host_ip": "127.0.0.1", "target": 8000, "published": "8000", "protocol": "tcp"}]},
        "web": {"ports": [{"host_ip": "127.0.0.1", "target": 3000, "published": "3000", "protocol": "tcp"}]},
        "clamav": {"expose": ["3310"]},
        "migrate": {}, "worker": {}, "preflight": {},
    }}


class PrivatePilotPortPolicyTests(unittest.TestCase):
    def test_exact_private_pilot_mapping_succeeds(self):
        self.assertEqual([], verify(safe_config()))

    def test_omitted_host_ip_wildcard_and_non_loopback_fail(self):
        for host_ip in (None, "", "0.0.0.0", "::", "192.168.1.20", "::1"):
            config = safe_config()
            config["services"]["db"]["ports"][0]["host_ip"] = host_ip
            self.assertTrue(verify(config), host_ip)

    def test_unexpected_or_dynamic_mappings_fail(self):
        for change in (
            {"published": "0"}, {"published": "8001"},
            {"target": 8001}, {"protocol": "udp"},
        ):
            config = safe_config()
            config["services"]["api"]["ports"][0].update(change)
            self.assertTrue(verify(config), change)
        config = safe_config()
        config["services"]["clamav"]["ports"] = [
            {"host_ip": "127.0.0.1", "target": 3310, "published": "3310"}
        ]
        self.assertTrue(verify(config))

    def test_duplicate_or_missing_service_bindings_fail(self):
        config = safe_config()
        config["services"]["db"]["ports"] *= 2
        self.assertTrue(verify(config))
        config = safe_config()
        del config["services"]["web"]
        self.assertTrue(verify(config))
        config = safe_config()
        config["services"]["web"]["ports"] = []
        self.assertTrue(verify(config))

    def test_host_network_and_unrendered_config_fail(self):
        config = safe_config()
        config["services"]["worker"]["network_mode"] = "host"
        self.assertTrue(verify(config))
        config = safe_config()
        config["services"]["db"]["ports"] = ["127.0.0.1:5432:5432"]
        self.assertTrue(verify(config))
        self.assertTrue(verify({"services": []}))

    def test_compose_failure_never_surfaces_secret_content(self):
        with tempfile.TemporaryDirectory() as td:
            env = Path(td) / ".env"
            compose = Path(td) / "docker-compose.yml"
            env.write_text("SECRET_KEY=secret-canary")
            compose.write_text("services: {}")
            with patch("pilot_compose_port_policy.subprocess.run", return_value=CompletedProcess(
                [], 1, "secret-canary", "secret-canary",
            )):
                with self.assertRaisesRegex(RuntimeError, "Docker Compose rejected") as context:
                    render_compose(env_file=env, compose_file=compose)
                self.assertNotIn("secret-canary", str(context.exception))
            with patch("pilot_compose_port_policy.subprocess.run", side_effect=TimeoutExpired([], 1)):
                with self.assertRaisesRegex(RuntimeError, "unavailable"):
                    render_compose(env_file=env, compose_file=compose)

    def test_cli_calls_rendered_compose_not_static_yaml(self):
        with patch("pilot_compose_port_policy.render_compose", return_value=safe_config()):
            self.assertEqual(0, main(["--env-file", ".env.pilot.example"]))
        config = safe_config()
        config["services"]["web"]["ports"][0]["host_ip"] = "0.0.0.0"
        with patch("pilot_compose_port_policy.render_compose", return_value=config):
            self.assertEqual(1, main(["--env-file", ".env.pilot.example"]))


if __name__ == "__main__":
    unittest.main()
