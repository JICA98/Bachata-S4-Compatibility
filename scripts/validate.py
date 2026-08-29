#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from common import CUSA_RE, STATUS_LABELS, iso_datetime, load_json, sha256

MAX_SCREENSHOTS = 3
MAX_SCREENSHOT_BYTES = 3 * 1024 * 1024
MAX_LOG_BYTES = 25 * 1024 * 1024
SCREENSHOT_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg"}
ISSUE_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SCHEMA_V1_ISSUE_REPOSITORY = "JICA98/Bachata-S4"


def _issue_ref(value: object) -> tuple[str, int] | None:
    if not isinstance(value, dict) or set(value) != {"repository", "number"}:
        return None
    repository = value.get("repository")
    number = value.get("number")
    if not isinstance(repository, str) or not ISSUE_REPOSITORY_RE.fullmatch(repository):
        return None
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        return None
    return repository, number


def issue_identity_errors(game: dict) -> list[str]:
    if game.get("schemaVersion") != 2:
        return ["schemaVersion must be 2"]
    errors: list[str] = []
    canonical = _issue_ref(game.get("canonicalIssue"))
    if canonical is None:
        errors.append("canonicalIssue must contain only a valid repository and number")
    legacy_value = game.get("legacyIssues")
    if not isinstance(legacy_value, list):
        return errors + ["legacyIssues must be an array"]
    legacy: list[tuple[str, int]] = []
    for index, value in enumerate(legacy_value):
        reference = _issue_ref(value)
        if reference is None:
            errors.append(f"legacyIssues[{index}] must contain only a valid repository and number")
        else:
            legacy.append(reference)
    if len(legacy) != len(set(legacy)):
        errors.append("duplicate legacy issue")
    if canonical is not None and canonical in legacy:
        errors.append("canonical issue cannot also be legacy")
    return errors


def allowed_issue_refs(game: dict) -> set[tuple[str, int]]:
    if game.get("schemaVersion") == 1:
        number = game.get("issueNumber")
        return {(SCHEMA_V1_ISSUE_REPOSITORY, number)} if isinstance(number, int) and number >= 1 else set()
    errors = issue_identity_errors(game)
    if errors:
        raise ValueError("; ".join(errors))
    canonical = _issue_ref(game["canonicalIssue"])
    legacy = {_issue_ref(value) for value in game["legacyIssues"]}
    return {canonical, *legacy}  # type: ignore[arg-type]


def report_issue_reference_error(game: dict, report: dict) -> str | None:
    number = report.get("issueNumber")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        return "issueNumber must be an integer of at least 1"
    if game.get("schemaVersion") == 1:
        return None if number == game.get("issueNumber") else "issueNumber must match game.json"
    try:
        allowed = allowed_issue_refs(game)
    except ValueError as exc:
        return f"invalid game issue identity: {exc}"
    repository = report.get("issueRepository")
    if repository is not None:
        if not isinstance(repository, str) or not ISSUE_REPOSITORY_RE.fullmatch(repository):
            return "issueRepository must be an owner/repository name"
        if (repository, number) not in allowed:
            return "report issue is not canonical or declared legacy issue"
        return None
    legacy_matches = [
        reference for reference in allowed
        if reference[1] == number and reference != _issue_ref(game.get("canonicalIssue"))
    ]
    if len(legacy_matches) == 1:
        return None
    if len(legacy_matches) > 1:
        return "historical issue repository is ambiguous; issueRepository is required"
    if _issue_ref(game.get("canonicalIssue")) == ("JICA98/Bachata-S4", number):
        return "issueRepository is required for a canonical schema-v2 report"
    return "report issue is not canonical or declared legacy issue"


def fail(errors: list[str], path: Path | str, message: str) -> None:
    errors.append(f"{path}: {message}")


