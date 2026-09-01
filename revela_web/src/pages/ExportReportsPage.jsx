import { useState, useEffect, useRef } from "react";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  AreaChart,
  Area
} from "recharts";
import DashboardLayout from "../components/DashboardLayout";
import { useAuth } from "../context/AuthContext";
import { getAnalyticsOverviewRequest, getFlagsRequest } from "../services/api";
import Papa from "papaparse";
import { saveAs } from "file-saver";
import Swal from "sweetalert2";
import html2canvas from "html2canvas";
import bpLogo from "../assets/bagongpilipinas.png";
import sealImg from "../assets/seal.png";

// ── Color Palettes ─────────────────────────────────────────────────────────────
const SIZE_COLORS = ["#8b5cf6", "#3b82f6", "#10b981", "#f59e0b", "#ef4444"];
const TYPE_COLORS = ["#14b8a6", "#f97316", "#ec4899", "#8b5cf6", "#3b82f6", "#6366f1"];
const SECTOR_COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#06b6d4"
];

// ── Operational Reports (strictly retained per requirements) ──────────────────
const OPERATIONAL_REPORTS = [
  {
    id: "unregistered",
    title: "List of Unregistered Businesses",
    tag: "Field Enforcement",
    tagColor: "#dc2626",
    tagBg: "#fee2e2",
    desc: "Active Red and Yellow flags indicating suspected unregistered commercial activity with resolved addresses, landmarks, and coordinates for field verification."
  },
  {
    id: "dispatch",
    title: "Field Inspector Dispatch Plan",
    tag: "WLC Operational Priority",
    tagColor: "#2563eb",
    tagBg: "#dbeafe",
    desc: "Barangay prioritization rankings derived from the WLC Operational Priority Score (OPS) with targeted inspector allocation recommendations."
  }
];

// ── Reusable Empty State Component for Visual Chart Cards ─────────────────────
function ChartEmptyState({ title = "No Data Recorded", message = "No registered business records available in this category yet." }) {
  return (
    <div
      style={{
        height: "100%",
        minHeight: 200,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px 16px",
        textAlign: "center",
        background: "rgba(0, 0, 0, 0.015)",
        borderRadius: 8,
        border: "1px dashed rgba(226, 232, 240, 0.9)"
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: "50%",
          background: "rgba(100, 116, 139, 0.08)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 10,
          color: "var(--color-muted, #64748b)"
        }}
      >
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.75">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </div>
      <div style={{ fontSize: 13.5, fontWeight: 700, color: "var(--color-ink, #0f172a)", marginBottom: 3 }}>
        {title}
      </div>
      <div style={{ fontSize: 12, color: "var(--color-muted, #64748b)", maxWidth: 280, lineHeight: 1.4 }}>
        {message}
      </div>
    </div>
  );
}

