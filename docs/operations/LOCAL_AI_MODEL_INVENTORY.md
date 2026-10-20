# #752 — opt-in localhost Ollama model inventory (development only)

This operator-only check requests the **local model tag listing** with
one bounded HTTP `GET /api/tags` on **127.0.0.1:11434**. It never runs
inference or sends a document, prompt, customer identifier or insurer
Evidence; it does not inspect arbitrary files or contact an external API.

## PowerShell on the developer PC

From the repository root with Ollama running:

```powershell
ollama list
$env:PYTHONPATH = "apps/api"
python -m scripts.pilot_local_ai_model_inventory --inspect-fixed-local-ollama-tag
```

The only accepted option is the exact explicit flag. Without it, the
command does not connect. The model tag is fixed as `qwen3:1.7b`.

The output JSON contains only a fixed model tag, whether that tag
appeared exactly once in the local registry and its reported 64-hex
SHA-256 digest (or null if missing). The digest comes from the local
server's own untrusted `/api/tags` response. It is not independent attestation
of the model weights, binaries, machine, network controls,
or actual model used during a subsequent inference call. The model
could be replaced between this check and inference. Record and compare
the digest independently, following a security-reviewed process,
before drawing provenance conclusions.

The output always sets `observed_digest_source_attested=false`,
`model_artifact_independently_attested=false`,
`model_execution_verified=false`,
`network_egress_isolation_verified=false`,
`human_review_completed=false` and `pilot_accepted=false`.

The script never returns other installed model names, raw JSON, HTTP
error text, IP-derived host details, stack traces, model responses or
other source content. Invalid, oversized, duplicate and malformed model
entries fail closed. The script writes no file and reports a generic
error in those cases. A missing tag also returns a nonzero exit code.

Tests do **not** access localhost or execute a model:

```bash
python -m unittest scripts.tests.test_pilot_local_ai_model_inventory -v
python -m unittest scripts.tests.test_pilot_local_ai_model_inventory_policy -v
```

This inspection can precede
`python -m scripts.pilot_local_ai_hm_repeat_smoke --run-fixed-synthetic-ollama-repeat-3`.
The latter is separately opt-in and runs only nine synthetic fixed
requests. Neither CLI enables production AI.

**Pilot GO=NO.** Independent runtime provenance, real local inference,
human H&M expert reference, security isolation verification and operator
authorization have not been established by GitHub CI.
