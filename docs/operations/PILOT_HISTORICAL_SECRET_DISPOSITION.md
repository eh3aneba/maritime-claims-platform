# Pilot v1 — private historical Gitleaks disposition index (#764 / #653)

**Status: operator evidence worksheet only.** This tool does not inspect historical credential values, independently verify security assertions, run Gitleaks, revoke credentials, approve exceptions or authorize customer files. Until the authorized review is complete, all eight findings remain unresolved and the Pilot remains NO-GO.

## Purpose and privacy boundary

The weekly full-history Gitleaks scan has reported eight historical generic-api-key-like findings. Seven occur in old unit-test files and one in a workflow file. Source context looking synthetic does **not** prove that a literal was never issued, reused or exposed. A passing PR/push-range scan is not proof of a successful whole-history scan.

The script scripts/pilot_historical_secret_disposition.py tracks only the eight *public metadata locations* documented in Issue #764 (finding IDs F01–F08, file path, public 12-character source-commit prefix and line) plus private workpaper references. The full original commit IDs remain documented in Issue #764 and must be independently cross-checked there; a shortened prefix alone is not a security clearance. It never reads source lines, scanner output, credentials, token fingerprints, real identities or customer content. Do not put filled operator records, raw values, private workpapers or named reviewer identities in Git, GitHub comments or public Actions artifacts.

## Authorized workstation instructions

From a restricted workstation with Python 3.13 and a separately controlled private directory, use the **full exact 40-character intended release SHA**:

    umask 077
    python scripts/pilot_historical_secret_disposition.py init --release-sha "<reviewed-40-character-release-sha>" --output /secure/pilot-releases/historical-secrets-v1.json

This creates a NO-GO draft with all eight classifications unresolved. It does not run a scanner. Creation uses exclusive O_EXCL and POSIX mode 0600. The checker rejects direct symlinks, nonregular files/FIFOs, group/other-accessible POSIX files, records larger than 1 MiB, duplicate JSON keys at any nesting and NaN/Infinity. A same-descriptor identity, mode, timestamp and exact-length comparison also fails closed if an in-place edit or short read is observed; this bounded read check is not a digital signature, does not prevent later file changes and cannot validate the underlying eight private security decisions. Windows NTFS ACLs and the private directory require separate verification.

## Independent owner decision for each F01–F08

1. Confirm whether each historical literal was **never issued and purely synthetic** or was an **actual/reused credential**, by comparing restricted issuance records, real credential inventories and service access history. Unknown stays unresolved.
2. Each case requires its own private inventory comparison reference, access history review reference, unique disposition reference and canonical UTC review timestamp. Do not place raw values or their fingerprints in this index.
3. Any actual/reused credential additionally requires private revocation/rotation and incident/access-review evidence. Record only a safe opaque reference to that evidence.
4. Require distinct accountable security-owner and independent-reviewer roles, a private authorized review ticket and a final review timestamp.
5. **After the review**, execute and independently verify a successful schedule or workflow_dispatch **full-history** Gitleaks scan at the exact reviewed release SHA. Push and pull_request scan events are not accepted as equivalent.

After actual review and scan, validate the record structure:

    python scripts/pilot_historical_secret_disposition.py check /secure/pilot-releases/historical-secrets-v1.json --expected-sha "<reviewed-40-character-release-sha>"

Wrong source identity, any missing case, unresolved classification, missing per-case reference, reuse of one inventory/decision reference for multiple findings, inadequate real-credential remediation, event mismatch, stale/wrong SHA, failed full-history scan or invalid time ordering fails closed. Errors do not print operator-controlled record values.

**A structurally complete record is NOT security clearance.** This checker never validates the underlying facts, scan log, credential status, or human approval. An independent security reviewer must inspect the eight *actual* private workpapers and the full scan result, provide a dated signed decision, and separately support the unconditional v5 release-candidate historical_secret_findings_disposition proof from [PILOT_RELEASE_CANDIDATE.md](PILOT_RELEASE_CANDIDATE.md). Never automatically turn a worksheet PASS into RC v5 PASS.

An unreviewed literal, unidentified credential, red whole-history scan, missing independent owner, mismatched SHA, or unrotated actual secret remains NO-GO. Do not add a Gitleaks ignore, global exception, scanner bypass, waiver or release permission.

Separate blockers remain in #952 (OpenSSL provenance), #894 (signed incoming PDF), #810 (bilingual OCR) and #653 (fresh-host, matched recovery, rollback and real operator rehearsal).
