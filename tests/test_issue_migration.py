import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from migrate_issue_repository import NEW_REPOSITORY, OLD_REPOSITORY, migrate_game, migrate_report, rewrite  # noqa: E402
from validate import report_issue_reference_error  # noqa: E402


class IssueMigrationTests(unittest.TestCase):
    mapping = {1: 101, 23: 123}

    def test_canonical_issue_moves_and_legacy_archive_stays(self):
        game = {
            "schemaVersion": 2, "cusaId": "CUSA00900",
            "canonicalIssue": {"repository": OLD_REPOSITORY, "number": 1},
            "legacyIssues": [{"repository": "JICA98/Bachata-S4-Fork-Archive", "number": 2}],
        }
        migrated = migrate_game(game, self.mapping)
        self.assertEqual(migrated["canonicalIssue"], {"repository": NEW_REPOSITORY, "number": 101})
        self.assertEqual(migrated["legacyIssues"], game["legacyIssues"])

    def test_unmapped_issue_is_left_alone(self):
        game = {"schemaVersion": 2, "canonicalIssue": {"repository": OLD_REPOSITORY, "number": 9}, "legacyIssues": []}
        self.assertEqual(migrate_game(game, self.mapping), game)

    def test_report_reference_follows_its_issue_and_still_validates(self):
        game = migrate_game({"schemaVersion": 2, "canonicalIssue": {"repository": OLD_REPOSITORY, "number": 23}, "legacyIssues": []}, self.mapping)
        report = migrate_report({"schemaVersion": 1, "issueRepository": OLD_REPOSITORY, "issueNumber": 23}, self.mapping)
        self.assertEqual((report["issueRepository"], report["issueNumber"]), (NEW_REPOSITORY, 123))
        self.assertIsNone(report_issue_reference_error(game, report))

    def test_report_without_repository_follows_the_games_old_issue(self):
        report = {"schemaVersion": 1, "issueNumber": 1}
        migrated = migrate_report(report, self.mapping, {1})
        self.assertEqual((migrated["issueRepository"], migrated["issueNumber"]), (NEW_REPOSITORY, 101))
        # Without the game's old reference the number belongs to another repository (e.g. the fork archive).
        self.assertEqual(migrate_report(report, self.mapping), report)

    def test_rewrite_reports_whether_anything_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "game.json"
            path.write_text(json.dumps({"canonicalIssue": {"repository": OLD_REPOSITORY, "number": 1}, "legacyIssues": []}))
            self.assertTrue(rewrite(path, migrate_game, self.mapping))
            self.assertFalse(rewrite(path, migrate_game, self.mapping))


if __name__ == "__main__":
    unittest.main()
