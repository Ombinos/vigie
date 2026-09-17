# Vigie — co-founder audit and product decisions

Date: 2026-09-17. Scope: local repository, registry, data snapshots, Python pipeline, generated pages, browser behavior and release process. This is a product and implementation assessment, not proof of market demand or the truth of publisher content.

## The judgment

Vigie began as a transparent RSS lookout with an experimental source-comparison interface. Its strongest asset is the refusal to invent news or hide ranking decisions. Its weakest point was the distance between that philosophy and the resident's actual task: **tell me what changed around me, let me check it, and help me decide whether to do anything.**

The product should compete on useful understanding per minute. A resident leaving better oriented is the desired outcome. The changes in this pass establish that front door and repair evidence defects. They do not establish product-market fit, exhaustive coverage, or a defensible business.

## Strengths to preserve

| Strength | Why it matters | Condition |
|---|---|---|
| Québec-first scope | A coherent civic context makes relevance assessable | Require local evidence, not just a local publisher |
| Named, finite source registry | Readers can inspect selection and omissions | Expose unavailable sources and publish changes |
| Source links and excerpts | Evidence stays inspectable | Attribute excerpts and preserve original URLs |
| Public ranking | Editorial choices are visible | Document both score and display rules |
| Source comparison | Readers can inspect different accounts | Never equate grouping with contradiction |
| Static delivery | Cheap hosting and a small operational surface | Avoid unnecessary backend services |
| No account requirement | Removes friction before first value | Make personal storage explicit |
| Existing domain tests | Encodes lessons such as Lévis versus télévision | Test behavior rather than preserving old copy forever |

## Defects and implemented changes

| Finding | Consequence | Correction |
|---|---|---|
| English/internal vocabulary at the entrance | Residents had to learn the prototype | French homepage; older workbench isolated at `/explorer.html` |
| Method presented before useful news | Effort before value | Finite local brief, source drawers, direct civic-service links |
| Download time used as publication time | Undated stories appeared fresh | RFC/ISO parsing; no freshness reward for missing/future dates |
| Build clocks confused with freshness | Old news looked newly checked | Actual collection timestamp, six-hour stale warning, partial/unavailable states |
| Failed/disabled/stale sources resurfaced | Coverage appeared healthier than it was | Latest outcomes, enabled registry, 48-hour raw-snapshot expiry |
| Parsing errors could report success | Broken feeds inflated availability | Both fetch and parse must succeed |
| Publisher URLs influenced geography | World articles leaked into local space | Text evidence and context for ambiguous place names |
| Police topic implied death | Enrichment invented a consequence | Separate security impact label |
| A politician's name joined unrelated stories | False dispute narrative | Separate subjects and conservative event grouping |
| Four hardcoded issues constrained discovery | New local events could not become dossiers | Generic headline grouping with strong precision limits |
| IDs depended on source counts | Continuity broke as reporting grew | Stable identities; content-aware workbench change fingerprints |
| Source counts implied confirmation | False certainty | Explicitly unassessed contradiction and independence |
| Claim tests rewarded mere extraction | Provenance could silently vanish | Source containment and provenance validation |
| Unsafe/unbounded feed handling | Network and resource exposure | Public targets, pinned addresses, redirect checks, bounded bodies |
| Incomplete HTML attribute escaping | Feed text could break attributes | Both quote types escaped; executable links rejected |
| Staging copied a hardcoded shortlist | Missing new assets and retained old files | Complete clean snapshot, manifest, link checks and rollback |
| Preview exposed directories/symlinks | Unintended file access | Restricted routes, no listings, consistent GET/HEAD |
| No complete verification command | Unit tests could miss broken delivery | Tests, syntax, staging, links and HTTP byte checks |

## What residents can now do

The homepage starts with Québec and nearby places. Residents can narrow by place mention or topic, search titles and excerpts without sending queries anywhere, inspect sources, keep an article locally and explicitly record a point of reading. The return view reports newly present article URLs; it does not claim to detect changes to the world or revisions within a publisher's article.

Only usable publication dates in the seven days before the edition enter the brief. Six articles appear per step, with a stopping point and no infinite scroll. Saved markers do not archive publisher content; articles absent from the current collection are counted as unavailable.

