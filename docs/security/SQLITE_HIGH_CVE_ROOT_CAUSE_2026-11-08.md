# SQLite High findings — root-cause analysis and release-gate runbook

**As of:** 2026-11-08 UTC  
**Repository:** `eh3aneba/maritime-claims-platform`  
**Tracking:** [#876](https://github.com/eh3aneba/maritime-claims-platform/issues/876)  
**Baseline:** `main@800b12549b433164c030047e758cf63d67fed82c`  
**Status:** **OPEN / SECURITY HOLD / CUSTOMER PILOT NO-GO**

This is an engineering and vendor-remediation record, **not** an acceptance of
security risk, a VEX statement, or a request to weaken branch rules.

## 1. Separate the actual failure from its downstream symptoms

The authoritative check is **Container image vulnerability scan** within
`.github/workflows/supply-chain.yml`. Its three Grype scans enforce
`fail-build: true`, `severity-cutoff: high`, and `.grype.yaml` has
`ignore: []`. The normal final enforcement step fails if **any** of the
API, Web, or Worker scan outcomes is not `success`.

Actual push run on the above main:
- [#42491900185](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42491900185)
  completed FAILURE on the image enforcement step.
- **API: failure; Worker: failure; Web: success.**
- Both failing images carried Alpine APK `sqlite-libs 3.53.4-r0`,
  matching four **High** findings: `CVE-2026-119373`,
  `CVE-2026-119374`, `CVE-2026-119379`,
  `CVE-2026-119586`.
- Other reported lower-severity findings do not change the High stop.
  SBOM/dependency and secret-history jobs succeeded; they do **not**
  cancel image vulnerabilities.

Earlier `#875` failures were the same inherited base-image defect, not a
result of profile SQL refactoring. A previously green scan against an
older vulnerability database is historical only; re-running a known failing
scan without a materially different package is not remediation.

## 2. Why SQLite is present though the business database is PostgreSQL

`apps/api/Dockerfile` uses `python:3.14.10-alpine3.24` for the Python
builder, OCR tool builder, final API `base`, and final `worker`.
The official Python runtime's optional `_sqlite3` extension links to
`libsqlite3.so.0`; the API therefore inherits the library independently
of any application-selected PostgreSQL SQLAlchemy URL.

The worker additionally installs Alpine `nss`, used by the
current Poppler PDF-signature backend. NSS has a shared-object dependency
on `libsqlite3.so.0`. Disabling this backend would change document
signature handling, not simply remove an unused database engine.

**Consequences:** deleting Python's `sqlite3` module, forcing `apk del`,
removing NSS, falsifying package metadata, or assuming PostgreSQL eliminates
SQLite would be unsafe without separate end-to-end engineering proof.
No such removal is authorized or delivered here.

## 3. CVE classification — two different remediation conditions

| CVE | Affected subsystem | Status as of 2026-11-08 |
| --- | --- | --- |
| `CVE-2026-119373` | FTS5 heap buffer overflow | Upstream versions before 3.54.0 affected |
| `CVE-2026-119374` | FTS5 heap buffer overflow | Upstream versions before 3.54.0 affected |
| `CVE-2026-119379` | Session changeset heap buffer overflow | Upstream versions before 3.54.0 affected |
| `CVE-2026-119586` | **sqlite3 command-line shell** `.recover` output | Remains unaddressed in upstream 3.54.1 |

Supporting vendor/security sources:
- [Debian library-CVE record fixed by 3.54.1-1](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1152790).
- [Separate unresolved CLI-CVE record](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1152878).
- [Alpine supported stable package reference](https://pkgs.alpinelinux.org/package/v3.24/main/armv7/sqlite-libs).
- [Official SQLite release history](https://www.sqlite.org/changes.html).

No observed `sqlite3` shell executable in earlier bounded base/final image
investigations is **not** proof of CVE remediation or authority for a waiver.
The three library findings cannot be dismissed as CLI-only. A vendor-provided
backport may use a non-obvious version; check its signed provenance and
vendor advisories, not just compare upstream version strings.

## 4. Work completed, and why each attempt does not close #876

| Work | Outcome | Limitation |
| --- | --- | --- |
| [#885 stable-source SQLite upgrades](https://github.com/eh3aneba/maritime-claims-platform/pull/885) | Draft; source-policy tests passed; image scans [#42461481299](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42461481299) failed | Alpine v3.24 currently still ships `3.53.4-r0`; `apk upgrade` cannot install an unavailable signed fix |
| [#886 Alpine package observer](https://github.com/eh3aneba/maritime-claims-platform/pull/886) | Merged; read-only Monday monitoring of official x86_64/aarch64 APKINDEX | Candidate discovery is not a signature verification, image build, or clean Grype scan |
| [#887 Debian Slim feasibility](https://github.com/eh3aneba/maritime-claims-platform/pull/887) | Closed without merge after actual diagnostic [#42495364563](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42495364563) | `python:3.14.10-slim-trixie` still linked SQLite 3.46.1 (`libsqlite3-0 3.46.1-7+deb13u2`); CLI absent and FTS5 synthetic PASS do not establish an all-CVE fix |
| [#877 Alpine Edge diagnostic](https://github.com/eh3aneba/maritime-claims-platform/pull/877) | Held | Owner explicitly rejected production Edge/waiver; also does not clear CLI CVE |

**No safe complete remediation has been verified.** Keep #884/#875/#885/#877
unmerged while the existing security hold is active. Do not create a
false-green image job by changing the path classifier.

## 5. Next executable steps, in priority order

1. **Upstream stable fix:** request an **official signed supported
   Alpine 3.24** SQLite backport that addresses all three library CVEs
   and ask for explicit disposition/patch of CLI `CVE-2026-119586`.
   Maintain a separate upstream request; do not claim one was sent
   until its actual URL/receipt exists. A proposed message is in
   `docs/security/SQLITE_ALPINE_BACKPORT_REQUEST_2026-11-08.md`.
2. **Observe available package:** rely on the already-merged scheduled
   `Supported Alpine SQLite Observation` workflow for the *real* stable
   `sqlite-libs` package version in x86_64 and aarch64. Changed index
   alone only opens human source/CVE review; no automatic merge.
3. **Upon a viable signed source:** rebase Draft #885 onto the latest
   `main`, install only from the supported signed Alpine repository,
   record actual installed versions and CLI presence in **both final
   production images**, and run fresh actual API/Web/Worker Grype
   with `ignore: []` and unchanged High threshold.
4. **Compatibility:** exercise Python `sqlite3`, the NSS/Poppler
   PDF-signature route, PDF rendering, Tesseract Persian/English OCR,
   and PostgreSQL concurrency. Compare signed PDFs and document evidence
   with synthetic data; no unreviewed weakening.
5. **Final merge admission:** all eleven required **exact-head**
   checks SUCCESS, all 64 backend shards where required, no outstanding
   protected review threads, and actual final-image scan evidence on
   the same candidate. No forced merge, exception, classifier bypass,
   or production/customer-pilot release until authorized security owner
   and independent bilingual H&M review obligations are also met.

## 6. Explicitly prohibited shortcuts

- Pulling unapproved Alpine Edge/testing packages into the production
  Alpine 3.24 image.
- Manually injecting unsigned/precompiled SQLite libraries or silently
  substituting rebuilt binaries while leaving SBOM/Grype blind.
- Falsifying package versions, dropping package inventory, downgrading
  High severity, adding a hidden `.grype.yaml` ignore, or redefining
  a failed scan as a success.
- Disabling NSS or the Python SQLite extension without signed-PDF,
  OCR, application-import and dependency-graph validation.
- Promoting a clean **scope-skipped** PR scan into evidence that
  the final production images have no vulnerabilities.

This file is an evidence-backed checkpoint, not a claim that the
supplier-dependent fix has been accomplished.
