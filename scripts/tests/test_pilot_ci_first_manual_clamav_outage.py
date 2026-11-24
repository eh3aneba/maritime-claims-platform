"""Offline fail-closed tests for hosted synthetic ClamAV outage drill."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ci_first_manual_clamav_outage as c
import pilot_ci_first_manual_fault_probe as p


class ClamavOutageTests(unittest.TestCase):
    def test_scope_refuses_non_hosted_pilot_before_commands(self):
        with patch.object(c, "admitted_source", return_value=False), \
             patch.object(p, "run") as execute:
            with self.assertRaises(p.FaultProbeError):
                c.check_marker({"MCRI_CI_FIRST_MANUAL_CLAMAV_FAULT": "1"})
            execute.assert_not_called()

    def test_scanner_outage_must_be_actual_exited_service(self):
        good = {"db": {"pass": True}, "worker": {"pass": True},
                "clamav": {"observed": True, "status": "exited", "pass": False}}
        with patch.object(p, "status", return_value=([], {
            "compose_status_complete": False, "services": good
        })):
            c.scanner_down("a"*40)
        for broken in (
            {**good, "clamav": {"observed": True, "status": "running", "pass": True}},
            {**good, "worker": {"pass": False}},
        ):
            with patch.object(p, "status", return_value=([], {
                "compose_status_complete": False, "services": broken
            })), self.assertRaises(p.FaultProbeError):
                c.scanner_down("a"*40)

    def test_no_real_http_2xx_accepted_as_outage_proof(self):
        class Resp:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, *_): return b""
        class Opener:
            def open(self, *a, **k): return Resp()
        with patch.object(c, "_login", return_value="a"*36), \
             patch.object(c.urllib.request, "build_opener", return_value=Opener()):
            with self.assertRaises(p.FaultProbeError):
                c.upload_must_quarantine({})

    def test_only_http_503_qualifies_as_failed_closed(self):
        class Opener:
            def __init__(self, code): self.code = code
            def open(self, req, timeout=20):
                raise urllib.error.HTTPError("http://localhost/", self.code, "synthetic", None, None)
        with patch.object(c, "_login", return_value="a"*36):
            for code in (400, 401, 404, 409, 422, 500):
                with self.subTest(code=code), \
                     patch.object(c.urllib.request, "build_opener", return_value=Opener(code)):
                    with self.assertRaises(p.FaultProbeError):
                        c.upload_must_quarantine({})


if __name__ == "__main__":
    unittest.main()