Official links cover municipal works, RTC information, consultations and snow-removal alerts. These are useful navigation; their data is **not** ingested or presented as a real-time warning service.

The new homepage uses local CSS/JavaScript and available fonts, with no analytics or location request. Source reading and disclosures remain usable without JavaScript. The older workbench can still load external fonts and publisher thumbnails; it has a different privacy surface and remains experimental.

## The next leap: a local change record

The promising direction is an explainable relationship between **an event, a place, a time, a source and a possible action**. This is a product hypothesis, not a shipped capability.

A future road-work entry should show:

1. What the official source says changed, with original wording and update time.
2. Where it applies, using source coordinates or a documented boundary.
3. When it starts and ends, including unknown or revised dates.
4. Which source fields support the consequence, with inferred effects marked.
5. A useful next step, such as checking the official map or route.
6. Its revision history: added, changed, postponed, resolved or unavailable.

This requires better underlying information and durable event identity. An LLM might eventually help extract structured fields; it cannot replace source provenance, correction handling, geographic validation or measured error rates.

### First experiment: daily mobility

Start with one recurring job: **will something change my usual trip?** Validate with a small group of Québec residents who repeatedly travel the same corridors. Record useful discoveries and false alarms with their permission; do not add hidden behavioral tracking.

The Ville publishes an official [WZDX road-obstruction dataset](https://www.donneesquebec.ca/recherche/dataset/entraves-a-la-circulation-en-temps-reel-de-la-ville-de-quebec). The registry describes spatial road-work information, a real-time update frequency and CC-BY 4.0 attribution. Actual endpoint behavior, field completeness and operational uptime still need engineering verification before integration. The [RTC information page](https://www.rtcquebec.ca/restez-informe) provides official route/alert context; actual API availability and conditions must be checked before promising integration.

Progress from one official change source to reliable revision history, then explicit saved places/corridors. Avoid requiring a home address. “We could not check this route” must be as clear as “a change was reported.”

### Second experiment: decisions before deadlines

The City's [participation portal](https://participationcitoyenne.ville.quebec.qc.ca/) is a potential source for consultations. A later feature should surface the official closing date, affected area, original proposal and participation link. Extracted dates need source-level validation before any reminder or calendar promise.

### What could become defensible

Reliable local event identity, revision history, corrections, tested geography and source relationships could make Vigie difficult to replace. A generic chat box or opaque truth score would not. This is a strategic hypothesis; proprietary advantage and willingness to pay are unproven.

## Remaining constraints

- **Coverage:** RSS is incomplete and can be truncated. Municipal communications are not an emergency-alert feed. Neighborhood/community coverage is uneven.
- **Relevance:** text rules remain provisional. They can miss paraphrases or overmatch names. Québec and environs includes Lévis and nearby communities; it is not a City boundary filter.
- **Dossiers:** conservative lexical grouping misses bilingual and differently worded reports. Newsroom identity is not independent ownership/reporting.
- **Consequences:** extracted quantities cannot reliably calculate a policy's effect on a particular resident. No such outcome should be implied.
- **Operations:** a local/staged release is ready to serve, but no confirmed deployment target, refresh schedule, alert delivery, production monitoring or production backup service was configured here.
- **Publisher permissions:** reuse notes are in the registry. This pass did not establish commercial redistribution or image-use arrangements.
- **Corrections:** there is no staffed correction inbox or confirmed response commitment. An original article may change without RSS reflecting the revision.
- **Accessibility:** semantic controls, focus, reduced motion and responsive layouts are implemented; full assistive-technology auditing remains separate.
- **Technical debt:** the legacy workbench remains a large generated HTML module with some brittle historical tests. It is isolated, not fully rearchitected.
- **Business:** founder-backed funding, retention, pricing and willingness to pay remain unvalidated. Do not purchase growth before earning repeat use.

## Acceptance

Run `python -X utf8 scripts/verify.py --rebuild` for current tests, syntax and staged HTTP delivery, and `python -X utf8 scripts/check_claims.py` for extraction integrity. The final execution report records exact counts; an old document count must not masquerade as current verification.

Product acceptance requires watching residents find a relevant development, identify its source/date, recognize uncertainty and reach a useful next step without assistance. Measure time and mistakes. A paradigm shift is earned by those outcomes, not declared by the interface.
