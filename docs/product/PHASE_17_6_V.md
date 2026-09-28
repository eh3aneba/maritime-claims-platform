# Phase 17.6-V — SFTP processing-release compatibility

Phase V proves that SFTP Evidence admitted by Phase T and bound by Phase U can use the existing generic downstream-processing release without an SFTP-specific release subsystem.

## Flow

1. Complete T and create canonical initial SFTP Evidence/Document v1.
2. Complete U and bind that Document to the generic Evidence family.
3. Confirm processing retry remains blocked.
4. An Admin+MFA actor grants the existing generic processing release for the exact current Document.
5. The release authorizes local text processing only.
6. Normal processing/retry may then enqueue local extraction.
7. Revocation re-blocks downstream processing.

## Authority boundary

The release itself performs no:

- SFTP/provider network operation;
- object-storage read/write/delete;
- Document mutation;
- processing enqueue;
- OCR/extraction;
- AI execution or AI authorization;
- Claim mutation;
- checkpoint advance;
- recurring synchronization.

## AI boundary

`local_text_processing_authorized = true` does not imply AI authority.

`ai_processing_authorized` remains false throughout grant, replay and revocation.

## Integrity

Processing-release resolution depends on the generic U Evidence-family binding. Because U revalidates the SFTP T/S/R/Q/P lineage, tampering anywhere in that trusted lineage invalidates the release fail-closed.

## Compatibility outcome

Phase V intentionally adds no provider-specific processing-release production code. The compatibility tests are the acceptance proof. If they remain green with the existing SharePoint/Google Drive processing-release suite unchanged, the generic boundary is confirmed provider-neutral for SFTP.
