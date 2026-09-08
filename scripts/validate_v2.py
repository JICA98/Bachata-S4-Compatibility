#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

CUSA_RE = re.compile(r"^CUSA[0-9]{5}$")
REPORT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,160}$")
SOC_ID_RE = re.compile(r"^[a-z0-9._-]{2,80}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONTRIBUTOR_RE = re.compile(r"^[A-Za-z0-9._-]{4,80}$")
SETTING_ID_RE = re.compile(r"^[A-Za-z0-9._-]{2,120}$")
ISSUE_ID_RE = re.compile(r"^[a-z0-9._-]{2,80}$")
STATUS = {"playable", "ingame", "menus", "boots", "nothing"}
DRIVER_TYPES = {"system", "turnip", "custom"}
CAPTURE_TYPES = {"app-captured", "structured-manual", "maintainer-verified", "legacy-imported"}
FRAME_PACING = {"smooth", "minor-stutter", "stuttery", "severe-stutter", "unknown"}
WITHDRAWAL_REASONS = {"user-request", "privacy", "legal-removal", "security", "invalid-report"}
PRIVATE_RE = re.compile(
    r"content://|file://|/storage/emulated/|/data/user/|/sdcard/|ro\.serialno|android[_ -]?id|"
    r"adb[_ -]?serial|mac[_ -]?address|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}",
    re.I,
)

TOP_LEVEL_KEYS = {
    "schemaVersion", "reportId", "cusaId", "testedAt", "status", "game", "release", "device",
    "driver", "config", "patches", "performance", "result", "evidence", "contributor", "provenance",
    "supersedes", "withdrawn", "withdrawalReason",
}


def fail(errors: list[str], path: Path, message: str) -> None:
    errors.append(f"{path}: {message}")


def closed_object(errors: list[str], path: Path, label: str, value: object, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        fail(errors, path, f"{label} must be an object")
        return {}
    unknown = set(value) - allowed
    if unknown:
        fail(errors, path, f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    missing = required - set(value)
    if missing:
        fail(errors, path, f"{label} is missing: {', '.join(sorted(missing))}")
    return value


def bounded_text(errors: list[str], path: Path, label: str, value: object, maximum: int, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        fail(errors, path, f"{label} must be text")
        return ""
    text = value.strip()
    if required and not text:
        fail(errors, path, f"{label} is required")
    if len(text) > maximum:
        fail(errors, path, f"{label} exceeds {maximum} characters")
    if PRIVATE_RE.search(text):
        fail(errors, path, f"{label} contains a private identifier or local path")
    return text


def scalar_map(errors: list[str], path: Path, label: str, value: object) -> None:
    if not isinstance(value, dict):
        fail(errors, path, f"{label} must be an object")
        return
    if len(value) > 128:
        fail(errors, path, f"{label} has too many fields")
    for key, item in value.items():
        if not isinstance(key, str) or not SETTING_ID_RE.fullmatch(key):
            fail(errors, path, f"{label} contains unsafe setting id: {key!r}")
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            continue
        if isinstance(item, str):
            if PRIVATE_RE.search(item):
                fail(errors, path, f"{label}.{key} contains a private path or identifier")
            continue
        fail(errors, path, f"{label}.{key} must be a boolean, number, or string")


def scan_private(errors: list[str], path: Path, value: object, label: str = "report", depth: int = 0) -> None:
    if depth > 10:
        fail(errors, path, f"{label} is too deeply nested")
        return
    if isinstance(value, str):
        if PRIVATE_RE.search(value):
            fail(errors, path, f"{label} contains a private identifier or local path")
    elif isinstance(value, list):
        if len(value) > 128:
            fail(errors, path, f"{label} array is too large")
        for index, item in enumerate(value):
            scan_private(errors, path, item, f"{label}[{index}]", depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            scan_private(errors, path, item, f"{label}.{key}", depth + 1)


def validate_report_v2(report_path: Path, report: dict, expected_cusa: str | None = None) -> list[str]:
    errors: list[str] = []
    scan_private(errors, report_path, report)
    if set(report) - TOP_LEVEL_KEYS:
        fail(errors, report_path, f"unknown top-level fields: {', '.join(sorted(set(report) - TOP_LEVEL_KEYS))}")
    required = {"schemaVersion", "reportId", "cusaId", "testedAt", "status", "release", "device", "driver", "config", "result", "contributor", "provenance"}
    missing = required - set(report)
    if missing:
        fail(errors, report_path, f"missing required fields: {', '.join(sorted(missing))}")
    if report.get("schemaVersion") != 2:
        fail(errors, report_path, "schemaVersion must be 2")

    report_id = report.get("reportId")
    if not isinstance(report_id, str) or not REPORT_ID_RE.fullmatch(report_id):
        fail(errors, report_path, "invalid reportId")
    elif report_path.stem != report_id:
        fail(errors, report_path, "filename must equal reportId.json")

    cusa = report.get("cusaId")
    if not isinstance(cusa, str) or not CUSA_RE.fullmatch(cusa):
        fail(errors, report_path, "cusaId must match CUSAxxxxx")
    elif expected_cusa and cusa != expected_cusa:
        fail(errors, report_path, "cusaId does not match game directory")
    if report.get("status") not in STATUS:
        fail(errors, report_path, "invalid status")

    tested_at = bounded_text(errors, report_path, "testedAt", report.get("testedAt"), 40, True)
    if tested_at:
        try:
            from datetime import datetime
            datetime.fromisoformat(tested_at.replace("Z", "+00:00"))
        except ValueError:
            fail(errors, report_path, "testedAt must be ISO-8601")

    release = closed_object(errors, report_path, "release", report.get("release"), {"tag", "commit", "runtimeRevision"}, {"tag", "commit"})
    bounded_text(errors, report_path, "release.tag", release.get("tag"), 40, True)
    commit = bounded_text(errors, report_path, "release.commit", release.get("commit"), 40, True)
    if commit and not SHA_RE.fullmatch(commit):
        fail(errors, report_path, "release.commit must be a 7-40 character hexadecimal SHA")
    bounded_text(errors, report_path, "release.runtimeRevision", release.get("runtimeRevision"), 120)

    game = report.get("game")
    if game is not None:
        game = closed_object(errors, report_path, "game", game, {"version", "region"})
        bounded_text(errors, report_path, "game.version", game.get("version"), 40)
        bounded_text(errors, report_path, "game.region", game.get("region"), 40)

    device = closed_object(
        errors, report_path, "device", report.get("device"),
        {"manufacturer", "model", "socId", "socName", "gpu", "androidVersion", "ramBucketGb"},
        {"manufacturer", "model", "socId", "socName", "gpu", "androidVersion", "ramBucketGb"},
    )
    for key, maximum in (("manufacturer", 80), ("model", 120), ("socName", 120), ("gpu", 120), ("androidVersion", 32)):
        bounded_text(errors, report_path, f"device.{key}", device.get(key), maximum, True)
    soc = bounded_text(errors, report_path, "device.socId", device.get("socId"), 80, True)
    if soc and not SOC_ID_RE.fullmatch(soc):
        fail(errors, report_path, "device.socId must be canonical lowercase id")
    ram = device.get("ramBucketGb")
    if not isinstance(ram, int) or isinstance(ram, bool) or not 1 <= ram <= 64:
        fail(errors, report_path, "device.ramBucketGb must be an integer from 1 to 64")

    driver = closed_object(errors, report_path, "driver", report.get("driver"), {"id", "type", "name", "version", "build"}, {"type", "name", "version"})
    if driver.get("type") not in DRIVER_TYPES:
        fail(errors, report_path, "driver.type must be system, turnip, or custom")
    bounded_text(errors, report_path, "driver.id", driver.get("id"), 160)
    bounded_text(errors, report_path, "driver.name", driver.get("name"), 160, True)
    bounded_text(errors, report_path, "driver.version", driver.get("version"), 120, True)
    bounded_text(errors, report_path, "driver.build", driver.get("build"), 160)

    config = closed_object(
        errors, report_path, "config", report.get("config"),
        {"settings", "requiredOverrides", "driverId", "guestBackend", "frameGenerationMode", "fexPreset", "adrenoTurboMode", "bigCoreAffinity", "maliGpuOptimizations"},
        {"settings", "driverId", "guestBackend", "frameGenerationMode", "fexPreset"},
    )
    scalar_map(errors, report_path, "config.settings", config.get("settings"))
    if "requiredOverrides" in config:
        scalar_map(errors, report_path, "config.requiredOverrides", config.get("requiredOverrides"))
    bounded_text(errors, report_path, "config.driverId", config.get("driverId"), 160, True)
    if config.get("guestBackend") != "FEX":
        fail(errors, report_path, "config.guestBackend must be FEX")
    bounded_text(errors, report_path, "config.frameGenerationMode", config.get("frameGenerationMode"), 40, True)
    bounded_text(errors, report_path, "config.fexPreset", config.get("fexPreset"), 80, True)
    for key in ("adrenoTurboMode", "bigCoreAffinity", "maliGpuOptimizations"):
        if key in config and not isinstance(config[key], bool):
            fail(errors, report_path, f"config.{key} must be boolean")

    patches = report.get("patches", [])
    if not isinstance(patches, list) or len(patches) > 32:
        fail(errors, report_path, "patches must be an array of at most 32 items")
    else:
        for index, value in enumerate(patches):
            patch = closed_object(errors, report_path, f"patches[{index}]", value, {"id", "preset", "revision"}, {"id"})
            bounded_text(errors, report_path, f"patches[{index}].id", patch.get("id"), 160, True)
            bounded_text(errors, report_path, f"patches[{index}].preset", patch.get("preset"), 160)
            bounded_text(errors, report_path, f"patches[{index}].revision", patch.get("revision"), 120)

    performance = report.get("performance")
    if performance is not None:
        performance = closed_object(errors, report_path, "performance", performance, {"nativeAverageFps", "nativeOnePercentLowFps", "outputAverageFps", "testDurationSeconds", "framePacing"})
        for key, maximum in (("nativeAverageFps", 240), ("nativeOnePercentLowFps", 240), ("outputAverageFps", 480)):
            if key in performance:
                value = performance[key]
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= maximum:
                    fail(errors, report_path, f"performance.{key} must be 0-{maximum}")
        if "testDurationSeconds" in performance:
            duration = performance["testDurationSeconds"]
            if not isinstance(duration, int) or isinstance(duration, bool) or not 1 <= duration <= 86400:
                fail(errors, report_path, "performance.testDurationSeconds must be 1-86400")
        if "framePacing" in performance and performance["framePacing"] not in FRAME_PACING:
            fail(errors, report_path, "invalid performance.framePacing")

    result = closed_object(errors, report_path, "result", report.get("result"), {"summary", "notes", "issues"}, {"summary"})
    bounded_text(errors, report_path, "result.summary", result.get("summary"), 1000, True)
    bounded_text(errors, report_path, "result.notes", result.get("notes"), 6000)
    issues = result.get("issues", [])
    if not isinstance(issues, list) or len(issues) > 32:
        fail(errors, report_path, "result.issues must be an array of at most 32 items")
    else:
        for value in issues:
            if not isinstance(value, str) or not ISSUE_ID_RE.fullmatch(value):
                fail(errors, report_path, f"invalid issue id: {value!r}")

    contributor = closed_object(errors, report_path, "contributor", report.get("contributor"), {"publicId", "displayName"}, {"publicId"})
    public_id = bounded_text(errors, report_path, "contributor.publicId", contributor.get("publicId"), 80, True)
    if public_id and not CONTRIBUTOR_RE.fullmatch(public_id):
        fail(errors, report_path, "invalid contributor.publicId")
    bounded_text(errors, report_path, "contributor.displayName", contributor.get("displayName"), 80)

    provenance = closed_object(errors, report_path, "provenance", report.get("provenance"), {"captureType", "appBuild"}, {"captureType"})
    if provenance.get("captureType") not in CAPTURE_TYPES:
        fail(errors, report_path, "invalid provenance.captureType")
    bounded_text(errors, report_path, "provenance.appBuild", provenance.get("appBuild"), 120)

    evidence = report.get("evidence")
    if evidence is not None:
        evidence = closed_object(errors, report_path, "evidence", evidence, {"screenshots", "diagnostics"})
        for category in ("screenshots", "diagnostics"):
            entries = evidence.get(category, [])
            if not isinstance(entries, list) or len(entries) > 3:
                fail(errors, report_path, f"evidence.{category} must have at most 3 items")
                continue
            for index, item in enumerate(entries):
                fields = {"url", "sha256", "caption"} if category == "screenshots" else {"url", "sha256", "label"}
                entry = closed_object(errors, report_path, f"evidence.{category}[{index}]", item, fields, {"url", "sha256"})
                url = bounded_text(errors, report_path, f"evidence.{category}[{index}].url", entry.get("url"), 2048, True)
                if url:
                    parsed = urlparse(url)
                    if parsed.scheme != "https" or not parsed.netloc:
                        fail(errors, report_path, f"evidence.{category}[{index}].url must be HTTPS")
                digest = bounded_text(errors, report_path, f"evidence.{category}[{index}].sha256", entry.get("sha256"), 64, True)
                if digest and not SHA256_RE.fullmatch(digest):
                    fail(errors, report_path, f"evidence.{category}[{index}].sha256 must be lowercase SHA-256")
                bounded_text(errors, report_path, f"evidence.{category}[{index}].caption", entry.get("caption"), 300)
                bounded_text(errors, report_path, f"evidence.{category}[{index}].label", entry.get("label"), 120)

    if report.get("withdrawn") is not None and not isinstance(report.get("withdrawn"), bool):
        fail(errors, report_path, "withdrawn must be boolean")
    if report.get("withdrawalReason") is not None and report.get("withdrawalReason") not in WITHDRAWAL_REASONS:
        fail(errors, report_path, "invalid withdrawalReason")
    if report.get("withdrawn") is True and not report.get("withdrawalReason"):
        fail(errors, report_path, "withdrawn reports require withdrawalReason")
    if report.get("supersedes") is not None:
        value = bounded_text(errors, report_path, "supersedes", report.get("supersedes"), 160, True)
        if value and not REPORT_ID_RE.fullmatch(value):
            fail(errors, report_path, "invalid supersedes report id")

    return errors
