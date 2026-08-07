# ADR-021 — Alternative quotations are not cumulative claim exposure

## Status
Accepted — Sprint 5 Phase B

## Context
The MT ORION pilot found that Initial Assessment summed quotation line items from two mutually exclusive repair options together with an invoice, producing a misleading USD 755,000 exposure figure.

## Decision
Financial exposure summaries must distinguish at least:
- reviewed invoiced/claimed cost;
- accepted cost;
- paid cost;
- quotation alternatives.

Quotation alternatives are displayed individually and are never added together into a single claim-exposure total merely because they coexist in the file.

## Consequences
Financial Review can still compare multiple repair scopes and prices, while Initial Assessment no longer inflates exposure by summing mutually exclusive commercial options. Human reviewers remain responsible for recoverability, accepted quantum and settlement decisions.
