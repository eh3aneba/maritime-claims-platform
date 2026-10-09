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
