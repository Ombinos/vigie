"""Regression tests for the 2026-09-19 deep audit (renderer + collect/media).

Renderer review: display-spoofing strip in rank_display.esc, literal "<" kept in
resident_brief.plain, anomaly truncation disclosed, change-ledger malformed
evidence / missing counts, ambient Stage-fight fallback parity.

Collect/media review: linear _clean_person, plain_text trailing "&", edge_atlas
deep-JSON and 3^N-phrase bounds, media gate classification, numeric WZDX ids,
the empty-edition deploy gate, and feed-health foreign-metas as diagnosed facts.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import harness  # noqa: F401 - puts scripts/ on sys.path

import ambient_pulse
import change_ledger
import edge_atlas
import feed_health
import fetch_brief_media
import ingest_rss
import ingest_wzdx
import normalize
import rank_display
import resident_brief
import verify


class RendererFixes(unittest.TestCase):
    def test_esc_strips_display_spoofing_controls(self):
        out = rank_display.esc("Tramway\u202e reversed")
        self.assertNotIn("\u202e", out)
        self.assertIn("Tramway", out)

    def test_plain_keeps_literal_angle_brackets_but_strips_markup(self):
        self.assertEqual(resident_brief.plain("Budget: 5 < 6 > 7 M$"), "Budget: 5 < 6 > 7 M$")
        self.assertEqual(resident_brief.plain("<b>Gras</b>"), "Gras")

    def test_anomaly_truncation_is_announced(self):
        doc = {
            "method": resident_brief.ANOMALIES_METHOD,
            "anomaly_count": 5,
            "anomalies": [
                {"claim": f"c{n}", "rule_label": "Concentration", "evidence_event_ids": []}
                for n in range(5)
            ],
        }
        rows = resident_brief.valid_anomalies(doc)
        html = resident_brief.anomalies_html(rows, total=resident_brief.anomaly_total(doc, rows))
        self.assertEqual(html.count('<li class="rw-anomaly"'), 3)
        self.assertIn("+ 2 autres anomalies mesurées", html)

    def test_change_ledger_tolerates_malformed_evidence(self):
        led = change_ledger.diff_editions(
            [{"issue_id": "a", "evidence": ["x"], "item_count": 2}],
            [{"issue_id": "a", "item_count": 2}],
        )
        self.assertEqual(led["developed_count"], 0)

    def test_change_ledger_missing_previous_counts_never_inflate(self):
        led = change_ledger.diff_editions(
            [{"issue_id": "a", "item_count": 9, "source_count": 4}],
            [{"issue_id": "a"}],
        )
        self.assertEqual(led["developed_count"], 0)

    def test_ambient_stage_fight_ids_match_arrival_fallback(self):
        issues = [{"issue_id": "a"}, {"scar": "s"}, {"question": "no id"}]
        self.assertEqual(ambient_pulse.stage_fight_issue_ids(issues), ["a", "s", "idx-2"])


class CollectMediaFixes(unittest.TestCase):
    def test_clean_person_is_linear_on_a_huge_token(self):
        started = time.monotonic()
        out = ingest_rss._clean_person("x" * 200_000)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(len(out), 120)

    def test_clean_person_never_publishes_an_email(self):
        self.assertEqual(ingest_rss._clean_person("a@b.com (Jean Tremblay)"), "Jean Tremblay")
        self.assertIsNone(ingest_rss._clean_person("a@b.com"))

    def test_plain_text_keeps_trailing_ampersand(self):
        self.assertEqual(normalize.plain_text("P&O", 50), "P&O")
        self.assertEqual(normalize.plain_text("Santé &", 50), "Santé &")

    def test_edge_atlas_deep_json_snapshot_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path(tmp) / "deep.geojson"
            deep.write_text("[" * 200_000, encoding="utf-8")
            with patch.object(edge_atlas.ingest_wzdx, "latest_snapshot", return_value=deep):
                self.assertEqual(edge_atlas.load_geometry(Path(tmp), "src"), {})

    def test_phrase_variants_bounded_on_a_long_name(self):
        raw = "rue " + " ".join(f"token{n}" for n in range(24))
        started = time.monotonic()
        out = edge_atlas.phrase_variants(raw)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertTrue(out)

    def test_gate_active_tolerates_naive_retry_stamp(self):
        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        self.assertFalse(fetch_brief_media._gate_active({"retry_after": "2026-09-19T00:00:00"}, now))

    def test_wzdx_numeric_zero_id_is_kept(self):
        feature = {"id": 0, "properties": {"description": "x"},
                   "geometry": {"type": "Point", "coordinates": [-71.2, 46.8]}}
        event, reason = ingest_wzdx.parse_event(feature)
        self.assertIsNone(reason)
        self.assertEqual(event["event_id"], "0")

    def test_verify_refuses_an_empty_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(verify, "ROOT", Path(tmp)), \
                    self.assertRaisesRegex(RuntimeError, "empty edition"):
                verify.guard_nonempty_edition()

    def test_feed_health_foreign_meta_is_diagnosed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"
            source.mkdir()
            (source / "20260917T060000Z_aaaaaaaaaaaa.json").write_text(
                json.dumps(["not", "a", "dict"]), encoding="utf-8")
            timeline = feed_health.load_source_timeline(source)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["error"], "foreign meta")
        self.assertFalse(timeline[0]["ok"])


if __name__ == "__main__":
    unittest.main()
