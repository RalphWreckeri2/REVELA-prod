/**
 * KpiCard.jsx
 *
 * Reusable metric card for the KPI grid.
 * Used 3+ times on the Overview page; will be reused on Analytics, etc.
 *
 * Props:
 *   icon     — SVG element
 *   iconVariant — "gold" | "red" | "green" (controls icon background/color)
 *   value    — string | number  (the big headline number)
 *   label    — string           (descriptive caption below the value)
 *   delta    — string           (optional: "+2.3% vs last month")
 *   trend    — "up" | "down"    (optional: controls color and arrow)
 */

const VARIANT_CLASSES = {
  gold:  "kpi-icon--gold",
  red:   "kpi-icon--red",
  green: "kpi-icon--green",
};

export default function KpiCard({ icon, iconVariant = "green", value, label, delta, trend, style }) {
  // Determine delta color and arrow depending on the trend direction
  const trendColor = trend === 'up' ? '#16a34a' : trend === 'down' ? '#dc2626' : '#64748b';
  const trendIcon = trend === 'up' ? '↑' : trend === 'down' ? '↓' : '−';

  return (
    <div className="kpi-card frosted-glass saas-card" style={style}>
      <div className={`kpi-icon ${VARIANT_CLASSES[iconVariant]}`}>
        {icon}
      </div>
      <div className="kpi-info">
        <h3>{value}</h3>
        <p>{label}</p>
        {delta && (
          <p style={{ fontSize: 12, fontWeight: 600, color: trendColor, margin: "4px 0 0 0" }}>
            {trendIcon} {delta}
          </p>
        )}
      </div>
    </div>
  );
}
