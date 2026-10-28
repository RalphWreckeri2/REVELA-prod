import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, Tooltip, XAxis, YAxis } from "recharts";
import ResponsiveChart from "./ResponsiveChart";
import WrappedAxisTick from "./WrappedAxisTick";

const SHORT_BARANGAY = (name = "") => String(name).replace("Barangay ", "Brgy. ");

function StackedTooltip({ active, payload, statuses }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="analytics-chart-tooltip analytics-stacked-tooltip">
      <p className="analytics-stacked-tooltip-title">{row.barangayName}</p>
      {statuses.map(status => {
        const count = Number(row.__counts?.[status.key] || 0);
        const share = row.__total > 0 ? (count / row.__total) * 100 : 0;
        return (
          <div className="analytics-stacked-tooltip-row" key={status.key}>
            <span className="analytics-stacked-swatch" style={{ background: status.color }} />
            <span className="analytics-stacked-tooltip-label">{status.label}</span>
            <strong>{count.toLocaleString()}</strong>
            <span className="analytics-stacked-tooltip-share">{share.toFixed(1)}%</span>
          </div>
        );
      })}
      <div className="analytics-stacked-tooltip-total">
        <span>Total</span>
        <strong>{Number(row.__total || 0).toLocaleString()}</strong>
        <span>100%</span>
      </div>
    </div>
  );
}

export default function StackedBarangayChart({
  data = [],
  statuses,
  legendLabel,
  totalLabel = "total",
  annotation = null,
  emptyMessage = "No records match the selected filters.",
}) {
  const [mode, setMode] = useState("counts");
  const rows = useMemo(() => data.map(row => {
    const counts = {};
    let total = 0;
    statuses.forEach(status => {
      const value = Number(row[status.key] || 0);
      counts[status.key] = Number.isFinite(value) ? value : 0;
      total += counts[status.key];
    });
    const values = {};
    statuses.forEach(status => {
      values[status.key] = mode === "share"
        ? (total > 0 ? (counts[status.key] / total) * 100 : 0)
        : counts[status.key];
    });
    return { ...row, ...values, __counts: counts, __total: total };
  }), [data, mode, statuses]);

  const hasData = rows.some(row => row.__total > 0);
  const chartHeight = Math.max(280, rows.length * 34 + 70);
  const statusTotals = statuses.map(status => ({
    ...status,
    total: rows.reduce((sum, row) => sum + Number(row.__counts?.[status.key] || 0), 0),
  }));
  const nonzeroStatuses = statusTotals.filter(status => status.total > 0);
  const singleCategoryNote = nonzeroStatuses.length === 1
    ? `All ${nonzeroStatuses[0].total.toLocaleString()} ${totalLabel} in this filtered view are ${nonzeroStatuses[0].label}.`
    : null;

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
      <div className="analytics-stacked-chart-toolbar">
        <div className="analytics-stacked-legend" aria-label={`${legendLabel} legend`}>
          <span className="analytics-stacked-legend-label">{legendLabel}</span>
          {statuses.map(status => (
            <span className="analytics-stacked-legend-item" key={status.key}>
              <span className="analytics-stacked-swatch" style={{ background: status.color }} />
              {status.label}
            </span>
          ))}
        </div>
        <div className="analytics-stacked-mode" role="group" aria-label={`Show ${legendLabel.toLowerCase()} as counts or share`}>
          <button type="button" aria-pressed={mode === "counts"} className={mode === "counts" ? "active" : ""}
            onClick={() => setMode("counts")}>Counts</button>
          <button type="button" aria-pressed={mode === "share"} className={mode === "share" ? "active" : ""}
            onClick={() => setMode("share")}>Share</button>
        </div>
      </div>

      {annotation && (
        <p className="analytics-stacked-annotation">
          <span className="analytics-stacked-swatch" style={{ background: annotation.color }} />
          <strong>{annotation.label}</strong>
          <span>{annotation.text}</span>
        </p>
      )}

      {singleCategoryNote && <p className="analytics-stacked-footnote">{singleCategoryNote}</p>}
      <div className="analytics-stacked-scroll" tabIndex={0} aria-label={`Scrollable ${legendLabel.toLowerCase()} chart by barangay`}>
        <ResponsiveChart height={chartHeight}>
          {({ width }) => {
            const labelWidth = Math.min(210, Math.max(128, width * 0.28));
            return (
              <BarChart data={rows} layout="vertical" barSize={20} barCategoryGap="26%"
                margin={{ top: 8, right: 58, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="rgba(226,232,240,0.4)" />
                <XAxis type="number" domain={mode === "share" ? [0, 100] : [0, "auto"]}
                  allowDecimals={mode !== "share"}
                  tickFormatter={value => mode === "share" ? `${Math.round(value)}%` : Number(value).toLocaleString()}
                  tick={{ fontSize: 10, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="barangayName" width={labelWidth} interval={0}
                  tick={<WrappedAxisTick width={labelWidth - 12} maxLines={2} format={SHORT_BARANGAY} />}
                  axisLine={false} tickLine={false} />
                <Tooltip content={<StackedTooltip statuses={statuses} />}
                  cursor={{ fill: "rgba(255,255,255,0.05)" }} />
                {statuses.map((status, statusIndex) => (
                  <Bar key={status.key} dataKey={status.key} stackId="status" name={status.label}
                    fill={status.color} isAnimationActive={false}>
                    <LabelList dataKey={status.key} content={(props) => {
                      const row = rows[props.index];
                      if (!row) return null;
                      const lastVisible = statuses.reduce((last, item, index) =>
                        row.__counts[item.key] > 0 ? index : last, -1);
                      if (row.__total > 0 && statusIndex !== lastVisible) return null;
                      if (row.__total === 0 && statusIndex !== 0) return null;
                      const x = Number(props.x || 0) + Number(props.width || 0) + 6;
                      const y = Number(props.y || 0) + Number(props.height || 0) / 2;
                      return (
                        <text x={x} y={y} dominantBaseline="middle" textAnchor="start"
                          fill="var(--color-ink)" fontSize={10} fontWeight={700}>
                          {row.__total.toLocaleString()}
                        </text>
                      );
                    }} />
                  </Bar>
                ))}
              </BarChart>
            );
          }}
        </ResponsiveChart>
      </div>
      <p className="analytics-stacked-footnote">
        {mode === "share"
          ? `Bars show each status share of the ${totalLabel}; the number at each bar end is the ${totalLabel} count.`
          : `Bars show ${totalLabel} counts; the number at each bar end is the ${totalLabel} total.`}
      </p>
    </div>
  );
}
