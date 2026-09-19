# Vigie — Technical process (v0) — as built

How the lookout works. Physics, not poetry. Updated 2026-09-19 to match the scripts.

## Goal of v0

One thin loop for Quebec City:

**ingest (RSS + official WZDX) → normalize → enrich (proposed) → cluster Issues → edge atlas + anomaly rules → brief media → rank → display**

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
| 1 Ingest RSS | `scripts/ingest_rss.py` | `data/raw/<source_id>/` append-only |
| 1b Ingest WZDX | `scripts/ingest_wzdx.py` | `data/raw/` + `data/roadworks/latest_roadworks.json` — official change data; bypasses the article pipeline, the RSS ceiling, the ranking and the silence map |
| 2 Normalize | `scripts/normalize.py` | `data/normalized/latest_candidates.json` |
| 3 Enrich | `scripts/enrich.py` | `data/normalized/latest_enriched.json` — **all tags proposed** |
| 4 Cluster | `scripts/cluster_issues.py` | `data/issues/latest_issues.json` — multi-voice only |
| 4b Edge Atlas | `scripts/edge_atlas.py` | `data/edges/latest_edges.json` — literal street-name joins between the official collection and the dossiers (`edge.md`) |
| 4c Anomalies | `scripts/compile_anomalies.py` | `data/anomalies/latest_verdict.json` — fixed-threshold structural rules over the official collection (`anomalies.md`) |
| 4d Brief media | `scripts/fetch_brief_media.py` | `data/media/brief/` + `brief_manifest.json` — publisher og:image, locally re-hosted and sniffed |
| 5 Rank+HTML | `scripts/rank_display.py` | `latest_ranked.json` + `public/index.html` (French brief, incl. roadworks/beacon/joins) + `explorer.html` + ambient twin via `ambient_pulse` |
| 5b Ambient | `scripts/ambient_pulse.py` | `data/pulse/latest_morning.{json,txt}` + `public/morning.html` (same Approaches; no second rank; store order — no facets, no beacon) |
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

## Success / failure

Wrong if: skim-feed behavior; hidden party line; Near me full of world wire; Issues with one voice calling themselves contradictions.

Right if: a resident returns because local → linked chains beat propaganda fog on something that hits their life.