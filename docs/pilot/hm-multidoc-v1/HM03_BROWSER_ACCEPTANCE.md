# HM-03 attributed-alarm source intake — test boundaries

The disposable browser test `tests/browser/hm_multidoc_conflicting_alarm_e2e.py` uses four invented DOCX files. An engineer statement cites 11:30 UTC, and an independent workshop statement cites 11:55 UTC. Neither clock has been independently verified.

The test uploads and processes all four files, redownloads both alarm statements, verifies their SHA-256 and exact line contents, and generates only a preliminary source-linked assessment. It checks that no unreviewed Claim Fact or automatically reconciled chronology was created.

This is **not** proof that the software detects a semantic contradiction or that a qualified claims handler compared original records. Real-case permission and independent H&M review remain absent. Machine-only timing and explicit non-acceptance fields are recorded in the CI artifact. Pilot remains NO-GO.
