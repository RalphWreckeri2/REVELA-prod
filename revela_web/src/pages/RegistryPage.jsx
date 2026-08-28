/**
 * RegistryPage.jsx
 * Business Registry — wired to /api/registry with upload, search, filter, pagination.
 */

import { useState, useEffect, useCallback, useContext } from "react";
import DashboardLayout from "../components/DashboardLayout";
import StatusBadge from "../components/StatusBadge";
import { UploadModal } from "../components/UploadModal";
import AnimatePresence from "../components/AnimatePresence";
import { AuthContext } from "../context/AuthContext";
import Papa from "papaparse";
import Swal from "sweetalert2";
import {
  getRegistryRequest,
  getBusinessByIdRequest,
  getBarangaysRequest,
  updateBusinessRequest,
} from "../services/api";

// ── Icons ─────────────────────────────────────────────────────────────────────
const Icon = {
  Upload: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  ),
  Search: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  ),
  Filter: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  ),
  ChevronLeft: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  ),
  ChevronRight: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  ),
  Download: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  ),
  Import: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  ),
  Eye: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
  Database: () => (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  ),
  Check: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  AlertCircle: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  ),
  X: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  ),
  Edit: () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
    </svg>
  ),
};


const STATUS_FILTERS = ["All Status", "Active", "Expired", "Revoked", "Pending", "Closed"];
const PAGE_SIZE_OPTIONS = [5, 10, 20, 50];
const DEFAULT_PAGE_SIZE = 10;

// ── Status helpers ─────────────────────────────────────────────────────────────
function getStatusVariant(status) {
  return { Active: "green", Expired: "gold", Revoked: "black", Pending: "default", Closed: "purple" }[status] ?? "default";
}

function getFlagVariant(flag) {
  if (!flag) return "default";
  const f = String(flag);
  if (f === "Green") return "green";
  if (f === "Yellow") return "gold";
  if (f === "Orange") return "orange";
  if (f === "Black") return "black";
  if (f === "Red") return "red";
  if (f === "Purple") return "purple";
  return "default";
}

function formatCoord(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(6) : String(v);
}

/** Must match table header count (including actions column). */
const REGISTRY_TABLE_COL_COUNT = 11;

// ── Empty State ───────────────────────────────────────────────────────────────
function EmptyState({ hasFilters, onUpload }) {
  if (hasFilters) {
    return (
      <tr>
        <td colSpan={REGISTRY_TABLE_COL_COUNT} style={styles.emptyCell}>
          <div style={styles.emptyContent}>
            <img src="/searching.png" alt="No businesses found" style={{ height: 100, objectFit: "contain", opacity: 0.9, marginBottom: 16 }} />
            <span style={{ color: "var(--color-muted)", fontSize: 13 }}>
              No businesses match your current filters.
            </span>
          </div>
        </td>
      </tr>
    );
  }
  return (
    <tr>
      <td colSpan={REGISTRY_TABLE_COL_COUNT} style={{ ...styles.emptyCell, paddingTop: 64, paddingBottom: 64 }}>
        <div style={styles.emptyContent}>
          <img src="/searching.png" alt="Registry Empty" style={{ height: 120, objectFit: "contain", opacity: 0.9, marginBottom: 20 }} />
          <p style={{ fontWeight: 700, fontSize: 15, color: "var(--color-ink)", marginBottom: 6 }}>
            No businesses in the registry yet
          </p>
          <p style={{ fontSize: 13, color: "var(--color-muted)", marginBottom: 20, maxWidth: 340 }}>
            Upload the official BPLO registry CSV or Excel file to get started.
            The system will geocode each entry automatically.
          </p>
          <button className="primary-btn" onClick={onUpload}>
            <Icon.Upload /> Upload Registry File
          </button>
        </div>
      </td>
    </tr>
  );
}


