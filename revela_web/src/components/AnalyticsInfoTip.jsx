import { useId } from "react";

export default function AnalyticsInfoTip({ children, label = "More information" }) {
  const tooltipId = useId();
  return (
    <span className="analytics-info-tip">
      <button type="button" className="analytics-info-tip-trigger"
        aria-label={label} aria-describedby={tooltipId}>
        i
      </button>
      <span id={tooltipId} className="analytics-info-tip-content" role="tooltip">
        {children}
      </span>
    </span>
  );
}
