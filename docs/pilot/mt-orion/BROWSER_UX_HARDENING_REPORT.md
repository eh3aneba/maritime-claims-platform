# MT ORION — Real Browser UX Hardening Report

## Browser findings addressed

### Chronology
- Raw structured measurements are rendered as human-readable values.
- Event importance and conflict severity are labelled separately.
- Source-document names are visible for each event.
- Evidence drawers distinguish source count from field count.
- Canonical timestamp wording now states that the convention is for display only and does not determine evidentiary truth.

### Technical Review
- Maintenance values are human-readable rather than JSON.
- Internal extraction/document UUIDs are hidden from Claim Handler presentation.
- Evidence is displayed as readable cards with source quotes where available.
- HIGH/MEDIUM labels are explicitly described as investigation priority.
- Reviewed workshop evidence can be expanded without exposing database internals.

### Financial Review
- Invoice/actual commercial evidence is separated from quotation alternatives.
- Cost line items are grouped by source commercial document.
- Current reserve, invoiced, accepted, paid and open flags are visible in a summary row.
- Quotation alternatives remain explicitly non-cumulative.

### Initial Assessment
- Current Vessel Status no longer prints boolean values.
- Damage & Technical Findings separates equipment, physical findings, maintenance context and open issues.
- Documents use human-readable labels.
- Chronology entries include source-document labels.
- Requirement actions and their rule-generated tasks are deduplicated.
- Overdue task due dates are marked in newly generated versions.
- Approved assessments are immutable; revisions require a new version.

## Deployment fixes consolidated
- Next.js TypeScript intelligence-type fix.
- PostgreSQL 18 volume path.
- Alembic revision-column width.
- Explicit/document-processing migration integrity fix.
- Robust date/datetime formatting.
- Explicit web HOSTNAME/PORT for container health checks.
