# ADR-264: SFTP operator readiness and recurring-baseline observability

## Status

Proposed for Phase 17.6-AE-B.

## Context

The existing External Evidence operator surface already composes durable source, Evidence, schedule, observation, review, refresh, admission and processing-release state.

Production SFTP adds two questions: whether the current runtime lineage is qualified, and whether an admitted N+1 has an explicit recurring-baseline transition.

## Decision

Extend the existing DB-only operator read model and /external-evidence page instead of creating a second SFTP dashboard.

## Runtime readiness

SFTP runtime readiness is derived from the latest durable credential-health qualification, transport/host-key verification and session activation.

ready requires one coherent current lineage:
- all three rows match the current profile hash;
- credential health is qualified;
- transport is verified;
- session is activated;
- the session references those exact latest credential-health and transport rows.

An explicit failed/unqualified current stage yields attention.

A missing, stale or mixed-lineage stage yields not_qualified.

The overview performs no secret resolution or provider network call.

## Recurring baseline state

For SFTP Evidence version N+1+, the read model looks for an exact established transition keyed by binding, current Document and current version.

If none exists, baseline_transition_required is true.

This is attention state only; it grants no authority.

## Governed action

When the exact AC admission execution exists and the baseline is still required, the page exposes one explicit AD action with a human reason and unique request key.

There is no automatic baseline advancement.

## Privacy

The read model/UI does not expose raw SFTP paths, usernames, credential references, secrets/private keys/passphrases or file content.

## Compatibility

Non-SFTP profile/family read-model behavior remains unchanged.
