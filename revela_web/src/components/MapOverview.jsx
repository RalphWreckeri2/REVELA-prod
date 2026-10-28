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
  quantileBreaks,
  quantileClass,
  quantileRangeLabels,
} from "./barangayOverviewPresentation";
import "../styles/MapOverview.css";

const MAP_CENTER = { lat: 13.9667, lng: 121.1167 };
const BAR_COLORS = ["#2563eb", "#0f9f8f", "#7c3aed", "#f59e0b", "#e11d48", "#64748b"];
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
  return name.replace(/^Barangay /, "Brgy. ");
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
        {rows.map((row, index) => (
          <span key={row.value} title={`${row.label}: ${row.count}`}
            style={{
              width: `${(Number(row.count) / total) * 100}%`,
              background: row.color || BAR_COLORS[index % BAR_COLORS.length],
            }} />
        ))}
      </div>
      <ul className="map-overview-count-list">
        {rows.map((row, index) => (
          <li key={row.value}>
            <span className="map-overview-count-swatch"
              style={{ background: row.color || BAR_COLORS[index % BAR_COLORS.length] }} />
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
  const hasFitBoundsRef = useRef(false);
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
  const overallData = overview?.overall;
  const mapCounts = useMemo(() => barangayRows.map((row) => Number(
    mapView === "registered" ? row.registry_total : row.inspections.total,
  )), [barangayRows, mapView]);
  const mapBreaks = useMemo(() => quantileBreaks(mapCounts), [mapCounts]);
  const mapRangeLabels = useMemo(() => quantileRangeLabels(mapBreaks), [mapBreaks]);
  const selectedDimension = REGISTRY_DIMENSIONS.find(
    (dimension) => dimension.key === activeDimension,
  ) || REGISTRY_DIMENSIONS[0];
  const dimensionRows = selectedDimension
    ? panelData?.registry?.[selectedDimension.key] || []
    : [];
  const pendingInspections = Number(overallData?.inspections?.pending || 0)
    + Number(overallData?.inspections?.waiting_for_review || 0);
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
    if (hasFitBoundsRef.current || !mapRef.current || !boundaryFeaturesRef.current.length) return;
    const bounds = new window.google.maps.LatLngBounds();
    boundaryFeaturesRef.current.forEach((feature) => {
      feature.getGeometry()?.forEachLatLng((latLng) => bounds.extend(latLng));
    });
    if (!bounds.isEmpty()) {
      mapRef.current.fitBounds(bounds, { top: 24, right: 24, bottom: 24, left: 24 });
      hasFitBoundsRef.current = true;
    }
  }, []);

  const addBarangayLabels = useCallback((features, sourceFeatures) => {
    labelMarkersRef.current.forEach((marker) => marker.setMap(null));
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
      labelMarkersRef.current.push(marker);
    });
  }, []);

  const handleMapLoad = useCallback((map) => {
    mapRef.current = map;
    if (boundaryFeaturesRef.current.length) {
      addBarangayLabels(
        boundaryFeaturesRef.current,
        sourceGeoJsonFeaturesRef.current,
      );
    }
    fitBarangayBounds();
  }, [addBarangayLabels, fitBarangayBounds]);

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
        fitBarangayBounds();
      })
      .catch(() => setBoundaryError(true));
  }, [addBarangayLabels, fitBarangayBounds]);

  const handleDataLayerUnmount = useCallback(() => {
    labelMarkersRef.current.forEach((marker) => marker.setMap(null));
    labelMarkersRef.current = [];
    boundaryFeaturesRef.current = [];
    sourceGeoJsonFeaturesRef.current = [];
    hasFitBoundsRef.current = false;
    mapRef.current = null;
    dataLayerRef.current = null;
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
    if (!panelData?.pins) return [];
    const allRows = [
      { key: "registered_on_map", label: "Registered on map" },
      { key: "detected_not_in_registry", label: "Detected, not in registry" },
      { key: "detection_with_business_id", label: "Detected and linked to a business" },
      { key: "added_by_inspector", label: "Added by inspector" },
      { key: "other_source", label: "Other pins" },
    ].map((row) => ({
      ...row,
      value: row.key,
      count: Number(panelData.pins[row.key] || 0),
      color: STATUS_COLORS[row.key],
    }));
    if (pinView === "detected") {
      return allRows.slice(1, 3).filter((row) => row.count > 0);
    }
    if (pinView === "inspector") {
      return allRows.slice(3, 4).filter((row) => row.count > 0);
    }
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
          <div className="map-overview-total">
            <strong>{Number(overallData?.registry_total || 0).toLocaleString()}</strong>
            <span>Registered businesses</span>
          </div>
          <div className="map-overview-total">
            <strong>{Number(overallData?.pins?.detected_not_in_registry || 0).toLocaleString()}</strong>
            <span>Found on the map, not in registry</span>
          </div>
          <div className="map-overview-total">
            <strong>{pendingInspections.toLocaleString()}</strong>
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
              <div>
                <h4>A. Official Registry</h4>
                <p className="map-overview-card-subtitle">Registered businesses</p>
              </div>
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
            <CountsBar rows={dimensionRows}
              emptyMessage="No registered businesses in this view yet." />
          </section>

          <section className="map-overview-detail-card">
            <div className="map-overview-card-heading">
              <h4>B. Field Inspections</h4>
            </div>
            <div className="map-overview-field-section">
              <div className="map-overview-card-heading">
                <h5>Found on the map</h5>
                <AnalyticsInfoTip label="About map pins">
                  Each map pin is counted once. Pins without coordinates are included in totals but cannot be placed on the map.
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
                <h5>Inspections</h5>
                <AnalyticsInfoTip label="About inspection progress">
                  Not yet done combines Assigned, Reassigned, In Progress, and Unassigned reports. Waiting for review includes submitted reports.
                </AnalyticsInfoTip>
              </div>
              <CountsBar rows={inspectionRows}
                emptyMessage={selectedRow
                  ? "No inspections in this barangay yet."
                  : "No inspections yet across these barangays."} />
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
