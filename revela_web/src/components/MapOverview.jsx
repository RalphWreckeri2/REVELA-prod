import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Data, GoogleMap } from "@react-google-maps/api";
import AnalyticsInfoTip from "./AnalyticsInfoTip";
import { getBarangayOverviewRequest } from "../services/api";
import { useGoogleMapsScript } from "../utils/googleMaps";
import { REVELA_MAP_ID } from "../utils/mapStyles";
import {
  getBarangayIdForGeoJsonName,
  getGeoJsonCentroid,
  getShortBarangayLabel,
  normalizeGeoJsonWinding,
} from "./barangayMapMapping";
import {
  buildBarangayOverviewFilters,
  getBarangayTopTotals,
  getMapPinBuckets,
  quantileBreaks,
  quantileClass,
  quantileRangeLabels,
  registryCategoryColor,
} from "./barangayOverviewPresentation";
import "../styles/MapOverview.css";

const MAP_CENTER = { lat: 13.9667, lng: 121.1167 };
const CHOROPLETH_COLORS = {
  registered: ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
  inspections: ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
};
const EMPTY_BARANGAY_ROWS = Object.freeze([]);
const REGISTRY_DIMENSIONS = [
  { key: "business_size", label: "By size" },
  { key: "business_type", label: "By type" },
  { key: "registration_type", label: "By registration type" },
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
          setSnapshot({
            key: requestKey,
            overview: null,
            error: requestError.message || "The barangay overview could not be loaded.",
          });
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

export default function MapOverview({ token, filters, onOpenAdvancedFilters }) {
  const [datePreset, setDatePreset] = useState("all");
  const [mapView, setMapView] = useState("registered");
  const [selectedBarangayId, setSelectedBarangayId] = useState(null);
  const [hoveredBarangayId, setHoveredBarangayId] = useState(null);
  const [activeDimension, setActiveDimension] = useState("business_size");
  const [pinView, setPinView] = useState("all");
  const [boundaryError, setBoundaryError] = useState(false);
  const dataLayerRef = useRef(null);
  const styleFeatureRef = useRef(null);
  const mapRef = useRef(null);
  const boundaryFeaturesRef = useRef([]);
  const sourceGeoJsonFeaturesRef = useRef([]);
  const labelMarkersRef = useRef([]);
  const mapIdleRef = useRef(false);
  const mapIdleListenerRef = useRef(null);
  const resizeObserverRef = useRef(null);
  const fitFrameRef = useRef(null);
  const lastFitSignatureRef = useRef("");
  const lastMapSizeRef = useRef("");
  const fitBarangayBoundsRef = useRef(null);
  const updateLabelVisibilityRef = useRef(null);
  const { isLoaded, loadError } = useGoogleMapsScript();
  const { overview, loading, error, retry } = useBarangayOverview(
    token,
    filters,
    datePreset,
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
  const coloredDimensionRows = dimensionRows.map((row) => ({
    ...row,
    color: registryCategoryColor(activeDimension, row.value),
  }));
  const topTotals = getBarangayTopTotals(panelData);
  const mapRowsById = rowsById;

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
      fillColor: colorIndex < 0
        ? "#cbd5e1"
        : CHOROPLETH_COLORS[mapView][colorIndex],
      fillOpacity: 1,
      strokeColor: isSelected ? "#0f172a" : isHovered ? "#f97316" : "#ffffff",
      strokeWeight: isSelected ? 4 : isHovered ? 2 : 1,
      zIndex: isSelected ? 100 : isHovered ? 10 : 0,
    };
  }, [hoveredBarangayId, mapBreaks, mapRowsById, mapView, selectedBarangayId]);

  useEffect(() => {
    styleFeatureRef.current = styleFeature;
    dataLayerRef.current?.setStyle((feature) => styleFeature(feature));
  }, [styleFeature]);

  const fitBarangayBounds = useCallback(() => {
    const map = mapRef.current;
    const container = map?.getDiv();
    if (!mapIdleRef.current || !map || !container?.clientWidth || !container?.clientHeight
      || !boundaryFeaturesRef.current.length) return;
    const size = `${container.clientWidth}x${container.clientHeight}`;
    const selectedId = selectedBarangayId == null ? null : Number(selectedBarangayId);
    const signature = `${selectedId ?? "all"}:${size}`;
    if (signature === lastFitSignatureRef.current) return;
    const bounds = new window.google.maps.LatLngBounds();
    const features = selectedId == null
      ? boundaryFeaturesRef.current
      : boundaryFeaturesRef.current.filter((feature) => (
        getBarangayIdForGeoJsonName(feature.getProperty("ADM4_EN")) === selectedId
      ));
    features.forEach((feature) => {
      feature.getGeometry()?.forEachLatLng((latLng) => bounds.extend(latLng));
    });
    if (!bounds.isEmpty()) {
      lastFitSignatureRef.current = signature;
      const padding = selectedId == null ? 24 : 40;
      map.fitBounds(bounds, {
        top: padding,
        right: padding,
        bottom: padding,
        left: padding,
      });
    }
  }, [selectedBarangayId]);

  const scheduleBarangayFit = useCallback(() => {
    if (fitFrameRef.current != null) {
      window.cancelAnimationFrame(fitFrameRef.current);
    }
    fitFrameRef.current = window.requestAnimationFrame(() => {
      fitFrameRef.current = window.requestAnimationFrame(() => {
        fitFrameRef.current = null;
        fitBarangayBoundsRef.current?.();
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
        },
      });
      labelMarkersRef.current.push({ marker, barangayId: id });
    });
  }, []);

  const updateBarangayLabelVisibility = useCallback(() => {
    const zoom = mapRef.current?.getZoom() || 0;
    labelMarkersRef.current.forEach(({ marker, barangayId }) => {
      const visible = zoom >= 14
        || barangayId === Number(selectedBarangayId)
        || barangayId === Number(hoveredBarangayId);
      marker.setVisible(visible);
    });
  }, [hoveredBarangayId, selectedBarangayId]);

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
    scheduleBarangayFit();
  }, [scheduleBarangayFit, selectedBarangayId]);

  const handleMapLoad = useCallback((map) => {
    mapRef.current = map;
    if (boundaryFeaturesRef.current.length) {
      addBarangayLabels(
        boundaryFeaturesRef.current,
        sourceGeoJsonFeaturesRef.current,
      );
      updateLabelVisibilityRef.current?.();
    }
    mapIdleListenerRef.current = map.addListener("idle", () => {
      mapIdleRef.current = true;
      scheduleBarangayFit();
      updateLabelVisibilityRef.current?.();
    });
    if (typeof ResizeObserver !== "undefined") {
      resizeObserverRef.current = new ResizeObserver(() => {
        const container = map.getDiv();
        const size = `${container.clientWidth}x${container.clientHeight}`;
        if (size === lastMapSizeRef.current) return;
        lastMapSizeRef.current = size;
        lastFitSignatureRef.current = "";
        scheduleBarangayFit();
      });
      resizeObserverRef.current.observe(map.getDiv());
    }
    scheduleBarangayFit();
  }, [addBarangayLabels, scheduleBarangayFit]);

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
    dataLayerRef.current = null;
  }, []);

  const handleMapUnmount = useCallback(() => {
    mapIdleListenerRef.current?.remove();
    mapIdleListenerRef.current = null;
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    if (fitFrameRef.current != null) {
      window.cancelAnimationFrame(fitFrameRef.current);
      fitFrameRef.current = null;
    }
    mapIdleRef.current = false;
    lastFitSignatureRef.current = "";
    lastMapSizeRef.current = "";
    mapRef.current = null;
  }, []);

  const selectFeature = useCallback((event) => {
    const id = getBarangayIdForGeoJsonName(event.feature?.getProperty("ADM4_EN"));
    if (id != null) setSelectedBarangayId(id);
  }, []);

  const setHoveredFeature = useCallback((event) => {
    const id = getBarangayIdForGeoJsonName(event.feature?.getProperty("ADM4_EN"));
    setHoveredBarangayId(id);
  }, []);

  const clearHoveredFeature = useCallback(() => setHoveredBarangayId(null), []);

  const selectFromList = (event) => {
    setSelectedBarangayId(event.target.value ? Number(event.target.value) : null);
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
    return <div className="map-overview-loading" role="status">Loading barangay details…</div>;
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
    <div className="map-overview">
      <div className="map-overview-controls">
        <div className="map-overview-topbar" aria-label="Barangay totals">
          <span className="map-overview-current-selection">
            {selectedRow ? shortBarangay(selectedRow.barangayName) : "All barangays"}
          </span>
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
        <label>
          <span>Date range</span>
          <select value={datePreset} onChange={(event) => setDatePreset(event.target.value)}>
            <option value="all">All time</option>
            <option value="year">This year</option>
            <option value="30days">Last 30 days</option>
            <option value="7days">Last 7 days</option>
          </select>
        </label>
        <details className="map-overview-advanced">
          <summary>Advanced filters</summary>
          <button type="button" onClick={onOpenAdvancedFilters}>Open filters</button>
        </details>
      </div>

      {loading && <p className="map-overview-refreshing" role="status">Updating barangay details…</p>}
      {error && <p className="map-overview-error-inline" role="alert">Some barangay details could not be updated.</p>}

      <div className="map-overview-layout">
        <section className="map-overview-map-card" aria-label="Barangay map">
          <div className="map-overview-map-heading">
            <div className="map-overview-segmented" role="group" aria-label="Map color">
              <button type="button" className={mapView === "registered" ? "active" : ""}
                aria-pressed={mapView === "registered"} onClick={() => setMapView("registered")}>
                Registered
              </button>
              <button type="button" className={mapView === "inspections" ? "active" : ""}
                aria-pressed={mapView === "inspections"} onClick={() => setMapView("inspections")}>
                Inspections
              </button>
              <button type="button" disabled aria-label="Hotspots coming soon">
                Hotspots · Coming soon
              </button>
            </div>
          </div>
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
              options={{
                mapId: REVELA_MAP_ID,
                clickableIcons: false,
                mapTypeControl: false,
                streetViewControl: false,
                fullscreenControl: true,
                zoomControl: true,
              }}
            >
              <Data
                onLoad={handleDataLayerLoad}
                onUnmount={handleDataLayerUnmount}
                onClick={selectFeature}
                onMouseOver={setHoveredFeature}
                onMouseOut={clearHoveredFeature}
              />
            </GoogleMap>
          )}
          {boundaryError && (
            <p className="map-overview-map-error" role="alert">
              Barangay boundaries could not be displayed.
            </p>
          )}
          <div className="map-overview-map-legend">
            <span className="map-overview-legend-title">
              {mapView === "inspections" ? "Inspections per barangay" : "Businesses per barangay"}
            </span>
            <div className="map-overview-legend-ranges">
              {mapRangeLabels.map((label, index) => (
                <span key={label}>
                  <i style={{ background: CHOROPLETH_COLORS[mapView][index] }} />
                  {label}
                </span>
              ))}
            </div>
            <span className="map-overview-legend-empty">
              <i /> {mapView === "inspections" ? "No inspections yet" : "No registered businesses"}
            </span>
          </div>
          <label className="map-overview-select-label">
            <span>Choose a barangay</span>
            <select value={selectedBarangayId ?? ""} onChange={selectFromList}>
              <option value="">All barangays</option>
              {barangayRows.map((row) => (
                <option key={row.barangayID} value={row.barangayID}>{row.barangayName}</option>
              ))}
            </select>
          </label>
        </section>

        <aside className="map-overview-panel" aria-label="Barangay details">
          <div className="map-overview-panel-heading">
            {selectedRow ? (
              <span className="map-overview-selection-chip">
                {shortBarangay(selectedRow.barangayName)}
                <button type="button" aria-label="Show all barangays"
                  onClick={() => setSelectedBarangayId(null)}>×</button>
              </span>
            ) : (
              <h3>All barangays</h3>
            )}
            {selectedRow && (
              <button className="map-overview-reset" type="button"
                onClick={() => setSelectedBarangayId(null)}>Show all barangays</button>
            )}
          </div>

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
            <CountsBar rows={coloredDimensionRows}
              emptyMessage="No registered businesses in this view yet." />
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
        </aside>
      </div>
    </div>
  );
}
