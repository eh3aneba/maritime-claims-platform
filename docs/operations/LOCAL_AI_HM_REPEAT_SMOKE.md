# #752 — repeat exactly three fixed synthetic H&M cases three times (local PC)

**Experimental manual-only benchmark candidate, not a claim workflow.**
This script reuses the merged three-scenario source/critical-quote gate
and the existing development adapter that connects only to literal
`127.0.0.1:11434`. It sends exactly **nine invented, code-owned** requests
(three rounds × three scenarios) sequentially. It does **not** read user
files, customer Evidence, arbitrary prompts, claim IDs or tenant data.

From the repository root **on the PC that has Ollama and `qwen3:1.7b`**:

```powershell
ollama list
$env:PYTHONPATH = "$(Get-Location)\apps\api;$(Get-Location)"
& .\.venv-local-ai\Scripts\python.exe -m scripts.pilot_local_ai_hm_repeat_smoke --run-fixed-synthetic-ollama-repeat-3
```

The exact option is mandatory and the command is **not invoked by CI**;
without it, the script refuses to connect. The local adapter uses a
fixed 30s per-request socket timeout (not an end-to-end SLA),
`temperature=0`, bounded output, fixed schema, `think=false` and
code-owned `keep_alive="1m"` (since merged #798). The adapter asks
Ollama to retain the model locally between sequential synthetic calls,
not to guarantee a warm execution. Observed latency still depends on
host load, prompt/response size and runtime. No production benchmark
or inference-provider activation follows from this setting.

For the bounded 2026-10-24 post-#798 operator observations and
interpretation caveats, see [POST_RETENTION_SYNTHETIC_HM_OBSERVATION_20261024.md](POST_RETENTION_SYNTHETIC_HM_OBSERVATION_20261024.md).
The results are not independent model/expert attestations.

## Output / nonclaims

Stdout contains only a JSON summary: three code-owned scenario labels,
round count, per-scenario counts of `accepted_rounds`,
`incomplete_rounds`, `rejected_rounds`, and min/max observed response
milliseconds. Per scenario the output additionally counts
`context_complete_rounds`, `context_incomplete_rounds`,
`context_not_evaluated_rounds` (rejected responses cannot be scored)
and `context_pairs_missing_total`. These are bounded *non-gating*
observations of three fixed fact/qualifier pairs appearing in the same
validated excerpt; they are **not semantic correctness or expert review**.
A round is source-accepted only if **all required literal
quote anchors** are found in source-backed extracts. Incomplete and
unsupported/invented excerpts are counted separately.

There is no prompt, source body, model text, exception trace, private
identifier or automatic file write in the output. Any missing,
incomplete or rejected case makes the process exit with a nonzero code.

This tool **does not independently verify** that a specific Ollama
binary/model artifact executed or that the host's network egress is blocked.

**These counts do not establish model accuracy or statistical
reproducibility.** Three runs are far too few to establish reliability
or semantic correctness. The synthetic phrase baseline has **not**
been independently approved by an H&M expert; model artifact identity,
network isolation configuration and actual execution logs have not
been independently verified. The JSON therefore always reports
`repeatability_proven=false`,
`model_execution_independently_attested=false`,
`context_preservation_expert_verified=false`,
`model_digest_attested=false`,
`expert_ground_truth_approved=false`, and `pilot_accepted=false`.

CI tests use fake provider objects and **do not execute real Ollama**.

```bash
pytest -q apps/api/tests/test_local_ai_hm_repeat_smoke.py
python -m unittest scripts.tests.test_pilot_local_ai_hm_repeat_smoke_policy -v
```

**Pilot GO=NO.** No insurer/customer documents are authorized. Before
moving beyond these invented scenarios, perform a separately reviewed
real local PC run, verify the model runtime SHA/digest, apply operator
network controls, establish an independent marine claims reference and
human review criteria, and obtain formal pilot security approval.
