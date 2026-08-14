# Controlled Claim-Pack Exports

## Purpose

Claim-pack exports turn the current reviewed claim file into a portable, immutable
snapshot for controlled internal review or authorized circulation. They do not
replace the live claim workspace and do not make a claim decision.

## Canonical snapshot

PDF and XLSX render from the same server-side snapshot. The snapshot contains:

- claim and vessel identity
- current human-approved Claim Facts through the Evidence Matrix
- supporting evidence names, versions, locators, quotes and current/superseded state
- active evidence conflicts
- outstanding document requirements
- open claim tasks
- reviewed financial items and open financial flags
- the latest approved Initial Assessment, when one exists
- generator identity, generation time, schema version and review state

Pending AI candidates and unapproved assessment drafts are excluded from
authoritative sections.

## Immutability and integrity

Each successful export stores:

- the complete JSON snapshot
- a canonical SHA-256 snapshot hash
- the generated file in protected evidence storage
- a SHA-256 file hash
- format, MIME type, size, filename, generator and timestamp

The export record and file are never updated in place. A changed live claim
requires a new export. Generation is memory-first; a partial file is never
registered. If database persistence fails, the generated file is removed.

## Authorization and audit

All operations reuse tenant-scoped Claim access. Cross-tenant and cross-claim
list or download attempts return not found. Generation and download write audit
events. Downloads use private no-store response controls and expose both hashes
as response headers.

## Rendering

The XLSX workbook preserves Unicode and separates summary, Evidence Matrix,
outstanding evidence, actions, financial review, approved assessment and export
manifest into worksheets.

The pilot PDF renderer is deterministic and text-based, using the standard PDF
Helvetica font. Excel is the canonical full-Unicode companion for Persian or
other non-CP1252 content until a production-grade embedded-font PDF renderer is
introduced.

## Permanent boundaries

- review-aid acknowledgement is required before generation
- no automated coverage, causation, liability, fraud, reserve, recoverability or settlement conclusion
- no export mutation of Claim Facts, chronology, financial review or assessment versions
- no external AI call and no external evidence transfer
- unresolved conflicts, missing evidence and superseded sources remain visible
