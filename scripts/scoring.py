#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

STATUS_SCORE = {"nothing": 0, "boots": 25, "menus": 45, "ingame": 75, "playable": 100}
STATUS_ORDER = ["nothing", "boots", "menus", "ingame", "playable"]
CAPTURE_WEIGHT = {
    "maintainer-verified": 1.0,
    "app-captured": 1.0,
    "structured-manual": 0.85,
    "legacy-imported": 0.65,
}


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def latest_release_tag(release_index: dict) -> str:
    releases = [r for r in release_index.get("releases", []) if not r.get("prerelease") and not r.get("archived")]
    explicit = next((r for r in releases if r.get("latest")), None)
    if explicit:
        return str(explicit["tag"])
    if not releases:
        return ""
    return str(max(releases, key=lambda r: r.get("publishedAt", ""))["tag"])


def previous_release_tag(release_index: dict, current: str) -> str:
    releases = [r for r in release_index.get("releases", []) if not r.get("prerelease") and not r.get("archived")]
    ordered = sorted(releases, key=lambda r: r.get("publishedAt", ""), reverse=True)
    tags = [str(r.get("tag", "")) for r in ordered]
    try:
        idx = tags.index(current)
    except ValueError:
        return ""
    return tags[idx + 1] if idx + 1 < len(tags) else ""


def contributor_id(report: dict) -> str:
    contributor = report.get("contributor") or {}
    return str(contributor.get("publicId") or report.get("tester") or "anonymous")


def device_key(report: dict) -> str:
    device = report.get("device") or {}
    return "|".join([
        str(device.get("manufacturer", "")).casefold(),
        str(device.get("model", "")).casefold(),
        str(device.get("socId") or device.get("soc") or "").casefold(),
    ])


def release_tag(report: dict) -> str:
    return str((report.get("release") or {}).get("tag") or "")


def soc_id(report: dict) -> str:
    device = report.get("device") or {}
    return str(device.get("socId") or device.get("soc") or "unknown").casefold()


def dedupe_reports(reports: Iterable[dict]) -> list[dict]:
    """Count only the newest report per contributor/device/release combination."""
    newest: dict[tuple[str, str, str], dict] = {}
    for report in reports:
        if report.get("withdrawn"):
            continue
        key = (contributor_id(report), device_key(report), release_tag(report))
        old = newest.get(key)
        if old is None or _parse_time(str(report.get("testedAt", "1970-01-01T00:00:00Z"))) > _parse_time(str(old.get("testedAt", "1970-01-01T00:00:00Z"))):
            newest[key] = report
    return list(newest.values())


def capture_weight(report: dict) -> float:
    if report.get("schemaVersion") == 1:
        return CAPTURE_WEIGHT["legacy-imported"] if report.get("legacyImported") else CAPTURE_WEIGHT["structured-manual"]
    provenance = report.get("provenance") or {}
    return CAPTURE_WEIGHT.get(str(provenance.get("captureType") or "structured-manual"), 0.75)


def score_to_status(score: float) -> str:
    if score >= 87.5:
        return "playable"
    if score >= 60:
        return "ingame"
    if score >= 35:
        return "menus"
    if score >= 12.5:
        return "boots"
    return "nothing"


def confidence(reports: list[dict]) -> str:
    testers = {contributor_id(r) for r in reports}
    devices = {device_key(r) for r in reports}
    if len(reports) >= 5 and len(testers) >= 3 and len(devices) >= 2:
        scores = [STATUS_SCORE.get(str(r.get("status")), 0) for r in reports]
        if max(scores, default=0) - min(scores, default=0) <= 45:
            return "high"
    if len(reports) >= 2 and len(testers) >= 2:
        return "medium"
    return "low"


