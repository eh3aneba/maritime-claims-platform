# ADR-025 — Design-partner demo data is deterministic and synthetic

## Status
Accepted

## Context
External AI calls and real claim evidence introduce privacy, cost and reproducibility risks during product demonstrations.

## Decision
The MT ORION design-partner seed uses the same synthetic source documents and deterministic structured AI fixture payloads as the regression pilot. The seed runs with external AI disabled, is idempotent, and labels the claim with `MCRI-DEMO-MT-ORION`.

## Consequences
- Product walkthroughs are reproducible without sending evidence to an external model provider.
- Demo output can be compared against regression expectations.
- Synthetic demo behavior must never be represented as live model accuracy or real claim data.
