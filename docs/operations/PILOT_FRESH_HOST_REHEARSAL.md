# Pilot P0 #653 — fresh-host synthetic deployment and operator evidence

Tracking: [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653); scope [#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647). Related gates: branch protection [#461](https://github.com/eh3aneba/maritime-claims-platform/issues/461), optional real-SFTP acceptance [#652](https://github.com/eh3aneba/maritime-claims-platform/issues/652).

**State: procedure only — no clean-host deployment, external alert, backup/restore, rollback or real-user acceptance is attested here. Customer-data Pilot remains NO-GO until each independent #653 requirement passes and a release owner authorizes a bounded environment.**

## 1. Authorized environment, operator and release identity

Use an **independently provisioned, empty, isolated host** with no customer volumes, credentials, SFTP endpoint or production network access. Obtain a private change/rehearsal ticket and separate deployment operator, security/evidence custodian and reviewer. Record (privately) OS/kernel/architecture, Docker Engine and Compose v2 versions, disk/capacity, time synchronization, storage encryption/backup location, reverse-proxy/TLS/firewall exposure and who can administer the host. The repository does not certify a specific OS hardening baseline; the responsible operator must review one.

Freeze one **full 40-character Git SHA** from protected `main` and retrieve its exact tree from the reviewed repository. Verify `git rev-parse HEAD`, `git status --porcelain` (must be empty), approval/change ticket and the exact corresponding workflow evidence. Do **not** assume the squash-merged SHA equals the prior PR HEAD. Record the approved API/Web/Worker/Postgres/ClamAV immutable registry references separately; a successful build or `docker image ls` is not a registry digest attestation.

**Stop** if the code revision, builder inputs or digest lineage cannot be independently reconciled. Do not fabricate `@sha256` values to satisfy the release record.

## 2. Synthetic-only configuration and non-public network

Use a new environment file in restricted operator storage based on `.env.pilot.example`; replace every `REPLACE_WITH_*` value with private approved test secrets. This is **not** a customer tenant bootstrap. Set `AI_PROVIDER=disabled`, retain ClamAV and local `eng+fas` OCR, allow only a synthetic fixture set, and leave all external evidence integrations/SFTP disabled unless separately authorized and qualified. Review database/storage persistence, rotation, retention/legal holds and off-host recovery custody before admitting data.

From the *exact frozen checkout*, run checks that do not start the stack:

```bash
docker compose version
docker compose --env-file .env config >/dev/null
python scripts/pilot_compose_port_policy.py --env-file .env
```

The rendered Compose ports 5432, 8000 and 3000 must remain loopback-only, and ClamAV port 3310 must not be published. Verify host firewall/proxy/TLS separately: passing the port-policy script does **not** prove network isolation. Never publish `.env`, `docker compose config` output, authentication tokens, container inspection output or raw claims in a GitHub comment/artifact.

## 3. Clean-host startup and bounded synthetic journey

Only after the preceding controls and operator authorization, add `MCRI_SYNTHETIC_ONLY_CONFIRM=YES` **only** to the authorized synthetic rehearsal environment; never add it to customer/production configuration. The `pilot_demo_seed_guard.py` preflight refuses unsafe environment class, remote DB URL, non-loopback API URL, external AI, disabled malware scanning or remote storage. It still cannot establish that existing volumes contain no customer data, so the independently verified **empty-host** prerequisite remains mandatory.

```bash
# This command BUILDS/STARTS services and seeds MT ORION.
# Run it exclusively on the empty, synthetic-only rehearsal host.
./scripts/design_partner_preflight.sh .env
```

**Do not run the helper in a customer environment or one containing existing tenant data.** It executes `docker compose up -d --build` and the `demo-seed` profile. Its success is a local synthetic smoke test, not a clean host proof by itself, final image provenance, release authorization or a safe customer organization bootstrap.

After independent review of the expected 11 services, image config IDs and the candidate SHA, record read-only host observations:

```bash
python scripts/pilot_compose_readiness.py \
  --env-file .env \
  --release-sha "<frozen-40-char-main-SHA>" \
  --output /secure/pilot-releases/rc-001-compose-status.json

python scripts/pilot_running_image_identity.py \
  --init \
  --release-sha "<frozen-40-char-main-SHA>" \
  --output /secure/pilot-releases/rc-001-image-manifest.json

# An independent operator must first populate the manifest from approved
# image build records; do not copy values from the running host as "expected".
python scripts/pilot_running_image_identity.py \
  --verify \
  --release-sha "<frozen-40-char-main-SHA>" \
  --manifest /secure/pilot-releases/rc-001-image-manifest.json \
  --env-file .env \
  --output /secure/pilot-releases/rc-001-image-readback.json
```

An image **config ID** is not the registry `name@sha256:manifest-digest`; review both identities. Verify the deployed Alembic revision, API/Web readiness, healthy ClamAV/worker/queue and OCR with genuine bounded test probes. Have a real designated claims handler perform the exact [Pilot v1](../pilot/DESIGN_PARTNER_PILOT_PROTOCOL.md) synthetic H&M machinery path: intake, evidence quarantine, missing/conflicting documents, chronology, technical/financial review, immutable versioned assessment, human approval and correspondence/export. Record *observed* outcome and blockers, not a pre-filled pass.

## 4. Independent recovery, rollback and monitoring — separate exercises

A passing CI restore or Compose readiness observation **does not** complete these steps.

- **Backup/restore:** separately capture a quiesced DB archive and matched Evidence object-store point; verify sidecars and pair manifest; prove a **new, separately controlled** restore environment with all writers stopped, no unknown DB writers, matching Evidence/Document hashes, audit/receipt lineage and Alembic head. Follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md), including its fail-closed destructive-operation precautions; do not copy a destructive restore command into an unreviewed host.
- **Rollback:** identify a real prior known-good code/image SHA, compatible migration boundary and application-only vs paired-backup mode. Authorize and *actually rehearse* with synthetic data. Use `scripts/pilot_rollback_rehearsal.py` only to validate the private **evidence record**, never as a substitute for the operation. Never improvise database downgrades.
- **Alerts:** exercise API/readiness, DB/migrations, queue/document worker, scheduler/observer/projector, storage, ClamAV, backup age/recovery, authentication and latency/error alarms. Require delivery and acknowledgement by an identified on-call owner and escalation path. `scripts/pilot_monitoring_ownership.py` validates only record completeness.
- **Tenant controls:** independently prove same-tenant MFA/roles, denial of cross-tenant access, integration disablement, data/legal-hold ownership, session revocation and controlled exit using [PILOT_TENANT_LIFECYCLE.md](PILOT_TENANT_LIFECYCLE.md). Synthetic `demo-seed` is **not** a reviewed customer tenant onboarding method.

Keep operator and independent reviewer identity, exact host/environment, timing, recovery point age, duration and immutable private evidence references in the controlled change record. Public issue updates should include only bounded result and opaque references.

## 5. Final candidate record and acceptance decision

Create and independently verify the [release candidate evidence record](PILOT_RELEASE_CANDIDATE.md), using:

```bash
python scripts/pilot_rc_gate.py init \
  --release-sha "<frozen-40-char-main-SHA>" \
  --output /secure/pilot-releases/rc-001.json
```

Populate the Alembic head, **reviewed registry image digests**, configuration/limitations references, actual operator attestations and exact-SHA CI references *only when observed*. A successful `pilot_rc_gate.py check` only establishes the shape of this record; it does not verify host evidence or authorize Pilot GO.

**Evidence disposition:** [#461](https://github.com/eh3aneba/maritime-claims-platform/issues/461) requires independently reviewed red-blocked/green-clean enforcement; [#652](https://github.com/eh3aneba/maritime-claims-platform/issues/652) is required before any SFTP-enabled Pilot; and [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653) remains OPEN until the actual fresh-host, matched restore, rollback, monitoring, tenant and operator exercises have independently passed. Any unknown or failed P0 is **NO-GO**, even when all CI workflows are green.