def inside_repo(root: Path, relative: str, errors: list[str], owner: Path) -> Path | None:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        fail(errors, owner, f"path escapes repository: {relative}")
        return None
    return candidate


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    release_file = root / "data/releases.json"
    if not release_file.is_file():
        return [f"{release_file}: missing release index"]
    try:
        release_data = load_json(release_file)
        releases = release_data.get("releases", [])
        release_tags = {entry.get("tag") for entry in releases if isinstance(entry, dict)}
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{release_file}: {exc}"]
    if not release_tags:
        fail(errors, release_file, "must contain at least one release")

    game_paths = sorted((root / "games").glob("CUSA*/game.json"))
    report_ids: set[str] = set()
    referenced_assets: set[Path] = set()

    for game_path in game_paths:
        try:
            game = load_json(game_path)
        except (OSError, json.JSONDecodeError) as exc:
            fail(errors, game_path, str(exc)); continue
        cusa = game.get("cusaId")
        if not isinstance(cusa, str) or not CUSA_RE.fullmatch(cusa):
            fail(errors, game_path, "cusaId must match CUSAxxxxx"); continue
        if game_path.parent.name != cusa:
            fail(errors, game_path, "directory name must equal cusaId")
        for key in ("title", "region", "publisher"):
            if not isinstance(game.get(key), str) or not game[key].strip():
                fail(errors, game_path, f"{key} is required")
        schema_version = game.get("schemaVersion")
        issue = game.get("issueNumber")
        if schema_version == 2:
            for message in issue_identity_errors(game):
                fail(errors, game_path, message)
        else:
            legacy = game.get("legacyImported") is True
            if not legacy and (not isinstance(issue, int) or issue < 1):
                fail(errors, game_path, "issueNumber is required for non-legacy games")

        reports_dir = game_path.parent / "reports"
        for report_path in sorted(reports_dir.glob("*.json")):
            try:
                report = load_json(report_path)
            except (OSError, json.JSONDecodeError) as exc:
                fail(errors, report_path, str(exc)); continue
            report_id = report.get("reportId")
            if not isinstance(report_id, str) or not report_id:
                fail(errors, report_path, "reportId is required"); continue
            if report_path.stem != report_id:
                fail(errors, report_path, "filename must equal reportId.json")
            if report_id in report_ids:
                fail(errors, report_path, f"duplicate reportId: {report_id}")
            report_ids.add(report_id)
            if report.get("cusaId") != cusa:
                fail(errors, report_path, "cusaId does not match game metadata")
            try:
                iso_datetime(str(report.get("testedAt", "")))
            except (ValueError, TypeError) as exc:
                fail(errors, report_path, f"invalid testedAt: {exc}")
            if report.get("status") not in STATUS_LABELS:
                fail(errors, report_path, "invalid status")
            release = report.get("release") or {}
            if release.get("tag") not in release_tags:
                fail(errors, report_path, f"release tag is not in data/releases.json: {release.get('tag')}")
            commit = str(release.get("commit") or "")
            if not (7 <= len(commit) <= 40 and all(ch in "0123456789abcdefABCDEF" for ch in commit)):
                fail(errors, report_path, "release.commit must be a 7-40 character hexadecimal SHA")
            report_legacy = report.get("legacyImported") is True
            report_issue = report.get("issueNumber")
            issue_error = report_issue_reference_error(game, report)
            historical_canonical_without_repository = (
                report.get("schemaVersion") == 1
                and report.get("issueRepository") is None
                and issue_error == "issueRepository is required for a canonical schema-v2 report"
            )
            if issue_error and not report_legacy and not historical_canonical_without_repository:
                fail(errors, report_path, issue_error)
            device = report.get("device") or {}
            for key in ("label", "manufacturer", "model", "soc", "gpu", "androidVersion"):
                if not str(device.get(key) or "").strip():
                    fail(errors, report_path, f"device.{key} is required")
            driver = report.get("driver") or {}
            if driver.get("type") not in {"system", "turnip", "custom"}:
                fail(errors, report_path, "driver.type must be system, turnip, or custom")
            if not str(driver.get("name") or "").strip():
                fail(errors, report_path, "driver.name is required")
            if driver.get("type") == "turnip" and not str(driver.get("version") or "").strip():
                fail(errors, report_path, "exact driver.version is required for Turnip")
            for key in ("summary", "notes", "tester"):
                if not str(report.get(key) or "").strip():
                    fail(errors, report_path, f"{key} is required")

            evidence = report.get("evidence") or {}
            screenshots = evidence.get("screenshots") or []
            logs = evidence.get("logs") or []
            if not (1 <= len(screenshots) <= MAX_SCREENSHOTS):
                fail(errors, report_path, f"must reference 1-{MAX_SCREENSHOTS} screenshots")
            if not logs:
                fail(errors, report_path, "must reference at least one log")
            expected_prefix = f"assets/{cusa}/{report_id}/"
            for item in screenshots:
                relative = item.get("path") if isinstance(item, dict) else None
                if not isinstance(relative, str) or not relative.startswith(expected_prefix):
                    fail(errors, report_path, f"screenshot must live below {expected_prefix}"); continue
                asset = inside_repo(root, relative, errors, report_path)
                if not asset: continue
                referenced_assets.add(asset)
                if not asset.is_file():
                    fail(errors, report_path, f"missing screenshot: {relative}")
                elif asset.suffix.lower() not in SCREENSHOT_SUFFIXES:
                    fail(errors, report_path, f"unsupported screenshot type: {relative}")
                elif asset.stat().st_size > MAX_SCREENSHOT_BYTES:
                    fail(errors, report_path, f"screenshot exceeds {MAX_SCREENSHOT_BYTES // 1024 // 1024} MiB: {relative}")
            for item in logs:
                if not isinstance(item, dict):
                    fail(errors, report_path, "log entry must be an object"); continue
                relative = item.get("path")
                external = item.get("externalUrl")
                recorded_hash = str(item.get("sha256") or "").lower()
                if len(recorded_hash) != 64 or any(ch not in "0123456789abcdef" for ch in recorded_hash):
                    fail(errors, report_path, "log sha256 must be 64 lowercase hexadecimal characters")
                if relative:
                    if not str(relative).startswith(expected_prefix):
                        fail(errors, report_path, f"log must live below {expected_prefix}"); continue
                    asset = inside_repo(root, str(relative), errors, report_path)
                    if not asset: continue
                    referenced_assets.add(asset)
                    if not asset.is_file():
                        fail(errors, report_path, f"missing log: {relative}")
                    else:
                        if asset.suffix != ".gz": fail(errors, report_path, "logs must be gzip-compressed")
                        if asset.stat().st_size > MAX_LOG_BYTES: fail(errors, report_path, "log exceeds 25 MiB")
                        if sha256(asset) != recorded_hash: fail(errors, report_path, f"log hash mismatch: {relative}")
                        try:
                            with gzip.open(asset, "rb") as handle: handle.read(1)
                        except OSError as exc:
                            fail(errors, report_path, f"invalid gzip log {relative}: {exc}")
                elif external:
                    parsed = urlparse(str(external))
                    if not report_legacy or parsed.scheme != "https" or parsed.netloc != "raw.githubusercontent.com":
                        fail(errors, report_path, "externalUrl is permitted only for HTTPS raw GitHub legacy imports")
                else:
                    fail(errors, report_path, "log requires path or legacy externalUrl")

    # Flag accidental unreferenced evidence, except placeholders.
    assets_root = root / "assets"
    if assets_root.exists():
        for asset in assets_root.rglob("*"):
            if asset.is_file() and asset.name != ".gitkeep" and asset.resolve() not in referenced_assets:
                fail(errors, asset, "unreferenced evidence file")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Bachata S4 compatibility repository")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        print(f"Compatibility validation failed with {len(errors)} error(s):", file=sys.stderr)
        for error in errors: print(f"- {error}", file=sys.stderr)
        return 1
    reports = len(list((args.root / "games").glob("CUSA*/reports/*.json")))
    games = len(list((args.root / "games").glob("CUSA*/game.json")))
    print(f"Validated {games} game(s) and {reports} immutable report(s).")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
