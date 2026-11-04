# SQLite runtime library remediation proposal — 2026-11-04

**Partial proposal, not merge-ready.** Tracks [#876](https://github.com/eh3aneba/maritime-claims-platform/issues/876)
and blocks #875 security admission. No scanner exception or production source
choice has been approved. No customer evidence or external AI is used.

## Confirmed observations

The final #875 image job126437976153 (run41789077386) correctly failed on four
High findings against `sqlite-libs3.53.4-r0` in API/worker images:
`CVE-2026-119586`, `CVE-2026-119374`, `CVE-2026-119379`, `CVE-2026-119373`.
The web scan passed. This runtime package predates the SQL-template change.
Both main and PR use Python base digest
`sha256:eb2c62658b8d51bff0acc408504b76521d02030de56a8a3c1e830083e89b89d2`.
Main's earlier successful scan used the November3 Grype DB; the new failing
scan uses November4 DB. Historical success does not clear newer findings.

Official Alpine3.24 still offers3.53.4-r0. Official edge offers3.54.1-r0.
CNA records mark the three library heap-corruption findings as before3.54.0;
CVE119586 instead concerns CLI `.recover` through3.54.1, with no fixed version
listed. The exact base has FTS5/SESSION enabled and no sqlite3 executable.
Base-only CLI absence does not prove final API/worker inventory, reachability,
non-exploitability or entitlement to an exception.

## Proposed change and actual isolated verification

Install only the explicitly pinned, official signed `sqlite-libs=3.54.1-r0`
from Alpine edge in both runtime stages, after stable packages. Edge is not
persisted as a repository. Default APK signature verification and TLS remain;
no untrusted flag, force-broken removal, feature omission, base-image migration,
application dependency/lock/schema or scanner-policy change. **Mixing this one
edge package into stable3.24 is a proposed source/compatibility decision requiring
review**, not an assertion that edge is an approved production baseline.

A build-only helper rejects the old runtime with nonzero exit, then exercises
synthetic in-memory Unicode roundtrip and FTS5 query, requires the retained
SESSION/FTS5 features and reports CLI presence. It reports compatibility only;
it never awards vulnerability admission, OCR resolution or human acceptance.

An isolated diagnostic image made exactly one package upgrade3.53.4→3.54.1;
real compatibility probe failed on old and passed on new. No network or host
Evidence mount in runtime probes. Build used an ephemeral public combined CA
mount; it was never copied into a layer, and no TLS/signature bypass was used.

Verified official Grype0.110.0 against its published checksum, using the same
November4 DB, repo `ignore: []` and `--fail-on high`: probe **exited2**, with
only **CVE-2026-119586 High** remaining. The three library High matches no longer
appeared. This is a base-only diagnostic, **not a clean security scan or full
final-image acceptance**. [Bounded observations](evidence/sqlite-runtime-2026-11-04.json)
record exact versions, source pins, actual exits and unapproved fields.

## Required review and acceptance

1. Prefer a supported signed stable package when available; review the exact
   proposed vendor-source pin/backport, ABI and long-term availability risk.
2. Build and inspect both final API/worker images, verify runtime version and
   preserved features, NSS/OCR/API synthetic compatibility and actual CLI
   presence/absence. Observe fresh authoritative scanner results; do not use
   only the base probe or infer the remaining CVE is cleared.
3. If the CLI finding is confirmed non-applicable to both final images, any
   proposed metadata/VEX exception must be separately reviewable under
   [dependency security policy](DEPENDENCY_SECURITY.md), with exact CVE/package/
   version/type, concrete evidence, accountable owner and expiry. **No active
   exception is present here**, no expiry chosen and no real library issue
   suppressed. Future CLI presence must not be silently covered by an exception.
4. Only after the required security gate and all applicable final-head checks
   actually pass may normal protected merge be considered. All11 check names,
   full64 production-backend regression, classifier and High cutoff retained.
   Docker compatibility success or Draft Backend skip is not a security pass.

Accountable security/operations owner **UNASSIGNED — HUMAN APPOINTMENT REQUIRED**;
source decision **NOT APPROVED**; exception/expiry **NOT APPROVED**. No approval
is inferred from generic merge authorization. Original #875 stays unmerged until
its blocker is resolved. Related manual main scan41813290992 also failed in the
secret-detection step; #764 requires private owner triage. No raw secret values
were fetched/copied or new secret/rotation diagnosis claimed here.

Rollback is reverting this package/helper change and rebuilding images; doing so
restores the known vulnerable library, not security acceptance. Keep production
and customer pilot **NO-GO** until their independent gates are satisfied.

Sources: [SQLite releases](https://www.sqlite.org/changes.html),
[stable index](https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/APKINDEX.tar.gz),
[edge index](https://dl-cdn.alpinelinux.org/alpine/edge/main/x86_64/APKINDEX.tar.gz),
[CNA CLI record](https://cveawg.mitre.org/api/cve/CVE-2026-119586),
[CNA FTS5 record](https://cveawg.mitre.org/api/cve/CVE-2026-119374),
[CNA session record](https://cveawg.mitre.org/api/cve/CVE-2026-119379),
[CNA second FTS5 record](https://cveawg.mitre.org/api/cve/CVE-2026-119373).
