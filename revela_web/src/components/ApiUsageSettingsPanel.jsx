import { useCallback, useMemo, useState } from "react";
import Swal from "sweetalert2";
import {
  getApiUsageReportRequest,
  getApiQuotaSettingsRequest,
  updateApiQuotaSettingsRequest,
  resetApiQuotaSettingsRequest,
  getTestModeSettingsRequest,
  updateTestModeSettingsRequest,
  resetTestModeSettingsRequest,
  purgeTestFixturesRequest,
  matchingDryRunRequest,
} from "../services/api";

/**
 * Admin-only "API Usage & Testing" section for the Maps page.
 *
 * Design notes, matching the rest of the app:
 *  - Surfaces (`saas-card`, `frosted-glass`, `primary-btn`, `ghost-btn`,
 *    `badge`) and every colour come from `src/styles/global.css`; nothing here
 *    introduces a new token, so dark mode works without extra rules.
 *  - Toggles are segmented pill groups rather than checkboxes, which is the
 *    established pattern in `SettingsPage.jsx`.
 *  - Layout is intrinsic CSS Grid (`repeat(auto-fit, minmax(...))`) so it
 *    reflows without media queries or JS width checks.
 *
 * The three limit kinds are visually distinct throughout, because conflating
 * them is the mistake this screen exists to prevent:
 *   Google Cloud quota   — blue, read-only, "not editable here"
 *   REVELA application cap — green, editable, clamped to the Cloud quota
 *   Request pacing       — grey, informational
 */

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

