#!/usr/bin/env python3
"""Move the two legacy Sonic Mania logs from Bachata-S4 into this data repository."""
from __future__ import annotations

import argparse
import base64
import json
import urllib.request
from pathlib import Path

from common import load_json, sha256, write_json

ROOT = Path(__file__).resolve().parents[1]
REPORT_ID = "20260731T181457Z-v0.1.6-oneplus13-turnip-26.3.0"
REPORT_PATH = ROOT / "games/CUSA07023/reports" / f"{REPORT_ID}.json"
API_PREFIX = "https://api.github.com/repos/JICA98/Bachata-S4/contents/"
FILES = [
    (
        "compatibility-site/assets/logs/cusa07023/20260731-181457-01-application.log.gz",
        "01-application.log.gz",
        "bdc1e236aa6848722b42ed19b228ff9a8893b22558561e307c78ed3f8ea099af",
    ),
    (
        "compatibility-site/assets/logs/cusa07023/20260731-181457-02-shadps4.log.gz",
        "02-shadps4.log.gz",
        "0e235d3ac7dda106c0a1a8f1dc326e451a111dbf3c9350787d1b00761275d0eb",
    ),
]


def fetch(path: str) -> bytes:
    request = urllib.request.Request(
        f"{API_PREFIX}{path}?ref=main",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "bachata-compatibility-migration"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    return base64.b64decode(value["content"].replace("\n", ""))


def source_bytes(relative: str, main_root: Path | None) -> bytes:
    if main_root is not None:
        local = main_root / relative
        if local.is_file():
            return local.read_bytes()
    return fetch(relative)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-root", type=Path, help="Existing Bachata-S4 clone containing the legacy logs")
    args = parser.parse_args()
    main_root = args.main_root.expanduser().resolve() if args.main_root else None

    report = load_json(REPORT_PATH)
    destination_dir = ROOT / "assets/CUSA07023" / REPORT_ID / "logs"
    destination_dir.mkdir(parents=True, exist_ok=True)
    local_entries = []
    old_entries = report["evidence"]["logs"]
    for index, (source_path, filename, expected) in enumerate(FILES):
        destination = destination_dir / filename
        if not destination.exists():
            destination.write_bytes(source_bytes(source_path, main_root))
        actual = sha256(destination)
        if actual != expected:
            raise SystemExit(f"Hash mismatch for {destination}: expected {expected}, got {actual}")
        local_entries.append(
            {
                "path": destination.relative_to(ROOT).as_posix(),
                "label": old_entries[index]["label"],
                "sha256": expected,
            }
        )
    report["evidence"]["logs"] = local_entries
    write_json(REPORT_PATH, report)
    print("Migrated both legacy Sonic Mania logs and preserved their hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
