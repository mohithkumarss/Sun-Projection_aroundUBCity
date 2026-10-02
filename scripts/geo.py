"""
Geometry and CRS helpers shared across the pipeline.

Conventions used throughout the project (also stated in research/METHODOLOGY.md):

* Storage / interchange ......... EPSG:4326 (WGS 84 longitude, latitude)
* Metric computation ............ EPSG:32643 (WGS 84 / UTM zone 43N, metres)
* Azimuth ...................... degrees clockwise from true north (0 = N,
                                 90 = E, 180 = S, 270 = W)
* Solar elevation .............. degrees above the true horizon
* Solar zenith ................. degrees from vertical; zenith = 90 - elevation
* Shadow direction ............. the direction light *travels*, i.e. opposite
                                 the direction to the sun
* Units ........................ metres, square metres, degrees (unless noted)
"""

from __future__ import annotations

import math
from typing import Iterable

from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from pipeline_config import CRS_METRIC, CRS_STORAGE

# --------------------------------------------------------------------------
# CRS transformers (module-level singletons: pyproj transformers are thread
# safe and expensive to construct).
# --------------------------------------------------------------------------

_TO_METRIC = Transformer.from_crs(CRS_STORAGE, CRS_METRIC, always_xy=True)
_TO_GEOGRAPHIC = Transformer.from_crs(CRS_METRIC, CRS_STORAGE, always_xy=True)


def to_metric(geom: BaseGeometry) -> BaseGeometry:
    """Reproject a WGS84 geometry into EPSG:32643 (metres)."""
    return shapely_transform(_TO_METRIC.transform, geom)


def to_wgs84(geom: BaseGeometry) -> BaseGeometry:
    """Reproject an EPSG:32643 geometry back to WGS84 for GeoJSON output."""
    return shapely_transform(_TO_GEOGRAPHIC.transform, geom)


def lonlat_to_metric(lon: float, lat: float) -> tuple[float, float]:
    return _TO_METRIC.transform(lon, lat)


def metric_to_lonlat(x: float, y: float) -> tuple[float, float]:
    return _TO_GEOGRAPHIC.transform(x, y)


# --------------------------------------------------------------------------
# Sun-vector construction
# --------------------------------------------------------------------------


def sun_vector_east_north_up(
    azimuth_deg: float, elevation_deg: float
) -> tuple[float, float, float]:
    """
    Unit vector from the observer TOWARDS the sun, in a local
    East / North / Up (ENU) frame.

    Parameters
    ----------
    azimuth_deg
        Solar azimuth, degrees clockwise from true north.
    elevation_deg
        Solar elevation above the horizon, degrees.

    Returns
    -------
    (east, north, up) with ``up > 0`` for a sun above the horizon.

    Notes
    -----
    This frame is local: +East and +North are tangent to the WGS84 ellipsoid
    at the site. We deliberately do NOT use a full geodetic (ENU) basis derived
    from the ellipsoid normal because the study area is ~250 m across; the
    difference between geodetic and geographic up over that distance is
    < 0.001 deg and is far below the accuracy of the input building data.
    See research/ASSUMPTIONS.md.
    """
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    cos_el = math.cos(el)
    return (
        cos_el * math.sin(az),  # east
        cos_el * math.cos(az),  # north
        math.sin(el),  # up
    )


def horizontal_shadow_azimuth_deg(solar_azimuth_deg: float) -> float:
    """
    Azimuth (degrees clockwise from north) of the direction in which the
    shadow extends, i.e. the projection of the light-travel vector onto the
    horizontal plane.

    A shadow always points AWAY from the sun, so this is the solar azimuth
    + 180 deg, normalised to [0, 360).
    """
    return (solar_azimuth_deg + 180.0) % 360.0


# --------------------------------------------------------------------------
# Validity / finite-value guards
# --------------------------------------------------------------------------


def coords_are_finite(geom: BaseGeometry) -> bool:
    """True if every coordinate in the geometry is finite (no NaN / inf)."""
    for ring in _iter_rings(geom):
        for x, y in ring:
            if not (math.isfinite(x) and math.isfinite(y)):
                return False
    return True


def _iter_rings(geom: BaseGeometry) -> Iterable[list[tuple[float, float]]]:
    """Yield each coordinate sequence (exterior ring, interior rings, ...)."""
    g = geom
    if g.geom_type == "Polygon":
        yield list(g.exterior.coords)
        for interior in g.interiors:
            yield list(interior.coords)
    elif g.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in g.geoms:
            yield from _iter_rings(part)
    elif g.geom_type == "Point":
        yield [(g.x, g.y)]
    elif g.geom_type in ("LineString", "LinearRing"):
        yield list(g.coords)


def assert_valid(geom: BaseGeometry, context: str) -> BaseGeometry:
    """Raise if the geometry is invalid or contains non-finite coordinates."""
    if not coords_are_finite(geom):
        raise ValueError(f"{context}: non-finite coordinates")
    if not geom.is_valid:
        raise ValueError(f"{context}: invalid geometry ({geom.is_valid_reason})")
    return geom


def describe_crs() -> dict[str, str]:
    return {
        "storage_crs": CRS_STORAGE,
        "storage_crs_name": CRS.from_user_input(CRS_STORAGE).name,
        "metric_crs": CRS_METRIC,
        "metric_crs_name": CRS.from_user_input(CRS_METRIC).name,
    }


def shapely_from_geojson(feature: dict) -> BaseGeometry:
    return shape(feature["geometry"])
