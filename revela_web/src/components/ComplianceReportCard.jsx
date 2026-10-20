import { useState } from "react";
import { saveAs } from "file-saver";
import Swal from "sweetalert2";
import FilterDropdown from "./FilterDropdown";
import InspectionDialog from "./InspectionDialog";
import { getInspectionVerifiedCompliantRequest } from "../services/api";
import {
  buildComplianceReport, complianceCsv, compliancePrintReport, paginateRecords, REGISTRY_LINK_OPTIONS,
  COMPLIANCE_REPORT_TITLE, COMPLIANCE_REPORT_DESCRIPTION, COMPLIANCE_REPORT_SCOPE,
} from "./businessCompliance";

const DEFAULT_FILTERS = { search: "", barangayID: "all", registryLink: "all" };

export default function ComplianceReportCard({ token, user, onPrint }) {
  const [open, setOpen] = useState(false);
  const [records, setRecords] = useState([]);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [checkedAt, setCheckedAt] = useState(null);
  const report = buildComplianceReport(records, filters, checkedAt);
  const visible = paginateRecords(report.rows, page, 10);
  const barangays = [{ value: "all", label: "All Barangays" }, ...[...new Map(records.map(record =>
    [String(record.barangayID), { value: String(record.barangayID), label: record.barangayName || "Unknown barangay" }],
  )).values()].sort((a, b) => a.label.localeCompare(b.label))];
  if (!barangays.some(option => option.value === filters.barangayID)) {
    barangays.push({ value: filters.barangayID, label: filters.barangayName || "Selected barangay (no current records)" });
  }

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const snapshot = await getInspectionVerifiedCompliantRequest(token);
      if (!Array.isArray(snapshot?.data)) throw new Error("The report API returned no record list.");
      setRecords(snapshot.data);
      setCheckedAt(snapshot.generatedAt);
      return snapshot;
    } catch (err) {
      setError(err.message || "Unable to load the current-compliance report.");
      return null;
    } finally {
      setLoading(false);
    }
  };
  const changeFilter = change => {
    setFilters(previous => ({ ...previous, ...change }));
    setPage(1);
  };
  const clearFilters = () => { setFilters(DEFAULT_FILTERS); setPage(1); };
  const viewList = () => { setOpen(true); setPage(1); void load(); };
  const download = async format => {
    // Refresh eligibility and update the open list to this same export snapshot.
    const snapshot = await load();
    if (!snapshot) return false;
    const exportReport = buildComplianceReport(snapshot.data, filters, snapshot.generatedAt);
    try {
      if (format === "csv") {
        saveAs(new Blob([complianceCsv(exportReport)], { type: "text/csv;charset=utf-8;" }),
          `Inspection_Verified_Compliant_Businesses_${snapshot.generatedAt.slice(0, 10)}.csv`);
      } else {
        onPrint(compliancePrintReport(exportReport, user));
      }
      return true;
    } catch (err) {
      setError(err.message || "Unable to export the current-compliance report.");
      return false;
    }
  };
  const chooseDownloadFormat = async () => {
    const { value: format } = await Swal.fire({
      title: `Export ${COMPLIANCE_REPORT_TITLE}`,
      text: "Select your desired export file format:",
      input: "radio",
      inputOptions: {
        pdf: "Official PDF Document",
        csv: "CSV Spreadsheet (Raw Data)",
      },
      inputValidator: value => {
        if (!value) return "Please choose an export format!";
      },
      showCancelButton: true,
      confirmButtonText: "Generate Report",
      confirmButtonColor: "var(--color-primary, #10b981)",
    });

    if (!format) return;
    if (!await download(format)) return;
    await Swal.fire({
      icon: "success",
      title: "Export Complete!",
      text: `${COMPLIANCE_REPORT_TITLE} exported as ${format.toUpperCase()}`,
      timer: 2000,
      showConfirmButton: false,
    });
  };
  const actions = <>
    <button type="button" className="ghost-btn compliance-report-download" onClick={() => void chooseDownloadFormat()} disabled={loading}>Download</button>
  </>;

  return <>
    <div className="saas-card frosted-glass operational-report-card">
      <div>
        <h3>{COMPLIANCE_REPORT_TITLE}</h3>
        <p>{COMPLIANCE_REPORT_DESCRIPTION}</p>
        <small>{COMPLIANCE_REPORT_SCOPE}</small>
        <small>Downloads use the View List filters. PDF opens the print / Save as PDF dialog.</small>
        {checkedAt && <small>Applied filters: {report.filtersLabel}</small>}
        {!open && error && <p role="alert">{error} <button type="button" className="ghost-btn" disabled={loading} onClick={() => void load()}>Retry</button></p>}
        {!open && loading && <p role="status">Preparing current-compliance records…</p>}
      </div>
      <div className="operational-report-actions">
        <button type="button" className="primary-btn" onClick={viewList} disabled={loading}>View List</button>
        {actions}
      </div>
    </div>
    {open && <InspectionDialog title={COMPLIANCE_REPORT_TITLE} description={COMPLIANCE_REPORT_SCOPE}
      onClose={() => setOpen(false)} busy={loading} className="compliance-report-dialog"
      panelStyle={{ width: "min(1100px, calc(100vw - 40px))", maxHeight: "90vh" }}>
      <div className="compliance-report-content">
        <p className="compliance-report-note">Pin Reference is the geospatial log reference, not an official Business ID. Dates use Asia/Manila.</p>
        <div className="compliance-report-filters">
          <label className="compliance-report-search">Business name / reference
            <input type="search" placeholder="Search business name or pin reference" value={filters.search}
              disabled={loading} onChange={event => changeFilter({ search: event.target.value })} />
          </label>
          <FilterDropdown label="Barangay" value={filters.barangayID} options={barangays} disabled={loading}
            onChange={value => changeFilter({ barangayID: value, barangayName: barangays.find(option => option.value === value)?.label })} />
          <FilterDropdown label="Registry Link" value={filters.registryLink} options={REGISTRY_LINK_OPTIONS} disabled={loading}
            onChange={value => changeFilter({ registryLink: value })} />
        </div>
        <div className="compliance-report-toolbar">
          <p role="status" aria-live="polite">{loading ? "Loading records…" : error ? "Report unavailable" : `${report.count} matching ${report.count === 1 ? "business" : "businesses"}`}</p>
          <div className="operational-report-actions">
            <button type="button" className="ghost-btn" disabled={loading} onClick={clearFilters}>Clear filters</button>
            <button type="button" className="ghost-btn" disabled={loading} onClick={() => void load()}>Refresh list</button>
            {actions}
          </div>
        </div>
        {error ? <div role="alert" className="compliance-report-empty"><p>{error}</p>
          <button type="button" className="secondary-btn" onClick={() => void load()}>Retry</button></div>
          : loading ? <p className="compliance-report-empty">Loading current-compliance evidence…</p>
            : report.count === 0 ? <p className="compliance-report-empty">No inspection-verified compliant businesses match these filters.</p>
              : <>
                <div className="compliance-report-table-scroll"><table className="compliance-report-table">
                  <thead><tr>{report.columns.map(column => <th key={column} scope="col">{column}</th>)}</tr></thead>
                  <tbody>{visible.data.map(row => <tr key={row["Pin Reference"]}>
                    {report.columns.map(column => <td key={column}>{row[column] || "—"}</td>)}
                  </tr>)}</tbody>
                </table></div>
                <div className="compliance-report-pagination">
                  <button type="button" className="ghost-btn" disabled={visible.page === 1} onClick={() => setPage(visible.page - 1)}>Previous</button>
                  <span>Page {visible.page} of {visible.pages}</span>
                  <button type="button" className="ghost-btn" disabled={visible.page === visible.pages} onClick={() => setPage(visible.page + 1)}>Next</button>
                </div>
              </>}
        {checkedAt && <p className="compliance-report-note">Eligibility checked: {report.date}. Exports include all matching records across every page.</p>}
      </div>
    </InspectionDialog>}
  </>;
}
