# Methodology

How a shadow polygon in this project is produced, stated precisely enough to be
reimplemented or contested.

---

## 1. Sign and unit conventions

| Quantity | Convention | Units |
| --- | --- | --- |
| **Solar azimuth** | Degrees **clockwise from true north** (0 = N, 90 = E, 180 = S, 270 = W). Describes the direction **from the observer towards the sun**. | degrees |
| **Solar elevation** | Angle between the sun and the **true horizon**, positive above. | degrees |
| **Solar zenith** | Angle from vertical. `zenith = 90° − elevation`. | degrees |
| **Apparent elevation** | Elevation after atmospheric refraction, as reported by the solar model. | degrees |
| **Shadow azimuth** | Direction the shadow **extends**, i.e. the direction light **travels**. Always `solar_azimuth + 180°`. | degrees |
| **Sun vector** | Unit vector **towards the sun** in a local East/North/Up frame: `(cos E·sin A, cos E·cos A, sin E)`. | unitless |
| **Light-travel vector** | The negation of the sun vector. | unitless |
| **Ground plane** | `z = 0`, flat. | metres |
| **Distances, areas** | Planar, in EPSG:32643. | m, m² |
| **Heights** | Above the ground plane, i.e. above `z = 0`. | m |

The sun vector uses a **local tangent-plane ENU frame**, not a full geodetic
basis derived from the ellipsoid normal. Over a 310 m site the difference
between geodetic and geographic "up" is under 0.001°, which is orders of
magnitude below the building-data error. This is a deliberate, documented
simplification, not an oversight.

---

## 2. Solar position

**Implementation:** `pvlib` 0.16.1, `solarposition.get_solarposition(method="nrel_numpy")`.

This is pvlib's implementation of the **NREL SPA** (Reda & Andreas, *Solar
Position Algorithm for Solar Radiation Applications*, 2003/2004), including
atmospheric refraction and solar-disc corrections. It is a validated,
peer-reviewed astronomical implementation. **No hand-written solar
approximation is used anywhere in this project.**

Inputs are the exact study-area centroid (12.9715 °N, 77.59555 °E), the exact
timestamp, and the `Asia/Kolkata` timezone. The UI displays local civil clock
time; all computation is timezone-aware and the UTC offset (+05:30) is carried
in every timestamp string.

Sanity results for 2026-10-01: sunrise **06:14**, sunset **18:08**, maximum
elevation **73.65°** near 12:00 with the sun due south, azimuth sweeping
E → S → W across the day. All physically correct for 12.97 °N in October.

---

## 3. Shadow geometry

### 3.1 The physical model

Each building is a set of **vertical prisms**: a footprint assumed constant with
height, spanning `z_bottom … z_top` (flat roof, vertical walls). The ground is
`z = 0`.

Light leaves the top of a vertical edge at height `z` and travels to the ground
plane. The horizontal distance it covers is

$$L(z) = \frac{z}{\tan E}$$

along the horizontal direction **opposite** the sun. With
`d̂ = (−sin A, −cos A)` the unit horizontal anti-solar direction, the shadow of a
prism is exactly the **Minkowski sum** of its footprint with the segment

$$S = \left[ \frac{z_{bottom}}{\tan E}\,\hat{d},\ \ \frac{z_{top}}{\tan E}\,\hat{d} \right]$$

### 3.2 Computing the Minkowski sum exactly

For a polygon `P` and a vector `s`, `P ⊕ [0, s]` is computed as the union of

* `P` itself
* `P + s` (the translated polygon)
* for every edge `(a, b)` of `P`, the quad `(a, b, b+s, a+s)`

This is **exact**, including for **concave** footprints. A convex-hull
approximation would be wrong for an L-shaped building, and several UB City
footprints are not convex.

For a prism with `z_bottom > 0` the footprint is first translated by the
`start` offset, so the shadow is `(P + start) ⊕ [0, end − start]`. Omitting that
initial translation is a real bug — it is invisible for ground-based prisms and
silently wrong for raised ones. The test
`test_podium_plus_tower_equals_solid_prism` catches it by asserting that a
building modelled as podium + tower casts **exactly** the same shadow as the
equivalent solid prism.

### 3.3 Building-to-building shadowing

Shadows are **not** computed independently and left to overlap visually. For
each frame the engine runs an occlusion test:

* For every building, sample points on a deterministic 12 × 12 lattice across
  the top surface of each of its prisms.
* For each sample, test whether it lies inside the shadow volume cast by **any
  other** building **at that same height**.

The same Minkowski construction is reused at height `h` for this test, so the
occlusion result and the rendered geometry can never disagree. The result is
published per building as `shaded_fraction` and `shaded_by`, so a taller
neighbour demonstrably shades a lower one.

*Scope:* this is a one-directional test along the sun vector, which is exactly
the shadow test. It is not a general two-way visibility solver, and it does not
model diffuse sky light, reflections, or partial shading from geometry finer
than the sample lattice.

### 3.4 Numerical robustness at low sun

`L = z / tan E` diverges as `E → 0`. Two rules apply, both published with every
frame:

1. **Emission threshold.** No shadow is emitted for `E < 0.10°`
   (`MIN_SHADOW_ELEVATION_DEG`). Below this the projection is dominated by the
   clip and represents nothing meaningful.
2. **Hard clip.** Projection is truncated at **1000 m** from the building base
   (`MAX_SHADOW_LENGTH_M`). Any frame where this engages is flagged
   `truncated: true`, surfaced in the UI, and written into the GeoJSON export.

The functions raise rather than return non-finite values, and a test walks the
entire published dataset asserting every float is finite and every coordinate is
a real longitude/latitude.

---

## 4. Frame timeline

Exactly **25 frames**, hourly, from **06:00 local on 2026-10-01 to 06:00 local
on 2026-10-02** — 24 hourly steps plus both endpoints. Every frame is an exact
timestamp, and the UI displays that exact clock time rather than a bin.

Of these, **12 have the sun above the horizon** and produce shadow geometry;
**13 are at night** and produce **no shadow polygon at all**, with
`sun_above_horizon: false` stated explicitly in the data and shown in the UI.

Frames are **never interpolated**. Moving the slider to 11:00 displays the
geometry computed for 11:00. Interpolating between hourly frames would
produce a polygon corresponding to no real solar position.

---

## 5. Architectural separation

```
Next.js / Mapbox GL JS  ── renders pre-computed GeoJSON, owns no science
        ▲
        │  static JSON over HTTP
public/data/*.geojson, simulation.json
        ▲
        │  written by
Python pipeline  ── all geometry, solar position, statistics, validation
        ▲
        │  read from
OpenStreetMap API  (live, real data — never fabricated)
```

**The browser never computes a shadow.** It selects a pre-computed frame and
hands it to a Mapbox source. Slider movement performs a `setData` on an
in-memory GeoJSON object — no reprojection, no solar maths, no polygon
construction in the client.

Mapbox's own lighting is used only as ambient scene shading for the 3D
extrusions. It is **never** the scientific shadow calculation.

---

## 6. Reproducibility

`python scripts/run_pipeline.py` rebuilds everything from source: acquisition →
normalisation → solar → shadows → validation → report. Each stage runs as a
separate process so a failure in one cannot leave a partially-updated dataset,
and the pipeline exits non-zero on any failure.

The published `simulation.json` carries a `simulation_sha256` over its own
canonical serialisation, so a given dataset can be identified exactly. The
simulation date, timezone, frame count, CRS pair, solar algorithm and library
version, clip limits, and ground model are all recorded in the output.
