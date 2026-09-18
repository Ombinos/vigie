"""
Vigie - durable multi-edition history per dossier (facts only).

Answers "is this rapprochement new, or has Vigie been seeing it for a while?"
without inventing importance. An edition is one collection snapshot
(normalized_at), not one pipeline run: re-running offline over the same
snapshot never inflates the counts.

House-law guards (scar discipline):
  * absence != resolution: editions_missed counts absences from the collected
    snapshot (fetch limits, RSS caps, the 7-day window, unmatched wording).
    Never "resolved", never "over".
  * history only moves forward: an edition timestamp at or before the last
    recorded update is ignored (idempotent re-runs, older snapshots).
  * editions_seen is a collection fact, never a rank, never a confirmation
    count. Grouping stays proposed.
  * a foreign-method store is never mixed in - start fresh instead.

No LLM. No network. Pure functions plus one small JSON store kept beside the
issue store, so tests that redirect OUT_ISSUES redirect the history with it.
"""
from __future__ import annotations

import json
from pathlib import Path

METHOD = "dossier-history-v1"
TIMELINE_CAP = 40   # most recent presence entries kept per dossier
DOSSIER_CAP = 200   # max dossiers tracked; pruned by oldest last_seen
MISSED_PRUNE = 120  # editions missed before a dormant dossier is dropped


def empty_history() -> dict:
    return {"method": METHOD, "updated_at": None, "edition_count": 0, "dossiers": {}}


def load_history(path: Path) -> dict:
    """Missing, corrupt or foreign-method stores start fresh - never mixed."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_history()
    if not isinstance(raw, dict) or raw.get("method") != METHOD:
        return empty_history()
    dossiers = raw.get("dossiers")
    if not isinstance(dossiers, dict):
        return empty_history()
    try:
        edition_count = int(raw.get("edition_count") or 0)
    except (TypeError, ValueError):
        edition_count = 0
    return {
        "method": METHOD,
        "updated_at": raw.get("updated_at"),
        "edition_count": edition_count,
        "dossiers": {
            str(k): v for k, v in dossiers.items() if isinstance(v, dict)
        },
    }


def update_history(history: dict, issues: list[dict], edition_ts: str) -> dict:
    """Pure: returns the history advanced by one edition; input is not mutated.

    Counts one edition per distinct collection timestamp and only moves
    forward: an edition_ts at or before updated_at returns history unchanged.
    Dossiers absent from this edition gain editions_missed - an absence from
    the collection, never a resolution.
    """
    edition_ts = str(edition_ts or "").strip()
    if not edition_ts:
        return history
    updated_at = str(history.get("updated_at") or "")
    if updated_at and edition_ts <= updated_at:
        return history

    dossiers: dict[str, dict] = {}
    for key, rec in (history.get("dossiers") or {}).items():
        if isinstance(rec, dict):
            dossiers[str(key)] = dict(rec)

    present: set[str] = set()
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        iid = str(issue.get("issue_id") or "").strip()
        if not iid:
            continue
        present.add(iid)
        entry = {
            "ts": edition_ts,
            "sources": int(issue.get("source_count") or 0),
        }
        rec = dossiers.get(iid)
        if rec is None:
            dossiers[iid] = {
                "scar": issue.get("scar"),
                "first_seen": edition_ts,
                "last_seen": edition_ts,
                "editions_seen": 1,
                "editions_missed": 0,
                "timeline": [entry],
            }
            continue
        rec["scar"] = issue.get("scar") or rec.get("scar")
        rec["last_seen"] = edition_ts
        rec["editions_seen"] = int(rec.get("editions_seen") or 0) + 1
        timeline = list(rec.get("timeline") or [])
        timeline.append(entry)
        rec["timeline"] = timeline[-TIMELINE_CAP:]
        dossiers[iid] = rec

    for iid, rec in dossiers.items():
        if iid not in present:
            rec["editions_missed"] = int(rec.get("editions_missed") or 0) + 1

    dossiers = {
        iid: rec
        for iid, rec in dossiers.items()
        if int(rec.get("editions_missed") or 0) < MISSED_PRUNE
    }
    if len(dossiers) > DOSSIER_CAP:
        keep = sorted(
            dossiers,
            key=lambda iid: (str(dossiers[iid].get("last_seen") or ""), iid),
            reverse=True,
        )[:DOSSIER_CAP]
        dossiers = {iid: dossiers[iid] for iid in keep}

    return {
        "method": METHOD,
        "updated_at": edition_ts,
        "edition_count": int(history.get("edition_count") or 0) + 1,
        "dossiers": dossiers,
    }


def tracking_of(history: dict, issue_id: str) -> dict | None:
    """The per-dossier summary embedded in latest_issues.json (facts only)."""
    rec = (history.get("dossiers") or {}).get(str(issue_id))
    if not isinstance(rec, dict):
        return None
    return {
        "status": "proposed",
        "method": METHOD,
        "first_seen": rec.get("first_seen"),
        "last_seen": rec.get("last_seen"),
        "editions_seen": int(rec.get("editions_seen") or 0),
        "editions_missed": int(rec.get("editions_missed") or 0),
    }
