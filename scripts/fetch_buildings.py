"""
Step 1 of the pipeline: acquire REAL OpenStreetMap building data.

Source: the official OpenStreetMap API 6.0 "map" call.

    GET https://api.openstreetmap.org/api/0.6/map.json?bbox=W,S,E,N

Why not Overpass? Overpass (overpass-api.de and its mirrors) is unreachable
from the execution environment - it returns HTTP 406 from a filtering proxy.
The main OSM API serves the same underlying OpenStreetMap database and is
documented as the canonical method for small bounding-box extractions. This is
recorded in research/DATA_PROVENANCE.md.

This script NEVER fabricates data. If OSM cannot be reached, or returns no
buildings, it raises `DataAcquisitionError` and the pipeline stops.

Outputs
-------
public/data/_raw/osm_map_<west>_<south>_<east>_<north>.json
    The unmodified API response, retained for auditability.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_config import (  # noqa: E402
    HTTP_TIMEOUT_S,
    OSM_API_BASE,
    RAW_DIR,
    STUDY_AREA,
    USER_AGENT,
)

# Tags that carry vertical information, and the tags we retain for provenance.
VERTICAL_TAGS = (
    "height",
    "building:height",
    "min_height",
    "building:levels",
    "building:min_level",
    "roof:height",
    "roof:levels",
    "roof:shape",
    "building:part",
    "start_date",
)
PROVENANCE_TAGS = (
    "name",
    "name:en",
    "building",
    "building:levels",
    "height",
    "min_height",
    "addr:housenumber",
    "addr:street",
    "addr:city",
    "addr:postcode",
    "operator",
    "brand",
    "website",
    "wikidata",
    "wikipedia",
    "source",
    "building:levels:underground",
)


class DataAcquisitionError(RuntimeError):
    """Raised when real source data cannot be obtained. Never swallowed."""


def fetch_osm_map(bbox: tuple[float, float, float, float]) -> dict:
    """
    Download the raw OSM elements for a bounding box.

    Raises DataAcquisitionError on any transport error, non-200 status, or
    malformed payload. The raw response is written to disk unchanged.
    """
    west, south, east, north = bbox
    url = f"{OSM_API_BASE}/map.json"
    params = {
        "bbox": f"{west},{south},{east},{north}",
    }
    headers = {"User-Agent": USER_AGENT}

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"osm_map_{west}_{south}_{east}_{north}.json"

    try:
        response = requests.get(
            url, params=params, headers=headers, timeout=HTTP_TIMEOUT_S
        )
    except requests.RequestException as exc:  # pragma: no cover - network
        raise DataAcquisitionError(
            f"Could not reach the OpenStreetMap API at {url}.\n"
            f"  Requested bbox: {bbox}\n"
            f"  Underlying error: {exc!r}\n"
            "  This pipeline requires live OpenStreetMap data and will not "
            "substitute invented geometry."
        ) from exc

    if response.status_code != 200:
        raise DataAcquisitionError(
            f"OpenStreetMap API returned HTTP {response.status_code} for "
            f"bbox {bbox}.\n  Body: {response.text[:400]}\n"
            "  The request may exceed the API's area/element limits, or the "
            "endpoint may be unavailable."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise DataAcquisitionError(
            f"OpenStreetMap API returned a non-JSON body for bbox {bbox}. "
            f"First 200 bytes: {response.text[:200]!r}"
        ) from exc

    if "elements" not in payload or not isinstance(payload["elements"], list):
        raise DataAcquisitionError(
            "OpenStreetMap payload did not contain an 'elements' array. "
            f"Top-level keys: {sorted(payload.keys())}"
        )

    # Retain the unmodified response for provenance / reproducibility.
    raw_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"  saved raw OSM payload -> {raw_path.relative_to(RAW_DIR.parents[1])}")
    print(f"  elements: {len(payload['elements'])}")
    return payload


def extract_buildings(payload: dict) -> list[dict]:
    """
    Reduce an OSM payload to building-carrying ways with resolved geometry.

    The main OSM API returns nodes and ways but not relation members, so
    multipolygon buildings assembled from relations are out of scope for this
    extraction method. This is a documented limitation (see DATA_PROVENANCE.md)
    and is reported, not silently dropped.
    """
    nodes: dict[int, tuple[float, float]] = {
        element["id"]: (element["lon"], element["lat"])
        for element in payload["elements"]
        if element["type"] == "node" and "lon" in element and "lat" in element
    }

    buildings: list[dict] = []
    relations_with_buildings = 0

    for element in payload["elements"]:
        tags = element.get("tags") or {}

        if element["type"] == "relation" and "building" in tags:
            relations_with_buildings += 1
            continue

        if element["type"] != "way" or "building" not in tags:
            continue

        # Resolve the way's node references to coordinates. Nodes that fall
        # outside the requested bbox may be absent from the response; we record
        # that rather than inventing them.
        coords: list[tuple[float, float]] = []
        missing = 0
        for node_id in element.get("nodes", []):
            point = nodes.get(node_id)
            if point is None:
                missing += 1
            else:
                coords.append(point)

        if len(coords) < 3:
            continue
        if missing:
            print(
                f"  ! way {element['id']}: {missing} node(s) outside the API "
                "response; geometry may be clipped by the bbox"
            )

        buildings.append(
            {
                "osm_type": "way",
                "osm_id": element["id"],
                "osm_version": element.get("version"),
                "osm_timestamp": element.get("timestamp"),
                "coords": coords,
                "closed": bool(element.get("nodes")) and element["nodes"][0] == element["nodes"][-1],
                "tags": tags,
                "vertical_tags": {k: v for k, v in tags.items() if k in VERTICAL_TAGS},
                "provenance_tags": {
                    k: v for k, v in tags.items() if k in PROVENANCE_TAGS
                },
            }
        )

    if relations_with_buildings:
        print(
            f"  ! {relations_with_buildings} building relation(s) present but not "
            "resolvable via the main OSM API (members are not returned). "
            "Recorded as a known extraction limitation."
        )

    if not buildings:
        raise DataAcquisitionError(
            "The OpenStreetMap response contained no tagged building ways for "
            f"bbox {STUDY_AREA.seed_bbox}. This usually means the bounding box "
            "is wrong (UB City may be geocoded elsewhere) rather than that the "
            "area has no buildings. Refusing to generate a dataset from an "
            "empty or wrong area."
        )

    return buildings


def main() -> None:
    print("[fetch_buildings] acquiring real OpenStreetMap data")
    print(f"  seed bbox (W,S,E,N) = {STUDY_AREA.seed_bbox}")
    retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
    print(f"  retrieved_at (UTC) = {retrieved_at}")

    payload = fetch_osm_map(STUDY_AREA.seed_bbox)
    buildings = extract_buildings(payload)
    print(f"  building ways: {len(buildings)}")

    out_path = RAW_DIR.parent / "_buildings_raw.json"
    out_path.write_text(
        json.dumps(
            {
                "retrieved_at_utc": retrieved_at,
                "source": OSM_API_BASE + "/map.json",
                "source_params": {"bbox": list(STUDY_AREA.seed_bbox)},
                "user_agent": USER_AGENT,
                "buildings": buildings,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
