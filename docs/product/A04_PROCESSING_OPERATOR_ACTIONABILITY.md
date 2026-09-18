# A04 — Operator-actionable document processing

## Purpose

A03 makes stale document-processing leases recoverable and fenced. A04 makes that backend truth visible and actionable in the claim Evidence & Documents workspace.

## Operator contract

The processing summary now exposes three operator-safe fields:

- `operator_status`: `uploaded`, `queued`, `running`, `completed`, or `failed`;
- `can_retry`: whether the backend currently permits an explicit operator retry/recovery action;
- `retry_recommended`: whether recovery is recommended because processing failed or the running lease is stale.

The UI does not decide retry eligibility from local timers or from `Document.processing_status`. Backend state remains authoritative.

Stale-lease classification also reuses the same backend predicate as A03 recovery, so operator presentation and recovery cannot silently drift to different timeout semantics.

## Stale running jobs

A running extraction whose durable lease is older than `PROCESSING_STALE_AFTER_SECONDS` remains labelled Running but becomes recoverable. Selecting Recover uses the existing A03 retry endpoint. That endpoint atomically recovers the stale lease to Pending (or fails it if the attempt budget is exhausted), after which the UI refreshes from the backend and shows Queued or Failed.

## Failure presentation

Failed processing shows a concise operator state and attempt count. Raw worker ownership, lock timestamps and raw internal error text are never rendered in the claim UI.

## Interaction safety

- retry/recovery buttons appear only when `can_retry=true`;
- the button disables immediately while a request is in flight;
- active queued/running states are refreshed every few seconds;
- successful retry refreshes authoritative backend state rather than assuming success from HTTP acceptance alone.

## Localization and accessibility

Processing labels and actions are available in English and Persian. Action buttons use normal button semantics and disabled state while executing.

## Validation

- backend regression coverage for stale-running recoverability, queued state after recovery and terminal failure retryability;
- browser E2E coverage for failed and stale-running presentation, safe error non-rendering, retry/recover behavior and duplicate-click protection;
- normal frontend typecheck/build, design-partner E2E and repository quality gates.

## Merge boundary

A04 is stacked on A03 while A03 remains unmerged. After A03 is merged, refresh this branch against `main` so final review contains only A04-specific changes. No merge occurs without fresh explicit user authorization.
