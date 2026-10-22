# Optional non-root runtime configuration rehearsal (#487)

**Default Compose is unchanged.** The base `docker-compose.yml` has not
been switched to UID 1000 for API, document worker, or Evidence preflight.
The additional `docker-compose.nonroot-optin.yml` is an **explicit operator
opt-in** for a separately approved, disposable or independently cloned
Evidence volume only. **Do not** put this overlay in `COMPOSE_FILE`, an
autostart service, or an existing customer deployment.

## Safe first check: render-only, no container start

From the repository root, provide an **explicit synthetic-only volume
name** for a render-only policy check. Docker does not create or mount it:

```bash
MCRI_NONROOT_CLONE_EVIDENCE_VOLUME=mcri-nonroot-clone-synthetic-example \
python scripts/pilot_nonroot_compose_gate.py --verify-optin-nonroot-config --env-file .env.pilot.example
```

On Windows PowerShell, first set
`$env:MCRI_NONROOT_CLONE_EVIDENCE_VOLUME="mcri-nonroot-clone-synthetic-example"`
then run the same Python command. **Do not** set this variable globally for
normal customer deployment or reuse an existing production Evidence volume.

The command renders the **base + opt-in overlay** with Docker Compose and
checks only the parsed configuration in memory. It never starts, stops,
restarts or changes containers, volume ownership or file permissions.
It prints only fixed error categories, never expanded environment secrets.
It verifies that the `preflight`, `api` and `worker` services all use
`1000:1000`, drop every Linux capability, forbid privilege escalation,
avoid host namespaces, and require an **external, pre-existing, separately named clone
volume** mounted at `/data/documents`. The original `local_documents`
volume is never an accepted mount for the three opt-in services. Without
`MCRI_NONROOT_CLONE_EVIDENCE_VOLUME`, Compose interpolation rejects the
overlay. Docker must not automatically create the clone volume: the
`external: true` declaration requires that the actual operator-controlled
clone exists before any attempted startup. The policy checks its
`mcri-nonroot-clone-...` name namespace but cannot prove its provenance.
The existing private pilot host-port policy must also pass. Protected CI
renders with a synthetic placeholder name, without creating that volume.

A passing render means **configuration syntax and policy only**.
It does not prove the final process UID, mount ownership/ACLs, file
accessibility, process capabilities at runtime, production secrets,
actual network isolation, or readiness for real Evidence. The default
named `local_documents` volume is **not automatically migrated** and may
be root-owned. A named external clone is not evidence of correct UID/ACL
ownership, provenance, backup recovery-point alignment or customer-data
authorization; those are separate operator acceptance gates.

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
