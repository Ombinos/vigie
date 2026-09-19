"""Vigie v0 — ingest enabled RSS/Atom feeds into data/raw (append-only).

Stdlib only. No pip. Parses the subset of sources.yaml we actually ship.
Does not enrich, rank, or invent news. Fetch is the scar.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = ROOT / "sources.yaml"
RAW_DIR = ROOT / "data" / "raw"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Vigie/0.1"
)
TIMEOUT = 25
RETRIES = 3
MAX_FEED_BYTES = 8 * 1024 * 1024

# CBC often resets Python urllib with a custom UA; keep browser-like UA + alts.
URL_ALTERNATES = {
    "https://rss.cbc.ca/lineup/canada-montreal.xml": [
        "https://www.cbc.ca/cmlink/rss-canada-montreal",
        "https://www.cbc.ca/webfeed/rss/rss-canada-montreal",
    ],
    "https://rss.cbc.ca/lineup/politics.xml": [
        "https://www.cbc.ca/cmlink/rss-politics",
        "https://www.cbc.ca/webfeed/rss/rss-politics",
    ],
}

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _scalar(val: str):
    val = val.strip()
    if "#" in val:
        val = val.split("#", 1)[0].strip()
    if val in ("", "|", ">", "null", "~"):
        return None
    if val.lower() in ("true", "false"):
        return val.lower() == "true"
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    return val


def load_enabled_by_type(path: Path, source_type: str) -> list[dict]:
    """Minimal parser for our sources.yaml list-of-maps. Not a general YAML engine."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^sources:\n(.*?)(?=^[a-zA-Z].*:|\Z)", text)
    if not m:
        raise SystemExit(f"No sources: block in {path}")
    body = m.group(1)
    chunks = re.split(r"\n  - id:", "\n" + body)
    out: list[dict] = []
    for chunk in chunks:
        chunk = chunk.strip("\n")
        if not chunk.strip() or chunk.strip().startswith("#"):
            continue
        if not chunk.lstrip().startswith("id:"):
            chunk = "id:" + chunk
        rec: dict = {}
        for raw_line in chunk.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            if line.startswith("- "):
                line = line[2:]
            key, _, val = line.partition(":")
            rec[key.strip()] = _scalar(val)
        if rec.get("enabled") is True and rec.get("type") == source_type and rec.get("id") and rec.get("url"):
            out.append(rec)
    return out


def load_enabled_rss(path: Path) -> list[dict]:
    return load_enabled_by_type(path, "rss")


def public_http_url(url: str, *, resolve: bool = False) -> str:
    """Reject executable URLs and local network targets before using feed input."""
    if not isinstance(url, str) or any(ord(ch) < 32 for ch in url) or "\\" in url:
        raise ValueError("Invalid URL characters")
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() not in {"https", "http"} or not host:
        raise ValueError("An absolute HTTP(S) URL is required")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credentials in URLs are not allowed")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Only web ports are allowed")
    if ("." not in host and ":" not in host) or host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "%" in host:
        raise ValueError("Local hostnames are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is None and re.fullmatch(r"(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+))*", host, re.I):
        raise ValueError("Ambiguous numeric hostnames are not allowed")
    if address is not None and not _public_address(address):
        raise ValueError("Non-public IP addresses are not allowed")
    if resolve:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not addresses or any(not _public_address(ipaddress.ip_address(info[4][0])) for info in addresses):
            raise ValueError("Host does not resolve exclusively to public addresses")
    return url.strip()


def _public_address(address) -> bool:
    return address.is_global and not address.is_multicast


def _public_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """Resolve once, validate every answer, then connect to an exact IP address.

    HTTP Host and HTTPS certificate/SNI still use the original hostname. No second
    resolver lookup is allowed between validation and opening the socket.
    """
    host, port = address
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not answers or any(not _public_address(ipaddress.ip_address(info[4][0])) for info in answers):
        raise ValueError("Connection destination is not public")
    last_error = None
    for family, socktype, proto, _, sockaddr in answers:
        connection = socket.socket(family, socktype, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                connection.settimeout(timeout)
            if source_address:
                connection.bind(source_address)
            connection.connect(sockaddr)
            return connection
        except OSError as exc:
            connection.close()
            last_error = exc
    raise last_error or OSError("No usable public address")


class _PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _public_connection


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _public_connection


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTPConnection, req)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPSConnection, req, context=self._context)


class PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_http_url(newurl, resolve=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_opener():
    """Shared outbound HTTP boundary for feeds and optional publisher metadata."""
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), PublicRedirectHandler(),
        _PublicHTTPHandler(), _PublicHTTPSHandler(context=ctx),
    )


def _http_cache_path() -> Path:
    """Resolved through RAW_DIR at call time so tests can redirect it."""
    return RAW_DIR / "_http_cache.json"


def _body_cache_path(url: str) -> Path:
    return RAW_DIR / "_bodies" / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".body")


def _load_http_cache() -> dict:
    try:
        doc = json.loads(_http_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _save_http_cache(cache: dict) -> None:
    try:
        path = _http_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".tmp")
        part.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        part.replace(path)
    except (OSError, ValueError, TypeError):
        pass


def _read_body_cache(url: str) -> bytes | None:
    try:
        raw = _body_cache_path(url).read_bytes()
    except OSError:
        return None
    return raw or None


def _write_body_cache(url: str, raw: bytes) -> None:
    try:
        path = _body_cache_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".tmp")
        part.write_bytes(raw)
        part.replace(path)
    except OSError:
        pass


def fetch_bytes(url: str) -> tuple[bytes, str | None]:
    """Fetch with retries, optional alternate URLs (CBC scar) and conditional GET.

    Bandwidth is rent: when a server previously sent an ETag or
    Last-Modified, the next request carries the matching conditional header
    and a 304 answer returns the cached body - zero payload bytes on the
    wire, caller unchanged (the snapshot digest simply repeats, which
    ingest_one records as not_modified). A validator without a cached body
    falls back to one unconditional fetch. Cache files live beside the raw
    snapshots; a corrupt cache degrades to unconditional fetching, never to
    a wrong body.
    """
    candidates = [url] + list(URL_ALTERNATES.get(url, []))
    opener = public_opener()
    cache = _load_http_cache()
    last_err: Exception | None = None
    for candidate in candidates:
        entry = cache.get(candidate)
        entry = entry if isinstance(entry, dict) else {}
        validators: dict[str, str] = {}
        if isinstance(entry.get("etag"), str) and entry["etag"]:
            validators["If-None-Match"] = entry["etag"]
        if isinstance(entry.get("last_modified"), str) and entry["last_modified"]:
            validators["If-Modified-Since"] = entry["last_modified"]
        for conditional in ((True, False) if validators else (False,)):
            for attempt in range(1, RETRIES + 1):
                try:
                    public_http_url(candidate, resolve=True)
                    headers = {
                        "User-Agent": USER_AGENT,
                        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
                        "Accept-Language": "en-CA,fr-CA;q=0.9,en;q=0.8",
                    }
                    if conditional:
                        headers.update(validators)
                    req = urllib.request.Request(candidate, headers=headers, method="GET")
                    with opener.open(req, timeout=TIMEOUT) as resp:
                        content_type = resp.headers.get("Content-Type")
                        content_length = resp.headers.get("Content-Length")
                        # Header hint only — a malformed or absent value must not
                        # fail the fetch; the bounded read below is the real cap.
                        try:
                            declared = int(content_length) if content_length else None
                        except ValueError:
                            declared = None
                        if declared is not None and declared > MAX_FEED_BYTES:
                            raise ValueError("Feed exceeds size limit")
                        body = resp.read(MAX_FEED_BYTES + 1)
                        if len(body) > MAX_FEED_BYTES:
                            raise ValueError("Feed exceeds size limit")
                        etag = resp.headers.get("ETag")
                        last_modified = resp.headers.get("Last-Modified")
                        has_etag = isinstance(etag, str) and bool(etag)
                        has_lm = isinstance(last_modified, str) and bool(last_modified)
                        if has_etag or has_lm:
                            cache[candidate] = {
                                "etag": etag if has_etag else None,
                                "last_modified": last_modified if has_lm else None,
                                "content_type": content_type,
                                "updated_at": utc_now().isoformat(timespec="seconds"),
                            }
                            _save_http_cache(cache)
                            _write_body_cache(candidate, body)
                        return body, content_type
                except ValueError:
                    raise
                except urllib.error.HTTPError as e:
                    if e.code == 304 and conditional:
                        cached_body = _read_body_cache(candidate)
                        if cached_body is not None:
                            return cached_body, entry.get("content_type")
                        break  # validator without body: refetch unconditionally
                    last_err = e
                    continue
                except Exception as e:
                    last_err = e
                    continue
    assert last_err is not None
    raise last_err


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    t = " ".join("".join(el.itertext()).split())
    return t or None


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in el if _local(child.tag).lower() == name.lower()), None)


