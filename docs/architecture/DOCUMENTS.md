# Document & Evidence Foundation — Sprint 2 Phase G

## Purpose

Phase G introduces the first secure evidence lifecycle for a marine claim. AI/OCR remains deliberately deferred to Sprint 3; Phase G establishes the source-of-truth bytes and metadata that later AI outputs must cite.

## Endpoints

- `GET /api/v1/claims/{claim_id}/documents` — list active claim documents.
- `POST /api/v1/claims/{claim_id}/documents` — upload one evidence file using multipart form data.
- `GET /api/v1/claims/{claim_id}/documents/{document_id}/download` — authenticated evidence download.
- `DELETE /api/v1/claims/{claim_id}/documents/{document_id}` — soft-delete from the active claim file.

## Accepted MVP formats

- PDF
- JPG/JPEG
- PNG
- DOCX
- XLSX

The default limit is 25 MB per file (`MAX_UPLOAD_MB`). Server-side validation checks extension, declared content type and a basic file signature. Full malware/virus scanning is a pre-pilot/enterprise security milestone rather than an MVP claim.

## Storage model

Uploaded bytes never use the user filename as their path. Local development uses a server-generated key:

```text
{organization_uuid}/{claim_uuid}/{document_uuid}.{extension}
```

The database keeps original filename, MIME type, byte size, SHA-256, confidentiality, uploader, status and storage key. Docker persists local evidence in the `local_documents` volume. The storage boundary is intentionally small so an S3-compatible implementation can replace local storage later.

## Integrity and duplicates

SHA-256 is calculated while streaming the upload. The current model treats identical bytes inside the same claim as a duplicate and returns `409 Conflict`. Same bytes in different claims are allowed because evidence provenance is claim-scoped.

## Deletion semantics

Delete is a **soft delete**. The document disappears from active listing/download endpoints but the underlying bytes remain retained for evidentiary/audit purposes. Physical retention and purge policy will later become tenant-configurable under data-governance controls.

## Audit events

- `UPLOAD_DOCUMENT`
- `DOWNLOAD_DOCUMENT`
- `DELETE_DOCUMENT`

## Tenant security

Every document operation first resolves the parent claim within the authenticated `organization_id`, then resolves the document by organization + claim + document id. Cross-tenant requests return `404` without revealing whether the target resource exists.

## Sprint 3 boundary

Phase G does **not** classify or understand evidence. Sprint 3 will process an uploaded document through OCR/text extraction, document classification and structured fact extraction while preserving this original evidence record as the immutable source.
