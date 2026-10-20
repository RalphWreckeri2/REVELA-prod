import { BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip } from "recharts";
import ResponsiveChart from "./ResponsiveChart";
import WrappedAxisTick from "./WrappedAxisTick";

// Give every barangay a readable label, without making the SVG wider than its
// card. Dense/narrow charts use horizontal rows; roomy charts retain columns.
export default function GeographicBarChart({ data, seriesName = "Total Businesses", tooltipContent }) {
  const needsRows = width => width < data.length * 72 + 80;
  return (
    <ResponsiveChart height={({ width }) => needsRows(width) ? Math.max(260, data.length * 24 + 40) : 340}>
      {({ width }) => {
        const rows = needsRows(width);
        const labelWidth = rows ? Math.min(240, Math.max(170, width * 0.32)) : 52;
        return (
          <BarChart data={data} layout={rows ? "vertical" : "horizontal"}
            margin={{ top: 10, right: 20, left: 4, bottom: 8 }} barSize={rows ? 16 : undefined}>
            <CartesianGrid strokeDasharray="3 3" vertical={rows} horizontal={!rows} stroke="rgba(226,232,240,0.4)" />
            <XAxis type={rows ? "number" : "category"} dataKey={rows ? undefined : "barangayName"}
              height={rows ? 30 : 108} tickMargin={rows ? 8 : 12} interval={rows ? "preserveStartEnd" : 0}
              tick={rows ? { fontSize: 11, fill: "var(--color-muted)" } : <WrappedAxisTick
                width={Math.min(110, (width - 80) / data.length - 6)} maxLines={null}
                textAnchor="middle" verticalAnchor="start" format={name => name.replace("Barangay ", "Brgy. ")} />}
              axisLine={false} tickLine={false} />
            <YAxis type={rows ? "category" : "number"} dataKey={rows ? "barangayName" : undefined}
              width={labelWidth} interval={0}
              tick={rows ? <WrappedAxisTick width={labelWidth - 12} maxLines={2} format={name => name.replace("Barangay ", "Brgy. ")} /> : { fontSize: 11, fill: "var(--color-muted)" }}
              axisLine={false} tickLine={false} />
            <Tooltip content={tooltipContent} labelFormatter={(label, payload) => payload[0]?.payload?.fullName || label}
              cursor={{ fill: "rgba(255,255,255,0.05)" }}
              contentStyle={{ borderRadius: 8, border: "none", boxShadow: "0 4px 12px rgba(0,0,0,0.15)", background: "var(--color-surface)", fontSize: 12 }} />
            <Bar dataKey="total" name={seriesName} fill="#3b82f6" radius={rows ? [0, 4, 4, 0] : [4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        );
      }}
    </ResponsiveChart>
  );
}
