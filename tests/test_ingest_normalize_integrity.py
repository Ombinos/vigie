"""Regression cases at Vigie's untrusted feed and freshness boundary."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import harness
import enrich
import ingest_rss
import normalize


class FeedParsing(unittest.TestCase):
    def test_namespaced_rdf_preserves_text_date_and_link(self):
        xml = b'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
            <item><title>Street <b>closure</b></title><link>/story</link>
            <description>Use the detour</description><dc:date>2026-09-16T10:00:00Z</dc:date>
            </item></rdf:RDF>'''
        item = ingest_rss.parse_feed(xml, "https://news.example/feed")[0]
        self.assertEqual(item["title"], "Street closure")
        self.assertEqual(item["url"], "https://news.example/story")
        self.assertEqual(item["published_at"], "2026-09-16T10:00:00Z")

    def test_atom_updated_never_replaces_publication_date(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <title>Transit</title><updated>2026-09-16T10:00:00Z</updated>
            <published>2026-09-01T10:00:00Z</published>
            <link rel="self" href="https://news.example/api/item"/>
            <link rel="alternate" href="https://news.example/story"/>
            </entry></feed>'''
        item = ingest_rss.parse_feed(xml)[0]
        self.assertEqual(item["published_at"], "2026-09-01T10:00:00Z")
        self.assertEqual(item["updated_at"], "2026-09-16T10:00:00Z")
        self.assertEqual(item["url"], "https://news.example/story")

    def test_atom_self_link_and_updated_only_are_not_article_publication(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <title>Transit</title><updated>2026-09-16T10:00:00Z</updated>
            <link rel="self" href="https://news.example/api/item"/></entry></feed>'''
        item = ingest_rss.parse_feed(xml)[0]
        self.assertIsNone(item["url"])
        self.assertIsNone(item["published_at"])

    def test_guid_is_not_an_article_url_unless_it_is_a_permalink(self):
        xml = b'''<rss><channel><item><title>Story</title>
            <guid isPermaLink="false">https://news.example/internal-id</guid>
            </item></channel></rss>'''
        self.assertIsNone(ingest_rss.parse_feed(xml)[0]["url"])

    def test_html_and_entity_documents_are_failed_feeds(self):
        for xml in (b"<html><body>Access denied</body></html>",
                    b'<!DOCTYPE rss [<!ENTITY x "hello">]><rss/>',
                    '<!DOCTYPE rss [<!ENTITY x "hello">]><rss/>'.encode("utf-16")):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                ingest_rss.parse_feed(xml)

    def test_parser_failure_is_recorded_as_unsuccessful_ingest(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ingest_rss, "RAW_DIR", Path(tmp)), \
                mock.patch.object(ingest_rss, "fetch_bytes", return_value=(b"<html>denied</html>", "text/html")):
            result = ingest_rss.ingest_one({"id": "news", "url": "https://news.example/feed"}, datetime.now(timezone.utc))
            self.assertFalse(result["ok"])
            self.assertIn("Unsupported feed", result["parse_error"])
            self.assertEqual(result["item_count"], 0)


class FeedNetworkBoundary(unittest.TestCase):
    def test_executable_local_and_ambiguous_urls_are_rejected(self):
        for url in ("javascript:alert(1)", "data:text/html,hello", "file:///etc/passwd", "/story",
                    "http://localhost/x", "http://127.0.0.1/x", "http://127.1/x", "http://2130706433/x",
                    "http://0x7f000001/x", "http://10.1.2.3/x", "http://[::1]/x", "http://thing.internal/x",
                    "http://224.0.0.1/x", "http://[ff02::1]/x", "http://[2606:4700:4700::1111%eth0]/x",
                    "https://user:pass@news.example/x", "https://news.example:8123/x", "https://news.example\\@127.0.0.1/x"):
            with self.subTest(url=url):
                self.assertIsNone(normalize.canonical_url(url))

    def test_public_host_with_private_dns_is_rejected(self):
        with mock.patch.object(ingest_rss.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.3", 443))]):
            with self.assertRaises(ValueError):
                ingest_rss.public_http_url("https://news.example/feed", resolve=True)

    def test_redirect_destination_is_checked(self):
        handler = ingest_rss.PublicRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/metadata")

    def test_connection_pins_the_address_it_validates(self):
        public = (2, 1, 6, "", ("1.1.1.1", 443))
        private = (2, 1, 6, "", ("127.0.0.1", 443))
        with mock.patch.object(ingest_rss.socket, "getaddrinfo", side_effect=[[public], [private]]) as resolver, \
                mock.patch.object(ingest_rss.socket, "socket") as make_socket:
            connection = ingest_rss._public_connection(("news.example", 443), 3)
            self.assertIs(connection, make_socket.return_value)
            make_socket.return_value.connect.assert_called_once_with(("1.1.1.1", 443))
            resolver.assert_called_once()

    def test_rebinding_between_url_check_and_connect_is_rejected(self):
        public = (2, 1, 6, "", ("1.1.1.1", 443))
        private = (2, 1, 6, "", ("127.0.0.1", 443))
        with mock.patch.object(ingest_rss.socket, "getaddrinfo", side_effect=[[public], [private]]), \
                mock.patch.object(ingest_rss.socket, "socket") as make_socket:
            ingest_rss.public_http_url("https://news.example/feed", resolve=True)
            with self.assertRaisesRegex(ValueError, "not public"):
                ingest_rss._public_connection(("news.example", 443), 3)
            make_socket.assert_not_called()

    def test_pinned_https_still_checks_original_tls_hostname(self):
        with mock.patch.object(ingest_rss, "_public_connection", return_value=mock.Mock()):
            connection = ingest_rss._PublicHTTPSConnection("news.example")
            with mock.patch.object(connection._context, "wrap_socket") as wrap_socket:
                connection.connect()
                self.assertEqual(wrap_socket.call_args.kwargs["server_hostname"], "news.example")

    def test_download_is_bounded_even_without_content_length(self):
        response = mock.MagicMock()
        response.headers = {"Content-Type": "application/rss+xml"}
        response.read.return_value = b"x" * 33
        response.__enter__.return_value = response
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(ingest_rss, "public_http_url"), \
                mock.patch.object(ingest_rss.urllib.request, "build_opener", return_value=opener), \
                mock.patch.object(ingest_rss, "MAX_FEED_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "size limit"):
                ingest_rss.fetch_bytes("https://news.example/feed")
        response.read.assert_called_once_with(33)


class CandidateIntegrity(unittest.TestCase):
    def test_tracking_parameters_dedupe_but_functional_query_is_preserved(self):
        clean = "https://news.example/article?id=42&lang=fr"
        tracked = "https://NEWS.example:443/article?id=42&utm_source=email&lang=fr&fbclid=abc#top"
        self.assertEqual(normalize.canonical_url(tracked), clean)
        self.assertNotEqual(normalize.canonical_url(clean), normalize.canonical_url(clean.replace("42", "43")))
        self.assertEqual(normalize.stable_id(tracked, "a", "Title", None), normalize.stable_id(clean, "a", "Title", None))

    def test_linkless_guids_do_not_collide_between_publishers(self):
        self.assertNotEqual(normalize.stable_id(None, "a", "Title", "123"), normalize.stable_id(None, "b", "Title", "123"))

    def test_canonicalization_preserves_path_and_signed_query_bytes(self):
        url = "https://news.example/article/?query=a%20b&opaque=%2f%2F&utm_source=email&signature=A%2BB"
        self.assertEqual(normalize.canonical_url(url), "https://news.example/article/?query=a%20b&opaque=%2f%2F&signature=A%2BB")
        self.assertNotEqual(normalize.canonical_url("https://news.example/a/"), normalize.canonical_url("https://news.example/a"))

    def test_html_entities_and_script_content_do_not_pollute_evidence(self):
        item = normalize.normalize_item({"title": "<b>Québec</b> &amp; nous", "body": "<p>À pied.</p><script>Limoilou</script><p>Vélo.</p>"}, {"source_id": "a"})
        self.assertEqual(item["title"], "Québec & nous")
        self.assertEqual(item["summary"], "À pied. Vélo.")

    def test_bad_article_url_cannot_reach_public_candidates(self):
        self.assertIsNone(normalize.normalize_item({"title": "Click me", "url": "javascript:alert(1)"}, {}))

    def test_rfc_date_becomes_explicit_utc_without_inventing_undated_dates(self):
        meta = {"source_id": "a", "fetched_at": "2026-09-16T15:00:00Z"}
        item = normalize.normalize_item({"title": "Story", "published_at": "Wed, 16 Sep 2026 10:00:00 -0400"}, meta)
        self.assertEqual(item["published_at"], "2026-09-16T14:00:00+00:00")
        for date, status in ((None, "missing"), ("not a date", "invalid"), ("2026-09-16T15:00:00", "invalid"), ("0001-01-01T00:00:00+01:00", "invalid"), ("9999-12-31T23:59:59-01:00", "invalid"), ("2027-09-16T15:00:00Z", "future")):
            with self.subTest(date=date):
                item = normalize.normalize_item({"title": "Story", "published_at": date}, meta)
                self.assertIsNone(item["published_at"])
                self.assertEqual(item["publication_date_status"], status)

    def test_source_metadata_has_authority_over_item_kind(self):
        item = normalize.normalize_item({"title": "Story", "source_kind": "official"}, {"source_id": "a", "source_kind": "media", "institution": "publisher"})
        self.assertEqual(item["source_kind"], "media")
        self.assertEqual(item["institution"], "publisher")


class OfflineRebuildEditionIdentity(unittest.TestCase):
    """An offline rebuild of the same raw snapshots is the same edition.

    dossier_history keys an edition on normalized_at; if normalize stamped the
    rebuild clock instead of the collection clock, every --offline run would
    inflate every dossier's editions_seen (contradicting the house law).
    """

    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        raw, out = root / "raw", root / "normalized"
        sources = root / "sources.yaml"
        raw.mkdir()
        sources.write_text(
            "sources:\n  - id: a\n    type: rss\n    name: a\n"
            "    url: https://news.example/a\n    enabled: true\n",
            encoding="utf-8",
        )
        dest = raw / "a"
        dest.mkdir()
        (dest / "20260918T060000Z_ok.json").write_text(json.dumps({
            "ok": True, "source_id": "a", "fetched_at": "2026-09-18T06:00:00+00:00",
            "items": [{"title": "Avis", "url": "https://news.example/1"}],
        }), encoding="utf-8")
        return raw, out, sources

    def _normalized_at(self, raw: Path, out: Path, sources: Path, build: datetime) -> str:
        with mock.patch.multiple(normalize, RAW_DIR=raw, OUT_DIR=out, SOURCES_PATH=sources), \
                mock.patch.object(normalize, "utc_now", return_value=build):
            self.assertEqual(normalize.main(), 0)
        return json.loads((out / "latest_candidates.json").read_text(encoding="utf-8"))["normalized_at"]

    def test_rebuild_clock_is_not_the_edition_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw, out, sources = self._fixture(Path(tmp))
            first = self._normalized_at(raw, out, sources, datetime(2026, 9, 18, 7, tzinfo=timezone.utc))
            second = self._normalized_at(raw, out, sources, datetime(2026, 9, 18, 13, tzinfo=timezone.utc))
            self.assertEqual(first, second)
            self.assertEqual(first, "2026-09-18T06:00:00+00:00")

    def test_newest_ingest_run_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw, out, sources = self._fixture(Path(tmp))
            (raw / "_run_20260918T060000Z.json").write_text(
                json.dumps({"fetched_at": "2026-09-18T06:00:00+00:00"}), encoding="utf-8")
            (raw / "_run_20260918T090000Z.json").write_text(
                json.dumps({"fetched_at": "2026-09-18T09:00:00+00:00"}), encoding="utf-8")
            stamp = self._normalized_at(raw, out, sources, datetime(2026, 9, 18, 13, tzinfo=timezone.utc))
            self.assertEqual(stamp, "2026-09-18T09:00:00+00:00")


class NormalizationFreshness(unittest.TestCase):
    def test_disabled_failed_stale_and_corrupt_feeds_do_not_resurface(self):
        now = datetime(2026, 9, 16, 18, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            out = root / "normalized"
            sources = root / "sources.yaml"
            sources.write_text("sources:\n" + "".join(
                f"  - id: {sid}\n    type: rss\n    name: {sid}\n    url: https://news.example/{sid}\n    enabled: {'false' if sid == 'disabled' else 'true'}\n"
                for sid in ("fresh", "failed", "stale", "broken", "bad-items", "disabled", "missing")), encoding="utf-8")
            for sid in ("fresh", "failed", "stale", "broken", "bad-items", "disabled"):
                dest = raw / sid
                dest.mkdir(parents=True)
                fetched = now - timedelta(hours=49 if sid == "stale" else 1)
                payload = {"ok": True, "source_id": sid, "fetched_at": fetched.isoformat(), "items": [
                    {"title": sid, "url": f"https://news.example/{sid}"},
                    {"title": sid, "url": f"https://news.example/{sid}?utm_source=duplicate"}]}
                if sid == "bad-items":
                    payload["items"] = 42
                (dest / "20260916T170000Z_ok.json").write_text(json.dumps(payload), encoding="utf-8")
                if sid == "failed":
                    (dest / "20260916T180000Z_error.json").write_text(json.dumps({"ok": False, "error": "Timeout"}), encoding="utf-8")
                if sid == "broken":
                    (dest / "20260916T180000Z_broken.json").write_text("{", encoding="utf-8")
            with mock.patch.multiple(normalize, RAW_DIR=raw, OUT_DIR=out, SOURCES_PATH=sources), mock.patch.object(normalize, "utc_now", return_value=now):
                self.assertEqual(normalize.main(), 0)
            result = json.loads((out / "latest_candidates.json").read_text(encoding="utf-8"))
            self.assertEqual([c["source_id"] for c in result["candidates"]], ["fresh"])
            self.assertEqual(result["source_status"]["failed"]["status"], "failed")
            self.assertEqual(result["source_status"]["stale"]["status"], "stale")
            self.assertEqual(result["source_status"]["broken"]["status"], "invalid")
            self.assertEqual(result["source_status"]["bad-items"]["status"], "invalid")
            self.assertEqual(result["source_status"]["missing"]["status"], "missing")
            self.assertNotIn("disabled", result["source_status"])


class GeographicEvidence(unittest.TestCase):
    def propose(self, title, url="https://news.example/story", nest="primary"):
        candidate = {"title": title, "url": url, "nest_role": nest, "geo": "quebec-city"}
        return enrich.propose_geo(candidate, enrich.blob(candidate))["geo"]

    def test_publisher_url_cannot_create_local_relevance(self):
        self.assertEqual(self.propose("Un musée ouvre à Tokyo", "https://quebec.ca/quebec-city?city=Limoilou"), "linked")

    def test_primary_media_source_does_not_localize_world_news(self):
        self.assertEqual(self.propose("Un incendie à Los Angeles"), "linked")

    def test_vanier_in_ottawa_does_not_become_quebec_city(self):
        self.assertNotEqual(self.propose("Travaux dans Vanier à Ottawa"), "quebec-city")
        self.assertEqual(self.propose("Travaux dans Vanier à Québec"), "quebec-city")

    def test_quebec_effect_of_world_event_keeps_provincial_relevance(self):
        self.assertEqual(self.propose("Les tarifs de Trump frappent les entreprises du Québec", nest="province"), "quebec")

    def test_city_venues_and_explicit_city_location_are_recognized(self):
        for title in ("Déficit d'opération du Centre Vidéotron", "Les scientifiques manifestent à Québec", "Travaux sur le pont Pierre-Laporte", "Le projet TramCité avance"):
            with self.subTest(title=title):
                self.assertEqual(self.propose(title), "quebec-city")
        self.assertEqual(self.propose("La hausse des loyers au Québec"), "quebec")
        self.assertEqual(self.propose("Ottawa demande à Québec de négocier"), "quebec")

    def test_security_topic_does_not_invent_a_death(self):
        impacts = enrich.propose_impacts(enrich.propose_topics("La police inaugure un poste à Limoilou"))
        self.assertNotIn("death", [impact["label"] for impact in impacts])

    def test_resident_transport_and_plural_housing_are_recognized(self):
        self.assertIn("transport", [topic["topic"] for topic in enrich.propose_topics("Entraves sur le parcours du RTC")])
        self.assertIn("housing", [topic["topic"] for topic in enrich.propose_topics("200 logements et des loyers modérés")])


if __name__ == "__main__":
    unittest.main()
