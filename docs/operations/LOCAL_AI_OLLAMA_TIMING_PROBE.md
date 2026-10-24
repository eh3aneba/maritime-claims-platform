# Local AI #752 — opt-in synthetic-only Ollama timing probe

## Purpose

Operator's Windows PC returned a 10.014s rejection under prior 10s limit,
and later a 30.017s rejection under 30s limit. Repeated H&M fixtures were
accepted for *source quote review* 5/9 times in the second run. The adapter's
`keep_alive=0` may cause repeated model unload, but **that hypothesis has
not been verified** by these observations. Do not blindly increase runtime
timeouts, enable external AI, or process insurer Evidence.

## PowerShell operator experiment

After updating to the merged commit, from the repository root, with Ollama
and exact tag `qwen3:1.7b` running:

```powershell
cd "C:\MCRI\maritime-claims-platform"
& .\.venv-local-ai\Scripts\python.exe -m scripts.pilot_local_ai_ollama_timing_probe --run-fixed-synthetic-ollama-timing-probe
Write-Host "Exit code: $LASTEXITCODE"
ollama ps
```

This program makes **exactly two** sequential identical trivial invented
requests to literal `127.0.0.1:11434`, HTTP `/api/generate`. It has **no
input file/claim/customer loader**, no arbitrary CLI prompt, no generic URL,
no external inference API, no database, no persistence and no new application
AI provider activation.

Each request uses fixed model, `stream=false`, `think=false`, `num_ctx=4096`,
`num_predict=16`, `temperature=0`, a 90-second **socket read timeout**
(not a total elapsed-time deadline), and **`keep_alive="1m"`** so Ollama is
asked to retain the model in memory for one minute. This differs
intentionally from the existing H&M adapter's `keep_alive=0`, which remains
**unchanged**. The operator may observe higher memory usage during that minute.

Only bounded timing/count categories (`wall`, native `load`, `prompt_eval`,
`eval`, `total` milliseconds, output token count), request order, and fixed
FALSE attestation flags are printed; **no model-generated prose, prompt text,
HTTP exception, registry digest or customer identifiers** are printed. A
failed request outputs a fixed `local_runtime_unavailable` or
`invalid_model_response` category and the next fixed test proceeds. An
unexpected exception prints only a fixed failure message. No artifact is
saved or sent anywhere outside the local operator's console.

## Interpretation limits

Compare *both* `load_ms_observed` and `eval_ms_observed`, and note `ollama ps`
PROCESSOR to help distinguish warm model loading from inference speed.
Neither the first trial is **proven cold** nor the second **proven warm**: the
model may have already been loaded before the command or Ollama may evict
it early. Native Ollama metrics are **no independent attestation** and do
not prove GPU utilization, sustained H&M throughput, model weight integrity,
completeness/accuracy of evidence attribution, network egress isolation,
or fitness of the tiny `qwen3:1.7b` model for claims decisions.

Only when actual timings support the model-retention hypothesis consider a
separate bounded, synthetic-only change to `keep_alive`, with explicit negative
security regression tests. The current production/pilot AI provider remains
disabled. **Pilot GO=NO**; no real customer Evidence is permitted in this probe.
