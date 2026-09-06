# ADR-121: Provider attachment acquisition is quarantine authority, not Evidence authority

- **Status:** Accepted
- **Date:** 2026-09-06
- **Phase:** 15.4
- **Parent:** #214

## Context

Phase 15.1 bound inbound email staging to an explicit provider source and made provider replay integrity fail closed. Phase 15.2 introduced bounded read-only Microsoft Graph and Gmail execution without storing provider credentials or opaque provider checkpoints in the application database. Phase 15.3 then protected provider execution state and exposed content-free operational reconciliation.

Those phases deliberately staged attachment metadata only. The application already has mature Document malware/quarantine controls, but its normal human upload path promotes malware-clean bytes into a canonical `Document` and processing workflow. That is appropriate for an explicitly filed claim document; it is too much authority for bytes obtained from an external mailbox provider.

The provider must not be able to create Evidence merely because an email contains an attachment.

## Decision

### 1. Human claim linkage is required before byte acquisition

Provider attachment bytes may be acquired only when:

- the staged email is tenant-scoped;
- it is bound to an explicit Graph or Gmail adapter;
- the email has already been explicitly reviewed and linked by a human to a claim;
- the adapter and consented connection are active;
- a claims manager or administrator explicitly invokes acquisition for one attachment manifest.

A suggested claim id is never sufficient. Pending, rejected, expired, legacy connection-only and cross-tenant messages have no provider attachment byte authority.

### 2. Provider object identity is proven at acquisition time

The staged manifest intentionally does not need to trust or expose a provider locator during ordinary inbox review.

When acquisition is requested, the application re-reads attachment metadata under the exact staged provider message and requires exactly one provider object matching the staged:

- filename;
- MIME type;
- byte-size metadata.

Zero or multiple matches fail closed. The application does not guess by attachment order or partially matching names.

After byte acquisition succeeds, the resolved provider attachment locator may be retained internally for provenance/idempotency. It is not returned by ordinary inbox or acquisition responses and is excluded from audit metadata.

### 3. Fetch authority is exact and bounded

Graph acquisition fetches only the resolved attachment id beneath the exact staged Graph message id.

Gmail acquisition fetches only the resolved Gmail `attachmentId` beneath the exact staged Gmail message id.

Provider URLs must be HTTPS and match the existing Graph/Gmail hostname allowlist. Credentials are resolved through the existing out-of-database credential-reference boundary. Provider-declared size is not trusted: the response read and Gmail base64-decoded bytes are independently bounded by the configured upload limit.

### 4. External bytes enter quarantine only

Provider attachment acquisition requires malware scanning to be enabled. Before scanning, the application applies the existing allowed extension/MIME and file-signature rules.

Bytes are stored under a dedicated provider-quarantine key and then scanned with the existing malware scanner.

The resulting states are:

- `clean_pending_human_admission`: scan clean, bytes still quarantined;
- `infected_quarantined`: malware detected, bytes quarantined;
- `scan_error_quarantined`: authoritative scan unavailable, bytes quarantined.

A clean scanner result is **not** Evidence admission.

This tranche creates no `Document`, no document-processing job, no OCR/AI task, no rule evaluation and no evidence-search entry.

### 5. Acquisition and Evidence admission are separate authorities

Future admission of `clean_pending_human_admission` bytes into canonical `Document` / Evidence must be a separate human action with its own source provenance and decision record.

The email provider, provider executor, malware scanner and acquisition endpoint cannot perform that admission automatically.

### 6. Idempotency does not re-fetch terminal quarantine state

Once a manifest has a terminal quarantine state and its quarantine bytes remain present, repeated acquisition returns the existing bounded acquisition state rather than re-fetching or re-scanning provider content.

Missing or inconsistent provider object identity must fail closed rather than silently changing provenance.

### 7. Retention includes physical provider-quarantine cleanup

Email staging retention now includes provider attachment quarantine state. When the staged email expires:

- provider-quarantine bytes are physically deleted;
- internal provider locator and quarantine key are cleared;
- acquired byte hash and size are cleared;
- staged provider hash and residual attachment MIME/size metadata are redacted;
- the manifest records an expired/purged state.

A separately filed canonical Correspondence record is not deleted by this staging-retention action; it remains under its own record authority.

### 8. Audit remains content-free

Attachment acquisition audit metadata may record only bounded operational fields such as provider kind, internal message/claim ids, admission state, scanner state and byte size.

It must not contain:

- credential values or bearer tokens;
- credential references;
- provider attachment locators;
- filenames;
- message subject/body/sender/recipient content;
- raw provider responses;
- attachment bytes;
- attachment hashes;
- claim evidence or privileged/legal content.

## Consequences

### Positive

- External email attachments can now enter a controlled malware boundary without becoming Evidence.
- Exact provider object resolution prevents ambiguous attachment acquisition.
- Clean, infected and scanner-error bytes all remain isolated until a later explicit authority decision.
- Retention cannot leave provider-quarantine bytes orphaned after staging data expires.
- Existing provider credential, tenant, replay, correspondence and claim-authority boundaries remain intact.

### Trade-offs

- A claims manager must first link the email and then explicitly request acquisition.
- Clean attachments require a later separate human Evidence-admission tranche before claim processing can use them as Documents.
- No background attachment sweep, automatic retry, OAuth refresh or provider push attachment download is introduced.

## Non-authority statement

This decision grants no email send authority, no automatic claim association, no automatic Correspondence promotion, no automatic Evidence admission, no OCR/AI execution over provider bytes, and no authority over coverage, causation, fault, liability, fraud, recoverability, governing law, legal time-bar effect, reserve, settlement, payment or claim closure.
