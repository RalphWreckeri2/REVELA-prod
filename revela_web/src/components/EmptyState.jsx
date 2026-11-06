export default function EmptyState({
  title = "No data available",
  message = "",
  actionLabel,
  onAction,
  actionClassName = "ghost-btn",
  icon = "/searching.png",
  compact = false,
  className = "",
  style,
}) {
  return (
    <div
      className={`app-empty-state${compact ? " app-empty-state--compact" : ""}${className ? ` ${className}` : ""}`}
      role="status"
      style={style}
    >
      {icon && <img src={icon} alt="" aria-hidden="true" />}
      <div className="app-empty-state__content">
        <strong>{title}</strong>
        {message && <p>{message}</p>}
        {actionLabel && onAction && (
          <button type="button" className={actionClassName} onClick={onAction}>
            {actionLabel}
          </button>
        )}
      </div>
    </div>
  );
}
