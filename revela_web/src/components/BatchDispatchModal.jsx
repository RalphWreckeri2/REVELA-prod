import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Swal from "sweetalert2";
import { canDispatchFlag, normalizeDispatchColor } from "./dispatchEligibility";
import {
  API_ORIGIN,
  assignInspectionBatchRequest,
  getAllFlagsRequest,
} from "../services/api";
import { hasMapCoordinates } from "./mapLocationMetrics.js";

const FLAG_COLORS = {
  Red: { bg: "#fee2e2", text: "#b91c1c" },
  Yellow: { bg: "#fef9c3", text: "#a16207" },
  Orange: { bg: "#ffedd5", text: "#c2410c" },
  Purple: { bg: "#f3e8ff", text: "#7e22ce" },
};

function normalizeBatchFlag(flag) {
  return {
    id: Number(flag.logID ?? flag.id),
    name: flag.detectedName || "Unknown Establishment",
    barangayID: flag.barangayID,
    color: normalizeDispatchColor(flag.flagColor),
    verificationStatus: flag.verificationStatus,
    hasExactCoords: hasMapCoordinates(flag),
    hasActiveInspection: flag.verificationStatus != null &&
      flag.verificationStatus !== "Verified",
  };
}

export default function BatchDispatchModal({ barangays, token, onClose, onSuccess }) {
  const [allFlags, setAllFlags] = useState([]);
  const [inspectors, setInspectors] = useState([]);
  const [selectedBarangayID, setSelectedBarangayID] = useState("");
  const [selectedUID, setSelectedUID] = useState("");
  const [selectedLogIDs, setSelectedLogIDs] = useState([]);
  const [deadline, setDeadline] = useState("");
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isCurrent = true;
    Promise.all([
      getAllFlagsRequest(token),
      fetch(`${API_ORIGIN}/api/users/?role=Inspector`, {
        headers: { Authorization: `Bearer ${token}` },
      }).then(async response => {
        if (!response.ok) throw new Error("Could not load inspectors.");
        return response.json();
      }),
    ])
      .then(([rawFlags, inspectorData]) => {
        if (!isCurrent) return;
        const list = Array.isArray(inspectorData)
          ? inspectorData
          : (inspectorData.data ?? inspectorData.users ?? []);
        setAllFlags(rawFlags.map(normalizeBatchFlag));
        setInspectors(list.filter(inspector => (
          inspector.userRole === "Inspector" &&
          inspector.isActive !== 0 &&
          inspector.isActive !== false
        )));
      })
      .catch(err => {
        if (isCurrent) setError(err.message || "Could not load dispatch data.");
      })
      .finally(() => {
        if (isCurrent) setFetching(false);
      });
    return () => { isCurrent = false; };
  }, [token]);

  const eligibleFlags = useMemo(() => allFlags.filter(flag => (
    flag.id > 0 &&
    String(flag.barangayID) === String(selectedBarangayID) &&
    !flag.hasActiveInspection &&
    canDispatchFlag(flag, { isAdmin: true })
  )), [allFlags, selectedBarangayID]);
  const noExactLocationCount = selectedBarangayID
    ? allFlags.filter(flag => (
      String(flag.barangayID) === String(selectedBarangayID) &&
      !flag.hasExactCoords
    )).length
    : 0;

  const allSelected = eligibleFlags.length > 0 &&
    eligibleFlags.every(flag => selectedLogIDs.includes(flag.id));

  const toggleAll = () => {
    setSelectedLogIDs(allSelected ? [] : eligibleFlags.map(flag => flag.id));
  };

  const toggleFlag = logID => {
    setSelectedLogIDs(current => current.includes(logID)
      ? current.filter(id => id !== logID)
      : [...current, logID]);
  };

  const handleDispatch = async () => {
    if (!selectedBarangayID || !selectedUID || selectedLogIDs.length === 0) {
      setError("Choose a barangay, an inspector, and at least one business.");
      return;
    }
    if (deadline && new Date(deadline) < new Date()) {
      setError("Choose a deadline in the future.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await assignInspectionBatchRequest({
        barangayID: Number(selectedBarangayID),
        userID: Number(selectedUID),
        logIDs: selectedLogIDs,
        deadline: deadline || null,
      }, token);
      const skippedDetails = (result.skipped || [])
        .slice(0, 5)
        .map(item => `#${item.logID}: ${item.error}`)
        .join("\n");
      await Swal.fire({
        icon: result.skippedCount ? "warning" : "success",
        title: "Batch dispatch complete",
        text: `${result.assignedCount} assigned, ${result.skippedCount} skipped.${skippedDetails ? `\n${skippedDetails}` : ""}`,
        confirmButtonColor: "var(--color-primary)",
      });
      onSuccess();
      onClose();
    } catch (err) {
      setError(err.message || "Batch dispatch failed.");
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = {
    width: "100%",
    padding: "10px 12px",
    marginBottom: 14,
    border: "1px solid var(--color-border)",
    borderRadius: 8,
    background: "var(--color-modal-bg)",
    color: "var(--color-ink)",
    boxSizing: "border-box",
  };

  return createPortal(
    <div className="modal-backdrop" style={{ position: "fixed", inset: 0, zIndex: 10002, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }} onClick={!loading ? onClose : undefined}>
      <div className="modal-panel" style={{ width: "min(720px, calc(100vw - 32px))", maxHeight: "88vh", padding: 24, display: "flex", flexDirection: "column", overflowY: "auto", borderRadius: 12, background: "var(--color-modal-bg)", boxShadow: "0 24px 48px rgba(0,0,0,0.2)" }} onClick={event => event.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, color: "var(--color-ink)" }}>Batch Dispatch by Barangay</h3>
          {!loading && <button className="modal-close-btn" onClick={onClose} aria-label="Close">X</button>}
        </div>

        {error && <p role="alert" style={{ color: "var(--color-danger)", fontSize: 13, margin: "0 0 12px" }}>{error}</p>}

        <label style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>Barangay</label>
        <select value={selectedBarangayID} onChange={event => { setSelectedBarangayID(event.target.value); setSelectedLogIDs([]); }} disabled={fetching || loading} style={inputStyle}>
          <option value="">Choose a barangay...</option>
          {barangays.map(barangay => <option key={barangay.barangayID} value={barangay.barangayID}>{barangay.barangayName}</option>)}
        </select>

        <label style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>Inspector</label>
        <select value={selectedUID} onChange={event => setSelectedUID(event.target.value)} disabled={fetching || loading} style={inputStyle}>
          <option value="">Choose an inspector...</option>
          {inspectors.map(inspector => <option key={inspector.userID} value={inspector.userID}>{inspector.fullName}</option>)}
        </select>

        <label style={{ fontSize: 11, fontWeight: 700, marginBottom: 6 }}>Deadline (Optional)</label>
        <input type="datetime-local" value={deadline} min={new Date(new Date().getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)} onChange={event => setDeadline(event.target.value)} disabled={loading} style={inputStyle} />

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 10px", borderBottom: "1px solid var(--color-border-soft)" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13, fontWeight: 700 }}>
            <input type="checkbox" checked={allSelected} onChange={toggleAll} disabled={fetching || loading || eligibleFlags.length === 0} />
            Select all eligible
          </label>
          <span style={{ fontSize: 12, color: "var(--color-muted)" }}>
            {selectedLogIDs.length} selected | {eligibleFlags.length} eligible
            {noExactLocationCount > 0 && ` | ${noExactLocationCount} excluded: No exact location`}
          </span>
        </div>

        <div style={{ overflowY: "auto", minHeight: 150, maxHeight: "36vh" }}>
          {fetching ? (
            <p style={{ padding: 16, color: "var(--color-muted)", fontSize: 13 }}>Loading businesses...</p>
          ) : !selectedBarangayID ? (
            <p style={{ padding: 16, color: "var(--color-muted)", fontSize: 13 }}>Choose a barangay to see its eligible businesses.</p>
          ) : eligibleFlags.length === 0 ? (
            <p style={{ padding: 16, color: "var(--color-muted)", fontSize: 13 }}>No eligible businesses available in this barangay.</p>
          ) : eligibleFlags.map(flag => {
            const color = FLAG_COLORS[flag.color];
            return (
              <label key={flag.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 8px", borderBottom: "1px solid var(--color-border-soft)", cursor: loading ? "default" : "pointer" }}>
                <input type="checkbox" checked={selectedLogIDs.includes(flag.id)} onChange={() => toggleFlag(flag.id)} disabled={loading} />
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span style={{ display: "block", color: "var(--color-ink)", fontSize: 13, fontWeight: 600, overflowWrap: "anywhere" }}>{flag.name}</span>
                  <span style={{ color: "var(--color-muted)", fontSize: 11 }}>Inspection #{flag.id}</span>
                </span>
                <span style={{ color: color.text, background: color.bg, borderRadius: 4, padding: "3px 7px", fontSize: 11, fontWeight: 700, whiteSpace: "nowrap" }}>{flag.color}</span>
              </label>
            );
          })}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--color-border-soft)" }}>
          <button className="ghost-btn" onClick={onClose} disabled={loading}>Cancel</button>
          <button className="primary-btn" onClick={handleDispatch} disabled={loading || fetching || !selectedUID || !selectedBarangayID || selectedLogIDs.length === 0}>
            {loading ? "Dispatching..." : `Dispatch ${selectedLogIDs.length} selected`}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}