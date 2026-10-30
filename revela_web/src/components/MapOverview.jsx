import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Circle, Data, GoogleMap, Marker, Polyline } from "@react-google-maps/api";
import { useNavigate } from "react-router-dom";
import AnalyticsInfoTip from "./AnalyticsInfoTip";
import {
  getFlagsRequest,
  getAnalyticsHotspotsRequest,
  getBarangayOverviewRequest,
} from "../services/api";
import { useGoogleMapsScript } from "../utils/googleMaps";
import { OverviewMapSkeleton } from "./AnalyticsLoadingLayouts";
import { REVELA_MAP_ID } from "../utils/mapStyles";
import { useTheme } from "../context/themeContext";
import { FLAG_COLORS } from "./flagColors";
import {
  getBarangayIdForGeoJsonName,
  getGeoJsonCentroid,
  getShortBarangayLabel,
  normalizeGeoJsonWinding,
} from "./barangayMapMapping";
import { createBarangayMapPopup } from "./barangayMapPopup";
import {
  BARANGAY_MAP_INTERACTION_EVENTS,
  fitMapToGeoJsonFeatures,
  MIN_BARANGAY_MAP_ZOOM,
  shouldFitBarangayMap,
} from "./barangayMapFit";
import {
  buildBarangayOverviewFilters,
  getBarangayTopTotals,
  getMapPinBuckets,
  lineOfBusinessKeyAfterSectorChange,
  lineOfBusinessOptionsForSector,
  quantileBreaks,
  quantileClass,
  quantileRangeLabels,
  registryCategoryColor,
  registryCategoryColorsForRows,
  sortRegistryBreakdownRows,
} from "./barangayOverviewPresentation";
import {
  hotspotOverlayRadius,
  hotspotBadgeTier,
  hotspotCirclePath,
  hotspotGroupLocation,
  hotspotGroupMapPath,
  hotspotMethodNote,
  fetchHotspotClusterPins,
  hotspotClusterDetails,
  hotspotTooltipLabel,
  hotspotViewTransition,
  hotspotRequestParams,
  hotspotPeriodLabel,
  hotspotResponseMatchesPeriod,
  hotspotScanNote,
  hotspotSummary,
} from "./hotspotPresentation";
import "../styles/MapOverview.css";
import "../styles/barangayMapPopup.css";

const MAP_CENTER = { lat: 13.9667, lng: 121.1167 };
const MAP_MIN_ZOOM = 12;
const MAP_MAX_ZOOM = 20;
const MAX_SELECTED_BARANGAY_ZOOM = 16;
const CHOROPLETH_COLORS = {
  registered: ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
  inspections: ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
};
const DARK_CHOROPLETH_COLORS = {
  registered: ["#174036", "#1c6952", "#258c65", "#39ae7b", "#6dd6a1"],
  inspections: ["#172d4b", "#1d4772", "#286395", "#377fb7", "#68a8da"],
};
const EMPTY_BARANGAY_ROWS = Object.freeze([]);
const EMPTY_OVERVIEW_OPTIONS = Object.freeze([]);
const REGISTRY_DIMENSIONS = [
  { key: "business_size", label: "By size" },
  { key: "business_type", label: "By type" },
  { key: "registration_type", label: "By registration type" },
  { key: "display_sector", label: "By sector" },
];
const STATUS_COLORS = {
  registered_on_map: "#2563eb",
  detected_not_in_registry: "#f97316",
  detection_with_business_id: "#7c3aed",
  added_by_inspector: "#0f9f8f",
  other_source: "#64748b",
  pending: "#f97316",
  waiting_for_review: "#3b82f6",
  verified: "#10b981",
  Green: "#10b981",
  Yellow: "#f59e0b",
  Red: "#ef4444",
};

function shortBarangay(name = "") {
  return name
    .replace(/^District (.+?)(?: \(Pob\.\))?$/, "Brgy. $1")
    .replace(/^Barangay /, "Brgy. ");
}

function totalOf(rows = []) {
  return rows.reduce((total, row) => total + Number(row.count || 0), 0);
}

