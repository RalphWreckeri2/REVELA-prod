import { useState, useEffect } from "react";
import DashboardLayout from "../components/DashboardLayout";
import { useAuth } from "../context/AuthContext";
import { getAnalyticsOverviewRequest, getFlagsRequest, getBarangayHeatmapRequest, getSectorComplianceRequest, getInspectorPerformanceRequest } from "../services/api";
import Papa from "papaparse";
import { saveAs } from "file-saver";
import Swal from "sweetalert2";
import myLogo from "../assets/logo.png";
import bpLogo from "../assets/bagongpilipinas.png";
import sealImg from "../assets/seal.png";

const REPORTS = [
  { id: 1, title: "Weekly Compliance Summary", type: "compliance", desc: "Overview of registered vs. unregistered entities and compliance rate." },
  { id: 2, title: "Top Unregistered Establishments", type: "unregistered", desc: "List of active Red and Yellow flags indicating suspected unregistered businesses." },
  { id: 3, title: "Field Inspector Dispatch Plan", type: "dispatch", desc: "Barangay priority rankings based on the WLC Operational Priority Score (OPS)." },
  { id: 4, title: "Barangay Heatmap & Compliance Breakdown", type: "barangay-heatmap", desc: "Spatial summary per Barangay: registered businesses, active flags (Red/Yellow), overall compliance rate.", formats: ['PDF', 'CSV'] },
  { id: 5, title: "Sectoral & Industrial Compliance Audit", type: "sector-compliance", desc: "Classify establishments by sector/industry against their current compliance status.", formats: ['PDF', 'CSV'] },
  { id: 6, title: "Inspector Performance & Accomplishment Log", type: "inspector-performance", desc: "Field inspector performance: completed inspections, verified flags, deployment timelines.", formats: ['PDF', 'CSV'] },
];

