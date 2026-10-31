import { SkeletonBlock } from "./LoadingSkeleton";
import "../styles/MapOverview.css";

const lines = (count, className) => Array.from({ length: count }, (_, index) => (
  <SkeletonBlock key={index} className={className} />
));

export function OverviewMapSkeleton() {
  return (
    <div className="map-overview analytics-overview-skeleton" aria-hidden="true">
      <div className="map-overview-topbar">
        {lines(3, "map-overview-total analytics-loading-kpi")}
      </div>
      <section className="map-overview-filter-card">
        <div className="map-overview-filter-heading">
          <SkeletonBlock className="map-overview-filter-heading-icon" />
          <div className="analytics-loading-copy">{lines(2, "analytics-loading-line")}</div>
        </div>
        <div className="map-overview-controls">
          <div className="map-overview-control-group">
            {["Barangay", "Sector", "Line of business", "Date range"].map(label => (
              <div className="map-overview-select-label--filter" key={label}>
                <span>{label}</span>
                <SkeletonBlock className="analytics-loading-select" />
              </div>
            ))}
          </div>
        </div>
        <p className="map-overview-filter-scope">Filters registered businesses only.</p>
      </section>
      <div className="analytics-map-update-slot" />
      <div className="map-overview-layout">
        <section className="map-overview-map-card">
          <div className="map-overview-map-heading map-overview-map-toolbar">
            <div className="map-overview-segmented">{lines(2, "analytics-loading-control")}</div>
            <div className="map-overview-hotspot-controls">
              <SkeletonBlock className="map-overview-hotspot-toggle" />
              <SkeletonBlock className="analytics-loading-line" />
            </div>
          </div>
          <div className="map-overview-map-stage"><SkeletonBlock className="analytics-loading-map" /></div>
          <div className="map-overview-map-hint"><SkeletonBlock className="analytics-loading-line" /></div>
        </section>
        <aside className="map-overview-panel">
          <div className="map-overview-panel-heading"><SkeletonBlock className="analytics-loading-heading" /></div>
          <section className="map-overview-detail-card">
            <div className="map-overview-card-heading"><SkeletonBlock className="analytics-loading-heading" /></div>
            <div className="map-overview-choice-row">{lines(4, "analytics-loading-control")}</div>
            <SkeletonBlock className="map-overview-stacked-bar" />
            <div className="map-overview-count-list">{lines(4, "analytics-loading-count-row")}</div>
          </section>
          <section className="map-overview-detail-card">
            <div className="map-overview-card-heading"><SkeletonBlock className="analytics-loading-heading" /></div>
            <div className="map-overview-choice-row">{lines(3, "analytics-loading-control")}</div>
            <SkeletonBlock className="map-overview-stacked-bar" />
            <div className="map-overview-count-list">{lines(3, "analytics-loading-count-row")}</div>
            <div className="map-overview-field-section">
              <div className="map-overview-card-heading"><SkeletonBlock className="analytics-loading-heading" /></div>
              <SkeletonBlock className="map-overview-stacked-bar" />
              <div className="map-overview-status-list">{lines(3, "analytics-loading-count-row")}</div>
              <div className="map-overview-outcome-list">{lines(3, "analytics-loading-count-row")}</div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

export function InspectorOperationsSkeleton() {
  return (
    <section className="saas-card frosted-glass analytics-inspector-operations-card" aria-hidden="true">
      <div className="analytics-card-heading"><div className="analytics-loading-copy">
        <SkeletonBlock className="analytics-loading-heading" />
        <SkeletonBlock className="analytics-loading-line" />
      </div></div>
      <div className="analytics-operations-legend">{lines(3, "analytics-loading-line")}</div>
      <div className="analytics-loading-operations-chart">
        {lines(2, "analytics-loading-operations-row")}
      </div>
      <div className="analytics-profile-disclosure analytics-inspector-detail">
        <SkeletonBlock className="analytics-loading-line" />
      </div>
    </section>
  );
}

export function RecommendationsSkeleton() {
  return (
    <section className="analytics-recommendation-list analytics-recommendations-skeleton" aria-hidden="true">
      <div className="analytics-recommendation-heading">
        <SkeletonBlock className="analytics-loading-recommendation-heading" />
        <SkeletonBlock className="analytics-loading-line" />
      </div>
      <div className="analytics-recommendation-table">
        <div className="analytics-recommendation-columns">
          <span /> <span>Barangay</span> <span>Priority</span> <span>Dispatch</span>
        </div>
        <div className="analytics-recommendation-rows">
          {Array.from({ length: 5 }, (_, index) => (
            <div className="analytics-recommendation-row" key={index}>
              <div className="analytics-loading-recommendation-row">
                <SkeletonBlock className="analytics-recommendation-rank" />
                <div className="analytics-recommendation-place">{lines(2, "analytics-loading-line")}</div>
                <SkeletonBlock className="analytics-recommendation-priority analytics-loading-priority" />
                <SkeletonBlock className="analytics-recommendation-assignment" />
              </div>
            </div>
          ))}
        </div>
      </div>
      <SkeletonBlock className="analytics-recommendation-toggle" />
      <div className="analytics-loading-recommendation-footer">{lines(2, "analytics-loading-line")}</div>
    </section>
  );
}
