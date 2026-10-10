import { useCallback, useEffect, useMemo, useState } from "react";
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
  detectionScanSummary,
  formatNumber,
  isCustomLimit,
  limitState,
  methodLabel,
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
 * Everything technical — application limits, workflow allocations, Test Mode,
 * fixture management, and the raw Cloud-quota comparison — lives inside a
 * collapsed "Advanced Settings" block restricted to Super Admins. Nothing is
 * fetched for a plain administrator, so a restricted operator never even loads
 * that data.
 *
 * Design notes, matching the rest of the app:
 *  - Surfaces (`saas-card`, `frosted-glass`, `primary-btn`, `ghost-btn`,
 *    `badge`) and every colour come from `src/styles/global.css` / `MapPage.css`;
 *    nothing here introduces a new token, so dark mode works unchanged.
 *  - Layout is intrinsic CSS Grid (`repeat(auto-fit, minmax(...))`) so it
 *    reflows without media queries or JS width checks.
 *  - Wording, thresholds, and arithmetic live in `apiUsageView.js` so they can
 *    be unit tested without a DOM.
 *
 * This component is read-and-edit only. Quota enforcement lives in the
 * backend reservation path (`api/utils/places_quota.py`) and is untouched here.
 */

const BILLING_NOTE =
  "REVELA counts these Google requests in its own internal ledger. The figures "
  + "below are application limits, not Google Cloud billing.";

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
    <section
      style={{
        border: "1px solid var(--color-border-soft)",
        borderRadius: "var(--radius-md)",
        padding: 16,
        background: "var(--color-card-alt)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 14,
        }}
      >
        <div>
          <h4
            style={{
              margin: "0 0 4px",
              fontSize: 14,
              fontWeight: 700,
              color: "var(--color-ink)",
            }}
          >
            {title}
          </h4>
          {description && (
            <p
              style={{
                margin: 0,
                fontSize: 12,
                color: "var(--color-muted)",
                lineHeight: 1.5,
                maxWidth: 720,
              }}
            >
              {description}
            </p>
          )}
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

