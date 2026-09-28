# Phase 17.6-T — Admit one canonical initial SFTP Evidence/Document v1

Phase T consumes one Phase-S authorization and creates one initial canonical Document from the already-governed generation-3 SFTP staged bytes.

## Admission sequence

1. Lock the S authorization and verify its receipt.
2. Require the same human actor and active Claim.
3. Lock/revalidate the exact Q checkpoint and require the authorized R observation to remain latest.
4. Perform one fresh exact-file SFTP stat.
5. Require the fresh metadata projection to match the S authorization exactly.
6. Read the Phase-P staged object; do not reread remote SFTP content.
7. Verify staged SHA-256, size, ETag where available and storage-key hash.
8. Derive the filename only from the trusted governed listing lineage.
9. Validate allowed file type and file signature.
10. Run fresh authoritative malware scanning.
11. Promote clean bytes to canonical Document storage.
12. Create one Document, one T execution, one receipt and one audit event.

## Single-use and replay

One S authorization can create at most one T execution. Exact replay returns that execution without another stat, staged read or malware scan. A changed replay conflicts.

## Currentness

Any newer completed R observation makes an unconsumed S authorization stale. T does not bypass that failure even when the newer observation is also unchanged.

The Q checkpoint lock remains held through currentness, fresh-stat, staged verification and the final database commit so a concurrent R observation cannot slip into the decision window.

## Processing remains blocked

The admitted Document has no OCR/AI/content-processing authority. The processing service treats the new SFTP T execution as admitted external Evidence, so normal content-processing entrypoints require the later explicit processing-release boundary.

## Explicit exclusions

No remote content reread, folder listing, provider write/delete, staged-object mutation, OCR, text extraction, indexing, AI, Claim assessment mutation, checkpoint advance or recurring synchronization is performed.

## Next phase

Phase 17.6-U should bind this initial SFTP Document into the provider-neutral external Evidence-family control plane.
