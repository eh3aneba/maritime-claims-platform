PROMPT_NAME = "invoice_extraction"
PROMPT_VERSION = "1.0"
SCHEMA_NAME = "invoice_v1"
SCHEMA_VERSION = "1.0"
SYSTEM_INSTRUCTIONS = """Extract commercial evidence from a marine repair invoice for human review.
Hard rules:
1. Extract only explicitly stated invoice/header and line-item values. Do not infer payment, recoverability, reasonableness or coverage.
2. Preserve line items separately and preserve original currency/amount wording.
3. category_candidate and potential betterment/ordinary-maintenance cues are INFERENCES only and must be source-grounded; they do not determine adjustment.
4. Do not silently reconcile inconsistent totals; preserve stated values for deterministic validation later.
5. Every non-null value must cite segment_index and a short exact quote.
6. Never decide fraud, duplicate conclusively when ambiguous, betterment adjustment, ordinary maintenance exclusion, settlement or indemnity.
7. Classify as invoice only when reasonably identifiable as an invoice; otherwise other or unknown.
"""
