# SeeClaims — local AI first development host (owner decision)

**Decision status:** Owner-approved *development environment* preference.
**Personal-PC prototype:** Qwen3 1.7B / Ollama local execution **OBSERVED**. **Pilot AI runtime and model:** NOT INTEGRATED / NOT OPERATIONALLY ACCEPTED.

## Owner selection

For issue [#752](https://github.com/eh3aneba/maritime-claims-platform/issues/752),
the first **synthetic-only local LLM prototype** shall be attempted on the
**product owner's personal computer**, not a separately provisioned server.

This supplements the previously approved **self-hosted local AI first /
external inference API later** decision. A personal development computer is
**not** the eventual approved insurer environment and cannot be represented
as one. Do not place identifiable customer claims, privileged company
materials, tokens or production credentials in this prototype.

## Step 1 — establish hardware feasibility without secrets

Owner supplied screenshots of the first development host; see the dated
observations below. The following is still a useful checklist for a **new**
development host, not an unfulfilled requirement for this PC:

- OS and version; CPU model and architecture
- installed RAM and available free disk space
- discrete GPU model and dedicated VRAM, if any; CPU-only is valid for a
  small feasibility experiment but its latency must be measured
- whether Docker/WSL2 is already available and roughly how much storage
  can be allocated (if running Windows)
- whether local loopback-bound inference and restricted outbound network
  can be configured on this development host

### Optional Windows inspection (read-only)

In PowerShell, the owner can run:

```powershell
Get-CimInstance Win32_Processor | Select-Object Name
Get-CimInstance Win32_ComputerSystem | Select-Object @{Name='RAM_GB';Expression={[math]::Round($_.TotalPhysicalMemory / 1GB, 1)}}
Get-CimInstance Win32_VideoController | Select-Object Name
Get-PSDrive C | Select-Object Name,@{Name='Free_GB';Expression={[math]::Round($_.Free / 1GB, 1)}}
nvidia-smi
```

`nvidia-smi` is **optional** and may be unavailable; GPU VRAM reported by
Windows drivers can be inaccurate, so the owner should also check
Task Manager → Performance → GPU → **Dedicated GPU memory**.

Only share CPU/GPU models, RAM/VRAM, OS and free storage; **do not**
share device IDs, serial numbers, usernames, private paths or credentials.
The script is illustrative guidance, **not proof** that it has run.

## Dated owner-observed local feasibility (2026-10-15)

| Item | Evidence, not an R5 gate |
| --- | --- |
| OS | Windows 10 Pro 22H2, x64 |
| CPU / RAM | AMD Ryzen 5 2500U; 16 GB installed RAM |
| GPU | NVIDIA GTX 1050, 4 GB dedicated VRAM |
| Driver | NVIDIA 582.78 (after upgrade from 462.31) |
| Local runtime | Owner-reported Ollama CLI 0.40.4 |
| Local model | `qwen3:1.7b`, loaded via `llamacpp` |
| Offload | Owner's `ollama ps` reported **100% GPU**, 1.7 GB occupied, context 4096; not a timed end-to-end SeeClaims measurement |

The owner-provided synthetic turbocharger claim transcript uncovered
**material acceptance problems**, documented in issue #752: the model
misclassified imagined hypotheses as reported party allegations, inferred
possible negligence merely from missing logs, and sometimes treated
*not supplied* records as *non-existent*. The experimental prompt was also
split into several independent interactive turns with an unsupported
`/no_think` slash command; therefore **there is no clean, scored,
stateless 5-section evaluation yet**. No verified local inference adapter
is committed or connected to SeeClaims and no end-to-end privacy/egress
assessment was performed. Treat this as **environment feasibility only**,
not reliable maritime claims assistance.

**GitHub-first engineering mode (owner direction, 2026-10-18):**
Proceed in the repository with small reviewed PRs for the provider-neutral
local AI adapter, strictly synthetic/mock tests, source attribution,
fail-closed security, model/prompt/version custody and human-review
validation. Do not block ordinary GitHub engineering progress on new
interactive PowerShell exercises; reserve the owner's PC for later optional
acceptance tests. Never claim CI mocks constitute verified real local
model inference in the final release.

## Step 2 — controlled model and runtime selection

Select one or two suitably licensed, locally served small models **after**
hardware inspection. Prefer a simple loopback-only inference runtime
and preserve the provider-neutral AI gateway; model, quantization, model
hash, context length, source of download and license must be recorded.
Keep `ai_provider=disabled` in current deployable configurations until a
separate approved local adapter, fail-closed controls and test evidence
exist. Do not bind an unauthenticated model service to a public interface.

## Step 3 — H&M machinery synthetic smoke and measurement

Start with an invented machinery claim, such as an engine/turbocharger
failure, using **synthetic** Chief Engineer, engine-log and survey text.
Compare one local-LLM extraction against deterministic no-model logic.
Record:

1. setup and download sizes, RAM/VRAM consumption and processing time;
2. exact source excerpt/page/reference support for proposed findings;
3. missing and contradictory records, explicit abstention where unknown;
4. no claims, financial decisions or approval fields mutated by the LLM;
5. failures/timeouts, no outbound prompt/evidence egress and human review.

**Exit for this development-host choice:** supported hardware inventory,
chosen local inference runtime, model/version/license, repeatable synthetic
demo results and measured limits. This is **not** R5 acceptance or
permission for a 30-day customer pilot.

## Next engineering action

Continue **on GitHub** with a bounded implementation and regression PR.
Keep `ai_provider=disabled` and external inference OFF until real
operator-controlled runtime acceptance; no confidential customer data,
source-unverified conclusions, or autonomous coverage/liability decisions.