def parse_feed(xml_bytes: bytes, base_url: str | None = None) -> list[dict]:
    if len(xml_bytes) > MAX_FEED_BYTES:
        raise ValueError("Feed exceeds size limit")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", xml_bytes.replace(b"\x00", b""), re.I):
        raise ValueError("Feed document type and entity declarations are not allowed")
    root = ET.fromstring(xml_bytes)
    tag = _local(root.tag).lower()
    items: list[dict] = []
    if tag == "rss" or tag == "rdf":
        nodes = [n for n in root.iter() if _local(n.tag).lower() == "item"]
        for item in nodes:
            title = _text(_child(item, "title"))
            link = _text(_child(item, "link"))
            if not link:
                guid_el = _child(item, "guid")
                if guid_el is not None and guid_el.attrib.get("isPermaLink", "true").lower() != "false":
                    guid_text = _text(guid_el)
                    if guid_text and guid_text.startswith(("https://", "http://")):
                        link = guid_text
            desc = _text(_child(item, "description")) or _text(_child(item, "encoded"))
            pub = _text(_child(item, "pubdate")) or _text(_child(item, "date"))
            guid_el = _child(item, "guid")
            guid = _text(guid_el)
            items.append(
                {
                    "title": title,
                    "url": link,
                    "body": desc,
                    "published_at": pub,
                    "guid": guid,
                }
            )
    elif tag == "feed":
        for entry in list(root):
            if _local(entry.tag).lower() != "entry":
                continue
            title = _text(entry.find("title"))
            if title is None:
                for child in entry:
                    if _local(child.tag).lower() == "title":
                        title = _text(child)
                        break
            link = None
            for child in entry:
                if _local(child.tag).lower() == "link":
                    href = child.attrib.get("href")
                    rel = child.attrib.get("rel", "alternate")
                    if href and rel in ("alternate", ""):
                        link = href
                        break
            summary = None
            for child in entry:
                loc = _local(child.tag).lower()
                if loc in ("summary", "content"):
                    summary = _text(child) or ("".join(child.itertext()).strip() or None)
                    if summary:
                        break
            published = _text(_child(entry, "published"))
            updated = _text(_child(entry, "updated"))
            eid = None
            for child in entry:
                if _local(child.tag).lower() == "id":
                    eid = _text(child)
                    break
            items.append(
                {
                    "title": title,
                    "url": link,
                    "body": summary,
                    "published_at": published,
                    "updated_at": updated,
                    "guid": eid,
                }
            )
    else:
        raise ValueError(f"Unsupported feed root: {tag}")
    if base_url:
        for item in items:
            if item.get("url"):
                item["url"] = urljoin(base_url, item["url"])
    return [it for it in items if it.get("url") or it.get("title")]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest_one(src: dict, fetched_at: datetime) -> dict:
    source_id = src["id"]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", source_id):
        raise ValueError("Invalid source identifier")
    url = src["url"]
    dest_dir = RAW_DIR / source_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    try:
        raw, content_type = fetch_bytes(url)
    except Exception as e:
        err = {
            "ok": False,
            "source_id": source_id,
            "url": url,
            "error": f"{type(e).__name__}: {e}",
            "fetched_at": fetched_at.isoformat(),
        }
        err_path = dest_dir / f"{stamp}_error.json"
        err_path.write_text(json.dumps(err, ensure_ascii=False, indent=2), encoding="utf-8")
        return err

    digest = sha256_hex(raw)
    prev_xmls = sorted(dest_dir.glob("*.xml"))
    # The collection happened; the bytes simply repeat the previous snapshot
    # (a 304 or an unchanged feed). Recorded as a fact, never hidden.
    not_modified = bool(prev_xmls) and prev_xmls[-1].name.endswith(f"_{digest[:12]}.xml")
    xml_path = dest_dir / f"{stamp}_{digest[:12]}.xml"
    xml_path.write_bytes(raw)

    parse_error = None
    items: list[dict] = []
    try:
        items = parse_feed(raw, url)
    except Exception as e:
        parse_error = f"{type(e).__name__}: {e}"

    raw_item_count = len(items)
    max_items = src.get("max_items")
    capped = False
    if isinstance(max_items, int) and max_items > 0 and len(items) > max_items:
        items = items[:max_items]
        capped = True

    source_kind = (src.get("source_kind") or "media").strip().lower()
    if source_kind not in ("media", "official"):
        source_kind = "media"

    def rel_or_abs(p: Path) -> str:
        try:
            return str(p.relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")

    payload = {
        "ok": parse_error is None,
        "source_id": source_id,
        "source_name": src.get("name"),
        "institution": src.get("institution") or source_id,
        "institution_name": src.get("institution_name") or src.get("name"),
        "language": src.get("language"),
        "geo": src.get("geo"),
        "nest_role": src.get("nest_role"),
        "source_kind": source_kind,
        "feed_url": url,
        "fetched_at": fetched_at.isoformat(),
        "content_type": content_type,
        "bytes": len(raw),
        "sha256": digest,
        "xml_file": rel_or_abs(xml_path),
        "raw_item_count": raw_item_count,
        "not_modified": not_modified,
        "max_items": max_items if isinstance(max_items, int) else None,
        "capped": capped,
        "item_count": len(items),
        "parse_error": parse_error,
        "error": parse_error,
        "items": [
            {
                "source_id": source_id,
                "source_kind": source_kind,
                "url": it.get("url"),
                "title": it.get("title"),
                "body": it.get("body"),
                "published_at": it.get("published_at"),
                "updated_at": it.get("updated_at"),
                "guid": it.get("guid"),
                "language": src.get("language"),
                "fetched_at": fetched_at.isoformat(),
            }
            for it in items
        ],
    }
    meta_path = dest_dir / f"{stamp}_{digest[:12]}.json"
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["meta_file"] = rel_or_abs(meta_path)
    return payload


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    sources = load_enabled_rss(SOURCES_PATH)
    fetched_at = utc_now()
    run = {
        "fetched_at": fetched_at.isoformat(),
        "sources_file": "sources.yaml",
        "enabled_rss": [s["id"] for s in sources],
        "results": [],
    }
    print(f"Vigie ingest {fetched_at.isoformat()} — {len(sources)} enabled RSS")
    for src in sources:
        print(f"  fetch {src['id']} ...", flush=True)
        result = ingest_one(src, fetched_at)
        slim = {
            "source_id": result["source_id"],
            "ok": result["ok"],
            "item_count": result.get("item_count", 0),
            "error": result.get("error"),
            "parse_error": result.get("parse_error"),
            "xml_file": result.get("xml_file"),
            "meta_file": result.get("meta_file"),
        }
        run["results"].append(slim)
        if result["ok"]:
            print(f"    ok  items={slim['item_count']}  {slim.get('meta_file')}")
        else:
            print(f"    FAIL {slim['error']}")
    stamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    run_path = RAW_DIR / f"_run_{stamp}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    ok_n = sum(1 for r in run["results"] if r["ok"])
    items_n = sum(r.get("item_count") or 0 for r in run["results"])
    print(f"run log: {run_path.relative_to(ROOT)}")
    print(f"done: {ok_n}/{len(sources)} feeds ok, {items_n} items")
    return 0 if ok_n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
