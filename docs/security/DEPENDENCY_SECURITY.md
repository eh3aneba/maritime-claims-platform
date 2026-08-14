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
2. why the finding is a false positive or why the vulnerable code path is not
   exploitable in this deployment;
3. the accountable owner;
4. an expiry date and remediation issue.

## Active scanner exception

| Finding | Exact scope | Justification | Owner | Expires | Tracking |
| --- | --- | --- | --- | --- | --- |
| `CVE-2026-15308` | `python` `3.13.15` (`binary`) | The PSF-supplied ranges published by NVD mark Python 3.13 versions earlier than 3.13.15 as affected, while the current Grype database reports 3.13.15. The rule is a scanner-metadata exception, not accepted product risk. | `@eh3aneba` | 2026-09-14 | [Issue #21](https://github.com/eh3aneba/maritime-claims-platform/issues/21) |

The corresponding `.grype.yaml` rule matches the CVE, package name, installed
version and package type. It does not suppress any other vulnerability. The
exception must be removed as soon as the scanner database reflects the official
affected range, and no later than the expiry date.

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
