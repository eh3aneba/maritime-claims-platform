# Phase 17.6-Z — SFTP changed/missing review handoff

Phase Z allows a changed or missing SFTP due-tick observation to enter the existing pending human-review queue.

## Eligible observations

Only integrity-valid due-tick observations with result:
- changed; or
- missing

are projected.

Unchanged remains ineligible.

## Projection

The internal review projector creates one immutable pending handoff and one receipt.

Exact replay returns the same handoff.

Projection does not contact SFTP and does not repeat the stat already performed by Phase Y.

## Safety boundary

No:
- provider metadata/content I/O;
- object-storage I/O;
- Document/Claim mutation;
- checkpoint advance;
- processing enqueue;
- review decision;
- refresh authorization;
- AI execution.

## Human authority remains separate

Phase Z only surfaces the item for review.

Phase AA will separately authorize the human review-decision matrix for SFTP.
