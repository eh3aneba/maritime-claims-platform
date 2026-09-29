# ADR-263: SFTP operator UX and privacy-safe observability

## Status

Proposed for Phase 17.6-AE-B.

## Context

The existing External Evidence operator page already composes durable source-family, schedule, observation, review, refresh, admission and processing-release facts.

SFTP adds three readiness stages before normal Evidence operations and one explicit recurring-baseline transition after refreshed N+1 admission.

## Decision

Extend the existing provider-neutral operator read model instead of creating an SFTP-only console.

### SFTP profile readiness

Expose only:
- credential-reference qualification status/time;
- pinned-host-key transport verification status/latency/time;
- SFTP session activation status/latency/time.

Do not expose:
- hostname;
- port;
- username;
- remote path;
- credential reference name;
- secret material.

### Refreshed Evidence baseline

For SFTP N+1, expose:
- baseline transition id/status/time;
- whether an explicit transition is required.

The operator UI may call the already-governed AD transition API only after a human enters an audit reason. The transition remains separate from admission and processing release.

## Operational events

Use the project's existing structured-logging approach.

The dedicated `mcri.sftp` event schema is deliberately low-cardinality:

- `event=sftp_operation`;
- `operation`;
- `result`;
- `latency_class`.

No customer locator, tenant content, path, username, secret reference or evidence bytes are event labels.

## Authority

The read model is non-authoritative.

Showing a status never grants the next authority.

All human-controlled actions continue to call their own MFA-gated APIs.

## Compatibility

SharePoint/Google Drive operator fields and workflow remain unchanged.

## Follow-up

AE-C closes restart/replay/recovery and full production-shaped end-to-end acceptance.
