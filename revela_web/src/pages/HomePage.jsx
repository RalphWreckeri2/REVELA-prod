/**
 * HomePage.jsx — Overview Dashboard
 * Progressive KPIs and priorities from /api/analytics/all section reads
 * Assignment deadlines and backend-ranked barangay priorities
 * Google Map preview with the existing flag population and marker behavior
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { GoogleMap } from "@react-google-maps/api";
import DashboardLayout from "../components/DashboardLayout";
import { SkeletonBlock } from "../components/LoadingSkeleton";
import Footer from "../components/Footer";
import { useAuth } from "../context/authContext";
import { useTheme } from "../context/themeContext";
import { useAnalyticsData } from "../components/useAnalyticsData";
import { useAppDataRefresh, useSessionDataset, refreshResults } from "../components/useAppDataRefresh";
import { hasDispatchableWlcTargets, wlcEligibilityLabel } from "../components/wlcPolicy";
import { getFlagsRequest, getInspectionsRequest, getInspectorsRequest, markNotificationsReadRequest } from "../services/api";
import { getBarangayCentroid } from "../utils/barangayCentroids";
import { useGoogleMapsScript } from "../utils/googleMaps";
import { REVELA_MAP_ID } from "../utils/mapStyles";
import { availableNumber, dateQuery, deadlinePresentation, formatOverviewNumber, manilaGreeting, weatherPresentation } from "./overviewPresentation";
import Swal from "sweetalert2";
import "../styles/HomePage.css";
import "../styles/OverviewDashboard.css";

const DEFAULT_CENTER = { lat: 13.9667, lng: 121.1167 };
const GOOGLE_MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";
const OVERVIEW_ANALYTICS_SECTIONS = ["summary", "prescriptive"];

const FLAG_COLORS = {
  Red: { marker: "#ef4444", bg: "var(--flag-red-bg)", text: "var(--flag-red-text)", label: "Detected Unregistered" },
  Yellow: { marker: "#f59e0b", bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)", label: "Suspected Unregistered" },
  Orange: { marker: "#e65100", bg: "var(--flag-orange-bg)", text: "var(--flag-orange-text)", label: "1st/2nd Warning / 3rd Notice Closure" },
  Black: { marker: "#000000", bg: "var(--flag-black-bg)", text: "var(--flag-black-text)", label: "Blacklisted / Non-Responsive" },
  Purple: { marker: "#7c3aed", bg: "var(--flag-purple-bg)", text: "var(--flag-purple-text)", label: "Closed / Abandoned" },
  Green: { marker: "#22c55e", bg: "var(--flag-green-bg)", text: "var(--flag-green-text)", label: "Active Business" },
};
const defaultColor = { marker: "var(--color-muted)", bg: "var(--flag-default-bg)", text: "var(--flag-default-text)", label: "Unknown" };
const getFlagColor = (c) => FLAG_COLORS[c] ?? defaultColor;

const parseColor = (f) => {
  const raw = f.flagColor || f.color || f.flag_color;
  if (!raw) return "Red";
  const s = String(raw).trim();
  if (!s) return "Red";
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
};

const shortBarangay = (name = "") => String(name ?? "").replace("Barangay ", "Brgy.");

// ── Hero Banner ───────────────────────────────────────────────────────────────
const HERO_SHORTCUTS = [
  { icon: "registry", label: "Open Registry", to: "/registry" },
  { icon: "map", label: "Review Geospatial Flags", to: "/map" },
  { icon: "inspection", label: "Manage Inspections", to: "/inspections" },
];

function OverviewIcon({ kind, className = "" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="18" height="18" aria-hidden="true">
      {kind === "registry" && <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8M8 17h6" /></>}
      {kind === "map" && <path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6zM9 3v15M15 6v15" />}
      {kind === "inspection" && <><rect x="4" y="4" width="16" height="18" rx="2" /><path d="M9 2h6v4H9zM8 13l3 3 5-6" /></>}
      {kind === "clock" && <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>}
      {kind === "arrow" && <path d="M5 12h14m-6-6 6 6-6 6" />}
      {kind === "refresh" && <path d="M20 3v5h-5M20 8a9 9 0 1 0 1 7" />}
    </svg>
  );
}

function RequestFeedback({ state, label }) {
  if (!state.loading && !state.error) return null;
  const message = state.loading
    ? `${state.hasResult ? "Refreshing" : "Loading"} ${label}…`
    : state.hasResult
      ? `Could not refresh ${label}. Showing last loaded data.`
      : `Could not load ${label}.`;
  return <p className={`overview-feedback${state.error && !state.loading ? " is-error" : ""}`} role="status">{message}</p>;
}

function PersonalizedGreeting({ user }) {
  const [greeting, setGreeting] = useState(() => manilaGreeting());
  useEffect(() => {
    // Only a greeting-period change rerenders this heading.
    const timer = setInterval(() => setGreeting(manilaGreeting()), 1000);
    return () => clearInterval(timer);
  }, []);
  const firstName = typeof user?.fullName === "string" && user.fullName.trim()
    ? user.fullName.trim().split(/\s+/)[0] : "Admin";
  return (
    <h1 className="hero-greeting" id="overview-greeting">
      {greeting},<br />
      <span className="hero-greeting-name">{firstName}</span>{" "}
      <span className="hero-wave" role="img" aria-label="waving hand">👋</span>
    </h1>
  );
}

const clockFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Manila", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true,
});
const clockDateFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Manila", weekday: "long", month: "long", day: "numeric", year: "numeric",
});

function PhilippineClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  const [time, amPm] = clockFormat.format(now).split(" ");
  return (
    <div className="hero-card hero-clock-card" aria-label="Philippine Time, UTC+8">
      <div className="hero-card-title"><OverviewIcon kind="clock" /> Philippine Time</div>
      <div className="hero-clock">{time} <span className="hero-clock-ampm">{amPm}</span></div>
      <p className="hero-card-date">{clockDateFormat.format(now)}</p>
      <p className="hero-card-foot">Asia/Manila · UTC+8</p>
    </div>
  );
}

function WeatherIcon({ kind }) {
  return (
    <svg data-weather-icon={kind} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="28" height="28" aria-hidden="true">
      {kind === "sun" && <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>}
      {kind === "partly-cloudy" && <><path d="M9 2v2M2 9h2M3.5 3.5 5 5M14.5 3.5 13 5" /><path d="M6 11a4 4 0 1 1 6-5" /></>}
      {["partly-cloudy", "cloud", "rain", "snow", "thunderstorm"].includes(kind) && <path d="M6 17a4 4 0 0 1-1-7.9A6 6 0 0 1 16.5 8 4.5 4.5 0 1 1 18 17" />}
      {kind === "rain" && <path d="m8 16-1 4m6-4-1 4m6-4-1 4" />}
      {kind === "snow" && <path d="M8 20h.01M12 22h.01M16 20h.01M10 17h.01M14 17h.01" strokeWidth="3" />}
      {kind === "thunderstorm" && <path d="m13 13-4 5h4l-2 5 6-7h-4l2-3" />}
      {kind === "fog" && <path d="M4 7h16M2 11h18M4 15h18M2 19h18" />}
      {kind === "unknown" && <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 17h.01" /></>}
    </svg>
  );
}

function SystemStatusRow({ label, value, tone = "neutral" }) {
  return (
    <div className={`hero-status-row is-${tone}`}>
      <dt><span className="hero-status-dot" aria-hidden="true" />{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function HeroBanner({ user, kpis, requestStates, mapsReady, mapsError, onRefresh, isRefreshing }) {
  const [weather, setWeather] = useState(null);
  const [weatherState, setWeatherState] = useState("loading");
  useEffect(() => {
    let cancelled = false;
    fetch("https://api.open-meteo.com/v1/forecast?latitude=13.9667&longitude=121.1167&current=temperature_2m,weather_code")
      .then(res => {
        if (!res.ok) throw new Error("Weather unavailable");
        return res.json();
      })
      .then(data => {
        if (cancelled) return;
        const presentation = weatherPresentation(data);
        if (!presentation) throw new Error("Weather unavailable");
        setWeather(presentation);
        setWeatherState(presentation.partial ? "partial" : "ready");
      })
      .catch(() => {
        if (!cancelled) setWeatherState("error");
      });
    return () => { cancelled = true; };
  }, []);

  const states = Object.values(requestStates);
  const dashboardLoading = states.some(state => state.loading);
  const dashboardError = states.some(state => state.error);
  const hasResult = states.some(state => state.hasResult);
  const metricsPartial = kpis && [kpis.total_businesses, kpis.compliance_rate,
    kpis.current_year_registered_count ?? kpis.current_year_count,
    kpis.upcoming_year_renewal_count, kpis.total_flagged].some(value => availableNumber(value) === null);
  const dashboardValue = dashboardLoading ? (hasResult ? "Refreshing…" : "Loading…")
    : dashboardError || metricsPartial ? (hasResult ? "Partial data" : "Unavailable") : "Loaded";
  const weatherValue = { loading: "Loading…", ready: "Loaded", partial: "Partial data", error: "Unavailable" }[weatherState];
  const registry = formatOverviewNumber(kpis?.total_businesses);

  return (
    <section className="hero-banner" aria-labelledby="overview-greeting">
      <div className="hero-left">
        <p className="hero-eyebrow">Mataasnakahoy · BPLO</p>
        <PersonalizedGreeting user={user} />
        <p className="hero-sub">Your municipal overview for registry records, geospatial flags, and outstanding inspection assignments.</p>
        <nav className="hero-shortcuts" aria-label="Workflow shortcuts">
          {HERO_SHORTCUTS.map(({ icon, label, to }) => (
            <Link key={to} className="hero-shortcut" to={to}>
              <span className={`hero-shortcut-icon is-${icon}`}><OverviewIcon kind={icon} /></span>
              <span>{label}</span>
              <OverviewIcon kind="arrow" className="hero-shortcut-arrow" />
            </Link>
          ))}
        </nav>
      </div>

      <div className="hero-right">
        <div className="hero-cards">
          <PhilippineClock />
          <div className="hero-card hero-weather-card" aria-busy={weatherState === "loading"}>
            <div className="hero-card-title">Local Weather</div>
            <div className="hero-weather-row">
              <span className="hero-temp">{weather?.temperature ?? "—"}</span>
              <span className={`hero-weather-icon is-${weather?.icon ?? "unknown"}`}><WeatherIcon kind={weather?.icon ?? "unknown"} /></span>
            </div>
            <p className="hero-cond">{weather?.description ?? (weatherState === "loading" ? "Loading weather…" : "Weather unavailable")}</p>
            <p className="hero-card-loc">Mataasnakahoy</p>
            {weather?.observation && <p className="hero-card-foot">Observed {weather.observation}</p>}
          </div>
        </div>

        <section className="hero-status-card" aria-labelledby="overview-system-status">
          <div className="hero-status-header">
            <h2 id="overview-system-status">System Status</h2>
            <button className="overview-refresh" type="button" onClick={onRefresh} disabled={isRefreshing}>
              <OverviewIcon kind="refresh" />
              <span>{isRefreshing ? "Refreshing dashboard…" : "Refresh dashboard"}</span>
            </button>
          </div>
          <dl>
            <SystemStatusRow label="Dashboard data" value={dashboardValue} tone={dashboardLoading ? "wait" : dashboardError || metricsPartial ? "error" : "ready"} />
            <SystemStatusRow label="Maps library" value={mapsError ? "Unavailable" : mapsReady ? "Ready" : "Loading…"} tone={mapsError ? "error" : mapsReady ? "ready" : "wait"} />
            <SystemStatusRow label="Weather feed" value={weatherValue} tone={weatherState === "ready" ? "ready" : weatherState === "loading" ? "wait" : "error"} />
            <SystemStatusRow label="Registry records" value={registry === "—" ? "Unavailable" : `${registry}${requestStates.kpis.error ? " · stale" : ""}`} />
          </dl>
        </section>
      </div>
    </section>
  );
}

function KpiSummary({ kpis, state, onRetry }) {
  const measures = [
    { label: "Total registry records", value: kpis?.total_businesses, note: "All records in the official registry." },
    { label: "Active share of registry", value: kpis?.compliance_rate, suffix: "%", note: "Active records as a share of all registry records." },
    { label: "Renewal/issue-year records", value: kpis?.current_year_registered_count ?? kpis?.current_year_count, note: "Renewal/issue date in the backend’s current year." },
    { label: "Next-year renewal basis — derived", value: kpis?.upcoming_year_renewal_count, note: "Current-year active and next-year dated records." },
    { label: "Non-green map locations", value: kpis?.total_flagged, note: "Non-green logs and registry-only locations shown on the Map." },
  ];
  const partial = state.hasResult && measures.some(measure => availableNumber(measure.value) === null);
  const metric = ({ label, value, suffix, note }, index) => (
    <div className={`overview-metric metric-${index}`} key={label}>
      <dt>{label}</dt>
      <dd aria-label={availableNumber(value) === null ? "Unavailable" : undefined}>
        {state.loading && !state.hasResult
          ? <SkeletonBlock style={{ width: 84, height: 24, margin: "0 auto" }} />
          : formatOverviewNumber(value, suffix)}
      </dd>
      <p>{note}</p>
    </div>
  );
  return (
    <section className="overview-surface overview-kpis" aria-labelledby="overview-kpi-title" aria-busy={state.loading}>
      <div className="overview-section-heading">
        <h2 id="overview-kpi-title">Registry &amp; Flag Summary</h2>
        <span className="overview-section-kicker">Overview</span>
      </div>
      <RequestFeedback state={state} label="summary metrics" />
      {state.error && !state.loading && <button type="button" className="overview-inline-action" onClick={onRetry}>Retry summary</button>}
      {partial && !state.error && <p className="overview-feedback" role="status">Some metric values are unavailable.</p>}
      <dl className="overview-kpis-primary">{measures.slice(0, 2).map(metric)}</dl>
      <dl className="overview-kpis-supporting">{measures.slice(2).map((measure, index) => metric(measure, index + 2))}</dl>
      <details className="overview-explanation">
        <summary>About these measures</summary>
        <p>Active share describes registry status, not municipality-wide compliance. The next-year basis is a derived count, not a renewal schedule.</p>
        <p>Current-year and next-year wording follows the backend’s reporting period{kpis?.reporting_year ? ` (${kpis.reporting_year})` : ""}, using each record’s renewal/issue date.</p>
        <p>This count includes non-green logs and non-green registry locations without a matching log, using the same population as the Map. Missing values appear as —; zero is a reported value.</p>
      </details>
    </section>
  );
}

function BarangayPrioritiesWidget({ opsRankings, state }) {
  // Preserve municipal WLC ranks; only display eligible new field destinations.
  const top5 = opsRankings.filter(b => b && hasDispatchableWlcTargets(b)).slice(0, 5);
  return (
    <section className="overview-surface overview-priorities" aria-labelledby="overview-priorities-title" aria-busy={state.loading}>
      <div className="overview-section-heading">
        <h2 id="overview-priorities-title">Barangay Inspection Priorities</h2>
      </div>
      <p className="overview-section-sub">Top five eligible field destinations in municipal WLC order.</p>
      <RequestFeedback state={state} label="barangay priorities" />
      {state.hasResult && top5.length === 0 && <p className="overview-empty">No barangays with targets eligible for a new inspection dispatch.</p>}
      <ol className="overview-priority-list">
        {state.loading && !state.hasResult ? (
          Array.from({ length: 4 }, (_, index) => (
            <li key={`skeleton-${index}`} aria-hidden="true">
              <SkeletonBlock style={{ height: 56, borderRadius: 10 }} />
            </li>
          ))
        ) : top5.map(b => {
          const category = typeof b.risk_level === "string" && b.risk_level.trim() ? b.risk_level : "Unavailable";
          const categoryClass = ["High", "Medium", "Low"].includes(category) ? category.toLowerCase() : "unknown";
          return (
            <li key={b.barangayID}>
              <Link className="overview-priority" to="/analytics" title="View Analytics">
                <span className="overview-priority-rank" aria-label={`Rank ${formatOverviewNumber(b.rank)}`}>{formatOverviewNumber(b.rank)}</span>
                <span className="overview-priority-main">
                  <span className="overview-priority-name">{shortBarangay(b.barangayName) || "Unknown barangay"}</span>
                  <span className="overview-priority-meta"><strong>{formatOverviewNumber(b.ops_score)}</strong>/100 OPS · {wlcEligibilityLabel(b)}</span>
                </span>
                <span className={`overview-priority-category is-${categoryClass}`}>{category}</span>
              </Link>
            </li>
          );
        })}
      </ol>
      <details className="overview-explanation">
        <summary>How priorities are ranked</summary>
        <p>OPS combines weighted flag burden, optional sector scores and proximity. Red, Yellow and Black flags supply risk context. New field plans skip Black-only barangays and already-assigned targets; the remaining destinations retain their municipal ranks.</p>
        <p>High: 60–100 · Medium: 30–below 60 · Low: below 30. These are barangay priorities, not counts of unassigned tasks.</p>
      </details>
      <Link className="overview-section-link" to="/analytics">View Analytics <OverviewIcon kind="arrow" /></Link>
    </section>
  );
}

// ── Mini Map Widget ───────────────────────────────────────────────────────────
function MiniMapWidget({ flags, state, isDark, onOpenMap, isLoaded, loadError }) {
  const [mapInstance, setMapInstance] = useState(null);
  const mapRef = useRef(null);
  const markerRefs = useRef([]);

  const buildMarkerEl = (color) => {
    const el = document.createElement("div");
    el.style.cssText = `width:22px;height:22px;cursor:pointer;filter:drop-shadow(0 2px 3px rgba(0,0,0,0.3))`;
    el.innerHTML = `<svg viewBox="0 0 24 32" width="22" height="22" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 9 12 20 12 20s12-11 12-20C24 5.37 18.63 0 12 0z" fill="${color}"/>
      <circle cx="12" cy="12" r="5" fill="white" opacity="0.9"/>
    </svg>`;
    return el;
  };

  const handleMapLoad = useCallback((map) => {
    mapRef.current = map;
    setMapInstance(map);
  }, []);

  // Place markers once map + flags are ready
  useEffect(() => {
    const activeMap = mapInstance || mapRef.current;
    if (!isLoaded || !activeMap) return;

    // Clear old markers
    markerRefs.current.forEach(m => {
      if (typeof m.setMap === "function") m.setMap(null);
      else m.map = null;
    });
    markerRefs.current = [];

    const canUseAdvanced = Boolean(window.google?.maps?.marker?.AdvancedMarkerElement);

    flags
      .slice(0, 100) // cap for performance
      .forEach(f => {
        const fc = getFlagColor(parseColor(f));
        const rawLat = f.latitude != null ? Number(f.latitude) : null;
        const rawLng = f.longitude != null ? Number(f.longitude) : null;
        const hasCoords = rawLat != null && rawLng != null && !isNaN(rawLat) && !isNaN(rawLng) && rawLat !== 0 && rawLng !== 0;
        const centroid = !hasCoords ? getBarangayCentroid(f.barangayName || f.barangay) : null;
        const position = {
          lat: hasCoords ? rawLat : (centroid?.lat ?? DEFAULT_CENTER.lat),
          lng: hasCoords ? rawLng : (centroid?.lng ?? DEFAULT_CENTER.lng),
        };
        let marker = null;

        if (canUseAdvanced) {
          try {
            marker = new window.google.maps.marker.AdvancedMarkerElement({
              position,
              map: activeMap,
              content: buildMarkerEl(fc.marker),
            });
          } catch {
            marker = null;
          }
        }

        if (!marker) {
          marker = new window.google.maps.Marker({
            position,
            map: activeMap,
            icon: {
              path: "M12 0C5.37 0 0 5.37 0 12c0 9 12 20 12 20s12-11 12-20C24 5.37 18.63 0 12 0z",
              fillColor: fc.marker,
              fillOpacity: 1,
              strokeColor: "#ffffff",
              strokeWeight: 1,
              scale: 0.8,
              anchor: new window.google.maps.Point(12, 32),
            }
          });
        }

        markerRefs.current.push(marker);
      });

    return () => {
      markerRefs.current.forEach(m => {
        if (typeof m.setMap === "function") m.setMap(null);
        else m.map = null;
      });
      markerRefs.current = [];
    };
  }, [isLoaded, mapInstance, flags]);

  const nonGreenPreviewCount = flags.slice(0, 100).filter(f => parseColor(f) !== "Green").length;

  return (
    <section className="overview-surface overview-map" aria-labelledby="overview-map-title" aria-busy={state.loading || (!isLoaded && !loadError)}>
      <div className="overview-section-heading">
        <h2 id="overview-map-title">Map Preview</h2>
        <button className="overview-inline-action" type="button" onClick={onOpenMap}>
          Open Full Map ↗
        </button>
      </div>
      <RequestFeedback state={state} label="map records" />
      <p className="overview-section-sub">Up to 100 markers from the {state.hasResult ? formatOverviewNumber(flags.length) : "—"} loaded records. Open the full map to explore more.</p>
      <div className="overview-map-canvas">
        {loadError ? (
          <div style={miniMapFallback}>
            <span>⚠ Google Maps failed to load.</span>
            <small>{GOOGLE_MAPS_API_KEY
              ? `Google Maps error: ${loadError?.message || String(loadError)}`
              : "No VITE_GOOGLE_MAPS_API_KEY configured in .env"
            }</small>
          </div>
        ) : !isLoaded ? (
          <div style={miniMapFallback}>Loading map…</div>
        ) : (
          <GoogleMap
            mapContainerStyle={{ width: "100%", height: "100%" }}
            center={DEFAULT_CENTER}
            zoom={12}
            options={{
              disableDefaultUI: true,
              clickableIcons: false,
              zoomControl: false,
              mapId: REVELA_MAP_ID,
              colorScheme: isDark ? "DARK" : "LIGHT",
            }}
            onLoad={handleMapLoad}
          />
        )}

        {/* Clickable overlay to open full map */}
        <button
          type="button"
          className="overview-map-open"
          onClick={onOpenMap}
          aria-label="Open Full Map from preview"
          title="Open full map"
        />

        {/* Flag count badge */}
        {state.hasResult && (
          <div className="overview-map-count">
            {formatOverviewNumber(nonGreenPreviewCount)} non-green records in preview
          </div>
        )}
      </div>

        {/* Mini legend */}
      <ul className="overview-map-legend" aria-label="Flag legend">
        {Object.entries(FLAG_COLORS).map(([color, meta]) => (
          <li key={color}>
            <span style={{ background: meta.marker }} aria-hidden="true" />
            {meta.label}
          </li>
        ))}
      </ul>
      {state.hasResult && flags.length === 0 && <p className="overview-empty">No map records in the loaded results.</p>}
    </section>
  );
}

