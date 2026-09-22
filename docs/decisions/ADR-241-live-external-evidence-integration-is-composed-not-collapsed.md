# ADR-241 — Live external Evidence integration is composed, not collapsed

## Status
Accepted for Phase 17.5-AK implementation.

## Context
Phases 17.5-A through AJ already separate source governance, credential-reference custody, provider activation, read-only listing/read, staging, canonical admission, recurring observation, human review, refresh and N+1 admission. Production integration must wire these boundaries to SharePoint/Microsoft Graph and Google Drive without creating a shortcut around them.

## Decision
Phase 17.5-AK is integration closure, not a new authority phase.

1. Live provider adapters are read-only and disabled by default.
2. Azure Key Vault and GCP Secret Manager references are resolved transiently. Raw credential material never enters request payloads, business persistence, audit values or API responses.
3. OAuth assertions/access tokens and provider clients live only inside adapter calls.
4. Provider writes/deletes remain absent.
5. The operator overview is a derived, non-authoritative read model. It may display state but cannot infer or grant permission for a later phase.
6. AG human review, refresh execution, AH admission authorization, AJ canonical admission and Phase-Z processing release remain separate calls.
7. A changed provider item never updates canonical Evidence automatically. Missing/deleted provider state is review-only.
8. AJ creates canonical N+1 Evidence but does not inherit a Phase-Z processing release or any external-AI authority.
9. No schema migration is introduced unless a durable-state gap is demonstrated.

## Consequences
The UI can show one understandable operational timeline while the backend keeps each security decision independent. Operators may see more steps, but a compromised or mistaken action cannot silently become provider mutation, Evidence admission, processing release or AI authority.

## Production credential shape
For SharePoint, the referenced secret is JSON containing `tenant_domain`, `client_id` and `client_secret`.
For Google Drive, the referenced secret is a standard service-account JSON subset containing `client_email`, `private_key` and optionally `private_key_id`.

Workload identity to the secret manager is preferred. Optional short-lived deployment tokens may be injected through `AZURE_KEY_VAULT_ACCESS_TOKEN` or `GOOGLE_CLOUD_ACCESS_TOKEN`; these values are never persisted by MCRI.
