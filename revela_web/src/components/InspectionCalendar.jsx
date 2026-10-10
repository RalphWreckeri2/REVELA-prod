/**
 * InspectionCalendar.jsx
 *
 * Full-page inspection activity calendar.
 *
 * Reads `GET /api/inspections/calendar?month=YYYY-MM&date=YYYY-MM-DD`, which
 * already returns both the per-day activity counts for the whole month and the
 * detailed lifecycle events for the selected day. Everything rendered below is
 * derived from that single response - no extra requests, no invented data.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getInspectionCalendarRequest } from "../services/api";

// ── Event vocabulary (mirrors the backend lifecycle event types) ───────────────
// `status` reuses the four Kanban board columns so the summary strip never
// introduces a status the rest of the app does not already use.
const EVENT_TYPES = {
  dispatched: { label: "Dispatched", status: "Assigned" },
  reassigned: { label: "Reassigned", status: "Reassigned" },
  submitted: { label: "Inspector submitted", status: "Submitted" },
  verified: { label: "Verified", status: "Verified" },
  cancelled: { label: "Cancelled", status: "Cancelled" },
};

const SUMMARY_ORDER = ["Assigned", "Reassigned", "Submitted", "Verified"];

// Restrained, semantic tones. Green is reserved for REVELA accents; the rest are
// used only for small indicators so the panel never becomes loud.
const STATUS_TONE = {
  Assigned: { fg: "var(--color-primary-dark)", bg: "var(--color-primary-light)", rail: "var(--color-primary)" },
  Reassigned: { fg: "#a16207", bg: "#fefce8", rail: "#eab308" },
  Submitted: { fg: "#15803d", bg: "#dcfce7", rail: "#16a34a" },
  Verified: { fg: "var(--color-muted)", bg: "var(--color-hover)", rail: "var(--color-subtle)" },
  Cancelled: { fg: "var(--color-danger)", bg: "var(--color-danger-light)", rail: "var(--color-danger)" },
};

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// ── Helpers ────────────────────────────────────────────────────────────────────
const toIsoDate = (date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const parseIsoDate = (iso) => new Date(`${iso}T00:00:00`);

const formatMonth = (date) =>
  new Intl.DateTimeFormat("en", { month: "long", year: "numeric" }).format(date);

const formatLongDate = (iso) =>
  new Intl.DateTimeFormat("en", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(parseIsoDate(iso));

/**
 * Reads HH:MM straight out of the stored timestamp so the displayed time is the
 * recorded local time, never shifted by the viewer's timezone.
 */
