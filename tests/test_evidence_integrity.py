"""Regression tests for false dossier joins, fabricated freshness and provenance."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import harness
import ambient_pulse
import check_claims
import cluster_issues as cluster


def article(sid: str, title: str, *, hours: int = 0, **kw) -> dict:
    return {
        "id": sid + title,
        "source_id": sid,
        "title": title,
        "summary": "",
        "published_at": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(),
        "url": "https://example.test/" + sid,
        "enrich": {"geo": {"geo": "quebec-city"}, "topics": [{"topic": "transport"}], "claims": []},
        **kw,
    }


class EventIntegrity(unittest.TestCase):
    def test_new_event_clusters_without_hardcoded_people(self):
        a = article("le-soleil", "Limoilou : fermeture temporaire du boulevard Hamel pour travaux")
        b = article("journal-de-quebec", "Travaux : fermeture temporaire du boulevard Hamel à Limoilou")
        buckets = cluster.event_buckets([a, b])
        self.assertEqual(len(buckets), 1)
        self.assertTrue(next(iter(buckets)).startswith("event-"))

    def test_shared_person_does_not_connect_immigration_and_taunt(self):
        a = article("le-soleil", "Marchand prévient : les cibles d'immigration demeurent")
        b = article("journal-de-quebec", "Duhaime aurait dû se présenter comme maire, dit Marchand")
        self.assertNotEqual(cluster.event_scar(a), cluster.event_scar(b))
        self.assertFalse(cluster.same_event(a, b))

    def test_other_missing_teen_is_not_maelyne(self):
        self.assertIsNone(cluster.event_scar(article("le-soleil", "La police de Lévis recherche une adolescente disparue")))

    def test_same_headline_from_another_week_is_not_same_event(self):
        title = "Fermeture temporaire du boulevard Hamel pour travaux"
        self.assertFalse(cluster.same_event(article("a", title), article("b", title, hours=96)))

    def test_unknown_date_is_not_automatic_event_evidence(self):
        title = "Fermeture temporaire du boulevard Hamel pour travaux"
        self.assertFalse(cluster.same_event(article("a", title, published_at=None), article("b", title)))

    def test_closure_boilerplate_does_not_merge_different_roads(self):
        self.assertFalse(cluster.same_event(
            article("a", "Limoilou : fermeture temporaire du boulevard Hamel pour travaux"),
            article("b", "Limoilou : fermeture temporaire du boulevard Charest pour travaux"),
        ))
        self.assertFalse(cluster.same_event(
            article("a", "Fermeture temporaire de la route 138 pour travaux"),
            article("b", "Fermeture temporaire de la route 175 pour travaux"),
        ))

    def test_negation_is_not_erased_in_duplicate_count(self):
        ev = cluster.evidence_metadata([
            article("a", "Marchand veut baisser les cibles"),
            article("b", "Marchand ne veut pas baisser les cibles"),
        ])
        self.assertEqual(ev["duplicate_headline_count"], 0)

    def test_complete_link_prevents_transitive_glue(self):
        a = article("a", "Limoilou travaux fermeture réseau Hamel")
        b = article("b", "Limoilou travaux fermeture réseau Hamel chantier urgence")
        c = article("c", "Limoilou fermeture réseau chantier urgence")
        self.assertTrue(cluster.same_event(a, b))
        self.assertTrue(cluster.same_event(b, c))
        self.assertFalse(cluster.same_event(a, c))
        self.assertTrue(all(len(items) < 3 for items in cluster.event_buckets([a, b, c]).values()))

    def test_publication_does_not_fall_back_to_fetch(self):
        self.assertIsNone(cluster.published_when({"fetched_at": datetime.now(timezone.utc).isoformat()}))
        self.assertIsNone(cluster.published_when({"published_at": "2026-09-16T10:00:00"}))
        self.assertEqual(cluster.published_when({"published_at": "Wed, 16 Sep 2026 04:00:00 EDT"}).hour, 8)

    def test_coverage_is_not_contradiction_or_independence(self):
        ev = cluster.evidence_metadata([article("a", "Headline", published_at=None)])
        self.assertEqual(ev["contradiction"], "not_assessed")
        self.assertEqual(ev["source_independence"], "not_assessed")
        self.assertEqual(ev["publication_unknown_count"], 1)
        self.assertFalse(ev["official_source_is_confirmation"])

    def run_cluster(self, candidates, previous=None):
        with tempfile.TemporaryDirectory() as tmp:
            inp, out = Path(tmp) / "in.json", Path(tmp) / "out.json"
            inp.write_text(json.dumps({"candidates": candidates}), encoding="utf-8")
            if previous:
                out.write_text(json.dumps(previous), encoding="utf-8")
            with patch.multiple(cluster, IN_PATH=inp, OUT_ISSUES=out):
                cluster.main()
            return json.loads(out.read_text(encoding="utf-8"))

    def test_stale_future_and_disabled_sources_cannot_found_dossier(self):
        title = "Marchand présente ses priorités"
        a = article("le-soleil", title)
        b = article("journal-de-quebec", title, hours=24 * 8)
        c = article("radio-canada-quebec", title, hours=-12)
        d = article("unconfigured", title)
        output = self.run_cluster([a, b, c, d])
        self.assertEqual(output["issue_count"], 0)
        self.assertEqual(output["excluded_candidates"]["publication_outside_window"], 2)
        self.assertEqual(output["excluded_candidates"]["source_not_enabled"], 1)

    def test_full_claim_provenance_and_dates_reach_issue(self):
        a = article("le-soleil", "Marchand présente ses priorités")
        claim = {"quote": "ses priorités", "speaker": "Marchand", "field": "title", "method": "pattern", "status": "proposed"}
        a["enrich"]["claims"] = [claim]
        b = article("journal-de-quebec", "Marchand présente ses priorités")
        output = self.run_cluster([a, b])
        issue = output["issues"][0]
        item = next(it for t in issue["tensions"] for it in t["items"] if it["source_id"] == "le-soleil")
        self.assertEqual(item["claims"], [claim])
        self.assertEqual(item["published_at"], a["published_at"])
        self.assertFalse(issue["silence"]["absence_is_editorial_silence"])

    def test_generic_id_survives_added_earlier_article(self):
        title = "Limoilou fermeture temporaire boulevard Hamel travaux"
        a, b = article("le-soleil", title), article("journal-de-quebec", title)
        original = self.run_cluster([a, b])
        added = article("radio-canada-quebec", title, hours=1)
        updated = self.run_cluster([a, b, added], previous=original)
        self.assertEqual(original["issues"][0]["issue_id"], updated["issues"][0]["issue_id"])
        self.assertEqual(updated["issues"][0]["label_kind"], "attributed_headline")


class ProvenanceAudit(unittest.TestCase):
    def test_empty_claims_are_valid_no_quota_for_invented_quotes(self):
        self.assertTrue(check_claims.audit_claims({"candidates": []}, {"issues": []})["ok"])

    def test_detects_quote_or_speaker_not_in_source(self):
        a = article("a", "Marchand présente ses priorités")
        a["enrich"]["claims"] = [{"quote": "ses priorités", "speaker": "Duhaime", "field": "title", "status": "proposed"}]
        report = check_claims.audit_claims({"candidates": [a]}, {})
        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"][0]["reason"], "speaker_not_in_declared_source_field")
        a["enrich"]["claims"][0]["quote"] = "Une citation inventée"
        self.assertEqual(check_claims.audit_claims({"candidates": [a]}, {})["errors"][0]["reason"], "excerpt_not_in_declared_source_field")

    def test_unknown_store_date_stays_unknown_after_rebuild(self):
        digest = ambient_pulse.build_digest([], [], built_at="2026-09-17T10:00:00Z")
        self.assertEqual(digest["clustered_at"], "")
        self.assertEqual(digest["pulse"]["clustered_at"], "")
        self.assertIn("date unknown", ambient_pulse.render_morning_widget(digest))


if __name__ == "__main__":
    unittest.main()