export default function ExportReportsPage() {
  const { token, user } = useAuth();
  const [loadingId, setLoadingId] = useState(null);
  const [printReport, setPrintReport] = useState(null);

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

  const handleDownload = async (report) => {
    const { value: format } = await Swal.fire({
      title: 'Select Export Format',
      input: 'radio',
      inputOptions: {
        'pdf': 'PDF Document',
        'csv': 'CSV Spreadsheet'
      },
      inputValidator: (value) => {
        if (!value) {
          return 'You need to choose a format!'
        }
      },
      showCancelButton: true,
      confirmButtonText: 'Generate',
      confirmButtonColor: 'var(--color-primary)'
    });

    if (!format) return;

    setLoadingId(report.id);
    try {
      if (report.type === "compliance") {
        await generateComplianceReport(format);
      } else if (report.type === "unregistered") {
        await generateUnregisteredReport(format);
      } else if (report.type === "dispatch") {
        await generateDispatchReport(format);
      } else if (report.type === 'barangay-heatmap') {
        await generateBarangayHeatmapReport(format);
      } else if (report.type === 'sector-compliance') {
        await generateSectorComplianceReport(format);
      } else if (report.type === 'inspector-performance') {
        await generateInspectorPerformanceReport(format);
      }

      Swal.fire({
        icon: 'success',
        title: 'Success!',
        text: `${report.title} exported as ${format.toUpperCase()}`,
        timer: 2000,
        showConfirmButton: false
      });
    } catch (error) {
      console.error(error);
      Swal.fire({
        icon: 'error',
        title: 'Export Failed',
        text: error.message || 'An error occurred while generating the report.'
      });
    } finally {
      setLoadingId(null);
    }
  };

  // Draws a section header text for multi-section reports, handling page breaks safely
  const drawSectionTitle = (doc, titleText, finalY) => {
    const pageHeight = doc.internal.pageSize.height;
    let y = finalY + 12;
    if (y + 15 > pageHeight - 15) {
      doc.addPage();
      y = 25;
    }
    doc.setFont("Helvetica", "bold");
    doc.setFontSize(9.5);
    doc.setTextColor(15, 23, 42);
    doc.text(titleText, 14, y);
    return y + 4;
  };

  const generateComplianceReport = async (format) => {
    const data = await getAnalyticsOverviewRequest(token);
    const kpis = data?.descriptive?.kpis;
    const dateStr = new Date().toISOString().slice(0, 10);
    const filename = `Compliance_Summary_${dateStr}`;

    const csvData = [
      { Metric: "Total Registered Entities", Value: kpis?.total_businesses || 0 },
      { Metric: "Active Registrations", Value: kpis?.active_count || 0 },
      { Metric: "Pending Registrations", Value: kpis?.pending_count || 0 },
      { Metric: "Expired Permits", Value: kpis?.expired_count || 0 },
      { Metric: "Closed / Abandoned", Value: kpis?.closed_count || 0 },
      { Metric: "Registrations/Renewals in Current Year", Value: kpis?.current_year_count || 0 },
      { Metric: "Total Flagged Entities", Value: kpis?.total_flagged || 0 },
      { Metric: "Overall Compliance Rate", Value: `${kpis?.compliance_rate || 0}%` },
      { Metric: "High-Risk Barangays", Value: kpis?.high_risk_barangays || 0 }
    ];

    if (format === 'csv') {
      const csv = Papa.unparse(csvData);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }), `${filename}.csv`);
    } else {
      setPrintReport({
        type: 'compliance',
        title: "Weekly Compliance Summary",
        subtitle: "Comprehensive overview of registration rates, compliance audits, and sectoral metrics",
        date: new Date().toLocaleString(),
        preparedBy: user?.fullName || "BPLO Staff",
        office: "BPLO Mataasnakahoy",
        classification: "Official Use / Confidential",
        data: {
          kpis: csvData,
          sectors: data?.descriptive?.sectoral_distribution || [],
          sizes: data?.descriptive?.business_size_dist || [],
          audits: data?.descriptive?.audit_summary?.result_breakdown || [],
          totalInspections: data?.descriptive?.audit_summary?.total_inspections || 0
        }
      });
    }
  };

  const generateUnregisteredReport = async (format) => {
    const res = await getFlagsRequest({ limit: 1000 }, token);
    const allFlags = res?.data || [];
    const flags = allFlags.filter(f => f.flagColor === 'Red' || f.flagColor === 'Yellow');

    const dateStr = new Date().toISOString().slice(0, 10);
    const filename = `Unregistered_Establishments_${dateStr}`;

    const formattedData = flags.map(f => ({
      LogID: f.logID,
      Name: f.detectedName || "Unknown",
      Barangay: f.barangayName || "Unknown",
      Address: f.resolvedAddress || f.nearestLandmark || "",
      Status: f.flagColor === 'Red' ? 'Unregistered' : 'Suspected',
      DetectedDate: f.detectedDate ? f.detectedDate.slice(0, 10) : ""
    }));

    if (format === 'csv') {
      const csv = Papa.unparse(formattedData);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }), `${filename}.csv`);
    } else {
      setPrintReport({
        type: 'unregistered',
        title: "Top Suspected Unregistered Establishments",
        subtitle: "List of flagged business locations showing commercial activity without matching registrations",
        date: new Date().toLocaleString(),
        preparedBy: user?.fullName || "BPLO Staff",
        office: "BPLO Mataasnakahoy",
        classification: "Official Use / Confidential",
        isLandscape: true,
        data: {
          flags: formattedData,
          summary: {
            total: flags.length,
            red: flags.filter(f => f.flagColor === 'Red').length,
            yellow: flags.filter(f => f.flagColor === 'Yellow').length
          }
        }
      });
    }
  };

  const generateDispatchReport = async (format) => {
    const data = await getAnalyticsOverviewRequest(token);
    const rankings = data?.prescriptive?.rankings || [];

    const dateStr = new Date().toISOString().slice(0, 10);
    const filename = `Inspector_Dispatch_Plan_${dateStr}`;

    const formattedData = rankings.map(r => ({
      Rank: r.rank,
      Barangay: r.barangayName,
      PriorityScore: r.ops_score,
      RiskLevel: r.risk_level,
      TotalFlagged: r.flagged_count,
      RedFlags: r.red_count,
      NonComplianceRate: `${r.non_compliance_rate}%`
    }));

    const recs = (data?.prescriptive?.recommendations || []).map((r, i) => ({
      rank: i + 1,
      barangayName: r.barangayName,
      recommendation: r.recommendation
    }));

    if (format === 'csv') {
      const csv = Papa.unparse(formattedData);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }), `${filename}.csv`);
    } else {
      setPrintReport({
        type: 'dispatch',
        title: "Field Inspector Dispatch Plan",
        subtitle: "Barangay ranking prioritizations generated via WLC scoring model for optimal dispatching",
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

  const generateBarangayHeatmapReport = async (format) => {
    const data = await getBarangayHeatmapRequest(token);
    const dateStr = new Date().toISOString().slice(0, 10);
    const filename = `Barangay_Heatmap_${dateStr}`;

    if (format === 'csv') {
      const csv = Papa.unparse(data?.rows || data || []);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }), `${filename}.csv`);
      return;
    }

    setPrintReport({
      type: 'barangay-heatmap',
      title: 'Barangay Heatmap & Compliance Breakdown',
      subtitle: 'Spatial summary per Barangay',
      date: new Date().toLocaleString(),
      preparedBy: user?.fullName || 'BPLO Staff',
      office: 'BPLO Mataasnakahoy',
      classification: 'Official Use / Confidential',
      data: { rows: data?.rows || data || [] }
    });
  };

  const generateSectorComplianceReport = async (format) => {
    const data = await getSectorComplianceRequest(token);
    const dateStr = new Date().toISOString().slice(0, 10);
    const filename = `Sector_Compliance_${dateStr}`;

    if (format === 'csv') {
      const csv = Papa.unparse(data?.rows || data || []);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }), `${filename}.csv`);
      return;
    }

    setPrintReport({
      type: 'sector-compliance',
      title: 'Sectoral & Industrial Compliance Audit',
      subtitle: 'Sector and industry compliance breakdown',
      date: new Date().toLocaleString(),
      preparedBy: user?.fullName || 'BPLO Staff',
      office: 'BPLO Mataasnakahoy',
      classification: 'Official Use / Confidential',
      data: { rows: data?.rows || data || [] }
    });
  };

  const generateInspectorPerformanceReport = async (format) => {
    const data = await getInspectorPerformanceRequest(token);
    const dateStr = new Date().toISOString().slice(0, 10);
    const filename = `Inspector_Performance_${dateStr}`;

    if (format === 'csv') {
      const csv = Papa.unparse(data?.rows || data || []);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }), `${filename}.csv`);
      return;
    }

    setPrintReport({
      type: 'inspector-performance',
      title: 'Inspector Performance & Accomplishment Log',
      subtitle: 'Operational inspector performance summary',
      date: new Date().toLocaleString(),
      preparedBy: user?.fullName || 'BPLO Staff',
      office: 'BPLO Mataasnakahoy',
      classification: 'Official Use / Confidential',
      data: { rows: data?.rows || data || [] }
    });
  };

  return (
    <>
      <DashboardLayout>
        <div className="page-header">
          <div>
            <h1 className="page-title">Export Reports</h1>
            <p className="page-subtitle">Generate and download operational compliance reports in PDF or CSV formats.</p>
          </div>
        </div>

        <div className="saas-card frosted-glass">
          <div style={{ display: "grid", gap: 16 }}>
            {REPORTS.map((report) => (
              <div
                key={report.id}
                className="saas-card"
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, padding: "18px 20px" }}
              >
                <div>
                  <h3 style={{ margin: 0, fontSize: 16, color: "var(--color-ink)" }}>{report.title}</h3>
                  <p style={{ margin: "8px 0 0", color: "var(--color-muted)", fontSize: 13 }}>{report.desc}</p>
                </div>

                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <button
                    className="primary-btn"
                    type="button"
                    onClick={() => handleDownload(report)}
                    disabled={loadingId === report.id}
                  >
                    {loadingId === report.id ? "Generating..." : "Download"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer — hidden in print output so it never lands in generated reports */}
        <footer className="saas-footer frosted-glass print:hidden">
          <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
          <p className="footer-links"><span>BPLO Portal</span> &bull; <span>System Settings</span></p>
        </footer>
      </DashboardLayout>

      {/* ── Printable Report View (hidden on screen, visible only during print) ── */}
      {printReport && (
        <div className="print-report-container hidden print:block bg-white text-black font-sans w-full">

          {/* ── Custom Print CSS ── */}
          <style>{`
            @media print {
              @page {
                size: ${printReport.isLandscape ? "landscape" : "portrait"};
                margin: 0;
              }

              /* Hide all screen-only UI */
              .mobile-toggle, aside, header,
              .ambient-bg-mesh, .page-header,
              .saas-card.frosted-glass,
              .swal2-container, button, .no-print {
                display: none !important;
              }

              /* Reset parent wrappers to prevent blank-screen bug */
              html, body, #root, .saas-root, .saas-main, .saas-content {
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
                background: #fff !important;
                width: 100% !important;
                margin: 0 !important;
                padding: 0 !important;
                position: relative !important;
              }

              /* -- FIXED HEADER: pinned to top of every printed page -- */
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

              /* -- FIXED FOOTER: pinned to bottom of every printed page -- */
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

              /* -- BODY: breathing room so content never clips under header or footer -- */
              .report-body {
                margin-top: 105px !important;
                margin-bottom: 85px !important;
                padding: 0 15mm !important;
              }

              /* Print tables */
              .print-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 12px;
                margin-bottom: 22px;
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

              /* Page counter */
              body { counter-reset: page; }
              .print-page-number::after {
                counter-increment: page;
                content: "Page " counter(page);
              }

              .page-break-avoid { page-break-inside: avoid; }
            }
          `}</style>

          {/* -- FIXED HEADER -- */}
          <div className="print-header">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", paddingBottom: "10px" }}>
              {/* Left: LGU Seal */}
              <div style={{ width: "72px", textAlign: "left", flexShrink: 0 }}>
                <img src={sealImg} alt="Mataasnakahoy Seal" style={{ width: "62px", height: "62px", objectFit: "contain" }} />
              </div>

              {/* Center: Full letterhead text */}
              <div style={{ textAlign: "center", flex: 1, margin: "0 16px" }}>
                <div style={{ fontSize: "10.5px", textTransform: "uppercase", color: "#4b5563", fontWeight: "500", lineHeight: "1.5" }}>Republic of the Philippines</div>
                <div style={{ fontSize: "10.5px", color: "#4b5563", lineHeight: "1.5" }}>Province of Batangas</div>
                <div style={{ fontSize: "13px", color: "#111827", marginTop: "2px", lineHeight: "1.5" }}>Municipality of Mataasnakahoy</div>
                <div style={{ fontSize: "13px", fontWeight: "800", color: "#111827", textTransform: "uppercase", letterSpacing: "0.5px", lineHeight: "1.5" }}>Office of the Municipal Mayor</div>
                <div style={{ fontSize: "10px", color: "#4b5563", marginTop: "3px", lineHeight: "1.6" }}>
                  Telephone #: <span style={{ fontWeight: 600, color: "#111827" }}>461-2374</span> <br></br>
                  Email: <span style={{ fontWeight: 400, color: "#111827" }}>licensingoffice2374@yahoo.com</span>
                </div>
              </div>

              {/* Right: Bagong Pilipinas Logo */}
              <div style={{ width: "72px", textAlign: "right", flexShrink: 0 }}>
                <img src={bpLogo} alt="Bagong Pilipinas Logo" style={{ width: "62px", height: "62px", objectFit: "contain" }} />
              </div>
            </div>
            {/* Thin separator line below header */}
            <div style={{ borderBottom: "1.5px solid #e5e7eb", marginTop: "6px" }}></div>
          </div>

          {/* ── BODY CONTENT ── */}
          <div className="report-body">

            {/* Document Title */}
            <h2 style={{ fontSize: "15px", fontWeight: "bold", textAlign: "center", color: "#111827", marginBottom: "16px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              {printReport.title}
            </h2>

            {/* Document Subtitle */}
            {printReport.subtitle && (
              <p style={{ fontSize: "11px", color: "#6b7280", fontStyle: "italic", textAlign: "center", marginBottom: "16px", marginTop: "-10px" }}>
                {printReport.subtitle}
              </p>
            )}

            {/* ── BARANGAY HEATMAP ── */}
            {printReport.type === 'barangay-heatmap' && (
              <div>
                <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Barangay Heatmap & Compliance Breakdown</h3>
                <table className="print-table">
                  <thead>
                    <tr>
                      <th style={{ background: "#10b981", color: "#fff" }}>Barangay</th>
                      <th style={{ background: "#10b981", color: "#fff", width: "120px" }}>Registered</th>
                      <th style={{ background: "#10b981", color: "#fff", width: "100px" }}>Red Flags</th>
                      <th style={{ background: "#10b981", color: "#fff", width: "100px" }}>Yellow Flags</th>
                      <th style={{ background: "#10b981", color: "#fff", width: "120px" }}>Compliance Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {printReport.data.rows.map((r, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: "600", color: "#111827" }}>{r.barangay}</td>
                        <td>{r.registered_count}</td>
                        <td>{r.red_flags}</td>
                        <td>{r.yellow_flags}</td>
                        <td style={{ fontWeight: "600" }}>{r.compliance_rate}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* ── SECTOR COMPLIANCE ── */}
            {printReport.type === 'sector-compliance' && (
              <div>
                <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Sectoral & Industrial Compliance Audit</h3>
                <table className="print-table">
                  <thead>
                    <tr>
                      <th style={{ background: "#6b21a8", color: "#fff" }}>Sector / Industry</th>
                      <th style={{ background: "#6b21a8", color: "#fff", width: "120px" }}>Registered</th>
                      <th style={{ background: "#6b21a8", color: "#fff", width: "120px" }}>Non-Compliant</th>
                      <th style={{ background: "#6b21a8", color: "#fff", width: "120px" }}>Compliance Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {printReport.data.rows.map((s, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: "600", color: "#111827" }}>{s.sector}</td>
                        <td>{s.registered_count}</td>
                        <td>{s.non_compliant_count}</td>
                        <td style={{ fontWeight: "600" }}>{s.compliance_rate}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* ── INSPECTOR PERFORMANCE ── */}
            {printReport.type === 'inspector-performance' && (
              <div>
                <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Inspector Performance & Accomplishment Log</h3>
                <table className="print-table">
                  <thead>
                    <tr>
                      <th style={{ background: "#ef4444", color: "#fff" }}>Inspector</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "120px" }}>Inspections Completed</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "120px" }}>Flags Verified</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "120px" }}>Avg Response (hrs)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {printReport.data.rows.map((i, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: "600", color: "#111827" }}>{i.inspector_name}</td>
                        <td>{i.inspections_completed}</td>
                        <td>{i.flags_verified}</td>
                        <td>{i.avg_response_hours}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Metadata Section */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 24px", background: "var(--color-card-alt)", border: "1px solid var(--color-border)", borderRadius: "8px", padding: "14px", marginBottom: "20px", fontSize: "11px" }}>
              <div><span style={{ fontWeight: "bold", color: "#6b7280", marginRight: "6px" }}>DATE GENERATED:</span><span style={{ color: "#111827", fontWeight: "500" }}>{printReport.date}</span></div>
              <div><span style={{ fontWeight: "bold", color: "#6b7280", marginRight: "6px" }}>OFFICE:</span><span style={{ color: "#111827", fontWeight: "500" }}>{printReport.office}</span></div>
              <div><span style={{ fontWeight: "bold", color: "#6b7280", marginRight: "6px" }}>PREPARED BY:</span><span style={{ color: "#111827", fontWeight: "500" }}>{printReport.preparedBy}</span></div>
              <div><span style={{ fontWeight: "bold", color: "#6b7280", marginRight: "6px" }}>CLASSIFICATION:</span><span style={{ color: "#111827", fontWeight: "500" }}>{printReport.classification}</span></div>
            </div>

            {/* ── COMPLIANCE REPORT TABLES ── */}
            {printReport.type === 'compliance' && (
              <div>
                <div>
                  <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Key Performance Indicators</h3>
                  <table className="print-table">
                    <thead>
                      <tr>
                        <th style={{ background: "#56ab2f", color: "#fff" }}>Compliance Metric</th>
                        <th style={{ background: "#56ab2f", color: "#fff", width: "160px" }}>Reported Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {printReport.data.kpis.map((kpi, idx) => (
                        <tr key={idx}>
                          <td>{kpi.Metric}</td>
                          <td style={{ fontWeight: "600", color: "#111827" }}>{kpi.Value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {printReport.data.sectors?.length > 0 && (
                  <div className="page-break-avoid">
                    <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Business Sector Distribution (Top 10 LOB)</h3>
                    <table className="print-table">
                      <thead>
                        <tr>
                          <th style={{ background: "#56ab2f", color: "#fff" }}>Business Sector / Category</th>
                          <th style={{ background: "#56ab2f", color: "#fff", width: "160px" }}>Registered Entities Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {printReport.data.sectors.map((s, idx) => (
                          <tr key={idx}>
                            <td>{s.sector}</td>
                            <td style={{ fontWeight: "600", color: "#111827" }}>{s.count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {printReport.data.sizes?.length > 0 && (
                  <div className="page-break-avoid">
                    <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Business Size Classification Distribution</h3>
                    <table className="print-table">
                      <thead>
                        <tr>
                          <th style={{ background: "#56ab2f", color: "#fff" }}>Size Classification</th>
                          <th style={{ background: "#56ab2f", color: "#fff", width: "160px" }}>Registered Entities Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {printReport.data.sizes.map((s, idx) => (
                          <tr key={idx}>
                            <td>{s.size_label}</td>
                            <td style={{ fontWeight: "600", color: "#111827" }}>{s.count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {printReport.data.audits?.length > 0 && (
                  <div className="page-break-avoid">
                    <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Field Inspections Audit Results Breakdown</h3>
                    <table className="print-table">
                      <thead>
                        <tr>
                          <th style={{ background: "#56ab2f", color: "#fff" }}>Inspection Result Status</th>
                          <th style={{ background: "#56ab2f", color: "#fff", width: "160px" }}>Conducted Inspections Count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {printReport.data.audits.map((a, idx) => (
                          <tr key={idx}>
                            <td>{a.inspectionResult || "Unclassified"}</td>
                            <td style={{ fontWeight: "600", color: "#111827" }}>{a.count}</td>
                          </tr>
                        ))}
                        <tr style={{ fontWeight: "bold", background: "var(--color-surface)" }}>
                          <td>TOTAL AUDIT INSPECTIONS COMPLETED</td>
                          <td>{printReport.data.totalInspections}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* ── UNREGISTERED REPORT TABLES ── */}
            {printReport.type === 'unregistered' && (
              <div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px", marginBottom: "16px" }}>
                  <div style={{ background: "var(--color-card-alt)", border: "1px solid var(--color-border)", borderRadius: "8px", padding: "10px" }}>
                    <div style={{ fontSize: "9px", fontWeight: "bold", color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Total Flagged Locations</div>
                    <div style={{ fontSize: "13px", fontWeight: "bold", color: "var(--color-ink)", marginTop: "4px" }}>{printReport.data.summary.total} Suspected Entities</div>
                  </div>
                  <div style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", padding: "10px" }}>
                    <div style={{ fontSize: "9px", fontWeight: "bold", color: "#dc2626", textTransform: "uppercase", letterSpacing: "0.5px" }}>Unregistered Commercial (Red)</div>
                    <div style={{ fontSize: "13px", fontWeight: "bold", color: "#7f1d1d", marginTop: "4px" }}>{printReport.data.summary.red} Confirmed Locations</div>
                  </div>
                  <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: "8px", padding: "10px" }}>
                    <div style={{ fontSize: "9px", fontWeight: "bold", color: "#d97706", textTransform: "uppercase", letterSpacing: "0.5px" }}>Suspected Compliance Gap (Yellow)</div>
                    <div style={{ fontSize: "13px", fontWeight: "bold", color: "#92400e", marginTop: "4px" }}>{printReport.data.summary.yellow} Potential Violations</div>
                  </div>
                </div>

                <table className="print-table">
                  <thead>
                    <tr>
                      <th style={{ background: "#ef4444", color: "#fff", width: "48px" }}>Log ID</th>
                      <th style={{ background: "#ef4444", color: "#fff" }}>Establishment Name</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "100px" }}>Barangay</th>
                      <th style={{ background: "#ef4444", color: "#fff" }}>Resolved Address / Nearest Landmark</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "80px" }}>Flag Status</th>
                      <th style={{ background: "#ef4444", color: "#fff", width: "80px" }}>Date Flagged</th>
                    </tr>
                  </thead>
                  <tbody>
                    {printReport.data.flags.map((f, idx) => (
                      <tr key={idx}>
                        <td style={{ fontFamily: "monospace" }}>{f.LogID}</td>
                        <td style={{ fontWeight: "600", color: "#111827" }}>{f.Name}</td>
                        <td>{f.Barangay}</td>
                        <td style={{ fontSize: "10.5px" }}>{f.Address}</td>
                        <td>
                          <span style={{
                            padding: "2px 6px", borderRadius: "4px", fontSize: "10px", fontWeight: "bold",
                            background: f.Status === 'Unregistered' ? '#fee2e2' : '#fef3c7',
                            color: f.Status === 'Unregistered' ? '#b91c1c' : '#b45309'
                          }}>
                            {f.Status}
                          </span>
                        </td>
                        <td>{f.DetectedDate}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* ── DISPATCH REPORT TABLES ── */}
            {printReport.type === 'dispatch' && (
              <div>
                <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Barangay Priority Rankings</h3>
                <table className="print-table">
                  <thead>
                    <tr>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "48px" }}>Rank</th>
                      <th style={{ background: "#3b82f6", color: "#fff" }}>Barangay Name</th>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "100px" }}>WLC OPS Score</th>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "80px" }}>Risk Level</th>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "80px" }}>Flag Count</th>
                      <th style={{ background: "#3b82f6", color: "#fff", width: "100px" }}>Non-Compliance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {printReport.data.rankings.map((r, idx) => (
                      <tr key={idx}>
                        <td style={{ fontWeight: "bold", color: "#111827" }}>Rank {r.Rank}</td>
                        <td style={{ fontWeight: "600", color: "#111827" }}>{r.Barangay}</td>
                        <td>{r.PriorityScore}</td>
                        <td>
                          <span style={{
                            padding: "2px 6px", borderRadius: "4px", fontSize: "10px", fontWeight: "bold",
                            background: r.RiskLevel === 'High' ? '#fee2e2' : r.RiskLevel === 'Medium' ? '#fef3c7' : '#dcfce7',
                            color: r.RiskLevel === 'High' ? '#b91c1c' : r.RiskLevel === 'Medium' ? '#b45309' : '#166534'
                          }}>
                            {r.RiskLevel}
                          </span>
                        </td>
                        <td>{r.TotalFlagged}</td>
                        <td style={{ fontWeight: "600", color: "#111827" }}>{r.NonComplianceRate}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {printReport.data.recommendations?.length > 0 && (
                  <div className="page-break-avoid">
                    <h3 style={{ fontSize: "11px", fontWeight: "bold", color: "var(--color-ink)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>Actionable Dispatch Recommendations &amp; Allocations</h3>
                    <table className="print-table">
                      <thead>
                        <tr>
                          <th style={{ background: "#3b82f6", color: "#fff", width: "60px" }}>Rank</th>
                          <th style={{ background: "#3b82f6", color: "#fff", width: "140px" }}>Priority Barangay</th>
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

            {/* Signature block */}
            <div style={{ marginTop: "40px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "32px", fontSize: "11px" }}>
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

          </div>{/* end .report-body */}

          {/* -- FIXED FOOTER -- */}
          <div className="print-footer">
            {/* Top border line */}
            <div style={{ borderTop: "1.5px solid #e5e7eb", marginBottom: "8px" }}></div>

            {/* HOPE slogan - centered */}
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

              {/* LOVEMATAASNAKAHOY slogan */}
              <div style={{ fontSize: "9.5px", fontWeight: 800, color: "#d97706", letterSpacing: "0.3em", marginTop: "4px", textTransform: "uppercase", textAlign: "center" }}>
                LOVEMATAASNAKAHOY
              </div>
            </div>

            {/* System audit line and page number */}
            <div style={{ fontSize: "8.5px", color: "#9ca3af", marginTop: "6px", display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
              <span>REVELA System {'\u2022'} BPLO Compliance Audit Report</span>
              <span className="print-page-number" style={{ fontWeight: "500" }}></span>
            </div>
          </div>

        </div>
      )}
    </>
  );
}
