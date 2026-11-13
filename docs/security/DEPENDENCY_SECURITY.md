# Supply-Chain Security, Final-Image Scanning, and Base Refresh

This file describes the **current repository enforcement**, not a deployment or
customer-data authorization. Operational pilot readiness remains governed by
[#653](https://github.com/eh3aneba/maritime-claims-platform/issues/653) and the
scope freeze in [#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647).

## Required security controls

[Supply Chain Security](../../.github/workflows/supply-chain.yml) runs on
`main` pushes, `main` pull requests, its weekly schedule, and manual dispatch:

- `pip-audit` checks the hashed Python production lockfile
  `apps/api/requirements.lock`; `npm audit` checks production Web packages.
- Syft produces a **repository-manifest SPDX SBOM** as a GitHub Actions artifact
  retained for seven days. This artifact is **not a complete assertion of every
  custom C/C++ component compiled into the final image**.
- Gitleaks inspects Git history; suspected secrets must not be copied into
  PR comments or uploaded findings artifacts.
- Real final `api`, `worker`, and `web` container images are built and
  scanned by Grype. **High and Critical** findings fail the image gate; the
  final `Enforce image scan results` step must pass. The current
  [`.grype.yaml`](../../.grype.yaml) is exactly `ignore: []`.
- The changed-path classifier forces the final-image scan when runtime
  Dockerfiles, code/build tools, dependencies or security scan workflows change.
  For a source-only or documentation change outside this scope, a PR may skip
  expensive image builds according to the audited classifier; do **not** call
  a scope-skipped scan `PASS`.

Cross-architecture evidence is separate:
[SQLite-Free ARM64 Feasibility](../../.github/workflows/sqlite-free-arm64-experiment.yml)
builds **actual** native ARM64 API/Worker final images, scans both with the
unchanged Grype High policy and runs a restricted/offline/non-root synthetic
PDF-extraction, OCR and SQLite-absence probe.
[Web ARM64 Base Digest Verification](../../.github/workflows/web-base-arm64-pin.yml)
builds and scans the actual native ARM64 Web final image, including a restricted
offline runtime check. Both run on matching pull-request changes. A normal
`main` push runs the required Supply Chain workflow, **not necessarily these
PR-only ARM64 workflows**. Preserve exact SHA and architecture in the audit record.

## Current base image references (November 13, 2026)

These are **immutable image-index identities**, not a claim of publisher signature
verification. The authoritative values are the checked-in Dockerfiles:

| Runtime/build source | Pinned image reference | Used by |
| --- | --- | --- |
| Python 3.13.18 / Alpine 3.24 | `python:3.13.18-alpine3.24@sha256:9ef1a599f863231c3d91e941389bfdc4a2d6070557243d54df1a4e57015b960e` | API/Worker Python builder and sanitized stdlib source |
| Alpine 3.24 | `alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf` | Final API/Worker OS root |
| Node 22 / Alpine 3.24 | `node:22-alpine3.24@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a` | Web deps, builder and final runner |

The final Python images deliberately do **not** inherit original Python base
layers. The sanitized Python stdlib copied into Alpine excludes `_sqlite3`,
and the image builds fail closed if the SQLite shared library/package remains.
The Worker builds Poppler with **NSS and GPGME disabled**; this removes its
cryptographic PDF-signature verification backend. Ordinary text extraction,
rasterization and Tesseract OCR are not cryptographic signature verification.
Product/security acceptance for signed incoming PDF evidence is tracked under
[#894](https://github.com/eh3aneba/maritime-claims-platform/issues/894).
Persian-language legal/H&M source fidelity remains [#810](https://github.com/eh3aneba/maritime-claims-platform/issues/810).

Successful source PR [#893](https://github.com/eh3aneba/maritime-claims-platform/pull/893)
was merged at `e921af33eec7ca89aedad4af481f6850deacae0c`.
The **actual post-merge** [Supply Chain run #43389106224](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/43389106224)
passed final API/Worker/Web High scans, audit/SBOM and Secret History.
Web base pin [#895](https://github.com/eh3aneba/maritime-claims-platform/pull/895)
was merged at `27d64f2e072f64b26ab1921da19150876dff77ff`.
On its exact source PR head, native Web ARM64 [#43405995559](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/43405995559)
and required Supply Chain [#43405995469](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/43405995469)
both passed. These historical run links do **not** attest subsequent image
updates. Record a fresh main-push run for every merged base change.

## Safe base refresh procedure

Use one reviewable PR per affected stack, with issue/owner and the exact old
and proposed tag + manifest-list digest. Do **not** silently repoint a pinned
digest, lower Grype's cutoff, or use unapproved Alpine Edge, third-party APKs
or unsigned source patches to make a red gate green.

1. Identify the triggering upstream advisory, supported fix and affected
   architecture/package. For a new digest, verify official image source,
   registry identity and manifest-list platforms **independently of** its
   tag; a matching digest alone does not establish source authenticity.
   Record source links and the date of verification.
2. Change the selected Dockerfile `FROM` references together (all Web
   stages; relevant API/Worker Python and Alpine stages). Confirm supported
   runtime compatibility and evaluate OS package upgrades and C/C++
   libraries separately. Never infer that an unchanged parent digest yields
   a byte-for-byte reproducible final image when `apk`, `pip`, `npm`
   or external source downloads can still vary.
3. Run the protected PR checks on the **exact head**: hashed dependency
   audit/SBOM, Secret History, final API/Worker/Web Grype High gate,
   PostgreSQL migration and concurrency, Web typecheck/browser E2E,
   operational performance, production policy and the backend gate
   according to its audited scope. For affected images run the appropriate
   native ARM64 gate; a missing, failed or skipped required check is **not**
   a pass.
4. If compiled sources (e.g. Poppler, Tesseract, LibTIFF or Leptonica)
   change, review their release/advisory status and independently verify
   download provenance, expected hash, final-image component inventory,
   ABI compatibility, and meaningful PDF/OCR test coverage. The repository
   SPDX manifest SBOM and a green Grype scan do not prove complete C/C++
   source-component coverage.
5. Only after all required checks and authorized review succeed, merge by
   the allowed method. Check the **post-merge main-push** security run and
   record its commit, image digests/architecture and conclusions. A source
   PR's success cannot stand in for a failed or unexecuted post-merge scan.
6. Update the refresh ticket and release-candidate document with owner,
   date, old/new references, reasons, results and rollback considerations.
   Keep any unresolved pilot controls visibly **NO-GO**. Merging code
   never constitutes deployment/customer-pilot approval.

Track the follow-up base-update cadence/ownership in
[#474](https://github.com/eh3aneba/maritime-claims-platform/issues/474)
and separate Postgres/ClamAV pinning in
[#488](https://github.com/eh3aneba/maritime-claims-platform/issues/488).
Recheck supported image and vulnerability metadata regularly, and open a
scoped update PR when an authoritative fix or end-of-support condition
requires refresh. Never defer a verified urgent vulnerability solely to the
normal review cadence.

## Exceptions and incident handling

**Current Grype exceptions: none** — `.grype.yaml` has `ignore: []`.
Prior documents describing a temporary `CVE-2026-15308` exception that
expired in September 2026 were historical and must not be represented as an
active policy. SQLite High image findings were addressed by removal of
unused SQLite runtime dependencies, not by suppressing or accepting the
vulnerability reports.

If a real secret is found in history, revoke/rotate it before treating
removal from the latest commit as remediation. If a scanner reports an
apparent false positive, seek documented upstream/vendor component advice
and independent security review; record a dedicated, time-bounded,
explicitly authorized exception only under repository policy and never
quietly change `.grype.yaml` to bypass protected checks. No such exception
is currently approved.

## Useful local commands

```bash
# Production dependencies
pipx run pip-audit --require-hashes -r apps/api/requirements.lock
npm audit --omit=dev --audit-level=high --prefix apps/web

# Build production-target images
docker build --tag maritime-claims-api:local apps/api
docker build --target worker --tag maritime-claims-worker:local apps/api
docker build --target runner --tag maritime-claims-web:local apps/web
```

The authoritative security result comes from the **exact image and SHA**
scanned by the protected GitHub workflow, with its current vulnerability
database and no hidden ignore rules. This file is a process guide,
not a signed SBOM, runtime attestation or release certificate.
