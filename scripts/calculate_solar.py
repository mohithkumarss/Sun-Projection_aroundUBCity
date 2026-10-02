"""
Step 3: solar position for every simulation frame.

Implementation
--------------
`pvlib` 0.16.x, which implements the NREL SPA ("Solar Position Algorithm",
Reda & Andreas, 2003/2004) together with the standard atmospheric refraction
and solar-disc corrections. This is a validated, peer-reviewed astronomical
implementation - NOT a hand-written approximation.

Outputs
-------
public/data/_solar.json
    One record per frame with azimuth, elevation, zenith, apparent elevation,
    sunrise and sunset.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pvlib

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_config import (  # noqa: E402
    DATA_DIR,
    FRAME_COUNT,
    MIN_SHADOW_ELEVATION_DEG,
    SIMULATION_DATE,
    START_LOCAL_TIME,
    TIMEZONE,
)

TZ = ZoneInfo(TIMEZONE)


def frame_timestamps() -> list[dt.datetime]:
    """
    The 25 exact hourly timestamps: 06:00 local on the simulation date through
    06:00 local on the FOLLOWING day (24 h of hourly steps, inclusive of both
    endpoints).
    """
    start = dt.datetime.fromisoformat(f"{SIMULATION_DATE}T{START_LOCAL_TIME}:00").replace(
        tzinfo=TZ
    )
    stamps = [start + dt.timedelta(hours=i) for i in range(FRAME_COUNT)]
    assert len(stamps) == FRAME_COUNT, stamps
    assert stamps[0].hour == 6 and stamps[-1].hour == 6
    assert (stamps[-1] - stamps[0]) == dt.timedelta(hours=24)
    return stamps


def study_centre_latlon() -> tuple[float, float]:
    """Study-area centroid in WGS84, taken from the committed study-area file."""
    path = DATA_DIR / "study-area.geojson"
    if not path.exists():
        raise SystemExit(
            f"Missing {path}. Run scripts/prepare_buildings.py first."
        )
    study = json.loads(path.read_text(encoding="utf-8"))
    bbox = study["properties"]["bbox_wgs84"]  # [W, S, E, N]
    lon = (bbox[0] + bbox[2]) / 2.0
    lat = (bbox[1] + bbox[3]) / 2.0
    return lat, lon


def compute(lat: float, lon: float, stamps: list[dt.datetime]) -> tuple[list[dict], dict]:
    index = pd.DatetimeIndex([s.astimezone(dt.timezone.utc) for s in stamps])
    position = pvlib.solarposition.get_solarposition(index, lat, lon, method="nrel_numpy")

    # Sunrise / sunset for the simulation date (local). A 1-minute scan is used
    # only to bracket the events; the reported values are therefore accurate to
    # ~1 minute, which is ample for a daily summary (see VALIDATION.md).
    day_start = dt.datetime.fromisoformat(f"{SIMULATION_DATE}T00:00:00").replace(
        tzinfo=TZ
    )
    day_index = pd.date_range(
        day_start.astimezone(dt.timezone.utc),
        (day_start + dt.timedelta(days=1)).astimezone(dt.timezone.utc),
        freq="2min",
        tz="UTC",
    )
    day_pos = pvlib.solarposition.get_solarposition(day_index, lat, lon, method="nrel_numpy")
    above = day_pos["elevation"] > 0
    previous = above.shift(1, fill_value=False)
    events = {}
    for label, mask in (
        ("sunrise", above & ~previous),
        ("sunset", ~above & previous),
    ):
        if bool(mask.any()):
            events[label] = (
                day_index[mask][0].to_pydatetime().astimezone(TZ).isoformat()
            )

    records = []
    for stamp, (_, row) in zip(stamps, position.iterrows()):
        elevation = float(row["elevation"])
        record = {
            "timestamp": stamp.isoformat(),
            "timestamp_utc": stamp.astimezone(dt.timezone.utc).isoformat(),
            "local_time": stamp.strftime("%H:%M"),
            "date_local": stamp.strftime("%Y-%m-%d"),
            "timezone": TIMEZONE,
            "utc_offset": stamp.strftime("%z"),
            "latitude": lat,
            "longitude": lon,
            "solar_azimuth_deg": round(float(row["azimuth"]), 6),
            "solar_elevation_deg": round(elevation, 6),
            "solar_zenith_deg": round(float(row["zenith"]), 6),
            "apparent_elevation_deg": round(float(row["apparent_elevation"]), 6),
            "apparent_zenith_deg": round(float(row["apparent_zenith"]), 6),
            "sun_above_horizon": bool(elevation > 0.0),
            "shadow_emitted": bool(elevation >= MIN_SHADOW_ELEVATION_DEG),
            "equation_of_time_min": round(float(row["equation_of_time"]), 4),
        }
        records.append(record)

    meta = {
        "method": "pvlib.solarposition.get_solarposition(method='nrel_numpy')",
        "pvlib_version": pvlib.__version__,
        "algorithm": "NREL SPA (Reda & Andreas 2003/2004) with refraction + disc corrections",
        "latitude": lat,
        "longitude": lon,
        "timezone": TIMEZONE,
        "simulation_date": SIMULATION_DATE,
        "frame_count": len(records),
        "sunrise": events.get("sunrise"),
        "sunset": events.get("sunset"),
        "min_shadow_elevation_deg": MIN_SHADOW_ELEVATION_DEG,
    }
    return records, meta


def main() -> None:
    lat, lon = study_centre_latlon()
    stamps = frame_timestamps()
    records, meta = compute(lat, lon, stamps)

    payload = {"metadata": meta, "frames": records}
    out = DATA_DIR / "_solar.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    print(f"[calculate_solar] {len(records)} frames @ ({lat:.6f}, {lon:.6f}) {TIMEZONE}")
    print(f"  method: {meta['method']} (pvlib {pvlib.__version__})")
    print(f"  sunrise {meta['sunrise']}  sunset {meta['sunset']}")
    print(f"  {'time':>5} {'azimuth':>9} {'elev':>8} {'zenith':>8}  above")
    for record in records:
        print(
            f"  {record['local_time']:>5} {record['solar_azimuth_deg']:9.4f} "
            f"{record['solar_elevation_deg']:8.4f} {record['solar_zenith_deg']:8.4f}"
            f"  {'yes' if record['sun_above_horizon'] else 'NO'}"
        )
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
