# Dependency Security and SBOM

The repository runs an independent supply-chain workflow for every pull request
to `main`, every push to `main`, every Monday at 07:00 Asia/Baku, and on
manual dispatch.

## Enforced checks

- Python production dependencies are audited from
  `apps/api/requirements.lock` with `pip-audit`. Any known vulnerability
  fails the workflow.
- Web production dependencies are audited from
  `apps/web/package-lock.json` with `npm audit`. High and critical findings
  fail the workflow.
- Syft creates an SPDX JSON Software Bill of Materials (SBOM) from the
  repository dependency manifests. GitHub Actions retains the SBOM artifact for
  seven days.

The audit and SBOM tools process dependency metadata only. They do not receive
claim evidence, pilot documents, credentials, or runtime database content.

## Handling findings

Do not weaken or bypass the security job to merge a change. Prefer upgrading the
affected direct dependency and regenerating its committed lockfile.

A temporary exception is allowed only in a dedicated pull request that records:

1. the vulnerability identifier and affected package;
2. why the vulnerable code path is not exploitable in this deployment;
3. the accountable owner;
4. an expiry date and remediation issue.

No temporary exceptions are configured by default.

## Local commands

Python production lock:

```bash
pipx run pip-audit \
  --require-hashes \
  -r apps/api/requirements.lock
```

Web production dependencies:

```bash
npm audit --omit=dev --audit-level=high --prefix apps/web
```

The CI-generated SBOM is available from the completed workflow run under
**Artifacts → maritime-claims-platform-sbom**.
