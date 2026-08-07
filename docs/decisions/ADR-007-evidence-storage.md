# ADR-007: Keep claim evidence bytes outside PostgreSQL and use server-generated storage keys

## Status
Accepted

## Decision
Store document bytes in an object-storage abstraction (local persistent storage in the MVP; S3-compatible later). PostgreSQL stores metadata, SHA-256 and a generated `storage_key`. Never derive a physical storage path from the user-supplied filename.

Deletion is soft at the application layer during the MVP: active access is removed, while bytes remain retained for audit/evidentiary integrity.

## Rationale
- Avoids bloating the relational database with large binary objects.
- Provides a migration path to customer-controlled/on-prem object storage.
- Prevents path traversal via user filenames.
- Preserves evidence provenance and makes later OCR/AI reproducible from the original source.
