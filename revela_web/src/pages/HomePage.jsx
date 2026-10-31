/**
 * HomePage.jsx — Overview Dashboard
 * Progressive KPIs and priorities from /api/analytics/all section reads
 * Assignment deadlines and backend-ranked barangay priorities
 * Google Map preview with the existing flag population and marker behavior
 */

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { GoogleMap } from "@react-google-maps/api";
import DashboardLayout from "../components/DashboardLayout";
import { SkeletonBlock } from "../components/LoadingSkeleton";
import Footer from "../components/Footer";
import { useAuth } from "../context/authContext";
import { useTheme } from "../context/themeContext";
import { useAnalyticsData } from "../components/useAnalyticsData";
import { useAppDataRefresh, useSessionDataset, refreshResults } from "../components/useAppDataRefresh";
import { hasDispatchableWlcTargets } from "../components/wlcPolicy";
import { getFlagsRequest, getInspectionsRequest, getInspectorsRequest, getRegistryRequest, getInspectionWorkloadRequest, markNotificationsReadRequest } from "../services/api";
import {
  DEFAULT_MAP_CENTER,
  getApproximateBarangayDisplayPoint,
} from "../utils/barangayCentroids";
import {
  APPROXIMATE_LOCATION_LABEL,
  createApproximateMarkerContent,
  createApproximateMarkerIcon,
} from "../components/approximateMapMarker";
import { useGoogleMapsScript } from "../utils/googleMaps";
import { REVELA_MAP_ID } from "../utils/mapStyles";
import {
  createCentroidPreviewFlags,
  hasMapCoordinates,
} from "../components/mapLocationMetrics";
import { formatElapsedMinutes } from "../utils/formatElapsedMinutes";
import { dateQuery, deadlinePresentation, formatOverviewNumber, formatOverviewPeriod, formatOverviewUpdatedAt, manilaGreeting, weatherPresentation } from "./overviewPresentation";
import Swal from "sweetalert2";
import "../styles/HomePage.css";
import "../styles/OverviewDashboard.css";

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
function OverviewIcon({ kind, className = "" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" width="18" height="18" aria-hidden="true">
      {kind === "clock" && <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>}
      {kind === "arrow" && <path d="M5 12h14m-6-6 6 6-6 6" />}
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
      {greeting},{" "}
      <span className="hero-greeting-name">{firstName}</span>{" "}
    </h1>
  );
}

const clockFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Manila", hour: "numeric", minute: "2-digit", hour12: true,
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

