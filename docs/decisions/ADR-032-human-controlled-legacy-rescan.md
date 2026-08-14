# ADR-032: Human-controlled legacy evidence rescan and quarantine resolution

## Status

Accepted — Sprint 7C

## Context

ADR-031 protects new uploads but deliberately labels historical documents `legacy_unscanned`. Reclassifying those rows without reading their stored bytes would create false security provenance. A repository-wide synchronous scan would also block API requests and could quarantine many documents during a temporary scanner outage.

## Decision

Administrators and Claims Managers explicitly select a claim and queue at most 25 legacy documents per request. Each document receives a durable `malware_rescan` worker job, prioritized ahead of extraction and intelligence work. Only a real clean verdict changes a document to `clean`.

Malware and scanner errors are fail-closed: the source Document remains as provenance, its downloads/deletion/processing are blocked, and a source-linked QuarantinedUpload owns the retained byte location. Scanner-error records may be retried only through an operator action. A clean retry releases the file; an infected result cannot be released.

Only an organization Administrator may purge unresolved quarantine bytes. Purge requires the exact UUID and a meaningful reason. The immutable audit/provenance row remains after physical deletion.

## Consequences

- Historical evidence gains truthful, scanner-backed status in bounded batches.
- A scanner outage cannot silently admit evidence or allow continued processing.
- Claims Managers can recover transient scan failures without receiving destructive purge authority.
- The operator must check legal/evidentiary holds before purge until automated retention policy is implemented.
- PostgreSQL enum additions are append-only; migration downgrade removes new columns but does not rewrite enum types.
