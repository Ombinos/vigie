# Vigie — Technical process (v0) — as built

How the lookout works. Physics, not poetry. Updated 2026-09-19 to match the scripts.

## Goal of v0

One thin loop for Quebec City:

**ingest (RSS + official WZDX) → feed health → normalize → enrich (proposed) → cluster Issues → edge atlas + anomaly rules → brief media → rank → display → edition metrics → watchdog**

No SaaS theater. No multi-tenant billing. Prove the method.

## One command

```text
python scripts/pipeline.py
python scripts/serve.py
```

Open http://127.0.0.1:8765/

## Scripts (law of the house)

| Step | Script | Output |
|------|--------|--------|
| 1 Ingest RSS | `scripts/ingest_rss.py` | `data/raw/<source_id>/` append-only; conditional GET (ETag / If-Modified-Since, body cached under `data/raw/_bodies/`) — a 304 costs zero payload bytes and is recorded as `not_modified` in the run meta |
| 1b Ingest WZDX | `scripts/ingest_wzdx.py` | `data/raw/` + `data/roadworks/latest_roadworks.json` — official change data; bypasses the article pipeline, the RSS ceiling, the ranking and the silence map |
| 1c Feed health | `scripts/feed_health.py` | `data/ops/feed_health.json` — per-source failure streaks, parse errors, yield trends, 304 rates, disk growth; fixed-threshold statuses (healthy / degraded / failing / dead); no wall clock |
| 2 Normalize | `scripts/normalize.py` | `data/normalized/latest_candidates.json` |
| 3 Enrich | `scripts/enrich.py` | `data/normalized/latest_enriched.json` — **all tags proposed** |
| 4 Cluster | `scripts/cluster_issues.py` | `data/issues/latest_issues.json` — multi-voice only |
| 4b Edge Atlas | `scripts/edge_atlas.py` | `data/edges/latest_edges.json` — literal street-name joins between the official collection and the dossiers (`edge.md`) |
| 4c Anomalies | `scripts/compile_anomalies.py` | `data/anomalies/latest_verdict.json` — fixed-threshold structural rules over the official collection (`anomalies.md`) |
| 4d Brief media | `scripts/fetch_brief_media.py` | `data/media/brief/` + `brief_manifest.json` — publisher images (og:image, else the feed's own media), locally re-hosted and sniffed; every miss diagnosed + `data/ops/media_health.json` ledger |
| 5 Rank+HTML | `scripts/rank_display.py` | `latest_ranked.json` + `public/index.html` (French brief, incl. roadworks/beacon/joins) + `explorer.html` + ambient twin via `ambient_pulse` |
| 5b Ambient | `scripts/ambient_pulse.py` | `data/pulse/latest_morning.{json,txt}` + `public/morning.html` (same Approaches; no second rank; store order — no facets, no beacon) |
| 6 Edition metrics | `scripts/compile_metrics.py` | `data/ops/edition_metrics.json` — per-edition snapshot: items, top-30 churn, per-source yield, dossier population, roadworks diff volume, image coverage; capped 120-edition history; idempotent per edition; observes the machine, never steers the ranking |
| 6b Watchdog | `scripts/compile_watchdog.py` | `data/ops/watchdog.{md,json}` — the weekly human read: fixed-threshold attention rules over the three ledgers + refresh log + disk usage; same-week recompiles replace; capped 26-week history |
| Serve | `scripts/serve.py` | local static server |

## Published method files

- `VISION.md` — vow
- `sources.yaml` — finite chancellery
- `ranking.md` — the public ranking law (geo + recency; `w_impact` gated at 0)
- `RENT.md` — thin wallet / cost law
- `FRICTION.md` — arrival friction log
- `FACETS.md` — opt-in life facet → Approaches reorder method (not public rank)
- `DESIGN.md` — beauty without fog (Arrival composition law)
- `edge.md` — Edge Atlas: literal street-level joins (`edge-atlas-v1`)
- `anomalies.md` — anomaly beacon: fixed-threshold structural rules (`anomaly-beacon-v1`)

## Enrich rules (proposed only)

- Strict city tokens → `quebec-city` (Near me)
- Primary feed without city token → park `quebec`, not Near me
- Province feed without QC/CA token → park `linked` (no world-fog cloak)
- World-fog titles (Iran, Danemark/Russie, celebrity wire…) without QC scar → `linked`
- Topics/impacts are heuristics — never truth; claims and falsifiable units are proposed objects
- Impact units: price (CAD/%/¢/kWh), bylaw_id, housing_count — high precision; bond-issuance dollars denied
- `w_impact` stays 0 until a deliberate ACT after unit coverage is judged sufficient

## Issues rules

- Quebec-city-first founding
- Require ≥2 distinct `source_id`s (single-voice is not contradiction)
- Voices side by side — never crown an answer
- Status always `proposed`

## Ranking (see ranking.md)

- v0: geo + recency
- `w_impact` stays 0 until we choose to score provisional impacts in public
- Silent editorial boosts forbidden

## Machine room (self-diagnosis, no self-steering)

Doctrine: **every silence is a diagnosed fact, and every diagnosis feeds a fixed policy — never a model.** The pipeline observes itself into `data/ops/` ledgers; humans read the watchdog and amend law deliberately.

- `media_health.json` (`media-health-v1`) — why each scoped article has no image: fine-grained reasons, per-domain failures, capped 28-run history. Policy: dead articles permanent, bot walls permanent after 2 attempts, transients backed off to daily after 4; publisher feed media as fallback (brief-media-v2).
- `feed_health.json` (`feed-health-v1`) — per-source streaks, parse errors, yield trends, 304 rates, disk growth; statuses by fixed thresholds (dead ≥ 72 h without success, failing ≥ 3 consecutive failures, degraded on any streak or falling yield).
- `edition_metrics.json` (`edition-metrics-v1`) — per-edition churn of the visible top-30, per-source yield into the ranked store, dossier population, roadworks diff volume, image coverage; capped 120-edition history; idempotent per edition stamp. Metrics never feed back into ranking, clustering or rendering.
- `watchdog.md` / `watchdog.json` (`watchdog-v1`) — the weekly human read compiled from the ledgers + refresh log + disk usage. Attention lines are fixed thresholds (failing/dead source, > 5 missing images or a rise > 3 across the window, churn > 15 of 30, any FAIL since the last successful production deploy); failures already recovered inside the 7-day log window are watch lines, not attention. An empty attention list says "the machine is healthy" — absence of facts is reported as absence, never as health.
- Bandwidth is rent: feed fetches are conditional (ETag / If-Modified-Since with a local body cache); a 304 returns the cached body, costs zero payload bytes, and the run meta records `not_modified` — the collection still happened, honestly.
- All ledgers: no wall clock (stamps come from the data), fail-soft (corrupt input → empty facts, exit 0), never published, never staged.

## Success / failure

Wrong if: skim-feed behavior; hidden party line; Near me full of world wire; Issues with one voice calling themselves contradictions.

Right if: a resident returns because local → linked chains beat propaganda fog on something that hits their life.