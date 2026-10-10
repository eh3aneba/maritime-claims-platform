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

## Restore maintenance window

Restore is intentionally destructive and requires explicit confirmation:

```bash
MCRI_RESTORE_CONFIRM=YES ./scripts/restore_postgres.sh backups/mcri-YYYYMMDDTHHMMSSZ.dump
```

Before running it, establish a maintenance window and stop any ingress or database clients that are not part of this Compose project. The script can quiesce and verify the Compose stack, but it cannot discover external clients connecting directly to PostgreSQL.

The restore script:

1. stops the web/API ingress, all current workers, one-shot preflight/migration services and demo seed if present;
2. verifies fail-closed that no Compose service other than `db` and `clamav` remains running;
3. starts PostgreSQL if necessary and waits for the maintenance connection;
4. force-drops/recreates the target database, restores the custom-format dump and reapplies current migrations;
5. runs the application preflight after restore;
6. leaves application services stopped so an operator can complete integrity checks before reopening traffic.

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
