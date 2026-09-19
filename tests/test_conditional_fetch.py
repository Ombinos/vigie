"""Conditional fetching: bandwidth is rent, and a 304 is an honest collection.

Locks the ETag/If-Modified-Since layer inside ingest_rss.fetch_bytes (the
two-tuple contract every caller and mock relies on never changes), the disk
body cache, the unconditional fallback when a validator has no body, and
ingest_one's digest-based not_modified fact.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import harness  # noqa: F401 - puts scripts/ on sys.path

import ingest_rss

URL = "https://news.example/feed"
RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>t</title><link>https://news.example/a</link></item></channel></rss>'


def response(body: bytes, headers: dict | None = None):
    resp = mock.MagicMock()
    resp.headers = headers or {}
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    return resp


class ConditionalFetch(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raw = Path(self._tmp.name) / "raw"
        self.raw.mkdir()
        for name, value in (("RAW_DIR", self.raw), ("RETRIES", 3)):
            patcher = mock.patch.object(ingest_rss, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cache_path = self.raw / "_http_cache.json"

    def fetch(self, opener, url=URL):
        with mock.patch.object(ingest_rss, "public_http_url", side_effect=lambda u, resolve=False: u), \
                mock.patch.object(ingest_rss.urllib.request, "build_opener", return_value=opener):
            return ingest_rss.fetch_bytes(url)

    def seed_cache(self, etag='"v1"', last_modified="Wed, 17 Sep 2026 08:00:00 GMT",
                   body: bytes | None = RSS, content_type="application/rss+xml") -> None:
        self.cache_path.write_text(json.dumps({URL: {
            "etag": etag, "last_modified": last_modified,
            "content_type": content_type, "updated_at": "2026-09-18T00:00:00+00:00",
        }}), encoding="utf-8")
        if body is not None:
            body_path = self.raw / "_bodies" / (
                __import__("hashlib").sha256(URL.encode()).hexdigest()[:32] + ".body")
            body_path.parent.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(body)

    def requests_of(self, opener):
        return [call.args[0] for call in opener.open.call_args_list]

    def test_validators_saved_and_body_cached_on_success(self) -> None:
        opener = mock.Mock()
        opener.open.return_value = response(RSS, {"ETag": '"v1"', "Content-Type": "application/rss+xml"})
        body, ctype = self.fetch(opener)
        self.assertEqual(body, RSS)
        self.assertEqual(ctype, "application/rss+xml")
        cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(cache[URL]["etag"], '"v1"')
        self.assertIsNone(cache[URL]["last_modified"])
        bodies = list((self.raw / "_bodies").iterdir())
        self.assertEqual(len(bodies), 1)
        self.assertEqual(bodies[0].read_bytes(), RSS)

    def test_conditional_headers_sent_when_validators_known(self) -> None:
        self.seed_cache()
        opener = mock.Mock()
        opener.open.return_value = response(RSS, {"ETag": '"v2"'})
        self.fetch(opener)
        req = self.requests_of(opener)[0]
        self.assertEqual(req.get_header("If-none-match"), '"v1"')
        self.assertEqual(req.get_header("If-modified-since"), "Wed, 17 Sep 2026 08:00:00 GMT")

    def test_304_returns_cached_body_in_one_request(self) -> None:
        self.seed_cache()
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(URL, 304, "Not Modified", {}, None)
        body, ctype = self.fetch(opener)
        self.assertEqual(body, RSS)
        self.assertEqual(ctype, "application/rss+xml")
        self.assertEqual(opener.open.call_count, 1)  # a 304 is never retried

    def test_304_without_body_cache_refetches_unconditionally(self) -> None:
        self.seed_cache(body=None)
        opener = mock.Mock()
        fresh = response(b"<rss>new</rss>", {"Content-Type": "text/xml"})
        opener.open.side_effect = [
            urllib.error.HTTPError(URL, 304, "Not Modified", {}, None), fresh]
        body, ctype = self.fetch(opener)
        self.assertEqual(body, b"<rss>new</rss>")
        self.assertEqual(ctype, "text/xml")
        second = self.requests_of(opener)[1]
        self.assertIsNone(second.get_header("If-none-match"))

    def test_unknown_feed_gets_one_unconditional_request_and_no_cache(self) -> None:
        opener = mock.Mock()
        opener.open.return_value = response(RSS, {"Content-Type": "application/rss+xml"})
        self.fetch(opener)
        req = self.requests_of(opener)[0]
        self.assertIsNone(req.get_header("If-none-match"))
        self.assertIsNone(req.get_header("If-modified-since"))
        self.assertFalse(self.cache_path.exists())  # no validator, nothing to remember

    def test_corrupt_cache_degrades_to_unconditional_fetch(self) -> None:
        self.cache_path.write_text("garbage", encoding="utf-8")
        opener = mock.Mock()
        opener.open.return_value = response(RSS, {})
        body, _ = self.fetch(opener)
        self.assertEqual(body, RSS)
        req = self.requests_of(opener)[0]
        self.assertIsNone(req.get_header("If-none-match"))

    def test_unsolicited_304_without_validators_is_an_error(self) -> None:
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(URL, 304, "Not Modified", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch(opener)
        self.assertEqual(opener.open.call_count, ingest_rss.RETRIES)

    def test_server_errors_still_retry_then_raise(self) -> None:
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(URL, 500, "boom", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            self.fetch(opener)
        self.assertEqual(opener.open.call_count, ingest_rss.RETRIES)

    def test_size_guard_still_wins_over_caching(self) -> None:
        opener = mock.Mock()
        opener.open.return_value = response(b"x" * 33, {"ETag": '"big"'})
        with mock.patch.object(ingest_rss, "MAX_FEED_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "size limit"):
                self.fetch(opener)
        self.assertFalse(self.cache_path.exists())


class NotModifiedFact(unittest.TestCase):
    """ingest_one records the repeated-digest fact without any signature change."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raw = Path(self._tmp.name) / "raw"
        patcher = mock.patch.object(ingest_rss, "RAW_DIR", self.raw)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.src = {"id": "news", "url": URL}

    def ingest(self, minute: int):
        with mock.patch.object(ingest_rss, "fetch_bytes", return_value=(RSS, "application/rss+xml")):
            return ingest_rss.ingest_one(self.src, datetime(2026, 9, 19, 10, minute, tzinfo=timezone.utc))

    def test_repeated_digest_is_recorded_as_not_modified(self) -> None:
        first = self.ingest(0)
        self.assertFalse(first["not_modified"])
        second = self.ingest(1)
        self.assertTrue(second["not_modified"])
        self.assertEqual(second["item_count"], first["item_count"])

    def test_changed_feed_is_not_not_modified(self) -> None:
        self.ingest(0)
        changed = RSS.replace(b"<title>t</title>", b"<title>t2</title>")
        with mock.patch.object(ingest_rss, "fetch_bytes", return_value=(changed, "application/rss+xml")):
            third = ingest_rss.ingest_one(self.src, datetime(2026, 9, 19, 10, 2, tzinfo=timezone.utc))
        self.assertFalse(third["not_modified"])


if __name__ == "__main__":
    unittest.main()
