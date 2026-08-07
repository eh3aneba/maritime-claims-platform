#!/usr/bin/env sh
set -eu

python3 -m compileall apps/api/app
python3 -m json.tool apps/web/package.json >/dev/null

echo "Starter repository static checks passed."
