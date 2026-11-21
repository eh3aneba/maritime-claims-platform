"""Offline evidence-boundary contract for signed Alpine APK observation."""
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts import observe_signed_alpine_openssl as probe

ID = "sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64
HASHES = {"libcrypto3": "c" * 64, "libssl3": "d" * 64}
OUTPUT = "\n".join(
    f"{value}  {name}-{probe.VERSION}.apk" for name, value in HASHES.items()
)


class SignedOpenSSLObservationTests(unittest.TestCase):
    def test_exact_package_bytes_and_platform_are_reported_without_approval(self):
        for arch, docker_arch in probe.ARCH.items():
            with self.subTest(arch=arch), patch.object(
                probe, "run", side_effect=["", f"{ID}|{docker_arch}|alpine@{DIGEST}", OUTPUT]
            ) as run:
                record = probe.observe(arch)
                self.assertEqual(record["packages_sha256"], HASHES)
                self.assertEqual(record["trust_image_local_id"], ID)
                self.assertEqual(record["trust_image_registry_digest"], DIGEST)
                self.assertEqual(record["architecture"], arch)
                self.assertTrue(record["apk_verify_passed_using_image_trust_keys"])
                for field in (
                    "independent_trust_key_authentication_completed",
                    "deployed_binary_matches_signed_apk",
                    "source_patch_build_provenance_verified",
                    "security_owner_approval", "pilot_authorized",
                ):
                    self.assertIs(record[field], False)
                command = run.call_args.args[0]
                self.assertEqual(command[-3], ID)
                self.assertIn("--read-only", command)
                self.assertIn("--cap-drop", command)
                self.assertNotIn("--privileged", command)
                self.assertNotIn("--mount", command)
                self.assertNotIn("--volume", command)
                self.assertTrue(run.call_args.kwargs["check_diagnostics"])

    def test_exact_arch_image_and_registry_reference_are_required(self):
        for value in (
            f"{ID}|arm64|alpine@{DIGEST}",
            f"{ID}|amd64|different-image@{DIGEST}",
            "sha256:fake|amd64|alpine@" + DIGEST,
            f"{ID}|amd64|alpine@bad",
            f"{ID}|amd64|alpine@{DIGEST}|unexpected",
        ):
            with self.subTest(value=value), self.assertRaises(probe.ObservationError):
                probe.parse_image(value, "x86_64")
        self.assertEqual(
            probe.parse_image(f"{ID}|amd64|docker.io/library/alpine@{DIGEST}", "x86_64"),
            (ID, DIGEST),
        )
        with patch.object(probe, "run") as run:
            with self.assertRaises(probe.ObservationError):
                probe.observe("s390x")
            run.assert_not_called()

    def test_missing_duplicate_wrong_version_or_additional_output_is_rejected(self):
        for value in (
            "", OUTPUT.splitlines()[0],
            OUTPUT + "\n" + OUTPUT.splitlines()[0],
            OUTPUT.replace("3.5.9-r1", "3.5.10-r0"),
            OUTPUT.replace("libssl3", "openssl"),
            OUTPUT + "\nWARNING: signature cannot be verified",
            OUTPUT.replace("d" * 64, "d" * 63),
        ):
            with self.subTest(value=value), self.assertRaises(probe.ObservationError):
                probe.parse_hashes(value)

    def test_nonzero_and_unsafe_diagnostics_fail_even_if_hashes_look_valid(self):
        for status, stderr in (
            (1, ""), (0, "WARNING: repository verification failed"),
            (0, "ERROR: index"), (0, "untrusted"),
            (0, "bad signature"), (0, "invalid signature"),
        ):
            with self.subTest(status=status, stderr=stderr), patch.object(
                probe.subprocess, "run", return_value=subprocess.CompletedProcess(
                    ["docker"], status, OUTPUT, stderr
                )
            ):
                with self.assertRaises(probe.ObservationError):
                    probe.run(["docker"], 1, check_diagnostics=True)
        with patch.object(
            probe.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["docker"], 0, OUTPUT, "libssl3-3.5.9-r1.apk: OK"
            )
        ):
            self.assertEqual(probe.run(["docker"], 1, check_diagnostics=True), OUTPUT)

    def test_fetch_and_signature_verify_never_install_or_bypass_trust(self):
        self.assertIn(probe.REPOSITORY, probe.SHELL)
        self.assertIn("apk --no-cache --repositories-file /tmp/repos fetch", probe.SHELL)
        self.assertIn("apk verify", probe.SHELL)
        self.assertIn("sha256sum", probe.SHELL)
        for forbidden in (
            "--allow-untrusted", "--check-certificate=no", "apk add",
            "apk upgrade", "/etc/apk/keys/", "/edge/",
        ):
            self.assertNotIn(forbidden, probe.SHELL)


if __name__ == "__main__":
    unittest.main()
