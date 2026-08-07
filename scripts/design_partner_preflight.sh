#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Copy .env.pilot.example to .env and replace every REPLACE_WITH_* value." >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is not installed or not on PATH." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose v2 is required." >&2
  exit 1
fi
if grep -q 'REPLACE_WITH_' "$ENV_FILE"; then
  echo "ERROR: $ENV_FILE still contains REPLACE_WITH_* placeholders." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${MCRI_DEMO_PASSWORD:?MCRI_DEMO_PASSWORD must be set in $ENV_FILE}"
if [[ ${#MCRI_DEMO_PASSWORD} -lt 12 ]]; then
  echo "ERROR: MCRI_DEMO_PASSWORD must be at least 12 characters." >&2
  exit 1
fi

echo "[1/6] Validating compose configuration..."
docker compose --env-file "$ENV_FILE" config >/dev/null

echo "[2/6] Building and starting database/API/worker/web..."
docker compose --env-file "$ENV_FILE" up -d --build

echo "[3/6] Running application preflight inside the API image..."
docker compose --env-file "$ENV_FILE" exec -T api python -m app.core.preflight

echo "[4/6] Seeding the deterministic MT ORION demo..."
docker compose --env-file "$ENV_FILE" --profile demo run --rm demo-seed

echo "[5/6] Checking service health..."
docker compose --env-file "$ENV_FILE" ps
python - <<'PY'
import urllib.request
for url in ("http://127.0.0.1:8000/api/v1/health", "http://127.0.0.1:3000/login"):
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status >= 400:
            raise SystemExit(f"Health check failed: {url} -> {response.status}")
        print(f"OK {response.status}: {url}")
PY

echo "[6/6] Verifying demo authentication and MT ORION API visibility..."
python - <<'PY'
import http.cookiejar
import json
import os
import urllib.parse
import urllib.request

base = os.getenv("NEXT_PUBLIC_API_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
org = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
email = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
password = os.environ["MCRI_DEMO_PASSWORD"]
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
request = urllib.request.Request(
    base + "/auth/login",
    data=json.dumps({"organization_slug": org, "email": email, "password": password}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with opener.open(request, timeout=10) as response:
    if response.status != 200:
        raise SystemExit(f"Demo login failed: HTTP {response.status}")
query = urllib.parse.urlencode({"search": "MCRI-DEMO-MT-ORION"})
with opener.open(base + "/claims?" + query, timeout=10) as response:
    payload = json.load(response)
    if payload.get("total") != 1 or payload["items"][0].get("external_reference") != "MCRI-DEMO-MT-ORION":
        raise SystemExit("MT ORION demo claim was not visible after login")
print("Demo login and MT ORION API smoke passed.")
PY

echo "Design-partner preflight passed. Next: run tests/browser/design_partner_e2e.py."
