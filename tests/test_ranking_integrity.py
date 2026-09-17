"""Ranking cannot turn ingestion, malformed time or topic counts into evidence."""
import copy
import unittest
from datetime import datetime, timezone

import harness
import rank_display as rank


class RankingIntegrity(unittest.TestCase):
    def test_download_does_not_make_undated_article_fresh(self):
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)
        for raw in (None, "nonsense", "2026-09-16T12:00:00", "2027-01-01T00:00:00Z"):
            self.assertEqual(rank.recency_score({"published_at": raw, "fetched_at": now.isoformat()}, now), 0)

    def test_rfc_and_iso_are_identical_and_decay(self):
        now = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
        a = {"published_at": "2026-09-16T00:00:00Z"}
        b = {"published_at": "Wed, 16 Sep 2026 00:00:00 GMT"}
        self.assertEqual(rank.parse_when(a), rank.parse_when(b))
        self.assertEqual(rank.recency_score(a, now), .5)

    def test_attribute_and_link_safety(self):
        self.assertNotIn("'", rank.esc("x' onclick='bad()"))
        html = rank.card_html({"title": "test", "url": "javascript:alert(1)"})
        self.assertNotIn("javascript:", html)

    def test_same_count_different_evidence_changes_pulse(self):
        issue = {"issue_id": "one", "question": "Same topic", "source_count": 2,
                 "tensions": [{"items": [{"candidate_id": "a", "title": "Before", "claims": []}]}]}
        before = rank.build_approaches([issue], {"by_id": {}})
        other = copy.deepcopy(issue)
        other["tensions"][0]["items"][0]["title"] = "Corrected title"
        after = rank.build_approaches([other], {"by_id": {}})
        self.assertEqual(rank.since_left_delta(before, after)["changed"], ["one"])

    def test_rebuild_time_does_not_change_content_fingerprint(self):
        issue = {"issue_id": "one", "source_count": 2, "clustered_at": "yesterday"}
        a = rank.build_approaches([issue], {})
        issue["clustered_at"] = "today"
        b = rank.build_approaches([issue], {})
        self.assertEqual(rank.approach_fingerprint(a[0]), rank.approach_fingerprint(b[0]))
