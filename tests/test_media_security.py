"""Optional publisher metadata uses the same network boundary as RSS."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import harness
import fetch_media


class MediaNetwork(unittest.TestCase):
    def test_private_article_is_rejected_before_opener(self):
        with mock.patch.object(fetch_media, "public_opener") as opener:
            self.assertIsNone(fetch_media.fetch_html("http://127.0.0.1/private"))
            opener.assert_not_called()

    def response(self, body, headers=None):
        response = mock.MagicMock()
        response.headers = headers or {}
        response.read.return_value = body
        response.__enter__.return_value = response
        return response

    def test_fetch_uses_guarded_opener_and_bounded_read(self):
        response = self.response(b"<html>public</html>")
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(fetch_media, "public_http_url") as check, \
                mock.patch.object(fetch_media, "public_opener", return_value=opener):
            self.assertEqual(fetch_media.fetch_html("https://news.example/story"), "<html>public</html>")
            check.assert_called_once_with("https://news.example/story", resolve=True)
        response.read.assert_called_once_with(fetch_media.MAX_HTML_BYTES + 1)

    def test_oversized_html_is_rejected_not_silently_truncated(self):
        response = self.response(b"x" * 33)
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(fetch_media, "public_http_url"), \
                mock.patch.object(fetch_media, "public_opener", return_value=opener), \
                mock.patch.object(fetch_media, "MAX_HTML_BYTES", 32):
            self.assertIsNone(fetch_media.fetch_html("https://news.example/story"))
        opener.open.assert_called_once()

    def test_guarded_redirect_failure_is_not_retried(self):
        opener = mock.Mock()
        opener.open.side_effect = ValueError("Non-public redirect")
        with mock.patch.object(fetch_media, "public_http_url"), \
                mock.patch.object(fetch_media, "public_opener", return_value=opener):
            self.assertIsNone(fetch_media.fetch_html("https://news.example/story", retries=3))
        opener.open.assert_called_once()


class ImageMetadata(unittest.TestCase):
    def test_html_entities_relative_urls_and_attribute_order(self):
        html = '<meta content="/image.jpg?a=1&amp;b=2" property="og:image">'
        self.assertEqual(fetch_media.extract_og(html, "https://news.example/article"), "https://news.example/image.jpg?a=1&b=2")

    def test_unsafe_image_protocols_and_local_targets_are_skipped(self):
        for url in ("javascript:alert(1)", "data:image/svg+xml,hi", "http://news.example/image", "https://127.0.0.1/image", "https://localhost/image", "https://user:pass@news.example/image"):
            html = f'<meta property="og:image" content="{url}"><meta property="twitter:image" content="https://cdn.example/safe.jpg">'
            self.assertEqual(fetch_media.extract_og(html, "https://news.example/article"), "https://cdn.example/safe.jpg", url)

    def test_commented_out_metadata_is_not_used(self):
        self.assertIsNone(fetch_media.extract_og('<!-- <meta property="og:image" content="https://news.example/old.jpg"> -->', "https://news.example/article"))

    def test_unsafe_cached_images_are_not_republished(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "faces.json"
            out.write_text(json.dumps({"faces": {"a": {"image_url": "javascript:alert(1)", "article_url": "https://news.example/a"}, "retired": {"image_url": "https://cdn.example/old.jpg"}}}), encoding="utf-8")
            candidates = [{"id": "a", "url": "https://news.example/a"}]
            with mock.patch.object(fetch_media, "OUT", out), \
                    mock.patch.object(fetch_media, "load_candidates", return_value=candidates), \
                    mock.patch.object(fetch_media, "load_issues", return_value=[]), \
                    mock.patch.object(fetch_media, "map_scope", return_value=candidates), \
                    mock.patch.object(fetch_media, "fetch_html", return_value=None):
                self.assertEqual(fetch_media.main(), 0)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertIsNone(result["faces"]["a"]["image_url"])
            self.assertNotIn("retired", result["faces"])


if __name__ == "__main__":
    unittest.main()