const formatClock = (value) => {
  const match = String(value || "").match(/T?(\d{2}):(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : "";
};

const toneFor = (eventType) => STATUS_TONE[EVENT_TYPES[eventType]?.status] ?? STATUS_TONE.Verified;

/**
 * Maps an inspection result onto the shared `--flag-*` design tokens. Falls back
 * safely for values that have no dedicated token (e.g. "Given First Notice").
 */
const flagToken = (value) => String(value || "").trim().split(/\s+/)[0].toLowerCase();

/** Normalises the backend's "YYYY-MM-DD HH:MM:SS" for a <time dateTime>. */
const toIsoDateTime = (value) => String(value || "").trim().replace(" ", "T");

// ── Icons ──────────────────────────────────────────────────────────────────────
const Icon = {
  Chevron: ({ dir = "left" }) => (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={dir === "right" ? { transform: "rotate(180deg)" } : undefined}
    >
      <polyline points="15 18 9 12 15 6" />
    </svg>
  ),
  Refresh: () => (
    <svg
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  ),
};

export default function InspectionCalendar({ token, initialDate }) {
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const date = initialDate ? parseIsoDate(initialDate) : new Date();
    return new Date(date.getFullYear(), date.getMonth(), 1);
  });
  const [selectedDate, setSelectedDate] = useState(() => initialDate || toIsoDate(new Date()));
  const [calendar, setCalendar] = useState({ days: [], activities: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const todayIso = useMemo(() => toIsoDate(new Date()), []);

  const fetchCalendar = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const result = await getInspectionCalendarRequest(
        `${visibleMonth.getFullYear()}-${String(visibleMonth.getMonth() + 1).padStart(2, "0")}`,
        selectedDate,
        token,
      );
      setCalendar(result);
    } catch (requestError) {
      setError(requestError.message || "Unable to load inspection activities.");
    } finally {
      setLoading(false);
    }
  }, [token, visibleMonth, selectedDate]);

  useEffect(() => {
    void Promise.resolve().then(fetchCalendar);
  }, [fetchCalendar]);

  const activities = useMemo(() => calendar.activities || [], [calendar.activities]);

  const dayCounts = useMemo(
    () => new Map((calendar.days || []).map((day) => [day.date, day.count])),
    [calendar.days],
  );

  /** Cells are padded to whole weeks so every row keeps a consistent height. */
  const monthCells = useMemo(() => {
    const year = visibleMonth.getFullYear();
    const month = visibleMonth.getMonth();
    const leading = new Date(year, month, 1).getDay();
    const dayCount = new Date(year, month + 1, 0).getDate();
    const cells = [
      ...Array.from({ length: leading }, () => null),
      ...Array.from({ length: dayCount }, (_, i) => i + 1),
    ];
    while (cells.length % 7 !== 0) cells.push(null);
    return cells;
  }, [visibleMonth]);

  /** Counts per board status for the selected day, from the events we already have. */
  const statusSummary = useMemo(() => {
    const counts = new Map(SUMMARY_ORDER.map((status) => [status, 0]));
    activities.forEach((activity) => {
      const status = EVENT_TYPES[activity.eventType]?.status;
      if (counts.has(status)) counts.set(status, counts.get(status) + 1);
    });
    return SUMMARY_ORDER.map((status) => ({ status, count: counts.get(status) }));
  }, [activities]);

  const selectMonth = (offset) => {
    const next = new Date(
      visibleMonth.getFullYear(),
      visibleMonth.getMonth() + offset,
      1,
    );
    setVisibleMonth(next);
    setSelectedDate(toIsoDate(next));
  };

  const goToToday = () => {
    const today = new Date();
    setVisibleMonth(new Date(today.getFullYear(), today.getMonth(), 1));
    setSelectedDate(toIsoDate(today));
  };

  return (
    <section className="inspection-calendar-page" aria-label="Inspection activity calendar">
      <div className="inspection-calendar-layout">
        {/* ── Calendar panel ─────────────────────────────────────────────── */}
        <section className="inspection-calendar-card inspection-calendar-panel" aria-label="Calendar">
          <div className="inspection-calendar-toolbar">
            <div className="inspection-calendar-month">
              <h2 id="inspection-calendar-month-label">{formatMonth(visibleMonth)}</h2>
              <div className="inspection-calendar-nav" role="group" aria-label="Month navigation">
                <button
                  type="button"
                  onClick={() => selectMonth(-1)}
                  aria-label="Previous month"
                  title="Previous month"
                >
                  <Icon.Chevron dir="left" />
                </button>
                <button
                  type="button"
                  onClick={() => selectMonth(1)}
                  aria-label="Next month"
                  title="Next month"
                >
                  <Icon.Chevron dir="right" />
                </button>
              </div>
            </div>

            <div className="inspection-calendar-tools">
              <button type="button" className="ghost-btn" onClick={goToToday}>
                Today
              </button>
              <button
                type="button"
                className="ghost-btn"
                onClick={() => void fetchCalendar()}
                disabled={loading}
                aria-label="Refresh inspection activity"
              >
                <Icon.Refresh />
                {loading ? "Refreshing…" : "Refresh"}
              </button>
            </div>
          </div>

          <div
            className="inspection-calendar-grid inspection-calendar-weekdays"
            aria-hidden="true"
          >
            {WEEKDAYS.map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>

          <div
            className="inspection-calendar-grid"
            role="group"
            aria-labelledby="inspection-calendar-month-label"
          >
            {monthCells.map((day, index) => {
              if (!day) {
                return <span className="inspection-calendar-empty" key={`empty-${index}`} aria-hidden="true" />;
              }
              const date = toIsoDate(new Date(
                visibleMonth.getFullYear(),
                visibleMonth.getMonth(),
                day,
              ));
              const count = dayCounts.get(date) || 0;
              const isSelected = selectedDate === date;
              const isToday = date === todayIso;
              const classes = [
                "inspection-calendar-day",
                isToday ? "is-today" : "",
                isSelected ? "is-selected" : "",
              ]
                .filter(Boolean)
                .join(" ");

              return (
                <button
                  key={date}
                  type="button"
                  className={classes}
                  onClick={() => setSelectedDate(date)}
                  aria-pressed={isSelected}
                  aria-label={`${formatLongDate(date)}${isToday ? " (today)" : ""}, ${
                    count === 0
                      ? "no inspection activity"
                      : `${count} inspection ${count === 1 ? "activity" : "activities"}`
                  }`}
                  title={count > 0 ? `${count} inspection ${count === 1 ? "activity" : "activities"}` : undefined}
                >
                  <span className="inspection-calendar-day-number">{day}</span>
                  {count > 0 && (
                    <span
                      className={`inspection-calendar-day-dot${count > 1 ? " is-count" : ""}`}
                      aria-hidden="true"
                    >
                      {count > 1 ? count : null}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <p className="inspection-calendar-key">
            <span className="inspection-calendar-key-dot" aria-hidden="true" />
            A dot marks days with recorded inspection activity (number = event count).
          </p>
        </section>

        {/* ── Selected-date panel ────────────────────────────────────────── */}
        <section className="inspection-calendar-card inspection-calendar-activities" aria-label="Selected date activity">
          <header className="inspection-calendar-activities-header">
            <div className="inspection-calendar-activities-heading">
              <p className="inspection-calendar-eyebrow">Selected date</p>
              <h2>{formatLongDate(selectedDate)}</h2>
            </div>
            <span className="inspection-calendar-count">
              {activities.length} {activities.length === 1 ? "activity" : "activities"}
            </span>
          </header>

          {activities.length > 0 && (
            <dl className="inspection-calendar-summary">
              {statusSummary.map(({ status, count }) => {
                const tone = STATUS_TONE[status];
                return (
                  <div className="inspection-calendar-summary-item" key={status}>
                    <dt>
                      <span
                        className="inspection-calendar-summary-dot"
                        style={{ background: tone.rail }}
                        aria-hidden="true"
                      />
                      {status}
                    </dt>
                    <dd style={{ color: count > 0 ? tone.fg : undefined }}>{count}</dd>
                  </div>
                );
              })}
            </dl>
          )}

          {loading ? (
            <p className="inspection-calendar-state">Loading activities…</p>
          ) : error ? (
            <div className="inspection-calendar-error" role="alert">
              <p className="inspection-calendar-state is-error">{error}</p>
              <button
                className="ghost-btn"
                type="button"
                onClick={() => void fetchCalendar()}
                disabled={loading}
              >
                Retry
              </button>
            </div>
          ) : activities.length ? (
            <ol className="inspection-calendar-list">
              {activities.map((activity) => {
                const meta = EVENT_TYPES[activity.eventType] || { label: activity.eventType };
                const tone = toneFor(activity.eventType);
                const clock = formatClock(activity.eventTimestamp);
                const flag = flagToken(activity.inspectionResult);
                const details = [
                  activity.barangayName,
                  activity.assignedToName && `Inspector: ${activity.assignedToName}`,
                  activity.actorName && `By: ${activity.actorName}`,
                ]
                  .filter(Boolean)
                  .join(" · ");

                return (
                  <li className="inspection-calendar-activity" key={activity.eventID}>
                    <span
                      className="inspection-calendar-activity-rail"
                      style={{ background: tone.rail }}
                      aria-hidden="true"
                    />
                    <div className="inspection-calendar-activity-body">
                      <div className="inspection-calendar-activity-top">
                        <span
                          className="inspection-calendar-status"
                          style={{ color: tone.fg, background: tone.bg }}
                        >
                          {meta.label}
                        </span>
                        {clock && (
                          <time dateTime={toIsoDateTime(activity.eventTimestamp)}>{clock}</time>
                        )}
                      </div>

                      <p className="inspection-calendar-activity-name">
                        {activity.detectedName || `Location #${activity.targetLogID}`}
                      </p>

                      {details && (
                        <p className="inspection-calendar-activity-meta">{details}</p>
                      )}

                      {activity.remarks && (
                        <p className="inspection-calendar-activity-remark">
                          {activity.remarks}
                        </p>
                      )}

                      <div className="inspection-calendar-activity-foot">
                        {activity.inspectionResult && (
                          <span
                            className="inspection-calendar-flag"
                            style={{
                              background: `var(--flag-${flag}-bg, var(--color-hover))`,
                              color: `var(--flag-${flag}-text, var(--color-muted))`,
                            }}
                          >
                            {activity.inspectionResult}
                          </span>
                        )}
                        {activity.targetLogID != null && (
                          <Link
                            className="inspection-calendar-record-link"
                            to={`/inspections?search=${encodeURIComponent(activity.targetLogID)}`}
                          >
                            Open dispatch record
                          </Link>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <div className="inspection-calendar-empty-state">
              <img src="/searching.png" alt="" width="72" height="72" />
              <p className="inspection-calendar-empty-title">No activity recorded</p>
              <p className="inspection-calendar-empty-text">
                Nothing was dispatched, reassigned, submitted, or verified on this date.
                Pick another day to review its inspection history.
              </p>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
