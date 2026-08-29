from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


class IssueIdentitySchemaTests(unittest.TestCase):
    def test_schema_v2_requires_canonical_and_legacy_issue_fields(self) -> None:
        schema = load_schema("game.schema.json")
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 2)
        self.assertIn("canonicalIssue", schema["required"])
        self.assertIn("legacyIssues", schema["required"])
        self.assertNotIn("issueNumber", schema["properties"])
        self.assertNotIn("issueRepository", schema["properties"])

    def test_issue_reference_is_closed_and_bounded(self) -> None:
        schema = load_schema("game.schema.json")
        reference = schema["$defs"]["issueReference"]
        self.assertFalse(reference["additionalProperties"])
        self.assertEqual(reference["required"], ["repository", "number"])
        self.assertEqual(reference["properties"]["repository"]["pattern"], r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
        self.assertEqual(reference["properties"]["number"], {"type": "integer", "minimum": 1})
        self.assertEqual(schema["properties"]["legacyIssues"]["uniqueItems"], True)

    def test_report_schema_allows_explicit_issue_repository(self) -> None:
        schema = load_schema("report.schema.json")
        self.assertEqual(
            schema["properties"]["issueRepository"],
            {"type": "string", "pattern": r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"},
        )
        self.assertNotIn("issueRepository", schema["required"])


if __name__ == "__main__":
    unittest.main()
