"""Vigie v0 — ingest official WZDX roadwork feeds into data/raw + data/roadworks.

Structured official change data, not articles: this bypasses normalize/enrich/
cluster/rank entirely. Raw GeoJSON snapshots are append-only (fetch is the scar).
The store keeps parsed active events inside the metro bbox plus an honest
collection diff — removal from a collection is never reported as ended or
resolved, and estimated dates stay marked estimated. A feed outage never kills
the news pipeline: on failure the previous store is kept and this exits 0.

Stdlib only. No pip. Does not invent, rank, or interpret anything.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ingest_rss import SOURCES_PATH, fetch_bytes, load_enabled_by_type, sha256_hex, utc_now

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
STORE_PATH = ROOT / "data" / "roadworks" / "latest_roadworks.json"
METHOD = "wzdx-roadworks-v1"
# Quebec metro bbox (min_lon, min_lat, max_lon, max_lat) — a locality sanity
# guard on the feed, not an editorial filter. The feed is the city's own.
METRO_BBOX = (-71.85, 46.50, -70.75, 47.25)
COMPARE_FIELDS = (
    "event_status", "vehicle_impact", "start_date", "end_date",
    "description", "road_names", "restrictions",
)
ENDED_STATUSES = ("completed", "cancelled")
SKIP_REASONS = ("malformed", "missing_identifier", "missing_geometry", "outside_bbox")


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _points(geometry: object) -> list[tuple[float, float]]:
    """Flatten Point/LineString/MultiLineString coordinates into (lon, lat) pairs."""
    if not isinstance(geometry, dict):
        return []
    coords = geometry.get("coordinates")
    kind = str(geometry.get("type") or "").lower()

    def pair(value: object) -> tuple[float, float] | None:
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(n, (int, float)) for n in value[:2]):
            return (float(value[0]), float(value[1]))
        return None

    points: list[tuple[float, float]] = []
    if kind == "point":
        p = pair(coords)
        if p:
            points.append(p)
    elif kind == "linestring" and isinstance(coords, list):
        points.extend(p for p in map(pair, coords) if p)
    elif kind == "multilinestring" and isinstance(coords, list):
        for line in coords:
            if isinstance(line, list):
                points.extend(p for p in map(pair, line) if p)
    return points


def in_bbox(points: list[tuple[float, float]], bbox: tuple[float, float, float, float] = METRO_BBOX) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return any(min_lon <= lon <= max_lon and min_lat <= lat <= max_lat for lon, lat in points)


def _clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v or "").strip()]


def _clean_str(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def parse_event(feature: object) -> tuple[dict | None, str | None]:
    """One WZDX feature -> (event, None) or (None, skip reason). Never invents fields."""
    if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
        return None, "malformed"
    props = feature["properties"]
    event_id = str(props.get("data_source_id") or "").strip()
    if not event_id:
        return None, "missing_identifier"
    points = _points(feature.get("geometry"))
    if not points:
        return None, "missing_geometry"
    if not in_bbox(points):
        return None, "outside_bbox"
    event = {
        "event_id": event_id,
        "event_type": _clean_str(props.get("event_type")),
        "event_status": (_clean_str(props.get("event_status")) or "").lower() or None,
        "vehicle_impact": (_clean_str(props.get("vehicle_impact")) or "").lower() or None,
        "road_names": _clean_list(props.get("road_names")),
        "direction": (_clean_str(props.get("direction")) or "").lower() or None,
        "start_date": props.get("start_date") if isinstance(props.get("start_date"), str) else None,
        "end_date": props.get("end_date") if isinstance(props.get("end_date"), str) else None,
        "start_date_accuracy": (_clean_str(props.get("start_date_accuracy")) or "").lower() or None,
        "end_date_accuracy": (_clean_str(props.get("end_date_accuracy")) or "").lower() or None,
        "description": _clean_str(props.get("description")),
        "update_date": props.get("update_date") if isinstance(props.get("update_date"), str) else None,
        "restrictions": _clean_list(props.get("restrictions")),
    }
    return event, None


def is_active(event: dict, now: datetime) -> bool:
    """Official status wins; otherwise the official end date decides.

    A real-time obstruction feed with no status and no end date is active:
    the city is still publishing it. Fetch time is never an event time.
    """
    status = str(event.get("event_status") or "").lower()
    if status == "active":
        return True
    if status in ENDED_STATUSES:
        return False
    end = _parse_iso(event.get("end_date"))
    if end is None:
        return True
    return end >= now


def diff_events(current: list[dict], previous: list[dict] | None, *, now: datetime) -> dict:
    """Honest collection diff. New ≠ important; changed ≠ worse; removed ≠ ended."""
    empty = {"has_previous": False, "new": [], "removed": [], "changed": [],
             "new_count": 0, "removed_count": 0, "changed_count": 0,
             "note": "Aucune collecte précédente comparable."}
    if previous is None:
        return empty

    def keyed(rows: object) -> dict[str, dict]:
        return {str(e["event_id"]): e for e in (rows or []) if isinstance(e, dict) and e.get("event_id")}

    cur, prev = keyed(current), keyed(previous)
    new = [
        {"event_id": eid, "road_names": cur[eid].get("road_names") or [],
         "event_type": cur[eid].get("event_type"), "change": "new", "status": "proposed"}
        for eid in sorted(set(cur) - set(prev))
    ]
    removed = []
    for eid in sorted(set(prev) - set(cur)):
        end = _parse_iso(prev[eid].get("end_date"))
        removed.append({
            "event_id": eid, "road_names": prev[eid].get("road_names") or [],
            "event_type": prev[eid].get("event_type"), "change": "removed", "status": "proposed",
            "official_end_date_passed": bool(end is not None and end < now),
        })
    changed = []
    for eid in sorted(set(cur) & set(prev)):
        fields = [f for f in COMPARE_FIELDS if cur[eid].get(f) != prev[eid].get(f)]
        if fields:
            changed.append({"event_id": eid, "road_names": cur[eid].get("road_names") or [],
                            "fields": fields, "change": "changed", "status": "proposed"})
    return {
        "has_previous": True, "new": new, "removed": removed, "changed": changed,
        "new_count": len(new), "removed_count": len(removed), "changed_count": len(changed),
        "note": "« Retirée » signifie absente de cette collecte, pas terminée ni résolue.",
    }


def load_previous(store_path: Path) -> list[dict] | None:
    """Previous store events, or None when absent/corrupt (no comparison claimed)."""
    try:
        doc = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    events = doc.get("events") if isinstance(doc, dict) else None
    return events if isinstance(events, list) else None


def build_store(src: dict, active: list[dict], counts: dict, diff: dict, fetched_at: datetime) -> dict:
    return {
        "method": METHOD,
        "status": "proposed",
        "source_id": src.get("id"),
        "source_name": src.get("name"),
        "institution_name": src.get("institution_name") or src.get("name"),
        "feed_url": src.get("url"),
        "dataset_url": src.get("homepage"),
        "license_note": src.get("license_note"),
        "fetched_at": fetched_at.isoformat(),
        "bbox": list(METRO_BBOX),
        "counts": {**counts, "active": len(active)},
        "events": active,
        "diff": diff,
    }


def latest_snapshot(raw_dir: Path, source_id: str) -> Path | None:
    """Most recent raw GeoJSON snapshot (stamps sort chronologically)."""
    directory = raw_dir / source_id
    if not directory.is_dir():
        return None
    snapshots = sorted(directory.glob("*.geojson"))
    return snapshots[-1] if snapshots else None


def snapshot_fetched_at(snapshot: Path) -> datetime | None:
    meta = snapshot.with_suffix(".json")
    if meta.exists():
        try:
            return _parse_iso(json.loads(meta.read_text(encoding="utf-8")).get("fetched_at"))
        except (OSError, ValueError):
            pass
    return None


def collect(sources: list[dict], now: datetime, *, offline: bool = False,
            raw_dir: Path = RAW_DIR, store_path: Path = STORE_PATH, fetch=fetch_bytes) -> dict:
    """Rebuild the roadworks store. All-or-nothing per run: any fetch or parse
    failure keeps the previous store untouched and reports ok=False."""
    if not sources:
        print("  no enabled wzdx sources; keeping previous store")
        return {"ok": False, "reason": "no_sources"}
    previous = load_previous(store_path)
    counts = {"features": 0, "parsed": 0, **{reason: 0 for reason in SKIP_REASONS}}
    all_events: list[dict] = []
    fetched_ats: list[datetime] = []
    for src in sources:
        source_id = str(src.get("id") or "")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", source_id):
            print(f"  FAIL {source_id!r}: invalid source identifier; keeping previous store")
            return {"ok": False, "reason": "invalid_source_id"}
        dest_dir = raw_dir / source_id
        if offline:
            snapshot = latest_snapshot(raw_dir, source_id)
            if snapshot is None:
                print(f"  {source_id}: no raw snapshot to reuse offline; keeping previous store")
                return {"ok": False, "reason": "no_snapshot"}
            raw = snapshot.read_bytes()
            fetched_at = snapshot_fetched_at(snapshot) or now
            print(f"  {source_id}: reusing {snapshot.name} (fetched {fetched_at.isoformat()})")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            stamp = now.strftime("%Y%m%dT%H%M%SZ")
            try:
                raw, content_type = fetch(src["url"])
            except Exception as exc:
                error = {"ok": False, "source_id": source_id, "url": src.get("url"),
                         "error": f"{type(exc).__name__}: {exc}", "fetched_at": now.isoformat()}
                (dest_dir / f"{stamp}_error.json").write_text(
                    json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  FAIL {source_id}: {error['error']} — keeping previous store")
                return {"ok": False, "reason": "fetch_failed"}
            fetched_at = now
            digest = sha256_hex(raw)
            snapshot = dest_dir / f"{stamp}_{digest[:12]}.geojson"
            snapshot.write_bytes(raw)
        parse_error = None
        features: list = []
        try:
            doc = json.loads(raw)
            features = doc.get("features") if isinstance(doc, dict) else None
            if not isinstance(features, list):
                raise ValueError("no features array in GeoJSON document")
        except ValueError as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
        if not offline:
            meta = {
                "ok": parse_error is None, "source_id": source_id, "source_name": src.get("name"),
                "institution": src.get("institution") or source_id, "type": "wzdx",
                "feed_url": src.get("url"), "fetched_at": fetched_at.isoformat(),
                "content_type": content_type if parse_error is None else None,
                "bytes": len(raw), "sha256": sha256_hex(raw),
                "geojson_file": str(snapshot.relative_to(raw_dir.parent.parent)).replace("\\", "/")
                if snapshot.is_relative_to(raw_dir.parent.parent) else str(snapshot),
                "feature_count": len(features), "parse_error": parse_error,
            }
            snapshot.with_suffix(".json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if parse_error:
            print(f"  FAIL {source_id}: {parse_error} — keeping previous store")
            return {"ok": False, "reason": "parse_failed"}
        for feature in features:
            counts["features"] += 1
            event, reason = parse_event(feature)
            if event is None:
                counts[reason or "malformed"] += 1
                continue
            event["source_id"] = source_id
            event["active"] = is_active(event, fetched_at)
            all_events.append(event)
        counts["parsed"] += sum(1 for e in all_events if e.get("source_id") == source_id)
        fetched_ats.append(fetched_at)
    store_fetched_at = min(fetched_ats)
    active = sorted((e for e in all_events if e.get("active")), key=lambda e: str(e["event_id"]))
    diff = diff_events(active, previous, now=store_fetched_at)
    store = build_store(sources[0], active, counts, diff, store_fetched_at)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "store": store, "store_path": store_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="Reuse the latest raw snapshot; make no network requests")
    args = parser.parse_args(argv)
    sources = load_enabled_by_type(SOURCES_PATH, "wzdx")
    now = utc_now()
    print(f"Vigie roadworks ingest {now.isoformat()} — {len(sources)} enabled WZDX"
          + (" (offline snapshots)" if args.offline else ""))
    result = collect(sources, now, offline=args.offline)
    if result.get("ok"):
        store = result["store"]
        c, d = store["counts"], store["diff"]
        skipped = sum(c.get(reason, 0) for reason in SKIP_REASONS)
        print(f"  features={c['features']} parsed={c['parsed']} active={c['active']} skipped={skipped}")
        if d["has_previous"]:
            print(f"  diff: +{d['new_count']} new, -{d['removed_count']} removed, ~{d['changed_count']} changed")
        else:
            print("  diff: no previous collection to compare")
        try:
            print(f"store: {result['store_path'].relative_to(ROOT)}")
        except ValueError:
            print(f"store: {result['store_path']}")
    # Always 0: a roadwork feed outage must never block the news pipeline.
    return 0


if __name__ == "__main__":
    sys.exit(main())
