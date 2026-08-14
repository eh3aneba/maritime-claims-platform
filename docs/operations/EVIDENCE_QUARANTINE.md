# Evidence Quarantine Operations

## Purpose

This runbook governs legacy malware rescans, scanner-error retries, infected-file investigation and secure purge for the private pilot. It does not authorize release of malware or override legal/evidentiary retention duties.

## Roles

| Action | Claims Handler | Claims Manager | Administrator |
| --- | --- | --- | --- |
| View quarantine metadata | Yes | Yes | Yes |
| Queue bounded legacy rescan | No | Yes | Yes |
| Retry `scan_error` | No | Yes | Yes |
| Release after authoritative clean retry | No | Trigger retry | Trigger retry |
| Purge retained bytes | No | No | Yes |

## Standard procedure

1. Confirm ClamAV is healthy and `MALWARE_SCAN_ENABLED=true`.
2. Open one claim and queue no more than 25 legacy records.
3. Let the worker finish; do not restart or bypass failed security jobs.
4. Review each result:
   - `clean`: normal evidence access may continue.
   - `scan_error`: investigate scanner/storage health, then retry explicitly.
   - `infected`: isolate the host if unexpected, record the threat name and notify the pilot security owner.
5. Never download or release an infected record. The product exposes no infected-release endpoint.
6. Before purge, confirm the file is synthetic/test data or that legal, contractual and evidentiary retention approval exists. Record the approval basis in the required reason.
7. An Administrator enters the exact quarantine UUID and a reason of at least 20 characters. Physical bytes are deleted; database provenance and the audit event remain.

## Retry rules

- Only `scan_error` may be retried.
- A retry returning `clean` releases or recreates the active Document and queues text extraction when needed.
- A retry returning malware changes the quarantine to `infected` and remains blocked.
- A repeated scanner error increments the retry counter and remains unresolved.

## Incident evidence

Preserve the claim ID, quarantine UUID, SHA-256, threat name, scanner time, operator, retry count and related audit events. Do not copy suspected malware into tickets, email, chat or external AI systems.

## Pilot limitation

Automated legal hold, tenant-specific retention periods and scheduled purge are not implemented. Until that milestone, purge approval is a documented human control.
