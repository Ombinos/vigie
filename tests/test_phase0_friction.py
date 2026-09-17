"""Phase 0 — Freeze truth: instrument friction claims vs live Arrival.

Does NOT claim resident walks. Proves instrument remediations are still true on disk.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import harness

import rank_display


ROOT = harness.ROOT


def _arrival(html: str) -> str:
    m = re.search(r'<section class="arrival"[^>]*>.*?</section>', html, re.S)
    assert m, "missing arrival"
    return m.group(0)


class Phase0FrictionDoc(unittest.TestCase):
    def test_friction_md_honest_dod(self) -> None:
        text = (ROOT / "FRICTION.md").read_text(encoding="utf-8")
        self.assertIn("Phase 0 is incomplete", text)
        self.assertIn("NOT MET — 0 / 5", text)
        self.assertIn("Resident walkthrough protocol", text)
        self.assertIn("| R1 |", text)
        self.assertIn("*awaiting*", text)
        # Must not pretend residents already walked
        self.assertNotIn("R1 completed", text.lower())
        self.assertIn("Kill list", text)
        self.assertIn("Instrument re-walk", text)


class Phase0InstrumentRemediations(unittest.TestCase):
    def setUp(self) -> None:
        issues = [
            {
                "scar": "marchand",
                "issue_id": "iss1",
                "question": "Quelles priorités pour Québec sous Marchand ?",
                "geo_focus": ["quebec-city"],
                "source_count": 3,
                "media_remix": True,
                "silence": {
                    "silent_count": 6,
                    "silent": [{"source_kind": "official"}],
                },
                "topic": {"topic": "housing"},
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
            }
        ]
        ranked = [
            {
                "id": "c1",
                "title": "Near",
                "url": "https://example.test/1",
                "source_id": "le-soleil",
                "rank_score": 0.9,
                "geo": "quebec-city",
                "enrich": {
                    "geo": {"geo": "quebec-city"},
                    "impacts": [
                        {
                            "units": [
                                {
                                    "kind": "housing_count",
                                    "value": 12,
                                    "unit": "logements",
                                    "raw": "12 logements",
                                }
                            ]
                        }
                    ],
                },
            }
        ]
        self.html = rank_display.render_html(
            ranked, "2026-09-16T00:00:00+00:00", issues=issues
        )
        self.arrival = _arrival(self.html)

    def test_f1_f6_f7_field_hidden_arrival_first(self) -> None:
        self.assertIn(".field-shell", self.html)
        self.assertRegex(self.html, r"\.field-shell\s*\{[^}]*display:\s*none")
        self.assertLess(
            self.html.find('id="arrival"'), self.html.find('id="command"')
        )
        self.assertLess(
            self.arrival.find('id="approaches"'),
            self.html.find('id="command"'),
        )

    def test_f2_brand_hero_signal(self) -> None:
        self.assertIn("arrival-brand", self.arrival)
        self.assertIn("clamp(3.6rem", self.html)
        self.assertLess(
            self.arrival.find("arrival-brand"), self.arrival.find("arrival-line")
        )

    def test_f3_composition_order(self) -> None:
        a = self.arrival
        self.assertLess(a.find("arrival-brand"), a.find('id="approaches"'))
        self.assertLess(a.find('id="approaches"'), a.find("arrival-cta"))
        self.assertLess(a.find("arrival-cta"), a.find('id="life-facets"'))

    def test_f4_silence_units_on_approach(self) -> None:
        self.assertIn("chip silence", self.arrival)
        self.assertIn("12 logements", self.arrival)
        self.assertIn("official quiet", self.arrival)

    def test_f5_no_cream_radial(self) -> None:
        low = self.html.lower()
        self.assertNotIn("#f3f0e8", low)
        self.assertNotIn("#f4f1ea", low)
        self.assertNotIn("radial-gradient", low)

    def test_f8_ops_collapsed(self) -> None:
        self.assertIn('id="arrival-ops"', self.arrival)
        self.assertIn("Clock &amp; method", self.arrival)
        # Clock lives inside ops details, not as a free hero strip before approaches
        self.assertLess(
            self.arrival.find('id="approaches"'), self.arrival.find('id="arrival-ops"')
        )
        self.assertLess(
            self.arrival.find("arrival-cta"), self.arrival.find('id="arrival-ops"')
        )

    def test_kill_list_still_holds(self) -> None:
        low = self.arrival.lower()
        self.assertNotIn("for-you", low)
        self.assertNotIn("for you", low)
        self.assertNotIn("trust meter", low)
        self.assertNotIn("bias meter", low)
        self.assertNotIn("class='score'", self.arrival)
        self.assertEqual(rank_display.W_IMPACT, 0.0)


if __name__ == "__main__":
    unittest.main()
