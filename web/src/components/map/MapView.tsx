"use client";

/**
 * Mapbox GL JS visualisation layer.
 *
 * Design constraints from the brief:
 *  - the base map is Mapbox Light and stays visually quiet
 *  - shadows are drawn as real, pre-computed GeoJSON polygons, never as a
 *    lighting effect
 *  - 2D and 3D share one map instance and one selected timestamp
 *  - no expensive work happens on slider movement: the geometry for the
 *    selected frame is already in memory, so moving the slider only swaps a
 *    map source's data
 */

import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import type { Map as MapboxMap, MapMouseEvent } from "mapbox-gl";
import { MAPBOX_STYLE_LIGHT } from "@/lib/mapbox/token";
import type {
  BuildingFeature,
  BuildingsCollection,
  MapMode,
  ShadowFeature,
  SimulationFrame,
  StudyArea,
} from "@/lib/types";

// Layer and source identifiers.
const SRC_SHADOW = "shadow-geometry";
const SRC_SHADOW_OUTLINE = "shadow-geometry-outline";
const SRC_BUILDINGS = "buildings-3d";
const SRC_BUILDINGS_2D = "buildings-2d";
const SRC_STUDY_AREA = "study-area";

const FILL_LAYER = "shadow-fill";
const OUTLINE_LAYER = "shadow-outline";
const BUILDING_LAYER_3D = "buildings-extruded";
const BUILDING_LAYER_2D = "buildings-flat";
const BUILDING_LINE_2D = "buildings-line";
const STUDY_LAYER = "study-area-line";

export interface MapViewProps {
  token: string;
  mode: MapMode;
  frame: SimulationFrame;
  shadows: ShadowFeature[];
  buildings: BuildingsCollection;
  studyArea: StudyArea;
  selectedBuildingId: string | null;
  onSelectBuilding: (buildingId: string | null) => void;
  maxShadowLengthM: number;
  minShadowElevationDeg: number;
  /** Reported upward so the failure state lives with the app, not in the map. */
  onMapError: (message: string | null) => void;
  mapError: string | null;
}

/** View state derived from the study-area bounding box. */
function useViewForStudyArea(studyArea: StudyArea) {
  return useMemo(() => {
    const [west, south, east, north] = studyArea.properties.bbox_wgs84;
    const centre: [number, number] = [
      (west + east) / 2,
      (south + north) / 2,
    ];
    return {
      centre,
      // The study area is ~270 x 310 m, so a 16.5 zoom frames it with a small
      // margin. Close enough to read individual buildings, far enough that the
      // long low-sun shadows (up to the 1000 m clip) stay partly visible.
      zoom2d: 16.5,
      pitch3d: 58,
      bearing3d: -18,
      distance3d: 620,
    };
  }, [studyArea]);
}

