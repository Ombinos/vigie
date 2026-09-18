"""Vigie brief media v1 - locally served publisher preview images.

The front door must never make a reader's browser contact a publisher: that
would trade the product's core promise (no account, no tracking, one origin)
for decoration. So preview images are fetched HERE, at collection time,
through the same guarded network boundary as RSS (public_http_url +
public_opener, HTTPS-only, public addresses only), sniffed for their true
format, size-capped, and stored under data/media/brief/. The renderer only
ever emits same-origin /media/<uid>.<ext> references; staging refuses any
media file that does not match that shape.

House law:
  * publisher og:image / twitter:image only - never stock, never generated,
    never a crop we invent. A silent publisher means no image, not a filler.
  * bytes are sniffed, not trusted: the declared Content-Type never decides
    the stored extension, and SVG is never stored - a scriptable format is
    never served from our own origin.
  * identity is the renderer's identity: uid = sha256(safe_url(url))[:20],
    the exact derivation prepare_items uses, so bookmarks and marks survive.
  * fail-soft like the roadworks feed: a media outage keeps the previous
    manifest and never blocks the news pipeline (always exits 0).
  * the manifest never references a missing file; orphan files are pruned
    only after the new manifest is durable on disk.
  * new articles get their image on the next refresh - an honest crawl lag,
    never a placeholder.

No LLM. Runs between cluster and rank so the rendered edition picks up the
fresh manifest. --offline reuses the cache and makes no network requests.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fetch_media  # noqa: E402  (fetch_html, extract_og, USER_AGENT, TIMEOUT)
import resident_brief as brief  # noqa: E402  (safe_url - identity must match the renderer)
from ingest_rss import public_http_url, public_opener  # noqa: E402

RANKED = ROOT / "data" / "normalized" / "latest_ranked.json"
ENRICHED = ROOT / "data" / "normalized" / "latest_enriched.json"
MEDIA_DIR = ROOT / "data" / "media" / "brief"
MANIFEST = ROOT / "data" / "media" / "brief_manifest.json"

METHOD = "brief-media-v1"
SCOPE_CAP = 60        # top articles in display order whose images the brief tracks
FETCH_CAP = 40        # new article fetches per run ceiling - wallet thin
MAX_IMAGE_BYTES = 700_000
SLEEP = 0.08
FILE_RE = re.compile(r"[a-f0-9]{20}\.(?:jpg|jpeg|png|webp|avif|gif)")


def sniff_image(raw: bytes) -> str | None:
    """True format from magic bytes; the declared Content-Type never decides.

    SVG is deliberately absent: a scriptable format is never served from our
    own origin, whatever a publisher's header claims.
    """
    if not isinstance(raw, bytes):
        return None
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[4:8] == b"ftyp" and raw[8:12] in (b"avif", b"avis"):
        return "avif"
    return None


def fetch_image(url: str, referer: str = "", *, retries: int = 2) -> tuple[bytes, str] | None:
    """Guarded image GET -> (bytes, true extension) or None. Never raises."""
    try:
        public_http_url(url, resolve=True)
    except (ValueError, OSError, TypeError):
        return None
    headers = {
        "User-Agent": fetch_media.USER_AGENT,
        "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    opener = public_opener()
    attempts = max(1, min(retries, 3))
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with opener.open(req, timeout=fetch_media.TIMEOUT) as resp:
                length = resp.headers.get("Content-Length")
                if length and str(length).isdigit() and int(length) > MAX_IMAGE_BYTES:
                    return None
                raw = resp.read(MAX_IMAGE_BYTES + 1)
        except ValueError:
            return None  # a guarded redirect failure is never retried
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            if attempt + 1 < attempts:
                time.sleep(0.35 * (attempt + 1))
            continue
        if len(raw) > MAX_IMAGE_BYTES:
            return None
        ext = sniff_image(raw)
        return (raw, ext) if ext else None
    return None


def brief_uid(url: object) -> str:
    """Same identity as the renderer: sha256 of the canonical safe URL, 20 hex."""
    safe = brief.safe_url(url)
    return hashlib.sha256(safe.encode()).hexdigest()[:20] if safe else ""


def load_scope() -> list[dict]:
    """Top SCOPE_CAP candidates in display order.

    Prefers the previous ranked edition (the order the brief shows); falls
    back to the current enriched store. New articles enter the scope on the
    next run - an honest crawl lag, never a placeholder.
    """
    for path in (RANKED, ENRICHED):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, list):
            cands = payload
        elif isinstance(payload, dict):
            cands = payload.get("candidates") or payload.get("ranked") or []
        else:
            continue
        cands = [c for c in cands if isinstance(c, dict) and c.get("url")]
        if cands:
            return cands[:SCOPE_CAP]
    return []


def load_manifest(path: Path = MANIFEST) -> dict:
    """uid -> entry from a brief-media-v1 manifest; foreign or corrupt -> {}."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("method") != METHOD:
        return {}
    media = doc.get("media")
    if not isinstance(media, dict):
        return {}
    return {str(k): v for k, v in media.items() if isinstance(v, dict)}


