"""A finite, French-first resident brief. No generated news or inferred advice.

Rendering is deterministic, offline, and uses the same public ranking. Search and
saved stories run in the browser; no account, analytics, or location collection.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from ingest_rss import public_http_url

ROOT = Path(__file__).resolve().parents[1]
WINDOW_DAYS = 7
TOPICS = {
    "housing": "Se loger", "transport": "Se déplacer", "energy/hydro": "Énergie",
    "education": "Éducation", "law": "Vie publique", "health": "Santé",
    "trade": "Économie", "economy": "Économie", "security": "Sécurité",
    "environment": "Environnement", "death": "Société", "culture": "Culture",
    "other": "Vie locale",
}
AREAS = {
    "cite": ("La Cité-Limoilou", r"\b(?:limoilou|saint[- ]roch|saint[- ]sauveur|montcalm|saint[- ]sacrement|vieux[- ]quebec|saint[- ]jean[- ]baptiste|lairet|maizerets)\b"),
    "rivières": ("Les Rivières", r"\b(?:les rivieres|duberger|les saules|lebourgneuf|(?:quartier|secteur|a) vanier)\b"),
    "foy": ("Sainte-Foy–Sillery–Cap-Rouge", r"\b(?:sainte[- ]foy|sillery|cap[- ]rouge)\b"),
    "charlesbourg": ("Charlesbourg", r"\bcharlesbourg\b"),
    "beauport": ("Beauport", r"\bbeauport\b"),
    "haute": ("La Haute-Saint-Charles", r"\b(?:haute[- ]saint[- ]charles|val[- ]belair|loretteville|saint[- ]emile|lac[- ]saint[- ]charles)\b"),
    "levis": ("Lévis", r"\blevis\b"),
}
SERVICES = (
    ("01", "Avant de partir", "Entraves et travaux", "La carte officielle des travaux sur votre trajet.", "https://carte.ville.quebec.qc.ca/"),
    ("02", "Transport en commun", "Mon parcours RTC", "Horaires, avis et outils du Réseau de transport de la Capitale.", "https://www.rtcquebec.ca/restez-informe"),
    ("03", "Avoir son mot à dire", "Consultations publiques", "Les projets sur lesquels la Ville consulte les citoyens.", "https://participationcitoyenne.ville.quebec.qc.ca/"),
    ("04", "L’hiver à Québec", "Alertes de déneigement", "S’abonner directement aux avis de la Ville.", "https://www.ville.quebec.qc.ca/apropos/espace-presse/abonnement/alertes_sms.aspx"),
)


# Display-spoofing control characters (C0/C1 except tab/LF/CR, soft hyphen,
# zero-width marks and bidi overrides) are stripped from relayed text. The
# visible wording stays verbatim; these characters are display instructions,
# not content, and a hostile feed must not be able to spoof what a title says.
_SPOOF = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\xad\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)

TITLE_CAP = 300     # relayed titles are truncated, never padded or rewritten
SUMMARY_CAP = 2000  # excerpt source and search index; longer summaries add no recall


def sanitize(value: object) -> str:
    return _SPOOF.sub("", str(value if value is not None else ""))


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def esc(value: object) -> str:
    return html.escape(sanitize(value), quote=True)


def plain(value: object) -> str:
    text = sanitize(html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", text)).strip()


def folded(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def safe_url(value: object) -> str:
    value = str(value or "").strip()
    try:
        if re.search(r"[\x00-\x20\x7f\\]", value):
            return ""
        return public_http_url(value)
    except (ValueError, TypeError):
        return ""


def parse_date(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    for parser in (lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")), parsedate_to_datetime):
        try:
            dt = parser(raw.strip())
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def date_html(value: object, *, fallback: str = "Date non précisée") -> str:
    dt = parse_date(value)
    if dt is None:
        return esc(fallback)
    # Browser localizes to Québec, including DST. UTC is an honest no-JS fallback.
    return f'<time datetime="{dt.isoformat()}">{dt:%Y-%m-%d %H:%M} UTC</time>'


def collection_status(run: dict, now: datetime) -> dict:
    results = run.get("results") or []
    by_id = {r.get("source_id"): r for r in results if isinstance(r, dict)}
    enabled = run.get("enabled_rss") or list(by_id)
    ok = sum(bool(by_id.get(s, {}).get("ok")) and not by_id.get(s, {}).get("parse_error") for s in enabled)
    stamp = parse_date(run.get("fetched_at"))
    age = (now - stamp).total_seconds() if stamp else None
    stale = not enabled or age is None or age > 6 * 3600 or age < -300
    return {"ok": ok, "total": len(enabled), "stale": stale,
            "partial": not enabled or ok < len(enabled), "at": stamp.isoformat() if stamp else "",
            "failed": [s for s in enabled if not by_id.get(s, {}).get("ok") or by_id.get(s, {}).get("parse_error")]}


def latest_run() -> dict:
    paths = sorted((ROOT / "data" / "raw").glob("_run_*.json"), reverse=True)
    if paths:
        try:
            return json.loads(paths[0].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


MEDIA_MANIFEST = ROOT / "data" / "media" / "brief_manifest.json"
_MEDIA_FILE = re.compile(r"[a-f0-9]{20}\.(?:jpg|jpeg|png|webp|avif|gif)")


def load_brief_media() -> dict:
    """uid -> local filename for publisher preview images (brief-media-v1).

    Images are fetched at collection time and served from this site: reading
    the brief never contacts a publisher. A foreign or corrupt manifest
    renders no images rather than guessing, and only strict filenames pass,
    so a hostile store can never aim an <img> outside /media/.
    """
    try:
        doc = json.loads(MEDIA_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("method") != "brief-media-v1":
        return {}
    media = doc.get("media")
    if not isinstance(media, dict):
        return {}
    return {
        str(uid): entry["file"]
        for uid, entry in media.items()
        if isinstance(entry, dict) and isinstance(entry.get("file"), str)
        and _MEDIA_FILE.fullmatch(entry["file"])
    }


def prepare_items(ranked: list[dict], now: datetime) -> tuple[list[dict], int]:
    """Preserve rank order; age gate by publication, never fetch time."""
    rows, excluded, seen = [], 0, set()
    for item in ranked or []:
        if not isinstance(item, dict):
            excluded += 1
            continue
        url = safe_url(item.get("url"))
        title = plain(item.get("title"))
        if len(title) > TITLE_CAP:
            title = title[:TITLE_CAP].rstrip() + "…"
        when = parse_date(item.get("published_at"))
        if not title or not url:
            excluded += 1
            continue
        if when is None or (now - when).total_seconds() < -300 or (now - when).days >= WINDOW_DAYS:
            excluded += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        enrich = item.get("enrich")
        enrich = enrich if isinstance(enrich, dict) else {}
        geo_block = enrich.get("geo")
        geo = (geo_block.get("geo") if isinstance(geo_block, dict) else None) or item.get("display_geo", "linked")
        topics_block = enrich.get("topics")
        topic_ids = [t.get("topic", "other") for t in (topics_block if isinstance(topics_block, list) else []) if isinstance(t, dict)] or ["other"]
        summary = plain(item.get("summary"))[:SUMMARY_CAP]
        text = folded(title + " " + summary)
        areas = [key for key, (_, pattern) in AREAS.items() if geo == "quebec-city" and re.search(pattern, text)]
        # IDs are derived from canonical URLs: syndication/feed changes do not erase bookmarks.
        uid = hashlib.sha256(url.encode()).hexdigest()[:20]
        rows.append({**item, "uid": uid, "url": url, "title": title,
                     "summary": summary, "published": when.isoformat(),
                     "geo": geo, "topics": topic_ids, "areas": areas})
    return rows, excluded


def related_sources(item: dict, issues: list[dict], eligible: dict[str, dict]) -> list[dict]:
    rows, seen = [], {item["url"]}
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        entries = [
            it
            for voice in (issue.get("tensions") or [])
            if isinstance(voice, dict)
            for it in (voice.get("items") or [])
            if isinstance(it, dict)
        ]
        if not any(it.get("candidate_id") == item.get("id") for it in entries):
            continue
        for entry in entries:
            other = eligible.get(entry.get("candidate_id"))
            if other and other["url"] not in seen:
                seen.add(other["url"])
                rows.append(other)
    return rows[:5]


NEST_LABELS = {"quebec-city": "Québec et environs", "quebec": "Au Québec", "linked": "Ailleurs"}


def dossier_nest(geo_focus: object) -> str:
    geos = geo_focus or []
    if "quebec-city" in geos:
        return "quebec-city"
    if "quebec" in geos:
        return "quebec"
    return "linked"


def dossier_units(issue: dict, eligible: dict) -> list[str]:
    """Checkable units already on dossier items in this brief — never invented."""
    raws: list[str] = []
    seen: set[str] = set()
    for tension in issue.get("tensions") or []:
        for entry in tension.get("items") or []:
            row = eligible.get(entry.get("candidate_id"))
            if not row:
                continue
            for impact in (row.get("enrich") or {}).get("impacts") or []:
                for unit in impact.get("units") or []:
                    raw = str(unit.get("raw") or "").strip()
                    if raw and raw not in seen:
                        seen.add(raw)
                        raws.append(raw)
    return raws[:4]


def tracking_html(issue: dict) -> str:
    """Durable-history line: collection facts only.

    Absence is never a resolution; editions_seen is never importance.
    """
    tracking = issue.get("tracking")
    tracking = tracking if isinstance(tracking, dict) else {}
    seen = safe_int(tracking.get("editions_seen"))
    if seen <= 0:
        return ""
    if seen == 1:
        text = "Suivi depuis cette édition."
    else:
        first = date_html(tracking.get("first_seen"), fallback="date non précisée")
        text = f"Suivi depuis le {first} — présent dans {seen} éditions collectées."
    missed = safe_int(tracking.get("editions_missed"))
    if missed > 0:
        label = "édition" if missed == 1 else "éditions"
        text += (
            f" Absent de {missed} {label} — une absence de la collecte"
            " n’est pas une résolution."
        )
    return f'<p class="dossier-tracking fine">{text}</p>'


def dossier_html(issue: dict, eligible: dict) -> str:
    """One dossier: the question, who spoke, who stayed silent, sources to compare.

    Grouping is never a contradiction; absence is never proven editorial silence;
    several media are never several independent confirmations. Judgment stays with
    the reader.
    """
    question = esc(issue.get("question") or "Sujet suivi")
    nest = dossier_nest(issue.get("geo_focus"))
    tensions = issue.get("tensions") or []
    spoke: list[str] = []
    for tension in tensions:
        name = str(tension.get("institution_name") or "").strip()
        if name and name not in spoke:
            spoke.append(name)
    spoke_count = safe_int(issue.get("source_count"), len(spoke))
    bits: list[str] = []
    for tension in tensions:
        inst = esc(str(tension.get("institution_name") or "Source").strip())
        for entry in (tension.get("items") or [])[:2]:
            url = safe_url(entry.get("url"))
            if not url:
                continue
            bits.append(
                f'<li><span class="dossier-inst">{inst}</span>'
                f'<a href="{esc(url)}" rel="noopener noreferrer">{esc(entry.get("title") or "Sans titre")}'
                f'<span class="arrow" aria-hidden="true"> ↗</span></a></li>'
            )
    sources = f'<ul class="dossier-sources">{"".join(bits)}</ul>' if bits else ""
    spoke_line = (
        f'<p class="dossier-spoke"><strong>{spoke_count}</strong> sources ont parlé : '
        + " · ".join(esc(n) for n in spoke[:5])
        + "</p>"
    ) if spoke else ""
    silence = issue.get("silence") or {}
    quiet = [
        str(s.get("institution_name") or s.get("source_id") or "").strip()
        for s in (silence.get("silent") or [])
        if (s.get("source_kind") or "").lower() == "official"
    ]
    quiet = [n for n in quiet if n]
    silence_line = (
        '<p class="dossier-silence">Officiellement muets dans cette collecte : <strong>'
        + " · ".join(esc(n) for n in quiet[:3])
        + '</strong>. <span class="fine">Une absence dans nos flux n’est pas un silence '
        'éditorial prouvé, et ce n’est pas un indicateur de biais.</span></p>'
    ) if quiet else ""
    remix_line = (
        '<p class="dossier-remix fine">Aucune source officielle sur ce dossier — '
        "rapprochement de médias seulement.</p>"
        if issue.get("media_remix")
        else ""
    )
    units = dossier_units(issue, eligible)
    units_line = (
        '<p class="dossier-units">Repères à vérifier : '
        + "".join(f'<span class="unit">{esc(u[:48])}</span>' for u in units)
        + "</p>"
    ) if units else ""
    return (
        f'<article class="dossier" data-nest="{esc(nest)}">'
        f'<div class="dossier-head"><span class="dossier-nest">{esc(NEST_LABELS[nest])}</span>'
        f'<span class="dossier-count">{spoke_count} sources · rapprochement proposé</span></div>'
        f'<h3 class="dossier-q">{question}</h3>'
        f"{tracking_html(issue)}{spoke_line}{sources}{silence_line}{remix_line}{units_line}"
        f"</article>"
    )


def dossiers_section(issues: list[dict], eligible: dict) -> str:
    """Cross-source dossiers on the resident front door — the lookout, in French."""
    dossiers = [iss for iss in (issues or []) if isinstance(iss, dict) and iss.get("question")]
    count = len(dossiers)
    if dossiers:
        cards = "".join(dossier_html(iss, eligible) for iss in dossiers[:6])
        label = "dossier proposé" if count == 1 else "dossiers proposés"
        note = f"{count} {label}<br>cette édition."
        listing = f'<div class="dossier-list">{cards}</div>'
    else:
        note = "Aucun dossier<br>cette édition."
        listing = (
            '<p class="no-data">Aucun sujet n’a été rapproché entre plusieurs institutions '
            "dans cette collecte. Cela ne dit rien de la couverture ailleurs.</p>"
        )
    return (
        '<section class="dossiers" id="dossiers" aria-labelledby="dossiers-title">'
        '<div class="section-top"><div><p class="eyebrow">REGARD CROISÉ</p>'
        '<h2 id="dossiers-title">Ce que les sources racontent ensemble.</h2></div>'
        f'<p class="section-note">{note}</p></div>'
        '<p class="dossiers-intro">Quand plusieurs institutions parlent du même sujet, Vigie '
        "les rassemble — sans décider qui a raison. Un rapprochement n’est pas une "
        "contradiction, et plusieurs médias ne sont pas plusieurs confirmations "
        "indépendantes.</p>"
        f"{listing}</section>"
    )


def _delta_text(delta: dict | None) -> str:
    delta = delta if isinstance(delta, dict) else {}
    parts: list[str] = []
    added = safe_int(delta.get("items_added"))
    if added:
        parts.append(f"+{added} article" + ("s" if added > 1 else ""))
    voices = safe_int(delta.get("voices_added"))
    if voices:
        parts.append(f"+{voices} source" + ("s" if voices > 1 else ""))
    if delta.get("official_voice_joined"):
        parts.append("une source officielle a rejoint")
    if delta.get("newer_publication"):
        parts.append("publication plus récente")
    return " · ".join(parts)


def change_section(ledger: dict | None) -> str:
    """Editorial “what changed in the city since the last edition” — public.

    Distinct from the client-side “Depuis mon repère” reading marker, which is
    personal and article-level. This is dossier-level and identical for every
    reader. Returns "" when no prior edition was archived, so a first edition
    never implies a comparison that did not happen. New ≠ important; developed
    ≠ escalation; quiet ≠ resolved. Judgment stays with the reader.
    """
    ledger = ledger or {}
    if not ledger.get("has_previous"):
        return ""
    new = ledger.get("new") or []
    developed = ledger.get("developed") or []
    quiet = ledger.get("quiet") or []
    if not (new or developed or quiet):
        body = (
            '<p class="no-data">Aucun dossier n’a changé depuis la dernière édition '
            "(aucun nouveau, aucun développé, aucun retiré de la collecte). Cela ne dit "
            "rien de la couverture ailleurs.</p>"
        )
    else:
        blocks: list[str] = []
        if new:
            items = "".join(
                '<li><span class="chg-tag chg-new">Nouveau</span>'
                f'<a href="#dossiers">{esc(e.get("question") or "Dossier suivi")}</a></li>'
                for e in new[:6]
            )
            blocks.append(
                f'<div class="chg-group"><h3>Nouveaux dossiers <span class="chg-n">{len(new)}</span></h3>'
                f'<ul class="chg-list">{items}</ul></div>'
            )
        if developed:
            items = "".join(
                '<li><span class="chg-tag chg-dev">Développé</span>'
                f'<a href="#dossiers">{esc(e.get("question") or "Dossier suivi")}</a>'
                f'<span class="chg-delta">{esc(_delta_text(e.get("delta")))}</span></li>'
                for e in developed[:6]
            )
            blocks.append(
                f'<div class="chg-group"><h3>Dossiers développés <span class="chg-n">{len(developed)}</span></h3>'
                f'<ul class="chg-list">{items}</ul></div>'
            )
        if quiet:
            items = "".join(
                '<li><span class="chg-tag chg-quiet">Retiré</span>'
                f'<span class="chg-q">{esc(e.get("question") or "Dossier suivi")}</span></li>'
                for e in quiet[:6]
            )
            blocks.append(
                f'<div class="chg-group"><h3>Disparus de cette collecte <span class="chg-n">{len(quiet)}</span></h3>'
                f'<ul class="chg-list">{items}</ul>'
                '<p class="fine">« Retiré » signifie absent de cette collecte, pas réglé. '
                "Une absence n’est pas un silence éditorial prouvé.</p></div>"
            )
        body = "".join(blocks)
    return (
        '<section class="changes" id="changements" aria-labelledby="changes-title">'
        '<div class="section-top"><div><p class="eyebrow">CE QUI A CHANGÉ</p>'
        '<h2 id="changes-title">Depuis la dernière édition.</h2></div>'
        '<p class="section-note">Comparaison<br>des dossiers proposés.</p></div>'
        '<p class="dossiers-intro">Vigie compare les dossiers de cette édition à la '
        "précédente. « Nouveau » signifie nouvellement rapproché, pas plus important. "
        "Un rapprochement n’est pas une contradiction, et plusieurs médias ne sont pas "
        "plusieurs confirmations indépendantes.</p>"
        f"{body}</section>"
    )


RW_IMPACT_LABELS = {
    "all-lanes-closed": "Toutes les voies fermées",
    "some-lanes-closed": "Voies partiellement fermées",
    "alternating-one-way": "Circulation en alternance",
    "some-lanes-closed-intermittent-or-short-duration": "Fermetures intermittentes ou de courte durée",
    "all-lanes-open": "Toutes les voies ouvertes",
    "no-lanes-closed": "Aucune voie fermée",
    "unknown": "Impact non précisé",
}
RW_DIRECTION_LABELS = {
    "northbound": "direction nord", "southbound": "direction sud",
    "eastbound": "direction est", "westbound": "direction ouest",
    "both-directions": "deux directions",
}
RW_EVENT_TYPE_LABELS = {
    "road-work": "Travaux", "work-zone": "Zone de travaux", "detour": "Détour",
    "incident": "Incident", "accident": "Accident", "event": "Événement",
}
# The City's own status vocabulary, relayed literally. "active" needs no badge;
# planned/pending declarations are labeled so a future window is never presented
# as a current closure.
RW_STATUS_LABELS = {"planned": "Planifiée", "pending": "En attente"}
RW_SEVERITY = {
    "all-lanes-closed": 0, "some-lanes-closed": 1, "alternating-one-way": 2,
    "some-lanes-closed-intermittent-or-short-duration": 3,
    "all-lanes-open": 4, "no-lanes-closed": 5,
}
RW_DISPLAY_CAP = 8
RW_MAP_URL = "https://carte.ville.quebec.qc.ca/"


def _rw_places(event: dict) -> str:
    roads = [str(r).strip() for r in (event.get("road_names") or []) if str(r or "").strip()]
    return " · ".join(roads[:3])


def _rw_dates(event: dict) -> str:
    start, end = event.get("start_date"), event.get("end_date")
    estimated = "estimated" in (
        str(event.get("start_date_accuracy") or ""), str(event.get("end_date_accuracy") or "")
    )
    note = ' <span class="fine">(dates estimées par la Ville)</span>' if estimated else ""
    if start and end:
        return f'<p class="rw-dates">Du {date_html(start)} au {date_html(end)}{note}</p>'
    if start:
        return f'<p class="rw-dates">Depuis le {date_html(start)}{note}</p>'
    if end:
        return f'<p class="rw-dates">Jusqu’au {date_html(end)}{note}</p>'
    return ""


def _rw_history_line(event: dict, history: dict) -> str:
    """Durable per-event collection facts. An absence is never an end of works."""
    rec = history.get(str(event.get("event_id")))
    if not isinstance(rec, dict):
        return ""
    seen = safe_int(rec.get("collections_seen"))
    if seen <= 0:
        return ""
    if seen == 1:
        text = "Première collecte où cette entrave apparaît."
    else:
        first = date_html(rec.get("first_seen"), fallback="date non précisée")
        text = f"Dans nos collectes depuis le {first} — {seen} collectes."
    missed = safe_int(rec.get("collections_missed"))
    if missed > 0:
        label = "collecte" if missed == 1 else "collectes"
        text += (
            f" Auparavant absente de {missed} {label} — une absence"
            " n’est pas une fin des travaux."
        )
    return f'<p class="rw-history fine">{text}</p>'


def _rw_card(event: dict, new_ids: set, changed_by_id: dict, has_previous: bool,
             history: dict | None = None) -> str:
    eid = str(event.get("event_id"))
    impact = str(event.get("vehicle_impact") or "")
    severity = RW_SEVERITY.get(impact, 6)
    kicker = [
        label for label in (
            RW_STATUS_LABELS.get(str(event.get("event_status") or "")),
            RW_EVENT_TYPE_LABELS.get(str(event.get("event_type") or "")),
            RW_IMPACT_LABELS.get(impact),
            RW_DIRECTION_LABELS.get(str(event.get("direction") or "")),
        ) if label
    ]
    tags = ""
    if has_previous:
        if eid in new_ids:
            tags += '<span class="rw-tag rw-t-new">Nouvelle</span>'
        change = changed_by_id.get(eid)
        if isinstance(change, dict):
            # The City's own date revision, relayed with its direction. Postponed
            # is not extended works; advanced is not finished.
            moved = change.get("end_date_moved")
            if moved == "later":
                tags += '<span class="rw-tag rw-t-post">Fin reportée</span>'
            elif moved == "earlier":
                tags += '<span class="rw-tag rw-t-adv">Fin avancée</span>'
            else:
                tags += '<span class="rw-tag rw-t-chg">Modifiée</span>'
    kicker_html = f'<p class="rw-kicker">{" · ".join(esc(k) for k in kicker)}</p>' if kicker else ""
    desc = plain(event.get("description"))
    if len(desc) > 200:
        desc = desc[:200].rsplit(" ", 1)[0] + "…"
    desc_html = f'<p class="rw-desc">{esc(desc)}</p>' if desc else ""
    return (
        f'<li class="rw-item rw-sev-{severity}">'
        f'<div class="rw-head">{tags}<span class="rw-roads">{esc(_rw_places(event) or "Lieu non précisé")}</span></div>'
        f"{kicker_html}{_rw_dates(event)}{_rw_history_line(event, history or {})}{desc_html}</li>"
    )


def roadworks_section(rw: dict | None, now: datetime) -> str:
    """Official road obstructions — structured change data, never articles.

    Renders only when a store exists with a parseable collection timestamp, so
    the section never implies data that was not collected. Removed ≠ ended;
    estimated dates stay marked estimated; no personal-route effect is ever
    computed. Judgment stays with the reader, on the official map.
    """
    rw = rw if isinstance(rw, dict) else {}
    events = rw.get("events")
    fetched = parse_date(rw.get("fetched_at"))
    if not isinstance(events, list) or fetched is None:
        return ""
    events = [e for e in events if isinstance(e, dict) and e.get("event_id")]
    diff = rw.get("diff") if isinstance(rw.get("diff"), dict) else {}
    has_previous = bool(diff.get("has_previous"))
    stale = (now - fetched).total_seconds() > 6 * 3600 or (now - fetched).total_seconds() < -300
    # Stable three-pass sort: severity first, then most recently updated, then id.
    ordered = sorted(events, key=lambda e: str(e.get("event_id")))
    ordered.sort(key=lambda e: str(e.get("update_date") or ""), reverse=True)
    ordered.sort(key=lambda e: RW_SEVERITY.get(str(e.get("vehicle_impact") or ""), 6))
    new_ids = {e.get("event_id") for e in (diff.get("new") or []) if isinstance(e, dict)}
    changed_by_id = {
        e.get("event_id"): e for e in (diff.get("changed") or []) if isinstance(e, dict)
    }
    hist_doc = rw.get("event_history") if isinstance(rw.get("event_history"), dict) else {}
    # Method guard mirrors ingest_wzdx.HISTORY_METHOD: a foreign-history store
    # renders no collection facts rather than misreading another model's record.
    history = (
        hist_doc.get("events")
        if hist_doc.get("method") == "wzdx-event-history-v1"
        and isinstance(hist_doc.get("events"), dict)
        else {}
    )
    cards = "".join(
        _rw_card(e, new_ids, changed_by_id, has_previous, history)
        for e in ordered[:RW_DISPLAY_CAP]
    )
    count = len(ordered)
    count_note = f"{count} entrave déclarée<br>du flux officiel." if count == 1 else f"{count} entraves déclarées<br>du flux officiel."
    if ordered:
        listing = f'<ul class="rw-list">{cards}</ul>'
        more = (
            f'<p class="rw-more">+ {count - RW_DISPLAY_CAP} autres entraves déclarées dans cette collecte.</p>'
            if count > RW_DISPLAY_CAP else ""
        )
    else:
        listing = (
            '<p class="no-data">Aucune entrave déclarée dans cette collecte. Cela ne signifie '
            "pas qu’aucun travail n’a lieu ailleurs sur le réseau.</p>"
        )
        more = ""
    changes = ""
    if has_previous:
        bits = []
        new_count = safe_int(diff.get("new_count"))
        changed_count = safe_int(diff.get("changed_count"))
        removed_count = safe_int(diff.get("removed_count"))
        if new_count:
            bits.append(f"+{new_count} nouvelle" + ("s" if new_count > 1 else ""))
        if changed_count:
            bits.append(f"~{changed_count} modifiée" + ("s" if changed_count > 1 else ""))
        if removed_count:
            bits.append(f"−{removed_count} retirée" + ("s" if removed_count > 1 else ""))
        if bits:
            removed_note = (
                ' <span class="fine">« Retirée » signifie absente de cette collecte, '
                "pas nécessairement terminée.</span>" if removed_count else ""
            )
            changes = f'<p class="rw-changes">Depuis la dernière collecte : {" · ".join(bits)}.{removed_note}</p>'
        declared: dict[str, int] = {}
        for entry in diff.get("removed") or []:
            if not isinstance(entry, dict):
                continue
            state = str(entry.get("city_declared_status") or "").strip()
            if state:
                declared[state] = declared.get(state, 0) + 1
        if declared:
            # The City's own ended vocabulary, relayed literally: a declaration,
            # never a resolution verified by Vigie.
            parts = ", ".join(
                f'{n} entrave{"s" if n > 1 else ""} « {esc(state)} »'
                for state, n in sorted(declared.items())
            )
            changes += (
                f'<p class="rw-ended">La Ville déclare depuis la dernière collecte : {parts}. '
                '<span class="fine">Statuts officiels relayés tels quels — une déclaration, '
                "pas une vérification sur le terrain.</span></p>"
            )
    stale_html = (
        '<p class="rw-stale warning">Collecte à actualiser : ces données ont plus de six '
        "heures. Vérifiez la carte officielle avant de partir.</p>" if stale else ""
    )
    institution = esc(str(rw.get("institution_name") or "Ville de Québec").strip())
    dataset = safe_url(rw.get("dataset_url"))
    dataset_link = (
        f'<a href="{esc(dataset)}" rel="noopener noreferrer">{institution} — Entraves à la circulation en temps réel</a>'
        if dataset else f"{institution} — Entraves à la circulation en temps réel"
    )
    return (
        '<section class="roadworks" id="travaux" aria-labelledby="roadworks-title">'
        '<div class="section-top"><div><p class="eyebrow">DONNÉES OFFICIELLES</p>'
        '<h2 id="roadworks-title">Travaux et entraves.</h2></div>'
        f'<p class="section-note">{count_note}</p></div>'
        '<p class="dossiers-intro">Les entraves déclarées par la Ville dans son flux '
        "officiel en temps réel, relayées telles quelles. Vigie ne recalcule aucun "
        "effet sur votre trajet et ne classe pas ces données avec les articles.</p>"
        f"{changes}{listing}{more}{stale_html}"
        f'<p class="rw-map"><a href="{RW_MAP_URL}" rel="noopener noreferrer">Ouvrir la carte officielle des travaux <span aria-hidden="true">↗</span></a></p>'
        f'<p class="rw-attr fine">Données : {dataset_link} (CC-BY 4.0, via Données Québec). '
        f"Collecte du {date_html(fetched.isoformat())}. Les dates marquées « estimées » "
        "le sont par la Ville, pas par Vigie.</p></section>"
    )


def article_html(item: dict, index: int, related: list[dict], media: dict | None = None) -> str:
    title = esc(item["title"])
    media_file = media.get(item["uid"]) if isinstance(media, dict) else None
    if not isinstance(media_file, str) or not _MEDIA_FILE.fullmatch(media_file):
        media_file = None
    media_html = (
        f'<div class="story-media"><img src="/media/{media_file}" alt="" loading="lazy" decoding="async"></div>'
        if media_file else ""
    )
    geo = {"quebec-city": "Québec et environs", "quebec": "Au Québec", "linked": "Ailleurs"}.get(item["geo"], "Ailleurs")
    topic = TOPICS.get(item["topics"][0], "Vie locale")
    source = esc(item.get("source_name") or item.get("source_id") or "Source")
    summary = item["summary"]
    excerpt = summary[:240].rsplit(" ", 1)[0] + "…" if len(summary) > 240 else summary
    excerpt_html = f'<p class="excerpt">{esc(excerpt)}</p><span class="excerpt-label">Extrait du flux de {source}</span>' if excerpt else '<p class="excerpt-label">Le flux ne fournit pas de résumé. Consultez l’article original.</p>'
    peers = "".join(f'<li><span>{esc(r.get("source_name") or r.get("source_id"))}</span><a href="{esc(r["url"])}" rel="noopener noreferrer">{esc(r["title"])}</a>{date_html(r["published"])}</li>' for r in related)
    related_html = f'<p class="evidence-label">Autres articles du dossier proposé</p><ul class="source-list">{peers}</ul><p class="fine">Rapprochement automatique à vérifier. Plusieurs médias ne constituent pas plusieurs confirmations indépendantes.</p>' if peers else '<p class="fine">Aucun autre article rapproché dans cette collecte. Cela ne dit rien de la couverture ailleurs.</p>'
    kind = '<span class="official">Source officielle</span>' if item.get("source_kind") == "official" else ''
    place_reason = "Un lieu ou acteur local a été repéré dans le titre ou l’extrait." if item["geo"] == "quebec-city" else "Le classement géographique est proposé à partir du titre et de l’extrait."
    if item.get("source_kind") == "official" and item["geo"] == "quebec-city":
        place_reason = "Ce document provient d’une source officielle locale."
    return f'''<article class="story" id="article-{item['uid']}" data-id="{item['uid']}" data-geo="{esc(item['geo'])}" data-topics="{esc(' '.join(item['topics']))}" data-areas="{esc(' '.join(item['areas']))}" data-search="{esc(folded(item['title'] + ' ' + summary + ' ' + str(item.get('source_name', ''))))}" data-published="{esc(item['published'])}">
      <div class="story-number" aria-hidden="true">{index:02}</div><div class="story-body">
      {media_html}<div class="story-kicker"><span>{esc(topic)}</span><span>{geo}</span>{kind}<span class="new-label" hidden>Nouveau dans la collecte</span></div>
      <h3><a href="{esc(item['url'])}" rel="noopener noreferrer">{title}<span class="arrow" aria-hidden="true"> ↗</span></a></h3>
      <p class="byline">{source}<span aria-hidden="true"> · </span>{date_html(item['published'])}{'<span class="language">Article en anglais</span>' if item.get('language') == 'en' else ''}</p>
      {excerpt_html}
      <div class="story-actions"><details class="evidence"><summary>Sources et contexte <span aria-hidden="true">＋</span></summary><div class="evidence-body"><p>{place_reason} Ce repérage ne prouve pas un effet sur votre situation.</p>{related_html}</div></details>
      <button class="save js-only" type="button" data-save="{item['uid']}" aria-pressed="false" aria-label="Garder : {title}">Garder <span aria-hidden="true">＋</span></button></div>
      </div></article>'''


def render_brief(ranked: list[dict], generated_at: str, issues: list[dict], run: dict | None = None, ledger: dict | None = None, roadworks: dict | None = None, media: dict | None = None) -> str:
    now = parse_date(generated_at) or datetime.now(timezone.utc)
    rows, excluded = prepare_items(ranked, now)
    run = latest_run() if run is None else run
    if media is None:
        media = load_brief_media()
    elif not isinstance(media, dict):
        media = {}
    status = collection_status(run, now)
    eligible = {r.get("id"): r for r in rows}
    stories = "".join(article_html(r, n + 1, related_sources(r, issues, eligible), media) for n, r in enumerate(rows))
    areas = "".join(f'<option value="{esc(k)}">{esc(v[0])}</option>' for k, v in AREAS.items())
    topics = (("all", "Tout"), ("transport", "Se déplacer"), ("housing", "Se loger"), ("health", "Santé"), ("law", "Vie publique"), ("culture", "Culture"))
    filters = "".join(f'<button type="button" data-topic="{k}" aria-pressed="{"true" if k == "all" else "false"}">{v}</button>' for k, v in topics)
    service_html = "".join(f'<a class="service" href="{url}" rel="noopener noreferrer"><span class="service-index">{num} / {esc(eyebrow)}</span><h3>{esc(title)} <span aria-hidden="true">↗</span></h3><p>{esc(desc)}</p></a>' for num, eyebrow, title, desc, url in SERVICES)
    outcomes = {r.get("source_id"): r for r in run.get("results", []) if isinstance(r, dict)}
    source_rows = "".join(f'<li><span>{esc(sid)}</span><span>{"Collecté" if outcomes.get(sid, {}).get("ok") and not outcomes.get(sid, {}).get("parse_error") else "Indisponible"}</span></li>' for sid in (run.get("enabled_rss") or list(outcomes)))
    status_label = "État des sources inconnu" if not status["total"] else "Collecte indisponible" if not status["ok"] else "Collecte à actualiser" if status["stale"] else "Collecte partielle" if status["partial"] else "Dernière collecte"
    coverage = f'{status["ok"]} flux disponibles sur {status["total"]}' if status["total"] else 'État des sources inconnu'
    empty = '<p class="no-data">Aucun article récent avec une date de publication exploitable. Consultez les sources officielles ci-dessous.</p>' if not rows else ''
    return f'''<!doctype html>
<html lang="fr-CA"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Comprendre ce qui bouge à Québec. Un point local, des sources à comparer et des repères pour agir. Sans compte, sans fil infini.">
<meta name="theme-color" content="#152f3a"><meta name="referrer" content="no-referrer">
<title>Vigie — Québec, à hauteur de vie</title><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/brief.css"><script src="/assets/brief.js" defer></script></head>
<body><a class="skip-link" href="#essentiel">Aller aux nouvelles</a>
<header class="masthead"><a class="wordmark" href="/" aria-label="Vigie, accueil"><svg width="28" height="32" viewBox="0 0 28 32" aria-hidden="true"><path d="M2 5 14 28 26 5M8 5l6 12 6-12" fill="none" stroke="currentColor" stroke-width="2.5"/></svg>vigie<span class="wordmark-dot">.</span></a><span class="edition">QUÉBEC, À HAUTEUR DE VIE</span><nav aria-label="Navigation principale"><a href="#essentiel">Le point</a><a href="#dossiers">Les dossiers</a><a href="#agir">Repères utiles</a><a href="#methode">Notre méthode</a></nav></header>
<main><section class="intro" aria-labelledby="intro-title"><div><p class="eyebrow">UNE VILLE. VOTRE QUOTIDIEN.</p><h1 id="intro-title">Moins de bruit.<br><em>Plus de Québec.</em></h1><p class="intro-text">Les nouvelles locales. Les sources pour comprendre. Les repères pour agir. Puis, reprenez votre journée.</p></div>
<aside class="edition-note" aria-label="Fraîcheur des informations"><div class="compass" aria-hidden="true"><span>N</span><svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="43"/><path d="M60 5v22M60 93v22M5 60h22M93 60h22M60 31l13 42-13-8-13 8Z"/></svg></div><p class="eyebrow">LE POINT DE REPÈRE</p><p id="freshness-label" class="freshness{' warning' if status['stale'] or status['partial'] else ''}" data-fetched="{esc(status['at'])}" data-partial="{str(status['partial']).lower()}" data-total="{status['total']}" data-ok="{status['ok']}">{status_label}</p><p class="edition-time">{date_html(status['at'], fallback='Aucune collecte horodatée')}</p><a class="coverage-link" href="#couverture">{coverage} <span aria-hidden="true">↗</span></a><p class="fine">Un instantané des sources. Pas un service d’alerte en temps réel.</p></aside></section>
<section class="brief" id="essentiel" aria-labelledby="brief-title"><div class="section-top"><div><p class="eyebrow">L’ESSENTIEL, À VOTRE ÉCHELLE</p><h2 id="brief-title">Faire le point.</h2></div><p class="section-note">7 jours de publications.<br>Édition du {date_html(generated_at)}.</p></div>
<div class="visit-strip js-only"><p id="visit-status" role="status">Une première visite ? Prenez vos repères.</p><button id="remember" type="button">Mémoriser ce point de lecture</button></div>
<div class="controls js-only"><div class="view-tabs" role="group" aria-label="Vue des articles"><button type="button" data-view="brief" aria-pressed="true">Le point local</button><button type="button" data-view="new" aria-pressed="false">Depuis mon repère <span id="new-count"></span></button><button type="button" data-view="saved" aria-pressed="false">Mes articles gardés <span id="saved-count"></span></button></div>
<div class="search-row"><label class="search-label"><span class="sr-only">Rechercher dans les titres et extraits</span><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8" cy="8" r="5.5"/><path d="m12 12 5 5"/></svg><input id="search" type="search" placeholder="Une rue, un sujet, un nom…" autocomplete="off" maxlength="200"></label><label class="select-label"><span>Territoire</span><select id="scope"><option value="local">Québec et environs</option><option value="province">Tout le Québec</option><option value="all">Tous les flux</option></select></label><label class="select-label"><span>Lieu mentionné</span><select id="area"><option value="all">Tous les lieux</option>{areas}</select></label></div><div class="topic-filters" role="group" aria-label="Thème des articles">{filters}</div><p class="filter-note">Les lieux et thèmes sont repérés automatiquement. Un lieu absent d’un extrait peut échapper au filtre.</p></div>
<noscript><p class="notice">Tous les articles récents sont affichés. La recherche et les repères personnels nécessitent JavaScript.</p></noscript>
<div class="results-bar"><p id="result-count" role="status">{len(rows)} articles récents dans les flux collectés</p><button class="text-button js-only" type="button" id="reset-filters">Réinitialiser les filtres</button></div><div id="stories">{stories}{empty}</div>
<div id="no-results" class="no-data" hidden><h3>Aucun article dans cette vue.</h3><p>Essayez un autre lieu ou élargissez le territoire. Une absence dans nos flux ne signifie pas qu’il ne se passe rien.</p><button type="button" id="empty-reset">Voir le point local</button></div>
<div class="brief-end"><p id="end-note">Vous avez fait le tour de cette sélection.</p><button class="js-only" id="show-more" type="button">Voir les autres articles</button><span class="fine">Pas de défilement infini. Revenez quand vous en avez besoin.</span></div></section>
{roadworks_section(roadworks, now)}
{change_section(ledger)}
{dossiers_section(issues, eligible)}
<section class="services" id="agir" aria-labelledby="services-title"><div class="section-top"><div><p class="eyebrow">L’INFORMATION DEVIENT UTILE</p><h2 id="services-title">Et maintenant ?</h2></div><p class="section-note">Quatre accès directs<br>aux services officiels.</p></div><div class="service-grid">{service_html}</div><p class="fine">Ces liens ouvrent les services officiels. Leurs avis ne sont pas collectés par Vigie.</p></section>
<section class="method" id="methode" aria-labelledby="method-title"><div><p class="eyebrow">LA CONFIANCE SE VÉRIFIE</p><h2 id="method-title">Les sources d’abord.<br>Le jugement vous appartient.</h2><p>Vigie rassemble des titres et des extraits. Il ne réécrit pas l’actualité et ne décide pas de ce qui est vrai à votre place.</p></div><div class="method-details"><details><summary>Comment les articles sont-ils choisis ?</summary><p>Proximité géographique (60 %) et fraîcheur de publication (40 %). La fraîcheur diminue de moitié après 36 heures. Seuls les articles datés des 7 jours précédant cette édition entrent dans ce point. Aucun poids pour les clics ou la publicité.</p><p>{excluded} articles écartés de ce point : trop anciens, date absente ou invalide, ou lien inexploitable. Les filtres changent la sélection, jamais l’ordre public.</p><a href="/ranking.md">Lire le classement publié ↗</a></details><details id="couverture"><summary>Quelles sont les limites de la couverture ?</summary><p>{coverage}. Collecte : {date_html(status['at'])}. Un flux peut omettre des articles, être tronqué ou indisponible. Cette liste n’est pas toute l’actualité de Québec.</p><ul class="coverage-list">{source_rows}</ul><a href="/sources.yaml">Consulter la liste des sources ↗</a></details><details><summary>Mes repères restent-ils privés ?</summary><p>Les articles gardés et votre point de lecture restent sur cet appareil, dans ce navigateur. Aucun compte, suivi publicitaire ou accès à votre position. Les recherches restent dans la page. Les sites sources ont leurs propres pratiques.</p><p>Les images d’aperçu proviennent des éditeurs (og:image) : Vigie les récupère au moment de la collecte et les sert depuis ce site — votre navigateur ne contacte aucun éditeur en lisant ce point. Un article dont l’éditeur ne publie pas d’image reste sans image : aucune image n’est inventée.</p><button id="clear-local" type="button" class="js-only">Effacer mes repères sur cet appareil</button><p id="privacy-status" role="status"></p></details><details><summary>Qui finance Vigie ?</summary><p>Le projet est actuellement financé par son fondateur. Aucun achat de placement dans le classement.</p><a href="/RENT.md">Lire le financement déclaré ↗</a></details><details><summary>Explorer le prototype et ses dossiers</summary><p>L’atelier conserve les comparaisons de sources et la méthode expérimentale. Les regroupements sont proposés, les contradictions et l’indépendance des sources ne sont pas établies.</p><a href="/explorer.html">Ouvrir l’atelier de recherche ↗</a></details></div></section></main>
<footer><a class="wordmark" href="/">vigie<span class="wordmark-dot">.</span></a><p>Un peu plus au courant.<br>Un peu plus libre de votre temps.</p><span>Fait pour Québec.<br>Édition expérimentale.</span></footer><div id="toast" role="status" aria-live="polite"></div></body></html>'''
