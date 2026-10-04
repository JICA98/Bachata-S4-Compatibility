from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_site_data import build


class WebsiteCurrentScoringTests(unittest.TestCase):
    def test_historical_playable_does_not_mask_current_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "generated"
            (root / "data").mkdir()
            (root / "games/CUSA00900/reports").mkdir(parents=True)
            (root / "data/releases.json").write_text(json.dumps({
                "releases": [
                    {"tag": "v0.2.0", "publishedAt": "2026-09-08T00:00:00Z", "latest": True, "prerelease": False},
                    {"tag": "v0.1.9", "publishedAt": "2026-08-29T00:00:00Z", "latest": False, "prerelease": False},
                ]
            }), encoding="utf-8")
            (root / "data/socs.json").write_text(json.dumps({
                "schemaVersion": 1,
                "socs": {"sm7475": {"name": "Snapdragon 7+ Gen 2", "aliases": ["SM7475"]}}
            }), encoding="utf-8")
            (root / "games/CUSA00900/game.json").write_text(json.dumps({
                "schemaVersion": 2,
                "cusaId": "CUSA00900",
                "title": "Bloodborne",
                "region": "US",
                "publisher": "Sony",
                "canonicalIssue": {"repository": "JICA98/Bachata-S4", "number": 1},
                "legacyIssues": [],
            }), encoding="utf-8")

            common = {
                "schemaVersion": 2,
                "cusaId": "CUSA00900",
                "device": {
                    "manufacturer": "Example", "model": "Phone", "socId": "sm7475",
                    "socName": "Snapdragon 7+ Gen 2", "gpu": "Adreno 725",
                    "androidVersion": "16", "ramBucketGb": 12,
                },
                "driver": {"type": "turnip", "name": "Mesa Turnip", "version": "26.3"},
                "config": {
                    "settings": {}, "requiredOverrides": {}, "driverId": "turnip-test",
                    "guestBackend": "FEX", "frameGenerationMode": "OFF", "fexPreset": "DEFAULT",
                },
                "result": {"summary": "Observed", "notes": "", "issues": []},
                "contributor": {"publicId": "tester-a"},
                "provenance": {"captureType": "app-captured"},
                "issueNumber": 1,
                "issueRepository": "JICA98/Bachata-S4",
            }
            historical = {
                **common,
                "reportId": "historical-playable",
                "testedAt": "2026-08-29T00:00:00Z",
                "status": "playable",
                "release": {"tag": "v0.1.9", "commit": "abcdef1"},
            }
            current = {
                **common,
                "reportId": "current-regression",
                "testedAt": "2026-09-08T00:00:00Z",
                "status": "nothing",
                "release": {"tag": "v0.2.0", "commit": "abcdef2"},
            }
            for value in (historical, current):
                (root / f"games/CUSA00900/reports/{value['reportId']}.json").write_text(
                    json.dumps(value), encoding="utf-8"
                )

            with patch("build_site_data.validate", return_value=[]):
                build(root, output)

            index = json.loads((output / "site-index.json").read_text(encoding="utf-8"))
            game = index["games"][0]
            self.assertEqual("playable", game["bestStatus"])
            self.assertEqual("nothing", game["currentCompatibility"]["status"])
            self.assertEqual(0, game["currentCompatibility"]["score"])
            self.assertTrue(game["currentCompatibility"]["hasCurrentReports"])

            details = json.loads((output / "games/CUSA00900.json").read_text(encoding="utf-8"))
            self.assertEqual("v0.2.0", details["currentRelease"])
            self.assertEqual("nothing", details["currentCompatibility"]["status"])


if __name__ == "__main__":
    unittest.main()
