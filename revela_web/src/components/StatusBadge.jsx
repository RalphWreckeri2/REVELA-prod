/**
 * StatusBadge.jsx
 *
 * Reusable pill badge for compliance status, counts, labels.
 * Composes the shared .badge + .badge--{variant} CSS classes from global.css.
 *
 * Props:
 *   variant — "red" | "green" | "gold" | "orange" | "default"
 *   children — badge content (text or number)
 */

export default function StatusBadge({ variant = "default", children }) {
  const cls = variant === "default" ? "badge" : `badge badge--${variant}`;
  return <span className={cls}>{children}</span>;
}
