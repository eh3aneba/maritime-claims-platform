# SeeClaims R0 — Pilot v1 scope and decisions

**Status: R0-01 customer type, vessel machinery scope and five essential workflow groups OWNER-APPROVED; remaining R0 choices are pending.**
Working paper derived from the product owner's
`SeeClaims_Execution_Roadmap_v1_2026-10-15_FA.docx` (pp. 2–4, 19).
The product owner explicitly confirmed on 2026-10-15 that the **first target
customer is an insurer's H&M claims-handling team** and the **initial focus is
vessel machinery damage claims**. The owner subsequently explicitly
confirmed the **five essential workflow groups** below (2026-10-15).
These scoped product decisions do **not** assert buyer demand, a selected
design partner, approved exclusions beyond what the roadmap proposes,
an accepted case fixture, pilot entry method, operator assignment or
independent review.

## R0-01: First customer and first end-to-end claim

| Decision | Proposed starting option | Acceptance state |
| --- | --- | --- |
| Primary customer type | **H&M claims-handling team within an insurance company** | **APPROVED by product owner — 2026-10-15** |
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
| Evidence entry | Secure authenticated **manual upload** | Awaiting product owner |
| SFTP | **Disabled** in Pilot v1 unless a named buyer requires it | Awaiting product owner |
| Email / Drive | Disabled unless a named authorized pilot workflow requires them | Awaiting product owner |
| External AI | **Disabled by default** until permitted data, independent review, model/cost/source validation and activation contract exist | Awaiting product owner |
| Local OCR | English + Persian for the selected evidence types; human correction and source lineage | Candidate behavior, operational gate outstanding |
| Evidence | Synthetic, consented anonymized or explicitly customer-authorized only; never put customer files in a public repo | Required |

An OFF decision does not close #652 or prove that inactive connectors
cannot activate. Technical acceptance must assert disabled settings,
permissions and runtime negative cases against the final pilot candidate.

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

- **D-R0-01a — APPROVED (2026-10-15):** Target an **insurance company's
  H&M claims-handling team**, initially focusing on **vessel machinery
  damage claims**. No specific insurer or permission to access its files is
  implied.
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
- **D-R0-02:** Accept manual-only intake and disabled SFTP/email/Drive or
  document a buyer-specific requirement.
- **D-R0-03:** Confirm external AI disabled for pilot v1 unless explicitly
  authorized separately.
- **D-R0-04:** Name operations and independent security/restore reviewers
  or mark the later host exercise **BLOCKED**.
- **D-R0-05:** Confirm which permitted synthetic/anonymized test cases can
  underpin three R5 reference fixtures: complete, missing evidence,
  and contradictory technical/financial evidence.

## Completion definition (not yet met)

R0-01a and R0-01b are **approved product-scope decisions**, not a
completed R0-01 package. The daily user, economic buyer, costly problem,
example scenario and exclusions still require explicit closure.
R0 is accepted only when the owner records the primary segment,
workflow, five essentials, explicit exclusions, document intake, external
AI mode, responsible pilot operations/reviewers, live backlog dispositions,
and exact issue/evidence links; `README`, #25 and #647 cannot contradict
the accepted state.

Every later change to accepted scope needs an owner-approved decision
record explaining acceptance effect and timeline change.
