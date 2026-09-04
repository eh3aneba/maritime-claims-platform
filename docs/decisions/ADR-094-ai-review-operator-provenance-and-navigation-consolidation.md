# ADR-094 — AI Review is the canonical operator decision surface; provenance is explicit and rollout history leaves primary navigation

Status: Accepted for Phase 13.2B implementation

## Context

The platform already has one mature human-in-the-loop review surface at `/ai-review`: grouped/row review, field-by-field review, source preview, human feedback, approve/edit/reject actions, and explicit promotion into the canonical `ClaimFact` layer. Phase 13.2A added typed append-only `ClaimFactRevision` history and safe restoration when a superseding AI fact is later rejected.

Two operator-maturity gaps remain. First, the existing UI shows AI feedback but does not clearly distinguish that feedback from the canonical fact's provenance/version history, and an approval can replace an existing human-approved fact without first making that consequence obvious. Second, historical AI rollout/readiness stages created during earlier delivery phases are all exposed as peer navigation destinations. Those routes are useful retained rollout evidence, but they are not all primary operator tasks and their visibility creates feature sprawl.

## Decision

1. `/ai-review` remains the canonical operator surface for reviewing source-linked AI extraction candidates. No parallel review dashboard or new rollout stage is introduced.
2. The existing review-detail endpoint returns the current canonical `ClaimFact` plus up to the 100 most recent typed `ClaimFactRevision` rows for the same tenant, claim, and field path. AI feedback and canonical revisions remain separate concepts in both API and UI.
3. Before an approve/edit action would supersede a canonical fact that is not already sourced from the same AI extraction, the UI performs a read-only preflight and requires an explicit second confirmation. The warning shows the existing fact's field, value, provenance, and version.
4. Locale switching changes only presentation. It must not approve, reject, edit, supersede, or otherwise mutate evidence/reviewer content. Technical identifiers remain controlled LTR islands.
5. Canonical history is displayed as current fact + immutable revision timeline. Human feedback is displayed separately as review-action history. Audit prose is not used as a fact-history substitute.
6. Historical rollout/readiness routes remain routable and retain their backend/data/tests, but are removed from the desktop and mobile primary navigation. Core operator destinations such as AI Review, Governance, Evaluation, Operations, and Integrations remain visible.
7. Navigation consolidation is dependency-safe: hiding a historical route is not permission to delete its data model, API, migration, tests, or operational evidence without a separate dependency audit.
8. Phase 13.2B proves supersession confirmation and restoration in browser acceptance. Deliberate re-review controls for already-reviewed field items remain a follow-on maturity tranche inside the same Phase 13.2 feature; no new top-level feature is created for that work.
9. Queue ordering follows operator intent instead of one global timestamp rule: pending work is FIFO by candidate creation so older unattended work remains visible, while approved/edited/rejected history is ordered by most recent human review so newly completed decisions cannot disappear behind older rows at the API page limit. The mixed `all` view shows newest candidates first.

## Authority and safety boundaries

- No AI candidate becomes canonical without explicit human review.
- No automatic coverage, liability, causation, fraud, reserve, settlement, payment, recovery, policy interpretation, or legal decision is introduced.
- Source evidence, AI output, reviewer reasons, hashes, UUIDs, enums, audit records, and other persisted technical/legal content are not translated by locale switching.
- Existing tenant and source-document authorization remains server-enforced.

## Consequences

- Operators can see what authoritative fact exists before replacing it and can distinguish intake-reviewed provenance from AI-reviewed provenance.
- Canonical fact revisions become understandable product evidence instead of an invisible backend mechanism.
- Newly reviewed historical rows remain visible even on claims whose accumulated AI extraction history exceeds one API page.
- The primary navigation becomes materially smaller without destructive deletion of historical rollout capability.
- Group/bulk review remains subject to the same server-side human-authority boundaries; further UI edge hardening and reviewed-item re-review controls can proceed as the next tranche of the same feature after this base is validated.
