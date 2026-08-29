/**
 * HomePage.jsx — Overview Dashboard
 * Live KPIs from /api/analytics/all
 * Recent Detections from /api/flags (newest activity, all colors)
 * Mini Google Map preview with real flag markers
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useLoadScript, GoogleMap } from "@react-google-maps/api";
import DashboardLayout from "../components/DashboardLayout";
import KpiCard from "../components/KpiCard";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { getAnalyticsOverviewRequest, getFlagsRequest, getInspectionsRequest, getInspectorsRequest, getOpsRankingsRequest, markNotificationsReadRequest } from "../services/api";
import Swal from "sweetalert2";
import "../styles/HomePage.css";

const MAP_LIBRARIES = ["places", "marker"];
const DEFAULT_CENTER = { lat: 13.9667, lng: 121.1167 };

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

const shortBarangay = (name = "") => name.replace("Barangay ", "Brgy.");

// ── Hero Banner ───────────────────────────────────────────────────────────────
const HERO_STEPS = [
  { num: 1, label: "Upload Registry CSV", to: "/registry" },
  { num: 2, label: "Review Geospatial Flags", to: "/map" },
  { num: 3, label: "Priority Dispatch", to: "/inspections" },
];

// WMO weather interpretation codes (Open-Meteo)
const WEATHER_CODES = {
  0: "Clear Sky", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
  45: "Foggy", 48: "Rime Fog",
  51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
  61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
  71: "Light Snow", 73: "Snow", 75: "Heavy Snow",
  80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
  95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
};

function HeroBanner({ user, kpis, mapsReady, navigate, onRefresh, isRefreshing }) {
  // Live clock — ticks every second
  const [now, setNow] = useState(() => new Date());
  // Live weather for Mataasnakahoy (Open-Meteo, keyless)
  const [weather, setWeather] = useState(null);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("https://api.open-meteo.com/v1/forecast?latitude=13.9667&longitude=121.1167&current=temperature_2m,weather_code")
      .then(res => res.json())
      .then(data => {
        if (cancelled || !data?.current) return;
        setWeather({
          temp: Math.round(data.current.temperature_2m ?? 28),
          label: WEATHER_CODES[data.current.weather_code] ?? "Fair",
        });
      })
      .catch(() => { }); // fall back to the default readout on failure
    return () => { cancelled = true; };
  }, []);

  // All times are locked to Philippine Standard Time (UTC+8)
  const timeFmt = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Manila", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true });
  const dateFmt = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Manila", weekday: "long", month: "long", day: "numeric", year: "numeric" });
  const hourFmt = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Manila", hour: "numeric", hour12: false });

  const manilaHour = Number(hourFmt.format(now)) % 24;
  const greeting = manilaHour < 12 ? "Good morning" : manilaHour < 18 ? "Good afternoon" : "Good evening";
  const firstName = user?.fullName ? user.fullName.trim().split(/\s+/)[0] : "Admin";

  const [timeStr, amPm] = timeFmt.format(now).split(" ");
  const flaggedCount = kpis ? kpis.total_flagged.toLocaleString() : "—";

  return (
    <section className="hero-banner">
      <div className="hero-glow" aria-hidden="true" />

      {/* ── Left: greeting + steps ── */}
      <div className="hero-left">
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div className="hero-status-pill">
            <span className="hero-status-item">
              <span className="hero-status-dot" />
              BPLO Geospatial Engine Active
            </span>
            <span className="hero-status-divider" aria-hidden="true" />
            <span className="hero-status-item">Mataasnakahoy Compliance Portal</span>
          </div>

          {onRefresh && (
            <button
              className="quick-refresh-btn"
              type="button"
              onClick={onRefresh}
              disabled={isRefreshing}
              style={{ padding: "4px 10px", fontSize: 11.5, height: 28 }}
              title="Refresh overview metrics"
            >
              <svg className={isRefreshing ? "spin-icon" : ""} viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19" /></svg>
              <span>{isRefreshing ? "Syncing…" : "Sync Live"}</span>
            </button>
          )}
        </div>

        <h1 className="hero-greeting">
          {greeting},<br />
          <span className="hero-greeting-name">{firstName} 👋</span>
        </h1>

        <p className="hero-sub">
          Welcome back! You have{" "}
          <strong className="hero-sub-highlight">{flaggedCount} commercial flags</strong>{" "}
          pending geospatial audit. System dispatch priority model is active.
        </p>

        <div className="hero-steps">
          {HERO_STEPS.map(({ num, label, to }) => (
            <button key={num} className="hero-step" onClick={() => navigate(to)}>
              <span className="hero-step-num">{num}</span>
              <span>{label}</span>
              <svg className="hero-step-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                <path d="M5 12h14" /><path d="M13 6l6 6-6 6" />
              </svg>
            </button>
          ))}
        </div>
      </div>

      {/* ── Right: stat cards + quick actions ── */}
      <div className="hero-right">
        <div className="hero-cards">
          {/* Municipal Time */}
          <div className="hero-card">
            <div className="hero-card-head">
              <span className="hero-card-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15">
                  <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
                </svg>
                <span>Municipal<br />Time</span>
              </span>
              <span className="hero-card-badge">PST<br />(UTC+8)</span>
            </div>
            <div className="hero-clock">
              {timeStr} <span className="hero-clock-ampm">{amPm}</span>
            </div>
            <p className="hero-card-date">{dateFmt.format(now)}</p>
            <div className="hero-card-foot">
              <span>Status: {mapsReady ? "Syncing Google Maps" : "Loading Google Maps"}</span>
              <span className={mapsReady ? "hero-foot-value" : "hero-foot-value--loading"}>
                {mapsReady ? "100%" : "…"}
              </span>
            </div>
          </div>

          {/* Field Weather */}
          <div className="hero-card">
            <div className="hero-card-head">
              <span className="hero-card-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="15" height="15">
                  <path d="M17.5 19a4.5 4.5 0 1 0-1.13-8.86A6 6 0 1 0 5 14.7" />
                </svg>
                <span>Field<br />Weather</span>
              </span>
              <span className="hero-card-loc">Mataasnakahoy</span>
            </div>
            <div className="hero-weather-row">
              <div>
                <div className="hero-temp">{weather ? `${weather.temp}°C` : "28°C"}</div>
                <p className="hero-cond">{weather ? `${weather.label} · Fair` : "Partly Cloudy · Fair"}</p>
              </div>
              <div className="hero-sun">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="22" height="22">
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
                </svg>
              </div>
            </div>
            <div className="hero-card-foot">
              <span>Inspection Readiness</span>
              <span className="hero-foot-value hero-foot-value--optimal">Optimal</span>
            </div>
          </div>
        </div>

        {/* System Status */}
        <div className="hero-status-card">
          <span className="hero-status-card-title">System Status</span>
          <div className="hero-status-row">
            <span className="hero-status-row-label">
              <span className="hero-status-dot" />
              Geospatial Engine
            </span>
            <span className="hero-status-row-value hero-status-row-value--ok">Online</span>
          </div>
          <div className="hero-status-row">
            <span className="hero-status-row-label">
              <span className={mapsReady ? "hero-status-dot" : "hero-status-dot hero-status-dot--idle"} />
              Google Maps Sync
            </span>
            <span className={mapsReady ? "hero-status-row-value hero-status-row-value--ok" : "hero-status-row-value hero-status-row-value--wait"}>
              {mapsReady ? "Ready" : "Syncing…"}
            </span>
          </div>
          <div className="hero-status-row">
            <span className="hero-status-row-label">
              <span className={weather ? "hero-status-dot" : "hero-status-dot hero-status-dot--idle"} />
              Weather Feed
            </span>
            <span className={weather ? "hero-status-row-value hero-status-row-value--ok" : "hero-status-row-value hero-status-row-value--wait"}>
              {weather ? "Live" : "Connecting…"}
            </span>
          </div>
          <div className="hero-status-row">
            <span className="hero-status-row-label">
              <span className="hero-status-dot" />
              Registry Baseline
            </span>
            <span className="hero-status-row-value">
              {kpis ? `${kpis.total_businesses.toLocaleString()} entities` : "—"}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

