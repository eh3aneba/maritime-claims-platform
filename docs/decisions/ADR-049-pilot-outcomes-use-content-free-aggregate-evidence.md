# ADR-049 — Pilot outcomes use content-free aggregate evidence

Status: Accepted

A private-pilot execution may reference tenant-scoped claims, but its outcome model stores only bounded workflow durations, human AI-review counts, deterministic-rule usefulness counts, open-work counts and allowlisted evidence references. Aggregate metrics explicitly declare that content is not included.

A completed Go rehearsal is required, a Manager/Admin explicitly starts and completes the pilot, and Proceed is blocked while any P0 gap is unresolved. The canonical SHA-256 outcome freezes the metrics and accountable gap states. This keeps pilot learning measurable without copying claim narrative, document text, personal data or secrets into an operational analytics ledger.
