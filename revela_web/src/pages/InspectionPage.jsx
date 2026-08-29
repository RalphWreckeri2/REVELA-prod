/**
 * InspectionPage.jsx
 * Wired to /api/inspections — admin kanban + assign modal + verify action.
 * Inspectors only see their own tasks via the same page (role-gated views).
 */

import { useState, useEffect, useCallback, useContext } from "react";
import { createPortal } from "react-dom";
import DashboardLayout from "../components/DashboardLayout";
import { AuthContext } from "../context/AuthContext";
import {
  getInspectionsRequest,
  getInspectorTasksRequest,
  assignInspectionRequest,
  reassignSubmittedInspectionRequest,
  verifyInspectionRequest,
  getInspectorsRequest,
  inspectionEvidenceUrls,
} from "../services/api";
import Swal from "sweetalert2";
import AnimatePresence from "../components/AnimatePresence";

const formatResult = (val) => {
  if (!val) return val;
  switch (val) {
    case 'Green': return 'Registered';
    case 'Yellow': return 'Suspected / Needs Verification';
    case 'Orange': return 'Warned / Non-Compliant';
    case 'Red': return 'Unregistered';
    case 'Black': return 'Blacklisted / Non-Responsive';
    case 'Purple': return 'Closed / Abandoned';
    default: return val;
  }
};

// ── Icons ──────────────────────────────────────────────────────────────────────
const Icon = {
  MapPin: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="10" r="3"/><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/>
    </svg>
  ),
  User: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
    </svg>
  ),
  Check: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="20 6 9 17 4 12"/>
    </svg>
  ),
  X: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  ),
  AlertCircle: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
  ),
  Send: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
    </svg>
  ),
  Clock: () => (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
    </svg>
  ),
  RefreshCw: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="23 4 23 10 17 10"/>
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
    </svg>
  ),
  Flag: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>
      <line x1="4" y1="22" x2="4" y2="15"/>
    </svg>
  ),
  Search: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
    </svg>
  ),
  AlignJustify: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  ),
  Archive: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="21 8 21 21 3 21 3 8" />
      <rect x="1" y="3" width="22" height="5" />
      <line x1="10" y1="12" x2="14" y2="12" />
    </svg>
  ),
};

// ── Constants ──────────────────────────────────────────────────────────────────
const STATUS_COLS = ["Assigned", "Reassigned", "Submitted", "Verified"];

const FLAG_COLOR = {
  Red:    { bg: "var(--flag-red-bg)",    text: "var(--flag-red-text)" },
  Yellow: { bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)" },
  Green:  { bg: "var(--flag-green-bg)",  text: "var(--flag-green-text)" },
  Black:  { bg: "var(--flag-black-bg)",  text: "var(--flag-black-text)" },
  Orange: { bg: "var(--flag-orange-bg)", text: "var(--flag-orange-text)" },
  Purple: { bg: "var(--flag-purple-bg)", text: "var(--flag-purple-text)" },
  "Given First Notice": { bg: "var(--flag-orange-bg)", text: "var(--flag-orange-text)" },
};

const getFriendlyFlagLabel = (color) => {
  return {
    Green:  "Registered",
    Yellow: "Suspected",
    Red:    "Unregistered",
    Orange: "Warning / Notice",
    Black:  "Blacklisted / Non-Responsive",
    Purple: "Closed / Abandoned",
  }[color] || color;
};

const STATUS_COLOR = {
  Assigned:   { bg: "#eff6ff", text: "#3b82f6" },
  Reassigned: { bg: "#fefce8", text: "#ca8a04" },
  Submitted:  { bg: "#f0fdf4", text: "#16a34a" },
  Verified:   { bg: "#f8fafc", text: "var(--color-muted)" },
};

