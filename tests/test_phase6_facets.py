"""Phase 6 — Life facets: published weights; reorder only; w_impact gated."""
from __future__ import annotations

import inspect
import json
import re
import unittest

import harness  # noqa: F401

import ambient_pulse
import life_facets
import rank_display


class Phase6LifeFacets(unittest.TestCase):
    def test_catalog_lockstep_with_facets_md(self) -> None:
        md = (harness.ROOT / "FACETS.md").read_text(encoding="utf-8")
        ok, errors = life_facets.catalog_matches_facets_md(md)
        self.assertTrue(ok, errors)
        self.assertIn("life-facets-v0.1", md)
        self.assertIn("w_impact stays gated", md.lower())
        self.assertIn("reorder Approaches", md)

    def test_w_impact_gated_and_score_item_clean(self) -> None:
        self.assertTrue(life_facets.w_impact_still_gated())
        self.assertEqual(rank_display.W_IMPACT, 0.0)
        src = inspect.getsource(rank_display.score_item)
        self.assertNotIn("life_facet", src.lower())
        self.assertNotIn("FACET_CATALOG", src)
        self.assertIn("W_IMPACT * 0.0", src)

    def test_reorder_preserves_data_i_contract(self) -> None:
        issues = [
            {
                "issue_id": "a",
                "scar": "a",
                "question": "A?",
                "topic": {"topic": "security"},
                "geo_focus": ["quebec"],
                "source_count": 2,
                "silence": {"silent_count": 1, "silent": []},
                "tensions": [],
            },
            {
                "issue_id": "b",
                "scar": "b",
                "question": "B housing?",
                "topic": {"topic": "housing"},
                "geo_focus": ["quebec-city"],
                "source_count": 2,
                "silence": {"silent_count": 1, "silent": []},
                "tensions": [],
            },
        ]
        ap = rank_display.build_approaches(issues, rank_display.build_continuity(issues, []))
        out = life_facets.reorder_approaches(ap, ["renter"], issues=issues)
        self.assertEqual(out[0]["issue_id"], "b")
        # store index / data-i stays the original Approaches index
        self.assertEqual(out[0]["index"], 1)
        self.assertEqual(out[0]["store_index"], 1)
        self.assertTrue(life_facets.same_approach_set(ap, out))
        html = rank_display.approach_button_html(out[0])
        self.assertIn("data-i='1'", html)
        self.assertIn("data-store-index='1'", html)

    def test_js_python_score_parity(self) -> None:
        ap = {
            "topic": "housing",
            "unit_kinds": ["housing_count"],
        }
        self.assertEqual(life_facets.facet_score(ap, ["renter"]), 1.35)
        self.assertEqual(life_facets.facet_score(ap, ["transit"]), 0.0)
        self.assertEqual(
            life_facets.facet_score({"topic": "transport", "unit_kinds": []}, ["transit"]),
            1.0,
        )

    def test_arrival_embeds_unit_kinds_and_gate_copy(self) -> None:
        issues = [
            {
                "issue_id": "h1",
                "scar": "housing",
                "question": "Housing?",
                "topic": {"topic": "housing"},
                "geo_focus": ["quebec-city"],
                "source_count": 2,
                "silence": {"silent_count": 1, "silent": []},
                "tensions": [
                    {"items": [{"candidate_id": "c1", "title": "x", "url": "https://e.test/1"}]}
                ],
            }
        ]
        ranked = [
            {
                "id": "c1",
                "title": "Loyer",
                "url": "https://e.test/1",
                "enrich": {
                    "geo": {"geo": "quebec-city"},
                    "impacts": [
                        {
                            "units": [
                                {
                                    "kind": "housing_count",
                                    "value": 10,
                                    "unit": "logements",
                                    "raw": "10 logements",
                                }
                            ]
                        }
                    ],
                },
            }
        ]
        html = rank_display.render_html(ranked, "2026-09-16T00:00:00+00:00", issues=issues)
        self.assertIn("data-unit-kinds='housing_count'", html)
        self.assertIn("w_impact gated", html)
        self.assertIn("data-unit-kinds", html)
        self.assertIn('id="vigie-facets"', html)
        bundle = json.loads(
            re.search(r'id="vigie-facets">(.*?)</script>', html, re.S).group(1)
        )
        self.assertEqual(bundle["catalog"]["method_file"], "FACETS.md")
        self.assertIn("w_impact stays gated", bundle["catalog"]["note"])

    def test_ambient_ignores_facets_stays_store_order(self) -> None:
        issues = [
            {
                "issue_id": "a-secure",
                "scar": "sec",
                "question": "Security?",
                "topic": {"topic": "security"},
                "geo_focus": ["quebec"],
                "source_count": 2,
                "clustered_at": "2026-09-16T12:00:00+00:00",
                "silence": {"silent_count": 1, "silent": []},
                "tensions": [],
            },
            {
                "issue_id": "b-house",
                "scar": "house",
                "question": "Housing?",
                "topic": {"topic": "housing"},
                "geo_focus": ["quebec-city"],
                "source_count": 2,
                "silence": {"silent_count": 1, "silent": []},
                "tensions": [],
            },
        ]
        digest = ambient_pulse.build_digest(issues, [], built_at="t0")
        # Store order — renter would have put housing first if ambient applied facets
        self.assertEqual(digest["identity"]["issue_ids"], ["a-secure", "b-house"])
        reordered = life_facets.reorder_approaches(
            digest["approaches"], ["renter"], issues=issues
        )
        self.assertEqual(reordered[0]["issue_id"], "b-house")
        self.assertNotEqual(
            [a["issue_id"] for a in digest["approaches"]],
            [a["issue_id"] for a in reordered],
        )


if __name__ == "__main__":
    unittest.main()
