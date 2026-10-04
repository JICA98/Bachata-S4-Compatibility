#!/usr/bin/env python3
"""Point game and report issue references at transferred issues.

Compatibility issues moved from JICA98/Bachata-S4 to this repository. GitHub gives a
transferred issue a new number, so references are rewritten from a mapping of
old number -> new number (as produced when the issues were transferred).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OLD_REPOSITORY = "JICA98/Bachata-S4"
NEW_REPOSITORY = "JICA98/Bachata-S4-Compatibility"


def load_mapping(path: Path) -> dict[int, int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(old): int(new) for old, new in raw.items()}


def migrate_reference(value, mapping: dict[int, int]):
    if isinstance(value, dict) and value.get("repository") == OLD_REPOSITORY and value.get("number") in mapping:
        return {**value, "repository": NEW_REPOSITORY, "number": mapping[value["number"]]}
    return value


def migrate_game(game: dict, mapping: dict[int, int]) -> dict:
    out = dict(game)
    if "canonicalIssue" in out:
        out["canonicalIssue"] = migrate_reference(out["canonicalIssue"], mapping)
    if isinstance(out.get("legacyIssues"), list):
        canonical = out.get("canonicalIssue")
        legacy = []
        for item in out["legacyIssues"]:
            item = migrate_reference(item, mapping)
            if item != canonical and item not in legacy:
                legacy.append(item)
        out["legacyIssues"] = legacy
    return out


def old_issue_numbers(game: dict) -> set[int]:
    """Numbers of the game's references to the old repository, before migration."""
    refs = [game.get("canonicalIssue"), *(game.get("legacyIssues") or [])]
    return {ref["number"] for ref in refs if isinstance(ref, dict) and ref.get("repository") == OLD_REPOSITORY}


def migrate_report(report: dict, mapping: dict[int, int], implicit_old: set[int] = frozenset()) -> dict:
    # Older reports omit issueRepository; their number then refers to the game's old canonical issue.
    repository = report.get("issueRepository") or (OLD_REPOSITORY if report.get("issueNumber") in implicit_old else None)
    if repository == OLD_REPOSITORY and report.get("issueNumber") in mapping:
        return {**report, "issueRepository": NEW_REPOSITORY, "issueNumber": mapping[report["issueNumber"]]}
    return report


def rewrite(path: Path, transform, mapping: dict[int, int]) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    migrated = transform(data, mapping)
    if migrated == data:
        return False
    path.write_text(json.dumps(migrated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=Path("data/issue-transfer.json"), help="JSON object of old issue number -> new issue number")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    mapping = load_mapping(args.mapping)
    changed = []
    for game_path in sorted((args.root / "games").glob("CUSA*/game.json")):
        implicit_old = old_issue_numbers(json.loads(game_path.read_text(encoding="utf-8")))
        if rewrite(game_path, migrate_game, mapping):
            changed.append(game_path)
        for report_path in sorted((game_path.parent / "reports").glob("*.json")):
            if rewrite(report_path, lambda report, m: migrate_report(report, m, implicit_old), mapping):
                changed.append(report_path)
    for path in changed:
        print(path.relative_to(args.root))
    print(f"{len(changed)} files updated")


if __name__ == "__main__":
    main()
