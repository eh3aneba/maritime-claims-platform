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

1. `pg_dump` writes to a private temporary path rather than the final operator-facing filename;
2. the custom-format archive must parse successfully through `pg_restore --list`;
3. the script records the current database Alembic revision(s);
4. SHA-256 and bounded metadata sidecars are prepared;
5. only after those checks pass is the final dump path published.

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

**Synthetic post-recovery controlled service resume:** after the synthetic writer-stop → private DB+Evidence backup → tamper checks → clone restore/lineage/Document SHA matching step has succeeded, the CI operational-performance job executes `scripts/pilot_ci_resume_probe.py`. This separate helper requires `.env.performance`, `APP_ENV=test`, the fixed `mcri_performance` PostgreSQL database/user, a CI-only marker and a full candidate SHA. Before acting, it independently checks **only DB and ClamAV are running**. It then uses `docker compose start` to restart exactly seven existing API/Web/document/governance/external-evidence worker services (never running migrate/seed, creating a new DB, rebuilding images or restoring customer data). Within a bounded time, it must observe all 11 expected Compose statuses passing using the independent read-only readiness checker, perform a **real unauthenticated API readiness HTTP request** with DB connectivity OK, and complete a **real synthetic authenticated login and MT ORION claim list read**. Any failure blocks the stable performance gate; CI's always-run teardown still removes synthetic containers/volumes. The only surviving artifact is a privacy-safe record of boolean tests and the number of resumed services, never credentials, access tokens, HTTP response bodies or claim IDs.

This is a non-destructive **same-version, same-host synthetic restart exercise** after a separately restored DB clone was verified. It is **not** restoring the production/live application DB or Evidence into an independently provisioned host, not rolling back to a previous application image, not demonstrating rollback schema compatibility, and not real operator change approval. All these qualifications remain false in the result. The actual #653 fresh-host full recovery and rollback rehearsal, external writer quiescence and operational signoff are separate P0 requirements.

**Scope boundary:** this proves known Compose writers were stopped during the synthetic database and Evidence capture, and the restored bytes match the temporary database clone. It does **not** prove quiescence of possible external writers, consistency of a real shared object store, a fully atomic DB+Evidence snapshot on a real host, recovery into the production storage volume, normal post-restore worker/download functions, a production-grade recovery window or any SLA. The JSON flags `compose_writer_quiescence_verified=true`, `external_writer_quiescence_verified=false`, `matched_recovery_point_verified=false`, `full_restore_drill_verified=false` and `pilot_authorized=false` state this boundary explicitly. The operator remains responsible for independent real-host quiescence, off-host backup, matched recovery-point verification, full fresh-host DB+Evidence restore and rollback proof.

This is **not** a production restore rehearsal. It intentionally never drops or restores the live application database, never restores Evidence to a matching new storage volume, does not pause all writers to establish a consistent multi-store point, and has no independent operator/quiescence proof. Its record always sets `matched_recovery_point_verified=false`, `evidence_restore_verified=false`, `full_restore_drill_verified=false` and `pilot_authorized=false`. These are open P0 items in #653 and must be completed through a separately authorized destructive maintenance exercise. Never repurpose the CI probe on customer records or use it to claim production RPO/RTO.

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
