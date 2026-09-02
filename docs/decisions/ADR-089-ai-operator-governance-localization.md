# ADR-089 — AI operator and governance localization is presentation-only

Status: Accepted for Phase 12K implementation

## Context
AI Review, provider activation, evaluation/promotion, AI Operations and AI Integrations expose governed operator controls around model output, source evidence, authorization, immutable evaluation records, Production Decision Logs and content-free outbound webhooks. These surfaces contain technical identifiers and human/source/model content whose meaning, provenance and audit lineage must not change merely because the UI locale changes.

Localization must also preserve the existing separation between presentation and authority: changing EN/FA cannot execute AI, approve or reject model output, authorize a provider, attest a document, finalize or promote an evaluation, record a different-human review, hand off an incident, create/update an integration destination, rotate a secret, queue a test delivery or retry a webhook.

## Decision
1. Localize controlled UI labels, guidance, buttons, status/enum presentation, metrics, filters and empty/loading/error states across AI Review, AI Governance, AI Evaluation, AI Operations and AI Integrations.
2. Keep all API/storage enum values, provider/model identifiers, authorization IDs, UUIDs, hashes, bundle versions, event types, endpoint URLs, secret references and mutation payload values locale-neutral.
3. Do not automatically translate, rewrite or reinterpret source quotes, source evidence, document/source names, AI/model output, reviewer-entered reasons or notes, benchmark evidence references, integration destination names/endpoints, external payload content or other source/human content.
4. Persisted default audit/review text remains locale-independent. Locale switching must not rewrite an editable form value that may later be submitted.
5. Preserve the existing no-authority boundaries: localization does not create ClaimFacts, coverage/liability/causation/recoverability decisions, reserve/settlement/payment authority, provider authorization, evaluation promotion, incident declarations or integration remediation.
6. Locale switching and navigation are read-only presentation actions. They must not cause POST, PATCH, PUT or DELETE requests to the scoped AI/governance endpoints.
7. Preserve LTR islands for UUIDs, hashes, model/provider identifiers, prompt/schema bundle versions, endpoints, secrets/references, HTTP/status codes and technical measurements. Source/human free text uses direction-aware presentation without changing content.
8. Keep the content-free boundaries of AI Operations and AI Integrations intact. Localization does not expose prompts, questions, evidence passages, provider responses, synthesized answers or raw claim/model content.
9. English remains the compatibility baseline; Persian receives an RTL operator shell with controlled terminology while the underlying governed records remain identical.

## Consequences
- Operators can review and govern AI workflows in English or Persian without creating a second semantic or authorization layer.
- Stored AI, evidence, review, evaluation and integration records remain deterministic and auditable across locales.
- Technical identifiers remain readable in RTL layouts.
- A future feature that translates model/source/reviewer content would require separate provenance, consent, audit and authority design and is outside Phase 12K.
