import { useState, useEffect, useCallback, useMemo, useRef, memo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis, LabelList, AreaChart, Area,
  ScatterChart, Scatter, ZAxis, ReferenceLine
} from "recharts";
import DashboardLayout from "../components/DashboardLayout";
import KpiCard from "../components/KpiCard";
import { useAuth } from "../context/AuthContext";
import {
  getWlcConfigRequest,
  updateWlcConfigRequest,
  getAnalyticsOverviewRequest,
  getAnalyticsFilterMetadataRequest,
  getBarangaysRequest,
  sendAnalyticsChatRequest,
} from "../services/api";

// ── Palette — matches REVELA's premium styling ────────────────────────────────
const COLOR = {
  green: "#10b981", // elegant emerald
  red: "#f43f5e", // elegant rose
  yellow: "#fbbf24", // elegant amber
  black: "#64748b", // slate gray for "closed/nonconforming" instead of blinding white
  blue: "#3b82f6",
  muted: "var(--color-muted)",
  orange: "#f97316",
  purple: "#7c3aed",
  slate: "#64748b",
  greenLight: "rgba(16, 185, 129, 0.15)",
  redLight: "rgba(244, 63, 94, 0.15)",
  yellowLight: "rgba(251, 191, 36, 0.15)",
  blueLight: "rgba(59, 130, 246, 0.15)",
};

const FLAG_COLORS = {
  Green: COLOR.green,
  Red: COLOR.red,
  Yellow: COLOR.yellow,
  Black: COLOR.slate,
  Orange: COLOR.orange,
  Purple: COLOR.purple,
};

// ── Tiny helpers ──────────────────────────────────────────────────────────────
const shortBarangay = (name = "") =>
  name.replace("Barangay ", "Brgy. ").replace("San Sebastian", "San Seb.");

