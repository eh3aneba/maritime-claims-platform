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

## Restore

Restore is intentionally destructive and requires explicit confirmation:

```bash
MCRI_RESTORE_CONFIRM=YES ./scripts/restore_postgres.sh backups/mcri-YYYYMMDDTHHMMSSZ.dump
```

The script stops app services, recreates the database, restores the dump, reapplies current migrations and leaves restart under operator control.

## Restore verification

After restore:

```bash
docker compose up -d
docker compose exec -T api python -m app.core.preflight
```

Then verify at minimum:

- Login works.
- Claim count is expected.
- A known claim opens.
- Evidence metadata is present.
- Evidence files are downloadable from the restored evidence volume.
- Audit records and assessment versions are present.
