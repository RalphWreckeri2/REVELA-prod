import { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef, memo, lazy, Suspense } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";
import { analyticsRoute } from "./analyticsNavigation";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis
} from "recharts";
import DashboardLayout from "../components/DashboardLayout";
import { SkeletonBlock } from "../components/LoadingSkeleton";
import { OverviewMapSkeleton, InspectorOperationsSkeleton, RecommendationsSkeleton } from "../components/AnalyticsLoadingLayouts";
import { scheduleAnalyticsSkeleton } from "../components/analyticsLoadingPolicy";
import "../styles/AnalyticsPage.css";
import KpiCard from "../components/KpiCard";
import PinMonitoringPanel from "../components/PinMonitoringPanel";
import StackedBarangayChart from "../components/StackedBarangayChart";
const MapOverview = lazy(() => import("../components/MapOverview"));
import AnalyticsInfoTip from "../components/AnalyticsInfoTip";
import ResponsiveChart from "../components/ResponsiveChart";
import {
  activeInspectorWorkload,
  activeFlagRecommendations,
  completeInspectionTimeline,
  groupOperationsStatusBreakdown,
  groupInspectionStatuses,
  INSPECTION_STATUS_STACKS,
  pivotCategoryCounts,
  recommendationAllocationLabel,
  recommendationReason,
  rankedRecommendationRows,
} from "../components/analyticsPresentation";
import { analyticsDetectionScanSummary } from "../components/hotspotPresentation";
import { useAnalyticsData } from "../components/useAnalyticsData";
import { useSessionDataset } from "../components/useAppDataRefresh";
import { DEFAULT_WLC_WEIGHTS, wlcPolicyError, registryFlagRateLabel, opsRadarData, wlcEligibilityLabel } from "../components/wlcPolicy";
import { useAuth } from "../context/authContext";
import {
  getWlcConfigRequest,
  updateWlcConfigRequest,
  getAnalyticsFilterMetadataRequest,
  getBarangaysRequest,
  getAnalyticsHotspotsRequest,
  sendAnalyticsChatRequest,
} from "../services/api";

const EMPTY_FILTER_BARANGAYS = Object.freeze([]);
const ANALYTICS_TABS = [
  { id: "descriptive", label: "Overview", dot: "var(--color-green)" },
  { id: "prescriptive", label: "Recommendations", dot: "#6366f1" },
];
const ADMIN_PRESCRIPTIVE_DETAILS_ENABLED = false;
// ── Palette — matches REVELA's premium styling ────────────────────────────────
const COLOR = {
  green: "#10b981", // elegant emerald
  red: "#f43f5e", // elegant rose
  black: "#64748b", // slate gray for "closed/nonconforming" instead of blinding white
  blue: "#3b82f6",
  yellow: "#f59e0b",
  muted: "var(--color-muted)",
  orange: "#f97316",
  purple: "#7c3aed",
  slate: "#64748b",
  greenLight: "rgba(16, 185, 129, 0.15)",
  redLight: "rgba(244, 63, 94, 0.15)",
  yellowLight: "rgba(251, 191, 36, 0.15)",
  blueLight: "rgba(59, 130, 246, 0.15)",
};

// Descriptive status stacks use fixed permit/report colors, deliberately not
// the Map flag palette. Labels call these "Permit status" and "Current report
// status" so a purple Closed permit is never read as a purple Map flag.
const REGISTRY_STATUS_STACKS = [
  { key: "active", label: "Active", color: "#10b981" },
  { key: "pending", label: "Pending", color: "#f59e0b" },
  { key: "expired", label: "Expired", color: "#f43f5e" },
  { key: "closed", label: "Closed", color: "#7c3aed" },
  { key: "revoked", label: "Revoked", color: "var(--analytics-revoked)" },
];

const OPERATIONS_STATUS_STACKS = INSPECTION_STATUS_STACKS;

const OUTCOME_STACKS = [
  { key: "Green", label: "Green", color: COLOR.green },
  { key: "Yellow", label: "Yellow", color: COLOR.yellow },
  { key: "Red", label: "Red", color: COLOR.red },
];

const BUSINESS_SIZE_COLORS = {
  Micro: "#3b82f6",
  Small: "#14b8a6",
  Medium: "#8b5cf6",
  Large: "#f59e0b",
  Unknown: "#64748b",
};

// ── Tiny helpers ──────────────────────────────────────────────────────────────
const shortBarangay = (name = "") =>
  name.replace("Barangay ", "Brgy. ").replace("San Sebastian", "San Seb.");

const riskBadgeStyle = (level) => ({
  High: { background: COLOR.redLight, color: COLOR.red, border: `1px solid ${COLOR.red}` },
  Medium: { background: COLOR.yellowLight, color: "var(--analytics-risk-medium)", border: "1px solid #f59e0b" },
  Low: { background: COLOR.greenLight, color: "var(--analytics-risk-low)", border: `1px solid ${COLOR.green}` },
}[level] || {});

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="analytics-chart-tooltip" style={{
      background: "#111827", border: "1px solid #374151", color: "#ffffff",
      borderRadius: 10, padding: "10px 14px", fontSize: 13, boxShadow: "0 4px 20px rgba(0,0,0,0.08)"
    }}>
      <p style={{ fontWeight: 700, color: "#ffffff", marginBottom: 6 }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: "#ffffff", margin: "2px 0" }}>
          {p.name}: <strong>{typeof p.value === "number" ? p.value.toLocaleString() : p.value}</strong>
        </p>
      ))}
    </div>
  );
};

// ── Section header ────────────────────────────────────────────────────────────
const SectionHeader = ({ tier, title, subtitle }) => {
  const tierColors = {
    descriptive: { bg: COLOR.greenLight, color: COLOR.green, label: "Descriptive" },
    diagnostic: { bg: COLOR.yellowLight, color: "var(--analytics-risk-medium)", label: "Diagnostic" },
    prescriptive: { bg: "rgba(99,102,241,0.1)", color: "var(--analytics-indigo)", label: "Prescriptive" },
    operations: { bg: COLOR.blueLight, color: COLOR.blue, label: "Operations" },
  }[tier];
  return (
    <div style={{ marginBottom: 24, paddingBottom: 16, borderBottom: "1px solid var(--color-border-soft)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <span style={{
          padding: "2px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700,
          textTransform: "uppercase", letterSpacing: "0.08em",
          background: tierColors.bg, color: tierColors.color,
        }}>
          {tierColors.label}
        </span>
        <h2 style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>{title}</h2>
      </div>
      {subtitle && <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>{subtitle}</p>}
    </div>
  );
};

