from __future__ import annotations

import json
import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate import allowed_issue_refs, issue_identity_errors, report_issue_reference_error, validate


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


class MixedProvenanceValidationTests(unittest.TestCase):
    @staticmethod
    def game(canonical=("JICA98/Bachata-S4", 4), legacy=()):
        return {
            "schemaVersion": 2,
            "canonicalIssue": {"repository": canonical[0], "number": canonical[1]},
            "legacyIssues": [{"repository": repo, "number": number} for repo, number in legacy],
        }

    def test_historical_report_may_reference_declared_legacy_issue(self) -> None:
        game = self.game(legacy=[("JICA98/Bachata-S4-Fork-Archive", 2)])
        report = {"schemaVersion": 1, "issueNumber": 2}
        self.assertIsNone(report_issue_reference_error(game, report))
        self.assertIn(("JICA98/Bachata-S4-Fork-Archive", 2), allowed_issue_refs(game))

    def test_explicit_declared_legacy_repository_is_accepted(self) -> None:
        game = self.game(legacy=[("JICA98/Bachata-S4-Fork-Archive", 2)])
        report = {"schemaVersion": 1, "issueNumber": 2, "issueRepository": "JICA98/Bachata-S4-Fork-Archive"}
        self.assertIsNone(report_issue_reference_error(game, report))

    def test_undeclared_report_issue_is_rejected(self) -> None:
        error = report_issue_reference_error(self.game(), {"schemaVersion": 1, "issueNumber": 2})
        self.assertIn("not canonical or declared legacy issue", error)

    def test_new_canonical_report_requires_explicit_repository(self) -> None:
        game = self.game()
        self.assertIn("issueRepository is required", report_issue_reference_error(game, {"schemaVersion": 1, "issueNumber": 4}))
        self.assertIsNone(report_issue_reference_error(game, {"schemaVersion": 1, "issueNumber": 4, "issueRepository": "JICA98/Bachata-S4"}))

    def test_duplicate_or_canonical_legacy_references_are_rejected(self) -> None:
        duplicate = self.game(legacy=[("archive/repo", 2), ("archive/repo", 2)])
        self.assertTrue(any("duplicate legacy issue" in error for error in issue_identity_errors(duplicate)))
        same = self.game(legacy=[("JICA98/Bachata-S4", 4)])
        self.assertTrue(any("canonical issue cannot also be legacy" in error for error in issue_identity_errors(same)))

    def test_repository_validation_does_not_rewrite_immutable_reports(self) -> None:
        def inventory():
            return {
                str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((ROOT / "games").glob("CUSA*/reports/*.json"))
            }
        before = inventory()
        self.assertEqual(validate(ROOT), [])
        self.assertEqual(inventory(), before)


if __name__ == "__main__":
    unittest.main()
