/**
 * InspectionCalendar.jsx
 *
 * Deadline-first calendar of latest report rows, with the existing persisted
 * lifecycle calendar retained separately under Activity history.
 */

import { useEffect, useMemo, useState, useRef } from "react";
import { Link } from "react-router-dom";
import { getInspectionCalendarRequest, getInspectionsRequest } from "../services/api";
import { deadlineGroups, deadlineStatusCounts, loadLatestAssignments, manilaToday } from "./deadlineCalendar";
import "../styles/InspectionCalendar.css";

// ── Event vocabulary (mirrors the backend lifecycle event types) ───────────────
const EVENT_TYPES = {
  dispatched: { label: "Dispatched", status: "Assigned" },
  reassigned: { label: "Reassigned", status: "Reassigned" },
  submitted: { label: "Inspector submitted", status: "Submitted" },
  verified: { label: "Verified", status: "Verified" },
  cancelled: { label: "Cancelled", status: "Cancelled" },
};

// Restrained, semantic tones. Green is reserved for REVELA accents; the rest are
// used only when a selected-day event supplies its actual type.
const STATUS_TONE = {
  Assigned: { fg: "var(--color-primary-dark)", bg: "var(--color-primary-light)", rail: "var(--color-primary)" },
  Reassigned: { fg: "var(--flag-yellow-text)", bg: "var(--flag-yellow-bg)", rail: "var(--color-gold)" },
  Submitted: { fg: "var(--flag-green-text)", bg: "var(--flag-green-bg)", rail: "var(--color-primary)" },
  Verified: { fg: "var(--color-muted)", bg: "var(--color-hover)", rail: "var(--color-subtle)" },
  Cancelled: { fg: "var(--color-danger)", bg: "var(--color-danger-light)", rail: "var(--color-danger)" },
};

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const NO_ACTIVITIES = [];

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
 * recorded UTC time, never shifted by the viewer's timezone.
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

const eventCountLabel = (count) => `${count} ${count === 1 ? "event" : "events"}`;
const deadlineCountLabel = (count) => `${count} ${count === 1 ? "deadline" : "deadlines"}`;

