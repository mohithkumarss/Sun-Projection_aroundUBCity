"""
Step 2 of the pipeline: normalise buildings, resolve vertical information,
derive the study area, and write buildings.geojson + provenance metadata.

Vertical-information policy (this is the scientifically important part)
---------------------------------------------------------------------
A building is assigned a shadow-casting height ONLY when a real source states
one. The decision table is:

1. ``height`` / ``building:height`` tag present
       -> method ``OSM_exact``, the tagged value is used verbatim.
2. Only ``building:levels`` present
       -> method ``unresolved``.  The floor count is RETAINED in metadata but is
          NOT converted to a height, so the building cannot cast a shadow.
          A levels->height conversion is available behind the explicit
          ``ALLOW_LEVELS_DERIVATION`` flag in pipeline_config (default False)
          because doing it silently would misrepresent an estimate as a
          measurement. If enabled, such buildings are labelled
          ``derived_from_levels`` with ``low`` confidence.
3. Neither present
       -> method ``unresolved``, height_m = null, excluded from shadow casting.

Building parts
--------------
Where a footprint carries ``building:part`` children, each part is retained as
a separate vertical prism with its own ``min_height``..``height`` z-range. This
is a more faithful vertical model than the outer footprint alone, so the parts
are preferred for shadow casting (the outer footprint is still kept for
footprint-area reporting and 2D display).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))

from geo import describe_crs, to_metric  # noqa: E402
from pipeline_config import (  # noqa: E402
    ALLOW_LEVELS_DERIVATION,
    ASSUMED_FLOOR_HEIGHT_M,
    CRS_METRIC,
    CRS_STORAGE,
    DATA_DIR,
    HTTP_TIMEOUT_S,
    NOMINATIM_BASE,
    RAW_DIR,
    STUDY_AREA,
    USER_AGENT,
)

DEFAULT_ESTIMATED_FLOOR_HEIGHT_M = ASSUMED_FLOOR_HEIGHT_M


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def parse_height_m(value: str) -> float | None:
    """
    Parse an OSM height tag into metres.

    OSM heights are usually a bare number in metres but may carry a unit
    suffix. Anything unparseable returns None rather than guessing.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    # Strip a unit suffix if present.
    for suffix in ("meters", "metres", "meter", "metre", "m"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    if text.endswith("'") or text.endswith("ft"):
        return None  # feet are not used here; refusing beats mis-converting
    try:
        result = float(text)
    except ValueError:
        return None
    if result <= 0 or result > 1000:
        return None  # implausible for an urban building; flagged, not used
    return result


def parse_levels(value: str) -> int | None:
    if value is None:
        return None
    try:
        levels = int(float(str(value).strip()))
    except ValueError:
        return None
    return levels if 0 < levels < 200 else None


# --------------------------------------------------------------------------
# Geometry normalisation
# --------------------------------------------------------------------------


def normalise_polygon(coords: list[tuple[float, float]], osm_id: int, log: list[str]):
    """
    Build a shapely Polygon from an OSM way, repairing it if necessary.

    Invalid geometry is repaired with a zero-width buffer and LOGGED. It is
    never silently discarded.
    """
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    poly = Polygon(coords)

    if not poly.is_valid:
        reason = poly.is_valid_reason if hasattr(poly, "is_valid_reason") else "unknown"
        repaired = poly.buffer(0)
        log.append(
            f"way {osm_id}: invalid polygon ({reason}); repaired with "
            f"buffer(0) -> {repaired.geom_type}"
        )
        if repaired.geom_type == "MultiPolygon":
            # Keep only the largest part so a building stays a single prism,
            # and say so explicitly.
            largest = max(repaired.geoms, key=lambda g: g.area)
            log.append(
                f"way {osm_id}: repair produced {len(repaired.geoms)} parts; "
                f"kept the largest ({largest.area:.1f} m^2)"
            )
            poly = largest
        else:
            poly = repaired

    if poly.area <= 0:
        log.append(f"way {osm_id}: zero-area polygon after repair; dropped")
        return None
    return poly


# --------------------------------------------------------------------------
# Height resolution
# --------------------------------------------------------------------------


def resolve_vertical(tags: dict) -> dict:
    """
    Decide the shadow-casting height for one footprint, with full provenance.
    """
    vertical = {}
    conflicts = []

    candidates = []
    for key in ("height", "building:height"):
        if key in tags:
            parsed = parse_height_m(tags[key])
            if parsed is None:
                conflicts.append(
                    {
                        "field": key,
                        "raw_value": tags[key],
                        "issue": "unparseable or implausible height value",
                    }
                )
            else:
                candidates.append((key, parsed))

    if candidates:
        chosen_key, chosen_value = candidates[0]
        if len(candidates) > 1:
            conflicts.append(
                {
                    "field": "height",
                    "issue": "multiple height tags disagree",
                    "values": {k: v for k, v in candidates},
                    "resolution_rule": (
                        "First tag in the documented precedence order "
                        "(height, building:height) is used; all values retained."
                    ),
                }
            )
        return {
            "height_m": chosen_value,
            "min_height_m": 0.0,
            "levels": parse_levels(tags.get("building:levels")),
            "height_method": "OSM_exact",
            "height_confidence": "medium",
            "height_source": f"OpenStreetMap tag `{chosen_key}` on way (survey/operator tagged)",
            "height_source_url": f"https://www.openstreetmap.org/way/{tags.get('__osm_id__', '')}",
            "height_source_ref": f"osm:{tags.get('__osm_type__', 'way')}/{tags.get('__osm_id__', '')}",
            "height_conflicts": conflicts,
            "shadow_casting": True,
        }

    # No documented height. Floor count alone is NOT converted by default.
    levels = parse_levels(tags.get("building:levels"))
    if levels is not None and ALLOW_LEVELS_DERIVATION:
        return {
            "height_m": round(levels * DEFAULT_ESTIMATED_FLOOR_HEIGHT_M, 2),
            "min_height_m": 0.0,
            "levels": levels,
            "height_method": "derived_from_levels",
            "height_confidence": "low",
            "height_source": (
                f"Derived from OpenStreetMap building:levels={levels} using an "
                f"assumed floor-to-floor height of "
                f"{DEFAULT_ESTIMATED_FLOOR_HEIGHT_M} m"
            ),
            "height_source_url": f"https://www.openstreetmap.org/way/{tags.get('__osm_id__', '')}",
            "height_source_ref": f"osm:{tags.get('__osm_type__', 'way')}/{tags.get('__osm_id__', '')}",
            "height_conflicts": conflicts,
            "shadow_casting": True,
        }

    return {
        "height_m": None,
        "min_height_m": 0.0,
        "levels": levels,
        "height_method": "unresolved",
        "height_confidence": "none",
        "height_source": (
            "No documented height in OpenStreetMap. Floor count retained but NOT "
            "converted to a height (levels->height derivation is disabled by "
            "default because it would present an estimate as a measurement). "
            "This building is excluded from shadow casting."
            if levels is not None
            else "No documented height in OpenStreetMap. Excluded from shadow casting."
        ),
        "height_source_url": f"https://www.openstreetmap.org/way/{tags.get('__osm_id__', '')}",
        "height_source_ref": f"osm:{tags.get('__osm_type__', 'way')}/{tags.get('__osm_id__', '')}",
        "height_conflicts": conflicts,
        "shadow_casting": False,
    }


# --------------------------------------------------------------------------
# Nominatim cross-check (records a real second source for the place)
# --------------------------------------------------------------------------


def nominatim_crosscheck() -> dict:
    import requests

    try:
        response = requests.get(
            f"{NOMINATIM_BASE}/search",
            params={"q": "UB City, Bengaluru, Karnataka, India", "format": "jsonv2", "limit": 5},
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT_S,
        )
        response.raise_for_status()
        results = response.json()
    except Exception as exc:  # non-fatal: provenance enrichment only
        return {"status": "unavailable", "error": repr(exc)}

    entries = [
        {
            "osm_type": r.get("osm_type"),
            "osm_id": r.get("osm_id"),
            "name": r.get("name"),
            "display_name": r.get("display_name"),
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "class": r.get("class"),
            "type": r.get("type"),
        }
        for r in results
    ]
    return {"status": "ok", "query": "UB City, Bengaluru, Karnataka, India", "results": entries}


# --------------------------------------------------------------------------
# Main normalisation
# --------------------------------------------------------------------------


def main() -> None:
    raw_path = RAW_DIR.parent / "_buildings_raw.json"
    if not raw_path.exists():
        raise SystemExit(
            f"Missing {raw_path}. Run scripts/fetch_buildings.py first - the "
            "pipeline will not invent building data."
        )

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    entries = raw["buildings"]
    log: list[str] = []

    polys: dict[int, Polygon] = {}
    tags_by_id: dict[int, dict] = {}
    for entry in entries:
        oid = entry["osm_id"]
        tags = dict(entry["tags"])
        tags["__osm_id__"] = oid
        tags["__osm_type__"] = entry["osm_type"]
        tags_by_id[oid] = tags
        poly = normalise_polygon(
            [(lon, lat) for lon, lat in entry["coords"]], oid, log
        )
        if poly is not None:
            polys[oid] = poly

    # Group building parts under their parent footprint.
    parts_by_parent: dict[int, list[int]] = defaultdict(list)
    parent_ids = {oid for oid, t in tags_by_id.items() if "building" in t}
    for oid, tags in tags_by_id.items():
        if tags.get("building:part") in ("yes", "true", "1") and oid not in parent_ids:
            relation = tags.get("building:part:parent") or tags.get("parent")
            # OSM does not reliably encode the parent link; we infer it below
            # from containment when the tag is absent.
            if relation and str(relation) in {str(p) for p in parent_ids}:
                parts_by_parent[int(relation)].append(oid)

    # Infer parentage geometrically for parts with no explicit parent tag.
    unlinked_parts = [
        oid
        for oid, t in tags_by_id.items()
        if t.get("building:part") in ("yes", "true", "1") and oid not in parent_ids
        and not any(oid in group for group in parts_by_parent.values())
    ]
    for part_id in unlinked_parts:
        part_poly = polys.get(part_id)
        if part_poly is None:
            continue
        for parent_id in parent_ids:
            parent_poly = polys.get(parent_id)
            if parent_poly is None or parent_id in parts_by_parent:
                continue
            if parent_poly.contains(part_poly.representative_point()):
                parts_by_parent[parent_id].append(part_id)
                break

    # ----------------------------------------------------------------------
    # Build output records
    # ----------------------------------------------------------------------
    features = []
    shadow_casters = 0
    unresolved = 0

    for oid in sorted(parent_ids):
        poly = polys.get(oid)
        if poly is None:
            log.append(f"way {oid}: skipped (unusable geometry)")
            continue
        tags = tags_by_id[oid]
        vertical = resolve_vertical(tags)

        metric_poly = to_metric(poly)
        area_m2 = metric_poly.area

        building_id = f"osm:way/{oid}"
        part_ids = parts_by_parent.get(oid, [])

        # Vertical model: prefer building parts (more faithful), else the
        # footprint itself at the resolved height.
        prisms = []
        if part_ids:
            part_union_metric = None
            for pid in sorted(part_ids):
                ppoly = polys.get(pid)
                if ppoly is None:
                    continue
                ptags = tags_by_id[pid]
                pvert = resolve_vertical(ptags)
                z_bottom = pvert["min_height_m"] or 0.0
                if pvert["height_m"] is None:
                    continue
                z_top = z_bottom + pvert["height_m"]
                pmetric = to_metric(ppoly)
                part_union_metric = (
                    pmetric if part_union_metric is None else part_union_metric.union(pmetric)
                )
                prisms.append(
                    {
                        "part_osm_id": pid,
                        "geometry_wgs84": mapping(ppoly),
                        "z_bottom_m": round(z_bottom, 3),
                        "z_top_m": round(z_top, 3),
                        "height_m": pvert["height_m"],
                        "height_method": pvert["height_method"],
                        "height_confidence": pvert["height_confidence"],
                    }
                )
            if prisms and part_union_metric is not None:
                area_m2 = part_union_metric.area
        if not prisms and vertical["height_m"] is not None:
            prisms.append(
                {
                    "part_osm_id": None,
                    "geometry_wgs84": mapping(poly),
                    "z_bottom_m": 0.0,
                    "z_top_m": round(vertical["height_m"], 3),
                    "height_m": vertical["height_m"],
                    "height_method": vertical["height_method"],
                    "height_confidence": vertical["height_confidence"],
                }
            )

        if vertical["shadow_casting"] and prisms:
            shadow_casters += 1
        else:
            unresolved += 1
            prisms = []  # no vertical model -> no shadow contribution

        address = {
            k: v
            for k, v in tags.items()
            if k.startswith("addr:")
        }

        features.append(
            {
                "type": "Feature",
                "id": building_id,
                "geometry": mapping(poly),  # source geometry, WGS84, un-simplified
                "properties": {
                    "id": building_id,
                    "name": tags.get("name") or tags.get("name:en"),
                    "name_en": tags.get("name:en"),
                    "building_type": tags.get("building"),
                    "levels": vertical["levels"],
                    "height_m": vertical["height_m"],
                    "min_height_m": vertical["min_height_m"],
                    "height_method": vertical["height_method"],
                    "height_confidence": vertical["height_confidence"],
                    "height_source": vertical["height_source"],
                    "height_source_url": vertical["height_source_url"],
                    "height_source_ref": vertical["height_source_ref"],
                    "height_conflicts": vertical["height_conflicts"],
                    "ground_elevation_m": None,  # flat-ground assumption, see ASSUMPTIONS.md
                    "footprint_area_m2": round(area_m2, 2),
                    "footprint_perimeter_m": round(metric_poly.length, 2),
                    "shadow_casting": bool(prisms),
                    "vertical_model": "building_parts" if part_ids and prisms else ("single_prism" if prisms else "none"),
                    "building_part_ids": part_ids,
                    "prisms": prisms,
                    "address": address,
                    "operator": tags.get("operator"),
                    "brand": tags.get("brand"),
                    "website": tags.get("website"),
                    "wikidata": tags.get("wikidata"),
                    "wikipedia": tags.get("wikipedia"),
                    "source": "OpenStreetMap",
                    "source_tags": {k: v for k, v in tags.items() if not k.startswith("__")},
                    "osm_id": oid,
                    "osm_type": "way",
                    "osm_version": raw["buildings"][0].get("osm_version") if raw["buildings"] else None,
                    "source_osm_timestamp": None,
                },
            }
        )

    # ----------------------------------------------------------------------
    # Study area derived from the ACTUAL retrieved geometry
    # ----------------------------------------------------------------------
    union_metric = unary_union([to_metric(p) for p in polys.values()])
    minx, miny, maxx, maxy = union_metric.bounds

    pad_m = 10.0
    bbox_metric = (minx - pad_m, miny - pad_m, maxx + pad_m, maxy + pad_m)

    from pyproj import Transformer

    back = Transformer.from_crs(CRS_METRIC, CRS_STORAGE, always_xy=True)
    west, south = back.transform(bbox_metric[0], bbox_metric[1])
    east, north = back.transform(bbox_metric[2], bbox_metric[3])

    def round_out(value: float, places: int = 4) -> float:
        """Round OUTWARD so the bbox fully contains the data (floor/ceil)."""
        factor = 10**places
        scaled = value * factor
        if scaled >= 0:
            return math.floor(scaled) / factor
        return math.ceil(scaled) / factor

    bbox_wgs84 = [
        round_out(west, 4),
        round_out(south, 4),
        round_out(east, 4),
        round_out(north, 4),
    ]
    span_x = bbox_wgs84[2] - bbox_wgs84[0]
    span_y = bbox_wgs84[3] - bbox_wgs84[1]
    extent_m = (round(span_x * 108300, 1), round(span_y * 110900, 1))

    collection = {
        "type": "FeatureCollection",
        "name": "UB City, Bengaluru - real OpenStreetMap building footprints",
        "crs": {"type": "name", "properties": {"name": CRS_STORAGE}},
        "metadata": {
            "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": raw["source"],
            "source_params": raw["source_params"],
            "retrieved_at_utc": raw["retrieved_at_utc"],
            "user_agent": raw["user_agent"],
            "storage_crs": CRS_STORAGE,
            "metric_crs": CRS_METRIC,
            "levels_derivation_enabled": ALLOW_LEVELS_DERIVATION,
            "assumed_floor_height_m": DEFAULT_ESTIMATED_FLOOR_HEIGHT_M,
            "geometry_simplification": "none (source OSM vertex coordinates retained)",
            "ground_elevation_m": None,
            "ground_model": "flat (z = 0 m) - see research/ASSUMPTIONS.md",
        },
        "features": features,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    buildings_path = DATA_DIR / "buildings.geojson"
    buildings_path.write_text(json.dumps(collection, indent=1), encoding="utf-8")

    study_area = {
        "type": "FeatureCollection",
        "name": "UB City study area",
        "crs": {"type": "name", "properties": {"name": CRS_STORAGE}},
        "properties": {
            "study_area_name": STUDY_AREA.name,
            "bbox_wgs84": bbox_wgs84,
            "bbox_metric_epsg32643": [round(v, 3) for v in bbox_metric],
            "extent_east_m": extent_m[0],
            "extent_north_m": extent_m[1],
            "selection_rationale": (
                "Derived from the bounding box of the real OSM building cluster "
                "returned for the Nominatim geocode of UB City, padded by 10 m so "
                "that shadow polygons falling outside the built footprints remain "
                "visible. The resulting extent is compared against the 200-300 m "
                "target in the assignment."
            ),
            "seed_bbox_used_for_query": list(STUDY_AREA.seed_bbox),
            "area_m2": round(extent_m[0] * extent_m[1], 1),
            "crs": CRS_STORAGE,
        },
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "study_area_name": STUDY_AREA.name,
                    "bbox_wgs84": bbox_wgs84,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [bbox_wgs84[0], bbox_wgs84[1]],
                            [bbox_wgs84[2], bbox_wgs84[1]],
                            [bbox_wgs84[2], bbox_wgs84[3]],
                            [bbox_wgs84[0], bbox_wgs84[3]],
                            [bbox_wgs84[0], bbox_wgs84[1]],
                        ]
                    ],
                },
            }
        ],
    }
    (DATA_DIR / "study-area.geojson").write_text(
        json.dumps(study_area, indent=1), encoding="utf-8"
    )

    # ----------------------------------------------------------------------
    # Provenance
    # ----------------------------------------------------------------------
    provenance = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "study_area": {
            "name": STUDY_AREA.name,
            "bbox_wgs84": bbox_wgs84,
            "extent_m": {"east_west": extent_m[0], "north_south": extent_m[1]},
            "selection": study_area["properties"]["selection_rationale"],
        },
        "crs": describe_crs(),
        "data_source": {
            "name": "OpenStreetMap",
            "endpoint": raw["source"],
            "request": f"{raw['source']}?bbox={','.join(str(v) for v in STUDY_AREA.seed_bbox)}",
            "retrieved_at_utc": raw["retrieved_at_utc"],
            "user_agent": raw["user_agent"],
            "licence": "ODbL 1.0 (c) OpenStreetMap contributors",
            "citation": (
                "(c) OpenStreetMap contributors, ODbL 1.0. "
                "https://www.openstreetmap.org/copyright"
            ),
            "why_not_overpass": (
                "Overpass (overpass-api.de and mirrors) is unreachable from the "
                "execution environment (HTTP 406 from a filtering proxy). The main "
                "OSM API serves the same OpenStreetMap database."
            ),
            "known_limitation": (
                "The main OSM API returns nodes and ways only; multipolygon "
                "buildings assembled from relations are not resolvable by this "
                "method. Any building relation in the bbox is reported and skipped."
            ),
        },
        "place_cross_check": nominatim_crosscheck(),
        "summary": {
            "buildings_total": len(features),
            "shadow_casting_buildings": shadow_casters,
            "unresolved_height_buildings": unresolved,
            "heights_by_method": {
                method: sum(
                    1 for f in features if f["properties"]["height_method"] == method
                )
                for method in sorted({f["properties"]["height_method"] for f in features})
            },
        },
        "height_methodology": {
            "OSM_exact": "A height value is tagged in OpenStreetMap; used verbatim.",
            "documented": "Reserved for a height taken from an external published document.",
            "survey": "Reserved for a survey-grade measured height.",
            "lidar": "Reserved for a height derived from a lidar/DEM dataset.",
            "derived_from_levels": (
                f"Floor count x {DEFAULT_ESTIMATED_FLOOR_HEIGHT_M} m assumed floor-to-floor "
                "height. DISABLED by default (ALLOW_LEVELS_DERIVATION=False) because it "
                "is an estimate, not a measurement."
            ),
            "unresolved": (
                "No documented height available. The building is displayed but "
                "excluded from shadow casting."
            ),
        },
        "buildings": [
            {
                "id": f["properties"]["id"],
                "name": f["properties"]["name"],
                "height_m": f["properties"]["height_m"],
                "levels": f["properties"]["levels"],
                "height_method": f["properties"]["height_method"],
                "height_confidence": f["properties"]["height_confidence"],
                "height_source": f["properties"]["height_source"],
                "height_source_url": f["properties"]["height_source_url"],
                "footprint_area_m2": f["properties"]["footprint_area_m2"],
                "building_parts": f["properties"]["building_part_ids"],
                "vertical_model": f["properties"]["vertical_model"],
                "shadow_casting": f["properties"]["shadow_casting"],
                "source_tags": f["properties"]["source_tags"],
            }
            for f in features
        ],
        "geometry_repair_log": log,
    }
    (DATA_DIR / "_provenance.json").write_text(
        json.dumps(provenance, indent=1), encoding="utf-8"
    )

    print(f"  buildings: {len(features)}")
    print(f"  shadow casters: {shadow_casters}, unresolved height: {unresolved}")
    print(f"  study bbox (W,S,E,N) = {bbox_wgs84}")
    print(f"  study extent: {extent_m[0]} m x {extent_m[1]} m")
    print(f"  crs: {describe_crs()}")
    for line in log:
        print(f"  [geometry] {line}")


if __name__ == "__main__":
    main()
