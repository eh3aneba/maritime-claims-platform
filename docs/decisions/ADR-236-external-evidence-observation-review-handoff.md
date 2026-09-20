# ADR-236 — Scheduled observation review handoff

## Decision

A completed recurring due-tick observation with result `changed` or `missing` is projected into one immutable DB-only pending human-review handoff.

`unchanged` produces no handoff.

The handoff is a historical snapshot of the completed observation. It does not assert that schedule, provider or canonical Document authority is still current when a human later acts. Any future action must revalidate fresh authority.

## Identity

Projection is performed by an internal non-human projector. The configured logical projector identifier is normalized and only its SHA-256 hash is persisted. `AuditLog.user_id` remains null.

## Safety

AF performs no provider-client construction, token acquisition, remote metadata/content read, storage access, Document mutation, Evidence admission, processing enqueue, AI execution, Claim mutation or checkpoint advancement.

## Exactly-once boundary

The observation row is locked before projection and the handoff table has a unique `observation_execution_id`. Concurrent projectors therefore serialize on the same immutable observation and converge on one handoff.

## Follow-up

A later human-decision phase may approve or dismiss a pending handoff. That phase must establish fresh authority before any content refresh can begin.
