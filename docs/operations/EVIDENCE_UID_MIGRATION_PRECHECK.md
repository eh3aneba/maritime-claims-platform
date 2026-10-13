# Evidence volume UID/GID readiness — read-only operator precheck

This is a **NO-MUTATION** tool for security issue #487. It helps identify why
an existing, root-populated `local_documents` volume may be incompatible with
future non-root API and OCR workers. It does **not** authorize a migration,
change any existing file, or establish customer Pilot GO (#653).

On the **approved maintenance host**, after controlling external writes and
confirming the actual deployment target and Evidence volume, run the audited
helper **inside the existing API service** so it sees the mounted filesystem:

```bash
docker compose exec -T api python -m app.core.evidence_volume_uid_audit
```

This command reads filesystem metadata only: configured
`LOCAL_STORAGE_PATH`, existing directory/file mode bits, UID/GID, file type
and subtree depth. No filenames, directory paths, file content, permission
bits, hostnames or Docker environment values are emitted. The output is a
fixed `PRECHECK PASS` or a bounded `NO-GO` reason; failures exit with code 2.
It checks whether proposed **UID/GID 1000:1000** appears able to traverse,
list and create/rename within the existing directory tree and read existing
files. It rejects missing/inaccessible roots, symlinks, unusual file types,
world-writable paths and a bounded-scan overflow (20,000 entries / 32 levels).
It never creates a write-probe file, writes state, alters ACLs, changes
ownership, or performs `chmod`/`chown`.

A typical previously root-owned `0755` Evidence root will be **NO-GO**:
it is not writable by the proposed runtime UID even when current root workers
are healthy. Do **not** bypass this with `0777`, root-capable API processes,
a recursive `chown`, silently discarding existing Evidence, or an unreviewed
data move. Any ownership remediation requires a separately reviewed,
quiesced and reversible operator runbook with custody/backups and operator
signoff, plus real API quarantine/upload/download and OCR Eng/Fas functional
checks against new and legacy data.

**Synthetic live-stack regression:** The required `Operational Performance Smoke`
also executes the *same metadata-only audit* inside the actual running API
container against its mounted, seeded, disposable CI Evidence volume. It
asserts that a proposed UID/GID 1000 cannot receive a false PASS if the
actual volume root lacks directory write/traverse permissions, and that
the root directory's device, inode, mode and owner remain unchanged.
An explicit fail-closed `directory_permissions` finding is **a successful
test of the refusal**, not an accepted operational migration or a reason
to bypass the check. No paths, Evidence filenames or file contents are
printed. This CI exercise is **not** a customer-host test; it does not
change the target runtime user or prove the effective UID's real access.

**Disposable effective-UID rehearsal (CI only):** after the read-only
metadata check, the required Operational Performance workflow creates a fresh
randomized scratch directory on the disposable GitHub runner, owns **only that
directory** as UID/GID `1000:1000`, and mounts it at
`/mnt/mcri-ci-uid-probe` in one-shot API and document-worker containers.
Those temporary processes actually run as UID/GID 1000. The API creates a
synthetic marker with private permissions; the OCR worker must read, rename
and delete that marker, and execute Tesseract with both `eng+fas` languages
and the Poppler utility binaries. The test verifies that no probe files remain,
then deletes the temporary scratch. It does **not** bind scratch over
`/data/documents`, reconfigure the production service's default user,
read/write the existing Evidence tree, run an authenticated upload transaction,
or modify customer host or filesystem metadata. Failure of any real UID access
or OCR utility step fails the mandatory Operational Performance gate.

A pass establishes only that the selected API/worker images and **new,
properly owned synthetic scratch** support non-root access. It is not proof
that existing root-created customer Evidence folders, ACLs, scan quarantine
directories or database/document lifecycle behave under a migrated non-root
runtime. These require a separate approved cloned-volume integration and
rollback rehearsal before any changes to a real deployment.

**Limitations:** This is a necessary POSIX mode-bit screening check, **not**
an effective-UID permissions test. POSIX/NFS ACLs, SELinux/AppArmor,
supplemental group memberships, mount/idmap policy and race conditions cannot
be proven through metadata inspection alone. A passing result is **not**
an atomic filesystem snapshot, not proof of actual worker write permission,
not a DB/Evidence point-in-time backup, and not a security authorization.
Perform live non-root access probes only in an independently approved,
quiesced synthetic or cloned volume; never use arbitrary customer files
as destructive test fixtures.

The migration/preflight/demo-seed and document/AI processing services remain
**unchanged** by this precheck PR; explicit changes to their runtime users
must only follow an operator-approved compatibility procedure.
