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

Store production/pilot backups off-host and encrypted according to the organization's retention policy.

## Evidence files

The local pilot stores evidence in the Docker named volume `local_documents`. Database backup alone is not a complete claim backup. Back up the evidence volume separately at the host/storage layer, preserving paths and file integrity.

Before a real-data pilot, move this baseline to an S3-compatible/private object store or establish a documented encrypted volume-backup process.

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
