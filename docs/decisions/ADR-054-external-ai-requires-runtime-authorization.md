# ADR-054: External AI requires an independent runtime authorization

## Status

Accepted for Sprint 11A.

## Decision

An environment key and `AI_PROVIDER=openai` do not by themselves authorize external processing. Every OpenAI queue path must enforce a tenant-scoped, unexpired staging authorization and a document-level synthetic/de-identified eligibility attestation. The activation pins the provider, model, prompt/schema bundles, document types and input/output limits.

The activation requires three independent Security, Privacy and Product approvals from different Manager/Admin users, none of whom is the requester. A non-requesting Administrator records the final time-bounded decision. The canonical decision hash and audit ledger preserve the exact scope. Revocation blocks new queueing immediately.

## Consequences

- Staging configuration drift fails closed.
- A credential leak or misconfiguration cannot alone open the application queue.
- Production, restricted documents and real claim data remain explicitly unauthorized.
- Key material and raw evidence stay out of governance records.
- Provider-project provisioning, hard spend controls and contractual/privacy controls remain separate operational actions with bounded evidence references.
- AI output remains candidate-only and subject to mandatory human review.

