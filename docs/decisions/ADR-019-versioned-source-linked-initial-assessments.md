# ADR-019: Versioned, source-linked initial assessments

## Status
Accepted

## Decision
Initial Assessments are persisted as immutable-by-version snapshots with independently reviewable sections. The first drafting layer is deterministic and assembled from existing claim records, human-approved facts, reviewed chronology, rule outputs, financial evidence, reserve history, and open tasks.

An LLM may later propose wording improvements, but it must not silently replace source-linked section content or promote unreviewed material into an approved assessment.

If the claim readiness gate is not satisfied, generation requires an explicit human override reason and the resulting assessment is marked Preliminary.

Overall approval requires every section to have been Approved or Edited by a human. Approval of the complete assessment is restricted to Claims Manager/Admin roles.

## Rationale
This preserves auditability, supports offline/private deployments, avoids free-form unsupported summaries, and maintains a clear distinction between machine drafting and the official human-reviewed claims record.
