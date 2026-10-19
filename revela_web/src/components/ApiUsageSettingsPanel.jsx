import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Swal from "sweetalert2";
import {
  getApiUsageReportRequest,
  getApiQuotaSettingsRequest,
  getDetectionQuotaRequest,
  updateApiQuotaSettingsRequest,
  resetApiQuotaSettingsRequest,
  getTestModeSettingsRequest,
  updateTestModeSettingsRequest,
  resetTestModeSettingsRequest,
  purgeTestFixturesRequest,
} from "../services/api";
import {
  buildUsageWarnings,
  describeLimitSource,
  detectionMethodKey,
  detectionScanSummary,
  dirtySettingKeys,
  formatNumber,
  isCustomLimit,
  limitState,
  methodLabel,
  mergeSettingsDraft,
  summarizeUsage,
} from "./apiUsageView";

/**
 * "API Usage & Limits", opened from More Actions on Map & Flags.
 *
 * Written for a BPLO administrator, so the default view answers four questions
 * and nothing else: how much has been used today, how much this month, how much
 * of each API method's monthly allowance is left, and how many Run Detection
 * scans remain. Warnings appear on their own whenever a budget is nearly or
 * fully spent.
 *
 * Super Admins navigate between application limits, testing/fixtures, and
 * technical details. Drafts live above the section content so navigation and
 * read-only refreshes preserve outstanding edits. Restricted settings payloads
 * are requested only for Super Admins.
 *
 * Design notes, matching the rest of the app:
 *  - Surfaces (`saas-card`, `frosted-glass`, `primary-btn`, `ghost-btn`,
 *    `badge`) and every colour come from `src/styles/global.css` / `MapPage.css`;
 *    nothing here introduces a new token, so dark mode works unchanged.
 *  - Modal styles are scoped to the API usage modal, with compact navigation
 *    on narrow screens.
 *  - Wording, thresholds, and arithmetic live in `apiUsageView.js` so they can
 *    be unit tested without a DOM.
 *
 * This component is read-and-edit only. Quota enforcement lives in the
 * backend reservation path (`api/utils/places_quota.py`) and is untouched here.
 */

const BILLING_NOTE =
  "REVELA counts these Google requests in its own internal ledger. The figures "
  + "below are application limits, not Google Cloud billing.";

const SECTIONS = [
  { id: "overview", title: "Usage overview", description: "Shared usage and remaining allowances", navHint: "Requests, scans, and warnings" },
  { id: "limits", title: "Application limits", description: "Manage REVELA's request budgets", navHint: "Budgets and workflow allocations" },
  { id: "testing", title: "Testing & fixtures", description: "Configure Test Mode and cached responses", navHint: "Test scope and fixture management" },
  { id: "technical", title: "Technical details", description: "Inspect Cloud quotas, pacing, and the selected endpoint", navHint: "Cloud quotas and request pacing" },
];

const LIMIT_META = {
  cloud: {
    label: "Google Cloud quota",
    color: "var(--color-blue, #3b82f6)",
    bg: "rgba(59, 130, 246, 0.10)",
    border: "rgba(59, 130, 246, 0.30)",
    hint: "Limit Google imposes. Not editable here.",
  },
  app: {
    label: "REVELA application cap",
    color: "var(--color-primary)",
    bg: "var(--color-primary-light)",
    border: "rgba(86, 171, 47, 0.30)",
    hint: "REVELA's own budget. Editable, but never above the Cloud quota.",
  },
  pacing: {
    label: "Request pacing",
    color: "var(--color-muted)",
    bg: "rgba(100, 116, 139, 0.10)",
    border: "rgba(100, 116, 139, 0.28)",
    hint: "REVELA's client-side delay. Unrelated to either limit.",
  },
};

