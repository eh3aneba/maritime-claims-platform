# ADR-257: SFTP observation review handoff

## Status

Proposed for Phase 17.6-Z.

## Context

Phase Y proves SFTP recurring schedules can reach the generic due-tick observation model and produce unchanged, changed or missing results.

The review-handoff projector is already provider-neutral at the service layer, but the handoff persistence model still restricts `provider_kind` to SharePoint and Google Drive.

The downstream human review-decision and refresh-authorization models remain separate authority boundaries and are intentionally not opened in Z.

## Decision

Allow `provider_kind=sftp` in the existing immutable observation-review handoff model.

Do not create an SFTP-specific review queue or projector.

Changed and missing SFTP due-tick observations may project one pending review handoff through the existing generic projector.

Unchanged observations remain ineligible.

## Integrity

The handoff continues to bind:
- source observation execution and completion hash;
- schedule and Evidence-family binding;
- exact observed Document/version;
- provider kind/profile hash/stable source identity;
- changed or missing result facts.

Existing handoff scope/completion hash formats remain provider-neutral and do not require SFTP-specific branches.

## Authority boundary

Projection performs no SFTP/provider I/O, no object-storage I/O, no Document/Claim mutation, no processing enqueue, no refresh authorization and no AI.

## Explicit exclusions

Phase Z does not widen:
- observation review-decision provider constraints;
- observation refresh-authorization provider constraints.

Those remain separate human authority boundaries.

## Next

Phase 17.6-AA makes the human review-decision matrix provider-neutral for SFTP while keeping refresh execution separately controlled.