function HighPriorityAlertsWidget({ opsRankings, navigate, loading }) {
  const RISK_COLORS = {
    High: { bg: "rgba(239,68,68,0.12)", text: "#dc2626", border: "#fca5a5" },
    Medium: { bg: "rgba(245,158,11,0.12)", text: "#b45309", border: "#fcd34d" },
    Low: { bg: "rgba(34,197,94,0.12)", text: "#166534", border: "#86efac" },
  };

  // Top 5 barangays by OPS score (already sorted from backend)
  const top5 = (opsRankings || []).filter(b => b.flagged_count > 0).slice(0, 5);

  return (
    <div className="dashboard-widget frosted-glass saas-card">
      <div className="widget-header">
        <h3 style={{ color: "var(--color-danger)", display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          High-Priority Alerts
        </h3>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
        {loading ? (
          <div style={{ textAlign: "center", padding: "20px 0", color: "var(--color-muted)", fontSize: 13 }}>
            Loading priority queue…
          </div>
        ) : top5.length === 0 ? (
          <div style={{ textAlign: "center", padding: "20px 0", color: "var(--color-muted)", fontSize: 13 }}>
            No barangays with active flags detected.
          </div>
        ) : top5.map((b, i) => {
          const riskStyle = RISK_COLORS[b.risk_level] || RISK_COLORS.Low;
          return (
            <div
              key={b.barangayID}
              className="hover-lift"
              style={{ background: "var(--color-surface)", border: "1px solid var(--color-border-soft)", padding: "10px 12px", borderRadius: "10px", cursor: "pointer" }}
              onClick={() => navigate('/analytics')}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 3 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{
                    width: 18, height: 18, borderRadius: "50%",
                    background: "var(--color-primary)", color: "#fff",
                    fontSize: 10, fontWeight: 800,
                    display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0
                  }}>
                    {b.rank}
                  </span>
                  {shortBarangay(b.barangayName)}
                </div>
                <span style={{
                  fontSize: 10, fontWeight: 700,
                  padding: "2px 8px", borderRadius: 6,
                  background: riskStyle.bg, color: riskStyle.text,
                  border: `1px solid ${riskStyle.border}`,
                }}>
                  {b.risk_level}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "var(--color-muted)", paddingLeft: 24, display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span>OPS <b style={{ color: "var(--color-ink)" }}>{b.ops_score}</b>/100</span>
                <span>·</span>
                <span>{b.flagged_count} flag{b.flagged_count !== 1 ? "s" : ""}</span>
                {b.red_count > 0 && <span style={{ color: "#ef4444" }}>({b.red_count} Red)</span>}
                {b.black_count > 0 && <span style={{ color: "#374151" }}>({b.black_count} Black)</span>}
              </div>
            </div>
          );
        })}
        {top5.length > 0 && (
          <button className="ghost-btn" style={{ fontSize: 11, padding: "6px", color: "var(--color-danger)", borderColor: "transparent", marginTop: 4, width: "100%" }} onClick={() => navigate('/analytics')}>
            View Full Priority Queue →
          </button>
        )}
      </div>
    </div>
  );
}

// ── Mini Map Widget ───────────────────────────────────────────────────────────
function MiniMapWidget({ flags, isDark, onOpenMap, isLoaded, loadError }) {
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
  }, []);

  // Place markers once map + flags are ready
  useEffect(() => {
    if (!isLoaded || !mapRef.current || !window.google?.maps?.marker) return;

    // Clear old markers
    markerRefs.current.forEach(m => { m.map = null; });
    markerRefs.current = [];

    flags
      .filter(f => f.latitude != null && f.longitude != null)
      .slice(0, 100) // cap for performance
      .forEach(f => {
        const fc = getFlagColor(parseColor(f));
        const marker = new window.google.maps.marker.AdvancedMarkerElement({
          position: { lat: Number(f.latitude), lng: Number(f.longitude) },
          map: mapRef.current,
          content: buildMarkerEl(fc.marker),
        });
        markerRefs.current.push(marker);
      });

    return () => {
      markerRefs.current.forEach(m => { m.map = null; });
      markerRefs.current = [];
    };
  }, [isLoaded, flags]);

  return (
    <div className="dashboard-widget frosted-glass saas-card map-widget">
      <div className="widget-header">
        <h3>Live Map Preview</h3>
        <button className="ghost-btn" type="button" onClick={onOpenMap}>
          Open Full Map ↗
        </button>
      </div>

      <div style={{ borderRadius: 12, overflow: "hidden", height: 260, position: "relative" }}>
        {loadError ? (
          <div style={miniMapFallback}>
            <span>⚠ Google Maps failed to load.</span>
            <small>{googleMapsApiKey
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
              mapId: "34390388b3abb63aa84876a7",
              colorScheme: isDark ? "DARK" : "LIGHT",
            }}
            onLoad={handleMapLoad}
          />
        )}

        {/* Clickable overlay to open full map */}
        <div
          onClick={onOpenMap}
          title="Open full map"
          style={{
            position: "absolute", inset: 0, zIndex: 5, cursor: "pointer",
            background: "transparent",
          }}
        />

        {/* Flag count badge */}
        {flags.length > 0 && (
          <div style={{
            position: "absolute", top: 10, left: 10, zIndex: 10,
            background: "rgba(239,68,68,0.9)", color: "#fff",
            fontSize: 11, fontWeight: 700, padding: "4px 10px",
            borderRadius: 20, backdropFilter: "blur(4px)",
            pointerEvents: "none",
          }}>
            {flags.filter(f => parseColor(f) !== "Green").length} active flags
          </div>
        )}
      </div>

      {/* Mini legend */}
      <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap" }}>
        {Object.entries(FLAG_COLORS).map(([color, meta]) => (
          <div key={color} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--color-muted)" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: meta.marker, display: "inline-block" }} />
            {meta.label}
          </div>
        ))}
      </div>
    </div>
  );
}

