import { ChevronLeft, ChevronRight, RotateCw } from "lucide-react";
import { useEffect, useState } from "react";
import {
  getRefreshes,
  type RefreshOutcome,
  type RefreshPage,
  type RefreshRecord,
  type RefreshTrigger
} from "../../../lib/adminApi";
import { ageLabel } from "../../../lib/format";
import { Button, EmptyState, Pill } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

const PAGE_SIZE = 25;

/**
 * Every refresh, manual or Auto-Refresh, with its outcome (#103).
 *
 * Reads `GET /api/v1/admin/refreshes`: stored records only, so loading, paging
 * and filtering never refresh anything or spend credits. Failed and refused rows
 * stand out. Read when the tab opens and on Reload; nothing polls.
 */
export function RefreshLogPanel() {
  const [trigger, setTrigger] = useState<RefreshTrigger | "">("");
  const [outcome, setOutcome] = useState<RefreshOutcome | "">("");
  const [page, setPage] = useState(1);
  const [reloads, setReloads] = useState(0);
  const [log, setLog] = useState<RefreshPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getRefreshes({
      trigger: trigger || undefined,
      outcome: outcome || undefined,
      page,
      page_size: PAGE_SIZE
    })
      .then((response) => {
        if (cancelled) return;
        setLog(response);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [trigger, outcome, page, reloads]);

  const filtered = trigger !== "" || outcome !== "";

  return (
    <AdminPanel
      title="Refresh log"
      actions={
        <Button variant="ghost" aria-label="Reload refresh log" onClick={() => setReloads((n) => n + 1)}>
          <RotateCw size={16} />
        </Button>
      }
    >
      <div className="admin-row">
        <label className="select-shell">
          Trigger
          <select
            value={trigger}
            onChange={(event) => {
              setTrigger(event.target.value as RefreshTrigger | "");
              setPage(1);
            }}
          >
            <option value="">All</option>
            <option value="manual">Manual</option>
            <option value="auto">Auto-Refresh</option>
          </select>
        </label>
        <label className="select-shell">
          Outcome
          <select
            value={outcome}
            onChange={(event) => {
              setOutcome(event.target.value as RefreshOutcome | "");
              setPage(1);
            }}
          >
            <option value="">All</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
            <option value="refused">Refused</option>
          </select>
        </label>
        {log && (
          <span className="admin-muted">
            {log.total_items} refresh{log.total_items === 1 ? "" : "es"}
          </span>
        )}
      </div>

      {error && <p className="admin-warn">{error}</p>}
      {!log && !error && <p className="admin-muted">Loading…</p>}
      {log && log.refreshes.length === 0 && (
        <EmptyState>
          {filtered
            ? "No refresh matches these filters."
            : "No refreshes yet. Each manual or Auto-Refresh refresh will show here."}
        </EmptyState>
      )}

      {log && log.refreshes.length > 0 && (
        <ol className="refresh-log">
          {log.refreshes.map((record, index) => (
            <RefreshRow key={`${record.started_at}-${index}`} record={record} />
          ))}
        </ol>
      )}

      {log && log.total_pages > 1 && (
        <div className="pager">
          <Button variant="ghost" disabled={log.page <= 1} onClick={() => setPage(log.page - 1)}>
            <ChevronLeft size={16} />
          </Button>
          <span>
            Page {log.page} of {log.total_pages}
          </span>
          <Button
            variant="ghost"
            disabled={log.page >= log.total_pages}
            onClick={() => setPage(log.page + 1)}
          >
            <ChevronRight size={16} />
          </Button>
        </div>
      )}
    </AdminPanel>
  );
}

function RefreshRow({ record }: { record: RefreshRecord }) {
  const bad = record.outcome !== "succeeded";
  const startedAt = new Date(record.started_at);
  return (
    <li className={`refresh-log-row refresh-log-${record.outcome}`}>
      <div className="refresh-log-main">
        <Pill tone={bad ? "warn" : "good"}>{record.outcome}</Pill>
        <span className="refresh-log-target">
          {record.sport}
          {record.event_id && <span className="admin-muted"> · event {record.event_id}</span>}
        </span>
        <span className="admin-muted">{record.trigger === "auto" ? "Auto-Refresh" : "Manual"}</span>
      </div>
      <div className="refresh-log-meta admin-muted">
        <time dateTime={record.started_at} title={startedAt.toLocaleString()}>
          {ageLabel(record.started_at) ?? record.started_at}
        </time>
        <span>
          {record.events_refreshed} event{record.events_refreshed === 1 ? "" : "s"}
        </span>
        <span>{durationLabel(record)}</span>
        <span title="Credits the upstream call it used spent">{costLabel(record)}</span>
      </div>
      {bad && (record.error_code || record.error) && (
        <p className="admin-warn refresh-log-error">
          {[record.error_code, record.error].filter(Boolean).join(" · ")}
        </p>
      )}
    </li>
  );
}

/** Cost through the linked upstream call; no call, no cost. */
function costLabel(record: RefreshRecord) {
  if (record.credits_spent === null) return "no call";
  return `${record.credits_spent} credit${record.credits_spent === 1 ? "" : "s"}`;
}

function durationLabel(record: RefreshRecord) {
  const ms = new Date(record.finished_at).getTime() - new Date(record.started_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
