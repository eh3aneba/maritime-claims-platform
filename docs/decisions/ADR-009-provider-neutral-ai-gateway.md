# ADR-009: Keep AI providers behind a provider-neutral gateway

## Status
Accepted

## Decision
Application modules call `app.ai.gateway.AIProvider` rather than vendor SDKs directly. Sprint 3 Phase A shipped with the `disabled` provider only. Phase B adds an OpenAI adapter while keeping `disabled` as the deployment default and preserving the same provider-neutral interface.

## Rationale
- Avoid vendor lock-in.
- Support future private/on-prem deployments.
- Centralize model configuration, logging, safety controls and versioning.
- Prevent AI providers from becoming direct database writers.

AI remains decision support. Provider responses must flow through extraction schemas and human review before becoming approved claim data.
