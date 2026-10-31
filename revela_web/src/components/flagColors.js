// Flag color → UI color mapping shared by Maps & Flags and Analytics.
export const FLAG_COLORS = Object.freeze({
  Red: { marker: "#ef4444", bg: "var(--flag-red-bg)", text: "var(--flag-red-text)", label: "Detected Unregistered" },
  Yellow: { marker: "#f59e0b", bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)", label: "Suspected Unregistered" },
  Yellow_Inspector: { marker: "#f59e0b", bg: "var(--flag-yellow-bg)", text: "var(--flag-yellow-text)", label: "Suspected Unregistered from Inspectors" },
  Orange: { marker: "#e65100", bg: "var(--flag-orange-bg)", text: "var(--flag-orange-text)", label: "1st/2nd Warning / 3rd Notice Closure" },
  Black: { marker: "#000000", bg: "var(--flag-black-bg)", text: "var(--flag-black-text)", label: "Blacklisted / Non-Responsive" },
  Purple: { marker: "#7c3aed", bg: "var(--flag-purple-bg)", text: "var(--flag-purple-text)", label: "Closed / Abandoned" },
  Green: { marker: "#22c55e", bg: "var(--flag-green-bg)", text: "var(--flag-green-text)", label: "Active Business" },
  in_inspection: { marker: "#0284c7", bg: "rgba(2, 132, 199, 0.12)", text: "#0284c7", label: "Currently Being Inspected / Dispatched" },
});

export const defaultColor = {
  marker: "var(--color-muted)",
  bg: "var(--flag-default-bg)",
  text: "var(--flag-default-text)",
  label: "Unknown",
};
