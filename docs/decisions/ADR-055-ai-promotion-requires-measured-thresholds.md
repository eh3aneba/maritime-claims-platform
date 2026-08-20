# ADR-055: AI staging promotion requires measured, reproducible thresholds

## Status

Accepted for Sprint 11B.

## Decision

An active provider authorization proves accountable scope but not model quality. Shared synthetic/de-identified staging promotion therefore requires an append-only benchmark suite pinned to the activation’s model, prompt and schema versions.

The server owns the threshold profile and deterministically calculates precision, recall, unsupported-claim rate, source-grounding validity, human override rate, P95 latency and mean observed cost. Prompt-injection, malformed-input, cross-tenant and restricted-data controls must all pass. A failure freezes the attempt and cannot be overridden into a pass.

Only two independent Quality/Risk approvals and a separate Admin decision can promote a passing suite. Promotion expires with the Sprint 11A activation and can be revoked immediately.

## Consequences

- Model/prompt/schema drift requires a fresh evaluation.
- Failed cases and human overrides remain visible rather than being averaged away.
- Benchmark content and provider responses stay outside the application ledger.
- Observed cost supports governance without claiming calculated provider billing.
- Promotion remains staging-only, synthetic/de-identified and human-reviewed.
- Real claim documents and production remain subject to Sprint 11C and later decisions.

