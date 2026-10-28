import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Data, GoogleMap } from "@react-google-maps/api";
import AnalyticsInfoTip from "./AnalyticsInfoTip";
import { getBarangayOverviewRequest } from "../services/api";
import { useGoogleMapsScript } from "../utils/googleMaps";
import { REVELA_MAP_ID } from "../utils/mapStyles";
import { getBarangayIdForGeoJsonName } from "./barangayMapMapping";
import {
  buildBarangayOverviewFilters,
  visibleRegistryDimensions,
} from "./barangayOverviewPresentation";
import "../styles/MapOverview.css";

const MAP_CENTER = { lat: 13.9667, lng: 121.1167 };
const BAR_COLORS = ["#2563eb", "#0f9f8f", "#7c3aed", "#f59e0b", "#e11d48", "#64748b"];
const EMPTY_BARANGAY_ROWS = Object.freeze([]);
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

function getMapFill(count, maximum, isInspectionView) {
  if (!count) return "#cbd5e1";
  const ratio = maximum ? count / maximum : 0;
  const colors = isInspectionView
    ? ["#dbeafe", "#93c5fd", "#3b82f6", "#1d4ed8"]
    : ["#dcfce7", "#86efac", "#22c55e", "#15803d"];
  return colors[Math.min(colors.length - 1, Math.floor(ratio * colors.length))];
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
              background: BAR_COLORS[index % BAR_COLORS.length],
            }} />
        ))}
      </div>
      <ul className="map-overview-count-list">
        {rows.map((row, index) => (
          <li key={row.value}>
            <span className="map-overview-count-swatch"
              style={{ background: BAR_COLORS[index % BAR_COLORS.length] }} />
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
  const maxMapCount = useMemo(() => Math.max(
    0,
    ...barangayRows.map((row) => Number(mapView === "registered"
      ? row.registry_total
      : row.inspections.total)),
  ), [barangayRows, mapView]);
  const visibleDimensions = useMemo(
    () => visibleRegistryDimensions(panelData?.registry),
    [panelData],
  );
  const selectedDimension = visibleDimensions.find(
    (dimension) => dimension.key === activeDimension,
  ) || visibleDimensions[0];
  const dimensionRows = selectedDimension
    ? panelData?.registry?.[selectedDimension.key] || []
    : [];
  const pendingInspections = Number(panelData?.inspections?.pending || 0)
    + Number(panelData?.inspections?.waiting_for_review || 0);
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
    return {
      fillColor: getMapFill(count, maxMapCount, mapView === "inspections"),
      fillOpacity: isSelected ? 0.78 : isHovered ? 0.68 : 0.52,
      strokeColor: isSelected ? "#0f172a" : isHovered ? "#f97316" : "#ffffff",
      strokeWeight: isSelected ? 3 : isHovered ? 2.5 : 1,
      zIndex: isSelected ? 2 : isHovered ? 1 : 0,
    };
  }, [hoveredBarangayId, mapRowsById, mapView, maxMapCount, selectedBarangayId]);

  useEffect(() => {
    styleFeatureRef.current = styleFeature;
    dataLayerRef.current?.setStyle((feature) => styleFeature(feature));
  }, [styleFeature]);

  const handleDataLayerLoad = useCallback((dataLayer) => {
    dataLayerRef.current = dataLayer;
    setBoundaryError(false);
    dataLayer.setStyle((feature) => styleFeatureRef.current?.(feature) || {});
    try {
      Promise.resolve(dataLayer.loadGeoJson("/data/mataasnakahoy.json"))
        .then(() => dataLayer.setStyle((feature) => styleFeatureRef.current?.(feature) || {}))
        .catch(() => setBoundaryError(true));
    } catch {
      setBoundaryError(true);
    }
  }, []);

  const handleDataLayerUnmount = useCallback(() => {
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
    ];
    if (pinView === "detected") {
      return allRows.slice(1, 3).map((row) => ({
        ...row,
        count: Number(panelData.pins[row.key] || 0),
        color: STATUS_COLORS[row.key],
      }));
    }
    if (pinView === "inspector") {
      return allRows.slice(3, 4).map((row) => ({
        ...row,
        count: Number(panelData.pins[row.key] || 0),
        color: STATUS_COLORS[row.key],
      }));
    }
    return allRows.map((row) => ({
      ...row,
      count: Number(panelData.pins[row.key] || 0),
      color: STATUS_COLORS[row.key],
    })).filter((row) => row.count > 0);
  }, [panelData, pinView]);

  const inspectionRows = [
    { key: "pending", label: "Not yet done", count: Number(panelData?.inspections?.pending || 0) },
    { key: "waiting_for_review", label: "Waiting for review", count: Number(panelData?.inspections?.waiting_for_review || 0) },
    { key: "verified", label: "Verified", count: Number(panelData?.inspections?.verified || 0) },
  ];

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
        <label>
          <span>Show results from</span>
          <select value={datePreset} onChange={(event) => setDatePreset(event.target.value)}>
            <option value="all">All time</option>
            <option value="year">This year</option>
            <option value="30days">Last 30 days</option>
            <option value="7days">Last 7 days</option>
          </select>
        </label>
        <details className="map-overview-advanced">
          <summary>Advanced filters</summary>
          <p>Use your current filters to narrow registry, pin, and inspection results.</p>
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
            </div>
            <div className="map-overview-hotspot-tip">
              <button type="button" disabled aria-label="Hotspots coming soon">
                Hotspots · Coming soon
              </button>
              <AnalyticsInfoTip label="About map hotspots">
                This map currently shows barangay totals. Hotspot details may be added later.
              </AnalyticsInfoTip>
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
          {hoveredBarangayId != null && rowsById.get(Number(hoveredBarangayId)) && (
            <div className="map-overview-hover-label" aria-live="polite">
              {rowsById.get(Number(hoveredBarangayId)).barangayName}
            </div>
          )}
          <div className="map-overview-map-legend">
            <span>{mapView === "registered" ? "Fewer businesses" : "Fewer inspections"}</span>
            <span className={`map-overview-legend-gradient${mapView === "inspections"
              ? " map-overview-legend-gradient--inspections" : ""}`} aria-hidden="true" />
            <span>{mapView === "registered" ? "More businesses" : "More inspections"}</span>
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

          <p className="map-overview-summary">
            {Number(panelData?.registry_total || 0).toLocaleString()} registered businesses ·{" "}
            {Number(panelData?.pins?.detected_not_in_registry || 0).toLocaleString()} found on the map, not in the registry ·{" "}
            {pendingInspections.toLocaleString()} being inspected
          </p>

          <section className="map-overview-detail-card">
            <div className="map-overview-card-heading">
              <h4>Registered businesses</h4>
              <AnalyticsInfoTip label="About registered businesses">
                Counts are from the official registry. The selected date range applies to map pins and inspections, not registry totals.
              </AnalyticsInfoTip>
            </div>
            <div className="map-overview-choice-row" role="group" aria-label="Business breakdown">
              {visibleDimensions.map((dimension) => (
                <button key={dimension.key} type="button"
                  className={selectedDimension?.key === dimension.key ? "active" : ""}
                  aria-pressed={selectedDimension?.key === dimension.key}
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
              <h4>Found on the map</h4>
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
            <ul className="map-overview-status-list">
              {pinRows.map((row) => (
                <li key={row.key}>
                  <span className="map-overview-count-swatch" style={{ background: row.color }} />
                  <span>{row.label}</span>
                  <strong>{row.count.toLocaleString()}</strong>
                </li>
              ))}
              {pinRows.length === 0 && <li className="map-overview-empty">No pins in this view yet.</li>}
            </ul>
            <p className="map-overview-note">
              {Number(panelData?.pins_without_location || 0).toLocaleString()} pins have no location
            </p>
          </section>

          <section className="map-overview-detail-card">
            <div className="map-overview-card-heading">
              <h4>Inspections</h4>
              <AnalyticsInfoTip label="About inspection progress">
                Not yet done combines Assigned, Reassigned, In Progress, and Unassigned reports. Waiting for review includes submitted reports.
              </AnalyticsInfoTip>
            </div>
            {Number(panelData?.inspections?.total || 0) === 0 ? (
              <p className="map-overview-empty">
                {selectedRow
                  ? "No inspections in this barangay yet."
                  : "No inspections yet across these barangays."}
              </p>
            ) : (
              <>
                <ul className="map-overview-status-list">
                  {inspectionRows.map((row) => (
                    <li key={row.key}>
                      <span className="map-overview-count-swatch"
                        style={{ background: STATUS_COLORS[row.key] }} />
                      <span>{row.label}</span>
                      <strong>{row.count.toLocaleString()}</strong>
                    </li>
                  ))}
                </ul>
                {Number(panelData?.inspections?.verified || 0) > 0 && (
                  <ul className="map-overview-outcome-list" aria-label="Verified results">
                    {["Green", "Yellow", "Red"].map((outcome) => (
                      <li key={outcome}>
                        <span className="map-overview-count-swatch"
                          style={{ background: STATUS_COLORS[outcome] }} />
                        <span>{outcome}</span>
                        <strong>{Number(panelData.inspections.outcomes?.[outcome] || 0).toLocaleString()}</strong>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </section>
        </aside>
      </div>
      {Number(panelData?.pins?.detection_with_business_id || 0) > 0 && (
        <p className="map-overview-anomaly" role="status">
          {Number(panelData.pins.detection_with_business_id).toLocaleString()} detected pins are already linked to a registered business.
        </p>
      )}
    </div>
  );
}
