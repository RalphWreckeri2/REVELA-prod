export function SkeletonBlock({ className = "", style, statusLabel }) {
  return (
    <div
      aria-hidden={statusLabel ? undefined : "true"}
      aria-label={statusLabel}
      aria-busy={statusLabel ? "true" : undefined}
      role={statusLabel ? "status" : undefined}
      className={`ui-skeleton ${className}`.trim()}
      style={style}
    />
  );
}

export function SkeletonTableRows({ columns, rows = 5 }) {
  return Array.from({ length: rows }, (_, rowIndex) => (
    <tr key={rowIndex} className="ui-skeleton-table-row">
      {Array.from({ length: columns }, (_, columnIndex) => (
        <td key={columnIndex}>
          {rowIndex === 0 && columnIndex === 0 && (
            <span className="ui-sr-only" role="status" aria-busy="true">Loading records</span>
          )}
          <SkeletonBlock
            style={{
              width: columnIndex === 0 ? "62%" : `${48 + ((rowIndex + columnIndex) % 4) * 12}%`,
            }}
          />
        </td>
      ))}
    </tr>
  ));
}

export function SkeletonList({ rows = 4 }) {
  return (
    <div className="ui-skeleton-list" role="status" aria-label="Loading records" aria-busy="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="ui-skeleton-list-row">
          <SkeletonBlock className="ui-skeleton-list-icon" />
          <div className="ui-skeleton-list-copy">
            <SkeletonBlock className="ui-skeleton-list-title" />
            <SkeletonBlock className="ui-skeleton-list-subtitle" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function SkeletonDetails({ rows = 5 }) {
  return (
    <div className="ui-skeleton-details" role="status" aria-label="Loading details" aria-busy="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="ui-skeleton-details-row">
          <SkeletonBlock className="ui-skeleton-details-label" />
          <SkeletonBlock className="ui-skeleton-details-value" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonKanbanBoard({ columns = 4 }) {
  return (
    <div
      className="ui-skeleton-kanban"
      role="status"
      aria-label="Loading inspections"
      aria-busy="true"
      style={{ "--skeleton-columns": columns }}
    >
      {Array.from({ length: columns }, (_, columnIndex) => (
        <div key={columnIndex} className="ui-skeleton-kanban-column">
          <SkeletonBlock className="ui-skeleton-kanban-heading" />
          {[0, 1, 2].map((cardIndex) => (
            <div key={cardIndex} className="ui-skeleton-kanban-card">
              <SkeletonBlock className="ui-skeleton-kanban-line" />
              <SkeletonBlock className="ui-skeleton-kanban-line ui-skeleton-kanban-line--short" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
