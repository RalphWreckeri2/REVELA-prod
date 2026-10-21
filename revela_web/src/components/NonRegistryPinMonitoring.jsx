import { useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis } from "recharts";
import { saveAs } from "file-saver";
import KpiCard from "./KpiCard";
import ResponsiveChart from "./ResponsiveChart";
import InspectionDialog from "./InspectionDialog";
import { formatManilaDate, paginateRecords } from "./businessCompliance";
import {
  isNonRegistrySnapshot, NON_REGISTRY_COLUMNS, NON_REGISTRY_PIN_COLORS,
  nonRegistryCsv, nonRegistryRows,
} from "./nonRegistryMonitoring";
import "../styles/NonRegistryPinMonitoring.css";

const CARDS = [
  { key: "total", label: "Total non-registry pins", variant: "plain" },
  { key: "needs_verification", label: "Red / Yellow for verification", variant: "gold" },
  { key: "under_inspection", label: "Under inspection", variant: "gold" },
  { key: "verified_green", label: "Inspection-verified Green", variant: "green" },
];

export default function NonRegistryPinMonitoring({ snapshot, refreshing = false }) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [exportError, setExportError] = useState("");
  const listButtonRef = useRef(null);
  const valid = isNonRegistrySnapshot(snapshot);
  const rows = useMemo(() => valid ? nonRegistryRows(snapshot.records) : [], [snapshot, valid]);
  const visible = paginateRecords(rows, page, 20);
  const colors = NON_REGISTRY_PIN_COLORS.filter(({ key }) => key !== "Unknown"
    || (valid && snapshot.by_barangay.some(row => row.Unknown > 0)));
  const exportCsv = () => {
    setExportError("");
    try {
      const csv = nonRegistryCsv(snapshot);
      saveAs(new Blob([csv], { type: "text/csv;charset=utf-8;" }),
        `Non_Registry_Pins_${snapshot.generated_at.slice(0, 10)}.csv`);
    } catch (error) {
      setExportError(error.message || "Could not export non-registry pins.");
    }
  };

  return (
    <section className="non-registry-monitoring saas-card frosted-glass" aria-labelledby="non-registry-monitoring-title">
      <div className="non-registry-heading">
        <div>
          <h4 id="non-registry-monitoring-title">Non-Registry Pin Monitoring</h4>
          <p>Current pins marked “Not in Registry” using the same membership rules as the Map. Not in the imported registry does not automatically mean non-compliant.</p>
        </div>
        <div className="non-registry-actions">
          <button type="button" className="ghost-btn" ref={listButtonRef} disabled={!valid}
            onClick={() => { setPage(1); setOpen(true); }}>View List</button>
          <button type="button" className="ghost-btn" disabled={!valid} onClick={exportCsv}>Export CSV</button>
        </div>
      </div>
      {!valid ? <p role="status" className="non-registry-empty">Non-registry monitoring data is unavailable. Refresh Analytics to load this section.</p> : <>
        <div className="non-registry-kpis">
          {CARDS.map(card => <KpiCard key={card.key} value={snapshot.summary[card.key]} label={card.label} iconVariant={card.variant}
            icon={<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="3" /></svg>} />)}
        </div>
        <p className="non-registry-note">Counts are pins, not deduplicated businesses. Under inspection includes submitted reports awaiting verification and may overlap Red/Yellow counts. Verified Green uses the compliant-business export’s detection/inspector-report origins and current admin-verification evidence; Green colour alone is not enough.</p>
        <h5>Non-registry pins by barangay and current flag</h5>
        {snapshot.summary.total === 0 ? <p className="non-registry-empty" role="status">No non-registry pins match the selected filters.</p> : (
          <ResponsiveChart height={Math.max(260, snapshot.by_barangay.length * 32 + 80)}>
            {({ width }) => <BarChart data={snapshot.by_barangay} layout="vertical" margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
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
        <p className="non-registry-note">Barangay, flag, detection-date and latest-inspection filters apply. Registry status, sector, business type/size and renewal filters do not apply to this non-registry population.</p>
        <p className="non-registry-note">Snapshot: {formatManilaDate(snapshot.generated_at)}. Cards, chart, View List and CSV use the same complete filtered snapshot.{refreshing ? " Updating snapshot…" : ""}</p>
      </>}
      {exportError && !open && <p role="alert" className="non-registry-error">{exportError}</p>}
      {open && valid && <InspectionDialog title="Non-Registry Pin Monitoring — View List" onClose={() => setOpen(false)}
        description="Pin Reference is a map record reference, not an official Business ID. This list uses the same snapshot and dashboard filters as the monitoring cards and chart."
        className="non-registry-dialog" returnFocusRef={listButtonRef}>
        <div className="non-registry-list-toolbar">
          <p role="status">{snapshot.summary.total} matching {snapshot.summary.total === 1 ? "pin" : "pins"}</p>
          <button type="button" className="ghost-btn" onClick={exportCsv}>Export CSV</button>
        </div>
        {exportError && <p role="alert" className="non-registry-error">{exportError}</p>}
        {rows.length === 0 ? <p className="non-registry-empty">No non-registry pins match the selected filters.</p> : <>
          <div className="non-registry-table-scroll"><table className="non-registry-table">
            <caption className="analytics-sr-only">Non-registry pins, current flags and inspection status</caption>
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
    </section>
  );
}
