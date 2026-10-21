"""Offline fail-closed checks for the opt-in production UID rehearsal contract."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_nonroot_compose_gate as gate  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]


def _safe_rendered():
    port = lambda v: {"host_ip": "127.0.0.1", "target": v,
                      "published": str(v), "protocol": "tcp"}
    evidence = lambda: [{
        "type": "volume",
        "source": "maritime-claims-platform_local_documents",
        "target": "/data/documents",
    }]
    guarded = lambda: {
        "user": "1000:1000",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "volumes": evidence(),
    }
    return {"services": {
        "db": {"ports": [port(5432)]},
        "web": {"ports": [port(3000)]},
        "api": {**guarded(), "ports": [port(8000)]},
        "preflight": guarded(),
        "worker": guarded(),
        "clamav": {"expose": ["3310"]},
        "migrate": {"user": "1000:1000"},
    }}


class OptInNonrootComposeContractTests(unittest.TestCase):
    def test_only_allowlisted_uid_mount_and_private_ports_pass(self):
        self.assertEqual(gate.verify_optin_rendered_compose(_safe_rendered()), [])

    def test_missing_identity_capability_and_privileges_fail(self):
        for service in ("preflight", "api", "worker"):
            for field, value in (
                ("user", "0:0"),
                ("user", None),
                ("cap_drop", []),
                ("cap_drop", ["NET_ADMIN", "ALL"]),
                ("security_opt", []),
                ("privileged", True),
                ("cap_add", ["SYS_ADMIN"]),
                ("devices", ["/dev/sda:/dev/sda"]),
                ("pid", "host"),
                ("ipc", "host"),
                ("network_mode", "host"),
                ("userns_mode", "host"),
            ):
                with self.subTest(service=service, field=field, value=value):
                    cfg = _safe_rendered()
                    cfg["services"][service][field] = value
                    self.assertTrue(gate.verify_optin_rendered_compose(cfg))

    def test_non_volume_bind_different_source_and_writable_rules_fail(self):
        for bad in (
            [],
            [{"type": "bind", "source": "/home/user/data", "target": "/data/documents"}],
            [{"type": "volume", "source": "somebody_else", "target": "/data/documents"}],
            [{"type": "volume", "source": "local_documents_other", "target": "/data/documents"}],
            [{"type": "volume", "source": "local_documents", "target": "/tmp/evidence"}],
            [{"type": "volume", "source": "local_documents", "target": "/data/documents",
              "read_only": True}],
            [{"type": "volume", "source": "local_documents", "target": "/data/documents"}] * 2,
        ):
            with self.subTest(bad=bad):
                cfg = _safe_rendered()
                cfg["services"]["worker"]["volumes"] = bad
                self.assertIn("worker:evidence_mount_unexpected",
                              gate.verify_optin_rendered_compose(cfg))

    def test_synthetic_host_exposure_and_incomplete_service_rejected(self):
        for operation in ("public_api", "extra_malware_port", "missing_worker"):
            cfg = _safe_rendered()
            if operation == "public_api":
                cfg["services"]["api"]["ports"][0]["host_ip"] = "0.0.0.0"
            elif operation == "extra_malware_port":
                cfg["services"]["clamav"]["ports"] = [{
                    "host_ip": "0.0.0.0", "target": 3310, "published": "3310",
                }]
            else:
                del cfg["services"]["worker"]
            self.assertTrue(gate.verify_optin_rendered_compose(cfg))
        self.assertTrue(gate.verify_optin_rendered_compose([]))

    def test_render_command_is_fixed_and_never_exposes_expanded_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            env = Path(td) / ".env"
            env.write_text("SECRET_KEY=sensitive-value", encoding="utf-8")
            with patch.object(gate.subprocess, "run", return_value=CompletedProcess(
                [], 0, json.dumps(_safe_rendered()), "untrusted-SECRET"
            )) as invoke:
                result = gate.render_optin_compose(env_file=env)
            self.assertEqual(gate.verify_optin_rendered_compose(result), [])
            command = invoke.call_args.args[0]
            self.assertEqual(command[0:2], ["docker", "compose"])
            self.assertIn(str(gate._OVERLAY), command)
            self.assertIn(str(gate._COMPOSE), command)
            self.assertEqual(command[-3:], ["config", "--format", "json"])

            for failure in (
                CompletedProcess([], 1, "sensitive-value", "sensitive-value"),
                CompletedProcess([], 0, "sensitive-value", ""),
            ):
                with patch.object(gate.subprocess, "run", return_value=failure):
                    with self.assertRaises(RuntimeError) as context:
                        gate.render_optin_compose(env_file=env)
                    self.assertNotIn("sensitive-value", str(context.exception))
            with patch.object(gate.subprocess, "run",
                              side_effect=TimeoutExpired([], 45, stderr="sensitive-value")):
                with self.assertRaises(RuntimeError) as context:
                    gate.render_optin_compose(env_file=env)
                self.assertNotIn("sensitive-value", str(context.exception))

    def test_manual_gate_requires_explicit_flag_and_never_starts_containers(self):
        with patch.object(gate, "render_optin_compose") as rendered:
            with contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(gate.main([]), 2)
            rendered.assert_not_called()
            self.assertIn("NO-GO", output.getvalue())
        with patch.object(gate, "render_optin_compose", return_value=_safe_rendered()):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(gate.main(["--verify-optin-nonroot-config"]), 0)
            self.assertIn("NOT proof of runtime identity", output.getvalue())
            self.assertIn("Pilot GO", output.getvalue())

    def test_default_compose_stays_unmigrated_and_overlay_is_exact(self):
        base = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        overlay = (_ROOT / "docker-compose.nonroot-optin.yml").read_text(encoding="utf-8")
        self.assertIn("services:", overlay)
        self.assertEqual(overlay.count('user: "1000:1000"'), 3)
        for service in ("preflight", "api", "worker"):
            self.assertIn(f"  {service}:\n", overlay)
        self.assertNotIn("chown", overlay.replace("ownership", ""))
        self.assertNotIn("chmod", overlay)
        self.assertNotIn("volume:", overlay)
        self.assertIn("  api:\n", base)
        self.assertIn("  worker:\n", base)
        self.assertIn("  preflight:\n", base)
        self.assertIn("python -m app.core.evidence_volume_uid_audit",
                      (_ROOT / "docs/operations/EVIDENCE_UID_MIGRATION_PRECHECK.md")
                      .read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
