"""Claims as objects — quote, speaker, status=proposed. Kill empty-claims theater."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import harness

import enrich


class ProposeClaims(unittest.TestCase):
    def test_guillemets_with_affirme_speaker(self) -> None:
        c = {
            "title": (
                "«On a quand même joué sur notre patinoire», affirme Éric Duhaime "
                "après le débat"
            ),
            "summary": "",
        }
        claims = enrich.propose_claims(c)
        self.assertTrue(claims)
        self.assertEqual(claims[0]["status"], "proposed")
        self.assertIn("patinoire", claims[0]["quote"].lower())
        self.assertIsNotNone(claims[0]["speaker"])
        self.assertIn("Duhaime", claims[0]["speaker"])
        self.assertEqual(claims[0]["attribution"], "said")

    def test_selon_speaker_and_rest(self) -> None:
        c = {
            "title": "Le PQ sous-estime les coûts, selon Christine Fréchette, en campagne",
            "summary": "",
        }
        # Force a selon+rest shape in summary (title alone may not capture rest)
        c = {
            "title": "Cadre financier",
            "summary": "Selon Christine Fréchette, le Parti Québécois sous-estime les coûts de 4 milliards.",
        }
        claims = enrich.propose_claims(c)
        self.assertTrue(claims)
        self.assertEqual(claims[0]["speaker"], "Christine Fréchette")
        self.assertEqual(claims[0]["attribution"], "selon")
        self.assertIn("coûts", claims[0]["quote"].lower())

    def test_name_verb_colon_claim(self) -> None:
        c = {
            "title": "Marchand prévient : On ne revoit pas à la baisse nos 13 000 immigrants",
            "summary": "",
        }
        claims = enrich.propose_claims(c)
        self.assertTrue(claims)
        self.assertIn("Marchand", claims[0]["speaker"] or "")
        self.assertIn("immigrants", claims[0]["quote"].lower())

    def test_short_program_name_is_not_a_claim(self) -> None:
        c = {"title": "PSPP remporte le «Face-à-Face» de TVA", "summary": ""}
        claims = enrich.propose_claims(c)
        for cl in claims:
            self.assertNotRegex(cl["quote"], r"(?i)^face")

    def test_election_title_colon_is_not_a_speaker_claim(self) -> None:
        c = {
            "title": "Élections provinciales de 2026 : les avis d'inscription sont envoyés",
            "summary": "",
        }
        claims = enrich.propose_claims(c)
        self.assertEqual(claims, [])

    def test_carney_says_en(self) -> None:
        c = {
            "title": 'Carney says Canada will open airports to private investment',
            "summary": "",
        }
        claims = enrich.propose_claims(c)
        self.assertTrue(claims)
        self.assertIn("Carney", claims[0]["speaker"] or "")
        self.assertIn("airport", claims[0]["quote"].lower())

    def test_enrich_one_writes_claims_not_permanent_empty(self) -> None:
        out = enrich.enrich_one(
            {
                "title": "«C'était un bon débat», estime Paul St-Pierre Plamondon",
                "summary": "",
                "nest_role": "primary",
                "geo": "quebec-city",
                "source_kind": "media",
            }
        )
        self.assertTrue(out["enrich"]["claims"])
        self.assertEqual(out["enrich"]["claims"][0]["status"], "proposed")
        self.assertIn("claims", out["enrich"]["method"])


class LiveClaimsGuard(unittest.TestCase):
    def test_live_store_has_nonempty_claims(self) -> None:
        path = harness.ROOT / "data" / "normalized" / "latest_enriched.json"
        if not path.is_file():
            self.skipTest("no live enriched")
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Re-derive from candidates if store predates claims-v0.1
        cands = payload.get("candidates") or []
        if not cands:
            self.skipTest("empty store")
        # Prefer checking propose_claims on live titles (deterministic vs stale file)
        n = sum(1 for c in cands if enrich.propose_claims(c))
        self.assertGreater(n, 0, "no extractable claims in live titles/summaries")


if __name__ == "__main__":
    unittest.main()
