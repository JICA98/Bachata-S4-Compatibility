from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate import allowed_issue_refs, issue_identity_errors, report_issue_reference_error, validate
from build_site_data import project_issue_identity
from add_report import canonical_issue_error
from migrate_issue import migrate_games


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


class SiteIssueProjectionTests(unittest.TestCase):
    def test_site_uses_canonical_issue_and_keeps_archive_provenance(self) -> None:
        game = MixedProvenanceValidationTests.game(
            canonical=("JICA98/Bachata-S4", 4),
            legacy=[("JICA98/Bachata-S4-Fork-Archive", 2)],
        )
        projected = project_issue_identity(game)
        self.assertEqual(projected["issueNumber"], 4)
        self.assertEqual(projected["issueRepository"], "JICA98/Bachata-S4")
        self.assertEqual(projected["issueUrl"], "https://github.com/JICA98/Bachata-S4/issues/4")
        self.assertEqual(projected["canonicalIssue"]["url"], projected["issueUrl"])
        self.assertEqual(
            projected["legacyIssues"][0]["url"],
            "https://github.com/JICA98/Bachata-S4-Fork-Archive/issues/2",
        )


class CreationAndMigrationTests(unittest.TestCase):
    def test_add_report_requires_exact_canonical_issue(self) -> None:
        game = MixedProvenanceValidationTests.game(canonical=("JICA98/Bachata-S4", 4))
        self.assertIsNone(canonical_issue_error(game, "JICA98/Bachata-S4", 4))
        self.assertIn("does not match canonicalIssue", canonical_issue_error(game, "JICA98/Bachata-S4", 5))
        self.assertIn("does not match canonicalIssue", canonical_issue_error(game, "other/repo", 4))

    def test_game_only_migration_preserves_report_and_evidence_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game_path = root / "games/CUSA00900/game.json"
            report_path = root / "games/CUSA00900/reports/report.json"
            evidence_path = root / "assets/CUSA00900/report/log.gz"
            game_path.parent.mkdir(parents=True)
            report_path.parent.mkdir(parents=True)
            evidence_path.parent.mkdir(parents=True)
            game_path.write_text(json.dumps({
                "schemaVersion": 1, "cusaId": "CUSA00900", "title": "Test",
                "region": "US", "publisher": "Publisher", "issueNumber": 2,
            }) + "\n", encoding="utf-8")
            report_path.write_bytes(b'{"schemaVersion":1,"issueNumber":2}\n')
            evidence_path.write_bytes(b"immutable evidence")
            mapping = {
                "schemaVersion": 1,
                "issues": [{
                    "cusaId": "CUSA00900",
                    "sourceRepository": "JICA98/Bachata-S4-Fork-Archive", "sourceNumber": 2,
                    "sourceNodeId": "source-node-2",
                    "targetRepository": "JICA98/Bachata-S4", "targetNumber": 4,
                    "targetNodeId": "target-node-4", "type": "compatibility",
                }],
            }
            report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
            evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()

            dry_run = migrate_games(root, mapping, dry_run=True)
            self.assertEqual(dry_run[0]["path"], "games/CUSA00900/game.json")
            self.assertEqual(json.loads(game_path.read_text())["schemaVersion"], 1)

            changed = migrate_games(root, mapping, dry_run=False)
            self.assertEqual(changed, dry_run)
            game = json.loads(game_path.read_text())
            self.assertEqual(game["schemaVersion"], 2)
            self.assertEqual(game["canonicalIssue"], {"repository": "JICA98/Bachata-S4", "number": 4})
            self.assertEqual(game["legacyIssues"], [{"repository": "JICA98/Bachata-S4-Fork-Archive", "number": 2}])
            self.assertNotIn("issueNumber", game)
            self.assertEqual(hashlib.sha256(report_path.read_bytes()).hexdigest(), report_hash)
            self.assertEqual(hashlib.sha256(evidence_path.read_bytes()).hexdigest(), evidence_hash)

    def test_migration_rejects_duplicate_or_conflicting_map_entries(self) -> None:
        entry = {
            "cusaId": "CUSA00900",
            "sourceRepository": "archive/repo", "sourceNumber": 2, "sourceNodeId": "source-node",
            "targetRepository": "JICA98/Bachata-S4", "targetNumber": 4, "targetNodeId": "target-node",
            "type": "compatibility",
        }
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "duplicate mapping"):
                migrate_games(Path(temporary), {"schemaVersion": 1, "issues": [entry, entry]}, dry_run=True)

    def test_migration_ignores_non_compatibility_issue_map_entries(self) -> None:
        mapping = {"schemaVersion": 1, "issues": [{
            "sourceRepository": "archive/repo", "sourceNumber": 8, "sourceNodeId": "feature-source",
            "targetRepository": "JICA98/Bachata-S4", "targetNumber": 3, "targetNodeId": "feature-target",
            "type": "feature",
        }]}
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(migrate_games(Path(temporary), mapping, dry_run=True), [])


if __name__ == "__main__":
    unittest.main()
