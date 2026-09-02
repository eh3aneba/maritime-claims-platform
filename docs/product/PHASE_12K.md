# Phase 12K — Bilingual English/Persian operator UI and RTL localization

Issue: #135

## Goal
Make active operator workflows equally usable in English and Persian while keeping locale strictly presentation-only.

## Foundation increment
- typed `en` / `fa` catalog with compile-time key parity;
- single locale provider for the application;
- English safe default;
- browser-local preference persistence;
- dynamic `lang` and `dir` attributes;
- mirrored authenticated shell/sidebar;
- language switcher on login and authenticated shell;
- technical identifier LTR isolation in Persian;
- localized login and Claims Workbench;
- direction-aware shared tables;
- browser E2E for switch/persistence/RTL/no-mutation.

## Core claims portfolio increment
- localized Dashboard copy, metrics, recent-claims table and empty/error states;
- localized Claims list, search/filter controls, table headings, empty/loading states and intelligence link;
- shared localized claim status and priority presentation;
- locale-aware money/date presentation with Persian UI retaining the Gregorian calendar and Latin digits for operational/legal readability;
- claim references, external references, IMO values and monetary source values retain controlled LTR presentation where appropriate;
- expanded browser E2E verifies Dashboard and Claims list in Persian against the synthetic MT ORION environment and asserts locale changes/navigation do not mutate claim APIs.

## Claim intake and workspace increment
- localized human-approved claim intake in document and manual modes;
- preserved source-document/OCR proposals as non-authoritative until explicit approval;
- retained locale-neutral create/approve/reject payload semantics and the existing audit review-note behavior;
- localized claim overview, metrics, approved Claim Facts, workflow status display, reserve control and primary workspace navigation;
- preserved locale-neutral audit reason for status advancement and explicit human reserve changes;
- kept claim reference, IMO, external reference, dates, currency and monetary presentation directionally controlled in Persian;
- expanded browser E2E verifies Persian Claim Intake and the MT ORION claim workspace while asserting locale changes/navigation do not mutate claim APIs.

## Evidence & Documents increment
- localized Evidence & Documents labels, help text, upload controls, confidentiality/document-type presentation, empty/loading/error states and operator prompts;
- localized malware-security presentation for clean, infected/blocked, scanner-error/blocked and legacy-unscanned states without changing the underlying verdict enums;
- localized version/current/superseded presentation while preserving lineage, replacement reasons, prior approvals and the existing replacement API semantics;
- localized quarantine warnings and operator controls while preserving manager/admin retry authority, administrator-only purge authority and fail-closed download/processing restrictions;
- preserved source filenames/content, SHA-256 hashes, IDs, threat signatures and replacement reasons without automatic translation;
- used controlled LTR presentation for hashes, version identifiers, sizes, timestamps and quarantine references inside Persian RTL UI;
- expanded browser E2E with a read-only evidence snapshot covering clean/current, superseded, blocked, legacy, infected quarantine and scanner-error quarantine states;
- browser E2E explicitly asserts localization/navigation cause no evidence uploads, replacements, deletes, downloads, rescans, quarantine actions or AI queue mutations.

## Chronology increment
- localized Chronology labels, metrics, guidance, empty/loading/error states and rebuild presentation;
- localized event materiality, conflict status/type presentation, measurement labels, evidence-verification labels and human conflict-review actions without changing stored enums;
- preserved event titles/descriptions, source quotes, source filenames, source values and existing human resolution notes without automatic translation;
- directionally isolated claim references, dates, times, timezone labels, source filenames, technical field labels and numeric/engineering values in Persian RTL UI;
- preserved deterministic clustering, event ordering and canonical-display timestamp rules;
- preserved chronology rebuild and conflict-resolution endpoints, methods and payloads exactly;
- dedicated browser E2E verifies EN/FA Chronology presentation and asserts locale switching/navigation causes no chronology rebuild or conflict-resolution mutation.

## Technical, financial, severity, recovery and time-bar increment
- localized Technical Review headings, maintenance labels, investigation-priority presentation, evidence-section labels, workshop-evidence labels and empty/loading/error states;
- preserved technical rule output, source quotes, engineering values and reviewed evidence content without automatic translation;
- localized Financial Review metrics, cost-schedule labels, review-status presentation, financial-flag controls, quotation presentation and reserve-history labels without changing `CostReviewStatus` values or financial mutations;
- preserved supplier names, descriptions, scope summaries, review reasons, currencies and monetary values as source/human data, with no FX conversion;
- localized Severity & Reserve Support headings, support/status/severity presentation and human-disposition controls while preserving immutable evaluations and append-only decisions;
- preserved the hard reserve-authority boundary: localization cannot create or change authoritative reserve state and no automatic reserve action exists;
- localized Recovery & Time-bar headings, status/urgency presentation, candidate-date labels and human-decision controls while preserving source wording, candidate implications, rationale and evidence lineage without automatic translation;
- preserved candidate time-bar dates as non-authoritative review aids requiring human/legal verification;
- controlled LTR presentation for claim references, dates, amounts, currencies, percentages, rule/source identifiers, hashes and technical values in Persian RTL UI;
- dedicated browser E2E verifies EN/FA presentation across all four review surfaces and fails on any locale-caused Technical/Financial/Severity/Recovery-Timebar mutation.

