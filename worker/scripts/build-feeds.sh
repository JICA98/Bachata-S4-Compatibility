#!/usr/bin/env bash
set -euo pipefail

worker_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
compat_root="$(cd -- "$worker_root/.." && pwd)"
generated_root="$compat_root/generated"
public_feed="$worker_root/public/data/compat/v2"

python3 "$compat_root/scripts/build_site_data.py" \
  --root "$compat_root" \
  --output "$generated_root"
python3 "$compat_root/scripts/build_app_data.py" \
  --root "$compat_root" \
  --output "$generated_root/app-v2"
python3 "$compat_root/scripts/apply_tombstones.py" \
  --root "$compat_root" \
  --site-output "$generated_root" \
  --app-output "$generated_root/app-v2"

rm -rf -- "$public_feed"
mkdir -p -- "$public_feed"
cp -R -- "$generated_root/app-v2/." "$public_feed/"
