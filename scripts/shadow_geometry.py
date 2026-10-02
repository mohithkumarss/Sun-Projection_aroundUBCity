"""
Shadow geometry engine.

Physical model
--------------
Each building is represented as one or more vertical prisms. A prism spans
z_bottom .. z_top over a footprint that is assumed constant with height
(flat-top, vertical walls). The ground is the plane z = 0 (flat-ground
assumption; see research/ASSUMPTIONS.md).

Sign conventions
----------------
* Solar azimuth is degrees clockwise from true north. It describes the
  direction FROM the observer TO the sun.
* The shadow therefore extends in the opposite horizontal direction:
  ``shadow_azimuth = (solar_azimuth + 180) mod 360``.
* In the local ENU frame the unit vector towards the sun is
  ``(cos(el)sin(az), cos(el)cos(az), sin(el))`` and light TRAVELS along its
  negation. The horizontal shadow direction is the negation of the horizontal
  component of the sun vector, i.e. ``(-sin(az), -cos(az))``.

Shadow polygon
--------------
A ray leaving the top of a vertical edge at height z and travelling until it
reaches z = 0 covers a horizontal distance ``z / tan(elevation)`` in the
shadow direction. The shadow of a prism is therefore exactly the Minkowski sum
of its footprint with the segment

    S = [ (z_bottom/tan(el)) * d_hat  ,  (z_top/tan(el)) * d_hat ]

where ``d_hat`` is the unit horizontal shadow direction. The Minkowski sum of a
polygon with a segment is computed exactly (not approximated by a convex hull,
which would be wrong for concave footprints) as the union of

    P,  P + S,  and for every edge (a, b) of P the quad (a, b, b+S, a+S).

Low-sun handling
----------------
``z / tan(elevation)`` diverges as the elevation approaches zero. We impose a
hard clip at ``MAX_SHADOW_LENGTH_M`` measured from the building base. When the
clip engages, the frame is flagged ``truncated`` so the under-report is never
silent. Shadows are only emitted for ``elevation >= MIN_SHADOW_ELEVATION_DEG``.
"""

from __future__ import annotations

import math

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from geo import horizontal_shadow_azimuth_deg, sun_vector_east_north_up

MIN_SHADOW_ELEVATION_DEG = 0.10
MAX_SHADOW_LENGTH_M = 1000.0


class ShadowGeometryError(RuntimeError):
    pass


def shadow_unit_direction(azimuth_deg: float) -> tuple[float, float]:
    """Unit horizontal vector (east, north) in which the shadow extends."""
    az = math.radians(azimuth_deg)
    return (-math.sin(az), -math.cos(az))


def shadow_length_for_height(height_m: float, elevation_deg: float) -> float:
    """L = H / tan(elevation), the horizontal run of a vertical edge of height H."""
    if elevation_deg <= 0:
        raise ShadowGeometryError(
            f"shadow_length_for_height called with elevation {elevation_deg} deg; "
            "this indicates a night frame reached the geometry stage."
        )
    return height_m / math.tan(math.radians(elevation_deg))


def minkowski_sum_with_segment(polygon: BaseGeometry, segment: tuple[float, float]):
    """
    Exact Minkowski sum of a (multi)polygon with a segment vector.

    ``segment`` is (dx, dy): the vector added to every point of the polygon.
    """
    if abs(segment[0]) < 1e-12 and abs(segment[1]) < 1e-12:
        return polygon

    dx, dy = segment
    polys = polygon.geoms if isinstance(polygon, MultiPolygon) else [polygon]
    pieces = []
    for poly in polys:
        if poly.is_empty:
            continue
        moved = Polygon([(x + dx, y + dy) for x, y in poly.exterior.coords])
        pieces.append(poly)
        pieces.append(moved)
        coords = list(poly.exterior.coords)
        for i in range(len(coords) - 1):
            ax, ay = coords[i]
            bx, by = coords[i + 1]
            quad = Polygon(
                [
                    (ax, ay),
                    (bx, by),
                    (bx + dx, by + dy),
                    (ax + dx, ay + dy),
                ]
            )
            if quad.area > 0:
                pieces.append(quad)

    result = unary_union(pieces)
    if not result.is_valid:
        result = result.buffer(0)
    return result


