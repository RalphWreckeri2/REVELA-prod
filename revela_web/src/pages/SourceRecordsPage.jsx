import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import DashboardLayout from "../components/DashboardLayout";
import { useAuth } from "../context/authContext";
import { useAppDataRefresh, useSessionDataset } from "../components/useAppDataRefresh";
import { getFlagsRequest } from "../services/api";
import "../styles/SourceRecordsPage.css";

const ORIGINS = {
  detection: "Unlinked Detection Records",
  manual: "Unlinked Manual Records",
  unclassified: "Unclassified Records",
};

export default function SourceRecordsPage() {
  const { token } = useAuth();
  const [params, setParams] = useSearchParams();
  const origin = Object.hasOwn(ORIGINS, params.get("origin")) ? params.get("origin") : "unclassified";
  const page = Math.max(1, Number.parseInt(params.get("page"), 10) || 1);
  const key = `source-records:${origin}:${page}`;
  const [snapshot, setSnapshot, hasResult] = useSessionDataset(key, "list", null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(() => !hasResult);
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), [key]);
  const load = useCallback(async (silent = false) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    if (!silent) setLoading(!hasResult);
    setError("");
    try {
      const result = await getFlagsRequest({ origin, registryLink: "unlinked", page, limit: 20, signal: controller.signal }, token);
      if (controller.signal.aborted) return { ok: false };
      if (!Array.isArray(result?.data) || !Number.isFinite(result?.total)) throw new Error("Invalid records response");
      setSnapshot(result);
      return { ok: true };
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure.message || "Could not load source records");
      return { ok: false };
    } finally {
      if (request.current === controller) { request.current = null; setLoading(false); }
    }
  }, [origin, page, token, hasResult, setSnapshot]);
  const refresh = useAppDataRefresh(key, reason => load(reason === "scheduled"));
  const changePage = next => setParams(previous => {
    const updated = new URLSearchParams(previous);
    updated.set("origin", origin);
    if (next === 1) updated.delete("page"); else updated.set("page", String(next));
    updated.set("registryLink", "unlinked");
    return updated;
  });
  const total = snapshot?.total ?? 0;
  return <DashboardLayout className="source-records-page">
    <header className="source-records-header"><div><h1>{ORIGINS[origin]}</h1>
      <p>One row per unlinked map pin, not a distinct-business census.</p></div>
      <Link to="/home">Back to Overview</Link>
    </header>
    {loading && hasResult && <p role="status">Refreshing records…</p>}
    {error && <p role="alert">{hasResult ? "Showing last loaded records. " : "Records unavailable. "}{error} <button type="button" onClick={refresh}>Retry</button></p>}
    {!hasResult && !error ? <p role="status">Loading records…</p> : error && !hasResult ? null : <>
      <p role="status">{total} matching records · page {page} of {Math.max(1, Math.ceil(total / 20))}</p>
      {snapshot?.data.length === 0 ? <p>No records match this source.</p> : <ul className="source-records-list">
        {(snapshot?.data ?? []).map(record => <li key={record.logID}>
          <Link to={`/map?flag=${record.logID}`}>
            <strong>{record.detectedName || "Unnamed pin"}</strong>
            <span>#{record.logID} · {record.barangayName || "Unknown barangay"} · {record.originSource || "unknown"} ↗</span>
          </Link>
        </li>)}
      </ul>}
      <nav aria-label="Source records pagination" className="source-records-pagination">
        <button type="button" disabled={page <= 1} onClick={() => changePage(page - 1)}>Previous</button>
        <button type="button" disabled={page * 20 >= total} onClick={() => changePage(page + 1)}>Next</button>
      </nav>
    </>}
  </DashboardLayout>;
}
