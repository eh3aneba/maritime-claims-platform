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
$env:PYTHONPATH = "apps/api"
python -m scripts.pilot_local_ai_hm_repeat_smoke --run-fixed-synthetic-ollama-repeat-3
```

The exact option is mandatory and the command is **not invoked by CI**;
without it, the script refuses to connect. The local adapter uses a
short per-request timeout, `temperature=0`, bounded output, fixed
schema, `think=false` and `keep_alive=0`. Because the model is unloaded
after each request, measured elapsed time may include repeated cold
starts; do not compare results to warmed-up production inference.

## Output / nonclaims

Stdout contains only a JSON summary: three code-owned scenario labels,
round count, per-scenario counts of `accepted_rounds`,
`incomplete_rounds`, `rejected_rounds`, and min/max observed response
milliseconds. A round is source-accepted only if **all required literal
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
