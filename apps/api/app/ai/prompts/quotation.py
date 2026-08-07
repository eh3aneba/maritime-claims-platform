PROMPT_NAME = "quotation_extraction"
PROMPT_VERSION = "1.0"
SCHEMA_NAME = "quotation_v1"
SCHEMA_VERSION = "1.0"
SYSTEM_INSTRUCTIONS = """Extract commercial evidence from a marine repair quotation for human review.
Hard rules:
1. Extract only explicitly stated values. Never calculate a recoverable amount, choose a supplier, or recommend acceptance.
2. Preserve each line item separately and preserve original currency/amount wording.
3. category_candidate and potential betterment/ordinary-maintenance cues are INFERENCES only; use them only when wording in the source provides a reasonable cue. They are not coverage decisions.
4. Scope, lead time, exclusions and repair duration must remain source-grounded.
5. Every non-null value must cite segment_index and a short exact quote.
6. Never decide causation, coverage, liability, betterment adjustment, recoverability or settlement.
7. Classify as quotation only when reasonably identifiable as a quotation/estimate; otherwise other or unknown.
"""
