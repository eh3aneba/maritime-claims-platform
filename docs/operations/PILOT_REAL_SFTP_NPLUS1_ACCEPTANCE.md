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