function Section({ title, description, action, children }) {
  return (
    <section className="api-usage-section">
      <div className="api-usage-section-header">
        <div>
          <h4>{title}</h4>
          {description && <p>{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function LimitBlock({ kind, rows, note }) {
  const meta = LIMIT_META[kind];
  return (
    <div
      style={{
        background: meta.bg,
        border: `1px solid ${meta.border}`,
        borderRadius: 8,
        padding: "10px 12px",
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: 10.5,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.03em",
          color: meta.color,
          marginBottom: 6,
        }}
      >
        {meta.label}
      </div>
      {rows.map((row) => (
        <div
          key={row.label}
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 10,
            fontSize: 12,
            color: "var(--color-ink)",
            lineHeight: 1.7,
          }}
        >
          <span style={{ color: "var(--color-muted)", minWidth: 0 }}>{row.label}</span>
          <span style={{ fontWeight: 700, whiteSpace: "nowrap" }}>{row.value}</span>
        </div>
      ))}
      {note && (
        <div
          style={{
            marginTop: 6,
            fontSize: 10.5,
            color: "var(--color-muted)",
            lineHeight: 1.45,
          }}
        >
          {note}
        </div>
      )}
    </div>
  );
}

function Meter({ used, cap }) {
  const { percent, level } = limitState(used, cap);
  const color = level === "full"
    ? "var(--color-danger)"
    : level === "near"
      ? "var(--color-warning)"
      : level === "off"
        ? "var(--color-border)"
        : "var(--color-primary)";
  return (
    <div className="api-usage-meter">
      <div
        style={{
          width: `${percent}%`,
          height: "100%",
          background: color,
          transition: "width var(--duration-normal, 0.2s)",
        }}
      />
    </div>
  );
}

function SegmentedToggle({ label, value, options, onChange, disabled }) {
  return (
    <div
      role="group"
      aria-label={label}
      style={{
        display: "inline-flex",
        background: "var(--color-hover)",
        borderRadius: 12,
        padding: 4,
        border: "1px solid var(--color-border-soft)",
      }}
    >
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={String(opt.value)}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            style={{
              padding: "7px 14px",
              borderRadius: 8,
              border: "none",
              cursor: disabled ? "not-allowed" : "pointer",
              fontSize: 12.5,
              fontFamily: "inherit",
              fontWeight: active ? 700 : 500,
              background: active ? "var(--color-primary)" : "transparent",
              color: active ? "#fff" : "var(--color-muted)",
              transition: "all var(--duration-fast, 0.15s)",
              boxShadow: active ? "0 2px 8px rgba(86, 171, 47, 0.3)" : "none",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

const inputStyle = {
  width: "100%",
  padding: "8px 11px",
  borderRadius: 8,
  border: "1px solid var(--color-border)",
  background: "var(--color-input-bg)",
  color: "var(--color-ink)",
  fontSize: 13,
  fontFamily: "inherit",
  boxSizing: "border-box",
};

const labelStyle = {
  display: "block",
  fontSize: 11,
  fontWeight: 700,
  color: "var(--color-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.03em",
  marginBottom: 5,
};

const hintStyle = {
  fontSize: 10.5,
  color: "var(--color-muted)",
  marginTop: 5,
  lineHeight: 1.45,
};

function draftFromFields(fields = {}) {
  return Object.fromEntries(
    Object.entries(fields).map(([key, field]) => [key, field.value]),
  );
}

function editableTestModeDraft(config = {}) {
  return Object.fromEntries(
    Object.entries(config).filter(
      ([key]) => key !== "test_mode.fixture_storage_approved",
    ),
  );
}

export default function ApiUsageSettingsPanel({
  token,
  isAdmin,
  isSuperAdmin = false,
  onOpen,
  onUsageChanged,
}) {
  const [open, setOpen] = useState(false);
  const [activeSection, setActiveSection] = useState("overview");
  const [usage, setUsage] = useState(null);
  const [detectionQuota, setDetectionQuota] = useState(null);
  const [quotaSettings, setQuotaSettings] = useState({ data: null, draft: {} });
  const [testSettings, setTestSettings] = useState({ data: null, draft: {} });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef(null);
  const contentRef = useRef(null);
  const triggerRef = useRef(null);
  const quota = quotaSettings.data;
  const draft = quotaSettings.draft;
  const testMode = testSettings.data;
  const testDraft = testSettings.draft;
  const setDraft = (updater) => setQuotaSettings((current) => ({
    ...current, draft: updater(current.draft),
  }));
  const setTestDraft = (updater) => setTestSettings((current) => ({
    ...current, draft: updater(current.draft),
  }));

  const load = useCallback(async () => {
    if (!token || !isAdmin) return;
    setLoading(true);
    setError("");
    try {
      const [usageData, detectionData, quotaData, testData] = await Promise.all([
        getApiUsageReportRequest(token),
        getDetectionQuotaRequest(token),
        // Editing sections are Super Admin only, so their two payloads are never
        // requested — and never rendered — for a plain administrator.
        ...(isSuperAdmin
          ? [getApiQuotaSettingsRequest(token), getTestModeSettingsRequest(token)]
          : []),
      ]);
      setUsage(usageData);
      setDetectionQuota(detectionData);
      if (quotaData) {
        setQuotaSettings((current) => ({
          data: quotaData,
          draft: mergeSettingsDraft(
            current.draft, draftFromFields(current.data?.fields), draftFromFields(quotaData.fields),
          ),
        }));
      }
      if (testData) {
        setTestSettings((current) => ({
          data: testData,
          draft: mergeSettingsDraft(
            current.draft, editableTestModeDraft(current.data?.config), editableTestModeDraft(testData.config),
          ),
        }));
      }
    } catch (err) {
      setError(err.message || "Could not load API usage settings.");
    } finally {
      setLoading(false);
    }
  }, [token, isAdmin, isSuperAdmin]);

  useEffect(() => {
    if (!open) return undefined;
    const dialog = dialogRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog?.querySelector('[aria-current="page"]')?.focus();
    const onKeyDown = (event) => {
      // Confirmation dialogs manage their own focus and Escape handling.
      if (!dialog || (!dialog.contains(document.activeElement) && document.activeElement !== document.body)) return;
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      }
      if (event.key !== "Tab") return;
      const focusable = [...dialog.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]')]
        .filter((element) => element.getClientRects().length > 0);
      const first = focusable[0];
      const last = focusable.at(-1);
      if (document.activeElement === document.body) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const trigger = triggerRef.current;
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      // The host closes More Actions on open; its summary remains focusable.
      const returnTarget = trigger?.closest("details")?.querySelector("summary") ?? trigger;
      returnTarget?.focus();
    };
  }, [open]);

  // Load only when the modal opens; the content is only needed while visible.
  const handleToggle = () => {
    if (!open) {
      setActiveSection("overview");
      void load();
      // Let the host collapse the surrounding menu the trigger lives in.
      onOpen?.();
    }
    setOpen(!open);
  };

  const methods = useMemo(() => usage?.methods ?? [], [usage]);
  const nearbyApiMode = usage?.run_detection?.nearby_api_mode;
  const activeMethodKey = detectionMethodKey(nearbyApiMode);
  const hasScanQuota = Number.isFinite(detectionQuota?.used_this_month)
    && Number.isFinite(detectionQuota?.monthly_limit)
    && Number.isFinite(detectionQuota?.remaining_this_month);
  const usageTotals = useMemo(() => summarizeUsage(methods), [methods]);
  const scans = useMemo(
    () => detectionScanSummary(detectionQuota),
    [detectionQuota],
  );
  const warnings = useMemo(
    () => buildUsageWarnings(methods, detectionQuota, nearbyApiMode),
    [methods, detectionQuota, nearbyApiMode],
  );

  const dirtyQuotaKeys = useMemo(() => {
    return dirtySettingKeys(draft, draftFromFields(quota?.fields));
  }, [draft, quota]);
  const dirtyTestKeys = useMemo(
    () => dirtySettingKeys(testDraft, editableTestModeDraft(testMode?.config)),
    [testDraft, testMode],
  );
  const selectedSection = SECTIONS.find((section) => section.id === (isSuperAdmin ? activeSection : "overview"));
  const sections = isSuperAdmin ? SECTIONS : SECTIONS.slice(0, 1);
  const changeSection = (id) => {
    setActiveSection(id);
    if (contentRef.current) contentRef.current.scrollTop = 0;
  };

  const handleSaveQuota = async () => {
    if (!quota?.fields) return;
    const payload = {};
    for (const key of dirtyQuotaKeys) {
      const field = quota.fields[key];
      if (field) payload[key] = Number(draft[key]);
    }
    if (Object.keys(payload).length === 0) return;
    setSaving(true);
    try {
      const result = await updateApiQuotaSettingsRequest(payload, token);
      setQuotaSettings({ data: result, draft: draftFromFields(result.fields) });
      Swal.fire({
        icon: "success",
        title: "Limits saved",
        text: `${result.saved} limit(s) updated. They apply to the next request without a redeploy.`,
        confirmButtonColor: "var(--color-primary)",
      });
      await load();
      // Keep the Maps page header pills and Run Detection button in step with
      // the caps that were just changed.
      onUsageChanged?.();
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Limits not saved",
        text: err.message,
        confirmButtonColor: "#ef4444",
      });
    } finally {
      setSaving(false);
    }
  };

  // Explicit and confirmed on purpose: this discards stored custom values.
  // Nothing is ever reset implicitly by opening or refreshing the modal.
  const handleResetQuota = async () => {
    const confirm = await Swal.fire({
      icon: "question",
      title: "Restore application defaults?",
      html: "Custom limits will be discarded and the application defaults will "
        + "apply again. This does <b>not</b> reset usage counters or grant "
        + "extra quota.",
      showCancelButton: true,
      confirmButtonColor: "var(--color-primary)",
      cancelButtonColor: "var(--color-muted)",
    });
    if (!confirm.isConfirmed) return;
    try {
      const result = await resetApiQuotaSettingsRequest(token);
      setQuotaSettings({ data: result, draft: draftFromFields(result.fields) });
      await load();
      onUsageChanged?.();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSaveTestMode = async (patch) => {
    setSaving(true);
    try {
      const result = await updateTestModeSettingsRequest(patch, token);
      setTestSettings((current) => ({
        data: { ...current.data, config: result.config },
        draft: editableTestModeDraft(result.config),
      }));
      return true;
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Test Mode not saved",
        text: err.message,
        confirmButtonColor: "#ef4444",
      });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handlePurgeFixtures = async (olderThanDays) => {
    const retention = olderThanDays ?? testMode?.fixtures?.retention_days;
    const confirm = await Swal.fire({
      icon: "warning",
      title: "Delete cached payloads?",
      html: olderThanDays === 0
        ? "This deletes <b>every</b> stored fixture. Usage counters are not affected."
        : `This deletes fixtures older than ${retention != null ? `${retention} day(s)` : "the configured retention window"}. Usage counters are not affected.`,
      showCancelButton: true,
      confirmButtonColor: "#ef4444",
      cancelButtonColor: "var(--color-muted)",
    });
    if (!confirm.isConfirmed) return;
    try {
      const result = await purgeTestFixturesRequest(token, olderThanDays);
      setTestSettings((current) => ({ ...current, data: { ...current.data, fixtures: result.fixtures } }));
      Swal.fire({
        icon: "success",
        title: "Fixtures cleared",
        text: `${result.removed} stored response(s) deleted.`,
        confirmButtonColor: "var(--color-primary)",
      });
    } catch (err) {
      setError(err.message);
    }
  };

  if (!isAdmin) return null;

  return (
    <>
      {/* Trigger lives inside MapPage's More Actions dropdown, so it reuses the
          same compact menu-item styling as Reconcile / Snap Pins / Re-verify
          instead of a separate full-width banner button. */}
      <button
        ref={triggerRef}
        type="button"
        onClick={handleToggle}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="ghost-btn map-more-actions-item"
      >
        API Usage &amp; Limits
      </button>

      {open && createPortal(
        <div
          className="api-usage-modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <section
            ref={dialogRef}
            className="api-usage-modal saas-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="api-usage-modal-title"
          >
            <header className="api-usage-modal-header">
              <div>
                <h2 id="api-usage-modal-title">API Usage &amp; Limits</h2>
                <p>
                  Counts are shared across all administrator accounts.
                </p>
              </div>
              <div className="api-usage-header-actions">
                <span className="api-usage-role-badge">{isSuperAdmin ? "Super Admin" : "Admin · Read only"}</span>
                <button
                  type="button"
                  className="ghost-btn"
                  onClick={() => setOpen(false)}
                  aria-label="Close API usage and limits"
                >
                  Close
                </button>
              </div>
            </header>
            <div className="api-usage-modal-body">
              <aside className="api-usage-sidebar">
                <p className="api-usage-nav-label">{isSuperAdmin ? "Monitor & manage" : "Monitoring"}</p>
                <nav className="api-usage-nav" aria-label="API usage sections">
                  {sections.map((section, index) => {
                    const edits = section.id === "limits" ? dirtyQuotaKeys.length
                      : section.id === "testing" ? dirtyTestKeys.length : 0;
                    return (
                      <button
                        key={section.id}
                        type="button"
                        className="api-usage-nav-item"
                        aria-current={section.id === selectedSection.id ? "page" : undefined}
                        aria-controls="api-usage-section"
                        onClick={() => changeSection(section.id)}
                      >
                        <span className="api-usage-nav-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                        <span className="api-usage-nav-copy">
                          <span>{section.title}</span>
                          <small>{edits ? `${edits} unsaved ${edits === 1 ? "change" : "changes"}` : section.navHint}</small>
                        </span>
                        {edits > 0 && <span className="api-usage-draft-dot" aria-hidden="true" />}
                      </button>
                    );
                  })}
                </nav>
                <div className="api-usage-sidebar-note">
                  <strong>{isSuperAdmin ? "Shared settings" : "Read-only access"}</strong>
                  <p>{isSuperAdmin
                    ? "Limits apply across administrator accounts. Section changes keep your unsaved drafts."
                    : "Application limits, testing, and technical settings are available to Super Admins."}</p>
                  {testMode?.config?.["test_mode.enabled"] && isSuperAdmin && (
                    <span className="api-usage-active-badge">Test Mode active</span>
                  )}
                </div>
              </aside>
              <div className="api-usage-modal-content" ref={contentRef}>
                <header className="api-usage-content-header">
                  <div>
                    <h3 id="api-usage-section-heading">{selectedSection.title}</h3>
                    <p>{selectedSection.description}</p>
                  </div>
                  <button type="button" className="ghost-btn" onClick={() => void load()} disabled={loading || saving}>
                    {loading ? "Refreshing…" : "Refresh"}
                  </button>
                </header>
                <div className="api-usage-toolbar" role="status">
                  <span>{usage?.generated_at ? `Report updated ${usage.generated_at}` : loading ? "Loading current usage…" : "Report not available"}</span>
                  {isSuperAdmin && dirtyQuotaKeys.length + dirtyTestKeys.length > 0 && (
                    <span className="api-usage-draft-status">Unsaved changes · Drafts kept when switching sections</span>
                  )}
                </div>
              {error && (
                <div role="alert" className="api-usage-error">
                  {error}
                </div>
              )}
              <section id="api-usage-section" className="api-usage-section-content" aria-labelledby="api-usage-section-heading" aria-busy={loading}>
              {selectedSection.id === "overview" && (<>
              <p className="api-usage-note">{BILLING_NOTE}</p>

              {/* ── Headline figures ───────────────────────────────────── */}
              <div className="api-usage-overview">
                <div className="api-usage-overview-card">
                  <span>Requests used today</span>
                  <strong>
                    {usage ? formatNumber(usageTotals.usedToday) : loading ? "…" : "—"}
                  </strong>
                  <small>Across all lookup types</small>
                </div>
                <div className="api-usage-overview-card">
                  <span>Requests used this month</span>
                  <strong>
                    {usage ? formatNumber(usageTotals.usedMonth) : loading ? "…" : "—"}
                  </strong>
                  <small>Across all lookup types</small>
                </div>
                <div className="api-usage-overview-card">
                  <span>Run Detection scans left</span>
                  <strong>{hasScanQuota ? formatNumber(scans.remaining) : loading ? "…" : "—"}</strong>
                  <small>
                    {hasScanQuota
                      ? `${formatNumber(scans.used)} of ${formatNumber(scans.limit)} used this month`
                      : "Monthly scan allowance"}
                  </small>
                  {detectionQuota?.resets_on && <small>Resets {detectionQuota.resets_on}</small>}
                </div>
              </div>

              {usage?.run_detection?.preflight && (
                <Section title="Can the next scan finish?" description="Request budgets are shared across accounts, separately for each API method. Completed monthly scans and API requests are independent counters.">
                  <div className="api-usage-methods">
                    {Object.entries(usage.run_detection.preflight).map(([mode, plan]) => (
                      <div key={mode} className="api-usage-method-card">
                        <strong>{mode === "quick" ? "Quick Discovery" : "Full Coverage"}</strong>
                        <p>{plan.saved_points} of {plan.total_points} centers saved. Remaining request estimate: <b>{formatNumber(plan.minimum_requests)}–{formatNumber(plan.maximum_requests)}</b>.</p>
                        <p>Execution cap: <b>{formatNumber(plan.work_slice_requests)} requests / {plan.work_slice_seconds}s</b> ({plan.request_cap_source}). Daily allowance remaining: {formatNumber(plan.daily_remaining)}; minimum to start: {formatNumber(plan.required_remaining_allowance)}. This execution is bounded to {formatNumber(plan.planned_requests)} paid requests.</p>
                        <p>{plan.can_start ? (plan.budget_covers_complete_run ? "Request allowance covers the remaining scope; time limits can still pause it." : "Allowance covers a resumable slice only.") : plan.blockers.join(" ")}</p>
                        {mode === "full" && <p>A fully bounded dense cell may need {formatNumber(plan.maximum_requests_per_point)} requests. A smaller execution cap can repeatedly pause inside that cell.</p>}
                        <small>Includes applicable pagination, adaptive queries and retries. Partial scans consume API requests even when no monthly scan is deducted.</small>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {/* ── Warnings ───────────────────────────────────────────── */}
              {warnings.length > 0 && (
                <div className="api-usage-warnings" role="status">
                  {warnings.map((warning) => (
                    <div
                      key={warning.id}
                      className={`api-usage-warning api-usage-warning--${warning.level}`}
                    >
                      {warning.text}
                    </div>
                  ))}
                </div>
              )}

              {/* ── Monthly allowance per API method ───────────────────── */}
              <Section
                title="Monthly allowance"
                description="Each type has its own allowance, so what is left for one type is never used by another."
              >
                {!usage ? (
                  <p className="api-usage-empty" role="status">
                    {loading ? "Loading usage…" : "Usage is unavailable. Refresh to try again."}
                  </p>
                ) : (
                  <div className="api-usage-methods">
                    {methods.map((method) => {
                      const cap = method.revela_app_cap ?? {};
                      const monthly = limitState(
                        cap.used_month, cap.monthly_cap, cap.monthly_quota_exceeded,
                      );
                      const daily = limitState(
                        cap.used_today, cap.daily_cap, cap.daily_quota_exceeded,
                      );
                      const reached = monthly.level === "full" || daily.level === "full";
                      const near = monthly.level === "near" || daily.level === "near";
                      return (
                        <div key={method.method} className="api-usage-method-card">
                          <div className="api-usage-method-header">
                            <strong>{methodLabel(method, nearbyApiMode)}</strong>
                            {method.method === activeMethodKey && <span className="api-usage-active-badge">Selected endpoint</span>}
                            {cap.disabled && <span className="badge badge--black">Not in use</span>}
                            {reached && <span className="badge badge--red">Limit reached</span>}
                            {!reached && near && <span className="badge badge--gold">Near limit</span>}
                          </div>

                          <div className="api-usage-method-usage">
                            <span>This month</span>
                            <strong>
                              {formatNumber(cap.used_month)} / {formatNumber(cap.monthly_cap)}
                            </strong>
                          </div>
                          <Meter used={cap.used_month} cap={cap.monthly_cap} />

                          <div className="api-usage-method-foot">
                            <span>
                              {monthly.level === "off"
                                ? "No monthly allowance set"
                                : `${formatNumber(cap.monthly_remaining ?? monthly.remaining)} left this month`}
                            </span>
                            <span>
                              Today {formatNumber(cap.used_today)} / {formatNumber(cap.daily_cap)}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </Section>
              {!isSuperAdmin && <p className="api-usage-access-note">You can monitor shared usage here. A Super Admin manages application limits and Test Mode.</p>}
              </>)}

              {/* Settings stay in parent state when section content unmounts. */}
              {isSuperAdmin && selectedSection.id !== "overview" && !(selectedSection.id === "limits" ? quota : selectedSection.id === "testing" ? testMode : usage) && (
                <p className="api-usage-empty" role="status">{loading ? "Loading settings…" : "Settings are unavailable. Refresh to try again."}</p>
              )}
              {isSuperAdmin && selectedSection.id === "limits" && quota && (<>
                  <Section
                    title="Application limits"
                    description="These are REVELA's own request budgets. Each one starts as the application default; a custom value is kept until it is explicitly changed or restored. Google Cloud limits cannot be changed here."
                    action={
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <button
                          type="button"
                          className="primary-btn"
                          onClick={handleSaveQuota}
                          disabled={loading || saving || dirtyQuotaKeys.length === 0}
                          style={{ fontSize: 12, padding: "7px 14px" }}
                        >
                          {saving
                            ? "Saving…"
                            : `Save${dirtyQuotaKeys.length ? ` (${dirtyQuotaKeys.length})` : ""}`}
                        </button>
                        <button
                          type="button"
                          className="ghost-btn"
                          onClick={handleResetQuota}
                          disabled={loading || saving}
                          style={{ fontSize: 12, padding: "7px 14px" }}
                        >
                          Restore defaults
                        </button>
                      </div>
                    }
                  >
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns:
                          "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
                        gap: 12,
                      }}
                    >
                      {Object.entries(quota?.fields ?? {}).map(([key, field]) => {
                        const max =
                          field.cloud_ceiling != null
                            ? Math.min(field.maximum ?? Infinity, field.cloud_ceiling)
                            : field.maximum;
                        const overCeiling =
                          field.cloud_ceiling != null && Number(draft[key]) > field.cloud_ceiling;
                        const custom = isCustomLimit(field);
                        return (
                          <div key={key}>
                            <label style={labelStyle} htmlFor={`quota-${key}`}>
                              {field.label}
                            </label>
                            <input
                              id={`quota-${key}`}
                              type="number"
                              disabled={loading || saving}
                              step={field.kind === "float" ? "0.0001" : "1"}
                              min={field.minimum}
                              max={Number.isFinite(max) ? max : undefined}
                              value={draft[key] ?? field.value}
                              onChange={(e) =>
                                setDraft((prev) => ({ ...prev, [key]: e.target.value }))
                              }
                              style={{
                                ...inputStyle,
                                borderColor: overCeiling ? "var(--color-danger)" : undefined,
                              }}
                            />
                            <div
                              className={`api-usage-limit-source${
                                custom ? " api-usage-limit-source--custom" : ""
                              }`}
                            >
                              <strong>{describeLimitSource(field)}</strong>
                              <span>{field.help}</span>
                              {field.cloud_ceiling != null && (
                                <span>Enforced daily ceiling: {formatNumber(field.cloud_ceiling)}</span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </Section>

                  {/* ── Workflow allocations ─────────────────────────────── */}
                  {usage?.text_search_workflows && (
                    <Section
                      title="Business Lookup workflow limits"
                      description="Registry import, Snap Pins, and Re-verify share one Business Lookup daily limit. Their allocations must add up to no more than it."
                    >
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns:
                            "repeat(auto-fit, minmax(min(100%, 180px), 1fr))",
                          gap: 10,
                        }}
                      >
                        {Object.entries(usage.text_search_workflows).map(([key, wf]) => (
                          <div
                            key={key}
                            className="saas-card"
                            style={{ padding: "12px 14px", borderRadius: 10 }}
                          >
                            <div style={labelStyle}>{wf.label}</div>
                            <div style={{ fontSize: 19, fontWeight: 800, color: "var(--color-ink)" }}>
                              {formatNumber(wf.used_today)} / {formatNumber(wf.daily_cap)}
                            </div>
                            <Meter used={wf.used_today} cap={wf.daily_cap} />
                          </div>
                        ))}
                      </div>
                    </Section>
                  )}
              </>)}

              {isSuperAdmin && selectedSection.id === "testing" && testMode && (<>
                  <Section
                    title="Test Mode"
                    description="Bounds a detection run to a small area and request cap. Real Google calls remain quota-counted. Fixture replay is separately gated because it stores Google-derived content."
                  >
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 16,
                        flexWrap: "wrap",
                        marginBottom: 14,
                      }}
                    >
                      <span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--color-ink)" }}>
                        Enable Test Mode for Run Detection
                      </span>
                      <SegmentedToggle
                        label="Enable Test Mode for Run Detection"
                        value={Boolean(testDraft["test_mode.enabled"])}
                        options={[
                          { label: "On", value: true },
                          { label: "Off", value: false },
                        ]}
                        disabled={loading || saving}
                        onChange={(value) =>
                          setTestDraft((prev) => ({ ...prev, "test_mode.enabled": value }))
                        }
                      />
                    </div>

                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 16,
                        flexWrap: "wrap",
                        marginBottom: 14,
                        padding: 12,
                        border: "1px solid var(--color-border-soft)",
                        borderRadius: 8,
                      }}
                    >
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-ink)" }}>
                          Store minimal Google response fixtures
                        </div>
                        <div style={hintStyle}>
                          {testMode?.config?.["test_mode.fixture_storage_approved"]
                            ? "Server policy approval is enabled. Retention follows the saved fixture retention setting."
                            : "Disabled until the server explicitly approves Google Places fixture storage."}
                        </div>
                      </div>
                      <SegmentedToggle
                        label="Store minimal Google response fixtures"
                        value={Boolean(testDraft["test_mode.fixture_storage_enabled"])}
                        options={[
                          { label: "On", value: true },
                          { label: "Off", value: false },
                        ]}
                        disabled={
                          saving
                          || loading
                          || !testMode?.config?.["test_mode.fixture_storage_approved"]
                        }
                        onChange={(value) =>
                          setTestDraft((prev) => ({
                            ...prev,
                            "test_mode.fixture_storage_enabled": value,
                          }))
                        }
                      />
                    </div>
                    {!testMode?.config?.["test_mode.fixture_storage_enabled"] && (
                      <div className="api-usage-inline-warning">
                        The saved configuration has fixture replay off. Test Mode may still make live Google
                        requests; those use normal quota reservations and may incur
                        charges.
                      </div>
                    )}

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns:
                          "repeat(auto-fit, minmax(min(100%, 210px), 1fr))",
                        gap: 12,
                      }}
                    >
                      {[
                        {
                          key: "test_mode.max_grid_points",
                          label: "Grid points per run",
                          hint: "Geographic scope: how many cells the run may visit.",
                        },
                        {
                          key: "test_mode.radius_m",
                          label: "Search radius (m)",
                          hint: "Smaller radius, narrower sweep.",
                        },
                        {
                          key: "test_mode.max_requests",
                          label: "Requests per run",
                          hint: "Hard ceiling for a Test Mode run.",
                        },
                        {
                          key: "test_mode.grid_step_degrees",
                          label: "Grid step (degrees)",
                          hint: "Coverage is not monotonic in this value — change it only alongside the grid coverage test.",
                        },
                        {
                          key: "test_mode.fixture_ttl_days",
                          label: "Fixture retention (days)",
                          hint: "Cached payloads older than this can be purged.",
                        },
                      ].map((field) => (
                        <div key={field.key}>
                          <label style={labelStyle} htmlFor={field.key}>
                            {field.label}
                          </label>
                          <input
                            id={field.key}
                            type="number"
                            disabled={loading || saving}
                            step={field.key === "test_mode.grid_step_degrees" ? "0.0001" : "1"}
                            value={testDraft[field.key] ?? ""}
                            onChange={(e) =>
                              setTestDraft((prev) => ({ ...prev, [field.key]: e.target.value }))
                            }
                            style={inputStyle}
                          />
                          <div style={hintStyle}>{field.hint}</div>
                        </div>
                      ))}

                      <div>
                        <label style={labelStyle} htmlFor="test_mode.fixture_policy">
                          Cached response policy
                        </label>
                        <select
                          id="test_mode.fixture_policy"
                          value={testDraft["test_mode.fixture_policy"] ?? ""}
                          disabled={
                            saving
                            || loading
                            || !testDraft["test_mode.fixture_storage_enabled"]
                          }
                          onChange={(e) =>
                            setTestDraft((prev) => ({
                              ...prev,
                              "test_mode.fixture_policy": e.target.value,
                            }))
                          }
                          style={{ ...inputStyle, appearance: "auto" }}
                        >
                          <option value="cache_then_live">
                            Replay if stored, else call Google
                          </option>
                          <option value="cache_only">
                            Replay only — never call Google
                          </option>
                        </select>
                        <div style={hintStyle}>
                          "Replay only" fails loudly when a request has no stored
                          fixture instead of spending quota.
                        </div>
                      </div>
                    </div>

                    <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="primary-btn"
                        disabled={loading || saving || dirtyTestKeys.length === 0}
                        onClick={async () => {
                          const patch = {};
                          for (const key of dirtyTestKeys) {
                            patch[key] = typeof testMode.config[key] === "number"
                              ? Number(testDraft[key])
                              : testDraft[key];
                          }
                          if (await handleSaveTestMode(patch)) await load();
                        }}
                        style={{ fontSize: 12, padding: "7px 14px" }}
                      >
                        {saving ? "Saving…" : "Save Test Mode"}
                      </button>
                      <button
                        type="button"
                        className="ghost-btn"
                        disabled={loading || saving}
                        onClick={async () => {
                          try {
                            const result = await resetTestModeSettingsRequest(token);
                            setTestSettings((current) => ({
                              data: { ...current.data, config: result.config },
                              draft: editableTestModeDraft(result.config),
                            }));
                          } catch (err) {
                            setError(err.message);
                          }
                        }}
                        style={{ fontSize: 12, padding: "7px 14px" }}
                      >
                        Restore defaults
                      </button>
                    </div>
                  </Section>

                  {/* ── Fixture management ───────────────────────────────── */}
                  <Section
                    title="Fixture management"
                    description="Cached Google payloads used for Test Mode replay. A replay issues no Google request and does not change usage counters."
                  >
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns:
                          "repeat(auto-fit, minmax(min(100%, 150px), 1fr))",
                        gap: 10,
                        marginBottom: 12,
                      }}
                    >
                      <div>
                        <div style={labelStyle}>Stored fixtures</div>
                        <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-ink)" }}>
                          {testMode.fixtures?.available !== false && testMode.fixtures?.total != null ? formatNumber(testMode.fixtures.total) : "—"}
                        </div>
                      </div>
                      <div>
                        <div style={labelStyle}>Replays served</div>
                        <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-ink)" }}>
                          {testMode.fixtures?.replay_hits != null ? formatNumber(testMode.fixtures.replay_hits) : "—"}
                        </div>
                      </div>
                      <div>
                        <div style={labelStyle}>Retention (days)</div>
                        <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-primary)" }}>
                          {testMode.fixtures?.retention_days != null ? formatNumber(testMode.fixtures.retention_days) : "—"}
                        </div>
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="ghost-btn"
                        disabled={loading || saving || testMode.fixtures?.available === false}
                        onClick={() => handlePurgeFixtures(undefined)}
                        style={{ fontSize: 12, padding: "6px 12px" }}
                      >
                        Purge expired
                      </button>
                      <button
                        type="button"
                        className="ghost-btn"
                        disabled={loading || saving || testMode.fixtures?.available === false}
                        onClick={() => handlePurgeFixtures(0)}
                        style={{ fontSize: 12, padding: "6px 12px" }}
                      >
                        Purge all
                      </button>
                    </div>
                    {testMode.fixtures?.available === false && (
                      <p className="api-usage-empty" role="status">Fixture statistics are unavailable.</p>
                    )}
                  </Section>
              </>)}

              {isSuperAdmin && selectedSection.id === "technical" && usage && (<>
                  <p className="api-usage-note">Google Cloud quotas are reported limits; application caps are REVELA budgets. Request pacing is a separate delay between calls.</p>
                  <Section title="Quota comparison" description="Current server-reported Cloud quotas, application caps, and request pacing for each method.">
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns:
                          "repeat(auto-fit, minmax(min(100%, 210px), 1fr))",
                        gap: 10,
                      }}
                    >
                      {methods.map((method) => (
                        <div
                          key={method.method}
                          style={{
                            border: "1px solid var(--color-border-soft)",
                            borderRadius: 10,
                            padding: "12px 14px",
                            background: "var(--color-modal-bg)",
                          }}
                        >
                          <div
                            style={{
                              fontSize: 13,
                              fontWeight: 700,
                              color: "var(--color-ink)",
                              marginBottom: 10,
                            }}
                          >
                            {methodLabel(method, nearbyApiMode)}
                            <span style={{ color: "var(--color-muted)", fontWeight: 500 }}>
                              {" "}— {method.label}
                            </span>
                          </div>
                          <div style={{ display: "grid", gap: 10 }}>
                            <LimitBlock
                              kind="cloud"
                              rows={[
                                {
                                  label: "Requests / day",
                                  value: method.google_cloud_quota.daily_requests ?? "not verified",
                                },
                                {
                                  label: "Requests / minute",
                                  value: method.google_cloud_quota.per_minute_requests ?? "not verified",
                                },
                                {
                                  label: "Confirmed",
                                  value: method.google_cloud_quota.verified ? "Yes" : "No",
                                },
                              ]}
                              note={method.google_cloud_quota.source}
                            />
                            <LimitBlock
                              kind="app"
                              rows={[
                                {
                                  label: "Today",
                                  value: `${method.revela_app_cap.used_today} / ${method.revela_app_cap.daily_cap}`,
                                },
                                {
                                  label: "This month",
                                  value: `${method.revela_app_cap.used_month} / ${method.revela_app_cap.monthly_cap}`,
                                },
                                {
                                  label: "Monthly left",
                                  value: method.revela_app_cap.monthly_remaining,
                                },
                                {
                                  label: "Daily left",
                                  value: method.revela_app_cap.daily_remaining,
                                },
                                {
                                  label: "Cap set by",
                                  value:
                                    method.revela_app_cap.daily_cap_source === "admin_override"
                                      ? "custom setting"
                                      : "application default",
                                },
                              ]}
                              note={
                                method.revela_app_cap.daily_cloud_ceiling != null
                                  ? `Cloud ceiling: ${method.revela_app_cap.daily_cloud_ceiling}/day`
                                  : "No Cloud ceiling recorded for this method."
                              }
                            />
                            <LimitBlock
                              kind="pacing"
                              rows={[
                                {
                                  label: "Min interval",
                                  value:
                                    method.request_pacing.min_interval_ms > 0
                                      ? `${method.request_pacing.min_interval_ms} ms`
                                      : "none",
                                },
                                {
                                  label: "Enforced",
                                  value: method.request_pacing.enforced ? "Yes" : "No",
                                },
                              ]}
                              note={method.request_pacing.note}
                            />
                          </div>
                        </div>
                      ))}
                    </div>

                    {usage?.run_detection && (
                      <div style={{ marginTop: 12, fontSize: 11.5, color: "var(--color-muted)", lineHeight: 1.55 }}>
                        Run Detection work slice: {usage.run_detection.work_slice_seconds}s /{" "}
                        {usage.run_detection.work_slice_requests} requests · Nearby endpoint:{" "}
                        {usage.run_detection.nearby_api_mode}. {usage.run_detection.note}
                      </div>
                    )}
                  </Section>
              </>)}
              </section>
              </div>
            </div>
          </section>
        </div>,
        document.body,
      )}
    </>
  );
}
