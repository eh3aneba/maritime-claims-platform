# Document & Evidence Foundation — Sprint 2 Phase G

## Purpose

Phase G introduced the secure evidence lifecycle for a marine claim. Sprint 7B adds quarantine-first malware admission scanning before text extraction or controlled AI intelligence can touch a new upload; OCR for scanned evidence remains pending.

## Endpoints

- `GET /api/v1/claims/{claim_id}/documents` — list active claim documents and non-downloadable quarantine metadata.
- `POST /api/v1/claims/{claim_id}/documents` — upload one evidence file using multipart form data.
- `GET /api/v1/claims/{claim_id}/documents/{document_id}/download` — authenticated evidence download.
- `DELETE /api/v1/claims/{claim_id}/documents/{document_id}` — soft-delete from the active claim file.

## Accepted MVP formats

- PDF
- JPG/JPEG
- PNG
- DOCX
- XLSX

The default limit is 25 MB per file (`MAX_UPLOAD_MB`). Server-side validation checks extension, declared content type and a basic file signature before ClamAV admission scanning. These controls reduce risk but do not constitute production security certification.

## Admission and quarantine flow

1. Stream the upload to `_quarantine/{organization_uuid}/{claim_uuid}/{upload_uuid}.{extension}` while calculating SHA-256.
2. Reject empty, oversized, unsupported, signature-mismatched or duplicate bytes.
3. Stream the stored bytes to `clamd` with the INSTREAM protocol. The scanner never receives the host path or user filename.
4. On `CLEAN`, atomically promote the bytes to active storage, create the `documents` record and queue text extraction.
5. On `FOUND`, retain a `quarantined_uploads` record and bytes, write `QUARANTINE_DOCUMENT_UPLOAD`, and return `422`.
6. On scanner/transport/storage-promotion failure, fail closed, retain quarantine metadata and bytes, and return `503`.

Quarantined uploads are visible to the claim handler but have no download or processing endpoint. The ClamAV TCP port is exposed only inside the Compose network.

## Storage model

Uploaded bytes never use the user filename as their path. Local development uses a server-generated key:

```text
{organization_uuid}/{claim_uuid}/{document_uuid}.{extension}
```

The database keeps original filename, MIME type, byte size, SHA-256, confidentiality, uploader, processing status, malware scan status/timestamp and storage key. Docker persists local evidence in the `local_documents` volume and ClamAV signatures in `clamav_data`. The storage boundary is intentionally small so an S3-compatible implementation can replace local storage later.

Rows created before Sprint 7B migrate to `legacy_unscanned`. They remain usable and visibly distinct from `clean` uploads; a separate controlled rescan workflow is required before changing their status.

## Integrity and duplicates

SHA-256 is calculated while streaming the upload. The current model treats identical bytes inside the same claim as a duplicate and returns `409 Conflict`. Same bytes in different claims are allowed because evidence provenance is claim-scoped.

## Deletion semantics

Delete is a **soft delete**. The document disappears from active listing/download endpoints but the underlying bytes remain retained for evidentiary/audit purposes. Physical retention and purge policy will later become tenant-configurable under data-governance controls.

## Audit events

- `UPLOAD_DOCUMENT`
- `QUARANTINE_DOCUMENT_UPLOAD`
- `DOWNLOAD_DOCUMENT`
- `DELETE_DOCUMENT`

## Tenant security

Every document operation first resolves the parent claim within the authenticated `organization_id`, then resolves the document by organization + claim + document id. Cross-tenant requests return `404` without revealing whether the target resource exists.

## Sprint 3 boundary

Phase G does **not** classify or understand evidence. Sprint 3 will process an uploaded document through OCR/text extraction, document classification and structured fact extraction while preserving this original evidence record as the immutable source.
