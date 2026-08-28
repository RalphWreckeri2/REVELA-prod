// ── UploadModal.jsx ───────────────────────────────────────────────────────────
// Drop-in replacement for the UploadModal component in RegistryPage.jsx.
//
// KEY BEHAVIOUR:
//   - Before upload  → drag/drop form, same as before
//   - During upload  → animated row counter that ticks through fileRowCount,
//                      slowing near the end so it never hits 100% before the
//                      real response arrives (no fake "done" flash)
//   - After upload   → existing summary + error list, unchanged
//
// HOW THE COUNTER WORKS:
//   Each geocoding call takes roughly 300-500 ms on the backend.
//   We tick one row every ~(totalMs / rows) ms, but apply an easing curve
//   so the counter slows down past 80% and freezes at 95% to wait for the
//   real response. When the response arrives we jump straight to the real
//   `inserted` count.
//
// IMPORTANT: No backend changes needed. The counter is purely frontend.
// ─────────────────────────────────────────────────────────────────────────────

import Papa from "papaparse";
import { useState, useEffect, useRef, useCallback } from "react";
import Swal from "sweetalert2";
import { uploadRegistryFile, syncRegistryFile, cancelRegistryImport } from "../services/api";

// ── Icons (self-contained so this file is independently droppable) ─────────────
const Icon = {
  Upload: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
      <polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
    </svg>
  ),
  Check: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  ),
  AlertCircle: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
  ),
  X: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  ),
  FileText: () => (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10 9 9 9 8 9"/>
    </svg>
  ),
};

function useRegistryProgress({ active, done, finalCount }) {
  const [displayed, setDisplayed] = useState(0);

  useEffect(() => {
    if (!active || done) return;
    
    const handleProgress = (e) => {
      const data = e.detail;
      if (data.processed !== undefined) {
        setDisplayed(data.processed);
      }
    };

    window.addEventListener("revela:registry-progress", handleProgress);
    return () => window.removeEventListener("revela:registry-progress", handleProgress);
  }, [active, done]);

  useEffect(() => {
    if (done && finalCount !== undefined) {
      setDisplayed(finalCount);
    }
  }, [done, finalCount]);

  useEffect(() => {
    if (!active && !done) setDisplayed(0);
  }, [active, done]);

  return displayed;
};

// ── Progress bar sub-component ─────────────────────────────────────────────────
function ProgressBar({ value, total, color = "var(--color-primary)" }) {
  const pct = total > 0 ? Math.min((value / total) * 100, 100) : 0;
  return (
    <div style={barStyles.track}>
      <div
        style={{
          ...barStyles.fill,
          width: `${pct}%`,
          background: color,
          transition: "width 0.12s linear",
        }}
      />
    </div>
  );
}

const barStyles = {
  track: {
    width: "100%", height: 6, background: "var(--color-border)",
    borderRadius: 99, overflow: "hidden",
  },
  fill: { height: "100%", borderRadius: 99, minWidth: 4 },
};

// ── Phase labels shown under the counter ──────────────────────────────────────
function phaseLabel(displayed, total) {
  const pct = total > 0 ? displayed / total : 0;
  if (pct < 0.1)  return "Parsing rows…";
  if (pct < 0.4)  return "Geocoding addresses via Google Maps…";
  if (pct < 0.75) return "Cross-referencing barangay records…";
  if (pct < 0.95) return "Inserting into registry…";
  return "Finalising — waiting for server response…";
}

