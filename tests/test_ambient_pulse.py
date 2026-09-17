"""Ambient morning pulse — store-identical digest (Phase 5).

Never a second ranking. Never LLM. Never For You.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import harness

import ambient_pulse
import rank_display


def _sample_store() -> tuple[list[dict], list[dict]]:
    ranked = [
        {
            "id": "c1",
            "title": "Near me sample",
            "url": "https://example.test/1",
            "source_id": "le-soleil",
            "source_name": "Le Soleil",
            "nest_role": "primary",
            "geo": "quebec-city",
            "rank_score": 0.9,
            "enrich": {
                "geo": {"geo": "quebec-city"},
                "topics": [{"topic": "housing"}],
                "impacts": [
                    {
                        "label": "housing",
                        "units": [
                            {
                                "kind": "housing_count",
                                "value": 120,
                                "unit": "logements",
                                "raw": "120 logements",
                            }
                        ],
                    }
                ],
            },
        },
        {
            "id": "c2",
            "title": "High score decoy — must not reorder Approaches",
            "url": "https://example.test/2",
            "source_id": "cbc-montreal",
            "rank_score": 99.0,
            "geo": "linked",
            "enrich": {"geo": {"geo": "linked"}},
        },
    ]
    issues = [
        {
            "issue_id": "scar-a",
            "scar": "marchand",
            "question": "Quelles priorités pour Québec sous Marchand ?",
            "geo_focus": ["quebec-city"],
            "source_count": 3,
            "media_remix": True,
            "clustered_at": "2026-09-16T12:00:00+00:00",
            "silence": {
                "silent_count": 6,
                "silent": [
                    {"source_kind": "official", "institution_id": "ville-quebec"},
                    {"source_kind": "official", "institution_id": "hydro-quebec"},
                    {"source_kind": "media", "institution_id": "le-devoir"},
                ],
            },
            "topic": {"topic": "other"},
            "tensions": [
                {
                    "label": "voice:Le Soleil",
                    "source_kind": "media",
                    "items": [
                        {
                            "candidate_id": "c1",
                            "title": "x",
                            "url": "https://example.test/1",
                        }
                    ],
                }
            ],
        },
        {
            "issue_id": "scar-b",
            "scar": "housing",
            "question": "Le logement abordable avance-t-il ?",
            "geo_focus": ["quebec"],
            "source_count": 2,
            "media_remix": False,
            "silence": {"silent_count": 7, "silent": []},
            "tensions": [],
        },
        {
            "issue_id": "scar-c",
            "scar": "hydro",
            "question": "Les tarifs Hydro tiennent-ils ?",
            "geo_focus": ["linked"],
            "source_count": 2,
            "silence": {"silent_count": 5, "silent": []},
            "tensions": [],
        },
    ]
    return issues, ranked


class DigestIdentity(unittest.TestCase):
    def test_digest_identical_to_build_approaches(self) -> None:
        issues, ranked = _sample_store()
        digest = ambient_pulse.build_digest(
            issues, ranked, ranked_at="2026-09-16T12:01:00+00:00", built_at="2026-09-16T12:02:00+00:00"
        )
        continuity = rank_display.build_continuity(issues, ranked)
        approaches = rank_display.build_approaches(issues, continuity)
        self.assertTrue(ambient_pulse.digest_matches_approaches(digest, approaches))
        self.assertEqual(digest["kind"], "morning_digest")
        self.assertEqual(digest["method"], ambient_pulse.METHOD)
        self.assertIn("Not a second ranking", digest["note"])
        self.assertIn("No personalization feed", digest["note"])
        self.assertNotIn("for-you", digest["note"].lower())
        self.assertEqual(
            [a["question"] for a in digest["approaches"]],
            [
                "Quelles priorités pour Québec sous Marchand ?",
                "Le logement abordable avance-t-il ?",
                "Les tarifs Hydro tiennent-ils ?",
            ],
        )
        # Rank score must not reorder Approaches (c2 score 99 is irrelevant)
        self.assertEqual(digest["identity"]["issue_ids"], ["scar-a", "scar-b", "scar-c"])
        self.assertEqual(digest["pulse"]["clustered_at"], "2026-09-16T12:00:00+00:00")
        self.assertEqual(len(digest["pulse"]["approaches"]), 3)

    def test_store_order_not_rank_order(self) -> None:
        issues, ranked = _sample_store()
        # Shuffle issues into reverse store order vs any score fantasy
        issues = list(reversed(issues))
        digest = ambient_pulse.build_digest(issues, ranked, built_at="t0")
        self.assertEqual(
            digest["identity"]["issue_ids"],
            ["scar-c", "scar-b", "scar-a"],
        )
        continuity = rank_display.build_continuity(issues, ranked)
        approaches = rank_display.build_approaches(issues, continuity)
        self.assertTrue(ambient_pulse.digest_matches_approaches(digest, approaches))

    def test_max_five_same_as_arrival(self) -> None:
        issues = [
            {
                "issue_id": f"i{i}",
                "scar": f"s{i}",
                "question": f"Q{i}?",
                "geo_focus": ["quebec"],
                "source_count": 2,
                "silence": {"silent_count": 1, "silent": []},
                "tensions": [],
            }
            for i in range(8)
        ]
        digest = ambient_pulse.build_digest(issues, [], built_at="t0")
        self.assertEqual(len(digest["approaches"]), 5)
        self.assertEqual(digest["identity"]["questions"], [f"Q{i}?" for i in range(5)])


class DigestRender(unittest.TestCase):
    def test_html_and_txt_carry_store_questions(self) -> None:
        issues, ranked = _sample_store()
        digest = ambient_pulse.build_digest(issues, ranked, built_at="t0")
        html = ambient_pulse.render_morning_html(digest)
        txt = ambient_pulse.render_morning_txt(digest)
        self.assertIn("Morning pulse", html)
        self.assertIn("Vigie", html)
        self.assertIn("Quelles priorités pour Québec sous Marchand ?", html)
        self.assertIn("/explorer.html?approach=0", html)
        self.assertIn("120 logements", html)
        self.assertIn("official quiet", html)
        self.assertIn("id=\"vigie-pulse\"", html)
        self.assertIn("Des sources réunies ne sont pas des confirmations indépendantes", html)
        self.assertIn("silence éditorial", html)
        self.assertIn("ne sont pas les dates de publication", html)
        self.assertIn("same-store-as-arrival", html)
        low = html.lower()
        self.assertNotIn("for you", low)
        self.assertNotIn("for-you", low)
        self.assertIn("not a second ranking", low)
        self.assertIn("no personalization feed", low)
        self.assertIn("Not a second ranking", html)
        self.assertIn("Quelles priorités pour Québec sous Marchand ?", txt)
        self.assertIn("Le logement abordable avance-t-il ?", txt)
        self.assertIn(ambient_pulse.NOTE, txt)
        self.assertIn(ambient_pulse.TRUST_NOTE, txt)

    def test_attributed_headline_keeps_source_origin(self) -> None:
        issues, ranked = _sample_store()
        issues[0]["label_kind"] = "attributed_headline"
        issues[0]["label_source"] = {"source_name": "Le Soleil", "source_id": "le-soleil"}
        digest = ambient_pulse.build_digest(issues, ranked)
        html = ambient_pulse.render_morning_html(digest)
        self.assertIn("Titre de Le Soleil", html)
        self.assertIn("rapprochement proposé", html)
        self.assertIn("Titre de Le Soleil", ambient_pulse.render_morning_txt(digest))
        self.assertIn(ambient_pulse.TRUST_NOTE, ambient_pulse.render_morning_widget(digest))
        self.assertIn('/explorer.html?approach=0', html)

    def test_link_html_hooks(self) -> None:
        html = ambient_pulse.digest_approach_link_html(
            {
                "index": 1,
                "issue_id": "scar-b",
                "question": "Le logement abordable avance-t-il ?",
                "nest": "province",
                "voices": 2,
                "silent": 7,
                "official_silent": 0,
                "remix": False,
                "units": [],
            }
        )
        self.assertIn("href=\"/explorer.html?approach=1\"", html)
        self.assertIn("data-issue-id='scar-b'", html)
        self.assertIn("data-fp='2|7|0|0'", html)
        self.assertIn("Province", html)


class EmitFromStore(unittest.TestCase):
    def test_emit_writes_twin_files_and_refuses_drift(self) -> None:
        issues, ranked = _sample_store()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_json = tmp_path / "latest_morning.json"
            out_txt = tmp_path / "latest_morning.txt"
            out_widget = tmp_path / "latest_morning.widget.txt"
            out_html = tmp_path / "morning.html"
            with mock.patch.multiple(
                ambient_pulse,
                OUT_DIR=tmp_path,
                OUT_JSON=out_json,
                OUT_TXT=out_txt,
                OUT_WIDGET=out_widget,
                OUT_HTML=out_html,
            ):
                digest = ambient_pulse.emit_from_store(
                    issues=issues,
                    ranked=ranked,
                    ranked_at="2026-09-16T12:01:00+00:00",
                    built_at="2026-09-16T12:02:00+00:00",
                )
            self.assertTrue(out_json.is_file())
            self.assertTrue(out_txt.is_file())
            self.assertTrue(out_widget.is_file())
            self.assertTrue(out_html.is_file())
            loaded = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(
                ambient_pulse.digest_identity_tuple(loaded),
                ambient_pulse.digest_identity_tuple(digest),
            )
            self.assertIn("Morning pulse", out_html.read_text(encoding="utf-8"))
            self.assertIn("no second ranking", out_widget.read_text(encoding="utf-8").lower())
            self.assertIn("120 logements", out_widget.read_text(encoding="utf-8"))

    def test_emit_refuses_identity_failure(self) -> None:
        issues, ranked = _sample_store()
        broken = ambient_pulse.build_digest(issues, ranked, built_at="t0")
        broken["identity"]["issue_ids"] = ["tampered"]
        with mock.patch.object(ambient_pulse, "build_digest", return_value=broken):
            with self.assertRaises(SystemExit) as ctx:
                ambient_pulse.emit_from_store(issues=issues, ranked=ranked, built_at="t0")
        self.assertIn("identity failed", str(ctx.exception))

    def test_emit_refuses_pulse_twin_failure(self) -> None:
        issues, ranked = _sample_store()
        broken = ambient_pulse.build_digest(issues, ranked, built_at="t0")
        broken["pulse"] = {"clustered_at": "x", "approaches": []}
        with mock.patch.object(ambient_pulse, "build_digest", return_value=broken):
            with self.assertRaises(SystemExit) as ctx:
                ambient_pulse.emit_from_store(issues=issues, ranked=ranked, built_at="t0")
        self.assertIn("pulse twin failed", str(ctx.exception))

    def test_emit_refuses_stage_twin_failure(self) -> None:
        issues, ranked = _sample_store()
        broken = ambient_pulse.build_digest(issues, ranked, built_at="t0")
        # Keep identity matching approaches but break Stage fight set check
        with mock.patch.object(ambient_pulse, "build_digest", return_value=broken):
            with mock.patch.object(
                ambient_pulse,
                "digest_matches_stage_fights",
                return_value=False,
            ):
                with self.assertRaises(SystemExit) as ctx:
                    ambient_pulse.emit_from_store(issues=issues, ranked=ranked, built_at="t0")
        self.assertIn("Stage fight twin failed", str(ctx.exception))

    def test_load_store_and_emit_default_path(self) -> None:
        issues, ranked = _sample_store()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            issues_path = tmp_path / "latest_issues.json"
            ranked_path = tmp_path / "latest_ranked.json"
            issues_path.write_text(
                json.dumps({"issues": issues}, ensure_ascii=False), encoding="utf-8"
            )
            ranked_path.write_text(
                json.dumps(
                    {"ranked_at": "2026-09-16T12:01:00+00:00", "candidates": ranked},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            out_json = tmp_path / "pulse" / "latest_morning.json"
            out_txt = tmp_path / "pulse" / "latest_morning.txt"
            out_widget = tmp_path / "pulse" / "latest_morning.widget.txt"
            out_html = tmp_path / "morning.html"
            with mock.patch.multiple(
                ambient_pulse,
                ISSUES=issues_path,
                RANKED=ranked_path,
                OUT_DIR=tmp_path / "pulse",
                OUT_JSON=out_json,
                OUT_TXT=out_txt,
                OUT_WIDGET=out_widget,
                OUT_HTML=out_html,
            ):
                loaded_i, loaded_r, loaded_at = ambient_pulse.load_store()
                self.assertEqual(len(loaded_i), 3)
                self.assertEqual(len(loaded_r), 2)
                self.assertEqual(loaded_at, "2026-09-16T12:01:00+00:00")
                digest = ambient_pulse.emit_from_store(built_at="t-load")
                self.assertEqual(digest["identity"]["issue_ids"][0], "scar-a")
                self.assertEqual(ambient_pulse.main(), 0)
            self.assertTrue(out_html.is_file())

    def test_main_missing_store_exits(self) -> None:
        missing = Path("/no/such/vigie-store.json")
        with mock.patch.multiple(ambient_pulse, ISSUES=missing, RANKED=missing):
            with self.assertRaises(SystemExit) as ctx:
                ambient_pulse.main()
        self.assertIn("Missing store", str(ctx.exception))

    def test_empty_approaches_html_and_txt_edges(self) -> None:
        digest = ambient_pulse.build_digest([], [], built_at="t0")
        html = ambient_pulse.render_morning_html(digest)
        self.assertIn("No Approaches yet", html)
        # silent None + empty unit raw + default nest
        link = ambient_pulse.digest_approach_link_html(
            {
                "index": 0,
                "issue_id": "x",
                "question": "",
                "nest": "weird-nest",
                "voices": 0,
                "silent": None,
                "official_silent": 0,
                "remix": False,
                "units": [{"raw": "  "}, {"raw": "ok"}],
            }
        )
        self.assertIn("Issue", link)
        self.assertIn("weird-nest", link)
        self.assertIn("ok", link)
        # Phase 2: silence always glanceable (None → 0)
        self.assertIn("chip silence", link)
        self.assertIn("0 silent", link)
        txt = ambient_pulse.render_morning_txt(
            {
                "clustered_at": "t",
                "method": "m",
                "approaches": [
                    {
                        "nest": "near",
                        "question": "Q?",
                        "voices": 1,
                        "silent": None,
                        "units": [{"raw": ""}],
                    }
                ],
            }
        )
        self.assertIn("Q?", txt)
        self.assertIn("0 silent", txt)
        self.assertIn("no units yet", txt)
        widget = ambient_pulse.render_morning_widget(
            {
                "clustered_at": "2026-09-16T22:40:14+00:00",
                "approaches": [
                    {
                        "nest": "near",
                        "question": "Q?",
                        "voices": 1,
                        "silent": None,
                        "units": [],
                    }
                ],
            }
        )
        self.assertIn("Vigie morning", widget)
        self.assertIn("no second ranking", widget)
        self.assertIn("1v/0s", widget)
        self.assertIn("no units yet", widget)
        # built_at default path
        d2 = ambient_pulse.build_digest([], [], clustered_at="forced")
        self.assertEqual(d2["clustered_at"], "forced")
        self.assertTrue(d2["built_at"])


class ArrivalLinksMorning(unittest.TestCase):
    def test_arrival_cta_links_morning_and_deep_link_js(self) -> None:
        issues, ranked = _sample_store()
        html = rank_display.render_html(
            ranked, "2026-09-16T00:00:00+00:00", issues=issues
        )
        self.assertIn('href="/morning.html"', html)
        self.assertIn("Morning pulse", html)
        self.assertIn('params.get("approach")', html)
        self.assertEqual(rank_display.W_IMPACT, 0.0)


if __name__ == "__main__":
    unittest.main()
