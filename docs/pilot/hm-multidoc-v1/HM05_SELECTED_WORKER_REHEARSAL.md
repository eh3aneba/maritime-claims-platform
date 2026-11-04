# HM-05 selected pinned worker rehearsal — 2026-11-01

**Synthetic only. Independent bilingual H&M acceptance: PENDING. Pilot: NO-GO.**

The selected worker now reproduces the clause-boundary omissions against the
unchanged original raster. This is engineering reproduction, not expert source
adjudication, a corrected transcript or authorization to approve an Assessment.

## Exact source and image

- Application/Dockerfile: `fa2c471463f5aecb988f89e791aae359385227e4`;
  `apps/api` tree `f239abea5a30d08e3b5d7a3c4508ff91fa55057a`.
- Local image **configuration digest**, not a published registry digest:
  `sha256:63b5d8850d5ac76cc0bb2b2f8f95a837c8748b05574683dc492566f06318b5da`.
  No registry push occurred; `RepoDigests` is empty.
- Tesseract **5.5.3**, source commit
  `8ae68101439b3f7df123499a784e8896c805179d`; Leptonica 1.87.0,
  LibTIFF 4.7.2, Poppler 25.12.0. Pinned English/Persian language data and
  their measured hashes are in the [observation](validation/hm05-selected-worker-2026-11-01.json).
- Original PNG SHA-256:
  `1eef5de99985ee76048f93b04b7184c9a5daf4b6f33441b36c99e9a850e56d4c`.
  All eight original reviewer-packet checksums still pass. The historical
  `docker-replay.pending.json` inside that frozen packet is preserved; this
  separate observation supersedes its runtime-reproduction status only.

## Build and setup limits

The published network policy now permits the four requested domains. GitHub API
and necessary source downloads worked. No environment configuration was changed
or republished by this execution.

Build from `git archive <source-sha>:apps/api`, extracted with readable archive
modes, instead of using restored workspace file permissions. The first build
copied restored `0600` source files as root-owned files. UID 1000 could run the
engine but could not read application/Alembic files; the migration failed with
`PermissionError` and the mounted harness import also failed. These setup
attempts are excluded from successful migration/service results. No runtime
root fallback, broad permission relaxation or production-code fix was used.

The repository Dockerfile is unchanged. For this managed environment only,
each `RUN` was prefixed with a required BuildKit secret mount of the combined
system/session CA bundle and shell exports of `SSL_CERT_FILE`, `PIP_CERT`,
`REQUESTS_CA_BUNDLE` and `GIT_SSL_CAINFO` to that mounted bundle. The exact
original commands, source commits, package/artifact checks and TLS verification
were retained. No CA file was copied into image layers. Both original and
CA-adapted Dockerfile hashes are recorded in the observation.

From the repository root, reproduce the context and trust-only adaptation:

```bash
set -euo pipefail
hm05_context="$(mktemp -d)"
hm05_dockerfile="$(mktemp)"
git archive fa2c471463f5aecb988f89e791aae359385227e4:apps/api |
  tar -xpf - -C "$hm05_context"
python - "$hm05_context/Dockerfile" "$hm05_dockerfile" <<'PY'
from pathlib import Path
import hashlib, sys
source = Path(sys.argv[1]).read_bytes()
assert hashlib.sha256(source).hexdigest() == "7f629fcd0e61e0a0b15ca5ed533954e8dd732b180b1b65130a8c27c09ba6472b"
prefix = "RUN --mount=type=secret,id=proxy_bundle,required=true export SSL_CERT_FILE=/run/secrets/proxy_bundle REQUESTS_CA_BUNDLE=/run/secrets/proxy_bundle PIP_CERT=/run/secrets/proxy_bundle GIT_SSL_CAINFO=/run/secrets/proxy_bundle; "
adapted = source.decode().replace("RUN ", prefix)
assert hashlib.sha256(adapted.encode()).hexdigest() == "2eca59c0a5aba73844b9010e46a9e979de66cf93a6699a4e2861b33df0c300a3"
Path(sys.argv[2]).write_text(adapted)
PY
docker build --target worker --progress=plain \
  --secret id=proxy_bundle,src=/etc/ssl/certs/ca-certificates.crt \
  -f "$hm05_dockerfile" -t seeclaims-hm05-worker:reproduction "$hm05_context"
```

