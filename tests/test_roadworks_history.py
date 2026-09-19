"""Roadworks event history: durable per-event collection facts.

One collection = one distinct fetched_at snapshot; offline reuse never
inflates counts; history only moves forward; an absence counts as missed,
never as ended (removed ≠ ended); events[] stays a pure City relay.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import harness  # noqa: F401 - puts scripts/ on sys.path

import ingest_wzdx
import resident_brief as brief
from test_roadworks import NOW, SRC, _event, _store, feature, geojson

TS1 = "2026-09-17T06:00:00+00:00"
TS2 = "2026-09-17T12:00:00+00:00"
TS3 = "2026-09-17T18:00:00+00:00"


def ev(eid: str) -> dict:
    return {"event_id": eid}


def ts_series(n: int) -> list[str]:
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return [(base + timedelta(hours=6 * i)).isoformat() for i in range(n)]


class UpdateEventHistory(unittest.TestCase):
    def test_first_collection(self) -> None:
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), [ev("a")], TS1
        )
        rec = h["events"]["a"]
        self.assertEqual(rec["first_seen"], TS1)
        self.assertEqual(rec["last_seen"], TS1)
        self.assertEqual(rec["collections_seen"], 1)
        self.assertEqual(rec["collections_missed"], 0)
        self.assertEqual(h["collection_count"], 1)
        self.assertEqual(h["updated_at"], TS1)

    def test_second_collection_keeps_first_seen(self) -> None:
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), [ev("a")], TS1
        )
        h = ingest_wzdx.update_event_history(h, [ev("a")], TS2)
        rec = h["events"]["a"]
        self.assertEqual(rec["first_seen"], TS1)
        self.assertEqual(rec["last_seen"], TS2)
        self.assertEqual(rec["collections_seen"], 2)
        self.assertEqual(h["collection_count"], 2)

    def test_a_flickering_event_is_not_pruned_for_lifetime_misses(self) -> None:
        h = ingest_wzdx.update_event_history(ingest_wzdx.empty_event_history(), [ev("a")], TS1)
        h = ingest_wzdx.update_event_history(h, [], TS2)
        self.assertEqual(h["events"]["a"]["absent_streak"], 1)
        h = ingest_wzdx.update_event_history(h, [ev("a")], TS3)
        self.assertEqual(h["events"]["a"]["absent_streak"], 0)
        # lifetime misses stay a display fact; the prune uses the streak only
        h["events"]["a"]["collections_missed"] = ingest_wzdx.HISTORY_MISSED_PRUNE + 5
        h2 = ingest_wzdx.update_event_history(h, [ev("a")], TS3)
        self.assertIn("a", h2["events"])

    def test_a_dormant_event_is_pruned_after_consecutive_absences(self) -> None:
        h = ingest_wzdx.update_event_history(ingest_wzdx.empty_event_history(), [ev("a")], TS1)
        h["events"]["a"]["absent_streak"] = ingest_wzdx.HISTORY_MISSED_PRUNE
        h2 = ingest_wzdx.update_event_history(h, [], TS2)
        self.assertNotIn("a", h2["events"])

    def test_absence_counts_missed_never_ended(self) -> None:
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), [ev("a"), ev("b")], TS1
        )
        h = ingest_wzdx.update_event_history(h, [ev("a")], TS2)
        rec = h["events"]["b"]
        self.assertEqual(rec["collections_missed"], 1)
        self.assertEqual(rec["collections_seen"], 1)
        self.assertEqual(rec["last_seen"], TS1)
        self.assertNotIn("ended", json.dumps(h))
        self.assertNotIn("resolved", json.dumps(h))

    def test_return_after_missed_collections(self) -> None:
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), [ev("a"), ev("b")], TS1
        )
        h = ingest_wzdx.update_event_history(h, [ev("a")], TS2)
        h = ingest_wzdx.update_event_history(h, [ev("a"), ev("b")], TS3)
        rec = h["events"]["b"]
        self.assertEqual(rec["collections_seen"], 2)
        self.assertEqual(rec["collections_missed"], 1)
        self.assertEqual(rec["first_seen"], TS1)
        self.assertEqual(rec["last_seen"], TS3)

    def test_same_snapshot_is_idempotent(self) -> None:
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), [ev("a")], TS1
        )
        h2 = ingest_wzdx.update_event_history(h, [ev("a")], TS1)
        self.assertEqual(h2["events"]["a"]["collections_seen"], 1)
        self.assertEqual(h2["collection_count"], 1)

    def test_older_snapshot_ignored(self) -> None:
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), [ev("a")], TS2
        )
        h2 = ingest_wzdx.update_event_history(h, [ev("a"), ev("b")], TS1)
        self.assertEqual(h2["events"]["a"]["collections_seen"], 1)
        self.assertNotIn("b", h2["events"])
        self.assertEqual(h2["collection_count"], 1)

    def test_input_not_mutated(self) -> None:
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), [ev("a")], TS1
        )
        snapshot = json.dumps(h, sort_keys=True)
        ingest_wzdx.update_event_history(h, [ev("a"), ev("b")], TS2)
        self.assertEqual(json.dumps(h, sort_keys=True), snapshot)

    def test_long_missed_events_pruned(self) -> None:
        tss = ts_series(ingest_wzdx.HISTORY_MISSED_PRUNE + 1)
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), [ev("gone"), ev("stay")], tss[0]
        )
        for ts in tss[1:]:
            h = ingest_wzdx.update_event_history(h, [ev("stay")], ts)
        self.assertNotIn("gone", h["events"])
        self.assertIn("stay", h["events"])

    def test_event_cap_prunes_oldest(self) -> None:
        events = [ev(f"e{i:05d}") for i in range(ingest_wzdx.HISTORY_EVENT_CAP + 100)]
        h = ingest_wzdx.update_event_history(
            ingest_wzdx.empty_event_history(), events, TS1
        )
        self.assertEqual(len(h["events"]), ingest_wzdx.HISTORY_EVENT_CAP)
        self.assertIn(f"e{ingest_wzdx.HISTORY_EVENT_CAP + 99:05d}", h["events"])
        self.assertNotIn("e00000", h["events"])


class LoadEventHistory(unittest.TestCase):
    def _write(self, temp: str, doc: object) -> Path:
        p = Path(temp) / "latest_roadworks.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False),
            encoding="utf-8",
        )
        return p

    def test_missing_file_starts_empty(self) -> None:
        h = ingest_wzdx.load_event_history(Path("/no/such/store.json"))
        self.assertEqual(h, ingest_wzdx.empty_event_history())

    def test_corrupt_file_starts_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            p = self._write(temp, "{not json")
            self.assertEqual(
                ingest_wzdx.load_event_history(p), ingest_wzdx.empty_event_history()
            )

    def test_foreign_store_method_never_mixed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = _store(method="wzdx-roadworks-v1")
            store["event_history"] = {
                "method": ingest_wzdx.HISTORY_METHOD,
                "updated_at": TS1,
                "collection_count": 9,
                "events": {"a": {"collections_seen": 9}},
            }
            p = self._write(temp, store)
            self.assertEqual(
                ingest_wzdx.load_event_history(p), ingest_wzdx.empty_event_history()
            )

    def test_foreign_history_method_never_mixed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = _store()
            store["event_history"] = {
                "method": "wzdx-event-history-v0",
                "updated_at": TS1,
                "collection_count": 9,
                "events": {"a": {"collections_seen": 9}},
            }
            p = self._write(temp, store)
            self.assertEqual(
                ingest_wzdx.load_event_history(p), ingest_wzdx.empty_event_history()
            )

    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = _store()
            store["event_history"] = ingest_wzdx.update_event_history(
                ingest_wzdx.empty_event_history(), [ev("a")], TS1
            )
            p = self._write(temp, store)
            loaded = ingest_wzdx.load_event_history(p)
            self.assertEqual(loaded["events"]["a"]["collections_seen"], 1)
            self.assertEqual(loaded["collection_count"], 1)
            self.assertEqual(loaded["updated_at"], TS1)


class CollectHistory(unittest.TestCase):
    def _paths(self, temp: str) -> tuple[Path, Path]:
        return Path(temp) / "raw", Path(temp) / "roadworks" / "latest_roadworks.json"

    def test_two_collections_track_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            raw_dir, store_path = self._paths(temp)
            body = geojson(feature("a"), feature("b"))
            r1 = ingest_wzdx.collect(
                [SRC], NOW, raw_dir=raw_dir, store_path=store_path,
                fetch=lambda url: (body, "application/json"),
            )
            self.assertTrue(r1["ok"])
            h1 = r1["store"]["event_history"]
            self.assertEqual(h1["method"], ingest_wzdx.HISTORY_METHOD)
            self.assertEqual(h1["collection_count"], 1)
            self.assertEqual(h1["events"]["a"]["collections_seen"], 1)

            body2 = geojson(feature("a"), feature("b"), feature("c"))
            r2 = ingest_wzdx.collect(
                [SRC], NOW + timedelta(hours=6), raw_dir=raw_dir, store_path=store_path,
                fetch=lambda url: (body2, "application/json"),
            )
            self.assertTrue(r2["ok"])
            h2 = r2["store"]["event_history"]
            self.assertEqual(h2["collection_count"], 2)
            self.assertEqual(h2["events"]["a"]["collections_seen"], 2)
            self.assertEqual(h2["events"]["a"]["first_seen"], NOW.isoformat())
            self.assertEqual(h2["events"]["c"]["collections_seen"], 1)
            # events[] stays a pure City relay — no Vigie metadata on events.
            for event in r2["store"]["events"]:
                self.assertNotIn("first_seen", event)
                self.assertNotIn("collections_seen", event)
            # The history is persisted in the store, not only returned.
            stored = json.loads(store_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["event_history"]["collection_count"], 2)

    def test_offline_rerun_same_snapshot_no_inflation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            raw_dir, store_path = self._paths(temp)
            body = geojson(feature("a"))
            ingest_wzdx.collect(
                [SRC], NOW, raw_dir=raw_dir, store_path=store_path,
                fetch=lambda url: (body, "application/json"),
            )

            def no_fetch(url):
                raise AssertionError("offline mode must not fetch")

            r = ingest_wzdx.collect(
                [SRC], NOW + timedelta(hours=1), offline=True,
                raw_dir=raw_dir, store_path=store_path, fetch=no_fetch,
            )
            self.assertTrue(r["ok"])
            h = r["store"]["event_history"]
            self.assertEqual(h["collection_count"], 1)
            self.assertEqual(h["events"]["a"]["collections_seen"], 1)

    def test_removed_event_counts_missed_not_ended(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            raw_dir, store_path = self._paths(temp)
            ingest_wzdx.collect(
                [SRC], NOW, raw_dir=raw_dir, store_path=store_path,
                fetch=lambda url: (geojson(feature("a"), feature("b")), "application/json"),
            )
            r = ingest_wzdx.collect(
                [SRC], NOW + timedelta(hours=6), raw_dir=raw_dir, store_path=store_path,
                fetch=lambda url: (geojson(feature("a")), "application/json"),
            )
            rec = r["store"]["event_history"]["events"]["b"]
            self.assertEqual(rec["collections_seen"], 1)
            self.assertEqual(rec["collections_missed"], 1)

    def test_failed_fetch_keeps_history_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            raw_dir, store_path = self._paths(temp)
            body = geojson(feature("a"))
            ingest_wzdx.collect(
                [SRC], NOW, raw_dir=raw_dir, store_path=store_path,
                fetch=lambda url: (body, "application/json"),
            )
            before = json.loads(store_path.read_text(encoding="utf-8"))

            def boom(url):
                raise OSError("network down")

            r = ingest_wzdx.collect(
                [SRC], NOW + timedelta(hours=6), raw_dir=raw_dir,
                store_path=store_path, fetch=boom,
            )
            self.assertFalse(r["ok"])
            after = json.loads(store_path.read_text(encoding="utf-8"))
            self.assertEqual(after["event_history"], before["event_history"])


class RenderHistory(unittest.TestCase):
    def _history(self, rec: dict) -> dict:
        return {
            "method": ingest_wzdx.HISTORY_METHOD,
            "updated_at": TS2,
            "collection_count": 2,
            "events": {"EV-001": rec},
        }

    def _rec(self, seen: int, missed: int = 0) -> dict:
        return {
            "first_seen": TS1, "last_seen": TS2,
            "collections_seen": seen, "collections_missed": missed,
        }

    def test_no_history_no_line(self) -> None:
        html = brief.roadworks_section(_store(), NOW)
        self.assertNotIn("rw-history", html)

    def test_first_collection_line(self) -> None:
        rw = _store(event_history=self._history(self._rec(1)))
        html = brief.roadworks_section(rw, NOW)
        self.assertIn("rw-history", html)
        self.assertIn("Première collecte où cette entrave apparaît", html)

    def test_multi_collection_line(self) -> None:
        rw = _store(event_history=self._history(self._rec(3)))
        html = brief.roadworks_section(rw, NOW)
        self.assertIn("Dans nos collectes depuis", html)
        self.assertIn("3 collectes", html)
        self.assertIn("<time", html)

    def test_missed_line_states_absence_not_end(self) -> None:
        rw = _store(event_history=self._history(self._rec(2, missed=2)))
        html = brief.roadworks_section(rw, NOW)
        self.assertIn("Auparavant absente de 2 collectes", html)
        self.assertIn("pas une fin des travaux", html)

    def test_foreign_history_renders_nothing(self) -> None:
        rw = _store()
        rw["event_history"] = {"method": "wzdx-event-history-v0", "events": {"EV-001": self._rec(5)}}
        html = brief.roadworks_section(rw, NOW)
        self.assertNotIn("rw-history", html)


if __name__ == "__main__":
    unittest.main()
