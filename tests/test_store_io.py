"""Atomic store writes (store_io) — locked as the one write law."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import harness  # noqa: F401 - puts scripts/ on sys.path

import store_io


class AtomicWrite(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "store.json"

    def test_writes_content_and_leaves_no_temp(self) -> None:
        store_io.write_json_atomic(self.path, {"a": 1})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_creates_parent_directories(self) -> None:
        nested = self.dir / "a" / "b" / "store.json"
        store_io.write_text_atomic(nested, "x")
        self.assertEqual(nested.read_text(encoding="utf-8"), "x")

    def test_a_failed_stage_preserves_the_previous_store_and_cleans_up(self) -> None:
        self.path.write_text("old", encoding="utf-8")
        real = Path.write_text

        def failing(self, data, *args, **kwargs):
            if self.name.endswith(".tmp"):
                raise OSError("disk full")
            return real(self, data, *args, **kwargs)

        with mock.patch.object(Path, "write_text", failing):
            with self.assertRaises(OSError):
                store_io.write_text_atomic(self.path, "new")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_replace_refusal_falls_back_to_a_direct_write(self) -> None:
        # Windows: an open reader can block os.replace with PermissionError.
        # The stage must still complete rather than fail the whole chain.
        with mock.patch.object(store_io.os, "replace", side_effect=PermissionError("locked")):
            store_io.write_text_atomic(self.path, "direct")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "direct")
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_temp_names_are_unique_per_writer(self) -> None:
        # A fixed .tmp name lets two writers publish each other's partial file.
        with mock.patch.object(store_io.uuid, "uuid4", side_effect=[
                mock.Mock(hex="aaaa1111"), mock.Mock(hex="bbbb2222")]):
            store_io.write_text_atomic(self.path, "one")
            store_io.write_text_atomic(self.path, "two")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "two")
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
