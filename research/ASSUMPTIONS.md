# Assumptions and limitations

Every assumption made by this project, and what each one costs. An assumption
that is not written down is a defect in a research deliverable.

---

## A1 — Ground is a flat plane at z = 0

**Assumed.** The entire study area sits on one horizontal plane.

**Why.** Integrating a DEM was out of scope for the first prototype, and the
data model already carries `ground_elevation_m` on every building (currently
`null`, never a fabricated number) so a DEM can be added without redesign.

**Cost.** Real relief across a 270 × 310 m site in central Bengaluru is small
but not zero, and Bengaluru sits at roughly 920 m elevation. A constant offset
would be harmless, but a *gradient* would tilt every shadow slightly and shear
the projection. Treat all shadow positions as having a systematic vertical
uncertainty of order the local relief, not as metre-accurate.

**To remove it:** attach a DEM (e.g. SRTM/Copernicus), set
`ground_elevation_m` per building and per vertex, and intersect rays with the
terrain surface instead of `z = 0`. The ray-intersection code is the only part
that must change.

---

## A2 — Flat roofs, vertical walls

**Assumed.** Footprints are extruded straight up; roof shape, setbacks and
terraces are not modelled.

**Why.** OSM `building:part` data would be needed for true massing, and this
bounding box contains no separate child part ways.

**Cost.** A real setback tower casts a differently-shaped shadow than its
prismatic approximation. For the five UB City towers tagged at 50–60 m with no
part data, the prismatic shadow is an approximation of unknown fidelity.

---

## A3 — Shadow length clipped at 1000 m

**Assumed.** Projection beyond 1000 m from the building base is discarded.

**Why.** `z / tan E` diverges as the sun approaches the horizon. At the 18:00
frame (elevation 1.51°) the natural shadow of a 60 m building is ~2 270 m —
several times the size of the study area, and unbounded as `E → 0`. Without a
clip, the last daylight frame produces enormous polygons dominated by a
degenerate case.

**Consequence, stated plainly:** the 18:00 frame's reported shadow area and
coverage are **lower bounds, not measurements**. The frame is flagged
`truncated: true`, the UI shows a warning, and the export records the limit.

**Why 1000 m:** roughly 3× the study area's long axis, so the clipped shadow
still visibly crosses the entire site. A different limit would be equally
defensible; the important thing is that it is explicit and published.

**Alternative considered and rejected:** dropping frames below some elevation
threshold. That would hide real low-sun behaviour, which is scientifically the
most interesting part of the day.

---

## A4 — No shadow below 0.10° solar elevation

**Assumed.** At `E < 0.10°` no shadow polygon is emitted at all.

**Why.** At that elevation the clip dominates completely, so the polygon would
be an artefact of the clip rather than a projection.

**Consequence:** the night count is 13 frames, and a frame between 0° and 0.10°
would be labelled `sun_above_horizon: true` but `shadow_emitted: false`. Both
flags are published, and the UI distinguishes the two states rather than
collapsing them.

---

## A5 — Floor counts are not converted to heights

**Assumed.** A building with only `building:levels` gets **no** height and casts
**no** shadow.

**Why.** Floor-to-floor height varies enormously between buildings — an
assumption of 3 m would be wrong for a luxury hotel and for a parking
structure. Presenting such a number as a height would present an estimate as a
measurement.

**Consequence, stated plainly:** **5 of 10 buildings cast no shadow at all**,
including one with a recorded floor count (Bagmane, 3 levels) and two schools.
Every shadow statistic in this project is therefore a **lower bound** on the
true shadowing of UB City.

**To relax it:** set `ALLOW_LEVELS_DERIVATION = True` in
`scripts/pipeline_config.py`. Affected buildings are then labelled
`derived_from_levels` with `low` confidence, and the assumption is recorded in
the provenance report. It is off by default by design.

---

## A6 — No terrain, no trees, no street furniture

**Assumed.** Only buildings occlude sunlight.

**Cost.** Bengaluru has mature street trees. Real shadow coverage is higher
than computed. Omitting vegetation is a known, unquantified underestimate.

---

## A7 — Building footprints are volunteer-surveyed

**Assumed.** The OSM geometry is accurate enough to project from.

