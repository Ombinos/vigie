"""Front-end v0.2 (2026-09-19): answer-first digest, self-hosted type,
dark/contrast adaptation, command palette, continuity, sticky wayfinding.

House law under test: no external request on any surface; the digest is
sentences (never a stat strip), links only to sections that exist, and is
byte-identical for the same inputs; the masthead never promotes roadworks.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import harness

import resident_brief as brief

ROOT = harness.ROOT
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _rows(local: int = 2, province: int = 1) -> list[dict]:
    return [{"geo": "quebec-city"}] * local + [{"geo": "quebec"}] * province


class AnswerFirstDigest(unittest.TestCase):
    def _digest(self, **over) -> str:
        args = dict(
            rows=_rows(),
            status={},
            ledger={"has_previous": True, "new_count": 1, "developed_count": 0, "quiet_count": 2},
            roadworks={"counts": {"active": 5}, "fetched_at": NOW.isoformat()},
            issues=[{"silence": {"silent": [{"institution_name": "Ville de Québec"}]}}],
            now=NOW,
            has_changes=True,
        )
        args.update(over)
        return brief.digest_html(**args)

    def test_measures_are_sentences_with_jump_links(self) -> None:
        html = self._digest()
        self.assertIn('<nav class="glance"', html)
        for needle in ('href="#stories"', 'href="#travaux"', 'href="#changements"', 'href="#dossiers"'):
            self.assertIn(needle, html)
        self.assertIn("<strong>2</strong> articles touchent Québec", html)
        self.assertIn("<strong>5</strong> entraves", html)
        self.assertIn("disparu", html)
        self.assertIn("Jamais « résolu »", html)

    def test_quiet_digest_is_empty_not_fabricated(self) -> None:
        self.assertEqual(self._digest(rows=[], ledger=None, roadworks=None, issues=[]), "")

    def test_no_link_to_a_section_that_is_absent(self) -> None:
        html = self._digest(ledger=None, roadworks=None, issues=[], has_changes=False)
        self.assertIn('href="#stories"', html)
        self.assertNotIn('href="#travaux"', html)
        self.assertNotIn('href="#changements"', html)
        self.assertNotIn('href="#dossiers"', html)

    def test_digest_is_deterministic(self) -> None:
        self.assertEqual(self._digest(), self._digest())


class DigestInPage(unittest.TestCase):
    def _page(self) -> str:
        issues = [{
            "issue_id": "i1", "scar": "s", "question": "Q ?",
            "geo_focus": ["quebec-city"], "source_count": 2,
            "silence": {"silent_count": 1, "silent": [{"institution_name": "Ville de Québec"}]},
            "tensions": [],
        }]
        page = brief.render_brief([], "2026-09-19T12:00:00+00:00", issues, None)
        self.assertIn('class="glance"', page)
        return page

    def test_digest_sits_before_the_controls(self) -> None:
        page = self._page()
        self.assertLess(page.index('class="glance"'), page.index('class="visit-strip'))


class SelfHostedType(unittest.TestCase):
    def test_brief_css_declares_the_voice(self) -> None:
        css = (ROOT / "public" / "assets" / "brief.css").read_text(encoding="utf-8")
        self.assertIn("'Newsreader'", css)
        self.assertIn("'Figtree'", css)
        self.assertIn("prefers-color-scheme:dark", css)
        self.assertIn("color-scheme:light dark", css)
        self.assertIn("position:sticky", css)
        self.assertIn("prefers-contrast:more", css)

    def test_font_faces_are_local_woff2(self) -> None:
        css = (ROOT / "public" / "assets" / "fonts.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("@font-face"), 4)
        self.assertIn("/assets/fonts/newsreader-latin.woff2", css)
        self.assertIn("/assets/fonts/figtree-latin.woff2", css)
        self.assertNotIn("http", css.replace("http://www.w3.org", ""))

    def test_no_surface_contacts_an_external_font_origin(self) -> None:
        for name in ("vercel.json", "public/vercel.json"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("fonts.googleapis", text)
            self.assertNotIn("fonts.gstatic", text)
        for name in ("index.html", "explorer.html", "morning.html"):
            path = ROOT / "public" / name
            if not path.is_file():
                continue
            html = path.read_text(encoding="utf-8")
            self.assertNotIn("fonts.googleapis", html)
            self.assertNotIn("fonts.gstatic", html)
            self.assertIn("/assets/fonts.css", html)


class WayfindingAndContinuity(unittest.TestCase):
    def test_index_carries_palette_and_continuity_hooks(self) -> None:
        path = ROOT / "public" / "index.html"
        if not path.is_file():
            self.skipTest("no generated index")
        html = path.read_text(encoding="utf-8")
        for needle in ('id="cmdk"', 'id="cmdk-input"', 'id="cmdk-open"', 'id="visit-list"'):
            self.assertIn(needle, html)
        head = html[: html.index("</head>")]
        self.assertIn('media="(prefers-color-scheme: dark)"', head)
        self.assertIn("/assets/fonts.css", head)

    def test_script_implements_palette_and_scout(self) -> None:
        js = (ROOT / "public" / "assets" / "brief.js").read_text(encoding="utf-8")
        for needle in ("cmdkChoose", "cmdkDraw", "IntersectionObserver", "aria-current", "visit-more"):
            self.assertIn(needle, js)
        # Storage contract and lean-scan guardrails must survive.
        self.assertIn("vigie.resident.v1", js)
        self.assertIn("setTimeout(render, 150)", js)
        self.assertNotIn("rows.some", js)

    def test_roadworks_never_in_the_masthead(self) -> None:
        path = ROOT / "public" / "index.html"
        if not path.is_file():
            self.skipTest("no generated index")
        html = path.read_text(encoding="utf-8")
        masthead = html[html.index('class="masthead"'):html.index("</header>")]
        self.assertNotIn('href="#travaux"', masthead)


if __name__ == "__main__":
    unittest.main()
