#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from common import write_json

API = "https://api.github.com/repos/JICA98/Bachata-S4/releases?per_page=100"

def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize published Bachata S4 releases")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/releases.json")
    args = parser.parse_args()
    headers = {"Accept":"application/vnd.github+json","User-Agent":"bachata-compatibility-sync","X-GitHub-Api-Version":"2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token: headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response: releases = json.load(response)
    active = [entry for entry in releases if not entry.get("draft")]
    latest_stable = next((entry["tag_name"] for entry in active if not entry.get("prerelease")), None)
    value = {"schemaVersion":1,"generatedAt":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),"repository":"JICA98/Bachata-S4","releases":[]}
    for entry in active:
        value["releases"].append({"tag":entry["tag_name"],"name":entry.get("name") or entry["tag_name"],"url":entry["html_url"],"publishedAt":entry.get("published_at"),"prerelease":bool(entry.get("prerelease")),"latest":entry["tag_name"]==latest_stable})
    write_json(args.output, value)
    print(f"Wrote {len(active)} releases to {args.output}")
    return 0
if __name__ == '__main__': raise SystemExit(main())
