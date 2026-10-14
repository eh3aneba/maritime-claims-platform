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

**Synthetic permission-failure rollback (CI only):** the runner also records a
SHA-256 checksum of the disposable root-owned source before copying it and
requires the private UID/GID 1000 copy to match. The non-root API process
temporarily removes read permission from **only its own copied file**, proves
the real permission audit rejects that copy (`file_permissions`) and that
the file cannot be read, then restores the copy's mode to `0600` and verifies
the audit and digest succeed again. The independent non-root worker verifies
the copied digest before its existing custody operations. Finally the runner
rechecks the original source SHA-256, ownership and mode and requires complete
scratch cleanup. This is a controlled copy-level permission rollback
regression, **not** a database/application rollback, production filesystem
remediation, customer-storage migration or restore of a real backup.

**Actual restricted API HTTP readiness (CI only):** after proving the
synthetic clone, the one-shot UID/GID 1000 API container explicitly overrides
`LOCAL_STORAGE_PATH` to its *isolated scratch mount* and requires
`APP_ENV=test`, `MCRI_SYNTHETIC_ONLY_CONFIRM=YES`, and disabled external AI.
It executes the **real** application preflight (synthetic database connection,
ClamAV connectivity and a temporary scratch-only storage write probe); the
temporary file must be removed. It then starts the real Uvicorn application
bound only to `127.0.0.1` **inside the one-shot container**, checks HTTP
liveness/readiness and live PostgreSQL dependency status, requires a
request to the documents endpoint without credentials to return HTTP 401,
and verifies the actual child process retains UID/GID 1000,
`CapEff=0` and `NoNewPrivs=1`. A `finally` block terminates the
temporary server and reaps it. No Docker port is published and no customer
storage path is used.

This establishes a **non-root HTTP startup and read-only readiness/auth
boundary** on the disposable seeded CI stack. It does not prove authenticated
document upload, a database-committed quarantine/scan/OCR transaction,
production API/worker user changes, any customer Evidence volume migration,
or Pilot GO.

**Restricted worker with live ClamAV (CI only):** the same synthetic
API scratch rehearsal uses the real `LocalDocumentStorage.save_upload` method
to quarantine a clean test PDF and the harmless standard EICAR antivirus test
signature under UID/GID 1000. The **separate** restricted document-worker
container connects to the existing live CI ClamAV daemon over the Compose
network, obtains actual `CLEAN` and `INFECTED` verdicts via the production
`scan_file` streaming interface, and verifies an unreachable scanner
raises `MalwareScannerError` rather than being interpreted as clean. Only
the clean PDF follows the existing synthetic Quarantine → Evidence promotion
rehearsal. The infected test signature must stay outside the Evidence
namespace; its quarantine digest is verified and the synthetic copy is
deleted afterward. There are no new published ports, no real malware, no
customer files, no changes to the production worker user, and no DB write.

This verifies **real scanner transport and verdict behavior under non-root
worker credentials**, not an authenticated document upload, persisted
`QuarantinedUpload` or `Document` record, database/scan transaction
atomicity, automatic quarantining of actual customer uploads, or Pilot GO.
All of those require independent integrated application acceptance.

**Unauthorized HTTP upload fail-closed proof (CI only):** the real
loopback-only Uvicorn API process under UID/GID 1000 receives multipart POST
requests carrying a harmless synthetic PDF and EICAR test signature, first
without authentication and then with an invalid bearer token. Every request
must return `401` and the runner compares the complete relative scratch
namespace (including file SHA-256 digests) before and after each refusal.
No anonymous request may publish, modify or leave a synthetic Evidence or
Quarantine file. The requests are deliberately aimed at a synthetic
nonexistent claim ID and do not authorize access to real claims.

The probe does not authenticate a real user, commit a database document or
quarantine record, execute an end-to-end malware-scan admission transaction,
or demonstrate rollback on a production database. Those remain separately
gated steps and require an independently isolated disposable database before
any mutating acceptance test. This is **not** customer Pilot GO.

**Authenticated real API on a separate disposable synthetic database
(CI only):** the Operational Performance Smoke workflow now creates a
private PostgreSQL custom dump of the *synthetic seeded test database*, creates
a randomly named **new database in the same disposable PostgreSQL server**,
restores the dump into that database, and points a separate UID/GID 1000,
zero-capability, no-new-privileges one-shot API solely at this clone. It uses
private scratch storage, an internal `127.0.0.1` Uvicorn listener without
Docker port publication, and the real preflight and live DB/ClamAV services.
A seeded synthetic user logs in through the real HTTP endpoint, creating a
session **in the clone only**, then performs authenticated claim and document
metadata reads. After verifying the source authentication-session count did
not change, the runner terminates Uvicorn, drops only the freshly created
clone, and removes the private temporary dump and scratch. A preexisting
clone name is never reused, overwritten or dropped.

**Authenticated clean HTTP admission on this disposable database (CI only):**
after the successful login and document-metadata read, the same non-root
Uvicorn API now receives an authenticated multipart POST with a uniquely
generated **synthetic** PDF. It uses the *real* application
`create_document_from_upload` path and the live CI ClamAV scanner. The test
requires HTTP 201, an exact payload SHA-256 and length, an authoritative
`CLEAN` malware verdict and timestamp, and an admitted private mode-`0600`
file with matching bytes. It checks the newly committed `Document`, its
pending `DocumentProcessingJob`, the absence of a same-hash
`QuarantinedUpload`, and the real authenticated HTTP download. The
test now generates an actual parseable single-page PDF with synthetic text
(rather than just a PDF signature). The API hands **only its new document and
job identifiers** to a distinct OCR-capable, UID/GID 1000 worker through a
mode-`0600` scratch marker. That separate worker, with zero Linux capabilities
and `no-new-privileges`, locks **only this precise new pending job**, records
a bounded running lease, and executes the existing
`process_job_with_lease(..., processor=process_job)` path. It checks the job
completed once, the document was processed, and an authentic `pypdf`
extraction and text segment were committed against the same document/claim
and contain its unique synthetic marker. The worker deletes only its own
temporary scratch Evidence and marker. No staging/Quarantine leftovers are
allowed. The disposable database gains **exactly one Document, one processing
job, one text extraction and one text segment**, while the seeded source
database's matching row counts remain unchanged. The separate temporary DB
is then dropped by the existing guarded cleanup trap.