## Correspondence and Claim Pack increment
- localized Correspondence Centre headings, controlled enum/status presentation, workflow guidance, manager-review/dispatch controls, empty/loading/error states and operator prompts;
- preserved correspondence subject/body, sender/recipient labels, review notes and external/dispatch references as human/source content without automatic translation;
- kept the default correspondence body locale-independent so changing EN/FA never rewrites draft content;
- localized Claim Pack export controls, review-aid warnings, export-history labels and empty/loading/error states while preserving the immutable snapshot/export model;
- preserved generated Claim Pack content, filenames, hashes, approved claim data and source evidence without automatic translation or regeneration;
- preserved all correspondence and Claim Pack API/storage enum values, authorization rules and mutation payloads;
- controlled LTR presentation for claim references, external references, dates, filenames, file sizes and hashes in Persian RTL UI;
- dedicated browser E2E verifies EN/FA presentation and fails if locale switching/navigation creates correspondence or Claim Pack mutations;
- confirmed Tasks/Outreach are not active standalone operator surfaces in the current product, so Phase 12K does not invent workflows to localize.

## AI review, governance, evaluation, operations and integrations increment
- localized AI Review queue/group controls, semantic/review-status presentation, evidence guidance, human review actions, source/history controls and empty/loading/error states;
- preserved source quotes, document/source names, AI candidate values, approved human values, reviewer reasons/history and existing audit content without automatic translation;
- localized provider activation and document-eligibility controls while preserving exact provider/model identifiers, authorization/eligibility records, distinct-reviewer rules and all existing staging-only authority boundaries;
- localized measured evaluation/promotion controls, benchmark labels, threshold/review presentation and immutable case-ledger UI while preserving benchmark evidence references, human verification notes, model/prompt/schema versions, hashes and action payload enums;
- localized AI Operations metrics, filters, event/review presentation, lineage drill-down, different-human review controls and explicit incident-handoff shell while retaining the content-free governance plane and existing Production incident authority;
- localized AI Integrations/SIEM destination, delivery and retry presentation while preserving endpoint URLs, destination content, signing secrets/references, event-type payload values and outbound-only/no-inbound-command boundaries;
- centralized recurring AI enum/status terminology in a presentation-only helper instead of translating stored values;
- controlled LTR presentation for UUIDs, hashes, model/provider identifiers, prompt/schema bundle versions, endpoints, secret references, HTTP/status codes and technical measurements in Persian RTL UI;
- locale switching/navigation remains read-only: it cannot execute AI, approve/reject output, authorize/revoke a provider or document, create/finalize/review/promote an evaluation, record an operator review, hand off an incident, mutate an integration destination, rotate a secret, queue a test delivery or retry a webhook;
- dedicated browser E2E covers all five major AI surfaces, verifies EN/FA + RTL/LTR behavior, preserves editable destination content across locale changes and fails on any locale-caused AI/governance mutation;
- ADR-089 records the presentation-only AI governance localization boundary.

## Coverage matrix
| Surface | Phase 12K status |
| --- | --- |
| Root app direction/language | Implemented |
| Authenticated app shell/navigation | Implemented |
| Login | Implemented |
| Dashboard | Implemented |
| Claims list | Implemented |
| Claims Workbench | Implemented |
| Shared claim status/priority presentation | Implemented |
| Shared table direction | Implemented |
| Claim intake | Implemented |
| Claim detail/workspace | Core implemented |
| Evidence/document workflows | Implemented |
| Chronology | Implemented |
| Technical/financial/severity/recovery workflows | Implemented |
| Correspondence | Implemented |
| Claim-pack controls | Implemented |
| Tasks / Outreach | Deferred / not currently exposed as active standalone workflows |
| AI Review | Implemented |
| AI Governance / Evaluation | Implemented |
| AI Operations / AI Integrations | Implemented |
| Final localization / RTL / accessibility sweep | Pending |

## Permanent boundaries
Localization does not translate or mutate source evidence, API enum values, hashes, ClaimFacts, AI governance/authorization state, coverage/liability/causation/recoverability, reserves, settlement/payment, legal rights or external correspondence.

H&M, P&I, GA, PA, IMO and AI remain controlled abbreviations. Candidate time-bar dates remain explicitly non-authoritative in Persian and English.

## Exit criteria for full Phase 12K
Every active user-facing workflow has material English/Persian coverage, RTL is usable on desktop/mobile, technical values remain readable, existing English E2E journeys still pass and exact-head CI + Supply Chain Security are green before merge.