// ── Main UploadModal ───────────────────────────────────────────────────────────
export function UploadModal({ onClose, onSuccess, token, variant = "upload", isClosing }) {
  const isSync = variant === "sync";
  const [dragging,      setDragging]      = useState(false);
  const [file,          setFile]          = useState(null);
  const [fileRowCount,  setFileRowCount]  = useState(null);
  const [loading,       setLoading]       = useState(false);
  const [cancelling,    setCancelling]    = useState(false);
  const [summary,       setSummary]       = useState(null);
  const [error,         setError]         = useState("");

  const abortControllerRef = useRef(null);

  // Counter state
  const displayed = useRegistryProgress({
    active:     loading,
    done:       !!summary,
    finalCount: summary
      ? (isSync ? (summary.inserted ?? 0) + (summary.updated ?? 0) : summary.inserted)
      : undefined,
  });

  const handleFile = (f) => {
    setError("");
    setSummary(null);
    setFileRowCount(null);
    const allowed = ["csv", "xlsx", "xls"];
    const ext     = f.name.split(".").pop().toLowerCase();
    if (!allowed.includes(ext)) {
      setError("Only CSV and Excel files are accepted (.csv, .xlsx, .xls)");
      return;
    }
    setFile(f);
    if (ext === "csv") {
      Papa.parse(f, {
        header: true,
        skipEmptyLines: true,
        complete: (results) => {
          setFileRowCount(Array.isArray(results.data) ? results.data.length : null);
        },
        error: () => setFileRowCount(null),
      });
    }
  };

  const handleSubmit = async () => {
    if (!file) return;
    setLoading(true);
    setError("");
    abortControllerRef.current = new AbortController();
    try {
      const uploadFn = isSync ? syncRegistryFile : uploadRegistryFile;
      const result = await uploadFn(file, token, abortControllerRef.current.signal);
      setSummary(result);
    } catch (err) {
      if (err.name === "AbortError") return;
      setError(err.message || "Upload failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleCancelUpload = async () => {
    const result = await Swal.fire({
      title: 'Are you sure?',
      text: "Everything loaded will be rolled back.",
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtoncolor: "var(--color-muted)",
      confirmButtonText: 'Yes, cancel it'
    });

    if (result.isConfirmed) {
      setCancelling(true);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      await cancelRegistryImport(token);
      setLoading(false);
      setCancelling(false);
      setError("Upload cancelled by user — no data was saved.");
    }
  };

  const handleDone = () => {
    if (summary) onSuccess();
    onClose();
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} style={s.backdrop} onClick={!loading ? onClose : undefined}>
      <div className={"modal-panel" + (isClosing ? " closing" : "")} style={s.card} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={s.header}>
          <h3 style={s.title}>
            {summary
              ? (isSync ? "Import Complete" : "Upload Complete")
              : loading
                ? (isSync ? "Synchronizing Registry…" : "Processing Registry…")
                : (isSync ? "Import BPLO Registry" : "Upload BPLO Registry")}
          </h3>
          {!loading && (
            <button className="modal-close-btn" onClick={handleDone}>
              <Icon.X />
            </button>
          )}
        </div>

        {/* ── SUCCESS VIEW ── */}
        {summary ? (
          <div>
            {/* Completion counter banner */}
            <div style={s.completionBanner}>
              <div style={s.completionIcon}><Icon.Check /></div>
              <div>
                <p style={s.completionMain}>
                  {isSync
                    ? `${(summary.inserted ?? 0) + (summary.updated ?? 0)} of ${summary.total_rows} rows applied (${summary.updated ?? 0} updated, ${summary.inserted ?? 0} new)`
                    : `${summary.inserted} of ${summary.total_rows} rows inserted`}
                </p>
                <p style={s.completionSub}>
                  {summary.geocoded_ok} geocoded &nbsp;·&nbsp; {summary.skipped} skipped
                </p>
              </div>
            </div>

            <div style={s.summaryResult}>
              {[
                ["Total rows in file",             summary.total_rows,       "var(--color-muted)"],
                ...(isSync
                  ? [
                      ["Existing records updated",   summary.updated ?? 0,     "var(--color-primary)"],
                      ["New businesses added",       summary.inserted ?? 0,    "var(--color-primary)"],
                    ]
                  : [["Successfully inserted",       summary.inserted,         "var(--color-primary)"]]),
                ["Geocoded successfully",          summary.geocoded_ok,       "var(--color-muted)"],
                ["Geocoding failed",               summary.geocoded_failed,   "var(--color-gold-dark)"],
                ["Skipped (invalid / no name)",    summary.skipped,           "var(--color-muted)"],
              ].map(([label, value, color]) => (
                <div key={label} style={s.summaryRow}>
                  <span style={{ color: "var(--color-muted)" }}>{label}</span>
                  <strong style={{ color }}>{value}</strong>
                </div>
              ))}
            </div>

            {summary.errors?.length > 0 && (
              <div style={s.errorList}>
                <p style={{ fontWeight: 600, fontSize: 12, marginBottom: 6 }}>Skipped rows:</p>
                {summary.errors.slice(0, 5).map((e, i) => (
                  <p key={i} style={{ fontSize: 11, color: "var(--color-muted)", marginBottom: 2 }}>{e}</p>
                ))}
                {summary.errors.length > 5 && (
                  <p style={{ fontSize: 11, color: "var(--color-muted)" }}>
                    + {summary.errors.length - 5} more
                  </p>
                )}
              </div>
            )}

            <div style={s.footer}>
              <button className="primary-btn" onClick={handleDone}>
                <Icon.Check /> Done
              </button>
            </div>
          </div>

        /* ── LOADING / COUNTER VIEW ── */
        ) : loading ? (
          <div style={s.loadingView}>

            {/* Big animated counter */}
            <div style={s.counterBlock}>
              <div style={s.counterNumbers}>
                <span style={s.counterCurrent}>{displayed.toLocaleString()}</span>
                {fileRowCount && (
                  <>
                    <span style={s.counterSep}>/</span>
                    <span style={s.counterTotal}>{fileRowCount.toLocaleString()}</span>
                  </>
                )}
              </div>
              <p style={s.counterLabel}>rows processed</p>
            </div>

            {/* Progress bar */}
            {fileRowCount && (
              <div style={{ width: "100%", marginBottom: 12 }}>
                <ProgressBar value={displayed} total={fileRowCount} />
                <div style={s.progressMeta}>
                  <span>{Math.round((displayed / fileRowCount) * 100)}%</span>
                  <span>{fileRowCount - displayed} remaining</span>
                </div>
              </div>
            )}

            {/* Phase label */}
            <p style={s.phaseLabel}>
              {fileRowCount
                ? phaseLabel(displayed, fileRowCount)
                : "Geocoding addresses via Google Maps API…"}
            </p>

            {/* Animated dots */}
            <div style={s.dotsRow}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{ ...s.dot, animationDelay: `${i * 0.2}s` }} />
              ))}
            </div>

            <div style={{ marginTop: 16 }}>
              <button 
                type="button" 
                className="ghost-btn" 
                style={{ color: "var(--color-danger)", borderColor: "var(--color-danger-light)", display: "flex", alignItems: "center", gap: "6px", opacity: cancelling ? 0.5 : 1, cursor: cancelling ? "not-allowed" : "pointer" }} 
                onClick={handleCancelUpload}
                disabled={cancelling}
              >
                <Icon.X /> {cancelling ? "Cancelling..." : "Cancel Upload"}
              </button>
            </div>

            <style>{`
              @keyframes dotBounce {
                0%, 80%, 100% { transform: translateY(0); opacity: 0.3; }
                40%            { transform: translateY(-6px); opacity: 1; }
              }
              /* spin keyframe now defined globally in global.css */
            `}</style>
          </div>

        /* ── FORM VIEW ── */
        ) : (
          <>
            <p style={s.sub}>
              {isSync
                ? "Choose an updated BPLO export. Matching businesses (same name and barangay) are overwritten with the file data; new rows are added. Initial seeding should use Upload File (Admin)."
                : "Upload the official BPLO registry CSV or Excel file. The system will geocode each business address and seed the registry table."}
            </p>

            {/* Drop zone */}
            <div
              style={{ ...s.dropZone, ...(dragging ? s.dropZoneActive : {}) }}
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); }}
            >
              {file ? (
                <>
                  <div style={{ color: "var(--color-primary)", marginBottom: 8 }}><Icon.FileText /></div>
                  <p style={{ color: "var(--color-primary)", fontWeight: 600, fontSize: 14 }}>{file.name}</p>
                  {fileRowCount !== null && (
                    <p style={{ fontSize: 12, color: "var(--color-muted)", marginTop: 4 }}>
                      {fileRowCount.toLocaleString()} row{fileRowCount !== 1 ? "s" : ""} detected
                    </p>
                  )}
                </>
              ) : (
                <>
                  <div style={{ color: "var(--color-muted)", marginBottom: 8, opacity: 0.5 }}><Icon.Upload /></div>
                  <p style={{ fontWeight: 600, fontSize: 14, color: "var(--color-ink)" }}>
                    Drag &amp; drop your file here
                  </p>
                  <p style={{ fontSize: 12, color: "var(--color-muted)", marginTop: 4 }}>
                    or click to browse &nbsp;·&nbsp; CSV, XLSX, XLS accepted
                  </p>
                </>
              )}
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                style={s.fileInput}
                onChange={e => handleFile(e.target.files[0])}
              />
            </div>

            {/* Column hint */}
            <div style={s.hint}>
              <strong>Expected columns (flexible naming):</strong>
              &nbsp; business_name, barangay, business_type, line_of_business, size_of_business,
              business_address, status / status_of_registration, last_renewal_date
            </div>

            {error && (
              <div style={s.errorBanner}>
                <Icon.AlertCircle /> &nbsp;{error}
              </div>
            )}

            <div style={s.footer}>
              <button className="ghost-btn" onClick={onClose}>Cancel</button>
              <button
                className="primary-btn"
                disabled={!file}
                style={!file ? { opacity: 0.5, cursor: "not-allowed" } : {}}
                onClick={handleSubmit}
              >
                <Icon.Upload /> {isSync ? "Import & sync" : "Process File"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────────
const s = {
  backdrop: {
    position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)",
    backdropFilter: "blur(4px)", display: "flex",
    alignItems: "center", justifyContent: "center", zIndex: 100,
  },
  card: {
    background: "var(--color-modal-bg)", borderRadius: "var(--radius-xl)",
    padding: 32, width: 480,
    boxShadow: "0 25px 50px rgba(0,0,0,0.15)",
    maxHeight: "90vh", overflowY: "auto",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  title:  { fontSize: 18, fontWeight: 700, color: "var(--color-ink)" },
  closeBtn: { background: "none", border: "none", color: "var(--color-muted)", cursor: "pointer", display: "flex" },
  sub:    { fontSize: 13, color: "var(--color-muted)", lineHeight: 1.6, marginBottom: 24 },

  // Loading view
  loadingView: {
    display: "flex", flexDirection: "column", alignItems: "center",
    padding: "12px 0 8px", gap: 0,
  },
  counterBlock: {
    display: "flex", flexDirection: "column", alignItems: "center",
    marginBottom: 20,
  },
  counterNumbers: {
    display: "flex", alignItems: "baseline", gap: 8,
  },
  counterCurrent: {
    fontSize: 52, fontWeight: 800, color: "var(--color-primary)",
    lineHeight: 1, fontVariantNumeric: "tabular-nums",
    transition: "color 0.3s",
  },
  counterSep: {
    fontSize: 28, fontWeight: 300, color: "var(--color-border)", lineHeight: 1,
  },
  counterTotal: {
    fontSize: 28, fontWeight: 600, color: "var(--color-muted)", lineHeight: 1,
    fontVariantNumeric: "tabular-nums",
  },
  counterLabel: {
    fontSize: 12, fontWeight: 500, color: "var(--color-muted)",
    textTransform: "uppercase", letterSpacing: "0.08em", marginTop: 6,
  },
  progressMeta: {
    display: "flex", justifyContent: "space-between",
    fontSize: 11, color: "var(--color-muted)", marginTop: 6, fontWeight: 500,
  },
  phaseLabel: {
    fontSize: 13, color: "var(--color-ink)", fontWeight: 500,
    textAlign: "center", marginTop: 8, marginBottom: 16,
    minHeight: 20,
  },
  dotsRow: {
    display: "flex", gap: 6, alignItems: "center", marginBottom: 20,
  },
  dot: {
    width: 7, height: 7, borderRadius: "50%",
    background: "var(--color-primary)", opacity: 0.3,
    animation: "dotBounce 1.2s ease-in-out infinite",
  },
  warningNote: {
    fontSize: 11, color: "var(--color-muted)", textAlign: "center",
    padding: "8px 16px", background: "var(--color-hover)",
    borderRadius: "var(--radius-sm)", width: "100%",
  },

  // Completion banner
  completionBanner: {
    display: "flex", alignItems: "center", gap: 14,
    background: "var(--color-primary-light)", border: "1px solid rgba(86,171,47,0.25)",
    borderRadius: "var(--radius-md)", padding: "14px 18px", marginBottom: 20,
  },
  completionIcon: {
    width: 36, height: 36, borderRadius: "50%",
    background: "var(--color-primary)", color: "#fff",
    display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
  },
  completionMain: { fontSize: 15, fontWeight: 700, color: "var(--color-ink)", marginBottom: 2 },
  completionSub:  { fontSize: 12, color: "var(--color-muted)" },

  // Summary result
  summaryResult: {
    display: "flex", flexDirection: "column", gap: 10, marginBottom: 16,
    padding: 16, background: "var(--color-hover)", borderRadius: "var(--radius-lg)",
  },
  summaryRow: { display: "flex", justifyContent: "space-between", fontSize: 13 },
  errorList: {
    background: "var(--color-error-bg)", border: "1px solid var(--color-error-border)",
    borderRadius: "var(--radius-sm)", padding: "10px 14px", marginBottom: 16,
  },
  errorBanner: {
    display: "flex", alignItems: "center", gap: 8,
    background: "var(--color-error-bg)", border: "1px solid var(--color-error-border)",
    borderRadius: "var(--radius-sm)", padding: "10px 14px",
    fontSize: 13, color: "var(--color-danger)", marginBottom: 16,
  },
  footer: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 },

  // Drop zone
  dropZone: {
    border: "2px dashed var(--color-border)", borderRadius: "var(--radius-lg)",
    padding: "32px 24px", textAlign: "center", cursor: "pointer",
    position: "relative", transition: "all 0.2s", marginBottom: 16,
  },
  dropZoneActive: { borderColor: "var(--color-primary)", background: "var(--color-primary-light)" },
  fileInput: { position: "absolute", inset: 0, opacity: 0, cursor: "pointer" },
  hint: {
    background: "var(--color-hover)", border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-sm)", padding: "10px 14px",
    fontSize: 12, color: "var(--color-muted)", marginBottom: 16, lineHeight: 1.6,
  },
};
