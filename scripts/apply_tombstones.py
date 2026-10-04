#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json, write_json


def load_tombstones(root: Path) -> tuple[set[str], list[dict]]:
    path = root / "data/tombstones.json"
    data = load_json(path)
    if data.get("schemaVersion") != 1 or not isinstance(data.get("tombstones"), list):
        raise SystemExit(f"{path}: invalid tombstone registry")
    ids: set[str] = set()
    entries: list[dict] = []
    for index, item in enumerate(data["tombstones"]):
        if not isinstance(item, dict):
            raise SystemExit(f"{path}: tombstones[{index}] must be an object")
        report_id = str(item.get("reportId") or "")
        reason = str(item.get("reason") or "")
        removed_at = str(item.get("removedAt") or "")
        if not report_id or not reason or not removed_at:
            raise SystemExit(f"{path}: tombstones[{index}] missing required fields")
        if report_id in ids:
            raise SystemExit(f"{path}: duplicate tombstone for {report_id}")
        ids.add(report_id)
        entries.append(item)
    return ids, entries


def prune_site(output: Path, ids: set[str]) -> None:
    index_path = output / "site-index.json"
    if index_path.is_file():
        index = load_json(index_path)
        for game in index.get("games", []):
            reports = game.get("reports") or []
            game["reports"] = [r for r in reports if r.get("reportId") not in ids]
            game["reportCount"] = len(game["reports"])
        write_json(index_path, index)

    games_dir = output / "games"
    if games_dir.is_dir():
        for path in games_dir.glob("CUSA*.json"):
            data = load_json(path)
            if isinstance(data.get("reports"), list):
                data["reports"] = [r for r in data["reports"] if r.get("reportId") not in ids]
                write_json(path, data)


def prune_app(output: Path, ids: set[str]) -> None:
    games_dir = output / "games"
    if not games_dir.is_dir():
        return
    for path in games_dir.glob("CUSA*.json"):
        data = load_json(path)
        reports = data.get("reports")
        if isinstance(reports, list):
            data["reports"] = [r for r in reports if r.get("reportId") not in ids]
            # Aggregates are built before pruning and therefore may include a removed report.
            # Fail closed: mark aggregates that cannot be trusted after a removal as unavailable.
            if len(data["reports"]) != len(reports):
                data["general"] = {
                    "score": None,
                    "status": "unknown",
                    "confidence": "none",
                    "reportCount": 0,
                    "testerCount": 0,
                    "deviceCount": 0,
                    "hasCurrentReports": False,
                    "tombstoneRebuildRequired": True,
                }
                data["socs"] = {}
            write_json(path, data)


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove legally/privacy withdrawn reports from generated compatibility feeds")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--site-output", type=Path, default=Path("generated"))
    parser.add_argument("--app-output", type=Path, default=Path("generated/app-v2"))
    args = parser.parse_args()
    root = args.root.resolve()
    ids, _ = load_tombstones(root)
    site = args.site_output if args.site_output.is_absolute() else root / args.site_output
    app = args.app_output if args.app_output.is_absolute() else root / args.app_output
    prune_site(site.resolve(), ids)
    prune_app(app.resolve(), ids)
    print(f"Applied {len(ids)} compatibility tombstone(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