const miniMapFallback = {
  width: "100%", height: "100%", display: "flex", flexDirection: "column",
  alignItems: "center", justifyContent: "center", gap: 6,
  background: "var(--color-surface)", color: "var(--color-muted)", fontSize: 13, textAlign: "center",
};

// ── Visual Calendar Widget ──────────────────────────────────────────────────
function VisualCalendarWidget({ inspections, state, navigate }) {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [selectedDay, setSelectedDay] = useState(null);

  // Get days in month
  const getDaysInMonth = (date) => new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
  const getFirstDayOfMonth = (date) => new Date(date.getFullYear(), date.getMonth(), 1).getDay();

  const daysInMonth = getDaysInMonth(currentDate);
  const firstDay = getFirstDayOfMonth(currentDate);

  const prevMonth = () => { setCurrentDate(new Date(currentDate.getFullYear(), currentDate.getMonth() - 1, 1)); setSelectedDay(null); };
  const nextMonth = () => { setCurrentDate(new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 1)); setSelectedDay(null); };

  const monthName = currentDate.toLocaleString('default', { month: 'long', year: 'numeric' });
  const weekDays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  const { outstanding, statusByDate, tasksByDate, displayedTasks } = deadlinePresentation(inspections, currentDate, selectedDay);
  const selectedDate = selectedDay !== null ? new Date(currentDate.getFullYear(), currentDate.getMonth(), selectedDay) : null;
  const activityPath = `/inspections/calendar${selectedDate ? `?date=${dateQuery(selectedDate)}` : ""}`;

  return (
    <section className="overview-surface calendar-widget" aria-labelledby="overview-deadlines-title" aria-busy={state.loading}>
      <div className="overview-section-heading">
        <h2 id="overview-deadlines-title">Assignment Deadlines</h2>
      </div>
      <p className="overview-section-sub">Outstanding assignments in the loaded inspection records.</p>
      <RequestFeedback state={state} label="assignment deadlines" />
      <div className="calendar-widget-header">
        <h3 className="calendar-widget-title">
          <svg className="calendar-widget-title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16" aria-hidden="true">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
            <line x1="16" y1="2" x2="16" y2="6" />
            <line x1="8" y1="2" x2="8" y2="6" />
            <line x1="3" y1="10" x2="21" y2="10" />
          </svg>
          <span>{monthName}</span>
        </h3>

        <div className="calendar-widget-controls">
          <div className="calendar-widget-nav" role="group" aria-label="Month navigation">
            <button type="button" onClick={prevMonth} aria-label="Previous month" title="Previous month">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14" aria-hidden="true">
                <polyline points="15 18 9 12 15 6" />
              </svg>
            </button>
            <button type="button" onClick={nextMonth} aria-label="Next month" title="Next month">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14" aria-hidden="true">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <div className="calendar-widget-weekdays">
        {weekDays.map(day => (
          <span key={day}>{day}</span>
        ))}
      </div>

      <div className="calendar-widget-grid">
        {Array.from({ length: firstDay }).map((_, i) => <span key={`empty-${i}`} />)}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const day = i + 1;
          const status = statusByDate[day];
          const now = new Date();
          const isToday =
            now.getDate() === day &&
            now.getMonth() === currentDate.getMonth() &&
            now.getFullYear() === currentDate.getFullYear();
          const isSelected = selectedDay === day;
          const taskCount = tasksByDate[day]?.length ?? 0;

          const classes = [
            "calendar-widget-day",
            status === "overdue" ? "is-overdue" : "",
            status === "upcoming" ? "is-upcoming" : "",
            isToday ? "is-today" : "",
            isSelected ? "is-selected" : "",
          ].filter(Boolean).join(" ");

          return (
            <button
              key={day}
              type="button"
              className={classes}
              onClick={() => setSelectedDay(day === selectedDay ? null : day)}
              aria-pressed={isSelected}
              aria-current={isToday ? "date" : undefined}
              aria-label={`${monthName} ${day}${isToday ? " (today)" : ""}, ${
                !state.hasResult ? "deadlines unavailable" : taskCount === 0
                  ? "no outstanding deadlines"
                  : `${taskCount} outstanding ${taskCount === 1 ? "deadline" : "deadlines"}${status === "overdue" ? ", overdue" : ", upcoming"}`
              }`}
            >
              <span className="calendar-widget-day-number">{day}</span>
              <span
                className={`calendar-widget-day-dot${status ? ` is-${status}` : ""}`}
                aria-hidden="true"
              />
            </button>
          );
        })}
      </div>

      <div className="calendar-widget-legend" aria-label="Deadline indicators">
        <span><i className="is-overdue" aria-hidden="true" />Overdue</span>
        <span><i className="is-upcoming" aria-hidden="true" />Upcoming</span>
        <span className="calendar-widget-today-key">Today</span>
      </div>
      <div className="calendar-widget-tasks">
        <div className="calendar-widget-tasks-header">
          <h3 id="overview-selected-deadlines" aria-live="polite">
            {selectedDate ? `Deadlines · ${selectedDate.toLocaleDateString("en-PH", { month: "short", day: "numeric" })}` : "Earliest outstanding"}
          </h3>
          {selectedDate && (
            <button className="overview-inline-action" type="button" onClick={() => setSelectedDay(null)}>Clear date</button>
          )}
        </div>
        <div className="calendar-widget-task-list" aria-labelledby="overview-selected-deadlines">
          {state.hasResult && displayedTasks.length === 0 ? (
            <p className="overview-empty">{selectedDate ? "No outstanding deadlines for this date in the loaded records." : "No outstanding assignment deadlines in the loaded records."}</p>
          ) : displayedTasks.map(task => {
            const isOverdue = new Date(task.deadline) < new Date();
            return (
              <button
                type="button"
                key={task.reportID}
                className={`calendar-widget-task${isOverdue ? " is-overdue" : ""}`}
                onClick={() => navigate('/inspections')}
                title="Open Inspection Dispatch"
              >
                <span className="calendar-widget-task-main">
                  <span className="calendar-widget-task-name">{task.detectedName || "Unknown establishment"}</span>
                  <span className="calendar-widget-task-meta">Inspector: {task.inspectorName || "Unknown"}</span>
                </span>
                <span className="calendar-widget-task-due">
                  <strong>{isOverdue ? "Overdue" : "Due"}</strong>
                  <span>{new Date(task.deadline).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                </span>
              </button>
            );
          })}
        </div>
        {!selectedDate && outstanding.length > 3 && <p className="overview-scope-note">Showing the earliest three deadlines. Select a date to see its assignments.</p>}
      </div>
      <p className="overview-scope-note">Based on up to 1,000 loaded inspection records. Task links open Dispatch.</p>
      <Link className="overview-section-link" to={activityPath} title="Review recorded inspection lifecycle activity">View Inspection Activity <OverviewIcon kind="arrow" /></Link>
    </section>
  );
}

