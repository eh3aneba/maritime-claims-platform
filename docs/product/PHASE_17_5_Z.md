# Phase 17.5-Z — Explicit downstream-processing release

Phase Z introduces a separate human-controlled authority boundary between admitted external Evidence and
normal downstream processing.

## Authority model

An external Evidence Document admitted by Phase X and bound by Phase Y remains non-processable until an
Admin with current MFA assurance records an exact-current processing release with a human reason.

The release is bound to:

- tenant and Claim;
- external source profile;
- durable Phase-Y Evidence-family binding;
- exact Document family;
- exact current Document ID and version number;
- releasing human actor;
- immutable grant receipt and integrity hashes.

The initial release permits local text extraction/OCR-related processing. It does not authorize external AI.
Existing AI runtime/governance checks remain independently mandatory.

## Enforcement

The processing service revalidates authority twice:

1. before enqueue, so unauthorized work cannot enter the queue;
2. immediately before worker execution, so queued work cannot outlive revocation or version/currentness changes.

Missing, revoked, stale, superseded, deleted, cross-tenant, cross-Claim, family/version-mismatched or
integrity-tampered release state fails closed.

`MALWARE_RESCAN` remains the security-only exception and cannot escalate into content processing.

## Operator experience

The Evidence table distinguishes **Awaiting processing authorization** from ordinary uploaded state.
Authorized Admin users can grant or revoke processing authority with a required reason. After a valid release,
normal local processing/retry becomes available. AI actions remain governed separately.

## Non-authority

Creating or revoking a Phase-Z release performs no provider I/O, storage I/O, Document mutation, processing
enqueue, extraction, AI execution, Claim mutation, checkpoint advancement or background synchronization.
