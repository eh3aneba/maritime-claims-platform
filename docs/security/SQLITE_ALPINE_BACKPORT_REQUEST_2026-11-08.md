# Alpine 3.24 stable SQLite security backport — mailing-list request SENT, GitLab issue pending

**Originally prepared:** 2026-11-08. **Updated with live, final-image evidence:** 2026-11-09.  
**Submission status:** **Email SENT 2026-11-09**, verified in the connected Gmail Sent folder. Recipient: public Alpine development list `~alpine/devel@lists.alpinelinux.org`; CC: public sqlite APKBUILD maintainer `huajingyun@loongson.cn`. **GitLab issue NOT submitted; no Alpine maintainer acknowledgement or patch exists.** A Sent-folder record confirms a message was submitted for delivery, not that the list accepted or a maintainer read it.  
**Intended channel:** official [Alpine aports packaging issues](https://gitlab.alpinelinux.org/alpine/aports/-/issues) or an approved Alpine security channel. The GitHub aports repository is a read-only mirror for these purposes; do not claim a GitHub report was submitted.  
**Tracking:** [SeeClaims #876](https://github.com/eh3aneba/maritime-claims-platform/issues/876).  
**Safety:** this document includes public vulnerability and synthetic runtime information only. It does not authorize deployment or CVE suppression. The mailing-list message sent was an earlier condensed technical variant of the detailed template below; do not claim the full template was sent verbatim.

## Sent mailing-list request: technical content and GitLab-ready template

**Suggested title:** Alpine v3.24: request signed supported sqlite-libs FTS5/SESSION security backport; clarify CLI-only CVE-2026-119586

Hello Alpine maintainers,

The supported official Alpine **v3.24/main** SQLite package `sqlite-libs 3.53.4-r0` is still present in the signed repository indexes for **x86_64 and aarch64**. We verified the actual native-architecture indexes using `apk` inside unmodified official `alpine:3.24` containers, each with its own bundled trusted APK keys and only the official stable repositories. Both jobs succeeded in [read-only signed-index run #42560311243](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42560311243); candidate on both architectures: `3.53.4-r0`. This proves authenticated repository **metadata**, not an installed patched library.

We maintain an application with Python `_sqlite3` and the NSS-dependent Poppler PDF-signature backend. Our actual **final** Alpine-based Python 3.14.10 API and Worker images each contain the SQLite shared library. The relevant supported-image security evidence is:

| Evidence | Final API | Final Worker |
| --- | --- | --- |
| APK sqlite-libs package | `3.53.4-r0` | `3.53.4-r0` |
| Python SQLite library version | `3.53.4` | `3.53.4` |
| Mapped library | `/usr/lib/libsqlite3.so.3.53.4` | `/usr/lib/libsqlite3.so.3.53.4` |
| FTS5 compiled and synthetic in-memory FTS5 check | **YES** | **YES** |
| `ENABLE_SESSION` compiled | **YES** | **YES** |
| `sqlite3` shell executable in final image | **NO** | **NO** |
| Mandatory Grype (`--fail-on high`, no ignores) | **FAIL: four High** | **FAIL: four High** |

This was reproduced in [Supply Chain Security run #42586615777](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42586615777), then repeated after an additional fail-closed observer/version-provenance check in [run #42589764085](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42589764085). The final Web image passed. The complete set of distinct High matches in each failing image is `CVE-2026-119373`, `CVE-2026-119374`, `CVE-2026-119379`, `CVE-2026-119586`.

Based on [Debian's security bug group](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1152790) and [upstream SQLite release history](https://sqlite.org/changes.html), the first three issues affect library FTS5/Session paths in pre-3.54.0 SQLite and have upstream fixed versions in the 3.54 series. `CVE-2026-119586` is a **separate** security question involving the `sqlite3` command-line `.recover` output being subsequently interpreted as dot-commands. Its [Debian security tracker](https://security-tracker.debian.org/tracker/CVE-2026-119586) still records **undetermined** through Debian sid SQLite `3.54.1-2`. [SQLite 3.54.1](https://sqlite.org/releaselog/3_54_1.html) is **not** an established fix for that CLI issue.

**Requests:**

1. Could Alpine provide or identify a **supported, signed v3.24 stable-repository backport** to `sqlite-libs` for the three library CVEs (including required ABI/soname and dependent package compatibility)? Please link the official package revision, patch/MR, and corresponding Alpine security advisories.
2. Please clarify **`CVE-2026-119586` applicability to the `sqlite-libs` shared-library subpackage** versus the separate `sqlite3` CLI binary package. In particular, would Alpine issue a signed-package-level applicability ruling or advisory update for library-only installations with no CLI? We are **not** asking for a downstream scanner exception based solely on absence of the shell.
3. If an official CLI fix or Alpine backport exists, please identify its **upstream commit/fixed release**, signing provenance, and supported v3.24 package revision in both architectures.

We explicitly **do not** request Alpine Edge, unsigned or third-party APKs, renamed package metadata, weakened Grype thresholds, or a finding suppression. We will independently verify a signed package in both *actual* final images, re-run all original High-severity Grype scans and runtime/PDF/OCR regression tests, and keep deployment blocked until successful.

Thank you for any authoritative supported-branch package and applicability guidance.

## Reproduction references (non-sensitive)

- [Authenticated native x86_64/aarch64 v3.24 APK index checks](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42560311243).
- [Final-image package, loaded shared object, FTS5/SESSION/CLI inventory and Grype results](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42586615777).
- [Repeated provenance-validated final-image results](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/42589764085).
- [Official SQLite release chronology](https://www.sqlite.org/chronology.html).
- [Debian CVE-2026-119586 unresolved tracker](https://security-tracker.debian.org/tracker/CVE-2026-119586).
- [Separate Debian upstream CLI report](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1152878).

## Submission, package, and release gates

| Gate | Verified state on 2026-11-09 |
| --- | --- |
| Alpine development mailing-list request | **SENT 2026-11-09; no acknowledgement or response yet** | 
| Alpine GitLab aports issue URL/receipt | **NONE — not filed** |
| Supported, independently verified signed Alpine v3.24 fixed SQLite candidate | **NO: currently 3.53.4-r0 (both arches)** |
| Authoritative CLI applicability/repair ruling | **NO** |
| Final API/Worker Grype High | **FAIL / FAIL** |
| Final Web Grype High | **PASS** |
| SeeClaims Draft #885 merged | **NO** |
| SeeClaims issue #876 closed | **NO** |
| Production and real-customer pilot | **NO-GO** |

**Evidence validity boundary:** a successful read-only repository-index verification, a zero-CLI runtime probe, or successful PR-scoped unit checks **does not** waive any unresolved Grype High match. Only actual supported vendor evidence and a full authorized release gate may change this status.
