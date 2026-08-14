# ADR-033: Human-approved FNOL intake with bounded local OCR

## Status

Accepted

## Context

Opening a maritime claim from a notification is repetitive, but the source may be scanned, bilingual, incomplete or malicious. Direct automatic claim creation would turn uncertain extraction into operational truth and could cross tenant, evidence and audit boundaries.

## Decision

Use a separate tenant-scoped `ClaimIntakeDraft` and durable processing job. Every source is quarantined and must receive a clean ClamAV verdict before local extraction. Scanned PDFs and images use bounded Tesseract `eng+fas` OCR in the worker image. Deterministic classification and field parsing create editable candidates with evidence metadata.

A human reviewer must select an existing tenant vessel, verify/edit required values and record a note. Only the approval command creates one Claim and promotes one clean source Document. Approval is idempotent. Candidate values are not written to `claim_facts`, and external AI is not involved.

## Consequences

- Intake failures, rejection and malware events remain auditable without polluting active claims.
- Review adds an intentional human step but prevents silent claim-truth mutation.
- Worker images are larger because OCR binaries/language data are isolated there.
- OCR quality depends on scan quality and is not a handwriting or semantic-understanding guarantee.
- Email-provider ingestion, document-version replacement and advanced classification remain separate decisions.
