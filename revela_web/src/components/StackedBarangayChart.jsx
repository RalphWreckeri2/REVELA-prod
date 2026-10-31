import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import ResponsiveChart from "./ResponsiveChart";
import WrappedAxisTick from "./WrappedAxisTick";

const SHORT_BARANGAY = (name = "") => String(name).replace("Barangay ", "Brgy. ");

function StackedTooltip({ active, payload, statuses, categoryKey }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="analytics-chart-tooltip analytics-stacked-tooltip">
      <p className="analytics-stacked-tooltip-title">{row[categoryKey]}</p>
      {statuses.map(status => {
        const count = Number(row.__counts?.[status.key] || 0);
        return (
          <div className="analytics-stacked-tooltip-row" key={status.key}>
            <span className="analytics-stacked-swatch" style={{ background: status.color }} />
            <span className="analytics-stacked-tooltip-label">{status.label}</span>
            <strong>{count.toLocaleString()}</strong>
          </div>
        );
      })}
      <div className="analytics-stacked-tooltip-total">
        <span className="analytics-stacked-swatch" aria-hidden="true" />
        <span>Total</span>
        <strong>{Number(row.__total || 0).toLocaleString()}</strong>
        <span />
      </div>
    </div>
  );
}

export default function StackedBarangayChart({
  data = [],
  statuses,
  categoryKey = "barangayName",
  categoryLabel = "category",
  emptyMessage = "No records match the selected filters.",
}) {
  const rows = useMemo(() => data.map(row => {
    const counts = {};
    let total = 0;
    statuses.forEach(status => {
      const value = Number(row[status.key] || 0);
      counts[status.key] = Number.isFinite(value) ? value : 0;
      total += counts[status.key];
    });
    return { ...row, ...counts, __counts: counts, __total: total };
  }).filter(row => row.__total > 0)
    .sort((a, b) => b.__total - a.__total || String(a[categoryKey]).localeCompare(String(b[categoryKey]))),
  [data, statuses, categoryKey]);

  const hasData = rows.some(row => row.__total > 0);
  const chartHeight = Math.max(280, rows.length * 40 + 70);
  const statusTotals = statuses.map(status => ({
    ...status,
    total: rows.reduce((sum, row) => sum + Number(row.__counts?.[status.key] || 0), 0),
  }));
  const nonzeroStatuses = statusTotals.filter(status => status.total > 0);
  const maxTotal = rows.reduce((max, row) => Math.max(max, row.__total), 0);

  if (!hasData) {
    return (
      <div className="analytics-chart-empty" role="status">
        <strong>No data</strong>
        <span>{emptyMessage}</span>
      </div>
    );
  }

  return (
    <div className="analytics-stacked-chart">
      <div className="analytics-stacked-legend" aria-label={`${categoryLabel} chart legend`}>
        {nonzeroStatuses.map(status => (
          <span className="analytics-stacked-legend-item" key={status.key}>
            <span className="analytics-stacked-swatch" style={{ background: status.color }} />
            {status.label}
          </span>
        ))}
      </div>
      <ResponsiveChart height={chartHeight}>
        {({ width }) => {
          const labelWidth = Math.min(210, Math.max(128, width * 0.28));
          return (
            <BarChart data={rows} layout="vertical" barSize={24} barCategoryGap="22%"
              margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
               <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--analytics-grid-color)" />
              <XAxis type="number" domain={[0, maxTotal]} allowDecimals={false}
                tickFormatter={value => Number(value).toLocaleString()}
                tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
              <YAxis type="category" dataKey={categoryKey} width={labelWidth} interval={0}
                tick={<WrappedAxisTick width={labelWidth - 12} maxLines={2}
                  format={categoryKey === "barangayName" ? SHORT_BARANGAY : undefined} />}
                axisLine={false} tickLine={false} />
              <Tooltip content={<StackedTooltip statuses={nonzeroStatuses} categoryKey={categoryKey} />}
                 cursor={{ fill: "var(--analytics-chart-hover)" }} />
              {nonzeroStatuses.map(status => (
                <Bar key={status.key} dataKey={status.key} stackId="count" name={status.label}
                  fill={status.color} isAnimationActive={false} />
              ))}
            </BarChart>
          );
        }}
      </ResponsiveChart>
    </div>
  );
}
