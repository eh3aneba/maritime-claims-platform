# ADR-022 — AI review is grouped by evidence unit and exception-first

## Status
Accepted — Sprint 5 Phase C

## Context
The MT ORION pilot produced 223 extraction candidates from eight intelligence runs. Reviewing every field as an independent card created unnecessary cognitive load, especially for Engine Log rows, PMS jobs and commercial line items where several related fields describe one evidence unit.

## Decision
- Repeatable structured evidence is grouped by a deterministic field-path prefix such as `engine_log.events[n]`, `pms.records[n]`, `quotation.line_items[n]` and `invoice.line_items[n]`.
- A reviewer may approve or reject all pending fields in one group atomically.
- Editing remains field-level so human corrections preserve precise provenance.
- Groups with unverified citations, validation warnings, confidence below 0.90, or opinion/inference fields are marked `Needs Attention` and sorted first.
- The UI defaults to an exception-only grouped view; routine groups remain available by disabling the filter.
- Grouping changes review ergonomics only. It does not merge the underlying extraction records or change promotion rules.

## Consequences
The MT ORION regression set maps 223 extraction fields to 93 review groups, a 58.3% reduction in potential review actions if groups are reviewed once. The exception-first first pass contains 22 groups. Audit history remains field-level because each grouped action still records a review event against every extraction.
