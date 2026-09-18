"""City-declared revisions: postponed/advanced ends and declared endings, relayed literally.

House law under test: a declaration is not a verified resolution; a plain
absence stays unknown; direction comes from the City's own dates, never from
inference; unparseable dates stay directionless.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import harness  # noqa: F401 - puts scripts/ on sys.path

import ingest_wzdx
from test_roadworks import NOW, SRC, _event, _render, _store, feature, geojson


class DiffRevisions(unittest.TestCase):
    def test_end_date_moved_later(self) -> None:
        cur = [_event("a", end_date="2026-10-05T03:59:59Z")]
        prev = [_event("a")]
        d = ingest_wzdx.diff_events(cur, prev, now=NOW)
        self.assertEqual(d["changed"][0]["end_date_moved"], "later")

    def test_end_date_moved_earlier(self) -> None:
        cur = [_event("a", end_date="2026-09-20T03:59:59Z")]
        prev = [_event("a")]
        d = ingest_wzdx.diff_events(cur, prev, now=NOW)
        self.assertEqual(d["changed"][0]["end_date_moved"], "earlier")

    def test_unparseable_end_date_stays_directionless(self) -> None:
        cur = [_event("a", end_date="bientôt")]
        prev = [_event("a")]
        d = ingest_wzdx.diff_events(cur, prev, now=NOW)
        self.assertIn("end_date", d["changed"][0]["fields"])
        self.assertNotIn("end_date_moved", d["changed"][0])

    def test_untouched_end_date_has_no_direction(self) -> None:
        cur = [_event("a", description="Autre description")]
        prev = [_event("a")]
        d = ingest_wzdx.diff_events(cur, prev, now=NOW)
        self.assertNotIn("end_date_moved", d["changed"][0])

    def test_declared_end_attached_to_removal(self) -> None:
        prev = [_event("a")]
        d = ingest_wzdx.diff_events([], prev, now=NOW, ended={"a": "completed"})
        self.assertEqual(d["removed"][0]["city_declared_status"], "completed")

    def test_plain_absence_carries_no_declaration(self) -> None:
        prev = [_event("a")]
        d = ingest_wzdx.diff_events([], prev, now=NOW)
        self.assertNotIn("city_declared_status", d["removed"][0])

    def test_declared_status_normalized_lowercase(self) -> None:
        prev = [_event("a")]
        d = ingest_wzdx.diff_events([], prev, now=NOW, ended={"a": " Cancelled "})
        self.assertEqual(d["removed"][0]["city_declared_status"], "cancelled")


class CollectRevisions(unittest.TestCase):
    def _paths(self, temp: str) -> tuple[Path, Path]:
        return Path(temp) / "raw", Path(temp) / "roadworks" / "latest_roadworks.json"

    def test_completed_event_becomes_declared_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            raw_dir, store_path = self._paths(temp)
            previous = _store(events=[_event("a"), _event("b")])
            store_path.parent.mkdir(parents=True)
            store_path.write_text(json.dumps(previous), encoding="utf-8")
            body = geojson(feature("a"), feature("b", status="completed"))
            result = ingest_wzdx.collect(
                [SRC], NOW, raw_dir=raw_dir, store_path=store_path,
                fetch=lambda url: (body, "application/json"),
            )
            self.assertTrue(result["ok"])
            diff = result["store"]["diff"]
            removed = {e["event_id"]: e for e in diff["removed"]}
            self.assertEqual(removed["b"]["city_declared_status"], "completed")
            self.assertEqual([e["event_id"] for e in result["store"]["events"]], ["a"])

    def test_postponed_end_date_in_store_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            raw_dir, store_path = self._paths(temp)
            previous = _store(events=[_event("a")])
            store_path.parent.mkdir(parents=True)
            store_path.write_text(json.dumps(previous), encoding="utf-8")
            body = geojson(feature("a", end="2026-10-09T03:59:59Z"))
            result = ingest_wzdx.collect(
                [SRC], NOW, raw_dir=raw_dir, store_path=store_path,
                fetch=lambda url: (body, "application/json"),
            )
            self.assertTrue(result["ok"])
            changed = result["store"]["diff"]["changed"]
            self.assertEqual(changed[0]["event_id"], "a")
            self.assertEqual(changed[0]["end_date_moved"], "later")


class RenderRevisions(unittest.TestCase):
    def _diff(self, **over) -> dict:
        base = {"has_previous": True, "new": [], "removed": [], "changed": [],
                "new_count": 0, "removed_count": 0, "changed_count": 0}
        base.update(over)
        return base

    def test_postponed_tag_replaces_generic(self) -> None:
        diff = self._diff(changed=[{"event_id": "EV-001", "end_date_moved": "later"}],
                          changed_count=1)
        page = _render(_store(diff=diff))
        self.assertIn("rw-t-post", page)
        self.assertIn("Fin reportée", page)
        self.assertNotIn("rw-t-chg", page)

    def test_advanced_tag(self) -> None:
        diff = self._diff(changed=[{"event_id": "EV-001", "end_date_moved": "earlier"}],
                          changed_count=1)
        page = _render(_store(diff=diff))
        self.assertIn("rw-t-adv", page)
        self.assertIn("Fin avancée", page)

    def test_plain_change_keeps_generic_tag(self) -> None:
        diff = self._diff(changed=[{"event_id": "EV-001", "fields": ["description"]}],
                          changed_count=1)
        page = _render(_store(diff=diff))
        self.assertIn("rw-t-chg", page)
        self.assertIn("Modifiée", page)
        self.assertNotIn("rw-t-post", page)

    def test_declared_ends_line(self) -> None:
        diff = self._diff(
            removed=[
                {"event_id": "x", "city_declared_status": "completed"},
                {"event_id": "y", "city_declared_status": "completed"},
                {"event_id": "z", "city_declared_status": "cancelled"},
            ],
            removed_count=3,
        )
        page = _render(_store(diff=diff))
        self.assertIn("La Ville déclare depuis la dernière collecte", page)
        self.assertIn("2 entraves « completed »", page)
        self.assertIn("1 entrave « cancelled »", page)
        self.assertIn("pas une vérification sur le terrain", page)

    def test_no_declaration_no_line(self) -> None:
        diff = self._diff(removed=[{"event_id": "x"}], removed_count=1)
        page = _render(_store(diff=diff))
        self.assertNotIn("La Ville déclare", page)
        self.assertNotIn("rw-ended", page)
        # The plain-absence note still stands.
        self.assertIn("pas nécessairement terminée", page)

    def test_declared_status_is_escaped(self) -> None:
        diff = self._diff(
            removed=[{"event_id": "x", "city_declared_status": "<b>fini</b>"}],
            removed_count=1,
        )
        page = _render(_store(diff=diff))
        self.assertNotIn("<b>fini</b>", page)
        self.assertIn("&lt;b&gt;fini&lt;/b&gt;", page)


if __name__ == "__main__":
    unittest.main()
