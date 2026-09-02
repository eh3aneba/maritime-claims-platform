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
| Technical/financial/severity/recovery workflows | Pending migration |
| Tasks/outreach/correspondence | Pending migration |
| Claim-pack controls | Pending migration |
| AI Review / AI governance pages | Pending migration |
| AI Operations / AI Integrations | Pending migration |

## Permanent boundaries
Localization does not translate or mutate source evidence, API enum values, hashes, ClaimFacts, AI governance/authorization state, coverage/liability/causation/recoverability, reserves, settlement/payment, legal rights or external correspondence.

H&M, P&I, GA, PA, IMO and AI remain controlled abbreviations. Candidate time-bar dates remain explicitly non-authoritative in Persian and English.

## Exit criteria for full Phase 12K
Every active user-facing workflow has material English/Persian coverage, RTL is usable on desktop/mobile, technical values remain readable, existing English E2E journeys still pass and exact-head CI + Supply Chain Security are green before merge.