const miniMapFallback = {
  width: "100%", height: "100%", display: "flex", flexDirection: "column",
  alignItems: "center", justifyContent: "center", gap: 6,
  background: "var(--color-surface)", color: "var(--color-muted)", fontSize: 13, textAlign: "center",
};

// ── Visual Calendar Widget ──────────────────────────────────────────────────
function VisualCalendarWidget({ inspections, navigate }) {
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

  // Map deadlines
  const activeTasksWithDeadline = inspections
    .filter(i => (i.verificationStatus === "Assigned" || i.verificationStatus === "Reassigned") && i.deadline);

  // statusByDate: day -> 'overdue' | 'upcoming'
  const statusByDate = {};
  const tasksByDate = {};

  activeTasksWithDeadline.forEach(t => {
    const d = new Date(t.deadline);
    if (d.getFullYear() === currentDate.getFullYear() && d.getMonth() === currentDate.getMonth()) {
      const day = d.getDate();
      if (!tasksByDate[day]) tasksByDate[day] = [];
      tasksByDate[day].push(t);

      const isOverdue = d < new Date();
      if (statusByDate[day] !== 'overdue') {
        statusByDate[day] = isOverdue ? 'overdue' : 'upcoming';
      }
    }
  });

  const displayedTasks = selectedDay && tasksByDate[selectedDay]
    ? tasksByDate[selectedDay].sort((a, b) => new Date(a.deadline) - new Date(b.deadline))
    : activeTasksWithDeadline.sort((a, b) => new Date(a.deadline) - new Date(b.deadline)).slice(0, 3);

  return (
    <div className="dashboard-widget frosted-glass saas-card" style={{ padding: "20px 0" }}>
      <div className="widget-header" style={{ padding: "0 20px", marginBottom: 16 }}>
        <h3 style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line>
          </svg>
          {monthName}
        </h3>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="ghost-btn" onClick={prevMonth} style={{ padding: "4px 8px" }}>&larr;</button>
          <button className="ghost-btn" onClick={nextMonth} style={{ padding: "4px 8px" }}>&rarr;</button>
        </div>
      </div>

      <div style={{ padding: "0 20px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", textAlign: "center", gap: 4, marginBottom: 8 }}>
          {weekDays.map(day => (
            <div key={day} style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase" }}>{day}</div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4, textAlign: "center" }}>
          {Array.from({ length: firstDay }).map((_, i) => <div key={`empty-${i}`} />)}
          {Array.from({ length: daysInMonth }).map((_, i) => {
            const day = i + 1;
            const status = statusByDate[day];
            const isToday = new Date().getDate() === day && new Date().getMonth() === currentDate.getMonth() && new Date().getFullYear() === currentDate.getFullYear();
            const isSelected = selectedDay === day;

            let color = isToday ? "var(--color-primary)" : "var(--color-ink)";
            let dotColor = null;
            if (status === 'overdue') {
              dotColor = "var(--color-danger)";
            } else if (status === 'upcoming') {
              dotColor = "var(--color-primary)";
            }

            let bg = isSelected ? "var(--color-border-soft)" : "transparent";

            return (
              <div key={day} style={{
                padding: "4px 0",
                fontSize: 13,
                fontWeight: isToday || isSelected ? 700 : 500,
                color: color,
                background: bg,
                borderRadius: "8px",
                cursor: "pointer",
                width: 28,
                height: 32,
                margin: "0 auto",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: isSelected ? "0 0 0 1px var(--color-border-soft)" : "none",
                transform: isSelected ? "scale(1.1)" : "scale(1)",
                transition: "all 0.15s"
              }}
                onClick={() => setSelectedDay(day === selectedDay ? null : day)}
              >
                <span style={{ lineHeight: 1 }}>{day}</span>
                <span style={{ width: 4, height: 4, borderRadius: "50%", background: dotColor || "transparent", marginTop: 2 }} />
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ padding: "20px 20px 0", marginTop: 16, borderTop: "1px solid var(--color-border-soft)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h4 style={{ fontSize: 13, fontWeight: 700, color: "var(--color-ink)", margin: 0 }}>
            {selectedDay ? `Tasks for ${monthName.split(' ')[0]} ${selectedDay}` : "Upcoming Tasks"}
          </h4>
          {selectedDay && <button className="ghost-btn" style={{ padding: "2px 6px", fontSize: 10 }} onClick={() => setSelectedDay(null)}>Clear</button>}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {displayedTasks.length === 0 ? (
            <div style={{ textAlign: "center", padding: "10px 0", color: "var(--color-muted)", fontSize: 13 }}>No tasks for this date.</div>
          ) : displayedTasks.map(task => {
            const isOverdue = new Date(task.deadline) < new Date();
            return (
              <div
                key={task.reportID}
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "var(--color-hover)", border: "1px solid var(--color-border-soft)", borderLeft: isOverdue ? "4px solid var(--color-danger)" : "4px solid var(--color-primary)", padding: "10px 12px", borderRadius: 10, cursor: "pointer" }}
                onClick={() => navigate('/inspections')}
              >
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-ink)" }}>{task.detectedName}</div>
                  <div style={{ fontSize: 11, color: "var(--color-muted)", marginTop: 2 }}>Inspector: {task.inspectorName || "Unknown"}</div>
                </div>
                <div style={{ fontSize: 11, fontWeight: 700, color: isOverdue ? "var(--color-danger)" : "var(--color-primary)" }}>
                  {isOverdue ? "⚠ Overdue" : new Date(task.deadline).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
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
    if (searchTerm && !f.detectedName?.toLowerCase().includes(searchTerm.toLowerCase())) return false;
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
              <svg style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--color-muted)" }} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
              <input
                type="text"
                placeholder="Search..."
                className="saas-input"
                style={{ padding: "8px 14px 8px 36px", width: 220, borderRadius: 8, background: "transparent" }}
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
              />
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

  const isDark = resolvedTheme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);

  const googleMapsApiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";
  const { isLoaded, loadError } = useLoadScript({
    googleMapsApiKey,
    libraries: MAP_LIBRARIES,
    version: "beta",
  });


  // KPIs
  const [kpis, setKpis] = useState(null);
  const [kpiError, setKpiError] = useState(false);

  // Flags
  const [allFlags, setAllFlags] = useState([]);
  const [flagsLoading, setFlagsLoading] = useState(true);

  const [inspections, setInspections] = useState([]);
  const [inspectors, setInspectors] = useState([]);
  const [isInspectorModalOpen, setIsInspectorModalOpen] = useState(false);
  const [opsRankings, setOpsRankings] = useState([]);
  const [opsLoading, setOpsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchDashboardData = useCallback(async (isSilent = false) => {
    if (!token) return;
    if (!isSilent) {
      setIsRefreshing(true);
    }

    try {
      const [analyticsRes, flagsRes, inspRes, inspectorsRes, opsRes] = await Promise.allSettled([
        getAnalyticsOverviewRequest(token),
        getFlagsRequest({ limit: 200 }, token),
        getInspectionsRequest({ limit: 1000 }, token),
        getInspectorsRequest(token),
        getOpsRankingsRequest(token),
      ]);

      // KPIs & Rollover
      if (analyticsRes.status === "fulfilled" && analyticsRes.value) {
        const data = analyticsRes.value;
        setKpis(data?.descriptive?.kpis ?? null);
        setKpiError(false);

        if (data?.new_year_rollover?.detected) {
          Swal.fire({
            title: "Happy New Year!",
            html: `<div style="text-align: left; font-size: 13.5px; line-height: 1.6; color: var(--color-ink);">` +
              `Welcome to <b>${data.new_year_rollover.year}</b>!<br/><br/>` +
              `The system has automatically marked <b>${data.new_year_rollover.count}</b> active business permits from previous years as <span style="color: var(--color-danger); font-weight: 700;">Expired</span> and their map flags as <span style="color: var(--color-danger); font-weight: 700;">Red</span>.<br/><br/>` +
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
            if (data.new_year_rollover.notification_id) {
              markNotificationsReadRequest(token, [data.new_year_rollover.notification_id]).catch(() => {});
            }
            if (result.isConfirmed) {
              navigate("/registry");
            }
          });
        }
      } else if (analyticsRes.status === "rejected") {
        setKpiError(true);
      }

      // Flags
      if (flagsRes.status === "fulfilled" && flagsRes.value) {
        setAllFlags(flagsRes.value?.data ?? []);
      }

      // Inspections
      if (inspRes.status === "fulfilled" && inspRes.value) {
        setInspections(inspRes.value?.data ?? []);
      }

      // Inspectors
      if (inspectorsRes.status === "fulfilled" && inspectorsRes.value) {
        setInspectors(inspectorsRes.value || []);
      }

      // OPS Rankings
      if (opsRes.status === "fulfilled" && opsRes.value) {
        setOpsRankings(opsRes.value?.data || []);
      }
    } catch {
      /* ignore */
    } finally {
      setFlagsLoading(false);
      setOpsLoading(false);
      setIsRefreshing(false);
    }
  }, [token, navigate]);

  useEffect(() => {
    fetchDashboardData(false);

    const handleEventUpdate = () => {
      fetchDashboardData(true);
    };

    window.addEventListener("revela:inspection-update", handleEventUpdate);
    window.addEventListener("revela:yellow-flag", handleEventUpdate);
    window.addEventListener("revela:flag-update", handleEventUpdate);
    window.addEventListener("revela:registry-update", handleEventUpdate);
    window.addEventListener("revela:global-refresh", handleEventUpdate);

    // Silent background auto-polling every 20s
    const pollInterval = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchDashboardData(true);
      }
    }, 20000);

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        fetchDashboardData(true);
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", handleVisibilityChange);

    return () => {
      window.removeEventListener("revela:inspection-update", handleEventUpdate);
      window.removeEventListener("revela:yellow-flag", handleEventUpdate);
      window.removeEventListener("revela:flag-update", handleEventUpdate);
      window.removeEventListener("revela:registry-update", handleEventUpdate);
      window.removeEventListener("revela:global-refresh", handleEventUpdate);
      window.clearInterval(pollInterval);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", handleVisibilityChange);
    };
  }, [fetchDashboardData]);

  const kpiCards = [
    {
      value: kpis ? kpis.total_businesses.toLocaleString() : "—",
      label: "Total Registered Entities",
      delta: kpis?.total_businesses_delta ? `${kpis.total_businesses_delta > 0 ? '+' : ''}${kpis.total_businesses_delta} vs last month` : undefined,
      trend: kpis?.total_businesses_delta >= 0 ? "up" : "down",
      iconVariant: "gold",
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 3v18h18" /><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3" />
        </svg>
      ),
    },
    {
      value: kpis ? kpis.total_flagged : "—",
      label: "Unregistered Flags Detected",
      delta: kpis?.total_flagged_delta ? `${kpis.total_flagged_delta > 0 ? '+' : ''}${kpis.total_flagged_delta} vs last month` : undefined,
      trend: kpis?.total_flagged_delta > 0 ? "down" : "up", // Red flag: more is bad
      iconVariant: "red",
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
          <line x1="4" y1="22" x2="4" y2="15" />
        </svg>
      ),
    },
    {
      value: kpis ? `${kpis.compliance_rate}%` : "—",
      label: "Overall Compliance Rate",
      delta: kpis?.compliance_rate_delta ? `${kpis.compliance_rate_delta > 0 ? '+' : ''}${kpis.compliance_rate_delta}% vs last month` : undefined,
      trend: kpis?.compliance_rate_delta >= 0 ? "up" : "down",
      iconVariant: "green",
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      ),
    },
  ];

  return (
    <DashboardLayout>
      {/* Main Layout: 2 Columns */}
      <div style={{ display: "grid", gridTemplateColumns: "3fr 1fr", gap: 24, alignItems: "start" }}>

        {/* Left Column (Main Content) */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <HeroBanner
            user={user}
            kpis={kpis}
            mapsReady={isLoaded}
            navigate={navigate}
            onRefresh={() => fetchDashboardData(false)}
            isRefreshing={isRefreshing}
          />

          {kpiError && (
            <div style={{
              background: "var(--color-danger-light)", border: "1px solid var(--color-danger)",
              borderRadius: 8, padding: "10px 16px",
              color: "var(--color-danger)", fontSize: 13, fontWeight: 600,
            }}>
              ⚠ Could not load live metrics — check that the backend is running.
            </div>
          )}

          {/* KPI row */}
          <div className="kpi-grid">
            {kpiCards.map(kpi => <KpiCard key={kpi.label} {...kpi} />)}
          </div>

          {/* Map */}
          <div style={{ height: "400px" }}>
            <MiniMapWidget
              flags={allFlags}
              isDark={isDark}
              onOpenMap={() => navigate("/map")}
              isLoaded={isLoaded}
              loadError={loadError}
            />
          </div>
        </div>

        {/* Right Column (Sidebar) */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <VisualCalendarWidget inspections={inspections} navigate={navigate} />

          <HighPriorityAlertsWidget
            opsRankings={opsRankings}
            navigate={navigate}
            loading={opsLoading}
          />
        </div>
      </div>

      {/* Footer */}
      <footer className="saas-footer frosted-glass">
        <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
        <p className="footer-links">
          <span>BPLO Portal</span> &bull; <span>System Settings</span>
        </p>
      </footer>

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
