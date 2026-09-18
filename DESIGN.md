# Vigie — Beauty without fog (design law)

Date: 2026-09-16  
Last verified: 2026-09-17  
Method id: `beauty-without-fog-v0.1`  
Surface: Lookout Arrival first viewport (`public/index.html` via `rank_display.py`)

Beauty is method made effortless. Fog is chrome that pretends to clarify.

## Do

1. **One composition** in the first viewport: brand · one line · one supporting sentence · optional Since-you-left strip · Approaches · one CTA group. Facets / clock stay after CTA (opt-in / collapsed).
2. **Brand as hero signal** — `arrival-brand` must out-scale the headline. No competing chrome above it.
3. **Expressive type** — display + UI pair (Newsreader / Figtree). No Inter / Roboto / Arial / system-only stack as the voice.
4. **Atmospheric nest depth** — Near me / Province / Linked readable as depth on Approaches (inset nest edge). Palette = Cap Diamant stone · fleuve slate · winter ice. Not purple-on-white. Not cream+terracotta broadsheet.
5. **Full-bleed place atmosphere** only when a real Quebec City life image is on disk under `public/place/` and named in this file. Until then: quiet nest wash only — **refuse** abstract multi-layer AI gradients as “hero.”
6. **Cards only as interaction containers** — Approach buttons. Not decorative card grids in the hero. Glance chips on an Approach are method facts (geo / voices / silence / units), not a hero stat strip.

## Do not

1. Dashboard chrome, score worship, pill clusters, or stat strips in the hero.
2. Bias rainbows, trust meters, floating promo badges.
3. Inset hero collage; multi-layer glow; engagement streaks.
4. Invent news or crown a voice to make the UI look cleaner.
5. Silent personalization / For You theater.
6. Turning on `w_impact` as a visual excuse.

## Place tokens (v0.1)

| Token | Role | Notes |
|-------|------|-------|
| `--bg` / `--bg-deep` | Fleuve / ice wash | Cool slate, not cream |
| `--ink` | Stone reading | High contrast, calm |
| `--accent` | Lookout copper-teal | Cap / copper roof cue — not purple |
| `--nest-near` / `--nest-province` / `--nest-linked` | Nest depth edges | Approaches only |

## Named place images (full-bleed allowed only when listed)

_None yet._ Do not invent a Quebec City photo. Empty `public/place/` is correct.

## Motion (intentional, finite)

- Brand settle on Arrival
- Approach enter stagger (store order)
- Field open (existing)

All honor `prefers-reduced-motion: reduce`.

## Preview images (resident brief)

Publisher `og:image` only, fetched at collection time (`scripts/fetch_brief_media.py`) and served from our own origin — reading the brief never contacts a publisher. Bytes are sniffed, never trusted: no SVG, no mislabeled HTML, 700 KB cap. A silent publisher means no image — not a filler, never stock. Same treatment for every card that has one: full-width strip, 1200/630, hairline `--line` border, `object-fit: cover`; no invented hierarchy. New articles get their image on the next refresh; the lag is honest, placeholders are not.

## Decision log

| Date | Decision | Owner |
|------|----------|--------|
| 2026-09-16 | Ship law + Arrival polish; no invented QC photo; nest wash only | Bucky + Inventor |
| 2026-09-17 | Verification: composition order; silence chrome de-purpled to slate; place/ empty; tests lock Do/Do-not | Bucky + Inventor |
| TBD | Add full-bleed only with a real named place image in `public/place/` and a row above | Inventor |
| 2026-09-18 | Brief preview images: publisher og:image, locally re-hosted and sniffed; never stock, never invented | Bucky + Inventor |
