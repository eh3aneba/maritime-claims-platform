# External AI Provider Activation Gate

Sprint 11A adds a tenant-scoped control plane in front of the existing provider-neutral AI gateway. The OpenAI adapter remains disabled by default. A key in the environment is necessary but no longer sufficient to queue an external request.

## Runtime decision

An OpenAI extraction job is queued only when all of the following are true:

1. `APP_ENV=staging`; development, pilot and production fail closed.
2. The tenant has one unexpired `staging_authorized` activation attempt.
3. The configured model, prompt bundle, schema bundle and output-token cap exactly match the immutable authorization.
4. The document is non-restricted, its exact type is in the activation allowlist and its extracted character count is within the authorized limit.
5. A current synthetic/de-identified eligibility attestation exists for that document and activation.

The restricted-document check runs before the authorization lookup so an operator cannot turn a missing authorization into an accidental classification oracle. Existing fake providers used by deterministic tests are not treated as external OpenAI traffic.

## Approval lifecycle

Each activation is append-only and limited to `staging` plus `openai`. The requester cannot approve or finalize it. Security, Privacy and Product approvals must come from three different Manager/Admin users, all different from the requester. An Administrator then records `authorize_staging` or `hold`. The canonical SHA-256 decision includes the pinned versions, allowlist, limits, owners, bounded references, expiry, reviewer identities and explicit non-authorizations.

Rejection, hold, revocation or expiry permits a new numbered attempt. Authorization and document eligibility have explicit revoke endpoints. Revoking the activation is the application kill switch: later queue requests fail closed immediately.

## Data and secret boundary

The database stores governance metadata and bounded references such as `artifact://`, `runbook://`, `ticket://` and `monitor://`. It never stores API keys, secret values, raw provider configuration, raw evidence content or unrestricted URLs. Actual key provisioning, provider-project access, spend limits, alerts, retention/residency controls and incident procedures remain separate operational actions whose approved evidence is referenced by the activation record.

Sprint 11A does not authorize production, restricted documents or real claim data. It does not make provider configuration changes and cannot bypass the existing mandatory human review of AI candidates.

## Operator sequence

1. Create a separate staging provider project and provision its key through the approved secret system.
2. Configure project access, rate limits, spend cap and alerts outside the application.
3. Record the activation request with exact model/prompt/schema versions and bounded evidence references.
4. Obtain independent Security, Privacy and Product approvals using separate accounts.
5. Have an Administrator authorize the time-bounded staging attempt.
6. Attest each synthetic/de-identified document individually.
7. Configure the matching staging environment and run the Sprint 11B evaluation suite.
8. Revoke immediately on scope drift, incident, unexpected spend or failed evaluation.

