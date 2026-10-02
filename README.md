# UB City Solar Shadow Research Prototype

A GIS research prototype that projects the shadows of **real** buildings at
**UB City, Bengaluru** across a 24-hour period, and visualises the result on a
Mapbox Light basemap in 2D and 3D.

The scientific calculation lives entirely in a Python pipeline. The Next.js
application only selects and renders pre-computed geometry — it never computes
a shadow.

---

## What this is (and is not)

This project uses **real OpenStreetMap building data** for UB City and a
**validated astronomical solar model**. No building footprint, height,
coordinate, or shadow polygon is invented.

Where a height is not documented, the building is shown **without** a height and
**does not cast a shadow**, rather than being given a plausible-looking number.
Five of the ten buildings in the study area are in that state. Reported shadow
areas are therefore a documented **lower bound**.

Read `research/ASSUMPTIONS.md` before interpreting any number.

---

## Layout

```
scripts/            Python research pipeline (all science happens here)
  pipeline_config.py     single source of truth for every constant
  geo.py                 CRS transforms, sign conventions, validity guards
  fetch_buildings.py     1. acquire real OpenStreetMap data
  prepare_buildings.py   2. normalise geometry, resolve heights, derive study area
  calculate_solar.py     3. solar position, 25 frames, NREL SPA via pvlib
  shadow_geometry.py       the shadow projection engine
  generate_shadows.py    4. project 25 frames, measure, write GeoJSON
  validate_simulation.py 6. independent re-check + VALIDATION.md
  run_pipeline.py        one command for all of the above

tests/
  test_simulation.py     73 scientific & geometric tests

research/
  DATA_PROVENANCE.md     sources, retrieval, CRS, heights, open problems
  METHODOLOGY.md         sign conventions and the exact shadow algorithm
  ASSUMPTIONS.md         every assumption and what it costs
  VALIDATION.md          generated test report

web/                  Next.js + TypeScript + Tailwind + Mapbox GL JS
  src/app/                page, layout, global styles
  src/components/         map, timeline, analysis, building, controls
  src/lib/                typed data model, dataset loader, GeoJSON export
  public/data/            the generated dataset (copied in by the pipeline)

public/data/         generated dataset (canonical location)
```

---

## Reproduce the dataset

Requires Python 3.11+ and network access to the OpenStreetMap API.

```bash
cd assignment-29thsept2026

python3 -m venv .venv
.venv/bin/pip install shapely pyproj requests pvlib pytest

.venv/bin/python scripts/run_pipeline.py
```

This performs acquisition → normalisation → solar → shadows → validation →
report, and **exits non-zero if any stage fails**. It will not emit a partial or
fabricated dataset. Expect a `DataAcquisitionError` naming the exact endpoint
and failure if OSM is unreachable.

After a successful run, copy the dataset into the web app:

```bash
rm -rf web/public/data && cp -r public/data web/public/data
```

To run a single stage:

```bash
.venv/bin/python scripts/fetch_buildings.py
.venv/bin/python scripts/prepare_buildings.py
.venv/bin/python scripts/calculate_solar.py
.venv/bin/python scripts/generate_shadows.py
.venv/bin/python -m pytest tests -v
```

---

## Run the application

Requires Node 18+.

```bash
cd web
npm install

cp .env.example .env.local
# edit .env.local and set NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN=pk....

npm run dev      # http://localhost:3000
```

Production:

```bash
npm run build
npm run start
```

The token is read from the environment and is **never committed**. With no token
the app shows an explicit setup screen rather than a blank map.

---

## Study area and method at a glance

| | |
| --- | --- |
| Study area | UB City, Bengaluru — `77.5943, 12.9701, 77.5968, 12.9729` |
| Extent | 270.7 m × 310.5 m (8.41 ha) |
| Buildings | 10 real OSM ways; **5** cast shadows |
| Storage CRS | EPSG:4326 (WGS 84) |
| Metric CRS | EPSG:32643 (WGS 84 / UTM zone 43N) |
| Solar model | NREL SPA (Reda & Andreas 2003/2004) via `pvlib` 0.16.1 |
| Sunrise / sunset | 06:14 / 18:08 IST on 2026-10-01 |
| Frames | 25 hourly, 06:00 → next-day 06:00 IST |
| Daylight frames | 12 (13 night frames produce **no** shadow) |
| Shadow formula | Minkowski sum of footprint with `[z_bot/tan E, z_top/tan E]` along the anti-solar direction |
| Max shadow length | clipped at 1000 m; affected frames flagged `truncated` |

---

## Controls

* **Timeline** — 25 exact hourly positions, play/pause, 0.5×–4× speed, prev/next.
  Geometry is **never interpolated** between frames.
* **2D / 3D** — extrusions use real heights; buildings with unresolved heights
  are not extruded. Switching modes preserves the selected timestamp.
* **Click a building** — name, id, height, floors, height source, source URL,
  confidence, footprint area, and its shadow at the current time.
* **Export** — current frame, or all 25 frames, as GeoJSON with full solar and
  provenance metadata retained.

---

## Validation

```bash
.venv/bin/python -m pytest tests -v      # 73 tests
.venv/bin/python scripts/validate_simulation.py
```

Coverage includes: CRS correctness, solar position against a live `pvlib` call,
shadow **direction** (shadow must oppose the sun), shadow **length** against
the closed form `L = H / tan E`, an independent synthetic validation scene
(20 × 30 × 50 m), polygon validity, absence of NaN/inf coordinates, the
isoperimetric bound on area vs perimeter, exactly-25-frames, and no shadow
whenever the sun is below the horizon.

A bug found and fixed during development is worth noting, because it is exactly
the kind the tests exist to catch: a raised prism (`z_bottom > 0`) projected its
shadow from the origin instead of from its lower edge. It was invisible for
ground-based buildings and would have silently corrupted any podium-and-tower
massing. `test_podium_plus_tower_equals_solid_prism` now pins the correct
behaviour.

---

## Accuracy, stated honestly

Three accuracies are tracked separately and none is inflated:

1. **Solar position** — high astronomical precision (NREL SPA with refraction).
2. **Building positional accuracy** — volunteer-surveyed OSM geometry, roughly
   1–5 m, not survey grade. **This is the dominant error source.**
3. **Building height accuracy** — OSM-tagged, provenance unrecorded, `medium`
   confidence; half the buildings have no height at all.

The shadow result is only as accurate as its weakest input, which is the
building data. See `research/ASSUMPTIONS.md` §A7–A8 and `research/VALIDATION.md`.

---

## Licence and attribution

Building data © OpenStreetMap contributors, licensed **ODbL 1.0**.
Map data © Mapbox. Both are attributed in the application.
