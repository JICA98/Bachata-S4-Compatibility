#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from common import CUSA_RE, gzip_copy, load_json, sha256, slug, write_json


def canonical_issue_error(game: dict, repository: str, number: int) -> str | None:
    canonical = game.get("canonicalIssue") if game.get("schemaVersion") == 2 else None
    if canonical != {"repository": repository, "number": number}:
        return f"issue {repository}#{number} does not match canonicalIssue"
    return None


def parse_number(value: str | None) -> float | None:
    return None if value in (None, "") else float(value)


def parse_evidence(values: list[str]) -> list[tuple[Path, str]]:
    parsed: list[tuple[Path, str]] = []
    for value in values:
        path, _, description = value.partition("::")
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise SystemExit(f"Evidence file does not exist: {source}")
        parsed.append((source, description.strip()))
    return parsed


def copy_screenshot(source: Path, destination: Path) -> Path:
    try:
        from PIL import Image
    except ImportError:
        destination = destination.with_suffix(source.suffix.lower())
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination

    destination = destination.with_suffix(".webp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = image.convert("RGB")
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        image.save(destination, "WEBP", quality=82, method=6)
    return destination


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Add one immutable Bachata S4 compatibility report")
    value.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    value.add_argument("--title", required=True)
    value.add_argument("--cusa", required=True)
    value.add_argument("--region", required=True)
    value.add_argument("--publisher", required=True)
    value.add_argument("--issue-number", required=True, type=int)
    value.add_argument("--issue-repository", required=True)
    value.add_argument("--status", required=True, choices=["playable", "ingame", "menus", "boots", "nothing"])
    value.add_argument("--tested-at", default=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    value.add_argument("--game-version", default="")
    value.add_argument("--release-tag", required=True)
    value.add_argument("--commit", required=True)
    value.add_argument("--emulator-version", default="")
    value.add_argument("--guest-backend", default="fex")
    value.add_argument("--summary", required=True)
    value.add_argument("--notes", required=True)
    value.add_argument("--issue", action="append", default=[])
    value.add_argument("--device-json", type=Path, required=True)
    value.add_argument("--driver-type", required=True, choices=["system", "turnip", "custom"])
    value.add_argument("--driver-name", required=True)
    value.add_argument("--driver-version", default="")
    value.add_argument("--driver-build", default="")
    value.add_argument("--driver-source", default="")
    value.add_argument("--resolution-scale", type=float)
    value.add_argument("--average-fps")
    value.add_argument("--min-fps")
    value.add_argument("--max-fps")
    value.add_argument("--frame-pacing", default="")
    value.add_argument("--test-duration-seconds", type=int)
    value.add_argument("--screenshot", action="append", required=True)
    value.add_argument("--log", action="append", required=True)
    value.add_argument("--tester", required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    root = args.root.resolve()
    cusa = args.cusa.upper()
    if not CUSA_RE.fullmatch(cusa):
        raise SystemExit("--cusa must match CUSAxxxxx")
    if args.driver_type == "turnip" and not args.driver_version.strip():
        raise SystemExit("--driver-version is mandatory for Turnip")
    if not 1 <= len(args.screenshot) <= 3:
        raise SystemExit("Each report requires one to three screenshots")

    device = load_json(args.device_json.resolve())
    tested_at = datetime.fromisoformat(args.tested_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    stamp = tested_at.strftime("%Y%m%dT%H%M%SZ")
    report_id = "-".join(
        [stamp, slug(args.release_tag), slug(device.get("label", "device")), slug(args.driver_name), slug(args.driver_version or args.driver_type)]
    )[:180]

    game_dir = root / "games" / cusa
    game_file = game_dir / "game.json"
    report_file = game_dir / "reports" / f"{report_id}.json"
    if report_file.exists():
        raise SystemExit(f"Report already exists: {report_file}")

    if game_file.exists():
        game = load_json(game_file)
        issue_error = canonical_issue_error(game, args.issue_repository, args.issue_number)
        if issue_error:
            raise SystemExit(issue_error)
        for key, expected in (("title", args.title), ("region", args.region), ("publisher", args.publisher)):
            if game.get(key) != expected:
                raise SystemExit(f"Existing game {key} differs: {game.get(key)!r}")
    else:
        write_json(
            game_file,
            {
                "schemaVersion": 2,
                "cusaId": cusa,
                "title": args.title,
                "region": args.region,
                "publisher": args.publisher,
                "canonicalIssue": {
                    "repository": args.issue_repository,
                    "number": args.issue_number,
                },
                "legacyIssues": [],
            },
        )

    asset_dir = root / "assets" / cusa / report_id
    screenshots = []
    for index, (source, caption) in enumerate(parse_evidence(args.screenshot), 1):
        destination = copy_screenshot(source, asset_dir / "screenshots" / f"{index:02d}{source.suffix.lower()}")
        screenshots.append({"path": destination.relative_to(root).as_posix(), "caption": caption or f"Screenshot {index}"})

    logs = []
    for index, (source, label) in enumerate(parse_evidence(args.log), 1):
        destination = asset_dir / "logs" / f"{index:02d}-{slug(source.stem)}.log.gz"
        if source.suffix == ".gz":
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        else:
            gzip_copy(source, destination)
        logs.append({"path": destination.relative_to(root).as_posix(), "label": label or source.name, "sha256": sha256(destination)})

    performance = {}
    for key, source in (("averageFps", args.average_fps), ("minimumFps", args.min_fps), ("maximumFps", args.max_fps)):
        parsed = parse_number(source)
        if parsed is not None:
            performance[key] = parsed
    if args.frame_pacing:
        performance["framePacing"] = args.frame_pacing
    if args.test_duration_seconds is not None:
        performance["testDurationSeconds"] = args.test_duration_seconds

    driver = {"type": args.driver_type, "name": args.driver_name}
    for key, source in (("version", args.driver_version), ("build", args.driver_build), ("source", args.driver_source)):
        if source:
            driver[key] = source

    report = {
        "schemaVersion": 1,
        "reportId": report_id,
        "cusaId": cusa,
        "testedAt": args.tested_at,
        "status": args.status,
        "gameVersion": args.game_version,
        "release": {
            "tag": args.release_tag,
            "commit": args.commit,
            "url": f"https://github.com/JICA98/Bachata-S4/releases/tag/{args.release_tag}",
        },
        "emulatorVersion": args.emulator_version,
        "guestBackend": args.guest_backend,
        "summary": args.summary,
        "notes": args.notes,
        "issues": args.issue,
        "device": device,
        "driver": driver,
        "settings": {"resolutionScale": args.resolution_scale} if args.resolution_scale is not None else {},
        "performance": performance,
        "evidence": {"screenshots": screenshots, "logs": logs},
        "tester": args.tester,
        "issueNumber": args.issue_number,
        "issueRepository": args.issue_repository,
    }
    write_json(report_file, report)
    print(report_file.relative_to(root))
    print(f"Report ID: {report_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
