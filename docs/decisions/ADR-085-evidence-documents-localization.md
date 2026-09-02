# ADR-085 — Evidence & Documents localization boundary

**Status:** Proposed in Phase 12K

## Decision
Localize the Evidence & Documents operator surface as presentation only. English/Persian labels, warnings, prompts, status presentation and RTL/LTR layout may change with locale; evidence bytes, source content, evidence-security verdicts, storage/version semantics, API enums and workflow authority may not.

## Security invariants
- Malware states remain the existing `clean`, `infected_quarantined`, `scan_error` and `legacy_unscanned` values.
- The existing evidence-availability rule remains unchanged: only `clean` and `legacy_unscanned` documents are available through the current active-document controls.
- Quarantined bytes remain excluded from download and document processing.
- Retry remains an explicit manager/admin action and purge remains an explicit administrator action with the existing reason and confirmation requirements.
- Locale switching never triggers upload, replacement, delete, download, malware rescan, quarantine retry/purge or document-intelligence queueing.
- Fail-closed scan and quarantine behavior is not weakened by localization.

## Evidence/version invariants
- Original filenames, hashes, IDs, threat names, replacement reasons and uploaded source content are never translated automatically.
- Version numbers and superseded/current relationships are presentation-localized without changing lineage.
- Replacement keeps the existing explicit reason requirement and does not transfer Claim Facts, reviews or assessment approvals automatically.
- Download continues to use the original filename and existing evidence endpoint.

## Directionality
Technical values such as SHA-256 hashes, version identifiers, sizes, timestamps, IDs and threat signatures use controlled LTR presentation inside Persian RTL UI. Source/user-authored text remains unmodified.

## Browser acceptance
Phase 12K localization E2E uses a read-only controlled Evidence & Documents snapshot covering clean/current, superseded, blocked scan-error, legacy-unscanned, infected quarantine and scanner-error quarantine states. The test asserts EN/FA rendering and verifies locale changes/navigation cause no evidence mutations.
