# ADR-258: Provider-neutral human review decisions for SFTP

## Status

Proposed for Phase 17.6-AA.

## Context

Phase Z allows changed/missing SFTP due-tick observations to enter the existing pending human-review handoff queue.

The review-decision lifecycle is already provider-neutral at the service level, but decision persistence still restricts provider kind to SharePoint and Google Drive.

The existing `approve_refresh` decision also creates a separate refresh authorization. That is a distinct authority boundary and must not be opened implicitly for SFTP.

## Decision

Allow SFTP handoffs to receive the existing immutable human review decisions, with a provider-specific temporary restriction:

- changed:
  - dismiss — allowed;
  - approve_refresh — fail closed until Phase 17.6-AB.
- missing:
  - acknowledge_missing — allowed;
  - dismiss — allowed.

Legacy SharePoint/Google Drive decision behavior, including approve_refresh, remains unchanged.

## Persistence

Migration 0218 widens only the review-decision provider check to include `sftp`.

The observation refresh-authorization provider check is not changed.

Downgrade fails closed while SFTP review decisions exist.

## Authority boundary

SFTP approve_refresh is rejected after handoff integrity/matrix validation and before decision persistence or refresh-authorization creation.

AA performs no provider I/O, object-storage I/O, Document/Claim mutation, processing enqueue, checkpoint advance or AI.

## Next

Phase 17.6-AB separately opens narrow SFTP refresh authorization/execution for an approved changed observation.
