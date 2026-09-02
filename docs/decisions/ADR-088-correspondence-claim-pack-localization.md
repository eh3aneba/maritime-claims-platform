# ADR-088 — Correspondence and Claim Pack localization is presentation-only

Status: Accepted for Phase 12K implementation

## Context
The Correspondence Centre contains operator-authored and externally sourced content that can affect claim communications. Claim Pack exports are immutable snapshots built from reviewed claim data and evidence metadata. Translating either stored correspondence content or generated pack content as a side effect of UI locale would change meaning, provenance or the audit record.

Tasks and Outreach are not active standalone operator workflows in the current product. Phase 12K must not create new workflow capability merely to satisfy a localization checklist.

## Decision
1. Localize controlled UI labels, guidance, buttons, status presentation, empty/loading/error states and operator prompts for Correspondence and Claim Pack.
2. Do not automatically translate, rewrite or reinterpret correspondence subject/body, review notes, sender/recipient labels, dispatch/external references, or other human/source content.
3. Keep the default correspondence body as correspondence content rather than locale-dependent UI copy. Changing locale must not rewrite it.
4. Do not translate or regenerate Claim Pack snapshot content, PDFs, spreadsheets, filenames, hashes, approved claim data or source evidence when locale changes.
5. Keep correspondence and export API/storage enums and mutation payloads locale-neutral.
6. Locale switching or navigation must never create, update, submit, approve, reject or mark correspondence as sent and must never generate/rebuild a Claim Pack.
7. Preserve LTR islands for claim references, external/message references, filenames, hashes, timestamps and code-like identifiers. Human free text uses direction-aware presentation without changing stored content.
8. Preserve existing authorization and audit rules. Localization grants no new authority to send correspondence, approve wording, generate claim decisions or alter an immutable export.
9. Record Tasks/Outreach accurately as deferred/not currently exposed rather than inventing a localized workflow.

## Consequences
- Persian operators receive an RTL, localized control shell while source/human communication remains exactly as entered.
- English behavior remains the compatibility baseline.
- Generated Claim Pack artifacts remain deterministic and auditable across UI locales.
- A future explicit translation feature would require separate governance, provenance and audit design; it is outside Phase 12K.
