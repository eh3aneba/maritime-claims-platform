# AI Quality, Safety and Cost Evaluation Promotion Gate

Sprint 11B turns the Sprint 11A staging activation into a measured, version-pinned promotion decision. The application records benchmark observations but does not execute a provider benchmark automatically, store benchmark content or calculate a provider invoice.

## Lifecycle

1. A Manager/Admin creates an append-only suite anchored to one active Sprint 11A activation.
2. The suite freezes the activation’s model, prompt bundle and schema bundle plus the server-owned `quality_safety_cost_v1` thresholds.
3. Managers record content-free aggregate case results with a bounded evidence reference and canonical SHA-256 result hash.
4. Finalization deterministically calculates metrics and freezes a SHA-256 evaluation snapshot. Any missing or failed threshold makes the attempt terminal and non-promotable.
5. A Quality reviewer and Risk reviewer—different people and both different from the requester—independently reproduce the evidence.
6. A non-requesting Administrator records `promote_staging` or `hold`. Promotion expires no later than the anchored activation.
7. Revocation is an immediate application promotion kill switch. A new attempt is append-only.

## Benchmark profile

The first profile requires at least 12 cases, including at least three Chief Engineer Reports and three Engine Logs. It also requires passing results for prompt injection, malformed input, cross-tenant access and restricted-data blocking.

| Metric | Calculation | Threshold |
|---|---|---:|
| Field precision | TP / (TP + FP) | ≥ 90% |
| Field recall | TP / (TP + FN) | ≥ 85% |
| Unsupported-claim rate | Unsupported / extracted claims | ≤ 2% |
| Source-quote validity | Valid / checked quotes | ≥ 98% |
| Human override rate | (Edited + Rejected) / reviewed | ≤ 20% |
| P95 latency | nearest-rank case latency | ≤ 30 s |
| Mean observed provider cost | ceiling of observed µUSD / case count | ≤ USD 0.50 |

Rates are stored as integer basis points to make threshold decisions deterministic. Cost is an observed value supplied from the controlled provider artifact; the platform explicitly does not calculate or certify provider billing.

## Content boundary

Case records accept counts, latency, tokens, observed cost, pass/fail state, data mode, a bounded `artifact://`, `runbook://`, `ticket://` or `monitor://` reference, a concise human note and execution time. Request schemas reject extra fields. Document text, prompts, expected answers, extracted answers, source quotes, provider responses, keys and unrestricted URLs are outside the model.

## Authorization boundary

Promotion authorizes only the measured synthetic/de-identified staging bundle. It does not modify provider configuration, authorize production, restricted or real claim documents, permit autonomous claim decisions or bypass the existing human review queue. Sprint 11C remains the separate organization/data-owner authorization for a bounded real-document pilot.

