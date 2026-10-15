# SeeClaims R0 — Pilot v1 scope and decisions

**Status: International H&M insurer and five workflows APPROVED; R0-02a manual-only Evidence intake APPROVED; R0-02b self-hosted local AI FIRST and external APIs DEFERRED APPROVED. Actual inference capability, operating jurisdiction, buyer and R0 exit still PENDING.**
Working paper derived from the product owner's
`SeeClaims_Execution_Roadmap_v1_2026-10-15_FA.docx` (pp. 2–4, 19).
The product owner explicitly confirmed on 2026-10-15 that the **first target
customer is an international (non-Iranian) insurance company's H&M
claims-handling team** and the **initial focus is vessel machinery damage
claims**. The target operating jurisdiction, buyer company and contractual
counterparty have not yet been selected. The owner subsequently explicitly
confirmed the **five essential workflow groups** below (2026-10-15).
These scoped product decisions do **not** assert buyer demand, a selected
design partner, approved exclusions beyond what the roadmap proposes,
an accepted case fixture, operator assignment or independent review.
On 2026-10-15, the owner also confirmed the separate **Pilot v1 intake**
decision: secure manual uploads only, with SFTP, email and Drive connectors
**not enabled for the pilot**. The owner subsequently approved starting with
**self-hosted AI inside the controlled deployment boundary**, deferring any
OpenAI/other external inference API to a separately governed future stage.
These decisions do not assert that local model inference is implemented,
that a final candidate has been configured, or that disabled integration
and network-egress boundaries have been independently verified.

## R0-01: First customer and first end-to-end claim

| Decision | Proposed starting option | Acceptance state |
| --- | --- | --- |
| Primary customer type | **H&M claims-handling team within an international (non-Iranian) insurance company** | **APPROVED by product owner — 2026-10-15; international focus clarified subsequently** |
| Target market / jurisdiction | International insurer outside Iran; **specific country, legal entity, hosting jurisdiction and buyer unknown** | **International target APPROVED; country/entity selection PENDING** |
| Initial case domain | **Vessel machinery damage claims (H&M)** | **APPROVED by product owner — 2026-10-15** |
| Daily user | Claims handler + Claims Manager human reviewer | Awaiting product owner |
| Economic buyer | Claims Director / Head of Marine Claims (to validate by interview) | Unknown |
| Costly first problem | Repeated manual collection/review of vessel machinery damage documents, evidence chronology, technical conflicts and financial summary | Hypothesis, not customer-proven |
| One illustrative case | Turbocharger / main-engine machinery Particular Average (synthetic or explicitly authorized claim) | Awaiting product owner |
| Human decision authority | Coverage, causation, liability, reserve, settlement and payment decisions remain with responsible humans | Non-negotiable safety boundary |

Five **essential workflow groups APPROVED by the product owner (2026-10-15)**
for Pilot v1's selected H&M machinery handler journey:

1. Secure document/claim intake with quarantine and traceable document version.
2. Identify missing and contradictory evidence and construct source-linked chronology.
3. Handler-led technical and financial review with deductible/limit/FX context.
4. Immutable, versioned, source-located Initial Assessment with unknown/unsupported states.
5. Human-controlled correspondence and traceable export or case packet.

**Not in the first 30-day pilot:** Cargo, Crew, Demurrage/Laytime,
comprehensive GA collaboration, reserve prediction, public API, ERP,
e-signature, mobile/surveyor portal, broad white-label rollout and an
unmeasured production SLA. These enter only with a documented buyer blocker.

## R0-02: Intake/AI/connector activation

| Decision | Safest proposed default | State |
| --- | --- | --- |
| Evidence entry | Secure authenticated **manual upload** only for Pilot v1 | **APPROVED by product owner — 2026-10-15; not yet runtime-verified** |
| SFTP | **Not enabled** in Pilot v1; a future buyer-requested exception requires scope change and separate acceptance | **APPROVED by product owner — 2026-10-15; disabled-config verification pending** |
| Email / Drive | **Not enabled** in Pilot v1; any exception requires explicit authorization, owner approval and acceptance tests | **APPROVED by product owner — 2026-10-15; disabled-config verification pending** |
| Local generative AI (LLM inference) | **Use a self-hosted model inside the controlled deployment boundary FIRST**; model/version/hardware/license to be benchmarked against synthetic H&M machinery fixtures; no customer activation until technical and independent acceptance | **PRODUCT APPROVED (2026-10-15); implementation, selection and acceptance PENDING — #752** |
| External AI APIs (OpenAI or alternative) | **Do not use in initial Pilot v1; optional future integration only after separate owner approval, supported jurisdiction, contract/data-processing permissions, cost controls and independent review** | **DEFERRED by product owner — 2026-10-15; not activated** |
| Local OCR | English + Persian for the selected evidence types; human correction and source lineage | Candidate behavior, operational gate outstanding |
| Evidence | Synthetic, consented anonymized or explicitly customer-authorized only; never put customer files in a public repo | Required |

