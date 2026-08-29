#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common import CUSA_RE, load_json, write_json


REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def issue_ref(value: object, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != {"repository", "number"}:
        raise ValueError(f"{label} must contain exactly repository and number")
    repository = value.get("repository")
    number = value.get("number")
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise ValueError(f"{label}.repository must be owner/repository")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValueError(f"{label}.number must be an integer of at least 1")
    return {"repository": repository, "number": number}


def normalized_map(mapping: dict) -> dict[str, dict]:
    if mapping.get("schemaVersion") != 1 or not isinstance(mapping.get("issues"), list):
        raise ValueError("issue map must use schemaVersion 1 and contain an issues array")
    by_cusa: dict[str, dict] = {}
    sources: set[tuple[str, int]] = set()
    targets: set[tuple[str, int]] = set()
    for index, value in enumerate(mapping["issues"]):
        if not isinstance(value, dict):
            raise ValueError(f"issues[{index}] must be an object")
        if value.get("type") != "compatibility":
            continue
        required = {
            "cusaId", "sourceRepository", "sourceNumber", "sourceNodeId",
            "targetRepository", "targetNumber", "targetNodeId", "type",
        }
        if set(value) != required:
            raise ValueError(f"issues[{index}] must match the compatibility issue-map contract")
        cusa = value.get("cusaId")
        if not isinstance(cusa, str) or not CUSA_RE.fullmatch(cusa):
            raise ValueError(f"issues[{index}].cusaId must match CUSAxxxxx")
        source = issue_ref(
            {"repository": value.get("sourceRepository"), "number": value.get("sourceNumber")},
            f"issues[{index}].source",
        )
        target = issue_ref(
            {"repository": value.get("targetRepository"), "number": value.get("targetNumber")},
            f"issues[{index}].target",
        )
        source_key = (source["repository"], source["number"])
        target_key = (target["repository"], target["number"])
        if cusa in by_cusa or source_key in sources or target_key in targets:
            raise ValueError(f"duplicate mapping for {cusa}")
        if source == target:
            raise ValueError(f"conflicting mapping for {cusa}: source equals target")
        sources.add(source_key)
        targets.add(target_key)
        by_cusa[cusa] = {"cusaId": cusa, "source": source, "target": target}
    return by_cusa


def migrate_games(root: Path, mapping: dict, *, dry_run: bool) -> list[dict]:
    by_cusa = normalized_map(mapping)
    game_paths = sorted((root / "games").glob("CUSA*/game.json"))
    repository_cusas = {path.parent.name for path in game_paths}
    missing_mappings = sorted(repository_cusas - set(by_cusa))
    missing_games = sorted(set(by_cusa) - repository_cusas)
    if missing_mappings:
        raise ValueError(f"missing mappings for: {', '.join(missing_mappings)}")
    if missing_games:
        raise ValueError(f"mapping references missing games: {', '.join(missing_games)}")

    changes: list[dict] = []
    for game_path in game_paths:
        cusa = game_path.parent.name
        entry = by_cusa[cusa]
        game = load_json(game_path)
        source = entry["source"]
        target = entry["target"]
        if game.get("schemaVersion") == 2:
            if game.get("canonicalIssue") == target and source in game.get("legacyIssues", []):
                continue
            raise ValueError(f"conflicting schema-v2 identity for {cusa}")
        if game.get("schemaVersion") != 1 or game.get("issueNumber") != source["number"]:
            raise ValueError(f"source issue does not match game metadata for {cusa}")
        migrated = {
            key: value for key, value in game.items()
            if key not in {"issueNumber", "issueRepository"}
        }
        migrated["schemaVersion"] = 2
        migrated["canonicalIssue"] = target
        migrated["legacyIssues"] = [source]
        change = {
            "path": game_path.relative_to(root).as_posix(),
            "old": source,
            "new": target,
        }
        changes.append(change)
        if not dry_run:
            write_json(game_path, migrated)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate game issue identity without changing reports or evidence")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    changes = migrate_games(args.root.resolve(), mapping, dry_run=args.dry_run)
    for change in changes:
        print(f"{change['path']}: {change['old']['repository']}#{change['old']['number']} -> {change['new']['repository']}#{change['new']['number']}")
    print(f"{'Would migrate' if args.dry_run else 'Migrated'} {len(changes)} game(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
