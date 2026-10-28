import { useState } from "react";
import NonRegistryPinMonitoring from "./NonRegistryPinMonitoring";
import AnalyticsInfoTip from "./AnalyticsInfoTip";

const TABS = [
  { id: "unlinked", label: "Non-registry pins", membership: "unlinked" },
  { id: "linked", label: "Registry-linked pins", membership: "linked" },
];

export default function PinMonitoringPanel({ nonRegistry, registryLinked, refreshing = false }) {
  const [activeTab, setActiveTab] = useState("unlinked");
  const current = TABS.find(tab => tab.id === activeTab) || TABS[0];
  return (
    <details className="pin-monitoring-panel saas-card frosted-glass">
      <summary>
        <span>
          <strong>Pin monitoring</strong>
        </span>
        <span className="pin-monitoring-summary-hint">Open panel</span>
      </summary>
      <div className="pin-monitoring-body">
        <div className="pin-monitoring-tabs" role="tablist" aria-label="Pin monitoring membership">
          {TABS.map(tab => (
            <button key={tab.id} type="button" role="tab" id={`pin-tab-${tab.id}`}
              aria-selected={activeTab === tab.id} aria-controls={`pin-panel-${tab.id}`}
              tabIndex={activeTab === tab.id ? 0 : -1}
              className={activeTab === tab.id ? "active" : ""}
              onClick={() => setActiveTab(tab.id)}>
              {tab.label}
            </button>
          ))}
        </div>
        <div id={`pin-panel-${current.id}`} role="tabpanel" aria-labelledby={`pin-tab-${current.id}`}>
          <NonRegistryPinMonitoring embedded membership={current.membership} refreshing={refreshing}
            snapshot={current.membership === "linked" ? registryLinked : nonRegistry} />
        </div>
        <div className="pin-monitoring-note">
          <AnalyticsInfoTip label="About pin monitoring">
            Pin counts are separate from registry businesses and inspection reports. Non-registry membership follows the Map rules; a pin outside the imported registry is not automatically non-compliant.
          </AnalyticsInfoTip>
        </div>
      </div>
    </details>
  );
}