function LegendPill({ kind }) {
  const meta = LIMIT_META[kind];
  return (
    <span
      title={meta.hint}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 10.5,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.03em",
        color: meta.color,
        background: meta.bg,
        border: `1px solid ${meta.border}`,
        borderRadius: 6,
        padding: "2px 7px",
        whiteSpace: "nowrap",
      }}
    >
      {meta.label}
    </span>
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
  const safeCap = Number(cap) || 0;
  const pct = safeCap > 0 ? Math.min(100, (Number(used) / safeCap) * 100) : 0;
  const color =
    pct >= 100 ? "var(--color-danger)" : pct >= 80 ? "var(--color-warning)" : "var(--color-primary)";
  return (
    <div
      style={{
        height: 6,
        borderRadius: 3,
        background: "var(--color-hover)",
        overflow: "hidden",
        marginTop: 8,
      }}
    >
      <div
        style={{
          width: `${pct}%`,
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

function editableTestModeDraft(config = {}) {
  return Object.fromEntries(
    Object.entries(config).filter(
      ([key]) => key !== "test_mode.fixture_storage_approved",
    ),
  );
}

export default function ApiUsageSettingsPanel({ token, isAdmin, onUsageChanged }) {
  const [open, setOpen] = useState(false);
  const [usage, setUsage] = useState(null);
  const [quota, setQuota] = useState(null);
  const [testMode, setTestMode] = useState(null);
  const [draft, setDraft] = useState({});
  const [testDraft, setTestDraft] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dryRunText, setDryRunText] = useState(
    '[\n  {"name": "Mabini Store", "lat": 13.9667, "lng": 121.1167, "types": ["store"]}\n]',
  );
  const [dryRunResult, setDryRunResult] = useState(null);

  const load = useCallback(async () => {
    if (!token || !isAdmin) return;
    setLoading(true);
    setError("");
    try {
      const [usageData, quotaData, testData] = await Promise.all([
        getApiUsageReportRequest(token),
        getApiQuotaSettingsRequest(token),
        getTestModeSettingsRequest(token),
      ]);
      setUsage(usageData);
      setQuota(quotaData);
      setTestMode(testData);
      setDraft(quotaData?.fields ?? {});
      setTestDraft(editableTestModeDraft(testData?.config));
    } catch (err) {
      setError(err.message || "Could not load API usage settings.");
    } finally {
      setLoading(false);
    }
  }, [token, isAdmin]);

  // Loaded when the panel is opened rather than in an effect: the data is only
  // needed while it is visible, and loading on click avoids a cascading render.
  const handleToggle = () => {
    setOpen((prev) => {
      if (!prev) load();
      return !prev;
    });
  };

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
    const payload = {};
    for (const key of dirtyQuotaKeys) {
      const field = quota.fields[key];
      payload[key] = field.kind === "float" ? Number(draft[key]) : Number(draft[key]);
    }
    if (Object.keys(payload).length === 0) return;
    setSaving(true);
    try {
      const result = await updateApiQuotaSettingsRequest(payload, token);
      setQuota({ fields: result.fields });
      setDraft(result.fields);
      Swal.fire({
        icon: "success",
        title: "Quota settings saved",
        text: `${result.saved} setting(s) updated. They apply to the next request without a redeploy.`,
        confirmButtonColor: "var(--color-primary)",
      });
      await load();
      // Keep the Maps page header pills and Run Detection button in step with
      // the caps that were just changed.
      onUsageChanged?.();
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Settings not saved",
        text: err.message,
        confirmButtonColor: "#ef4444",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleResetQuota = async () => {
    const confirm = await Swal.fire({
      icon: "question",
      title: "Restore default caps?",
      html: "Admin overrides will be discarded and the environment baseline will apply again. This does <b>not</b> reset usage counters or grant extra quota.",
      showCancelButton: true,
      confirmButtonColor: "var(--color-primary)",
      cancelButtonColor: "var(--color-muted)",
    });
    if (!confirm.isConfirmed) return;
    try {
      const result = await resetApiQuotaSettingsRequest(token);
      setQuota({ fields: result.fields });
      setDraft(result.fields);
      await load();
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

  const handleDryRun = async () => {
    let candidates;
    try {
      candidates = JSON.parse(dryRunText);
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Invalid JSON",
        text: err.message,
        confirmButtonColor: "#ef4444",
      });
      return;
    }
    if (!Array.isArray(candidates) || candidates.length === 0) {
      Swal.fire({
        icon: "error",
        title: "Expected a non-empty array",
        confirmButtonColor: "#ef4444",
      });
      return;
    }
    try {
      setDryRunResult(await matchingDryRunRequest(candidates, token));
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Dry run failed",
        text: err.message,
        confirmButtonColor: "#ef4444",
      });
    }
  };

  if (!isAdmin) return null;

  return (
    <div className="saas-card frosted-glass" style={{ padding: 20 }}>
      <button
        type="button"
        onClick={handleToggle}
        aria-expanded={open}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 0,
          textAlign: "left",
          fontFamily: "inherit",
        }}
      >
        <div>
          <h3
            style={{
              margin: "0 0 4px",
              fontSize: 16,
              fontWeight: 750,
              color: "var(--color-ink)",
            }}
          >
            API Usage &amp; Testing
          </h3>
          <p style={{ margin: 0, fontSize: 12.5, color: "var(--color-muted)" }}>
            Google Cloud quotas, REVELA application caps, and request pacing —
            reported separately. Administrator only.
          </p>
        </div>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12,
            fontWeight: 600,
            color: "var(--color-muted)",
          }}
        >
          {open ? "Hide" : "Show"}
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            style={{
              transition: "transform var(--duration-normal, 0.2s)",
              transform: open ? "rotate(180deg)" : "rotate(0deg)",
            }}
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 18, display: "grid", gap: 16 }}>
          {error && (
            <div
              role="alert"
              style={{
                fontSize: 12.5,
                color: "var(--color-danger)",
                background: "var(--color-danger-light)",
                border: "1px solid rgba(239, 68, 68, 0.28)",
                borderRadius: 8,
                padding: "10px 12px",
              }}
            >
              {error}
            </div>
          )}

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            {Object.keys(LIMIT_META).map((kind) => (
              <LegendPill key={kind} kind={kind} />
            ))}
            <button
              type="button"
              className="ghost-btn"
              onClick={load}
              disabled={loading}
              style={{ marginLeft: "auto", fontSize: 12, padding: "6px 12px" }}
            >
              {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {/* ── Usage per method ─────────────────────────────────────────── */}
          <Section
            title="Usage by API method"
            description="Every real Google request is reserved before it is sent, so these counters only ever describe billable calls. Fixture replays are never counted."
          >
            {loading && !usage ? (
              <div style={{ fontSize: 12.5, color: "var(--color-muted)" }}>Loading usage…</div>
            ) : (
              <div style={{ display: "grid", gap: 12 }}>
                {(usage?.methods ?? []).map((method) => (
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
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 10,
                        flexWrap: "wrap",
                        marginBottom: 10,
                      }}
                    >
                      <strong style={{ fontSize: 13.5, color: "var(--color-ink)" }}>
                        {method.label}
                      </strong>
                      {method.revela_app_cap.disabled && (
                        <span className="badge badge--black">Disabled</span>
                      )}
                      {method.revela_app_cap.daily_quota_exceeded && (
                        <span className="badge badge--red">Daily cap reached</span>
                      )}
                      {method.revela_app_cap.over_cloud_ceiling && (
                        <span className="badge badge--red">Above Cloud quota</span>
                      )}
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns:
                          "repeat(auto-fit, minmax(min(100%, 210px), 1fr))",
                        gap: 10,
                      }}
                    >
                      <LimitBlock
                        kind="cloud"
                        rows={[
                          {
                            label: "Requests / day",
                            value:
                              method.google_cloud_quota.daily_requests ??
                              "not verified",
                          },
                          {
                            label: "Requests / minute",
                            value:
                              method.google_cloud_quota.per_minute_requests ??
                              "not verified",
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
                            label: "Daily left",
                            value: method.revela_app_cap.daily_remaining,
                          },
                          {
                            label: "Cap set by",
                            value:
                              method.revela_app_cap.daily_cap_source === "admin_override"
                                ? "admin override"
                                : "environment",
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

                    <Meter
                      used={method.revela_app_cap.used_today}
                      cap={method.revela_app_cap.daily_cap}
                    />

                    {method.cost_estimate ? (
                      <div
                        style={{
                          marginTop: 10,
                          fontSize: 11.5,
                          color: "var(--color-muted)",
                          lineHeight: 1.55,
                        }}
                      >
                        <strong style={{ color: "var(--color-ink)" }}>
                          Estimated cost this month: $
                          {method.cost_estimate.estimated_cost_usd.toFixed(2)}
                        </strong>{" "}
                        · SKU {method.cost_estimate.sku_label} ·{" "}
                        {method.cost_estimate.free_monthly_calls == null
                          ? "no free allowance recorded"
                          : `${method.cost_estimate.free_monthly_calls.toLocaleString()} free calls/month`}{" "}
                        · {method.cost_estimate.note}
                      </div>
                    ) : (
                      <div
                        style={{
                          marginTop: 10,
                          fontSize: 11.5,
                          color: "var(--color-muted)",
                        }}
                      >
                        Pricing not available for this method.
                      </div>
                    )}
                  </div>
                ))}

                {usage?.totals && (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fit, minmax(min(100%, 180px), 1fr))",
                      gap: 10,
                    }}
                  >
                    <div className="saas-card" style={{ padding: "12px 14px", borderRadius: 10 }}>
                      <div style={labelStyle}>Estimated month total</div>
                      <div style={{ fontSize: 20, fontWeight: 800, color: "var(--color-ink)" }}>
                        ${usage.totals.estimated_monthly_cost_usd.toFixed(2)}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--color-muted)", marginTop: 2 }}>
                        Estimate only — confirm against current Google pricing.
                      </div>
                    </div>
                    <div className="saas-card" style={{ padding: "12px 14px", borderRadius: 10 }}>
                      <div style={labelStyle}>Run Detection slice</div>
                      <div style={{ fontSize: 13, color: "var(--color-ink)", lineHeight: 1.6 }}>
                        {usage.run_detection.work_slice_seconds}s /{" "}
                        {usage.run_detection.work_slice_requests} requests
                        <br />
                        grid step {usage.run_detection.grid_step_degrees}°,{" "}
                        {usage.run_detection.monthly_scan_limit} scans/month
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </Section>

          {/* ── Workflow allocations ─────────────────────────────────────── */}
          {usage?.text_search_workflows && (
            <Section
              title="Text Search workflow allocations"
              description="Registry import, Snap Pins, and Re-verify share one Text Search daily cap. Their sub-budgets must add up to no more than it."
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
                      {wf.used_today} / {wf.daily_cap}
                    </div>
                    <Meter used={wf.used_today} cap={wf.daily_cap} />
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* ── Quota settings ───────────────────────────────────────────── */}
          <Section
            title="Application quota caps"
            description="These are REVELA's budgets. They can be lowered freely, but can never be raised above the recorded Google Cloud quota — that limit lives in Cloud Console, not here."
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
                      style={{
                        fontSize: 10.5,
                        color: "var(--color-muted)",
                        marginTop: 5,
                        lineHeight: 1.45,
                      }}
                    >
                      {field.help}
                      {field.source === "admin_override" && (
                        <>
                          {" "}
                          <strong style={{ color: "var(--color-primary)" }}>
                            (overridden; env baseline {field.baseline})
                          </strong>
                        </>
                      )}
                      {field.cloud_ceiling != null && (
                        <> Cloud ceiling: {field.cloud_ceiling}/day.</>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </Section>

          {/* ── Test Mode ────────────────────────────────────────────────── */}
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
                <div style={{ fontSize: 11, color: "var(--color-muted)", marginTop: 3 }}>
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
              <div
                style={{
                  marginBottom: 14,
                  padding: "8px 10px",
                  border: "1px solid rgba(245, 158, 11, 0.35)",
                  borderRadius: 6,
                  color: "#92400e",
                  background: "rgba(245, 158, 11, 0.08)",
                  fontSize: 11.5,
                  lineHeight: 1.45,
                }}
              >
                Fixture replay is off. Test Mode may still make live Google requests; those use normal quota reservations and may incur charges.
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
                  <div
                    style={{
                      fontSize: 10.5,
                      color: "var(--color-muted)",
                      marginTop: 5,
                      lineHeight: 1.45,
                    }}
                  >
                    {field.hint}
                  </div>
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
                  style={{
                    ...inputStyle,
                    appearance: "auto",
                  }}
                >
                  <option value="cache_then_live">
                    Replay if stored, else call Google
                  </option>
                  <option value="cache_only">
                    Replay only — never call Google
                  </option>
                </select>
                <div
                  style={{
                    fontSize: 10.5,
                    color: "var(--color-muted)",
                    marginTop: 5,
                    lineHeight: 1.45,
                  }}
                >
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

            <div
              style={{
                marginTop: 16,
                paddingTop: 14,
                borderTop: "1px solid var(--color-border-soft)",
              }}
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
                    {testMode?.fixtures?.total ?? 0}
                  </div>
                </div>
                <div>
                  <div style={labelStyle}>Replays served</div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-ink)" }}>
                    {testMode?.fixtures?.replay_hits ?? 0}
                  </div>
                </div>
                <div>
                  <div style={labelStyle}>Usage rows written</div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: "var(--color-primary)" }}>
                    0
                  </div>
                  <div style={{ fontSize: 10.5, color: "var(--color-muted)" }}>
                    by replays
                  </div>
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
            </div>
          </Section>

          {/* ── Matching dry run ─────────────────────────────────────────── */}
          <Section
            title="Matching dry run"
            description="Replay candidate businesses through the matcher against the live registry. No Google request is made, no usage row is written, and no flag is created."
            action={
              <button
                type="button"
                className="primary-btn"
                onClick={handleDryRun}
                style={{ fontSize: 12, padding: "7px 14px" }}
              >
                Run dry run
              </button>
            }
          >
            <textarea
              value={dryRunText}
              onChange={(e) => setDryRunText(e.target.value)}
              spellCheck={false}
              aria-label="Candidates JSON"
              style={{
                ...inputStyle,
                minHeight: 120,
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: 12,
                resize: "vertical",
              }}
            />
            {dryRunResult && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 12, color: "var(--color-muted)", marginBottom: 8 }}>
                  {dryRunResult.candidates_evaluated} candidate(s) against{" "}
                  {dryRunResult.registry_size} registry entries ·{" "}
                  {dryRunResult.google_requests_made} Google requests ·{" "}
                  {dryRunResult.usage_rows_written} usage rows written
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr
                        style={{
                          color: "var(--color-muted)",
                          fontSize: 11,
                          textTransform: "uppercase",
                        }}
                      >
                        <th style={{ textAlign: "left", padding: "6px 8px" }}>Name</th>
                        <th style={{ textAlign: "left", padding: "6px 8px" }}>Decision</th>
                        <th style={{ textAlign: "right", padding: "6px 8px" }}>Score</th>
                        <th style={{ textAlign: "right", padding: "6px 8px" }}>Distance</th>
                        <th style={{ textAlign: "left", padding: "6px 8px" }}>Matched</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dryRunResult.results.map((row) => (
                        <tr
                          key={row.index}
                          style={{ borderTop: "1px solid var(--color-border-soft)" }}
                        >
                          <td style={{ padding: "6px 8px", fontSize: 12, color: "var(--color-ink)" }}>
                            {row.error ?? row.name ?? "—"}
                          </td>
                          <td style={{ padding: "6px 8px", fontSize: 12 }}>
                            {row.match_status ? (
                              <span
                                className={
                                  row.match_status === "auto"
                                    ? "badge badge--green"
                                    : row.match_status === "no_match"
                                      ? "badge badge--black"
                                      : "badge badge--gold"
                                }
                              >
                                {row.match_status}
                              </span>
                            ) : (
                              <span style={{ color: "var(--color-danger)" }}>{row.error}</span>
                            )}
                          </td>
                          <td style={{ padding: "6px 8px", fontSize: 12, textAlign: "right" }}>
                            {row.score ?? "—"}
                          </td>
                          <td style={{ padding: "6px 8px", fontSize: 12, textAlign: "right" }}>
                            {row.distance_m != null ? `${row.distance_m} m` : "—"}
                          </td>
                          <td style={{ padding: "6px 8px", fontSize: 12, color: "var(--color-muted)" }}>
                            {row.matched_business_name ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </Section>
        </div>
      )}
    </div>
  );
}
