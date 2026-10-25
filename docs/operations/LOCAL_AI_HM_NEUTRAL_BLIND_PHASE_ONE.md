# #752 — neutral phase-one source packet for independent H&M reference review

**Purpose:** reduce answer priming before an independent machinery-claims
specialist creates reference judgments. The existing source-only packet
includes meaningful scenario names and issue-specific evaluation criteria;
those are useful *after* independent coding but risk telegraphing what
the software is looking for to a reviewer. This narrower Phase 1 view
uses three neutral labels (`CASE-01` through `CASE-03`) and the nine
fixed **invented** source documents, plus the **same four general open
questions** for every case. It includes NO code-authored source quote
baseline, expected outcome, scenario name, model output, performance
counter, critical anchor, or targeted context-pair criterion.

## On a workstation with the SeeClaims repository

From the repository root:

```powershell
& .\.venv-local-ai\Scripts\python.exe -m scripts.pilot_local_ai_hm_neutral_blind_packet --print-neutral-blind-synthetic-hm-phase-one
```

The one exact opt-in flag is mandatory. The code uses only installed
Python standard library and existing code-owned sources. It does not
invoke Ollama, read uploaded customer Evidence, accept arbitrary input,
write files, contact external APIs or record professional judgments.
The printed JSON **does include invented source text**. It is safe for
this development-only synthetic evaluation, NOT for actual customer files.

## Separation-of-information protocol

1. Appoint a competent independent H&M machinery reviewer and disclose
   conflicts of interest privately; assign **only this neutral Phase 1
   packet**, not the repository, previous success metrics or model
   candidate outputs. `CASE-01` etc. are deliberately neutral and
   are not a judgment about case content. Do not show the keyed
   source-only checklist, scenario titles, critical anchors, baseline
   exact-match results or these operator experiments to the reviewer
   before their initial independent reference is frozen.
2. Ask the reviewer to cite each provided `S1`/`S2`/`S3` with its
   version; distinguish a claim reported by a source from a fact that
   is independently corroborated, note unresolved conflicts and gaps,
   and identify any conclusions not justified by the source packet.
   The packet's prompts are **generic**, not reference answers.
3. Capture the dated expert coding, reviewer independence, conflicts,
   disagreement adjudication and source-packet observed SHA in a
   separately **approved access-controlled human-review system**.
   Neither the CLI nor GitHub records labels, signatures or identities.
   Reconcile `CASE-01` etc. to scenario-specific criteria **only after**
   independent coding is finalized. The project cannot truthfully claim
   `reviewer_blindness_verified=true` without evidence outside GitHub.
4. Later, authorized project reviewers can compare fixed synthetic
   model quotations and baseline output with the frozen independent
   labels; do NOT treat text-substring success, context co-location,
   tag consistency or this packet's hash as expert H&M approval.

The SHA-256 is computed over the printed neutral cases and generic
questions to help detect accidental source drift across copies; it is
**not a signature or independent attestation**. The response always
marks expert labels, review completion, reviewer blindness, digest
attestation and pilot acceptance FALSE. A successful CLI run only
creates an **unfilled review preparation packet**.

Offline tests:

```bash
python -m unittest scripts.tests.test_pilot_local_ai_hm_neutral_blind_packet -v
```

**Pilot GO=NO.** Do not use insurer/customer evidence, infer coverage,
causation, reserve, settlement, or authorize external inference.
