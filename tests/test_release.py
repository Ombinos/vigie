"""Release integrity and filesystem exposure regressions (no network needed)."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import harness
import serve
import stage_public
import verify
import pipeline


class StaticRelease(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = self.root / "public"
        self.public.mkdir()
        self.output = self.root / "deploy" / "public"
        for name in stage_public.METHODS:
            (self.root / name).write_text("Public method", encoding="utf-8")
        (self.public / "index.html").write_text('<a href="/morning.html#brief">Brief</a><link href="/favicon.svg"><a href="/VISION.md">Method</a>', encoding="utf-8")
        (self.public / "morning.html").write_text('<h1 id="brief">Brief</h1>', encoding="utf-8")
        (self.public / "explorer.html").write_text('<h1>Workbench</h1>', encoding="utf-8")
        (self.public / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")

    def test_nested_assets_stale_removal_and_exact_manifest(self):
        (self.public / "assets").mkdir()
        (self.public / "assets" / "brief.js").write_text("'use strict';", encoding="utf-8")
        self.output.mkdir(parents=True)
        (self.output / "obsolete.html").write_text("old", encoding="utf-8")
        manifest = stage_public.stage(self.root, self.output)
        self.assertFalse((self.output / "obsolete.html").exists())
        self.assertEqual((self.output / "assets" / "brief.js").read_text(), "'use strict';")
        for name, entry in manifest["files"].items():
            data = (self.output / name).read_bytes()
            self.assertEqual(entry, {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.assertEqual(json.loads((self.output / "build-manifest.json").read_text()), manifest)

    def test_broken_link_preserves_previous_release(self):
        stage_public.stage(self.root, self.output)
        old = (self.output / "index.html").read_bytes()
        (self.public / "index.html").write_text('<a href="/missing.css">Broken</a>', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing local target"):
            stage_public.stage(self.root, self.output)
        self.assertEqual((self.output / "index.html").read_bytes(), old)
        self.assertEqual([p.name for p in self.output.parent.iterdir()], ["public"])

    def test_missing_method_blocks_release(self):
        (self.root / "ranking.md").unlink()
        with self.assertRaisesRegex(ValueError, "ranking.md"):
            stage_public.stage(self.root, self.output)

    def test_missing_explorer_blocks_release(self):
        (self.public / "explorer.html").unlink()
        with self.assertRaisesRegex(ValueError, "explorer.html"):
            stage_public.stage(self.root, self.output)

    def test_data_scheme_link_blocks_release(self):
        (self.public / "index.html").write_text(
            '<img src="data:image/png;base64,AAAA">', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            stage_public.stage(self.root, self.output)

    def test_stale_stage_leftovers_are_swept(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        stale = self.output.parent / ".vigie-stage-dead"
        stale.mkdir()
        (stale / "junk").write_text("x", encoding="utf-8")
        old = time.time() - 2 * 24 * 3600
        os.utime(stale, (old, old))
        stage_public.stage(self.root, self.output)
        self.assertFalse(stale.exists())

    def test_failed_replacement_restores_previous_release(self):
        stage_public.stage(self.root, self.output)
        old = (self.output / "index.html").read_bytes()
        (self.public / "index.html").write_text("New valid page", encoding="utf-8")
        rename = Path.rename

        def fail_new(path, target):
            if path.name.startswith(".vigie-stage-"):
                raise OSError("Simulated filesystem failure")
            return rename(path, target)

        with patch.object(Path, "rename", fail_new), self.assertRaises(OSError):
            stage_public.stage(self.root, self.output)
        self.assertEqual((self.output / "index.html").read_bytes(), old)
        self.assertEqual([p.name for p in self.output.parent.iterdir()], ["public"])

    def test_symlink_cannot_enter_publish_snapshot(self):
        try:
            (self.public / "leak.txt").symlink_to(self.root / "VISION.md")
        except OSError:
            self.skipTest("OS does not permit symlink creation")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            stage_public.stage(self.root, self.output)

    def test_private_file_blocks_release(self):
        (self.public / ".env").write_text("never publish", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Private file"):
            stage_public.stage(self.root, self.output)

    def test_source_directory_cannot_be_overwritten(self):
        for target in (self.root, self.public, self.root / "scripts"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                stage_public.stage(self.root, target)

    def test_broken_anchor_and_duplicate_ids_detected(self):
        (self.public / "index.html").write_text('<p id="a"></p><p id="a"></p><a href="#missing">x</a>', encoding="utf-8")
        errors = stage_public.validate_site(self.public)
        self.assertTrue(any("duplicate id a" in error for error in errors))
        self.assertTrue(any("missing anchor" in error for error in errors))

    def test_external_links_and_same_page_queries_are_not_files(self):
        (self.public / "index.html").write_text('<a href="https://example.test/story">x</a><a href="?facet=health#here">x</a><p id="here">Here</p>', encoding="utf-8")
        self.assertEqual(stage_public.validate_site(self.public), [])

    def test_http_release_is_byte_identical(self):
        manifest = stage_public.stage(self.root, self.output)
        verify.smoke_site(self.output, manifest)


class PreviewServer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = self.root / "public"
        self.public.mkdir()
        (self.public / "index.html").write_text("Vigie", encoding="utf-8")
        (self.public / "assets").mkdir()
        (self.public / ".env").write_text("secret", encoding="utf-8")
        (self.root / "VISION.md").write_text("Public method", encoding="utf-8")
        self.patch = patch.object(serve, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        handler = functools.partial(verify.QuietHandler, directory=self.public, methods={"/VISION.md": self.root / "VISION.md"})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def test_methods_get_and_head_have_matching_metadata(self):
        with urlopen(self.base + "/VISION.md?version=1") as response:
            self.assertEqual(response.read(), b"Public method")
            self.assertEqual(response.headers["Content-Type"], "text/plain; charset=utf-8")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        with urlopen(Request(self.base + "/VISION.md", method="HEAD")) as response:
            self.assertEqual(response.headers["Content-Length"], "13")
            self.assertEqual(response.read(), b"")

    def test_dotfiles_traversal_and_directory_listing_are_unavailable(self):
        for path in ("/.env", "/%2eenv", "/../VISION.md", "/assets/", "/%00"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.base + path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_symlink_cannot_expose_nonpublic_file(self):
        link = self.public / "leak.txt"
        try:
            link.symlink_to(self.root / "VISION.md")
        except OSError:
            self.skipTest("OS does not permit symlink creation")
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/leak.txt")
        self.assertEqual(error.exception.code, 404)
        error.exception.close()


class PipelineModes(unittest.TestCase):
    def test_offline_mode_never_runs_fetch(self):
        with patch("sys.argv", ["pipeline.py", "--offline", "--stage"]), patch.object(pipeline, "run") as run:
            self.assertEqual(pipeline.main(), 0)
        self.assertEqual([call.args[0] for call in run.call_args_list], [*pipeline.SCRIPTS[1:], "stage_public.py"])

    def test_render_only_leaves_upstream_data_alone(self):
        with patch("sys.argv", ["pipeline.py", "--render-only"]), patch.object(pipeline, "run") as run:
            self.assertEqual(pipeline.main(), 0)
        run.assert_called_once_with("rank_display.py")

    def test_failed_build_never_stages(self):
        with patch("sys.argv", ["pipeline.py", "--stage"]), patch.object(pipeline, "run", side_effect=SystemExit("failed")) as run:
            with self.assertRaises(SystemExit):
                pipeline.main()
        self.assertNotIn("stage_public.py", [call.args[0] for call in run.call_args_list])


class ReleaseGuards(unittest.TestCase):
    def test_offline_rebuild_refuses_missing_or_stale_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(verify, "ROOT", root):
                with self.assertRaises(RuntimeError):
                    verify.guard_offline_rebuild()  # no raw snapshot at all
                (root / "data" / "raw").mkdir(parents=True)
                (root / "data" / "raw" / "_run_20200101T000000Z.json").write_text(
                    "{}", encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    verify.guard_offline_rebuild()  # stale -> would empty the edition

    def test_claims_gate_is_a_noop_without_stores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(verify, "ROOT", Path(tmp)):
                verify.claims_gate()  # must not raise on a fresh checkout

    def test_claims_gate_passes_on_the_live_edition(self) -> None:
        # The real stores are exactly what refresh.py's verify step will see.
        verify.claims_gate()


if __name__ == "__main__":
    unittest.main()
