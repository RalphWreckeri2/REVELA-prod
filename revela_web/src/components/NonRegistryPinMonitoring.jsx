import { useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis } from "recharts";
import { saveAs } from "file-saver";
import KpiCard from "./KpiCard";
import ResponsiveChart from "./ResponsiveChart";
import AnalyticsInfoTip from "./AnalyticsInfoTip";
import InspectionDialog from "./InspectionDialog";
import { formatManilaDate, paginateRecords } from "./businessCompliance";
import {
  isNonRegistrySnapshot, isRegistryLinkedSnapshot, NON_REGISTRY_COLUMNS, NON_REGISTRY_PIN_COLORS,
  nonRegistryCsv, registryLinkedCsv, nonRegistryRows,
} from "./nonRegistryMonitoring";
import "../styles/NonRegistryPinMonitoring.css";

const CARDS = [
  { key: "total", label: "Total non-registry pins", variant: "plain" },
  { key: "needs_verification", label: "Red / Yellow for verification", variant: "gold" },
  { key: "under_inspection", label: "Under inspection", variant: "gold" },
  { key: "verified_green", label: "Inspection-verified Green", variant: "green" },
];

export default function NonRegistryPinMonitoring({ snapshot, refreshing = false, membership = "unlinked", embedded = false }) {
  const linked = membership === "linked";
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [exportError, setExportError] = useState("");
  const listButtonRef = useRef(null);
  const valid = linked ? isRegistryLinkedSnapshot(snapshot) : isNonRegistrySnapshot(snapshot);
  const rows = useMemo(() => valid ? nonRegistryRows(snapshot.records) : [], [snapshot, valid]);
  const visible = paginateRecords(rows, page, 20);
  const colors = NON_REGISTRY_PIN_COLORS.filter(({ key }) => valid
    && snapshot.by_barangay.some(row => Number(row[key] || 0) > 0));
  const chartRows = valid ? [...snapshot.by_barangay].map(row => ({
    ...row,
    __total: colors.reduce((sum, { key }) => sum + Number(row[key] || 0), 0),
  })).sort((a, b) => b.__total - a.__total || a.barangayName.localeCompare(b.barangayName)) : [];
  const exportCsv = () => {
    setExportError("");
    try {
      const csv = linked ? registryLinkedCsv(snapshot) : nonRegistryCsv(snapshot);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }),
        `${linked ? "Registry_Linked" : "Non_Registry"}_Pins_${snapshot.generated_at.slice(0, 10)}.csv`);
    } catch (error) {
      setExportError(error.message || "Could not export non-registry pins.");
    }
  };

  const Wrapper = embedded ? "div" : "section";
  return (
    <Wrapper className={`non-registry-monitoring${embedded ? " non-registry-monitoring--embedded" : " saas-card frosted-glass"}`}
      aria-labelledby={embedded ? undefined : `pin-monitoring-title-${membership}`}>
      {!embedded && (
        <div className="non-registry-heading">
          <div>
            <h4 id={`pin-monitoring-title-${membership}`}>{linked ? "Registry-Linked Pin Monitoring" : "Non-Registry Pin Monitoring"}</h4>
            <p>{linked
              ? "Current geospatial pins linked to an official Registry business by businessID. Origin remains separately recorded."
              : "Current pins marked “Not in Registry” using the same membership rules as the Map. Not in the imported registry does not automatically mean non-compliant."}</p>
          </div>
          <div className="non-registry-actions">
            <button type="button" className="ghost-btn" ref={listButtonRef} disabled={!valid}
              onClick={() => { setPage(1); setOpen(true); }}>View List</button>
            <button type="button" className="ghost-btn" disabled={!valid} onClick={exportCsv}>Export CSV</button>
          </div>
        </div>
      )}
      {embedded && (
        <div className="non-registry-embedded-toolbar">
          <div className="non-registry-actions">
            <button type="button" className="ghost-btn" ref={listButtonRef} disabled={!valid}
              onClick={() => { setPage(1); setOpen(true); }}>View List</button>
            <button type="button" className="ghost-btn" disabled={!valid} onClick={exportCsv}>Export CSV</button>
          </div>
        </div>
      )}
      {!valid ? <p role="status" className="non-registry-empty">{linked ? "Registry-linked" : "Non-registry"} monitoring data is unavailable. Refresh Analytics to load this section.</p> : <>
        <div className="non-registry-kpis">
          {CARDS.map(card => (
            <KpiCard key={card.key} value={snapshot.summary[card.key]}
              label={linked ? card.label.replace("non-registry", "Registry-linked") : card.label}
              iconVariant={card.variant}
              icon={<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="3" /></svg>} />
          ))}
        </div>
        <h5>
          How many {linked ? "registry-linked" : "non-registry"} pins are in each barangay?
          <AnalyticsInfoTip label="About pin monitoring chart">
            These counts are map pins, not unique businesses. Under-inspection pins may overlap flag counts; verified Green requires current inspection evidence.
          </AnalyticsInfoTip>
        </h5>
        {snapshot.summary.total === 0 ? <p className="non-registry-empty" role="status">No {linked ? "Registry-linked" : "non-registry"} pins match the selected filters.</p> : (
          <ResponsiveChart height={Math.max(260, chartRows.length * 36 + 80)}>
            {({ width }) => <BarChart data={chartRows} layout="vertical" margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--color-border-soft)" />
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: "var(--color-muted)" }} />
              <YAxis type="category" dataKey="barangayName" interval={0} width={width < 440 ? 112 : 142}
                tick={{ fontSize: 10, fill: "var(--color-muted)" }} tickFormatter={name => String(name).replace("Barangay ", "Brgy. ")} />
              <Tooltip contentStyle={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {colors.map(({ key, color }) => <Bar key={key} dataKey={key} stackId="pins" fill={color} name={`${key} pins`} isAnimationActive={false} />)}
            </BarChart>}
          </ResponsiveChart>
        )}
        <div className="non-registry-note">
          <AnalyticsInfoTip label="About pin filters and refresh">
            Barangay, flag, detection-date, and latest-inspection filters apply. Registry status, sector, business type/size, and renewal-date filters do not apply. This panel’s cards, chart, list, and CSV use one filtered snapshot from {formatManilaDate(snapshot.generated_at)}.
            {refreshing ? " The snapshot is refreshing." : ""}
          </AnalyticsInfoTip>
        </div>
      </>}
      {exportError && !open && <p role="alert" className="non-registry-error">{exportError}</p>}
      {open && valid && <InspectionDialog title={`${linked ? "Registry-Linked" : "Non-Registry"} Pin Monitoring — View List`} onClose={() => setOpen(false)}
        description="Pin Reference is a map record reference, not an official Business ID. Origin and Registry link are shown separately."
        className="non-registry-dialog" returnFocusRef={listButtonRef}>
        <div className="non-registry-list-toolbar">
          <p role="status">{snapshot.summary.total} matching {snapshot.summary.total === 1 ? "pin" : "pins"}</p>
          <button type="button" className="ghost-btn" onClick={exportCsv}>Export CSV</button>
        </div>
        {exportError && <p role="alert" className="non-registry-error">{exportError}</p>}
        {rows.length === 0 ? <p className="non-registry-empty">No {linked ? "Registry-linked" : "non-registry"} pins match the selected filters.</p> : <>
          <div className="non-registry-table-scroll"><table className="non-registry-table">
            <caption className="analytics-sr-only">{linked ? "Registry-linked" : "Non-registry"} pins, origin, current flags and inspection status</caption>
            <thead><tr>{NON_REGISTRY_COLUMNS.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead>
            <tbody>{visible.data.map(row => <tr key={row["Pin Reference"]}>
              {NON_REGISTRY_COLUMNS.map(column => <td key={column}>{row[column]}</td>)}
            </tr>)}</tbody>
          </table></div>
          <div className="non-registry-pagination">
            <button type="button" className="ghost-btn" disabled={visible.page === 1} onClick={() => setPage(visible.page - 1)}>Previous</button>
            <span>Page {visible.page} of {visible.pages}</span>
            <button type="button" className="ghost-btn" disabled={visible.page === visible.pages} onClick={() => setPage(visible.page + 1)}>Next</button>
          </div>
        </>}
        <p className="non-registry-note">CSV exports include all {snapshot.summary.total} matching pins, not just this page. Snapshot: {formatManilaDate(snapshot.generated_at)}.</p>
      </InspectionDialog>}
    </Wrapper>
  );
}
