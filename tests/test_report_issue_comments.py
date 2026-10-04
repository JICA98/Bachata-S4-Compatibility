import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from comment_report_issues import build_comment, emulator_version, marker  # noqa: E402

SHA = "a" * 40
BASE = "https://github.com/JICA98/Bachata-S4-Compatibility/blob/" + SHA


def v2_report(**overrides):
    report = {
        "schemaVersion": 2,
        "reportId": "s_abc",
        "cusaId": "CUSA01410",
        "status": "playable",
        "release": {"tag": "v0.2.4"},
        "device": {"manufacturer": "LENOVO", "model": "TB321FU", "socName": "SM8650"},
        "driver": {"name": "Turnip gen8 v5", "version": "gen8-v5"},
        "evidence": {
            "screenshots": [
                {"path": "assets/CUSA01410/s_abc/screenshots/01.webp", "caption": "first"},
                {"path": "assets/CUSA01410/s_abc/screenshots/02.webp", "caption": "second"},
            ],
            "diagnostics": [
                {"path": "assets/CUSA01410/s_abc/logs/01-application.log.gz", "label": "Bachata application log"},
                {"path": "assets/CUSA01410/s_abc/logs/02-shadps4.log.gz", "label": "shadPS4 session log"},
            ],
        },
    }
    report.update(overrides)
    return report


class ReportIssueCommentTest(unittest.TestCase):
    def test_starts_with_marker_then_emulator_version(self):
        lines = build_comment(v2_report(), "games/CUSA01410/reports/s_abc.json", SHA).splitlines()
        self.assertEqual(lines[0], marker("s_abc"))
        self.assertTrue(lines[1].startswith("### Bachata S4 v0.2.4 · "))

    def test_embeds_only_first_screenshot_pinned_to_commit(self):
        body = build_comment(v2_report(), "games/CUSA01410/reports/s_abc.json", SHA)
        self.assertIn(f"raw.githubusercontent.com/JICA98/Bachata-S4-Compatibility/{SHA}/assets/CUSA01410/s_abc/screenshots/01.webp", body)
        self.assertNotIn("screenshots/02.webp", body)
        self.assertIn("1 more screenshot on the", body)

    def test_links_v2_diagnostics_and_v1_logs(self):
        body = build_comment(v2_report(), "games/CUSA01410/reports/s_abc.json", SHA)
        self.assertIn(f"[Bachata application log]({BASE}/assets/CUSA01410/s_abc/logs/01-application.log.gz)", body)
        self.assertIn(f"[shadPS4 session log]({BASE}/assets/CUSA01410/s_abc/logs/02-shadps4.log.gz)", body)
        v1 = v2_report(evidence={"logs": [{"path": "assets/x/logs/01-application.log.gz", "label": "App"}]})
        self.assertIn(f"[App]({BASE}/assets/x/logs/01-application.log.gz)", build_comment(v1, "games/x/reports/r.json", SHA))

    def test_no_evidence_still_links_report(self):
        body = build_comment(v2_report(evidence={}), "games/CUSA01410/reports/s_abc.json", SHA)
        self.assertNotIn("**Logs**", body)
        self.assertIn(f"[Report JSON]({BASE}/games/CUSA01410/reports/s_abc.json)", body)

    def test_emulator_version_fallbacks(self):
        self.assertEqual(emulator_version({"emulatorVersion": "0.2.1"}), "v0.2.1")
        self.assertEqual(emulator_version({"provenance": {"appBuild": "0.2.4"}}), "v0.2.4")
        self.assertEqual(emulator_version({}), "unreleased")
        self.assertEqual(emulator_version({"release": {"tag": "unreleased", "commit": "6f7e87b6417e"}, "provenance": {"appBuild": "0.2.4"}}), "v0.2.4 (6f7e87b)")

    def test_user_text_cannot_break_table_or_inject_html(self):
        body = build_comment(v2_report(device={"label": "A|B <img src=x>"}), "games/CUSA01410/reports/s_abc.json", SHA)
        self.assertIn("A\\|B &lt;img src=x&gt;", body)
        self.assertNotIn("<img", body)


if __name__ == "__main__":
    unittest.main()
