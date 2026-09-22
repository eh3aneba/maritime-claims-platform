# Phase 17.5-AK Operator Runbook

## Enablement
1. Keep `EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED=false` until secret-manager workload identity and provider permissions are ready.
2. Provision a read-only Microsoft Graph application for the governed SharePoint site/library, or a read-only Google Drive service account for the governed shared drive/folder.
3. Store only the provider credential JSON in Azure Key Vault or GCP Secret Manager.
4. In MCRI, bind only the secret reference locator; never paste the secret or token into an API request.
5. Enable the deployment flag and run the normal production preflight and exact-head CI gates.

## Daily operation
Open **External Evidence**.

For each profile inspect provider health, last observation and next due time. For each family inspect current + historical canonical versions, observation result, pending human handoff, AG/AH/AI/AJ state and the Phase-Z requirement.

### Unchanged
No human action is needed. The canonical document remains unchanged.

### Changed
A changed observation creates a review handoff. Enter an explicit human reason/audit note (minimum 20 characters), then make the AG review decision. Only an explicit **AG · Approve refresh** decision creates the single-use refresh authority. **AH · Read & stage exact refresh**, **AI · Authorize exact admission**, and **AJ · Admit canonical N+1** are separate later actions and must be executed separately. Phase-AI here is the A→AJ phase label and does not authorize or execute external artificial intelligence.

### Missing
Treat as review-only. Enter the human reason/audit note, then use **AG · Acknowledge missing** or **AG · Dismiss** according to the governed review workflow. Do not delete or supersede canonical Evidence because the provider item is missing.

### After AJ
Confirm the family shows N+1 as current and the prior version remains historical. The new document must display **Phase-Z required** until an independent processing release is granted for that exact document/version.

## Failure handling
401/403 provider failures indicate authorization or permission problems. 404 during exact read is bounded as not-found and returns to the governed review path. 429/5xx are bounded provider-unavailable conditions and should be retried through the existing idempotent execution path, not by creating a parallel authority. Timeouts and malformed/oversized provider responses fail closed.

Never paste raw provider responses, access tokens, client secrets, private keys or pre-authenticated download URLs into issue comments, audit notes or support tickets.

## Rollback
Disable `EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED`. This removes live runtime adapter registration without deleting source profiles, Evidence, historical receipts or schedules. It does not revoke already-existing canonical documents or processing releases; use their dedicated governed revocation/disable APIs where applicable.
