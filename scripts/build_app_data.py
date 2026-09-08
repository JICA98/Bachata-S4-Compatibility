#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from common import load_json, write_json
from scoring import aggregate, group_by_soc, latest_release_tag, native_fps_summary, soc_id


def load_soc_registry(root: Path) -> tuple[dict, dict[str, str]]:
    data = load_json(root / "data/socs.json")
    socs = data.get("socs", {})
    aliases: dict[str, str] = {}
    for key, value in socs.items():
        aliases[key.casefold()] = key
        aliases[str(value.get("name", "")).casefold()] = key
        for alias in value.get("aliases", []):
            aliases[str(alias).casefold()] = key
    return socs, aliases


def canonical_soc(report: dict, aliases: dict[str, str]) -> str:
    raw = soc_id(report)
    return aliases.get(raw.casefold(), raw.casefold().replace(" ", "-"))


def safe_report(report: dict, aliases: dict[str, str]) -> dict:
    device = report.get("device") or {}
    perf = report.get("performance") or {}
    config = report.get("config") or {}
    native_average = perf.get("nativeAverageFps")
    native_low = perf.get("nativeOnePercentLowFps")
    output_average = perf.get("outputAverageFps")
    if report.get("schemaVersion") == 1:
        native_average = perf.get("averageFps")
        config = {
            "requiredOverrides": {"graphics.resolutionScale": (report.get("settings") or {}).get("resolutionScale")}
            if (report.get("settings") or {}).get("resolutionScale") is not None else {},
            "guestBackend": str(report.get("guestBackend") or "fex").upper(),
            "frameGenerationMode": "OFF",
            "fexPreset": "DEFAULT",
        }
    result = report.get("result") or {}
    summary = result.get("summary") or report.get("summary") or ""
    notes = result.get("notes") if "notes" in result else report.get("notes", "")
    issues = result.get("issues") if "issues" in result else report.get("issues", [])
    contributor = report.get("contributor") or {}
    return {
        "reportId": report.get("reportId"),
        "schemaVersion": report.get("schemaVersion", 1),
        "testedAt": report.get("testedAt"),
        "status": report.get("status"),
        "release": {
            "tag": (report.get("release") or {}).get("tag", ""),
            "commit": (report.get("release") or {}).get("commit", ""),
        },
        "gameVersion": (report.get("game") or {}).get("version") or report.get("gameVersion", ""),
        "device": {
            "manufacturer": device.get("manufacturer", ""),
            "model": device.get("model", ""),
            "socId": canonical_soc(report, aliases),
            "socName": device.get("socName") or device.get("soc", ""),
            "gpu": device.get("gpu", ""),
            "androidVersion": device.get("androidVersion", ""),
            "ramBucketGb": device.get("ramBucketGb") or (round(float(device["ramGb"])) if device.get("ramGb") else None),
        },
        "driver": {k: v for k, v in (report.get("driver") or {}).items() if k in {"id", "type", "kind", "name", "version", "build"}},
        "config": {
            "requiredOverrides": {k: v for k, v in (config.get("requiredOverrides") or config.get("settings") or {}).items() if v is not None},
            "driverId": config.get("driverId"),
            "guestBackend": config.get("guestBackend", "FEX"),
            "frameGenerationMode": config.get("frameGenerationMode", "OFF"),
            "fexPreset": config.get("fexPreset", "DEFAULT"),
            "adrenoTurboMode": config.get("adrenoTurboMode"),
            "bigCoreAffinity": config.get("bigCoreAffinity"),
            "maliGpuOptimizations": config.get("maliGpuOptimizations"),
        },
        "patches": report.get("patches", []),
        "performance": {
            "nativeAverageFps": native_average,
            "nativeOnePercentLowFps": native_low,
            "outputAverageFps": output_average,
            "testDurationSeconds": perf.get("testDurationSeconds"),
            "framePacing": perf.get("framePacing", "unknown"),
        },
        "result": {"summary": summary, "notes": notes or "", "issues": issues or []},
        "contributor": {
            "publicId": contributor.get("publicId") or report.get("tester") or "legacy",
            "displayName": contributor.get("displayName"),
        },
        "provenance": report.get("provenance") or {"captureType": "legacy-imported" if report.get("legacyImported") else "structured-manual"},
    }


def build(root: Path, output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    (output / "games").mkdir(parents=True)
    release_index = load_json(root / "data/releases.json")
    current_release = latest_release_tag(release_index)
    socs, aliases = load_soc_registry(root)
    games_index = []

    for game_path in sorted((root / "games").glob("CUSA*/game.json")):
        game = load_json(game_path)
        raw_reports = [load_json(path) for path in sorted((game_path.parent / "reports").glob("*.json"))]
        reports = [safe_report(r, aliases) for r in raw_reports if not r.get("withdrawn")]
        # Scoring operates on canonicalized safe reports to guarantee exact-SoC joins.
        general = aggregate(reports, current_release)
        general["performance"] = native_fps_summary(reports, current_release)
        by_soc = group_by_soc(reports, current_release)
        used_families = {}
        for key in by_soc:
            registry = socs.get(key, {})
            family = registry.get("family")
            if family:
                used_families.setdefault(family, []).append(key)
        payload = {
            "schemaVersion": 2,
            "generatedForRelease": current_release,
            "game": {
                "cusaId": game["cusaId"],
                "title": game.get("title", ""),
                "region": game.get("region", ""),
                "publisher": game.get("publisher", ""),
            },
            "general": general,
            "socs": by_soc,
            "families": used_families,
            "reports": sorted(reports, key=lambda r: r.get("testedAt") or "", reverse=True),
        }
        write_json(output / "games" / f"{game['cusaId']}.json", payload)
        games_index.append({
            "cusaId": game["cusaId"],
            "title": game.get("title", ""),
            "general": general,
            "reportCount": len(reports),
            "socCount": len(by_soc),
        })

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    write_json(output / "index.json", {
        "schemaVersion": 2,
        "generatedAt": now,
        "currentRelease": current_release,
        "gameCount": len(games_index),
        "games": games_index,
    })
    write_json(output / "socs.json", {"schemaVersion": 1, "socs": socs})
    print(f"Generated Android compatibility feed for {len(games_index)} game(s), release {current_release or 'unknown'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Bachata S4 Android compatibility v2 feed")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("generated/app-v2"))
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else args.root / args.output
    build(args.root.resolve(), output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
