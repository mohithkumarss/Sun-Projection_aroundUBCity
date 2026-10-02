"""
Step 4: generate the 25 hourly shadow frames.

For every frame this script
  * reads the pre-computed solar position (scripts/calculate_solar.py),
  * projects each building prism onto the ground plane in EPSG:32643,
  * runs the building-to-building occlusion test,
  * measures area / perimeter / maximum length / dominant direction,
  * writes per-frame GeoJSON (WGS84) and a consolidated simulation.json,
  * writes the per-frame analysis used by the research panel.

All expensive geometry happens HERE, once, in Python. The browser only ever
selects and renders a pre-computed frame - it never recomputes a shadow.

Output layout
-------------
    public/data/simulation.json          consolidated index + analysis
    public/data/shadows/<frame>.geojson  one FeatureCollection per timestamp
    public/data/shadow-frames.json       per-frame shadow features (WGS84)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))

from geo import coords_are_finite, to_metric, to_wgs84  # noqa: E402
from pipeline_config import (  # noqa: E402
    DATA_DIR,
    MAX_SHADOW_LENGTH_M,
    MIN_SHADOW_ELEVATION_DEG,
    SHADOW_DIR,
    SIMULATION_DATE,
    TIMEZONE,
)
from shadow_geometry import (  # noqa: E402
    building_shadow_polygon,
    describe_azimuth,
    dominant_direction,
    occlusion_analysis,
    shadow_length_for_height,
)

# Fix the value used by the geometry module from the single config source of
# truth. Import-time wiring keeps shadow_geometry free of a config dependency
# cycle while guaranteeing the two agree.
import shadow_geometry  # noqa: E402

shadow_geometry.MIN_SHADOW_ELEVATION_DEG = MIN_SHADOW_ELEVATION_DEG
shadow_geometry.MAX_SHADOW_LENGTH_M = MAX_SHADOW_LENGTH_M


def frame_slug(record: dict) -> str:
    """Filesystem-safe ISO-like slug, e.g. 2026-10-01T06-00+05-30."""
    stamp = record["timestamp"]
    return stamp.replace(":", "-")


def load_inputs():
    buildings_path = DATA_DIR / "buildings.geojson"
    solar_path = DATA_DIR / "_solar.json"
    study_path = DATA_DIR / "study-area.geojson"
    for path in (buildings_path, solar_path, study_path):
        if not path.exists():
            raise SystemExit(
                f"Missing {path}. The pipeline will not fabricate inputs. Run "
                "fetch_buildings.py, prepare_buildings.py and calculate_solar.py first."
            )
    return (
        json.loads(buildings_path.read_text(encoding="utf-8")),
        json.loads(solar_path.read_text(encoding="utf-8")),
        json.loads(study_path.read_text(encoding="utf-8")),
    )


def build_prism_index(buildings: dict) -> tuple[dict, list[dict]]:
    """
    Convert the published buildings into metric prisms grouped by building id.
    """
    prisms: dict[str, list[dict]] = {}
    catalogue: list[dict] = []

    for feature in buildings["features"]:
        props = feature["properties"]
        building_id = props["id"]

        metric_footprint = to_metric(shape(feature["geometry"]))
        catalogue.append(
            {
                "id": building_id,
                "name": props.get("name"),
                "height_m": props.get("height_m"),
                "levels": props.get("levels"),
                "height_method": props.get("height_method"),
                "height_confidence": props.get("height_confidence"),
                "height_source": props.get("height_source"),
                "height_source_url": props.get("height_source_url"),
                "footprint_area_m2": props.get("footprint_area_m2"),
                "shadow_casting": props.get("shadow_casting"),
                "vertical_model": props.get("vertical_model"),
                "ground_elevation_m": props.get("ground_elevation_m"),
                "prism_count": len(props.get("prisms") or []),
            }
        )

        if not props.get("shadow_casting"):
            continue

        for prism in props.get("prisms") or []:
            part_geom = shape(prism["geometry_wgs84"])
            prisms.setdefault(building_id, []).append(
                {
                    "footprint_metric": metric_footprint
                    if prism.get("part_osm_id") is None
                    else to_metric(part_geom),
                    "z_bottom_m": prism["z_bottom_m"],
                    "z_top_m": prism["z_top_m"],
                    "height_m": prism["height_m"],
                    "height_method": prism["height_method"],
                }
            )

    return prisms, catalogue


def main() -> None:
    buildings, solar, study = load_inputs()
    frames = solar["frames"]
    prisms, catalogue = build_prism_index(buildings)

    study_bbox = study["properties"]["bbox_wgs84"]
    study_metric = to_metric(
        Polygon(
            [
                (study_bbox[0], study_bbox[1]),
                (study_bbox[2], study_bbox[1]),
                (study_bbox[2], study_bbox[3]),
                (study_bbox[0], study_bbox[3]),
            ]
        )
    )
    study_area_m2 = study_metric.area

    print(
        f"[generate_shadows] {len(frames)} frames, "
        f"{sum(len(v) for v in prisms.values())} prisms across "
        f"{len(prisms)} shadow-casting buildings"
    )
    print(f"  study area: {study_area_m2:,.0f} m^2")

    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    for stale in SHADOW_DIR.glob("*.geojson"):
        stale.unlink()

    frame_index = []
    per_building_stats: dict[str, dict] = {}
    all_features: dict[str, list] = {}
    warnings: list[str] = []

    for record in frames:
        slug = frame_slug(record)
        elevation = record["solar_elevation_deg"]
        azimuth = record["solar_azimuth_deg"]
        above = record["sun_above_horizon"]
        emits = above and elevation >= MIN_SHADOW_ELEVATION_DEG

        features: list[dict] = []
        frame_total_area = 0.0
        frame_total_area_clipped = 0.0
        frame_max_length = 0.0
        any_truncated = False

        if emits:
            for building_id, building_prisms in prisms.items():
                parts = []
                info_rows = []
                for prism in building_prisms:
                    poly, info = building_shadow_polygon(
                        prism["footprint_metric"],
                        prism["z_bottom_m"],
                        prism["z_top_m"],
                        azimuth,
                        elevation,
                        MAX_SHADOW_LENGTH_M,
                    )
                    if poly.is_empty:
                        continue
                    if not coords_are_finite(poly):
                        warnings.append(
                            f"{slug} {building_id}: non-finite shadow coordinates discarded"
                        )
                        continue
                    if not poly.is_valid:
                        warnings.append(
                            f"{slug} {building_id}: invalid shadow polygon repaired"
                        )
                        poly = poly.buffer(0)
                    parts.append(poly)
                    info_rows.append(info)
                    if info["truncated"]:
                        any_truncated = True

                if not parts:
                    continue

                shadow_metric = unary_union(parts)
                shadow_wgs84 = to_wgs84(shadow_metric)
                if not shadow_wgs84.is_valid:
                    shadow_wgs84 = shadow_wgs84.buffer(0)

                area_m2 = shadow_metric.area
                area_in_study = shadow_metric.intersection(study_metric).area
                # Rounding happens HERE, at the serialisation boundary. The
                # geometry engine keeps full double precision.
                max_length = round(max(r["shadow_length_m"] for r in info_rows), 3)
                natural_length = round(
                    max(r["shadow_length_natural_m"] for r in info_rows), 3
                )
                direction = dominant_direction(shadow_metric)

                stats = per_building_stats.setdefault(
                    building_id,
                    {
                        "building_id": building_id,
                        "frames_with_shadow": 0,
                        "max_shadow_length_m": 0.0,
                        "max_shadow_area_m2": 0.0,
                        "total_shadow_area_m2": 0.0,
                        "areas_by_frame": {},
                        "lengths_by_frame": {},
                        "directions_by_frame": {},
                    },
                )
                stats["frames_with_shadow"] += 1
                stats["max_shadow_length_m"] = max(stats["max_shadow_length_m"], max_length)
                stats["max_shadow_area_m2"] = max(stats["max_shadow_area_m2"], area_m2)
                stats["total_shadow_area_m2"] += area_m2
                stats["areas_by_frame"][record["local_time"]] = round(area_m2, 2)
                stats["lengths_by_frame"][record["local_time"]] = round(max_length, 2)
                stats["directions_by_frame"][record["local_time"]] = direction["azimuth_deg"] if direction else None

                features.append(
                    {
                        "type": "Feature",
                        "id": f"{building_id}@{record['local_time']}",
                        "geometry": mapping(shadow_wgs84),
                        "properties": {
                            "building_id": building_id,
                            "timestamp": record["timestamp"],
                            "local_time": record["local_time"],
                            "date_local": record["date_local"],
                            "timezone": TIMEZONE,
                            "solar_azimuth_deg": azimuth,
                            "solar_elevation_deg": elevation,
                            "solar_zenith_deg": record["solar_zenith_deg"],
                            "sun_above_horizon": above,
                            "shadow_azimuth_deg": round((azimuth + 180.0) % 360.0, 6),
                            "shadow_direction": describe_azimuth((azimuth + 180.0) % 360.0),
                            "height_m": building_prisms[0]["height_m"],
                            "height_method": building_prisms[0]["height_method"],
                            "shadow_area_m2": round(area_m2, 3),
                            "shadow_area_in_study_area_m2": round(area_in_study, 3),
                            "shadow_perimeter_m": round(shadow_metric.length, 3),
                            "max_shadow_length_m": round(max_length, 3),
                            "max_shadow_length_natural_m": round(natural_length, 3),
                            "truncated_at_max_length": bool(
                                any(r["truncated"] for r in info_rows)
                            ),
                            "dominant_direction": direction,
                            "prism_count": len(parts),
                            "crs_calculated_in": "EPSG:32643",
                            "crs_exported_in": "EPSG:4326",
                        },
                    }
                )
                frame_total_area += area_m2
                frame_total_area_clipped += area_in_study
                frame_max_length = max(frame_max_length, max_length)

            occlusion = occlusion_analysis(prisms, azimuth, elevation)
        else:
            occlusion = {"per_building": {}, "method": "not computed (sun below threshold)"}

        payload = {
            "type": "FeatureCollection",
            "name": f"UB City shadow projection {record['timestamp']}",
            "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
            "metadata": {
                "timestamp": record["timestamp"],
                "local_time": record["local_time"],
                "date_local": record["date_local"],
                "timezone": TIMEZONE,
                "solar_azimuth_deg": azimuth,
                "solar_elevation_deg": elevation,
                "solar_zenith_deg": record["solar_zenith_deg"],
                "sun_above_horizon": above,
                "shadow_emitted": emits,
                "shadow_azimuth_deg": round((azimuth + 180.0) % 360.0, 6),
                "active_building_shadows": len(features),
                "total_shadow_area_m2": round(frame_total_area, 3),
                "total_shadow_area_in_study_area_m2": round(frame_total_area_clipped, 3),
                "max_shadow_length_m": round(frame_max_length, 3),
                "study_area_m2": round(study_area_m2, 2),
                "shadow_coverage_percent": round(
                    100.0 * frame_total_area_clipped / study_area_m2, 4
                ),
                "truncated": any_truncated,
                "max_shadow_length_m_limit": MAX_SHADOW_LENGTH_M,
                "min_shadow_elevation_deg": MIN_SHADOW_ELEVATION_DEG,
                "occlusion": occlusion,
                "computed_in_crs": "EPSG:32643",
                "exported_in_crs": "EPSG:4326",
            },
            "features": features,
        }

        frame_path = SHADOW_DIR / f"{slug}.geojson"
        frame_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        all_features[slug] = features

        frame_index.append(
            {
                "index": len(frame_index),
                "slug": slug,
                "timestamp": record["timestamp"],
                "timestamp_utc": record["timestamp_utc"],
                "local_time": record["local_time"],
                "date_local": record["date_local"],
                "timezone": TIMEZONE,
                "solar_azimuth_deg": azimuth,
                "solar_elevation_deg": elevation,
                "solar_zenith_deg": record["solar_zenith_deg"],
                "apparent_elevation_deg": record["apparent_elevation_deg"],
                "sun_above_horizon": above,
                "shadow_emitted": emits,
                "shadow_azimuth_deg": round((azimuth + 180.0) % 360.0, 6),
                "shadow_direction": describe_azimuth((azimuth + 180.0) % 360.0),
                "active_building_shadows": len(features),
                "total_shadow_area_m2": round(frame_total_area, 3),
                "total_shadow_area_in_study_area_m2": round(frame_total_area_clipped, 3),
                "max_shadow_length_m": round(frame_max_length, 3),
                "study_area_m2": round(study_area_m2, 2),
                "shadow_coverage_percent": round(
                    100.0 * frame_total_area_clipped / study_area_m2, 4
                ),
                "truncated": any_truncated,
                "file": f"shadows/{slug}.geojson",
            }
        )

        print(
            f"  {record['local_time']}  elev {elevation:7.3f}  "
            f"shadows {len(features):2d}  area {frame_total_area:12,.1f} m^2  "
            f"maxL {frame_max_length:8.1f} m  "
            f"cov {100.0 * frame_total_area_clipped / study_area_m2:6.3f}%"
            + ("  [TRUNCATED]" if any_truncated else "")
        )

    # ------------------------------------------------------------------
    # Consolidated simulation index
    # ------------------------------------------------------------------
    daylight = [f for f in frame_index if f["shadow_emitted"]]
    simulation = {
        "metadata": {
            "study_area": study["properties"],
            "simulation_date": SIMULATION_DATE,
            "timezone": TIMEZONE,
            "frame_count": len(frame_index),
            "start_local": frame_index[0]["timestamp"],
            "end_local": frame_index[-1]["timestamp"],
            "crs_storage": "EPSG:4326",
            "crs_computation": "EPSG:32643",
            "solar_method": solar["metadata"],
            "max_shadow_length_m": MAX_SHADOW_LENGTH_M,
            "min_shadow_elevation_deg": MIN_SHADOW_ELEVATION_DEG,
            "ground_model": "flat plane z = 0 m",
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "shadow_model": (
                "Vertical prism extruded to ground; shadow = exact Minkowski sum of "
                "the footprint with the segment [z_bottom/tan(E), z_top/tan(E)] "
                "along the anti-solar horizontal direction."
            ),
            "warnings": warnings,
            "night_frames": [
                f["local_time"] for f in frame_index if not f["sun_above_horizon"]
            ],
        },
        "buildings": catalogue,
        "frames": frame_index,
        "analysis": {
            "study_area": {
                "area_m2": round(study_area_m2, 2),
                "max_total_shadow_area_m2": max(
                    (f["total_shadow_area_in_study_area_m2"] for f in frame_index),
                    default=0.0,
                ),
                "max_shadow_coverage_percent": max(
                    (f["shadow_coverage_percent"] for f in frame_index), default=0.0
                ),
                "coverage_by_frame": {
                    f["local_time"]: f["shadow_coverage_percent"] for f in frame_index
                },
                "total_area_by_frame": {
                    f["local_time"]: f["total_shadow_area_in_study_area_m2"]
                    for f in frame_index
                },
            },
            "per_building": sorted(
                per_building_stats.values(), key=lambda s: s["building_id"]
            ),
        },
    }

    digest = hashlib.sha256(
        json.dumps(simulation, sort_keys=True).encode("utf-8")
    ).hexdigest()
    simulation["metadata"]["simulation_sha256"] = digest

    (DATA_DIR / "simulation.json").write_text(
        json.dumps(simulation, indent=1), encoding="utf-8"
    )
    (DATA_DIR / "shadow-frames.json").write_text(
        json.dumps(all_features, indent=1), encoding="utf-8"
    )

    print(f"  wrote simulation.json (sha256 {digest[:16]}...)")
    print(f"  daylight frames: {len(daylight)}, night frames: {len(frame_index) - len(daylight)}")
    for warning in warnings:
        print(f"  [warn] {warning}")


if __name__ == "__main__":
    main()