def building_shadow_polygon(
    footprint_metric: BaseGeometry,
    z_bottom_m: float,
    z_top_m: float,
    solar_azimuth_deg: float,
    solar_elevation_deg: float,
    max_length_m: float = MAX_SHADOW_LENGTH_M,
) -> tuple[BaseGeometry, dict]:
    """
    Ground shadow polygon of a single vertical prism, in EPSG:32643.

    Returns (polygon, info) where info records truncation and the realised
    shadow length.
    """
    if solar_elevation_deg < MIN_SHADOW_ELEVATION_DEG:
        raise ShadowGeometryError(
            f"elevation {solar_elevation_deg} deg is below the emission "
            f"threshold {MIN_SHADOW_ELEVATION_DEG} deg"
        )

    d_hat = shadow_unit_direction(solar_azimuth_deg)
    tan_el = math.tan(math.radians(solar_elevation_deg))

    start_len = z_bottom_m / tan_el
    natural_end_len = z_top_m / tan_el
    truncated = natural_end_len > max_length_m
    end_len = min(natural_end_len, max_length_m)

    start = (d_hat[0] * start_len, d_hat[1] * start_len)
    end = (d_hat[0] * end_len, d_hat[1] * end_len)

    # The shadow of a slab spanning z_bottom..z_top is the footprint swept
    # through the offsets [start_len, end_len] along d_hat, i.e.
    #
    #     (footprint + start) (+) [0, end - start]
    #
    # The initial translation by `start` is essential: without it a raised
    # slab (z_bottom > 0) would project from the origin instead of from where
    # its lower edge actually is.
    from shapely import affinity

    shifted = affinity.translate(footprint_metric, xoff=start[0], yoff=start[1])
    segment = (end[0] - start[0], end[1] - start[1])

    shadow = minkowski_sum_with_segment(shifted, segment)
    if not shadow.is_valid:
        shadow = shadow.buffer(0)

    # NOTE: full precision is retained here. Rounding to a fixed number of
    # decimals is a serialisation concern and is applied by the writer, so that
    # validation tests can compare against the closed form at tight tolerance.
    info = {
        "shadow_start_offset_m": start_len,
        "shadow_end_offset_m": end_len,
        "shadow_length_m": end_len - start_len,
        "shadow_length_natural_m": natural_end_len - start_len,
        "truncated": bool(truncated),
        "max_length_m": max_length_m,
    }
    return shadow, info


def shadow_polygon_at_height(
    footprint_metric: BaseGeometry,
    height_m: float,
    solar_azimuth_deg: float,
    solar_elevation_deg: float,
    max_length_m: float = MAX_SHADOW_LENGTH_M,
) -> BaseGeometry:
    """
    The region of the horizontal plane at height ``height_m`` that is in
    geometric shadow.

    Used for the building-to-building occlusion test: a point on a neighbour's
    roof is unlit exactly when it lies inside this polygon. Reusing the same
    construction as the ground shadow guarantees the rendered geometry and the
    occlusion test can never disagree.
    """
    d_hat = shadow_unit_direction(solar_azimuth_deg)
    tan_el = math.tan(math.radians(solar_elevation_deg))
    length = min(height_m / tan_el, max_length_m)
    return minkowski_sum_with_segment(
        footprint_metric, (d_hat[0] * length, d_hat[1] * length)
    )


def sample_points(geometry: BaseGeometry, n: int) -> list[tuple[float, float]]:
    """
    Deterministic interior sample points of a polygon, on an n x n lattice.

    Deterministic (not random) so that the occlusion statistics are exactly
    reproducible between runs.
    """
    minx, miny, maxx, maxy = geometry.bounds
    width, height = maxx - minx, maxy - miny
    if width <= 0 or height <= 0:
        return []
    points = []
    for i in range(n):
        for j in range(n):
            x = minx + width * (i + 0.5) / n
            y = miny + height * (j + 0.5) / n
            if geometry.contains(Point(x, y)):
                points.append((x, y))
    return points