function DeadlineAssignments({ date, reports }) {
  const [visible, setVisible] = useState(6);
  const counts = deadlineStatusCounts(reports);
  const breakdown = [
    ["Pending field submission", counts.pending],
    ["Submitted awaiting review", counts.submitted],
    ["Verified", counts.verified],
    ...(counts.other ? [["Other statuses", counts.other]] : []),
  ];
  return <>
    <header className="inspection-calendar-activities-header">
      <div>
        <p className="inspection-calendar-eyebrow">Latest recorded assignments · Selected deadline date</p>
        <h2 id="inspection-calendar-deadline-selected-label">{formatLongDate(date)}</h2>
      </div>
      <span className="inspection-calendar-count">{deadlineCountLabel(reports.length)}</span>
    </header>
    <dl className="inspection-calendar-summary">
      {breakdown.map(([label, count]) => <div className="inspection-calendar-summary-item" key={label}><dt>{label}</dt><dd>{count}</dd></div>)}
    </dl>
    {reports.length ? <>
      <ol className="inspection-calendar-list">
        {reports.slice(0, visible).map(report => {
          const tone = STATUS_TONE[report.verificationStatus] || STATUS_TONE.Verified;
          const deadline = report.recordedDeadline;
          return <li className="inspection-calendar-activity" key={report.reportID}>
            <span className="inspection-calendar-activity-rail" style={{ background: tone.rail }} aria-hidden="true" />
            <div className="inspection-calendar-activity-body">
              <div className="inspection-calendar-activity-top">
                <h3 className="inspection-calendar-assignment-name">{report.detectedName || "Establishment name unavailable"}</h3>
                <span className="inspection-calendar-status" style={{ color: tone.fg, background: tone.bg }}>{report.verificationStatus || "Status unavailable"}</span>
              </div>
              <dl className="inspection-calendar-deadline-meta">
                <div><dt>Barangay:</dt><dd>{report.barangayName || "Unavailable"}</dd></div>
                <div><dt>Inspector:</dt><dd>{report.inspectorName || "Unavailable"}</dd></div>
                <div><dt>Deadline:</dt><dd><time dateTime={deadline.dateTime}>{deadline.date} · {deadline.clock || "Time not supplied"}</time> · Asia/Manila</dd></div>
              </dl>
              <div className="inspection-calendar-activity-foot">
                <span className="inspection-calendar-activity-meta">Report #{report.reportID}{report.logID != null ? ` · Location #${report.logID}` : ""}</span>
                {report.logID != null && <Link className="inspection-calendar-record-link" to={`/inspections?search=${encodeURIComponent(report.logID)}`}>Search Dispatch for location #{report.logID}</Link>}
              </div>
            </div>
          </li>;
        })}
      </ol>
      {visible < reports.length && <button className="ghost-btn inspection-calendar-show-more" type="button" onClick={() => setVisible(count => count + 6)}>Show more ({reports.length - visible} remaining)</button>}
    </> : <p className="inspection-calendar-empty-state">No latest recorded assignments have a valid deadline on this date.</p>}
  </>;
}

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

/** The mini-calendar and month view share selection, counts, and keyboard behavior. */
function MonthDates({ visibleMonth, monthCells, selectedDate, todayIso, dayCounts, hasCounts, compact = false, onSelectDate, countLabel = eventCountLabel, deadlines = false }) {
  const dayCount = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 0).getDate();

  const handleDateKey = (event, day) => {
    const offsets = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    let nextDay;
    if (event.key in offsets) nextDay = day + offsets[event.key];
    else if (event.key === "Home") nextDay = 1;
    else if (event.key === "End") nextDay = dayCount;
    else return;

    event.preventDefault();
    nextDay = Math.max(1, Math.min(dayCount, nextDay));
    event.currentTarget.parentElement.querySelector(`[data-day="${nextDay}"]`)?.focus();
    onSelectDate(toIsoDate(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), nextDay)));
  };

  return (
    <div
      className={`inspection-calendar-grid ${compact ? "inspection-calendar-mini-dates" : "inspection-calendar-dates"}`}
      role="group"
      aria-labelledby={compact ? "inspection-calendar-mini-label" : "inspection-calendar-month-label"}
      aria-describedby="inspection-calendar-keyboard-help"
    >
      {monthCells.map((day, index) => {
        if (!day) {
          return <span className="inspection-calendar-empty" key={`empty-${index}`} aria-hidden="true" />;
        }
        const date = toIsoDate(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), day));
        const count = dayCounts.get(date) || 0;
        const isSelected = selectedDate === date;
        const isToday = date === todayIso;
        const countDescription = hasCounts
          ? `${countLabel(count)} recorded`
          : deadlines ? "deadline counts unavailable" : "activity counts not loaded";

        return (
          <button
            key={date}
            type="button"
            data-day={day}
            className={[
              "inspection-calendar-day",
              isToday ? "is-today" : "",
              isSelected ? "is-selected" : "",
              count > 0 ? "has-activity" : "",
            ].filter(Boolean).join(" ")}
            onClick={() => onSelectDate(date)}
            onFocus={(event) => event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" })}
            onKeyDown={(event) => handleDateKey(event, day)}
            tabIndex={isSelected ? 0 : -1}
            aria-pressed={isSelected}
            aria-current={isToday ? "date" : undefined}
            aria-controls={deadlines ? "inspection-calendar-selected-deadlines" : "inspection-calendar-selected-activity"}
            aria-label={`${formatLongDate(date)}${isToday ? " (today)" : ""}, ${countDescription}`}
          >
            <span className="inspection-calendar-day-number">{day}</span>
            {(count > 0 || (deadlines && !hasCounts && !compact)) && (
              <span className="inspection-calendar-day-events" aria-hidden="true">
                {compact ? null : hasCounts ? countLabel(count) : "—"}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default function InspectionCalendar({ token, initialDate }) {
  const [view, setView] = useState("deadlines");
  const deadlines = view === "deadlines";
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const date = parseIsoDate(initialDate || manilaToday());
    return new Date(date.getFullYear(), date.getMonth(), 1);
  });
  const [selectedDate, setSelectedDate] = useState(() => initialDate || manilaToday());
  const [calendar, setCalendar] = useState(null);
  const [requestState, setRequestState] = useState(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [deadlineVersion, setDeadlineVersion] = useState(0);
  const [deadlineData, setDeadlineData] = useState(null);
  const [deadlineRequest, setDeadlineRequest] = useState(null);
  const deadlineCache = useRef(null);

  const todayIso = deadlines ? manilaToday() : toIsoDate(new Date());
  const monthIso = `${visibleMonth.getFullYear()}-${String(visibleMonth.getMonth() + 1).padStart(2, "0")}`;
  const monthLabel = formatMonth(visibleMonth);

  useEffect(() => {
    if (!token || deadlines) return undefined;
    let isCurrent = true;
    const request = { token, month: monthIso, date: selectedDate, refreshVersion };
    const loadCalendar = async () => {
      if (!isCurrent) return;
      setRequestState({ ...request, status: "loading", error: "" });
      try {
        const result = await getInspectionCalendarRequest(monthIso, selectedDate, token);
        if (!isCurrent) return;
        if (
          result?.month !== monthIso || result?.selectedDate !== selectedDate ||
          !Array.isArray(result?.days) || !Array.isArray(result?.activities)
        ) {
          throw new Error("Unable to read inspection activity. Please try again.");
        }
        setCalendar({ token, refreshVersion, data: result });
        setRequestState({ ...request, status: "success", error: "" });
      } catch (requestError) {
        if (isCurrent) {
          setRequestState({
            ...request,
            status: "error",
            error: requestError.message || "Unable to load inspection activity.",
          });
        }
      }
    };
    void Promise.resolve().then(loadCalendar);
    // Ignore older responses after rapid date/month changes or unmounting.
    return () => { isCurrent = false; };
  }, [token, monthIso, selectedDate, refreshVersion, deadlines]);

  useEffect(() => {
    if (!token || !deadlines) return undefined;
    if (deadlineCache.current?.token === token && deadlineCache.current?.version === deadlineVersion) return undefined;
    let isCurrent = true;
    const request = { token, version: deadlineVersion };
    const load = async () => {
      if (!isCurrent) return;
      setDeadlineRequest({ ...request, status: "loading", error: "" });
      try {
        const rows = await loadLatestAssignments(params => getInspectionsRequest(params, token), {
          isCurrent: () => isCurrent,
          onProgress: progress => { if (isCurrent) setDeadlineRequest({ ...request, ...progress, status: "loading", error: "" }); },
        });
        if (!isCurrent || !rows) return;
        deadlineCache.current = { ...request, rows };
        setDeadlineData({ ...request, rows });
        setDeadlineRequest(previous => ({ ...previous, ...request, status: "success", error: "" }));
      } catch (requestError) {
        if (isCurrent) setDeadlineRequest(previous => ({ ...previous, ...request, status: "error", error: requestError.message || "Could not load assignment deadlines." }));
      }
    };
    void Promise.resolve().then(load);
    return () => { isCurrent = false; };
  }, [token, deadlines, deadlineVersion]);

  const requestMatches = requestState?.token === token &&
    requestState?.month === monthIso && requestState?.date === selectedDate &&
    requestState?.refreshVersion === refreshVersion;
  const activityLoading = !requestMatches || requestState.status === "loading";
  const activityError = requestMatches ? requestState.error : "";
  // Monthly counts can stay visible while another day in the same month loads.
  // Day details are never rendered until the response matches the current date.
  const monthData = calendar?.token === token && calendar?.data.month === monthIso &&
    calendar?.refreshVersion === refreshVersion && !activityError ? calendar.data : null;
  const dayReady = !activityLoading && !activityError && monthData?.selectedDate === selectedDate;
  const activities = dayReady ? monthData.activities : NO_ACTIVITIES;

  const activityDayCounts = useMemo(
    () => new Map((monthData?.days || [])
      .filter((day) => day.date.startsWith(`${monthIso}-`) && day.count > 0)
      .map((day) => [day.date, day.count])),
    [monthData, monthIso],
  );
  const monthlyEvents = [...activityDayCounts.values()].reduce((total, count) => total + count, 0);
  const latestActiveDate = [...activityDayCounts.keys()].sort().at(-1);
  const deadlineRequestMatches = deadlineRequest?.token === token && deadlineRequest?.version === deadlineVersion;
  const deadlineReady = deadlineRequestMatches && deadlineRequest.status === "success"
    && deadlineData?.token === token && deadlineData?.version === deadlineVersion;
  const deadlineLoading = !deadlineRequestMatches || deadlineRequest.status === "loading";
  const groups = useMemo(() => deadlineGroups(deadlineReady ? deadlineData.rows : []), [deadlineReady, deadlineData]);
  const deadlineDayCounts = useMemo(() => new Map([...groups.days].filter(([date]) => date.startsWith(`${monthIso}-`)).map(([date, rows]) => [date, rows.length])), [groups, monthIso]);
  const monthlyDeadlines = [...deadlineDayCounts.values()].reduce((sum, count) => sum + count, 0);
  const selectedAssignments = groups.days.get(selectedDate) || [];
  const dayCounts = deadlines ? deadlineDayCounts : activityDayCounts;
  const hasCounts = deadlines ? deadlineReady : Boolean(monthData);
  const loading = deadlines ? deadlineLoading : activityLoading;
  const error = deadlines ? deadlineRequestMatches ? deadlineRequest.error : "" : activityError;
  const progress = deadlineRequestMatches && deadlineRequest.pages
    ? `Page ${deadlineRequest.page} of ${deadlineRequest.pages}: ${deadlineRequest.loaded} of ${deadlineRequest.total} unique exposed rows loaded.` : "";

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

  /** Only summarize types actually present in the loaded selected-day events. */
  const statusSummary = useMemo(() => {
    const counts = new Map();
    activities.forEach((activity) => {
      counts.set(activity.eventType, (counts.get(activity.eventType) || 0) + 1);
    });
    return Object.entries(EVENT_TYPES)
      .filter(([eventType]) => counts.has(eventType))
      .map(([eventType, meta]) => ({ eventType, ...meta, count: counts.get(eventType) }));
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
    const today = deadlines ? parseIsoDate(manilaToday()) : new Date();
    setVisibleMonth(new Date(today.getFullYear(), today.getMonth(), 1));
    setSelectedDate(toIsoDate(today));
  };

  const refreshCalendar = () => deadlines ? setDeadlineVersion(version => version + 1) : setRefreshVersion(version => version + 1);
  const sharedDateProps = {
    visibleMonth, monthCells, selectedDate, todayIso, dayCounts,
    hasCounts, onSelectDate: setSelectedDate, deadlines,
    countLabel: deadlines ? deadlineCountLabel : eventCountLabel,
  };

  return (
    <section className="inspection-calendar-page" aria-label="Inspection calendar">
      <div className="inspection-calendar-tabs" role="tablist" aria-label="Inspection calendar view">
        {[['deadlines', 'Deadlines'], ['activity', 'Activity history']].map(([mode, label]) => <button
          key={mode} id={`inspection-calendar-tab-${mode}`} type="button" role="tab" aria-selected={view === mode}
          aria-controls="inspection-calendar-view" tabIndex={view === mode ? 0 : -1}
          onClick={() => setView(mode)} onKeyDown={event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === "Home" ? "deadlines" : event.key === "End" ? "activity" : mode === "deadlines" ? "activity" : "deadlines";
            setView(next); document.getElementById(`inspection-calendar-tab-${next}`)?.focus();
          }}
        >{label}</button>)}
      </div>
      <p id="inspection-calendar-keyboard-help" className="sr-only">
        Use the arrow keys to select dates in this month. Home selects the first day; End selects the last day.
        Selected-day {deadlines ? "assignments" : "activity"} appears below the calendar.
      </p>
      <div id="inspection-calendar-view" role="tabpanel" aria-labelledby={`inspection-calendar-tab-${view}`}>
      <section className="inspection-calendar-card inspection-calendar-scope" aria-label="Calendar counting scope">
        <h2>{deadlines ? "Latest recorded assignments" : "Activity history · UTC recording dates"}</h2>
        {deadlines ? <>
          <p>Counts use unique latest report rows and their deadlines, including Submitted and Verified—not lifecycle events or completion dates. Reassignment can replace earlier deadlines; this is not complete historical scheduling.</p>
          <p>Timezone-less deadlines are treated as Asia/Manila wall time for this view. This convention cannot establish the original timezone of old records. Offset pagination can shift during concurrent changes; even validated pages are not a guaranteed stable snapshot.</p>
          {deadlineReady ? <p>{deadlineData.rows.length} unique latest rows retrieved; {groups.excluded} missing/invalid deadlines excluded.</p> : <p role="status">{progress} Deadline totals remain unavailable until pagination finishes successfully.</p>}
        </> : <p>Counts and times use the existing recorded UTC dates without conversion. An inspection can have multiple lifecycle events; these are not deadline counts or completed-on-date counts.</p>}
      </section>
      <div className="inspection-calendar-layout">
        <aside className="inspection-calendar-card inspection-calendar-sidebar" aria-label="Calendar shortcuts and month overview">
          <div className="inspection-calendar-create">
            <Link className="primary-btn inspection-calendar-create-link" to="/map" aria-describedby="inspection-calendar-create-help">
              <span className="inspection-calendar-plus" aria-hidden="true">＋</span>
              <span>Create inspection assignment</span>
            </Link>
            <p id="inspection-calendar-create-help">
              Choose an establishment in Map &amp; Flags, then assign an inspector.
            </p>
          </div>

          <section className="inspection-calendar-sidebar-section inspection-calendar-mini" aria-labelledby="inspection-calendar-mini-label">
            <h3 id="inspection-calendar-mini-label"><span className="sr-only">Mini-calendar: </span>{monthLabel}</h3>
            <div className="inspection-calendar-grid inspection-calendar-mini-weekdays" aria-hidden="true">
              {WEEKDAYS.map((day) => <span key={day}>{day.charAt(0)}</span>)}
            </div>
            <MonthDates {...sharedDateProps} compact />
          </section>

          <section className="inspection-calendar-sidebar-section inspection-calendar-totals" aria-label={`Monthly ${deadlines ? "deadlines" : "activity"} for ${monthLabel}`}>
            <h3>{deadlines ? "Monthly deadlines" : "Monthly activity"}</h3>
            <dl>
              <div>
                <dt>{deadlines ? "Recorded deadlines" : "Lifecycle events"}</dt>
                <dd>{hasCounts ? deadlines ? monthlyDeadlines : monthlyEvents : "—"}</dd>
              </div>
              <div>
                <dt>{deadlines ? "Days with deadlines" : "Active days"}</dt>
                <dd>{hasCounts ? dayCounts.size : "—"}</dd>
              </div>
            </dl>
            <p>{deadlines ? "Submitted and Verified remain on their recorded deadline date until that deadline is replaced." : "An inspection can have multiple events. UTC recording dates."}</p>
          </section>

          <section className="inspection-calendar-sidebar-section inspection-calendar-legend" aria-labelledby="inspection-calendar-legend-label">
            <h3 id="inspection-calendar-legend-label">{deadlines ? "Deadline" : "Activity"} legend</h3>
            <ul>
              <li><span className="inspection-calendar-legend-marker is-activity" aria-hidden="true" />{deadlines ? "Recorded deadline" : "Recorded activity"}</li>
              <li><span className="inspection-calendar-legend-marker is-today" aria-hidden="true" />Today</li>
              <li><span className="inspection-calendar-legend-marker is-selected" aria-hidden="true" />Selected date</li>
            </ul>
          </section>
        </aside>

        <div className="inspection-calendar-main">
        <section className="inspection-calendar-card inspection-calendar-panel" aria-label="Month calendar">
          <div className="inspection-calendar-toolbar">
            <div className="inspection-calendar-month">
              <div className="inspection-calendar-month-heading">
                <h2 id="inspection-calendar-month-label">{monthLabel}</h2>
                <p className="inspection-calendar-toolbar-context" role="status">
                  {deadlines ? loading ? "Loading latest assignment pages…" : error ? "Deadline counts unavailable" : "Latest recorded assignments · Manila deadline dates" : loading
                    ? monthData ? "Loading selected-day activity…" : "Loading calendar activity…"
                    : error ? "Activity unavailable" : "Recorded inspection activity · Month view"}
                </p>
              </div>
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
                onClick={refreshCalendar}
                disabled={loading}
                aria-label={deadlines ? "Refresh assignment deadlines" : "Refresh inspection activity"}
              >
                <Icon.Refresh />
                Refresh
              </button>
            </div>
          </div>

          {error && (
            <div className="inspection-calendar-error" role="alert">
              <p className="inspection-calendar-state is-error">{error}</p>
              <button className="ghost-btn" type="button" onClick={refreshCalendar}>Retry</button>
            </div>
          )}

          <div className="inspection-calendar-month-scroll">
            <div className="inspection-calendar-month-view">
              <div className="inspection-calendar-grid inspection-calendar-weekdays" aria-hidden="true">
                {WEEKDAYS.map((day) => <span key={day}>{day}</span>)}
              </div>
              <MonthDates {...sharedDateProps} />
            </div>
          </div>

          <div className="inspection-calendar-footer">
            <p className="inspection-calendar-key">
              {deadlines ? error ? "Deadline counts are unavailable. Retry the paginated load." : !deadlineReady ? "Loading deadlines; no final counts are shown." : "Select a date to review its latest recorded assignments below." : error ? "Activity counts are unavailable. Try loading the calendar again."
                : monthData && monthlyEvents === 0 ? "No recorded events this month. Select a date to review its history."
                : "Select a date to review its recorded activity below."}
              <span className="inspection-calendar-scroll-hint"> Scroll sideways to see all weekdays if needed.</span>
            </p>
            <a className="inspection-calendar-detail-link" href={deadlines ? "#inspection-calendar-selected-deadlines" : "#inspection-calendar-selected-activity"}>
              View selected-day {deadlines ? "assignments" : "activity"} <span aria-hidden="true">↓</span>
            </a>
          </div>
        </section>
        </div>
      </div>

        {/* ── Selected-date panel ────────────────────────────────────────── */}
        {deadlines ? <section
          id="inspection-calendar-selected-deadlines" className="inspection-calendar-card inspection-calendar-activities inspection-calendar-selected-full"
          aria-labelledby="inspection-calendar-deadline-selected-label" aria-busy={loading} tabIndex={-1}
        >
          {deadlineReady ? <DeadlineAssignments key={selectedDate} date={selectedDate} reports={selectedAssignments} /> : <>
            <h2 id="inspection-calendar-deadline-selected-label">{formatLongDate(selectedDate)}</h2>
            <p className={`inspection-calendar-state${error ? " is-error" : ""}`} role="status">{error || "Loading latest recorded assignments…"} {progress} No final deadline count is available.</p>
          </>}
        </section> : <section
          id="inspection-calendar-selected-activity"
          className="inspection-calendar-card inspection-calendar-activities inspection-calendar-selected-full"
          aria-labelledby="inspection-calendar-selected-label"
          aria-busy={loading}
          tabIndex={-1}
        >
          <header className="inspection-calendar-activities-header">
            <div className="inspection-calendar-activities-heading">
              <p className="inspection-calendar-eyebrow">Selected-day activity</p>
              <h2 id="inspection-calendar-selected-label">{formatLongDate(selectedDate)}</h2>
              <p className="inspection-calendar-activities-description">Recorded lifecycle events, in chronological order. UTC recording dates and times.</p>
            </div>
            {dayReady && <span className="inspection-calendar-count">{eventCountLabel(activities.length)}</span>}
          </header>

          {statusSummary.length > 0 && (
            <dl className="inspection-calendar-summary">
              {statusSummary.map(({ eventType, label, status, count }) => {
                const tone = STATUS_TONE[status];
                return (
                  <div className="inspection-calendar-summary-item" key={eventType}>
                    <dt>
                      <span
                        className="inspection-calendar-summary-dot"
                        style={{ background: tone.rail }}
                        aria-hidden="true"
                      />
                       {label}
                    </dt>
                    <dd>{count}</dd>
                  </div>
                );
              })}
            </dl>
          )}

          {loading ? (
            <p className="inspection-calendar-state" role="status">Loading activity for this date…</p>
          ) : error ? (
            <p className="inspection-calendar-state is-error">Activity for this date could not be loaded. Use Retry above to try again.</p>
          ) : activities.length ? (
            <ol className="inspection-calendar-list">
              {activities.map((activity) => {
                const meta = EVENT_TYPES[activity.eventType] || { label: activity.eventType || "Recorded event" };
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
                          <time dateTime={toIsoDateTime(activity.eventTimestamp)}>{clock} UTC</time>
                        )}
                      </div>

                      <p className="inspection-calendar-activity-name">
                        {activity.detectedName || (activity.targetLogID != null ? `Location #${activity.targetLogID}` : "Establishment name unavailable")}
                      </p>

                      {details && (
                        <p className="inspection-calendar-activity-meta">{details}</p>
                      )}

                      <p className="inspection-calendar-activity-meta">
                        {[
                          activity.eventID != null && `Event #${activity.eventID}`,
                          activity.targetLogID != null && `Location #${activity.targetLogID}`,
                          activity.reportID != null && `Report #${activity.reportID}`,
                          activity.cycleID != null && `Cycle #${activity.cycleID}`,
                        ].filter(Boolean).join(" · ")}
                      </p>

                      {activity.remarks && (
                        <p className="inspection-calendar-activity-remark">
                          {activity.remarks}
                        </p>
                      )}

                      <div className="inspection-calendar-activity-foot">
                        {activity.flagColorAtEvent && (
                          <span className="inspection-calendar-activity-meta">Flag at event: {activity.flagColorAtEvent}</span>
                        )}
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
                            Search Dispatch for location #{activity.targetLogID}
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
              <div>
                <p className="inspection-calendar-empty-title">No activity recorded on this date</p>
                <p className="inspection-calendar-empty-text">Select another day to review its inspection history.</p>
              </div>
              {latestActiveDate && (
                <button className="ghost-btn" type="button" onClick={() => setSelectedDate(latestActiveDate)}>
                  View latest activity this month
                </button>
              )}
            </div>
          )}
        </section>}
      </div>
    </section>
  );
}
