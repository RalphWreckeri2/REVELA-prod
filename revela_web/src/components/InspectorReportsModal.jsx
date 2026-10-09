import { useState } from 'react';
import ReactDOM from 'react-dom';
import AnimatePresence from './AnimatePresence';

const FLAG_COLORS = {
  Red: { marker: "#ef4444", bg: "var(--flag-red-bg)", text: "var(--flag-red-text)", label: "Detected Unregistered" },
  Yellow: { marker: "#f59e0b", bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)", label: "Suspected Unregistered" },
  Yellow_Inspector: { marker: "#f59e0b", bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)", label: "Inspector Reported" },
  Orange: { marker: "#e65100", bg: "var(--flag-orange-bg)", text: "var(--flag-orange-text)", label: "Warning / Notice" },
  Black: { marker: "#000000", bg: "var(--flag-black-bg)", text: "var(--flag-black-text)", label: "Blacklisted / Non-Responsive" },
  Purple: { marker: "#7c3aed", bg: "var(--flag-purple-bg)", text: "var(--flag-purple-text)", label: "Closed / Abandoned" },
  Green: { marker: "#22c55e", bg: "var(--flag-green-bg)", text: "var(--flag-green-text)", label: "Active Business" },
};

function parseColor(flag) {
  if (flag.color) return flag.color;
  if (flag.flagColor) return flag.flagColor;
  return "Unknown";
}

function getFlagColor(colorName) {
  return FLAG_COLORS[colorName] || { bg: "var(--color-hover)", text: "var(--color-ink)", label: "Unknown", marker: "gray" };
}

function shortBarangay(b) {
  if (!b) return "";
  return b.replace(/Barangay\s+/i, "Brgy. ");
}

export default function InspectorReportsModal(props) {
  return (
    <AnimatePresence isVisible={props.isOpen}>
      <InspectorReportsModalInner {...props} />
    </AnimatePresence>
  );
}