Use the supported session proxy and combined CA trust. Do not disable TLS,
checksums or package verification if another environment lacks those prerequisites.

## Actual execution and discrepancies

Fresh PostgreSQL **18.4** migrations reached
`0224_obs_refresh_recovery_anchor`. On an internal-only Docker network, with
no published ports, the image ran as **UID/GID 1000**, read-only root filesystem,
all capabilities dropped and `no-new-privileges`. Only bounded `/tmp` and
synthetic document-storage tmpfs paths were writable.

The [replay harness](validation/hm05_selected_worker_replay.py) calls the real
upload service, ClamAV scanner, job claim/processing and source-preview functions
using an invented organization/user/claim fixture. It is a **service-level**
rehearsal, not HTTP authentication, browser, independent operator-host or
real-review acceptance. No scanner stub, transcript patch or source-text
replacement was supplied. The scanner returned CLEAN; that verdict does not
establish an approved signature-freshness policy. ClamAV 1.5.4 reported database
28164 dated 2026-10-25; no acceptable-age threshold was invented.
The Claim's dates are fixed fixture setup values, explicitly unrelated to OCR
date adjudication; no date was normalized or promoted from the machine text.

The [exact raw engine output](validation/hm05-selected-worker-engine-raw.txt)
has SHA-256 `b9ede8b00dba60daa0885d6900f67b340248f9856259209cf9499eed39052ac3`.
Its trailing whitespace differs from the stored text. Applying only the
existing application's documented `.strip()` produces the exact persisted
transcript hash:
`5a2304f4b11d628d7694eb38e24d8d335bf8dbf31e0e0b5cb639bc2cd0bd3cd2`.
An independent PostgreSQL connection confirmed this persisted hash after the
worker exited. It is byte-identical to the earlier native persisted transcript;
the frozen packet's machine file is therefore reused without rewriting it.

- Paragraph 2 / machine raw line 3 loses ` شد.` at source UTF-16 [60,64).
- Paragraph 3 / machine raw line 5 loses ` است.` at source UTF-16 [50,55).
- `معلوم نیست` remains present. A retained negation token does not retrieve
  the complete authored clause or establish semantic fidelity.
- The two short continuation endings are visible in the original raster.
  This localizes these omissions to the OCR stage, not an observed persistence
  corruption; it does not establish the engine's internal reason for omission.
- Authored logical date `۲۰۲۶-۰۹-۱۱` differs from the raster's displayed order
  and machine sequence `۱۱-۰۹-۲۰۲۶`. The renderer/RTL presentation is already
  part of the comparison. Do not blame OCR alone, silently normalize a date,
  or decide its intended meaning without bilingual adjudication.

Locators remain **document version 1, page 1, segment 0**. The persisted
extraction has `requires_ocr=false` (text is available), while source-preview
readback remains `machine_unverified` and
`ocr_human_source_comparison_required`. No ClaimFact or Assessment was created.
These are the baseline OCR source-comparison controls, not a new human
discrepancy attestation or dispute resolution. Independent review fields and
the original [bilingual packet](reviewer-packet-hm05-2026-11-01/README.md)
remain unchanged and pending.

## Reproduction contract and next acceptance

