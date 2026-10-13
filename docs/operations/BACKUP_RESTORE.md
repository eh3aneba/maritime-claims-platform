# Backup and Restore Baseline

## Database backup

With the compose stack running:

```bash
./scripts/backup_postgres.sh
```

A timestamped PostgreSQL custom-format dump is written to `backups/`.

Optional output path:

```bash
./scripts/backup_postgres.sh /secure/path/mcri.dump
```

The backup is published fail-closed:

1. `pg_dump` writes to an exclusively created `mktemp` file in the destination directory (mode `0600` under `umask 077`), rather than a predictable PID-suffixed temporary or final file;
2. the custom-format archive must parse successfully through `pg_restore --list`;
3. the script records the current database Alembic revision(s);
4. SHA-256 and bounded metadata sidecars are prepared in independently exclusive temporary files;
5. only after those checks pass are both sidecars and finally the dump **published using atomic, same-filesystem no-clobber hard links**. An unexpected late collision at **any** final filename aborts the publication and preserves the other file. Sidecars created by the failed attempt are cleaned up; foreign files are never deliberately overwritten.

The no-clobber rule is enforced at the **publish operation itself**, not merely through an earlier `test -e`. An offline fake-Docker regression exercises competing final dump, digest and metadata files, pre-existing symlinks, malformed archive failure and the normal case. This protects against accidental same-directory backup naming races; it does **not** make PostgreSQL and Evidence snapshots atomic or protect an operator-writable backup directory against a malicious account with write access. Protect that directory and retain the verified dump/sidecars together.

A successful backup produces:

- `mcri-....dump` — PostgreSQL custom-format archive;
- `mcri-....dump.sha256` — SHA-256 plus dump basename;
- `mcri-....dump.meta` — bounded metadata including UTC creation time, database name, repository SHA when available, Alembic revision(s), dump basename and digest.

Existing backup artifacts are never silently overwritten. A failed archive validation or Alembic revision change during backup leaves no final dump/checksum/metadata artifact at the requested path.

After copying a backup off-host or before using it in a recovery exercise, re-verify the dump against both sidecars and the PostgreSQL archive parser:

```bash
./scripts/verify_postgres_backup.sh /secure/path/mcri.dump
```

The verifier is read-only. It checks the dump SHA-256, sidecar filename/digest binding, metadata format/Alembic revision presence, and `pg_restore --list`. A checksum mismatch fails before archive parsing.

The SHA-256 sidecar is an integrity/copy-consistency control, not a digital signature. Protect the dump and both sidecars together with the organization's access controls and off-host backup policy; an attacker able to replace all artifacts could recompute the digest.

Store production/pilot backups off-host and encrypted according to the organization's retention policy.

### Restore writer-census fail-closed boundary

Before any destructive PostgreSQL restore, `scripts/restore_postgres.sh`
stops the enumerated application services and checks the running Compose
service inventory. A **nonzero or unavailable `docker compose ps` result**
is a hard NO-GO; it must **never** be interpreted as “no workers running.”
The script checks the Compose inventory after stopping writers, after bringing
up the PostgreSQL maintenance connection, and immediately before `dropdb`.
**It also queries PostgreSQL's `pg_stat_activity` directly within the target
database, excluding only its own read-only inspection session**, after DB
readiness and again immediately before `dropdb`. Any other connection —
including clients outside Compose — blocks deletion. A failed, malformed or
unavailable SQL census is also NO-GO, as is an unexpected Compose service
or missing DB container. Diagnostics intentionally omit raw Docker/PostgreSQL
output, connection metadata, hostnames, service names and credentials.

This remains an observation, **not an atomic lock** against a new external
connection after the final read. Importantly, the destructive `dropdb` also
runs **without `--force`**, so PostgreSQL itself refuses deletion if a
new client races in after inspection; the script leaves writers stopped on
that error. Authorized operators must still control database ingress,
externally managed workers and maintenance access throughout the restore
interval. Do not use `dropdb --force` to bypass a live-session refusal.

The accompanying `test_pilot_restore_writer_census.py` uses a fake Docker
executable and a synthetic archive to cover failures at all three Compose checkpoints,
including foreign PostgreSQL connections and fail-closed SQL inspection failures.
It does **not** exercise a real host or prove that external writers,
independent connections or non-Compose applications are quiesced. An operator
must separately enforce the approved maintenance window and verify actual
writer isolation before executing a destructive restore.

### Recovery-point consistency boundary

