# Bounded Real-Document Private AI Pilot

Sprint 11C is the first authorization boundary that can admit real claim documents to the external AI provider. It remains a staging-only, small-cohort pilot and accepts only non-restricted Chief Engineer Reports and Engine Logs. Sprint 11A authorization and Sprint 11B promotion remain necessary but are not sufficient by themselves.

## Authorization lifecycle

1. A Manager creates an append-only pilot attempt anchored to one active Sprint 11B promotion and its Sprint 11A activation.
2. The attempt freezes a document allowlist, claim/document/user/run caps, a period of no more than 30 days, and bounded authorization, monitoring, incident and rollback references.
3. An organization owner and a data owner—different users and both different from the requester—independently approve the exact cohort.
4. A non-requesting Administrator records `authorize_pilot` or `hold`. The SHA-256 decision snapshot cannot expand the promoted model/prompt/schema bundle or outlive its anchors.
5. A Manager separately attests each current document, including its authorization basis and data-minimization evidence. Restricted documents fail closed.
6. Queue-time enforcement rechecks environment, activation, promotion, pilot window, pinned bundle, confidentiality, allowlist, input limit, document eligibility and remaining user/run quotas.
7. Every external run creates a content-free reservation. A different human must record Approve/Edit/Reject before the run is counted as reviewed.
8. Any incident pauses new runs immediately. Admin resolution may resume only after all open incidents are resolved; revocation is an immediate kill switch.
9. Completion requires at least one run, a human-review outcome for every run and no open incident. Completion does not authorize broad production AI.

## Data boundary

The pilot control tables store IDs, file hashes, classifications, authorization/evidence references, caps, timestamps, counts, human-review actions and SHA-256 decision/outcome hashes. They do not copy document text, prompts, candidate answers, source quotes, provider responses or credentials.

The existing document-processing and AI-extraction stores still hold the minimum product evidence needed for human review. AI candidates remain non-authoritative: they cannot directly change liability, coverage, reserve, settlement, payment or approved claim facts.

## Fail-closed conditions

- application environment is not staging
- Sprint 11A activation or Sprint 11B promotion is absent, expired, revoked or version-drifted
- pilot is pending, held, paused, completed, revoked, expired or outside its start window
- document is Restricted, superseded, deleted, outside the allowlist or lacks active document authorization
- input exceeds the pinned cap or user/provider-run quota is exhausted
- the configured model, prompt, schema or output cap differs from the promoted bundle

## Exit boundary

The cohort can be completed after fully reviewed outcomes and resolved incidents. A later production-AI decision requires a new explicit authorization, evidence and rollout plan. Restricted documents remain a separate future decision.

