# MT ORION Synthetic End-to-End Pilot

This folder contains a synthetic H&M machinery-damage pilot used to exercise the MCRI MVP end to end without using customer data or an external AI provider.

## Scenario

- Vessel: MT ORION (fictional)
- IMO: 7000301 (synthetic fixture value)
- Incident: 10 July 2026
- Claim: Main Engine Turbocharger No.2 failure
- Initial estimate: USD 550,000
- Pilot reserve: USD 575,000

All documents are clearly marked or intended as **synthetic pilot fixtures**. They must not be treated as a real claim file.

## Evidence pack

1. `01_claim_notification.docx`
2. `02_chief_engineer_report.docx`
3. `03_engine_log.xlsx`
4. `04_running_hours.xlsx`
5. `05_pms_history.xlsx`
6. `06_workshop_report.docx`
7. `07_quotation_A.xlsx`
8. `08_quotation_B.xlsx`
9. `09_invoice.xlsx`

The pilot intentionally omits the H&M policy and the previous overhaul report so the Missing Document / Readiness workflow can be tested.

## Run

From the repository root:

```bash
make pilot-mt-orion
```

or:

```bash
cd apps/api
pytest -q tests/test_mt_orion_end_to_end_pilot.py
```

The test uses deterministic fixture AI responses. No evidence is sent to an external AI provider.

## What is exercised

Claim creation -> evidence upload -> DOCX/XLSX text extraction -> structured AI schemas -> human review -> approved claim facts -> deterministic rules -> missing-document request tasks -> chronology/conflicts -> technical review -> financial review -> reserve history -> preliminary initial assessment.

See `PILOT_REPORT.md` for the original observed results, `HARDENING_REPORT.md` for the Sprint 5 Phase B P0 closure regression, and `USABILITY_REPORT.md` for the Sprint 5 Phase C Claim Handler workflow hardening.