The PostgreSQL checksum/metadata sidecars prove the database dump artifact itself; they do **not** prove that Evidence/storage bytes belong to the same recovery point.

Before Pilot v1 can claim a complete recovery point, the operator must quiesce or otherwise consistently snapshot all database writers and the corresponding Evidence/storage layer, then bind both artifact identifiers in the recovery record. Do not infer storage consistency merely because a database dump passed integrity validation.

## Evidence files

The local pilot stores evidence in the Docker named volume `local_documents`. Database backup alone is not a complete claim backup. Back up the evidence volume separately at the host/storage layer, preserving paths and file integrity.

Before a real-data pilot, move this baseline to an S3-compatible/private object store or establish a documented encrypted volume-backup process.

## Bind one PostgreSQL dump to a separately captured Evidence archive

The bounded local Pilot v1 uses the `local_documents` volume. After stopping/quiescing **all** database and Evidence writers, an authorized operator must take an independently retained Evidence archive at the **same intended recovery point** as the PostgreSQL dump. Keep archive creation and access controls under your backup procedure; do not treat an online, unquiesced tar copy as an atomic snapshot.

First validate the PostgreSQL dump (requires the DB service and PostgreSQL archive parser):

```bash
./scripts/verify_postgres_backup.sh /secure/recovery/mcri.dump
```

Create a read-only **artifact-integrity binding** using the separate Evidence tar/tar.gz and an opaque reference to a human-controlled quiescence/change record (never place secrets, usernames or customer paths in the record ID):

```bash
python scripts/pilot_recovery_pair.py create \
  --db-dump /secure/recovery/mcri.dump \
  --evidence-archive /secure/recovery/evidence.tar.gz \
  --release-sha "<full-exact-40-hex-commit-of-backup>" \
  --quiescence-ref pilot-recovery-20261010-001 \
  --output /secure/recovery/recovery-pair.json

python scripts/pilot_recovery_pair.py verify \
  --manifest /secure/recovery/recovery-pair.json \
  --db-dump /secure/recovery/mcri.dump \
  --evidence-archive /secure/recovery/evidence.tar.gz \
  --release-sha "<full-exact-40-hex-commit-of-backup>"
```

The binder checks the PostgreSQL checksum and metadata sidecars against the dump, requires its recorded Git SHA to equal the independently provided commit, hashes the separate Evidence archive, and rejects unsafe archive members such as symlinks, traversal paths or duplicate names. The output is **created exclusively** (never overwritten) and contains digests, counts and an opaque operator-supplied reference—not the Evidence filenames, archive bytes, credentials or private storage paths.

**Boundary:** the presence of a quiescence-record ID is *not* independent proof that quiescence actually happened. An archive checksum and tar header scan are also not a demonstrated restorable object store. The resulting record deliberately sets `same_recovery_point_verified=false`, `restore_drill_verified=false` and `pilot_authorized=false`; the tool **cannot** promote these values to PASS. An accountable operator must separately review the stop/quiescence sequence, timestamped source snapshots, DB/object correspondence, scanner readiness and destructive restore drill before any release approval. A real matched DB + Evidence restore remains **P0 OPEN** in [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653). Do not commit real backup bytes or release manifests to the public repository.

## Synthetic CI backup + isolated clone restore proof

For relevant pull requests, the `Operational Performance Smoke` workflow first deploys the **ephemeral synthetic** stack, verifies all 11 Compose services and real ClamAV clean/EICAR behavior, then runs performance measurements. Only **after** that workflow succeeds, `scripts/pilot_ci_restore_probe.py` exercises the existing backup and archive-integrity tools on the synthetic DB and local Evidence volume:

