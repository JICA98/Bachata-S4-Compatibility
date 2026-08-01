#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from common import RAW_BASE, STATUS_ORDER, display_driver, load_json, write_json
from validate import validate


def screenshot_url(path: str) -> str:
    return f"evidence/{path}"


def log_url(item: dict) -> str:
    return str(item.get("externalUrl") or f"{RAW_BASE}{item['path']}")


def transform_report(report: dict) -> dict:
    value = copy.deepcopy(report)
    evidence = value.setdefault("evidence", {})
    evidence["screenshots"] = [
        {**item, "url": screenshot_url(item["path"])} for item in evidence.get("screenshots", [])
    ]
    evidence["logs"] = [
        {**item, "url": log_url(item)} for item in evidence.get("logs", [])
    ]
    return value


def report_summary(report: dict) -> dict:
    screenshots = report.get("evidence", {}).get("screenshots", [])
    driver = report.get("driver", {})
    performance = report.get("performance", {})
    return {
        "reportId": report["reportId"],
        "status": report["status"],
        "testedAt": report["testedAt"],
        "gameVersion": report.get("gameVersion", ""),
        "releaseTag": report["release"]["tag"],
        "releaseCommit": report["release"]["commit"],
        "summary": report.get("summary", ""),
        "device": {
            "label": report["device"].get("label", "Unknown device"),
            "soc": report["device"].get("soc", ""),
            "gpu": report["device"].get("gpu", ""),
            "androidVersion": report["device"].get("androidVersion", "")
        },
        "driver": {**driver, "display": display_driver(driver)},
        "performance": {"averageFps": performance.get("averageFps")},
        "thumbnail": screenshot_url(screenshots[-1]["path"]) if screenshots else "assets/placeholder.svg"
    }


def build(root: Path, output: Path) -> None:
    errors = validate(root)
    if errors:
        raise SystemExit("Validation failed before build:\n- " + "\n- ".join(errors))
    if output.exists(): shutil.rmtree(output)
    (output / "games").mkdir(parents=True)
    release_data = load_json(root / "data/releases.json")
    write_json(output / "releases.json", release_data)

    games_index = []
    status_counts = Counter()
    all_devices = set()
    all_reports = 0
    for game_path in sorted((root / "games").glob("CUSA*/game.json")):
        game = load_json(game_path)
        reports = [load_json(path) for path in sorted((game_path.parent / "reports").glob("*.json"))]
        reports.sort(key=lambda item: item["testedAt"], reverse=True)
        transformed = [transform_report(report) for report in reports]
        write_json(output / "games" / f"{game['cusaId']}.json", {"schemaVersion": 1, "game": game, "reports": transformed})
        summaries = [report_summary(report) for report in reports]
        best = min(reports, key=lambda item: STATUS_ORDER[item["status"]]) if reports else None
        latest = reports[0] if reports else None
        devices = {report["device"]["label"] for report in reports}
        all_devices.update(devices)
        all_reports += len(reports)
        if best: status_counts[best["status"]] += 1
        games_index.append({
            **game,
            "issueUrl": f"https://github.com/JICA98/Bachata-S4-Compatibility/issues/{game['issueNumber']}" if game.get("issueNumber") else "",
            "reportCount": len(reports),
            "deviceCount": len(devices),
            "bestStatus": best["status"] if best else "unknown",
            "latestStatus": latest["status"] if latest else "unknown",
            "latestTestedAt": latest["testedAt"] if latest else "",
            "latestRelease": latest["release"]["tag"] if latest else "",
            "thumbnail": summaries[0]["thumbnail"] if summaries else "assets/placeholder.svg",
            "reports": summaries
        })
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    index = {
        "schemaVersion": 3,
        "generatedAt": now,
        "project": {
            "name": "Bachata S4",
            "repository": "https://github.com/JICA98/Bachata-S4",
            "dataRepository": "https://github.com/JICA98/Bachata-S4-Compatibility",
            "platform": "Android"
        },
        "stats": {
            "games": len(games_index), "reports": all_reports, "devices": len(all_devices),
            "playable": status_counts["playable"], "ingame": status_counts["ingame"]
        },
        "games": games_index
    }
    write_json(output / "site-index.json", index)
    print(f"Generated site data for {len(games_index)} game(s), {all_reports} report(s) in {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact and per-game website JSON")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("generated"))
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else args.root / args.output
    build(args.root.resolve(), output.resolve())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