function SegmentedToggle({ value, options, onChange, disabled }) {
  return (
    <div
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
  const [usage, setUsage] = useState(null);
  const [detectionQuota, setDetectionQuota] = useState(null);
  const [quota, setQuota] = useState(null);
  const [testMode, setTestMode] = useState(null);
  const [draft, setDraft] = useState({});
  const [testDraft, setTestDraft] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!token || !isAdmin) return;
    setLoading(true);
    setError("");
    try {
      const [usageData, detectionData, quotaData, testData] = await Promise.all([
        getApiUsageReportRequest(token),
        getDetectionQuotaRequest(token),
        // Advanced Settings is Super Admin only, so its two payloads are never
        // requested — and never rendered — for a plain administrator.
        ...(isSuperAdmin
          ? [getApiQuotaSettingsRequest(token), getTestModeSettingsRequest(token)]
          : []),
      ]);
      setUsage(usageData);
      setDetectionQuota(detectionData);
      if (quotaData) {
        setQuota(quotaData);
        setDraft(draftFromFields(quotaData.fields));
      }
      if (testData) {
        setTestMode(testData);
        setTestDraft(editableTestModeDraft(testData.config));
      }
    } catch (err) {
      setError(err.message || "Could not load API usage settings.");
    } finally {
      setLoading(false);
    }
  }, [token, isAdmin, isSuperAdmin]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  // Load only when the modal opens; the content is only needed while visible.
  const handleToggle = () => {
    setOpen((prev) => {
      if (!prev) {
        load();
        // Let the host collapse the surrounding menu the trigger lives in.
        onOpen?.();
      }
      return !prev;
    });
  };

  const methods = useMemo(() => usage?.methods ?? [], [usage]);
  const usageTotals = useMemo(() => summarizeUsage(methods), [methods]);
  const scans = useMemo(
    () => detectionScanSummary(detectionQuota),
    [detectionQuota],
  );
  const warnings = useMemo(
    () => buildUsageWarnings(methods, detectionQuota),
    [methods, detectionQuota],
  );

  const dirtyQuotaKeys = useMemo(() => {
    if (!quota?.fields) return [];
    return Object.keys(draft).filter((key) => {
      const field = quota.fields[key];
      if (!field) return false;
      return Number(draft[key]) !== Number(field.baseline)
        && String(draft[key]) !== String(field.baseline);
    });
  }, [draft, quota]);

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
      setQuota({ fields: result.fields });
      setDraft(draftFromFields(result.fields));
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
      setQuota({ fields: result.fields });
      setDraft(draftFromFields(result.fields));
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
      setTestMode((prev) => ({ ...prev, config: result.config }));
      setTestDraft(editableTestModeDraft(result.config));
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
    const confirm = await Swal.fire({
      icon: "warning",
      title: "Delete cached payloads?",
      html: olderThanDays === 0
        ? "This deletes <b>every</b> stored fixture. Usage counters are not affected."
        : `This deletes fixtures older than ${olderThanDays} day(s). Usage counters are not affected.`,
      showCancelButton: true,
      confirmButtonColor: "#ef4444",
      cancelButtonColor: "var(--color-muted)",
    });
    if (!confirm.isConfirmed) return;
    try {
      const result = await purgeTestFixturesRequest(token, olderThanDays);
      setTestMode((prev) => ({ ...prev, fixtures: result.fixtures }));
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
              <button
                type="button"
                className="ghost-btn"
                onClick={() => setOpen(false)}
                aria-label="Close API usage and limits"
              >
                Close
              </button>
            </header>
            <div className="api-usage-modal-content">
              {error && (
                <div role="alert" className="api-usage-error">
                  {error}
                </div>
              )}

              <p className="api-usage-note">{BILLING_NOTE}</p>

              <div className="api-usage-toolbar">
                <button
                  type="button"
                  className="ghost-btn"
                  onClick={load}
                  disabled={loading}
                >
                  {loading ? "Refreshing…" : "Refresh"}
                </button>
              </div>

              {/* ── Headline figures ───────────────────────────────────── */}
              <div className="api-usage-overview">
                <div className="api-usage-overview-card">
                  <span>Requests used today</span>
                  <strong>
                    {loading && !usage ? "…" : formatNumber(usageTotals.usedToday)}
                  </strong>
                  <small>Across all lookup types</small>
                </div>
                <div className="api-usage-overview-card">
                  <span>Requests used this month</span>
                  <strong>
                    {loading && !usage ? "…" : formatNumber(usageTotals.usedMonth)}
                  </strong>
                  <small>Across all lookup types</small>
                </div>
                <div className="api-usage-overview-card">
                  <span>Run Detection scans left</span>
                  <strong>{detectionQuota ? formatNumber(scans.remaining) : "…"}</strong>
                  <small>
                    {detectionQuota
                      ? `${formatNumber(scans.used)} of ${formatNumber(scans.limit)} used this month`
                      : "Monthly scan allowance"}
                  </small>
                </div>
              </div>

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
                {loading && !usage ? (
                  <div style={{ fontSize: 12.5, color: "var(--color-muted)" }}>
                    Loading usage…
                  </div>
                ) : (
                  <div className="api-usage-methods">
                    {methods.map((method) => {
                      const cap = method.revela_app_cap;
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
                            <strong>{methodLabel(method)}</strong>
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
                                : `${formatNumber(monthly.remaining)} left this month`}
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

              {/* ── Advanced Settings (Super Admin) ────────────────────── */}
              {isSuperAdmin ? (
                <details className="api-usage-advanced">
                  <summary>
                    Advanced Settings
                    {testMode?.config?.["test_mode.enabled"] && (
                      <span className="api-usage-active-badge">Test Mode active</span>
                    )}
                  </summary>

                  <Section
                    title="Application limits"
                    description="These are REVELA's own request budgets. Each one starts as the application default; a custom value is kept until it is explicitly changed or restored. Google Cloud limits cannot be changed here."
                    action={
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <button
                          type="button"
                          className="primary-btn"
                          onClick={handleSaveQuota}
                          disabled={saving || dirtyQuotaKeys.length === 0}
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
                              step={field.kind === "float" ? "0.0001" : "1"}
                              min={field.minimum}
                              max={Number.isFinite(max) ? max : undefined}
                              value={draft[key] ?? field.baseline}
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
                                <span>Google Cloud daily limit: {formatNumber(field.cloud_ceiling)}</span>
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

                  {/* ── Test Mode ────────────────────────────────────────── */}
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
                        value={Boolean(testDraft["test_mode.enabled"])}
                        options={[
                          { label: "On", value: true },
                          { label: "Off", value: false },
                        ]}
                        disabled={saving}
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
                            ? "Server policy approval is enabled. Retention is limited to 30 days or less."
                            : "Disabled until the server explicitly approves Google Places fixture storage."}
                        </div>
                      </div>
                      <SegmentedToggle
                        value={Boolean(testDraft["test_mode.fixture_storage_enabled"])}
                        options={[
                          { label: "On", value: true },
                          { label: "Off", value: false },
                        ]}
                        disabled={
                          saving
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
                        Fixture replay is off. Test Mode may still make live Google
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
                          value={testDraft["test_mode.fixture_policy"] ?? "cache_then_live"}
                          disabled={
                            saving
                            || !testMode?.config?.["test_mode.fixture_storage_enabled"]
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
                        disabled={saving}
                        onClick={async () => {
                          const patch = {};
                          for (const [key, value] of Object.entries(testDraft)) {
                            patch[key] = key === "test_mode.grid_step_degrees"
                              ? Number(value)
                              : value;
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
                        disabled={saving}
                        onClick={async () => {
                          try {
                            const result = await resetTestModeSettingsRequest(token);
                            setTestMode((prev) => ({ ...prev, config: result.config }));
                            setTestDraft(editableTestModeDraft(result.config));
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
                          {formatNumber(testMode?.fixtures?.total ?? 0)}
                        </div>
                      </div>
                      <div>
                        <div style={labelStyle}>Replays served</div>
                        <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-ink)" }}>
                          {formatNumber(testMode?.fixtures?.replay_hits ?? 0)}
                        </div>
                      </div>
                      <div>
                        <div style={labelStyle}>Usage rows written</div>
                        <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-primary)" }}>
                          0
                        </div>
                        <div style={hintStyle}>by replays</div>
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="ghost-btn"
                        onClick={() => handlePurgeFixtures(undefined)}
                        style={{ fontSize: 12, padding: "6px 12px" }}
                      >
                        Purge expired
                      </button>
                      <button
                        type="button"
                        className="ghost-btn"
                        onClick={() => handlePurgeFixtures(0)}
                        style={{ fontSize: 12, padding: "6px 12px" }}
                      >
                        Purge all
                      </button>
                    </div>
                  </Section>

                  {/* ── Technical detail ─────────────────────────────────── */}
                  <details className="api-usage-technical-details">
                    <summary>Technical quota detail</summary>
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
                            {methodLabel(method)}
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
                  </details>
                </details>
              ) : (
                <p className="api-usage-note">
                  Application limits, Test Mode, and fixture management are part of
                  Advanced Settings and are available to Super Admins.
                </p>
              )}
            </div>
          </section>
        </div>,
        document.body,
      )}
    </>
  );
}