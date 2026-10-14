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

The follow-up synthetic check also runs the **actual**
`LocalDocumentStorage.save_upload`, `save_bytes`, `promote` and
`delete_physical` methods as UID/GID 1000, with two separate one-shot
containers sharing the *scratch-only* mount. It checks the recorded SHA-256,
private mode-0600 uploaded PDF, Quarantine → Evidence promotion, refusal to
overwrite an already-present Evidence key, preservation of existing bytes,
and cleanup of all synthetic files/directories. This is a filesystem-level
custody regression, **not** a full HTTP upload/DB transaction, malware scan,
tenant authorization or legacy-volume migration. In particular, never use
this scratch test to approve an in-place ownership change on the mounted
`local_documents` volume.

The synthetic API process also attempts a duplicate streaming upload and a
deliberately oversized upload. Both must be rejected without modifying the
prior quarantine payload or leaving a published/temporary partial file.
These negative tests do not exercise authenticated requests, scanner verdicts,
a committed database transaction or customer data.

The synthetic CI-only Compose overlay
(`docker-compose.ci-nonroot-custody.yml`) additionally drops **all Linux
capabilities** and enforces `no-new-privileges` for the one-shot API and OCR
worker probes. Each process verifies its actual `/proc/self/status`
`CapEff=0` and `NoNewPrivs=1` at UID/GID 1000 while running the
filesystem-custody/OCR exercise. The override is deliberately applied only to
the two disposable `docker compose run --no-deps` commands; it is **not**
the production API/worker configuration and does not change mounted
`local_documents` permissions.

**Legacy-mode refusal rehearsal (CI only):** the same isolated test now
creates an additional disposable, root-owned `0755` directory containing a
root-owned `0600` synthetic file, mounted **read-only** at a distinct path
inside the one-shot API container. Running as actual UID/GID 1000 with zero
effective Linux capabilities, the API must be unable to read the file and
the existing `audit_evidence_tree` must reject the directory with
`directory_permissions`. The test confirms that root metadata is unchanged.
Only those synthetic fixture files receive root ownership; it never changes
`local_documents`, performs a customer-volume probe, or authorizes a
permission conversion on a cloned/production Evidence volume.

**Synthetic permission-remapped copy rehearsal (CI only):** after the
negative root-owned fixture, the disposable runner creates a **separate copy**
of those known synthetic bytes inside the UID/GID 1000-owned scratch mount,
with private `0700` directory and `0600` file modes. The original root-owned
fixture stays independently mounted read-only. The real non-root API process
must read the copy and receive an `audit_evidence_tree` PASS; the independent
non-root OCR worker must read and write through the actual
`LocalDocumentStorage` contract, then remove **only** the copied synthetic
files. The runner rechecks the original source bytes, ownership and modes,
and requires full scratch cleanup. This exercises **known synthetic copied
layout only**: it is **not** a customer-data clone, DB/storage recovery-point
reconciliation, audited production migration, ACL or mount-policy proof,
operator sign-off, or an authorized API/Worker production UID change.

A pass establishes only that the selected API/worker images and **new,
properly owned synthetic scratch** support non-root access. It is not proof
that existing root-created customer Evidence folders, ACLs, scan quarantine
directories or database/document lifecycle behave under a migrated non-root
runtime. These require a separate approved cloned-volume integration and
rollback rehearsal before any changes to a real deployment.

**Evidence publication collision protection:** LocalDocumentStorage now writes
every uploaded file into an exclusively created mode-`0600` staging file
under the same target directory, completes the upload/hash/size checks, and
publishes the final name using an atomic **no-clobber hard link**. An existing
or raced-in final Evidence name is never removed during failed upload
cleanup; only the private temporary file is removed. Local promotion from
Quarantine to admitted Evidence similarly links at the destination before
unlinking the Quarantine name: if the final name already exists (including a
late collision), both preexisting Evidence and the original Quarantine
source remain intact. This preserves the local same-filesystem admission
contract; stores that do not support hard links must fail closed and require
a separately reviewed admission strategy, **not** a fallback to overwriting
`rename`. If Quarantine cleanup fails after a successful hard link, both
names can temporarily reference the same inode. Stop and reconcile custody
through the established audit/recovery process; do not auto-delete either.
New private uploads require the eventual non-root API/worker to share the
reviewed UID/GID contract; existing file ownership still requires a
separate approved migration. This protects namespace collision behavior
but does not replace full durable DB/Filesystem atomicity or external-host
acceptance.

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
