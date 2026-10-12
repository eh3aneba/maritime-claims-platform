"""No-network fail-closed regression coverage for real SFTP JUnit verifier."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree.ElementTree import Element, SubElement, tostring

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pilot_real_sftp_junit_evidence import (  # noqa: E402
    REQUIRED_CASES,
    VerificationError,
    main,
    verify_report,
)


def xml_report(suite: str, *, missing: str | None = None,
               extra: tuple[str, ...] = (),
               case_status: str | None = None) -> bytes:
    names = sorted(REQUIRED_CASES[suite] - ({missing} if missing else set()))
    names += list(extra)
    root = Element("testsuites")
    inner = SubElement(root, "testsuite", {
        "name": "pytest", "tests": str(len(names)),
        "errors": "0", "failures": "0",
        "skipped": "1" if case_status == "skipped" else "0",
    })
    for i, name in enumerate(names):
        case = SubElement(inner, "testcase", {
            "name": name, "classname": "tests.controlled_openssh",
        })
        if i == 0 and case_status is not None:
            SubElement(case, case_status)
    return tostring(root, encoding="utf-8")


class RealSftpJUnitCoverageTests(unittest.TestCase):
    def test_each_suite_complete_pass(self):
        for suite, expected in REQUIRED_CASES.items():
            self.assertEqual(verify_report(suite=suite, report_bytes=xml_report(suite)),
                             len(expected))

    def test_omitted_required_case_fails_even_if_junit_is_green(self):
        for suite, names in REQUIRED_CASES.items():
            with self.assertRaises(VerificationError):
                verify_report(suite=suite,
                              report_bytes=xml_report(suite, missing=next(iter(names))))

    def test_unknown_and_duplicate_required_case_rejected(self):
        suite = "initial_custody"
        case = next(iter(REQUIRED_CASES[suite]))
        with self.assertRaises(VerificationError):
            verify_report(suite="unknown", report_bytes=xml_report(suite))
        with self.assertRaises(VerificationError):
            verify_report(suite=suite,
                          report_bytes=xml_report(suite, extra=(case,)))

    def test_skip_error_and_failure_fail_closed(self):
        for status in ("skipped", "error", "failure"):
            with self.assertRaises(VerificationError):
                verify_report(suite="live_runtime",
                              report_bytes=xml_report("live_runtime", case_status=status))

    def test_empty_invalid_and_xml_entity_rejected(self):
        for invalid in (b"", b"<broken", b"<!DOCTYPE a><testsuite/>",
                        b"<!ENTITY x 'y'><testsuite/>", b"x" * (1024 * 1024 + 1)):
            with self.assertRaises(VerificationError):
                verify_report(suite="governed_nplus1", report_bytes=invalid)

    def test_count_mismatch_rejected(self):
        bad = xml_report("initial_custody").replace(b'tests="1"', b'tests="2"')
        with self.assertRaises(VerificationError):
            verify_report(suite="initial_custody", report_bytes=bad)

    def test_cli_writes_no_fixture_data_and_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "controlled.xml"
            args = ["--suite", "postgres_due_tick", "--report", str(p)]
            self.assertEqual(main(args), 2)
            p.write_bytes(xml_report("postgres_due_tick"))
            self.assertEqual(main(args), 0)
            p.write_bytes(xml_report("postgres_due_tick", case_status="skipped"))
            self.assertEqual(main(args), 2)


if __name__ == "__main__":
    unittest.main()
