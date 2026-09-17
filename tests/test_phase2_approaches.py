"""Phase 2 — Approach objects: geo + voices + silence + units without Stage."""
from __future__ import annotations

import re
import unittest

import harness  # noqa: F401

import rank_display


def _arrival(html: str) -> str:
    m = re.search(r'<section class="arrival"[^>]*>.*?</section>', html, re.S)
    assert m, "missing arrival"
    return m.group(0)


def _fixture() -> tuple[list[dict], list[dict]]:
    ranked = [
        {
            "id": "c1",
            "title": "Loyer",
            "url": "https://example.test/1",
            "source_id": "le-soleil",
            "rank_score": 0.5,
            "geo": "quebec-city",
            "enrich": {
                "geo": {"geo": "quebec-city"},
                "impacts": [
                    {
                        "units": [
                            {
                                "kind": "housing_count",
                                "value": 120,
                                "unit": "logements",
                                "raw": "120 logements",
                            }
                        ]
                    }
                ],
            },
        }
    ]
    issues = [
        {
            "issue_id": "iss-house",
            "scar": "housing",
            "question": "Le logement abordable avance-t-il ?",
            "geo_focus": ["quebec-city"],
            "source_count": 3,
            "media_remix": True,
            "topic": {"topic": "housing"},
            "silence": {
                "silent_count": 6,
                "silent": [
                    {
                        "source_kind": "official",
                        "institution_id": "ville-quebec",
                        "institution_name": "Ville de Québec",
                    },
                    {
                        "source_kind": "official",
                        "institution_id": "hydro-quebec",
                        "institution_name": "Hydro-Québec",
                    },
                    {
                        "source_kind": "media",
                        "institution_id": "le-devoir",
                        "institution_name": "Le Devoir",
                    },
                ],
            },
            "tensions": [
                {
                    "items": [
                        {
                            "candidate_id": "c1",
                            "title": "x",
                            "url": "https://example.test/1",
                        }
                    ]
                }
            ],
        },
        {
            "issue_id": "iss-empty-units",
            "scar": "security",
            "question": "Security scar without units?",
            "geo_focus": ["quebec"],
            "source_count": 2,
            "topic": {"topic": "security"},
            "silence": {"silent_count": 7, "silent": []},
            "tensions": [],
        },
    ]
    return issues, ranked


class Phase2ApproachObject(unittest.TestCase):
    def test_build_approaches_carries_glance_fields(self) -> None:
        issues, ranked = _fixture()
        ap = rank_display.build_approaches(
            issues, rank_display.build_continuity(issues, ranked)
        )
        self.assertEqual(len(ap), 2)
        self.assertEqual(ap[0]["nest"], "near")
        self.assertEqual(ap[0]["voices"], 3)
        self.assertEqual(ap[0]["silent"], 6)
        self.assertEqual(ap[0]["official_silent"], 2)
        self.assertEqual(
            ap[0]["quiet_names"],
            ["Ville de Québec", "Hydro-Québec"],
        )
        self.assertEqual(ap[0]["units"][0]["raw"], "120 logements")
        self.assertEqual(ap[1]["units"], [])
        self.assertEqual(ap[1]["nest"], "province")

    def test_arrival_shows_unit_and_silence_without_stage(self) -> None:
        issues, ranked = _fixture()
        html = rank_display.render_html(
            ranked, "2026-09-16T00:00:00+00:00", issues=issues
        )
        arrival = _arrival(html)
        # No archive cards in Arrival
        self.assertNotIn("class='card'", arrival)
        self.assertNotIn('class="card"', arrival)
        # Geo + voices + silence always
        self.assertIn("Near me", arrival)
        self.assertIn("chip voices", arrival)
        self.assertIn("3 voices", arrival)
        self.assertIn("chip silence", arrival)
        self.assertIn("6 silent", arrival)
        self.assertIn("official quiet", arrival)
        # Units visible on Arrival (not Stage-only)
        self.assertIn("120 logements", arrival)
        self.assertIn("chip unit", arrival)
        # Empty-units Approach still surfaces honest empty
        self.assertIn("no units yet", arrival)
        # Official quiet names glanceable
        self.assertIn("approach-silence-preview", arrival)
        self.assertIn("Ville de Québec", arrival)
        self.assertIn("Hydro-Québec", arrival)
        # Stage fight-arc exists later — not required for Approach glance
        self.assertLess(arrival.find("120 logements"), html.find("fight-arc"))
        self.assertEqual(rank_display.W_IMPACT, 0.0)

    def test_meta_chips_always_include_silence_and_unit_slot(self) -> None:
        chips = rank_display.approach_meta_chips_html(
            {
                "nest": "linked",
                "voices": 0,
                "silent": 0,
                "official_silent": 0,
                "units": [],
            }
        )
        self.assertIn("0 silent", chips)
        self.assertIn("no units yet", chips)
        self.assertIn("Linked", chips)

    def test_store_order_not_re_ranked(self) -> None:
        issues, ranked = _fixture()
        # Reverse would fail if someone sorted by score
        ap = rank_display.build_approaches(
            issues, rank_display.build_continuity(issues, ranked)
        )
        self.assertEqual(
            [a["issue_id"] for a in ap],
            ["iss-house", "iss-empty-units"],
        )


if __name__ == "__main__":
    unittest.main()
