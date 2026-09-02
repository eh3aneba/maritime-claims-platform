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
- retained the existing Evidence & Documents component without changing its malware, quarantine, versioning or evidence-security behavior; that module is the next localization tranche;
- expanded browser E2E verifies Persian Claim Intake and the MT ORION claim workspace while asserting locale changes/navigation do not mutate claim APIs.

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
| Claim detail/workspace | Core implemented; embedded evidence module pending |
| Evidence/document workflows | Pending migration |
| Chronology | Pending migration |
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
