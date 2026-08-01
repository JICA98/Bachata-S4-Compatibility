#!/usr/bin/env bash
set -euo pipefail
BASE_REF="${1:-origin/main}"
git fetch origin main --depth=1 >/dev/null 2>&1 || true
violations="$(git diff --name-status "$BASE_REF"...HEAD -- 'games/*/reports/*.json' 'assets/**' | awk '$1 != "A" {print}')"
if [[ -n "$violations" ]]; then
  echo "Existing reports and evidence are immutable. Add a superseding report instead:" >&2
  echo "$violations" >&2
  exit 1
fi