**D-R0-02a is an approved product decision, not a deployed configuration.**
For the first Pilot v1 candidate, users will upload permitted Evidence
through the existing authenticated manual interface; external SFTP,
email ingestion and Drive integrations will not be activated. No connector
features are removed, and no customer integrations or credentials are
authorized by this decision.

An OFF decision does not close #652 or prove that inactive connectors
cannot activate. Technical acceptance must assert disabled settings,
permissions and runtime negative cases against the final pilot candidate.
If SFTP is not enabled, #652's controlled real-server exercise is not
a prerequisite for this *manual-only* pilot, but the issue itself remains
open; enabling it later reintroduces that acceptance gate. **Local
Tesseract OCR and deterministic extraction are not a locally hosted
LLM.** The initial model-serving implementation, benchmark and fail-closed
network boundary require separately demonstrated acceptance under #752.
External AI is excluded from this pilot's initial processing and cannot
be silently enabled by setting credentials. Local OCR acceptance also
remains a separate runtime gate.

## Roles that must be named before operational acceptance

- Product owner and pilot scope signoff: **owner of SeeClaims** (approval pending).
- Technical implementer: responsible for commits, CI and issue evidence.
- **Operations owner: NOT NAMED** — host, backups/restore, alerts,
  on-call/escalation, secrets and runbooks.
- **Independent reviewer: NOT NAMED** — security / restore / candidate review.
- **Customer representative: NOT NAMED** — approved cases, baseline,
  usability study and customer acceptance.

Owner validation is required; technical commit authors cannot certify
independent operational proof.

## Decisions to obtain in R0

- **D-R0-01a — APPROVED and subsequently CLARIFIED:** Target an
  **international (non-Iranian) insurance company's H&M claims-handling
  team**, initially focusing on **vessel machinery damage claims**.
  The product owner expressly chose an international rather than Iran-first
  target. No named country, insurer, operating jurisdiction, buyer,
  hosting location, external-provider availability, data-export consent
  or authority to access customer documents is implied.
- **D-R0-01b — APPROVED (2026-10-15):** The five workflow groups listed
  above are the exact required product scope: secure claim/document
  intake and versions; missing/conflicting evidence and source-linked
  chronology; handler-led technical/financial review including
  deductible/limits/FX; versioned source-linked Initial Assessment with
  unknown states; human-controlled correspondence and file export.
  These are scope commitments, **not** an operational acceptance of the
  individual software capabilities.
- **D-R0-01c — PENDING:** Validate the actual daily-user roles, economic
  buyer, expensive workflow problem, representative Particular Average/
  turbocharger case and explicitly proposed exclusions with the owner
  and any prospective buyer. Do not infer their acceptance from the
  approved five workflow groups.
- **D-R0-02a — APPROVED (2026-10-15):** Pilot v1 Evidence intake uses
  authenticated manual upload; SFTP, email ingestion and Drive connectors
  remain **OFF** for the candidate. Implementation must prove
  configuration, denied activation and absence of unauthorized external
  access before real-data pilot approval. This approval is **not** proof
  the deployment is already configured or that #652 is closed.
- **D-R0-02b — APPROVED (2026-10-15):** Start with **local/self-hosted
  model inference** for SeeClaims H&M machinery AI assistance. The model
  and serving stack must remain inside an approved deployment environment
  without sending document bytes, prompts or extracted text to an
  external AI provider; enforce outbound-network controls, model version
  and license review, synthetic evaluation, bounded processing, immutable
  source-linked proposals and human authority. Track real implementation
  and acceptance in #752. `ai_provider=disabled` remains the safe
  deployed default until a reviewed local inference path is built and
  separately authorized; **OCR/rules do not equal a local LLM**.
  OpenAI/API-provider integration is **DEFERRED to a later separately
  approved stage**, which must establish supported legal jurisdiction,
  customer data permissions, contractual processing/retention, security,
  benchmark, cost and operator acceptance; this decision grants no
  external document transfer or API activation.
- **D-R0-03 — APPROVED in scope:** External AI remains disabled for
  the initial pilot; enabling any external provider later requires a
  new explicit product-owner decision and separate acceptance.
- **D-R0-04:** Name operations and independent security/restore reviewers
  or mark the later host exercise **BLOCKED**.
- **D-R0-05:** Confirm which permitted synthetic/anonymized test cases can
  underpin three R5 reference fixtures: complete, missing evidence,
  and contradictory technical/financial evidence.

## Completion definition (not yet met)

R0-01a, R0-01b, R0-02a and R0-02b are **approved product decisions**,
not completed R0-01/R0-02 operational acceptance or the overall R0 gate.
The real local model, exact deployment environment, cost and evaluator
remain a future implementation/verification task (#752). The daily user, economic buyer, costly problem,
example scenario, target operating jurisdiction and exclusions still
require explicit closure.
R0 is accepted only when the owner records the primary segment,
workflow, five essentials, explicit exclusions, document intake, external
AI mode, responsible pilot operations/reviewers, live backlog dispositions,
and exact issue/evidence links; `README`, #25 and #647 cannot contradict
the accepted state.

Every later change to accepted scope needs an owner-approved decision
record explaining acceptance effect and timeline change.
