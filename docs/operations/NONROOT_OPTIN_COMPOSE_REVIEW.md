# Optional non-root runtime configuration rehearsal (#487)

**Default Compose is unchanged.** The base `docker-compose.yml` has not
been switched to UID 1000 for API, document worker, or Evidence preflight.
The additional `docker-compose.nonroot-optin.yml` is an **explicit operator
opt-in** for a separately approved, disposable or independently cloned
Evidence volume only. **Do not** put this overlay in `COMPOSE_FILE`, an
autostart service, or an existing customer deployment.

## Safe first check: render-only, no container start

From the repository root:

```bash
python scripts/pilot_nonroot_compose_gate.py --verify-optin-nonroot-config --env-file .env.pilot.example
```

The command renders the **base + opt-in overlay** with Docker Compose and
checks only the parsed configuration in memory. It never starts, stops,
restarts or changes containers, volume ownership or file permissions.
It prints only fixed error categories, never expanded environment secrets.
It verifies that the `preflight`, `api` and `worker` services all use
`1000:1000`, drop every Linux capability, forbid privilege escalation,
avoid host namespaces, and keep the **named** Evidence volume attached
read/write only at `/data/documents`. The existing private pilot host-port
policy must also pass. The required CI Production Deployment Policy runs
this check against the synthetic example configuration.

A passing render means **configuration syntax and policy only**.
It does not prove the final process UID, mount ownership/ACLs, file
accessibility, process capabilities at runtime, production secrets,
actual network isolation, or readiness for real Evidence. The default
named `local_documents` volume is **not automatically migrated** and may
be root-owned.

## Mandatory independent operator steps before considering activation

1. Approve a maintenance window, identify the exact container/image SHA
   and inventory the actual Evidence mount and PostgreSQL recovery point.
   Quiesce all writers and retain immutable backup/recovery references.
2. Run the existing metadata-only audit **in the currently authorized
   API container** using
   `docker compose exec -T api python -m app.core.evidence_volume_uid_audit`.
   A failure is **NO-GO**, not a request to run recursive chmod/chown.
3. Only on an isolated, independently verified clone or newly prepared
   synthetic Evidence volume, have an authorized operator test the same
   UID/GID contract with the existing disposable CI-style
   authenticated upload, ClamAV scan/quarantine, read/download, leased
   native-PDF processing and ENG+FAS image-only OCR workflows. Verify
   both clean and pre-existing records by content hashes, tenant lineage,
   private modes and delete/refusal behavior. Do not point those probes
   at customer storage.
4. Record effective UID/GID, capabilities, no-new-privileges, mount
   properties, POSIX/NFS ACLs, SELinux/AppArmor/idmaps where relevant,
   actual compatibility and human approval **outside GitHub**.
5. Prepare a tested, explicitly authorized rollback using retained
   immutable image and DB/Evidence recovery references. Do not perform
   an improvised database downgrade or in-place volume ownership rewrite.
6. Only after independent operations/security signoff can a separate
   controlled activation change be reviewed. This PR itself does
   **not** activate non-root API or document worker in the default stack.

This overlay is a proposed **least-privilege configuration contract**,
not a migration script, customer data permission, completion of #487,
or production deployment authorization. Related restore work #653 and
historical Gitleaks triage #764 remain independent gates.
**Pilot GO=NO.**

Offline regression:
```bash
python -m unittest scripts.tests.test_pilot_nonroot_compose_gate -v
```