Use a fresh disposable database with the pinned image and unchanged packet
mounted read-only at `/review`, and the harness mounted read-only at `/replay.py`.
Set synthetic-only test configuration, AI/external integrations disabled,
OCR enabled with `eng+fas`, real ClamAV enabled and a private generated test
secret. Supply `DATABASE_URL`, `CLAMAV_HOST` and writable synthetic
`LOCAL_STORAGE_PATH` through a private environment file, never repository or
logs. Run `alembic upgrade head`, then `python /replay.py` using the restrictions
above. Never point this fixture at an existing/customer database. The harness
asserts UID 1000, original raster hash, actual clean scan, completed processing,
persisted transcript hash integrity, source-review state and zero facts/assessments.
The final harness was re-executed successfully on another fresh database. Its
test-mode/disabled-AI/dedicated-database/empty-dataset assertions were retained.
Two negative invocations returned nonzero before fixture writes: non-test mode
and an existing synthetic dataset. The first populated-database negative runner
omitted the required read-only `/review` mount and failed at fixture setup;
that attempt is excluded, and both guard checks passed with the complete mount
contract. The populated-database rejection left one organization/claim and the
same extraction hash, confirmed through a separate PostgreSQL connection.
Record fresh image/runtime identities rather than reusing this run's attestation.

Next acceptance requires an authorized bilingual H&M reviewer to examine the
original and exact transcript, answer the existing packet's source-linked
questions and record a governed workpaper. This reproduction neither supplies
that person nor closes #810/#850, clears a hold or authorizes customer Evidence.

## Replay-helper optimization guard correction — 2026-11-02

The historical successful replay above used ordinary Python, not optimization.
A later review found its standalone helper used `assert` for safety preconditions
and postconditions. A content-free isolated reproduction of the original UID
preflight with injected UID 0 rejected normally but continued with `optimize=2`.
No application import, database or real evidence was involved in that reproduction.

The reusable helper now raises explicit nonzero failures instead of relying on
assertions. Its runtime settings, expected database name, exact immutable raster
hash, empty organization/claim/document dataset, scan/worker/source/hold checks
survive optimization. Importing it is inert; an invalid UID fails before application
imports. The change affects the synthetic replay tool, not production evidence
admission, OCR output, source holds or historical receipt fields.

```bash
python -m unittest discover \
  -s docs/pilot/hm-multidoc-v1/validation \
  -p test_hm05_replay_guards.py -v
```

Six tests passed, exercising 17 preflight scenarios in **both ordinary and `-O`
subprocesses** (34 invocations), including seven unsafe settings, wrong UID,
modified/missing raster bytes, wrong DB names and existing data at each guarded
model position. Application imports are forbidden in these synthetic preflight
tests. Valid preflight is not scanner, OCR, operator or human acceptance.
At the initial guard-only review stage the revised helper had not yet been
re-executed against Docker/PostgreSQL; the subsequent run below supersedes that
execution-status limitation. Historical runtime/source receipts and the frozen eight-file packet
remain unchanged and retain their original provenance; do not substitute the new
helper hash into old run evidence. Independent reviewer acceptance remains pending.


## Subsequent optimized full replay — 2026-11-02, 10:35 Asia/Tehran

[New runtime receipt](validation/hm05-optimized-guarded-worker-2026-11-02.json)
binds helper commit `f201644fc448bdc7d7287aaf2982808ed950ec9b` and its SHA-256
to the same unchanged raster and cached pinned worker image. A fresh internal-only
PostgreSQL 18.4 database migrated to `0224_obs_refresh_recovery_anchor`; real
ClamAV scanned the upload and `python -O /review/replay.py` completed processing.
Worker UID1000, read-only root, ALL capability drop, no-new-privileges and bounded
scratch mounts were retained, with no published ports or external AI.

The persisted transcript hash remained
`5a2304f4b11d628d7694eb38e24d8d335bf8dbf31e0e0b5cb639bc2cd0bd3cd2`,
verified again from PostgreSQL after worker exit. Review state remained
`machine_unverified` / `ocr_human_source_comparison_required`, with zero ClaimFacts
and Assessments. Subsequent populated-dataset and production-mode invocations
both returned 1 under optimization; organization/claim/document fixture counts
remained `1|1|1`. Disposable containers, internal network and private environment
files were removed. No historical packet or receipt was rewritten.

The application image is still explicitly source `fa2c471463f5aecb988f89e791aae359385227e4`,
not a rebuilt latest-main image. This verifies the corrected helper with that
selected runtime; it does not repair the omitted clause endings, adjudicate date
ordering, attest signature freshness, verify an independent workpaper or confer
expert/host/customer acceptance. The incomplete transcript and review holds remain.