function HeroBanner({ user }) {
  const [weather, setWeather] = useState(null);
  const [weatherState, setWeatherState] = useState("loading");
  useEffect(() => {
    let cancelled = false;
    const weatherUrl = new URL("https://api.open-meteo.com/v1/forecast");
    weatherUrl.search = new URLSearchParams({
      latitude: String(DEFAULT_MAP_CENTER.lat),
      longitude: String(DEFAULT_MAP_CENTER.lng),
      current: "temperature_2m,weather_code",
    });
    fetch(weatherUrl)
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

  return (
    <section className="hero-banner" aria-labelledby="overview-greeting">
      <div className="hero-left">
        <p className="hero-eyebrow">BPLO · Mataasnakahoy</p>
        <PersonalizedGreeting user={user} />
        <p className="hero-sub">A quick look at what matters today.</p>
      </div>

      <div className="hero-right">
        <div className="hero-cards">
          <PhilippineClock />
          <div className="hero-card hero-weather-card" aria-busy={weatherState === "loading"}>
            <div className="hero-card-title">Weather in Mataasnakahoy</div>
            <div className="hero-weather-row">
              <span className="hero-temp">{weather?.temperature ?? "—"}</span>
              <span className={`hero-weather-icon is-${weather?.icon ?? "unknown"}`}><WeatherIcon kind={weather?.icon ?? "unknown"} /></span>
            </div>
            <p className="hero-cond">{weather?.description ?? (weatherState === "loading" ? "Loading weather…" : "Weather unavailable")}</p>
            <p className="hero-card-loc">Mataasnakahoy</p>
            {weather?.observation && <p className="hero-card-foot">Observed {weather.observation}</p>}
          </div>
        </div>

      </div>
    </section>
  );
}

function ActionCard({ label, value, to, note, state, suffix = "", empty = "No data", formatValue, tone = "neutral" }) {
  const shown = !state.hasResult ? state.error ? "Could not load" : "Loading…"
    : formatValue ? formatValue(value) : value === null || value === undefined ? empty : `${formatOverviewNumber(value)}${suffix}`;
  return <Link className={`overview-action-card is-${tone}`} to={to} aria-label={`${label}: ${shown}. ${note}`}>
    <span className="overview-action-label">{label}</span><strong>{shown}</strong>
    <small>{note}{state.error && state.hasResult ? " · Last loaded data" : ""}</small>
    <OverviewIcon kind="arrow" className="overview-action-arrow" />
  </Link>;
}

const sourcePath = source => `/map?source=${source}&registryLink=unlinked`;
const workloadPath = (view, reportID) => `/inspections?view=${encodeURIComponent(view)}${reportID ? `&reportID=${reportID}` : ""}`;

function SourceCards({ sources, states }) {
  const cards = [
    ["Registered businesses", sources.registry?.total, "/registry", "In the business registry", states.registry, "registry"],
    ["Unlinked map detections", sources.detection?.total, sourcePath("detection"), "Not yet linked to the registry", states.detection, "detection"],
    ["Unlinked inspector reports", sources.manual?.total, sourcePath("manual"), "Not yet linked to the registry", states.manual, "manual"],
  ];
  if (sources.unclassified?.total > 0 || states.unclassified.error) cards.push(
    ["Unclassified Records", sources.unclassified?.total, sourcePath("unclassified"), "Unknown source", states.unclassified, "unclassified"]);
  return <section className="overview-surface overview-business-records" aria-labelledby="overview-source-title">
    <div className="overview-section-heading"><h2 id="overview-source-title">Business records</h2></div>
    <p className="overview-section-sub">Where the business information comes from.</p>
    <div className="overview-action-grid source-grid">{cards.map(([label, value, to, note, state, tone]) =>
      <ActionCard key={label} {...{ label, value, to, note, state, tone }} />)}</div>
    <details className="overview-explanation"><summary>What these counts mean</summary>
      <p>Registry counts are businesses. Unlinked counts are map records, not confirmed separate businesses. Linked detections and manual records are already part of the registry. Records with an unknown source stay unclassified. These totals should not be added together.</p>
    </details>
  </section>;
}

function NeedsAttention({ data, state }) {
  const updatedAt = formatOverviewUpdatedAt(data?.as_of);
  return <section className="overview-surface overview-attention" aria-labelledby="overview-attention-title">
    <div className="overview-section-heading"><div><p className="overview-section-kicker">Your starting point</p><h2 id="overview-attention-title">Needs your attention</h2></div>
      {data && <span className="overview-updated-at">{updatedAt ?? "Update time unavailable"}</span>}</div>
    <RequestFeedback state={state} label="inspection workload" />
    <div className="overview-action-grid attention-grid">
      <ActionCard label="Overdue assignments" value={data?.overdue} empty="Unavailable" to={workloadPath("overdue")}
        note={data?.overdue === 0 ? "None overdue" : "Past their due date"} state={state} tone={data?.overdue > 0 ? "warning" : "neutral"} />
      <ActionCard label="Awaiting verification" value={data?.awaiting_verification} empty="Unavailable" to={workloadPath("awaiting_verification")}
        note={data?.awaiting_verification === 0 ? "Nothing awaiting review" : "Submitted for review"} state={state} tone={data?.awaiting_verification > 0 ? "review" : "neutral"} />
      <ActionCard label="Open 15+ days" value={data?.age_groups?.["15+"]} empty="Unavailable" to={workloadPath("age_15+")}
        note={data?.age_groups?.["15+"] === 0 ? "None pending 15+ days" : "Waiting 15 days or more"} state={state} tone={data?.age_groups?.["15+"] > 0 ? "warning" : "neutral"} />
    </div>
    <InspectionSnapshot data={data} state={state} />
  </section>;
}

function InspectionSnapshot({ data, state }) {
  const groups = data?.age_groups || {};
  const qualityItems = data ? [
    data.missing_deadlines > 0 && `${data.missing_deadlines} missing due dates`,
    data.age_unavailable > 0 && `${data.age_unavailable} without a start date`,
    data.older_hidden_open_reports > 0 && `${data.older_hidden_open_reports} older open not counted`,
    data.invalid_deadlines > 0 && `${data.invalid_deadlines} invalid due dates`,
    data.ambiguous_deadlines > 0 && `${data.ambiguous_deadlines} due dates need a time check`,
    data.legacy_in_progress > 0 && `${data.legacy_in_progress} in-progress not counted`,
    data.missing_submission_received > 0 && `${data.missing_submission_received} missing received times`,
    data.resolution_excluded > 0 && `${data.resolution_excluded} durations not used`,
  ].filter(Boolean) : [];
  const updatedAt = formatOverviewUpdatedAt(data?.as_of);
  const period = formatOverviewPeriod(data?.period_from, data?.period_to);
  return <details className="overview-workload" aria-labelledby="overview-workload-title">
    <summary className="overview-workload-toggle" id="overview-workload-title">
      <span>More about open assignments</span>
      {state.hasResult && <small>{formatOverviewNumber(data?.open)} currently open</small>}
    </summary>
    <div className="overview-action-grid workload-grid">
      <ActionCard label="Open assignments" value={data?.open} to={workloadPath("open")} note="Currently in dispatch" state={state} />
      <ActionCard label="Oldest open" value={data?.oldest_open_days} empty={data?.open === 0 ? "None open" : "Age unavailable"} formatValue={days => days == null ? data?.open === 0 ? "None open" : "Age unavailable" : `${formatOverviewNumber(days)} ${days === 1 ? "day" : "days"}`} to={workloadPath("oldest", data?.oldest_report_id)} note="Days since last dispatch" state={state} />
      <ActionCard label="Average resolution" value={data?.average_resolution_minutes} formatValue={formatElapsedMinutes} to={workloadPath("resolution")} note={`Last 30 days · ${formatOverviewNumber(data?.resolution_sample_size)} ${data?.resolution_sample_size === 1 ? "submission" : "submissions"}`} state={state} tone="duration" />
    </div>
    <div className="overview-pending-age">
      <div className="overview-pending-heading"><h3>Pending age</h3><span>Days since the latest dispatch or reassignment</span></div>
      <nav aria-label="Open assignment age ranges" className="overview-age-segments">
        {["0-3", "4-7", "8-14"].map(group => {
          const count = !state.hasResult ? state.error ? "Unavailable" : "Loading…" : formatOverviewNumber(groups[group]);
          return <Link key={group} className="overview-age-chip" to={workloadPath(`age_${group}`)} aria-label={`${group} days: ${count} open assignments`}>
            <span>{group.replace("-", "–")} days</span><strong>{count}</strong>
          </Link>;
        })}
      </nav>
      <Link className="overview-age-unavailable" to={workloadPath("age_unavailable")}>Age unavailable <strong>{!state.hasResult ? state.error ? "Unavailable" : "Loading…" : formatOverviewNumber(data?.age_unavailable)}</strong><OverviewIcon kind="arrow" /></Link>
    </div>
    {data && <details className="overview-explanation overview-quality">
      <summary>{qualityItems.length ? `Data notes · ${qualityItems.join(" · ")}` : "Data notes · nothing needs checking"}</summary>
      <p><Link to={workloadPath("deadline_missing")}>No due date: {data.missing_deadlines} open assignments</Link> · <Link to={workloadPath("age_unavailable")}>No reliable start: {data.age_unavailable}</Link> · Invalid due date: {data.invalid_deadlines} · Needs a time check: {data.ambiguous_deadlines} · Older open outside the totals: {data.older_hidden_open_reports} · In Progress outside the open count: {data.legacy_in_progress}</p>
      <p>Completed reports with no received time: {data.missing_submission_received}. Durations not used in the average: {data.resolution_excluded}.</p>
    </details>}
    {data && <details className="overview-explanation overview-methodology"><summary>How these numbers are calculated</summary>
      <p>{updatedAt ?? "Update time unavailable"}. The average covers the last 30 days{period ? ` (${period})` : ""} and uses {formatOverviewNumber(data.resolution_sample_size)} completed {data.resolution_sample_size === 1 ? "report" : "reports"}. Waiting time counts whole days from the latest dispatch or reassignment, not from completion. Due dates use Philippine local time; older records may not show their original timezone.</p>
    </details>}
  </details>;
}

function BarangayPrioritiesWidget({ opsRankings, state }) {
  // Preserve municipal WLC ranks; only display eligible new field destinations.
  const top5 = opsRankings.filter(b => b && hasDispatchableWlcTargets(b)).slice(0, 5);
  return (
    <section className="overview-surface overview-priorities" aria-labelledby="overview-priorities-title" aria-busy={state.loading}>
      <div className="overview-section-heading">
        <h2 id="overview-priorities-title">Where to inspect next</h2>
      </div>
      <p className="overview-section-sub">Barangays with the highest priority for new inspections.</p>
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
              <Link className="overview-priority" to={`/analytics?tab=prescriptive&barangay_id=${encodeURIComponent(b.barangayID)}`} title="View Prescriptive Analytics">
                <span className="overview-priority-rank" aria-label={`Rank ${formatOverviewNumber(b.rank)}`}>{formatOverviewNumber(b.rank)}</span>
                <span className="overview-priority-main">
                  <span className="overview-priority-name">{shortBarangay(b.barangayName) || "Unknown barangay"}</span>
                  <span className="overview-priority-meta">Priority score <strong>{formatOverviewNumber(b.ops_score)}</strong>/100 · {formatOverviewNumber(b.dispatchable_count ?? ((b.red_count || 0) + (b.yellow_count || 0)))} available for inspection</span>
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
      <Link className="overview-section-link" to="/analytics?tab=prescriptive">Explore inspection priorities <OverviewIcon kind="arrow" /></Link>
    </section>
  );
}

// ── Mini Map Widget ───────────────────────────────────────────────────────────
function MiniMapWidget({ flags, state, isDark, onOpenMap, isLoaded, loadError }) {
  const [mapInstance, setMapInstance] = useState(null);
  const [showApproximateLocations, setShowApproximateLocations] = useState(false);
  const mapRef = useRef(null);
  const markerRefs = useRef([]);

  const buildMarkerEl = useCallback((color, approximate = false) => {
    if (approximate) {
      return createApproximateMarkerContent(26, 34, false, false, color);
    }
    const el = document.createElement("div");
    el.style.cssText = `width:22px;height:22px;cursor:pointer;filter:drop-shadow(0 2px 3px rgba(0,0,0,0.3))`;
    el.innerHTML = `<svg viewBox="0 0 24 32" width="22" height="22" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 9 12 20 12 20s12-11 12-20C24 5.37 18.63 0 12 0z" fill="${color}"/>
      <circle cx="12" cy="12" r="5" fill="white" opacity="0.9"/>
    </svg>`;
    return el;
  }, []);
  const approximateFlags = useMemo(
    () => createCentroidPreviewFlags(
      flags,
      getApproximateBarangayDisplayPoint,
    ),
    [flags],
  );
  const exactFlags = useMemo(
    () => flags.filter(hasMapCoordinates).slice(0, 100),
    [flags],
  );
  const displayedFlags = useMemo(
    () => showApproximateLocations
      ? [...exactFlags, ...approximateFlags.slice(0, 100)]
      : exactFlags,
    [approximateFlags, exactFlags, showApproximateLocations],
  );
  const noExactLocationCount = flags.filter((flag) => !hasMapCoordinates(flag)).length;
  const nonGreenPreviewCount = exactFlags.filter(
    (flag) => parseColor(flag) !== "Green",
  ).length;
  const unassignedCount = flags.filter((flag) => {
    if (hasMapCoordinates(flag)) return false;
    const id = Number(flag.barangayID);
    return !Number.isInteger(id) || id <= 0;
  }).length;

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

    displayedFlags.forEach(f => {
        const fc = getFlagColor(parseColor(f));
        const position = f.isCentroidPreview
          ? f.mapPreviewPosition
          : { lat: Number(f.latitude), lng: Number(f.longitude) };
        if (!position || !Number.isFinite(position.lat) || !Number.isFinite(position.lng)) return;
        let marker = null;

        if (canUseAdvanced) {
          try {
            marker = new window.google.maps.marker.AdvancedMarkerElement({
              position,
              map: activeMap,
              content: buildMarkerEl(fc.marker, f.isCentroidPreview),
              title: f.isCentroidPreview
                ? APPROXIMATE_LOCATION_LABEL
                : f.detectedName || f.name || "Business location",
            });
          } catch {
            marker = null;
          }
        }

        if (!marker) {
          marker = new window.google.maps.Marker({
            position,
            map: activeMap,
            title: f.isCentroidPreview
              ? APPROXIMATE_LOCATION_LABEL
              : f.detectedName || f.name || "Business location",
            icon: f.isCentroidPreview
              ? createApproximateMarkerIcon(window.google.maps, 1, fc.marker)
              : {
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
  }, [buildMarkerEl, displayedFlags, isLoaded, mapInstance]);

  return (
    <section className="overview-surface overview-map" aria-labelledby="overview-map-title" aria-busy={state.loading || (!isLoaded && !loadError)}>
      <div className="overview-section-heading">
        <h2 id="overview-map-title">Explore the map</h2>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "flex-end", gap: 8 }}>
          {approximateFlags.length > 0 && (
            <button
              type="button"
              className="overview-approximate-toggle"
              aria-pressed={showApproximateLocations}
              onClick={() => setShowApproximateLocations((visible) => !visible)}
            >
              {showApproximateLocations ? "Hide" : "Show"} approximate locations ({approximateFlags.length})
            </button>
          )}
          <button className="overview-inline-action" type="button" onClick={onOpenMap}>
            Open full map ↗
          </button>
        </div>
      </div>
      <RequestFeedback state={state} label="map records" />
      <p className="overview-section-sub">See where business records are located around Mataasnakahoy.</p>
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
            center={DEFAULT_MAP_CENTER}
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
            {formatOverviewNumber(nonGreenPreviewCount)} flagged locations shown
          </div>
        )}
      </div>

      <details className="overview-explanation overview-map-notes">
        <summary>About the locations shown</summary>
        <p>Up to 100 exact locations are shown. Approximate previews are optional and do not affect counts.
          {state.hasResult && ` ${formatOverviewNumber(noExactLocationCount)} businesses have no exact location yet.`}
          {unassignedCount > 0 && ` ${formatOverviewNumber(unassignedCount)} have no stored barangay ID and are not placed.`}
          {" "}Open the full map to explore more.</p>
      </details>

      {/* Mini legend */}
      <details className="overview-explanation overview-map-key">
        <summary>What the map colors mean</summary>
        <ul className="overview-map-legend" aria-label="Flag legend">
          {Object.entries(FLAG_COLORS).map(([color, meta]) => (
            <li key={color}>
              <span style={{ background: meta.marker }} aria-hidden="true" />
              {meta.label}
            </li>
          ))}
        </ul>
      </details>
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
      <p className="overview-section-sub">{state.hasResult
        ? outstanding.length === 0 ? "Stay on top of inspection due dates." : `${formatOverviewNumber(outstanding.length)} outstanding ${outstanding.length === 1 ? "deadline" : "deadlines"} in the loaded records.`
        : "See when open assignments are due."}</p>
      <RequestFeedback state={state} label="assignment deadlines" />
      <div className="overview-deadline-content">
      <details className="overview-calendar-details">
        <summary>Browse deadlines by date</summary>
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
              onClick={() => taskCount ? navigate(`/inspections?view=deadline_day&deadlineDate=${dateQuery(new Date(currentDate.getFullYear(), currentDate.getMonth(), day))}`) : setSelectedDay(day === selectedDay ? null : day)}
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
      <p className="overview-scope-note">Based on up to 1,000 loaded inspection records.</p>
      </details>
      <div className="calendar-widget-tasks">
        <div className="calendar-widget-tasks-header">
          <h3 id="overview-selected-deadlines" aria-live="polite">
            {selectedDate ? `Deadlines · ${selectedDate.toLocaleDateString("en-PH", { month: "short", day: "numeric" })}` : "Next deadlines"}
          </h3>
          {selectedDate && (
            <button className="overview-inline-action" type="button" onClick={() => setSelectedDay(null)}>Clear date</button>
          )}
        </div>
        <div className="calendar-widget-task-list" aria-labelledby="overview-selected-deadlines">
          {state.hasResult && displayedTasks.length === 0 ? (
            selectedDate ? <p className="overview-empty">No outstanding deadlines for this date in the loaded records.</p> : (
              <div className="overview-deadline-empty" role="status">
                <span className="overview-deadline-empty-icon" aria-hidden="true">✓</span>
                <strong>All caught up</strong>
                <p>No assignment deadlines to review right now.</p>
              </div>
            )
          ) : displayedTasks.map(task => {
            const isOverdue = new Date(task.deadline) < new Date();
            return (
              <button
                type="button"
                key={task.reportID}
                className={`calendar-widget-task${isOverdue ? " is-overdue" : ""}`}
                 onClick={() => navigate(`/inspections?view=open&reportID=${task.reportID}`)}
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
      </div>
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
  const [workload, setWorkload, hasWorkload] = useSessionDataset("home", "workload", null);
  const [registryCount, setRegistryCount, hasRegistryCount] = useSessionDataset("home", "registry-count", null);
  const [detectionCount, setDetectionCount, hasDetectionCount] = useSessionDataset("home", "detection-count", null);
  const [manualCount, setManualCount, hasManualCount] = useSessionDataset("home", "manual-count", null);
  const [unclassifiedCount, setUnclassifiedCount, hasUnclassifiedCount] = useSessionDataset("home", "unclassified-count", null);
  const [isInspectorModalOpen, setIsInspectorModalOpen] = useState(false);
  const [auxiliaryStates, setAuxiliaryStates] = useState(() => Object.fromEntries(
    Object.entries({ flags: hasFlags, inspections: hasInspections, inspectors: hasInspectors,
      workload: hasWorkload, registry: hasRegistryCount, detection: hasDetectionCount,
      manual: hasManualCount, unclassified: hasUnclassifiedCount })
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

  const fetchDashboardData = useCallback(async () => {
    if (!token) return;
    // Manual refresh, polling and focus share active work rather than restarting it.
    if (dashboardRequestRef.current) return dashboardRequestRef.current.promise;
    const controller = new AbortController();
    dashboardRequestRef.current = controller;
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
      load("workload", signal => getInspectionWorkloadRequest({ summary: 1, signal }, token), result => result?.as_of ? [result] : null, result => setWorkload(result[0])),
      load("registry", signal => getRegistryRequest({ limit: 1, signal }, token), result => Number.isFinite(result?.total) ? [result] : null, result => setRegistryCount(result[0])),
      ...[["detection", setDetectionCount], ["manual", setManualCount], ["unclassified", setUnclassifiedCount]]
        .map(([origin, commit]) => load(origin, signal => getFlagsRequest({ origin, registryLink: "unlinked", limit: 1, signal }, token),
          result => Number.isFinite(result?.total) ? [result] : null, result => commit(result[0]))),
    ]).then(results => results.every(Boolean)).finally(() => {
      if (dashboardRequestRef.current === controller) {
        dashboardRequestRef.current = null;
      }
    });
    return controller.promise;
  }, [token, setAllFlags, setInspections, setInspectors, setWorkload, setRegistryCount, setDetectionCount, setManualCount, setUnclassifiedCount]);
  useAppDataRefresh("home", () => refreshResults([
    refreshAnalytics(), fetchDashboardData(),
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
        </p>
      )}
      {/* Overview sections follow reading order; only the map and priorities share a row. */}
      <div className="overview-dashboard-layout">
        <HeroBanner user={user} />
        <NeedsAttention data={workload} state={requestStates.workload} />

        <div className="overview-feature-grid">
          <MiniMapWidget
            flags={allFlags}
            state={requestStates.flags}
            isDark={isDark}
            onOpenMap={() => navigate("/map")}
            isLoaded={isLoaded}
            loadError={loadError}
          />
          <BarangayPrioritiesWidget
            opsRankings={opsRankings}
            state={requestStates.ops}
          />
        </div>
        <SourceCards sources={{ registry: registryCount, detection: detectionCount, manual: manualCount, unclassified: unclassifiedCount }} states={requestStates} />
        <VisualCalendarWidget inspections={inspections} state={requestStates.inspections} navigate={navigate} />
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