// ── Assign Modal ───────────────────────────────────────────────────────────────
function AssignModal({ report, token, onClose, onSuccess, isClosing }) {
  const isRedo = report.verificationStatus === "Submitted";
  const [inspectors, setInspectors] = useState([]);
  const [selectedUID, setSelectedUID] = useState(
    () => (report.inspectorID != null ? String(report.inspectorID) : ""),
  );
  const [deadline, setDeadline] = useState(
    () => (report.deadline ? report.deadline.slice(0, 16) : "")
  );
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getInspectorsRequest(token)
      .then((data) => {
        const list = Array.isArray(data) ? data : (data.data ?? []);
        setInspectors(
          list.filter(
            (u) =>
              u.isActive !== 0 &&
              u.isActive !== false &&
              u.userRole === "Inspector",
          ),
        );
        setFetching(false);
      })
      .catch(() => {
        setFetching(false);
        setError("Could not load inspectors.");
      });
  }, [token]);

  const handleAssign = async () => {
    if (!selectedUID) { setError("Select an inspector first."); return; }
    if (deadline && new Date(deadline) < new Date()) {
      Swal.fire({
        icon: 'error',
        title: 'Invalid Deadline',
        text: 'It is no longer possible to select any date or time in the past when assigning a task to an inspector.',
        confirmButtonColor: 'var(--color-primary)'
      });
      return;
    }
    setLoading(true);
    setError("");
    try {
      const userID = parseInt(selectedUID, 10);
      if (isRedo) {
        await reassignSubmittedInspectionRequest(report.reportID, userID, deadline, token);
      } else {
        await assignInspectionRequest({ logID: report.logID, userID, deadline }, token);
      }
      Swal.fire({
        icon: 'success',
        title: isRedo ? 'Task Reassigned' : 'Inspector Dispatched',
        text: isRedo ? 'The task has been sent back for redo.' : 'The inspection task has been successfully assigned.',
        timer: 1500,
        showConfirmButton: false
      });
      onSuccess();
      onClose();
    } catch (err) {
      setError(err.message || (isRedo ? "Reassign failed." : "Assignment failed."));
    } finally {
      setLoading(false);
    }
  };

  return createPortal(
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} style={{...s.backdrop, zIndex: 10001}} onClick={!loading ? onClose : undefined}>
      <div className={"modal-panel" + (isClosing ? " closing" : "")} style={s.modal} onClick={e => e.stopPropagation()}>
        <div style={s.modalHeader}>
          <h3 style={s.modalTitle}>
            {isRedo ? "Send Back for Redo" : "Assign Inspector"}
          </h3>
          {!loading && <button className="modal-close-btn" onClick={onClose}><Icon.X /></button>}
        </div>

        <div style={s.flagPreview}>
          <span style={{
            ...s.flagPill,
            background: FLAG_COLOR[report.flagColor]?.bg,
            color: FLAG_COLOR[report.flagColor]?.text,
          }}>{report.flagColor}</span>
          <div>
            <p style={{ fontWeight: 700, fontSize: 14, color: "var(--color-ink)", marginBottom: 2 }}>
              {report.detectedName}
            </p>
            <p style={{ fontSize: 12, color: "var(--color-muted)" }}>
              {report.barangayName}
            </p>
          </div>
        </div>

        {isRedo && (
          <p style={{ fontSize: 13, color: "var(--color-muted)", marginBottom: 16, lineHeight: 1.5 }}>
            Clears the previous submission and moves the report to{" "}
            <strong>Reassigned</strong>. The inspector must submit new evidence and remarks on mobile.
          </p>
        )}

        {error && (
          <div style={s.errorBanner}><Icon.AlertCircle /> &nbsp;{error}</div>
        )}

        <label style={s.fieldLabel}>Select Inspector</label>
        {fetching ? (
          <p style={{ fontSize: 13, color: "var(--color-muted)" }}>Loading inspectors…</p>
        ) : (
          <select
            style={s.fieldSelect}
            value={selectedUID}
            onChange={e => setSelectedUID(e.target.value)}
          >
            <option value="">Choose an inspector…</option>
            {inspectors.map(u => (
              <option key={u.userID} value={u.userID}>{u.fullName}</option>
            ))}
          </select>
        )}

        <label style={s.fieldLabel}>Deadline (Optional)</label>
        <input
          type="datetime-local"
          style={{ ...s.fieldSelect, boxSizing: "border-box", marginTop: 4 }}
          value={deadline}
          min={new Date(new Date().getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)}
          onChange={e => setDeadline(e.target.value)}
        />

        <div style={s.modalFooter}>
          <button className="ghost-btn" onClick={onClose} disabled={loading}>Cancel</button>
          <button className="primary-btn" onClick={handleAssign} disabled={loading || fetching}>
            {loading
              ? isRedo
                ? "Reassigning…"
                : "Assigning…"
              : isRedo
                ? <><Icon.Send /> Reassign for redo</>
                : <><Icon.Send /> Dispatch</>}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// ── Verify Modal ───────────────────────────────────────────────────────────────