1. Refuse any environment other than `.env.performance`, `APP_ENV=test`, `POSTGRES_DB=mcri_performance`, `POSTGRES_USER=mcri_performance`, and `MCRI_CI_RESTORE_PROBE=1`.
2. Independently observe the checked-out full git SHA (which can differ from the PR head on GitHub's temporary merge ref). Verify one synthetic MT ORION claim and a valid Alembic revision.
3. After an explicit synthetic-only guard, stop all Compose application writers, verify that only `db` and `clamav` remain running, then use the **real** `backup_postgres.sh` and `verify_postgres_backup.sh` for a custom PostgreSQL dump and validated SHA/metadata sidecars.
4. Stream the actual synthetic Evidence volume through a **fresh, disposable, no-dependencies reader container** into a PRIVATE temporary tar, refusing empty archives, symbolic links and non-regular files. Bind and reverify the dump and Evidence archive through `pilot_recovery_pair.py`. Do not publish artifact bytes or private storage paths.
5. Create a constant, otherwise unused `mcri_ci_restore_probe` database in the same temporary PostgreSQL instance, `pg_restore` the real dump there, compare the restored synthetic claim count and Alembic revision with the original database, then drop **only** the new clone in all created-db outcomes.
6. Save one exclusive short-lived `synthetic-db-restore-probe.json` result in the CI `operational-performance-smoke` artifact. Missing/failed steps block that workflow; stdout/stderr from underlying Docker, SQL or backup commands is never surfaced in the metadata log. The temporary dump/Evidence archive/sidecars/manifest are automatically deleted.

The CI recovery probe additionally recreates all archived synthetic Evidence file bytes in a **fresh, temporary host directory**, never the live `local_documents` volume. For the restored MT ORION claim it reads `storage_key`, `file_hash` and `file_size_bytes` from the restored clone database, validates safe archive paths and file types, and independently recomputes SHA-256 and sizes against each restored Document. Any missing file, digest mismatch, unsafe archive entry or duplicate path fails the required performance gate. The bounded result reports only file and verified Document counts, not storage keys, filenames, contents or private paths.

**Compose-local writer stop proof (synthetic only):** after CI performance and scanner validation, but **before reading the database baseline or taking either backup**, the probe stops every known application writer and ingress service (API, Web, document worker, governance and external-evidence workers, seed, migration and preflight). It independently requires `docker compose ps --status running --services` to contain *exactly* `db` and `clamav`. Any unexpected running service or stop failure aborts before capture. The stopped API cannot be used for archiving, so the probe uses an ephemeral, `--no-deps`, stdin-free, synthetic-only **reader container** mounting the Evidence volume; it does not restart the API/worker. On success and failure, CI's existing always-run teardown removes the ephemeral containers/volumes.

**Restored claim-lineage reconciliation (synthetic only):** with every Compose writer stopped, the CI probe also reads canonical, size-bounded row fingerprints for seven known data families tied to MT ORION: Documents, Initial Assessment versions, Assessment Sections, Claim Correspondence, correspondence-review decisions, Reserve History and organization Audit Logs. Each synthetic family is read from **both** the original database (before dump) and the restored database clone (after `pg_restore`). The probe requires populated critical families (Documents, Assessment versions/sections, reserves), validates unique row IDs, checks **both row count and SHA-256 of complete canonical row content**, and fails the operational performance gate on any mismatch even if the number of rows is unchanged. Only fixed family and row counts are retained in the summary; audit entries, decisions, free text, user IDs, internal Document paths and original SQL results are not logged or exported. This detects unexpected lost/changed synthetic lineage across the database restore but **does not** prove off-host immutability, external-system receipts, legal sufficiency, independently verified host recovery or a production SLA.

**Live CI corruption challenge (synthetic artifacts only):** after the normal dump, SHA/metadata verification and Evidence-pair verification succeed, the probe makes two independent **temporary copies**. It deliberately appends a synthetic marker to the first copy's database dump *without* updating the copied sidecars, and requires the existing `verify_postgres_backup.sh` to reject it. It also appends a marker to a copy of the Evidence tar, retaining the original signed-off integrity record, and requires `pilot_recovery_pair.py verify` to reject the mismatch. An unavailable verifier or **zero exit code for either corrupted copy** fails the operational performance gate. The valid originals and database remain unchanged; no raw command output, file contents or paths are included in the CI result. Successful evidence flags are `corrupted_db_dump_rejected` and `corrupted_evidence_archive_rejected`; they are not evidence of backup authenticity against an adversary who can replace metadata and hashes together.

**Cross-runner synthetic recovery rehearsal (CI-only, separate ephemeral VM):** for any path-scoped change that requires the live Docker performance smoke, the CI job first completes writer quiescence, paired dump/Evidence integrity checks, tamper rejection, same-engine restored clone, and the second `--network none` PostgreSQL engine proof. Only then, and only under `APP_ENV=test`, `MCRI_CI_RESTORE_PROBE=1`, the GitHub Actions synthetic-only export marker and exact checkout SHA, `pilot_ci_cross_runner_transfer.py` creates an exclusive `synthetic-recovery-transfer` directory of **synthetic test artifacts only**: the custom PostgreSQL dump and both integrity sidecars, Evidence archive, pair manifest, and *bounded* seven-family source lineage SHA/count fingerprints. No test DB password, cookies, host keys, user contact details or raw SQL/claim text is added to its separate source record. The transfer rejects wrong names, unsafe or excessive sizes, invalid source lineages and an unverified pair, before publication. `actions/upload-artifact` retains this fixture package for **1 day** on the private CI run. This archive is **not approved for customer information**.

**Safe failure diagnosis (synthetic CI only):** Both the same-runner
second-engine recovery probe and the later independent-runner restorer classify
a failed PostgreSQL operation into a fixed, allowlisted code, such as
`container_start_failed`, `database_ready_unavailable`,
`archive_restore_failed`, `lineage_integrity_mismatch` or
`evidence_integrity_mismatch`. The applicable recovery job and stable operational performance gate remain **failed** and
never retries or ignores an integrity mismatch. Docker stderr, SQL, endpoints,
credentials, Evidence paths and exception text outside the allowlist must
never appear in GitHub logs. The isolated second-runner engine also
requires the **final PostgreSQL PID 1** (`/proc/1/comm=postgres`) and two
consecutive successful SQL `SELECT 1` readbacks after `pg_isready` before the
one and only `pg_restore` attempt. This avoids mistaking the entrypoint's
temporary initialization server for the final database. The gate still fails
on a restore error and never retries `pg_restore` against a partially
restored target. A transient failure followed by a successful manual rerun
is evidence of *successful retry*, not proof of the original root cause
or of customer-host recovery.

A **different GitHub-hosted CI job/ephemeral runner** checks out the precise PR head SHA, downloads the original artifact by name, rejects missing/extra/symlinked/tampered files and pair mismatch, generates its own short-lived synthetic password, and restores the received dump into a new `postgres:18.4` container with `--network none` and no published ports. It rechecks source MT ORION claim count, migration revision, all seven complete canonical table fingerprints, and separately unpacks/reconciles Evidence against restored Document sizes/hashes. The new `cross-runner-restore` job is mandatory in the stable `Operational performance gate` **whenever the live smoke is scope-required**; if a code/docs-only change legitimately skips live smoke, the cross-runner job must also be skipped. A separate minimal boolean/count-only result is retained for seven days. No secrets or actual customer Evidence should ever be uploaded.

**Evidence boundary:** This proves a synthetic artifact successfully crossed two separate *GitHub Actions jobs* and could be restored in a new ephemeral runner VM; it does not independently attest physical hardware separation, authenticated/immutable off-site production backup storage, true DB/Evidence same-instant capture, real SFTP or cloud-object-store durability, clean-host production deployment, a previous-release application rollback, external writer stoppage, accountable operator approval, or recovery SLA. Those stay NO-GO for Issue #653; an actual controlled clean Pilot host test and human signoff remain mandatory.

**Second independent PostgreSQL engine acceptance (synthetic CI only):** after the existing quiesced backup, Evidence snapshot/hash pair and successful first isolated DB clone, the same backup MUST restore into a newly created **separate official PostgreSQL 18.4 container/process/anonymous data volume** with `--network none` and **no published ports**. The checker `scripts/pilot_ci_independent_postgres.py` accepts ONLY `.env.performance`-equivalent APP_ENV=test credentials/user/database, the CI restore marker, and the current exact Git SHA. It supplies an ephemeral local-only Postgres password file, initializes a new test database over `docker exec`'s local Unix socket, re-runs `pg_restore`, then checks MT ORION claim count, exact Alembic revision, full seven-family assessment/correspondence/financial/audit lineage fingerprints, and an independently reconstructed Evidence tar against Document file hashes in a **different temporary directory**. Each error is fail-closed; the new container and its anonymous volume are removed only if this specific probe actually created them. Only boolean checks/counts survive, never credentials, claim text or raw Docker output.

This materially avoids relying only on **a second logical database inside the original PostgreSQL process**; it still runs on the **same CI runner host**, not on an independently provisioned clean host, and uses the same input backup and Evidence tar. It does not demonstrate off-host recovery transport, true recovery-point atomicity, actual disaster recovery, clean-image deployment, storage provider durability, rollback to previous binaries, operator approval or Pilot GO. Issue #653 still requires real independently controlled host/operator rehearsal before customer Pilot authorization.

**Synthetic post-recovery controlled service resume:** after the synthetic writer-stop → private DB+Evidence backup → tamper checks → clone restore/lineage/Document SHA matching step has succeeded, the CI operational-performance job executes `scripts/pilot_ci_resume_probe.py`. This separate helper requires `.env.performance`, `APP_ENV=test`, the fixed `mcri_performance` PostgreSQL database/user, a CI-only marker and a full candidate SHA. Before acting, it independently checks **only DB and ClamAV are running**. It then uses `docker compose start` to restart exactly seven existing API/Web/document/governance/external-evidence worker services (never running migrate/seed, creating a new DB, rebuilding images or restoring customer data). Within a bounded time, it must observe all 11 expected Compose statuses passing using the independent read-only readiness checker, perform a **real unauthenticated API readiness HTTP request** with DB connectivity OK, and complete a **real synthetic authenticated login and MT ORION claim list read**. Any failure blocks the stable performance gate; CI's always-run teardown still removes synthetic containers/volumes. The only surviving artifact is a privacy-safe record of boolean tests and the number of resumed services, never credentials, access tokens, HTTP response bodies or claim IDs.

This is a non-destructive **same-version, same-host synthetic restart exercise** after a separately restored DB clone was verified. It is **not** restoring the production/live application DB or Evidence into an independently provisioned host, not rolling back to a previous application image, not demonstrating rollback schema compatibility, and not real operator change approval. All these qualifications remain false in the result. The actual #653 fresh-host full recovery and rollback rehearsal, external writer quiescence and operational signoff are separate P0 requirements.

**Scope boundary:** this proves known Compose writers were stopped during the synthetic database and Evidence capture, and the restored bytes match the temporary database clone. It does **not** prove quiescence of possible external writers, consistency of a real shared object store, a fully atomic DB+Evidence snapshot on a real host, recovery into the production storage volume, normal post-restore worker/download functions, a production-grade recovery window or any SLA. The JSON flags `compose_writer_quiescence_verified=true`, `external_writer_quiescence_verified=false`, `matched_recovery_point_verified=false`, `full_restore_drill_verified=false` and `pilot_authorized=false` state this boundary explicitly. The operator remains responsible for independent real-host quiescence, off-host backup, matched recovery-point verification, full fresh-host DB+Evidence restore and rollback proof.

This is **not** a production restore rehearsal. It intentionally never drops or restores the live application database, never restores Evidence to a matching new storage volume, does not pause all writers to establish a consistent multi-store point, and has no independent operator/quiescence proof. Its record always sets `matched_recovery_point_verified=false`, `evidence_restore_verified=false`, `full_restore_drill_verified=false` and `pilot_authorized=false`. These are open P0 items in #653 and must be completed through a separately authorized destructive maintenance exercise. Never repurpose the CI probe on customer records or use it to claim production RPO/RTO.

## Bounded Pilot v1 rollback rehearsal evidence gate (operator only)

Restoring a PostgreSQL backup is **not** the same as rolling application images back to a previous exact release. A controlled Pilot rollback must separate these paths and explicitly refuse improvised database downgrades.

Before any controlled maintenance exercise, the accountable release team identifies the failed release (from SHA), the **different** previous approved release (to SHA), full immutable image digests for API/Web/Worker on both sides, the live Alembic revision, the change ticket, approved maintenance window and an independent reviewer. Record a previous known-good image digest from the actual registry; never derive one from a mutable tag or invent it.

Use the read-only standard-library gate to create a NO-GO draft in controlled operator storage:

```bash
python scripts/pilot_rollback_rehearsal.py init \
  --from-sha "<current-exact-40-character-release-SHA>" \
  --to-sha "<previous-known-good-exact-40-character-release-SHA>" \
  --output /secure/pilot-releases/rc-001-rollback.json
```

**Two strictly separated rollback choices:**

- `application_only`: the image release changes, but live PostgreSQL remains untouched. Require **identical independently observed Alembic revision** before/after, an approved pre-change backup and pre/post service health plus **real authenticated claim read** evidence. If revisions differ, this mode is **NO-GO**; merely hoping an older app will tolerate a newer schema is not an acceptable rollback proof.
- `recover_paired_backup`: a separately approved, controlled DB+Evidence recovery exercise was actually performed. Require the matched recovery-pair evidence reference, bounded restore-operation evidence, post-restore Document/lineage integrity checks, migration/preflight checks, and explicit operator signoff. No ad hoc `alembic downgrade` or unreviewed database rewrites are allowed.

The record additionally requires release and environment identities, two **different** operator and independent-approver roles, precise UTC start/end, `rollback_result="pass"`, `explicit_human_authorized=true`, and evidence references for the change approval, exercise log, backup, health checks, authenticated Pilot claim journey and independent review. Run a structural check **only after** those independent facts exist:

```bash
python scripts/pilot_rollback_rehearsal.py check \
  /secure/pilot-releases/rc-001-rollback.json \
  --from-sha "<independently-confirmed-current-SHA>" \
  --to-sha "<independently-confirmed-previous-SHA>"
```

A missing digest, mismatched SHA/migration, unsafe downgrade, incomplete authority, absent restore-pair proof or missing post-rollback acceptance yields **NO-GO**. This tool **does not execute a rollback**, independently verify operator signatures or GitHub/host evidence, restore a DB, or authorize customer-data use. Even `ROLLBACK RECORD COMPLETE` only means operator-entered references have the required shape. A separately approved full rehearsal on the actual isolated Pilot host is still P0 under [#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653); preserve evidence externally without secrets.

## Restore maintenance window

Restore is intentionally destructive and requires explicit confirmation:

```bash
APP_ENV=development MCRI_RESTORE_CONFIRM=YES \
  ./scripts/restore_postgres.sh backups/mcri-YYYYMMDDTHHMMSSZ.dump
```

Before running it, establish a maintenance window and stop any ingress or database clients that are not part of this Compose project. The script can quiesce and verify the Compose stack, but it cannot discover external clients connecting directly to PostgreSQL.

**New pre-destruction boundary:** `APP_ENV` must be explicitly classified (`development`, `test`, `pilot`, `staging`, or `production`); it is not inferred from a Compose default. Once Compose writers are quiesced and PostgreSQL is ready, but **before** `dropdb`, the restore script calls `scripts/verify_postgres_backup.sh` to check the SHA-256 sidecar, metadata binding, intended database name and `pg_restore --list` archive readability. Any failed check leaves the original database intact and application services stopped.

For `APP_ENV=pilot`, `staging` or `production`, the operation also requires all three recovery-pair inputs, verifies their contents with `pilot_recovery_pair.py verify` and refuses to reach `dropdb` if the Evidence archive or manifest has changed:

```bash
APP_ENV=pilot \
MCRI_RESTORE_CONFIRM=YES \
MCRI_RESTORE_PAIR_MANIFEST=/secure/recovery/recovery-pair.json \
MCRI_RESTORE_EVIDENCE_ARCHIVE=/secure/recovery/evidence.tar.gz \
MCRI_RESTORE_RELEASE_SHA="<full-exact-40-hex-commit-of-backup>" \
  ./scripts/restore_postgres.sh /secure/recovery/mcri.dump
```

All input artifacts must already have been captured, protected and independently reviewed. Pair verification proves **artifact integrity only**; it does not create or restore the Evidence volume, guarantee a common snapshot time, quiesce external database connections, or approve production use. The operator must restore the matching Evidence storage point separately and check file/DB correspondence before reopening services. A simulated test of the script is not a completed destructive restore rehearsal.


The restore script:

1. stops the web/API ingress, all current workers, one-shot preflight/migration services and demo seed if present;
2. verifies fail-closed that no Compose service other than `db` and `clamav` remains running;
3. starts PostgreSQL if necessary and waits for the maintenance connection;
4. verifies dump digest, sidecars, target database and `pg_restore --list`, plus the mandatory DB/Evidence recovery-pair binding for Pilot/staging/production;
5. force-drops/recreates the target database, restores the custom-format dump and reapplies current migrations;
6. runs the application preflight after restore;
7. leaves application services stopped so an operator can complete integrity checks before reopening traffic.

If a future Compose service remains running because the quiesce list was not updated, restore aborts before database destruction. If any restore step fails, application services stay stopped and must not be restarted until the failure is understood.

## Restore verification

After the script succeeds, verify at minimum before reopening traffic:

- the expected Alembic/database revision is present;
- claim counts match the expected backup point;
- a known claim opens successfully;
- evidence metadata is present;
- evidence files are downloadable from the matching restored evidence volume/storage backup;
- audit records and assessment versions are present;
- the restored database and restored evidence files belong to the same backup/recovery point;
- no unexpected worker or external client is writing during verification.

Only after those checks pass, restart the stack:

```bash
docker compose up -d
```

Then confirm readiness and a representative end-to-end claim path again. Record the restore timestamp, dump identifier, application/release SHA, migration head, evidence-backup identifier, verification result and operator in the incident/change record.
