"""Vigie - change ledger (the city-diff between editions).

A deterministic, rules-only diff of this edition's proposed dossiers against the
previous edition. It answers the resident question "what changed in my city since
last time?" without inventing news, ranking, or verdicts.

House-law guards (scar discipline):
  * "new"       = newly clustered this edition. Not "important", not "breaking".
  * "developed" = new articles or new voices since last edition. Not escalation,
                  not confirmation. Several media are never several independent
                  confirmations.
  * "quiet"     = absent from this edition's collection. Not "resolved", not
                  "over". Absence is never proven editorial silence: fetch limits,
                  RSS caps, paywalls, the 7-day window, or unmatched wording can
                  all explain it.
  * Grouping stays proposed. The ledger never crowns a correct answer.

No LLM. No network. A pure function of two issue lists plus one flag, so the
output is reproducible from the same inputs.
"""
from __future__ import annotations

METHOD = "change-ledger-v1 edition-diff"

# Minimal, honest projection of a dossier. Never adds resolution/impact/truth.
_ENTRY_FIELDS = (
    "issue_id", "scar", "question", "geo_focus",
    "source_count", "item_count", "official_voice_count", "media_remix",
)

_NOTE = (
    "Comparaison des dossiers proposés de cette édition à la précédente. "
    "« Nouveau » = nouvellement rapproché, pas plus important. "
    "« Développé » = nouveaux articles ou voix, pas une escalade ni une confirmation. "
    "« Disparu de la collecte » = absent de cette collecte, pas réglé. "
    "Une absence n’est pas un silence éditorial prouvé. Les rapprochements restent proposés."
)


def _entry(issue: dict, change: str) -> dict:
    row = {k: issue.get(k) for k in _ENTRY_FIELDS}
    row["change"] = change
    row["status"] = "proposed"
    if not isinstance(row.get("geo_focus"), list):
        row["geo_focus"] = []
    return row


def _latest_pub(issue: dict) -> str:
    value = (issue.get("evidence") or {}).get("publication_latest")
    return str(value) if isinstance(value, str) else ""


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _development(current: dict, previous: dict) -> dict:
    """Observable additive growth on a dossier present in both editions.

    Empty when nothing grew. Shrinking is not "development"; the ledger never
    inflates a story. Only counts and publication recency that are already in
    the issue store are used - nothing is inferred or fetched.
    """
    delta: dict = {}
    items = _as_int(current.get("item_count")) - _as_int(previous.get("item_count"))
    if items > 0:
        delta["items_added"] = items
    voices = _as_int(current.get("source_count")) - _as_int(previous.get("source_count"))
    if voices > 0:
        delta["voices_added"] = voices
    if _as_int(current.get("official_voice_count")) > _as_int(previous.get("official_voice_count")):
        delta["official_voice_joined"] = True
    cur_pub, prev_pub = _latest_pub(current), _latest_pub(previous)
    # Same-format UTC ISO strings sort lexicographically = chronologically.
    if cur_pub and prev_pub and cur_pub > prev_pub:
        delta["newer_publication"] = True
    return delta


def _index(issues: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for issue in issues or []:
        if isinstance(issue, dict) and issue.get("issue_id"):
            out[str(issue["issue_id"])] = issue
    return out


def diff_editions(
    current: list[dict] | None,
    previous: list[dict] | None,
    *,
    has_previous: bool | None = None,
) -> dict:
    """Diff two editions' proposed dossiers by stable issue_id.

    Deterministic: every list is sorted by issue_id. Pure: no I/O, no clock.
    `has_previous` separates "no archived edition yet" (first run) from "a
    previous edition existed"; when None it is inferred from a non-empty
    previous list. The diff is computed regardless, so callers can decide how
    to present a first edition honestly.
    """
    if has_previous is None:
        has_previous = bool(previous)
    cur_by_id = _index(current)
    prev_by_id = _index(previous)

    new_ids = sorted(set(cur_by_id) - set(prev_by_id))
    quiet_ids = sorted(set(prev_by_id) - set(cur_by_id))
    shared_ids = sorted(set(cur_by_id) & set(prev_by_id))

    new = [_entry(cur_by_id[i], "new") for i in new_ids]
    quiet = [_entry(prev_by_id[i], "quiet") for i in quiet_ids]
    developed = []
    for iid in shared_ids:
        delta = _development(cur_by_id[iid], prev_by_id[iid])
        if delta:
            developed.append({**_entry(cur_by_id[iid], "developed"), "delta": delta})

    return {
        "status": "proposed",
        "method": METHOD,
        "has_previous": bool(has_previous),
        "current_count": len(cur_by_id),
        "previous_count": len(prev_by_id),
        "new": new,
        "developed": developed,
        "quiet": quiet,
        "new_count": len(new),
        "developed_count": len(developed),
        "quiet_count": len(quiet),
        "note": _NOTE,
    }
