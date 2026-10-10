# Controlled real OpenSSH initial custody slice

Pilot P0 blocker: [#656](https://github.com/eh3aneba/maritime-claims-platform/issues/656); prerequisite to complete the actual real-server initial SFTP v1 intake. Linked to [#652](https://github.com/eh3aneba/maritime-claims-platform/issues/652) and [#647](https://github.com/eh3aneba/maritime-claims-platform/issues/647).

This opt-in **real OpenSSH + PostgreSQL** test registers a test-only, localhost-constrained bridge at the production runtime adapter boundary. The **real runtime** does the directory listing and each exact-file read. The governed service/API keeps real Postgres receipt/audit lineage for listing, content proof, quarantine staging and initial checkpoint. It validates digest/length, explicit read-only behavior, replay with the runtime unregistered, and no premature Document/Evidence admission.

## What remains simulated

- Approved SFTP profile, credential reference, transport-verification and session-activation *governance* are existing synthetic fixtures; actual OpenSSH is touched from listing onward. These are not production secret backends.
- Quarantine is a test storage double: this is not proof of S3 durability under crash or a real matched-storage restore.
- No canonical v1 Document is admitted, and neither a real-human sign-off nor production malware scanner runs.
- It does not simulate mutation/replacement between first proof read and staging reread.

## Safety boundary

All network requests are rebound only inside the test adapter to 127.0.0.1 with an ephemeral CI key and pinned OpenSSH host key; the persistent production destination restriction remains unchanged. Only synthetic fixture bytes are read. No remote shell, write, rename, delete, mkdir or chmod operation is authorized. Credentials and raw file bodies are excluded from the GitHub acceptance artifact.

**Go/No-Go**: Even a green exact-head test is not sufficient to close #656/#652 or approve pilot customer data. The true initial v1 admission and the full consecutive real-provider v1→N+1 lifecycle remain pending.
