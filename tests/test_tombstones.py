from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply_tombstones import load_tombstones, prune_app, prune_site


class TombstoneTests(unittest.TestCase):
    def test_registry_rejects_duplicate_report_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/tombstones.json").write_text(json.dumps({
                "schemaVersion": 1,
                "tombstones": [
                    {"reportId": "r1", "reason": "privacy", "removedAt": "2026-09-08T00:00:00Z"},
                    {"reportId": "r1", "reason": "legal", "removedAt": "2026-09-08T01:00:00Z"},
                ],
            }), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_tombstones(root)

    def test_prunes_report_from_site_and_app_and_invalidates_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "generated"
            app = site / "app-v2"
            (site / "games").mkdir(parents=True)
            (app / "games").mkdir(parents=True)

            site_index = {
                "games": [{"cusaId": "CUSA00900", "reportCount": 2, "reports": [{"reportId": "keep"}, {"reportId": "remove"}]}]
            }
            (site / "site-index.json").write_text(json.dumps(site_index), encoding="utf-8")
            (site / "games/CUSA00900.json").write_text(json.dumps({
                "reports": [{"reportId": "keep"}, {"reportId": "remove"}]
            }), encoding="utf-8")
            (app / "games/CUSA00900.json").write_text(json.dumps({
                "general": {"score": 100, "status": "playable", "hasCurrentReports": True},
                "socs": {"sm7475": {"score": 100}},
                "reports": [{"reportId": "keep"}, {"reportId": "remove"}],
            }), encoding="utf-8")

            prune_site(site, {"remove"})
            prune_app(app, {"remove"})

            site_after = json.loads((site / "site-index.json").read_text())
            self.assertEqual(1, site_after["games"][0]["reportCount"])
            self.assertEqual(["keep"], [r["reportId"] for r in site_after["games"][0]["reports"]])

            app_after = json.loads((app / "games/CUSA00900.json").read_text())
            self.assertEqual(["keep"], [r["reportId"] for r in app_after["reports"]])
            self.assertEqual("unknown", app_after["general"]["status"])
            self.assertFalse(app_after["general"]["hasCurrentReports"])
            self.assertEqual({}, app_after["socs"])
            self.assertTrue(app_after["general"]["tombstoneRebuildRequired"])


if __name__ == "__main__":
    unittest.main()
