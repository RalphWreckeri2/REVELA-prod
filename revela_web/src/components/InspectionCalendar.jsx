import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getInspectionCalendarRequest } from "../services/api";

const EVENT_LABELS = {
  dispatched: "Dispatched",
  reassigned: "Reassigned",
  submitted: "Inspector submitted",
  verified: "Verified",
  cancelled: "Cancelled",
};

const EVENT_COLORS = {
  dispatched: "#2563eb",
  reassigned: "#d97706",
  submitted: "#16a34a",
  verified: "#64748b",
  cancelled: "#dc2626",
};

const toIsoDate = (date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const formatMonth = (date) =>
  new Intl.DateTimeFormat("en", { month: "long", year: "numeric" }).format(date);

export default function InspectionCalendar({ token, initialDate }) {
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const date = initialDate ? new Date(`${initialDate}T00:00:00`) : new Date();
    return new Date(date.getFullYear(), date.getMonth(), 1);
  });
  const [selectedDate, setSelectedDate] = useState(() => initialDate || toIsoDate(new Date()));
  const [calendar, setCalendar] = useState({ days: [], activities: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

  const dayCounts = useMemo(
    () => new Map((calendar.days || []).map((day) => [day.date, day.count])),
    [calendar.days],
  );
  const monthCells = useMemo(() => {
    const firstWeekday = new Date(
      visibleMonth.getFullYear(),
      visibleMonth.getMonth(),
      1,
    ).getDay();
    const daysInMonth = new Date(
      visibleMonth.getFullYear(),
      visibleMonth.getMonth() + 1,
      0,
    ).getDate();
    return [
      ...Array.from({ length: firstWeekday }, () => null),
      ...Array.from({ length: daysInMonth }, (_, index) => index + 1),
    ];
  }, [visibleMonth]);

  const selectMonth = (offset) => {
    const next = new Date(
      visibleMonth.getFullYear(),
      visibleMonth.getMonth() + offset,
      1,
    );
    setVisibleMonth(next);
    setSelectedDate(toIsoDate(next));
  };

  return (
    <section className="inspection-calendar-page" aria-label="Inspection activity calendar">
      <div className="inspection-calendar-layout">
        <section className="inspection-calendar-card" aria-label="Calendar">
          <div className="inspection-calendar-month">
            <button type="button" aria-label="Previous month" onClick={() => selectMonth(-1)}>‹</button>
            <h2>{formatMonth(visibleMonth)}</h2>
            <button type="button" aria-label="Next month" onClick={() => selectMonth(1)}>›</button>
          </div>
          <div className="inspection-calendar-tools">
            <button type="button" className="ghost-btn" onClick={() => {
              const today = new Date();
              setVisibleMonth(new Date(today.getFullYear(), today.getMonth(), 1));
              setSelectedDate(toIsoDate(today));
            }}>Today</button>
            <button type="button" className="ghost-btn" onClick={() => void fetchCalendar()} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          <div className="inspection-calendar-grid inspection-calendar-weekdays" aria-hidden="true">
            {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div className="inspection-calendar-grid">
            {monthCells.map((day, index) => {
              if (!day) return <span className="inspection-calendar-empty" key={`empty-${index}`} />;
              const date = toIsoDate(new Date(
                visibleMonth.getFullYear(),
                visibleMonth.getMonth(),
                day,
              ));
              const count = dayCounts.get(date) || 0;
              return (
                <button
                  key={date}
                  type="button"
                  className={`inspection-calendar-day${selectedDate === date ? " is-selected" : ""}`}
                  onClick={() => setSelectedDate(date)}
                  aria-label={`${date}${count ? `, ${count} activities` : ""}`}
                  aria-pressed={selectedDate === date}
                >
                  <span>{day}</span>
                  {count > 0 && <small>{count}</small>}
                </button>
              );
            })}
          </div>
          <p className="inspection-calendar-key">
            <span /> A dot count indicates saved inspection activity.
          </p>
        </section>

        <section className="inspection-calendar-card inspection-calendar-activities">
          <div className="inspection-calendar-activities-header">
            <div>
              <p className="inspection-calendar-eyebrow">SELECTED DATE</p>
              <h2>{new Intl.DateTimeFormat("en", {
                weekday: "long",
                month: "long",
                day: "numeric",
                year: "numeric",
              }).format(new Date(`${selectedDate}T00:00:00`))}</h2>
            </div>
            <span className="inspection-calendar-count">
              {calendar.activities?.length || 0} activities
            </span>
          </div>

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
          ) : calendar.activities?.length ? (
            <ol className="inspection-calendar-list">
              {calendar.activities.map((activity) => (
                <li key={activity.eventID}>
                  <span
                    className="inspection-calendar-event-dot"
                    style={{ background: EVENT_COLORS[activity.eventType] || "#64748b" }}
                  />
                  <div className="inspection-calendar-event-content">
                    <div className="inspection-calendar-event-top">
                      <strong>{EVENT_LABELS[activity.eventType] || activity.eventType}</strong>
                      <time dateTime={activity.eventTimestamp}>
                        {String(activity.eventTimestamp).slice(11, 16)}
                      </time>
                    </div>
                    <p>{activity.detectedName || `Location #${activity.targetLogID}`}</p>
                    <small>
                      {[activity.barangayName, activity.assignedToName && `Inspector: ${activity.assignedToName}`, activity.actorName && `By: ${activity.actorName}`]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                    {activity.inspectionResult && (
                      <small>Result: {activity.inspectionResult}</small>
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
                </li>
              ))}
            </ol>
          ) : (
            <p className="inspection-calendar-state">
              No recorded inspection activity for this date.
            </p>
          )}
        </section>
      </div>
    </section>
  );
}
