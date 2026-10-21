# #752 — three-scenario H&M local AI fixture matrix (offline only)

This narrow test slice adds `scripts/pilot_local_ai_hm_fixture_matrix.py` and
`apps/api/tests/test_local_ai_hm_fixture_matrix.py` with three invented,
code-owned machinery-loss situations. No customer files or PII are involved.

| Scenario | Synthetic facts to keep separate | What this stage can check |
| --- | --- | --- |
| `complete_records` | Notice, reported engine-log entries, supplied maintenance/log extract status | Exact quotes remain attributed to their source and version |
| `missing_engine_records` | Reported vibration and missing *submission* of log/maintenance records | An absence of supplied documents is **not** proof of nonexistence or negligence |
| `conflicting_alarm_times` | Engineer reports 11:30; workshop reports 11:55 | Both source claims remain separately quoted; **no** resolution, fault finding or liability judgment |

### What is actually measured

`deterministic_reference_candidate(scenario)` is an **explicit,
code-authored no-model quotation baseline**, **not** a certified expert
ground truth. `evaluate_synthetic_scenario(scenario, candidate)` first
enforces the exact existing source/version/substring validation contract.
It then returns safe **counts only**: source-backed quotes, exact baseline
matches, omitted baseline quotes and additional source-backed excerpts.
It does not return raw model text or assert semantic correctness.

The expected model tag is `qwen3:1.7b` with the conspicuous all-zero,
**unverified** digest placeholder; this is synthetic metadata, **never an
identity attestation**. A matching tag or SHA256 shape cannot prove which
binary actually ran. Changing the prompt version or digest fails closed.
The baseline is constructed directly from literal fixture source bodies;
no model is executed. A matching count can still be misleading through
selective quotation or contradictory evidence. Human expert review and
separate actual-model evaluation are mandatory.

Run focused tests:

```bash
pytest -q apps/api/tests/test_local_ai_hm_fixture_matrix.py
```

### Explicit outstanding gates

- Obtain independent H&M claims-expert adjudication of expected answers,
  uncertainty handling and distinct fact/opinion categories.
- Measure a **real, pinned, self-hosted** model against these and an
  independently defined no-model baseline; record run/latency/quality
  with controlled infrastructure, input and versioning.
- Enforce authorized tenant+Evidence custody, legal/privacy constraints,
  reviewer identity and immutable auditable human decision persistence.
- Keep the local AI experimental adapter default-off for real claims,
  and external APIs disabled for Pilot v1.

**Pilot GO=NO.** This code is not an Evidence ingestion path, insurer
assessment, production adapter, reviewer workflow or approval.