function CountsBar({ rows, emptyMessage }) {
  const total = totalOf(rows);
  if (!total) return <p className="map-overview-empty">{emptyMessage}</p>;
  return (
    <>
      <div className="map-overview-stacked-bar" role="img"
        aria-label={rows.map((row) => `${row.label}: ${row.count}`).join(", ")}>
        {rows.map((row) => (
          <span key={row.value} title={`${row.label}: ${row.count}`}
            style={{
              width: `${(Number(row.count) / total) * 100}%`,
              background: row.color || registryCategoryColor("fallback", row.value),
            }} />
        ))}
      </div>
      <ul className="map-overview-count-list">
        {rows.map((row) => (
          <li key={row.value}>
            <span className="map-overview-count-swatch"
              style={{ background: row.color || registryCategoryColor("fallback", row.value) }} />
            <span className="map-overview-count-label">{row.label}</span>
            <strong>{Number(row.count).toLocaleString()}</strong>
            <span className="map-overview-count-percent">
              {((Number(row.count) / total) * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function useBarangayOverview(token, filters, datePreset) {
  const [retry, setRetry] = useState(0);
  const filterKey = JSON.stringify(filters || {});
  const requestKey = `${token}:${filterKey}:${datePreset}:${retry}`;
  const [snapshot, setSnapshot] = useState({
    key: null,
    overview: null,
    error: "",
  });
  const loading = snapshot.key !== requestKey;
  const overview = snapshot.overview;
  const error = snapshot.key === requestKey ? snapshot.error : "";

  useEffect(() => {
    const controller = new AbortController();
    const requestFilters = buildBarangayOverviewFilters(
      JSON.parse(filterKey),
      datePreset,
    );
    getBarangayOverviewRequest(token, requestFilters, { signal: controller.signal })
      .then((result) => {
        if (!Array.isArray(result?.barangays) || result.barangays.length !== 16
          || !result?.overall) {
          throw new Error("The barangay overview is incomplete.");
        }
        setSnapshot({ key: requestKey, overview: result, error: "" });
      })
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setSnapshot(previous => ({
            key: requestKey,
            overview: previous.overview,
            error: requestError.message || "The barangay overview could not be loaded.",
          }));
        }
      });
    return () => controller.abort();
  }, [token, filterKey, datePreset, retry, requestKey]);

  return {
    overview,
    loading,
    error,
    retry: () => setRetry((previous) => previous + 1),
  };
}

export default function MapOverview({ token, filters }) {
  const navigate = useNavigate();
  const { isDark } = useTheme();
  const [datePreset, setDatePreset] = useState("all");
  const [mapView, setMapView] = useState("registered");
  const [showHotspots, setShowHotspots] = useState(false);
  const [selectedClusterId, setSelectedClusterId] = useState(null);
  const [selectedClusterRequestKey, setSelectedClusterRequestKey] = useState("");
  const [clusterDetailRetry, setClusterDetailRetry] = useState(0);
  const [hotspotRetry, setHotspotRetry] = useState(0);
  const [mapZoom, setMapZoom] = useState(13);
  const [clusterPinsState, setClusterPinsState] = useState({
    key: "",
    pins: [],
    loading: false,
    error: "",
  });
  const [hotspotState, setHotspotState] = useState({
    requestKey: "",
    data: null,
    error: "",
  });
  const [selectedBarangayId, setSelectedBarangayId] = useState(null);
  const [selectedSectorKey, setSelectedSectorKey] = useState("");
  const [selectedLineOfBusinessKey, setSelectedLineOfBusinessKey] = useState("");
  const [legendOpen, setLegendOpen] = useState(false);
  const [hoveredBarangayId, setHoveredBarangayId] = useState(null);
  const [activeDimension, setActiveDimension] = useState("business_size");
  const [pinView, setPinView] = useState("all");
  const [boundaryError, setBoundaryError] = useState(false);
  const legendToggleRef = useRef(null);
  const legendPanelRef = useRef(null);
  const dataLayerRef = useRef(null);
  const hoverInfoWindowRef = useRef(null);
  const styleFeatureRef = useRef(null);
  const mapRef = useRef(null);
  const boundaryFeaturesRef = useRef([]);
  const sourceGeoJsonFeaturesRef = useRef([]);
  const labelMarkersRef = useRef([]);
  const mapIdleRef = useRef(false);
  const mapIdleListenerRef = useRef(null);
  const resizeObserverRef = useRef(null);
  const mapInteractionListenersRef = useRef([]);
  const fitFrameRef = useRef(null);
  const pendingSelectionFitRef = useRef(false);
  const userMapInteractedRef = useRef(false);
  const programmaticMapChangeRef = useRef(false);
  const initialFitCompletedRef = useRef(false);
  const containerSizeObservedRef = useRef(false);
  const lastFitSignatureRef = useRef("");
  const lastMapSizeRef = useRef("");
  const fitBarangayBoundsRef = useRef(null);
  const updateLabelVisibilityRef = useRef(null);
  const { isLoaded, loadError } = useGoogleMapsScript();
  const overviewFilters = useMemo(
    () => ({
      ...filters,
      display_sector: selectedSectorKey,
      line_of_business_key: selectedLineOfBusinessKey,
    }),
    [filters, selectedLineOfBusinessKey, selectedSectorKey],
  );
  const { overview, loading, error, retry } = useBarangayOverview(
    token,
    overviewFilters,
    datePreset,
  );
  const hotspotRequest = useMemo(
    () => hotspotRequestParams(datePreset),
    [datePreset],
  );
  const hotspotRequestKey = `${token ? "authenticated" : "anonymous"}:${hotspotRequest.date_preset}:${hotspotRetry}`;
  useEffect(() => {
    if (!token) return undefined;
    const controller = new AbortController();
    getAnalyticsHotspotsRequest(token, hotspotRequest.date_preset, {
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return;
        if (!hotspotResponseMatchesPeriod(data, hotspotRequest.date_preset)) {
          throw new Error(
            `Hotspot response period did not match ${hotspotPeriodLabel(hotspotRequest.date_preset)}.`,
          );
        }
        setHotspotState({ requestKey: hotspotRequestKey, data, error: "" });
      })
      .catch((requestError) => {
        if (!controller.signal.aborted && requestError.name !== "AbortError") {
          setHotspotState({
            requestKey: hotspotRequestKey,
            data: null,
            error: requestError.message || "Hotspot data could not be loaded.",
          });
        }
      });
    return () => controller.abort();
  }, [hotspotRequest.date_preset, hotspotRequestKey, hotspotRetry, token]);
  const displaySectorOptions = overview?.display_sectors || EMPTY_OVERVIEW_OPTIONS;
  const allLineOfBusinessOptions = (
    overview?.line_of_business_options || EMPTY_OVERVIEW_OPTIONS
  );
  const lineOfBusinessOptions = useMemo(
    () => lineOfBusinessOptionsForSector(
      allLineOfBusinessOptions,
      selectedSectorKey,
    ),
    [allLineOfBusinessOptions, selectedSectorKey],
  );
  const lineOfBusinessOptionsBySector = useMemo(() => (
    displaySectorOptions.map((sector) => ({
      ...sector,
      options: lineOfBusinessOptions.filter(
        (option) => option.sector_key === sector.value,
      ),
    })).filter((sector) => sector.options.length > 0)
  ), [displaySectorOptions, lineOfBusinessOptions]);
  const selectedLineOfBusinessOption = allLineOfBusinessOptions.find(
    (option) => option.value === selectedLineOfBusinessKey,
  );

  const barangayRows = overview?.barangays || EMPTY_BARANGAY_ROWS;
  const rowsById = useMemo(() => new Map(
    barangayRows.map((row) => [Number(row.barangayID), row]),
  ), [barangayRows]);
  const selectedRow = selectedBarangayId == null
    ? null
    : rowsById.get(Number(selectedBarangayId));
  const panelData = selectedRow || overview?.overall;
  const mapCounts = useMemo(() => barangayRows.map((row) => Number(
    mapView === "registered" ? row.registry_total : row.inspections.total,
  )), [barangayRows, mapView]);
  const mapBreaks = useMemo(() => quantileBreaks(mapCounts), [mapCounts]);
  const mapRangeLabels = useMemo(
    () => quantileRangeLabels(mapBreaks, mapCounts),
    [mapBreaks, mapCounts],
  );
  const selectedDimension = REGISTRY_DIMENSIONS.find(
    (dimension) => dimension.key === activeDimension,
  ) || REGISTRY_DIMENSIONS[0];
  const dimensionRows = selectedDimension
    ? panelData?.registry?.[selectedDimension.key] || []
    : [];
  const dimensionColors = registryCategoryColorsForRows(activeDimension, dimensionRows);
  const coloredDimensionRows = sortRegistryBreakdownRows(
    activeDimension,
    dimensionRows,
  ).map((row) => ({
    ...row,
    color: dimensionColors.get(String(row.value ?? "Unknown")),
  }));
  const topTotals = getBarangayTopTotals(panelData);
  const mapRowsById = rowsById;
  const hotspotIsCurrent = hotspotState.requestKey === hotspotRequestKey;
  const hotspotData = hotspotIsCurrent ? hotspotState.data : null;
  const hotspotLoading = Boolean(token && !hotspotIsCurrent);
  const hotspotError = token
    ? hotspotIsCurrent ? hotspotState.error : ""
    : "Hotspot data requires an authenticated session.";
  const hotspotStats = hotspotSummary(hotspotData);
  const hotspotClusters = useMemo(
    () => [...(hotspotData?.clusters || [])].sort(
      (first, second) => Number(second.size) - Number(first.size),
    ),
    [hotspotData?.clusters],
  );
  const selectedCluster = showHotspots && selectedClusterRequestKey === hotspotRequestKey
    ? hotspotClusters.find(
      (cluster) => Number(cluster.cluster_id) === Number(selectedClusterId),
    ) || null
    : null;
  const hasSelectedCluster = Boolean(
    showHotspots
    && selectedClusterId != null
    && selectedClusterRequestKey === hotspotRequestKey,
  );
  const selectedClusterKey = selectedCluster
    ? `${hotspotRequestKey}:${selectedCluster.cluster_id}:${JSON.stringify(selectedCluster.log_ids || [])}`
    : "";
  const clusterPinsRequestKey = selectedClusterKey
    ? `${selectedClusterKey}:${clusterDetailRetry}`
    : "";
  const clusterPinsAreCurrent = clusterPinsState.key === clusterPinsRequestKey;
  const clusterDetail = selectedCluster
    ? hotspotClusterDetails(
      selectedCluster,
      clusterPinsAreCurrent ? clusterPinsState.pins : [],
    )
    : null;
  const selectedClusterMapPath = selectedCluster
    ? hotspotGroupMapPath(selectedCluster)
    : null;
  const scanNote = hotspotScanNote(
    hotspotData?.last_detection_run,
  );

  const fitHotspotCluster = useCallback((cluster, pins = []) => {
    const map = mapRef.current;
    const maps = window.google?.maps;
    if (!map || !maps?.LatLngBounds) return;

    const bounds = new maps.LatLngBounds();
    const locatedPins = pins.filter((pin) => (
      Number.isFinite(Number(pin.latitude))
      && Number.isFinite(Number(pin.longitude))
    ));
    if (locatedPins.length > 1) {
      locatedPins.forEach((pin) => bounds.extend({
        lat: Number(pin.latitude),
        lng: Number(pin.longitude),
      }));
    } else {
      const lat = Number(cluster?.centroid?.lat);
      const lng = Number(cluster?.centroid?.lng);
      const radius = Math.max(8, Number(cluster?.radius_m) || 0);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
      const latDelta = radius / 111_320;
      const lngDelta = radius / (111_320 * Math.max(0.01, Math.cos(lat * Math.PI / 180)));
      bounds.extend({ lat: lat - latDelta, lng: lng - lngDelta });
      bounds.extend({ lat: lat + latDelta, lng: lng + lngDelta });
    }

    map.fitBounds(bounds, { top: 72, right: 72, bottom: 72, left: 72 });
  }, []);

  const selectHotspotCluster = useCallback((cluster) => {
    setSelectedClusterId(Number(cluster.cluster_id));
    setSelectedClusterRequestKey(hotspotRequestKey);
    fitHotspotCluster(cluster);
  }, [fitHotspotCluster, hotspotRequestKey]);

  useEffect(() => {
    if (!selectedCluster || !token) return undefined;
    const controller = new AbortController();
    fetchHotspotClusterPins(
      getFlagsRequest,
      token,
      selectedCluster,
      controller.signal,
    )
      .then((pins) => {
        if (!controller.signal.aborted) {
          setClusterPinsState({
            key: clusterPinsRequestKey,
            pins,
            loading: false,
            error: "",
          });
        }
      })
      .catch((requestError) => {
        if (!controller.signal.aborted && requestError.name !== "AbortError") {
          setClusterPinsState({
            key: clusterPinsRequestKey,
            pins: [],
            loading: false,
            error: requestError.message || "Cluster pin details could not be loaded.",
          });
        }
      });
    return () => controller.abort();
  }, [clusterPinsRequestKey, selectedCluster, token]);

  useEffect(() => {
    if (!selectedCluster || !clusterPinsAreCurrent || !clusterPinsState.pins.length) return;
    fitHotspotCluster(selectedCluster, clusterPinsState.pins);
  }, [
    clusterPinsAreCurrent,
    clusterPinsState.pins,
    fitHotspotCluster,
    selectedCluster,
  ]);

  const clearSelectedCluster = useCallback(() => {
    setSelectedClusterId(null);
    setSelectedClusterRequestKey("");
  }, []);

  const toggleHotspots = useCallback(() => {
    const next = !showHotspots;
    const transition = hotspotViewTransition(next);
    setShowHotspots(transition.showHotspots);
    if (transition.mapView) setMapView(transition.mapView);
    setSelectedClusterId(null);
    setSelectedClusterRequestKey("");
  }, [showHotspots]);

  useEffect(() => {
    if (!isLoaded) return;
    const preventMapGestures = window.google?.maps?.OverlayView?.preventMapHitsAndGesturesFrom;
    if (preventMapGestures) {
      [legendToggleRef.current, legendPanelRef.current]
        .filter(Boolean)
        .forEach((element) => preventMapGestures(element));
    }
  }, [isLoaded, legendOpen]);

  const styleFeature = useCallback((feature) => {
    const featureName = feature.getProperty("ADM4_EN");
    const id = getBarangayIdForGeoJsonName(featureName);
    const row = mapRowsById.get(id);
    const count = Number(mapView === "registered"
      ? row?.registry_total || 0
      : row?.inspections?.total || 0);
    const isHovered = Number(hoveredBarangayId) === id;
    const isSelected = Number(selectedBarangayId) === id;
    const colorIndex = quantileClass(count, mapBreaks);
    return {
      fillColor: showHotspots
        ? isDark ? "#34d399" : "#166534"
        : colorIndex < 0
          ? isDark ? "#334155" : "#cbd5e1"
          : (isDark ? DARK_CHOROPLETH_COLORS : CHOROPLETH_COLORS)[mapView][colorIndex],
      fillOpacity: showHotspots ? (isDark ? 0.2 : 0.16) : 1,
      strokeColor: showHotspots
        ? isDark ? "#a7f3d0" : "#ffffff"
        : isSelected
          ? (isDark ? "#fbbf24" : "#0f172a")
          : isHovered ? "#f97316" : isDark ? "#94a3b8" : "#ffffff",
      strokeWeight: showHotspots ? 1.5 : isSelected ? 4 : isHovered ? 2 : 1,
      zIndex: showHotspots ? 0 : isSelected ? 100 : isHovered ? 10 : 0,
    };
  }, [hoveredBarangayId, isDark, mapBreaks, mapRowsById, mapView, selectedBarangayId, showHotspots]);

  useEffect(() => {
    styleFeatureRef.current = styleFeature;
    dataLayerRef.current?.setStyle((feature) => styleFeature(feature));
  }, [styleFeature]);

  const fitBarangayBounds = useCallback((force = false, selectionOverride) => {
    const map = mapRef.current;
    const container = map?.getDiv();
    if (!mapIdleRef.current || !map || !container?.clientWidth || !container?.clientHeight
      || !containerSizeObservedRef.current || !sourceGeoJsonFeaturesRef.current.length) return;
    if (!shouldFitBarangayMap({
      force,
      userInteracted: userMapInteractedRef.current,
    })) return;
    const size = `${container.clientWidth}x${container.clientHeight}`;
    const activeSelection = selectionOverride === undefined
      ? selectedBarangayId
      : selectionOverride;
    const selectedId = activeSelection == null ? null : Number(activeSelection);
    const signature = `${selectedId ?? "all"}:${size}`;
    if (!force && signature === lastFitSignatureRef.current) return;
    const geoJsonFeatures = selectedId == null
      ? sourceGeoJsonFeaturesRef.current
      : sourceGeoJsonFeaturesRef.current.filter((feature) => (
        getBarangayIdForGeoJsonName(feature.properties?.ADM4_EN) === selectedId
      ));
    if (!geoJsonFeatures.length) return;
    const isSelectionFit = selectedId != null;
    lastFitSignatureRef.current = signature;
    const padding = isSelectionFit ? 60 : 24;
    if (isSelectionFit) pendingSelectionFitRef.current = true;
    programmaticMapChangeRef.current = true;
    const fittedBounds = fitMapToGeoJsonFeatures(map, geoJsonFeatures, padding);
    if (!fittedBounds) {
      programmaticMapChangeRef.current = false;
      lastFitSignatureRef.current = "";
      return;
    }
    if (!initialFitCompletedRef.current) {
      initialFitCompletedRef.current = true;
    }
  }, [selectedBarangayId]);

  const scheduleBarangayFit = useCallback((force = false, selectionOverride) => {
    if (fitFrameRef.current != null) {
      window.cancelAnimationFrame(fitFrameRef.current);
    }
    fitFrameRef.current = window.requestAnimationFrame(() => {
      fitFrameRef.current = window.requestAnimationFrame(() => {
        fitFrameRef.current = null;
        fitBarangayBoundsRef.current?.(force, selectionOverride);
      });
    });
  }, []);

  const addBarangayLabels = useCallback((features, sourceFeatures) => {
    labelMarkersRef.current.forEach(({ marker }) => marker.setMap(null));
    labelMarkersRef.current = [];
    if (!mapRef.current || !window.google?.maps?.Marker) return;
    const sourceByName = new Map(sourceFeatures.map((feature) => [
      feature.properties.ADM4_EN,
      feature,
    ]));
    features.forEach((feature) => {
      const name = feature.getProperty("ADM4_EN");
      const id = getBarangayIdForGeoJsonName(name);
      if (id == null) return;
      const position = getGeoJsonCentroid(sourceByName.get(name));
      if (!position) return;
      const marker = new window.google.maps.Marker({
        map: mapRef.current,
        position,
        clickable: false,
        optimized: true,
        zIndex: 1000,
        icon: {
          path: window.google.maps.SymbolPath.CIRCLE,
          scale: 0,
        },
        label: {
          text: getShortBarangayLabel(feature.getProperty("ADM4_EN")),
          className: "map-overview-feature-label",
          color: isDark ? "#f8fafc" : "#0f172a",
        },
      });
      labelMarkersRef.current.push({ marker, barangayId: id });
    });
  }, [isDark]);

  const updateBarangayLabelVisibility = useCallback(() => {
    const zoom = mapRef.current?.getZoom() || 0;
    labelMarkersRef.current.forEach(({ marker, barangayId }) => {
      const visible = zoom >= 14
        || barangayId === Number(selectedBarangayId)
        || barangayId === Number(hoveredBarangayId);
      const label = marker.getLabel();
      const labelColor = isDark ? "#f8fafc" : "#0f172a";
      if (label && label.color !== labelColor) marker.setLabel({ ...label, color: labelColor });
      marker.setVisible(visible);
    });
  }, [hoveredBarangayId, selectedBarangayId, isDark]);

  useEffect(() => {
    fitBarangayBoundsRef.current = fitBarangayBounds;
  }, [fitBarangayBounds]);

  useEffect(() => {
    updateLabelVisibilityRef.current = updateBarangayLabelVisibility;
  }, [updateBarangayLabelVisibility]);

  useEffect(() => {
    updateBarangayLabelVisibility();
  }, [updateBarangayLabelVisibility]);

  useEffect(() => {
    scheduleBarangayFit(true);
  }, [scheduleBarangayFit, selectedBarangayId]);

  const markUserMapInteraction = useCallback(() => {
    if (initialFitCompletedRef.current && !programmaticMapChangeRef.current) {
      userMapInteractedRef.current = true;
    }
  }, []);

  const handleMapLoad = useCallback((map) => {
    mapRef.current = map;
    hoverInfoWindowRef.current = new window.google.maps.InfoWindow();
    if (boundaryFeaturesRef.current.length) {
      addBarangayLabels(
        boundaryFeaturesRef.current,
        sourceGeoJsonFeaturesRef.current,
      );
      updateLabelVisibilityRef.current?.();
    }
    mapIdleListenerRef.current = map.addListener("idle", () => {
      mapIdleRef.current = true;
      programmaticMapChangeRef.current = false;
      if (pendingSelectionFitRef.current) {
        pendingSelectionFitRef.current = false;
        if (map.getZoom() > MAX_SELECTED_BARANGAY_ZOOM) {
          programmaticMapChangeRef.current = true;
          map.setZoom(MAX_SELECTED_BARANGAY_ZOOM);
        }
      }
      scheduleBarangayFit();
      updateLabelVisibilityRef.current?.();
    });
    mapInteractionListenersRef.current = BARANGAY_MAP_INTERACTION_EVENTS.map(
      (eventName) => map.addListener(eventName, markUserMapInteraction),
    );
    if (typeof ResizeObserver !== "undefined") {
      resizeObserverRef.current = new ResizeObserver(() => {
        const container = map.getDiv();
        const size = `${container.clientWidth}x${container.clientHeight}`;
        containerSizeObservedRef.current = true;
        if (size === lastMapSizeRef.current) return;
        lastMapSizeRef.current = size;
        lastFitSignatureRef.current = "";
        scheduleBarangayFit();
      });
      resizeObserverRef.current.observe(map.getDiv());
    } else {
      containerSizeObservedRef.current = true;
    }
    scheduleBarangayFit();
  }, [addBarangayLabels, markUserMapInteraction, scheduleBarangayFit]);

  const handleDataLayerLoad = useCallback((dataLayer) => {
    dataLayerRef.current = dataLayer;
    setBoundaryError(false);
    dataLayer.setStyle((feature) => styleFeatureRef.current?.(feature) || {});
    fetch("/data/mataasnakahoy.json")
      .then((response) => {
        if (!response.ok) throw new Error("Boundary data request failed.");
        return response.json();
      })
      .then((geoJson) => {
        const normalizedGeoJson = normalizeGeoJsonWinding(geoJson);
        const features = dataLayer.addGeoJson(normalizedGeoJson);
        if (features.length !== 16) throw new Error("Expected all barangay boundaries.");
        boundaryFeaturesRef.current = features;
        sourceGeoJsonFeaturesRef.current = normalizedGeoJson.features;
        dataLayer.setStyle((feature) => styleFeatureRef.current?.(feature) || {});
        addBarangayLabels(features, normalizedGeoJson.features);
        scheduleBarangayFit();
        updateLabelVisibilityRef.current?.();
      })
      .catch(() => setBoundaryError(true));
  }, [addBarangayLabels, scheduleBarangayFit]);

  const handleDataLayerUnmount = useCallback(() => {
    labelMarkersRef.current.forEach(({ marker }) => marker.setMap(null));
    labelMarkersRef.current = [];
    boundaryFeaturesRef.current = [];
    sourceGeoJsonFeaturesRef.current = [];
    lastFitSignatureRef.current = "";
    initialFitCompletedRef.current = false;
    dataLayerRef.current = null;
  }, []);

  const handleMapUnmount = useCallback(() => {
    hoverInfoWindowRef.current?.close();
    hoverInfoWindowRef.current = null;
    mapIdleListenerRef.current?.remove();
    mapIdleListenerRef.current = null;
    mapInteractionListenersRef.current.forEach((listener) => listener.remove());
    mapInteractionListenersRef.current = [];
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (fitFrameRef.current != null) {
      window.cancelAnimationFrame(fitFrameRef.current);
      fitFrameRef.current = null;
    }
    mapIdleRef.current = false;
    containerSizeObservedRef.current = false;
    initialFitCompletedRef.current = false;
    userMapInteractedRef.current = false;
    programmaticMapChangeRef.current = false;
    lastFitSignatureRef.current = "";
    lastMapSizeRef.current = "";
    pendingSelectionFitRef.current = false;
    mapRef.current = null;
  }, []);

  const selectFeature = useCallback((event) => {
    const id = getBarangayIdForGeoJsonName(event.feature?.getProperty("ADM4_EN"));
    if (id != null) setSelectedBarangayId(id);
  }, []);

  const setHoveredFeature = useCallback((event) => {
    const id = getBarangayIdForGeoJsonName(event.feature?.getProperty("ADM4_EN"));
    setHoveredBarangayId(id);
    const row = mapRowsById.get(id);
    const count = Number(mapView === "registered"
      ? row?.registry_total || 0
      : row?.inspections?.total || 0);
    const content = createBarangayMapPopup({
      name: row?.barangayName || event.feature?.getProperty("ADM4_EN"),
      count,
      countLabel: mapView === "registered" ? "registered businesses" : "inspection reports",
    });
    hoverInfoWindowRef.current?.setContent(content);
    if (event.latLng) {
      hoverInfoWindowRef.current?.setPosition(event.latLng);
      hoverInfoWindowRef.current?.open({ map: mapRef.current });
    }
  }, [mapRowsById, mapView]);

  const clearHoveredFeature = useCallback(() => {
    setHoveredBarangayId(null);
    hoverInfoWindowRef.current?.close();
  }, []);

  const selectFromList = (event) => {
    const selectedId = event.target.value ? Number(event.target.value) : null;
    if (selectedId == null) {
      userMapInteractedRef.current = false;
      lastFitSignatureRef.current = "";
    }
    setSelectedBarangayId(selectedId);
  };

  const fitAllBarangays = () => {
    userMapInteractedRef.current = false;
    lastFitSignatureRef.current = "";
    setSelectedBarangayId(null);
    scheduleBarangayFit(true, null);
  };

  const pinRows = useMemo(() => {
    const allRows = getMapPinBuckets(panelData?.pins).map((row) => ({
      ...row,
      value: row.key,
      color: STATUS_COLORS[row.key],
    }));
    if (pinView === "detected") return allRows.slice(1, 2).filter((row) => row.count > 0);
    if (pinView === "inspector") return allRows.slice(2, 3).filter((row) => row.count > 0);
    return allRows.filter((row) => row.count > 0);
  }, [panelData, pinView]);

  const inspectionRows = [
    { key: "pending", value: "pending", label: "Pending", count: Number(panelData?.inspections?.pending || 0), color: STATUS_COLORS.pending },
    { key: "waiting_for_review", value: "waiting_for_review", label: "Waiting for review", count: Number(panelData?.inspections?.waiting_for_review || 0), color: STATUS_COLORS.waiting_for_review },
    { key: "verified", value: "verified", label: "Verified", count: Number(panelData?.inspections?.verified || 0), color: STATUS_COLORS.verified },
  ].filter((row) => row.count > 0);
  const outcomeRows = ["Green", "Yellow", "Red"]
    .map((value) => ({
      value,
      label: value,
      count: Number(panelData?.inspections?.outcomes?.[value] || 0),
      color: STATUS_COLORS[value],
    }))
    .filter((row) => row.count > 0);

  if (loading && !overview) {
    return <div role="status" aria-label="Loading barangay details" aria-busy="true"><OverviewMapSkeleton /></div>;
  }
  if (error && !overview) {
    return (
      <div className="map-overview-error" role="alert">
        <p>Barangay details could not be loaded.</p>
        <button type="button" onClick={retry}>Try again</button>
      </div>
    );
  }

  return (
    <div
      className="map-overview"
      style={{ "--hotspot-flag-red": FLAG_COLORS.Red.marker }}
    >
      <div className="map-overview-topbar" aria-label={`${selectedRow ? shortBarangay(selectedRow.barangayName) : "All barangays"} totals`}>
        <div className="map-overview-total">
          <strong>{topTotals.registered.toLocaleString()}</strong>
          <span>Registered businesses</span>
        </div>
        <div className="map-overview-total">
          <strong>{topTotals.notInRegistry.toLocaleString()}</strong>
          <span>Found on the map, not in registry</span>
        </div>
        <div className="map-overview-total">
          <strong>{topTotals.beingInspected.toLocaleString()}</strong>
          <span>Being inspected</span>
        </div>
      </div>

      <section
        className="map-overview-filter-card"
        aria-labelledby="map-overview-filters-title"
      >
        <div className="map-overview-filter-heading">
          <div className="map-overview-filter-heading-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 5h16l-6.5 7.5v5l-3 1.5v-6.5L4 5z" />
            </svg>
          </div>
          <div>
            <h3 id="map-overview-filters-title">Filters</h3>
            <p>Choose what you would like to see on the map and in the details.</p>
          </div>
        </div>
        <div className="map-overview-controls" role="group" aria-label="Overview filters">
          <div className="map-overview-control-group">
            <label className="map-overview-select-label map-overview-select-label--filter">
              <span>Barangay</span>
              <select aria-label="Choose a barangay" value={selectedBarangayId ?? ""} onChange={selectFromList}>
                <option value="">All barangays</option>
                {barangayRows.map((row) => (
                  <option key={row.barangayID} value={row.barangayID}>{row.barangayName}</option>
                ))}
              </select>
            </label>
            <label className="map-overview-select-label map-overview-select-label--filter">
              <span>Sector</span>
              <select
                aria-label="Filter registered businesses by sector"
                value={selectedSectorKey}
                onChange={(event) => {
                  const nextSectorKey = event.target.value;
                  setSelectedLineOfBusinessKey((selectedKey) => (
                    lineOfBusinessKeyAfterSectorChange(
                      selectedKey,
                      allLineOfBusinessOptions,
                      nextSectorKey,
                    )
                  ));
                  setSelectedSectorKey(nextSectorKey);
                  setActiveDimension("display_sector");
                }}
              >
                <option value="">All sectors</option>
                {displaySectorOptions.map((sector) => (
                  <option key={sector.value} value={sector.value}>{sector.label}</option>
                ))}
              </select>
            </label>
            <label className="map-overview-select-label map-overview-select-label--filter">
              <span className="map-overview-filter-label-heading">
                <span>Line of business</span>
                <AnalyticsInfoTip label="About line-of-business filtering">
                  Each business is counted under its first-listed PSIC activity.
                  Secondary activities are not counted. The activity description
                  is a label; the filter uses its full normalized key.
                </AnalyticsInfoTip>
              </span>
              <select
                aria-label="Filter registered businesses by line of business"
                value={selectedLineOfBusinessKey}
                disabled={loading || lineOfBusinessOptions.length === 0}
                onChange={(event) => {
                  setSelectedLineOfBusinessKey(event.target.value);
                  setActiveDimension("display_sector");
                }}
              >
                <option value="">All activities</option>
                {selectedSectorKey
                  ? lineOfBusinessOptions.map((option) => (
                    <option key={option.value} value={option.value} title={option.label}>
                      {option.label}
                    </option>
                  ))
                  : lineOfBusinessOptionsBySector.map((sector) => (
                    <optgroup key={sector.value} label={sector.label}>
                      {sector.options.map((option) => (
                        <option key={option.value} value={option.value} title={option.label}>
                          {option.label}
                        </option>
                      ))}
                    </optgroup>
                  ))}
              </select>
            </label>
            <label className="map-overview-date-label" title="Choose the date range">
              <span>Date range</span>
              <select aria-label="Date range" title="Choose the date range"
                value={datePreset} onChange={(event) => {
                  clearSelectedCluster();
                  setDatePreset(event.target.value);
                }}>
                <option value="all">All time</option>
                <option value="year">This year</option>
                <option value="30days">Last 30 days</option>
                <option value="7days">Last 7 days</option>
              </select>
            </label>
          </div>
        </div>
        <p className="map-overview-filter-scope">
          Filters registered businesses only.
        </p>
        {(selectedSectorKey || selectedLineOfBusinessOption) && (
          <div className="map-overview-active-filters" aria-label="Active filters">
            {selectedSectorKey && (
              <span className="map-overview-active-filter">
                Sector: {displaySectorOptions.find(
                  (sector) => sector.value === selectedSectorKey,
                )?.label || selectedSectorKey}
                <button
                  type="button"
                  aria-label="Remove sector filter"
                  onClick={() => setSelectedSectorKey("")}
                >
                  ×
                </button>
              </span>
            )}
            {selectedLineOfBusinessOption && (
              <span className="map-overview-active-filter">
                Line of business: {selectedLineOfBusinessOption.label}
                <button
                  type="button"
                  aria-label="Remove line-of-business filter"
                  onClick={() => setSelectedLineOfBusinessKey("")}
                >
                  ×
                </button>
              </span>
            )}
          </div>
        )}
      </section>

      <div className="analytics-map-update-slot" role="status" aria-live="polite">
        {loading ? "Updating barangay details…" : error ? "Some barangay details could not be updated." : ""}
      </div>

      <div className="map-overview-layout">
        <section className="map-overview-map-card" aria-label="Barangay map">
          <div className="map-overview-map-heading map-overview-map-toolbar">
            {!showHotspots && (
              <div className="map-overview-segmented" role="group" aria-label="Map color">
                <button type="button" className={mapView === "registered" ? "active" : ""}
                  aria-pressed={mapView === "registered"} onClick={() => setMapView("registered")}>
                  Registered
                </button>
                <button type="button" className={mapView === "inspections" ? "active" : ""}
                  aria-pressed={mapView === "inspections"} onClick={() => setMapView("inspections")}>
                  Inspections
                </button>
              </div>
            )}
            <div className="map-overview-hotspot-controls">
              <button
                type="button"
                className={`map-overview-hotspot-toggle${showHotspots ? " active" : ""}`}
                role="switch"
                aria-checked={showHotspots}
                onClick={toggleHotspots}
              >
                Show hotspots
              </button>
              <div className="map-overview-hotspot-scan-note" role="status">
                {scanNote.text}
              </div>
            </div>
          </div>
          <div className="map-overview-map-stage">
            {loadError ? (
              <div className="map-overview-map-message" role="alert">The map could not be loaded.</div>
            ) : !isLoaded ? (
              <div className="map-overview-map-message" role="status">Loading map…</div>
            ) : (
              <GoogleMap
                mapContainerClassName="map-overview-canvas"
                center={MAP_CENTER}
                zoom={13}
                onLoad={handleMapLoad}
                onUnmount={handleMapUnmount}
                onZoomChanged={() => {
                  const zoom = mapRef.current?.getZoom();
                  if (zoom != null) setMapZoom(zoom);
                }}
                onClick={clearSelectedCluster}
                options={{
                   mapId: REVELA_MAP_ID,
                   colorScheme: isDark ? "DARK" : "LIGHT",
                  isFractionalZoomEnabled: true,
                  clickableIcons: false,
                  mapTypeControl: false,
                  streetViewControl: false,
                  fullscreenControl: true,
                  zoomControl: true,
                  minZoom: Math.max(MIN_BARANGAY_MAP_ZOOM, MAP_MIN_ZOOM),
                  maxZoom: MAP_MAX_ZOOM,
                }}
              >
                <Data
                  onLoad={handleDataLayerLoad}
                  onUnmount={handleDataLayerUnmount}
                  onClick={selectFeature}
                  onMouseOver={setHoveredFeature}
                  onMouseOut={clearHoveredFeature}
                />
                {showHotspots && hotspotClusters.map((cluster) => {
                  const isSelected = hasSelectedCluster
                    && Number(cluster.cluster_id) === Number(selectedClusterId);
                  const isDimmed = hasSelectedCluster && !isSelected;
                  const zIndex = 200 + Number(cluster.size || 0);
                  const outlinePath = hotspotCirclePath(
                    cluster.centroid,
                    hotspotOverlayRadius(cluster.radius_m),
                  );
                  const selectCluster = (event) => {
                    event?.domEvent?.stopPropagation();
                    selectHotspotCluster(cluster);
                  };
                  return (
                    <Fragment key={cluster.cluster_id}>
                      {mapZoom >= 14 && (
                        <>
                          <Circle
                            center={cluster.centroid}
                            radius={hotspotOverlayRadius(cluster.radius_m)}
                            onClick={selectCluster}
                            options={{
                              clickable: true,
                              fillColor: FLAG_COLORS.Red.marker,
                              fillOpacity: isDimmed ? 0.08 : 0.25,
                              strokeOpacity: 0,
                              strokeWeight: 0,
                              zIndex,
                            }}
                          />
                          <Polyline
                            path={outlinePath}
                            onClick={selectCluster}
                            options={{
                              clickable: true,
                              strokeOpacity: 0,
                              zIndex: zIndex + 1,
                              icons: [{
                                icon: {
                                  path: "M 0,-1 0,1",
                                  strokeColor: FLAG_COLORS.Red.marker,
                                  strokeOpacity: isDimmed ? 0.25 : 0.95,
                                  strokeWeight: isSelected ? 4 : 2,
                                  scale: 1,
                                },
                                repeat: "10px",
                              }],
                            }}
                          />
                        </>
                      )}
                      <Marker
                        position={cluster.centroid}
                        title={hotspotTooltipLabel(cluster)}
                        onClick={selectCluster}
                        options={{
                          clickable: true,
                          optimized: true,
                          zIndex: (isSelected ? 10_000 : 1_000) + Number(cluster.size || 0),
                          icon: {
                            path: window.google.maps.SymbolPath.CIRCLE,
                            scale: 0,
                          },
                          label: {
                            text: String(cluster.size),
                            className: [
                              "map-overview-hotspot-badge",
                              `map-overview-hotspot-badge--${hotspotBadgeTier(cluster.size)}`,
                              isSelected && "map-overview-hotspot-badge--selected",
                              isDimmed && "map-overview-hotspot-badge--dimmed",
                            ].filter(Boolean).join(" "),
                          },
                        }}
                      />
                      {isSelected && clusterPinsAreCurrent && clusterPinsState.pins
                        .filter((pin) => (
                          Number.isFinite(Number(pin.latitude))
                          && Number.isFinite(Number(pin.longitude))
                        ))
                        .map((pin) => (
                          <Marker
                            key={`member-${pin.logID}`}
                            position={{
                              lat: Number(pin.latitude),
                              lng: Number(pin.longitude),
                            }}
                            title={pin.detectedName || "Unnamed detection"}
                            options={{
                              clickable: false,
                              optimized: true,
                              zIndex: zIndex + 2,
                              icon: {
                                path: window.google.maps.SymbolPath.CIRCLE,
                                scale: 4,
                                fillColor: FLAG_COLORS.Red.marker,
                                fillOpacity: 1,
                                strokeColor: "#ffffff",
                                strokeWeight: 1,
                              },
                            }}
                          />
                        ))}
                    </Fragment>
                  );
                })}
              </GoogleMap>
            )}
            <button
              type="button"
              className="map-overview-fit-all"
              aria-label="Fit all 16 barangays in the map"
              onClick={fitAllBarangays}
            >
              Fit all barangays
            </button>
            {boundaryError && (
              <p className="map-overview-map-error" role="alert">
                Barangay boundaries could not be displayed.
              </p>
            )}
            <div className="map-overview-legend-control"
              onClick={(event) => event.stopPropagation()}
              onMouseDown={(event) => event.stopPropagation()}
              onDoubleClick={(event) => event.stopPropagation()}
              onPointerDown={(event) => event.stopPropagation()}
              onTouchStart={(event) => event.stopPropagation()}>
              <button ref={legendToggleRef} type="button" className="map-overview-legend-toggle"
                aria-label={legendOpen ? "Close map legend" : "Open map legend"}
                aria-expanded={legendOpen} aria-controls="map-overview-legend"
                title={legendOpen ? "Close map legend" : "Map legend"}
                onClick={() => setLegendOpen((open) => !open)}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M4 4h16v16H4z" />
                  <path d="M4 9h16M9 9v11" />
                </svg>
              </button>
              {legendOpen && showHotspots && (
                <div
                  ref={legendPanelRef}
                  id="map-overview-legend"
                  className="map-overview-map-legend map-overview-hotspot-legend"
                  role="group"
                  aria-label="Hotspot legend"
                  data-hotspot-legend
                >
                  <span className="map-overview-legend-title">Hotspot groups</span>
                  <div className="map-overview-hotspot-legend-copy">
                    <i aria-hidden="true" />
                    <span>
                      Hotspot group: 3 or more Red-flagged (expired or unregistered) locations within about 50 m. Number = locations in the group. Circle = area they cover.
                    </span>
                  </div>
                </div>
              )}
              {legendOpen && !showHotspots && (
                <div ref={legendPanelRef} id="map-overview-legend" className="map-overview-map-legend" role="group"
                  aria-label={mapView === "inspections"
                    ? "Inspections per barangay map legend"
                    : "Businesses per barangay map legend"}>
                  <span className="map-overview-legend-title">
                    {mapView === "inspections" ? "Inspections per barangay" : "Businesses per barangay"}
                  </span>
                  <div className="map-overview-legend-ranges">
                    {mapRangeLabels.map((label, index) => (
                      <span key={label}>
                         <i style={{ background: (isDark ? DARK_CHOROPLETH_COLORS : CHOROPLETH_COLORS)[mapView][index] }} />
                        {label}
                      </span>
                    ))}
                  </div>
                  <span className="map-overview-legend-empty">
                    <i /> {mapView === "inspections" ? "No inspections yet" : "No registered businesses"}
                  </span>
                </div>
              )}
            </div>
          </div>
          <p className="map-overview-map-hint">
            Zoom in or use the Barangay filter above to pick small barangays.
          </p>
        </section>

        <aside className="map-overview-panel" aria-label="Barangay details">
          {!showHotspots && (
            <div className="map-overview-panel-heading">
              {selectedRow ? (
                <span className="map-overview-selection-chip">
                  {shortBarangay(selectedRow.barangayName)}
                  <button type="button" aria-label="Show all barangays"
                    onClick={fitAllBarangays}>×</button>
                </span>
              ) : (
                <h3>All barangays</h3>
              )}
              {selectedRow && (
                <button className="map-overview-reset" type="button"
                  onClick={fitAllBarangays}>Show all barangays</button>
              )}
            </div>
          )}
          {showHotspots && (
            <>
              <section className="map-overview-hotspot-summary" aria-live="polite">
                <div className="map-overview-card-heading">
                  <h4>Possible hotspot groups</h4>
                  <AnalyticsInfoTip label="About hotspot locations">
                    {hotspotMethodNote(hotspotData?.parameters_used)}
                  </AnalyticsInfoTip>
                </div>
                <p className="map-overview-hotspot-period">
                  Period: {hotspotPeriodLabel(datePreset)}
                </p>
                {hotspotLoading ? (
                  <div className="map-overview-hotspot-summary-skeleton" role="status" aria-label="Loading hotspot groups">
                    <span />
                  </div>
                ) : hotspotError ? (
                  <div role="alert" className="map-overview-hotspot-error">
                    <p>{hotspotError}</p>
                    <button type="button" onClick={() => setHotspotRetry((retry) => retry + 1)}>
                      Retry
                    </button>
                  </div>
                ) : !hotspotData?.last_detection_run ? (
                  <p>No detection scan data yet. A scan is needed to identify possible groups.</p>
                ) : hotspotStats.clusterCount === 0 ? (
                  <>
                    <p>No nearby groups for this period.</p>
                    {datePreset !== "all" && (
                      <button type="button" onClick={() => {
                        clearSelectedCluster();
                        setDatePreset("all");
                      }}>
                        Show all time
                      </button>
                    )}
                  </>
                ) : (
                  <p>
                    {hotspotStats.clusterCount} possible groups found among {hotspotStats.redFlaggedCount.toLocaleString()} Red-flagged locations.
                  </p>
                )}
                {hotspotStats.outsideBoundaryCount > 0 && (
                  <p className="map-overview-hotspot-outside-boundary">
                    {hotspotStats.outsideBoundaryCount.toLocaleString()} locations are outside the municipal boundary.
                  </p>
                )}
                <p className="map-overview-hotspot-caveat">
                  Nearby groups are possible hotspots only; they do not confirm a violation.
                </p>
              </section>
              {hotspotLoading && (
                <div className="map-overview-hotspot-list-skeleton" aria-hidden="true">
                  {Array.from({ length: 7 }, (_, index) => (
                    <span key={index} />
                  ))}
                </div>
              )}
              {!hotspotLoading && !hotspotError && hotspotStats.clusterCount > 0 && (
                selectedCluster && clusterDetail ? (
                  <section className="map-overview-hotspot-summary map-overview-cluster-detail" aria-live="polite">
                    <div className="map-overview-card-heading">
                      <div>
                        <h4>Group of {clusterDetail.pinCount} nearby locations</h4>
                        <p>{clusterDetail.location}</p>
                      </div>
                    </div>
                    <div className="map-overview-cluster-pin-list" aria-label="Locations in selected hotspot group">
                      {token && (!clusterPinsAreCurrent || clusterPinsState.loading) ? (
                        <p role="status">Loading location details…</p>
                      ) : clusterPinsAreCurrent && clusterPinsState.error ? (
                        <div>
                          <p role="alert">{clusterPinsState.error}</p>
                          <button type="button" onClick={() => setClusterDetailRetry((value) => value + 1)}>
                            Retry
                          </button>
                        </div>
                      ) : clusterDetail.pins.map((pin) => (
                        <article className="map-overview-cluster-pin" key={pin.logID}>
                          <strong>{pin.name}</strong>
                          <span>{pin.address}</span>
                          <span>Detected {pin.detectedDate}</span>
                        </article>
                      ))}
                    </div>
                    <div className="map-overview-hotspot-actions">
                      <button
                        type="button"
                        className="map-overview-hotspot-open-map"
                        disabled={!selectedClusterMapPath}
                        onClick={() => selectedClusterMapPath && navigate(selectedClusterMapPath)}
                      >
                        View on Maps &amp; Flags
                      </button>
                      <button
                        type="button"
                        className="map-overview-hotspot-back"
                        onClick={clearSelectedCluster}
                      >
                        Back to list
                      </button>
                    </div>
                  </section>
                ) : (
                  <section className="map-overview-hotspot-group-list" aria-label="All hotspot groups">
                    {hotspotClusters.map((cluster) => (
                      <button
                        type="button"
                        key={cluster.cluster_id}
                        aria-pressed={selectedClusterRequestKey === hotspotRequestKey
                          && Number(cluster.cluster_id) === Number(selectedClusterId)}
                        onClick={() => selectHotspotCluster(cluster)}
                      >
                        Group of {Number(cluster.size)} · {hotspotGroupLocation(cluster)}
                      </button>
                    ))}
                  </section>
                )
              )}
            </>
          )}

          {!showHotspots && (
            <>
          <section className="map-overview-detail-card">
            <div className="map-overview-card-heading">
              <h4>A. Official Registry · {Number(panelData?.registry_total || 0).toLocaleString()} businesses</h4>
              <AnalyticsInfoTip label="About registered businesses">
                Counts are from the official registry. The selected date range applies to map pins and inspections, not registry totals.
              </AnalyticsInfoTip>
            </div>
            <div className="map-overview-choice-row" role="group" aria-label="Business breakdown">
              {REGISTRY_DIMENSIONS.map((dimension) => (
                <button key={dimension.key} type="button"
                  className={activeDimension === dimension.key ? "active" : ""}
                  aria-pressed={activeDimension === dimension.key}
                  onClick={() => setActiveDimension(dimension.key)}>
                  {dimension.label}
                </button>
              ))}
            </div>
            {selectedLineOfBusinessKey
              && Number(panelData?.registry_total || 0) === 0 ? (
                <div className="map-overview-filter-empty">
                  <p>No registered businesses match this filter.</p>
                  <button type="button" onClick={() => setSelectedLineOfBusinessKey("")}>
                    Clear
                  </button>
                </div>
              ) : (
                <CountsBar rows={coloredDimensionRows}
                  emptyMessage={selectedSectorKey
                    ? "No registered businesses match this sector."
                    : "No registered businesses in this view yet."} />
              )}
          </section>

          <section className="map-overview-detail-card">
            <div className="map-overview-card-heading">
              <h4>B. Field Inspections</h4>
            </div>
            <div className="map-overview-field-section">
              <div className="map-overview-card-heading">
                <h5>Found on the map · {Number(panelData?.pins?.total || 0).toLocaleString()} pins</h5>
                <AnalyticsInfoTip label="About map pins">
                  This includes every pin in the selected area. Detected pins linked to a business are grouped with registered pins. Pins without coordinates are still included.
                </AnalyticsInfoTip>
              </div>
              <div className="map-overview-choice-row" role="group" aria-label="Map pin groups">
                {[
                  ["all", "All"],
                  ["detected", "Detected"],
                  ["inspector", "Added by inspector"],
                ].map(([key, label]) => (
                  <button key={key} type="button" className={pinView === key ? "active" : ""}
                    aria-pressed={pinView === key} onClick={() => setPinView(key)}>
                    {label}
                  </button>
                ))}
              </div>
              <CountsBar rows={pinRows} emptyMessage="No pins in this view yet." />
              <p className="map-overview-note">
                {Number(panelData?.pins_without_location || 0).toLocaleString()} pins have no location
              </p>
            </div>
            <div className="map-overview-field-section">
              <div className="map-overview-card-heading">
                <h5>Inspections · {Number(panelData?.inspections?.total || 0).toLocaleString()} reports</h5>
                <AnalyticsInfoTip label="About inspection progress">
                  Not yet done combines Assigned, Reassigned, In Progress, and Unassigned reports. Waiting for review includes submitted reports.
                </AnalyticsInfoTip>
              </div>
              <CountsBar rows={inspectionRows}
                emptyMessage={selectedRow
                  ? "No inspections in this barangay yet."
                  : "No inspections yet across these barangays."} />
              {selectedRow && !Number(panelData?.inspections?.verified || 0)
                && <p className="map-overview-note">No verified results yet.</p>}
            {outcomeRows.length > 0 && (
              <>
                <p className="map-overview-note">Verified outcomes</p>
                <ul className="map-overview-outcome-list">
                  {outcomeRows.map((row) => (
                    <li key={row.value}>
                      <span className="map-overview-count-swatch"
                        style={{ background: row.color }} />
                      <span className="map-overview-count-label">{row.label}</span>
                      <strong>{row.count.toLocaleString()}</strong>
                      <span className="map-overview-count-percent">
                        {panelData?.inspections?.verified
                          ? `${((row.count / Number(panelData.inspections.verified)) * 100).toFixed(1)}%`
                          : "0.0%"}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            </div>
          </section>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
