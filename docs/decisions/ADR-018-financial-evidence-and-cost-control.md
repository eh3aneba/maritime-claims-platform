# ADR-018 — Keep commercial evidence outside scalar claim facts

**Status:** Accepted  
**Date:** 2026-08-07

Quotation and invoice fields are repeatable commercial evidence. They must remain source-linked and human-reviewed, but must not overwrite scalar `claim_facts` as multiple suppliers, quotes, invoices, and line items may legitimately coexist.

A derived `cost_items` schedule may be materialized only from human-approved/edited financial extractions. Financial flags remain deterministic review cues and never decide recoverability, betterment deductions, ordinary-maintenance exclusions, supplier selection, settlement, or indemnity.

Reserve changes are append-only in `reserve_history`; `claims.current_reserve` is only the current pointer used by operational screens.
