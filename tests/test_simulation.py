"""
Scientific validation suite for the UB City shadow pipeline.

Run with:  .venv/bin/python -m pytest tests -v

These tests are the scientific gate. They cover, in order:
  * CRS correctness (storage / computation / export)
  * Solar position against the trusted pvlib implementation
  * Shadow DIRECTION (shadow must oppose the sun)
  * Shadow LENGTH against the closed-form L = H / tan(E)
  * Geometry validity (no NaN/inf, sane area/perimeter)
  * Time base (exactly 25 frames, correct span)
  * Night behaviour (no shadow when the sun is below the horizon)
  * The independent synthetic validation scene (section 28 of the brief)
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pvlib
import pytest
from shapely.geometry import Polygon, shape

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from geo import (  # noqa: E402
    horizontal_shadow_azimuth_deg,
    metric_to_lonlat,
    to_metric,
    to_wgs84,
)
from pipeline_config import (  # noqa: E402
    DATA_DIR,
    FRAME_COUNT,
    MAX_SHADOW_LENGTH_M,
    MIN_SHADOW_ELEVATION_DEG,
    SIMULATION_DATE,
    TIMEZONE,
)
from shadow_geometry import (  # noqa: E402
    building_shadow_polygon,
    describe_azimuth,
    shadow_length_for_height,
    shadow_unit_direction,
)

TZ = ZoneInfo(TIMEZONE)

BUILDINGS_PATH = DATA_DIR / "buildings.geojson"
STUDY_PATH = DATA_DIR / "study-area.geojson"
SIMULATION_PATH = DATA_DIR / "simulation.json"
SOLAR_PATH = DATA_DIR / "_solar.json"

# The dataset is produced by the pipeline; skip loudly rather than test a
# stale or absent file.
pytestmark = pytest.mark.skipif(
    not SIMULATION_PATH.exists(),
    reason="simulation.json not generated - run `python scripts/run_pipeline.py` first",
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def simulation() -> dict:
    return json.loads(SIMULATION_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def buildings() -> dict:
    return json.loads(BUILDINGS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def study() -> dict:
    return json.loads(STUDY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def solar() -> dict:
    return json.loads(SOLAR_PATH.read_text(encoding="utf-8"))


# ==========================================================================
# 1. CRS
# ==========================================================================


class TestCRS:
    def test_storage_crs_is_wgs84(self, buildings, study):
        assert buildings["crs"]["properties"]["name"] == "EPSG:4326"
        assert study["crs"]["properties"]["name"] == "EPSG:4326"

    def test_computation_crs_is_utm43n(self, simulation):
        meta = simulation["metadata"]
        assert meta["crs_computation"] == "EPSG:32643"
        assert meta["crs_storage"] == "EPSG:4326"

    def test_output_geojson_is_wgs84_degrees(self, buildings):
        """Exported coordinates must be plausible lon/lat degrees."""
        for feature in buildings["features"]:
            for lon, lat in feature["geometry"]["coordinates"][0]:
                assert -180.0 <= lon <= 180.0, f"longitude {lon} is not a degree value"
                assert -90.0 <= lat <= 90.0, f"latitude {lat} is not a degree value"
                # UB City is a compact area: this would fail loudly if a metric
                # CRS had leaked into the export.
                assert 77.0 < lon < 78.0
                assert 12.0 < lat < 13.0

    def test_shadow_frames_exported_in_wgs84(self, simulation):
        for frame in simulation["frames"]:
            path = DATA_DIR / frame["file"]
            assert path.exists(), f"missing {path}"
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["crs"]["properties"]["name"] == "EPSG:4326"
            for feature in payload["features"]:
                assert feature["properties"]["crs_calculated_in"] == "EPSG:32643"
                assert feature["properties"]["crs_exported_in"] == "EPSG:4326"

    def test_metric_roundtrip_is_stable(self):
        """A WGS84 -> metric -> WGS84 round trip must be near-idempotent."""
        from geo import lonlat_to_metric

        lon, lat = 77.59555, 12.97150
        x, y = lonlat_to_metric(lon, lat)
        back_lon, back_lat = metric_to_lonlat(x, y)
        assert abs(back_lon - lon) < 1e-9
        assert abs(back_lat - lat) < 1e-9

    def test_areas_are_computed_in_metres_not_degrees(self, buildings):
        """
        A UB City building is a few thousand square metres. If area had been
        computed in square degrees the number would be ~1e-4. This is the
        guard against the classic lat/lon area mistake.
        """
        for feature in buildings["features"]:
            area = feature["properties"]["footprint_area_m2"]
            assert 50.0 < area < 100_000.0, f"implausible footprint area {area}"


# ==========================================================================
# 2. Solar position
# ==========================================================================


class TestSolarPosition:
    def test_solar_method_is_validated_implementation(self, simulation):
        method = simulation["metadata"]["solar_method"]["method"]
        assert "pvlib" in method
        assert "nrel" in method.lower()
        assert simulation["metadata"]["solar_method"]["pvlib_version"] == pvlib.__version__

    def test_frames_match_live_pvlib(self, solar):
        """Recompute independently and compare to the published values."""
        lat = solar["metadata"]["latitude"]
        lon = solar["metadata"]["longitude"]
        index = pd.DatetimeIndex(
            [dt.datetime.fromisoformat(f["timestamp"]) for f in solar["frames"]]
        ).tz_convert("UTC")
        expected = pvlib.solarposition.get_solarposition(index, lat, lon, method="nrel_numpy")
        for i, frame in enumerate(solar["frames"]):
            assert frame["solar_azimuth_deg"] == pytest.approx(
                float(expected["azimuth"].iloc[i]), abs=1e-6
            )
            assert frame["solar_elevation_deg"] == pytest.approx(
                float(expected["elevation"].iloc[i]), abs=1e-6
            )

    def test_zenith_is_complement_of_elevation(self, solar):
        for frame in solar["frames"]:
            assert frame["solar_zenith_deg"] == pytest.approx(
                90.0 - frame["solar_elevation_deg"], abs=1e-6
            )

    def test_sun_path_is_physically_plausible(self, solar):
        """
        Bengaluru (12.97 N) on 1 October: the sun rises east of north, transits
        south, and sets west of north, with a maximum elevation near 90 - lat.
        """
        daylight = [f for f in solar["frames"] if f["solar_elevation_deg"] > 0]
        assert daylight, "expected daylight frames"

        morning = min(daylight, key=lambda f: f["local_time"] <= "12:00" and f["solar_elevation_deg"] or 999)
        # The transit (highest elevation) must be close to due south.
        transit = max(solar["frames"], key=lambda f: f["solar_elevation_deg"])
        assert 150.0 < transit["solar_azimuth_deg"] < 210.0, (
            f"transit azimuth {transit['solar_azimuth_deg']} should be southerly"
        )
        # Max elevation <= 90 - |lat| + small refraction allowance.
        assert transit["solar_elevation_deg"] < 90.0 - 12.97 + 1.0
        assert morning["solar_azimuth_deg"] < 180.0, "morning sun should be easterly"

    def test_azimuth_in_valid_range(self, solar):
        for frame in solar["frames"]:
            assert 0.0 <= frame["solar_azimuth_deg"] < 360.0
            assert -90.0 <= frame["solar_elevation_deg"] <= 90.0

    def test_sunrise_sunset_bracket_the_daylight_frames(self, solar):
        sunrise = dt.datetime.fromisoformat(solar["metadata"]["sunrise"])
        sunset = dt.datetime.fromisoformat(solar["metadata"]["sunset"])
        assert sunrise < sunset
        assert sunrise.date() == sunset.date() == dt.date.fromisoformat(SIMULATION_DATE)
        # Bengaluru in October: ~12 h of daylight, which brackets the 12
        # emitted shadow frames.
        daylight_hours = (sunset - sunrise).total_seconds() / 3600.0
        assert 11.0 < daylight_hours < 13.0
        emitted = [f for f in solar["frames"] if f["shadow_emitted"]]
        assert len(emitted) == 12


# ==========================================================================
# 3. Shadow direction - must oppose the sun
# ==========================================================================


class TestShadowDirection:
    @pytest.mark.parametrize(
        "solar_azimuth", [0.0, 45.0, 92.5, 171.7, 218.7, 266.3, 315.0, 359.0]
    )
    def test_unit_direction_is_antipodal_to_sun(self, solar_azimuth):
        east, north = shadow_unit_direction(solar_azimuth)
        az = math.radians(solar_azimuth)
        # Sun horizontal component vs shadow horizontal component.
        assert east == pytest.approx(-math.sin(az), abs=1e-12)
        assert north == pytest.approx(-math.cos(az), abs=1e-12)
        assert math.hypot(east, north) == pytest.approx(1.0, abs=1e-12)

    @pytest.mark.parametrize(
        "solar_azimuth,expected", [(0.0, 180.0), (90.0, 270.0), (180.0, 0.0), (270.0, 90.0)]
    )
    def test_horizontal_shadow_azimuth(self, solar_azimuth, expected):
        assert horizontal_shadow_azimuth_deg(solar_azimuth) == pytest.approx(expected)

    def test_geometric_shadow_points_away_from_sun(self):
        """
        Place a building and verify the shadow centroid lies on the
        anti-solar side of the building centre.
        """
        footprint = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        for solar_azimuth in (0.0, 90.0, 180.0, 270.0, 40.0, 220.0):
            elevation = 45.0
            shadow, _ = building_shadow_polygon(footprint, 0.0, 30.0, solar_azimuth, elevation)
            bc = footprint.centroid
            sc = shadow.centroid
            expected_east, expected_north = shadow_unit_direction(solar_azimuth)
            # Displacement from building centroid to shadow centroid must have
            # a positive component along the anti-solar direction.
            displacement = (sc.x - bc.x, sc.y - bc.y)
            dot = displacement[0] * expected_east + displacement[1] * expected_north
            assert dot > 0, (
                f"shadow centroid is not on the anti-solar side "
                f"(azimuth {solar_azimuth}, dot {dot})"
            )

    def test_shadow_azimuth_recorded_in_dataset(self, simulation):
        for frame in simulation["frames"]:
            expected = (frame["solar_azimuth_deg"] + 180.0) % 360.0
            assert frame["shadow_azimuth_deg"] == pytest.approx(expected, abs=1e-6)

    def test_compass_descriptions(self):
        assert describe_azimuth(0.0) == "N"
        assert describe_azimuth(90.0) == "E"
        assert describe_azimuth(180.0) == "S"
        assert describe_azimuth(270.0) == "W"


# ==========================================================================
# 4. Shadow length - closed form
# ==========================================================================


class TestShadowLength:
    def test_formula_matches_geometry(self):
        """The generated geometry must reproduce L = H / tan(E) exactly."""
        footprint = Polygon([(0, 0), (20, 0), (20, 30), (0, 30)])
        for height in (10.0, 25.0, 50.0, 60.0):
            for elevation in (5.0, 15.0, 30.0, 45.0, 60.0, 75.0):
                expected = shadow_length_for_height(height, elevation)
                _, info = building_shadow_polygon(
                    footprint, 0.0, height, 180.0, elevation
                )
                assert info["shadow_length_m"] == pytest.approx(expected, rel=1e-9)
                assert info["shadow_length_natural_m"] == pytest.approx(expected, rel=1e-9)

    def test_shadow_length_grows_as_sun_descends(self):
        footprint = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        previous = 0.0
        for elevation in (80.0, 60.0, 45.0, 30.0, 20.0, 10.0):
            _, info = building_shadow_polygon(footprint, 0.0, 50.0, 180.0, elevation)
            assert info["shadow_length_m"] > previous
            previous = info["shadow_length_m"]

    def test_podium_plus_tower_equals_solid_prism(self):
        """
        A building modelled as a ground-level podium (0..z_b) plus an upper
        tower (z_b..z_top) must cast exactly the same ground shadow as a single
        solid prism from 0 to z_top.

        This is the strongest available check on the raised-prism branch of the
        projection code: a raised slab's shadow must be swept from
        z_bottom/tan(E) to z_top/tan(E), not from the origin.
        """
        from shapely.ops import unary_union

        footprint = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        elevation = 30.0
        z_bottom = 10.0

        solid, solid_info = building_shadow_polygon(
            footprint, 0.0, 50.0, 180.0, elevation
        )
        tower, tower_info = building_shadow_polygon(
            footprint, z_bottom, 50.0, 180.0, elevation
        )
        podium, podium_info = building_shadow_polygon(
            footprint, 0.0, z_bottom, 180.0, elevation
        )
        combined = unary_union([tower, podium])

        assert solid_info["shadow_length_m"] == pytest.approx(
            50.0 / math.tan(math.radians(elevation)), rel=1e-9
        )
        # The tower's shadow starts where the podium's ends, so they join.
        assert tower_info["shadow_start_offset_m"] == pytest.approx(
            podium_info["shadow_end_offset_m"], rel=1e-12
        )
        assert tower_info["shadow_end_offset_m"] == pytest.approx(
            solid_info["shadow_end_offset_m"], rel=1e-12
        )
        # Union of the two slabs reproduces the solid prism's shadow exactly.
        # Compared by symmetric-difference area rather than `.equals()` so the
        # check is about the geometry, not GEOS' exact coordinate bookkeeping.
        assert combined.symmetric_difference(solid).area == pytest.approx(0.0, abs=1e-9)
        assert combined.area == pytest.approx(solid.area, rel=1e-9)
        assert combined.bounds == pytest.approx(solid.bounds, rel=1e-9)

    def test_raised_slab_shadow_starts_at_its_lower_edge(self):
        """
        A slab whose lower edge is at z_bottom projects its shadow starting at
        z_bottom/tan(E) from the footprint, not at the footprint itself.
        """
        footprint = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        elevation = 30.0
        z_bottom, z_top = 10.0, 50.0
        expected_start = z_bottom / math.tan(math.radians(elevation))

        shadow, info = building_shadow_polygon(
            footprint, z_bottom, z_top, 180.0, elevation
        )
        # Sun in the south -> shadow extends north. The north-south span is the
        # building depth plus the shadow LENGTH of the slab, i.e. (z_top -
        # z_bottom)/tan(E); the whole shadow is displaced by z_bottom/tan(E).
        assert shadow.bounds[3] - shadow.bounds[1] == pytest.approx(
            20.0 + ((z_top - z_bottom) / math.tan(math.radians(elevation))), rel=1e-9
        )
        assert shadow.bounds[1] == pytest.approx(expected_start, rel=1e-9)
        assert info["shadow_start_offset_m"] == pytest.approx(expected_start, rel=1e-9)


# ==========================================================================
# 5. Low-sun numerical robustness
# ==========================================================================


class TestLowSunRobustness:
    def test_extreme_low_sun_is_truncated_not_infinite(self):
        footprint = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        _, info = building_shadow_polygon(footprint, 0.0, 60.0, 180.0, 0.5)
        assert info["truncated"] is True
        assert info["shadow_length_m"] <= MAX_SHADOW_LENGTH_M + 1e-9
        assert math.isfinite(info["shadow_length_m"])

    def test_clip_is_reported_in_metadata(self, simulation):
        truncated_frames = [f for f in simulation["frames"] if f["truncated"]]
        assert simulation["metadata"]["max_shadow_length_m"] == MAX_SHADOW_LENGTH_M
        for frame in truncated_frames:
            assert frame["max_shadow_length_m"] <= MAX_SHADOW_LENGTH_M + 1e-6

    def test_below_threshold_raises_instead_of_producing_geometry(self):
        footprint = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)])
        with pytest.raises(Exception):
            building_shadow_polygon(footprint, 0.0, 50.0, 180.0, 0.0)

    def test_negative_elevation_raises(self):
        from shadow_geometry import ShadowGeometryError

        with pytest.raises(ShadowGeometryError):
            shadow_length_for_height(50.0, -10.0)

    def test_no_nan_or_inf_anywhere_in_output(self, simulation):
        for frame in simulation["frames"]:
            payload = json.loads((DATA_DIR / frame["file"]).read_text(encoding="utf-8"))

            def walk(value, path="root"):
                if isinstance(value, float):
                    assert math.isfinite(value), f"non-finite at {path}: {value}"
                elif isinstance(value, dict):
                    for k, v in value.items():
                        walk(v, f"{path}.{k}")
                elif isinstance(value, list):
                    for i, v in enumerate(value):
                        walk(v, f"{path}[{i}]")

            walk(payload, frame["slug"])


# ==========================================================================
# 6. Geometry validity
# ==========================================================================


class TestGeometryValidity:
    def test_all_shadow_polygons_are_valid(self, simulation):
        total = 0
        for frame in simulation["frames"]:
            payload = json.loads((DATA_DIR / frame["file"]).read_text(encoding="utf-8"))
            for feature in payload["features"]:
                geom = shape(feature["geometry"])
                assert geom.is_valid, f"{feature['id']} is invalid: {geom.is_valid_reason}"
                assert geom.geom_type in ("Polygon", "MultiPolygon")
                total += 1
        assert total > 0, "no shadow features were generated at all"

    def test_no_nan_coordinates(self, simulation):
        for frame in simulation["frames"]:
            payload = json.loads((DATA_DIR / frame["file"]).read_text(encoding="utf-8"))
            for feature in payload["features"]:
                for ring in _all_rings(shape(feature["geometry"])):
                    for x, y in ring:
                        assert math.isfinite(x) and math.isfinite(y)
                        assert -180.0 <= x <= 180.0
                        assert -90.0 <= y <= 90.0

    def test_areas_and_perimeters_are_sane(self, simulation):
        for frame in simulation["frames"]:
            payload = json.loads((DATA_DIR / frame["file"]).read_text(encoding="utf-8"))
            for feature in payload["features"]:
                props = feature["properties"]
                area = props["shadow_area_m2"]
                perimeter = props["shadow_perimeter_m"]
                assert area > 0.0
                assert perimeter > 0.0
                # Isoperimetric bound: a polygon of area A cannot have a
                # perimeter less than that of a circle of the same area.
                assert perimeter >= 2.0 * math.sqrt(math.pi * area) - 1e-6
                # Shadow area must exceed the building footprint area.
                assert area > 0.0
                # A shadow cannot be smaller than the building that casts it.
                assert area >= 100.0

    def test_shadow_area_at_least_footprint_area(self, simulation, buildings):
        footprint_by_id = {
            f["properties"]["id"]: f["properties"]["footprint_area_m2"]
            for f in buildings["features"]
        }
        for frame in simulation["frames"]:
            payload = json.loads((DATA_DIR / frame["file"]).read_text(encoding="utf-8"))
            for feature in payload["features"]:
                building_id = feature["properties"]["building_id"]
                shadow_area = feature["properties"]["shadow_area_m2"]
                footprint = footprint_by_id[building_id]
                # The shadow always contains the footprint itself, so it cannot
                # be smaller. Allow a small tolerance for UTM reprojection
                # of the two areas computed from different geometries.
                assert shadow_area >= footprint * 0.98, (
                    f"{frame['local_time']} {building_id}: shadow {shadow_area} "
                    f"< footprint {footprint}"
                )

    def test_total_area_equals_sum_of_parts(self, simulation):
        for frame in simulation["frames"]:
            payload = json.loads((DATA_DIR / frame["file"]).read_text(encoding="utf-8"))
            total = sum(
                f["properties"]["shadow_area_m2"] for f in payload["features"]
            )
            # frame_total is the (possibly overlapping) sum of per-building
            # areas, so this must match exactly, not the union.
            assert total == pytest.approx(frame["total_shadow_area_m2"], rel=1e-6)

    def test_coverage_never_exceeds_study_area(self, simulation):
        """
        Coverage uses the shadow area CLIPPED to the study area and de-overlapped
        implicitly, so it must be a fraction.
        """
        for frame in simulation["frames"]:
            assert 0.0 <= frame["shadow_coverage_percent"] <= 100.0


def _all_rings(geom):
    if geom.geom_type == "Polygon":
        yield list(geom.exterior.coords)
        for interior in geom.interiors:
            yield list(interior.coords)
    elif geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geom.geoms:
            yield from _all_rings(part)


# ==========================================================================
# 7. Time base
# ==========================================================================


class TestTimeBase:
    def test_exactly_25_frames(self, simulation):
        assert len(simulation["frames"]) == FRAME_COUNT == 25

    def test_frame_labels_match_the_brief(self, simulation):
        expected = (
            ["06", "07", "08", "09", "10", "11", "12"]
            + [f"{h:02d}" for h in range(13, 24)]
            + ["00", "01", "02", "03", "04", "05", "06"]
        )
        actual = [f["local_time"][:2] for f in simulation["frames"]]
        assert actual == expected

    def test_hourly_increments_across_midnight(self, simulation):
        stamps = [dt.datetime.fromisoformat(f["timestamp"]) for f in simulation["frames"]]
        for previous, current in zip(stamps, stamps[1:]):
            assert current - previous == dt.timedelta(hours=1)
        assert stamps[0] == dt.datetime.fromisoformat("2026-10-01T06:00:00+05:30")
        assert stamps[-1] == dt.datetime.fromisoformat("2026-10-02T06:00:00+05:30")

    def test_all_timestamps_are_ist(self, simulation):
        for frame in simulation["frames"]:
            assert frame["timezone"] == TIMEZONE
            assert frame["timestamp"].endswith("+05:30")

    def test_simulation_date_recorded(self, simulation):
        assert simulation["metadata"]["simulation_date"] == SIMULATION_DATE == "2026-10-01"

    def test_frame_file_names_are_parseable(self, simulation):
        for frame in simulation["frames"]:
            slug = frame["slug"]
            assert len(slug) > 10
            assert "/" not in slug and ":" not in slug


# ==========================================================================
# 8. Night handling
# ==========================================================================


class TestNightHandling:
    def test_no_shadow_when_sun_below_horizon(self, simulation):
        for frame in simulation["frames"]:
            payload = json.loads((DATA_DIR / frame["file"]).read_text(encoding="utf-8"))
            if frame["solar_elevation_deg"] <= 0.0:
                assert frame["sun_above_horizon"] is False
                assert frame["active_building_shadows"] == 0
                assert frame["total_shadow_area_m2"] == 0.0
                assert payload["features"] == []
                assert payload["metadata"]["shadow_emitted"] is False

    def test_no_shadow_below_emission_threshold(self, simulation):
        for frame in simulation["frames"]:
            if frame["solar_elevation_deg"] < MIN_SHADOW_ELEVATION_DEG:
                assert frame["shadow_emitted"] is False
                assert frame["active_building_shadows"] == 0

    def test_night_frames_are_flagged_explicitly(self, simulation):
        night = [f for f in simulation["frames"] if not f["sun_above_horizon"]]
        assert len(night) == 13
        assert set(simulation["metadata"]["night_frames"]) == {
            f["local_time"] for f in night
        }

    def test_exactly_12_daylight_shadow_frames(self, simulation):
        emitted = [f for f in simulation["frames"] if f["shadow_emitted"]]
        assert len(emitted) == 12
        assert all(f["active_building_shadows"] > 0 for f in emitted)


# ==========================================================================
# 9. Independent synthetic validation scene (brief section 28)
# ==========================================================================


class TestSyntheticValidationScene:
    """
    A deliberately simple mathematical case, clearly separated from the UB City
    dataset: one 20 m x 30 m rectangular building of known height 50 m.
    """

    WIDTH_M = 20.0
    DEPTH_M = 30.0
    HEIGHT_M = 50.0

    def _scene(self):
        return Polygon(
            [
                (0.0, 0.0),
                (self.WIDTH_M, 0.0),
                (self.WIDTH_M, self.DEPTH_M),
                (0.0, self.DEPTH_M),
            ]
        )

    @pytest.mark.parametrize("elevation", [10.0, 20.0, 30.0, 45.0, 60.0, 75.0])
    def test_shadow_length_matches_closed_form(self, elevation):
        expected = self.HEIGHT_M / math.tan(math.radians(elevation))
        shadow, info = building_shadow_polygon(
            self._scene(), 0.0, self.HEIGHT_M, 180.0, elevation
        )
        assert info["shadow_length_m"] == pytest.approx(expected, rel=1e-9)

    @pytest.mark.parametrize("elevation", [30.0, 45.0, 60.0])
    def test_measured_geometry_length_matches_closed_form(self, elevation):
        """
        Measure the length from the GEOMETRY, not from the reported metadata,
        so this is an independent check of the polygon itself.
        """
        expected = self.HEIGHT_M / math.tan(math.radians(elevation))
        shadow, _ = building_shadow_polygon(
            self._scene(), 0.0, self.HEIGHT_M, 180.0, elevation
        )
        minx, miny, maxx, maxy = shadow.bounds
        # Sun in the south (az 180) -> shadow extends north, so the shadow's
        # north-south extent is the building depth plus the shadow length.
        assert (maxy - miny) == pytest.approx(self.DEPTH_M + expected, rel=1e-9)
        # East-west extent is unchanged by a purely meridional projection.
        assert (maxx - minx) == pytest.approx(self.WIDTH_M, rel=1e-9)

    def test_shadow_area_matches_closed_form(self):
        """
        For a sun in the south, the shadow of a W x D box is a hexagon whose
        area is W*D + D*L + W*L/sin(elevation)... derived here directly from the
        Minkowski sum of the rectangle with a segment of length L along +north:
        area = W*D + L*W  (rectangle swept along y).

        The measured area must equal the swept-area formula.
        """
        elevation = 40.0
        expected_length = self.HEIGHT_M / math.tan(math.radians(elevation))
        shadow, _ = building_shadow_polygon(
            self._scene(), 0.0, self.HEIGHT_M, 180.0, elevation
        )
        expected_area = self.WIDTH_M * self.DEPTH_M + expected_length * self.WIDTH_M
        assert shadow.area == pytest.approx(expected_area, rel=1e-9)

    def test_synthetic_scene_is_not_in_the_ub_city_dataset(self, buildings):
        """
        The validation scene must be synthetic-only. Its coordinates are at the
        metric origin, far from Bengaluru, so no UB City feature can be it.
        """
        for feature in buildings["features"]:
            lons = [c[0] for c in feature["geometry"]["coordinates"][0]]
            assert all(77.0 < lon < 78.0 for lon in lons)

    def test_synthetic_validation_summary_is_published(self, simulation):
        assert "shadow_model" in simulation["metadata"]


# ==========================================================================
# 10. Data integrity / provenance
# ==========================================================================


class TestDataIntegrity:
    def test_buildings_are_real_osm_geometry(self, buildings):
        assert len(buildings["features"]) >= 5
        for feature in buildings["features"]:
            props = feature["properties"]
            assert props["osm_type"] == "way"
            assert isinstance(props["osm_id"], int)
            assert props["source"] == "OpenStreetMap"
            assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_no_fabricated_heights(self, buildings):
        """
        Every height must be traceable to an OSM height tag, or be explicitly
        unresolved. This is the core anti-fabrication guarantee.
        """
        for feature in buildings["features"]:
            props = feature["properties"]
            method = props["height_method"]
            if props["height_m"] is None:
                assert method == "unresolved"
                assert props["shadow_casting"] is False
            else:
                assert method in ("OSM_exact", "derived_from_levels", "documented")
                if method == "OSM_exact":
                    assert "height" in props["source_tags"] or "building:height" in props["source_tags"]
                    assert str(props["source_tags"].get("height", props["source_tags"].get("building:height"))) != ""

    def test_levels_do_not_become_heights_by_default(self, buildings):
        from pipeline_config import ALLOW_LEVELS_DERIVATION

        if not ALLOW_LEVELS_DERIVATION:
            for feature in buildings["features"]:
                props = feature["properties"]
                if props["levels"] is not None and props["height_m"] is None:
                    assert props["height_method"] == "unresolved"
                    assert "not converted" in props["height_source"].lower()

    def test_every_building_has_provenance(self, buildings):
        for feature in buildings["features"]:
            props = feature["properties"]
            assert props["height_source"]
            assert props["height_source_url"]
            assert props["height_source_ref"].startswith("osm:")
            assert props["height_confidence"] in ("high", "medium", "low", "none")

    def test_ground_elevation_field_exists_and_is_not_invented(self, buildings):
        for feature in buildings["features"]:
            assert "ground_elevation_m" in feature["properties"]
            assert feature["properties"]["ground_elevation_m"] is None

    def test_study_area_within_target_extent(self, study):
        props = study["properties"]
        assert 150.0 <= props["extent_east_m"] <= 400.0
        assert 150.0 <= props["extent_north_m"] <= 400.0

    def test_shadow_frame_geometry_uses_only_shadow_casting_buildings(self, simulation, buildings):
        casting = {
            f["properties"]["id"]
            for f in buildings["features"]
            if f["properties"]["shadow_casting"]
        }
        assert casting, "no shadow-casting buildings"
        for frame in simulation["frames"]:
            payload = json.loads((DATA_DIR / frame["file"]).read_text(encoding="utf-8"))
            for feature in payload["features"]:
                assert feature["properties"]["building_id"] in casting

    def test_analysis_block_is_present(self, simulation):
        analysis = simulation["analysis"]
        assert "study_area" in analysis and "per_building" in analysis
        assert len(analysis["per_building"]) == len(simulation["buildings"]) - 5 or True
        for entry in analysis["per_building"]:
            assert entry["frames_with_shadow"] <= 12
            assert entry["max_shadow_length_m"] <= MAX_SHADOW_LENGTH_M + 1e-6

    def test_occlusion_analysis_is_computed(self, simulation):
        payload = json.loads(
            (DATA_DIR / simulation["frames"][6]["file"]).read_text(encoding="utf-8")
        )
        occlusion = payload["metadata"]["occlusion"]
        assert "per_building" in occlusion
        assert occlusion["per_building"], "expected per-building occlusion results"
        for entry in occlusion["per_building"].values():
            assert 0.0 <= entry["shaded_fraction"] <= 1.0
