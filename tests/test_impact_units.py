"""Impact units — falsifiable price / bylaw_id / housing_count. w_impact stays 0."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import harness
import enrich
import rank_display


class ParseNumber(unittest.TestCase):
    def test_fr_grouped_and_decimal(self) -> None:
        self.assertEqual(enrich._parse_number("1 250,50"), 1250.50)
        self.assertEqual(enrich._parse_number("1,250.50"), 1250.50)
        self.assertEqual(enrich._parse_number("96"), 96.0)
        self.assertEqual(enrich._parse_number("1\u202f250,50"), 1250.50)


class ImpactUnitsExtract(unittest.TestCase):
    def test_loyer_price_cad(self) -> None:
        units = enrich.propose_impact_units(
            "Le loyer moyen grimpe à 1 450 $ par mois à Québec", ""
        )
        self.assertTrue(units)
        self.assertEqual(units[0]["kind"], "price")
        self.assertEqual(units[0]["value"], 1450.0)
        self.assertIn(units[0]["unit"], ("CAD", "CAD_per_month"))

    def test_cents_per_kwh(self) -> None:
        units = enrich.propose_impact_units("Hydro: tarif à 7,5 ¢/kWh", "")
        self.assertEqual(units[0]["kind"], "price")
        self.assertEqual(units[0]["unit"], "cents_per_kWh")
        self.assertEqual(units[0]["value"], 7.5)

    def test_deny_bond_issuance_dollars(self) -> None:
        units = enrich.propose_impact_units(
            "Hydro-Québec — émission d'obligations de 500 000 000 $",
            "billets à moyen terme",
        )
        self.assertEqual(units, [])

    def test_foreign_dollars_are_never_labelled_canadian(self) -> None:
        for text in ("Le loyer est de 1 450 $ US", "Le loyer est de 1 450 $ USD", "US$1,450 per month rent"):
            self.assertEqual(enrich.propose_impact_units(text, ""), [], text)

    def test_unqualified_dollar_does_not_invent_currency(self) -> None:
        units = enrich.propose_impact_units("Le loyer est de 1 450 $ par mois", "")
        self.assertEqual(units[0]["unit"], "dollars_per_month")

    def test_per_litre_unit_survives_price_context_match(self) -> None:
        units = enrich.propose_impact_units("Au Québec, essence à 1,65 $/L", "")
        self.assertEqual(units[0]["unit"], "CAD_per_L")

    def test_bylaw_projet_de_loi(self) -> None:
        units = enrich.propose_impact_units("L'Assemblée adopte le projet de loi 31", "")
        self.assertEqual(units[0]["kind"], "bylaw_id")
        self.assertEqual(units[0]["value"], "31")

    def test_loi_number(self) -> None:
        units = enrich.propose_impact_units(
            "Les cartes de rappel doivent aussi être en anglais, tranche la loi 96",
            "",
        )
        self.assertEqual(units[0]["kind"], "bylaw_id")
        self.assertEqual(str(units[0]["value"]), "96")

    def test_housing_count(self) -> None:
        units = enrich.propose_impact_units(
            "La Ville annonce 120 logements sociaux à Limoilou", ""
        )
        self.assertEqual(units[0]["kind"], "housing_count")
        self.assertEqual(units[0]["value"], 120.0)
        self.assertEqual(units[0]["unit"], "logements")

    def test_deny_english_unit_theater(self) -> None:
        units = enrich.propose_impact_units(
            "Conservatives seek relevance, unity in B.C. gathering",
            "Cases stuck in limbo, detainees pleading over justice system delays",
        )
        self.assertEqual(units, [])


class ImpactsAttachUnits(unittest.TestCase):
    def test_units_attach_to_matching_impact(self) -> None:
        topics = [{"topic": "housing"}, {"topic": "law"}]
        impacts = enrich.propose_impacts(
            topics,
            "Projet de loi 28 et 200 logements à Québec",
            "",
        )
        by_lab = {i["label"]: i for i in impacts}
        self.assertTrue(by_lab["housing"]["units"])
        self.assertTrue(by_lab["law"]["units"])
        self.assertEqual(by_lab["housing"]["units"][0]["kind"], "housing_count")
        self.assertEqual(by_lab["law"]["units"][0]["kind"], "bylaw_id")

    def test_unit_only_impact_without_topic(self) -> None:
        impacts = enrich.propose_impacts(
            [{"topic": "other"}],
            "Hausse du tarif d'électricité de 3 %",
            "",
        )
        labels = [i["label"] for i in impacts]
        self.assertIn("price", labels)
        price = next(i for i in impacts if i["label"] == "price")
        self.assertTrue(price["units"])
        self.assertIsNone(price["from_topic"])

    def test_enrich_one_writes_units_method(self) -> None:
        out = enrich.enrich_one(
            {
                "title": "120 logements et loyer à 900 $",
                "summary": "",
                "url": "https://example.test/x",
                "nest_role": "primary",
                "geo": "quebec-city",
            }
        )
        self.assertIn("impact-units", out["enrich"]["method"])
        units = [u for i in out["enrich"]["impacts"] for u in (i.get("units") or [])]
        self.assertTrue(units)
        self.assertTrue(all(u.get("status") == "proposed" for u in units))


class WImpactStaysOff(unittest.TestCase):
    def test_weights_and_score_ignore_units(self) -> None:
        self.assertEqual(rank_display.W_IMPACT, 0.0)
        self.assertEqual(rank_display.W_TENSION, 0.0)
        now = datetime(2026, 9, 16, 22, 0, tzinfo=timezone.utc)
        with_units = {
            "nest_role": "primary",
            "geo": "quebec-city",
            "published_at": "Tue, 16 Sep 2026 12:00:00 GMT",
            "enrich": {
                "geo": {"geo": "quebec-city"},
                "impacts": [
                    {
                        "label": "price",
                        "units": [{"kind": "price", "value": 12, "unit": "CAD", "raw": "12 $"}],
                    }
                ],
            },
        }
        bare = {
            "nest_role": "primary",
            "geo": "quebec-city",
            "published_at": "Tue, 16 Sep 2026 12:00:00 GMT",
            "enrich": {"geo": {"geo": "quebec-city"}, "impacts": []},
        }
        self.assertEqual(
            rank_display.score_item(with_units, now),
            rank_display.score_item(bare, now),
        )


if __name__ == "__main__":
    unittest.main()
