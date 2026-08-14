# Unified Evidence Matrix

## Purpose

The Evidence Matrix gives a claims handler one read-only view of:

- human-approved Claim Facts;
- the reviewed extraction and document version supporting each fact;
- deterministic corroborating sources with the same field path and approved value;
- active evidence conflicts; and
- facts that still cite a superseded or unavailable document version.

It is a derived read model. It does not persist another fact table and does not mutate Claim Facts, document versions, chronology, financial review or assessment snapshots.

## Matrix columns

| Column | Meaning |
|---|---|
| Topic | Claims-native label derived from the structured field path or conflict topic |
| Fact | Current human-approved Claim Fact only |
| Supporting Evidence | Reviewed source document, version, locator, quote and verification state |
| Conflicting Evidence | Active chronology conflict and its human review status |
| Status | Supported, open conflict, reviewed conflict, superseded source or unavailable source |

## Source grouping

The authoritative source is the extraction recorded on the Claim Fact. Additional reviewed extractions are shown as corroborating evidence only when all of the following match deterministically:

1. the extraction semantic kind is `fact`;
2. the extraction has a human status of `approved` or `edited`;
3. the structured field path matches; and
4. the human-approved value equals the current Claim Fact value.

Opinions and inferences never enter the Fact column.

## Conflict handling

A conflict attaches to a fact row only through its source extraction identifiers. Active conflicts that cannot attach to a current Claim Fact remain visible as conflict-only rows. Conflict state never determines which source is factually correct.

## Document versions

The Matrix always identifies document family, version and current/superseded state. When a Claim Fact still cites a superseded source, the row is flagged for re-review. Approval is not transferred to the replacement document.

## Security and boundaries

- The parent claim is resolved inside the authenticated tenant before any matrix query.
- Deleted and cross-tenant claims return 404.
- No external AI call is made.
- No causation, coverage, liability, fraud, reserve or settlement conclusion is generated.
- Internal identifiers remain available to the API for provenance but are not the primary operator presentation.