const riskBadgeStyle = (level) => ({
  High: { background: COLOR.redLight, color: COLOR.red, border: `1px solid ${COLOR.red}` },
  Medium: { background: COLOR.yellowLight, color: "#b45309", border: "1px solid #f59e0b" },
  Low: { background: COLOR.greenLight, color: "#166534", border: `1px solid ${COLOR.green}` },
}[level] || {});

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
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
    diagnostic: { bg: COLOR.yellowLight, color: "#b45309", label: "Diagnostic" },
    prescriptive: { bg: "rgba(99,102,241,0.1)", color: "#6366f1", label: "Prescriptive" },
    operations: { bg: COLOR.blueLight, color: COLOR.blue, label: "Operations" },
  }[tier];
  return (
    <div style={{ marginBottom: 24, paddingBottom: 16, borderBottom: "1px solid rgba(226,232,240,0.6)" }}>
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
const Skeleton = ({ h = 200 }) => (
  <div style={{
    height: h, borderRadius: 12,
    background: "linear-gradient(90deg, rgba(226,232,240,0.5) 25%, rgba(241,245,249,0.5) 50%, rgba(226,232,240,0.5) 75%)",
    backgroundSize: "200% 100%",
    animation: "shimmer 1.5s infinite",
  }} />
);

// ── Empty State ──────────────────────────────────────────────────────────────
const EmptyState = ({ title = "No Data", message = "", h = 220, icon }) => (
  <div style={{
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


const createEmptyFilters = () => ({
  barangay_ids: [],
  application_status: "",
  line_of_business: "",
  business_type: "",
  business_size: "",
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
const InsightGenerator = {
  flagsByColor: (data) => {
    if (!data || data.length === 0) return "No flag data is currently available for the selected filters.";
    const total = data.reduce((sum, item) => sum + item.value, 0);
    if (total === 0) return "There are zero recorded entities matching this criteria.";

    const cleared = data.find(d => d.name.includes("Cleared"))?.value || 0;
    const unregistered = data.find(d => d.name.includes("Unregistered"))?.value || 0;

    const clearedPct = Math.round((cleared / total) * 100);
    const unregPct = Math.round((unregistered / total) * 100);

    if (unregPct > 30) {
      return `It looks like a significant chunk (${unregPct}%) of entities here are suspected to be unregistered. This is a major red flag—you should prioritize dispatching inspection teams to verify these businesses immediately.`;
    } else if (clearedPct > 80) {
      return `Great news! A massive ${clearedPct}% of the businesses here are fully cleared and active. Compliance in this segment is very healthy.`;
    } else {
      return `Currently, ${clearedPct}% of businesses are cleared, while ${unregPct}% are suspected unregistered. The rest are in intermediate warning states. Keep a close eye on the warning flags before they turn into full violations.`;
    }
  },

  timeline: (data) => {
    if (!data || data.length < 2) return "Not enough historical data to spot a trend yet.";
    const first = data[0];
    const last = data[data.length - 1];

    const activeDiff = last.active - first.active;
    if (activeDiff > 0) {
      return `Over this period, active business renewals have trended upwards, gaining ${activeDiff} new compliant entities. This means our enforcement and outreach are working!`;
    } else if (activeDiff < 0) {
      return `Warning: We've seen a drop of ${Math.abs(activeDiff)} active businesses over this timeframe. We might be looking at businesses shutting down or failing to renew. Consider a targeted renewal campaign.`;
    } else {
      return `Active business counts have remained completely flat over this period.`;
    }
  },

  leaderboard: (data) => {
    if (!data || data.length === 0) return "No barangay data available.";
    const worst = [...data].sort((a, b) => {
      if (a.rate !== b.rate) return a.rate - b.rate;
      return b.totalFlags - a.totalFlags;
    })[0];
    const best = [...data].sort((a, b) => {
      if (a.rate !== b.rate) return b.rate - a.rate;
      return (b.totalEntities || b.totalFlags) - (a.totalEntities || a.totalFlags);
    })[0];

    if (worst.rate < 70) {
      return `Right now, ${worst.barangayName} is struggling the most, sitting at a low ${worst.rate}% compliance rate with ${worst.totalFlags} active flags. I highly recommend focusing your next enforcement sweep there.`;
    }
    return `${best.barangayName} is leading the pack with an impressive ${best.rate}% compliance rate, while ${worst.barangayName} is trailing at ${worst.rate}%. Overall, the distribution looks relatively stable.`;
  },

  funnel: (data) => {
    if (!data || data.length < 2) return "Not enough funnel data.";
    const total = data.find(d => d.step === "Total Non-Compliant")?.value || 0;
    const cleared = data.find(d => d.step === "Compliant (Cleared)")?.value || 0;
    const conversion = total > 0 ? Math.round((cleared / total) * 100) : 0;

    if (conversion < 10) {
      return `We're seeing a very low end-to-end clearance rate of just ${conversion}%. This means the vast majority of non-compliant entities are getting stuck somewhere in the audit process or ignoring warnings. We need to streamline field inspections.`;
    }
    return `About ${conversion}% of all non-compliant entities successfully make it through to full clearance.`;
  },

  sectoral: (data) => {
    if (!data || data.length === 0) return "No sector data available.";
    const top = data[0];
    const total = data.reduce((sum, item) => sum + item.value, 0);
    const pct = Math.round((top.value / total) * 100);

    if (pct > 40) {
      return `The "${top.name}" sector is absolutely dominating this segment, making up ${pct}% of all records. Any policy changes here will have a massive ripple effect on the entire ecosystem.`;
    }
    return `The largest sector here is "${top.name}", but the distribution is fairly spread out across multiple industries, meaning risk isn't concentrated in just one area.`;
  },

  geographic: (data) => {
    if (!data || data.length === 0) return "No geographic spread data available.";
    const total = data.reduce((sum, item) => sum + Object.values(item).reduce((acc, val) => typeof val === 'number' ? acc + val : acc, 0), 0);
    return `This chart shows the distribution of ${total} businesses across different barangays, broken down by sector. The AI can help identify specific concentrations of industries in certain areas.`;
  },

  categoryRisk: (data) => {
    if (!data || data.length === 0) return "No category risk data available.";
    const top = data[0];
    return `The "${top.name}" sector currently has the highest number of flags (${top.count}). This indicates a sector-specific risk pattern that may require targeted enforcement or policy review.`;
  },

  businessSize: (data) => {
    if (!data || data.length === 0) return "No size data available.";
    const micro = data.find(d => d.name === "Micro")?.value || 0;
    const total = data.reduce((sum, item) => sum + item.value, 0);
    const microPct = Math.round((micro / total) * 100);

    if (microPct > 75) {
      return `As expected, Micro-sized businesses make up the overwhelming majority (${microPct}%). When designing compliance programs for this group, ensure the fees and paperwork aren't too burdensome for tiny operations.`;
    }
    return `While Micro businesses are present, there is a healthy mix of Small and Medium enterprises here, which generally indicates a maturing local economy.`;
  },

  businessType: (data) => {
    if (!data || data.length === 0) return "No business type data available.";
    const top = data[0];
    const total = data.reduce((sum, item) => sum + item.value, 0);
    const topPct = Math.round((top.value / total) * 100);

    if (top.name === "Single Proprietorship" && topPct > 80) {
      return `The local economy is heavily reliant on Single Proprietorships (${topPct}%). This typically points to a localized, informal economy. Compliance messaging should be simple and direct.`;
    }
    if (top.name === "Corporation") {
      return `Corporations make up the largest block of businesses here (${topPct}%). This indicates a highly formalized economy with more complex tax and compliance requirements.`;
    }
    return `The most common legal structure is ${top.name} (${topPct}%).`;
  },

  complianceBySize: (data) => {
    if (!data || data.length === 0) return "No compliance by size data available.";
    let highestNonCompliantPct = 0;
    let worstSize = "None";

    data.forEach(d => {
      const total = d.Active + d["Non-Active"];
      if (total > 0) {
        const ncPct = (d["Non-Active"] / total) * 100;
        if (ncPct > highestNonCompliantPct) {
          highestNonCompliantPct = ncPct;
          worstSize = d.name;
        }
      }
    });

    if (highestNonCompliantPct > 30) {
      return `Warning: The "${worstSize}" segment has the highest rate of non-compliance at ${Math.round(highestNonCompliantPct)}%. Consider launching targeted amnesty or simplified registration programs specifically for this demographic.`;
    }
    return `Compliance rates are generally stable across all business sizes, with no single segment showing extremely critical non-compliance rates.`;
  },

  renewalSeasonality: (data) => {
    if (!data || data.length === 0) return "No seasonality data available.";
    const totalRenewals = data.reduce((sum, item) => sum + item.Active + item["Non-Active"], 0);
    let peakMonth = data[0];
    let peakVolume = peakMonth.Active + peakMonth["Non-Active"];

    data.forEach(d => {
      const vol = d.Active + d["Non-Active"];
      if (vol > peakVolume) {
        peakVolume = vol;
        peakMonth = d;
      }
    });

    const peakPct = Math.round((peakVolume / totalRenewals) * 100);
    if (peakPct > 40) {
      return `There is a massive seasonal spike around ${peakMonth.month}, accounting for ${peakPct}% of all activity. Ensure inspection and processing teams are fully staffed during this window.`;
    }
    return `Business activity is relatively distributed over the year, peaking moderately in ${peakMonth.month}.`;
  },

  inspectorPerformance: (data) => {
    if (!data || data.length === 0) return "No inspector data available.";
    const topPerformer = [...data].sort((a, b) => b.total_completed - a.total_completed)[0];
    if (topPerformer && topPerformer.total_completed > 0) {
      return `Inspector ${topPerformer.fullName} is leading with ${topPerformer.total_completed} completed inspections. Keep up the momentum!`;
    }
    return "No completed inspections yet in the selected criteria.";
  },

  redFlagTrend: (data) => {
    if (!data || data.length < 2) return "Not enough data to determine a trend.";
    const first = data[0]["New Red Flags"];
    const last = data[data.length - 1]["New Red Flags"];
    const diff = last - first;

    if (diff > 0) {
      return `Red flag emergence is trending upwards, with an increase of ${diff} cases compared to the start of the period. This indicates a growing compliance risk that requires attention.`;
    } else if (diff < 0) {
      return `Good news: new red flags are trending downwards, dropping by ${Math.abs(diff)} cases. Our enforcement actions seem to be deterring critical violations.`;
    } else {
      return `The emergence of new red flags has remained stable over this period, with no significant spikes or drops detected.`;
    }
  },

  inspectionStatus: (data) => {
    if (!data || data.length === 0) return "No inspection status data available.";
    const total = data.reduce((sum, item) => sum + item.count, 0);
    const pending = data.filter(d => ['Assigned', 'In Progress', 'Reassigned', 'Unassigned'].includes(d.status)).reduce((sum, item) => sum + item.count, 0);
    const pendingPct = total > 0 ? Math.round((pending / total) * 100) : 0;

    if (pendingPct > 50) {
      return `A high number of inspections (${pendingPct}%) are currently pending (assigned, reassigned, or in progress). Operations might be backlogging. Consider re-evaluating the current dispatch load.`;
    }
    return `Operations are flowing steadily. Only ${pendingPct}% of current assignments are still pending.`;
  },

  opsTimeline: (data) => {
    if (!data || data.length === 0) return "Not enough operations timeline data available.";
    const total = data.reduce((sum, item) => sum + item.count, 0);
    return `Over this period, a total of ${total} inspections were recorded. Look for any spikes in activity that correspond with recent dispatch operations.`;
  },

  auditBreakdown: (data) => {
    if (!data || data.length === 0) return "No audit outcome data available.";
    const total = data.reduce((sum, item) => sum + item.value, 0);
    const green = data.find(d => d.name === "Green")?.value || 0;
    const red = data.find(d => d.name === "Red")?.value || 0;

    if (total === 0) return "No inspections have been recorded yet.";

    const greenPct = Math.round((green / total) * 100);
    const redPct = Math.round((red / total) * 100);

    if (redPct > 30) {
      return `Warning: ${redPct}% of verified inspections are resulting in a Red flag (severe non-compliance). This highlights a critical need for targeted enforcement and follow-up.`;
    } else if (greenPct > 70) {
      return `Positive outcome: ${greenPct}% of businesses inspected are receiving Green flags, showing strong compliance among those audited.`;
    }
    return `Inspections yield a mix of outcomes, with ${greenPct}% Green and ${redPct}% Red. The varied results indicate enforcement is uncovering both compliant and non-compliant operations effectively.`;
  }
};

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
         <div key={`table-${elements.length}`} style={{ overflowX: "auto", margin: "10px 0", borderRadius: 8, border: "1px solid var(--color-border)" }}>
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
  const [isExpanded, setIsExpanded] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const { token } = useAuth();
  const chatScrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (isExpanded && messages.length === 0) {
      setMessages([{ role: "model", content: "I am the REVELA AI Analyst. I have reviewed all the data currently visible on your dashboard. What would you like to know?" }]);
    }
    if (isExpanded && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 300);
    }
  }, [isExpanded, messages.length]);

  useEffect(() => {
    if (chatScrollRef.current) {
      const el = chatScrollRef.current;
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages, loading]);

  const handleSend = async (e, forcedInput = null) => {
    e?.preventDefault();
    const textToSend = forcedInput !== null ? forcedInput : input;
    if (!textToSend.trim() || loading) return;

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
      setLoading(false);
    }
  };

  return (
    <div style={{ position: "fixed", bottom: 32, right: 32, zIndex: 9999, display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
      <style>{`
        @keyframes aiChatSlideIn {
          from { opacity: 0; transform: translateY(20px) scale(0.95); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes aiBubbleFadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes aiTypingDot {
          0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
          30% { opacity: 1; transform: translateY(-4px); }
        }
        @keyframes aiPulseGlow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0.4); }
          50% { box-shadow: 0 0 0 10px rgba(16,185,129,0); }
        }
        .ai-chat-input:focus {
          border-color: var(--color-primary) !important;
          box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 15%, transparent) !important;
        }
        .ai-send-btn:hover:not(:disabled) {
          filter: brightness(1.1);
          transform: scale(1.03);
        }
        .ai-fab:hover {
          transform: scale(1.05);
        }
      `}</style>

      {!isExpanded && (
        <button
          onClick={() => setIsExpanded(true)}
          className="ai-fab"
          style={{
            width: 110, height: 110, border: "none", background: "transparent",
            cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
            transition: "transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
            padding: 0, overflow: "visible", position: "relative"
          }}
        >
          <img src="/standing.png" alt="AI Analyst" style={{ width: "100%", height: "100%", objectFit: "contain", filter: "drop-shadow(0 0 2px rgba(255,255,255,0.9)) drop-shadow(0 10px 15px rgba(0,0,0,0.2))" }} />
          <div style={{
            position: "absolute", bottom: 0, right: 0, width: 28, height: 28,
            background: "var(--color-primary)", borderRadius: "50%",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#fff", boxShadow: "0 4px 12px rgba(0,0,0,0.3)", fontSize: 14,
            animation: "aiPulseGlow 3s ease-in-out infinite"
          }}>✦</div>
        </button>
      )}

      {isExpanded && (
        <div style={{
          borderRadius: 20,
          background: "var(--color-surface)",
          border: "1px solid color-mix(in srgb, var(--color-primary) 20%, transparent)",
          boxShadow: "0 12px 48px rgba(0,0,0,0.15), 0 4px 16px rgba(0,0,0,0.08)",
          display: "flex", flexDirection: "column",
          width: 380, height: 500, overflow: "hidden",
          animation: "aiChatSlideIn 0.3s cubic-bezier(0.4, 0, 0.2, 1) forwards",
          transformOrigin: "bottom right"
        }}>
          {/* Header */}
          <div style={{
            padding: "16px 20px", display: "flex", alignItems: "center", justifyContent: "space-between",
            borderBottom: "1px solid var(--color-border)",
            background: "color-mix(in srgb, var(--color-primary) 5%, var(--color-surface))",
            flexShrink: 0
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{
                width: 40, height: 40, borderRadius: "50%",
                background: "linear-gradient(135deg, var(--color-surface), #f1f5f9)",
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
            <button 
              onClick={() => setIsExpanded(false)} 
              style={{ 
                background: "transparent", border: "none", cursor: "pointer", 
                color: "var(--color-muted)", padding: 4, borderRadius: "50%",
                display: "flex", alignItems: "center", justifyContent: "center"
              }}
              onMouseEnter={e => e.currentTarget.style.background = "var(--color-border)"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div ref={chatScrollRef} style={{
            padding: "20px 20px", overflowY: "auto", display: "flex",
            flexDirection: "column", gap: 12, flexGrow: 1
          }}>
            {messages.map((m, i) => (
              <div key={i} style={{
                alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                animation: "aiBubbleFadeIn 0.35s cubic-bezier(0.4, 0, 0.2, 1) forwards",
                animationDelay: `${i * 0.05}s`,
                opacity: 0,
                maxWidth: "85%",
              }}>
                <div style={{
                  background: m.role === "user"
                    ? "linear-gradient(135deg, var(--color-primary), var(--color-primary-dark))"
                    : "color-mix(in srgb, var(--color-primary) 6%, var(--color-card-alt))",
                  color: m.role === "user" ? "#022c22" : "var(--color-ink)",
                  padding: "12px 16px", borderRadius: 16,
                  borderBottomRightRadius: m.role === "user" ? 4 : 16,
                  borderBottomLeftRadius: m.role === "model" ? 4 : 16,
                  fontSize: 13, lineHeight: 1.6,
                  border: m.role === "model" ? "1px solid var(--color-border)" : "none",
                  boxShadow: m.role === "user"
                    ? "0 4px 12px rgba(16,185,129,0.2)"
                    : "0 2px 6px rgba(0,0,0,0.04)"
                }}>
                  <div style={{ fontSize: 10, fontWeight: 700, marginBottom: 4, opacity: 0.6, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    {m.role === "user" ? "You" : "AI Analyst"}
                  </div>
                  <div style={{ whiteSpace: "pre-wrap" }}>{m.role === "model" ? renderMarkdown(m.content) : m.content}</div>
                </div>
              </div>
            ))}
            {loading && (
              <div style={{
                alignSelf: "flex-start", padding: "14px 20px",
                background: "color-mix(in srgb, var(--color-primary) 6%, var(--color-card-alt))",
                borderRadius: 16, borderBottomLeftRadius: 4,
                border: "1px solid var(--color-border)",
                display: "flex", alignItems: "center", gap: 6,
                animation: "aiBubbleFadeIn 0.3s ease forwards"
              }}>
                {[0, 1, 2].map(n => (
                  <div key={n} style={{
                    width: 8, height: 8, borderRadius: "50%",
                    background: "var(--color-primary)",
                    animation: `aiTypingDot 1.2s ease-in-out ${n * 0.15}s infinite`
                  }} />
                ))}
              </div>
            )}
          </div>

          {/* Predefined Questions */}
          {messages.length === 1 && !loading && (
            <div style={{
              display: "flex", gap: 8, padding: "0 20px 14px", flexWrap: "wrap",
              background: "var(--color-surface)"
            }}>
              {[
                "What are the main takeaways?",
                "Are there any anomalies?",
                "How does this compare to expected trends?"
              ].map((q, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSend(null, q)}
                  type="button"
                  style={{
                    padding: "8px 14px", borderRadius: 16, border: "1px solid var(--color-border)",
                    background: "var(--color-card-alt)", color: "var(--color-ink)",
                    fontSize: 12, cursor: "pointer", transition: "all 0.2s ease",
                    fontWeight: 500
                  }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--color-primary)"; e.currentTarget.style.color = "var(--color-primary)"; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--color-border)"; e.currentTarget.style.color = "var(--color-ink)"; }}
                >
                  {q}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <form onSubmit={handleSend} style={{
            display: "flex", gap: 10,
            borderTop: "1px solid var(--color-border)",
            padding: "16px 20px",
            background: "var(--color-surface)",
            flexShrink: 0
          }}>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Ask me anything about this data..."
              className="ai-chat-input"
              style={{
                flexGrow: 1, padding: "10px 16px", border: "1.5px solid var(--color-border)",
                borderRadius: 24, fontSize: 13, outline: "none",
                background: "var(--color-card-alt)",
                color: "var(--color-ink)", fontFamily: "var(--font-base)",
                transition: "all 0.2s ease"
              }}
              disabled={loading}
            />
            <button
              type="submit"
              className="ai-send-btn"
              disabled={loading || !input.trim()}
              style={{
                padding: "10px 20px", borderRadius: 24, border: "none",
                background: input.trim() && !loading
                  ? "linear-gradient(135deg, var(--color-primary), var(--color-primary-dark))"
                  : "var(--color-border)",
                color: input.trim() && !loading ? "#022c22" : "var(--color-muted)", fontWeight: 600, fontSize: 13,
                cursor: input.trim() && !loading ? "pointer" : "not-allowed",
                transition: "all 0.2s ease", flexShrink: 0,
                display: "flex", alignItems: "center", gap: 6
              }}
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
  const { token } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState("descriptive"); // descriptive, diagnostic, prescriptive
  const [isScrolled, setIsScrolled] = useState(false);

  const tabMarkerRef = useRef(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        setIsScrolled(!entry.isIntersecting && entry.boundingClientRect.top < 300);
      },
      { threshold: 0, rootMargin: "0px 0px 0px 0px" }
    );
    if (tabMarkerRef.current) {
      observer.observe(tabMarkerRef.current);
    }
    return () => observer.disconnect();
  }, []);
  const [wlcConfig, setWlcConfig] = useState({ w1_risk: 68, w2_sector: 7, w3_distance: 25 });
  const [showWlcConfig, setShowWlcConfig] = useState(false);
  const [savingWlc, setSavingWlc] = useState(false);
  const [expandedDispatch, setExpandedDispatch] = useState({});
  const [draftFilters, setDraftFilters] = useState(createEmptyFilters);
  const [appliedFilters, setAppliedFilters] = useState(createEmptyFilters);
  const [showFilters, setShowFilters] = useState(false);
  const [openSections, setOpenSections] = useState({ location: false, business: false, flags: false, inspection: false });
  const [brgySearchTerm, setBrgySearchTerm] = useState("");
  const [brgyDropdownOpen, setBrgyDropdownOpen] = useState(false);
  const brgyDropdownRef = useRef(null);

  const [filterMeta, setFilterMeta] = useState(null);
  const [barangaysList, setBarangaysList] = useState([]);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchAnalytics = useCallback(async (isSilent = false) => {
    if (!token) return;

    if (!isSilent) {
      setLoading(true);
      setIsRefreshing(true);
    }
    setError(null);
    try {
      const json = await getAnalyticsOverviewRequest(token, appliedFilters);
      setData(json);
    } catch (e) {
      if (!isSilent) {
        setError(e.message);
      }
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, [token, appliedFilters]);

  const fetchWlcConfig = useCallback(async () => {
    if (!token) return;

    try {
      const res = await getWlcConfigRequest(token);
      if (res) {
        setWlcConfig({ w1_risk: res.w1_risk ?? 68, w2_sector: res.w2_sector ?? 7, w3_distance: res.w3_distance ?? 25 });
      }
    } catch (e) {
      console.error(e);
    }
  }, [token]);

  const handleSaveWlc = async () => {
    setSavingWlc(true);
    try {
      await updateWlcConfigRequest(wlcConfig, token);
      await fetchAnalytics(false);
      setShowWlcConfig(false);
    } catch (e) {
      console.error(e);
    } finally {
      setSavingWlc(false);
    }
  };

  const handleCancelWlc = () => {
    fetchWlcConfig();
    setShowWlcConfig(false);
  };

  useEffect(() => {
    fetchAnalytics(false);
    fetchWlcConfig();
  }, [fetchAnalytics, fetchWlcConfig]);

  // Real-time event listeners and auto-polling
  useEffect(() => {
    const handleSync = () => {
      fetchAnalytics(true);
    };

    window.addEventListener("revela:inspection-update", handleSync);
    window.addEventListener("revela:yellow-flag", handleSync);
    window.addEventListener("revela:flag-update", handleSync);
    window.addEventListener("revela:registry-update", handleSync);
    window.addEventListener("revela:user-update", handleSync);
    window.addEventListener("revela:global-refresh", handleSync);

    const pollTimer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchAnalytics(true);
      }
    }, 30000);

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        fetchAnalytics(true);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleVisibility);

    return () => {
      window.removeEventListener("revela:inspection-update", handleSync);
      window.removeEventListener("revela:yellow-flag", handleSync);
      window.removeEventListener("revela:flag-update", handleSync);
      window.removeEventListener("revela:registry-update", handleSync);
      window.removeEventListener("revela:user-update", handleSync);
      window.removeEventListener("revela:global-refresh", handleSync);
      window.clearInterval(pollTimer);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleVisibility);
    };
  }, [fetchAnalytics]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const [meta, brgy] = await Promise.all([
          getAnalyticsFilterMetadataRequest(token),
          getBarangaysRequest(token),
        ]);
        if (!cancelled) {
          setFilterMeta(meta);
          setBarangaysList(Array.isArray(brgy) ? brgy : (Array.isArray(brgy?.data) ? brgy.data : []));
        }
      } catch (e) {
        console.error(e);
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  // ── Derived shorthand references ──────────────────────────────────────────
  const desc = data?.descriptive;
  const diag = data?.diagnostic;
  const presc = data?.prescriptive;
  const kpis = desc?.kpis;





  // ── Sectoral distribution pie ─────────────────────────────────────────────
  const SECTOR_COLORS = [
    "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
    "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#06b6d4",
  ];
  const sectoralData = (desc?.sectoral_distribution || []).map((r) => ({
    name: r.sector,
    value: r.count,
  }));

  // ── Business size pie ─────────────────────────────────────────────────────
  const SIZE_COLORS = ["#8b5cf6", "#3b82f6", "#10b981", "#f59e0b", "#ef4444"];
  const sizeData = (desc?.business_size_dist || []).map((r, i) => ({
    name: r.size_label,
    value: r.count,
    fill: SIZE_COLORS[i % SIZE_COLORS.length],
  }));

  // ── Business type pie ─────────────────────────────────────────────────────
  const TYPE_COLORS = ["#14b8a6", "#f97316", "#ec4899", "#8b5cf6", "#3b82f6"];
  const typeData = (desc?.business_type_dist || []).map((r, i) => ({
    name: r.type_label,
    value: r.count,
    fill: TYPE_COLORS[i % TYPE_COLORS.length],
  }));

  // ── Compliance by size bar ────────────────────────────────────────────────
  const complianceBySizeData = (desc?.compliance_by_size || []).map((r) => ({
    name: r.size_label,
    Active: Number(r.active_count || 0),
    "Non-Active": Number(r.inactive_count || 0),
  }));

  const worstComplianceSize = useMemo(() => {
    if (!complianceBySizeData || complianceBySizeData.length === 0) return null;
    let highestPct = 0;
    let worst = null;
    complianceBySizeData.forEach(d => {
      const total = d.Active + d["Non-Active"];
      if (total > 0) {
        const pct = d["Non-Active"] / total;
        if (pct > highestPct) {
          highestPct = pct;
          worst = { name: d.name, pct: (pct * 100).toFixed(1) };
        }
      }
    });
    return worst;
  }, [complianceBySizeData]);

  // ── Compliance timeline ───────────────────────────────────────────────────
  const timelineData = (desc?.compliance_timeline || []).map(r => ({
    month: r.month,
    Active: r.active_count || 0,
    "Non-Active": r.non_active_count || 0,
  }));

  // ── Enforcement progress chart data ──────────────────────────────────────
  const naturePerBarangayData = desc?.nature_per_barangay || [];
  const natureKeys = useMemo(() => {
    const keys = new Set();
    naturePerBarangayData.forEach(row => {
      Object.keys(row).forEach(k => {
        if (k !== 'barangayName') keys.add(k);
      });
    });
    return Array.from(keys);
  }, [naturePerBarangayData]);

  // ── Audit result breakdown ────────────────────────────────────────────────
  const auditData = (desc?.audit_summary?.result_breakdown || []).map(r => ({
    name: r.inspectionResult,
    value: r.count,
    fill: FLAG_COLORS[r.inspectionResult] || COLOR.muted,
  }));


  // ── Diagnostic: category non-compliance horizontal bar ───────────────────
  // flagged_count = unique flagged entities per line of business (backend joins
  // detections to the registry with a normalized name match). 'Unclassified' is
  // excluded here since it is not a real line of business.
  const categoryData = (diag?.category_noncompliance || [])
    .filter(r => !r.category.toLowerCase().includes("unclassified"))
    .map(r => ({
      name: r.category,
      count: r.flagged_count,
    }));

  // ── Diagnostic: weekly flag trend line ───────────────────────────────────
  const trendData = (diag?.flag_trend || []).map(r => ({
    week: r.week_start?.slice(5) ?? r.week_start, // MM-DD
    "New Red Flags": r.new_red_flags || 0,
  }));

  // ── Prescriptive: WLC radar (top 8) ──────────────────────────────────────
  const radarData = (presc?.rankings || []).slice(0, 8).map(r => ({
    barangay: shortBarangay(r.barangayName),
    OPS: r.ops_score,
    "Non-Compliance %": Math.min(r.non_compliance_rate, 100),
    "Red Flags": Math.min((r.red_count / Math.max(...(presc?.rankings || []).map(x => x.red_count), 1)) * 100, 100),
  }));

  const auditBreakdown = desc?.audit_summary?.result_breakdown || [];
  const inspectedCount = auditBreakdown.reduce((sum, r) => sum + r.count, 0);
  const clearedCount = auditBreakdown.find(r => r.inspectionResult === 'Green' || r.inspectionResult === 'Compliant')?.count || 0;

  const dispatchedCount = useMemo(() => {
    const breakdown = data?.operations?.status_breakdown || [];
    return breakdown.reduce((sum, r) => {
      if (['Assigned', 'Reassigned', 'In Progress'].includes(r.status)) {
        return sum + Number(r.count || 0);
      }
      return sum;
    }, 0);
  }, [data?.operations?.status_breakdown]);

  const flagCounts = useMemo(() => {
    const progress = desc?.enforcement_progress || [];
    let green = 0, red = 0, yellow = 0, black = 0, orange = 0, purple = 0;
    progress.forEach(row => {
      green += row.green_count || 0;
      red += row.red_count || 0;
      yellow += row.yellow_count || 0;
      black += row.black_count || 0;
      orange += row.orange_count || 0;
      purple += row.purple_count || 0;
    });
    return { green, red, yellow, black, orange, purple, total: green + red + yellow + black + orange + purple };
  }, [desc?.enforcement_progress]);

  const funnelData = [
    { step: "Total Flags", value: flagCounts.total, color: "var(--color-ink)" },
    { step: "Total Non-Compliant", value: flagCounts.red + flagCounts.yellow + flagCounts.orange + flagCounts.black, color: "#f43f5e" },
    { step: "Total Inspected", value: inspectedCount, color: "#8b5cf6" },
    { step: "Compliant (Cleared)", value: clearedCount, color: "#10b981" },
  ];


  const leaderboardData = useMemo(() => {
    const progress = desc?.enforcement_progress;
    if (!progress) return [];
    return progress.map(row => {
      const g = row.green_count || 0;
      const r = row.red_count || 0;
      const y = row.yellow_count || 0;
      const b = row.black_count || 0;
      const o = row.orange_count || 0;
      const totalEntities = g + r + y + b + o;
      const totalFlags = r + y + b + o;
      const rate = totalEntities > 0 ? Math.round((g / totalEntities) * 100) : 100;
      return {
        barangayName: row.barangayName,
        shortName: shortBarangay(row.barangayName),
        activeCount: g,
        totalEntities,
        totalFlags,
        rate,
        g, y, o, r, b
      };
    });
  }, [desc?.enforcement_progress]);


  const activeFilterCount = countActiveBackendFilters(data?.applied_filters);

  const handleApplyFilters = () => {
    setAppliedFilters({
      ...draftFilters,
      barangay_ids: [...draftFilters.barangay_ids],
    });
  };

  const handleClearFilters = () => {
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
        if (b) chips.push({ key: `brgy-${id}`, label: b.barangayName, clear: () => setAppliedFilters((p) => ({ ...p, barangay_ids: p.barangay_ids.filter((x) => x !== id) })) });
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
      if (af[k]) chips.push({ key: k, label: `${lbl}: ${af[k]}`, clear: () => setAppliedFilters((p) => ({ ...p, [k]: "" })) });
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
  const globalData = useMemo(() => ({
    geographic: data?.descriptive?.nature_per_barangay || [],
    sectoral: data?.descriptive?.sectoral_distribution || [],
    size: data?.descriptive?.business_size_dist || [],
    legalStructure: data?.descriptive?.business_type_dist || [],
    complianceBySize: data?.descriptive?.compliance_by_size || [],
    complianceTimeline: data?.descriptive?.compliance_timeline || [],
    enforcement: data?.descriptive?.enforcement_progress || [],
    audit: data?.descriptive?.audit_summary || {},
    kpis: data?.descriptive?.kpis || {},
    barangayRisk: data?.diagnostic?.barangay_risk_data || [],
    categoryNoncompliance: data?.diagnostic?.category_noncompliance || [],
    flagTrend: data?.diagnostic?.flag_trend || [],
    // Prescriptive tier
    opsRankings: data?.prescriptive?.rankings || [],
    wlcConfig: data?.prescriptive?.wlc_config || {},
    dispatchRecommendations: data?.prescriptive?.dispatch_recommendations || [],
    // Operations tier
    inspectorStats: data?.operations?.inspector_stats || [],
    statusBreakdown: data?.operations?.status_breakdown || [],
    inspectionTimeline: data?.operations?.inspection_timeline || [],
  }), [data]);

  return (
    <DashboardLayout>
      <GlobalAIAssistant globalData={globalData} />
      <style>{`
        /* shimmer keyframe now defined globally in global.css */
        .saas-card { position: relative; }
        .saas-card:focus-within, .saas-card:hover { z-index: 50; }
        
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

        .sticky-tabs {
          position: sticky;
          top: 0;
          z-index: 100;
          background: var(--color-surface);
          padding: 16px 0;
          margin-bottom: 24px;
          border-bottom: 1px solid var(--color-border);
        }

        .analytics-tab-btn {
          padding: 8px 18px;
          border-radius: 8px;
          border: 1px solid var(--color-border);
          background: var(--color-input-bg);
          color: var(--color-muted);
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          transition: all var(--duration-fast);
        }
        .analytics-tab-btn.active {
          background: var(--color-ink);
          color: var(--color-surface);
          border-color: var(--color-ink);
        }
        .analytics-tab-btn:hover:not(.active) {
          background: var(--color-hover);
          color: var(--color-ink);
        }
        .ops-row:hover { background: "var(--color-modal-bg)" !important; }
        .ops-score-bar {
          height: 6px;
          border-radius: 3px;
          background: rgba(226,232,240,0.6);
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

      {/* PAGE WRAPPER */}
      <div style={{ width: "100%", minWidth: 0 }}>

        {/* PAGE HEADER */}
        <div style={{ marginBottom: 32, display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 className="page-title">System Analytics</h1>
            <p className="page-subtitle" style={{ color: "var(--color-muted)" }}>
              Descriptive · Diagnostic · Prescriptive — All 16 Barangays of Mataasnakahoy
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button
              className="quick-refresh-btn"
              type="button"
              onClick={() => fetchAnalytics(false)}
              disabled={isRefreshing}
              title="Refresh analytics data"
            >
              <svg
                className={isRefreshing ? "spin-icon" : ""}
                viewBox="0 0 24 24"
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19" />
              </svg>
              <span>{isRefreshing ? "Syncing…" : "Refresh"}</span>
            </button>
          </div>
        </div>

        {/* ANALYTICS FILTERS — redesigned: chips + accordion + sticky footer */}
        <div className="saas-card frosted-glass" style={{ marginBottom: 24, padding: "20px 22px", maxHeight: showFilters ? "85vh" : "auto", overflowY: showFilters ? "auto" : "visible" }}>
          {/* ── Header row: title + collapse toggle ── */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 14, marginBottom: showFilters ? 16 : 0 }}>
            <div
              style={{ cursor: "pointer", display: "flex", flexDirection: "column", flex: 1 }}
              onClick={() => setShowFilters(!showFilters)}
            >
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 8 }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>
                Data filters
                <span style={{ fontSize: 12, color: "var(--color-muted)", marginLeft: 4 }}>
                  {showFilters ? "▲" : "▼"}
                </span>
                {!showFilters && activeFilterCount > 0 && (
                  <span style={{ fontSize: 11, background: "rgba(16, 185, 129, 0.12)", color: "#10b981", padding: "2px 8px", borderRadius: 12, marginLeft: 8 }}>
                    {activeFilterCount} active
                  </span>
                )}
              </h3>
              {showFilters ? (
                <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--color-muted)", maxWidth: 720 }}>
                  Registry (status, sector, type, size, renewal window), geospatial flags (color, detection window),
                  and inspections (result, verification, timestamp window). Barangay selection limits spatial and joined aggregates.
                </p>
              ) : (
                <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--color-muted)" }}>
                  Click to expand and filter analytics data.
                </p>
              )}
            </div>
          </div>

          {/* ── Active filter chips (always visible when filters are set) ── */}
          {activeChips.length > 0 && (
            <div className="filter-chips-row" style={{ marginTop: showFilters ? 0 : 10, marginBottom: showFilters ? 12 : 0 }}>
              {activeChips.map((chip) => (
                <span key={chip.key} className="filter-chip">
                  {chip.label}
                  <button onClick={(e) => { e.stopPropagation(); chip.clear(); }} title="Remove filter">✕</button>
                </span>
              ))}
            </div>
          )}

          {showFilters && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

              {/* ── Primary Filters Row ────────────────────────────── */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
                gap: 16,
                padding: 16,
                border: "1px solid var(--color-border)",
                borderRadius: 12,
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
              <p style={{ margin: 0, fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Advanced Filters
              </p>

              {/* ── Advanced Section Accordions ────────────────────── */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 400px), 1fr))", gap: 12 }}>

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
                      {/* Custom multi-select dropdown */}
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

              {/* ── Sticky Apply / Clear Footer ─────────────────────── */}
              <div className="filter-sticky-footer">
                {activeFilterCount > 0 && (
                  <span style={{ fontSize: 12, fontWeight: 700, color: "#10b981", marginRight: "auto" }}>
                    {activeFilterCount} filter{activeFilterCount !== 1 ? "s" : ""} active
                  </span>
                )}
                <button className="ghost-btn" type="button" style={{ padding: "8px 16px", fontSize: 13 }} onClick={handleClearFilters}>
                  Clear all
                </button>
                <button className="primary-btn" type="button" style={{ padding: "8px 16px", fontSize: 13 }} onClick={handleApplyFilters}>
                  Apply filters
                </button>
              </div>

            </div>
          )}
        </div>

        {/* Scroll Marker */}
        <div ref={tabMarkerRef} style={{ width: "100%", height: 1, marginBottom: -1 }} />

        {/* MAIN TABS (Normal Flow) */}
        <div className="tier-1-card saas-card frosted-glass" style={{
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          flexDirection: "row",
          position: "relative",
          background: "var(--glass-bg)",
          backdropFilter: "var(--glass-blur)",
          WebkitBackdropFilter: "var(--glass-blur)",
          boxShadow: "none",
          padding: "24px",
          margin: "0 0 32px 0",
          borderRadius: 12,
          border: "1px solid var(--color-border)"
        }}>
          {[
            { id: "descriptive", label: "Descriptive", sub: "What is happening?", dot: "var(--color-green)" },
            { id: "diagnostic", label: "Diagnostic", sub: "Why is it happening?", dot: "var(--color-yellow)" },
            { id: "prescriptive", label: "Prescriptive", sub: "What should we do?", dot: "#6366f1" },
            { id: "operations", label: "Operations", sub: "Inspector performance", dot: "var(--color-blue, #3b82f6)" }
          ].map(tab => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                className={`analytics-tab-btn ${isActive ? "active" : ""}`}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  padding: "12px 20px",
                  borderRadius: 8,
                  border: "1px solid var(--color-border)",
                  background: isActive ? "var(--color-surface)" : "transparent",
                  cursor: "pointer",
                  minWidth: 160,
                  transition: "all 0.2s ease"
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 14, color: isActive ? "var(--color-primary-dark)" : "var(--color-muted)" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: tab.dot }} />
                  {tab.label}
                </div>
                <div style={{ fontSize: 12, color: "var(--color-muted)", marginTop: 4, marginLeft: 16 }}>{tab.sub}</div>
              </button>
            );
          })}
        </div>

        {/* FLOATING PILL (Shows when scrolled) */}
        <div style={{
          position: "fixed",
          bottom: 32,
          left: "50%",
          transform: `translateX(-50%) translateY(${isScrolled ? 0 : 20}px)`,
          opacity: isScrolled ? 1 : 0,
          pointerEvents: isScrolled ? "auto" : "none",
          zIndex: 999,
          display: "flex",
          flexDirection: "row",
          gap: 12,
          padding: "8px",
          borderRadius: 100,
          background: "var(--glass-bg-pill)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          boxShadow: "0 20px 40px rgba(0, 0, 0, 0.15)",
          border: "1px solid rgba(255, 255, 255, 0.1)",
          transition: "transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.2s ease"
        }}>
          {[
            { id: "descriptive", label: "Descriptive", dot: "var(--color-green)" },
            { id: "diagnostic", label: "Diagnostic", dot: "var(--color-yellow)" },
            { id: "prescriptive", label: "Prescriptive", dot: "#6366f1" },
            { id: "operations", label: "Operations", dot: "var(--color-blue, #3b82f6)" }
          ].map(tab => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => {
                  setActiveTab(tab.id);
                  if (tabMarkerRef.current) {
                    tabMarkerRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
                  }
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  padding: "10px 20px",
                  borderRadius: 100,
                  border: "1px solid transparent",
                  background: isActive ? "var(--color-surface)" : "transparent",
                  cursor: "pointer",
                  transition: "all 0.2s ease"
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 13, color: isActive ? "var(--color-primary-dark)" : "var(--color-muted)" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: !isActive ? "var(--color-muted)" : tab.dot, opacity: (!isActive) ? 0.5 : 1 }} />
                  {tab.label}
                </div>
              </button>
            );
          })}
        </div>

        {error && (
          <div style={{
            background: COLOR.redLight, border: `1px solid ${COLOR.red}`, borderRadius: 10,
            padding: "14px 20px", marginBottom: 24, color: COLOR.red, fontWeight: 600, fontSize: 14,
          }}>
            ⚠ Failed to load analytics: {error}. Check that the backend is running.
          </div>
        )}

        {/* ══════════════════════════════════════════════════════════════════════
          OVERVIEW SUMMARY
      ══════════════════════════════════════════════════════════════════════ */}
        {activeTab === "descriptive" && (
          <section style={{ marginBottom: 52 }}>
            <SectionHeader
              tier="descriptive"
              title="Descriptive Analytics"
              subtitle="Current-state demographic profile and field inspection summaries"
            />

            {presc?.dispatch_recommendations && presc.dispatch_recommendations.length > 0 && (
              <div className="tier-1-card saas-card frosted-glass" style={{ marginBottom: 24, padding: "20px", borderRadius: 12 }}>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 12px 0", display: "flex", alignItems: "center", gap: 8 }}>
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: "#6366f1" }}>
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                  </svg>
                  Priority Dispatch Overview
                </h3>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {presc.dispatch_recommendations.slice(0, 3).map((rec, idx) => (
                    <div key={idx} style={{ background: "rgba(99,102,241,0.04)", padding: "14px 18px", borderRadius: 10, border: "1px solid rgba(99,102,241,0.12)", transition: "background 0.2s" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <span style={{ background: "#6366f1", color: "#fff", fontWeight: 800, fontSize: 13, width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", flexShrink: 0 }}>
                          {rec.rank}
                        </span>
                        <span style={{ fontWeight: 700, fontSize: 15, color: "var(--color-ink)", flex: 1 }}>{rec.barangayName}</span>
                        <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 99, color: rec.urgencyColor, background: `${rec.urgencyColor}15`, border: `1px solid ${rec.urgencyColor}40`, letterSpacing: "0.05em" }}>{rec.urgency || "—"}</span>
                        <span style={{ fontSize: 12, color: "var(--color-muted)", fontWeight: 600 }}>OPS {rec.ops_score ?? "—"}</span>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--color-muted)" }}>
                          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                            <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
                            {rec.inspectors ?? 0}
                          </span>
                          <span>&middot;</span>
                          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                            <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" y1="22" x2="4" y2="15" /></svg>
                            {rec.flagged_count ?? 0}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* SECTION A: Official Registry Demographics */}
            <div style={{ marginBottom: 40 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24, borderBottom: "2px solid rgba(226,232,240,0.6)", paddingBottom: 8 }}>
                <h3 style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>A. Official Registry Demographics</h3>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", padding: "4px 8px", background: "rgba(59, 130, 246, 0.1)", color: "var(--color-blue, #3b82f6)", borderRadius: 12 }}>
                  Data Source: BPLO Registry
                </span>
              </div>

              <h4 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 16px 0" }}>Business Census</h4>
              <div className="kpi-grid" style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))", gap: 10, marginBottom: 24 }}>
                <KpiCard iconVariant="gold" value={kpis?.total_businesses ?? "—"} label="Total Registered" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="green" value={kpis?.active_count ?? "—"} label="Active" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="red" value={kpis?.expired_count ?? "—"} label="Expired" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="gold" value={kpis?.pending_count ?? "—"} label="Pending" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="red" value={kpis?.closed_count ?? "—"} label="Closed" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="9" x2="15" y2="15"></line><line x1="15" y1="9" x2="9" y2="15"></line></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="red" value={kpis?.revoked_count ?? "—"} label="Revoked" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M21 4H8l-7 8 7 8h13a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"></path><line x1="18" y1="9" x2="12" y2="15"></line><line x1="12" y1="9" x2="18" y2="15"></line></svg>} style={{ padding: "12px 10px" }} />
              </div>

              {/* Business Demographic Profile */}
              <div style={{ marginBottom: 24 }}>
                <div style={{ display: "none" }}>
                  <h2 style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>
                    Business Demographic Profile
                  </h2>
                  <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", padding: "4px 8px", background: "rgba(59, 130, 246, 0.1)", color: "var(--color-blue, #3b82f6)", borderRadius: 12 }}>
                    Data Source: BPLO Registry
                  </span>
                </div>

                {/* Executive FAQs */}
                <div style={{ marginBottom: 32 }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 16px 0" }}>Quick Insights (FAQ)</h3>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}>

                    <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-blue)", minWidth: 0 }}>
                      <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>Most Common Legal Structure</p>
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

                    <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-red)", minWidth: 0 }}>
                      <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>Highest Compliance Risk</p>
                      <p style={{ fontSize: 14, color: "var(--color-ink)", margin: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {worstComplianceSize ? `${worstComplianceSize.name} Enterprises (${worstComplianceSize.pct}% non-compliant)` : "None (100% Compliant)"}
                      </p>
                    </div>

                    <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-orange)", minWidth: 0 }}>
                      <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>Overall Compliance Rate</p>
                      <p style={{ fontSize: 14, color: "var(--color-ink)", margin: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {kpis?.compliance_rate != null ? `${kpis.compliance_rate}% of registered businesses` : "N/A"}
                      </p>
                    </div>

                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(max(400px, calc(50% - 24px)), 1fr))", gap: 24 }}>
                  {/* Geographic & Sector Spread */}
                  <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, gridColumn: "1 / -1", display: "flex", flexDirection: "column" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                      <div>
                        <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Geographic & Sector Spread</h3>
                        <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>Business distribution across barangays by sector</p>
                      </div>
                      <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", padding: "4px 8px", background: "rgba(59, 130, 246, 0.1)", color: "var(--color-blue, #3b82f6)", borderRadius: 12 }}>Demographics</span>
                    </div>
                    {loading ? <Skeleton h={350} /> : naturePerBarangayData.length === 0 ? (
                      <EmptyState h={350} title="No Geographic Data" message="No data available for the selected filters." />
                    ) : (
                      <div style={{ flexGrow: 1, minHeight: 350, width: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={naturePerBarangayData.map(r => ({
                              barangayName: r.barangayName,
                              total: natureKeys.reduce((sum, key) => sum + (r[key] || 0), 0)
                            }))}
                            margin={{ top: 10, right: 10, left: -20, bottom: 60 }}
                          >
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226,232,240,0.4)" />
                            <XAxis dataKey="barangayName" tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} interval={0} angle={-45} textAnchor="end" />
                            <YAxis tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                            <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.15)", background: "var(--color-surface)", fontSize: 12 }} />
                            <Bar dataKey="total" name="Total Businesses" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>

                  {/* Top Sectors Overall */}
                  <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, display: "flex", flexDirection: "column" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                      <div>
                        <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Top Sectors</h3>
                        <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>Highest volume business lines</p>
                      </div>
                    </div>
                    {loading ? <Skeleton h={220} /> : sectoralData.length === 0 ? (
                      <EmptyState h={220} title="No Sector Data" />
                    ) : (
                      <div style={{ flexGrow: 1, minHeight: 220, width: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={sectoralData.slice(0, 5)} layout="vertical" margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="rgba(226,232,240,0.4)" />
                            <XAxis type="number" tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                            <YAxis dataKey="name" type="category" width={160} tickFormatter={(v) => v.length > 25 ? v.substring(0, 25) + '...' : v} tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                            <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.15)", background: "var(--color-surface)", fontSize: 12 }} />
                            <Bar dataKey="value" name="Businesses" radius={[0, 4, 4, 0]}>
                              {sectoralData.slice(0, 5).map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={SECTOR_COLORS[index % SECTOR_COLORS.length]} />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>

                  {/* Business Size Profile */}
                  <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, display: "flex", flexDirection: "column" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                      <div>
                        <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Business Size Profile</h3>
                        <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>Distribution by enterprise scale</p>
                      </div>
                    </div>
                    {loading ? <Skeleton h={220} /> : sizeData.length === 0 ? (
                      <EmptyState h={220} title="No Size Data" />
                    ) : (
                      <div style={{ flexGrow: 1, minHeight: 220, width: "100%", display: "flex", alignItems: "center" }}>
                        <ResponsiveContainer width="50%" height="100%">
                          <PieChart>
                            <Pie
                              data={sizeData}
                              dataKey="value"
                              nameKey="name"
                              cx="50%"
                              cy="50%"
                              innerRadius={65}
                              outerRadius={95}
                              paddingAngle={4}
                              isAnimationActive={false}
                            >
                              {sizeData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.fill} />
                              ))}
                            </Pie>
                            <Tooltip content={<CustomTooltip />} />
                          </PieChart>
                        </ResponsiveContainer>
                        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 10, flex: 1, paddingLeft: 20 }}>
                          {sizeData.map((s, i) => (
                            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                              <span style={{ width: 10, height: 10, borderRadius: "50%", background: s.fill, flexShrink: 0 }} />
                              <span style={{ color: "var(--color-muted)", flex: 1 }}>{s.name}</span>
                              <strong style={{ color: "var(--color-ink)" }}>{s.value}</strong>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Business Legal Structure */}
                  <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, display: "flex", flexDirection: "column" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                      <div>
                        <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Business Legal Structure</h3>
                        <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>Distribution by business type</p>
                      </div>
                    </div>
                    {loading ? <Skeleton h={220} /> : typeData.length === 0 ? (
                      <EmptyState h={220} title="No Type Data" />
                    ) : (
                      <div style={{ flexGrow: 1, minHeight: 220, width: "100%", display: "flex", alignItems: "center" }}>
                        <ResponsiveContainer width="50%" height="100%">
                          <PieChart>
                            <Pie
                              data={typeData}
                              dataKey="value"
                              nameKey="name"
                              cx="50%"
                              cy="50%"
                              innerRadius={65}
                              outerRadius={95}
                              paddingAngle={4}
                              isAnimationActive={false}
                            >
                              {typeData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.fill} />
                              ))}
                            </Pie>
                            <Tooltip content={<CustomTooltip />} />
                          </PieChart>
                        </ResponsiveContainer>
                        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 10, flex: 1, paddingLeft: 20 }}>
                          {typeData.map((s, i) => (
                            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                              <span style={{ width: 10, height: 10, borderRadius: "50%", background: s.fill, flexShrink: 0 }} />
                              <span style={{ color: "var(--color-muted)", flex: 1 }}>{s.name}</span>
                              <strong style={{ color: "var(--color-ink)" }}>{s.value}</strong>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Compliance by Business Size */}
                  <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, display: "flex", flexDirection: "column" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                      <div>
                        <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Compliance by Business Size</h3>
                        <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>Active vs Non-Active comparison</p>
                      </div>
                    </div>
                    {loading ? <Skeleton h={220} /> : complianceBySizeData.length === 0 ? (
                      <EmptyState h={220} title="No Compliance Data" />
                    ) : (
                      <div style={{ flexGrow: 1, minHeight: 220, width: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={complianceBySizeData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226,232,240,0.4)" />
                            <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                            <YAxis tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                            <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.15)", background: "var(--color-surface)", fontSize: 12 }} />
                            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 10 }} />
                            <Bar dataKey="Active" stackId="a" fill="#10b981" radius={[0, 0, 0, 0]} />
                            <Bar dataKey="Non-Active" stackId="a" fill="#ef4444" radius={[4, 4, 0, 0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>

                </div>
              </div>

              <div style={{ marginTop: 24 }}>
                <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12 }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Compliance Timeline (12 Months)</h3>
                  <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "0 0 16px 0" }}>The gap between active vs non-active renewals over time.</p>
                  <div style={{ height: 260 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={timelineData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                          <linearGradient id="colorActive" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id="colorNonActive" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.8} />
                            <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226,232,240,0.4)" />
                        <XAxis dataKey="month" tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <Tooltip content={<CustomTooltip />} />
                        <Legend iconType="circle" wrapperStyle={{ fontSize: 12, paddingTop: 10 }} />
                        <Area type="monotone" dataKey="Active" stroke="#10b981" fillOpacity={1} fill="url(#colorActive)" />
                        <Area type="monotone" dataKey="Non-Active" stroke="#f43f5e" fillOpacity={1} fill="url(#colorNonActive)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            </div>

            {/* SECTION B: Field Inspections Demographics */}
            <div style={{ marginBottom: 40 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24, borderBottom: "2px solid rgba(226,232,240,0.6)", paddingBottom: 8 }}>
                <h3 style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>B. Field Inspections Demographics</h3>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", padding: "4px 8px", background: "rgba(245, 158, 11, 0.1)", color: "var(--color-orange, #f59e0b)", borderRadius: 12 }}>
                  Data Source: Field Inspections
                </span>
              </div>

              <h4 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 16px 0" }}>Field & Inspection KPIs</h4>
              <div className="kpi-grid" style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 10, marginBottom: 24 }}>
                <KpiCard iconVariant="red" value={(flagCounts.red + flagCounts.yellow + flagCounts.orange + flagCounts.black) ?? "—"} label="Total Non-Compliant" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="orange" value={dispatchedCount ?? "—"} label="Dispatched" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M5 12h14"></path><path d="M12 5l7 7-7 7"></path></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="gold" value={inspectedCount ?? "—"} label="Total Inspected" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="green" value={clearedCount ?? "—"} label="Compliant (Cleared)" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>} style={{ padding: "12px 10px" }} />
                <KpiCard iconVariant="gold" value={`${inspectedCount > 0 ? Math.round((clearedCount / inspectedCount) * 100) : 0}%`} label="Clearance Rate" icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="20" height="20"><circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle></svg>} style={{ padding: "12px 10px" }} />
              </div>

              {/* Field Inspections FAQs */}
              <div style={{ marginBottom: 32 }}>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 16px 0" }}>Quick Insights (FAQ)</h3>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}>

                  <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-blue)", minWidth: 0 }}>
                    <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>Most Common Inspection Outcome</p>
                    <p style={{ fontSize: 14, color: "var(--color-ink)", margin: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {auditData.length > 0 ? `${[...auditData].sort((a, b) => b.value - a.value)[0].name} (${Math.round(([...auditData].sort((a, b) => b.value - a.value)[0].value / inspectedCount) * 100)}%)` : "N/A"}
                    </p>
                  </div>

                  <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-red)", minWidth: 0 }}>
                    <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>Lowest Compliance Barangay</p>
                    <p style={{ fontSize: 14, color: "var(--color-ink)", margin: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {leaderboardData.length > 0 ? `${[...leaderboardData].sort((a, b) => a.rate - b.rate)[0].shortName} (${[...leaderboardData].sort((a, b) => a.rate - b.rate)[0].rate}% compliant)` : "N/A"}
                    </p>
                  </div>

                  <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-orange)", minWidth: 0 }}>
                    <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>End-to-End Clearance Rate</p>
                    <p style={{ fontSize: 14, color: "var(--color-ink)", margin: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {funnelData[0]?.value > 0 ? `${Math.round((clearedCount / funnelData[0].value) * 100)}% of total detected` : "N/A"}
                    </p>
                  </div>

                  <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 12, borderLeft: "4px solid var(--color-green)", minWidth: 0 }}>
                    <p style={{ fontSize: 11, color: "var(--color-muted)", margin: "0 0 4px 0", fontWeight: 600, textTransform: "uppercase" }}>Highest Compliance Barangay</p>
                    <p style={{ fontSize: 14, color: "var(--color-ink)", margin: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {leaderboardData.length > 0 ? (() => {
                        const best = [...leaderboardData].sort((a, b) => {
                          if (a.rate !== b.rate) return b.rate - a.rate;
                          return b.totalEntities - a.totalEntities;
                        })[0];
                        return `${best.shortName} (${best.rate}% compliant)`;
                      })() : "N/A"}
                    </p>
                  </div>

                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", gap: 24, marginBottom: 24 }}>
                <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, display: "flex", flexDirection: "column" }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Barangay Compliance Leaderboard</h3>
                  <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "0 0 16px 0" }}>Ranked compliance rates based on registered vs flagged entities.</p>
                  <div style={{ flexGrow: 1, minHeight: 260, overflowY: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                      <thead style={{ position: "sticky", top: 0, background: "var(--color-surface)", zIndex: 10 }}>
                        <tr style={{ borderBottom: "2px solid rgba(226,232,240,0.6)", color: "var(--color-muted)", fontSize: 11, textTransform: "uppercase" }}>
                          <th style={{ padding: "8px", fontWeight: 700 }}>Barangay</th>
                          <th style={{ padding: "8px", fontWeight: 700 }}>Compliance Rate</th>
                          <th style={{ padding: "8px", fontWeight: 700 }}>Flags</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...leaderboardData].sort((a, b) => {
                          if (a.rate !== b.rate) return b.rate - a.rate;
                          return b.totalEntities - a.totalEntities;
                        }).map((row) => (
                          <tr key={row.barangayName} style={{ borderBottom: "1px solid rgba(226,232,240,0.35)" }}>
                            <td style={{ padding: "8px", fontWeight: 600, color: "var(--color-ink)", fontSize: 12 }}>{row.barangayName}</td>
                            <td style={{ padding: "8px" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <strong style={{ fontSize: 12, color: row.rate >= 80 ? COLOR.green : row.rate >= 60 ? COLOR.yellow : COLOR.red, minWidth: 32 }}>{row.rate}%</strong>
                                <div className="ops-score-bar" style={{ width: 60 }}>
                                  <div className="ops-score-fill" style={{ width: `${row.rate}%`, background: row.rate >= 80 ? COLOR.green : row.rate >= 60 ? COLOR.yellow : COLOR.red }} />
                                </div>
                              </div>
                            </td>
                            <td style={{ padding: "8px", color: "var(--color-ink)", fontSize: 12, fontWeight: 700 }}>{row.totalFlags}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Category Risk Drivers */}
                <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, display: "flex", flexDirection: "column" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                    <div>
                      <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Category Risk Drivers</h3>
                      <p style={{ fontSize: 13, color: "var(--color-muted)", margin: 0 }}>Sector-specific patterns — top flagged lines of business</p>
                    </div>
                  </div>
                  {loading ? <Skeleton h={220} /> : categoryData.length === 0 ? (
                    <EmptyState h={220} title="No Category Risk Data" />
                  ) : (
                    <div style={{ flexGrow: 1, minHeight: 220, width: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={categoryData.slice(0, 7)} layout="vertical" margin={{ top: 0, right: 30, left: 10, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="rgba(226,232,240,0.4)" />
                        <XAxis type="number" allowDecimals={false} domain={[0, (dataMax) => Math.max(5, dataMax + 1)]} tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "var(--color-ink)", fontWeight: 500 }} width={120} axisLine={false} tickLine={false} tickFormatter={(val) => typeof val === 'string' && val.length > 18 ? val.substring(0, 18) + '…' : val} />
                        <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.15)", background: "var(--color-surface)" }} />
                        <Bar dataKey="count" fill={COLOR.orange} radius={[0, 4, 4, 0]} name="Flagged">
                          <LabelList dataKey="count" position="right" fill="var(--color-ink)" fontSize={11} fontWeight={600} />
                        </Bar>
                      </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
              </div>

              {/* Audit Summary Section */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", gap: 24 }}>
                <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, display: "flex", flexDirection: "column" }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Inspection Result Breakdown</h3>
                  <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "0 0 16px 0" }}>Distribution of audit outcomes for verified businesses.</p>
                  {loading ? <Skeleton h={260} /> : auditData.length === 0 ? (
                    <EmptyState h={260} title="No Audit Data" />
                  ) : (
                    <div style={{ flexGrow: 1, minHeight: 260, width: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={auditData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226,232,240,0.4)" />
                          <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                          <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.15)", background: "var(--color-surface)" }} />
                          <Bar dataKey="value" fill="#8b5cf6" radius={[4, 4, 0, 0]}>
                            {auditData.map((entry, index) => (
                              <Cell key={`cell-${index}`} fill={entry.fill} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
                <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, display: "flex", flexDirection: "column" }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Enforcement Funnel</h3>
                  <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "0 0 16px 0" }}>Actual conversion of detected entities through the audit process.</p>
                  <div style={{ flexGrow: 1, display: "flex", flexDirection: "column", gap: 12, marginTop: 24, justifyContent: "center" }}>
                    {funnelData.map((f, i) => {
                      const maxVal = Math.max(...funnelData.map(d => d.value)) || 1;
                      const pct = (f.value / maxVal) * 100;
                      return (
                        <div key={i} style={{ display: "flex", alignItems: "center", gap: 16 }}>
                          <div style={{ width: 110, fontSize: 13, fontWeight: 600, color: "var(--color-muted)", textAlign: "right" }}>{f.step}</div>
                          <div style={{ flex: 1, height: 24, background: "rgba(226,232,240,0.3)", borderRadius: 12, position: "relative", overflow: "hidden" }}>
                            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct}%`, background: f.color, borderRadius: 12, transition: "width 0.5s ease" }} />
                          </div>
                          <div style={{ width: 40, fontSize: 14, fontWeight: 800, color: "var(--color-ink)" }}>{f.value}</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* ══════════════════════════════════════════════════════════════════════
          TIER 2 — DIAGNOSTIC ANALYTICS
      ══════════════════════════════════════════════════════════════════════ */}
        {activeTab === "diagnostic" && (
          <section style={{ marginBottom: 52 }}>
            <SectionHeader
              tier="diagnostic"
              title="Diagnostic Analysis"
              subtitle="Automated risk intelligence, historical trends, and sector-level risk drivers"
            />

            {/* D1. NARRATIVES */}
            <div style={{ marginBottom: 40 }}>
              <h3 style={{ fontSize: 18, fontWeight: 800, color: "var(--color-ink)", margin: "0 0 16px 0", borderBottom: "2px solid rgba(226,232,240,0.6)", paddingBottom: 8 }}>D1. Risk Intelligence Narratives</h3>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", gap: 24 }}>
                <div className="tier-2-card saas-card frosted-glass" style={{ padding: "24px", borderRadius: 12 }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
                    <div style={{ color: "#8b5cf6" }}>
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="8" x2="12" y2="12" />
                        <line x1="12" y1="16" x2="12.01" y2="16" />
                      </svg>
                    </div>
                    <div style={{ flex: 1 }}>
                      <h3 style={{ fontSize: 16, fontWeight: 800, color: "var(--color-ink)", margin: "0 0 8px 0" }}>High-Risk Hotspot Detection (DBSCAN)</h3>
                      <p style={{ fontSize: 14, color: "var(--color-muted)", margin: 0, lineHeight: 1.5 }}>
                        {loading ? "Analyzing local map patterns..." : (diag?.dbscan_insight || "Hotspot detection temporarily unavailable.")}
                      </p>

                      {diag?.dbscan_clusters && diag.dbscan_clusters.length > 0 && (
                        (() => {
                          const displayClusters = [];
                          const seenClusters = new Set();
                          diag.dbscan_clusters.forEach(entry => {
                            if (entry.cluster === -1) {
                              displayClusters.push({ ...entry, renderType: 'noise' });
                            } else {
                              // 1. Render the centroid as a large hollow ring (only once per cluster)
                              if (!seenClusters.has(entry.cluster)) {
                                seenClusters.add(entry.cluster);
                                displayClusters.push({ ...entry, renderType: 'centroid' });
                              }
                              // 2. Render each actual business with a slight spatial jitter so they don't overlap perfectly
                              // 0.0004 degrees is roughly ~40 meters of scatter
                              const jitterLat = entry.lat + (Math.random() - 0.5) * 0.0004;
                              const jitterLng = entry.lng + (Math.random() - 0.5) * 0.0004;
                              displayClusters.push({ ...entry, lat: jitterLat, lng: jitterLng, renderType: 'point' });
                            }
                          });

                          return (
                            <>
                            <div style={{ height: 220, width: "100%", marginTop: 16 }}>
                              <ResponsiveContainer width="100%" height="100%">
                                <ScatterChart margin={{ top: 10, right: 10, bottom: 18, left: -10 }}>
                                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226,232,240,0.4)" />
                                  <XAxis type="number" dataKey="lng" name="Longitude" domain={['auto', 'auto']} tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} tickFormatter={(v) => v.toFixed(3)} label={{ value: "Longitude", position: "insideBottom", offset: -12, fontSize: 10, fill: "var(--color-muted)", fontWeight: 600 }} />
                                  <YAxis type="number" dataKey="lat" name="Latitude" domain={['auto', 'auto']} tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} tickFormatter={(v) => v.toFixed(3)} label={{ value: "Latitude", angle: -90, position: "insideLeft", offset: 10, fontSize: 10, fill: "var(--color-muted)", fontWeight: 600 }} />
                                  <ZAxis type="category" dataKey="barangay" name="Barangay" />
                                  <Tooltip
                                    cursor={{ strokeDasharray: '3 3' }}
                                    contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.15)", background: "var(--color-surface)", fontSize: 12 }}
                                    content={({ active, payload }) => {
                                      if (!active || !payload?.length) return null;
                                      const d = payload[0]?.payload;
                                      if (!d) return null;
                                      const typeLabel = d.renderType === 'noise'
                                        ? "Isolated (no cluster)"
                                        : d.renderType === 'centroid'
                                          ? `Cluster #${d.cluster} center`
                                          : `Cluster #${d.cluster} member`;
                                      return (
                                        <div style={{ background: "#111827", border: "1px solid #374151", color: "#ffffff", borderRadius: 8, padding: "8px 12px", boxShadow: "0 4px 12px rgba(0,0,0,0.3)", fontSize: 12, lineHeight: 1.6 }}>
                                          <div style={{ fontWeight: 700, color: "#ffffff", marginBottom: 2 }}>{d.barangay || "Unknown area"}</div>
                                          <div style={{ color: "#e5e7eb" }}>{typeLabel}{d.is_primary ? " · Primary hotspot" : ""}</div>
                                          <div style={{ color: "#e5e7eb", fontSize: 11, marginTop: 2 }}>{d.lat?.toFixed(4)}°N, {d.lng?.toFixed(4)}°E</div>
                                        </div>
                                      );
                                    }}
                                  />
                                  <Scatter
                                    name="Clusters"
                                    data={displayClusters}
                                    shape={(props) => {
                                      const { cx, cy, payload } = props;
                                      const isPrimary = payload.is_primary;
                                      const baseColor = isPrimary ? "#6366f1" : COLOR.orange;

                                      if (payload.renderType === 'noise') {
                                        return <circle cx={cx} cy={cy} r={3} fill={COLOR.slate} opacity={0.3} />;
                                      }

                                      if (payload.renderType === 'centroid') {
                                        const radius = isPrimary ? 14 : 10;
                                        return (
                                          <circle
                                            cx={cx} cy={cy} r={radius}
                                            fill={baseColor} fillOpacity={0.1}
                                            stroke={baseColor} strokeWidth={2} strokeOpacity={1}
                                          />
                                        );
                                      }

                                      // Jittered point
                                      return <circle cx={cx} cy={cy} r={3} fill={baseColor} opacity={0.7} />;
                                    }}
                                  />
                                </ScatterChart>
                              </ResponsiveContainer>
                            </div>

                            {/* ── DBSCAN Legend ─────────────────────── */}
                            <div style={{
                              display: "flex", flexWrap: "wrap", gap: "12px 20px",
                              marginTop: 10, padding: "8px 12px",
                              background: "rgba(255,255,255,0.05)", border: "1px solid rgba(229,231,235,0.16)", borderRadius: 8,
                              fontSize: 11, color: "#e5e7eb", lineHeight: 1.4
                            }}>
                              {/* Primary hotspot */}
                              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                                <svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="#6366f1" fillOpacity="0.15" stroke="#6366f1" strokeWidth="2"/></svg>
                                <span><b style={{ color: "#6366f1" }}>Top Problem Area</b> — biggest group of risky businesses</span>
                              </span>
                              {/* Secondary cluster */}
                              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                                <svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="5" fill={COLOR.orange} fillOpacity="0.15" stroke={COLOR.orange} strokeWidth="2"/></svg>
                                <span><b style={{ color: COLOR.orange }}>Other Problem Areas</b> — smaller groups nearby</span>
                              </span>
                              {/* Flagged businesses */}
                              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                                <svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3.5" fill="#6366f1" opacity="0.7"/><circle cx="13" cy="12" r="2.5" fill={COLOR.orange} opacity="0.7"/></svg>
                                <span>Individual flagged businesses in a group</span>
                              </span>
                              {/* Isolated / noise */}
                              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                                <svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3" fill={COLOR.slate} opacity="0.3"/></svg>
                                <span>Standalone businesses — not part of any group</span>
                              </span>
                            </div>
                            </>
                          );
                        })()
                      )}
                    </div>
                  </div>
                </div>

                <div className="tier-2-card saas-card frosted-glass" style={{ padding: "24px", borderRadius: 12 }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
                    <div style={{ color: "#7c3aed" }}>
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="18" cy="5" r="3" />
                        <circle cx="6" cy="12" r="3" />
                        <circle cx="18" cy="19" r="3" />
                        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                        <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
                      </svg>
                    </div>
                    <div style={{ flex: 1 }}>
                      <h3 style={{ fontSize: 16, fontWeight: 800, color: "var(--color-ink)", margin: "0 0 8px 0" }}>Regional Risk Patterns (Moran's I)</h3>
                      <p style={{ fontSize: 14, color: "var(--color-muted)", margin: 0, lineHeight: 1.5 }}>
                        {loading ? "Evaluating broader geographic patterns..." : (diag?.morans_insight || "Regional analysis temporarily unavailable.")}
                      </p>

                      {diag?.morans_data?.points && diag.morans_data.points.length > 0 && (
                        <div style={{ height: 180, width: "100%", marginTop: 16 }}>
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={diag.morans_data.points} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226,232,240,0.4)" />
                              <XAxis dataKey="barangay" tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} hide />
                              <YAxis tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                              <Tooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.15)", background: "var(--color-surface)", fontSize: 12 }} />
                              <ReferenceLine y={diag.morans_data.threshold} stroke="#6366f1" strokeDasharray="3 3" label={{ position: 'top', value: 'High Risk Threshold', fill: "#6366f1", fontSize: 10 }} />
                              <Bar dataKey="risk" name="Severe Flags" radius={[2, 2, 0, 0]}>
                                {diag.morans_data.points.map((entry, index) => (
                                  <Cell key={`cell-${index}`} fill={entry.is_high_risk ? "#6366f1" : "#8b5cf6"} opacity={entry.is_high_risk ? 0.9 : 0.4} />
                                ))}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", gap: 24 }}>
              {/* D2. TREND ANALYSIS */}
              <div>
                <h3 style={{ fontSize: 18, fontWeight: 800, color: "var(--color-ink)", margin: "0 0 16px 0", borderBottom: "2px solid rgba(226,232,240,0.6)", paddingBottom: 8 }}>D2. Trend Analysis</h3>
                <div className="tier-2-card saas-card frosted-glass" style={{ padding: 24, borderRadius: 12, height: "calc(100% - 46px)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                    <div>
                      <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>Weekly Red Flag Emergence</h3>
                      <p style={{ fontSize: 12, color: "var(--color-muted)", margin: 0 }}>Are we catching more critical issues over time?</p>
                    </div>
                  </div>
                  {loading ? <Skeleton h={220} /> : trendData.length === 0 ? (
                    <EmptyState h={220} title="No Trend Data" />
                  ) : (
                    <ResponsiveContainer width="100%" height={220}>
                      <LineChart data={trendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226,232,240,0.4)" />
                        <XAxis dataKey="week" tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <Tooltip content={<CustomTooltip />} />
                        <Line type="monotone" dataKey="New Red Flags" stroke="#6366f1" strokeWidth={3} dot={{ r: 4, fill: "#6366f1" }} activeDot={{ r: 6 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>
            </div>
          </section>
        )}

        {/* ══════════════════════════════════════════════════════════════════════
          TIER 3 — PRESCRIPTIVE ANALYTICS (WLC / OPS)
      ══════════════════════════════════════════════════════════════════════ */}
        {activeTab === "prescriptive" && (
          <section style={{ marginBottom: 32 }}>
            <SectionHeader
              tier="prescriptive"
              title="Prescriptive Analytics — Action Plan"
              subtitle="Weighted Linear Combination model (OPS = W1·Risk + W2·Sector − W3·Distance) normalised 0–100 per barangay"
            />

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
                                {rec.inspectors ?? 0} inspector{(rec.inspectors ?? 0) !== 1 ? "s" : ""}
                              </span>
                              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" /><line x1="4" y1="22" x2="4" y2="15" /></svg>
                                {rec.flagged_count ?? 0} flag{(rec.flagged_count ?? 0) !== 1 ? "s" : ""}
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
                              {rec.red_count > 0 && <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: "rgba(100,116,139,0.08)", color: "#475569" }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" /></svg> {rec.red_count} Unregistered</span>}
                              {rec.yellow_count > 0 && <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: "rgba(100,116,139,0.08)", color: "#475569" }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg> {rec.yellow_count} Suspicious</span>}
                              {rec.black_count > 0 && <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: "rgba(100,116,139,0.08)", color: "#475569" }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg> {rec.black_count} Violations</span>}
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
                                      <span style={{ fontSize: 20, fontWeight: 800, color }}>{data?.raw ?? 0}</span>
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

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: 24, marginBottom: 24 }}>
              {/* Radar chart — top 8 */}
              <div className="tier-3-card saas-card frosted-glass" style={{ borderRadius: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: 0 }}>
                    OPS Radar — Top 8 Barangays
                  </h3>
                  <button className="ghost-btn" onClick={() => showWlcConfig ? handleCancelWlc() : setShowWlcConfig(true)} style={{ fontSize: 12, padding: "4px 10px", margin: 0 }}>
                    {showWlcConfig ? "Close Quick Adjust" : "⚙ Quick Adjust WLC Weights"}
                  </button>
                </div>

                {showWlcConfig && (
                  <div style={{ background: "var(--color-hover)", marginBottom: 16, padding: "16px", borderRadius: 8, border: "1px solid var(--color-border)" }}>
                    <h4 style={{ margin: "0 0 16px 0", fontSize: 13, color: "var(--color-ink)" }}>WLC Weight Configuration</h4>
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                      <div>
                        <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--color-muted)", marginBottom: 6 }}>
                          Risk Severity (W1): <span style={{ color: "var(--color-primary)" }}>{wlcConfig.w1_risk}%</span>
                        </label>
                        <input type="range" min="0" max="100" value={wlcConfig.w1_risk} onChange={e => setWlcConfig({ ...wlcConfig, w1_risk: Number(e.target.value) })} style={{ width: "100%", accentColor: "var(--color-primary)" }} />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--color-muted)", marginBottom: 6 }}>
                          Sector Impact (W2): <span style={{ color: "var(--color-primary)" }}>{wlcConfig.w2_sector}%</span>
                        </label>
                        <input type="range" min="0" max="100" value={wlcConfig.w2_sector} onChange={e => setWlcConfig({ ...wlcConfig, w2_sector: Number(e.target.value) })} style={{ width: "100%", accentColor: "var(--color-primary)" }} />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "var(--color-muted)", marginBottom: 6 }}>
                          Travel Distance (W3): <span style={{ color: "var(--color-primary)" }}>{wlcConfig.w3_distance}%</span>
                        </label>
                        <input type="range" min="0" max="100" value={wlcConfig.w3_distance} onChange={e => setWlcConfig({ ...wlcConfig, w3_distance: Number(e.target.value) })} style={{ width: "100%", accentColor: "var(--color-primary)" }} />
                      </div>
                    </div>
                    <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}>
                      <button className="ghost-btn" style={{ padding: "6px 12px", fontSize: 11 }} onClick={handleCancelWlc} disabled={savingWlc}>
                        Cancel
                      </button>
                      <button className="primary-btn" style={{ padding: "6px 12px", fontSize: 11 }} onClick={handleSaveWlc} disabled={savingWlc}>
                        {savingWlc ? "Applying..." : "Apply"}
                      </button>
                    </div>
                  </div>
                )}

                {loading ? <Skeleton h={280} /> : radarData.length === 0 ? (
                  <EmptyState h={280} title="Insufficient Data" message="Not enough data to compute OPS rankings." />
                ) : (
                  <ResponsiveContainer width="100%" height={280}>
                    <RadarChart data={radarData}>
                      <PolarGrid stroke="rgba(226,232,240,0.6)" />
                      <PolarAngleAxis dataKey="barangay" tick={{ fontSize: 10, fill: "var(--color-muted)" }} />
                      <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 9 }} />
                      <Radar name="OPS Score" dataKey="OPS" stroke="#6366f1" fill="#6366f1" fillOpacity={0.18} strokeWidth={2} />
                      <Radar name="Non-Compliance %" dataKey="Non-Compliance %" stroke={COLOR.yellow} fill={COLOR.yellow} fillOpacity={0.12} strokeWidth={2} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Tooltip content={<CustomTooltip />} />
                    </RadarChart>
                  </ResponsiveContainer>
                )}
              </div>

              {/* Full WLC Rankings Table */}
              <div className="tier-2-card saas-card frosted-glass" style={{ borderRadius: 12 }}>
                <div style={{ marginBottom: 16 }}>
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-ink)", margin: "0 0 4px 0" }}>
                    Inspector Deployment Priority Table
                  </h3>
                  <p style={{ fontSize: 12, color: "var(--color-muted)", margin: 0 }}>
                    All 16 barangays ranked by OPS — deploy inspectors top-down
                  </p>
                </div>

                {loading ? <Skeleton h={380} /> : (
                  <div style={{ maxHeight: 400, overflowY: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                      <thead style={{ position: "sticky", top: 0, background: "var(--color-surface)", zIndex: 10 }}>
                        <tr style={{ borderBottom: "2px solid rgba(226,232,240,0.6)", color: "var(--color-muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                          <th style={{ padding: "10px 12px", fontWeight: 700 }}>#</th>
                          <th style={{ padding: "10px 12px", fontWeight: 700 }}>Barangay</th>
                          <th style={{ padding: "10px 12px", fontWeight: 700 }}>OPS</th>
                          <th style={{ padding: "10px 12px", fontWeight: 700 }}>Flagged</th>
                          <th style={{ padding: "10px 12px", fontWeight: 700 }}>R / Y / B</th>
                          <th style={{ padding: "10px 12px", fontWeight: 700 }}>Priority</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(presc?.rankings || []).map((row) => (
                          <tr
                            key={row.barangayID}
                            className="ops-row"
                            style={{ borderBottom: "1px solid rgba(226,232,240,0.35)", transition: "background 0.15s" }}
                          >
                            <td style={{ padding: "12px", fontWeight: 700, color: "var(--color-muted)", fontSize: 13 }}>
                              {row.rank <= 3
                                ? <span style={{ color: row.rank === 1 ? COLOR.red : row.rank === 2 ? COLOR.yellow : COLOR.green, fontWeight: 800 }}>#{row.rank}</span>
                                : `#${row.rank}`}
                            </td>
                            <td style={{ padding: "12px", fontWeight: 600, color: "var(--color-ink)", fontSize: 13 }}>
                              {row.barangayName}
                            </td>
                            <td style={{ padding: "12px" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <strong style={{ fontSize: 14, color: "var(--color-ink)", minWidth: 36 }}>{row.ops_score}</strong>
                                <div className="ops-score-bar" style={{ width: 40 }}>
                                  <div
                                    className="ops-score-fill"
                                    style={{
                                      width: `${row.ops_score}%`,
                                      background: row.risk_level === "High" ? COLOR.red
                                        : row.risk_level === "Medium" ? COLOR.yellow
                                          : COLOR.green,
                                    }}
                                  />
                                </div>
                              </div>
                            </td>
                            <td style={{ padding: "12px", color: "var(--color-muted)", fontSize: 13 }}>{row.flagged_count}</td>
                            <td style={{ padding: "12px", fontSize: 12 }}>
                              <span style={{ color: COLOR.red }}>{row.red_count}</span>
                              {" / "}
                              <span style={{ color: COLOR.yellow }}>{row.yellow_count}</span>
                              {" / "}
                              <span style={{ color: COLOR.black, fontWeight: 700 }}>{row.black_count}</span>
                            </td>
                            <td style={{ padding: "12px" }}>
                              <span style={{
                                padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 700,
                                ...riskBadgeStyle(row.risk_level),
                              }}>
                                {row.risk_level}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {/* ══════════════════════════════════════════════════════════════════════
            OPERATIONS
        ══════════════════════════════════════════════════════════════════════ */}
        {activeTab === "operations" && (
          <section style={{ marginBottom: 52 }}>
            <SectionHeader
              tier="operations"
              title="Inspector Operations"
              subtitle="Monitor inspector performance, timelines, and resolution statuses"
            />

            {loading ? (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
                <Skeleton h={380} />
                <Skeleton h={380} />
              </div>
            ) : (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: 24, marginBottom: 24 }}>

                  {/* Inspector Leaderboard */}
                  <div className="saas-card frosted-glass" style={{ padding: 24, borderRadius: 16 }}>
                    <div style={{ marginBottom: 20 }}>
                      <h3 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 8px 0", color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 8 }}>
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke={COLOR.blue} strokeWidth="2">
                          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                        </svg>
                        Inspector Leaderboard
                      </h3>
                      <p style={{ margin: 0, fontSize: 13, color: "var(--color-muted)", lineHeight: 1.5 }}>
                        {InsightGenerator.inspectorPerformance(data?.operations?.inspector_stats)}
                      </p>
                    </div>

                    <div style={{ maxHeight: 300, overflowY: "auto" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                        <thead style={{ position: "sticky", top: 0, background: "var(--color-surface)", zIndex: 10 }}>
                          <tr style={{ borderBottom: "2px solid rgba(226,232,240,0.6)", color: "var(--color-muted)", fontSize: 11, textTransform: "uppercase" }}>
                            <th style={{ padding: "10px 12px", fontWeight: 700 }}>Inspector</th>
                            <th style={{ padding: "10px 12px", fontWeight: 700 }}>Completed</th>
                            <th style={{ padding: "10px 12px", fontWeight: 700 }}>Assigned</th>
                            <th style={{ padding: "10px 12px", fontWeight: 700 }}>Yellow Flags Reported</th>
                            <th style={{ padding: "10px 12px", fontWeight: 700 }}>Avg Time (Days)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(data?.operations?.inspector_stats || []).map((row) => (
                            <tr key={row.userID} style={{ borderBottom: "1px solid rgba(226,232,240,0.35)" }}>
                              <td style={{ padding: "12px", fontWeight: 600, color: "var(--color-ink)", fontSize: 13 }}>
                                {row.fullName}
                              </td>
                              <td style={{ padding: "12px", fontWeight: 700, color: COLOR.green, fontSize: 13 }}>
                                {row.total_completed}
                              </td>
                              <td style={{ padding: "12px", color: "var(--color-muted)", fontSize: 13 }}>
                                {row.total_assigned}
                              </td>
                              <td style={{ padding: "12px", color: COLOR.gold, fontWeight: 600, fontSize: 13 }}>
                                {row.yellow_flags_reported || 0}
                              </td>
                              <td style={{ padding: "12px", color: "var(--color-muted)", fontSize: 13 }}>
                                {row.avg_resolution_time ? (row.avg_resolution_time / 1440).toFixed(1) : "-"}
                              </td>
                            </tr>
                          ))}
                          {(!data?.operations?.inspector_stats || data.operations.inspector_stats.length === 0) && (
                            <tr>
                              <td colSpan="5" style={{ padding: "24px" }}>
                                <EmptyState h={160} title="No Inspector Data" message="No operations found for these criteria." />
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Status Breakdown */}
                  <div className="saas-card frosted-glass" style={{ padding: 24, borderRadius: 16 }}>
                    <div style={{ marginBottom: 20 }}>
                      <h3 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 8px 0", color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 8 }}>
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke={COLOR.blue} strokeWidth="2">
                          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>
                        </svg>
                        Inspection Status Breakdown
                      </h3>
                      <p style={{ margin: 0, fontSize: 13, color: "var(--color-muted)", lineHeight: 1.5 }}>
                        {InsightGenerator.inspectionStatus(data?.operations?.status_breakdown)}
                      </p>
                    </div>

                    {data?.operations?.status_breakdown?.length === 0 ? (
                      <EmptyState h={260} title="No Status Data" message="No inspection status data available." />
                    ) : (
                      <div style={{ height: 260, width: "100%" }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={data?.operations?.status_breakdown || []}
                              dataKey="count"
                              nameKey="status"
                              cx="50%"
                              cy="50%"
                              innerRadius={60}
                              outerRadius={90}
                              paddingAngle={5}
                              activeShape={false}
                              isAnimationActive={false}
                              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                            >
                              {(data?.operations?.status_breakdown || []).map((entry, index) => {
                                const colors = { "Assigned": COLOR.orange, "In Progress": COLOR.yellow, "Reassigned": COLOR.slate, "Submitted": COLOR.blue, "Verified": COLOR.green, "Unassigned": COLOR.muted };
                                return <Cell key={`cell-${index}`} fill={colors[entry.status] || COLOR.muted} />;
                              })}
                            </Pie>
                            <Tooltip content={<CustomTooltip />} />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>
                </div>

                {/* Timeline */}
                <div className="saas-card frosted-glass" style={{ padding: 24, borderRadius: 16 }}>
                  <div style={{ marginBottom: 20 }}>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 8px 0", color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 8 }}>
                      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke={COLOR.blue} strokeWidth="2">
                        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
                      </svg>
                      Inspection Activity Timeline
                    </h3>
                    <p style={{ margin: 0, fontSize: 13, color: "var(--color-muted)", lineHeight: 1.5 }}>
                      {InsightGenerator.opsTimeline(data?.operations?.inspection_timeline)}
                    </p>
                  </div>

                  {data?.operations?.inspection_timeline?.length === 0 ? (
                    <EmptyState h={300} title="No Timeline Data" message="Not enough timeline data available." />
                  ) : (
                    <div style={{ height: 300, width: "100%" }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={data?.operations?.inspection_timeline || []} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                          <defs>
                            <linearGradient id="opsColor" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor={COLOR.blue} stopOpacity={0.3} />
                              <stop offset="95%" stopColor={COLOR.blue} stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226,232,240,0.6)" />
                          <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--color-muted)" }} tickMargin={10} minTickGap={20} />
                          <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--color-muted)" }} />
                          <Tooltip content={<CustomTooltip />} />
                          <Area type="monotone" dataKey="count" name="Inspections" stroke={COLOR.blue} strokeWidth={2} fillOpacity={1} fill="url(#opsColor)" activeDot={{ r: 6, strokeWidth: 0, fill: COLOR.blue }} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
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
        <p className="footer-links"><span>BPLO Portal</span> &bull; <span>System Settings</span></p>
      </footer>
    </DashboardLayout>
  );
}
