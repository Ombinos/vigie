"""Edge Atlas (edge-atlas-v1): literal street joins, deterministic and fail-soft.

House law under test: a shared street name is a proposed relation, never
geographic proof; matching is literal (no fuzzy, no model); the atlas never
touches ranking; stores compile byte-identically from the same inputs; an
absent, corrupt or foreign-method store yields an empty atlas and exit 0.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import harness  # noqa: F401 - puts scripts/ on sys.path

import edge_atlas
import pipeline

FETCHED = "2026-09-17T11:30:00+00:00"


def _event(eid="EV-001", roads=("Boulevard Charest Est",), **over) -> dict:
    ev = {
        "event_id": eid, "event_type": "work-zone", "event_status": "active",
        "vehicle_impact": "some-lanes-closed", "road_names": list(roads),
        "direction": "both-directions", "start_date": "2026-09-10T04:00:00Z",
        "end_date": "2026-10-01T03:59:59Z", "start_date_accuracy": None,
        "end_date_accuracy": None, "description": "Réfection", "update_date": None,
        "restrictions": [], "source_id": "wzdx-quebec", "active": True,
    }
    ev.update(over)
    return ev


def _store(events=None, **over) -> dict:
    base = {
        "method": "wzdx-roadworks-v2", "status": "proposed", "source_id": "wzdx-quebec",
        "source_name": "Ville de Québec — Entraves (WZDX)", "institution_name": "Ville de Québec",
        "feed_url": "https://quebec.gewi.com/wzdx/pull", "dataset_url": "https://example.invalid",
        "license_note": "CC-BY 4.0", "fetched_at": FETCHED,
        "bbox": [-71.85, 46.50, -70.75, 47.25],
        "counts": {"features": 1, "parsed": 1, "active": 1},
        "events": [_event()] if events is None else events,
        "diff": {"has_previous": False, "new": [], "removed": [], "changed": [],
                 "new_count": 0, "removed_count": 0, "changed_count": 0},
    }
    base.update(over)
    return base


def _issue(iid="iss-1", question="Des travaux sur le boulevard Charest Est ?", **over) -> dict:
    issue = {
        "issue_id": iid, "question": question, "status": "proposed",
        "geo_focus": ["quebec-city"], "source_count": 2,
        "label_source": None, "tensions": [], "silence": {},
    }
    issue.update(over)
    return issue


def _issues_doc(*issues) -> dict:
    return {"clustered_at": FETCHED, "issues": list(issues)}


class Normalizer(unittest.TestCase):
    TRUTH_TABLE = [
        ("Boulevard René-Lévesque O", "boulevard-rene-levesque-o"),
        ("boulevard rené-lévesque o", "boulevard-rene-levesque-o"),
        ("Boul. René-Lévesque O", "boulevard-rene-levesque-o"),
        ("BLVD Rene-Levesque O", "boulevard-rene-levesque-o"),
        ("Rue St-Jean", "rue-st-jean"),
        ("Rue Saint-Jean", "rue-st-jean"),
        ("RUE ST-JEAN", "rue-st-jean"),
        ("Rue St-Joseph E", "rue-st-joseph-e"),
        ("Rue St-Joseph O", "rue-st-joseph-o"),
        ("RTE-175", "route-175"),
        ("AUT-740", "autoroute-740"),
        ("Autoroute 40", "autoroute-40"),
        ("3e Avenue", "3e-avenue"),
        ("3e Avenue E", "3e-avenue-e"),
        ("76e Rue O", "76e-rue-o"),
        ("1e Avenue", "1e-avenue"),
        ("Chemin Ste-Foy", "chemin-ste-foy"),
        ("Chemin Sainte-Foy", "chemin-ste-foy"),
        ("Route Ste-Geneviève", "route-ste-genevieve"),
        ("Boulevard de l'Entente", "boulevard-de-l-entente"),
        ("Boulevard de l’Entente", "boulevard-de-l-entente"),
        ("Côte de la Fabrique", "cote-de-la-fabrique"),
        ("Quai St-André", "quai-st-andre"),
        ("Grande Allée E", "grande-allee-e"),
        ("Grande Allée O", "grande-allee-o"),
        ("Pont-Tunnel Joseph-Samson", "pont-tunnel-joseph-samson"),
        ("Place des Noyers", "place-des-noyers"),
        ("Carré de Bon-Accueil", "carre-de-bon-accueil"),
        ("Samuel King", "samuel-king"),
        ("Boulevard Henri-Bourassa", "boulevard-henri-bourassa"),
        ("Boulevard Charest Est", "boulevard-charest-e"),
        ("Boulevard Charest E", "boulevard-charest-e"),
        ("Rue St-Vallier Ouest", "rue-st-vallier-o"),
    ]

    def test_truth_table(self):
        for raw, expected in self.TRUTH_TABLE:
            with self.subTest(raw=raw):
                self.assertEqual(edge_atlas.street_key(raw), expected)

    def test_direction_is_part_of_identity(self):
        self.assertNotEqual(
            edge_atlas.street_key("Rue St-Joseph E"),
            edge_atlas.street_key("Rue St-Joseph O"),
        )

    def test_single_token_direction_is_a_name_not_a_compass(self):
        # A lone "E" has no base street to orient; it stays a name token.
        self.assertEqual(edge_atlas.street_key("E"), "e")

    def test_invalid_inputs_yield_none(self):
        for raw in ("", "   ", None, 123, ["Rue X"], "’‘"):
            with self.subTest(raw=raw):
                self.assertIsNone(edge_atlas.street_key(raw))

    def test_french_text_folds_to_the_same_key(self):
        # Prose spellings converge on the declared key through fold_text.
        folded = edge_atlas.fold_text("des travaux rue Saint-Jean près de la côte de la fabrique")
        self.assertIn("rue st-jean", folded)
        self.assertIn("cote de la fabrique", folded)

    def test_est_the_word_is_never_folded_to_a_compass(self):
        folded = edge_atlas.fold_text("le boulevard est fermé")
        self.assertIn(" est ", f" {folded} ")
        self.assertNotIn("boulevard e ", folded)

    def test_apostrophes_fold_consistently_on_both_sides(self):
        self.assertEqual(
            edge_atlas.street_key("Boulevard de l'Entente"),
            "boulevard-de-l-entente",
        )
        self.assertIn("boulevard de l-entente", edge_atlas.fold_text("le Boulevard de l’Entente"))


class Phrases(unittest.TestCase):
    def test_base_and_full_and_original_variants(self):
        phrases = edge_atlas.phrase_variants("Boulevard René-Lévesque O")
        self.assertIn("boulevard rene-levesque", phrases)      # directionless base
        self.assertIn("boulevard rene-levesque o", phrases)    # full declared form

    def test_hyphenated_route_variants(self):
        phrases = edge_atlas.phrase_variants("RTE-175")
        self.assertIn("route-175", phrases)
        self.assertIn("route 175", phrases)
        self.assertIn("rte-175", phrases)
        self.assertIn("rte 175", phrases)

    def test_short_junk_is_refused(self):
        self.assertEqual(edge_atlas.phrase_variants(""), [])
        self.assertEqual(edge_atlas.phrase_variants(None), [])
        for phrase in edge_atlas.phrase_variants("Rue E"):
            self.assertGreaterEqual(len(phrase), edge_atlas.PHRASE_MIN_LEN)

    def test_variants_are_capped_and_deterministic(self):
        a = edge_atlas.phrase_variants("Lien Piétonnier Pélissier-Pie-XII")
        b = edge_atlas.phrase_variants("Lien Piétonnier Pélissier-Pie-XII")
        self.assertEqual(a, b)
        self.assertLessEqual(len(a), edge_atlas.PHRASE_VARIANTS_CAP)


class Matcher(unittest.TestCase):
    def setUp(self):
        self.streets = {
            "rue-st-jean": ["rue st-jean"],
            "rue-st-jean-baptiste": ["rue st-jean-baptiste"],
            "3e-rue": ["3e rue"],
            "boulevard-rene-levesque-o": ["boulevard rene-levesque", "boulevard rene-levesque o"],
        }
        self.pattern, self.index = edge_atlas.build_matcher(self.streets)

    def match(self, text):
        return edge_atlas.streets_in_text(text, self.pattern, self.index)

    def test_literal_match_with_descriptor(self):
        self.assertEqual(self.match("Travaux rue Saint-Jean cette semaine"), ["rue-st-jean"])

    def test_longest_phrase_wins(self):
        self.assertEqual(
            self.match("la rue Saint-Jean-Baptiste"),
            ["rue-st-jean-baptiste"],
        )

    def test_hyphen_continuation_is_refused(self):
        # "rue st-jean" must not fire inside "rue st-jean-baptiste" alone.
        keys = self.match("une adresse rue Saint-Jean-Baptiste")
        self.assertNotIn("rue-st-jean", keys)

    def test_digit_prefix_is_refused(self):
        self.assertEqual(self.match("la 13e rue est fermée"), [])
        self.assertEqual(self.match("la 3e rue est fermée"), ["3e-rue"])

    def test_bare_proper_name_never_matches(self):
        self.assertEqual(self.match("le quartier Saint-Jean"), [])
        self.assertEqual(self.match("Jean parle à la télévision"), [])

    def test_directionless_prose_matches_declared_direction(self):
        self.assertEqual(
            self.match("le boulevard René-Lévesque Ouest est congestionné"),
            ["boulevard-rene-levesque-o"],
        )

    def test_empty_matcher_matches_nothing(self):
        pattern, index = edge_atlas.build_matcher({})
        self.assertEqual(edge_atlas.streets_in_text("rue st-jean", pattern, index), [])


class BuildStreets(unittest.TestCase):
    def test_counts_display_and_caps(self):
        events = [
            _event("EV-1", roads=("Boulevard Laurier",)),
            _event("EV-2", roads=("boulevard laurier",)),
            _event("EV-3", roads=("Boulevard Laurier", "Rue St-Jean")),
        ]
        streets = edge_atlas.build_streets(events)
        self.assertEqual(streets["boulevard-laurier"]["active_count"], 3)
        self.assertEqual(streets["boulevard-laurier"]["display"], "Boulevard Laurier")
        self.assertEqual(streets["rue-st-jean"]["active_count"], 1)
        self.assertEqual(streets["boulevard-laurier"]["event_ids"], ["EV-1", "EV-2", "EV-3"])

    def test_event_ids_are_capped_but_counts_exact(self):
        events = [_event(f"EV-{n:03d}", roads=("Rue St-Jean",)) for n in range(20)]
        streets = edge_atlas.build_streets(events)
        self.assertEqual(streets["rue-st-jean"]["active_count"], 20)
        self.assertEqual(len(streets["rue-st-jean"]["event_ids"]), edge_atlas.EVENT_IDS_CAP)

    def test_duplicate_road_names_count_once_per_event(self):
        events = [_event("EV-1", roads=("Rue St-Jean", "rue saint-jean"))]
        streets = edge_atlas.build_streets(events)
        self.assertEqual(streets["rue-st-jean"]["active_count"], 1)

    def test_centroid_from_geometry_rounded(self):
        events = [_event("EV-1", roads=("Rue St-Jean",))]
        geometry = {"EV-1": [(-71.21001234, 46.81009876), (-71.20001234, 46.80009876)]}
        streets = edge_atlas.build_streets(events, geometry)
        self.assertEqual(streets["rue-st-jean"]["centroid"], {"lat": 46.8051, "lon": -71.20501})

    def test_centroid_null_without_geometry(self):
        streets = edge_atlas.build_streets([_event("EV-1")])
        self.assertIsNone(streets["boulevard-charest-e"]["centroid"])

    def test_malformed_events_are_skipped(self):
        streets = edge_atlas.build_streets(["nope", {}, _event("", roads=("Rue X",)), None])
        self.assertEqual(streets, {})


class CompileAtlas(unittest.TestCase):
    def test_cross_reference_both_ways(self):
        rw = _store(events=[_event("EV-1", roads=("Boulevard Charest Est",))])
        doc = _issues_doc(_issue("iss-1", "Que dit-on du boulevard Charest Est ?"),
                          _issue("iss-2", "Le tramway et le maire"))
        atlas = edge_atlas.compile_atlas(rw, doc)
        self.assertEqual(atlas["method"], "edge-atlas-v1")
        self.assertEqual(atlas["built_at"], FETCHED)
        self.assertEqual(atlas["street_count"], 1)
        self.assertEqual(atlas["matched_issue_count"], 1)
        self.assertEqual(atlas["issues"], {"iss-1": {"streets": ["boulevard-charest-e"]}})
        self.assertEqual(
            atlas["streets"]["boulevard-charest-e"]["matched_issue_ids"], ["iss-1"]
        )

    def test_deterministic_bytes(self):
        rw = _store(events=[_event("EV-1"), _event("EV-2", roads=("Rue St-Jean",))])
        doc = _issues_doc(_issue())
        a = json.dumps(edge_atlas.compile_atlas(rw, doc), ensure_ascii=False, indent=2, sort_keys=True)
        b = json.dumps(edge_atlas.compile_atlas(rw, doc), ensure_ascii=False, indent=2, sort_keys=True)
        self.assertEqual(a, b)

    def test_no_wall_clock_anywhere(self):
        atlas = edge_atlas.compile_atlas(_store(), _issues_doc())
        self.assertEqual(atlas["built_at"], FETCHED)
        self.assertEqual(atlas["issues_clustered_at"], FETCHED)

    def test_caps(self):
        events = [_event(f"EV-{n:02d}", roads=("Rue St-Jean",)) for n in range(9)]
        issues = _issues_doc(*[
            _issue(f"iss-{n}", "toujours la rue Saint-Jean") for n in range(9)
        ])
        atlas = edge_atlas.compile_atlas(_store(events=events), issues)
        self.assertEqual(
            len(atlas["streets"]["rue-st-jean"]["matched_issue_ids"]),
            edge_atlas.MATCHED_ISSUES_CAP,
        )
        for rec in atlas["issues"].values():
            self.assertLessEqual(len(rec["streets"]), edge_atlas.ISSUE_STREETS_CAP)

    def test_malformed_issues_are_skipped(self):
        atlas = edge_atlas.compile_atlas(
            _store(), {"issues": ["nope", {}, {"question": "sans id"}, None]}
        )
        self.assertEqual(atlas["matched_issue_count"], 0)

    def test_missing_issues_doc_still_builds_streets(self):
        atlas = edge_atlas.compile_atlas(_store(), None)
        self.assertEqual(atlas["street_count"], 1)
        self.assertEqual(atlas["issues"], {})

    def test_internal_phrases_never_leak_into_the_store(self):
        atlas = edge_atlas.compile_atlas(_store(), _issues_doc())
        blob = json.dumps(atlas)
        self.assertNotIn("phrases", blob)


class Geometry(unittest.TestCase):
    def test_load_geometry_from_latest_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp)
            src = raw / "wzdx-quebec"
            src.mkdir(parents=True)
            doc = {"type": "FeatureCollection", "features": [
                {"id": "EV-1", "geometry": {"type": "Point", "coordinates": [-71.2, 46.8]},
                 "properties": {}},
                {"id": "EV-2", "geometry": None, "properties": {}},
                "nope",
            ]}
            (src / "20260917T000000Z_ab.geojson").write_text(json.dumps(doc), encoding="utf-8")
            geometry = edge_atlas.load_geometry(raw, "wzdx-quebec")
        self.assertEqual(geometry, {"EV-1": [(-71.2, 46.8)]})

    def test_missing_snapshot_yields_no_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(edge_atlas.load_geometry(Path(temp), "wzdx-quebec"), {})

    def test_corrupt_snapshot_yields_no_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "wzdx-quebec"
            src.mkdir(parents=True)
            (src / "20260917T000000Z_ab.geojson").write_text("{not json", encoding="utf-8")
            self.assertEqual(edge_atlas.load_geometry(Path(temp), "wzdx-quebec"), {})


class MainFailSoft(unittest.TestCase):
    def _run_main(self, root: Path) -> int:
        with patch.object(edge_atlas, "ROOT", root), \
                patch.object(edge_atlas, "ROADWORKS", root / "data" / "roadworks" / "latest_roadworks.json"), \
                patch.object(edge_atlas, "ISSUES", root / "data" / "issues" / "latest_issues.json"), \
                patch.object(edge_atlas, "RAW_DIR", root / "data" / "raw"), \
                patch.object(edge_atlas, "OUT_PATH", root / "data" / "edges" / "latest_edges.json"):
            return edge_atlas.main([])

    def test_missing_store_writes_empty_atlas_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(self._run_main(root), 0)
            atlas = json.loads((root / "data" / "edges" / "latest_edges.json").read_text(encoding="utf-8"))
        self.assertEqual(atlas["method"], "edge-atlas-v1")
        self.assertEqual(atlas["street_count"], 0)
        self.assertIsNone(atlas["built_at"])
        self.assertIn("Aucune collecte officielle exploitable", atlas["note"])

    def test_foreign_method_never_joins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_dir = root / "data" / "roadworks"
            store_dir.mkdir(parents=True)
            (store_dir / "latest_roadworks.json").write_text(
                json.dumps({"method": "some-other-model", "events": [_event()]}), encoding="utf-8")
            self.assertEqual(self._run_main(root), 0)
            atlas = json.loads((root / "data" / "edges" / "latest_edges.json").read_text(encoding="utf-8"))
        self.assertEqual(atlas["streets"], {})

    def test_corrupt_store_writes_empty_atlas(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store_dir = root / "data" / "roadworks"
            store_dir.mkdir(parents=True)
            (store_dir / "latest_roadworks.json").write_text("{corrupt", encoding="utf-8")
            self.assertEqual(self._run_main(root), 0)
            atlas = json.loads((root / "data" / "edges" / "latest_edges.json").read_text(encoding="utf-8"))
        self.assertEqual(atlas["street_count"], 0)

    def test_full_compile_is_byte_identical_across_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data" / "roadworks").mkdir(parents=True)
            (root / "data" / "issues").mkdir(parents=True)
            (root / "data" / "roadworks" / "latest_roadworks.json").write_text(
                json.dumps(_store(), ensure_ascii=False), encoding="utf-8")
            (root / "data" / "issues" / "latest_issues.json").write_text(
                json.dumps(_issues_doc(_issue()), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(self._run_main(root), 0)
            first = (root / "data" / "edges" / "latest_edges.json").read_bytes()
            self.assertEqual(self._run_main(root), 0)
            second = (root / "data" / "edges" / "latest_edges.json").read_bytes()
        self.assertEqual(first, second)


class PipelineWiring(unittest.TestCase):
    def test_atlas_and_anomalies_sit_between_cluster_and_media(self):
        s = pipeline.SCRIPTS
        self.assertLess(s.index("cluster_issues.py"), s.index("edge_atlas.py"))
        self.assertLess(s.index("edge_atlas.py"), s.index("compile_anomalies.py"))
        self.assertLess(s.index("compile_anomalies.py"), s.index("fetch_brief_media.py"))

    def test_new_stages_are_pure_disk_and_get_no_offline_flag(self):
        with patch("sys.argv", ["pipeline.py", "--offline"]), patch.object(pipeline, "run") as run:
            self.assertEqual(pipeline.main(), 0)
        calls = {c.args[0]: c.args[1:] for c in run.call_args_list}
        self.assertEqual(calls["edge_atlas.py"], ())
        self.assertEqual(calls["compile_anomalies.py"], ())

    def test_render_only_still_runs_rank_display_alone(self):
        with patch("sys.argv", ["pipeline.py", "--render-only"]), patch.object(pipeline, "run") as run:
            self.assertEqual(pipeline.main(), 0)
        self.assertEqual([c.args[0] for c in run.call_args_list], ["rank_display.py"])


if __name__ == "__main__":
    unittest.main()