def update_media(scope: list[dict], *, offline: bool = False,
                 media_dir: Path = MEDIA_DIR, manifest_path: Path = MANIFEST) -> dict:
    """Advance the local image store by one collection; returns the new manifest.

    Keeps still-scoped entries whose file exists, retries negatives and fills
    gaps within the fetch budget, rewrites the manifest durably, then prunes
    orphan files. The manifest never references a missing file.
    """
    previous = load_manifest(manifest_path)
    scoped: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for cand in scope or []:
        if not isinstance(cand, dict):
            continue
        uid = brief_uid(cand.get("url"))
        if uid and uid not in seen:
            seen.add(uid)
            scoped.append((uid, cand))

    media_dir = Path(media_dir)
    manifest_path = Path(manifest_path)
    entries: dict[str, dict] = {}
    reused = 0
    for uid, _ in scoped:
        prev = previous.get(uid)
        if not isinstance(prev, dict):
            continue
        file = prev.get("file")
        if isinstance(file, str) and FILE_RE.fullmatch(file) and (media_dir / file).is_file():
            entries[uid] = prev
            reused += 1
        elif not file:
            entries[uid] = prev  # negative result - retried within budget below

    budget = 0 if offline else FETCH_CAP
    fetched = 0
    for uid, cand in scoped:
        if budget <= 0:
            break
        if entries.get(uid, {}).get("file"):
            continue
        url = brief.safe_url(cand.get("url"))
        if not url:
            entries.pop(uid, None)
            continue
        budget -= 1
        fetched += 1
        entry: dict = {
            "status": "proposed", "file": None, "image_url": None, "article_url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        html = fetch_media.fetch_html(url)
        image_url = fetch_media.extract_og(html, url) if html else None
        if not html:
            entry["reason"] = "fetch_failed"
        elif not image_url:
            entry["reason"] = "no og:image"
        else:
            got = fetch_image(image_url, referer=url)
            if got is None:
                entry.update(reason="image_rejected", image_url=image_url)
            else:
                raw, ext = got
                name = f"{uid}.{ext}"
                media_dir.mkdir(parents=True, exist_ok=True)
                part = media_dir / f".{name}.part"
                part.write_bytes(raw)
                part.replace(media_dir / name)
                entry.update(reason="publisher og:image", image_url=image_url,
                             file=name, bytes=len(raw), format=ext)
        entries[uid] = entry
        time.sleep(SLEEP)

    # The manifest only ever references files that exist on disk.
    entries = {
        uid: e for uid, e in entries.items()
        if not e.get("file") or (media_dir / str(e["file"])).is_file()
    }
    doc = {
        "method": METHOD,
        "status": "proposed",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope_count": len(scoped),
        "entry_count": len(entries),
        "with_image": sum(1 for e in entries.values() if e.get("file")),
        "fetched_this_run": fetched,
        "reused": reused,
        "media": entries,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    part = manifest_path.with_name(manifest_path.name + ".tmp")
    part.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    part.replace(manifest_path)

    # Prune orphans only after the new manifest is durable.
    referenced = {str(e["file"]) for e in entries.values() if e.get("file")}
    pruned = 0
    if media_dir.is_dir():
        for path in sorted(media_dir.iterdir()):
            if not path.is_file() or path.is_symlink():
                continue
            stale_part = path.name.startswith(".") and path.name.endswith(".part")
            if path.name in referenced or not (stale_part or FILE_RE.fullmatch(path.name)):
                continue
            try:
                path.unlink()
                pruned += 1
            except OSError:
                pass
    doc["pruned"] = pruned
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch publisher preview images for the brief.")
    parser.add_argument("--offline", action="store_true",
                        help="Reuse the cached store; make no network requests")
    args = parser.parse_args(argv)
    scope = load_scope()
    if not scope:
        print("brief media: no candidates to scope; keeping previous manifest")
        return 0
    try:
        doc = update_media(scope, offline=args.offline)
    except (OSError, ValueError) as exc:
        print(f"brief media: FAIL {exc} - keeping previous manifest")
        return 0
    print(f"brief media -> {MANIFEST.relative_to(ROOT)}")
    print(f"  scope={doc['scope_count']} with_image={doc['with_image']} "
          f"fetched={doc['fetched_this_run']} reused={doc['reused']} pruned={doc['pruned']}"
          + (" (offline)" if args.offline else ""))
    # Fail-soft by design: a media outage never blocks the news pipeline.
    return 0


if __name__ == "__main__":
    sys.exit(main())
