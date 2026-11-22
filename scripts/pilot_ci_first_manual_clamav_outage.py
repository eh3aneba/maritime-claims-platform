#!/usr/bin/env python3
"""Synthetic hosted CI ClamAV outage: upload fail-closed quarantine and recovery.

Executes only after a successful, bounded MT ORION rollback and API/worker
fault rehearsal. Never manipulates customer data, secrets or external alarms.
It does not reprocess quarantined bytes or authorize an operator release.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import http.cookiejar
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

from hm_multidoc_packs import make_docx_bytes
import pilot_ci_first_manual_fault_probe as probe
from pilot_ci_first_manual_recovery import ENV_FILE, admitted_source
from pilot_running_image_identity import inspect_image_ids, _service_ids

API = "http://127.0.0.1:8000/api/v1"
PROOF = Path("artifacts/first-manual-ci/fault-detection.json")
OUTPUT = Path("artifacts/first-manual-ci/clamav-outage.json")
BASENAME = "synthetic-ci-scanner-unavailable.docx"
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SYNTHETIC_LINES = (
    "FICTIONAL MT ORION: scanner-outage safety check only.",
    "Turbocharger failure evidence must not be admitted without a malware scan.",
    "No real customer material or operational assessment is contained here.",
)
IN_CONTAINER = r"""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
from app.modules.documents.malware import ping_clamd, scan_file, MalwareScanVerdict
assert os.getenv("APP_ENV") == "pilot"
assert os.getenv("MALWARE_SCAN_ENABLED", "").lower() == "true"
assert os.getenv("CLAMAV_HOST", "clamav") == "clamav"
assert os.getenv("CLAMAV_PORT", "3310") == "3310"
ping_clamd(host="clamav", port=3310, timeout_seconds=15)
with TemporaryDirectory(prefix="mcri-ci-scanner-restored-") as tmp:
    target = Path(tmp) / "synthetic.txt"
    target.write_bytes(b"FICTIONAL MT ORION scanner recovered.")
    assert scan_file(target, host="clamav", port=3310, timeout_seconds=15).verdict is MalwareScanVerdict.CLEAN
    target.write_bytes(b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*')
    assert scan_file(target, host="clamav", port=3310, timeout_seconds=15).verdict is MalwareScanVerdict.INFECTED
"""


def check_marker(env: dict) -> str:
    probe.demand(env.get("MCRI_CI_FIRST_MANUAL_CLAMAV_FAULT") == "1"
                 and admitted_source(ENV_FILE, env), "clamav_hosted_scope_denied")
    sha = probe.run(["git", "rev-parse", "HEAD"], "clamav_source_identity")
    probe.demand(PROOF.is_file() and not PROOF.is_symlink()
                 and PROOF.stat().st_size < 8192, "prior_fault_proof_missing")
    try:
        previous = json.loads(PROOF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise probe.FaultProbeError("prior_fault_proof_invalid") from None
    probe.demand(previous.get("schema") == "mcri-first-manual-hosted-fault-probe-v1"
                 and previous.get("candidate_sha") == sha
                 and previous.get("real_compose_outage_detected_count") == 2
                 and previous.get("originals_and_business_lineage_preserved") is True
                 and previous.get("pilot_authorized") is False,
                 "prior_fault_proof_not_complete")
    return sha


def scanner_down(sha: str) -> None:
    _, status = probe.status(sha)
    scanner = status["services"]["clamav"]
    probe.demand(not status["compose_status_complete"]
                 and scanner["observed"]
                 and scanner["status"] == "exited"
                 and scanner["pass"] is False,
                 "scanner_outage_not_detected")
    # The database and document worker must not be explicitly stopped.
    probe.demand(status["services"]["db"]["pass"]
                 and status["services"]["worker"]["pass"],
                 "unrelated_core_service_failed")


def _login(opener, env: dict) -> str:
    payload = json.dumps({
        "organization_slug": env["MCRI_DEMO_ORG_SLUG"],
        "email": env["MCRI_DEMO_EMAIL"],
        "password": env["MCRI_DEMO_PASSWORD"],
    }).encode("utf-8")
    request = urllib.request.Request(
        API + "/auth/login", data=payload, method="POST",
        headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=10) as response:
        probe.demand(response.status == 200, "synthetic_login_failed")
    with opener.open(API + "/claims?search=MCRI-DEMO-MT-ORION", timeout=10) as response:
        raw = response.read(65536)
        data = json.loads(raw)
    probe.demand(data.get("total") == 1
                 and len(data.get("items", [])) == 1
                 and data["items"][0].get("external_reference") == "MCRI-DEMO-MT-ORION",
                 "synthetic_claim_scope_invalid")
    return data["items"][0]["id"]


def upload_must_quarantine(env: dict) -> str:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    claim_id = _login(opener, env)
    payload = make_docx_bytes(list(SYNTHETIC_LINES))
    digest = sha256(payload).hexdigest()
    boundary = b"----seeclaims-synthetic-clamav-fault"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="document_type"\r\n\r\n'
        b"chief_engineer_report\r\n"
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="' + BASENAME.encode("ascii") + b'"\r\n'
        b"Content-Type: " + MIME.encode("ascii") + b"\r\n\r\n"
        + payload + b"\r\n--" + boundary + b"--\r\n"
    )
    request = urllib.request.Request(
        API + "/claims/" + claim_id + "/documents",
        data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary.decode("ascii")},
    )
    try:
        with opener.open(request, timeout=20) as response:
            response.read(1024)
            raise probe.FaultProbeError("scanner_outage_upload_accepted")
    except urllib.error.HTTPError as exc:
        # Do not read, log or expose response text, tokens or references.
        probe.demand(exc.code == 503, "scanner_outage_not_http_503")
        exc.close()
    return digest


def _quarantine_count(digest: str) -> str:
    probe.demand(len(digest) == 64 and all(c in "0123456789abcdef" for c in digest),
                 "invalid_fixture_digest")
    sql = (
        "SELECT COUNT(*) FROM quarantined_uploads q JOIN claims c ON c.id=q.claim_id "
        "WHERE c.external_reference='MCRI-DEMO-MT-ORION' "
        "AND q.status='scan_error' AND q.file_hash='" + digest + "';"
    )
    return probe.rollback.query("unused", sql)


def observe(env: dict) -> dict:
    sha = check_marker(env)
    probe.docker_target.observe()
    probe.demand(probe.healthy(sha), "clamav_initial_stack_not_ready")
    initial, _ = probe.status(sha)
    images = inspect_image_ids(initial)
    ids = _service_ids(initial)
    family, audit, alembic = probe.rollback.snapshot()
    originals = probe.rollback.read_originals(env)
    probe.demand(probe.rollback.query("unused", "SELECT COUNT(*) FROM quarantined_uploads;") == "0",
                 "synthetic_quarantine_not_empty")
    stopped = False
    restarted = False
    try:
        probe.compose("stop", "clamav", timeout=90)
        stopped = True
        scanner_down(sha)
        digest = upload_must_quarantine(env)
        probe.demand(_quarantine_count(digest) == "1", "no_single_scan_error_quarantine")
        probe.demand(probe.rollback.query("unused", "SELECT COUNT(*) FROM documents;") == "2",
                     "quarantined_upload_promoted_to_evidence")
        probe.compose("start", "clamav", timeout=90)
        restarted = True
        for attempt in range(60):
            if probe.healthy(sha):
                break
            if attempt < 59:
                time.sleep(3)
        else:
            raise probe.FaultProbeError("clamav_recovery_unhealthy")
    finally:
        if stopped and not restarted:
            try:
                probe.compose("start", "clamav", timeout=90)
            except probe.FaultProbeError:
                pass

    # Validate real ClamAV clean/infected verdicts from the restored scanner.
    probe.run(["docker", "compose", "--project-directory", str(probe.ROOT),
               "--env-file", str(probe.ROOT / ENV_FILE),
               "-f", str(probe.ROOT / "docker-compose.yml"),
               "exec", "-T", "api", "python", "-c", IN_CONTAINER],
              "post_outage_real_scanner_verdicts", timeout=90)
    final, _ = probe.status(sha)
    probe.demand(inspect_image_ids(final) == images
                 and _service_ids(final) == ids, "scanner_outage_recreated_containers")
    probe.demand(probe.rollback.read_originals(env) == originals,
                 "original_documents_changed")
    later, later_audit, revision = probe.rollback.snapshot()
    probe.demand(later == family and revision == alembic, "claim_lineage_changed")
    probe.demand(all(later_audit.get(k) == v for k, v in audit.items()),
                 "prior_claim_audit_changed")
    return {
        "schema": "mcri-first-manual-clamav-outage-v1",
        "candidate_sha": sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "app_env": "pilot",
        "fictional_scanner_outage_detected": True,
        "fictional_upload_http_503": True,
        "quarantine_scan_error_record_verified": True,
        "no_unscanned_document_promoted": True,
        "scanner_restart_healthy": True,
        "post_restore_clean_and_eicar_verdicts_verified": True,
        "pre_existing_document_and_audit_lineage_preserved": True,
        "actual_external_alert_delivery_verified": False,
        "independent_monitoring_owner_approved": False,
        "pilot_authorized": False,
    }


def main() -> int:
    try:
        report = observe(dict(os.environ))
        with OUTPUT.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, sort_keys=True)
            output.write("\n")
    except (probe.FaultProbeError, OSError, ValueError, RuntimeError):
        print("NO-GO: hosted synthetic ClamAV outage protection check rejected", file=sys.stderr)
        return 2
    print("PASS: synthetic scanner outage quarantined upload, recovery and clean/EICAR checks; NOT Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
