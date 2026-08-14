# Supply-Chain Security and SBOM

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
- Gitleaks scans the complete Git history for committed credentials, API keys
  and tokens. Finding comments, summaries and SARIF uploads are disabled so
  suspected secret material is not copied into PR comments or artifacts.
- Grype scans the final API and web production images. High and critical
  operating-system or application-package vulnerabilities fail the workflow.

The dependency and image scanners process repository or image metadata on the
ephemeral GitHub runner. They do not connect to the application database,
local evidence volume or external AI provider. The secret scanner reads Git
history but does not upload a finding artifact.

## Handling findings

Do not weaken or bypass the security job to merge a change. Prefer upgrading the
affected direct dependency and regenerating its committed lockfile. For image
findings, update the affected runtime package or base image and rebuild.

If a real secret is detected, rotate or revoke it immediately before removing
it from code. Deleting the latest copy does not invalidate a credential already
present in Git history.

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

Production images:

```bash
docker build --tag maritime-claims-api:local apps/api
docker build --tag maritime-claims-web:local apps/web
```

Secret-history and image vulnerability scans are authoritative in GitHub
Actions because their scanner binaries and vulnerability databases are pinned
or downloaded by the workflow.

The CI-generated SBOM is available from the completed workflow run under
**Artifacts → maritime-claims-platform-sbom**.
