# ADR-261: Fresh processing release and explicit recurring baseline transition for SFTP N+1

## Status

Proposed for Phase 17.6-AD.

## Context

Phase AC creates canonical SFTP Evidence Document N+1 in the existing family, but correctly leaves processing and recurring-source authority separate.

The generic processing-release model is already version-specific.

Recurring due-tick baseline resolution, however, historically understands initial v1 and the older family-version admission lineage. An ObservationRefreshAdmissionExecution-created N+1 needs an explicit governed bridge before it may become the recurring observation baseline.

## Decision

Phase AD keeps two authorities separate.

### Processing release

Reuse the existing generic processing-release lifecycle unchanged.

A prior-version release never carries to N+1 because releases bind exact Document ID and version. N+1 requires a fresh human-controlled release. AI authority is not widened.

### Recurring baseline

Add an immutable `ExternalDocumentSourceRecurringBaselineTransition`.

The transition is human-authorized and binds:
- AC refresh admission execution;
- AB refresh execution;
- originating Y changed due-tick observation;
- active X recurring schedule revision;
- U Evidence-family binding;
- prior and current canonical Documents;
- refreshed projection/version token and content proof.

It performs no SFTP/provider I/O, no storage I/O and no mutable checkpoint/schedule/Document changes.

The transition is logical authority: baseline resolution recognizes the refreshed projection only when the exact transition row is integrity-valid.

## Fail-closed behavior

Before the transition, recurring baseline resolution for an AC-created SFTP N+1 fails explicitly.

A transition fails if:
- AC/AB/Y lineage is missing or drifted;
- current Document is no longer the AC N+1;
- schedule was disabled/replaced;
- binding/source identity changed;
- changed observation no longer matches AB refresh;
- request replay differs.

## Subsequent due tick

After transition, the next due tick uses the refreshed projection/version token as its baseline. Seeing the same remote metadata therefore classifies as `unchanged`.

## Legacy compatibility

Initial v1 and historical SharePoint/Google Drive family-version admission baseline behavior remain unchanged.

## Next

Phase 17.6-AE will close SFTP production integration with production adapter wiring, operator UX, restart/replay proof and full vN→vN+1 acceptance.
