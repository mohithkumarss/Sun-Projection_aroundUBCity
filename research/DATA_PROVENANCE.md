# Data provenance

UB City, Bengaluru — solar shadow research prototype.
All values in this document are read from the generated dataset; none are
transcribed by hand.

Dataset fingerprint: `simulation.json` → `metadata.simulation_sha256`

---

## 1. Study area

| Field | Value |
| --- | --- |
| Name | UB City, Bengaluru, Karnataka, India |
| Bounding box (W, S, E, N), WGS 84 | `77.5943, 12.9701, 77.5968, 12.9729` |
| Extent | 270.7 m (E–W) × 310.5 m (N–S) |
| Study area (padded rectangle) | 84,119 m² (8.41 ha) |
| Metric bounds (EPSG:32643) | recorded in `public/data/study-area.geojson` |

### How the bounding box was selected

1. **The place was geocoded, not guessed.** `UB City, Bengaluru, Karnataka,
   India` was resolved through Nominatim (OpenStreetMap's geocoder), which
   returned node `10291118242` on **Vittal Mallya Road, 12.9718 / 77.5956**.

   > An initial working assumption placed the site near 77.741 °E. That is
   > roughly 15 km east of the real UB City and returns a completely different
   > set of buildings. The geocode step caught this before any data was
   > accepted. This is recorded because it is a genuine reproducibility trap.

2. A **seed bounding box** of `77.5945, 12.9710, 77.5965, 12.9725` was queried
   against the OpenStreetMap API.

3. The **final bounding box is computed from the retrieved geometry**: the
   bounding box of the union of all returned building footprints, reprojected
   to EPSG:32643 and padded by 10 m so that shadows falling outside the built
   footprints remain visible.

The resulting extent (270.7 × 310.5 m) sits within the 200–300 m target of the
assignment on its short axis and slightly above it on the long axis. It was
**not** shrunk to hit the number: the box is a consequence of where the real UB
City buildings are.

---

## 2. Data source

| Field | Value |
| --- | --- |
| Source | OpenStreetMap |
| Endpoint | `https://api.openstreetmap.org/api/0.6/map.json` |
| Request | `…/map.json?bbox=77.5945,12.971,77.5965,12.9725` |
| Retrieved (UTC) | 2026-10-01T09:11:36 |
| Licence | ODbL 1.0, © OpenStreetMap contributors |
| Raw payload retained at | `public/data/_raw/osm_map_77.5945_12.971_77.5965_12.9725.json` |
| Elements returned | 536 (474 nodes, 62 ways) |
| Building ways kept | 10 |

### Why the main OSM API and not Overpass

Overpass (`overpass-api.de` and its mirrors) is **unreachable from the
execution environment**: every request, including `/api/status`, returns
**HTTP 406** from a filtering Apache proxy before it reaches the API. This was
verified directly, not assumed.

The main OpenStreetMap API serves the same underlying database and is the
documented method for small bounding-box extractions, so it is used instead.
This is a substitution of *transport*, not of *data*: the geometry is still
OpenStreetMap's.

### Known extraction limitation

The main OSM API returns **nodes and ways only**; it does not return relation
members. A multipolygon building assembled from an OSM relation therefore
**cannot be resolved by this method**. Any building relation in the bounding
box is detected, reported, and skipped. If UB City contained such a building it
would be absent from the dataset — this is a known blind spot, not a claim that
no such building exists.

---

## 3. Coordinate reference systems

| Purpose | CRS | Notes |
| --- | --- | --- |
| Storage / interchange | **EPSG:4326** (WGS 84) | All published GeoJSON |
| Metric computation | **EPSG:32643** (WGS 84 / UTM zone 43N) | All areas, lengths, ray intersections |

Every distance, area, shadow length, and planar geometry operation is performed
in EPSG:32643. No area or length is ever computed in degrees — this is enforced
by a test that asserts UB City building areas fall in a plausible square-metre
range and a round-trip projection test to 1e-9 degrees.

Output geometry is transformed back to EPSG:4326 for Mapbox. Round-trip
fidelity is verified to 1e-9 degrees (< 0.1 mm), which is far below the
accuracy of the source data and is not a claim about the data itself.

---

## 4. Building identifiers and heights

Ten OpenStreetMap **ways** form the study dataset. Identifiers are preserved as
`osm:way/<id>` and cross-reference to
`https://www.openstreetmap.org/way/<id>`.

| Building | OSM way | Height | Levels | Method | Confidence | Shadow |
| --- | --- | --- | --- | --- | --- | --- |
| UB City (hotel) | 107240643 | 50.0 m | 19 | `OSM_exact` | medium | yes |
| Comet | 364528078 | 60.0 m | 11 | `OSM_exact` | medium | yes |
| Concorde | 373431282 | 60.0 m | 20 | `OSM_exact` | medium | yes |
| (unnamed) | 1125334909 | 60.0 m | — | `OSM_exact` | medium | yes |
| Canberra | 1125334910 | 60.0 m | 18 | `OSM_exact` | medium | yes |
| Bagmane | 331183998 | **unresolved** | 3 | `unresolved` | none | no |
| (unnamed) | 331184021 | **unresolved** | — | `unresolved` | none | no |
| (unnamed school) | 498986775 | **unresolved** | — | `unresolved` | none | no |
| (unnamed school) | 1047676496 | **unresolved** | — | `unresolved` | none | no |
| (unnamed) | 1125334913 | **unresolved** | — | `unresolved` | none | no |

**5 of 10 buildings cast a shadow. 5 do not.**

### Height methodology

| Method | Meaning | Used here |
| --- | --- | --- |
| `OSM_exact` | An exact height is tagged in OpenStreetMap; used verbatim. | **yes, 5 buildings** |
| `documented` | Taken from an external citable document. | no — see §6 |
| `survey` | Measured by survey. | no |
| `lidar` | Derived from a lidar/DEM dataset. | no |
| `derived_from_levels` | Floor count × assumed floor height. | **disabled** |
| `unresolved` | No documented height. Displayed, casts no shadow. | **yes, 5 buildings** |

**Floor counts are never silently converted to heights.** The conversion exists
in the code behind the flag `ALLOW_LEVELS_DERIVATION` in
`scripts/pipeline_config.py`, which is **False by default**. Bagmane is tagged
`building:levels=3`; that value is retained and displayed, but Bagmane casts no
shadow, because a 3-storey assumption is an estimate and presenting it as a
measurement would be dishonest. A test (`test_levels_do_not_become_heights_by_default`)
enforces this.

### Why confidence is `medium`, not `high`

The five heights are OpenStreetMap `height` tags. Their actual provenance
varies between operators and community surveyors and is **not recorded in OSM
at the tag level**. Claiming `high` confidence would overstate what the data
supports, so every OSM height is labelled `medium`.

### Conflicts

No building in this dataset had two disagreeing height tags, so the
disagreement-preservation machinery (`height_conflicts`, the
first-tag-wins resolution rule) is implemented and exercised by the schema but
has nothing to report here. It is retained because a future OSM extract can and
will contain such cases.

### Building parts

Five ways carry `building:part=yes`, but in every case the *same way* also
carries a `building=*` tag, so there are **no separate child part ways** in this
bounding box. The part-based vertical model is implemented and used when child
ways exist; here each building resolves to a `single_prism`. This is reported
rather than papered over.

---

## 5. Transformation methodology

| Step | Tool | Detail |
| --- | --- | --- |
| OSM node refs → coordinates | `requests` | way node ids resolved from the API response |
| Ring closure | explicit | unclosed ways are closed before polygon construction |
| Validity repair | `shapely` `buffer(0)` | **only if invalid**, and every repair is logged |
| Degenerate removal | area test | zero-area results are dropped **and logged** |
| WGS 84 → UTM 43N | `pyproj` 3.8.0 | `always_xy=True` (lon, lat order) |
| UTM 43N → WGS 84 | `pyproj` 3.8.0 | for output |
| **Simplification** | **none** | source OSM vertex coordinates are retained exactly |

The geometry repair log for this run is **empty**: no polygon required repair.

---

## 6. Unresolved data problems

These are real, known, and not worked around:

1. **Five of ten buildings have no height.** They are displayed with their
   footprint and provenance but cast no shadow, which means **reported shadow
   areas are a lower bound** on the true shadowing in the study area. The two
   school buildings and three commercial structures are simply absent from the
   shadow model.
2. **No external height cross-reference was performed.** The brief suggests
   cross-referencing important buildings against public sources. The five OSM
   heights are used *as tagged* and are attributed to OSM. No independent
   published document was retrieved to confirm 50 m or 60 m, so the
   `documented` method is unused. A manual survey of developer/engineering
   documentation would strengthen this and is the highest-value next step.
3. **Relation-based multipolygon buildings are invisible** to this extraction
   method (§2).
4. **No DEM.** Ground is a flat plane at z = 0 m.
5. **Bbox-clipped geometry.** The OSM API can omit nodes that fall outside the
   requested box, which can clip a building that straddles the boundary. The
   retrieval code detects and reports such cases; none occurred in this run.
6. **Shadow length is clipped** at 1000 m, which affects the 18:00 frame only
   (see `ASSUMPTIONS.md`).

---

## 7. Files that constitute the dataset

```
public/data/
  buildings.geojson          10 real OSM footprints + full height provenance
  study-area.geojson         derived bbox + selection rationale
  simulation.json            25-frame index, solar metadata, analysis, sha256
  shadow-frames.json         all 60 shadow features, keyed by frame slug
  _provenance.json           machine-readable provenance (this document's source)
  _solar.json                raw solar position records
  _buildings_raw.json        pre-normalisation extraction
  _raw/osm_map_*.json        unmodified OSM API response
  shadows/*.geojson          25 per-frame FeatureCollections (WGS 84)
```

`VALIDATION.md` is generated by re-reading these files from disk and is the
authority on whether the published dataset passes its own checks.