**Cost.** This is the **weakest link in the entire chain**. Typical OSM building
positional error in a dense Indian urban core is on the order of **1–5 m**, and
it is not uniform. A 3 m footprint error displaces the shadow by up to 3 m
*(1 − z/z_top)*; for a 50 m building's base edge the displacement is ~3 m at the
base and ~0 m at the top. No survey-grade positional accuracy is claimed.

---

## A8 — OSM heights are treated as `medium` confidence

**Assumed.** A tagged `height` value is usable for projection.

**Cost.** OSM does not record *who* supplied a height tag or how. Some are
operator-supplied, some community-estimated. Labelling them `high` would
overstate the evidence, so all five are `medium`.

**Sensitivity:** at a 30° solar elevation, a 1 m error in a 60 m building
changes shadow length by `1/60 × 1/tan(30°) ≈ 2.9%`. So a plausible 2 m height
error translates to roughly a 6% shadow-length error — noticeably smaller than
the positional error in A7.

---

## A9 — Local tangent-plane ENU frame

**Assumed.** Sun geometry is computed in a flat local East/North/Up frame rather
than a full geodetic basis from the ellipsoid normal.

**Cost.** Under 0.001° over this site — negligible compared with A7 and A8.

---

## A10 — Clear-sky refraction, no weather

**Assumed.** Solar position is the true astronomical position with standard
atmospheric refraction, as computed by the solar model.

**Not modelled:** cloud cover, haze, atmospheric turbidity, or any reduction in
direct-beam irradiance. On a cloudy day in Bengaluru's monsoon season the
computed shadows would not exist at all. The result is a **clear-sky** shadow
projection, not an observed one.

---

## A11 — Occlusion is sampled, not solved

**Assumed.** Building-to-building shading is evaluated on a deterministic
12 × 12 lattice per prism.

**Consequence:** `shaded_fraction` is a sample estimate, accurate to roughly
±1–2% for a given building, not an exact occlusion integral. The lattice is
deterministic, so results are exactly reproducible between runs — the error is
a fixed bias, not run-to-run noise.

**Not modelled:** diffuse skylight, inter-reflection between facades, or
shading by vegetation.

---

## A12 — Overpass was unavailable

**Assumed.** Building data is obtained from the main OpenStreetMap API rather
than Overpass.

**Why.** Overpass returns HTTP 406 from a filtering proxy in this environment,
verified by direct request.

**Cost, and it is a real one:** the main API returns **nodes and ways only, not
relation members**, so a **multipolygon building assembled from an OSM relation
cannot be resolved by this method**. If UB City contains such a building, it is
absent from the dataset. The retrieval code detects building relations and
reports them rather than skipping them silently.

---

## A13 — Coverage percentage uses clipped, overlapping area

**Note on interpretation.** `shadow_coverage_percent` is
`Σ(per-building shadow area ∩ study area) / study area area`. Because shadows
overlap, **this can exceed what any physical observer would see**, and it is
capped at 100% only because the intersection is clipped to the study area.

Read it as *"summed building-shadow area intersecting the study area"* — an
intensity measure, not a fraction of ground that is actually dark. The two
quantities that are unambiguous are the per-building areas and the maximum
shadow length.

---

## A14 — Sunrise/sunset are bracketed to ±1 minute

**Assumed.** Sunrise and sunset are found on a 2-minute scan rather than by
root-finding the elevation crossing.

**Consequence:** accurate to about ±1 minute, which is ample for a daily
summary. The 25 hourly frames themselves are computed directly at their exact
timestamps and are unaffected.

---

## Summary of what is *not* claimed

This project does **not** claim, and the documentation deliberately avoids,
any statement of "real-time accurate", "survey accurate", or "perfectly
accurate". Specifically:

* Solar position is computed to high astronomical precision, but that says
  nothing about the buildings.
* Building footprints are volunteer-surveyed, not surveyed, and are the
  dominant error source.
* Building heights are tagged values of unrecorded provenance, and half the
  buildings have none at all.
* The ground is flat, vegetation is ignored, and the sky is assumed clear.
* Shadow areas and coverage percentages are **lower bounds** in absolute terms,
  for two independent reasons: half the buildings cast no shadow (A5), and the
  18:00 frame is clipped (A3).