// ── Business Detail Modal ─────────────────────────────────────────────────────
function BusinessDetailModal({ businessId, onClose, token, isAdmin, onSuccess, isClosing }) {
  const [business, setBusiness] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formData, setFormData] = useState({});

  useEffect(() => {
    async function fetch() {
      try {
        const data = await getBusinessByIdRequest(businessId, token);
        setBusiness(data);
        setFormData({
          businessName: data.businessName,
          ownerName: data.ownerName,
          address: data.address,
          status: data.status,
          contactEmail: data.contactEmail || "",
          contactPhone: data.contactPhone || "",
          businessType: data.businessType || "",
          dateRegistered: data.dateRegistered,
        });
      } catch (err) {
        setError(err.message || "Failed to load details.");
      } finally {
        setLoading(false);
      }
    }
    fetch();
  }, [businessId, token]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateBusinessRequest(business.businessID, formData, token);
      Swal.fire({
        icon: 'success',
        title: 'Updated',
        text: 'Business details saved successfully.',
        confirmButtonColor: '#56ab2f'
      });
      setIsEditing(false);
      const data = await getBusinessByIdRequest(businessId, token);
      setBusiness(data);
      if (onSuccess) onSuccess();
    } catch (err) {
      Swal.fire({ icon: 'error', title: 'Error', text: err.message || 'Failed to update.' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    const result = await Swal.fire({
      title: 'Are you sure?',
      text: "This business will be permanently removed from the registry.",
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtoncolor: "var(--color-muted)",
      confirmButtonText: 'Yes, delete it'
    });

    if (result.isConfirmed) {
      setSaving(true);
      setError("");
      try {
        const baseUrl = (import.meta.env && import.meta.env.VITE_API_ORIGIN) ? `${import.meta.env.VITE_API_ORIGIN}/api` : "http://localhost:5000/api";
        const res = await fetch(`${baseUrl}/registry/${businessId}`, {
          method: 'DELETE',
          headers: { "Authorization": `Bearer ${token}` }
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.error || "Failed to delete business");
        }
        Swal.fire({ icon: 'success', title: 'Deleted', text: 'Business deleted successfully.', timer: 1500, showConfirmButton: false });
        if (onSuccess) onSuccess();
        onClose();
      } catch (err) {
        setError(err.message || "Failed to delete business.");
        setSaving(false);
      }
    }
  };

  return (
    <div className={"modal-backdrop" + (isClosing ? " closing" : "")} style={styles.modalBackdrop} onClick={onClose}>
      <div className={"modal-panel" + (isClosing ? " closing" : "")} style={{ ...styles.modalCard, width: 560 }} onClick={e => e.stopPropagation()}>
        <div style={styles.modalHeader}>
          <h3 style={styles.modalTitle}>Business Details</h3>
          <button style={styles.closeBtn} onClick={onClose}><Icon.X /></button>
        </div>

        {loading && <p style={{ color: "var(--color-muted)", fontSize: 13 }}>Loading…</p>}
        {error && <p style={{ color: "var(--color-danger)", fontSize: 13 }}>{error}</p>}

        {business && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[
              ["Business Name", business.businessName, "title", "businessName"],
              ["Business Type", business.businessType || "—", "plain", "businessType"],
              ["Line of Business", business.lineOfBusiness || "—", "plain", "lineOfBusiness"],
              ["Business size", business.businessSize || "—", "plain", "businessSize"],
              ["Address", business.businessAddress || "—", "plain", "businessAddress"],
              ["Barangay", business.barangayName || "—", "readonly"],
              ["Latitude", formatCoord(business.latitude), "readonly"],
              ["Longitude", formatCoord(business.longitude), "readonly"],
              ["Permit status", business.applicationStatus, "permit", "applicationStatus"],
              ["Last renewal", business.lastRenewalDate ? business.lastRenewalDate.slice(0, 10) : "—", "readonly"],
              ["Latest geospatial flag", business.flagColor || "—", "flag"],
            ].map(([label, value, kind, field]) => (
              <div key={label} style={{ display: "flex", gap: 12, alignItems: isEditing && field ? "center" : "flex-start", minHeight: isEditing && field ? 36 : "auto" }}>
                <span style={{ minWidth: 150, fontSize: 12, color: "var(--color-muted)", fontWeight: 500, paddingTop: isEditing && field ? 0 : 3 }}>
                  {label}
                  {isEditing && field === "businessName" && <span style={{ color: "var(--color-danger)" }}> *</span>}
                </span>

                {isEditing && field ? (
                  field === "applicationStatus" ? (
                    <select
                      value={formData[field]}
                      onChange={(e) => setFormData({ ...formData, [field]: e.target.value })}
                      style={styles.editInput}
                    >
                      <option value="Pending">Pending</option>
                      <option value="Active">Active</option>
                      <option value="Expired">Expired</option>
                      <option value="Revoked">Revoked</option>
                      <option value="Closed">Closed</option>
                    </select>
                  ) : field === "businessSize" ? (
                    <select
                      value={formData[field]}
                      onChange={(e) => setFormData({ ...formData, [field]: e.target.value })}
                      style={styles.editInput}
                    >
                      <option value="">Select size...</option>
                      <option value="Micro">Micro</option>
                      <option value="Small">Small</option>
                      <option value="Medium">Medium</option>
                      <option value="Large">Large</option>
                    </select>
                  ) : (
                    <input
                      value={formData[field]}
                      onChange={(e) => setFormData({ ...formData, [field]: e.target.value })}
                      style={styles.editInput}
                      placeholder={`Enter ${label.toLowerCase()}`}
                    />
                  )
                ) : (
                  <span style={{
                    fontSize: 13,
                    color: "var(--color-ink)",
                    fontWeight: kind === "title" ? 600 : 400,
                    wordBreak: kind === "plain" && String(value).length > 48 ? "break-word" : undefined,
                  }}
                  >
                    {kind === "permit"
                      ? <StatusBadge variant={getStatusVariant(value)}>{value}</StatusBadge>
                      : kind === "flag" && value !== "—"
                        ? <StatusBadge variant={getFlagVariant(value)}>{value}</StatusBadge>
                        : value}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        <div style={{ ...styles.modalFooter, marginTop: 24 }}>
          {isEditing ? (
            <>
              <button className="ghost-btn" onClick={() => {
                setIsEditing(false);
                setFormData({
                  businessName: business.businessName || "",
                  businessType: business.businessType || "",
                  lineOfBusiness: business.lineOfBusiness || "",
                  businessSize: business.businessSize || "",
                  businessAddress: business.businessAddress || "",
                  applicationStatus: business.applicationStatus || "Pending",
                });
                setError("");
              }} disabled={saving}>Cancel</button>
              <button className="primary-btn" onClick={handleSave} disabled={saving}>
                {saving ? "Saving..." : "Save Changes"}
              </button>
            </>
          ) : (
            <>
              {isAdmin && (
                <button className="ghost-btn" style={{ color: "var(--color-danger)", marginRight: "auto" }} onClick={handleDelete} disabled={saving}>
                  Delete
                </button>
              )}
              <button className="ghost-btn" onClick={onClose}>Close</button>
              {isAdmin && (
                <button className="primary-btn" onClick={() => setIsEditing(true)}>
                  <Icon.Edit /> Edit Details
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function RegistryPage() {
  const { token, user } = useContext(AuthContext);
  const isAdmin = user?.role === "Admin" || user?.role === "SUPER_ADMIN";

  const [businesses, setBusinesses] = useState([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [barangay, setBarangay] = useState("All Barangays");
  const [status, setStatus] = useState("All Status");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const [showUpload, setShowUpload] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [detailId, setDetailId] = useState(null);

  // Dynamic barangay list loaded from API
  const [barangays, setBarangays] = useState([]);
  useEffect(() => {
    async function loadBarangays() {
      try {
        const data = await getBarangaysRequest(token);
        // The API may return a bare array or a {data: [...]} wrapper —
        // normalize either shape so `barangays` is always an array and
        // `.map` below never throws.
        const list = Array.isArray(data)
          ? data
          : Array.isArray(data?.data)
            ? data.data
            : [];
        setBarangays(list);
      } catch (err) {
        console.error("Failed to load barangays", err);
        setBarangays([]); // don't leave a stale/bad value in state
      }
    }
    loadBarangays();
  }, [token]);

  // Debounced search — wait 400ms after typing before firing the request
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(t);
  }, [search]);

  // ── Fetch businesses ──────────────────────────────────────────────────────
  const fetchBusinesses = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = { page, limit: pageSize };
      if (debouncedSearch) params.search = debouncedSearch;
      if (barangay !== "All Barangays") params.barangayID = barangay; // sends ID
      if (status !== "All Status") params.status = status;

      const result = await getRegistryRequest(params, token);
      setBusinesses(result.data ?? []);
      setTotal(result.total ?? 0);
      setTotalPages(Math.max(1, result.pages ?? Math.ceil((result.total ?? 0) / pageSize)));
    } catch (err) {
      setError(err.message || "Failed to load registry.");
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch, barangay, status, pageSize, token]);

  // ── Export CSV Handler ───────────────────────────────────────────────────
  const handleExport = async () => {
    setLoading(true);
    try {
      // 1. Fetch data from the existing Python API 
      // We set limit to 10000 to bypass the 10-row page limit
      const result = await getRegistryRequest({
        limit: 10000,
        status: status !== "All Status" ? status : undefined,
        barangayID: barangay !== "All Barangays" ? barangay : undefined,
        search: debouncedSearch
      }, token);

      // 2. Convert the JSON results to CSV
      const csv = Papa.unparse(result.data);

      // 3. Download the file to the browser
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `REVELA_Registry_${new Date().toISOString().slice(0, 10)}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      Swal.fire({
        icon: 'success',
        title: 'Success!',
        text: 'Registry exported to CSV',
        timer: 2000,
        showConfirmButton: false
      });
    } catch (err) {
      console.error("Export failed:", err);
      setError("Export failed. Please try again.");
      Swal.fire({
        icon: 'error',
        title: 'Export Failed',
        text: 'An error occurred while exporting the registry.'
      });
    } finally {
      setLoading(false);
    }
  };

  // ── Import / sync (merge file into existing registry) ───────────────────
  const handleImport = () => {
    if (!token) {
      Swal.fire({ icon: "warning", title: "Sign in required", text: "Please sign in to import the registry." });
      return;
    }
    setShowImport(true);
  };

  // Reset page to 1 whenever filters change (search, barangay, status, pageSize)
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, barangay, status, pageSize]);

  // Fetch whenever page or filters change
  useEffect(() => {
    if (!token) return;
    fetchBusinesses();
  }, [fetchBusinesses, token]);

  // ── Summary counts (derived from the full total, not just current page) ───
  // These come from a dedicated summary endpoint in later sprints.
  // For now we show the total returned.
  const hasFilters = debouncedSearch || barangay !== "All Barangays" || status !== "All Status";

  return (
    <DashboardLayout user={{ initials: user?.fullName?.charAt(0) ?? "?", name: user?.fullName ?? "" }}>

      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Business Registry</h1>
          <p className="page-subtitle">Official BPLO-registered establishments in Mataasnakahoy.</p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            className="ghost-btn"
            onClick={handleImport}
            disabled={loading}
          >
            <Icon.Import /> Import
          </button>
          <button
            className="ghost-btn"
            onClick={handleExport}
            disabled={loading}
          >
            <Icon.Download /> {loading ? "Exporting..." : "Export CSV"}
          </button>
          {user?.role === "Admin" && (
            <button className="primary-btn" onClick={() => setShowUpload(true)}>
              <Icon.Upload /> Upload File
            </button>
          )}
        </div>
      </div>

      {/* Summary Strip */}
      <div style={styles.summaryStrip}>
        {[
          { label: "Total Businesses", value: loading ? "—" : total, color: "var(--color-ink)" },
          { label: "Showing", value: loading ? "—" : businesses.length, color: "var(--color-primary)" },
          { label: "Current Page", value: loading ? "—" : `${page} / ${totalPages}`, color: "var(--color-muted)" },
          { label: "Page Size", value: loading ? "—" : pageSize, color: "var(--color-muted)" },
        ].map(s => (
          <div key={s.label} className="frosted-glass saas-card" style={styles.summaryCard}>
            <span style={{ ...styles.summaryValue, color: s.color }}>{s.value}</span>
            <span style={styles.summaryLabel}>{s.label}</span>
          </div>
        ))}
      </div>

      {/* Error banner */}
      {error && (
        <div style={styles.errorBanner}>
          <Icon.AlertCircle /> &nbsp;{error}
        </div>
      )}

      {/* Filters Bar */}
      <div className="frosted-glass saas-card" style={styles.filtersBar}>
        <div className="search-bar" style={{ width: 280 }}>
          <Icon.Search />
          <input
            type="text"
            placeholder="Search name, type, address…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div style={{ display: "flex", gap: 10, marginLeft: "auto", alignItems: "center" }}>
          <Icon.Filter />

          <select
            style={styles.select}
            value={barangay}
            onChange={e => setBarangay(e.target.value)}
          >
            <option value="All Barangays">All Barangays</option>
            {barangays.map(b => (
              <option key={b.barangayID} value={b.barangayID}>
                {b.barangayName}
              </option>
            ))}
          </select>

          <select
            style={styles.select}
            value={status}
            onChange={e => setStatus(e.target.value)}
          >
            {STATUS_FILTERS.map(s => <option key={s}>{s}</option>)}
          </select>

          <label style={styles.pageSizeLabel}>
            Rows
            <select
              style={{ ...styles.select, width: 120 }}
              value={pageSize}
              onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}
            >
              {PAGE_SIZE_OPTIONS.map(size => (
                <option key={size} value={size}>{`${size} per page`}</option>
              ))}
            </select>
          </label>

          <span style={styles.resultCount}>
            {loading ? "Loading…" : `${total} result${total !== 1 ? "s" : ""}`}
          </span>
        </div>
      </div>

      {/* Data Table */}
      <div className="frosted-glass saas-card" style={{ padding: 0 }}>
        <div style={{ overflowX: "auto" }}>
          <table style={styles.table}>
            <thead>
              <tr style={styles.thead}>
                {[
                  "ID",
                  "Business Name",
                  "Type",
                  "Line of Business",
                  "Barangay",
                  "Address",
                  "Size",
                  "Last Renewal",
                  "Permit",
                  "Flag",
                  "",
                ].map(h => (
                  <th key={h || "actions"} style={styles.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={REGISTRY_TABLE_COL_COUNT} style={styles.emptyCell}>
                    <div style={styles.emptyContent}>
                      <span style={{ color: "var(--color-muted)", fontSize: 13 }}>Loading registry…</span>
                    </div>
                  </td>
                </tr>
              ) : businesses.length === 0 ? (
                <EmptyState hasFilters={!!hasFilters} onUpload={() => setShowUpload(true)} />
              ) : (
                businesses.map((b, i) => (
                  <tr
                    key={b.businessID}
                    style={{ ...styles.tr, background: i % 2 === 0 ? "var(--color-input-bg)" : "transparent" }}
                  >
                    <td style={{ ...styles.td, fontFamily: "monospace", fontSize: 12, color: "var(--color-muted)" }}>
                      #{b.businessID}
                    </td>
                    <td style={{ ...styles.td, fontWeight: 600, color: "var(--color-ink)", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {b.businessName}
                    </td>
                    <td style={styles.td}>{b.businessType || "—"}</td>
                    <td style={{ ...styles.td, maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {b.lineOfBusiness || "—"}
                    </td>
                    <td style={styles.td}>{b.barangayName || "—"}</td>
                    <td style={{ ...styles.td, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {b.businessAddress || "—"}
                    </td>
                    <td style={styles.td}>{b.businessSize || "—"}</td>
                    <td style={{ ...styles.td, fontSize: 12 }}>
                      {b.lastRenewalDate ? b.lastRenewalDate.slice(0, 10) : "—"}
                    </td>
                    <td style={styles.td}>
                      <StatusBadge variant={getStatusVariant(b.applicationStatus)}>
                        {b.applicationStatus}
                      </StatusBadge>
                    </td>
                    <td style={styles.td}>
                      {b.flagColor
                        ? <StatusBadge variant={getFlagVariant(b.flagColor)}>{b.flagColor}</StatusBadge>
                        : "—"}
                    </td>
                    <td style={styles.td}>
                      <button
                        className="registry-action-btn"
                        style={styles.viewBtn}
                        onClick={() => setDetailId(b.businessID)}
                      >
                        <Icon.Eye /> View
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {!loading && businesses.length > 0 && (
          <div style={styles.pagination}>
            <span style={styles.pageInfo}>
              Page {page} of {totalPages} &nbsp;·&nbsp; {total} total entries
            </span>
            <div style={{ display: "flex", gap: 6 }}>
              <button
                style={styles.pageBtn}
                disabled={page === 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
              >
                <Icon.ChevronLeft /> Prev
              </button>

              {/* Show max 5 page buttons to avoid overflow */}
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter(n => n === 1 || n === totalPages || Math.abs(n - page) <= 2)
                .reduce((acc, n, idx, arr) => {
                  if (idx > 0 && arr[idx - 1] !== n - 1) {
                    acc.push(
                      <button key={`gap-${n}`} style={{ ...styles.pageBtn, cursor: "default" }} disabled>…</button>
                    );
                  }
                  acc.push(
                    <button
                      key={`page-${n}`}
                      style={{ ...styles.pageBtn, ...(n === page ? styles.pageBtnActive : {}) }}
                      onClick={() => setPage(n)}
                    >
                      {n}
                    </button>
                  );
                  return acc;
                }, [])}

              <button
                style={styles.pageBtn}
                disabled={page === totalPages}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              >
                Next <Icon.ChevronRight />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <footer className="saas-footer frosted-glass">
        <p>&copy; 2026 Municipality of Mataasnakahoy. All Rights Reserved.</p>
        <p className="footer-links"><span>BPLO Portal</span> &bull; <span>System Settings</span></p>
      </footer>

      {/* Upload Modal */}
      {/* Upload Modal */}
      <AnimatePresence isVisible={showUpload}>
        <UploadModal
          token={token}
          onClose={() => setShowUpload(false)}
          onSuccess={() => { fetchBusinesses(); setShowUpload(false); }}
        />
      </AnimatePresence>

      <AnimatePresence isVisible={showImport}>
        <UploadModal
          variant="sync"
          token={token}
          onClose={() => setShowImport(false)}
          onSuccess={() => { fetchBusinesses(); setShowImport(false); }}
        />
      </AnimatePresence>

      {/* Business Detail Modal */}
      <AnimatePresence isVisible={!!detailId}>
        <BusinessDetailModal
          businessId={detailId}
          token={token}
          isAdmin={isAdmin}
          onSuccess={fetchBusinesses}
          onClose={() => setDetailId(null)}
        />
      </AnimatePresence>

    </DashboardLayout>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = {
  summaryStrip: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 },
  summaryCard: { display: "flex", flexDirection: "column", gap: 4, padding: "18px 24px", borderRadius: "var(--radius-lg)" },
  summaryValue: { fontSize: 28, fontWeight: 800, lineHeight: 1 },
  summaryLabel: { fontSize: 12, color: "var(--color-muted)", fontWeight: 500 },
  filtersBar: { display: "flex", alignItems: "center", gap: 12, padding: "14px 20px", borderRadius: "var(--radius-lg)" },
  select: {
    background: "var(--color-hover)", border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-sm)", padding: "8px 12px", fontSize: 13,
    color: "var(--color-ink)", fontFamily: "var(--font-base)", cursor: "pointer", outline: "none",
  },
  resultCount: { fontSize: 12, color: "var(--color-muted)", fontWeight: 500, whiteSpace: "nowrap" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  thead: { background: "var(--color-input-bg)", borderBottom: "1px solid var(--color-border)" },
  th: {
    padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 700,
    color: "var(--color-muted)", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap",
  },
  tr: { borderBottom: "1px solid rgba(226,232,240,0.4)", transition: "background 0.15s" },
  td: { padding: "13px 16px", color: "var(--color-muted)", whiteSpace: "nowrap" },
  emptyCell: { padding: "48px 16px", textAlign: "center", color: "var(--color-muted)", fontSize: 14 },
  emptyContent: { display: "flex", flexDirection: "column", alignItems: "center", gap: 4 },
  viewBtn: { display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12 },
  pagination: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderTop: "1px solid var(--color-border-soft)" },
  pageInfo: { fontSize: 12, color: "var(--color-muted)" },
  pageBtn: {
    minWidth: 32, height: 32, padding: "0 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border)",
    background: "var(--color-modal-bg)", color: "var(--color-muted)", cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    gap: 6, fontSize: 13, fontWeight: 600, fontFamily: "var(--font-base)", transition: "all 0.15s",
  },
  pageBtnActive: { background: "var(--color-primary)", color: "#fff", border: "1px solid var(--color-primary)" },
  pageSizeLabel: { display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--color-muted)", cursor: "default" },

  // Modal styles
  modalBackdrop: { position: "fixed", inset: 0, zIndex: 100, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 },
  modalCard: { background: "var(--color-modal-bg)", borderRadius: "var(--radius-xl)", padding: 32, boxShadow: "0 24px 60px rgba(15,23,42,0.18)", position: "relative", maxHeight: "90vh", overflowY: "auto" },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 },
  modalTitle: { fontSize: 18, fontWeight: 700, color: "var(--color-ink)", margin: 0 },
  closeBtn: { background: "transparent", border: "none", cursor: "pointer", color: "var(--color-muted)", display: "flex", alignItems: "center", justifyContent: "center", padding: 4 },
  modalFooter: { display: "flex", justifyContent: "flex-end", gap: 10 },
  editInput: { flex: 1, padding: "8px 12px", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", fontSize: 13, color: "var(--color-ink)", fontFamily: "var(--font-base)", outline: "none", boxSizing: "border-box" },
};