function VerifyModal({ report, token, onClose, onSuccess, isClosing }) {
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");

  const handleVerify = async () => {
    setLoading(true);
    setError("");
    try {
      await verifyInspectionRequest(report.reportID, token);
      onSuccess();
      onClose();
    } catch (err) {
      setError(err.message || "Verification failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} style={{...s.backdrop, zIndex: 10001}} onClick={!loading ? onClose : undefined}>
      <div className={"modal-panel" + (isClosing ? " closing" : "")} style={s.modal} onClick={e => e.stopPropagation()}>
        <div style={s.modalHeader}>
          <h3 style={s.modalTitle}>Verify Inspection</h3>
          {!loading && <button className="modal-close-btn" onClick={onClose}><Icon.X /></button>}
        </div>

        <div style={s.flagPreview}>
          <span style={{
            ...s.flagPill,
            background: FLAG_COLOR[report.inspectionResult]?.bg ?? "#f1f5f9",
            color: FLAG_COLOR[report.inspectionResult]?.text ?? "var(--color-muted)",
          }}>{report.inspectionResult ?? "No result"}</span>
          <div>
            <p style={{ fontWeight: 700, fontSize: 14, color: "var(--color-ink)", marginBottom: 2 }}>
              {report.detectedName}
            </p>
            <p style={{ fontSize: 12, color: "var(--color-muted)" }}>
              Inspector: {report.inspectorName}
            </p>
          </div>
        </div>

        {report.remarks && (
          <div style={s.remarksBox}>
            <p style={{ fontSize: 11, fontWeight: 600, color: "var(--color-muted)", marginBottom: 4, textTransform: "uppercase" }}>
              Inspector Notes
            </p>
            <p style={{ fontSize: 13, color: "var(--color-ink)", lineHeight: 1.6 }}>{report.remarks}</p>
          </div>
        )}

        {inspectionEvidenceUrls(report.photoPath).length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <p style={{ fontSize: 11, fontWeight: 600, color: "var(--color-muted)", marginBottom: 8, textTransform: "uppercase" }}>
              Evidence photo{inspectionEvidenceUrls(report.photoPath).length > 1 ? "s" : ""}
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "10px", paddingBottom: "8px" }}>
              {inspectionEvidenceUrls(report.photoPath).map((url, i) => (
                <img
                  key={i}
                  src={url}
                  alt={`Inspection evidence ${i + 1}`}
                  style={{
                    width: "100%",
                    height: 120,
                    objectFit: "cover",
                    borderRadius: "var(--radius-md)",
                    border: "1px solid var(--color-border)",
                  }}
                />
              ))}
            </div>
          </div>
        )}

        {report.deadline && (
          <p style={{ fontSize: 12, color: "var(--color-danger)", marginBottom: report.resolutionTime ? 4 : 16, display: "flex", alignItems: "center", gap: 5, fontWeight: 600 }}>
            <Icon.Clock /> Due: {new Date(report.deadline).toLocaleString()}
          </p>
        )}

        {report.resolutionTime != null && (
          <p style={{ fontSize: 12, color: "var(--color-muted)", marginBottom: 16, display: "flex", alignItems: "center", gap: 5 }}>
            <Icon.Clock /> Resolved in {report.resolutionTime} min
          </p>
        )}

        {error && (
          <div style={s.errorBanner}><Icon.AlertCircle /> &nbsp;{error}</div>
        )}

        <p style={{ fontSize: 13, color: "var(--color-ink)", marginBottom: 20, lineHeight: 1.6 }}>
          Review the evidence and notes above. Confirming will update the flag color to&nbsp;
          <strong>{report.inspectionResult}</strong> on the map.
          This action cannot be undone.
        </p>

        <div style={s.modalFooter}>
          <button className="ghost-btn" onClick={onClose} disabled={loading}>Cancel</button>
          <button className="primary-btn" onClick={handleVerify} disabled={loading}>
            {loading ? "Verifying…" : <><Icon.Check /> Confirm & Verify</>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Detail Modal ───────────────────────────────────────────────────────────────
function InspectionDetailModal({ report, isAdmin, onAssign, onVerify, onClose, isClosing }) {
  const [enlargedImage, setEnlargedImage] = useState(null);
  
  const flagMeta    = FLAG_COLOR[report.flagColor]   ?? FLAG_COLOR.Red;
  const resultMeta  = FLAG_COLOR[report.inspectionResult] ?? null;
  const statusMeta  = STATUS_COLOR[report.verificationStatus] ?? STATUS_COLOR.Assigned;

  return createPortal(
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} style={s.backdrop} onClick={onClose}>
      <div className={"modal-panel" + (isClosing ? " closing" : "")} style={{ ...s.modal, width: 520 }} onClick={e => e.stopPropagation()}>
        <div style={s.modalHeader}>
          <h3 style={s.modalTitle}>Inspection Details</h3>
          <button style={s.closeBtn} onClick={onClose}><Icon.X /></button>
        </div>

        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
            <h2 style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>{report.detectedName}</h2>
          </div>
          <p style={{ fontSize: 13, color: "var(--color-muted)", display: "flex", alignItems: "center", gap: 5, margin: 0 }}>
            <Icon.MapPin /> {report.barangayName ?? "Unknown barangay"}
          </p>
        </div>

        <div style={{ border: "1px solid var(--color-border)", borderRadius: 12, marginBottom: 24, overflow: "hidden" }}>
          <div style={{ display: "flex" }}>
            <div style={{ flex: 1, padding: "12px 16px", borderRight: "1px solid var(--color-border)", borderBottom: report.inspectionResult || report.noticeLevel > 0 ? "1px solid var(--color-border)" : "none" }}>
              <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Current Flag Color</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 700, color: flagMeta.text }}>
                <Icon.Flag size={14} /> {report.flagColor}
              </span>
            </div>
            <div style={{ flex: 1, padding: "12px 16px", borderBottom: report.inspectionResult || report.noticeLevel > 0 ? "1px solid var(--color-border)" : "none" }}>
              <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Status</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 700, color: statusMeta.text }}>
                {report.verificationStatus}
              </span>
              {report.wasReassigned === 1 && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 4, background: "#fefce8", color: "#ca8a04", border: "1px solid rgba(202,138,4,0.2)", marginTop: 6 }}>
                  <Icon.RefreshCw /> Reassigned
                </span>
              )}
            </div>
          </div>
          {(report.inspectionResult || report.noticeLevel > 0) && (
            <div style={{ display: "flex" }}>
              {report.inspectionResult && (
                <div style={{ flex: 1, padding: "12px 16px", borderRight: report.noticeLevel > 0 ? "1px solid var(--color-border)" : "none" }}>
                  <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Result</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 700, color: resultMeta?.text ?? "var(--color-ink)" }}>
                    {formatResult(report.inspectionResult)}
                  </span>
                </div>
              )}
              {report.noticeLevel > 0 && (
                <div style={{ flex: 1, padding: "12px 16px" }}>
                  <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Notice Level</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 800, color: "#ea580c" }}>
                    {report.noticeLevel === 1 ? "1st Notice" : report.noticeLevel === 2 ? "2nd Notice" : report.noticeLevel === 3 ? "3rd Notice" : "Escalated"}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ marginBottom: 24 }}>
          <h4 style={{ fontSize: 14, fontWeight: 800, color: "var(--color-ink)", marginBottom: 12, marginTop: 0 }}>Assignment Info</h4>
          <div style={{ border: "1px solid var(--color-border)", borderRadius: 12, overflow: "hidden" }}>
            <div style={{ padding: "12px 16px", borderBottom: (report.resolutionTime != null || report.deadline) ? "1px solid var(--color-border)" : "none" }}>
              <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Inspector</span>
              <span style={{ fontSize: 14, color: "var(--color-ink)", fontWeight: 600 }}>{report.inspectorName ?? "Unassigned"}</span>
            </div>
            {(report.resolutionTime != null || report.deadline) && (
              <div style={{ display: "flex" }}>
                {report.resolutionTime != null && (
                  <div style={{ flex: 1, padding: "12px 16px", borderRight: report.deadline ? "1px solid var(--color-border)" : "none" }}>
                    <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Resolution Time</span>
                    <span style={{ fontSize: 14, color: "var(--color-ink)", fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}><Icon.Clock size={14} /> {report.resolutionTime} min</span>
                  </div>
                )}
                {report.deadline && (
                  <div style={{ flex: 1, padding: "12px 16px" }}>
                    <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Deadline</span>
                    <span style={{ fontSize: 14, color: "var(--color-danger)", fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}><Icon.Clock size={14} /> {new Date(report.deadline).toLocaleString()}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {report.remarks && (
          <div style={{ marginBottom: 24 }}>
            <h4 style={{ fontSize: 14, fontWeight: 800, color: "var(--color-ink)", marginBottom: 12, marginTop: 0 }}>Inspector Remarks</h4>
            <p style={{ fontSize: 14, color: "var(--color-ink)", lineHeight: 1.6, padding: "12px 16px", borderRadius: 12, border: "1px solid var(--color-border)", margin: 0 }}>
              {report.remarks}
            </p>
          </div>
        )}

        {inspectionEvidenceUrls(report.photoPath).length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <h4 style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8, marginTop: 0 }}>
              Evidence Photo{inspectionEvidenceUrls(report.photoPath).length > 1 ? "s" : ""}
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "10px", paddingBottom: "8px" }}>
              {inspectionEvidenceUrls(report.photoPath).map((url, i) => (
                <img
                  key={i}
                  src={url}
                  alt={`Evidence ${i + 1}`}
                  onClick={() => setEnlargedImage(url)}
                  style={{
                    width: "100%",
                    height: 120,
                    objectFit: "cover",
                    borderRadius: 8,
                    border: "1px solid var(--color-border)",
                    cursor: "zoom-in"
                  }}
                />
              ))}
            </div>
          </div>
        )}

        {isAdmin && (
          <div style={{ display: "flex", gap: 12, marginTop: 24, flexWrap: "wrap" }}>
            {(report.verificationStatus === "Assigned" ||
              report.verificationStatus === "Reassigned" ||
              (report.verificationStatus === "Verified" && report.inspectionResult !== "Black")) && (
              <button className="ghost-btn" style={{ fontSize: 14, fontWeight: 600, padding: "12px 16px", flex: 1, border: "1px solid var(--color-border-soft)", background: "transparent", color: "var(--color-ink)" }}
                onClick={(e) => { e.stopPropagation(); onAssign(report); }}>
                Reassign
              </button>
            )}
            {report.verificationStatus === "Submitted" && (
              <>
                <button
                  className="ghost-btn"
                  style={{ fontSize: 14, fontWeight: 600, padding: "12px 16px", flex: 1, border: "1px solid var(--color-border-soft)", background: "transparent", color: "var(--color-ink)" }}
                  onClick={(e) => { e.stopPropagation(); onAssign(report); }}
                >
                  Send back
                </button>
                <button
                  className="primary-btn"
                  style={{ fontSize: 14, fontWeight: 600, padding: "12px 16px", flex: 1 }}
                  onClick={(e) => { e.stopPropagation(); onVerify(report); }}
                >
                  <Icon.Check size={18} /> Verify
                </button>
              </>
            )}
            {report.verificationStatus === "Verified" && report.noticeLevel > 0 && report.noticeLevel < 4 && (
              <button
                className="primary-btn"
                style={{ fontSize: 14, fontWeight: 600, padding: "12px 16px", flex: 1, background: "#e65100", borderColor: "#e65100" }}
                onClick={(e) => { e.stopPropagation(); onAssign(report); }}
              >
                <Icon.Send size={18} /> Follow-up
              </button>
            )}
          </div>
        )}

        {enlargedImage && (
          <div 
            style={{ position: "fixed", inset: 0, zIndex: 100000, background: "rgba(0,0,0,0.85)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}
            onClick={(e) => { e.stopPropagation(); setEnlargedImage(null); }}
          >
            <img src={enlargedImage} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: 12, boxShadow: "0 25px 50px rgba(0,0,0,0.5)" }} onClick={e => e.stopPropagation()} />
            <button 
              style={{ position: "absolute", top: 24, right: 24, background: "rgba(255,255,255,0.1)", border: "none", color: "#fff", width: 48, height: 48, borderRadius: "50%", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", transition: "background 0.2s" }}
              onMouseOver={e => e.currentTarget.style.background = "rgba(255,255,255,0.2)"}
              onMouseOut={e => e.currentTarget.style.background = "rgba(255,255,255,0.1)"}
              onClick={(e) => { e.stopPropagation(); setEnlargedImage(null); }}
            >
              <Icon.X size={24} />
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}

// ── Column Focus Modal (Grid View) ─────────────────────────────────────────────
function ColumnFocusModal({ status, reports, isAdmin, onAssign, onVerify, onViewDetail, onClose, isClosing }) {
  const [search, setSearch] = useState("");
  const [filterFlag, setFilterFlag] = useState("");

  const statusMeta = STATUS_COLOR[status] ?? STATUS_COLOR.Assigned;

  const filteredReports = reports.filter(r => {
    if (filterFlag && r.flagColor !== filterFlag) return false;
    if (search) {
      const q = search.toLowerCase();
      const hay = [
        r.detectedName, r.barangayName, r.reportID, r.logID, r.inspectorName
      ].join(" ").toLowerCase();
      return hay.includes(q);
    }
    return true;
  });

  return createPortal(
    <div className="modal-backdrop" onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="modal-panel modal-content saas-card" onClick={e => e.stopPropagation()} style={{ width: 1040, maxWidth: "95vw", height: "85vh", display: "flex", flexDirection: "column", padding: 32, borderRadius: 24, background: "var(--color-modal-bg)", boxShadow: "0 24px 48px rgba(0,0,0,0.2)" }}>
        
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 12, height: 12, borderRadius: "50%", background: statusMeta.text, boxShadow: "0 2px 8px rgba(0,0,0,0.2)" }} />
              {status} Backlog <span style={{ color: "var(--color-muted)", fontSize: 16, fontWeight: 600 }}>({reports.length})</span>
            </h2>
            
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <div style={{ position: "relative" }}>
                <svg style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--color-muted)" }} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                <input 
                  type="text" 
                  placeholder="Search name or ID..." 
                  className="saas-input" 
                  style={{ padding: "8px 14px 8px 36px", width: 260, borderRadius: 8, background: "transparent" }}
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
              </div>
              
              <button className="modal-close-btn" onClick={onClose}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
            </div>
          </div>
          
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {["all", ...Object.keys(FLAG_COLOR)].map(c => {
              const count = c === "all" ? reports.length : reports.filter(r => r.flagColor === c).length;
              if (count === 0 && c !== "all") return null;
              
              const isActive = filterFlag === c || (filterFlag === "" && c === "all");
              const pillBg = isActive ? (c === "all" ? "var(--color-ink)" : (FLAG_COLOR[c]?.text ?? "var(--color-ink)")) : "var(--color-hover)";
              const pillText = isActive ? (c === "all" ? "var(--color-surface)" : "#fff") : "var(--color-muted)";
              const pillBorder = isActive ? "transparent" : "var(--color-border-soft)";
              
              return (
                <button
                  key={c}
                  onClick={() => setFilterFlag(c === "all" ? "" : c)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 20,
                    fontSize: 11,
                    fontWeight: 700,
                    cursor: "pointer",
                    border: "1px solid",
                    background: pillBg,
                    color: pillText,
                    borderColor: pillBorder,
                  }}
                >
                  {c === "all" ? "All" : (getFriendlyFlagLabel(c) ?? c)} ({count})
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto", paddingRight: 16 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
            {filteredReports.map(f => {
              const fc = FLAG_COLOR[f.flagColor] || FLAG_COLOR.Green;
              return (
                <div 
                  key={f.reportID ?? `log-${f.logID}`}
                  className="hover-lift"
                  onClick={() => onViewDetail(f)}
                  style={{ 
                    background: "var(--color-surface)", 
                    borderRadius: 16, 
                    padding: 20, 
                    display: "flex", 
                    flexDirection: "column", 
                    justifyContent: "space-between",
                    cursor: "pointer",
                    boxShadow: "0 2px 10px rgba(0,0,0,0.06)",
                    minHeight: 120
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 12, background: fc.bg || "var(--color-hover)", color: fc.text || "var(--color-ink)", display: "flex", alignItems: "center", gap: 6 }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>
                        {getFriendlyFlagLabel(f.flagColor) || f.flagColor || "Unknown"}
                      </span>
                      {f.verificationStatus && (
                        <>
                          <span style={{ color: "var(--color-muted)", fontSize: 12 }}>&gt;</span>
                          <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 12, background: STATUS_COLOR[f.verificationStatus]?.bg || "var(--color-hover)", color: STATUS_COLOR[f.verificationStatus]?.text || "var(--color-ink)" }}>
                            {f.verificationStatus}
                          </span>
                        </>
                      )}
                      {f.wasReassigned === 1 && (
                        <span style={{ fontSize: 10, fontWeight: 800, padding: "3px 8px", borderRadius: 4, background: "#fefce8", color: "#ca8a04", display: "inline-flex", alignItems: "center", gap: 4, border: "1px solid rgba(202,138,4,0.2)" }}>
                          <Icon.RefreshCw /> Reassigned
                        </span>
                      )}
                    </div>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                    <div style={{ flex: 1, paddingRight: 16 }}>
                      <h4 style={{ margin: "0 0 8px 0", fontSize: 16, fontWeight: 800, color: "var(--color-ink)", lineHeight: 1.3 }}>{f.detectedName || "Unknown Establishment"}</h4>
                      <p style={{ margin: 0, fontSize: 13, color: "var(--color-muted)", display: "flex", alignItems: "center", gap: 6 }}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
                        {f.barangayName ? f.barangayName.replace(/Barangay\s+/i, "Brgy. ") : "—"}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {filteredReports.length === 0 && (
            <div style={{ textAlign: "center", padding: "60px", display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
              <img src="/searching.png" alt="No reports" style={{ height: 120, objectFit: "contain", opacity: 0.9 }} />
              <p style={{ color: "var(--color-muted)", fontSize: 14, margin: 0 }}>No reports match your filters.</p>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

// ── Inspection Card ────────────────────────────────────────────────────────────
function InspectionCard({ report, isAdmin, onAssign, onVerify, onViewDetail, isCompact }) {
  const statusMeta = STATUS_COLOR[report.verificationStatus] ?? STATUS_COLOR.Assigned;
  const flagMeta = FLAG_COLOR[report.flagColor] ?? FLAG_COLOR.Green;

  // Uniform card styling for every report — overdue state is intentionally
  // not expressed via card borders so all cards look identical.
  const cardStyle = { ...s.card, padding: "12px 16px" };

  return (
    <div style={cardStyle} onClick={() => onViewDetail(report)}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ ...s.flagPill, background: flagMeta.bg, color: flagMeta.text }}>
            <Icon.Flag /> {getFriendlyFlagLabel(report.flagColor)}
          </span>
          {report.noticeLevel > 0 && (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--color-muted)" strokeWidth="2.5">
                <polyline points="9 18 15 12 9 6" />
              </svg>
              <span style={{ fontSize: 10, fontWeight: 800, padding: "3px 6px", borderRadius: 4, background: report.noticeLevel === 4 ? "var(--color-ink)" : "#ea580c", color: report.noticeLevel === 4 ? "var(--color-modal-bg)" : "#fff" }}>
                {report.noticeLevel === 1 ? "1st Notice" : report.noticeLevel === 2 ? "2nd Notice" : report.noticeLevel === 3 ? "3rd Notice" : "Escalated"}
              </span>
            </>
          )}
          {report.wasReassigned === 1 && (
            <span style={{ fontSize: 10, fontWeight: 800, padding: "3px 8px", borderRadius: 4, background: "#fefce8", color: "#ca8a04", display: "inline-flex", alignItems: "center", gap: 4, border: "1px solid rgba(202,138,4,0.2)" }}>
              <Icon.RefreshCw /> Reassigned
            </span>
          )}
        </div>
      </div>

      {/* Business name, Address & View Button Row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div style={{ paddingRight: 12 }}>
          <p style={{ fontSize: 15, fontWeight: 800, color: "var(--color-ink)", marginBottom: 6, lineHeight: 1.3 }}>
            {report.detectedName}
          </p>
          <p style={{ fontSize: 12, color: "var(--color-muted)", display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
            <Icon.MapPin /> {report.barangayName ?? "Unknown barangay"}
          </p>
        </div>
        
        <button 
          className="ghost-btn" 
          style={{ width: 36, height: 36, padding: 0, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "50%", flexShrink: 0, background: "var(--color-hover)" }}
          onClick={(e) => { e.stopPropagation(); onViewDetail(report); }}
          title="View Details"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="9 18 15 12 9 6" />
          </svg>
        </button>
      </div>
    </div>
  );
}

// ── Column ─────────────────────────────────────────────────────────────────────
function KanbanColumn({ status, reports, isAdmin, onAssign, onVerify, onViewDetail, isCompact, isCollapsed, onToggleCollapse, onFocusColumn }) {
  const statusMeta = STATUS_COLOR[status] ?? STATUS_COLOR.Assigned;

  const visibleReports = reports.slice(0, 5);
  const hasMore = reports.length > 5;

  if (isCollapsed) {
    return (
      <div style={{ ...s.column, flex: "0 0 60px", minWidth: 60, cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", padding: "16px 8px" }} onClick={onToggleCollapse}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: statusMeta.text, marginBottom: 16 }} />
        <span style={{ ...s.columnTitle, writingMode: "vertical-rl", transform: "rotate(180deg)", letterSpacing: "0.1em", marginBottom: 16 }}>{status}</span>
        <span style={{ ...s.statusPill, background: statusMeta.bg, color: statusMeta.text }}>
          {reports.length}
        </span>
      </div>
    );
  }

  return (
    <div style={s.column}>
      <div style={{ ...s.columnHeader, cursor: "pointer" }} onClick={onToggleCollapse}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: statusMeta.text }} />
          <span style={s.columnTitle}>{status}</span>
        </div>
        <span style={{ ...s.statusPill, background: statusMeta.bg, color: statusMeta.text }}>
          {reports.length}
        </span>
      </div>
      <div style={s.columnBody}>
        {reports.length === 0 ? (
          <div style={{ ...s.emptyCol, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
            <img src="/searching.png" alt="Empty" style={{ height: 80, objectFit: "contain", opacity: 0.8 }} />
            No reports
          </div>
        ) : (
          <>
            {visibleReports.map(r => (
              <InspectionCard
                key={r.reportID ?? `log-${r.logID}`}
                report={r}
                isAdmin={isAdmin}
                onAssign={onAssign}
                onVerify={onVerify}
                onViewDetail={onViewDetail}
                isCompact={isCompact}
              />
            ))}
            {hasMore && (
              <button 
                className="ghost-btn" 
                style={{ 
                  width: "100%", padding: "12px", fontSize: 12, fontWeight: 800, 
                  color: "var(--color-primary)", marginTop: 4, background: "rgba(0,0,0,0.02)",
                  border: "1px dashed var(--color-primary-light)", borderRadius: "var(--radius-sm)",
                  cursor: "pointer", transition: "all 0.2s"
                }}
                onClick={(e) => { e.stopPropagation(); onFocusColumn(status); }}
              >
                View all {reports.length} reports in Grid
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function InspectionPage() {
  const { token, user } = useContext(AuthContext);
  const isAdmin = ["Admin", "SUPER_ADMIN", "System Administrator"].includes(user?.role);

  const [reports,   setReports]   = useState([]);
  const [total,     setTotal]     = useState(0);
  // All report rows in the DB (incl. older revisions collapsed by the
  // latest-per-target query) — lets the UI disclose hidden history.
  const [totalRows, setTotalRows] = useState(0);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState("");

  // Kanban View Optimization State
  const isCompact = true;
  const [collapsedCols, setCollapsedCols] = useState(new Set());
  const [focusColumn, setFocusColumn] = useState(null);

  const toggleCollapse = (status) => {
    const next = new Set(collapsedCols);
    if (next.has(status)) next.delete(status);
    else next.add(status);
    setCollapsedCols(next);
  };

  // Modal state
  const [assignTarget, setAssignTarget] = useState(null);
  const [verifyTarget, setVerifyTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);

  // Filter state (admin only)
  const [filterStatus, setFilterStatus] = useState("");
  const [search, setSearch] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);

  // ── Fetch ────────────────────────────────────────────────────────────────────
  const fetchReports = useCallback(async (isSilent = false) => {
    if (!token) return;
    if (!isSilent) {
      setLoading(true);
      setIsRefreshing(true);
    }
    setError("");
    try {
      let result;
      if (isAdmin) {
        result = await getInspectionsRequest(
          { status: filterStatus || undefined, limit: 100 },
          token
        );
        setReports(result.data ?? []);
        setTotal(result.total ?? 0);
        setTotalRows(result.total_rows ?? result.total ?? 0);
      } else {
        result = await getInspectorTasksRequest(token);
        setReports(result.data ?? []);
        setTotal(result.total ?? 0);
        setTotalRows(result.total_rows ?? result.total ?? 0);
      }
    } catch (err) {
      if (!isSilent) {
        setError(err.message || "Failed to load inspections.");
      }
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, [token, isAdmin, filterStatus]);

  useEffect(() => {
    fetchReports(false);
  }, [fetchReports]);

  useEffect(() => {
    const onInspectionUpdate = () => fetchReports(true);
    window.addEventListener("revela:inspection-update", onInspectionUpdate);
    window.addEventListener("revela:flag-update", onInspectionUpdate);
    window.addEventListener("revela:global-refresh", onInspectionUpdate);

    // Silent background auto-polling every 15s
    const pollTimer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        fetchReports(true);
      }
    }, 15000);

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        fetchReports(true);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleVisibility);

    return () => {
      window.removeEventListener("revela:inspection-update", onInspectionUpdate);
      window.removeEventListener("revela:flag-update", onInspectionUpdate);
      window.removeEventListener("revela:global-refresh", onInspectionUpdate);
      window.clearInterval(pollTimer);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleVisibility);
    };
  }, [fetchReports]);

  // ── Derived ──────────────────────────────────────────────────────────────────
  const q = search.trim().toLowerCase();
  const filteredReports = q
    ? reports.filter((r) => {
        const hay = [
          r.detectedName,
          r.barangayName,
          r.inspectorName,
          r.verificationStatus,
          r.inspectionResult,
          r.reportID,
          r.logID,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      })
    : reports;

  const byStatus = (status) => {
    return filteredReports.filter((r) => r.verificationStatus === status);
  };

  // Admin sees all 4 columns; inspectors only see Assigned + Reassigned
  const visibleCols = isAdmin
    ? STATUS_COLS
    : ["Assigned", "Reassigned"];

  return (
    <DashboardLayout user={{ initials: user?.fullName?.charAt(0) ?? "?", name: user?.fullName ?? "" }}>

      {/* Page header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Inspection Dispatch</h1>
          <p className="page-subtitle">
            {isAdmin
              ? "Assign, track, and verify field inspections across Mataasnakahoy."
              : "Your active inspection assignments."}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {/* Quick manual refresh button */}
          <button
            className="quick-refresh-btn"
            type="button"
            onClick={() => fetchReports(false)}
            disabled={isRefreshing}
            title="Refresh inspection list"
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

          {/* Total badge */}
          {!loading && (
            <span
              style={s.totalPill}
              title={
                totalRows > total
                  ? `${totalRows - total} older revision${totalRows - total !== 1 ? "s" : ""} of re-dispatched flags are grouped under their latest report.`
                  : undefined
              }
            >
              {total} report{total !== 1 ? "s" : ""}
              {totalRows > total && (
                <span style={{ opacity: 0.65, fontWeight: 600 }}>
                  {" "}· {totalRows - total} in history
                </span>
              )}
            </span>
          )}

          {/* Status filter — admin only */}
          {isAdmin && (
            <select
              style={s.filterSelect}
              value={filterStatus}
              onChange={e => setFilterStatus(e.target.value)}
            >
              <option value="">All Statuses</option>
              {STATUS_COLS.map(st => (
                <option key={st} value={st}>{st}</option>
              ))}
            </select>
          )}

          {/* Live Search Bar */}
          <div className="search-bar" style={{ width: 240 }}>
            <Icon.Search />
            <input
              type="text"
              placeholder="Search name, ID, or area..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <button className="ghost-btn" onClick={fetchReports} style={{ fontSize: 13 }}>
            <Icon.RefreshCw /> Refresh
          </button>
        </div>
      </div>


      {/* Error */}
      {error && (
        <div style={s.errorBanner}>
          <Icon.AlertCircle /> &nbsp;{error}
        </div>
      )}

      {/* Kanban board */}
      {loading ? (
        <div style={s.loadingState}>Loading inspections…</div>
      ) : (
        <div style={{ ...s.board, gridTemplateColumns: `repeat(${visibleCols.length}, 1fr)` }}>
          {visibleCols.map(status => (
            <KanbanColumn
              key={status}
              status={status}
              reports={byStatus(status)}
              isAdmin={isAdmin}
              onAssign={r => setAssignTarget(r)}
              onVerify={r => setVerifyTarget(r)}
              onViewDetail={r => setDetailTarget(r)}
              isCompact={isCompact}
              isCollapsed={collapsedCols.has(status)}
              onToggleCollapse={() => toggleCollapse(status)}
              onFocusColumn={setFocusColumn}
            />
          ))}
        </div>
      )}

      {/* Footer */}
      <footer className="saas-footer frosted-glass">
        <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
        <p className="footer-links"><span>BPLO Portal</span> &bull; <span>System Settings</span></p>
      </footer>

      {/* Assign Modal */}
      <AnimatePresence isVisible={!!assignTarget}>
        <AssignModal
          report={assignTarget}
          token={token}
          onClose={() => setAssignTarget(null)}
          onSuccess={fetchReports}
        />
      </AnimatePresence>

      {/* Verify Modal */}
      <AnimatePresence isVisible={!!verifyTarget}>
        <VerifyModal
          report={verifyTarget}
          token={token}
          onClose={() => setVerifyTarget(null)}
          onSuccess={fetchReports}
        />
      </AnimatePresence>

      {/* Detail Modal */}
      <AnimatePresence isVisible={!!detailTarget}>
        <InspectionDetailModal
          report={detailTarget}
          isAdmin={isAdmin}
          onAssign={(r) => { setDetailTarget(null); setAssignTarget(r); }}
          onVerify={(r) => { setDetailTarget(null); setVerifyTarget(r); }}
          onClose={() => setDetailTarget(null)}
        />
      </AnimatePresence>

      {/* Grid View Modal */}
      <AnimatePresence isVisible={!!focusColumn}>
        <ColumnFocusModal
          status={focusColumn}
          reports={byStatus(focusColumn)}
          isAdmin={isAdmin}
          onAssign={r => setAssignTarget(r)}
          onVerify={r => setVerifyTarget(r)}
          onViewDetail={r => setDetailTarget(r)}
          onClose={() => setFocusColumn(null)}
        />
      </AnimatePresence>

    </DashboardLayout>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────────
const s = {
  board: {
    display: "grid",
    gap: 20,
    alignItems: "start",
  },
  column: {
    background: "var(--color-input-bg)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-xl)",
    overflow: "hidden",
    boxShadow: "0 12px 32px rgba(0, 0, 0, 0.05)",
  },
  columnHeader: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "16px 20px",
    borderBottom: "1px solid var(--color-border-soft)",
    background: "var(--color-input-bg)",
    backdropFilter: "blur(12px)",
    position: "sticky",
    top: 0,
    zIndex: 10,
  },
  columnTitle: {
    fontSize: 13, fontWeight: 800, color: "var(--color-ink)",
    textTransform: "uppercase", letterSpacing: "0.08em",
    display: "flex", alignItems: "center", gap: 8
  },
  columnBody: {
    padding: "16px", display: "flex", flexDirection: "column", gap: 14,
    minHeight: 120,
  },
  emptyCol: {
    textAlign: "center", padding: "32px 0",
    fontSize: 13, color: "var(--color-muted)", fontWeight: 500
  },

  // Card
  card: {
    background: "var(--color-modal-bg)",
    borderRadius: "var(--radius-lg)",
    padding: "16px 20px",
    boxShadow: "0 4px 16px rgba(0,0,0,0.06)",
    cursor: "pointer",
    transition: "transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
  },
  cardName: {
    fontSize: 14, fontWeight: 700, color: "var(--color-ink)",
    marginBottom: 4,
  },
  cardMeta: {
    fontSize: 12, color: "var(--color-muted)",
    display: "flex", alignItems: "center", gap: 4, marginBottom: 10,
  },
  cardInspector: {
    display: "flex", alignItems: "center", gap: 8,
    paddingTop: 10, borderTop: "1px solid var(--color-border-soft)",
    marginBottom: 6,
  },
  avatar: {
    width: 24, height: 24, borderRadius: "50%",
    color: "#fff", display: "flex", alignItems: "center",
    justifyContent: "center", fontSize: 10, fontWeight: 700, flexShrink: 0,
  },
  cardActions: {
    display: "flex", gap: 8, marginTop: 10,
    paddingTop: 10, borderTop: "1px solid var(--color-border-soft)",
  },
  remarksPreview: {
    fontSize: 11, color: "var(--color-muted)",
    fontStyle: "italic", marginTop: 6, lineHeight: 1.5,
    display: "-webkit-box", WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical", overflow: "hidden",
  },

  // Pills
  flagPill: {
    display: "inline-flex", alignItems: "center", gap: 4,
    fontSize: 10, fontWeight: 800, padding: "3px 8px",
    borderRadius: 10, letterSpacing: "0.05em",
  },
  statusPill: {
    fontSize: 10, fontWeight: 700, padding: "3px 8px",
    borderRadius: 10, letterSpacing: "0.05em",
  },
  totalPill: {
    fontSize: 12, fontWeight: 600, color: "var(--color-muted)",
    background: "var(--color-input-bg)",
    border: "1px solid var(--color-border)",
    padding: "6px 12px", borderRadius: 20,
  },

  // Filter
  filterSelect: {
    padding: "8px 12px", borderRadius: "var(--radius-sm)",
    border: "1px solid var(--color-border)", fontSize: 13,
    fontFamily: "var(--font-base)", color: "var(--color-ink)",
    background: "var(--color-modal-bg)", cursor: "pointer",
  },

  // Loading / error
  loadingState: {
    textAlign: "center", padding: "48px 0",
    fontSize: 14, color: "var(--color-muted)",
  },
  errorBanner: {
    display: "flex", alignItems: "center", gap: 8,
    background: "var(--color-error-bg)", border: "1px solid var(--color-error-border)",
    borderRadius: "var(--radius-sm)", padding: "10px 14px",
    fontSize: 13, color: "var(--color-danger)", marginBottom: 16,
  },

  // Modal
  backdrop: {
    position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)",
    backdropFilter: "blur(4px)", display: "flex",
    alignItems: "center", justifyContent: "center", zIndex: 10000,
  },
  modal: {
    background: "var(--color-modal-bg)", borderRadius: "var(--radius-xl)",
    padding: 32, width: 440,
    boxShadow: "0 25px 50px rgba(0,0,0,0.15)",
    maxHeight: "85vh",
    overflowY: "auto",
  },
  modalHeader: {
    display: "flex", justifyContent: "space-between",
    alignItems: "center", marginBottom: 20,
  },
  modalTitle: { fontSize: 18, fontWeight: 700, color: "var(--color-ink)" },
  closeBtn: {
    background: "none", border: "none",
    color: "var(--color-muted)", cursor: "pointer", display: "flex",
  },
  modalFooter: {
    display: "flex", justifyContent: "flex-end",
    gap: 10, marginTop: 24,
  },
  flagPreview: {
    display: "flex", alignItems: "center", gap: 12,
    background: "var(--color-hover)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-md)", padding: "12px 14px", marginBottom: 20,
  },
  fieldLabel: {
    display: "block", fontSize: 11, fontWeight: 600,
    color: "var(--color-ink)", marginBottom: 8,
    textTransform: "uppercase", letterSpacing: "0.05em",
  },
  fieldSelect: {
    width: "100%", padding: "10px 12px",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-sm)", fontSize: 14,
    fontFamily: "var(--font-base)", color: "var(--color-ink)",
    background: "var(--color-modal-bg)", cursor: "pointer", marginBottom: 4,
  },
  remarksBox: {
    background: "var(--color-hover)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-sm)",
    padding: "10px 14px", marginBottom: 14,
  },
};
