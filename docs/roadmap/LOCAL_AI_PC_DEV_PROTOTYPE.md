# SeeClaims — local AI first development host (owner decision)

**Decision status:** Owner-approved *development environment* preference.
**Pilot AI runtime and model:** NOT SELECTED / NOT OPERATIONALLY ACCEPTED.

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

The host's exact hardware is **not yet known**. Before selecting or
downloading an LLM, obtain the following owner-supplied information:

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

## Next owner input

Request CPU model, installed RAM (GB), GPU model plus dedicated VRAM
(GB), and operating system. Proceed with model sizing only after receipt.
