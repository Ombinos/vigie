"""Phase 1 — Arrival Lookout: first viewport DoD."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import harness

import rank_display


ROOT = harness.ROOT


def _body(html: str) -> str:
    return html.split("<body>", 1)[-1]


def _arrival(html: str) -> str:
    m = re.search(r'<section class="arrival"[^>]*>.*?</section>', html, re.S)
    assert m, "missing arrival"
    return m.group(0)


class Phase1ArrivalDoD(unittest.TestCase):
    def setUp(self) -> None:
        issues = [
            {
                "scar": "marchand",
                "issue_id": "iss1",
                "question": "Quelles priorités pour Québec sous Marchand ?",
                "geo_focus": ["quebec-city"],
                "source_count": 3,
                "silence": {"silent_count": 6, "silent": []},
                "topic": {"topic": "other"},
                "tensions": [],
            }
        ]
        self.html = rank_display.render_html([], "2026-09-16T00:00:00+00:00", issues=issues)
        self.arrival = _arrival(self.html)
        self.body = _body(self.html)

    def test_single_first_viewport_composition(self) -> None:
        a = self.arrival
        self.assertIn('data-phase="arrival-v0.1"', a)
        self.assertIn("arrival-brand", a)
        self.assertIn("arrival-line", a)
        self.assertIn('id="approaches"', a)
        self.assertIn("Open lookout field", a)
        # brand → line → approaches → cta (one composition)
        self.assertLess(a.find("arrival-brand"), a.find("arrival-line"))
        self.assertLess(a.find("arrival-line"), a.find('id="approaches"'))
        self.assertLess(a.find('id="approaches"'), a.find("arrival-cta"))
        # single h1 = the question line
        self.assertEqual(len(re.findall(r"<h1\b", a)), 1)
        self.assertIn('<h1 class="arrival-line">', a)

    def test_no_dashboard_in_first_paint(self) -> None:
        # Field inert until assent
        self.assertRegex(
            self.html,
            r'id="field-shell"[^>]*(hidden|aria-hidden="true")',
        )
        self.assertIn('id="field-shell" hidden', self.html)
        self.assertIn('aria-hidden="true"', self.html)
        self.assertRegex(self.html, r"\.field-shell\s*\{[^}]*display:\s*none")
        # Dashboard markers not inside Arrival
        self.assertNotIn('id="command"', self.arrival)
        self.assertNotIn("Impact Radar", self.arrival)
        self.assertNotIn('id="deck"', self.arrival)
        self.assertNotIn("class='score'", self.arrival)
        # Site footer not in first-paint surface
        self.assertIn("footer.site-foot", self.html)
        self.assertIn("body.field-open footer.site-foot", self.html)
        # openField reveals shell
        self.assertIn("shell.hidden = false", self.html)
        self.assertIn('aria-hidden", "false"', self.html)

    def test_mobile_and_seo_basics(self) -> None:
        self.assertIn('name="viewport"', self.html)
        self.assertIn("width=device-width", self.html)
        self.assertIn('name="description"', self.html)
        self.assertIn('rel="icon"', self.html)
        self.assertIn("/favicon.svg", self.html)
        self.assertIn('class="skip"', self.html)
        self.assertIn('href="#approaches"', self.html)
        self.assertTrue((ROOT / "public" / "favicon.svg").is_file())
        self.assertEqual(rank_display.W_IMPACT, 0.0)

    def test_kill_list_on_arrival(self) -> None:
        low = self.arrival.lower()
        self.assertNotIn("for-you", low)
        self.assertNotIn("for you", low)
        self.assertNotIn("trust meter", low)
        self.assertNotIn("bias meter", low)


if __name__ == "__main__":
    unittest.main()
