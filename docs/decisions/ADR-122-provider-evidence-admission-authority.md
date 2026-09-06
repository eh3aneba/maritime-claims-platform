# ADR-122: Provider attachment acquisition, Evidence admission and processing are separate authorities

- **Status:** Accepted
- **Date:** 2026-09-06
- **Phase:** 15.5
- **Parent:** #214

## Context

Phase 15.4 introduced provider attachment byte acquisition for Microsoft Graph and Gmail, but deliberately stopped clean bytes at `clean_pending_human_admission` quarantine. That boundary prevents an external mailbox provider, mailbox executor or malware scanner from creating canonical claim Evidence merely because an email contains an attachment.

The existing normal Document upload service is not an appropriate shortcut for provider bytes. It accepts a new human upload, performs upload-time quarantine controls, creates a `Document` and immediately enqueues text extraction. Provider bytes already have a distinct acquisition provenance and require a separate Evidence filing decision.

The platform therefore needs an explicit authority transition from clean provider quarantine to canonical Evidence without automatically starting document processing.

## Decision

### 1. Evidence admission is a separate human decision

Only a claims manager or administrator may admit a provider attachment into canonical Evidence.

Admission requires:

- the staged email and attachment manifest belong to the caller's tenant;
- the email has already been explicitly human-linked to a claim;
- the acquired provider bytes are bound to that same claim;
- the manifest is exactly `clean_pending_human_admission`;
- Phase 15.4 recorded a successful clean malware scan and quarantine provenance;
- the provider adapter and consented mailbox connection remain active;
- the caller supplies explicit confirmation and an admission note of at least 20 characters;
- the caller chooses or confirms bounded Document metadata such as document type and confidentiality.

A suggested claim id, provider classification or previous malware result is not sufficient authority.

### 2. Quarantine integrity is re-proven before filing

Immediately before Evidence creation the application:

- row-locks the email and manifest to serialize admission;
- requires the physical quarantine object to exist;
- recomputes SHA-256 and byte size and compares them with the Phase 15.4 acquisition record;
- re-validates extension, MIME and file signature;
- requires malware scanning to be enabled;
- runs a fresh malware scan over the exact quarantined bytes.

Missing or changed bytes fail closed and require provider reacquisition. A signature mismatch is treated as an integrity failure. An unavailable scanner leaves the clean quarantine unadmitted so the human may retry later. An infected admission-time scan moves the manifest to `infected_quarantined` and creates no Document.

### 3. Canonical Evidence carries explicit source provenance

`Document` gains a nullable unique `source_email_attachment_manifest_id` foreign key.

For provider-admitted Evidence:

- the field points to the exact source email attachment manifest;
- `uploaded_by_id` identifies the human who performed the admission;
- the admission note is retained internally as `source_admission_note`;
- standard human uploads keep the source-manifest field null.

The unique source pointer means one provider attachment manifest can create at most one canonical Document. The foreign key uses `RESTRICT` semantics so the source row cannot be silently deleted while a canonical Document depends on it.

The normal Document API may expose only the bounded source manifest id. It must not expose provider attachment locators, mailbox credentials or quarantine storage keys.

### 4. Exact replay is idempotent

If a canonical Document already exists for the exact source manifest, the admission endpoint returns that Document with `replayed=true` and performs no additional scan, storage move or Document creation.

If identical bytes already exist as a different Document in the same claim, admission returns a conflict. The platform does not silently rebind the provider source to a pre-existing Evidence record because that would alter provenance without an explicit source-link authority model.

### 5. Storage promotion occurs only after all checks pass

A new Document UUID and canonical storage key are generated only after integrity and malware controls succeed. The exact provider-quarantine object is moved into canonical claim storage.

If the database transaction cannot be committed, the service attempts to restore the bytes to the original quarantine key. If restoration itself fails, canonical untracked bytes are removed and the source manifest is marked for reacquisition rather than leaving an apparently valid quarantine pointer.

### 6. Evidence admission does not grant processing authority

A successful provider Evidence admission:

- creates a canonical `Document`;
- sets malware status to `clean` from the fresh admission-time scan;
- leaves processing status at `uploaded`;
- creates **no** `DocumentProcessingJob`;
- calls **no** text extraction, OCR, AI, rule, classification or claim-decision workflow.

The existing explicit `/claims/{claim_id}/documents/{document_id}/processing/retry` action remains the separate operator decision that can enqueue extraction later.

Thus the authority sequence is:

1. **Provider read authority** — mailbox message/metadata access.
2. **Attachment acquisition authority** — external bytes enter quarantine only.
3. **Evidence admission authority** — a human files verified bytes into canonical Evidence.
4. **Processing authority** — a separate explicit action may start extraction/processing.
5. **Claim decision authority** — remains human/governed and is never implied by any earlier stage.

### 7. Retention cannot delete admitted canonical bytes

After successful admission the manifest's quarantine key is cleared because those bytes have moved to canonical Evidence storage.

Later email staging retention may redact provider staging metadata, but it must not delete the canonical Document or its storage object. The Document's source manifest id remains as bounded provenance even if staging content is redacted under retention policy.

### 8. Audit is bounded

Successful admission audit may include:

- claim id;
- canonical Document id;
- source manifest id;
- document type and confidentiality;
- human admission note;
- admission status;
- byte size;
- malware status;
- an explicit statement that processing was not enqueued.

It must not include provider attachment locator, credential reference/value, mailbox subject/body/sender/recipients, quarantine/canonical storage key, raw bytes, provider response bodies or attachment hashes.

## Consequences

### Positive

- External provider bytes cannot become Evidence without a distinct human filing decision.
- Evidence provenance points back to the exact provider attachment manifest.
- Quarantine tampering or storage loss is detected before filing.
- A stale clean scan cannot bypass a fresh admission-time malware check.
- Evidence admission and OCR/AI processing remain operationally and legally distinguishable actions.
- Email staging retention cannot erase canonical Evidence bytes after filing.

### Trade-offs

- Managers perform an additional explicit filing action after acquisition.
- Provider-admitted Documents do not begin extraction automatically; an operator must trigger processing separately when appropriate.
- Duplicate bytes from a different Evidence source require a future explicit multi-source provenance model rather than being silently deduplicated.

## Non-authority statement

This decision grants no email send authority, no automatic claim association, no automatic Correspondence promotion, no automatic document processing, no OCR/AI authority and no authority over coverage, causation, fault, liability, fraud, recoverability, governing law, legal time-bar effect, reserve, settlement, payment or claim closure.