export default function MapView({
  token,
  mode,
  frame,
  shadows,
  buildings,
  studyArea,
  selectedBuildingId,
  onSelectBuilding,
  maxShadowLengthM,
  minShadowElevationDeg,
  onMapError,
  mapError,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const [loaded, setLoaded] = useState(false);
  const view = useViewForStudyArea(studyArea);

  // Keep the latest handlers in refs so the map is initialised exactly once and
  // is never torn down when a handler identity changes.
  const onSelectRef = useRef(onSelectBuilding);
  const onErrorRef = useRef(onMapError);

  useEffect(() => {
    onSelectRef.current = onSelectBuilding;
    onErrorRef.current = onMapError;
  }, [onSelectBuilding, onMapError]);

  // ---------------------------------------------------------------------
  // Static data: prepared once, then handed to the map as immutable blobs.
  // ---------------------------------------------------------------------
  const buildingGeoJson = useMemo<GeoJSON.FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: buildings.features.map((feature: BuildingFeature) => ({
        type: "Feature",
        id: feature.id,
        geometry: feature.geometry,
        properties: {
          id: feature.properties.id,
          name: feature.properties.name,
          height_m: feature.properties.height_m ?? 0,
          height_method: feature.properties.height_method,
          shadow_casting: feature.properties.shadow_casting,
        },
      })),
    }),
    [buildings],
  );

  const studyGeoJson = useMemo<GeoJSON.FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: studyArea.features,
    }),
    [studyArea],
  );

  const shadowGeoJson = useMemo<GeoJSON.FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: shadows as unknown as GeoJSON.Feature[],
    }),
    [shadows],
  );

  // ---------------------------------------------------------------------
  // Map initialisation (runs once)
  // ---------------------------------------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    mapboxgl.accessToken = token;

    let map: MapboxMap;
    try {
      map = new mapboxgl.Map({
        container: containerRef.current,
        style: MAPBOX_STYLE_LIGHT,
        center: view.centre,
        zoom: view.zoom2d,
        attributionControl: true,
        // Keeps the canvas predictable on HiDPI displays.
        antialias: true,
      });
    } catch (error) {
      onErrorRef.current(`Mapbox GL could not initialise: ${String(error)}`);
      return;
    }

    mapRef.current = map;
    map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "top-right");
    map.addControl(new mapboxgl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");

    const onError = (event: { error?: Error }) => {
      const message = event.error?.message ?? "unknown Mapbox error";
      // Style/tile 404s and token-scope errors surface here.
      onErrorRef.current(
        /token|unauthorized|401|403/i.test(message)
          ? `Mapbox rejected the access token. ${message} — check that NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN is valid and authorised for the Mapbox Light style.`
          : `Mapbox error: ${message}`,
      );
    };
    map.on("error", onError);

    map.on("load", () => {
      // Study-area boundary.
      map.addSource(SRC_STUDY_AREA, { type: "geojson", data: studyGeoJson });
      map.addLayer({
        id: STUDY_LAYER,
        type: "line",
        source: SRC_STUDY_AREA,
        paint: {
          "line-color": "#1f4b99",
          "line-width": 1.5,
          "line-dasharray": [3, 2],
          "line-opacity": 0.85,
        },
      });

      // Building footprints, used by the 2D mode and as the click target in
      // both modes (the 3D extrusion is not queryable, so the footprint layer
      // stays present in 3D too).
      map.addSource(SRC_BUILDINGS_2D, { type: "geojson", data: buildingGeoJson });
      map.addLayer({
        id: BUILDING_LAYER_2D,
        type: "fill",
        source: SRC_BUILDINGS_2D,
        paint: {
          "fill-color": [
            "case",
            ["==", ["get", "shadow_casting"], true],
            "#c9c9c2",
            "#e0e0da",
          ],
          "fill-opacity": 0.85,
        },
      });
      map.addLayer({
        id: BUILDING_LINE_2D,
        type: "line",
        source: SRC_BUILDINGS_2D,
        paint: {
          "line-color": [
            "case",
            ["==", ["get", "id"], selectedBuildingId ?? "__none__"],
            "#1f4b99",
            "#6f6f68",
          ],
          "line-width": [
            "case",
            ["==", ["get", "id"], selectedBuildingId ?? "__none__"],
            2.5,
            0.8,
          ],
        },
      });

      // 3D extrusion. Height is a real datum: buildings whose height is
      // unresolved have height_m = 0 and are therefore not extruded, which is
      // honest rather than showing a guessed massing.
      map.addSource(SRC_BUILDINGS, {
        type: "geojson",
        data: buildingGeoJson,
      });
      map.addLayer({
        id: BUILDING_LAYER_3D,
        type: "fill-extrusion",
        source: SRC_BUILDINGS,
        minzoom: 0,
        paint: {
          "fill-extrusion-color": "#b9b9b1",
          "fill-extrusion-height": ["get", "height_m"],
          "fill-extrusion-base": 0,
          "fill-extrusion-opacity": 0.92,
        },
      });

      // Shadow geometry: a semi-transparent dark neutral fill plus a thin
      // outline so the polygon edge stays legible over the light basemap.
      map.addSource(SRC_SHADOW, { type: "geojson", data: shadowGeoJson });
      map.addLayer({
        id: FILL_LAYER,
        type: "fill",
        source: SRC_SHADOW,
        paint: {
          "fill-color": "#101418",
          "fill-opacity": 0.34,
        },
      });
      map.addSource(SRC_SHADOW_OUTLINE, { type: "geojson", data: shadowGeoJson });
      map.addLayer({
        id: OUTLINE_LAYER,
        type: "line",
        source: SRC_SHADOW_OUTLINE,
        paint: {
          "line-color": "#0a0d10",
          "line-width": 0.9,
          "line-opacity": 0.5,
        },
      });

      setLoaded(true);
    });

    // Building click: footprint layer is the hit target in both modes.
    const handleClick = (event: MapMouseEvent) => {
      const features = map.queryRenderedFeatures(event.point, {
        layers: [BUILDING_LINE_2D],
      });
      const first = features[0];
      const id = first?.properties?.id;
      onSelectRef.current(typeof id === "string" ? id : null);
    };
    map.on("click", BUILDING_LINE_2D, handleClick);

    const handleMouse = (event: MapMouseEvent) => {
      const features = map.queryRenderedFeatures(event.point, {
        layers: [BUILDING_LINE_2D],
      });
      map.getCanvas().style.cursor = features.length ? "pointer" : "";
    };
    map.on("mousemove", BUILDING_LINE_2D, handleMouse);

    // Clicking empty ground clears the selection.
    const handleBackground = () => onSelectRef.current(null);
    map.on("click", (event) => {
      const features = map.queryRenderedFeatures(event.point, {
        layers: [BUILDING_LINE_2D, FILL_LAYER],
      });
      if (features.length === 0) handleBackground();
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Intentionally initialised once: the token and study area are stable for
    // the lifetime of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // ---------------------------------------------------------------------
  // 2D / 3D mode
  // ---------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;

    const is3d = mode === "3d";

    // Visibility is toggled rather than re-created so switching modes keeps
    // the camera, the selected timestamp, and the current selection intact.
    const setVisibility = (layerId: string, visible: boolean) => {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
      }
    };
    setVisibility(BUILDING_LAYER_2D, !is3d);
    setVisibility(BUILDING_LINE_2D, !is3d);
    setVisibility(BUILDING_LAYER_3D, is3d);

    if (is3d) {
      map.easeTo({
        pitch: view.pitch3d,
        bearing: view.bearing3d,
        zoom: view.zoom2d + 0.4,
        duration: 700,
      });
    } else {
      map.easeTo({ pitch: 0, bearing: 0, zoom: view.zoom2d, duration: 700 });
    }
  }, [mode, loaded, view]);

  // ---------------------------------------------------------------------
  // Frame swap: only the shadow source data changes. This is the only work
  // performed on a slider movement, and it is a source setData of already
  // computed geometry.
  // ---------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;

    const source = map.getSource(SRC_SHADOW) as mapboxgl.GeoJSONSource | undefined;
    if (source) source.setData(shadowGeoJson as GeoJSON.FeatureCollection);

    const outline = map.getSource(SRC_SHADOW_OUTLINE) as
      | mapboxgl.GeoJSONSource
      | undefined;
    if (outline) outline.setData(shadowGeoJson as GeoJSON.FeatureCollection);
  }, [shadowGeoJson, loaded]);

  // ---------------------------------------------------------------------
  // Selection highlight
  // ---------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded || !map.getLayer(BUILDING_LINE_2D)) return;
    map.setPaintProperty(BUILDING_LINE_2D, "line-color", [
      "case",
      ["==", ["get", "id"], selectedBuildingId ?? "__none__"],
      "#1f4b99",
      "#6f6f68",
    ]);
    map.setPaintProperty(BUILDING_LINE_2D, "line-width", [
      "case",
      ["==", ["get", "id"], selectedBuildingId ?? "__none__"],
      2.5,
      0.8,
    ]);
  }, [selectedBuildingId, loaded]);

  const error = mapError;

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      {!loaded && !error && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center bg-background/70">
          <p className="tnum text-sm text-muted">Loading Mapbox Light…</p>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 grid place-items-center bg-background p-6">
          <div className="max-w-md border border-panel-border bg-panel p-4">
            <h2 className="text-sm font-semibold text-warn">Map unavailable</h2>
            <p className="mt-2 text-sm text-muted">{error}</p>
          </div>
        </div>
      )}

      {/* Night overlay: an explicit, non-decorative state indicator. */}
      {!frame.shadow_emitted && loaded && !error && (
        <div className="pointer-events-none absolute left-1/2 top-4 -translate-x-1/2">
          <div className="tnum border border-night/30 bg-night/90 px-3 py-1.5 text-xs font-medium text-white">
            {frame.sun_above_horizon
              ? `Sun elevation ${frame.solar_elevation_deg.toFixed(2)}° is below the ${minShadowElevationDeg}° emission threshold`
              : "Night — sun below the horizon, no solar shadow"}
          </div>
        </div>
      )}

      {frame.truncated && loaded && !error && (
        <div className="pointer-events-none absolute left-1/2 top-4 -translate-x-1/2">
          <div className="tnum border border-warn/40 bg-warn/90 px-3 py-1.5 text-xs font-medium text-white">
            Shadow clipped at {maxShadowLengthM} m — low sun
          </div>
        </div>
      )}
    </div>
  );
}
