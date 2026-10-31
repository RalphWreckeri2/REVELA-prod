import { formatBackupDate, formatBackupSize } from "./backupStatusView";

export default function BackupStatusPanel({
  data, loading, error, actionError, actionLoading, notice,
  onRefresh, onBackupNow, onDownload,
}) {
  const lastBackup = data?.lastSuccessfulBackup;
  const automaticBackupStatus = loading ? "Loading…" : !data ? "Unavailable"
    : !data.configured ? "Setup required"
      : !data.schedule.enabled ? "Off"
        : !data.externalTriggerConfigured ? "Trigger missing"
          : data.automaticExecutionStatus === "ready" ? "On" : "Pending verification";
  const automaticBackupReason = !data?.configured
    ? "Complete the setup requirements below."
    : !data?.schedule?.enabled
      ? "Automatic scheduling is disabled in the backend configuration."
      : data?.automaticExecutionReason || "Automatic backup readiness is still being verified.";
  const actionReason = loading ? "Checking backend status. Backup actions are unavailable while status is loading."
    : error || !data ? "Backup actions are unavailable until the backend status can be verified."
      : data.manualBackupDisabledReason || (data.canManualBackup
        ? "Manual database backup is available." : "Manual database backup is unavailable.");
  const actionReasonUnavailable = !data?.canManualBackup || loading || error || !data;
  const actionReasonAlreadyShown = actionReasonUnavailable && !loading && !error
    && Boolean(data?.reason) && data.reason === actionReason;
  const downloadReason = data?.downloadDisabledReason || "Download is available only for completed backups.";
  const completedBackupsExist = data?.history?.some(backup => backup.status === "completed");

  return (
    <div className="database-backup-panel" aria-busy={loading}>
      <div className="database-backup-header">
        <p className="database-backup-description">
          Recovery copies of system database records. Inspection photos are managed separately.
        </p>
        <div className="database-backup-buttons">
          <button type="button" className="ghost-btn" onClick={onRefresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
          <button
            type="button"
            className="primary-btn"
            onClick={onBackupNow}
            disabled={loading || actionLoading || !data?.canManualBackup || data?.status === "running" || typeof onBackupNow !== "function"}
            aria-describedby={!data?.canManualBackup ? "database-backup-action-reason" : undefined}
          >{actionLoading ? "Starting…" : data?.status === "running" ? "Backup Running…" : "Back Up Now"}</button>
        </div>
      </div>
      {error && <p className="settings-error" role="alert">{error}</p>}
      {actionError && <p className="settings-error" role="alert">{actionError}</p>}
      {notice && <p className="database-backup-notice" role="status">{notice}</p>}
      {loading && <p className="database-backup-note" role="status">Loading database backup status…</p>}
      {!loading && data?.reason && <p
        id={actionReasonAlreadyShown ? "database-backup-action-reason" : undefined}
        className="database-backup-notice"
        role="status"
      >{data.reason}</p>}
      {!loading && data?.status === "running" && <p className="database-backup-notice" role="status">A database backup is running. Refresh to check its progress.</p>}
      {actionReasonUnavailable && !actionReasonAlreadyShown && <p id="database-backup-action-reason" className="database-backup-note">{actionReason}</p>}
      {!loading && !data?.configured && data?.configurationIssues?.length > 0 && (
        <details className="database-backup-setup">
          <summary>View setup requirements</summary>
          <ul>{data.configurationIssues.map((issue, index) => <li key={`${issue}-${index}`}>{issue}</li>)}</ul>
        </details>
      )}

      <dl className="database-backup-metrics">
        <div className="database-backup-metric">
          <dt>Last successful backup</dt>
          <dd>{loading ? "Loading…" : !data ? "Unavailable" : lastBackup ? <>
            <span>{formatBackupDate(lastBackup.completedAt)}</span>
            <span className="database-backup-detail">{formatBackupSize(lastBackup.sizeBytes)} · {lastBackup.trigger === "manual" ? "Manual" : "Automatic"}</span>
          </> : "No successful backup yet"}</dd>
        </div>
        <div className="database-backup-metric">
          <dt>Automatic backup</dt>
          <dd>{automaticBackupStatus}
            {!loading && data && automaticBackupStatus !== "On" && (
              <span className="database-backup-detail database-backup-warning">{automaticBackupReason}</span>
            )}
          </dd>
        </div>
        <div className="database-backup-metric">
          <dt>Retention</dt>
          <dd>{loading ? "Loading…" : !data ? "Unavailable" : data.retention.cleanupEnabled ? "Active" : "Not active"}
            <details className="database-backup-policy">
              <summary>View proposed policy</summary>
              <div>
                <p>Weekly backup: Friday at <strong>7:00 PM Asia/Manila</strong>.</p>
                <p>Keep the four most recent successful weekly copies and three monthly archives.</p>
                <p>Manual backups are retained separately for a proposed 30 days. Cleanup stays disabled until approved.</p>
                <p>{data?.retention?.cleanupEnabled ? "Cleanup is enabled." : "Cleanup is disabled."} Automatic scheduling also requires runtime verification, a restore test, and cost approval.</p>
              </div>
            </details>
          </dd>
        </div>
      </dl>

      <div className="database-backup-history">
        <h3 id="database-backup-history-title">Backup history</h3>
        <div className="database-backup-table-wrap" role="region" aria-labelledby="database-backup-history-title" tabIndex={0}>
          <table className="database-backup-table">
            <thead><tr><th scope="col">Date &amp; time</th><th scope="col">Type</th><th scope="col">Result</th><th scope="col">Size</th><th scope="col" aria-label="Actions"></th></tr></thead>
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
        <p id="database-backup-download-reason" className="database-backup-note">
          {completedBackupsExist && !data?.canDownload ? downloadReason : "Only completed backups can be downloaded."}
        </p>
      </div>
    </div>
  );
}
