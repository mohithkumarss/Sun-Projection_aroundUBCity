"""
One-command rebuild of the entire research dataset.

    .venv/bin/python scripts/run_pipeline.py

Stages
------
    1. acquire      fetch real OpenStreetMap building data
    2. normalize    geometry repair, height provenance, study area
    3. solar        25 frames of NREL SPA solar position (pvlib)
    4. shadows      geometric shadow projection in EPSG:32643
    5. validate     scientific + geometric test suite
    6. report       write research/VALIDATION.md

The pipeline FAILS LOUDLY. If live source data cannot be obtained, or if any
validation test fails, it exits non-zero rather than emitting a partial or
fabricated dataset.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
RESEARCH = PROJECT_ROOT / "research"
PYTHON = sys.executable


def run(label: str, argv: list[str], cwd: Path = PROJECT_ROOT) -> None:
    print(f"\n{'=' * 72}\n>>> {label}\n{'=' * 72}")
    started = time.time()
    result = subprocess.run(argv, cwd=cwd)
    elapsed = time.time() - started
    if result.returncode != 0:
        print(
            f"\n!!! STAGE FAILED: {label} (exit {result.returncode}, {elapsed:.1f}s)\n"
            "    The dataset has NOT been updated. No substitute data is generated."
        )
        raise SystemExit(result.returncode)
    print(f"<<< {label} ok ({elapsed:.1f}s)")


def main() -> None:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    started = time.time()

    run("1/6 acquire OpenStreetMap data", [PYTHON, "scripts/fetch_buildings.py"])
    run("2/6 normalize buildings + study area", [PYTHON, "scripts/prepare_buildings.py"])
    run("3/6 solar positions (NREL SPA)", [PYTHON, "scripts/calculate_solar.py"])
    run("4/6 shadow geometry (EPSG:32643)", [PYTHON, "scripts/generate_shadows.py"])
    run("5/6 validation suite", [PYTHON, "-m", "pytest", "tests", "-q"])
    run("6/6 validation report", [PYTHON, "scripts/validate_simulation.py"])

    # Publish the dataset into the Next.js app. Done only after validation
    # passes, so the web app can never serve a dataset that failed its checks.
    web_public = PROJECT_ROOT / "web" / "public" / "data"
    if (PROJECT_ROOT / "web").is_dir():
        print(f"\n>>> publishing dataset to {web_public}")
        if web_public.exists():
            shutil.rmtree(web_public)
        shutil.copytree(PROJECT_ROOT / "public" / "data", web_public)
        print(f"<<< dataset published")

    print(f"\n{'=' * 72}")
    print(f"PIPELINE COMPLETE in {time.time() - started:.1f}s")
    print(f"  dataset:  public/data/  (mirrored to web/public/data/)")
    print(f"  reports:  research/")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
