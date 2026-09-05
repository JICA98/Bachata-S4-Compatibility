from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sync_releases import merge_release_index, sync_to_path  # noqa: E402
from validate import validate  # noqa: E402


def gh(tag: str, *, name: str | None = None, published_at: str = "2026-08-01T00:00:00Z", prerelease: bool = False, draft: bool = False) -> dict:
    return {
        "tag_name": tag,
        "name": name or tag,
        "html_url": f"https://github.com/JICA98/Bachata-S4/releases/tag/{tag}",
        "published_at": published_at,
        "prerelease": prerelease,
        "draft": draft,
    }


class MergeReleaseIndexTests(unittest.TestCase):
    def test_adds_new_published_release(self) -> None:
        existing = {
            "schemaVersion": 1,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repository": "JICA98/Bachata-S4",
            "releases": [
                {
                    "tag": "v0.1.8",
                    "name": "BachataS4 v0.1.8",
                    "url": "https://github.com/JICA98/Bachata-S4/releases/tag/v0.1.8",
                    "publishedAt": "2026-08-28T00:00:00Z",
                    "prerelease": False,
                    "latest": True,
                }
            ],
        }
        merged = merge_release_index(existing, [gh("v0.1.9", published_at="2026-08-29T00:00:00Z"), gh("v0.1.8", published_at="2026-08-28T00:00:00Z")])
        tags = [entry["tag"] for entry in merged["releases"]]
        self.assertEqual(tags, ["v0.1.9", "v0.1.8"])
        by_tag = {entry["tag"]: entry for entry in merged["releases"]}
        self.assertTrue(by_tag["v0.1.9"]["latest"])
        self.assertFalse(by_tag["v0.1.8"]["latest"])
        self.assertFalse(by_tag["v0.1.9"].get("archived", False))

    def test_keeps_missing_github_release_as_archived(self) -> None:
        existing = {
            "schemaVersion": 1,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repository": "JICA98/Bachata-S4",
            "releases": [
                {
                    "tag": "v0.1.9",
                    "name": "BachataS4 v0.1.9",
                    "url": "https://github.com/JICA98/Bachata-S4/releases/tag/v0.1.9",
                    "publishedAt": "2026-08-29T00:00:00Z",
                    "prerelease": False,
                    "latest": True,
                },
                {
                    "tag": "v0.1.7",
                    "name": "BachataS4 v0.1.7",
                    "url": "https://github.com/JICA98/Bachata-S4/releases/tag/v0.1.7",
                    "publishedAt": "2026-08-01T00:00:00Z",
                    "prerelease": False,
                    "latest": False,
                },
            ],
        }
        merged = merge_release_index(existing, [gh("v0.1.9", published_at="2026-08-29T00:00:00Z")])
        by_tag = {entry["tag"]: entry for entry in merged["releases"]}
        self.assertIn("v0.1.7", by_tag)
        self.assertTrue(by_tag["v0.1.7"]["archived"])
        self.assertFalse(by_tag["v0.1.7"]["latest"])
        self.assertEqual(by_tag["v0.1.7"]["name"], "BachataS4 v0.1.7")
        self.assertFalse(by_tag["v0.1.9"].get("archived", False))
        self.assertTrue(by_tag["v0.1.9"]["latest"])

    def test_preserves_github_order_even_when_published_at_differs(self) -> None:
        existing = {
            "schemaVersion": 1,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repository": "JICA98/Bachata-S4",
            "releases": [],
        }
        merged = merge_release_index(
            existing,
            [
                gh("v0.1.9", published_at="2026-08-29T07:42:43Z"),
                gh("v0.1.8", published_at="2026-08-29T07:43:02Z"),
            ],
        )
        self.assertEqual([entry["tag"] for entry in merged["releases"]], ["v0.1.9", "v0.1.8"])

    def test_updates_existing_published_metadata(self) -> None:
        existing = {
            "schemaVersion": 1,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repository": "JICA98/Bachata-S4",
            "releases": [
                {
                    "tag": "v0.1.9",
                    "name": "old name",
                    "url": "https://example.invalid/old",
                    "publishedAt": "2026-01-01T00:00:00Z",
                    "prerelease": True,
                    "latest": False,
                    "archived": True,
                }
            ],
        }
        merged = merge_release_index(existing, [gh("v0.1.9", name="BachataS4 v0.1.9", published_at="2026-08-29T07:42:43Z")])
        entry = merged["releases"][0]
        self.assertEqual(entry["name"], "BachataS4 v0.1.9")
        self.assertEqual(entry["url"], "https://github.com/JICA98/Bachata-S4/releases/tag/v0.1.9")
        self.assertEqual(entry["publishedAt"], "2026-08-29T07:42:43Z")
        self.assertFalse(entry["prerelease"])
        self.assertTrue(entry["latest"])
        self.assertFalse(entry.get("archived", False))


class SyncWriteBehaviorTests(unittest.TestCase):
    def test_skips_write_when_release_metadata_unchanged(self) -> None:
        payload = {
            "schemaVersion": 1,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repository": "JICA98/Bachata-S4",
            "releases": [
                {
                    "tag": "v0.1.9",
                    "name": "BachataS4 v0.1.9",
                    "url": "https://github.com/JICA98/Bachata-S4/releases/tag/v0.1.9",
                    "publishedAt": "2026-08-29T07:42:43Z",
                    "prerelease": False,
                    "latest": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.json"
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            before = path.read_text(encoding="utf-8")
            with mock.patch("sync_releases.fetch_github_releases", return_value=[gh("v0.1.9", name="BachataS4 v0.1.9", published_at="2026-08-29T07:42:43Z")]):
                wrote = sync_to_path(path)
            after = path.read_text(encoding="utf-8")
            self.assertFalse(wrote)
            self.assertEqual(before, after)
            self.assertEqual(json.loads(after)["generatedAt"], "2026-01-01T00:00:00Z")

    def test_updates_generated_at_when_releases_change(self) -> None:
        payload = {
            "schemaVersion": 1,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repository": "JICA98/Bachata-S4",
            "releases": [
                {
                    "tag": "v0.1.8",
                    "name": "BachataS4 v0.1.8",
                    "url": "https://github.com/JICA98/Bachata-S4/releases/tag/v0.1.8",
                    "publishedAt": "2026-08-28T00:00:00Z",
                    "prerelease": False,
                    "latest": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.json"
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            with mock.patch(
                "sync_releases.fetch_github_releases",
                return_value=[
                    gh("v0.1.9", name="BachataS4 v0.1.9", published_at="2026-08-29T00:00:00Z"),
                    gh("v0.1.8", name="BachataS4 v0.1.8", published_at="2026-08-28T00:00:00Z"),
                ],
            ):
                wrote = sync_to_path(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(wrote)
            self.assertNotEqual(data["generatedAt"], "2026-01-01T00:00:00Z")
            self.assertEqual([entry["tag"] for entry in data["releases"]], ["v0.1.9", "v0.1.8"])


class ValidateMissingReleaseTagTests(unittest.TestCase):
    def test_repo_validate_allows_report_tags_missing_from_index(self) -> None:
        errors = validate(ROOT)
        missing_tag_errors = [error for error in errors if "release tag is not in data/releases.json" in error]
        self.assertEqual(missing_tag_errors, [])


if __name__ == "__main__":
    unittest.main()