function InspectorReportsModalInner({ isOpen, onClose, flags, navigate, isClosing }) {
  const [searchTerm, setSearchTerm] = useState("");
  const [filterColor, setFilterColor] = useState("all");
  const [sortBy, setSortBy] = useState("recent");

  if (!isOpen && !isClosing) return null;

  const q = searchTerm.trim().toLowerCase();
  const cleanQ = q.startsWith("#") ? q.slice(1).trim() : q;

  const filteredFlags = flags.filter(f => {
    const matchColor = filterColor === "all"
      ? true
      : filterColor === "Yellow_Inspector"
        ? parseColor(f) === "Yellow" && f.reportedByUserID
        : parseColor(f) === filterColor;
    
    const matchSearch = !q || (
      (f.detectedName || f.name || "").toLowerCase().includes(q) ||
      (f.barangayName || f.barangay || "").toLowerCase().includes(q) ||
      (f.address || f.resolvedAddress || f.nearestLandmark || "").toLowerCase().includes(q) ||
      (f.notes || "").toLowerCase().includes(q) ||
      (f.businessType || "").toLowerCase().includes(q) ||
      (f.businessSize || "").toLowerCase().includes(q) ||
      (f.inspectorName || f.reportedByName || "").toLowerCase().includes(q) ||
      String(f.logID || f.id || "").toLowerCase().includes(cleanQ)
    );
      
    return matchColor && matchSearch;
  });

  const sortedFlags = [...filteredFlags].sort((a, b) => {
    if (sortBy === "name") {
      const nameA = (a.detectedName || a.name || "").toLowerCase();
      const nameB = (b.detectedName || b.name || "").toLowerCase();
      return nameA.localeCompare(nameB);
    } else if (sortBy === "barangay") {
      const brgyA = (a.barangayName || a.barangay || "").toLowerCase();
      const brgyB = (b.barangayName || b.barangay || "").toLowerCase();
      return brgyA.localeCompare(brgyB);
    } else {
      const idA = a.logID || a.id || 0;
      const idB = b.logID || b.id || 0;
      return idA < idB ? 1 : -1;
    }
  });

  return ReactDOM.createPortal(
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className={"modal-panel modal-content saas-card" + (isClosing ? " closing" : "")} onClick={e => e.stopPropagation()} style={{ width: 1040, maxWidth: "95vw", height: "85vh", display: "flex", flexDirection: "column", padding: 32, borderRadius: 24, background: "var(--color-modal-bg)", boxShadow: "0 24px 48px rgba(0,0,0,0.2)" }}>
        
        {/* Header */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 24 }}>
          {/* Top Row: Title + Search/Close */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: "var(--color-ink)", display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ width: 12, height: 12, borderRadius: "50%", background: filterColor === "Yellow_Inspector" ? "#10b981" : (FLAG_COLORS[filterColor]?.marker || "#10b981"), display: "inline-block" }}></span>
              {filterColor === "Yellow_Inspector" ? "Submitted Backlog" : filterColor === "all" ? "All Flags" : FLAG_COLORS[filterColor]?.label || "Flags"} <span style={{ color: "var(--color-muted)", fontSize: 16, fontWeight: 600 }}>({filteredFlags.length})</span>
            </h2>
            
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <div style={{ position: "relative" }}>
                <svg style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--color-muted)", pointerEvents: "none" }} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                <input 
                  type="text" 
                  placeholder="Search name, ID, barangay, address..." 
                  className="saas-input" 
                  style={{ padding: "8px 30px 8px 36px", width: 260, borderRadius: 8, background: "transparent" }}
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

              <select
                style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid var(--color-border-soft)", background: "var(--color-surface)", color: "var(--color-ink)", fontSize: 13, outline: "none", cursor: "pointer", height: "36px" }}
                value={sortBy}
                onChange={e => setSortBy(e.target.value)}
              >
                <option value="recent">Most Recent</option>
                <option value="name">By Name</option>
                <option value="barangay">By Barangay</option>
              </select>
              
              <button className="modal-close-btn" onClick={onClose}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
            </div>
          </div>
          
          {/* Color filter pills */}
          <div style={{ display: "flex", gap: 6, flexWrap: "nowrap", overflowX: "auto", paddingBottom: 4, maxWidth: "100%" }}>
            {["all", "Green", "Yellow", "Yellow_Inspector", "Orange", "Red", "Black", "Purple"].map(c => {
              const isSelected = filterColor === c;
              return (
                <button
                  key={c}
                  onClick={() => setFilterColor(c)}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 20,
                    fontSize: 11,
                    fontWeight: 700,
                    cursor: "pointer",
                    border: "1px solid",
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                    background: isSelected ? (c === "all" ? "var(--color-primary)" : FLAG_COLORS[c]?.marker ?? "var(--color-primary)") : "var(--color-input-bg)",
                    color: isSelected ? "#ffffff" : "var(--color-ink)",
                    borderColor: isSelected ? "transparent" : "var(--color-border)",
                  }}
                >
                  {c === "all" ? "All" : (FLAG_COLORS[c]?.label ?? c)}
                </button>
              );
            })}
          </div>
        </div>

        {/* Grid Content */}
        <div style={{ flex: 1, overflowY: "auto", paddingRight: 16 }}>
          {sortedFlags.length === 0 ? (
            <div style={{ textAlign: "center", padding: "60px 0", color: "var(--color-muted)", fontSize: 15, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
              <img src="/searching.png" alt="No items found" style={{ height: 100, objectFit: "contain", opacity: 0.9 }} />
              No items found matching your criteria.
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
              {sortedFlags.map(f => {
                const fc = getFlagColor(parseColor(f));
                
                return (
                  <div 
                    key={f.logID || f.id}
                    className="hover-lift"
                    onClick={() => { 
                      if (typeof onClose === "function") onClose();
                      navigate('?flag=' + (f.logID || f.id)); 
                    }}
                    style={{ 
                      background: "var(--color-surface)", 
                      border: "1px solid var(--color-border-soft)", 
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
                        <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: 12, background: fc.bg || "var(--color-hover)", color: fc.text || "var(--color-ink)", display: "flex", alignItems: "center", gap: 6 }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>
                          {fc.label}
                        </span>
                        {parseColor(f) === 'Orange' && Boolean(f.noticeLevel) && f.noticeLevel !== 0 && f.noticeLevel !== "0" && (
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
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