def occlusion_analysis(
    prisms: list[dict],
    solar_azimuth_deg: float,
    solar_elevation_deg: float,
    samples_per_prism: int = 12,
) -> dict:
    """
    Building-to-building shadow interaction.

    For every building we sample points across its own prisms at the prism's
    top surface and test whether each sample lies in the shadow cast by any
    OTHER building at that same height. The result is the fraction of each
    building's upper surface that is shaded, and which buildings are responsible.

    This is a one-directional visibility test along the sun vector, which is
    exactly the shadow test; it is not an approximation of mutual visibility.
    """
    if solar_elevation_deg < MIN_SHADOW_ELEVATION_DEG:
        return {
            "per_building": {},
            "method": "sun-vector ray test against other buildings' shadow volumes",
            "samples_per_prism": samples_per_prism,
        }

    # Cache shadow polygons per (building, height) to avoid recomputation.
    cache: dict[tuple[str, float], BaseGeometry] = {}

    def shadow_of(building_id: str, height: float) -> BaseGeometry:
        key = (building_id, round(height, 3))
        if key not in cache:
            pieces = []
            for prism in prisms[building_id]:
                piece = shadow_polygon_at_height(
                    prism["footprint_metric"],
                    prism["z_top_m"],
                    solar_azimuth_deg,
                    solar_elevation_deg,
                )
                pieces.append(piece)
            cache[key] = unary_union(pieces) if pieces else Polygon()
        return cache[key]

    per_building = {}
    for building_id in prisms:
        total = 0
        shaded = 0
        shaded_by: dict[str, int] = {}
        for prism in prisms[building_id]:
            height = prism["z_top_m"]
            points = sample_points(prism["footprint_metric"], samples_per_prism)
            if not points:
                continue
            for x, y in points:
                total += 1
                point = Point(x, y)
                for other_id in prisms:
                    if other_id == building_id:
                        continue
                    if shadow_of(other_id, height).contains(point):
                        shaded += 1
                        shaded_by[other_id] = shaded_by.get(other_id, 0) + 1
                        break
        per_building[building_id] = {
            "samples": total,
            "shaded_samples": shaded,
            "shaded_fraction": round(shaded / total, 4) if total else None,
            "shaded_by": shaded_by,
        }

    return {
        "per_building": per_building,
        "method": "sun-vector ray test against other buildings' shadow volumes",
        "samples_per_prism": samples_per_prism,
    }


def dominant_direction(geometry: BaseGeometry) -> dict | None:
    """
    Dominant outward direction of a shadow polygon, from its principal axis.

    Uses the minimum rotated rectangle so the direction is a property of the
    shape's long axis rather than of an arbitrary vertex.
    """
    if geometry.is_empty:
        return None
    rect = geometry.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:-1]
    if len(coords) != 4:
        return None
    import numpy as np

    points = np.array(coords)
    centre = points.mean(axis=0)
    edges = np.roll(points, -1, axis=0) - points
    lengths = np.hypot(edges[:, 0], edges[:, 1])
    long_index = int(np.argmax(lengths))
    ex, ey = edges[long_index]
    midpoints = points + edges / 2.0
    direction = midpoints[long_index] - centre
    magnitude = float(np.hypot(*direction))
    if magnitude < 1e-9:
        return None
    east, north = direction / magnitude
    azimuth = (math.degrees(math.atan2(east, north)) + 360.0) % 360.0
    return {
        "azimuth_deg": round(azimuth, 3),
        "length_m": round(magnitude, 3),
        "angle_from_north_deg": round(azimuth, 3),
        "description": describe_azimuth(azimuth),
    }


def describe_azimuth(azimuth_deg: float) -> str:
    """Compass description for a clockwise-from-north azimuth."""
    names = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    index = int(((azimuth_deg % 360.0) + 11.25) // 22.5) % 16
    return names[index]