def aggregate(reports: Iterable[dict], current_release: str, exact_soc: str | None = None) -> dict:
    reports = dedupe_reports(reports)
    if exact_soc:
        reports = [r for r in reports if soc_id(r) == exact_soc.casefold()]
    current = [r for r in reports if release_tag(r) == current_release]
    if not current:
        return {
            "score": None,
            "status": "unknown",
            "confidence": "none",
            "reportCount": 0,
            "testerCount": 0,
            "deviceCount": 0,
            "releaseTag": current_release,
            "hasCurrentReports": False,
        }
    weighted = [(STATUS_SCORE[str(r["status"])], capture_weight(r)) for r in current]
    weight_sum = sum(w for _, w in weighted)
    score = round(sum(v * w for v, w in weighted) / weight_sum) if weight_sum else 0
    return {
        "score": score,
        "status": score_to_status(score),
        "confidence": confidence(current),
        "reportCount": len(current),
        "testerCount": len({contributor_id(r) for r in current}),
        "deviceCount": len({device_key(r) for r in current}),
        "releaseTag": current_release,
        "hasCurrentReports": True,
    }


def native_fps_summary(reports: Iterable[dict], current_release: str) -> dict:
    values: list[float] = []
    for report in dedupe_reports(reports):
        if release_tag(report) != current_release:
            continue
        perf = report.get("performance") or {}
        value = perf.get("nativeAverageFps")
        if value is None and report.get("schemaVersion") == 1:
            value = perf.get("averageFps")
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return {"min": None, "max": None, "average": None, "sampleCount": 0}
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "average": round(sum(values) / len(values), 2),
        "sampleCount": len(values),
    }


def recommended_setup(reports: Iterable[dict], current_release: str, exact_soc: str) -> dict | None:
    candidates = [
        r for r in dedupe_reports(reports)
        if release_tag(r) == current_release and soc_id(r) == exact_soc.casefold() and r.get("status") in {"ingame", "playable"}
    ]
    if not candidates:
        return None

    def fingerprint(report: dict) -> tuple:
        config = report.get("config") or {}
        overrides = config.get("requiredOverrides") or config.get("settings") or report.get("settings") or {}
        driver = report.get("driver") or {}
        patches = tuple(sorted((p.get("id"), p.get("preset")) for p in report.get("patches", []) if isinstance(p, dict)))
        return (
            str(driver.get("type", "")), str(driver.get("name", "")), str(driver.get("version", "")),
            tuple(sorted((str(k), str(v)) for k, v in overrides.items())), patches,
            str(config.get("frameGenerationMode", "OFF")), str(config.get("fexPreset", "DEFAULT")),
        )

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for report in candidates:
        groups[fingerprint(report)].append(report)
    best = max(groups.values(), key=lambda group: (len({contributor_id(r) for r in group}), len(group), max(_parse_time(r["testedAt"]) for r in group)))
    representative = max(best, key=lambda r: _parse_time(r["testedAt"]))
    config = representative.get("config") or {}
    return {
        "label": "community-recommended" if len({contributor_id(r) for r in best}) >= 2 and len(best) >= 3 else "known-working",
        "reportId": representative.get("reportId"),
        "supportingReports": len(best),
        "supportingTesters": len({contributor_id(r) for r in best}),
        "driver": representative.get("driver") or {},
        "config": {
            "requiredOverrides": config.get("requiredOverrides") or config.get("settings") or representative.get("settings") or {},
            "driverId": config.get("driverId"),
            "guestBackend": config.get("guestBackend", representative.get("guestBackend", "FEX")),
            "frameGenerationMode": config.get("frameGenerationMode", "OFF"),
            "fexPreset": config.get("fexPreset", "DEFAULT"),
            "adrenoTurboMode": config.get("adrenoTurboMode"),
            "bigCoreAffinity": config.get("bigCoreAffinity"),
            "maliGpuOptimizations": config.get("maliGpuOptimizations"),
        },
        "patches": representative.get("patches", []),
    }


def group_by_soc(reports: Iterable[dict], current_release: str) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for report in reports:
        grouped[soc_id(report)].append(report)
    result = {}
    for soc, items in sorted(grouped.items()):
        summary = aggregate(items, current_release, exact_soc=soc)
        summary["performance"] = native_fps_summary([r for r in items if soc_id(r) == soc], current_release)
        summary["recommendedSetup"] = recommended_setup(items, current_release, soc)
        result[soc] = summary
    return result
