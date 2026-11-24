"""Hosted synthetic same-schema backend rollback. Never a release approval.

Rebuild the protected base from its exact checkout, swap only backend runtime
images in the already-admitted fictional Compose project, keep PG/Evidence
volumes unchanged. No old seed, migrations, DB restore, registry publishing
or customer environment. The web source must be identical across revisions.
"""
from __future__ import annotations

from hashlib import sha256
import http.cookiejar
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

import pilot_compose_readiness as readiness
import pilot_demo_docker_target as docker_target
from pilot_ci_first_manual_recovery import admitted_source, ENV_FILE, DB
from pilot_ci_lineage_reconcile import collect_lineage, canonical_fingerprint, sql_for
from pilot_running_image_identity import inspect_image_ids, _service_ids, IMAGE_ID

ROOT = Path(__file__).resolve().parents[1]
BASE = "e2c7cbb892d430001f6ba2453a09bc52a88e7e8f"
SHA = re.compile(r"[a-f0-9]{40}\Z")
BACKEND = {
    "api": "api", "worker": "worker",
    "governance-webhook-worker": "base",
    "external-evidence-scheduler-worker": "base",
    "external-evidence-observation-worker": "base",
    "external-evidence-review-projector-worker": "base",
}
API = "http://127.0.0.1:8000/api/v1"


class RollbackError(RuntimeError):
    """Static diagnostics only: never echo Docker/SQL/auth output."""


def require(value, label):
    if not value:
        raise RollbackError(label)


def run(args, label, timeout=60):
    try:
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                              check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RollbackError(label + "_unavailable") from None
    require(proc.returncode == 0, label + "_failed")
    return proc.stdout.strip()


def compose(*args, override=None, timeout=60):
    command = ["docker", "compose", "--project-directory", str(ROOT),
               "--env-file", str(ROOT / ENV_FILE), "-f", str(ROOT / "docker-compose.yml")]
    if override is not None:
        command.extend(["-f", str(override)])
    return run(command + list(args), "compose_operation", timeout=timeout)


def query(_, sql):
    return compose("exec", "-T", "db", "psql", "-v", "ON_ERROR_STOP=1",
                   "-U", DB, "-d", DB, "-At", "-c", sql)


def snapshot():
    family = collect_lineage(DB, query, first_manual=True)
    # HTTP login/read may add audit entries; require each prior audit row to
    # survive unchanged rather than requiring the entire audit log to freeze.
    audit = json.loads(query(DB, sql_for("audit_logs")))
    family.pop("audit_logs")
    for table in ("claims", "claim_pack_exports"):
        family[table] = canonical_fingerprint(query(
            DB, "SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY t.id), '[]'::jsonb)::text FROM " + table + " t;"))
    require(family["claims"][0] == 1 and family["documents"][0] == 2
            and family["initial_assessments"][0] == 1
            and family["claim_pack_exports"][0] == 1
            and family["reserve_history"][0] == 0 and len(audit) > 0,
            "fictional_data_census")
    require(query(DB, "SELECT COUNT(*) FROM ai_runs;") == "0"
            and query(DB, "SELECT COUNT(*) FROM initial_assessments WHERE approved_by_id IS NOT NULL;") == "0",
            "fictional_no_ai_or_approval")
    revision = query(DB, "SELECT version_num FROM alembic_version;")
    require(re.fullmatch(r"[0-9]{4}_[a-z0-9_]+", revision), "migration_revision")
    return family, {row["id"]: row for row in audit}, revision


def read_originals(env):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        body = json.dumps({"organization_slug": env["MCRI_DEMO_ORG_SLUG"],
                           "email": env["MCRI_DEMO_EMAIL"],
                           "password": env["MCRI_DEMO_PASSWORD"]}).encode()
        with opener.open(urllib.request.Request(
                API + "/auth/login", data=body, method="POST",
                headers={"Content-Type": "application/json"}), timeout=10) as response:
            require(response.status == 200, "login")

        def get(path, binary=False):
            with opener.open(API + path, timeout=10) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
                require(response.status == 200 and len(raw) <= 16 * 1024 * 1024, "bounded_read")
                return raw if binary else json.loads(raw)

        listing = get("/claims?search=MCRI-DEMO-MT-ORION")
        require(listing["total"] == 1 and len(listing["items"]) == 1
                and listing["items"][0]["external_reference"] == "MCRI-DEMO-MT-ORION",
                "authenticated_claim")
        endpoint = "/claims/" + listing["items"][0]["id"]
        docs = get(endpoint + "/documents")["items"]
        require(len(docs) == 2, "document_count")
        originals = {}
        for item in docs:
            digest = sha256(get(endpoint + "/documents/" + item["id"] + "/download", True)).hexdigest()
            require(digest == item["file_hash"], "original_digest")
            originals[item["id"]] = digest
        history = get(endpoint + "/initial-assessment/history")["items"]
        require(len(history) == 1 and history[0]["is_preliminary"] is True
                and history[0]["approved_by_id"] is None, "preliminary_history")
        return originals
    except (OSError, ValueError, KeyError, TypeError):
        raise RollbackError("authenticated_readback_failed") from None


