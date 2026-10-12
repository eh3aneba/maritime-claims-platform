# Pilot P0: controlled real-OpenSSH N+1 acceptance

Related: [#656](https://github.com/eh3aneba/maritime-claims-platform/issues/656), [#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647), [#660](https://github.com/eh3aneba/maritime-claims-platform/pull/660), [#661](https://github.com/eh3aneba/maritime-claims-platform/pull/661).

## Intent and executed boundaries

Run the opt-in Python acceptance `apps/api/tests/test_external_document_source_live_sftp_nplus1_governed_acceptance.py` against the existing **ephemeral localhost OpenSSH** in the `Pilot Real SFTP Acceptance` workflow, together with actual PostgreSQL 18.4 and Alembic migrations.

The test intentionally reuses **synthetic/deterministic initial canonical v1** fixtures. It rebinds *only the test provider request* (never the persisted governed profile or production egress restrictions) to 127.0.0.1 and the runner's ephemeral public-key credential. The **production LiveSftpRuntime** performs the real metadata and changed-file content reads. The actual SFTP user receives no shell and no write authority.

The complete tested trajectory, if CI confirms success, is:

1. Existing governed synthetic v1; schedule and due-tick dispatched into real Postgres.
2. One real OpenSSH exact-file stat yields changed result against v1.
3. Project a review handoff; require an explicit human approval **in the application's authorization model** (synthetic test actor, not a real human session).
4. One production real SFTP exact-file read of the approved synthetic bytes; quarantine staging and same-key replay without additional SFTP read.
5. Separate synthetic human-role admission authorization; canonical version 2 with immutable original version 1 and exact digest/byte count.
6. Same-key canonical admission replay without duplicate version.
7. Recurring baseline transition; next scheduled **real SFTP stat** yields unchanged, without another content read.

## Safety and release boundaries

- Application-level human-authorizer flows run with synthetic test actors; no actual claims handler or customer signed off.
- Malicious-file scanning and signature verification are test doubles for this specific new version. It does **not** prove production scanner correctness.
- This is not a real-server initial v1 intake, not a process-kill fault injection, and not a full negative-case matrix.
- The fixture payload is synthetic and short. Avoid uploading any SFTP credentials, private keys, real document bytes or unsanitized server logs to artifacts.
- Both positive success and permission failures must remain **fail-closed**. A skipped workflow or green generic CI without the named real-server test is insufficient.
- Record the **exact SHA** of the successful runner in Issue #656. The PR is not a Pilot GO decision.

## Pilot exit not yet satisfied

Issue #656 remains open until all its complete real-environment v1 → N+1, restart/replay, failure, isolation and privacy acceptance criteria are verified. The production-readiness checklist (#653) and mandatory main branch protection (#461) also remain open. No authorized use of live customer claim data follows from this isolated test.

## Exact-head CI step-outcome evidence (2026-10-11 hardening)

The named `Pilot Real SFTP Acceptance` workflow now checks out the **PR head SHA** on pull requests (and the dispatch SHA on manual runs), rather than silently treating the GitHub-generated PR merge ref as the tested head. It verifies `git rev-parse HEAD` against that exact candidate SHA when writing an exclusive `summary.json` through `scripts/pilot_real_sftp_ci_evidence.py`.

The evidence contains only the run identity, synthetic OpenSSH package version when observed, and **six fixed step outcomes**: PostgreSQL schema; OpenSSH setup; direct real-SFTP runtime; real PostgreSQL due-tick; synthetic human-authorized N+1; and real-SFTP initial custody. Each outcome is one of `success`, `failure`, `cancelled`, `skipped`, or sanitized `not_reported`. It records `all_six_ci_steps_passed=true` **only** if every phase succeeded. An `if: always()` artifact from a failed or skipped acceptance run must display `incomplete_or_failed`, not an implied PASS. Output never includes credentials, customer hostnames, evidence bytes, unredacted exceptions or raw paths.

This is **CI step-outcome metadata**, not independent proof of production SFTP, human review, malware scanning, immutable backing storage, real-host recovery, or the full continuous real-provider v1-to-N+1 lineage. The record always retains `pilot_go=false` and `customer_data_authorized=false`. Check the referenced GitHub job logs and exact released SHA independently; the generated summary cannot close #652/#653 or authorize customer claims. The CI helper has offline negative regressions for missing/failed/skipped phase outcomes, invalid checkout SHA, malformed run identity and exclusive evidence writes.

## Required named-test execution proof (2026-10-12)

The `Pilot Real SFTP Acceptance` CI job now generates four **runner-private**
pytest JUnit XML files (direct OpenSSH runtime, governed PostgreSQL due-tick,
human-authorized N+1 and initial custody). Before each of the four phase steps
can report `success`, `scripts/pilot_real_sftp_junit_evidence.py` checks:

- every fixed, security-relevant test name for that phase was actually
  collected and executed **once** (including the real same-size in-place
  metadata-drift negative case);
- no collected test is `skipped`, `failed` or `errored`;
- declared JUnit counts agree with the actual cases; missing/malformed or
  oversized reports fail closed.

The checker prints **only** a bounded phase name and executed test count.
Raw JUnit XML and assertion details stay inside the ephemeral runner and are
not included in the public-facing `summary.json` artifact. The existing
six-phase exact-checkout-SHA metadata record from #695 reports phase
success only after the new named-test checks pass.

This prevents a fully skipped or silently de-selected pytest phase from
masquerading as successful real-provider acceptance. It is still **synthetic
CI evidence**: not production SFTP authentication/storage credentials, true
initial real-provider canonical v1→N+1 admission, independent operator
rehearsal, verified customer data permission, or Pilot GO.

## Independent real-provider operator evidence packet (#652)

Controlled GitHub CI tests against local OpenSSH + synthetic PostgreSQL are
not the independently observed, approved provider and host acceptance required
by #652. This additional **offline-only** operator tool prepares a constrained
checklist for a bounded real SFTP server exercise. It does **not** contact any
server, fetch source credentials, perform a backup, scan Evidence, execute a
provider mutation or authorize a Pilot:

```bash
python scripts/pilot_real_sftp_operator_evidence.py init \
  --sha "<independently-reviewed-deployed-release-SHA>" \
  --output /secure/pilot-releases/sftp-real-provider-acceptance-draft.json
```

A named operator and a **different independent reviewer** complete the
private draft against reviewed observations and link only bounded
`artifact://`, `ticket://`, `runbook://` or `monitor://`
references. The packet requires:

- **16 positive cases:** real provider secret-reference resolution and
  destination policy; host-key pin; authentication/subsystem; bounded directory
  listing; lstat and opened-handle checks; exact content read; quarantine and
  checkpoint; actual initial canonical v1 admission; metadata-only observation;
  separately human-approved N+1; idempotent replay and next unchanged tick;
  and no remote mutation permission
- **10 negative cases:** wrong pin/password, weak negotiation, missing file,
  traversal, symlink, metadata drift/replacement, oversize, timeout and
  mid-read disconnect
- exact release SHA, real server/version and enabled-algorithm evidence,
  approved pin, credential/permission boundary, immutable image evidence,
  approved ticket, privacy/cleanup review, UTC observation and independent
  reviewer references

Every positive case **must** have a real-provider artifact. Negative cases must
be marked `pass` with a real-server proof; a genuine server-side limitation
may instead be marked `unreproducible`, but **only** with both an explicit
limitation-ticket reference and a deterministic-CI fallback proof. The
result separately counts these exceptions so they cannot be reported as
real-server passes. Blank, skipped, errored, invented, non-UTC, mismatched
or unreferenced results are not accepted. No customer files or production
credentials, no remote writes and no invented release authorization are
permitted in this synthetic rehearsal.

```bash
python scripts/pilot_real_sftp_operator_evidence.py check \
  /secure/pilot-releases/sftp-real-provider-acceptance-draft.json \
  --sha "<independently-reviewed-exact-release-SHA>" \
  --output /secure/pilot-releases/sftp-real-provider-acceptance-readback.json
```

Output is exclusive and contains only fixed case counts, exact operator-supplied
SHA and deliberately false `actual_server_exercise_independently_verified`,
`credentials_and_data_compliance_independently_verified`,
`pilot_sftp_go_authorized` and `pilot_authorized` values. A structurally
complete record is **not evidence that the referenced artifacts are authentic**
or that a real SFTP server was actually exercised. An authorized release owner
must separately verify the immutable logs, server protocol/version/algorithms,
credentials isolation, no secret leakage, actual v1→N+1 lineage, synthetic
storage and malware verdict, replay and negative controls, then record an
explicit scoped sign-off. Keep #652 open and SFTP/customer Pilot **NO-GO** until
that independent review is complete.


## Real server-side least privilege for controlled CI (#652)

The disposable OpenSSH fixture must enforce **read-only filesystem
permissions on the SFTP principal**, independently of the production
`LiveSftpRuntime` returning `remote_write_performed=false`.
A client that simply chooses not to write does not demonstrate a
read-only server credential.

The synthetic `evidence` and nested `empty-folder` directories and
synthetic readable files are now root-owned, group-readable to the
`mcri-sftp-ci` account, and **not group-writable**. Its own login
home/`.ssh` remains correctly owned for ephemeral SSH authentication.
The unreadable fixture remains root-only. The same-size in-place
rewrite negative test intentionally uses `sudo` on the *local runner
host*; no remote SFTP write capability is granted.

The exact-head real-OpenSSH suite includes
`test_real_openssh_sftp_principal_cannot_write_rename_delete_or_mkdir`.
It establishes a separate authenticated, host-key-pinned SFTP client
session, proves a known synthetic file remains readable, then verifies
that direct SFTP **create, opening for write, mkdir, nested-file create,
delete and rename** requests are **actually rejected by OpenSSH**.
It checks the original bytes/metadata and absence of created objects.
The named-test JUnit gate requires this test to run and pass rather than
accepting skipped/omitted results.

This protects the **local disposable test fixture**, not remote customer
servers. Before #652 real-provider acceptance can pass, an independent
operator must examine the *actual* provider account's read-only ACL,
server-side effective permissions and absence of write/rename/delete
authority, record bounded receipts, and review credentials and limits.
Neither this synthetic denial nor a completed operator evidence draft
authorizes production/customer SFTP use.
