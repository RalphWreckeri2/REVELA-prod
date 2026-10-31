import { backupStatusPresentation, formatBackupDate, formatBackupSize } from "./backupStatusView";

export default function BackupStatusPanel({
  data, loading, error, actionError, actionLoading, notice,
  onRefresh, onBackupNow, onDownload,
}) {
  const state = backupStatusPresentation(data, loading, error);
  const lastBackup = data?.lastSuccessfulBackup;
  const scheduled = data?.configured === true && data.schedule.configured === true && data.schedule.enabled === true;
  const actionReason = loading ? "Checking backend status. Backup actions are unavailable while status is loading."
    : error || !data ? "Backup actions are unavailable until the backend status can be verified."
      : data.manualBackupDisabledReason || "Manual database backup is available.";
  const downloadReason = data?.downloadDisabledReason || "Download is available only for completed backups.";

  return (
    <div className="database-backup-panel" aria-busy={loading}>
      <p className="database-backup-description">
        Create and download recovery copies of system database records. Inspection photo files are managed separately under Inspection Evidence Storage &amp; Archival.
      </p>
      {error && <p className="settings-error" role="alert">{error}</p>}
      {actionError && <p className="settings-error" role="alert">{actionError}</p>}
      {notice && <p className="database-backup-notice" role="status">{notice}</p>}
      {loading && <p className="database-backup-note" role="status">Loading database backup status…</p>}
      {!loading && data?.reason && <p className="database-backup-notice" role="status">{data.reason}</p>}
      {!loading && data?.status === "running" && <p className="database-backup-notice" role="status">A database backup is running. Refresh Status to check its progress.</p>}
      {!loading && data?.automaticExecutionStatus === "not_ready" && (
        <p className="database-backup-notice" role="status">
          Automatic backup is not ready: {data.automaticExecutionReason || "A reliable external scheduled trigger is not configured."}
        </p>
      )}

      <dl className="database-backup-metrics">
        <div className="database-backup-metric">
          <dt>Backup status</dt>
          <dd><span className={`settings-section-state is-${state.tone}`}>{state.text}</span></dd>
        </div>
        <div className="database-backup-metric">
          <dt>Last successful backup</dt>
          <dd>{loading ? "Loading…" : !data ? "Unavailable" : lastBackup ? <>
            <span>{formatBackupDate(lastBackup.completedAt)}</span>
            <span className="database-backup-detail">{formatBackupSize(lastBackup.sizeBytes)}</span>
          </> : "No successful backup yet"}</dd>
        </div>
        <div className="database-backup-metric">
          <dt>Next scheduled backup</dt>
          <dd>{loading ? "Loading…" : !data ? "Unavailable" : scheduled
            ? formatBackupDate(data.schedule.nextRunAt) : "Not scheduled"}</dd>
        </div>
        <div className="database-backup-metric">
          <dt>Schedule &amp; retention</dt>
          <dd>{loading ? "Loading…" : !data ? "Unavailable" : <>
            <span>{data.schedule.configured && data.schedule.summary
              ? `${data.schedule.enabled ? "Enabled" : "Disabled"} · ${data.schedule.summary}` : "Schedule not configured"}</span>
            <span className="database-backup-detail">{data.retention.configured && data.retention.summary
              ? data.retention.summary : "Retention not configured"}</span>
          </>}</dd>
        </div>
      </dl>

      <aside className="database-backup-policy" aria-labelledby="database-backup-policy-title">
        <h3 id="database-backup-policy-title">Proposed policy <span className="settings-section-state">Proposal only</span></h3>
        <p>Weekly backup: Friday at <strong>7:00 PM Asia/Manila</strong>. This is the proposed backup start time.</p>
        <p>Keep the four most recent successful weekly copies and the three most recent monthly archives. Monthly archives are retained separately from the weekly count.</p>
        <p>Manual backups are a separate category; proposed retention is 30 days. This duration needs approval before cleanup can be enabled.</p>
        <p>{data?.retention?.cleanupEnabled ? "Cleanup is enabled." : "Cleanup is disabled until approved."} The external schedule and trigger remain disabled pending runtime verification, an isolated restore test, and explicit cost approval.</p>
      </aside>

      <div className="database-backup-history">
        <h3 id="database-backup-history-title">Backup history</h3>
        <p className="database-backup-note">Dates and times are shown in Asia/Manila.</p>
        <div className="database-backup-table-wrap" role="region" aria-labelledby="database-backup-history-title" tabIndex={0}>
          <table className="database-backup-table">
            <thead><tr><th scope="col">Date &amp; time</th><th scope="col">Type</th><th scope="col">Result</th><th scope="col">File size</th><th scope="col">Download</th></tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={5} className="database-backup-empty">Loading backup history…</td></tr>
                : !data || data.history === null ? <tr><td colSpan={5} className="database-backup-empty">{data?.historyUnavailableReason || "Backup history is unavailable until backend status can be verified."}</td></tr>
                  : data.history.length === 0 ? <tr><td colSpan={5} className="database-backup-empty">No backup runs have been reported by the backend.</td></tr>
                    : data.history.map(backup => <tr key={backup.id}>
                      <td>{formatBackupDate(backup.completedAt || backup.startedAt)}</td>
                      <td>{backup.trigger === "manual" ? "Manual" : backup.monthlyArchive ? "Monthly archive" : "Automatic"}</td>
                      <td><span className={`settings-section-state is-${backup.status === "completed" ? "ready" : backup.status === "failed" ? "error" : "warning"}`}>{backup.status === "completed" ? "Completed" : backup.status === "failed" ? "Failed" : "Running"}</span></td>
                      <td>{formatBackupSize(backup.sizeBytes)}</td>
                      <td>{backup.status === "completed" ? <button
                        type="button"
                        className="ghost-btn"
                        onClick={() => onDownload?.(backup.id)}
                        disabled={!data?.canDownload || typeof onDownload !== "function"}
                        aria-describedby={!data?.canDownload ? "database-backup-download-reason" : undefined}
                      >Download</button> : "—"}</td>
                    </tr>)}
            </tbody>
          </table>
        </div>
        {data?.history?.some(backup => backup.status === "completed") && <p id="database-backup-download-reason" className="database-backup-note">{downloadReason}</p>}
      </div>

      <div className="database-backup-actions">
        <p id="database-backup-action-reason" className="database-backup-note">{actionReason}</p>
        <div className="database-backup-buttons">
          <button type="button" className="ghost-btn" onClick={onRefresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh Status"}</button>
          <button
            type="button"
            className="primary-btn"
            onClick={onBackupNow}
            disabled={loading || actionLoading || !data?.canManualBackup || data?.status === "running" || typeof onBackupNow !== "function"}
            aria-describedby={!data?.canManualBackup ? "database-backup-action-reason" : undefined}
          >{actionLoading ? "Starting…" : data?.status === "running" ? "Backup Running…" : "Back Up Now"}</button>
        </div>
      </div>
    </div>
  );
}
