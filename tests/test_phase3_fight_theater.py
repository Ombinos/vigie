"""Phase 3 — Fight theater: who spoke / who didn't in one Stage glance."""
from __future__ import annotations

import re
import unittest

import harness  # noqa: F401

import rank_display


def _fixture_issue() -> dict:
    return {
        "issue_id": "iss-fight",
        "scar": "housing",
        "question": "Le logement abordable avance-t-il ?",
        "topic": {"topic": "housing"},
        "source_count": 2,
        "item_count": 3,
        "media_remix": True,
        "official_voice_count": 0,
        "status": "proposed",
        "sources": ["le-soleil", "cbc"],
        "tensions": [
            {
                "label": "voice:Le Soleil",
                "institution_id": "le-soleil",
                "institution_name": "Le Soleil",
                "source_kind": "media",
                "items": [
                    {
                        "candidate_id": "c1",
                        "title": "120 logements annoncés",
                        "url": "https://example.test/1",
                        "claims": [
                            {
                                "quote": "120 logements seront livrés",
                                "speaker": "maire",
                            }
                        ],
                    }
                ],
            },
            {
                "label": "voice:CBC",
                "institution_id": "cbc",
                "institution_name": "CBC",
                "source_kind": "media",
                "items": [
                    {
                        "candidate_id": "c2",
                        "title": "Housing plan",
                        "url": "https://example.test/2",
                        "claims": [],
                    }
                ],
            },
        ],
        "silence": {
            "spoke_count": 2,
            "silent_count": 3,
            "enabled_count": 5,
            "silent": [
                {
                    "institution_id": "ville-quebec",
                    "institution_name": "Ville de Québec",
                    "source_kind": "official",
                    "nest_role": "primary",
                },
                {
                    "institution_id": "hydro-quebec",
                    "institution_name": "Hydro-Québec",
                    "source_kind": "official",
                    "nest_role": "province",
                },
                {
                    "institution_id": "le-devoir",
                    "institution_name": "Le Devoir",
                    "source_kind": "media",
                    "nest_role": "province",
                },
            ],
        },
    }


class Phase3FightTheater(unittest.TestCase):
    def test_arc_lists_spoke_before_confrontation(self) -> None:
        html = rank_display.issue_stage_html(_fixture_issue())
        self.assertIn("fight-theater", html)
        self.assertIn("fight-arc", html)
        self.assertIn("Who spoke and who did not", html)
        self.assertIn("Spoke", html)
        self.assertIn("Did not speak", html)
        # Institution names — not feed desks
        self.assertIn("Le Soleil", html)
        self.assertIn("CBC", html)
        self.assertIn("Ville de Québec", html)
        self.assertIn("Hydro-Québec", html)
        self.assertIn("Le Devoir", html)
        # Arc before long voice archaeology
        arc_i = html.find("fight-arc")
        confront_i = html.find("confrontation-title")
        voice_i = html.find("voice-panel")
        self.assertGreater(arc_i, 0)
        self.assertGreater(confront_i, arc_i)
        self.assertGreater(voice_i, confront_i)
        # Dense status soup removed
        self.assertNotIn("status:proposed", html)
        self.assertNotIn("items:3", html)
        self.assertIn("2 spoke", html)
        self.assertIn("3 silent", html)
        # No bias meter
        low = html.lower()
        self.assertIn("not a bias meter", low)
        self.assertNotIn("for you", low)
        self.assertEqual(rank_display.W_IMPACT, 0.0)

    def test_glance_budget_under_ten_seconds_of_chrome(self) -> None:
        """Instrument proxy for <10s: spoke+quiet names appear in first Stage chunk."""
        html = rank_display.issue_stage_html(_fixture_issue())
        # First 1800 chars of Stage body must already name speakers + a quiet official
        head = html[:1800]
        self.assertIn("Le Soleil", head)
        self.assertIn("CBC", head)
        self.assertIn("Ville de Québec", head)
        self.assertIn("Did not speak", head)

    def test_empty_silence_still_honest(self) -> None:
        iss = _fixture_issue()
        iss["silence"] = {
            "spoke_count": 2,
            "silent_count": 0,
            "silent": [],
        }
        html = rank_display.fight_theater_arc_html(iss)
        self.assertIn("No enabled institution absent", html)

    def test_live_stage_has_fight_arc(self) -> None:
        path = harness.ROOT / "public" / "explorer.html"
        if not path.is_file():
            self.skipTest("no lookout html")
        html = path.read_text(encoding="utf-8")
        stages = re.findall(
            r"<article class='issue-stage fight-theater'[^>]*>.*?</article>",
            html,
            re.S,
        )
        if not stages:
            self.skipTest("lookout not rebuilt with fight theater")
        for st in stages[:3]:
            self.assertIn("fight-arc", st)
            self.assertIn("Spoke", st)
            self.assertIn("Did not speak", st)
            # Arc before confrontation copy
            self.assertLess(st.find("fight-arc"), st.find("confrontation-title"))


if __name__ == "__main__":
    unittest.main()