export default function ExportReportsPage() {
  const { token, user } = useAuth();
  const [analyticsData, setAnalyticsData] = useState(null);
  const [loadingAnalytics, setLoadingAnalytics] = useState(true);
  const [exportingImageId, setExportingImageId] = useState(null);
  const [exportingPdfId, setExportingPdfId] = useState(null);
  const [operationalLoadingId, setOperationalLoadingId] = useState(null);
  const [printReport, setPrintReport] = useState(null);

  // References for chart DOM elements to capture via html2canvas
  const chartRefs = useRef({});

  // Fetch demographic & operational analytics data
  useEffect(() => {
    let cancelled = false;
    async function loadData() {
      if (!token) {
        setLoadingAnalytics(false);
        return;
      }
      setLoadingAnalytics(true);
      try {
        const data = await getAnalyticsOverviewRequest(token);
        if (!cancelled && data) {
          setAnalyticsData(data);
        }
      } catch (err) {
        console.warn("Analytics overview request failed:", err);
      } finally {
        if (!cancelled) setLoadingAnalytics(false);
      }
    }
    loadData();
    return () => {
      cancelled = true;
    };
  }, [token]);

  // Handle native printing when printReport state changes
  useEffect(() => {
    if (printReport) {
      const handleAfterPrint = () => {
        setPrintReport(null);
      };
      window.addEventListener("afterprint", handleAfterPrint);

      const timer = setTimeout(() => {
        window.print();
      }, 500);

      return () => {
        clearTimeout(timer);
        window.removeEventListener("afterprint", handleAfterPrint);
      };
    }
  }, [printReport]);

  // ── Derived Demographic Datasets ───────────────────────────────────────────
  const desc = analyticsData?.descriptive;
  const kpis = desc?.kpis;

  // 1. Business Size Profile
  const rawSizeData = (desc?.business_size_dist || []).filter((r) => r.count > 0);
  const sizeData = rawSizeData.map((r, i) => ({
    name: r.size_label || "Unclassified",
    value: Number(r.count || 0),
    fill: SIZE_COLORS[i % SIZE_COLORS.length]
  }));
  const totalBySize = sizeData.reduce((acc, curr) => acc + curr.value, 0);

  // 2. Legal Structure (Business Type)
  const rawTypeData = (desc?.business_type_dist || []).filter((r) => r.count > 0);
  const typeData = rawTypeData.map((r, i) => ({
    name: r.type_label || "Unclassified",
    value: Number(r.count || 0),
    fill: TYPE_COLORS[i % TYPE_COLORS.length]
  }));
  const totalByType = typeData.reduce((acc, curr) => acc + curr.value, 0);

  // 3. Dominant Economic Sectors (Top Lines of Business)
  const rawSectoralData = (desc?.sectoral_distribution || []).filter((r) => r.count > 0);
  const sectoralData = rawSectoralData.map((r) => ({
    name: r.sector || "Unclassified",
    value: Number(r.count || 0)
  }));
  const totalBySector = sectoralData.reduce((acc, curr) => acc + curr.value, 0);

  // 4. Geographic Spread Across Barangays
  const naturePerBarangay = desc?.nature_per_barangay || [];
  const barangaySpreadData = naturePerBarangay
    .map((r) => {
      const total = r.total != null
        ? Number(r.total)
        : Object.keys(r).reduce((sum, key) => {
          if (key !== "barangayName") return sum + (Number(r[key]) || 0);
          return sum;
        }, 0);
      return {
        barangayName: (r.barangayName || "").replace("Barangay ", "Brgy. "),
        fullName: r.barangayName || "Unknown",
        total
      };
    })
    .filter((b) => b.total > 0);
  const totalBusinessesAcrossBarangays = barangaySpreadData.reduce((acc, curr) => acc + curr.total, 0);

  // 5. Compliance by Business Size
  const complianceBySizeData = (desc?.compliance_by_size || [])
    .map((r) => {
      const active = Number(r.active_count || 0);
      const nonActive = Number(r.inactive_count || 0);
      const total = active + nonActive;
      const rate = total > 0 ? Math.round((active / total) * 100) : 0;
      return {
        name: r.size_label || "Unclassified",
        Active: active,
        "Non-Active": nonActive,
        total,
        rate
      };
    })
    .filter((c) => c.total > 0);

  // 6. 12-Month Renewal & Compliance Trajectory
  const rawTimelineData = desc?.compliance_timeline || [];
  const timelineData = rawTimelineData.map((r) => ({
    month: r.month,
    Active: Number(r.active_count || 0),
    "Non-Active": Number(r.non_active_count || 0)
  }));
  const hasTimelineData = timelineData.some((t) => t.Active > 0 || t["Non-Active"] > 0);

  const isRegistryEmpty = (kpis?.total_businesses ?? 0) === 0;

  // ── High-Resolution Image (PNG) Export ──────────────────────────────────────
  const exportChartAsImage = async (chartId, chartTitle, hasData) => {
    if (!hasData) {
      Swal.fire({
        icon: "info",
        title: "No Data to Export",
        text: "There are currently no recorded business establishments in this category."
      });
      return;
    }

    const element = chartRefs.current[chartId];
    if (!element) return;

    try {
      setExportingImageId(chartId);

      const canvas = await html2canvas(element, {
        scale: 2, // 2x retina crispness
        useCORS: true,
        backgroundColor: "#ffffff",
        logging: false,
        onclone: (clonedDoc) => {
          const actionButtons = clonedDoc.querySelectorAll(".no-export");
          actionButtons.forEach((btn) => {
            btn.style.display = "none";
          });
          const card = clonedDoc.getElementById(`chart-card-${chartId}`);
          if (card) {
            card.style.background = "#ffffff";
            card.style.padding = "24px";
            card.style.color = "#0f172a";
            card.style.border = "1px solid #e2e8f0";
            card.style.boxShadow = "none";
          }
        }
      });

      const dateStr = new Date().toISOString().slice(0, 10);
      const filename = `Mataasnakahoy_Demographic_${chartId}_${dateStr}.png`;

      canvas.toBlob((blob) => {
        if (blob) {
          saveAs(blob, filename);
          Swal.fire({
            icon: "success",
            title: "Chart Exported!",
            text: `Saved as ${filename}`,
            timer: 2000,
            showConfirmButton: false
          });
        }
      }, "image/png");
    } catch (err) {
      console.error("Error capturing chart image:", err);
      Swal.fire({
        icon: "error",
        title: "Export Failed",
        text: err.message || "Failed to export chart image."
      });
    } finally {
      setExportingImageId(null);
    }
  };

  // ── Single Chart Official PDF Export ────────────────────────────────────────
  const exportChartAsPdf = async (chartId, chartTitle, chartSubtitle, summaryTable, hasData) => {
    if (!hasData) {
      Swal.fire({
        icon: "info",
        title: "No Data to Export",
        text: "There are currently no recorded business establishments in this category."
      });
      return;
    }

    const element = chartRefs.current[chartId];
    if (!element) return;

    try {
      setExportingPdfId(chartId);

      const canvas = await html2canvas(element, {
        scale: 2,
        useCORS: true,
        backgroundColor: "#ffffff",
        logging: false,
        onclone: (clonedDoc) => {
          const actionButtons = clonedDoc.querySelectorAll(".no-export");
          actionButtons.forEach((btn) => {
            btn.style.display = "none";
          });
          const card = clonedDoc.getElementById(`chart-card-${chartId}`);
          if (card) {
            card.style.background = "#ffffff";
            card.style.padding = "20px";
            card.style.color = "#0f172a";
            card.style.border = "none";
            card.style.boxShadow = "none";
          }
        }
      });

      const chartImage = canvas.toDataURL("image/png");

      setPrintReport({
        type: "demographic-single",
        title: `Official Demographic Profile: ${chartTitle}`,
        subtitle: chartSubtitle,
        date: new Date().toLocaleString(),
        preparedBy: user?.fullName || "BPLO Staff",
        office: "Business Permits & Licensing Office",
        classification: "Official LGU Demographic Report",
        chartImage,
        summaryTable,
        isLandscape: false
      });
    } catch (err) {
      console.error("Error generating chart PDF:", err);
      Swal.fire({
        icon: "error",
        title: "PDF Generation Failed",
        text: err.message || "Failed to prepare printable PDF report."
      });
    } finally {
      setExportingPdfId(null);
    }
  };

  // ── Master Demographic Dossier (Complete PDF) ──────────────────────────────
  const exportCompleteDemographicPdf = async () => {
    try {
      setPrintReport({
        type: "demographic-complete",
        title: "Comprehensive Municipal Business Demographic Profile",
        subtitle: "Official census analysis, sectoral breakdown, geographic distribution, and compliance indicators",
        date: new Date().toLocaleString(),
        preparedBy: user?.fullName || "BPLO Staff",
        office: "BPLO Mataasnakahoy",
        classification: "Official Municipal Record",
        isLandscape: false,
        data: {
          kpis: [
            { Metric: "Total Registered Business Establishments", Value: kpis?.total_businesses ?? 0 },
            { Metric: "Active & Compliant Registrations", Value: kpis?.active_count ?? 0 },
            { Metric: "Expired / Non-Renewed Permits", Value: kpis?.expired_count ?? 0 },
            { Metric: "Pending Applications Under Review", Value: kpis?.pending_count ?? 0 },
            { Metric: "Officially Closed Entities", Value: kpis?.closed_count ?? 0 },
            { Metric: "Revoked Business Permits", Value: kpis?.revoked_count ?? 0 },
            { Metric: "Overall Municipal Compliance Rate", Value: `${kpis?.compliance_rate ?? 0}%` }
          ],
          sizeDistribution: sizeData.map((s) => ({
            Classification: s.name,
            Count: s.value,
            Percentage: `${Math.round((s.value / (totalBySize || 1)) * 100)}%`
          })),
          typeDistribution: typeData.map((t) => ({
            "Legal Structure": t.name,
            Count: t.value,
            Percentage: `${Math.round((t.value / (totalByType || 1)) * 100)}%`
          })),
          topSectors: sectoralData.slice(0, 10).map((sec, idx) => ({
            Rank: idx + 1,
            Sector: sec.name,
            Count: sec.value,
            Share: `${Math.round((sec.value / (totalBySector || 1)) * 100)}%`
          })),
          barangayDensity: barangaySpreadData.map((b) => ({
            Barangay: b.fullName,
            "Registered Entities": b.total,
            Share: `${Math.round((b.total / (totalBusinessesAcrossBarangays || 1)) * 100)}%`
          })),
          complianceBySize: complianceBySizeData.map((c) => ({
            Classification: c.name,
            Active: c.Active,
            "Non-Active": c["Non-Active"],
            "Compliance Rate": `${c.rate}%`
          }))
        }
      });
    } catch (err) {
      console.error("Error creating full demographic dossier:", err);
      Swal.fire({
        icon: "error",
        title: "Export Failed",
        text: "Could not compile the complete demographic report."
      });
    }
  };

  // ── Master Demographic Raw Data (CSV) Export ───────────────────────────────
  const exportDemographicCsv = () => {
    try {
      const csvSections = [];

      // Section 1: KPIs
      csvSections.push({ Section: "=== MUNICIPAL CENSUS KPIS ===", Metric: "", Value: "" });
      csvSections.push({ Section: "KPI", Metric: "Total Registered Entities", Value: kpis?.total_businesses ?? 0 });
      csvSections.push({ Section: "KPI", Metric: "Active Registrations", Value: kpis?.active_count ?? 0 });
      csvSections.push({ Section: "KPI", Metric: "Expired Permits", Value: kpis?.expired_count ?? 0 });
      csvSections.push({ Section: "KPI", Metric: "Pending Review", Value: kpis?.pending_count ?? 0 });
      csvSections.push({ Section: "KPI", Metric: "Closed Establishments", Value: kpis?.closed_count ?? 0 });
      csvSections.push({ Section: "KPI", Metric: "Compliance Rate", Value: `${kpis?.compliance_rate ?? 0}%` });

      // Section 2: Business Size
      csvSections.push({ Section: "=== BUSINESS SIZE DISTRIBUTION ===", Metric: "", Value: "" });
      if (sizeData.length === 0) {
        csvSections.push({ Section: "Size Classification", Metric: "No records found", Value: 0, Share: "0%" });
      } else {
        sizeData.forEach((s) => {
          csvSections.push({
            Section: "Size Classification",
            Metric: s.name,
            Value: s.value,
            Share: `${Math.round((s.value / (totalBySize || 1)) * 100)}%`
          });
        });
      }

      // Section 3: Legal Structure
      csvSections.push({ Section: "=== BUSINESS LEGAL STRUCTURE ===", Metric: "", Value: "" });
      if (typeData.length === 0) {
        csvSections.push({ Section: "Legal Structure", Metric: "No records found", Value: 0, Share: "0%" });
      } else {
        typeData.forEach((t) => {
          csvSections.push({
            Section: "Legal Structure",
            Metric: t.name,
            Value: t.value,
            Share: `${Math.round((t.value / (totalByType || 1)) * 100)}%`
          });
        });
      }

      // Section 4: Top Sectors
      csvSections.push({ Section: "=== TOP ECONOMIC SECTORS ===", Metric: "", Value: "" });
      if (sectoralData.length === 0) {
        csvSections.push({ Section: "Economic Sector", Metric: "No records found", Value: 0, Share: "0%" });
      } else {
        sectoralData.slice(0, 15).forEach((sec) => {
          csvSections.push({
            Section: "Economic Sector",
            Metric: sec.name,
            Value: sec.value,
            Share: `${Math.round((sec.value / (totalBySector || 1)) * 100)}%`
          });
        });
      }

      // Section 5: Barangay Spread
      csvSections.push({ Section: "=== BARANGAY DENSITY SPREAD ===", Metric: "", Value: "" });
      if (barangaySpreadData.length === 0) {
        csvSections.push({ Section: "Barangay Spread", Metric: "No records found", Value: 0, Share: "0%" });
      } else {
        barangaySpreadData.forEach((b) => {
          csvSections.push({
            Section: "Barangay Spread",
            Metric: b.fullName,
            Value: b.total,
            Share: `${Math.round((b.total / (totalBusinessesAcrossBarangays || 1)) * 100)}%`
          });
        });
      }

      const csv = Papa.unparse(csvSections);
      const dateStr = new Date().toISOString().slice(0, 10);
      saveAs(
        new Blob([csv], { type: "text/csv;charset=utf-8;" }),
        `Mataasnakahoy_Demographic_Census_${dateStr}.csv`
      );

      Swal.fire({
        icon: "success",
        title: "CSV Exported!",
        text: "Demographic dataset downloaded successfully.",
        timer: 2000,
        showConfirmButton: false
      });
    } catch (err) {
      console.error("Error generating demographic CSV:", err);
      Swal.fire({
        icon: "error",
        title: "Export Failed",
        text: "Could not export demographic data as CSV."
      });
    }
  };

  // ── Operational Report Handlers (Top Unregistered & Inspector Dispatch) ────
  const handleDownloadOperational = async (report) => {
    const { value: format } = await Swal.fire({
      title: `Export ${report.title}`,
      text: "Select your desired export file format:",
      input: "radio",
      inputOptions: {
        pdf: "Official PDF Document (with Municipal Letterhead)",
        csv: "CSV Spreadsheet (Raw Data)"
      },
      inputValidator: (value) => {
        if (!value) return "Please choose an export format!";
      },
      showCancelButton: true,
      confirmButtonText: "Generate Report",
      confirmButtonColor: "var(--color-primary, #10b981)"
    });

    if (!format) return;

    setOperationalLoadingId(report.id);
    try {
      if (report.id === "unregistered") {
        await generateUnregisteredReport(format);
      } else if (report.id === "dispatch") {
        await generateDispatchReport(format);
      }

      Swal.fire({
        icon: "success",
        title: "Export Complete!",
        text: `${report.title} exported as ${format.toUpperCase()}`,
        timer: 2000,
        showConfirmButton: false
      });
    } catch (error) {
      console.error(error);
      Swal.fire({
        icon: "error",
        title: "Export Failed",
        text: error.message || "An error occurred while generating the report."
      });
    } finally {
      setOperationalLoadingId(null);
    }
  };

  const generateUnregisteredReport = async (format) => {
    let flags = [];
    try {
      const res = await getFlagsRequest({ limit: 1000 }, token);
      const allFlags = res?.data || [];
      flags = allFlags.filter((f) => f.flagColor === "Red" || f.flagColor === "Yellow");
    } catch (e) {
      console.warn("Could not fetch flags:", e);
    }

    const dateStr = new Date().toISOString().slice(0, 10);
    const filename = `Unregistered_Businesses_${dateStr}`;

    const formattedData = flags.map((f) => ({
      Name: f.detectedName || "Unknown",
      Barangay: f.barangayName || "Unknown",
      Address: f.resolvedAddress || f.nearestLandmark || "",
      Status: f.flagColor === "Red" ? "Unregistered" : "Suspected Gap",
      DetectedDate: f.detectedDate ? f.detectedDate.slice(0, 10) : ""
    }));

    if (format === "csv") {
      const csv = Papa.unparse(formattedData.length > 0 ? formattedData : [{ Note: "No active red or yellow flagged unregistered businesses detected" }]);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }), `${filename}.csv`);
    } else {
      setPrintReport({
        type: "unregistered",
        title: "List of Unregistered Businesses",
        subtitle: "Field inspection target list of commercial locations operating without active permits",
        date: new Date().toLocaleString(),
        preparedBy: user?.fullName || "BPLO Staff",
        office: "BPLO Mataasnakahoy",
        classification: "Official Use / Confidential",
        isLandscape: true,
        data: {
          flags: formattedData,
          summary: {
            total: flags.length,
            red: flags.filter((f) => f.flagColor === "Red").length,
            yellow: flags.filter((f) => f.flagColor === "Yellow").length
          }
        }
      });
    }
  };

  const generateDispatchReport = async (format) => {
    let rankings = [];
    let recs = [];
    try {
      const data = await getAnalyticsOverviewRequest(token);
      rankings = data?.prescriptive?.rankings || [];
      recs = (data?.prescriptive?.recommendations || []).map((r, i) => ({
        rank: i + 1,
        barangayName: r.barangayName,
        recommendation: r.recommendation
      }));
    } catch (e) {
      console.warn("Could not fetch rankings:", e);
    }

    const dateStr = new Date().toISOString().slice(0, 10);
    const filename = `Inspector_Dispatch_Plan_${dateStr}`;

    const formattedData = rankings.map((r) => ({
      Rank: r.rank,
      Barangay: r.barangayName,
      PriorityScore: r.ops_score,
      RiskLevel: r.risk_level,
      TotalFlagged: r.flagged_count,
      RedFlags: r.red_count,
      NonComplianceRate: typeof r.non_compliance_rate === "number" ? `${r.non_compliance_rate}%` : r.non_compliance_rate
    }));

    if (format === "csv") {
      const csv = Papa.unparse(formattedData.length > 0 ? formattedData : [{ Note: "No operational dispatch rankings currently available" }]);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }), `${filename}.csv`);
    } else {
      setPrintReport({
        type: "dispatch",
        title: "Field Inspector Dispatch Plan",
        subtitle: "WLC Operational Priority Rankings and targeted allocation strategy for municipal inspectors",
        date: new Date().toLocaleString(),
        preparedBy: user?.fullName || "BPLO Staff",
        office: "BPLO Mataasnakahoy",
        classification: "Official Use / Confidential",
        data: {
          rankings: formattedData,
          recommendations: recs
        }
      });
    }
  };

  // Custom visual tooltip
  const CustomChartTooltip = ({ active, payload, label }) => {
    if (!active || !payload || !payload.length) return null;
    return (
      <div
        style={{
          background: "#0f172a",
          border: "1px solid #334155",
          borderRadius: 8,
          padding: "8px 12px",
          color: "#ffffff",
          fontSize: 12,
          boxShadow: "0 10px 25px -5px rgba(0,0,0,0.3)"
        }}
      >
        <p style={{ margin: "0 0 4px 0", fontWeight: 700, color: "#93c5fd" }}>{label || payload[0]?.name}</p>
        {payload.map((entry, idx) => (
          <div key={idx} style={{ display: "flex", alignItems: "center", gap: 6, margin: "2px 0" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: entry.color || entry.fill }} />
            <span style={{ color: "#cbd5e1" }}>{entry.name}:</span>
            <span style={{ fontWeight: 700, color: "#ffffff" }}>{entry.value}</span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <>
      {/* ── Screen UI Container (Completely hidden during window.print()) ── */}
      <div className="screen-only no-print">
        <DashboardLayout>
          {/* Page Header */}
          <div className="page-header" style={{ marginBottom: 28 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                  <h1 className="page-title" style={{ margin: 0, fontSize: 24, fontWeight: 800 }}>
                    Export Reports &amp; Demographics
                  </h1>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      padding: "3px 10px",
                      background: "rgba(16, 185, 129, 0.12)",
                      color: "#10b981",
                      borderRadius: 99
                    }}
                  >
                    BPLO Official
                  </span>
                </div>
                <p className="page-subtitle" style={{ margin: 0, color: "var(--color-muted)", fontSize: 14 }}>
                  Export visual demographic profile charts with custom legends (Image or PDF) and official field operational plans.
                </p>
              </div>

              {/* Quick Master Actions */}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={exportDemographicCsv}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: 13,
                    padding: "9px 15px",
                    borderRadius: 8,
                    fontWeight: 600,
                    cursor: "pointer"
                  }}
                >
                  <svg viewBox="0 0 24 24" width="15" height="15" stroke="currentColor" strokeWidth="2" fill="none">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                  Export Demographics CSV
                </button>

                <button
                  type="button"
                  className="primary-btn"
                  onClick={exportCompleteDemographicPdf}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: 13,
                    padding: "9px 16px",
                    borderRadius: 8,
                    fontWeight: 600,
                    cursor: "pointer"
                  }}
                >
                  <svg viewBox="0 0 24 24" width="15" height="15" stroke="currentColor" strokeWidth="2" fill="none">
                    <polyline points="6 9 6 2 18 2 18 9" />
                    <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
                    <rect x="6" y="14" width="12" height="8" />
                  </svg>
                  Complete Demographic Dossier (PDF)
                </button>
              </div>
            </div>
          </div>

          {/* ══════════════════════════════════════════════════════════════════════
              SECTION 1: DEMOGRAPHIC PROFILE & VISUALIZATIONS
          ══════════════════════════════════════════════════════════════════════ */}
          <section style={{ marginBottom: 44 }}>
            {/* Section Header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 18,
                paddingBottom: 10,
                borderBottom: "2px solid rgba(226, 232, 240, 0.7)"
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span
                    style={{
                      background: "var(--color-primary, #10b981)",
                      color: "#fff",
                      fontWeight: 800,
                      fontSize: 12,
                      padding: "3px 8px",
                      borderRadius: 6
                    }}
                  >
                    Section 1
                  </span>
                  <h2 style={{ fontSize: 19, fontWeight: 800, margin: 0, color: "var(--color-ink)" }}>
                    Business Demographic Profile
                  </h2>
                </div>
                <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--color-muted)" }}>
                  Official municipal census charts with interactive legends. Export any graph as high-res PNG image or official PDF report.
                </p>
              </div>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "var(--color-muted)",
                  background: "rgba(0,0,0,0.04)",
                  padding: "4px 10px",
                  borderRadius: 6
                }}
              >
                Source: BPLO Registry Census
              </span>
            </div>

            {/* Empty Registry Notice Banner (displays when database has 0 registered records) */}
            {isRegistryEmpty && !loadingAnalytics && (
              <div
                style={{
                  background: "rgba(59, 130, 246, 0.06)",
                  border: "1px solid rgba(59, 130, 246, 0.2)",
                  borderRadius: 10,
                  padding: "14px 18px",
                  marginBottom: 20,
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 12
                }}
              >
                <div style={{ color: "#3b82f6", marginTop: 2 }}>
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                </div>
                <div>
                  <div style={{ fontSize: 13.5, fontWeight: 700, color: "#1e3a8a" }}>
                    Official Registry is Currently Empty
                  </div>
                  <div style={{ fontSize: 12.5, color: "#475569", marginTop: 2, lineHeight: 1.45 }}>
                    No registered establishments have been logged in the local database yet. Upload a registry dataset in the Registry portal to view live demographic distribution graphs and compliance breakdowns.
                  </div>
                </div>
              </div>
            )}

            {/* Quick Census KPI Strip */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
                gap: 14,
                marginBottom: 24
              }}
            >
              <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase" }}>
                  Total Registered
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: "var(--color-ink)", marginTop: 4 }}>
                  {kpis?.total_businesses ?? 0}
                </div>
                <div style={{ fontSize: 11, color: "#10b981", marginTop: 2, fontWeight: 600 }}>Active Municipality-wide</div>
              </div>

              <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase" }}>
                  Active &amp; Compliant
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: "#10b981", marginTop: 4 }}>
                  {kpis?.active_count ?? 0}
                </div>
                <div style={{ fontSize: 11, color: "var(--color-muted)", marginTop: 2 }}>Current year valid permits</div>
              </div>

              <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase" }}>
                  Expired / Lapsed
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: "#ef4444", marginTop: 4 }}>
                  {kpis?.expired_count ?? 0}
                </div>
                <div style={{ fontSize: 11, color: "var(--color-muted)", marginTop: 2 }}>Awaiting renewal</div>
              </div>

              <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase" }}>
                  Pending Review
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: "#f59e0b", marginTop: 4 }}>
                  {kpis?.pending_count ?? 0}
                </div>
                <div style={{ fontSize: 11, color: "var(--color-muted)", marginTop: 2 }}>In processing queue</div>
              </div>

              <div className="saas-card frosted-glass" style={{ padding: "14px 16px", borderRadius: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase" }}>
                  Compliance Rate
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: "#3b82f6", marginTop: 4 }}>
                  {kpis?.compliance_rate != null ? `${kpis.compliance_rate}%` : "0%"}
                </div>
                <div style={{ fontSize: 11, color: "var(--color-muted)", marginTop: 2 }}>Active vs Total Ratio</div>
              </div>
            </div>

            {/* Demographic Charts Grid (2 columns) */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 460px), 1fr))",
                gap: 22
              }}
            >
              {/* ── CHART 1: Business Size Classification ── */}
              <div
                id="chart-card-size"
                ref={(el) => (chartRefs.current["size"] = el)}
                className="saas-card frosted-glass"
                style={{
                  padding: 22,
                  borderRadius: 14,
                  display: "flex",
                  flexDirection: "column",
                  position: "relative"
                }}
              >
                {/* Card Header & Export Toolbar */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 16,
                    gap: 12
                  }}
                >
                  <div>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: "var(--color-ink)" }}>
                      Business Size Classification
                    </h3>
                    <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "4px 0 0" }}>
                      Distribution of enterprises by capital scale (Micro, Small, Medium, Large)
                    </p>
                  </div>

                  <div className="no-export" style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      title="Export chart as high-resolution PNG image"
                      onClick={() => exportChartAsImage("size", "Business_Size_Classification", sizeData.length > 0)}
                      disabled={exportingImageId === "size" || sizeData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: sizeData.length > 0 ? "rgba(59, 130, 246, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: sizeData.length > 0 ? "#2563eb" : "#94a3b8",
                        border: "1px solid rgba(59, 130, 246, 0.25)",
                        cursor: sizeData.length > 0 ? "pointer" : "not-allowed",
                        opacity: sizeData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" />
                        <polyline points="21 15 16 10 5 21" />
                      </svg>
                      {exportingImageId === "size" ? "Saving..." : "Export PNG"}
                    </button>

                    <button
                      type="button"
                      title="Export chart as printable official PDF document"
                      onClick={() =>
                        exportChartAsPdf(
                          "size",
                          "Business Size Classification",
                          "Official breakdown of registered commercial enterprises categorized by enterprise asset scale",
                          sizeData.map((s) => ({
                            Category: s.name,
                            Entities: s.value,
                            Share: `${Math.round((s.value / (totalBySize || 1)) * 100)}%`
                          })),
                          sizeData.length > 0
                        )
                      }
                      disabled={exportingPdfId === "size" || sizeData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: sizeData.length > 0 ? "rgba(16, 185, 129, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: sizeData.length > 0 ? "#059669" : "#94a3b8",
                        border: "1px solid rgba(16, 185, 129, 0.25)",
                        cursor: sizeData.length > 0 ? "pointer" : "not-allowed",
                        opacity: sizeData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="12" y1="18" x2="12" y2="12" />
                        <line x1="9" y1="15" x2="15" y2="15" />
                      </svg>
                      {exportingPdfId === "size" ? "Generating..." : "Export PDF"}
                    </button>
                  </div>
                </div>

                {/* Chart Visual / Empty State */}
                <div style={{ height: 210, width: "100%", position: "relative" }}>
                  {loadingAnalytics ? (
                    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-muted)" }}>
                      Loading demographic data...
                    </div>
                  ) : sizeData.length === 0 ? (
                    <ChartEmptyState
                      title="No Business Size Data"
                      message="Enterprise scale classifications (Micro, Small, Medium, Large) will appear once businesses are registered."
                    />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={sizeData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          innerRadius={55}
                          outerRadius={85}
                          paddingAngle={3}
                          isAnimationActive={false}
                        >
                          {sizeData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.fill} />
                          ))}
                        </Pie>
                        <Tooltip content={<CustomChartTooltip />} />
                      </PieChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Simple Legend with Counts & Percentages */}
                <div
                  style={{
                    marginTop: 14,
                    paddingTop: 12,
                    borderTop: "1px solid rgba(226, 232, 240, 0.7)",
                    display: sizeData.length > 0 ? "grid" : "block",
                    gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
                    gap: "8px 12px"
                  }}
                >
                  {sizeData.length === 0 ? (
                    <div style={{ fontSize: 12, color: "var(--color-muted)", fontStyle: "italic", textAlign: "center" }}>
                      No business size records available.
                    </div>
                  ) : (
                    sizeData.map((s, idx) => {
                      const pct = Math.round((s.value / (totalBySize || 1)) * 100);
                      return (
                        <div key={idx} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12 }}>
                          <span
                            style={{
                              width: 10,
                              height: 10,
                              borderRadius: "50%",
                              background: s.fill,
                              flexShrink: 0
                            }}
                          />
                          <span style={{ color: "var(--color-muted)", flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                            {s.name}
                          </span>
                          <strong style={{ color: "var(--color-ink)" }}>{s.value}</strong>
                          <span style={{ fontSize: 11, color: "var(--color-muted)" }}>({pct}%)</span>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* ── CHART 2: Business Legal Structure (Ownership Type) ── */}
              <div
                id="chart-card-type"
                ref={(el) => (chartRefs.current["type"] = el)}
                className="saas-card frosted-glass"
                style={{
                  padding: 22,
                  borderRadius: 14,
                  display: "flex",
                  flexDirection: "column",
                  position: "relative"
                }}
              >
                {/* Card Header & Export Toolbar */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 16,
                    gap: 12
                  }}
                >
                  <div>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: "var(--color-ink)" }}>
                      Business Legal Structure
                    </h3>
                    <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "4px 0 0" }}>
                      Breakdown by legal entity (Sole Proprietorship, Corporation, Partnership, etc.)
                    </p>
                  </div>

                  <div className="no-export" style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      title="Export chart as high-resolution PNG image"
                      onClick={() => exportChartAsImage("type", "Business_Legal_Structure", typeData.length > 0)}
                      disabled={exportingImageId === "type" || typeData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: typeData.length > 0 ? "rgba(59, 130, 246, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: typeData.length > 0 ? "#2563eb" : "#94a3b8",
                        border: "1px solid rgba(59, 130, 246, 0.25)",
                        cursor: typeData.length > 0 ? "pointer" : "not-allowed",
                        opacity: typeData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" />
                        <polyline points="21 15 16 10 5 21" />
                      </svg>
                      {exportingImageId === "type" ? "Saving..." : "Export PNG"}
                    </button>

                    <button
                      type="button"
                      title="Export chart as printable official PDF document"
                      onClick={() =>
                        exportChartAsPdf(
                          "type",
                          "Business Legal Structure",
                          "Official breakdown of registered commercial enterprises categorized by legal organization structure",
                          typeData.map((t) => ({
                            Structure: t.name,
                            Entities: t.value,
                            Share: `${Math.round((t.value / (totalByType || 1)) * 100)}%`
                          })),
                          typeData.length > 0
                        )
                      }
                      disabled={exportingPdfId === "type" || typeData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: typeData.length > 0 ? "rgba(16, 185, 129, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: typeData.length > 0 ? "#059669" : "#94a3b8",
                        border: "1px solid rgba(16, 185, 129, 0.25)",
                        cursor: typeData.length > 0 ? "pointer" : "not-allowed",
                        opacity: typeData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="12" y1="18" x2="12" y2="12" />
                        <line x1="9" y1="15" x2="15" y2="15" />
                      </svg>
                      {exportingPdfId === "type" ? "Generating..." : "Export PDF"}
                    </button>
                  </div>
                </div>

                {/* Chart Visual / Empty State */}
                <div style={{ height: 210, width: "100%", position: "relative" }}>
                  {loadingAnalytics ? (
                    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-muted)" }}>
                      Loading legal structure data...
                    </div>
                  ) : typeData.length === 0 ? (
                    <ChartEmptyState
                      title="No Legal Structure Data"
                      message="Sole proprietorships, corporations, and partnerships will appear here once registered."
                    />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={typeData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          innerRadius={55}
                          outerRadius={85}
                          paddingAngle={3}
                          isAnimationActive={false}
                        >
                          {typeData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.fill} />
                          ))}
                        </Pie>
                        <Tooltip content={<CustomChartTooltip />} />
                      </PieChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Simple Legend with Counts & Percentages */}
                <div
                  style={{
                    marginTop: 14,
                    paddingTop: 12,
                    borderTop: "1px solid rgba(226, 232, 240, 0.7)",
                    display: typeData.length > 0 ? "grid" : "block",
                    gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
                    gap: "8px 12px"
                  }}
                >
                  {typeData.length === 0 ? (
                    <div style={{ fontSize: 12, color: "var(--color-muted)", fontStyle: "italic", textAlign: "center" }}>
                      No legal structure records available.
                    </div>
                  ) : (
                    typeData.map((t, idx) => {
                      const pct = Math.round((t.value / (totalByType || 1)) * 100);
                      return (
                        <div key={idx} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12 }}>
                          <span
                            style={{
                              width: 10,
                              height: 10,
                              borderRadius: "50%",
                              background: t.fill,
                              flexShrink: 0
                            }}
                          />
                          <span style={{ color: "var(--color-muted)", flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                            {t.name}
                          </span>
                          <strong style={{ color: "var(--color-ink)" }}>{t.value}</strong>
                          <span style={{ fontSize: 11, color: "var(--color-muted)" }}>({pct}%)</span>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* ── CHART 3: Dominant Economic Sectors ── */}
              <div
                id="chart-card-sector"
                ref={(el) => (chartRefs.current["sector"] = el)}
                className="saas-card frosted-glass"
                style={{
                  padding: 22,
                  borderRadius: 14,
                  display: "flex",
                  flexDirection: "column",
                  position: "relative"
                }}
              >
                {/* Card Header & Export Toolbar */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 16,
                    gap: 12
                  }}
                >
                  <div>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: "var(--color-ink)" }}>
                      Top Economic Sectors
                    </h3>
                    <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "4px 0 0" }}>
                      Highest concentration lines of business (Top registered commercial sectors)
                    </p>
                  </div>

                  <div className="no-export" style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      title="Export chart as high-resolution PNG image"
                      onClick={() => exportChartAsImage("sector", "Top_Economic_Sectors", sectoralData.length > 0)}
                      disabled={exportingImageId === "sector" || sectoralData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: sectoralData.length > 0 ? "rgba(59, 130, 246, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: sectoralData.length > 0 ? "#2563eb" : "#94a3b8",
                        border: "1px solid rgba(59, 130, 246, 0.25)",
                        cursor: sectoralData.length > 0 ? "pointer" : "not-allowed",
                        opacity: sectoralData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" />
                        <polyline points="21 15 16 10 5 21" />
                      </svg>
                      {exportingImageId === "sector" ? "Saving..." : "Export PNG"}
                    </button>

                    <button
                      type="button"
                      title="Export chart as printable official PDF document"
                      onClick={() =>
                        exportChartAsPdf(
                          "sector",
                          "Dominant Economic Sectors",
                          "Official distribution ranking of commercial enterprises across top industry sectors and lines of business",
                          sectoralData.slice(0, 8).map((s, idx) => ({
                            Rank: idx + 1,
                            "Sector / Line of Business": s.name,
                            Count: s.value,
                            Share: `${Math.round((s.value / (totalBySector || 1)) * 100)}%`
                          })),
                          sectoralData.length > 0
                        )
                      }
                      disabled={exportingPdfId === "sector" || sectoralData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: sectoralData.length > 0 ? "rgba(16, 185, 129, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: sectoralData.length > 0 ? "#059669" : "#94a3b8",
                        border: "1px solid rgba(16, 185, 129, 0.25)",
                        cursor: sectoralData.length > 0 ? "pointer" : "not-allowed",
                        opacity: sectoralData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="12" y1="18" x2="12" y2="12" />
                        <line x1="9" y1="15" x2="15" y2="15" />
                      </svg>
                      {exportingPdfId === "sector" ? "Generating..." : "Export PDF"}
                    </button>
                  </div>
                </div>

                {/* Chart Visual / Empty State */}
                <div style={{ height: 220, width: "100%" }}>
                  {loadingAnalytics ? (
                    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-muted)" }}>
                      Loading sectoral data...
                    </div>
                  ) : sectoralData.length === 0 ? (
                    <ChartEmptyState
                      title="No Sector Data Available"
                      message="Commercial lines of business and industry sectors will appear here once records are imported."
                    />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={sectoralData.slice(0, 6)}
                        layout="vertical"
                        margin={{ top: 5, right: 25, left: 10, bottom: 5 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="rgba(226, 232, 240, 0.4)" />
                        <XAxis type="number" tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <YAxis
                          dataKey="name"
                          type="category"
                          width={140}
                          tickFormatter={(v) => (v.length > 20 ? `${v.substring(0, 20)}...` : v)}
                          tick={{ fontSize: 11, fill: "var(--color-muted)" }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <Tooltip content={<CustomChartTooltip />} />
                        <Bar dataKey="value" name="Registered Count" radius={[0, 4, 4, 0]}>
                          {sectoralData.slice(0, 6).map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={SECTOR_COLORS[index % SECTOR_COLORS.length]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Simple Legend with Top Sectors Summary */}
                <div
                  style={{
                    marginTop: 14,
                    paddingTop: 12,
                    borderTop: "1px solid rgba(226, 232, 240, 0.7)",
                    display: sectoralData.length > 0 ? "flex" : "block",
                    flexWrap: "wrap",
                    gap: "8px 16px"
                  }}
                >
                  {sectoralData.length === 0 ? (
                    <div style={{ fontSize: 12, color: "var(--color-muted)", fontStyle: "italic", textAlign: "center" }}>
                      No commercial sector records reported yet.
                    </div>
                  ) : (
                    sectoralData.slice(0, 4).map((s, idx) => (
                      <div key={idx} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                        <span style={{ width: 8, height: 8, borderRadius: 2, background: SECTOR_COLORS[idx % SECTOR_COLORS.length] }} />
                        <span style={{ color: "var(--color-muted)" }}>{s.name}:</span>
                        <strong style={{ color: "var(--color-ink)" }}>{s.value}</strong>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* ── CHART 4: Geographic Spread Across Barangays ── */}
              <div
                id="chart-card-barangay"
                ref={(el) => (chartRefs.current["barangay"] = el)}
                className="saas-card frosted-glass"
                style={{
                  padding: 22,
                  borderRadius: 14,
                  display: "flex",
                  flexDirection: "column",
                  position: "relative"
                }}
              >
                {/* Card Header & Export Toolbar */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 16,
                    gap: 12
                  }}
                >
                  <div>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: "var(--color-ink)" }}>
                      Geographic Spread Across Barangays
                    </h3>
                    <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "4px 0 0" }}>
                      Commercial establishment distribution across all Barangays of Mataasnakahoy
                    </p>
                  </div>

                  <div className="no-export" style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      title="Export chart as high-resolution PNG image"
                      onClick={() => exportChartAsImage("barangay", "Geographic_Spread_Barangays", barangaySpreadData.length > 0)}
                      disabled={exportingImageId === "barangay" || barangaySpreadData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: barangaySpreadData.length > 0 ? "rgba(59, 130, 246, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: barangaySpreadData.length > 0 ? "#2563eb" : "#94a3b8",
                        border: "1px solid rgba(59, 130, 246, 0.25)",
                        cursor: barangaySpreadData.length > 0 ? "pointer" : "not-allowed",
                        opacity: barangaySpreadData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" />
                        <polyline points="21 15 16 10 5 21" />
                      </svg>
                      {exportingImageId === "barangay" ? "Saving..." : "Export PNG"}
                    </button>

                    <button
                      type="button"
                      title="Export chart as printable official PDF document"
                      onClick={() =>
                        exportChartAsPdf(
                          "barangay",
                          "Geographic Spread Across Barangays",
                          "Official spatial distribution and density analysis of registered commercial entities per Barangay",
                          barangaySpreadData.map((b) => ({
                            Barangay: b.fullName,
                            "Registered Count": b.total,
                            Share: `${Math.round((b.total / (totalBusinessesAcrossBarangays || 1)) * 100)}%`
                          })),
                          barangaySpreadData.length > 0
                        )
                      }
                      disabled={exportingPdfId === "barangay" || barangaySpreadData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: barangaySpreadData.length > 0 ? "rgba(16, 185, 129, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: barangaySpreadData.length > 0 ? "#059669" : "#94a3b8",
                        border: "1px solid rgba(16, 185, 129, 0.25)",
                        cursor: barangaySpreadData.length > 0 ? "pointer" : "not-allowed",
                        opacity: barangaySpreadData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="12" y1="18" x2="12" y2="12" />
                        <line x1="9" y1="15" x2="15" y2="15" />
                      </svg>
                      {exportingPdfId === "barangay" ? "Generating..." : "Export PDF"}
                    </button>
                  </div>
                </div>

                {/* Chart Visual / Empty State */}
                <div style={{ height: 220, width: "100%" }}>
                  {loadingAnalytics ? (
                    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-muted)" }}>
                      Loading geographic distribution...
                    </div>
                  ) : barangaySpreadData.length === 0 ? (
                    <ChartEmptyState
                      title="No Barangay Data Available"
                      message="Establishment density per barangay will display once location data is mapped."
                    />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={barangaySpreadData} margin={{ top: 10, right: 10, left: -20, bottom: 45 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226, 232, 240, 0.4)" />
                        <XAxis
                          dataKey="barangayName"
                          tick={{ fontSize: 10, fill: "var(--color-muted)" }}
                          axisLine={false}
                          tickLine={false}
                          interval={0}
                          angle={-45}
                          textAnchor="end"
                        />
                        <YAxis tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <Tooltip content={<CustomChartTooltip />} />
                        <Bar dataKey="total" name="Registered Establishments" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Simple Legend Note */}
                <div
                  style={{
                    marginTop: 14,
                    paddingTop: 12,
                    borderTop: "1px solid rgba(226, 232, 240, 0.7)",
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 12,
                    color: "var(--color-muted)"
                  }}
                >
                  <span>
                    Barangays Active: <strong>{barangaySpreadData.length}</strong>
                  </span>
                  <span>
                    Total Census Units: <strong>{totalBusinessesAcrossBarangays}</strong>
                  </span>
                </div>
              </div>

              {/* ── CHART 5: Compliance by Business Size ── */}
              <div
                id="chart-card-compliance_size"
                ref={(el) => (chartRefs.current["compliance_size"] = el)}
                className="saas-card frosted-glass"
                style={{
                  padding: 22,
                  borderRadius: 14,
                  display: "flex",
                  flexDirection: "column",
                  position: "relative"
                }}
              >
                {/* Card Header & Export Toolbar */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 16,
                    gap: 12
                  }}
                >
                  <div>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: "var(--color-ink)" }}>
                      Compliance by Business Size
                    </h3>
                    <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "4px 0 0" }}>
                      Active valid registrations vs non-active/expired permit backlog by scale
                    </p>
                  </div>

                  <div className="no-export" style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      title="Export chart as high-resolution PNG image"
                      onClick={() => exportChartAsImage("compliance_size", "Compliance_By_Business_Size", complianceBySizeData.length > 0)}
                      disabled={exportingImageId === "compliance_size" || complianceBySizeData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: complianceBySizeData.length > 0 ? "rgba(59, 130, 246, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: complianceBySizeData.length > 0 ? "#2563eb" : "#94a3b8",
                        border: "1px solid rgba(59, 130, 246, 0.25)",
                        cursor: complianceBySizeData.length > 0 ? "pointer" : "not-allowed",
                        opacity: complianceBySizeData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" />
                        <polyline points="21 15 16 10 5 21" />
                      </svg>
                      {exportingImageId === "compliance_size" ? "Saving..." : "Export PNG"}
                    </button>

                    <button
                      type="button"
                      title="Export chart as printable official PDF document"
                      onClick={() =>
                        exportChartAsPdf(
                          "compliance_size",
                          "Compliance by Business Size",
                          "Comparative analysis of active permit status versus expired/inactive non-compliance across enterprise size tiers",
                          complianceBySizeData.map((c) => ({
                            Tier: c.name,
                            Active: c.Active,
                            "Non-Active": c["Non-Active"],
                            "Compliance Rate": `${c.rate}%`
                          })),
                          complianceBySizeData.length > 0
                        )
                      }
                      disabled={exportingPdfId === "compliance_size" || complianceBySizeData.length === 0}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: complianceBySizeData.length > 0 ? "rgba(16, 185, 129, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: complianceBySizeData.length > 0 ? "#059669" : "#94a3b8",
                        border: "1px solid rgba(16, 185, 129, 0.25)",
                        cursor: complianceBySizeData.length > 0 ? "pointer" : "not-allowed",
                        opacity: complianceBySizeData.length > 0 ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="12" y1="18" x2="12" y2="12" />
                        <line x1="9" y1="15" x2="15" y2="15" />
                      </svg>
                      {exportingPdfId === "compliance_size" ? "Generating..." : "Export PDF"}
                    </button>
                  </div>
                </div>

                {/* Chart Visual / Empty State */}
                <div style={{ height: 210, width: "100%" }}>
                  {loadingAnalytics ? (
                    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-muted)" }}>
                      Loading compliance data...
                    </div>
                  ) : complianceBySizeData.length === 0 ? (
                    <ChartEmptyState
                      title="No Compliance Data"
                      message="Active versus expired permit breakdowns will display once compliance logs are generated."
                    />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={complianceBySizeData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226, 232, 240, 0.4)" />
                        <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <Tooltip content={<CustomChartTooltip />} />
                        <Bar dataKey="Active" stackId="a" fill="#10b981" radius={[0, 0, 0, 0]} />
                        <Bar dataKey="Non-Active" stackId="a" fill="#ef4444" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Simple Legend with Clean Key Indicators */}
                <div
                  style={{
                    marginTop: 14,
                    paddingTop: 12,
                    borderTop: "1px solid rgba(226, 232, 240, 0.7)",
                    display: complianceBySizeData.length > 0 ? "flex" : "block",
                    alignItems: "center",
                    justifyContent: "space-between",
                    fontSize: 12
                  }}
                >
                  {complianceBySizeData.length === 0 ? (
                    <div style={{ fontSize: 12, color: "var(--color-muted)", fontStyle: "italic", textAlign: "center" }}>
                      No compliance status records available.
                    </div>
                  ) : (
                    <>
                      <div style={{ display: "flex", gap: 16 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ width: 10, height: 10, borderRadius: 2, background: "#10b981" }} />
                          <span style={{ color: "var(--color-muted)" }}>Active / Compliant</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ width: 10, height: 10, borderRadius: 2, background: "#ef4444" }} />
                          <span style={{ color: "var(--color-muted)" }}>Non-Active / Expired</span>
                        </div>
                      </div>
                      <span style={{ color: "var(--color-muted)", fontSize: 11 }}>Stacked comparison</span>
                    </>
                  )}
                </div>
              </div>

              {/* ── CHART 6: 12-Month Renewal & Compliance Trajectory ── */}
              <div
                id="chart-card-timeline"
                ref={(el) => (chartRefs.current["timeline"] = el)}
                className="saas-card frosted-glass"
                style={{
                  padding: 22,
                  borderRadius: 14,
                  display: "flex",
                  flexDirection: "column",
                  position: "relative"
                }}
              >
                {/* Card Header & Export Toolbar */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 16,
                    gap: 12
                  }}
                >
                  <div>
                    <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: "var(--color-ink)" }}>
                      12-Month Renewal &amp; Compliance Trend
                    </h3>
                    <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "4px 0 0" }}>
                      Monthly active permit renewals versus non-renewed backlog trajectory
                    </p>
                  </div>

                  <div className="no-export" style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      title="Export chart as high-resolution PNG image"
                      onClick={() => exportChartAsImage("timeline", "Compliance_Timeline_Trend", hasTimelineData)}
                      disabled={exportingImageId === "timeline" || !hasTimelineData}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: hasTimelineData ? "rgba(59, 130, 246, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: hasTimelineData ? "#2563eb" : "#94a3b8",
                        border: "1px solid rgba(59, 130, 246, 0.25)",
                        cursor: hasTimelineData ? "pointer" : "not-allowed",
                        opacity: hasTimelineData ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                        <circle cx="8.5" cy="8.5" r="1.5" />
                        <polyline points="21 15 16 10 5 21" />
                      </svg>
                      {exportingImageId === "timeline" ? "Saving..." : "Export PNG"}
                    </button>

                    <button
                      type="button"
                      title="Export chart as printable official PDF document"
                      onClick={() =>
                        exportChartAsPdf(
                          "timeline",
                          "12-Month Compliance & Renewal Trend",
                          "Chronological trajectory of monthly business permit renewal volumes and non-renewal intervals over the past 12 months",
                          timelineData.map((t) => ({
                            Month: t.month,
                            "Active Renewals": t.Active,
                            "Non-Active Gap": t["Non-Active"]
                          })),
                          hasTimelineData
                        )
                      }
                      disabled={exportingPdfId === "timeline" || !hasTimelineData}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 5,
                        fontSize: 11.5,
                        fontWeight: 600,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: hasTimelineData ? "rgba(16, 185, 129, 0.08)" : "rgba(0, 0, 0, 0.04)",
                        color: hasTimelineData ? "#059669" : "#94a3b8",
                        border: "1px solid rgba(16, 185, 129, 0.25)",
                        cursor: hasTimelineData ? "pointer" : "not-allowed",
                        opacity: hasTimelineData ? 1 : 0.6
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" strokeWidth="2" fill="none">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="12" y1="18" x2="12" y2="12" />
                        <line x1="9" y1="15" x2="15" y2="15" />
                      </svg>
                      {exportingPdfId === "timeline" ? "Generating..." : "Export PDF"}
                    </button>
                  </div>
                </div>

                {/* Chart Visual / Empty State */}
                <div style={{ height: 210, width: "100%" }}>
                  {loadingAnalytics ? (
                    <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-muted)" }}>
                      Loading trend data...
                    </div>
                  ) : !hasTimelineData ? (
                    <ChartEmptyState
                      title="No Renewal Trend Logged"
                      message="Monthly registration and renewal trends will trace dynamically once recorded."
                    />
                  ) : (
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
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(226, 232, 240, 0.4)" />
                        <XAxis dataKey="month" tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                        <Tooltip content={<CustomChartTooltip />} />
                        <Area type="monotone" dataKey="Active" name="Active Renewals" stroke="#10b981" fillOpacity={1} fill="url(#colorActive)" />
                        <Area type="monotone" dataKey="Non-Active" name="Non-Active Backlog" stroke="#f43f5e" fillOpacity={1} fill="url(#colorNonActive)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Simple Legend with Clean Key Indicators */}
                <div
                  style={{
                    marginTop: 14,
                    paddingTop: 12,
                    borderTop: "1px solid rgba(226, 232, 240, 0.7)",
                    display: hasTimelineData ? "flex" : "block",
                    alignItems: "center",
                    justifyContent: "space-between",
                    fontSize: 12
                  }}
                >
                  {!hasTimelineData ? (
                    <div style={{ fontSize: 12, color: "var(--color-muted)", fontStyle: "italic", textAlign: "center" }}>
                      No renewal timeline intervals available.
                    </div>
                  ) : (
                    <>
                      <div style={{ display: "flex", gap: 16 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#10b981" }} />
                          <span style={{ color: "var(--color-muted)" }}>Active Permits</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#f43f5e" }} />
                          <span style={{ color: "var(--color-muted)" }}>Non-Active Backlog</span>
                        </div>
                      </div>
                      <span style={{ color: "var(--color-muted)", fontSize: 11 }}>12-month window</span>
                    </>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* ══════════════════════════════════════════════════════════════════════
              SECTION 2: FIELD OPERATIONS & DISPATCH REPORTS
              (Strictly includes Top Unregistered Establishments & Inspector Dispatch Plan)
          ══════════════════════════════════════════════════════════════════════ */}
          <section style={{ marginBottom: 40 }}>
            {/* Section Header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 18,
                paddingBottom: 10,
                borderBottom: "2px solid rgba(226, 232, 240, 0.7)"
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span
                    style={{
                      background: "#3b82f6",
                      color: "#fff",
                      fontWeight: 800,
                      fontSize: 12,
                      padding: "3px 8px",
                      borderRadius: 6
                    }}
                  >
                    Section 2
                  </span>
                  <h2 style={{ fontSize: 19, fontWeight: 800, margin: 0, color: "var(--color-ink)" }}>
                    Operational &amp; Dispatch Reports
                  </h2>
                </div>
                <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--color-muted)" }}>
                  Official municipal operational intelligence for field inspectors and enforcement teams.
                </p>
              </div>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "var(--color-muted)",
                  background: "rgba(0,0,0,0.04)",
                  padding: "4px 10px",
                  borderRadius: 6
                }}
              >
                Formats: PDF &bull; CSV
              </span>
            </div>

            {/* Operational Reports List (Strictly 2 cards) */}
            <div style={{ display: "grid", gap: 16 }}>
              {OPERATIONAL_REPORTS.map((report) => (
                <div
                  key={report.id}
                  className="saas-card frosted-glass"
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "20px 24px",
                    borderRadius: 12,
                    gap: 20
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                      <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--color-ink)" }}>
                        {report.title}
                      </h3>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          padding: "2px 8px",
                          borderRadius: 4,
                          color: report.tagColor,
                          background: report.tagBg
                        }}
                      >
                        {report.tag}
                      </span>
                    </div>
                    <p style={{ margin: 0, color: "var(--color-muted)", fontSize: 13, lineHeight: 1.5 }}>
                      {report.desc}
                    </p>
                  </div>

                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexShrink: 0 }}>
                    <button
                      className="primary-btn"
                      type="button"
                      onClick={() => handleDownloadOperational(report)}
                      disabled={operationalLoadingId === report.id}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        fontSize: 13,
                        padding: "10px 18px",
                        borderRadius: 8,
                        fontWeight: 600,
                        cursor: "pointer"
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="15" height="15" stroke="currentColor" strokeWidth="2" fill="none">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      {operationalLoadingId === report.id ? "Generating..." : "Download Report"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Footer */}
          <footer className="saas-footer frosted-glass" style={{ marginTop: 40 }}>
            <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
            <p className="footer-links">
              <span>BPLO Portal</span> &bull; <span>Compliance Analytics</span>
            </p>
          </footer>
        </DashboardLayout>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          PRINTABLE REPORT VIEW (Visible ONLY during window.print())
      ══════════════════════════════════════════════════════════════════════ */}
      {printReport && (
        <div className="print-report-container hidden print:block bg-white text-black font-sans w-full">
          {/* Custom Print CSS */}
          <style>{`
            @media print {
              @page {
                size: ${printReport.isLandscape ? "landscape" : "portrait"};
                margin: 0;
              }

              /* Hide the entire application UI and all screen elements completely */
              .screen-only,
              .no-print,
              .mobile-toggle,
              aside,
              header,
              nav,
              footer,
              section,
              .ambient-bg-mesh,
              .page-header,
              .saas-footer,
              .saas-root,
              .saas-main,
              .saas-content,
              .saas-layout,
              .saas-card,
              .swal2-container,
              button,
              .no-export {
                display: none !important;
                visibility: hidden !important;
                height: 0 !important;
                max-height: 0 !important;
                overflow: hidden !important;
                margin: 0 !important;
                padding: 0 !important;
                border: none !important;
                box-shadow: none !important;
              }

              /* Reset parent elements so only print container is rendered */
              html, body, #root {
                height: auto !important;
                min-height: auto !important;
                max-height: none !important;
                overflow: visible !important;
                display: block !important;
                position: static !important;
                background: #fff !important;
                color: #000 !important;
                margin: 0 !important;
                padding: 0 !important;
                width: 100% !important;
                max-width: 100% !important;
                box-shadow: none !important;
                border: none !important;
              }

              .print-report-container {
                display: block !important;
                visibility: visible !important;
                background: #fff !important;
                width: 100% !important;
                margin: 0 !important;
                padding: 0 !important;
                position: relative !important;
              }

              /* Pinned official header on every page */
              .print-header {
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                background: #fff !important;
                z-index: 1000 !important;
                padding: 12mm 15mm 5mm 15mm !important;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
              }

              /* Pinned official footer on every page */
              .print-footer {
                position: fixed !important;
                bottom: 0 !important;
                left: 0 !important;
                right: 0 !important;
                background: #fff !important;
                z-index: 1000 !important;
                padding: 3mm 15mm 8mm 15mm !important;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
              }

              .report-body {
                margin-top: 105px !important;
                margin-bottom: 85px !important;
                padding: 0 15mm !important;
              }

              .print-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 12px;
                margin-bottom: 20px;
                page-break-inside: auto;
              }
              .print-table tr { page-break-inside: avoid; page-break-after: auto; }
              .print-table th, .print-table td {
                border: 1px solid #cbd5e1;
                padding: 7px 11px;
                text-align: left;
                font-size: 11px;
              }
              .print-table th {
                font-weight: bold;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
              }
              .print-table tr:nth-child(even) td {
                background-color: #f8fafc !important;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
              }

              body { counter-reset: page; }
              .print-page-number::after {
                counter-increment: page;
                content: "Page " counter(page);
              }

              .page-break-avoid { page-break-inside: avoid; }
            }
          `}</style>

          {/* ── FIXED OFFICIAL HEADER ── */}
          <div className="print-header">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", paddingBottom: "10px" }}>
              <div style={{ width: "72px", textAlign: "left", flexShrink: 0 }}>
                <img src={sealImg} alt="Mataasnakahoy Seal" style={{ width: "62px", height: "62px", objectFit: "contain" }} />
              </div>

              <div style={{ textAlign: "center", flex: 1, margin: "0 16px" }}>
                <div style={{ fontSize: "10.5px", textTransform: "uppercase", color: "#4b5563", fontWeight: "500", lineHeight: "1.5" }}>Republic of the Philippines</div>
                <div style={{ fontSize: "10.5px", color: "#4b5563", lineHeight: "1.5" }}>Province of Batangas</div>
                <div style={{ fontSize: "13px", color: "#111827", marginTop: "2px", lineHeight: "1.5" }}>Municipality of Mataasnakahoy</div>
                <div style={{ fontSize: "13px", fontWeight: "800", color: "#111827", textTransform: "uppercase", letterSpacing: "0.5px", lineHeight: "1.5" }}>Office of the Municipal Mayor</div>
                <div style={{ fontSize: "10px", color: "#4b5563", marginTop: "3px", lineHeight: "1.6" }}>
                  Telephone #: <span style={{ fontWeight: 600, color: "#111827" }}>461-2374</span> &bull; Email: <span style={{ fontWeight: 400, color: "#111827" }}>licensingoffice2374@yahoo.com</span>
                </div>
              </div>

              <div style={{ width: "72px", textAlign: "right", flexShrink: 0 }}>
                <img src={bpLogo} alt="Bagong Pilipinas Logo" style={{ width: "62px", height: "62px", objectFit: "contain" }} />
              </div>
            </div>
            <div style={{ borderBottom: "1.5px solid #e5e7eb", marginTop: "6px" }}></div>
          </div>

          {/* ── REPORT CONTENT BODY ── */}
          <div className="report-body">
            {/* Title */}
            <h2 style={{ fontSize: "15px", fontWeight: "bold", textAlign: "center", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              {printReport.title}
            </h2>

            {/* Subtitle */}
            {printReport.subtitle && (
              <p style={{ fontSize: "11px", color: "#6b7280", fontStyle: "italic", textAlign: "center", marginBottom: "16px" }}>
                {printReport.subtitle}
              </p>
            )}

            {/* Metadata Section */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "8px 24px",
                background: "#f8fafc",
                border: "1px solid #e2e8f0",
                borderRadius: "8px",
                padding: "12px 16px",
                marginBottom: "20px",
                fontSize: "11px"
              }}
            >
              <div>
                <span style={{ fontWeight: "bold", color: "#6b7280", marginRight: "6px" }}>DATE GENERATED:</span>
                <span style={{ color: "#111827", fontWeight: "500" }}>{printReport.date}</span>
              </div>
              <div>
                <span style={{ fontWeight: "bold", color: "#6b7280", marginRight: "6px" }}>OFFICE:</span>
                <span style={{ color: "#111827", fontWeight: "500" }}>{printReport.office}</span>
              </div>
              <div>
                <span style={{ fontWeight: "bold", color: "#6b7280", marginRight: "6px" }}>PREPARED BY:</span>
                <span style={{ color: "#111827", fontWeight: "500" }}>{printReport.preparedBy}</span>
              </div>
              <div>
                <span style={{ fontWeight: "bold", color: "#6b7280", marginRight: "6px" }}>CLASSIFICATION:</span>
                <span style={{ color: "#111827", fontWeight: "500" }}>{printReport.classification}</span>
              </div>
            </div>

            {/* ── CASE 1: Single Demographic Chart Report ── */}
            {printReport.type === "demographic-single" && (
              <div>
                {/* Captured Visual Chart */}
                {printReport.chartImage && (
                  <div style={{ textAlign: "center", marginBottom: 24 }}>
                    <img
                      src={printReport.chartImage}
                      alt="Demographic Chart Visual"
                      style={{
                        maxWidth: "100%",
                        maxHeight: "360px",
                        objectFit: "contain",
                        margin: "0 auto",
                        display: "block",
                        borderRadius: "8px",
                        border: "1px solid #e2e8f0"
                      }}
                    />
                  </div>
                )}

                {/* Summary Table with Empty State */}
                <div className="page-break-avoid">
                  <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Demographic Breakdown Summary
                  </h3>
                  {printReport.summaryTable && printReport.summaryTable.length > 0 ? (
                    <table className="print-table">
                      <thead>
                        <tr>
                          {Object.keys(printReport.summaryTable[0]).map((col, idx) => (
                            <th key={idx} style={{ background: "#10b981", color: "#fff" }}>
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {printReport.summaryTable.map((row, rIdx) => (
                          <tr key={rIdx}>
                            {Object.values(row).map((val, cIdx) => (
                              <td key={cIdx} style={cIdx === 0 ? { fontWeight: "600", color: "#111827" } : {}}>
                                {val}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <table className="print-table">
                      <tbody>
                        <tr>
                          <td style={{ textAlign: "center", padding: "16px", color: "#64748b", fontStyle: "italic", background: "#f8fafc" }}>
                            No registered business establishments logged under this demographic category.
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            )}

            {/* ── CASE 2: Complete Demographic Profile Dossier ── */}
            {printReport.type === "demographic-complete" && (
              <div>
                {/* Census KPIs Table */}
                <div style={{ marginBottom: 20 }}>
                  <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    I. Business Census Key Performance Indicators
                  </h3>
                  <table className="print-table">
                    <thead>
                      <tr>
                        <th style={{ background: "#10b981", color: "#fff" }}>Demographic Indicator</th>
                        <th style={{ background: "#10b981", color: "#fff", width: "160px" }}>Reported Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {printReport.data.kpis.map((k, idx) => (
                        <tr key={idx}>
                          <td>{k.Metric}</td>
                          <td style={{ fontWeight: "700", color: "#111827" }}>{k.Value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Size Distribution */}
                <div style={{ marginBottom: 20 }} className="page-break-avoid">
                  <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    II. Business Size Classification
                  </h3>
                  <table className="print-table">
                    <thead>
                      <tr>
                        <th style={{ background: "#8b5cf6", color: "#fff" }}>Classification</th>
                        <th style={{ background: "#8b5cf6", color: "#fff", width: "120px" }}>Entity Count</th>
                        <th style={{ background: "#8b5cf6", color: "#fff", width: "120px" }}>Percentage Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {printReport.data.sizeDistribution.length === 0 ? (
                        <tr>
                          <td colSpan={3} style={{ textAlign: "center", padding: "14px", color: "#64748b", fontStyle: "italic", background: "#f8fafc" }}>
                            No business size classification records currently found in the registry.
                          </td>
                        </tr>
                      ) : (
                        printReport.data.sizeDistribution.map((s, idx) => (
                          <tr key={idx}>
                            <td style={{ fontWeight: "600" }}>{s.Classification}</td>
                            <td>{s.Count}</td>
                            <td style={{ fontWeight: "600" }}>{s.Percentage}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Legal Structure */}
                <div style={{ marginBottom: 20 }} className="page-break-avoid">
                  <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    III. Business Legal Structure Distribution
                  </h3>
                  <table className="print-table">
                    <thead>
                      <tr>
                        <th style={{ background: "#14b8a6", color: "#fff" }}>Legal Structure Type</th>
                        <th style={{ background: "#14b8a6", color: "#fff", width: "120px" }}>Registered Count</th>
                        <th style={{ background: "#14b8a6", color: "#fff", width: "120px" }}>Percentage Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {printReport.data.typeDistribution.length === 0 ? (
                        <tr>
                          <td colSpan={3} style={{ textAlign: "center", padding: "14px", color: "#64748b", fontStyle: "italic", background: "#f8fafc" }}>
                            No legal structure records currently found in the registry.
                          </td>
                        </tr>
                      ) : (
                        printReport.data.typeDistribution.map((t, idx) => (
                          <tr key={idx}>
                            <td style={{ fontWeight: "600" }}>{t["Legal Structure"]}</td>
                            <td>{t.Count}</td>
                            <td style={{ fontWeight: "600" }}>{t.Percentage}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Top Sectors */}
                <div style={{ marginBottom: 20 }} className="page-break-avoid">
                  <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    IV. Top Commercial Lines of Business (Sectors)
                  </h3>
                  <table className="print-table">
                    <thead>
                      <tr>
                        <th style={{ background: "#3b82f6", color: "#fff", width: "60px" }}>Rank</th>
                        <th style={{ background: "#3b82f6", color: "#fff" }}>Economic Sector / Industry</th>
                        <th style={{ background: "#3b82f6", color: "#fff", width: "120px" }}>Entities Count</th>
                        <th style={{ background: "#3b82f6", color: "#fff", width: "120px" }}>Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {printReport.data.topSectors.length === 0 ? (
                        <tr>
                          <td colSpan={4} style={{ textAlign: "center", padding: "14px", color: "#64748b", fontStyle: "italic", background: "#f8fafc" }}>
                            No commercial sector lines of business records currently found in the registry.
                          </td>
                        </tr>
                      ) : (
                        printReport.data.topSectors.map((s, idx) => (
                          <tr key={idx}>
                            <td style={{ fontWeight: "bold" }}>#{s.Rank}</td>
                            <td style={{ fontWeight: "600" }}>{s.Sector}</td>
                            <td>{s.Count}</td>
                            <td style={{ fontWeight: "600" }}>{s.Share}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Geographic Density */}
                <div style={{ marginBottom: 20 }} className="page-break-avoid">
                  <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    V. Barangay Establishment Density Breakdown
                  </h3>
                  <table className="print-table">
                    <thead>
                      <tr>
                        <th style={{ background: "#059669", color: "#fff" }}>Barangay</th>
                        <th style={{ background: "#059669", color: "#fff", width: "140px" }}>Registered Entities</th>
                        <th style={{ background: "#059669", color: "#fff", width: "120px" }}>Municipality Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {printReport.data.barangayDensity.length === 0 ? (
                        <tr>
                          <td colSpan={3} style={{ textAlign: "center", padding: "14px", color: "#64748b", fontStyle: "italic", background: "#f8fafc" }}>
                            No barangay establishment density records currently found in the registry.
                          </td>
                        </tr>
                      ) : (
                        printReport.data.barangayDensity.map((b, idx) => (
                          <tr key={idx}>
                            <td style={{ fontWeight: "600" }}>{b.Barangay}</td>
                            <td>{b["Registered Entities"]}</td>
                            <td style={{ fontWeight: "600" }}>{b.Share}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Compliance by Size */}
                <div style={{ marginBottom: 20 }} className="page-break-avoid">
                  <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    VI. Compliance Status by Business Size Tier
                  </h3>
                  <table className="print-table">
                    <thead>
                      <tr>
                        <th style={{ background: "#f59e0b", color: "#fff" }}>Classification Tier</th>
                        <th style={{ background: "#f59e0b", color: "#fff", width: "110px" }}>Active</th>
                        <th style={{ background: "#f59e0b", color: "#fff", width: "110px" }}>Non-Active</th>
                        <th style={{ background: "#f59e0b", color: "#fff", width: "130px" }}>Compliance Rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {printReport.data.complianceBySize.length === 0 ? (
                        <tr>
                          <td colSpan={4} style={{ textAlign: "center", padding: "14px", color: "#64748b", fontStyle: "italic", background: "#f8fafc" }}>
                            No compliance audit status records currently found in the registry.
                          </td>
                        </tr>
                      ) : (
                        printReport.data.complianceBySize.map((c, idx) => (
                          <tr key={idx}>
                            <td style={{ fontWeight: "600" }}>{c.Classification}</td>
                            <td>{c.Active}</td>
                            <td>{c["Non-Active"]}</td>
                            <td style={{ fontWeight: "700" }}>{c["Compliance Rate"]}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* ── CASE 3: List of Unregistered Businesses ── */}
            {printReport.type === "unregistered" && (
              <div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px", marginBottom: "16px" }}>
                  <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "8px", padding: "10px" }}>
                    <div style={{ fontSize: "9px", fontWeight: "bold", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                      Total Flagged Locations
                    </div>
                    <div style={{ fontSize: "13px", fontWeight: "bold", color: "#0f172a", marginTop: "4px" }}>
                      {printReport.data.summary.total} Suspected Entities
                    </div>
                  </div>
                  <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", padding: "10px" }}>
                    <div style={{ fontSize: "9px", fontWeight: "bold", color: "#dc2626", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                      Unregistered Commercial (Red)
                    </div>
                    <div style={{ fontSize: "13px", fontWeight: "bold", color: "#7f1d1d", marginTop: "4px" }}>
                      {printReport.data.summary.red} Confirmed Locations
                    </div>
                  </div>
                  <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: "8px", padding: "10px" }}>
                    <div style={{ fontSize: "9px", fontWeight: "bold", color: "#d97706", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                      Suspected Compliance Gap (Yellow)
                    </div>
                    <div style={{ fontSize: "13px", fontWeight: "bold", color: "#92400e", marginTop: "4px" }}>
                      {printReport.data.summary.yellow} Potential Violations
                    </div>
                  </div>
                </div>

                <table className="print-table">
                  <thead>
                    <tr>
                      <th style={{ background: "#ef4444", color: "#fff" }}>Establishment Name</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "130px" }}>Barangay</th>
                      <th style={{ background: "#ef4444", color: "#fff" }}>Resolved Address / Nearest Landmark</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "100px" }}>Flag Status</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "95px" }}>Date Detected</th>
                    </tr>
                  </thead>
                  <tbody>
                    {printReport.data.flags.length === 0 ? (
                      <tr>
                        <td colSpan={5} style={{ textAlign: "center", padding: "16px", color: "#64748b", fontStyle: "italic", background: "#f8fafc" }}>
                          No active suspected unregistered businesses detected in the municipality.
                        </td>
                      </tr>
                    ) : (
                      printReport.data.flags.map((f, idx) => (
                        <tr key={idx}>
                          <td style={{ fontWeight: "600", color: "#111827" }}>{f.Name}</td>
                          <td>{f.Barangay}</td>
                          <td style={{ fontSize: "10.5px" }}>{f.Address}</td>
                          <td>
                            <span
                              style={{
                                padding: "2px 6px",
                                borderRadius: "4px",
                                fontSize: "10px",
                                fontWeight: "bold",
                                background: f.Status === "Unregistered" ? "#fee2e2" : "#fef3c7",
                                color: f.Status === "Unregistered" ? "#b91c1c" : "#b45309"
                              }}
                            >
                              {f.Status}
                            </span>
                          </td>
                          <td>{f.DetectedDate}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* ── CASE 4: Field Inspector Dispatch Plan ── */}
            {printReport.type === "dispatch" && (
              <div>
                <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                  Barangay Priority Rankings (WLC Score Model)
                </h3>
                <table className="print-table">
                  <thead>
                    <tr>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "48px" }}>Rank</th>
                      <th style={{ background: "#3b82f6", color: "#fff" }}>Barangay Name</th>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "100px" }}>WLC OPS Score</th>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "90px" }}>Risk Level</th>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "90px" }}>Flag Count</th>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "110px" }}>Non-Compliance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {printReport.data.rankings.length === 0 ? (
                      <tr>
                        <td colSpan={6} style={{ textAlign: "center", padding: "16px", color: "#64748b", fontStyle: "italic", background: "#f8fafc" }}>
                          No operational dispatch rankings currently calculated.
                        </td>
                      </tr>
                    ) : (
                      printReport.data.rankings.map((r, idx) => (
                        <tr key={idx}>
                          <td style={{ fontWeight: "bold", color: "#111827" }}>Rank {r.Rank}</td>
                          <td style={{ fontWeight: "600", color: "#111827" }}>{r.Barangay}</td>
                          <td>{r.PriorityScore}</td>
                          <td>
                            <span
                              style={{
                                padding: "2px 6px",
                                borderRadius: "4px",
                                fontSize: "10px",
                                fontWeight: "bold",
                                background: r.RiskLevel === "High" ? "#fee2e2" : r.RiskLevel === "Medium" ? "#fef3c7" : "#dcfce7",
                                color: r.RiskLevel === "High" ? "#b91c1c" : r.RiskLevel === "Medium" ? "#b45309" : "#166534"
                              }}
                            >
                              {r.RiskLevel}
                            </span>
                          </td>
                          <td>{r.TotalFlagged}</td>
                          <td style={{ fontWeight: "600", color: "#111827" }}>{r.NonComplianceRate}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>

                {printReport.data.recommendations?.length > 0 && (
                  <div className="page-break-avoid">
                    <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "#111827", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                      Actionable Dispatch Recommendations &amp; Inspector Allocations
                    </h3>
                    <table className="print-table">
                      <thead>
                        <tr>
                          <th style={{ background: "#3b82f6", color: "#fff", width: "60px" }}>Rank</th>
                          <th style={{ background: "#3b82f6", color: "#fff", width: "150px" }}>Priority Barangay</th>
                          <th style={{ background: "#3b82f6", color: "#fff" }}>Actionable Recommendation Plan</th>
                        </tr>
                      </thead>
                      <tbody>
                        {printReport.data.recommendations.map((rec, idx) => (
                          <tr key={idx}>
                            <td style={{ fontWeight: "bold", color: "#111827" }}>Rank {rec.rank}</td>
                            <td style={{ fontWeight: "600", color: "#111827" }}>{rec.barangayName}</td>
                            <td>{rec.recommendation}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* ── Official Signature Block ── */}
            <div style={{ marginTop: "36px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "32px", fontSize: "11px" }} className="page-break-avoid">
              <div>
                <div style={{ color: "#6b7280", fontWeight: "bold", marginBottom: "36px" }}>Prepared By:</div>
                <div style={{ borderBottom: "1px solid #cbd5e1", width: "180px", marginBottom: "4px" }}></div>
                <div style={{ fontWeight: "bold", color: "#111827" }}>{printReport.preparedBy.toUpperCase()}</div>
                <div style={{ color: "#6b7280", fontSize: "10px" }}>REVELA System Operator</div>
                <div style={{ color: "#6b7280", fontSize: "10px" }}>Business Permits &amp; Licensing Office</div>
              </div>
              <div>
                <div style={{ color: "#6b7280", fontWeight: "bold", marginBottom: "36px" }}>Noted By:</div>
                <div style={{ borderBottom: "1px solid #cbd5e1", width: "180px", marginBottom: "4px" }}></div>
                <div style={{ fontWeight: "bold", color: "#111827" }}>BPLO DEPARTMENT HEAD</div>
                <div style={{ color: "#6b7280", fontSize: "10px" }}>Business Permits &amp; Licensing Office</div>
              </div>
            </div>
          </div>

          {/* ── FIXED OFFICIAL FOOTER ── */}
          <div className="print-footer">
            <div style={{ borderTop: "1.5px solid #e5e7eb", marginBottom: "8px" }}></div>

            <div style={{ textAlign: "center" }}>
              <div style={{ display: "inline-flex", alignItems: "baseline", gap: "2px", fontSize: "10px", fontWeight: "600", color: "#374151" }}>
                <span style={{ display: "inline-flex", alignItems: "baseline" }}>
                  <span style={{ fontFamily: "'Dancing Script', 'Great Vibes', 'Brush Script MT', cursive", fontSize: "18px", color: "#1d4ed8", fontWeight: "700", lineHeight: 1 }}>H</span>
                  <span>ealth</span>
                </span>
                <span style={{ color: "#d1d5db", margin: "0 5px" }}>|</span>
                <span style={{ display: "inline-flex", alignItems: "baseline" }}>
                  <span style={{ fontFamily: "'Dancing Script', 'Great Vibes', 'Brush Script MT', cursive", fontSize: "18px", color: "#1d4ed8", fontWeight: "700", lineHeight: 1 }}>O</span>
                  <span>pportunity</span>
                </span>
                <span style={{ color: "#d1d5db", margin: "0 5px" }}>|</span>
                <span style={{ display: "inline-flex", alignItems: "baseline" }}>
                  <span style={{ fontFamily: "'Dancing Script', 'Great Vibes', 'Brush Script MT', cursive", fontSize: "18px", color: "#1d4ed8", fontWeight: "700", lineHeight: 1 }}>P</span>
                  <span>eace &amp; Order</span>
                </span>
                <span style={{ color: "#d1d5db", margin: "0 5px" }}>|</span>
                <span style={{ display: "inline-flex", alignItems: "baseline" }}>
                  <span style={{ fontFamily: "'Dancing Script', 'Great Vibes', 'Brush Script MT', cursive", fontSize: "18px", color: "#1d4ed8", fontWeight: "700", lineHeight: 1 }}>E</span>
                  <span>ducation &amp; Economy</span>
                </span>
              </div>

              <div style={{ fontSize: "9.5px", fontWeight: 800, color: "#d97706", letterSpacing: "0.3em", marginTop: "4px", textTransform: "uppercase", textAlign: "center" }}>
                LOVEMATAASNAKAHOY
              </div>
            </div>

            <div style={{ fontSize: "8.5px", color: "#9ca3af", marginTop: "6px", display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
              <span>REVELA System &bull; BPLO Compliance &amp; Demographic Report</span>
              <span className="print-page-number" style={{ fontWeight: "500" }}></span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
