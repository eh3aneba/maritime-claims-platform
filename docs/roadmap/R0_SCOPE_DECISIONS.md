# SeeClaims R0 — Pilot v1 scope and decisions

**Status: PROPOSED / NOT OWNER-APPROVED.**
Working paper derived from the product owner's
`SeeClaims_Execution_Roadmap_v1_2026-10-15_FA.docx` (pp. 2–4, 19).
This page does **not** assert that a buyer, design partner, operator or
reviewer has accepted these choices.

## R0-01: First customer and first end-to-end claim

| Decision | Proposed starting option | Acceptance state |
| --- | --- | --- |
| Primary customer type | **H&M machinery insurer's claims-handling team** | Awaiting product owner |
| Daily user | Claims handler + Claims Manager human reviewer | Awaiting product owner |
| Economic buyer | Claims Director / Head of Marine Claims (to validate by interview) | Unknown |
| Costly first problem | Repeated manual collection/review of vessel machinery damage documents, evidence chronology, technical conflicts and financial summary | Hypothesis, not customer-proven |
| One illustrative case | Turbocharger / main-engine machinery Particular Average (synthetic or explicitly authorized claim) | Awaiting product owner |
| Human decision authority | Coverage, causation, liability, reserve, settlement and payment decisions remain with responsible humans | Non-negotiable safety boundary |

Five **essential workflow groups** proposed for the pilot candidate:

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

- **D-R0-01:** Accept the H&M insurer handler / manager / buyer hypothesis
  and the machinery Particular Average sample, or provide exact alternative.
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

R0 is accepted only when the owner records the primary segment,
workflow, five essentials, explicit exclusions, document intake, external
AI mode, responsible pilot operations/reviewers, live backlog dispositions,
and exact issue/evidence links; `README`, #25 and #647 cannot contradict
the accepted state.

Every later change to accepted scope needs an owner-approved decision
record explaining acceptance effect and timeline change.
