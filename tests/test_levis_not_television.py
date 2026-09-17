"""Scar test: l[ée]vis must not match télévision / television.

If this file is green while a TV-wire story is Near me, the lookout is lying.
"""
from __future__ import annotations

import unittest

import harness

import cluster_issues
import enrich


# Exact 2026-09-16 Journal de Québec item that ranked #2 Near me.
HELICOPTER = {
    "title": (
        "EN IMAGES | Au moins trois morts dans l’écrasement d’un "
        "hélicoptère près de Los Angeles"
    ),
    "summary": (
        "Un hélicoptère d’une chaîne de télévision s'est écrasé mardi soir "
        "près Los Angeles, dans la vallée de San Fernando, faisant au moins "
        "trois morts."
    ),
    "url": (
        "https://www.journaldequebec.com/2026/09/16/"
        "au-moins-trois-morts-dans-lecrasement-dun-helicoptere-pres-de-los-angeles"
    ),
    "geo": "quebec-city",
    "nest_role": "primary",
    "source_id": "journal-de-quebec",
}


class LevisIsNotTelevision(unittest.TestCase):
    def test_strict_city_does_not_match_television_english(self) -> None:
        self.assertIsNone(enrich.STRICT_CITY.search("television"))
        self.assertIsNone(enrich.STRICT_CITY.search("a television crew"))

    def test_strict_city_does_not_match_television_french(self) -> None:
        self.assertIsNone(enrich.STRICT_CITY.search("télévision"))
        self.assertIsNone(enrich.STRICT_CITY.search("une chaîne de télévision"))

    def test_strict_city_still_matches_place_levis(self) -> None:
        self.assertIsNotNone(enrich.STRICT_CITY.search("Mort de Maëlyne Lugez à Lévis"))
        self.assertIsNotNone(enrich.STRICT_CITY.search("Le maire de Lévis"))
        self.assertIsNotNone(enrich.STRICT_CITY.search("Lévis-Lauzon"))

    def test_helicopter_crash_is_not_near_me(self) -> None:
        text = enrich.blob(HELICOPTER)
        self.assertRegex(text, r"t[ée]l[ée]vision")
        geo = enrich.propose_geo(HELICOPTER, text)
        self.assertNotEqual(
            geo["geo"],
            "quebec-city",
            f"lévis-inside-télévision crowned Near me: {geo}",
        )
        self.assertEqual(geo["geo"], "linked")
        self.assertIn("source geography is not article geography", geo["reason"])

    def test_cluster_does_not_found_maelyne_from_tv_and_police(self) -> None:
        hitch = {
            "title": "Une chaîne de télévision filme la police à Los Angeles",
            "summary": "Un hélicoptère de télévision s'écrase; la police arrive.",
        }
        self.assertIsNone(cluster_issues.scar_of(hitch))

    def test_real_levis_coroner_story_still_scars(self) -> None:
        real = {
            "title": "Quebec coroner says police mishandled 2024 search for missing Lévis teen",
            "summary": "",
        }
        self.assertEqual(cluster_issues.scar_of(real), "maelyne-levis")


if __name__ == "__main__":
    unittest.main()