// ── Recent Detections Widget ──────────────────────────────────────────────────


function InspectorReportsModal({ isOpen, onClose, flags, inspectors, navigate }) {
  const [searchTerm, setSearchTerm] = useState("");
  const [filterInspector, setFilterInspector] = useState("");

  if (!isOpen) return null;

  const filteredFlags = flags.filter(f => {
    // Show only flags reported by an inspector that are not verified as compliant (Green)
    if (!f.reportedByUserID || parseColor(f) === 'Green') return false;
    if (searchTerm) {
      const q = searchTerm.trim().toLowerCase();
      const cleanQ = q.startsWith("#") ? q.slice(1).trim() : q;
      const hay = [
        f.detectedName, f.name, f.barangayName, f.barangay, f.resolvedAddress, f.notes, f.inspectorName
      ].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(q) && !String(f.logID || f.id || "").toLowerCase().includes(cleanQ)) return false;
    }
    if (filterInspector && f.reportedByUserID !== Number(filterInspector)) return false;
    return true;
  });

  return (
    <div className="modal-backdrop" onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="modal-panel modal-content saas-card" onClick={e => e.stopPropagation()} style={{ width: 1040, maxWidth: "95vw", height: "85vh", display: "flex", flexDirection: "column", padding: 32, borderRadius: 24, background: "var(--color-modal-bg)", boxShadow: "0 24px 48px rgba(0,0,0,0.2)" }}>

        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ width: 12, height: 12, borderRadius: "50%", background: "var(--color-primary)", display: "inline-block" }}></span>
            Submitted Backlog <span style={{ color: "var(--color-muted)", fontSize: 16, fontWeight: 600 }}>({filteredFlags.length})</span>
          </h2>

          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <select
              className="saas-input"
              value={filterInspector}
              onChange={e => setFilterInspector(e.target.value)}
              style={{ padding: "8px 14px", minWidth: 160, borderRadius: 8, background: "transparent" }}
            >
              <option value="">All Flags</option>
              {inspectors.map(insp => (
                <option key={insp.userID} value={insp.userID}>{insp.fullName}</option>
              ))}
            </select>

            <div style={{ position: "relative" }}>
              <svg style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--color-muted)", pointerEvents: "none" }} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
              <input
                type="text"
                placeholder="Search name, ID, barangay..."
                className="saas-input"
                style={{ padding: "8px 30px 8px 36px", width: 220, borderRadius: 8, background: "transparent" }}
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
              />
              {searchTerm && (
                <button
                  type="button"
                  onClick={() => setSearchTerm("")}
                  style={{
                    position: "absolute",
                    right: 8,
                    top: "50%",
                    transform: "translateY(-50%)",
                    background: "transparent",
                    border: "none",
                    color: "var(--color-muted)",
                    cursor: "pointer",
                    padding: 2,
                    display: "flex",
                    alignItems: "center"
                  }}
                  title="Clear search"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </button>
              )}
            </div>

            <button className="modal-close-btn" onClick={onClose} style={{ marginLeft: 12 }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
        </div>

        {/* Grid Content */}
        <div style={{ flex: 1, overflowY: "auto", paddingRight: 16 }}>
          {filteredFlags.length === 0 ? (
            <div style={{ textAlign: "center", padding: "60px 0", color: "var(--color-muted)", fontSize: 15, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
              <img src="/searching.png" alt="No backlog items" style={{ height: 100, objectFit: "contain", opacity: 0.9 }} />
              No backlog items found matching your criteria.
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
              {filteredFlags.map(f => {
                const fc = getFlagColor(parseColor(f));
                const isRed = parseColor(f) === "Red";

                return (
                  <div
                    key={f.logID || f.id}
                    className="hover-lift"
                    onClick={() => { onClose(); navigate('/map?flag=' + (f.logID || f.id)); }}
                    style={{
                      background: "var(--color-surface)",
                      border: isRed ? "1px solid var(--color-danger)" : "1px solid var(--color-border-soft)",
                      borderRadius: 16,
                      padding: 20,
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                      cursor: "pointer",
                      boxShadow: "0 2px 10px rgba(0,0,0,0.02)",
                      minHeight: 120
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 12, background: fc.bg, color: fc.text, display: "flex", alignItems: "center", gap: 6 }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" y1="22" x2="4" y2="15" /></svg>
                          {fc.label}
                        </span>
                        {f.noticeLevel && (
                          <>
                            <span style={{ color: "var(--color-muted)", fontSize: 12 }}>&gt;</span>
                            <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 12, background: "var(--flag-orange-bg)", color: "var(--flag-orange-text)" }}>
                              {f.noticeLevel}
                            </span>
                          </>
                        )}
                      </div>
                    </div>

                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                      <div style={{ flex: 1, paddingRight: 16 }}>
                        <h4 style={{ margin: "0 0 8px 0", fontSize: 16, fontWeight: 800, color: "var(--color-ink)", lineHeight: 1.3 }}>{f.detectedName || f.name || "Unknown Establishment"}</h4>
                        <p style={{ margin: 0, fontSize: 13, color: "var(--color-muted)", display: "flex", alignItems: "center", gap: 6 }}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
                          {shortBarangay(f.barangayName || f.barangay || "—")}
                        </p>
                      </div>

                      <button style={{ width: 36, height: 36, borderRadius: "50%", border: "1px solid var(--color-border-soft)", background: "transparent", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: "var(--color-ink)", flexShrink: 0 }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6" /></svg>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function HomePage() {
  const { token, user } = useAuth();
  const { theme, resolvedTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const welcomeHandledRef = useRef(false);

  const isDark = resolvedTheme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);

  const { isLoaded, loadError } = useGoogleMapsScript();


  const { sections, refresh: refreshAnalytics } = useAnalyticsData(token, undefined, OVERVIEW_ANALYTICS_SECTIONS, null);
  const summary = sections.summary;
  const priorities = sections.prescriptive;
  const kpis = summary.data?.kpis;
  const opsRankings = priorities.data?.rankings ?? [];
  const rollover = summary.data?.new_year_rollover;

  // Flags
  const [allFlags, setAllFlags, hasFlags] = useSessionDataset("home", "flags", []);
  const [inspections, setInspections, hasInspections] = useSessionDataset("home", "inspections", []);
  const [inspectors, setInspectors, hasInspectors] = useSessionDataset("home", "inspectors", []);
  const [isInspectorModalOpen, setIsInspectorModalOpen] = useState(false);
  const [auxiliaryRefreshing, setAuxiliaryRefreshing] = useState(false);
  const [auxiliaryStates, setAuxiliaryStates] = useState(() => Object.fromEntries(
    Object.entries({ flags: hasFlags, inspections: hasInspections, inspectors: hasInspectors })
      .map(([key, hasResult]) => [key, { loading: !hasResult, error: false, hasResult }]),
  ));
  const sectionState = (section, valid) => ({
    loading: section.status === "loading" || section.updating,
    error: Boolean(section.error) || (!section.updating && section.status !== "loading" && !valid),
    hasResult: valid,
  });
  const requestStates = {
    ...auxiliaryStates,
    kpis: sectionState(summary, Boolean(kpis && typeof kpis === "object" && !Array.isArray(kpis))),
    ops: sectionState(priorities, Array.isArray(priorities.data?.rankings)),
  };
  const isRefreshing = auxiliaryRefreshing || Object.values(sections).some(section => section.updating);
  const dashboardRequestRef = useRef(null);

  useEffect(() => {
    if (!location.state?.showWelcome || !user || welcomeHandledRef.current) {
      return;
    }
    welcomeHandledRef.current = true;
    void Swal.fire({
      icon: "success",
      title: "Welcome!",
      text: "Welcome back, BPLO Officer.",
      timer: 2000,
      showConfirmButton: false,
    });
    navigate(location.pathname, { replace: true, state: null });
  }, [location.pathname, location.state, navigate, user]);

  const fetchDashboardData = useCallback(async (isSilent = false) => {
    if (!token) return;
    // Manual refresh, polling and focus share active work rather than restarting it.
    if (dashboardRequestRef.current) return dashboardRequestRef.current.promise;
    const controller = new AbortController();
    dashboardRequestRef.current = controller;
    if (!isSilent) {
      setAuxiliaryRefreshing(true);
    }
    setAuxiliaryStates(previous => Object.fromEntries(Object.entries(previous).map(([key, state]) => [key, { ...state, loading: !state.hasResult, error: false }])));

    const load = async (key, request, select, commit) => {
      const attempt = new AbortController();
      const abort = () => attempt.abort();
      controller.signal.addEventListener("abort", abort, { once: true });
      const timer = window.setTimeout(abort, 20000);
      try {
        const result = select(await request(attempt.signal));
        if (controller.signal.aborted) return;
        if (attempt.signal.aborted) throw new Error("Dashboard request timed out");
        if (!Array.isArray(result)) throw new Error("Invalid dashboard response");
        commit(result);
        setAuxiliaryStates(previous => ({ ...previous, [key]: { loading: false, error: false, hasResult: true } }));
        return true;
      } catch {
        if (!controller.signal.aborted) {
          setAuxiliaryStates(previous => ({ ...previous, [key]: { ...previous[key], loading: false, error: true } }));
        }
        return false;
      } finally {
        window.clearTimeout(timer);
        controller.signal.removeEventListener("abort", abort);
      }
    };
    controller.promise = Promise.all([
      load("flags", signal => getFlagsRequest({ limit: 200, signal }, token), result => result?.data, setAllFlags),
      load("inspections", signal => getInspectionsRequest({ limit: 1000, signal }, token), result => result?.data, setInspections),
      load("inspectors", signal => getInspectorsRequest(token, { signal }), result => result?.data ?? result, setInspectors),
    ]).then(results => results.every(Boolean)).finally(() => {
      if (dashboardRequestRef.current === controller) {
        dashboardRequestRef.current = null;
        setAuxiliaryRefreshing(false);
      }
    });
    return controller.promise;
  }, [token, setAllFlags, setInspections, setInspectors]);
  const refreshView = useAppDataRefresh("home", reason => refreshResults([
    refreshAnalytics(), fetchDashboardData(reason === "scheduled"),
  ]));

  useEffect(() => {
    if (rollover?.detected) {
      Swal.fire({
        title: "Happy New Year!",
        html: `<div style="text-align: left; font-size: 13.5px; line-height: 1.6; color: var(--color-ink);">` +
          `Welcome to <b>${rollover.year}</b>!<br/><br/>` +
          `The system has automatically marked <b>${rollover.count}</b> active business permits from previous years as <span style="color: var(--color-danger); font-weight: 700;">Expired</span> and their map flags as <span style="color: var(--color-danger); font-weight: 700;">Red</span>.<br/><br/>` +
          `Let's upload/sync the new BPLO registry to update their statuses.</div>`,
        icon: "info",
        confirmButtonText: "Upload Registry Now",
        showCancelButton: true,
        cancelButtonText: "Later",
        confirmButtonColor: "var(--color-primary-dark)",
        cancelButtonColor: "var(--color-muted)",
        background: "var(--color-surface)",
        color: "var(--color-ink)",
        customClass: {
          popup: 'frosted-glass saas-card',
          confirmButton: 'primary-btn',
          cancelButton: 'ghost-btn'
        }
      }).then((result) => {
        if (rollover.notification_id) {
          markNotificationsReadRequest(token, [rollover.notification_id]).catch(() => { });
        }
        if (result.isConfirmed) {
          navigate("/registry");
        }
      });
    }
  }, [rollover, token, navigate]);

  useEffect(() => () => {
    dashboardRequestRef.current?.abort();
    dashboardRequestRef.current = null;
  }, [fetchDashboardData]);

  return (
    <DashboardLayout className="overview-page">
      {Object.values(sections).some(section => section.status === "expired") && (
        <p role="alert" className="saas-card" style={{ padding: 14, marginBottom: 14 }}>
          Stale analytics: the displayed overview is the last successful snapshot, not current data.
          Last computed: {summary.metadata?.computed_at ?? priorities.metadata?.computed_at ?? "unknown"}.
          <button type="button" className="ghost-btn" onClick={refreshView}>Refresh now</button>
        </p>
      )}
      {/* Main Layout: 2 Columns */}
      <div className="overview-dashboard-layout">

        {/* Left Column (Main Content) */}
        <div className="overview-main-column">
          <HeroBanner
            user={user}
            kpis={kpis}
            requestStates={requestStates}
            mapsReady={isLoaded}
            mapsError={loadError}
            onRefresh={refreshView}
            isRefreshing={isRefreshing}
          />

          <KpiSummary kpis={kpis} state={requestStates.kpis} onRetry={refreshAnalytics} />

          {/* Map */}
          <MiniMapWidget
            flags={allFlags}
            state={requestStates.flags}
            isDark={isDark}
            onOpenMap={() => navigate("/map")}
            isLoaded={isLoaded}
            loadError={loadError}
          />
        </div>

        {/* Right Column (Sidebar) */}
        <div className="overview-side-column">
          <VisualCalendarWidget inspections={inspections} state={requestStates.inspections} navigate={navigate} />
          <BarangayPrioritiesWidget
            opsRankings={opsRankings}
            state={requestStates.ops}
          />
        </div>
      </div>

      {/* Footer */}
      <Footer style={{ marginTop: 32, width: "100%", boxSizing: "border-box" }} />

      {/* Modals */}
      <InspectorReportsModal
        isOpen={isInspectorModalOpen}
        onClose={() => setIsInspectorModalOpen(false)}
        flags={allFlags}
        inspectors={inspectors}
        navigate={navigate}
      />
    </DashboardLayout>
  );
}
