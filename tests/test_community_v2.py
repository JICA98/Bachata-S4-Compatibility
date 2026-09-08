from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scoring import aggregate, confidence, dedupe_reports, latest_release_tag, recommended_setup, score_to_status
from build_app_data import canonical_soc, load_soc_registry, safe_report


def report(
    report_id: str,
    *,
    status: str = "ingame",
    release: str = "v0.2.0",
    tester: str = "tester-a",
    model: str = "Phone A",
    soc: str = "sm7475",
    tested_at: str = "2026-09-08T00:00:00Z",
    capture: str = "app-captured",
    fps: float | None = 24.0,
) -> dict:
    value = {
        "schemaVersion": 2,
        "reportId": report_id,
        "cusaId": "CUSA00900",
        "testedAt": tested_at,
        "status": status,
        "release": {"tag": release, "commit": "abcdef1"},
        "device": {
            "manufacturer": "Example",
            "model": model,
            "socId": soc,
            "socName": soc,
            "gpu": "Adreno",
            "androidVersion": "16",
            "ramBucketGb": 12,
        },
        "driver": {"type": "turnip", "name": "Mesa Turnip", "version": "26.3"},
        "config": {
            "settings": {},
            "requiredOverrides": {"graphics.resolutionScale": 0.75},
            "driverId": "turnip-test",
            "guestBackend": "FEX",
            "frameGenerationMode": "OFF",
            "fexPreset": "DEFAULT",
        },
        "result": {"summary": "Test result", "issues": []},
        "contributor": {"publicId": tester},
        "provenance": {"captureType": capture},
    }
    if fps is not None:
        value["performance"] = {"nativeAverageFps": fps, "testDurationSeconds": 300, "framePacing": "minor-stutter"}
    return value


class ReportV2SchemaTests(unittest.TestCase):
    def test_schema_is_closed_and_evidence_is_optional(self) -> None:
        schema = json.loads((ROOT / "schemas/report-v2.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 2)
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("evidence", schema["required"])
        self.assertIn("config", schema["required"])
        self.assertFalse(schema["properties"]["device"]["additionalProperties"])
        self.assertFalse(schema["properties"]["config"]["additionalProperties"])

    def test_public_config_disallows_nested_or_array_values(self) -> None:
        schema = json.loads((ROOT / "schemas/report-v2.schema.json").read_text(encoding="utf-8"))
        allowed = schema["properties"]["config"]["properties"]["settings"]["additionalProperties"]["type"]
        self.assertEqual(allowed, ["boolean", "number", "string"])


class ScoringTests(unittest.TestCase):
    def test_old_release_does_not_become_current_compatibility(self) -> None:
        result = aggregate([report("old", release="v0.1.9", status="playable")], "v0.2.0")
        self.assertFalse(result["hasCurrentReports"])
        self.assertIsNone(result["score"])
        self.assertEqual(result["status"], "unknown")

    def test_exact_soc_never_includes_other_soc(self) -> None:
        reports = [
            report("exact", soc="sm7475", status="nothing", tester="a"),
            report("fast", soc="sm8750", status="playable", tester="b", model="Phone B"),
        ]
        exact = aggregate(reports, "v0.2.0", exact_soc="sm7475")
        self.assertEqual(exact["reportCount"], 1)
        self.assertEqual(exact["status"], "nothing")

    def test_duplicate_same_tester_device_release_only_counts_latest(self) -> None:
        reports = [
            report("first", status="playable", tested_at="2026-09-01T00:00:00Z"),
            report("latest", status="nothing", tested_at="2026-09-08T00:00:00Z"),
        ]
        deduped = dedupe_reports(reports)
        self.assertEqual([r["reportId"] for r in deduped], ["latest"])
        self.assertEqual(aggregate(reports, "v0.2.0")["score"], 0)

    def test_frame_generated_output_is_not_used_in_status_or_native_score(self) -> None:
        value = report("fg", status="ingame", fps=27.0)
        value["performance"]["outputAverageFps"] = 54.0
        result = aggregate([value], "v0.2.0")
        self.assertEqual(result["score"], 75)

    def test_confidence_requires_independent_testers(self) -> None:
        reports = [report("a", tester="same", model="A"), report("b", tester="same", model="B")]
        self.assertEqual(confidence(reports), "low")
        reports.append(report("c", tester="other", model="B"))
        self.assertEqual(confidence(reports), "medium")

    def test_status_thresholds(self) -> None:
        self.assertEqual(score_to_status(0), "nothing")
        self.assertEqual(score_to_status(25), "boots")
        self.assertEqual(score_to_status(45), "menus")
        self.assertEqual(score_to_status(75), "ingame")
        self.assertEqual(score_to_status(100), "playable")

    def test_recommendation_needs_three_reports_and_two_testers_for_community_label(self) -> None:
        reports = [
            report("a", tester="one", model="A"),
            report("b", tester="two", model="B"),
            report("c", tester="three", model="C"),
        ]
        setup = recommended_setup(reports, "v0.2.0", "sm7475")
        self.assertIsNotNone(setup)
        self.assertEqual(setup["label"], "community-recommended")


class SocTests(unittest.TestCase):
    def test_registry_normalizes_sm7475_alias(self) -> None:
        _, aliases = load_soc_registry(ROOT)
        legacy = {
            "device": {"soc": "SM7475"},
        }
        self.assertEqual(canonical_soc(legacy, aliases), "sm7475")

    def test_safe_legacy_projection_separates_native_fps(self) -> None:
        _, aliases = load_soc_registry(ROOT)
        legacy = {
            "schemaVersion": 1,
            "reportId": "legacy-report",
            "cusaId": "CUSA00900",
            "testedAt": "2026-08-01T00:00:00Z",
            "status": "ingame",
            "release": {"tag": "v0.1.6", "commit": "abcdef1"},
            "device": {"manufacturer":"OnePlus","model":"CPH2649","soc":"SM8750","gpu":"Adreno 830","androidVersion":"16","ramGb":16},
            "driver": {"type":"turnip","name":"Mesa Turnip","version":"26.3"},
            "settings": {"resolutionScale": 1.0},
            "performance": {"averageFps": 21.0},
            "summary": "Legacy",
            "notes": "",
            "issues": [],
            "tester": "JICA98",
        }
        projected = safe_report(legacy, aliases)
        self.assertEqual(projected["device"]["socId"], "sm8750")
        self.assertEqual(projected["performance"]["nativeAverageFps"], 21.0)
        self.assertIsNone(projected["performance"]["outputAverageFps"])


class ReleaseTests(unittest.TestCase):
    def test_latest_release_ignores_prerelease_and_archived(self) -> None:
        index = {"releases": [
            {"tag":"v0.2.0","publishedAt":"2026-09-07T00:00:00Z","latest":True,"prerelease":False},
            {"tag":"v0.2.1","publishedAt":"2026-09-08T00:00:00Z","prerelease":True,"archived":True},
        ]}
        self.assertEqual(latest_release_tag(index), "v0.2.0")


if __name__ == "__main__":
    unittest.main()
