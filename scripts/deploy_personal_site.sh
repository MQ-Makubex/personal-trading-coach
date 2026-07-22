#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BUNDLE=${BUNDLE:-/private/tmp/personal-trading-coach-deploy}
PROJECT=${CLOUDFLARE_PAGES_PROJECT:-makubex-trading-coach}

cd "$ROOT"
python3 scripts/prepare_cloudflare_deploy.py --output "$BUNDLE"
npx --yes wrangler@4.111.0 pages deploy "$BUNDLE" \
  --project-name "$PROJECT" \
  --branch main \
  --commit-dirty=true
