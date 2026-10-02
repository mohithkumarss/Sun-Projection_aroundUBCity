"""
Central configuration for the UB City solar-shadow research pipeline.

Every magic number used by the pipeline lives here so that the run is
reproducible and auditable. Nothing in this file is invented: the study-area
bounds are derived at runtime from real OSM data (see `derive_study_area.py`)
and this file only holds the *seed* box used to locate UB City.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "public" / "data"
SHADOW_DIR = DATA_DIR / "shadows"
RESEARCH_DIR = PROJECT_ROOT / "research"
RAW_DIR = DATA_DIR / "_raw"  # committed raw OSM payloads, for auditability

# --------------------------------------------------------------------------
# Coordinate reference systems (see research/METHODOLOGY.md)
# --------------------------------------------------------------------------

CRS_STORAGE = "EPSG:4326"  # WGS 84 geographic - storage & GeoJSON interchange
CRS_METRIC = "EPSG:32643"  # WGS 84 / UTM zone 43N - all metric computation

# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

SIMULATION_DATE = "2026-10-01"
TIMEZONE = "Asia/Kolkata"
FRAME_COUNT = 25
START_LOCAL_TIME = "06:00"
END_LOCAL_TIME = "06:00"  # on the following day

# --------------------------------------------------------------------------
# Numeric policy
# --------------------------------------------------------------------------

# Shadows are unbounded as the sun approaches the horizon (L = H / tan(elev)).
# We clip the projection at this length from the building base. Rationale and
# the resulting under-reporting are documented in research/ASSUMPTIONS.md.
MAX_SHADOW_LENGTH_M = 1000.0

# Minimum solar elevation for which a shadow is emitted at all. Below this the
# projection is so long that it is dominated by the clip, so we declare the sun
# effectively "not above horizon" for shadow purposes.
MIN_SHADOW_ELEVATION_DEG = 0.10

# Validations tolerance
AREA_RELATIVE_TOLERANCE = 1e-6

# --------------------------------------------------------------------------
# Vertical-information policy
# --------------------------------------------------------------------------

# When False (the default) a building that has ONLY a floor count is recorded
# with height_method="unresolved" and is EXCLUDED from shadow casting, because
# silently converting floors to metres would present an estimate as a
# measurement. Flip to True only if you accept `derived_from_levels` heights
# and are willing to label them as low confidence.
ALLOW_LEVELS_DERIVATION = False

# Used only if ALLOW_LEVELS_DERIVATION is enabled. Bengaluru high-rise
# floor-to-floor heights vary widely; this value is an assumption, not a
# measurement, and is recorded as such in the provenance report.
ASSUMED_FLOOR_HEIGHT_M = 3.0


# --------------------------------------------------------------------------
# Study area
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StudyAreaConfig:
    """
    Seed bounding box used to locate the real UB City cluster in OpenStreetMap.

    `seed_bbox` was itself derived from a Nominatim geocode of
    "UB City, Bengaluru" (node 10291118242, Vittal Mallya Road, 12.9718 / 77.5956)
    widened to capture the surrounding blocks. The FINAL, committed study-area
    bounds are computed from the retrieved geometry by `derive_study_area.py`
    and written to public/data/study-area.geojson + simulation.json.
    """

    name: str = "UB City, Bengaluru, Karnataka, India"
    seed_bbox: tuple[float, float, float, float] = (
        77.5945,
        12.9710,
        77.5965,
        12.9725,
    )  # (west, south, east, north) WGS84
    # Target extent in metres used to sanity-check the derived bounding box.
    target_extent_m: tuple[float, float] = (200.0, 300.0)


STUDY_AREA = StudyAreaConfig()


# --------------------------------------------------------------------------
# Data sources
# --------------------------------------------------------------------------

OSM_API_BASE = "https://api.openstreetmap.org/api/0.6"
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
USER_AGENT = os.environ.get(
    "GIS_USER_AGENT",
    "ub-city-shadow-research/0.1 (GIS coursework prototype; contact: local)",
)
HTTP_TIMEOUT_S = 120
