# Vigie

**Québec, à hauteur de vie.** A finite local briefing: understand what was published, inspect the sources, find a useful next step, and get on with your day.

French-first, account-free, static HTML. No paid APIs, analytics, geolocation, or generated news on the resident homepage. Search and reading markers stay in the browser.

## Run

Python 3.12+ and Node.js for verification. No package installation required. Tested on Windows with Python 3.14.

```text
python -X utf8 scripts/pipeline.py
python -X utf8 scripts/verify.py
python -X utf8 scripts/serve.py
```

Open http://127.0.0.1:8765/

Use `--port 8771` if the default port is occupied.

```text
python -X utf8 scripts/pipeline.py --offline      # rebuild cached RSS, no network
python -X utf8 scripts/pipeline.py --render-only  # render existing enriched data
python -X utf8 scripts/verify.py --rebuild        # tests + offline rebuild + release checks
python -X utf8 scripts/verify.py --code-only      # code checks without downloaded data
python -X utf8 scripts/check_claims.py            # extraction provenance, not truth verification
python -X utf8 scripts/refresh.py                 # collect, verify, deploy to production (Vercel)
```

Production: **https://vigieqc.com** (custom domain; Vercel aliases route there too). Verification stages a complete release in `deploy/public/`, checks links and asset hashes, and tests real HTTP GET/HEAD responses. It does not upload. `scripts/refresh.py` is the upload path — pipeline → verify → re-link → `vercel deploy --prod` — and the Windows scheduled task `Vigie Refresh` runs it every 6 hours (interactive-only; lock file against overlaps; log at `data/ops/refresh.log`; any failing step leaves the previous production site up). A clean checkout needs one online pipeline run to produce real data.

## Product surfaces

- `/`: French resident brief. Six articles per step, source excerpts, comparisons, place/topic/search filters, saved articles and an explicit reading marker. Two honest change surfaces: “Travaux et entraves” (official WZDX roadwork data, attributed, never ranked with articles; each entry carries its collection presence — first seen, collections seen/missed, an absence never an end; City date revisions and declared endings are relayed literally, never as verified resolutions) and “Depuis la dernière édition” (dossier-level edition diff, shown only when a prior edition exists). Each dossier also carries its durable collection history (“Suivi depuis…”: first seen, editions seen/missed — one edition is one collection snapshot, and a missed edition is an absence, never a resolution).
- `/explorer.html`: older experimental evidence workbench, retained for inspection with explicit limitations.
- `/morning.html`: experimental dossier companion from the same issue store.

The brief uses publication dates during the seven days preceding the edition. It starts with Québec and nearby places; broader feeds require an explicit territory choice. Neighborhoods are mentions in source text, not guarantees of geographic impact. Saved markers do not archive publisher articles.

Read [PRODUCT_AUDIT.md](PRODUCT_AUDIT.md) for the co-founder assessment, implementation decisions, remaining limits and next experiments.

## Law of the house

| File | Role |
|------|------|
| `VISION.md` | Vow — vision / mission / kill list |
| `sources.yaml` | Finite source chancellery |
| `RENT.md` | Who pays (v0 = Inventor wallet) |
| `ranking.md` | Published weights + change log |
| `TECHNICAL_PROCESS.md` | How the pipe works |

## Pipe

ingest (RSS + official WZDX roadworks) → normalize → enrich (proposed) → cluster dossiers → rank → resident brief + explorer + morning

Classifications and dossiers are provisional. Named institutions do not prove independent ownership or reporting. Publication, collection, grouping and build time remain distinct. WZDX roadwork data is structured official change data, not articles: it bypasses normalize/enrich/cluster/rank, renders in its own finite brief section with attribution and collection diffs, and a feed outage never blocks the news pipeline. Removed from a collection is never reported as ended or resolved.

Source files and `public/assets/` are authoritative. Data snapshots, generated HTML, deployment output, caches and historical patch logs are excluded from version control.

## Success / failure

Wrong: skim-feed; Near me full of world wire; single-voice “Issues”; selling the rank.

Right: a resident returns because city → province → linked chains beat propaganda fog on something that hits their life.
