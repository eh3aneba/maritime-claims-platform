"""No Docker/network regression suite for Pilot running-image identity readback."""
from __future__ import annotations

from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_running_image_identity as probe  # noqa: E402
import pilot_compose_readiness as readiness  # noqa: E402

SHA = "a" * 40
IMAGE = "sha256:" + "b" * 64
WRONG_IMAGE = "sha256:" + "c" * 64


def compose():
    items = []
    for i, service in enumerate(readiness.EXPECTED):
        status = {
            "Service": service, "ID": f"{i+1:064x}",
            "State": "exited" if service in readiness.ONESHOT else "running",
            "Health": "healthy" if service in readiness.HEALTHY else "none",
            "ExitCode": 0,
            "Name": "private-untrusted-hostname",
        }
        items.append(status)
    return items


class ImageIdentityReadbackTests(unittest.TestCase):
    def test_all_11_observed_healthy_and_identity_stable(self):
        before = compose()
        record = probe.evaluate_images(
            before=before, after=deepcopy(before),
            observed_image_ids={service: IMAGE for service in readiness.EXPECTED},
            expected={service: IMAGE for service in readiness.EXPECTED},
            release_sha=SHA,
        )
        self.assertTrue(record["all_running_image_ids_match_manifest"])
        self.assertEqual(record["matching_service_count"], 11)
        for key in ("source_sha_to_image_verified", "registry_image_digest_verified",
                    "expected_manifest_provenance_independently_verified",
                    "fresh_host_deployment_verified", "pilot_authorized"):
            self.assertIs(record[key], False)
        self.assertNotIn("private-untrusted-hostname", json.dumps(record))
        self.assertNotIn(IMAGE, json.dumps(record))
        self.assertNotIn("000000000", json.dumps(record))

    def test_mismatch_detected_not_represented_as_pass(self):
        before = compose()
        observed = {service: IMAGE for service in readiness.EXPECTED}
        observed["api"] = WRONG_IMAGE
        record = probe.evaluate_images(
            before=before, after=before, observed_image_ids=observed,
            expected={service: IMAGE for service in readiness.EXPECTED},
            release_sha=SHA,
        )
        self.assertFalse(record["all_running_image_ids_match_manifest"])
        self.assertEqual(record["matching_service_count"], 10)

    def test_stale_missing_duplicate_and_invalid_compose_rejected(self):
        before = compose()
        for after in (
            before[:-1],
            [{**entry, "ID": "f" * 64} if entry["Service"] == "api" else entry
             for entry in before],
            [*before, before[0]],
            [{**entry, "State": "restarting"} if entry["Service"] == "api"
             else entry for entry in before],
        ):
            with self.assertRaises(probe.ImageIdentityError):
                probe.evaluate_images(
                    before=before, after=after,
                    observed_image_ids={service: IMAGE for service in readiness.EXPECTED},
                    expected={service: IMAGE for service in readiness.EXPECTED},
                    release_sha=SHA,
                )
        before[0]["ID"] = "customer/id/unsafe"
        with self.assertRaises(probe.ImageIdentityError):
            probe._service_ids(before)

    def test_unapproved_or_incomplete_manifest_rejected(self):
        good = probe.manifest_template(SHA)
        good["expected_image_ids"] = {name: IMAGE for name in readiness.EXPECTED}
        self.assertEqual(probe.read_manifest(good, release_sha=SHA), good["expected_image_ids"])
        for mutate in (
            lambda x: x["expected_image_ids"].pop("worker"),
            lambda x: x["expected_image_ids"].update(api="repo:latest"),
            lambda x: x.update(candidate_release_sha="b" * 40),
            lambda x: x.update(unexpected_field="untrusted"),
        ):
            bad = deepcopy(good)
            mutate(bad)
            with self.assertRaises(probe.ImageIdentityError):
                probe.read_manifest(bad, release_sha=SHA)

    def test_inspect_reads_only_exact_container_and_sanitizes_errors(self):
        cid = "d" * 64
        good = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps([{"Id": cid, "Image": IMAGE,
                                "Config": {"Env": ["PASSWORD=secret"]}}]),
            stderr="private-token",
        )
        with patch.object(probe.subprocess, "run", return_value=good) as run:
            self.assertEqual(probe._inspect_one(cid), IMAGE)
            self.assertEqual(
                run.call_args.args[0],
                ["docker", "inspect", "--type", "container", cid],
            )
        failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="secret", stderr="private-token"
        )
        with patch.object(probe.subprocess, "run", return_value=failed):
            with self.assertRaises(probe.ImageIdentityError) as err:
                probe._inspect_one(cid)
        self.assertNotIn("secret", str(err.exception))

    def test_exclusive_draft_does_not_inspect_and_run_checks_private_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            draft = Path(td) / "manifest.json"
            args = ["--init", "--release-sha", SHA, "--output", str(draft)]
            with patch.object(probe, "observe", side_effect=AssertionError("must not read docker")):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(probe.main(args), 0)
            self.assertFalse(any(probe.manifest_template(SHA)["expected_image_ids"].values()))
            complete = json.loads(draft.read_text())
            complete["expected_image_ids"] = {name: IMAGE for name in readiness.EXPECTED}
            draft.write_text(json.dumps(complete))
            outfile = Path(td) / "observed.json"
            before = compose()
            with patch.object(probe, "observe", side_effect=[before, deepcopy(before)]), \
                 patch.object(probe, "inspect_image_ids",
                              return_value={name: IMAGE for name in readiness.EXPECTED}):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(probe.main([
                        "--verify", "--release-sha", SHA, "--manifest", str(draft),
                        "--env-file", ".env", "--output", str(outfile),
                    ]), 0)
            data = json.loads(outfile.read_text())
            self.assertTrue(data["all_running_image_ids_match_manifest"])
            self.assertFalse(data["source_sha_to_image_verified"])
            self.assertEqual(probe.main([
                "--verify", "--release-sha", SHA, "--manifest", str(draft),
                "--env-file", ".env", "--output", str(outfile),
            ]), 2)


if __name__ == "__main__":
    unittest.main()