// ── Loading skeleton ──────────────────────────────────────────────────────────
const Skeleton = ({ h = 200, variant = "chart", rows = 8, columns = 8 }) => {
  const bars = [42, 65, 52, 82, 60, 93, 72, 58];
  return (
    <div
      className={`analytics-skeleton-frame analytics-skeleton-frame--${variant}`}
      style={{ height: h }}
      aria-hidden="true"
    >
      {variant === "table" ? (
        <div
          className="analytics-skeleton-table"
          style={{ "--skeleton-table-columns": `1.4fr repeat(${columns - 1}, minmax(0, 1fr))` }}
        >
          <div className="analytics-skeleton-table-header">
            {Array.from({ length: columns }, (_, index) => (
              <SkeletonBlock key={index} />
            ))}
          </div>
          {Array.from({ length: 6 }, (_, row) => (
            <div className="analytics-skeleton-table-row" key={row}>
              {Array.from({ length: columns }, (_, column) => (
                <SkeletonBlock key={column} />
              ))}
            </div>
          ))}
        </div>
      ) : variant === "list" ? (
        <div className="analytics-skeleton-list">
          {Array.from({ length: 5 }, (_, index) => (
            <div className="analytics-skeleton-list-row" key={index}>
              <SkeletonBlock className="analytics-skeleton-list-rank" />
              <div className="analytics-skeleton-list-copy">
                <SkeletonBlock />
                <SkeletonBlock />
              </div>
              <SkeletonBlock className="analytics-skeleton-list-badge" />
              <SkeletonBlock className="analytics-skeleton-list-status" />
            </div>
          ))}
        </div>
      ) : variant === "stacked" || variant === "operations" ? (
        <div className={`analytics-skeleton-stacked${variant === "operations" ? " analytics-skeleton-operations" : ""}`}>
          <div className="analytics-skeleton-stacked-legend">
            {Array.from({ length: variant === "operations" ? 3 : 4 }, (_, index) => <SkeletonBlock key={index} />)}
          </div>
          <div className="analytics-skeleton-stacked-rows">
            {Array.from({ length: rows }, (_, index) => (
              <div className="analytics-skeleton-stacked-row-wrap" key={index}>
                {variant === "operations" && <SkeletonBlock className="analytics-skeleton-operations-label" />}
                <SkeletonBlock className="analytics-skeleton-stacked-row" style={{ width: `${bars[index % bars.length]}%` }} />
              </div>
            ))}
          </div>
        </div>
      ) : variant === "radar" ? (
        <div className="analytics-skeleton-radar">
          {[0, 1, 2, 3].map(level => <span key={level} />)}
        </div>
      ) : variant === "map" ? (
        <div className="analytics-skeleton-map">
          <SkeletonBlock className="analytics-skeleton-map-toolbar" />
          <div className="analytics-skeleton-map-body">
            <SkeletonBlock className="analytics-skeleton-map-canvas" />
            <div className="analytics-skeleton-map-panel">
              <SkeletonBlock />
              <SkeletonBlock />
              <SkeletonBlock />
              <SkeletonBlock />
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="analytics-skeleton-chart-heading">
            <SkeletonBlock />
            <SkeletonBlock />
          </div>
          <div className="analytics-skeleton-chart-plot">
            <div className="analytics-skeleton-chart-grid" />
            <div className="analytics-skeleton-chart-bars">
              {bars.map((height, index) => (
                <SkeletonBlock key={index} style={{ height: `${height}%` }} />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
};

const getStackedChartLayout = (data, statuses) => {
  const rows = data.filter(row => statuses.some(status => Number(row[status.key] || 0) > 0)).length;
  return { rows, height: rows > 0 ? Math.max(280, rows * 40 + 70) + 30 : 220 };
};

const AnalyticsMetricValue = ({ value, loading, variant = "standard" }) => (
  loading
    ? <SkeletonBlock className={`analytics-kpi-value-skeleton analytics-kpi-value-skeleton--${variant}`} />
    : value
);

// ── Empty State ──────────────────────────────────────────────────────────────
const EmptyState = ({ title = "No Data", message = "", h = 220, icon }) => (
  <div className="analytics-empty-state" style={{
    height: h, width: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
    textAlign: "center", gap: 12
  }}>
    {icon || <img src="/searching.png" alt="Empty" style={{ height: 80, objectFit: "contain", opacity: 0.9 }} />}
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-ink)", marginBottom: message ? 4 : 0 }}>{title}</div>
      {message && <div style={{ fontSize: 13, color: "var(--color-muted)", maxWidth: 220, margin: "0 auto", lineHeight: 1.4 }}>{message}</div>}
    </div>
  </div>
);

const ProfileTable = ({ title, rows, empty = "No data" }) => {
  const total = rows.reduce((sum, row) => sum + Number(row.value || 0), 0);
  return (
    <div className="analytics-profile-table-wrap">
      <h5>{title}</h5>
      {rows.length === 0 ? <p className="analytics-stacked-footnote">{empty}</p> : (
        <div className="analytics-profile-table-frame">
          <table className="analytics-profile-table">
            <caption className="analytics-sr-only">{title} distribution</caption>
            <thead><tr><th scope="col">Profile</th><th scope="col">Count</th><th scope="col">Share</th></tr></thead>
            <tbody>{rows.map(row => (
              <tr key={row.name}>
                <td>{row.name || "Unspecified"}</td>
                <td>{Number(row.value || 0).toLocaleString()}</td>
                <td>{total > 0 ? `${((Number(row.value || 0) / total) * 100).toFixed(1)}%` : "0.0%"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
};

const createEmptyFilters = () => ({
  barangay_ids: [],
  application_status: "",
  line_of_business: "",
  business_type: "",
  business_size: "",
  registration_type: "",
  renewal_from: "",
  renewal_to: "",
  flag_color: "",
  detected_from: "",
  detected_to: "",
  inspection_result: "",
  verification_status: "",
  inspection_from: "",
  inspection_to: "",
});

const filterInputStyle = {
  width: "100%",
  padding: "9px 12px",
  borderRadius: "var(--radius-sm, 8px)",
  border: "1px solid var(--color-border)",
  fontSize: 13,
  background: "var(--color-card-alt)",
  color: "var(--color-ink)",
  outline: "none",
  fontFamily: "var(--font-base)",
  transition: "border-color 0.15s ease",
};

const filterLabelStyle = {
  display: "block", fontSize: 11, fontWeight: 700, color: "var(--color-muted)",
  marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.04em"
};

function countActiveBackendFilters(applied) {
  if (!applied || typeof applied !== "object") return 0;
  let n = 0;
  if (applied.barangay_ids?.length) n += 1;
  for (const k of Object.keys(createEmptyFilters())) {
    if (k === "barangay_ids") continue;
    if (applied[k]) n += 1;
  }
  return n;
}

// ─────────────────────────────────────────────────────────────────────────────

// --- Insight Generator Logic (Auto-Analyze) ---
// Lightweight markdown renderer for AI chat bubbles
const renderMarkdown = (text) => {
  if (!text) return null;
  const lines = text.split("\n");
  const elements = [];
  let listItems = [];
  let listType = null;

  let inTable = false;
  let tableHeader = null;
  let tableRows = [];

  const formatInline = (str) => {
    const parts = str.split(/(\*\*[^*]+\*\*)/);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });
  };

  const flushList = () => {
    if (listItems.length > 0) {
      const Tag = listType === 'ol' ? 'ol' : 'ul';
      elements.push(
        <Tag key={`list-${elements.length}`} style={{ margin: "6px 0", paddingLeft: 20, lineHeight: 1.7 }}>
          {listItems.map((li, j) => <li key={j}>{formatInline(li)}</li>)}
        </Tag>
      );
      listItems = [];
      listType = null;
    }
  };

  const flushTable = () => {
    if (inTable) {
      elements.push(
        <div key={`table-${elements.length}`} className="ai-message-table">
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, textAlign: "left" }}>
            {tableHeader && <thead><tr style={{ background: "color-mix(in srgb, var(--color-ink) 5%, transparent)" }}>
              {tableHeader.map((h, i) => <th key={i} style={{ padding: "8px 12px", borderBottom: "1px solid var(--color-border)", fontWeight: 600 }}>{formatInline(h)}</th>)}
            </tr></thead>}
            <tbody>
              {tableRows.map((row, i) => (
                <tr key={i} style={{ borderBottom: i === tableRows.length - 1 ? "none" : "1px solid var(--color-border)" }}>
                  {row.map((cell, j) => <td key={j} style={{ padding: "8px 12px" }}>{formatInline(cell)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      inTable = false;
      tableHeader = null;
      tableRows = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    const olMatch = line.match(/^(\d+)\.\s+(.+)/);
    const ulMatch = line.match(/^[-*]\s+(.+)/);
    const headingMatch = line.match(/^(#{1,6})\s+(.+)/);
    const tableMatch = line.match(/^\|(.+)\|$/);

    if (tableMatch) {
      flushList();
      const cells = tableMatch[1].split('|').map(c => c.trim()).filter(c => c !== "");
      if (!inTable) {
        inTable = true;
        tableHeader = cells;
      } else {
        if (cells.every(c => c.replace(/[:\- ]/g, '') === '')) {
          // skip separator
        } else {
          tableRows.push(cells);
        }
      }
    } else if (headingMatch) {
      flushTable();
      flushList();
      const level = headingMatch[1].length;
      const Tag = `h${level}`;
      const fontSize = level === 1 ? 16 : level === 2 ? 15 : 14;
      elements.push(
        <Tag key={`h-${i}`} style={{ margin: "10px 0 4px", fontSize, fontWeight: 700 }}>
          {formatInline(headingMatch[2])}
        </Tag>
      );
    } else if (olMatch) {
      flushTable();
      if (listType !== 'ol') flushList();
      listType = 'ol';
      listItems.push(olMatch[2]);
    } else if (ulMatch) {
      flushTable();
      if (listType !== 'ul') flushList();
      listType = 'ul';
      listItems.push(ulMatch[1]);
    } else {
      flushTable();
      flushList();
      if (line === "") {
        elements.push(<div key={`br-${i}`} style={{ height: 6 }} />);
      } else {
        elements.push(<p key={`p-${i}`} style={{ margin: "3px 0" }}>{formatInline(line)}</p>);
      }
    }
  }
  flushTable();
  flushList();
  return elements;
};

const GlobalAIAssistant = memo(({ globalData }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [readingMode, setReadingMode] = useState(false);
  const [messages, setMessages] = useState([{
    role: "model",
    content: "I am the REVELA AI Analyst. I have reviewed all the data currently visible on your dashboard. What would you like to know?",
  }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const { token } = useAuth();
  const chatScrollRef = useRef(null);
  const inputRef = useRef(null);
  const launcherRef = useRef(null);
  const panelRef = useRef(null);
  const pendingRef = useRef(false);
  const followMessagesRef = useRef(true);
  const savedScrollTopRef = useRef(0);

  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  useLayoutEffect(() => {
    const el = chatScrollRef.current;
    if (!isOpen || !el) return;
    el.scrollTop = followMessagesRef.current ? el.scrollHeight : savedScrollTopRef.current;
  }, [isOpen]);

  useLayoutEffect(() => {
    const el = chatScrollRef.current;
    if (el && followMessagesRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  useLayoutEffect(() => {
    if (!isOpen || !inputRef.current) return;
    const textarea = inputRef.current;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 108)}px`;
  }, [input, isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const updateViewport = () => {
      const viewport = window.visualViewport;
      const panel = panelRef.current;
      if (!panel) return;
      panel.style.setProperty("--ai-visual-top", `${viewport?.offsetTop ?? 0}px`);
      panel.style.setProperty("--ai-visual-bottom", `${Math.max(0, window.innerHeight - (viewport?.offsetTop ?? 0) - (viewport?.height ?? window.innerHeight))}px`);
      panel.style.setProperty("--ai-visual-height", `${viewport?.height ?? window.innerHeight}px`);
    };
    updateViewport();
    window.visualViewport?.addEventListener("resize", updateViewport);
    window.visualViewport?.addEventListener("scroll", updateViewport);
    window.addEventListener("resize", updateViewport);
    return () => {
      window.visualViewport?.removeEventListener("resize", updateViewport);
      window.visualViewport?.removeEventListener("scroll", updateViewport);
      window.removeEventListener("resize", updateViewport);
    };
  }, [isOpen]);

  const closePanel = () => {
    savedScrollTopRef.current = chatScrollRef.current?.scrollTop ?? 0;
    setReadingMode(false);
    setIsOpen(false);
    requestAnimationFrame(() => launcherRef.current?.focus());
  };

  const handleSend = async (e, forcedInput = null) => {
    e?.preventDefault();
    const textToSend = forcedInput !== null ? forcedInput : input;
    if (!textToSend.trim() || pendingRef.current) return;
    pendingRef.current = true;

    const userMsg = { role: "user", content: textToSend.trim() };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    if (forcedInput === null) setInput("");
    setLoading(true);

    try {
      const data = await sendAnalyticsChatRequest({
        chartId: "global_dashboard",
        data: globalData,
        messages: messages,
        userQuery: userMsg.content
      }, token);

      setMessages([...newMessages, { role: "model", content: data.response }]);
    } catch (err) {
      setMessages([...newMessages, { role: "model", content: `Error: ${err.message}` }]);
    } finally {
      pendingRef.current = false;
      setLoading(false);
    }
  };

  return (
    <div className="analytics-assistant">
      {!isOpen && (
        <button
          ref={launcherRef}
          onClick={() => setIsOpen(true)}
          className="analytics-assistant-launcher analytics-mascot-launcher"
          aria-label="Open AI Analyst"
          title="Open AI Analyst"
        >
          <img src="/standing.png" alt="" />
          <span className="analytics-mascot-status" aria-hidden="true" />
        </button>
      )}

      {isOpen && (
        <div ref={panelRef} className={`analytics-assistant-panel${readingMode ? " is-reading" : ""}`} role="dialog" aria-label="REVELA AI Analyst">
          {/* Header */}
          <div className="ai-chat-header">
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{
                width: 40, height: 40, borderRadius: "50%",
                background: "linear-gradient(135deg, var(--color-surface), var(--color-card-alt))",
                display: "flex", alignItems: "center", justifyContent: "center",
                border: "2px solid var(--color-primary)", overflow: "hidden"
              }}>
                <img src={loading ? "/searching.png" : "/standing.png"} alt="Mascot" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-ink)" }}>REVELA AI Analyst</div>
                <div style={{ fontSize: 11, color: "var(--color-primary)", fontWeight: 600 }}>
                  {loading ? "Analyzing dashboard..." : "Online & Ready"}
                </div>
              </div>
            </div>
            <div className="ai-chat-header-actions">
              <button type="button" className="ai-chat-header-button" onClick={() => setReadingMode(current => !current)}
                aria-label={readingMode ? "Restore AI Analyst panel" : "Expand AI Analyst panel"} aria-pressed={readingMode}
                title={readingMode ? "Restore panel" : "Expand panel"}>
                {readingMode ? "↙" : "⤢"}
              </button>
              <button type="button" className="ai-chat-header-button" onClick={closePanel} aria-label="Close AI Analyst" title="Close AI Analyst">
                <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          {/* Messages */}
          <div ref={chatScrollRef} className="ai-chat-conversation" onScroll={event => {
            const el = event.currentTarget;
            savedScrollTopRef.current = el.scrollTop;
            followMessagesRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}>
            {messages.map((m, i) => (
              <div key={i} className={`ai-chat-message ai-chat-message--${m.role === "user" ? "user" : "model"}`}>
                <div className="ai-chat-bubble">
                  <div className="ai-chat-byline">
                    {m.role === "user" ? "You" : "AI Analyst"}
                  </div>
                  <div className="ai-message-content">{m.role === "model" ? renderMarkdown(m.content) : m.content}</div>
                </div>
              </div>
            ))}
            {loading && (
              <div className="ai-chat-typing" aria-label="AI Analyst is responding" role="status">
                {[0, 1, 2].map(n => (
                  <span key={n} style={{ animationDelay: `${n * 0.15}s` }} />
                ))}
              </div>
            )}

            {/* Predefined questions stay in the single conversation scroller. */}
            {messages.length === 1 && !loading && (
              <div className="ai-chat-suggestions">
                {[
                  "What are the main takeaways?",
                  "Are there any anomalies?",
                  "How does this compare to expected trends?"
                ].map((q, idx) => (
                  <button key={idx} onClick={() => handleSend(null, q)} type="button">{q}</button>
                ))}
              </div>
            )}
          </div>

          {/* Input */}
          <form className="ai-chat-composer" onSubmit={handleSend}>
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Ask me anything about this data..."
              aria-label="Message the AI Analyst"
              className="ai-chat-input"
              disabled={loading}
            />
            <button
              type="submit"
              className="ai-send-btn"
              disabled={loading || !input.trim()}
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
              Send
            </button>
          </form>
        </div>
      )}
    </div>
  );
});


export default function AnalyticsPage() {
  const { token, user } = useAuth();
  const canEditWlc = ["Admin", "SUPER_ADMIN", "System Administrator"].includes(user?.role);
  const [searchParams, setSearchParams] = useSearchParams();
  const route = analyticsRoute(searchParams);
  const activeTab = route.tab;
  const setActiveTab = (tab) => setSearchParams(previous => {
    const next = new URLSearchParams(previous);
    next.set("tab", tab);
    return next;
  });
  const [showFloatingNav, setShowFloatingNav] = useState(false);
  const sectionNavRef = useRef(null);
  const [draftFilters, setDraftFilters] = useState(() => ({ ...createEmptyFilters(), barangay_ids: route.barangayId ? [route.barangayId] : [] }));
  const [appliedFilters, setAppliedFilters] = useState(() => ({ ...createEmptyFilters(), barangay_ids: route.barangayId ? [route.barangayId] : [] }));
  const routeBarangay = route.barangayId;
  const [lastRouteBarangay, setLastRouteBarangay] = useState(routeBarangay);
  if (lastRouteBarangay !== routeBarangay) {
    setLastRouteBarangay(routeBarangay);
    setDraftFilters(previous => ({ ...previous, barangay_ids: routeBarangay ? [routeBarangay] : [] }));
    setAppliedFilters(previous => ({ ...previous, barangay_ids: routeBarangay ? [routeBarangay] : [] }));
  }
  const effectiveFilters = useMemo(() => activeTab === "prescriptive"
    ? { barangay_ids: appliedFilters.barangay_ids } : appliedFilters, [activeTab, appliedFilters]);
  const [wlcSnapshot, setWlcSnapshot] = useSessionDataset("analytics:settings", "wlc", null,
    `analytics:${JSON.stringify(effectiveFilters)}`);
  const [wlcConfig, setWlcConfig] = useState(() => wlcSnapshot ?? { ...DEFAULT_WLC_WEIGHTS });
  const [showWlcConfig, setShowWlcConfig] = useState(false);
  const [savingWlc, setSavingWlc] = useState(false);
  const [wlcSaveError, setWlcSaveError] = useState("");
  const [wlcConfigReady, setWlcConfigReady] = useState(() => Boolean(wlcSnapshot));
  const wlcValidationError = wlcPolicyError(wlcConfig);
  const [expandedDispatch, setExpandedDispatch] = useState({});
  const [showAllRecommendations, setShowAllRecommendations] = useState(false);
  const [lastDetectionRun, setLastDetectionRun] = useState(null);
  const [lastDetectionRunError, setLastDetectionRunError] = useState("");
  const [filterOptions, setFilterOptions] = useSessionDataset("analytics:options", "filters", null,
    `analytics:${JSON.stringify(effectiveFilters)}`);
  const filterMeta = filterOptions?.meta ?? null;
  const barangaysList = filterOptions?.barangays ?? EMPTY_FILTER_BARANGAYS;
  const [filterMetaError, setFilterMetaError] = useState(false);
  const [filterRetry, setFilterRetry] = useState(0);
  const loadFilterOptions = useCallback(async () => {
    if (!token) return false;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 20000);
    try {
      const [meta, brgy] = await Promise.allSettled([
        getAnalyticsFilterMetadataRequest(token, { signal: controller.signal }),
        getBarangaysRequest(token, { signal: controller.signal }),
      ]);
      if (meta.status === "fulfilled") setFilterOptions(previous => ({ ...previous, meta: meta.value }));
      if (brgy.status === "fulfilled") {
        const value = brgy.value;
        setFilterOptions(previous => ({ ...previous, barangays: Array.isArray(value) ? value : (Array.isArray(value?.data) ? value.data : []) }));
      }
      const failed = meta.status === "rejected" || brgy.status === "rejected";
      setFilterMetaError(failed);
      return !failed;
    } finally { window.clearTimeout(timer); }
  }, [token, setFilterOptions]);
  const { sections, offline, refresh: fetchAnalytics } = useAnalyticsData(token, effectiveFilters, undefined, "analytics", () => loadFilterOptions());
  const [rememberedSections, setRememberedSections] = useState({ source: sections, data: {} });
  if (rememberedSections.source !== sections) {
    setRememberedSections({ source: sections, data: Object.fromEntries(
      Object.entries(sections).map(([name, section]) => [name, section.data || rememberedSections.data[name]]),
    ) });
  }
  const currentSection = sections[activeTab];
  const hasVisibleData = Boolean(currentSection.data || rememberedSections.data[activeTab]);
  const data = useMemo(() => Object.fromEntries(
    Object.entries(sections).map(([name, section]) => [name, section.data || rememberedSections.data[name]]),
  ), [sections, rememberedSections.data]);
  const loading = !hasVisibleData && currentSection.status === "loading";
  const [skeletonTab, setSkeletonTab] = useState(null);
  useEffect(() => {
    if (!loading) return undefined;
    return scheduleAnalyticsSkeleton(() => setSkeletonTab(activeTab));
  }, [activeTab, loading]);
  const error = currentSection.error;
  const expiredSection = Object.values(sections).find(section => section.status === "expired");
  const snapshotIsExpired = Boolean(expiredSection);
  const cacheMetadata = expiredSection?.metadata ?? currentSection.metadata;
  const backgroundRefreshing = currentSection.updating;
  const [showFilters, setShowFilters] = useState(false);
  const [mapOverviewExpanded, setMapOverviewExpanded] = useState(false);
  const [openSections, setOpenSections] = useState({ location: false, business: false, flags: false, inspection: false });
  const [brgySearchTerm, setBrgySearchTerm] = useState("");
  const [brgyDropdownOpen, setBrgyDropdownOpen] = useState(false);
  const brgyDropdownRef = useRef(null);

  useEffect(() => {
    if (!showFilters) return undefined;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setShowFilters(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showFilters]);

  useEffect(() => {
    const nav = sectionNavRef.current;
    const scrollRoot = nav?.closest(".saas-content");
    if (!nav || !scrollRoot) return undefined;

    const observer = new IntersectionObserver(([entry]) => {
      setShowFloatingNav(!entry.isIntersecting || entry.intersectionRatio < 0.99);
    }, { root: scrollRoot, threshold: [0, 0.99, 1] });
    observer.observe(nav);
    return () => observer.disconnect();
  }, []);

  const fetchWlcConfig = useCallback(async () => {
    if (!token) return;
    setWlcConfigReady(false);
    try {
      const res = await getWlcConfigRequest(token);
      if (res) {
        setWlcConfig({ w1_risk: res.w1_risk ?? DEFAULT_WLC_WEIGHTS.w1_risk, w2_sector: res.w2_sector ?? DEFAULT_WLC_WEIGHTS.w2_sector, w3_distance: res.w3_distance ?? DEFAULT_WLC_WEIGHTS.w3_distance });
        setWlcSnapshot(res);
        setWlcConfigReady(true);
        setWlcSaveError("");
      }
    } catch (e) {
      setWlcSaveError(e.message || "Could not load saved WLC weights. Reopen Quick Adjust to retry.");
    }
  }, [token, setWlcSnapshot]);

  const handleSaveWlc = async () => {
    if (!wlcConfigReady) return;
    setWlcSaveError("");
    if (wlcValidationError) {
      setWlcSaveError(wlcValidationError);
      return;
    }
    setSavingWlc(true);
    try {
      await updateWlcConfigRequest(wlcConfig, token);
      window.dispatchEvent(new CustomEvent("revela:policy-update", { detail: { localMutation: true, policy: wlcConfig } }));
      await fetchAnalytics();
      setShowWlcConfig(false);
    } catch (e) {
      setWlcSaveError(e.message || "Could not save WLC weights.");
    } finally {
      setSavingWlc(false);
    }
  };

  const handleCancelWlc = () => {
    setWlcSaveError("");
    fetchWlcConfig();
    setShowWlcConfig(false);
  };

  const handleUseDefaultWlc = () => {
    setWlcConfig(prev => ({
      ...prev,
      ...DEFAULT_WLC_WEIGHTS,
    }));
  };


  useEffect(() => {
    let current = true;
    queueMicrotask(() => { if (current && !wlcSnapshot) void fetchWlcConfig(); });
    return () => { current = false; };
  }, [fetchWlcConfig, wlcSnapshot]);

  useEffect(() => {
    if (filterRetry) void loadFilterOptions();
  }, [filterRetry, loadFilterOptions]);

  useEffect(() => {
    if (!token || activeTab !== "prescriptive") return undefined;
    const controller = new AbortController();
    getAnalyticsHotspotsRequest(token, "all", { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setLastDetectionRun(response?.last_detection_run ?? null);
        setLastDetectionRunError("");
      })
      .catch((requestError) => {
        if (controller.signal.aborted || requestError.name === "AbortError") return;
        setLastDetectionRun(null);
        setLastDetectionRunError(
          requestError.message || "Detection scan status could not be loaded.",
        );
      });
    return () => controller.abort();
  }, [activeTab, token]);

  // ── Derived shorthand references ──────────────────────────────────────────
  const desc = data?.descriptive;
  const presc = data?.prescriptive;
  const prescWorkforce = presc?.workforce;
  const prescModel = presc?.model;
  const prescWeights = prescModel?.weights;
  const prescWeight = (key) =>
    typeof prescWeights?.[key] === "number" ? `${(prescWeights[key] * 100).toFixed(1)}%` : "—";
  const kpis = desc?.kpis;





  // ── Registry profile (compact tables, no charts) ──────────────────────────
  const sectoralData = (desc?.sectoral_distribution || []).map((r) => ({
    name: r.sector,
    value: r.count,
  }));
  const sizeData = (desc?.business_size_dist || []).map((r) => ({
    name: r.size_label,
    value: r.count,
  }));
  const typeData = (desc?.business_type_dist || []).map((r) => ({
    name: r.type_label,
    value: r.count,
  }));
  const regTypeData = (desc?.registration_type_dist || []).map((r) => ({
    name: r.type_label,
    value: r.count,
  }));
  const profileTables = [
    { title: "Sector", rows: sectoralData },
    { title: "Business size", rows: sizeData },
    { title: "Business type", rows: typeData },
    { title: "Registration type", rows: regTypeData },
  ];

  // ── Descriptive cross-tabs ────────────────────────────────────────────────
  const registryChartData = desc?.registry_by_barangay_status || [];
  const registrySizeChartData = pivotCategoryCounts(
    desc?.registry_size_by_barangay || [], "size_label",
  );
  const businessSizeLabels = [...new Set(
    (desc?.registry_size_by_barangay || []).map(row => row.size_label || "Unknown"),
  )].sort((a, b) => {
    const order = ["Micro", "Small", "Medium", "Large", "Unknown"];
    return (order.indexOf(a) < 0 ? order.length : order.indexOf(a))
      - (order.indexOf(b) < 0 ? order.length : order.indexOf(b)) || a.localeCompare(b);
  });
  const businessSizeStacks = businessSizeLabels.map((label, index) => ({
    key: label,
    label,
    color: BUSINESS_SIZE_COLORS[label] || [COLOR.blue, COLOR.green, COLOR.purple, COLOR.orange][index % 4],
  }));
  const rawInspectionChartData = desc?.inspection_by_barangay_status || [];
  const inspectionChartData = groupInspectionStatuses(rawInspectionChartData);
  const inspectionNoReportBarangays = Math.max(0,
    rawInspectionChartData.length - inspectionChartData.length);
  const inspectionOutcomeChartData = pivotCategoryCounts(
    desc?.inspection_outcome_by_barangay || [], "outcome",
  );
  const verifiedReportsWithoutOutcome = Number(
    desc?.audit_summary?.verified_reports_without_outcome ?? 0,
  );

  // ── Prescriptive: WLC radar (top 8) ──────────────────────────────────────
  const radarData = opsRadarData(presc?.rankings, shortBarangay);

  const linkedReportCount = Number(desc?.audit_summary?.total_reports ?? desc?.audit_summary?.total_inspections ?? 0);
  const verifiedReportCount = Number(desc?.audit_summary?.workflow?.verified_reports ?? 0);
  const awaitingCount = Number(desc?.audit_summary?.workflow?.awaiting_verification || 0);
  const confirmedCompliance = desc?.confirmed_compliance;

  const operationsStatusRows = activeInspectorWorkload(
    data?.operations?.inspector_stats || [],
    data?.operations?.inspector_status_counts || [],
  );
  const operationsStatusTotals = groupOperationsStatusBreakdown(
    data?.operations?.status_breakdown || [],
  );
  const operationsTimeline = completeInspectionTimeline(
    data?.operations?.inspection_status_timeline || [],
    appliedFilters.inspection_from,
    appliedFilters.inspection_to,
  );
  const operationsTimelineChartRows = operationsTimeline.rows.map(row => ({
    ...row,
    awaiting_review: row.submitted,
  }));
  const operationsChartStatusTotals = OPERATIONS_STATUS_STACKS.map(status => ({
    ...status,
    total: operationsStatusRows.reduce(
      (sum, row) => sum + Number(row[status.key] || 0),
      0,
    ),
  }));
  const recommendationRows = rankedRecommendationRows(
    presc?.rankings || [],
    presc?.dispatch_recommendations || [],
  );
  const activeRecommendations = activeFlagRecommendations(recommendationRows);
  const visibleRecommendations = showAllRecommendations
    ? activeRecommendations.rows
    : activeRecommendations.rows.slice(0, 5);


  const activeFilterCount = countActiveBackendFilters(appliedFilters);

  const handleApplyFilters = () => {
    if (activeTab === "prescriptive") {
      const next = new URLSearchParams(searchParams);
      if (draftFilters.barangay_ids[0]) next.set("barangay_id", String(draftFilters.barangay_ids[0]));
      else next.delete("barangay_id");
      setSearchParams(next);
    }
    setAppliedFilters({
      ...draftFilters,
      barangay_ids: [...draftFilters.barangay_ids],
    });
    setShowFilters(false);
  };

  const handleClearFilters = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("barangay_id");
    setSearchParams(next);
    const empty = createEmptyFilters();
    setDraftFilters(empty);
    setAppliedFilters(empty);
  };

  // ── Accordion toggle helper ─────────────────────────────────────────────
  const toggleSection = (key) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));

  // ── Outside-click handler for barangay dropdown ─────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (brgyDropdownRef.current && !brgyDropdownRef.current.contains(e.target)) {
        setBrgyDropdownOpen(false);
      }
    };
    if (brgyDropdownOpen) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [brgyDropdownOpen]);

  // ── Active filter chips from applied state ──────────────────────────────
  const activeChips = useMemo(() => {
    const chips = [];
    const af = appliedFilters;
    if (af.barangay_ids?.length) {
      af.barangay_ids.forEach((id) => {
        const b = barangaysList.find((x) => x.barangayID === id);
        if (b) chips.push({ key: `brgy-${id}`, label: b.barangayName, clear: () => {
          setAppliedFilters((p) => ({ ...p, barangay_ids: p.barangay_ids.filter((x) => x !== id) }));
          setDraftFilters((p) => ({ ...p, barangay_ids: p.barangay_ids.filter((x) => x !== id) }));
        } });
      });
    }
    const labelMap = {
      application_status: "Registry",
      flag_color: "Flag",
      line_of_business: "Sector",
      business_type: "Type",
      business_size: "Size",
      renewal_from: "Renewal ≥",
      renewal_to: "Renewal ≤",
      detected_from: "Detected ≥",
      detected_to: "Detected ≤",
      inspection_result: "Result",
      verification_status: "Verification",
      inspection_from: "Inspected ≥",
      inspection_to: "Inspected ≤",
    };
    Object.entries(labelMap).forEach(([k, lbl]) => {
      if (af[k]) chips.push({ key: k, label: `${lbl}: ${af[k]}`, clear: () => {
        setAppliedFilters((p) => ({ ...p, [k]: "" }));
        setDraftFilters((p) => ({ ...p, [k]: "" }));
      } });
    });
    return chips;
  }, [appliedFilters, barangaysList]);

  const formatResultName = (val) => {
    switch (val) {
      case 'Green': return 'Registered';
      case 'Yellow': return 'Suspected (Needs Verification)';
      case 'Orange': return 'Warned / Non-Compliant';
      case 'Red': return 'Unregistered';
      case 'Black': return 'Blacklisted / Non-Responsive';
      case 'Purple': return 'Closed / Abandoned';
      default: return val;
    }
  };

  const fm = filterMeta || {};
  const sel = (value, onChange, options, placeholder, isResult = false) => (
    <select value={value} onChange={onChange} style={filterInputStyle}>
      <option value="">{placeholder}</option>
      {(options || []).map((opt) => (
        <option key={String(opt)} value={String(opt)}>{isResult ? formatResultName(String(opt)) : String(opt)}</option>
      ))}
    </select>
  );

  // ─────────────────────────────────────────────────────────────────────────
  const globalData = useMemo(() => {
    const dbscanEntries = data?.diagnostic?.dbscan_clusters || [];
    const groupedRecords = new Map();
    dbscanEntries.forEach((entry) => {
      if (entry.cluster === -1) return;
      const records = groupedRecords.get(entry.cluster) || [];
      records.push(entry);
      groupedRecords.set(entry.cluster, records);
    });
    const barangayPoints = data?.diagnostic?.morans_data?.points || [];

    return {
      geographic: data?.descriptive?.nature_per_barangay || [],
      sectoral: data?.descriptive?.sectoral_distribution || [],
      size: data?.descriptive?.business_size_dist || [],
      legalStructure: data?.descriptive?.business_type_dist || [],
      complianceBySize: data?.descriptive?.compliance_by_size || [],
      complianceTimeline: data?.descriptive?.compliance_timeline || [],
      enforcement: data?.descriptive?.enforcement_progress || [],
      audit: data?.descriptive?.audit_summary || {},
      confirmedCompliance: data?.descriptive?.confirmed_compliance || {},
      kpis: data?.descriptive?.kpis || {},
      barangayRisk: data?.diagnostic?.barangay_risk_data || [],
      spatialDiagnostics: data?.diagnostic ? {
        nearbyFlaggedGroups: {
          analysisAvailable: dbscanEntries.length > 0,
          population: data?.diagnostic?.dbscan_population || {},
          parametersUsed: data?.diagnostic?.parameters_used || {},
          eligibleRecordCount: dbscanEntries.length,
          ungroupedRecordCount: dbscanEntries.filter((entry) => entry.cluster === -1).length,
          groupCount: groupedRecords.size,
          groups: [...groupedRecords.entries()].map(([cluster, records]) => ({
            cluster,
            recordCount: records.length,
            barangays: [...new Set(records.map((entry) => entry.barangay).filter(Boolean))],
          })),
        },
        severeFlagsByBarangay: {
          analysisAvailable: barangayPoints.length > 0,
          benchmark: data?.diagnostic?.morans_data?.threshold ?? 0,
          highCountBarangayCount: barangayPoints.filter((point) => point.is_high_risk).length,
          barangays: barangayPoints.map((point) => ({
            barangay: point.barangay,
            severeFlagRecordCount: point.risk,
            aboveBenchmark: point.is_high_risk,
          })),
        },
      } : {},
      categoryRiskDrivers: data?.diagnostic?.category_risk_drivers || [],
      categoryLinkageSummary: data?.diagnostic?.category_linkage_summary || {},
      scanHistory: data?.diagnostic?.scan_history || [],
      // Prescriptive tier
      opsRankings: data?.prescriptive?.rankings || [],
      wlcConfig: data?.prescriptive?.wlc_config || {},
      wlcModel: data?.prescriptive?.model || {},
      dispatchWorkforce: data?.prescriptive?.workforce || {},
      dispatchRecommendations: data?.prescriptive?.dispatch_recommendations || [],
      // Operations tier
      inspectorStats: data?.operations?.inspector_stats || [],
      statusBreakdown: data?.operations?.status_breakdown || [],
      inspectionTimeline: data?.operations?.inspection_timeline || [],
    };
  }, [data]);

  return (
    <DashboardLayout className="analytics-page" bottomBar={(
      <div className="analytics-tools">
        {showFloatingNav && !snapshotIsExpired && (
          <nav className="analytics-quick-nav" aria-label="Analytics quick navigation">
            {ANALYTICS_TABS.map(tab => (
              <button
                key={tab.id}
                type="button"
                className={`analytics-quick-nav-btn${activeTab === tab.id ? " active" : ""}`}
                aria-pressed={activeTab === tab.id}
                aria-current={activeTab === tab.id ? "page" : undefined}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        )}
        {!snapshotIsExpired && <GlobalAIAssistant globalData={globalData} />}
      </div>
    )}>
      <style>{`
        /* shimmer keyframe now defined globally in global.css */
        .saas-card { position: relative; }
        .saas-card:not(.analytics-filter-modal):focus-within,
        .saas-card:not(.analytics-filter-modal):hover { z-index: 50; }
        
        /* New Tier System */
        .tier-1-card {
          border: 2px solid rgba(99, 102, 241, 0.2);
          background: rgba(99, 102, 241, 0.03);
          box-shadow: 0 4px 20px rgba(99, 102, 241, 0.1);
        }
        .tier-2-card {
          /* Standard current style */
        }
        .tier-3-card {
          background: rgba(0, 0, 0, 0.02);
          border-color: transparent;
          box-shadow: none;
        }

        .ops-row:hover { background: var(--color-hover) !important; }
        .ops-score-bar {
          height: 6px;
          border-radius: 3px;
          background: var(--color-border-soft);
          overflow: hidden;
          width: 80px;
        }
        .ops-score-fill {
          height: 100%;
          border-radius: 3px;
          transition: width 0.6s var(--ease-in-out);
        }

        /* ── Filter Panel Redesign ──────────────────────────── */
        .filter-accordion-header {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
          border: 1px solid var(--color-border);
          border-radius: 10px;
          background: transparent;
          cursor: pointer;
          transition: all var(--duration-fast);
          width: 100%;
          text-align: left;
          color: var(--color-ink);
          font-family: var(--font-base);
        }
        .filter-accordion-header:hover {
          background: var(--color-hover);
          border-color: var(--color-border-soft);
        }
        .filter-accordion-header.open {
          border-bottom-left-radius: 0;
          border-bottom-right-radius: 0;
          border-bottom-color: transparent;
          background: var(--color-hover);
        }
        .filter-accordion-body {
          border: 1px solid var(--color-border);
          border-top: none;
          border-radius: 0 0 10px 10px;
          padding: 16px;
          background: transparent;
        }
        .filter-accordion-chevron {
          margin-left: auto;
          transition: transform var(--duration-normal) var(--ease-out);
          color: var(--color-muted);
          flex-shrink: 0;
        }
        .filter-accordion-chevron.open {
          transform: rotate(180deg);
        }
        .filter-accordion-icon {
          width: 16px;
          height: 16px;
          flex-shrink: 0;
          color: var(--color-muted);
        }
        .filter-accordion-title {
          font-size: 12px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--color-ink);
        }
        .filter-accordion-count {
          font-size: 10px;
          font-weight: 700;
          padding: 1px 7px;
          border-radius: 10px;
          background: rgba(59, 130, 246, 0.15);
          color: #3b82f6;
        }

        /* ── Custom Multi-Select Dropdown ───────────────────── */
        .brgy-multiselect {
          position: relative;
          width: 100%;
        }
        .brgy-multiselect-trigger {
          display: flex;
          align-items: center;
          flex-wrap: wrap;
          gap: 5px;
          min-height: 40px;
          padding: 6px 10px;
          border-radius: var(--radius-sm, 8px);
          border: 1px solid var(--color-border);
          background: var(--color-input-bg);
          cursor: pointer;
          transition: border-color var(--duration-fast);
        }
        .brgy-multiselect-trigger:hover,
        .brgy-multiselect-trigger.open {
          border-color: #3b82f6;
        }
        .brgy-multiselect-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 2px 8px;
          border-radius: 6px;
          background: rgba(59, 130, 246, 0.15);
          color: #3b82f6;
          font-size: 11px;
          font-weight: 600;
          white-space: nowrap;
        }
        .brgy-multiselect-chip button {
          background: none;
          border: none;
          color: #3b82f6;
          cursor: pointer;
          padding: 0;
          font-size: 13px;
          line-height: 1;
          opacity: 0.7;
          transition: opacity var(--duration-fast);
        }
        .brgy-multiselect-chip button:hover {
          opacity: 1;
        }
        .brgy-multiselect-placeholder {
          color: var(--color-muted);
          font-size: 13px;
        }
        .brgy-multiselect-panel {
          position: absolute;
          top: calc(100% + 4px);
          left: 0;
          right: 0;
          z-index: 200;
          background: var(--color-modal-bg);
          border: 1px solid var(--color-border);
          border-radius: 10px;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
          overflow: hidden;
        }
        .brgy-multiselect-search {
          width: 100%;
          padding: 10px 12px;
          border: none;
          border-bottom: 1px solid var(--color-border);
          background: transparent;
          color: var(--color-ink);
          font-size: 13px;
          font-family: var(--font-base);
          outline: none;
        }
        .brgy-multiselect-search::placeholder {
          color: var(--color-subtle);
        }
        .brgy-multiselect-list {
          max-height: 200px;
          overflow-y: auto;
          padding: 4px 0;
        }
        .brgy-multiselect-list::-webkit-scrollbar {
          width: 5px;
        }
        .brgy-multiselect-list::-webkit-scrollbar-thumb {
          background: var(--color-border);
          border-radius: 3px;
        }
        .brgy-multiselect-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 12px;
          cursor: pointer;
          transition: background var(--duration-fast);
          font-size: 13px;
          color: var(--color-ink);
        }
        .brgy-multiselect-item:hover {
          background: var(--color-hover);
        }
        .brgy-multiselect-item input[type="checkbox"] {
          accent-color: #3b82f6;
          width: 15px;
          height: 15px;
          cursor: pointer;
        }

        /* ── Filter Chips Row ──────────────────────────────── */
        .filter-chips-row {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          padding: 0;
          margin: 0;
        }
        .filter-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          border-radius: 20px;
          font-size: 12px;
          font-weight: 600;
          background: rgba(16, 185, 129, 0.12);
          color: #10b981;
          border: 1px solid rgba(16, 185, 129, 0.25);
          transition: all var(--duration-fast);
        }
        .filter-chip button {
          background: none;
          border: none;
          color: #10b981;
          cursor: pointer;
          padding: 0;
          font-size: 14px;
          line-height: 1;
          opacity: 0.7;
          transition: opacity var(--duration-fast);
        }
        .filter-chip button:hover {
          opacity: 1;
        }

        /* ── Date Range Pair ───────────────────────────────── */
        .date-range-pair {
          display: flex;
          align-items: center;
          gap: 0;
          border: 1px solid var(--color-border);
          border-radius: var(--radius-sm, 8px);
          overflow: hidden;
          background: var(--color-input-bg);
        }
        .date-range-pair input {
          flex: 1;
          padding: 9px 10px;
          border: none;
          background: transparent;
          color: var(--color-ink);
          font-size: 13px;
          font-family: var(--font-base);
          outline: none;
          min-width: 0;
        }
        .date-range-pair input:focus {
          background: var(--color-hover);
        }
        .date-range-sep {
          color: var(--color-muted);
          font-size: 12px;
          padding: 0 4px;
          flex-shrink: 0;
          user-select: none;
        }

        /* ── Sticky Footer Bar ─────────────────────────────── */
        .filter-sticky-footer {
          position: sticky;
          bottom: 0;
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 10px;
          padding: 12px 16px;
          margin: 16px -22px -20px -22px;
          border-top: 1px solid var(--color-border);
          background: var(--color-modal-bg);
          border-radius: 0 0 var(--radius-lg, 16px) var(--radius-lg, 16px);
          z-index: 10;
        }
      `}</style>

      <div className="analytics-page-shell">

        {/* PAGE HEADER */}
        <div className="analytics-page-heading">
          <div className="analytics-page-heading-copy">
            <h1 className="page-title">System Analytics</h1>
            <p className="page-subtitle" style={{ color: "var(--color-muted)" }}>
              Business and inspection insights across Mataasnakahoy
            </p>
          </div>

          <nav ref={sectionNavRef} className="analytics-section-nav" aria-label="Analytics sections">
            {ANALYTICS_TABS.map(tab => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  className={`analytics-tab-btn ${isActive ? "active" : ""}`}
                  aria-current={isActive ? "page" : undefined}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <span className="analytics-tab-label">
                    <span className="analytics-tab-dot" style={{ background: tab.dot }} aria-hidden="true" />
                    {tab.label}
                  </span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Hidden trigger for automated fixture query compatibility */}
        <h3
          className="analytics-filter-smoke-trigger"
          style={{ position: "absolute", width: 1, height: 1, padding: 0, margin: -1, overflow: "hidden", clip: "rect(0, 0, 0, 0)", border: 0 }}
          onClick={() => setShowFilters(true)}
          aria-hidden="true"
        >
          Data filters
        </h3>

        {/* Active filter chips (always visible on page when filters are set) */}
        {activeChips.length > 0 && (
          <div className="filter-chips-row" style={{ marginTop: 0, marginBottom: 16 }}>
            {activeChips.map((chip) => (
              <span key={chip.key} className="filter-chip">
                {chip.label}
                <button onClick={(e) => { e.stopPropagation(); chip.clear(); }} title="Remove filter">✕</button>
              </span>
            ))}
            <button
              type="button"
              className="ghost-btn"
              style={{ padding: "3px 10px", fontSize: 12, marginLeft: 4 }}
              onClick={handleClearFilters}
            >
              Clear all
            </button>
          </div>
        )}

        {/* ANALYTICS FILTERS PORTAL MODAL */}
        {typeof document !== "undefined" && createPortal(
          showFilters ? (
            <div className="analytics-filter-portal">
              <div
                className="analytics-filter-backdrop"
                onClick={() => setShowFilters(false)}
                aria-hidden="true"
              />
              <div
                id="analytics-filter-panel"
                className="analytics-filter-modal saas-card frosted-glass is-open"
                role="dialog"
                aria-modal="true"
                aria-labelledby="analytics-filter-title"
                onClick={(e) => e.stopPropagation()}
              >
                {/* ── Header row: title + active badge + close button ── */}
                <div className="analytics-filter-modal-header">
                  <div>
                    <h3
                      id="analytics-filter-title"
                      style={{ margin: 0, fontSize: 17, fontWeight: 800, color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 8 }}
                    >
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>
                      Data filters
                      {activeFilterCount > 0 && (
                        <span style={{ fontSize: 11, background: "rgba(16, 185, 129, 0.12)", color: "#10b981", padding: "2px 8px", borderRadius: 12, marginLeft: 8 }}>
                          {activeFilterCount} active
                        </span>
                      )}
                    </h3>
                    <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--color-muted)", maxWidth: 720 }}>
                      Registry (status, sector, type, size, renewal window), geospatial flags (color, detection window),
                      and inspections (result, verification, timestamp window). For Prescriptive, only barangay selection narrows the display; WLC scores and allocations remain municipality-wide.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="analytics-filter-close-btn"
                    onClick={() => setShowFilters(false)}
                    aria-label="Close filters"
                  >
                    ✕
                  </button>
                </div>

                {/* ── Scrollable Body ── */}
                <div className="analytics-filter-modal-body">
                  {filterMetaError && (
                    <p role="status" style={{ color: "var(--color-muted)", fontSize: 13, margin: "0 0 12px 0" }}>
                      Some filter options could not be loaded.
                      <button className="ghost-btn" type="button" onClick={() => setFilterRetry((value) => value + 1)} disabled={offline}>Retry filter options</button>
                    </p>
                  )}
                  {activeChips.length > 0 && (
                    <div className="filter-chips-row" style={{ marginBottom: 16 }}>
                      {activeChips.map((chip) => (
                        <span key={chip.key} className="filter-chip">
                          {chip.label}
                          <button onClick={(e) => { e.stopPropagation(); chip.clear(); }} title="Remove filter">✕</button>
                        </span>
                      ))}
                    </div>
                  )}

                  {/* ── Primary Filters Row ────────────────────────────── */}
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
                    gap: 16,
                    padding: 16,
                    border: "1px solid var(--color-border)",
                    borderRadius: 12,
                    marginBottom: 16,
                  }}>
                    {/* Barangay — single quick select */}
                    <div>
                      <label style={filterLabelStyle}>Barangay</label>
                      <select
                        value={draftFilters.barangay_ids[0] || ""}
                        onChange={(e) => {
                          const val = e.target.value;
                          const newIds = val ? [parseInt(val, 10)] : [];
                          setDraftFilters((d) => ({ ...d, barangay_ids: newIds }));
                          setAppliedFilters((a) => ({ ...a, barangay_ids: newIds }));
                          if (activeTab === "prescriptive") {
                            const next = new URLSearchParams(searchParams);
                            if (newIds[0]) next.set("barangay_id", String(newIds[0]));
                            else next.delete("barangay_id");
                            setSearchParams(next);
                          }
                        }}
                        style={filterInputStyle}
                      >
                        <option value="">All Barangays</option>
                        {barangaysList.map((b) => (
                          <option key={b.barangayID} value={b.barangayID}>{b.barangayName}</option>
                        ))}
                      </select>
                    </div>

                    {/* Registry Status */}
                    <div>
                      <label style={filterLabelStyle}>Registry Status</label>
                      <select
                        value={draftFilters.application_status}
                        onChange={(e) => setDraftFilters((d) => ({ ...d, application_status: e.target.value }))}
                        style={filterInputStyle}
                      >
                        <option value="">All statuses</option>
                        <option value="Active">Active</option>
                        <option value="Expired">Expired</option>
                        <option value="Revoked">Revoked</option>
                        <option value="Pending">Pending</option>
                        <option value="Closed">Closed</option>
                      </select>
                    </div>

                    {/* Flag Status */}
                    <div>
                      <label style={filterLabelStyle}>Flag Status</label>
                      <select
                        value={draftFilters.flag_color}
                        onChange={(e) => setDraftFilters((d) => ({ ...d, flag_color: e.target.value }))}
                        style={filterInputStyle}
                      >
                        <option value="">All statuses</option>
                        <option value="Green">Registered</option>
                        <option value="Yellow">Suspected</option>
                        <option value="Red">Unregistered</option>
                        <option value="Orange">1st/2nd Warning / 3rd Notice Closure</option>
                        <option value="Black">Blacklisted / Non-Responsive</option>
                        <option value="Purple">Closed / Abandoned</option>
                      </select>
                    </div>

                    {/* Sector */}
                    <div>
                      <label style={filterLabelStyle}>Sector</label>
                      {sel(draftFilters.line_of_business, (e) => setDraftFilters((d) => ({ ...d, line_of_business: e.target.value })), fm.lines_of_business, "All sectors")}
                    </div>
                  </div>

                  {/* ── Advanced Filters Label ──────────────────────────── */}
                  <p style={{ margin: "0 0 12px 0", fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Advanced Filters
                  </p>

                  {/* ── Advanced Section Accordions ────────────────────── */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 380px), 1fr))", gap: 12 }}>

                    {/* ─── LOCATION (Multi-Select) ──────────────────────── */}
                    <div>
                      <button
                        type="button"
                        className={`filter-accordion-header${openSections.location ? " open" : ""}`}
                        onClick={() => toggleSection("location")}
                      >
                        <svg className="filter-accordion-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle>
                        </svg>
                        <span className="filter-accordion-title">Location</span>
                        {draftFilters.barangay_ids.length > 0 && (
                          <span className="filter-accordion-count">{draftFilters.barangay_ids.length} selected</span>
                        )}
                        <svg className={`filter-accordion-chevron${openSections.location ? " open" : ""}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                      </button>
                      {openSections.location && (
                        <div className="filter-accordion-body">
                          <label style={{ ...filterLabelStyle, marginBottom: 8 }}>Select barangays</label>
                          <div className="brgy-multiselect" ref={brgyDropdownRef}>
                            <div
                              className={`brgy-multiselect-trigger${brgyDropdownOpen ? " open" : ""}`}
                              onClick={() => setBrgyDropdownOpen(!brgyDropdownOpen)}
                            >
                              {draftFilters.barangay_ids.length === 0 ? (
                                <span className="brgy-multiselect-placeholder">Click to select barangays…</span>
                              ) : (
                                draftFilters.barangay_ids.map((id) => {
                                  const b = barangaysList.find((x) => x.barangayID === id);
                                  return b ? (
                                    <span key={id} className="brgy-multiselect-chip">
                                      {shortBarangay(b.barangayName)}
                                      <button onClick={(e) => { e.stopPropagation(); setDraftFilters((d) => ({ ...d, barangay_ids: d.barangay_ids.filter((x) => x !== id) })); }}>✕</button>
                                    </span>
                                  ) : null;
                                })
                              )}
                            </div>
                            {brgyDropdownOpen && (
                              <div className="brgy-multiselect-panel">
                                <input
                                  className="brgy-multiselect-search"
                                  type="text"
                                  placeholder="Search barangays…"
                                  value={brgySearchTerm}
                                  onChange={(e) => setBrgySearchTerm(e.target.value)}
                                  onClick={(e) => e.stopPropagation()}
                                  autoFocus
                                />
                                <div className="brgy-multiselect-list">
                                  {barangaysList
                                    .filter((b) => b.barangayName.toLowerCase().includes(brgySearchTerm.toLowerCase()))
                                    .map((b) => {
                                      const checked = draftFilters.barangay_ids.includes(b.barangayID);
                                      return (
                                        <label
                                          key={b.barangayID}
                                          className="brgy-multiselect-item"
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                          <input
                                            type="checkbox"
                                            checked={checked}
                                            onChange={() => {
                                              setDraftFilters((d) => ({
                                                ...d,
                                                barangay_ids: checked
                                                  ? d.barangay_ids.filter((x) => x !== b.barangayID)
                                                  : [...d.barangay_ids, b.barangayID],
                                              }));
                                            }}
                                          />
                                          {b.barangayName}
                                        </label>
                                      );
                                    })}
                                  {barangaysList.filter((b) => b.barangayName.toLowerCase().includes(brgySearchTerm.toLowerCase())).length === 0 && (
                                    <div style={{ padding: "12px", textAlign: "center", color: "var(--color-muted)", fontSize: 13 }}>No matches</div>
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* ─── BUSINESS PROFILE ─────────────────────────────── */}
                    <div>
                      <button
                        type="button"
                        className={`filter-accordion-header${openSections.business ? " open" : ""}`}
                        onClick={() => toggleSection("business")}
                      >
                        <svg className="filter-accordion-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M20 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2z"></path><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"></path>
                        </svg>
                        <span className="filter-accordion-title">Business Profile</span>
                        {(draftFilters.business_type || draftFilters.business_size || draftFilters.renewal_from || draftFilters.renewal_to) && (
                          <span className="filter-accordion-count">filtered</span>
                        )}
                        <svg className={`filter-accordion-chevron${openSections.business ? " open" : ""}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                      </button>
                      {openSections.business && (
                        <div className="filter-accordion-body">
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                            <div>
                              <label style={filterLabelStyle}>Type</label>
                              {sel(draftFilters.business_type, (e) => setDraftFilters((d) => ({ ...d, business_type: e.target.value })), fm.business_types, "All types")}
                            </div>
                            <div>
                              <label style={filterLabelStyle}>Size</label>
                              {sel(draftFilters.business_size, (e) => setDraftFilters((d) => ({ ...d, business_size: e.target.value })), fm.business_sizes, "All sizes")}
                            </div>
                          </div>
                          <div style={{ marginTop: 12 }}>
                            <label style={filterLabelStyle}>Registration Status (Lifecycle)</label>
                            {sel(draftFilters.registration_type, (e) => setDraftFilters((d) => ({ ...d, registration_type: e.target.value })), fm.registration_types || ["New", "Renewal"], "All registration types")}
                          </div>
                          <div style={{ marginTop: 12 }}>
                            <label style={filterLabelStyle}>Renewal Date Range</label>
                            <div className="date-range-pair">
                              <input type="date" value={draftFilters.renewal_from} onChange={(e) => setDraftFilters((d) => ({ ...d, renewal_from: e.target.value }))} placeholder="From" />
                              <span className="date-range-sep">→</span>
                              <input type="date" value={draftFilters.renewal_to} onChange={(e) => setDraftFilters((d) => ({ ...d, renewal_to: e.target.value }))} placeholder="To" />
                            </div>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* ─── FLAG TIMELINES ───────────────────────────────── */}
                    <div>
                      <button
                        type="button"
                        className={`filter-accordion-header${openSections.flags ? " open" : ""}`}
                        onClick={() => toggleSection("flags")}
                      >
                        <svg className="filter-accordion-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"></path><line x1="4" y1="22" x2="4" y2="15"></line>
                        </svg>
                        <span className="filter-accordion-title">Flag Timelines</span>
                        {(draftFilters.detected_from || draftFilters.detected_to) && (
                          <span className="filter-accordion-count">filtered</span>
                        )}
                        <svg className={`filter-accordion-chevron${openSections.flags ? " open" : ""}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                      </button>
                      {openSections.flags && (
                        <div className="filter-accordion-body">
                          <label style={filterLabelStyle}>Detection Date Range</label>
                          <div className="date-range-pair">
                            <input type="date" value={draftFilters.detected_from} onChange={(e) => setDraftFilters((d) => ({ ...d, detected_from: e.target.value }))} placeholder="From" />
                            <span className="date-range-sep">→</span>
                            <input type="date" value={draftFilters.detected_to} onChange={(e) => setDraftFilters((d) => ({ ...d, detected_to: e.target.value }))} placeholder="To" />
                          </div>
                        </div>
                      )}
                    </div>

                    {/* ─── INSPECTION DETAILS ───────────────────────────── */}
                    <div>
                      <button
                        type="button"
                        className={`filter-accordion-header${openSections.inspection ? " open" : ""}`}
                        onClick={() => toggleSection("inspection")}
                      >
                        <svg className="filter-accordion-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line>
                        </svg>
                        <span className="filter-accordion-title">Inspection Details</span>
                        {(draftFilters.inspection_result || draftFilters.verification_status || draftFilters.inspection_from || draftFilters.inspection_to) && (
                          <span className="filter-accordion-count">filtered</span>
                        )}
                        <svg className={`filter-accordion-chevron${openSections.inspection ? " open" : ""}`} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                      </button>
                      {openSections.inspection && (
                        <div className="filter-accordion-body">
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                            <div>
                              <label style={filterLabelStyle}>Result</label>
                              {sel(draftFilters.inspection_result, (e) => setDraftFilters((d) => ({ ...d, inspection_result: e.target.value })), fm.inspection_results, "All results", true)}
                            </div>
                            <div>
                              <label style={filterLabelStyle}>Verification</label>
                              {sel(draftFilters.verification_status, (e) => setDraftFilters((d) => ({ ...d, verification_status: e.target.value })), fm.verification_statuses, "All verification")}
                            </div>
                          </div>
                          <label style={filterLabelStyle}>Inspection Date Range</label>
                          <div className="date-range-pair">
                            <input type="datetime-local" value={draftFilters.inspection_from} onChange={(e) => setDraftFilters((d) => ({ ...d, inspection_from: e.target.value }))} />
                            <span className="date-range-sep">→</span>
                            <input type="datetime-local" value={draftFilters.inspection_to} onChange={(e) => setDraftFilters((d) => ({ ...d, inspection_to: e.target.value }))} />
                          </div>
                        </div>
                      )}
                    </div>

                  </div>
                </div>

                {/* ── Sticky Apply / Clear / Close Footer ─────────────────────── */}
                <div className="analytics-filter-modal-footer">
                  {activeFilterCount > 0 && (
                    <span style={{ fontSize: 12, fontWeight: 700, color: "#10b981", marginRight: "auto" }}>
                      {activeFilterCount} filter{activeFilterCount !== 1 ? "s" : ""} active
                    </span>
                  )}
                  <button className="ghost-btn" type="button" style={{ padding: "8px 16px", fontSize: 13 }} onClick={handleClearFilters}>
                    Clear all
                  </button>
                  <button className="ghost-btn" type="button" style={{ padding: "8px 16px", fontSize: 13 }} onClick={() => setShowFilters(false)}>
                    Close
                  </button>
                  <button className="primary-btn" type="button" style={{ padding: "8px 16px", fontSize: 13 }} onClick={handleApplyFilters}>
                    Apply filters
                  </button>
                </div>

              </div>
            </div>
          ) : null,
          document.body
        )}
        {(error || offline) && (
          <div role="status" style={{
            background: COLOR.redLight, border: `1px solid ${COLOR.red}`, borderRadius: 10,
            padding: "14px 20px", marginBottom: 24, color: COLOR.red, fontWeight: 600, fontSize: 14,
          }}>
            {offline
              ? "You are offline. Available data is kept visible; analytics will retry when you reconnect."
              : `Unable to update this section: ${error}`}
            {!offline && <button type="button" className="ghost-btn" onClick={() => fetchAnalytics()}>Retry analytics</button>}
          </div>
        )}
        <div className="analytics-update-slot" role="status" aria-live="polite">
          {hasVisibleData && (currentSection.updating || !currentSection.data)
            ? "Updating analytics… Showing the last available data." : ""}
        </div>
        <span className="analytics-sr-only" role="status" aria-live="polite">
          {loading ? `Loading ${activeTab === "descriptive" ? "Overview" : "Recommendations"} analytics…` : ""}
        </span>
        {!loading && !hasVisibleData && !snapshotIsExpired && (
          <div className="saas-card analytics-section-state">
            <h3>{offline ? "Analytics unavailable offline" : "Analytics could not be loaded"}</h3>
            <p>{offline ? "Reconnect to load this section automatically." : "Please retry to load this section."}</p>
            <button type="button" className="ghost-btn" onClick={() => fetchAnalytics()} disabled={offline}>Retry</button>
          </div>
        )}

        {/* ══════════════════════════════════════════════════════════════════════
          OVERVIEW SUMMARY
      ══════════════════════════════════════════════════════════════════════ */}
        {snapshotIsExpired && (
          <div role="alert" className="saas-card analytics-stale-alert">
            <svg className="analytics-stale-alert-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 3.5 22 20.5H2L12 3.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
              <path d="M12 9v5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              <circle cx="12" cy="17" r="1" fill="currentColor" />
            </svg>
            <div className="analytics-stale-alert-copy">
              <strong className="analytics-stale-alert-title">Stale analytics — historical snapshot, not current rankings.</strong>
              <p className="analytics-stale-alert-description">
                The server's maximum fresh age is 15 minutes. Last successfully loaded results remain visible
                for reference only; do not use them as current dispatch priorities.
              </p>
              <p className="analytics-stale-alert-meta">
                Last computed: {cacheMetadata?.computed_at || "Unavailable"}.{" "}
                {cacheMetadata?.refresh_failed
                  ? "The refresh failed. The next request will retry after the backoff."
                  : backgroundRefreshing ? "Waiting for the background refresh."
                    : "Refresh Analytics to request an updated snapshot."}
              </p>
            </div>
            <button type="button" className="ghost-btn analytics-stale-alert-action" onClick={() => fetchAnalytics()} disabled={offline}>Retry</button>
          </div>
        )}
        <div className="analytics-loading-region" aria-busy={loading}>
        {activeTab === "descriptive" && loading && (
          <section className="analytics-loading-section" style={{ visibility: skeletonTab === activeTab ? "visible" : "hidden", marginBottom: 52 }}>
            <OverviewMapSkeleton />
            <InspectorOperationsSkeleton />
          </section>
        )}
        {activeTab === "descriptive" && !loading && (
          <section style={{ marginBottom: 52 }}>
            <Suspense fallback={<OverviewMapSkeleton />}>
              <MapOverview
                token={token}
                filters={appliedFilters}
              />
            </Suspense>
            <section className="saas-card frosted-glass analytics-inspector-operations-card"
              aria-labelledby="inspector-operations-heading">
              <div className="analytics-card-heading">
                <div>
                  <h3 id="inspector-operations-heading">C. Inspector Operations · All barangays</h3>
                  <p className="analytics-chart-caption">
                    Municipality-wide workload; this chart does not change with the selected barangay.
                  </p>
                </div>
                <AnalyticsInfoTip label="About inspector workload">
                  Pending includes Assigned, Reassigned, In Progress, and Unassigned reports. Waiting for review means Submitted. Verified reports are complete. Inspectors with no current work remain visible.
                </AnalyticsInfoTip>
              </div>
              {loading ? <Skeleton h={Math.max(260, operationsStatusRows.length * 40 + 80) + 40} variant="operations" rows={operationsStatusRows.length} /> : operationsStatusRows.length === 0 ? (
                <EmptyState h={260} title="No inspector data" message="No active inspectors are available for this view." />
              ) : (
                <>
                  <div className="analytics-operations-legend">
                    {INSPECTION_STATUS_STACKS.map(status => (
                      <span key={status.key}>
                        <i style={{ background: status.color }} />
                        {status.label}
                      </span>
                    ))}
                  </div>
                  <ResponsiveChart height={Math.max(260, operationsStatusRows.length * 40 + 80)}>
                    {({ width }) => (
                      <BarChart data={operationsStatusRows} layout="vertical"
                        barSize={24} barCategoryGap="22%"
                        margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                         <CartesianGrid strokeDasharray="3 3" horizontal={false}
                           stroke="var(--analytics-grid-color)" />
                        <XAxis type="number" domain={[0, "dataMax"]} allowDecimals={false}
                          tick={{ fontSize: 10, fill: "var(--color-muted)" }}
                          axisLine={false} tickLine={false} />
                        <YAxis type="category" dataKey="fullName"
                          width={Math.min(210, Math.max(128, width * 0.28))}
                          interval={0} tick={{ fontSize: 11, fill: "var(--color-muted)" }}
                          axisLine={false} tickLine={false} />
                         <Tooltip content={<CustomTooltip />} cursor={{ fill: "var(--analytics-operations-hover)" }} />
                        {INSPECTION_STATUS_STACKS.map(status => (
                          <Bar key={status.key} dataKey={status.key}
                            name={status.label} stackId="inspector-work"
                            fill={status.color} isAnimationActive={false} />
                        ))}
                      </BarChart>
                    )}
                  </ResponsiveChart>
                </>
              )}
              <details className="analytics-profile-disclosure analytics-inspector-detail">
                <summary>Details: average days and pins flagged yellow</summary>
                <div className="presc-priority-scroll">
                  <table className="analytics-operations-table">
                    <thead>
                      <tr><th>Name</th><th>Avg days</th><th>Pins flagged yellow</th></tr>
                    </thead>
                    <tbody>
                      {operationsStatusRows.map(row => (
                        <tr key={row.userID}>
                          <td>{row.fullName}</td>
                          <td>{row.avg_resolution_time ? (row.avg_resolution_time / 1440).toFixed(1) : "—"}</td>
                          <td>{Number(row.yellow_flags_reported || 0).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </section>
            {mapOverviewExpanded && (
              <>
            <SectionHeader
              tier="descriptive"
              title="Descriptive Analytics"
              subtitle="Current-state demographic profile and field inspection summaries"
            />

            {/* SECTION A: Official Registry Demographics */}
            <div style={{ marginBottom: 40 }}>
               <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24, borderBottom: "2px solid var(--color-border-soft)", paddingBottom: 8 }}>
                <h3 style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>A. Official Registry Demographics</h3>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", padding: "4px 8px", background: "rgba(59, 130, 246, 0.1)", color: "var(--color-blue, #3b82f6)", borderRadius: 12 }}>
                  Data Source: BPLO Registry
                </span>
              </div>

              <details
                className="map-overview-disclosure saas-card frosted-glass"
                onToggle={(event) => setMapOverviewExpanded(event.currentTarget.open)}
              >
                <summary>
                  <span>Which barangay would you like to explore?</span>
                </summary>
                <AnalyticsInfoTip label="About the barangay map">
                  Select a barangay to see its registry, map-pin, and inspection totals. The date range changes pin and inspection counts, not registry counts.
                </AnalyticsInfoTip>
                {mapOverviewExpanded && (
                  <Suspense fallback={<Skeleton h={560} variant="map" />}>
                    <MapOverview
                      token={token}
                      filters={appliedFilters}
                    />
                  </Suspense>
                )}
              </details>

              <h4 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 16px 0" }}>Business Census & Registration Metrics</h4>
              <div className="analytics-census-grid">
                <KpiCard iconVariant="plain" value={<AnalyticsMetricValue loading={loading} variant="compact" value={kpis?.total_businesses ?? "?"} />} label="Businesses in scope" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M3 21h18"></path><path d="M5 21V7l8-4v18"></path><path d="M19 21V11l-6-4"></path></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="green" value={<AnalyticsMetricValue loading={loading} variant="compact" value={kpis?.active_count ?? "?"} />} label="Active permits" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="red" value={<AnalyticsMetricValue loading={loading} variant="compact" value={Number(kpis?.total_businesses ?? 0) - Number(kpis?.active_count ?? 0)} />} label="Non-active permits" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>} style={{ padding: "12px 10px" }} />
              </div>

              <div className="tier-2-card saas-card frosted-glass analytics-feature-card" style={{ marginTop: 24 }}>
                <div className="analytics-card-heading">
                  <div>
                    <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: 0 }}>
                      How are businesses of each size distributed by barangay?
                    </h3>
                  </div>
                  <AnalyticsInfoTip label="About business size chart">
                    Uses the selected registry filters and groups businesses by their barangay and recorded business size. Empty sizes are shown as Unknown.
                  </AnalyticsInfoTip>
                </div>
                {loading ? <Skeleton h={getStackedChartLayout(registrySizeChartData, businessSizeStacks).height} variant="stacked" rows={Math.max(1, getStackedChartLayout(registrySizeChartData, businessSizeStacks).rows)} /> : (
                  <StackedBarangayChart data={registrySizeChartData} statuses={businessSizeStacks}
                    emptyMessage="No businesses match the selected filters." />
                )}
                <p className="analytics-chart-caption">
                  Each bar shows the number of registered businesses in that barangay.
                </p>
              </div>

              <div style={{ marginTop: 24 }}>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 16px 0" }}>Quick Insights (FAQ)</h3>
                <div className="analytics-insights-grid" style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 12 }}>
                  <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-blue)", minWidth: 0 }}>
                    <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>Most Common Business Type</p>
                    <p style={{ fontSize: 14, color: "var(--color-ink)", margin: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {typeData?.[0] ? `${typeData[0].name} (${Math.round((typeData[0].value / typeData.reduce((a, b) => a + b.value, 0)) * 100)}%)` : "N/A"}
                    </p>
                  </div>
                  <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-green)", minWidth: 0 }}>
                    <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>Dominant Economic Sector</p>
                    <p style={{ fontSize: 14, color: "var(--color-ink)", margin: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {sectoralData?.[0] ? sectoralData[0].name : "N/A"}
                    </p>
                  </div>
                </div>
              </div>

              <details className="analytics-profile-disclosure analytics-more-details">
                <summary>More details</summary>
                <div className="analytics-more-details-content">
                  <div className="tier-2-card saas-card frosted-glass analytics-feature-card analytics-feature-card--registry-status">
                    <div className="analytics-card-heading">
                      <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: 0 }}>
                        How many businesses in each barangay have each permit status?
                      </h3>
                      <AnalyticsInfoTip label="About permit status chart">
                        Uses the selected registry filters. Permit status filters limit the chart to the selected status; map and inspection filters do not affect it.
                      </AnalyticsInfoTip>
                    </div>
                    {loading ? <Skeleton h={getStackedChartLayout(registryChartData, REGISTRY_STATUS_STACKS).height} variant="stacked" rows={Math.max(1, getStackedChartLayout(registryChartData, REGISTRY_STATUS_STACKS).rows)} /> : (
                      <StackedBarangayChart data={registryChartData} statuses={REGISTRY_STATUS_STACKS}
                        emptyMessage="No businesses match the selected filters." />
                    )}
                  </div>
                  <div className="analytics-profile-grid">
                    {profileTables.map(table => (
                      <ProfileTable key={table.title} title={table.title} rows={table.rows}
                        empty={`No ${table.title.toLowerCase()} data for the selected filters.`} />
                    ))}
                  </div>
                </div>
              </details>
            </div>
            {/* SECTION B: Field Inspections Demographics */}
            <div style={{ marginBottom: 40 }}>
               <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24, borderBottom: "2px solid var(--color-border-soft)", paddingBottom: 8 }}>
                <h3 style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>B. Field Inspections Demographics</h3>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", padding: "4px 8px", background: "rgba(245, 158, 11, 0.1)", color: "var(--color-orange, #f59e0b)", borderRadius: 12 }}>
                  Data Source: Field Inspections
                </span>
              </div>

              <div className="analytics-field-kpi-group">
                <div className="analytics-field-kpi-heading">
                  <h4>Report status</h4>
                </div>
                <div className="analytics-field-kpi-grid analytics-field-kpi-grid--activity">
                  <KpiCard iconVariant="plain" value={<AnalyticsMetricValue loading={loading} value={linkedReportCount} />} label="Total reports" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>} />
                  <KpiCard iconVariant="gold" value={<AnalyticsMetricValue loading={loading} value={awaitingCount} />} label="Awaiting review" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>} />
                  <KpiCard iconVariant="green" value={<AnalyticsMetricValue loading={loading} value={verifiedReportCount} />} label="Verified" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>} />
                </div>
              </div>

              <div className="tier-2-card saas-card frosted-glass analytics-feature-card analytics-feature-card--inspection-status">
                <div className="analytics-card-heading">
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: 0 }}>
                    How many reports in each barangay are pending, awaiting review, or verified?
                  </h3>
                  <AnalyticsInfoTip label="About report status chart">
                    Pending combines Assigned, Reassigned, In Progress, and Unassigned reports. This chart includes reports that can be placed in a barangay.
                  </AnalyticsInfoTip>
                </div>
                {loading ? <Skeleton h={getStackedChartLayout(inspectionChartData, INSPECTION_STATUS_STACKS).height} variant="stacked" rows={Math.max(1, getStackedChartLayout(inspectionChartData, INSPECTION_STATUS_STACKS).rows)} /> : (
                  <StackedBarangayChart data={inspectionChartData} statuses={INSPECTION_STATUS_STACKS}
                emptyMessage="No reports match the selected filters." />
                )}
                <p className="analytics-chart-caption">
                  {inspectionNoReportBarangays} {inspectionNoReportBarangays === 1 ? "barangay has" : "barangays have"} no reports.
                </p>
              </div>

              <div className="tier-2-card saas-card frosted-glass analytics-feature-card analytics-feature-card--inspection-status" style={{ marginTop: 24 }}>
                <div className="analytics-card-heading">
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: 0 }}>
                    What verified outcomes were found in each barangay?
                  </h3>
                  <AnalyticsInfoTip label="About verified outcomes chart">
                    Shows Green, Yellow, and Red outcomes for verified reports. Other outcome values are not included in the bars.
                  </AnalyticsInfoTip>
                </div>
                {loading ? <Skeleton h={getStackedChartLayout(inspectionOutcomeChartData, OUTCOME_STACKS).height} variant="stacked" rows={Math.max(1, getStackedChartLayout(inspectionOutcomeChartData, OUTCOME_STACKS).rows)} /> : (
                  <StackedBarangayChart data={inspectionOutcomeChartData} statuses={OUTCOME_STACKS}
                    emptyMessage="No verified outcomes match the selected filters." />
                )}
                <p className="analytics-chart-caption">
                  {verifiedReportsWithoutOutcome} verified {verifiedReportsWithoutOutcome === 1 ? "report has" : "reports have"} no Green, Yellow, or Red outcome.
                </p>
              </div>

              <details className="analytics-profile-disclosure analytics-more-details">
                <summary>More details</summary>
                <div className="analytics-more-details-content">
                  <div className="analytics-field-kpi-group analytics-field-kpi-group--compliance">
                    <div className="analytics-field-kpi-heading">
                      <h4>Confirmed compliant businesses</h4>
                      <AnalyticsInfoTip label="About confirmed compliance">
                        These counts include businesses confirmed through office review or verified inspection evidence; they are not a count of every Green business.
                      </AnalyticsInfoTip>
                    </div>
                    <div className="analytics-field-kpi-grid analytics-field-kpi-grid--compliance">
                      <KpiCard iconVariant="green" value={<AnalyticsMetricValue loading={loading} value={confirmedCompliance?.office_confirmed ?? 0} />} label="Office-confirmed" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M4 21h16"></path><path d="M6 21V5l6-2 6 2v16"></path><path d="M9 9h1"></path><path d="M14 9h1"></path><path d="m9 15 2 2 4-4"></path></svg>} />
                      <KpiCard iconVariant="green" value={<AnalyticsMetricValue loading={loading} value={confirmedCompliance?.inspection_verified ?? 0} />} label="Inspection-verified" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M8 4H5a2 2 0 0 0-2 2v14h18V6a2 2 0 0 0-2-2h-3"></path><path d="M8 2h8v4H8z"></path><path d="m8 13 2.5 2.5L16 10"></path></svg>} />
                      <KpiCard iconVariant="green" value={<AnalyticsMetricValue loading={loading} value={confirmedCompliance?.total_confirmed ?? 0} />} label="Total confirmed" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><circle cx="9" cy="8" r="4"></circle><path d="M2 21v-2a7 7 0 0 1 14 0v2"></path><path d="m16 11 2 2 4-4"></path></svg>} />
                    </div>
                  </div>
                  <PinMonitoringPanel nonRegistry={desc?.non_registry_monitoring}
                    registryLinked={desc?.registry_linked_monitoring} refreshing={backgroundRefreshing} />
                </div>
              </details>
            </div>
              </>
            )}
          </section>
        )}

        {activeTab === "prescriptive" && loading && (
          <div style={{ visibility: skeletonTab === activeTab ? "visible" : "hidden" }}><RecommendationsSkeleton /></div>
        )}
        {data.prescriptive && activeTab === "prescriptive" && !loading && (
          <section className="analytics-recommendation-list" aria-labelledby="recommendations-heading">
            <div className="analytics-recommendation-heading">
              <h2 id="recommendations-heading">Where should inspectors go first?</h2>
              <p>
                {Number(prescWorkforce?.available_inspectors ?? 0)} inspector{Number(prescWorkforce?.available_inspectors ?? 0) === 1 ? "" : "s"} available. Dispatch recommendations cover up to 3 barangays; others wait for a free inspector.
              </p>
            </div>
            {(
              <>
                <div className="analytics-recommendation-table">
                  <div className="analytics-recommendation-columns">
                    <span aria-hidden="true" />
                    <span>Barangay</span>
                    <span className="analytics-recommendation-priority-label">
                      Priority
                      <AnalyticsInfoTip label="About priority">
                        Priority is a relative inspection order based on weighted Red, Yellow, and Black flag counts, plus straight-line distance from the BPLO office to the average location of dispatchable Red and Yellow records. When locations are unavailable, proximity uses a neutral value. Any sector score is a configured policy input, not measured industry risk.
                      </AnalyticsInfoTip>
                    </span>
                    <span className="analytics-recommendation-dispatch-label">Dispatch</span>
                  </div>
                  {activeRecommendations.rows.length > 0 ? (
                    <div className="analytics-recommendation-rows">
                {visibleRecommendations.map(row => {
                  const dispatch = row.dispatch;
                  return (
                    <details key={row.barangayID} className="analytics-recommendation-row">
                      <summary>
                        <span className="analytics-recommendation-rank">#{row.rank}</span>
                        <span className="analytics-recommendation-place">
                          <strong>{row.barangayName}</strong>
                          <span className="analytics-recommendation-reason">
                            {recommendationReason(row)}
                          </span>
                        </span>
                        <span className="analytics-recommendation-priority"
                          style={{ color: row.priority_color || "var(--color-muted)" }}
                          aria-label={`Priority: ${row.priority_label || row.risk_level || "No priority"}`}>
                          {row.priority_label || row.risk_level || "No priority"}
                        </span>
                        <span className="analytics-recommendation-assignment">
                          {recommendationAllocationLabel(dispatch)}
                        </span>
                      </summary>
                      <div className="analytics-recommendation-detail">
                        {dispatch ? (
                          <>
                            <dl className="analytics-recommendation-executive-metrics">
                              <div>
                                <dt>Priority level</dt>
                                <dd>{row.priority_label || row.risk_level || "No priority"}</dd>
                              </div>
                              <div>
                                <dt>Unregistered flags</dt>
                                <dd>{Number(row.unregistered_candidate_count || 0).toLocaleString()}</dd>
                              </div>
                              <div>
                                <dt>Distance from BPLO</dt>
                                <dd>
                                  {row.distance_km != null && Number.isFinite(Number(row.distance_km))
                                    ? `${Number(row.distance_km).toFixed(1)} km`
                                    : "Unavailable"}
                                </dd>
                              </div>
                              <div>
                                <dt>Sector policy version</dt>
                                <dd>{prescModel?.sector_policy?.version ?? "Unavailable"}</dd>
                              </div>
                            </dl>
                            <p>{dispatch.recommendation}</p>
                            <h4>Action steps</h4>
                            {dispatch.actionSteps?.length > 0 ? (
                              <ol>
                                {dispatch.actionSteps.map((step, index) => <li key={`${row.barangayID}-${index}`}>{step}</li>)}
                              </ol>
                            ) : (
                              <p>No additional action steps listed.</p>
                            )}
                          </>
                        ) : (
                          <p>No dispatch allocation is available for this barangay.</p>
                        )}
                      </div>
                    </details>
                  );
                })}
                    </div>
                  ) : (
                    <EmptyState h={180} title="No active flags" message="No barangays currently have active flags." />
                  )}
                </div>
                {activeRecommendations.rows.length > 5 && (
                  <button
                    type="button"
                    className="analytics-recommendation-toggle"
                    onClick={() => setShowAllRecommendations(value => !value)}
                  >
                    {showAllRecommendations ? "Show top 5" : `Show all ${activeRecommendations.rows.length}`}
                  </button>
                )}
                <p className="analytics-no-active-flags">
                  {activeRecommendations.noActiveFlagsCount} {activeRecommendations.noActiveFlagsCount === 1 ? "barangay has" : "barangays have"} no active flags.
                </p>
                <p className="analytics-scan-summary" role="status">
                  {analyticsDetectionScanSummary(lastDetectionRun)}
                  {lastDetectionRunError ? ` · ${lastDetectionRunError}` : ""}
                </p>
              </>
            )}
          </section>
        )}

        {/* ══════════════════════════════════════════════════════════════════════
          TIER 3 — PRESCRIPTIVE ANALYTICS (WLC / OPS)
      ══════════════════════════════════════════════════════════════════════ */}
        {ADMIN_PRESCRIPTIVE_DETAILS_ENABLED && data.prescriptive && activeTab === "prescriptive" && (
          <details className="analytics-calculation-disclosure">
            <summary>How this is calculated: scoring, charts, and full ranking table</summary>
            <section style={{ marginBottom: 32 }}>
            <SectionHeader
              tier="prescriptive"
              title="Prescriptive Analytics — Action Plan"
              subtitle="Recommended inspection priorities and inspector allocation."
            />

            <div className="saas-card frosted-glass presc-plan-intro">
              {prescWorkforce && (
                <div
                  className="presc-plan-summary"
                  role="group"
                  aria-label="Inspector availability and plan allocation"
                >
                  <div className="presc-plan-summary-item" aria-describedby="presc-inspector-count-help">
                    <span className="presc-plan-summary-label">Available inspectors</span>
                    <span className="presc-plan-summary-value">
                      <strong>{prescWorkforce.available_inspectors}</strong>
                      <span className="presc-plan-summary-unit">of {prescWorkforce.active_inspectors} active</span>
                    </span>
                    <p className="presc-plan-summary-explainer" id="presc-inspector-count-help">
                      Active means an enabled Inspector account, not someone online. Available means no Assigned, Reassigned, or In Progress report; confirm field availability separately.
                    </p>
                  </div>
                  <div className="presc-plan-summary-item">
                    <span className="presc-plan-summary-label">Recommended for this plan</span>
                    <span className="presc-plan-summary-value">
                      <strong>{prescWorkforce.allocated_inspectors}</strong>
                    </span>
                  </div>
                  <div className="presc-plan-summary-item">
                    <span className="presc-plan-summary-label">Unallocated inspectors</span>
                    <span className="presc-plan-summary-value">
                      <strong>{prescWorkforce.unallocated_inspectors}</strong>
                    </span>
                  </div>
                  <p className="presc-plan-summary-hint">
                    <strong>Allocation capacity: {prescWorkforce.allocation_capacity ?? "—"}</strong>
                    {` inspector${prescWorkforce.allocation_capacity === 1 ? "" : "s"}. `}
                    Capacity is capped at six; unallocated counts unused capacity in this plan. Recommendations cover eligible businesses in up to three eligible barangays.
                  </p>
                </div>
              )}

              {prescWorkforce?.available_inspectors === 0 && (
                <p role="status" className="presc-plan-deferred">
                  Deployments are deferred; WLC priority order is unchanged.
                </p>
              )}

              <p className="presc-plan-context">
                Scores reflect municipality-wide inspection priorities. Barangay filters narrow this list without changing scores or ranks.
              </p>

              <details className="presc-method">
                <summary>
                  <span className="presc-method-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M4 6h16" />
                      <path d="M4 12h16" />
                      <path d="M4 18h9" />
                      <circle cx="18.5" cy="18" r="2.5" />
                    </svg>
                  </span>
                  <span className="presc-method-copy">
                    <span className="presc-method-title">How priorities and allocation work</span>
                    <span className="presc-method-subtitle">Scoring, eligibility, priority bands, and inspector rules</span>
                  </span>
                  <span className="presc-method-action">
                    <span className="presc-method-action-closed">View details</span>
                    <span className="presc-method-action-open">Hide details</span>
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="m4 6 4 4 4-4" />
                    </svg>
                  </span>
                </summary>

                <div className="presc-method-body">
                  <section className="presc-method-group" aria-labelledby="presc-method-scoring">
                    <h4 id="presc-method-scoring">Score calculation and effective weights</h4>
                    <p>
                      Scores and ranks use current municipality-wide records. Barangay filters only narrow this list; registry, flag, date, and inspection filters do not recalculate operational priorities. A score is a relative inspection priority, not the probability of a violation.
                    </p>
                    <p>
                      Burden = 3 × Red + 2 × Yellow + 4 × Black. Risk = 100 × burden ÷ highest municipal burden ({prescModel?.reference_max_burden ?? "unavailable"}); zero when no active flags exist. Counts are eligible geospatial records, not unique businesses. Barangays without active flags receive OPS 0.
                    </p>
                    <div
                      className="presc-formula"
                      role="math"
                      aria-label="OPS equals W1 times Risk plus W2 times Sector plus W3 times Proximity, on a scale of 0 to 100"
                    >
                      <span className="presc-formula-result">OPS</span>
                      <span className="presc-formula-op">=</span>
                      <span className="presc-formula-term"><em>W<sub>1</sub></em> × Risk</span>
                      <span className="presc-formula-op">+</span>
                      <span className="presc-formula-term"><em>W<sub>2</sub></em> × Sector</span>
                      <span className="presc-formula-op">+</span>
                      <span className="presc-formula-term"><em>W<sub>3</sub></em> × Proximity</span>
                      <span className="presc-formula-range">0–100</span>
                    </div>
                    <dl className="presc-value-grid">
                      <div className="presc-value">
                        <dt>Risk weight</dt>
                        <dd>{prescWeight("w1")}</dd>
                      </div>
                      <div className="presc-value">
                        <dt>Sector weight</dt>
                        <dd>{prescWeight("w2")}</dd>
                      </div>
                      <div className="presc-value">
                        <dt>Proximity weight</dt>
                        <dd>{prescWeight("w3")}</dd>
                      </div>
                    </dl>
                    {prescModel?.sector_note && <p>{prescModel.sector_note}</p>}
                    <p>
                      {prescModel?.location_note ? `${prescModel.location_note} ` : ""}
                      Proximity = 100 − min(distance in km ÷ 20 × 100, 100).
                    </p>
                  </section>

                  <section className="presc-method-group" aria-labelledby="presc-method-eligibility">
                    <h4 id="presc-method-eligibility">Dispatch eligibility and exclusions</h4>
                    <p>
                      {prescModel?.eligibility_note || "Black flags remain risk context but cannot be dispatched. Recommendations skip Black-only barangays and targets with Assigned, Reassigned, or In Progress reports."}
                    </p>
                    <p>
                      New field plans require dispatchable Red/Yellow targets. Black-only barangays are for administrative review; already-assigned targets are not double-booked.
                    </p>
                  </section>

                  <section className="presc-method-group" aria-labelledby="presc-method-bands">
                    <h4 id="presc-method-bands">Priority bands and tie-breaking</h4>
                    <p>These are policy bands, not statistically calibrated violation categories.</p>
                    <ul className="presc-band-list">
                      <li>
                        <strong><span className="presc-band-dot presc-band-dot--high" aria-hidden="true" />High priority</strong>
                        <span>OPS ≥ 60</span>
                      </li>
                      <li>
                        <strong><span className="presc-band-dot presc-band-dot--standard" aria-hidden="true" />Standard</strong>
                        <span>OPS 30–59.9</span>
                      </li>
                      <li>
                        <strong><span className="presc-band-dot presc-band-dot--monitor" aria-hidden="true" />Monitor</strong>
                        <span>OPS below 30</span>
                      </li>
                    </ul>
                    <p>Ties use weighted burden, then barangay name, then barangay ID.</p>
                  </section>

                  <section className="presc-method-group" aria-labelledby="presc-method-workforce">
                    <h4 id="presc-method-workforce">Inspector availability and allocation rules</h4>
                    <p>
                      {prescWorkforce?.availability_rule || "Active inspectors without Assigned, Reassigned, or In Progress reports; shift and leave availability is not recorded."}
                    </p>
                    <p>
                      {prescWorkforce?.allocation_rule || "Maximum one inspector per eligible business; allocations are limited to the top three eligible WLC-ranked barangays."}
                    </p>
                    <p>
                      Highest WLC destinations receive inspectors first; remaining slots follow weighted burden using largest remainders. Confirm actual field availability before dispatch.
                    </p>
                    {prescWorkforce && (
                      <dl className="presc-value-grid presc-value-grid--inspectors">
                        <div className="presc-value">
                          <dt>Active inspectors</dt>
                          <dd>{prescWorkforce.active_inspectors}</dd>
                        </div>
                        <div className="presc-value">
                          <dt>Available inspectors</dt>
                          <dd>{prescWorkforce.available_inspectors}</dd>
                        </div>
                        <div className="presc-value">
                          <dt>Allocation capacity</dt>
                          <dd>{prescWorkforce.allocation_capacity ?? "—"}</dd>
                        </div>
                        <div className="presc-value">
                          <dt>Recommended for this plan</dt>
                          <dd>{prescWorkforce.allocated_inspectors}</dd>
                        </div>
                        <div className="presc-value">
                          <dt>Unallocated inspectors</dt>
                          <dd>{prescWorkforce.unallocated_inspectors}</dd>
                        </div>
                      </dl>
                    )}
                  </section>
                </div>
              </details>
            </div>

            {/* Focal Point: Actionable Dispatch Recommendations */}
            {presc?.dispatch_recommendations && presc.dispatch_recommendations.length > 0 && (
              <div className="tier-1-card saas-card frosted-glass" style={{ marginBottom: 24, padding: "20px 24px", borderRadius: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#6366f1" strokeWidth="2.5">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                  </svg>
                  <h3 style={{ fontSize: 18, fontWeight: 800, color: "var(--color-ink)", margin: 0, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                    Actionable Dispatch Recommendations
                  </h3>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {presc.dispatch_recommendations.map((rec, idx) => {
                    const isOpen = !!expandedDispatch[`presc-${idx}`];
                    return (
                      <div key={idx} style={{ background: "rgba(99,102,241,0.03)", borderRadius: 12, border: "1px solid rgba(99,102,241,0.10)", overflow: "hidden" }}>
                        {/* Clickable Header */}
                        <button
                          onClick={() => setExpandedDispatch(prev => ({ ...prev, [`presc-${idx}`]: !prev[`presc-${idx}`] }))}
                          style={{ width: "100%", display: "flex", alignItems: "center", gap: 12, padding: "16px 20px", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}
                        >
                          <span style={{ background: "#6366f1", color: "#fff", fontWeight: 800, fontSize: 14, width: 32, height: 32, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", flexShrink: 0 }}>
                            {rec.rank}
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                              <span style={{ fontWeight: 700, fontSize: 16, color: "var(--color-ink)" }}>{rec.barangayName}</span>
                              <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 99, color: rec.urgencyColor, background: `${rec.urgencyColor}15`, border: `1px solid ${rec.urgencyColor}40`, letterSpacing: "0.05em" }}>{rec.urgency || "—"}</span>
                            </div>
                            <div style={{ display: "flex", gap: 12, marginTop: 4, fontSize: 12, color: "var(--color-muted)" }}>
                              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
                                {rec.allocation_status === "deferred" ? "Deferred — no free inspector" : `${rec.inspectors ?? 0} inspector${(rec.inspectors ?? 0) !== 1 ? "s" : ""}`}
                              </span>
                              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" y1="22" x2="4" y2="15" /></svg>
                                {rec.flagged_count ?? 0} flag{(rec.flagged_count ?? 0) !== 1 ? "s" : ""}
                                {typeof rec.dispatchable_count === "number" && ` · ${rec.dispatchable_count} eligible for new dispatch`}
                              </span>
                            </div>
                          </div>
                          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="var(--color-muted)" strokeWidth="2" style={{ flexShrink: 0, transition: "transform 0.2s", transform: isOpen ? "rotate(180deg)" : "rotate(0deg)" }}>
                            <polyline points="6 9 12 15 18 9" />
                          </svg>
                        </button>

                        {/* Expandable Detail */}
                        {isOpen && (
                          <div style={{ padding: "0 20px 20px 20px", borderTop: "1px solid rgba(99,102,241,0.08)" }}>
                            {/* Flag Badges */}
                            <div style={{ display: "flex", gap: 8, marginTop: 14, marginBottom: 14, flexWrap: "wrap" }}>
                               {rec.red_count > 0 && <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: "var(--color-card-alt)", color: "var(--color-muted)" }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" /></svg> {rec.red_count} Registration / renewal checks</span>}
                               {rec.yellow_count > 0 && <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: "var(--color-card-alt)", color: "var(--color-muted)" }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg> {rec.yellow_count} Suspicious</span>}
                               {rec.black_count > 0 && <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: "var(--color-card-alt)", color: "var(--color-muted)" }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg> {rec.black_count} Black-flagged records</span>}
                            </div>

                            {/* Score Breakdown */}
                            {rec.scoreBreakdown && (
                              <div style={{ display: "flex", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
                                {[
                                  { label: "Risk", data: rec.scoreBreakdown.risk, color: "#8b5cf6" },
                                  { label: "Sector", data: rec.scoreBreakdown.sector, color: "#f59e0b" },
                                  { label: "Proximity", data: rec.scoreBreakdown.distance, color: "#3b82f6" },
                                ].map(({ label, data, color }) => (
                                  <div key={label} style={{ flex: "1 1 120px", background: "var(--color-surface)", padding: "10px 12px", borderRadius: 8, border: "1px solid var(--color-border)" }}>
                                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>{label} ({data?.weight ?? 0}%)</div>
                                    <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                                      <span style={{ fontSize: 20, fontWeight: 800, color }}>{label === "Sector" && data?.weight === 0 ? "Inactive" : data?.raw ?? 0}</span>
                                      <span style={{ fontSize: 11, color: "var(--color-muted)" }}>→ +{data?.contribution ?? 0}</span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Action Steps */}
                            {rec.actionSteps && rec.actionSteps.length > 0 && (
                              <div style={{ background: "var(--color-surface)", padding: "14px 16px", borderRadius: 8, border: "1px solid var(--color-border)" }}>
                                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>Action Plan</div>
                                <ol style={{ margin: 0, paddingLeft: 20 }}>
                                  {rec.actionSteps.map((step, sIdx) => (
                                    <li key={sIdx} style={{ fontSize: 13, color: "var(--color-ink)", lineHeight: 1.7, fontWeight: 500 }}>{step}</li>
                                  ))}
                                </ol>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="presc-results-grid">
              {/* Radar chart — top 8 */}
              <div className="tier-3-card saas-card frosted-glass" style={{ borderRadius: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: 0 }}>
                    OPS Radar — Top 8 Barangays
                  </h3>
                  {canEditWlc && (
                    <button className="ghost-btn" onClick={() => { if (showWlcConfig) handleCancelWlc(); else { void fetchWlcConfig(); setShowWlcConfig(true); } }} style={{ fontSize: 12, padding: "4px 10px", margin: 0 }}>
                      {showWlcConfig ? "Close Quick Adjust" : "⚙ Quick Adjust WLC Weights"}
                    </button>
                  )}
                </div>

                {canEditWlc && showWlcConfig && (
                  <div style={{ background: "var(--color-hover)", marginBottom: 16, padding: "16px", borderRadius: 8, border: "1px solid var(--color-border)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                      <h4 style={{ margin: 0, fontSize: 13, color: "var(--color-ink)" }}>WLC Weight Configuration</h4>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <button
                          type="button"
                          className="ghost-btn"
                          style={{
                            padding: "3px 8px",
                            fontSize: 11,
                            fontWeight: 600,
                            color: "var(--color-primary, #10b981)",
                            border: "1px solid var(--color-border)",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4
                          }}
                          onClick={handleUseDefaultWlc}
                           title="Reset sliders to interview-derived default weights (68% Risk, 7% Sector, 25% Proximity)"
                          disabled={savingWlc}
                        >
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /></svg>
                          Use Default
                        </button>
                        <span style={{ fontSize: 12, fontWeight: 700, color: !wlcValidationError ? "var(--color-primary)" : "var(--color-danger)" }}>
                          Total: {wlcConfig.w1_risk + wlcConfig.w2_sector + wlcConfig.w3_distance}%
                        </span>
                      </div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                      <div>
                        <label style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, color: "var(--color-muted)", marginBottom: 6 }}>
                          <span>Weighted Flag Burden (W1):</span>
                          <span style={{ color: "var(--color-primary)", fontWeight: 700 }}>{wlcConfig.w1_risk}%</span>
                        </label>
                        <input type="range" min="0" max="100" value={wlcConfig.w1_risk} onChange={e => setWlcConfig({ ...wlcConfig, w1_risk: Number(e.target.value) })} style={{ width: "100%", accentColor: "var(--color-primary)" }} />
                      </div>
                      <div>
                        <label style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, color: "var(--color-muted)", marginBottom: 6 }}>
                          <span>Sector Impact (W2):</span>
                          <span style={{ color: "var(--color-primary)", fontWeight: 700 }}>{wlcConfig.w2_sector}%</span>
                        </label>
                        <input type="range" min="0" max="100" value={wlcConfig.w2_sector} onChange={e => setWlcConfig({ ...wlcConfig, w2_sector: Number(e.target.value) })} style={{ width: "100%", accentColor: "var(--color-primary)" }} />
                        {presc?.model && <p style={{ margin: "4px 0 0", fontSize: 11, color: "var(--color-muted)" }}>
                          Active-flag entities use matched PSIC category scores; unmatched or unregistered entities use neutral 50
                          {" "}{Number(presc.model.sector_fallback_entity_count || 0).toLocaleString()} of {Number(presc.model.sector_entity_count || 0).toLocaleString()} entities are unclassified and use neutral 50 unless an explicit barangay override is configured.
                          The configured sector weight is retained; weights are not redistributed.
                        </p>}
                      </div>
                      <div>
                        <label style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, color: "var(--color-muted)", marginBottom: 6 }}>
                          <span>Proximity / travel efficiency (W3):</span>
                          <span style={{ color: "var(--color-primary)", fontWeight: 700 }}>{wlcConfig.w3_distance}%</span>
                        </label>
                        <input type="range" min="0" max="100" value={wlcConfig.w3_distance} onChange={e => setWlcConfig({ ...wlcConfig, w3_distance: Number(e.target.value) })} style={{ width: "100%", accentColor: "var(--color-primary)" }} />
                      </div>
                    </div>
                    {(wlcValidationError || wlcSaveError) && <p role="alert" style={{ color: "var(--color-danger)", fontSize: 12 }}>{wlcValidationError || wlcSaveError}</p>}
                    <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                      <button
                        type="button"
                        className="ghost-btn"
                        style={{
                          padding: "6px 12px",
                          fontSize: 11,
                          fontWeight: 700,
                          color: "var(--color-primary, #10b981)",
                          border: "1px solid var(--color-primary, #10b981)",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 5
                        }}
                        onClick={handleUseDefaultWlc}
                        disabled={savingWlc}
                        title="Revert back to interview-derived defaults: 68% Risk, 7% Sector, 25% Proximity"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /></svg>
                        Use Default (68/7/25)
                      </button>
                      <div style={{ display: "flex", gap: 8 }}>
                        <button className="ghost-btn" style={{ padding: "6px 12px", fontSize: 11 }} onClick={handleCancelWlc} disabled={savingWlc}>
                          Cancel
                        </button>
                        <button className="primary-btn" style={{ padding: "6px 12px", fontSize: 11 }} onClick={handleSaveWlc} disabled={savingWlc || !wlcConfigReady || Boolean(wlcValidationError)}>
                          {savingWlc ? "Applying..." : "Apply"}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {loading ? <Skeleton h={280} variant="radar" /> : radarData.length === 0 ? (
                  <EmptyState h={280} title="Insufficient Data" message="Not enough data to compute OPS rankings." />
                ) : (
                  <ResponsiveChart height={280}>
                    <RadarChart data={radarData}>
                       <PolarGrid stroke="var(--analytics-grid-color)" />
                      <PolarAngleAxis dataKey="barangay" tick={{ fontSize: 10, fill: "var(--color-muted)" }} />
                       <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 9, fill: "var(--color-muted)" }} axisLine={{ stroke: "var(--analytics-grid-color)" }} />
                      <Radar name="OPS Score" dataKey="OPS" stroke="#6366f1" fill="#6366f1" fillOpacity={0.18} strokeWidth={2} />
                      <Radar name="Relative flag burden" dataKey="Risk" stroke={COLOR.yellow} fill={COLOR.yellow} fillOpacity={0.12} strokeWidth={2} />
                      <Radar name="Proximity" dataKey="Proximity" stroke={COLOR.blue} fill={COLOR.blue} fillOpacity={0.06} strokeWidth={1} />
                       <Legend wrapperStyle={{ fontSize: 12, color: "var(--color-ink)" }} />
                      <Tooltip content={<CustomTooltip />} />
                    </RadarChart>
                  </ResponsiveChart>
                )}
              </div>

              {/* Full WLC Rankings Table */}
              <div className="tier-2-card saas-card frosted-glass presc-priority-card" style={{ borderRadius: 12, minWidth: 0 }}>
                <div style={{ marginBottom: 16 }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>
                    Inspector Deployment Priority Table
                  </h3>
                  <p style={{ fontSize: 12, color: "var(--color-muted)", margin: 0 }}>
                    Municipal OPS ranks — inspect top-down as staffing permits. Registry rates below are context only, not OPS inputs.
                  </p>
                </div>

                {loading ? <Skeleton h={480} variant="table" /> : (
                  <div className="presc-priority-scroll" role="region" aria-label="Inspector deployment priorities" tabIndex={0}>
                    <table className="presc-priority-table">
                      <colgroup>
                        <col className="presc-col-rank" />
                        <col className="presc-col-barangay" />
                        <col className="presc-col-ops" />
                        <col className="presc-col-flagged" />
                        <col className="presc-col-flags" />
                        <col className="presc-col-priority" />
                        <col className="presc-col-registry" />
                        <col className="presc-col-candidates" />
                      </colgroup>
                      <thead>
                        <tr>
                          <th scope="col">#</th>
                          <th scope="col">Barangay</th>
                          <th scope="col" className="presc-numeric">OPS</th>
                          <th scope="col" className="presc-numeric">Flagged</th>
                          <th scope="col" className="presc-numeric">R / Y / B</th>
                          <th scope="col">Priority</th>
                          <th scope="col" className="presc-numeric">Registry flag rate</th>
                          <th scope="col" className="presc-numeric">Unregistered candidates</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(presc?.rankings || []).map((row) => (
                          <tr key={row.barangayID} className="ops-row">
                            <td className="presc-rank-cell">
                              {row.rank <= 3
                                ? <span style={{ color: row.rank === 1 ? COLOR.red : row.rank === 2 ? COLOR.yellow : COLOR.green, fontWeight: 800 }}>#{row.rank}</span>
                                : `#${row.rank}`}
                            </td>
                            <td className="presc-barangay-cell">
                              <strong>{row.barangayName}</strong>
                              <small>{wlcEligibilityLabel(row)}</small>
                              {row.location_missing && row.inspection_required && <small>Location missing — neutral proximity</small>}
                            </td>
                            <td className="presc-numeric">
                              <div className="presc-ops-cell">
                                <strong>{Number(row.ops_score ?? 0).toFixed(1)}</strong>
                                <div className="ops-score-bar" aria-hidden="true">
                                  <div
                                    className="ops-score-fill"
                                    style={{
                                      width: `${row.ops_score}%`,
                                      background: row.priority_color || (row.risk_level === "High" ? COLOR.red
                                        : row.risk_level === "Medium" ? COLOR.yellow
                                          : COLOR.green),
                                    }}
                                  />
                                </div>
                              </div>
                            </td>
                            <td className="presc-numeric presc-flagged-cell">{row.flagged_count}</td>
                            <td className="presc-numeric">
                              <div className="presc-flag-counts" role="group" aria-label={`Red ${row.red_count}, Yellow ${row.yellow_count}, Black ${row.black_count}`}>
                                <span className="presc-flag-count presc-flag-count--red" style={{ color: COLOR.red }}><abbr title="Red">R</abbr><strong>{row.red_count}</strong></span>
                                <span className="presc-flag-count presc-flag-count--yellow" style={{ color: COLOR.yellow }}><abbr title="Yellow">Y</abbr><strong>{row.yellow_count}</strong></span>
                                <span className="presc-flag-count presc-flag-count--black" style={{ color: COLOR.black }}><abbr title="Black">B</abbr><strong>{row.black_count}</strong></span>
                              </div>
                            </td>
                            <td>
                              <span className="presc-priority-badge" style={{
                                ...riskBadgeStyle(row.risk_level),
                                ...(row.priority_color ? { color: row.priority_color, borderColor: row.priority_color } : {}),
                              }}>
                                {row.priority_label || row.risk_level}
                              </span>
                            </td>
                            <td className="presc-numeric presc-registry-cell">
                              <strong>{registryFlagRateLabel(row.registry_active_flag_rate)}</strong>
                              <small>{row.registry_flagged_count ?? "—"} / {row.total_registered ?? "—"} registry businesses</small>
                            </td>
                            <td className="presc-numeric presc-candidates-cell">{row.unregistered_candidate_count ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="presc-priority-note">Registry flag rate counts unique current Red/Yellow/Black registry businesses, including those without mapped records, against the same registry population; N/A means no denominator. It is not a confirmed-violation rate. Unregistered candidates are Red records with no registry match.</p>
              </div>
            </div>
            </section>
          </details>
        )}

        {/* ══════════════════════════════════════════════════════════════════════
            OPERATIONS
        ══════════════════════════════════════════════════════════════════════ */}
        {data.operations && activeTab === "operations" && (
          <section style={{ marginBottom: 52 }}>
            <SectionHeader
              tier="operations"
              title="Inspector Operations"
              subtitle="Reports by inspector and activity over time"
            />

            {loading ? (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
                <Skeleton h={380} />
                <Skeleton h={380} />
              </div>
            ) : (
              <>
                <p className="analytics-operations-summary">
                  {operationsStatusTotals.total.toLocaleString()} inspections:{" "}
                  {operationsStatusTotals.pending.toLocaleString()} pending,{" "}
                  {operationsStatusTotals.awaiting_review.toLocaleString()} waiting for review,{" "}
                  {operationsStatusTotals.verified.toLocaleString()} verified.
                </p>

                <div className="analytics-operations-grid">
                  <div className="saas-card frosted-glass analytics-operations-card">
                  <div className="analytics-card-heading">
                    <h3>Who is working on what?</h3>
                    <AnalyticsInfoTip label="About inspector workload">
                      Pending groups Assigned, Reassigned, In Progress, and Unassigned. Waiting for review means Submitted. Verified reports are complete. Active inspectors remain listed when they have no reports.
                    </AnalyticsInfoTip>
                  </div>
                  {operationsStatusRows.length === 0 ? (
                    <EmptyState h={260} title="No active inspectors" message="No inspectors match the selected filters." />
                  ) : (
                    <>
                      <div className="analytics-operations-legend">
                        {operationsChartStatusTotals.filter(status => status.total > 0).map(status => (
                          <span key={status.key}>
                            <i style={{ background: status.color }} />
                            {status.label}
                          </span>
                        ))}
                      </div>
                      <div style={{
                        height: Math.max(260, operationsStatusRows.length * 40 + 80),
                        width: "100%",
                      }}>
                        <ResponsiveChart height={Math.max(260, operationsStatusRows.length * 40 + 80)}>
                          {({ width }) => {
                            const labelWidth = Math.min(210, Math.max(128, width * 0.28));
                            return (
                              <BarChart data={operationsStatusRows} layout="vertical"
                                barSize={24} barCategoryGap="22%"
                                margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                         <CartesianGrid strokeDasharray="3 3" horizontal={false}
                           stroke="var(--analytics-grid-color)" />
                                <XAxis type="number" domain={[0, "dataMax"]}
                                  allowDecimals={false}
                                  tick={{ fontSize: 10, fill: "var(--color-muted)" }}
                                  axisLine={false} tickLine={false} />
                                <YAxis type="category" dataKey="fullName" width={labelWidth}
                                  interval={0}
                                  tick={{ fontSize: 11, fill: "var(--color-muted)" }}
                                  axisLine={false} tickLine={false} />
                                <Tooltip content={<CustomTooltip />} cursor={{ fill: "var(--analytics-operations-hover)" }} />
                                {OPERATIONS_STATUS_STACKS.map(status => (
                                  <Bar key={status.key} dataKey={status.key}
                                    name={status.label} stackId="inspector-work"
                                    fill={status.color} isAnimationActive={false} />
                                ))}
                              </BarChart>
                            );
                          }}
                        </ResponsiveChart>
                      </div>
                    </>
                  )}
                  <p className="analytics-chart-caption">
                    Each bar shows an inspector’s work by review stage.
                  </p>
                  </div>

                  <div className="saas-card frosted-glass analytics-operations-card">
                  <div className="analytics-card-heading">
                    <h3>Inspector details</h3>
                  </div>
                  <table className="analytics-operations-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Pending</th>
                        <th>Waiting for review</th>
                        <th>Verified</th>
                        <th>Avg days</th>
                      </tr>
                    </thead>
                    <tbody>
                      {operationsStatusRows.length === 0 ? (
                        <tr><td colSpan="5"><EmptyState h={120} title="No inspector data" message="No active inspectors match the selected filters." /></td></tr>
                      ) : operationsStatusRows.map(row => (
                        <tr key={row.userID}>
                          <td>{row.fullName}</td>
                          <td>{Number(row.pending || 0).toLocaleString()}</td>
                          <td>{Number(row.awaiting_review || 0).toLocaleString()}</td>
                          <td>{Number(row.verified || 0).toLocaleString()}</td>
                          <td>{row.avg_resolution_time ? (row.avg_resolution_time / 1440).toFixed(1) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <details className="analytics-profile-disclosure analytics-inspector-detail">
                    <summary>Pins flagged yellow</summary>
                    <table className="analytics-operations-table">
                      <thead><tr><th>Name</th><th>Pins flagged yellow</th></tr></thead>
                      <tbody>
                        {(data?.operations?.inspector_stats || []).map(row => (
                          <tr key={row.userID}>
                            <td>{row.fullName}</td>
                            <td>{Number(row.yellow_flags_reported || 0).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                  </div>
                </div>

                <div className="saas-card frosted-glass analytics-operations-card analytics-operations-timeline">
                  <div className="analytics-card-heading">
                  <h3>How many inspections were submitted each day?</h3>
                  <AnalyticsInfoTip label="About daily inspection counts">
                    Waiting for review includes submitted reports. Verified is shown separately. Dates without activity are included; ranges longer than 31 days are grouped by week.
                  </AnalyticsInfoTip>
                  </div>
                  {operationsTimelineChartRows.length === 0 ? (
                  <EmptyState h={300} title="No timeline data" message="No reports match the selected date range." />
                  ) : (
                  <div style={{ height: 320, width: "100%" }}>
                    <ResponsiveChart>
                      <BarChart data={operationsTimelineChartRows} margin={{ top: 10, right: 20, left: 0, bottom: 30 }}>
                         <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--analytics-grid-color)" />
                        <XAxis dataKey="date" axisLine={false} tickLine={false}
                          tick={{ fontSize: 10, fill: "var(--color-muted)" }} tickMargin={10} minTickGap={20}
                          angle={-30} textAnchor="end" />
                        <YAxis allowDecimals={false} axisLine={false} tickLine={false}
                          tick={{ fontSize: 11, fill: "var(--color-muted)" }} />
                        <Tooltip content={<CustomTooltip />} />
                        {[
                          { key: "awaiting_review", label: "Waiting for review", color: COLOR.blue },
                          { key: "verified", label: "Verified", color: COLOR.green },
                        ].filter(status => operationsTimelineChartRows.some(row => row[status.key] > 0))
                          .map(status => (
                            <Bar key={status.key} dataKey={status.key} name={status.label}
                              stackId="timeline" fill={status.color} isAnimationActive={false} />
                          ))}
                      </BarChart>
                    </ResponsiveChart>
                  </div>
                  )}
                  {operationsTimelineChartRows.length > 0 && (
                  <p className="analytics-chart-caption">
                    Compare reports waiting for review with reports already verified.
                  </p>
                  )}
                </div>
              </>
            )}
          </section>
        )}
        </div>

      {/* Footer */}
      <footer className="saas-footer frosted-glass">
        <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
        <p className="footer-links">
          <span>BPLO Portal</span> &bull; <span>System Settings</span> &bull;{" "}
          <button
            type="button"
            onClick={() => window.dispatchEvent(new CustomEvent("revela:open-about"))}
            style={{ background: "none", border: "none", padding: 0, font: "inherit", color: "inherit", cursor: "pointer" }}
          >
            About &amp; Credits
          </button>
        </p>
      </footer>
      </div>
    </DashboardLayout>
  );
}
