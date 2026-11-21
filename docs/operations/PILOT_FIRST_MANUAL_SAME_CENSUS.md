# First manual H&M pilot — single-census runtime observation (synthetic only)

Tracks Issue #653. This **read-only** operator aid reduces the risk of interpreting *different* container snapshots as one valid rehearsal. It cannot deploy, establish customer eligibility, or approve a release.

## Prerequisites — actual isolated selected host

Use only the independently designated empty host and approved **fictional MT ORION** rehearsal, with a locally selected Docker Engine (not SSH/TCP), 11 expected Compose services and **no customer documents, API AI keys, live SFTP or OCR**. Follow [fresh-host acceptance](PILOT_FRESH_HOST_REHEARSAL.md) and [first manual scope](../pilot/FIRST_MANUAL_HM_PILOT_SCOPE.md). An ephemeral CI Runner or a development laptop is not automatically an accepted independent host.

Have the security/operations reviewer privately supply an approved **11-service Docker image-ID manifest** following this operator command:

~~~bash
python scripts/pilot_running_image_identity.py --init \
  --release-sha "<reviewed-full-main-SHA>" \
  --output /secure/pilot-releases/rc-001-approved-image-ids.json
~~~

Each expected_image_ids value is a Docker sha256:<64 hex> IMAGE ID, **not** the immutable registry name@sha256:manifest-digest required separately for source-to-image provenance. The private manifest must be a regular file with owner-only permissions on POSIX; no unreviewed autofilling from a live environment.

## Operator read-only command

After the independently approved synthetic-only stack has been started and is healthy:

~~~bash
python scripts/pilot_first_manual_hm_census.py \
  --env-file /secure/pilot-releases/private-first-hm.env \
  --manifest /secure/pilot-releases/rc-001-approved-image-ids.json \
  --release-sha "<verified-full-40-character-main-SHA>" \
  --output /secure/pilot-releases/rc-001-same-census.json
~~~

The private input environment must be a **regular, non-symlink** file with owner-only POSIX permissions; secure its parent directory and check Windows ACLs separately. Use absolute paths. The output is new and exclusive, owner-only (0600 on POSIX), sanitized and never includes Docker container IDs, environment entries, credentials, raw Compose JSON or image IDs.

Within **one observation window**, the command: verifies the local Docker context and rejects redirecting environment overrides; checks rendered Compose configuration and exact disabled AI/OCR/external flags; snapshots the 11 Compose service IDs and health; reads each container's *effective Config.Env* with strict APP_ENV=pilot admission for all eight DB-connected services (plus optional demo-seed), OCR-off for Preflight/document Worker and image ID; then takes a second Compose snapshot. It refuses drift, inconsistent service status, unknown services, image differences, unsafe flags or an unsafe/missing manifest. No build, seed, data access, migrations, resets, network probes, or Docker writes are performed.

The output field bounded_same_census_passed=true proves **only that these specific bounded read-only checks agreed at that instant**, assuming the operator's Docker CLI and input manifest are trustworthy. It does **not** prove registry digests or release source, network egress/firewall isolation, DB-stored external integrations, data classification, host ownership, signed PDF authenticity, independent security decisions, recovery or alert response. The fields pilot_authorized and real_customer_data_authorized remain **false** by design.

**Required separate gates:** check the reviewed v5 Release Candidate with --require-first-manual-hm, check independently verified registry image provenance, same-epoch off-host PostgreSQL+Evidence restore, schema-safe rollback, acknowledged monitoring alerts, historical eight-finding security disposition and new full-history scan (#764), OpenSSL provenance (#952), signed inbound PDF scope (#894), the H&M operator journey and formal release decisions. See [release-candidate guide](PILOT_RELEASE_CANDIDATE.md) and [Issue #653](https://github.com/eh3aneba/maritime-claims-platform/issues/653).

Do not post private environment, manifests, JSON records or credential inventories to PRs, issues or public CI artifacts. Customer-data Pilot stays **NO-GO** until accountable humans independently verify every required item.