def validate_scope(env):
    require(env.get("MCRI_CI_FIRST_MANUAL_ROLLBACK") == "1"
            and admitted_source(ENV_FILE, env), "hosted_synthetic_guard")
    actual = run(["git", "rev-parse", "HEAD"], "candidate_sha")
    require(SHA.fullmatch(actual) and actual != BASE, "distinct_candidate")
    require(run(["git", "merge-base", BASE, actual], "base_ancestry") == BASE, "base_ancestry")
    # Strictly same tracked migration tree, deployment config, frontend and
    # backend dependencies/Dockerfile; only test this compatible release pair.
    run(["git", "diff", "--quiet", BASE, actual, "--", "docker-compose.yml",
         "apps/api/alembic", "apps/api/alembic.ini", "apps/api/Dockerfile",
         "apps/api/requirements.txt", "apps/api/requirements.lock",
         "apps/api/pyproject.toml", "apps/web"], "schema_and_shared_build_inputs")
    return actual


def observe(env):
    actual = validate_scope(env)
    docker_target.observe()
    before = readiness.observe(env_file=ENV_FILE)
    require(readiness.evaluate(before, release_sha=actual)["compose_status_complete"], "candidate_ready")
    original_ids = _service_ids(before)
    candidate_images = inspect_image_ids(before)
    original_bytes = read_originals(env)
    source, audit, revision = snapshot()

    with tempfile.TemporaryDirectory(prefix="mcri-hosted-first-manual-rollback-") as temp:
        temp = Path(temp)
        checkout = temp / "previous"
        # A separate actual Git checkout avoids using current app files or
        # merely relabeling the candidate image as the previous revision.
        run(["git", "worktree", "add", "--detach", str(checkout), BASE], "previous_checkout")
        try:
            require(run(["git", "-C", str(checkout), "rev-parse", "HEAD"], "previous_sha") == BASE,
                    "previous_checkout_identity")
            tags = {}
            built = {}
            for target in sorted(set(BACKEND.values())):
                tag = "mcri-ci-first-manual-previous-" + target + ":" + BASE[:16]
                iid_file = temp / (target + ".iid")
                run(["docker", "build", "--target", target,
                     "--label", "org.opencontainers.image.revision=" + BASE,
                     "--iidfile", str(iid_file), "-t", tag, str(checkout / "apps/api")],
                    "previous_image_build_" + target, timeout=900)
                image = iid_file.read_text().strip()
                require(IMAGE_ID.fullmatch(image) and
                        run(["docker", "image", "inspect", "--format", "{{.Id}}", tag], "previous_image_id") == image,
                        "previous_image_identity")
                tags[target], built[target] = tag, image

            expected = {service: built[target] for service, target in BACKEND.items()}
            require(all(candidate_images[service] != image for service, image in expected.items()),
                    "distinct_rollback_images")
            override = temp / "rollback.json"
            override.write_text(json.dumps({"services": {
                service: {"image": tags[target]} for service, target in BACKEND.items()
            }}))
            # Do not run seed, migrate or preflight again; no DB/container
            # recreation beyond the six fixed backend runtime service names.
            compose("up", "-d", "--no-deps", "--no-build", "--pull", "never",
                    "--force-recreate", *BACKEND, override=override, timeout=180)
            for attempt in range(40):
                after = readiness.observe(env_file=ENV_FILE)
                if readiness.evaluate(after, release_sha=actual)["compose_status_complete"]:
                    break
                time.sleep(3)
            else:
                raise RollbackError("rollback_stack_unready")
            observed = inspect_image_ids(after)
            after_ids = _service_ids(after)
            require(all(observed[s] == expected[s] and after_ids[s] != original_ids[s] for s in BACKEND),
                    "actual_rollback_image_readback")
            require(all(observed[s] == candidate_images[s] and after_ids[s] == original_ids[s]
                        for s in original_ids if s not in BACKEND), "non_target_containers_preserved")
            require(read_originals(env) == original_bytes, "authenticated_originals_preserved")
            recovered, new_audit, after_revision = snapshot()
            require(recovered == source and revision == after_revision, "business_lineage_preserved")
            require(all(new_audit.get(k) == v for k, v in audit.items()), "prior_audit_preserved")
        finally:
            run(["git", "worktree", "remove", "--force", str(checkout)], "previous_checkout_cleanup")

    return {
        "schema": "mcri-first-manual-synthetic-backend-rollback-v1",
        "from_sha": actual, "to_sha": BASE, "app_env": "pilot",
        "backend_services_recreated_and_image_ids_matched": len(BACKEND),
        "non_target_containers_preserved": True,
        "web_source_unchanged": True,
        "migration_revision_unchanged": True,
        "business_lineage_and_prior_audit_preserved": True,
        "authenticated_original_document_hashes_preserved": True,
        "database_downgrade_performed": False,
        "active_database_restore_performed": False,
        "prior_release_security_approved": False,
        "registry_provenance_verified": False,
        "independent_operator_approved": False,
        "real_customer_data_used": False,
        "pilot_authorized": False,
    }


def main():
    try:
        record = observe(dict(os.environ))
        with Path("artifacts/first-manual-ci/rollback.json").open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (RollbackError, OSError, ValueError, RuntimeError) as exc:
        print("NO-GO: " + (str(exc) if type(exc) is RollbackError else "rollback_observation_rejected"), file=sys.stderr)
        return 2
    print("PASS: synthetic same-schema backend image rollback and preserved claim lineage; NOT production rollback approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