This proves a bounded authenticated clean upload, live malware scan, DB
admission and **real non-root worker native-PDF text processing**, on a clone
in the same ephemeral PostgreSQL instance, not a separate engine or host.
The existing authenticated document/job test uses a PDF with native text.
A **separate read-only scanned-PDF OCR probe**, executed inside that same
UID/GID 1000 worker, now creates a private image-only PDF without a text
stream: Poppler renders the already verified **large-font, three-line** synthetic
one-page PDF to a grayscale PGM, keeping all expected text well within the
page crop boundary; pypdf then embeds those pixels as a compressed PDF Image
XObject. The Worker image installs the Alpine `font-liberation` package and verifies
that fontconfig resolves Helvetica to a readable Liberation Sans font. Without
a substitute for the PDF's standard Helvetica font, `pdftoppm` may return
a valid-sized but blank synthetic PGM although `pypdf` can read the PDF's
native text stream. This is a real image-rendering dependency, not a reason
to weaken OCR acceptance. The package is added to the Worker image only;
the production API image and customer Evidence volumes are untouched.

The probe first checks that the initial grayscale raster contains real
ink and that **the installed Tesseract** recognizes its synthetic phrase.
It then rasterizes the generated scanned-only PDF independently and requires
the pixel dimensions and visible ink to survive re-embedding. A blank or
invisible intermediate image is an explicit NO-GO rather than an OCR success.
First, native-only extraction must report **no text** and
`requires_ocr=True`. Next, the real `extract_document_text` pipeline with
`enable_ocr=True`, `eng+fas`, a one-page cap and bounded timeout must call
Poppler/Tesseract, return `pypdf+selective-tesseract:eng+fas`, recover the
synthetic marine-claims phrase and declare no remaining OCR requirement.
**Authenticated scanned-PDF persistence (disposable CI clone only):**
After the image-only PDF has passed the independent no-native-text, raster
visibility and real Tesseract checks, the restricted worker starts a separate
loopback Uvicorn API subprocess on port 18082, using the same temporary
UID-1000 Evidence scratch and exclusive new PostgreSQL database. It performs
the seeded synthetic-user login and a real multipart HTTP POST of the actual
image-only PDF. Live CI ClamAV must return CLEAN, the HTTP response must
contain the exact size/hash, and the authenticated download must preserve
the bytes. The Uvicorn process is terminated before job processing.

The worker queries the new `Document` and **only its matching new
`DocumentProcessingJob`**, claims a bounded lease and calls the real
lease-fenced processing path. It then requires COMPLETED status, a processed
Document, an authoritative
`pypdf+selective-tesseract:eng+fas` extraction, a nonempty hash and
matching extracted text segment connected to the correct claim. The final
CI database reconciliation requires **exactly two new Documents, two jobs,
two extractions and two text segments** (native-text and image-only
PDFs) on the clone. The original seeded synthetic PostgreSQL database's
session, Document, job, extraction and segment counts must remain unchanged.
Only the new scratch files are deleted; the temporary database is dropped
by the existing fail-closed cleanup trap. No customer Evidence is involved.

This proves authenticated scanned-PDF admission and durable worker OCR
extraction in a *second database in the same disposable PostgreSQL server*,
not a separate physical server, and not customer-host restore readiness.
The job is explicitly selected by its freshly generated identifier and
processed using the real lease-fenced function; **unrelated queue fairness**
is not proven.

**Authenticated HTTP infection and scanner-outage quarantine proof (CI only):**
After the two clean synthetic documents are successfully processed and
their scratch files removed, a new restricted UID/GID-1000 API process
authenticates a synthetic user and uploads a **valid DOCX ZIP archive**
containing the harmless EICAR test signature as a separate uncompressed
member. Appending the signature to a synthetic PDF header did **not** trigger
the real scanner and is therefore not a valid infection fixture. The
actual DOCX ZIP entry is verified byte-for-byte and the real ClamAV service
must first independently identify the archive as `INFECTED`. The
authenticated HTTP POST must then return **422**, with one durable
`QuarantinedUpload` row at status `infected` and matching private
mode-`0600` bytes under `_quarantine`, without creating a `Document`
or allowing a document download.

A *separate* isolated API process receives a different synthetic PDF
with only its own `CLAMAV_PORT=1` environment override; the central
CI scanner remains healthy. The authenticated POST must return **503**
and persist one distinct `scan_error` quarantine row and matching private
bytes, without admitting the file or allowing download. Both synthetic
quarantines are verified against their SHA-256 and removed **only from
fresh CI scratch**. The clone database must gain exactly two quarantine
records while the seeded source database's quarantined-upload count stays
unchanged, in addition to its unchanged Documents, jobs, text and session
counts. The guarded clone cleanup then drops only this test's database.

These security tests do not prove how production services handle a real
host-wide scanner outage, API restart between quarantine and release, or
independently restored legacy volumes. Production runtime-user changes,
legacy Evidence ACL compatibility, independent host rollback and Pilot GO
remain separately gated.

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
