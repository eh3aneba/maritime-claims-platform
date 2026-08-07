# Chronology & Evidence Conflicts — Sprint 3 Phase E

## Purpose

The chronology layer converts **human-reviewed evidence** into a claim timeline. It does not consume pending AI candidates and it does not adjudicate which source is true.

## Data flow

Reviewed CE Report / Engine Log extractions → deterministic event candidates → event clustering → chronology events → deterministic conflict rules → human resolution.

## Event clustering

- Only events with the same deterministic `event_type` are eligible to cluster.
- Events on the same date within **10 minutes** may cluster.
- Engine Log evidence has higher timestamp priority than narrative CE Report evidence inside a cluster.
- Source evidence remains linked individually; clustering never destroys the underlying reviewed extractions.

## Initial conflict thresholds

- `<= 10 minutes`: cluster / no material time conflict.
- `> 10 and <= 30 minutes`: Medium review conflict.
- `> 30 minutes`: High material conflict.
- Different dates for an event type treated as a single casualty event: Critical conflict.

These are configurable domain rules, not factual findings.

## Content conflicts

Phase E includes deterministic contradictions for selected operational facts, initially:

- CE Report `engine_stopped = false` vs reviewed Engine Log shutdown evidence.
- CE Report `load_reduced = false` vs reviewed Engine Log load-reduction evidence.

## Human resolution

Open conflicts can be marked `explained`, `resolved`, `accepted_difference`, or `irrelevant`. A note is required. Resolution changes are audited and are preserved across idempotent rebuilds when the evidence signature remains unchanged.

## Safety boundary

The rules engine never labels Source A or Source B as correct. It only identifies a discrepancy and supplies the evidence trail for human review.
