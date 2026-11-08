# Alpine 3.24 stable SQLite security backport request — prepared, NOT submitted

**Prepared:** 2026-11-08  
**Upstream target:** Alpine Linux aports / `main/sqlite` stable
`v3.24` maintenance. Submit through the **official** Alpine packaging
issues channel once a suitable authorized account is available.
Do not claim this draft was sent.

## Suggested upstream report (public CVEs only)

**Title:** Request Alpine v3.24 supported signed sqlite-libs backport for
CVE-2026-119373, CVE-2026-119374, CVE-2026-119379; clarify CVE-2026-119586 CLI

Alpine v3.24 official `main` repositories for x86_64 and aarch64
currently offer `sqlite-libs 3.53.4-r0` (last verified 2026-11-08 in
a read-only official APKINDEX check). Three public issues in the shared
SQLite library's FTS5/session code affect upstream versions before
3.54.0: CVE-2026-119373, -119374 and -119379. Official upstream
SQLite 3.54.1 fixes these library bugs, but
CVE-2026-119586 specifically concerns the `sqlite3` CLI `.recover`
pipeline and still affects 3.54.1 per the public CVE and Debian
maintainer record.

For users on the supported `v3.24` branch who need
`so:libsqlite3.so.0` for Python `_sqlite3` or NSS, would Alpine
consider a signed stable-branch security backport for the three library
issues? Separately, could maintainers clarify the official mitigation
or future patch strategy for CLI-specific CVE-2026-119586, including
whether the CLI-only exploit condition is relevant to the
`sqlite-libs` subpackage? A new version alone should not be
interpreted as clearing all four advisories.

We are not requesting Alpine Edge in production, unsupported APK inputs,
a scanner exception, or a package rename. A public signed stable package
and its upstream security provenance would allow downstream users to
run independent final-image scans under unchanged High-severity
policies.

References:
- https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1152790
- https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1152878
- https://pkgs.alpinelinux.org/package/v3.24/main/armv7/sqlite-libs
- https://www.sqlite.org/changes.html

## Submission and resolution tracking

- Submission status: **NOT SENT**.
- Upstream issue/MR URL: **NONE**.
- Signed stable package version: **NOT YET VERIFIED**.
- CLI-specific upstream remediation: **NOT YET VERIFIED**.
- Final API/Worker/Web Grype High scans: **NOT PASSED**.
- Independent security/operations owner: **UNASSIGNED**.
- Customer pilot: **NO-GO**.

Do not mark any entry resolved without an actual upstream
receipt, package index, signed repository inventory and image-scan logs.
