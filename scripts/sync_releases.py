#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import load_json, write_json

API = "https://api.github.com/repos/JICA98/Bachata-S4/releases?per_page=100"
REPOSITORY = "JICA98/Bachata-S4"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_github_releases() -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "bachata-compatibility-sync",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise RuntimeError("GitHub releases response must be a list")
    return payload


def load_existing_index(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schemaVersion": 1,
            "generatedAt": "",
            "repository": REPOSITORY,
            "releases": [],
        }
    try:
        data = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {
            "schemaVersion": 1,
            "generatedAt": "",
            "repository": REPOSITORY,
            "releases": [],
        }
    if not isinstance(data, dict):
        return {
            "schemaVersion": 1,
            "generatedAt": "",
            "repository": REPOSITORY,
            "releases": [],
        }
    releases = data.get("releases")
    if not isinstance(releases, list):
        releases = []
    return {
        "schemaVersion": int(data.get("schemaVersion") or 1),
        "generatedAt": str(data.get("generatedAt") or ""),
        "repository": str(data.get("repository") or REPOSITORY),
        "releases": [entry for entry in releases if isinstance(entry, dict) and entry.get("tag")],
    }


def _published_sort_key(entry: dict[str, Any]) -> str:
    # Newest first; missing dates sort last when reverse=True.
    return str(entry.get("publishedAt") or "")


def merge_release_index(existing: dict[str, Any], github_releases: list[dict[str, Any]]) -> dict[str, Any]:
    active = [entry for entry in github_releases if isinstance(entry, dict) and not entry.get("draft")]
    latest_stable = next((entry["tag_name"] for entry in active if not entry.get("prerelease")), None)

    by_tag: dict[str, dict[str, Any]] = {}
    for entry in existing.get("releases") or []:
        if not isinstance(entry, dict):
            continue
        tag = entry.get("tag")
        if not isinstance(tag, str) or not tag:
            continue
        by_tag[tag] = dict(entry)

    published_tags: set[str] = set()
    live: list[dict[str, Any]] = []
    for entry in active:
        tag = entry.get("tag_name")
        if not isinstance(tag, str) or not tag:
            continue
        published_tags.add(tag)
        current = by_tag.get(tag, {"tag": tag})
        current.update(
            {
                "tag": tag,
                "name": entry.get("name") or tag,
                "url": entry.get("html_url") or current.get("url") or f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
                "publishedAt": entry.get("published_at"),
                "prerelease": bool(entry.get("prerelease")),
                "latest": tag == latest_stable,
            }
        )
        current.pop("archived", None)
        by_tag[tag] = current
        live.append(current)

    archived: list[dict[str, Any]] = []
    for tag, entry in by_tag.items():
        if tag in published_tags:
            continue
        entry["latest"] = False
        entry["archived"] = True
        archived.append(entry)

    # Preserve GitHub API order for live releases (publishedAt can be unreliable).
    archived.sort(key=_published_sort_key, reverse=True)
    return {
        "schemaVersion": int(existing.get("schemaVersion") or 1),
        "generatedAt": str(existing.get("generatedAt") or ""),
        "repository": str(existing.get("repository") or REPOSITORY),
        "releases": live + archived,
    }


def releases_metadata(value: dict[str, Any]) -> dict[str, Any]:
    """Comparable payload excluding generatedAt."""
    return {
        "schemaVersion": value.get("schemaVersion"),
        "repository": value.get("repository"),
        "releases": value.get("releases"),
    }


def sync_to_path(path: Path, github_releases: list[dict[str, Any]] | None = None) -> bool:
    existing = load_existing_index(path)
    fetched = github_releases if github_releases is not None else fetch_github_releases()
    merged = merge_release_index(existing, fetched)
    if path.is_file() and releases_metadata(existing) == releases_metadata(merged):
        return False
    merged["generatedAt"] = utc_now()
    write_json(path, merged)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize published Bachata S4 releases")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data/releases.json",
    )
    args = parser.parse_args()
    wrote = sync_to_path(args.output)
    data = load_existing_index(args.output)
    action = "Wrote" if wrote else "Unchanged"
    print(f"{action} {len(data['releases'])} releases at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
