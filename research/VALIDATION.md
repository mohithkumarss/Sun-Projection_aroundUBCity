# Validation report

Generated 2026-10-01T09:42:33.767817+00:00 by
`scripts/validate_simulation.py`, which re-reads the published files from disk.

**Overall: PASS** -
24/24 checks passed.
The full automated suite (`tests/test_simulation.py`, 73 tests) also passes and
is run as stage 5 of `scripts/run_pipeline.py`.

## Checks

| Check | Result |
| --- | --- |
| storage CRS is EPSG:4326 | PASS |
| computation CRS is EPSG:32643 | PASS |
| all shadow files declare EPSG:4326 export | PASS |
| exactly 25 frames | PASS - got 25 |
| simulation date is 2026-10-01 | PASS |
| hourly increments across midnight | PASS |
| starts 06:00 local | PASS |
| ends 06:00 local next day | PASS |
| all timestamps in Asia/Kolkata (+05:30) | PASS |
| night frames produce zero shadow features | PASS - 13 night frames |
| night frames have zero area | PASS |
| no shadow emitted below the elevation threshold | PASS |
| shadow polygons exist | PASS - 60 features |
| all shadow polygons valid | PASS |
| no NaN / infinite coordinates | PASS |
| areas and perimeters plausible (isoperimetric bound) | PASS |
| shadow azimuth is opposite the solar azimuth | PASS |
| shadow length matches H/tan(E) for 20x30x50 m building | PASS |
| shadow area matches the swept-rectangle closed form | PASS |
| no height lacks a documented source | PASS |
| every building retains a source URL and reference | PASS |
| ground elevation present but not invented | PASS |
| study extent within the 200-300 m target | PASS - 270.7 m x 310.5 m |
| study-area selection is documented | PASS |

## Dataset summary

| Quantity | Value |
| --- | --- |
| Study area | UB City, Bengaluru, Karnataka, India |
| Bounding box (W, S, E, N) | [77.5943, 12.9701, 77.5968, 12.9729] |
| Extent | 270.7 m x 310.5 m |
| Study area | 84,119.1 m^2 |
| Buildings (OSM ways) | 10 |
| Shadow-casting buildings | 5 |
| Buildings with unresolved height | 5 |
| Frames | 25 (12 with sunlight, 13 at night) |
| Shadow features published | 60 |
| Peak shadow area frame | 07:00 (46,241 m^2, 54.97% of study area) |
| Dataset SHA-256 | `eb61e0010e82911bd223b9ebaff2a5fb4a811b1db68d4f43255ecc6173b0375c` |

## Accuracy statement

Three independent accuracy domains are kept separate and none of them is
claimed to be better than the underlying source data:

1. **Solar-position accuracy.** Computed with pvlib's implementation of the
   NREL SPA (Reda & Andreas, 2003/2004) including atmospheric refraction.
   This is the strongest link in the chain: solar position for a known instant
   is accurate to well under one arcminute, i.e. far better than the 0.01 deg
   rounding used in the published files. Sunrise/sunset are bracketed on a
   2-minute scan and are therefore accurate to about +/-1 minute.
2. **Building-data positional accuracy.** Footprints are OpenStreetMap
   volunteer-surveyed geometry. Typical OSM building positional error in an
   Indian urban core is on the order of 1-5 m, and is not uniform. No
   survey-grade positional accuracy is claimed.
3. **Building-height accuracy.** Heights are `height` tags on OpenStreetMap.
   Their provenance varies (some operator-supplied, some community-estimated),
   which is why they are reported as `medium` confidence rather than `high`.
   A 1 m error in a 60 m building changes shadow length by roughly 1.7% at a
   30 deg solar elevation.

The shadow result is only as accurate as the weaker of these inputs. A shadow
computed from a 3 m positional error in a footprint and a 1 m height error
inherits both; the geometry engine itself contributes only floating-point error.

The ground is modelled as a flat plane at z = 0. Real terrain relief across a
270 m x 310 m site in central Bengaluru is small, but it is not zero, and no
DEM is integrated (see ASSUMPTIONS.md).
