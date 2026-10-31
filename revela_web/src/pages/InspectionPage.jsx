/**
 * InspectionPage.jsx
 * Wired to /api/inspections — admin kanban + assign modal + verify action.
 * Inspectors only see their own tasks via the same page (role-gated views).
 */

import { useState, useEffect, useCallback, useContext, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import DashboardLayout from "../components/DashboardLayout";
import { useAppDataRefresh, useSessionDataset } from "../components/useAppDataRefresh";
import { SkeletonKanbanBoard } from "../components/LoadingSkeleton";
import Footer from "../components/Footer";
import { AuthContext } from "../context/authContext";
import AuthenticatedEvidenceImage from "../components/AuthenticatedEvidenceImage";
import {
  getInspectionWorkloadRequest,
  getInspectorTasksRequest,
  assignInspectionRequest,
  reassignSubmittedInspectionRequest,
  verifyInspectionRequest,
  previewGreenRegistryLinkRequest,
  previewWarningRegistryLinkRequest,
  getInspectorsRequest,
  parseInspectionEvidence,
  clearWarningRequest,
} from "../services/api";
import Swal from "sweetalert2";
import AnimatePresence from "../components/AnimatePresence";
import InspectionDialog from "../components/InspectionDialog";
import BusinessIDReview from "../components/BusinessIDReview";
import { confirmBusinessID } from "../components/businessIDReviewFlow";
import {
  canFollowUpInspection,
  canReassignInspection,
} from "../components/dispatchEligibility";
import { canClearInspectionWarning, clearInspectionWarning } from "../components/registryLadderPolicy";
import { dashboardUpdatedLabel, inspectionColumnPreview, inspectionDeadline, inspectionPeriodLabel, matchesDispatchSearch, matchesGridSearch, workloadFilterLabel, workloadResultLabel } from "./inspectionPresentation";
import { formatElapsedMinutes } from "../utils/formatElapsedMinutes";
import "../styles/InspectionPage.css";

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

const distanceMeters = (lat1, lng1, lat2, lng2) => {
  const toRadians = (degrees) => degrees * Math.PI / 180;
  const dLat = toRadians(lat2 - lat1);
  const dLng = toRadians(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) * Math.sin(dLng / 2) ** 2;
  return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

const finiteNumberOrNaN = (value) =>
  value === null || value === undefined || value === "" ? Number.NaN : Number(value);

// ── Icons ──────────────────────────────────────────────────────────────────────
const Icon = {
  MapPin: () => (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="10" r="3"/><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/>
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
  Calendar: () => (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  ),
  Dashboard: () => (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
};

// ── Constants ──────────────────────────────────────────────────────────────────
const STATUS_COLS = ["Assigned", "Reassigned", "Submitted", "Verified"];
const WORKLOAD_PAGE_SIZE = 20;

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
  Assigned:   { bg: "var(--dispatch-assigned-bg)", text: "var(--dispatch-assigned-text)" },
  Reassigned: { bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)" },
  Submitted:  { bg: "var(--flag-green-bg)", text: "var(--flag-green-text)" },
  Verified:   { bg: "var(--color-hover)", text: "var(--color-muted)" },
};

// ── Assign Modal ───────────────────────────────────────────────────────────────
function AssignModal({ report, token, onClose, onSuccess, isClosing, returnFocusRef, fallbackFocusRef }) {
  const isRedo = report.verificationStatus === "Submitted";
  const isAssignedReassignment = report.verificationStatus === "Assigned";
  const isReassignment = isRedo || isAssignedReassignment;
  const isFollowUp = report.verificationStatus === "Verified";
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
      if (isReassignment) {
        await reassignSubmittedInspectionRequest(report.reportID, userID, deadline, token);
      } else {
        await assignInspectionRequest({ logID: report.logID, userID, deadline }, token);
      }
      Swal.fire({
        icon: 'success',
        title: isReassignment ? 'Task Reassigned' : 'Follow-up Assigned',
        text: isRedo
          ? 'The submitted task has been sent back for redo.'
          : isAssignedReassignment
            ? 'The assigned inspector has been changed.'
            : 'The follow-up inspection has been assigned.',
        timer: 1500,
        showConfirmButton: false
      });
      onSuccess();
      onClose();
    } catch (err) {
      setError(err.message || (isReassignment ? "Reassign failed." : "Assignment failed."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <InspectionDialog
      title={isRedo
        ? "Send Back for Redo"
        : isAssignedReassignment
          ? "Reassign Inspector"
          : isFollowUp
            ? "Assign Follow-up Inspection"
            : "Assign Inspector"}
      onClose={onClose} busy={loading} isClosing={isClosing} layer={10001}
      returnFocusRef={returnFocusRef} fallbackFocusRef={fallbackFocusRef}
    >

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
        {isAssignedReassignment && (
          <p style={{ fontSize: 13, color: "var(--color-muted)", marginBottom: 16, lineHeight: 1.5 }}>
            Changes the inspector assigned to this report.
          </p>
        )}

        {error && (
          <div style={s.errorBanner}><Icon.AlertCircle /> &nbsp;{error}</div>
        )}

        <label htmlFor="dispatch-assign-inspector" style={s.fieldLabel}>Select Inspector</label>
        {fetching ? (
          <p style={{ fontSize: 13, color: "var(--color-muted)" }}>Loading inspectors…</p>
        ) : (
          <select
            id="dispatch-assign-inspector"
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

        <label htmlFor="dispatch-assign-deadline" style={s.fieldLabel}>Deadline (Optional)</label>
        <input
          id="dispatch-assign-deadline"
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
              ? isReassignment ? "Reassigning…" : "Assigning…"
              : isRedo
                ? <><Icon.Send /> Reassign for redo</>
                : isAssignedReassignment
                  ? <><Icon.Send /> Reassign inspector</>
                  : isFollowUp
                    ? <><Icon.Send /> Assign follow-up</>
                    : <><Icon.Send /> Dispatch</>}
          </button>
        </div>
    </InspectionDialog>
  );
}

// ── Verify Modal ───────────────────────────────────────────────────────────────
function VerifyModal({ report, token, onClose, onSuccess, isClosing, returnFocusRef, fallbackFocusRef }) {
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const isGreen = report.inspectionResult === "Green";
  const [businessID, setBusinessID] = useState(report.linkedBusinessID || "");
  const [linkReview, setLinkReview] = useState(null);
  const [registryFields, setRegistryFields] = useState({});
  const submitInFlight = useRef(false);
  const gpsLat = finiteNumberOrNaN(report.verifiedLatitude);
  const gpsLng = finiteNumberOrNaN(report.verifiedLongitude);
  const pinLat = finiteNumberOrNaN(report.latitude);
  const pinLng = finiteNumberOrNaN(report.longitude);
  const hasGps = Number.isFinite(gpsLat) && Number.isFinite(gpsLng);
  const hasPin = Number.isFinite(pinLat) && Number.isFinite(pinLng);
  const distance = hasGps && hasPin ? distanceMeters(gpsLat, gpsLng, pinLat, pinLng) : null;
  const accuracy = finiteNumberOrNaN(report.verifiedAccuracy);
  const hasAccuracy = Number.isFinite(accuracy) && accuracy >= 0;
  const shouldSuggestLocationUpdate = hasGps
    && (!hasPin || distance <= 500)
    && hasAccuracy
    && accuracy <= 100;
  const [updateLocation, setUpdateLocation] = useState(!isGreen && shouldSuggestLocationUpdate);

  const distanceLabel = distance == null
    ? null
    : distance < 1000
      ? `${Math.round(distance)} m`
      : `${(distance / 1000).toFixed(1)} km`;
  const gpsStatus = distance == null
    ? { text: hasGps ? "No current pin" : "No GPS fix", color: "#1d4ed8", background: "#eff6ff" }
    : distance <= 100
      ? { text: "On-site range", color: "#047857", background: "#ecfdf5" }
      : distance <= 500
        ? { text: "Nearby", color: "#a16207", background: "#fefce8" }
        : { text: "Far from pin", color: "#b91c1c", background: "#fef2f2" };

  const handleVerify = async () => {
    if (submitInFlight.current) return;
    submitInFlight.current = true;
    setLoading(true);
    setError("");
    try {
      if (isGreen) {
        await confirmBusinessID({ businessID, review: linkReview, registryFields,
          setReview: setLinkReview, setError,
          preview: id => previewGreenRegistryLinkRequest(report.reportID, id, token),
          save: async current => {
            await verifyInspectionRequest(report.reportID, token, false, {
              businessID: current.businessID, confirmEstablishment: true,
              registryReviewToken: current.reviewToken, registryFields,
            });
            onSuccess();
            onClose();
          },
        });
      } else {
        await verifyInspectionRequest(report.reportID, token, updateLocation);
        onSuccess();
        onClose();
      }
    } catch (err) {
      setError(err.message || "Verification failed.");
    } finally {
      setLoading(false);
      submitInFlight.current = false;
    }
  };

  return (
    <InspectionDialog
      title="Verify Inspection" onClose={onClose} busy={loading} isClosing={isClosing} layer={10001}
      returnFocusRef={returnFocusRef} fallbackFocusRef={fallbackFocusRef}
    >

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

        {isGreen && (
          <section style={{ ...s.remarksBox, marginBottom: 16 }} aria-label="Official registry link">
            <BusinessIDReview businessID={businessID} setBusinessID={setBusinessID}
              review={linkReview} setReview={setLinkReview}
              registryFields={registryFields} setRegistryFields={setRegistryFields}
              busy={loading} setError={setError} initialLinked={Boolean(report.linkedBusinessID)} />
            {error && <p role="alert" style={{ ...s.errorBanner, marginTop: 12 }}><Icon.AlertCircle /> &nbsp;{error}</p>}
          </section>
        )}

        {report.remarks && (
          <div style={s.remarksBox}>
            <p style={{ fontSize: 11, fontWeight: 600, color: "var(--color-muted)", marginBottom: 4, textTransform: "uppercase" }}>
              Inspector Notes
            </p>
            <p style={{ fontSize: 13, color: "var(--color-ink)", lineHeight: 1.6 }}>{report.remarks}</p>
          </div>
        )}

        <div style={{ border: "1px solid var(--color-border)", borderRadius: 8, padding: 12, marginBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 8 }}>
            <p style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", margin: 0, textTransform: "uppercase" }}>
              Inspector GPS
            </p>
            <span style={{ padding: "4px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700, color: gpsStatus.color, background: gpsStatus.background }}>
              {gpsStatus.text}
            </span>
          </div>
          {hasGps ? (
            <>
              <p style={{ fontSize: 12, color: "var(--color-ink)", margin: "0 0 5px" }}>
                {gpsLat.toFixed(6)}, {gpsLng.toFixed(6)}
              </p>
              <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "0 0 5px" }}>
                Current pin: {hasPin ? `${pinLat.toFixed(6)}, ${pinLng.toFixed(6)}` : "No coordinates"}
              </p>
              <p style={{ fontSize: 12, color: "var(--color-muted)", margin: "0 0 10px" }}>
                {hasAccuracy ? `Device accuracy ±${Math.round(accuracy)} m` : "Device accuracy not reported"}
                {distanceLabel ? ` · ${distanceLabel} from current pin` : ""}
              </p>
              {hasAccuracy && accuracy > 100 && (
                <p style={{ fontSize: 12, color: "#a16207", margin: "0 0 10px" }}>
                  GPS accuracy is low; review the position before applying it.
                </p>
              )}
              {!isGreen && <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12, lineHeight: 1.5, color: "var(--color-ink)", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={updateLocation}
                  onChange={event => setUpdateLocation(event.target.checked)}
                  style={{ marginTop: 2 }}
                />
                Update the map pin and registry location to this GPS position
              </label>}
            </>
          ) : (
            <p style={{ fontSize: 12, color: "var(--color-muted)", margin: 0 }}>
              This report has no valid GPS fix. Verification will not change the pin location.
            </p>
          )}
        </div>

        {(() => {
          const evList = parseInspectionEvidence(report.photoPath);
          if (!evList || evList.length === 0) return null;
          const live = evList.filter(e => !e.isArchived && e.url);
          const arch = evList.filter(e => e.isArchived);
          return (
            <div style={{ marginBottom: 14 }}>
              <p style={{ fontSize: 11, fontWeight: 600, color: "var(--color-muted)", marginBottom: 8, textTransform: "uppercase" }}>
                Evidence photo{evList.length > 1 ? "s" : ""}
              </p>
              {live.length > 0 && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "10px", paddingBottom: "8px" }}>
                  {live.map((item, i) => (
                    <AuthenticatedEvidenceImage
                      key={i}
                      url={item.url}
                      token={token}
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
              )}
              {arch.length > 0 && (
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "8px 12px",
                  background: "var(--color-hover)",
                  borderRadius: "var(--radius-md)",
                  border: "1px dashed var(--color-border)",
                  fontSize: 12,
                  color: "var(--color-muted)",
                }}>
                  <span style={{ fontSize: 15 }}>📦</span>
                  <div>
                    <span style={{ fontWeight: 600, color: "var(--color-ink)" }}>
                      {arch.length} photo{arch.length > 1 ? "s" : ""} archived to Municipal PC
                    </span>
                    <span style={{ display: "block", fontSize: 11, opacity: 0.8 }}>
                      Audit records &amp; notes preserved on server
                    </span>
                  </div>
                </div>
              )}
            </div>
          );
        })()}

        {report.deadline && (
          <p style={{ fontSize: 12, color: "var(--color-danger)", marginBottom: report.resolutionTime ? 4 : 16, display: "flex", alignItems: "center", gap: 5, fontWeight: 600 }}>
            <Icon.Clock /> Due: {new Date(report.deadline).toLocaleString()}
          </p>
        )}

        {report.resolutionTime != null && (
          <p style={{ fontSize: 12, color: "var(--color-muted)", marginBottom: 16, display: "flex", alignItems: "center", gap: 5 }}>
            <Icon.Clock /> Resolved in {formatElapsedMinutes(report.resolutionTime)}
          </p>
        )}

        {!isGreen && error && (
          <div style={s.errorBanner}><Icon.AlertCircle /> &nbsp;{error}</div>
        )}

        <p style={{ fontSize: 13, color: "var(--color-ink)", marginBottom: 20, lineHeight: 1.6 }}>
          Review the evidence and notes above. Confirming will update the flag color to&nbsp;
          <strong>{report.inspectionResult}</strong> on the map.
          {isGreen ? " The original pin location will be preserved. Existing enforcement protections still apply." : " The location changes only if the GPS update option is selected."}
        </p>

        <div style={s.modalFooter}>
          <button className="ghost-btn" onClick={onClose} disabled={loading}>Cancel</button>
          <button className="primary-btn" onClick={handleVerify} disabled={loading}>
            {loading ? "Verifying…" : <><Icon.Check /> Confirm &amp; verify</>}
          </button>
        </div>
    </InspectionDialog>
  );
}

// ── Detail Modal ───────────────────────────────────────────────────────────────
function InspectionDetailModal({ report, token, isAdmin, role, onWarningCleared, onAssign, onVerify, onClose, isClosing, returnFocusRef, fallbackFocusRef }) {
  const [enlargedImage, setEnlargedImage] = useState(null);
  const [clearingWarning, setClearingWarning] = useState(false);
  const [clearError, setClearError] = useState("");
  const photoReturnRef = useRef(null);

  const handleClearWarning = async () => {
    try {
      let businessID = report.businessID;
      let registryReview = null;
      if (!businessID) {
        const idPrompt = await Swal.fire({
          title: "Business ID required",
          text: "Enter the official Business ID from the office record before confirming compliance.",
          input: "text",
          inputPlaceholder: "Official Business ID",
          inputValidator: (value) => value?.trim() ? undefined : "Business ID is required.",
          showCancelButton: true,
          confirmButtonText: "Review Business ID",
        });
        if (!idPrompt.isConfirmed) return;
        businessID = idPrompt.value.trim();
        setClearingWarning(true);
        setClearError("");
        registryReview = await previewWarningRegistryLinkRequest(
          report.reportID, businessID, token,
        );
      }

      const establishment = report.detectedName || report.businessName || "this establishment";
      const reviewSummary = registryReview
        ? `${registryReview.registryExists ? "Existing registry record" : "New registry record"}: ${registryReview.registry.businessName || establishment}\nBusiness ID: ${registryReview.businessID}\nThis will link the original pin and set the business to Active / Green.`
        : `Business ID: ${businessID}\nThis will set the permit to Active and clear the warning to Green.`;
      const confirmation = await Swal.fire({
        title: "Confirm compliance?",
        text: reviewSummary,
        input: "text",
        inputLabel: "Office evidence/reference (optional)",
        inputPlaceholder: "Reason or office record reference",
        showCancelButton: true,
        confirmButtonText: "Confirm and mark Green",
      });
      if (!confirmation.isConfirmed) return;

      setClearingWarning(true);
      setClearError("");
      await clearInspectionWarning({
        report,
        role,
        reason: confirmation.value || null,
        token,
        businessID,
        registryReviewToken: registryReview?.reviewToken,
        confirmEstablishment: Boolean(registryReview),
        request: clearWarningRequest,
        refresh: onWarningCleared,
        onChanged: () => window.dispatchEvent(new CustomEvent("revela:registry-update", {
           detail: { localMutation: true, businessID, logID: report.logID },
        })),
      });
    } catch (err) {
      setClearError(err.message || "Could not clear the warning.");
    } finally {
      setClearingWarning(false);
    }
  };
  
  const flagMeta    = FLAG_COLOR[report.flagColor]   ?? FLAG_COLOR.Red;
  const resultMeta  = FLAG_COLOR[report.inspectionResult] ?? null;
  const statusMeta  = STATUS_COLOR[report.verificationStatus] ?? STATUS_COLOR.Assigned;

  return (
    <InspectionDialog
      title="Inspection Details" onClose={onClose} busy={clearingWarning} isClosing={isClosing} panelStyle={{ width: 520 }}
      returnFocusRef={returnFocusRef} fallbackFocusRef={fallbackFocusRef}
    >

        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
            <h2 style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)", margin: 0 }}>{report.detectedName}</h2>
          </div>
          <p style={{ fontSize: 13, color: "var(--color-muted)", display: "flex", alignItems: "center", gap: 5, margin: 0 }}>
            <Icon.MapPin /> {report.barangayName ?? "Unknown barangay"}
          </p>
          {(report.reportID != null || report.logID != null) && (
            <p style={{ fontSize: 11.5, color: "var(--color-muted)", margin: "4px 0 0" }}>
              {[report.reportID != null && `Report #${report.reportID}`, report.logID != null && `Location #${report.logID}`].filter(Boolean).join(" · ")}
            </p>
          )}
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
                <span className="dispatch-history" style={{ marginTop: 6 }}>
                  <Icon.RefreshCw /> Previously reassigned
                </span>
              )}
            </div>
          </div>
          {(report.inspectionResult || report.noticeLevel > 0) && (
            <div style={{ display: "flex" }}>
              {report.inspectionResult && (
                <div style={{ flex: 1, padding: "12px 16px", borderRight: report.noticeLevel > 0 ? "1px solid var(--color-border)" : "none" }}>
                  <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Submitted Result</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 700, color: resultMeta?.text ?? "var(--color-ink)" }}>
                    {formatResult(report.inspectionResult)}
                  </span>
                </div>
              )}
              {report.noticeLevel > 0 && (
                <div style={{ flex: 1, padding: "12px 16px" }}>
                  <span style={{ display: "block", fontSize: 10, color: "var(--color-muted)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Notice Stage</span>
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
                    <span style={{ fontSize: 14, color: "var(--color-ink)", fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}><Icon.Clock size={14} /> {formatElapsedMinutes(report.resolutionTime)}</span>
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

        {(() => {
          const evList = parseInspectionEvidence(report.photoPath);
          if (!evList || evList.length === 0) return null;
          const live = evList.filter(e => !e.isArchived && e.url);
          const arch = evList.filter(e => e.isArchived);
          return (
            <div style={{ marginBottom: 16 }}>
              <h4 style={{ fontSize: 11, fontWeight: 700, color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8, marginTop: 0 }}>
                Evidence Photo{evList.length > 1 ? "s" : ""}
              </h4>
              {live.length > 0 && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "10px", paddingBottom: "8px" }}>
                  {live.map((item, i) => (
                    <button
                      key={i} type="button" className="dispatch-evidence-button"
                      aria-label={`Enlarge inspection evidence ${i + 1}`}
                      onClick={event => { photoReturnRef.current = event.currentTarget; setEnlargedImage(item.url); }}
                    >
                      <AuthenticatedEvidenceImage
                        url={item.url} token={token} alt={`Evidence ${i + 1}`}
                        style={{ width: "100%", height: 120, objectFit: "cover", borderRadius: 8, border: "1px solid var(--color-border)" }}
                      />
                    </button>
                  ))}
                </div>
              )}
              {arch.length > 0 && (
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 14px",
                  background: "var(--color-hover)",
                  borderRadius: 8,
                  border: "1px dashed var(--color-border)",
                  fontSize: 12,
                  color: "var(--color-muted)",
                }}>
                  <span style={{ fontSize: 18 }}>📦</span>
                  <div>
                    <div style={{ fontWeight: 600, color: "var(--color-ink)" }}>
                      Photo evidence archived to Municipal PC backup
                    </div>
                    <div style={{ fontSize: 11, opacity: 0.8, marginTop: 2 }}>
                      File reference: {arch.map(a => a.filename).join(", ")}
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })()}

        {clearError && <div style={s.errorBanner} role="alert">{clearError}</div>}
        {isAdmin && (
          <div style={{ display: "flex", gap: 12, marginTop: 24, flexWrap: "wrap" }}>
            {canReassignInspection(report, { isAdmin }) && (
              <button className="ghost-btn" style={{ fontSize: 14, fontWeight: 600, padding: "12px 16px", flex: 1, border: "1px solid var(--color-border-soft)", background: "transparent", color: "var(--color-ink)" }}
                onClick={(e) => { e.stopPropagation(); onAssign(report); }}>
                Reassign
              </button>
            )}
            {report.verificationStatus === "Submitted" && (
              <>
                <button
                  className="primary-btn"
                  style={{ fontSize: 14, fontWeight: 600, padding: "12px 16px", flex: 1 }}
                  onClick={(e) => { e.stopPropagation(); onVerify(report); }}
                >
                  <Icon.Check size={18} /> Verify
                </button>
              </>
            )}
            {canFollowUpInspection(report, { isAdmin }) && (
              <button
                className="primary-btn"
                style={{ fontSize: 14, fontWeight: 600, padding: "12px 16px", flex: 1, background: "#e65100", borderColor: "#e65100" }}
                onClick={(e) => { e.stopPropagation(); onAssign(report); }}
              >
                <Icon.Send size={18} /> Follow-up
              </button>
            )}
            {canClearInspectionWarning(report, role) && (
              <button className="ghost-btn" disabled={clearingWarning} onClick={handleClearWarning}
                style={{ fontSize: 14, fontWeight: 600, padding: "12px 16px", flex: 1 }}>
                {clearingWarning ? "Clearing…" : "Clear Warning"}
              </button>
            )}
          </div>
        )}

        <AnimatePresence isVisible={!!enlargedImage}>
          <InspectionEvidenceModal
            url={enlargedImage} token={token} onClose={() => setEnlargedImage(null)}
            returnFocusRef={photoReturnRef} fallbackFocusRef={fallbackFocusRef}
          />
        </AnimatePresence>
    </InspectionDialog>
  );
}

function InspectionEvidenceModal({ url, token, onClose, isClosing, returnFocusRef, fallbackFocusRef }) {
  return (
    <InspectionDialog
      title="Inspection evidence" onClose={onClose} isClosing={isClosing} layer={100000}
      className="dispatch-evidence-dialog" returnFocusRef={returnFocusRef} fallbackFocusRef={fallbackFocusRef}
    >
      <AuthenticatedEvidenceImage url={url} token={token} alt="Enlarged inspection evidence" style={{ maxWidth: "100%", maxHeight: "65vh", objectFit: "contain" }} />
    </InspectionDialog>
  );
}

// ── Column Focus Modal (Grid View) ─────────────────────────────────────────────
function ColumnFocusModal({ status, reports, initialSearch = "", onViewDetail, onClose, isClosing, returnFocusRef, fallbackFocusRef }) {
  const [search, setSearch] = useState(initialSearch);
  const [filterFlag, setFilterFlag] = useState("");
  const gridSearchRef = useRef(null);
  const filteredReports = reports.filter(report => (!filterFlag || report.flagColor === filterFlag)
    && matchesGridSearch(report, search, initialSearch));

  return (
    <InspectionDialog
      title={`${status} reports (${filteredReports.length})`}
      description="Only reports already loaded in Dispatch are included. Opening this grid does not fetch more records."
      className="dispatch-grid-dialog" layer={9999} onClose={onClose} isClosing={isClosing}
      returnFocusRef={returnFocusRef} fallbackFocusRef={fallbackFocusRef}
    >
      <div className="dispatch-grid-controls">
        <div className="dispatch-grid-search">
          <label htmlFor="dispatch-grid-search">Search loaded {status.toLowerCase()} reports</label>
          <div className="dispatch-search-input">
            <Icon.Search />
            <input ref={gridSearchRef} id="dispatch-grid-search" type="text" placeholder="Search name, ID, or area..." value={search} onChange={event => setSearch(event.target.value)} />
            {search && <button className="dispatch-clear-search" type="button" aria-label="Clear grid search" title="Clear grid search" onClick={() => { setSearch(""); gridSearchRef.current.focus(); }}><Icon.X /></button>}
          </div>
        </div>
        <p className="dispatch-grid-help">Search starts with the Dispatch query. Edit or clear it here without changing the board. Current-flag filters also apply only here; their counts show the loaded column before search.</p>
        <div className="dispatch-grid-flags" role="group" aria-label="Filter grid by current flag">
            {["all", ...Object.keys(FLAG_COLOR)].map(c => {
              const count = c === "all" ? reports.length : reports.filter(r => r.flagColor === c).length;
              if (count === 0 && c !== "all") return null;
              
              const isActive = filterFlag === c || (filterFlag === "" && c === "all");
              
              return (
                <button
                  key={c}
                  type="button"
                  aria-pressed={isActive}
                  aria-label={`Current flag ${c === "all" ? "All" : c}, ${count} loaded reports`}
                  title={c === "all" ? "All current flags" : `Current flag: ${c}`}
                  onClick={() => setFilterFlag(c === "all" ? "" : c)}
                >
                  {c === "all" ? "All" : (getFriendlyFlagLabel(c) ?? c)} ({count})
                </button>
              );
            })}
          </div>
        </div>

        <p className="dispatch-grid-count" role="status">Showing {filteredReports.length} of {reports.length} {status.toLowerCase()} reports.</p>
        <div className="dispatch-grid-content">
          <div className="dispatch-grid-cards">
            {filteredReports.map(report => <InspectionCard key={report.reportID ?? `log-${report.logID}`} report={report} onViewDetail={onViewDetail} />)}
          </div>
          {filteredReports.length === 0 && (
            <div className="dispatch-empty"><strong>No matching reports</strong>Change or clear the grid search and current-flag filter.</div>
          )}
        </div>
    </InspectionDialog>
  );
}

// ── Inspection Card ────────────────────────────────────────────────────────────
function InspectionCard({ report, onViewDetail }) {
  const name = report.detectedName || "Unknown establishment";
  const deadline = inspectionDeadline(report.deadline);

  return (
    <button
      className="dispatch-card" type="button" data-report-id={report.reportID}
      onClick={event => onViewDetail(report, event.currentTarget)}
    >
      <span className="dispatch-card-name">{name}</span>
      <span className="dispatch-card-location">
        <Icon.MapPin />{report.barangayName || "Barangay unavailable"}
      </span>
      <span className="dispatch-card-footer">
        <span className="dispatch-card-deadline">
          <Icon.Clock />
          {deadline.dateTime ? <>Due <time dateTime={deadline.dateTime}>{deadline.label}</time></> : "No deadline"}
        </span>
        <span className="dispatch-card-action">View details <span aria-hidden="true">→</span></span>
      </span>
    </button>
  );
}

// ── Column ─────────────────────────────────────────────────────────────────────
function KanbanColumn({ status, reports, onViewDetail, isCollapsed, onToggleCollapse, onFocusColumn, isFiltered }) {
  const statusMeta = STATUS_COLOR[status] ?? STATUS_COLOR.Assigned;
  const { visibleReports, hasMore } = inspectionColumnPreview(reports);
  const bodyID = `dispatch-column-${status.toLowerCase()}-reports`;

  return (
    <section
      className={`dispatch-column${isCollapsed ? " is-collapsed" : ""}`}
      aria-labelledby={`${bodyID}-title`} data-status={status}
      style={{ "--dispatch-status-bg": statusMeta.bg, "--dispatch-status-text": statusMeta.text }}
    >
      <h2 className="dispatch-column-heading">
        <button
          className="dispatch-column-toggle" type="button" onClick={onToggleCollapse}
          aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${status} column`}
          aria-expanded={!isCollapsed} aria-controls={bodyID}
          aria-describedby={`${bodyID}-count`}
          title={`${isCollapsed ? "Expand" : "Collapse"} ${status} column`}
        >
          <span className="dispatch-column-dot" aria-hidden="true" />
          <span className="dispatch-column-title" id={`${bodyID}-title`}>{status}</span>
          <span className="dispatch-column-count" id={`${bodyID}-count`} aria-label={`${reports.length} matching reports`}>{reports.length}</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d={isCollapsed ? "M9 18l6-6-6-6" : "M15 18l-6-6 6-6"} /></svg>
        </button>
      </h2>
      <div className="dispatch-column-body" id={bodyID} hidden={isCollapsed}>
        {!isCollapsed && (reports.length ? (
          <>
            {visibleReports.map(report => <InspectionCard key={report.reportID ?? `log-${report.logID}`} report={report} onViewDetail={onViewDetail} />)}
            {hasMore && <button className="dispatch-view-all" type="button" onClick={event => onFocusColumn(status, event.currentTarget)}>View all {reports.length} {status.toLowerCase()} reports</button>}
          </>
        ) : (
          <div className="dispatch-empty"><strong>{isFiltered ? "No matching reports" : `No ${status.toLowerCase()} reports`}</strong></div>
        ))}
      </div>
    </section>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function InspectionPage() {
  const { token, user } = useContext(AuthContext);
  const [searchParams, setSearchParams] = useSearchParams();
  const view = ["open", "overdue", "awaiting_verification", "oldest", "resolution", "age_0-3", "age_4-7", "age_8-14", "age_15+", "age_unavailable", "deadline_missing", "deadline_day"].includes(searchParams.get("view")) ? searchParams.get("view") : "all";
  const page = Math.max(1, Number.parseInt(searchParams.get("page"), 10) || 1);
  const reportID = /^\d+$/.test(searchParams.get("reportID") || "") ? searchParams.get("reportID") : null;
  const deadlineDate = searchParams.get("deadlineDate");
  const changeParams = (changes) => setSearchParams(previous => {
    const next = new URLSearchParams(previous);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") next.delete(key); else next.set(key, String(value));
    }
    return next;
  });
  const isAdmin = ["Admin", "SUPER_ADMIN", "System Administrator"].includes(user?.role);

  const [error,     setError]     = useState("");

  // Kanban View Optimization State
  const [collapsedCols, setCollapsedCols] = useState(new Set());
  const [focusColumn, setFocusColumn] = useState(null);
  const gridVersionRef = useRef(0);
  const gridReturnRef = useRef(null);
  const detailReturnRef = useRef(null);
  const actionReturnRef = useRef(null);
  const searchRef = useRef(null);

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
  const filterStatus = searchParams.get("status") || "";
  const [search, setSearch] = useState(() => searchParams.get("search") || "");
  useEffect(() => { setSearch(searchParams.get("search") || ""); }, [searchParams]);
  const requestKey = `inspections:${isAdmin ? `${view}:${page}:${reportID || ""}:${deadlineDate || ""}:${filterStatus}` : "tasks"}`;
  const [reportData, setReportData, hasReports] = useSessionDataset(requestKey, "reports", null);
  const reports = reportData?.data ?? [];
  const total = reportData?.total ?? 0;
  const [loading, setLoading] = useState(() => !hasReports);
  const currentRequestKey = useRef(requestKey);
  const reportRequestSequence = useRef(0);
  useEffect(() => { currentRequestKey.current = requestKey; }, [requestKey]);

  // ── Fetch ────────────────────────────────────────────────────────────────────
  const fetchReports = useCallback(async (isSilent = false) => {
    if (!token) return;
    const key = requestKey;
    const sequence = ++reportRequestSequence.current;
    if (!isSilent) {
      setLoading(!hasReports);
    }
    setError("");
    try {
      let result;
      if (isAdmin) {
        result = await getInspectionWorkloadRequest(
          { status: filterStatus || undefined, view, page, reportID, deadlineDate, limit: WORKLOAD_PAGE_SIZE },
          token
        );
        if (currentRequestKey.current !== key || sequence !== reportRequestSequence.current) return false;
      } else {
        result = await getInspectorTasksRequest(token);
        if (currentRequestKey.current !== key || sequence !== reportRequestSequence.current) return false;
      }
      setReportData({ data: result.data ?? [], total: result.total ?? 0, total_rows: result.total_rows ?? result.total ?? 0,
        as_of: result.as_of, period_from: result.period_from });
      setDetailTarget(current => current
        ? (result.data ?? []).find(row => row.reportID === current.reportID) ?? current
        : null);
      return true;
    } catch (err) {
      if (!isSilent && currentRequestKey.current === key && sequence === reportRequestSequence.current) {
        setError(err.message || "Failed to load inspections.");
      }
      return false;
    } finally {
      if (currentRequestKey.current === key && sequence === reportRequestSequence.current) setLoading(false);
    }
  }, [token, isAdmin, filterStatus, requestKey, hasReports, setReportData, view, page, reportID, deadlineDate]);
  useAppDataRefresh(requestKey, async reason => {
    const ok = await fetchReports(reason === "scheduled");
    return { ok, status: ok ? "success" : "failure" };
  });

  // ── Derived ──────────────────────────────────────────────────────────────────
  const filteredReports = reports.filter(report => matchesDispatchSearch(report, search));
  const workloadPages = Math.max(1, Math.ceil(total / WORKLOAD_PAGE_SIZE));
  const hasWorkloadFilter = view !== "all" || Boolean(reportID);
  const hasActiveFilter = hasWorkloadFilter || Boolean(filterStatus);
  const workloadFilterName = view === "all" && reportID
    ? "Selected inspection report"
    : workloadFilterLabel(view, deadlineDate);
  const workloadResult = workloadResultLabel(total, page, WORKLOAD_PAGE_SIZE);
  const updatedLabel = dashboardUpdatedLabel(reportData?.as_of);
  const periodLabel = view === "resolution"
    ? inspectionPeriodLabel(reportData?.period_from, reportData?.as_of)
    : null;

  const byStatus = (status) => {
    return filteredReports.filter((r) => r.verificationStatus === status);
  };

  // Admin sees all 4 columns; inspectors only see Assigned + Reassigned
  const visibleCols = isAdmin
    ? (filterStatus === "In Progress" || reports.some(row => row.verificationStatus === "In Progress")
      ? [...STATUS_COLS, "In Progress"] : STATUS_COLS)
    : ["Assigned", "Reassigned"];

  const openDetail = (report, trigger) => {
    detailReturnRef.current = trigger || document.activeElement;
    setDetailTarget(report);
  };
  const openGrid = (status, trigger) => {
    gridReturnRef.current = trigger;
    gridVersionRef.current += 1;
    setFocusColumn({ status, initialSearch: search, key: gridVersionRef.current });
  };

  return (
    <DashboardLayout
      className="inspection-dispatch-page"
      user={{ initials: user?.fullName?.charAt(0) ?? "?", name: user?.fullName ?? "" }}
    >

      {/* Page header */}
      <div className="dispatch-header">
        <div>
          <h1 className="page-title">Inspection Dispatch</h1>
          <p className="page-subtitle">
            {isAdmin
              ? "Assign, track, and verify field inspections across Mataasnakahoy."
              : "Your active inspection assignments."}
          </p>
        </div>
        <div className="dispatch-header-actions">
          <Link className="toolbar-nav-btn" to="/inspections/calendar"><Icon.Calendar />Calendar View</Link>
        </div>
      </div>

      <div className="dispatch-toolbar">
        <div className="dispatch-search-field">
          <div className="dispatch-search-label">
            <label htmlFor="dispatch-search">Search inspections</label>
            {search.trim() && (
              <span className="dispatch-search-count" role="status">
                {filteredReports.length} {filteredReports.length === 1 ? "match" : "matches"} on this page
              </span>
            )}
          </div>
          <div className="dispatch-search-input">
            <Icon.Search />
            <input ref={searchRef} id="dispatch-search" type="text" placeholder="Search name, ID, or area..." value={search} onChange={event => { setSearch(event.target.value); changeParams({ search: event.target.value }); }} />
            {search && <button className="dispatch-clear-search" type="button" aria-label="Clear Dispatch search" title="Clear search" onClick={() => { setSearch(""); changeParams({ search: null }); searchRef.current.focus(); }}><Icon.X /></button>}
          </div>
        </div>
      </div>

      {isAdmin && (
        <section className="dispatch-workload-context" aria-label="Inspection filter context">
          <span className="dispatch-workload-context-icon" aria-hidden="true"><Icon.Dashboard /></span>
          <div className="dispatch-workload-context-copy">
            <span className="dispatch-workload-context-eyebrow">{hasWorkloadFilter ? "From dashboard" : "Inspection results"}</span>
            <div className="dispatch-workload-context-title">
              <strong>{workloadFilterName}</strong>
              {filterStatus && <span className="dispatch-workload-chip">{filterStatus}</span>}
              {reportID && <span className="dispatch-workload-chip" title={`Selected report ID ${reportID}`}>Selected report #{reportID}</span>}
            </div>
            {(periodLabel || updatedLabel) && (
              <span className="dispatch-workload-meta">
                {periodLabel && <span>Resolution average for {periodLabel}</span>}
                {periodLabel && updatedLabel && <span aria-hidden="true"> · </span>}
                {updatedLabel && <time dateTime={reportData?.as_of}>{updatedLabel}</time>}
              </span>
            )}
          </div>
          <div className="dispatch-workload-context-actions">
            {loading && !hasReports
              ? <span className="ui-skeleton dispatch-workload-count-skeleton" aria-hidden="true" />
              : <span className="dispatch-workload-count">{workloadResult}</span>}
            {workloadPages > 1 && (
              <nav className="dispatch-workload-pager" aria-label="Inspection results pagination">
                <button type="button" disabled={page <= 1} onClick={() => changeParams({ page: page - 1 })}>Previous</button>
                <button type="button" disabled={page >= workloadPages} onClick={() => changeParams({ page: page + 1 })}>Next</button>
              </nav>
            )}
            {hasActiveFilter && (
              <button className="dispatch-workload-clear" type="button" onClick={() => changeParams({ view: null, reportID: null, deadlineDate: null, status: null, page: null })}>Clear filter</button>
            )}
          </div>
        </section>
      )}
      {isAdmin && reportID && !loading && hasReports && total === 0 && <p role="status">This report no longer matches the current filter. Results were recalculated when this page opened.</p>}

      {error && (
        <div style={s.errorBanner} role="alert">
          <Icon.AlertCircle /> &nbsp;{error}
        </div>
      )}

      {loading && !hasReports ? (
        <SkeletonKanbanBoard columns={visibleCols.length} />
      ) : (
        <div>
          <p className="dispatch-board-help" id="dispatch-board-help">Columns show up to five reports; use View all for the rest.</p>
          <div className="dispatch-board-scroll" role="region" aria-label="Inspection status columns" aria-describedby="dispatch-board-help" tabIndex={0}>
          <div
            className="dispatch-board"
            style={{
              gridTemplateColumns: visibleCols
                .map((status) => (collapsedCols.has(status) ? "60px" : "minmax(250px, 1fr)"))
                .join(" "),
              minWidth: visibleCols.reduce(
                (acc, status) => acc + (collapsedCols.has(status) ? 60 : 250),
                (visibleCols.length - 1) * 16
              ),
            }}
          >
            {visibleCols.map((status) => (
              <KanbanColumn
                key={status}
                status={status}
                reports={byStatus(status)}
                onViewDetail={openDetail}
                isFiltered={Boolean(search.trim() || filterStatus)}
                isCollapsed={collapsedCols.has(status)}
                onToggleCollapse={() => toggleCollapse(status)}
                onFocusColumn={openGrid}
              />
            ))}
          </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <Footer />

      {/* Assign Modal */}
      <AnimatePresence isVisible={!!assignTarget}>
        <AssignModal
          report={assignTarget}
          token={token}
          onClose={() => setAssignTarget(null)}
          onSuccess={() => { window.dispatchEvent(new CustomEvent("revela:inspection-update", { detail: { localMutation: true } })); return fetchReports(); }}
          returnFocusRef={actionReturnRef} fallbackFocusRef={searchRef}
        />
      </AnimatePresence>

      {/* Verify Modal */}
      <AnimatePresence isVisible={!!verifyTarget}>
        <VerifyModal
          report={verifyTarget}
          token={token}
          onClose={() => setVerifyTarget(null)}
          onSuccess={() => { window.dispatchEvent(new CustomEvent("revela:inspection-update", { detail: { localMutation: true } })); return fetchReports(); }}
          returnFocusRef={actionReturnRef} fallbackFocusRef={searchRef}
        />
      </AnimatePresence>

      {/* Detail Modal */}
      <AnimatePresence isVisible={!!detailTarget}>
        <InspectionDetailModal
          report={detailTarget}
          token={token}
          isAdmin={isAdmin}
          role={user?.role}
          onWarningCleared={() => fetchReports(true)}
          onAssign={(r) => { actionReturnRef.current = detailReturnRef.current; setDetailTarget(null); setAssignTarget(r); }}
          onVerify={(r) => { actionReturnRef.current = detailReturnRef.current; setDetailTarget(null); setVerifyTarget(r); }}
          onClose={() => setDetailTarget(null)}
          returnFocusRef={detailReturnRef} fallbackFocusRef={searchRef}
        />
      </AnimatePresence>

      {/* Grid View Modal */}
      <AnimatePresence isVisible={!!focusColumn}>
        <ColumnFocusModal
          key={focusColumn?.key}
          status={focusColumn?.status}
          reports={reports.filter(r => r.verificationStatus === focusColumn?.status)}
          initialSearch={focusColumn?.initialSearch || ""}
          onViewDetail={openDetail}
          onClose={() => setFocusColumn(null)}
          returnFocusRef={gridReturnRef} fallbackFocusRef={searchRef}
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
    padding: 32, width: 440, maxWidth: "calc(100vw - 32px)", boxSizing: "border-box",
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
