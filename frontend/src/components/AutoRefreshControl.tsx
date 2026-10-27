import { useEffect, useRef, useState } from "react";
import { getAutoRefresh, putAutoRefresh, type AutoRefresh } from "../lib/api";
import { ageLabel } from "../lib/format";
import { Button } from "./primitives";

const INTERVAL_CHOICES = [1, 2, 5, 10, 15, 30, 60];

/**
 * The Admin view's Auto-Refresh switch (ADR-016, #60 Variant A).
 *
 * It drives `GET/PUT /auto-refresh` only. Nothing here refreshes or polls: the
 * worker does, and only while the switch is on and a watch needs fresh lines.
 * The status is read when the control mounts and each time the popover opens.
 */
export function AutoRefreshControl() {
  const [status, setStatus] = useState<AutoRefresh | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    getAutoRefresh()
      .then((response) => {
        if (!cancelled) setStatus(response);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Close on a click outside, so the popover behaves like one.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  async function toggleOpen() {
    const opening = !open;
    setOpen(opening);
    if (!opening) return;
    try {
      setStatus(await getAutoRefresh());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unavailable");
    }
  }

  async function save(change: Partial<Pick<AutoRefresh, "enabled" | "interval_minutes">>) {
    if (!status || saving) return;
    setSaving(true);
    try {
      setStatus(
        await putAutoRefresh({
          enabled: change.enabled ?? status.enabled,
          interval_minutes: change.interval_minutes ?? status.interval_minutes,
          quota_floor: status.quota_floor
        })
      );
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const enabled = status?.enabled ?? false;
  const outcome = status?.last_outcome ?? null;

  return (
    <div className="auto-refresh" ref={rootRef}>
      <button
        type="button"
        className={enabled ? "auto-refresh-switch on" : "auto-refresh-switch"}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => void toggleOpen()}
      >
        <span className="dot" />
        Auto-Refresh {status ? (enabled ? "on" : "off") : "…"}
      </button>

      {open && (
        <div className="auto-refresh-popover" role="dialog" aria-label="Auto-Refresh">
          <div className="auto-refresh-row">
            <strong>Auto-Refresh</strong>
            <Button
              variant={enabled ? "danger" : "primary"}
              disabled={!status || saving}
              onClick={() => void save({ enabled: !enabled })}
            >
              {enabled ? "Turn off" : "Turn on"}
            </Button>
          </div>
          <p className="auto-refresh-muted">
            {enabled
              ? "Refreshes each sport with an active watch about once per interval. Idle when nothing is watched."
              : "Off. Nothing refreshes on its own; manual refresh still works."}
          </p>

          <label className="auto-refresh-row">
            Every
            <select
              value={status?.interval_minutes ?? 5}
              disabled={!status || saving}
              onChange={(event) => void save({ interval_minutes: Number(event.target.value) })}
            >
              {INTERVAL_CHOICES.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes} min
                </option>
              ))}
            </select>
          </label>
          <p className="auto-refresh-muted">
            ~3 credits per refresh per watched sport.
          </p>

          <p className={outcome?.status === "failed" ? "auto-refresh-warn" : "auto-refresh-muted"}>
            {outcomeLabel(outcome)}
          </p>
          {error && <p className="auto-refresh-warn">{error}</p>}
        </div>
      )}
    </div>
  );
}

function outcomeLabel(outcome: AutoRefresh["last_outcome"]) {
  if (!outcome) return "Last refresh: none yet";
  const when = ageLabel(outcome.at) ?? "at an unknown time";
  if (outcome.status === "failed") {
    return `Last refresh failed · ${outcome.sport} · ${when}${outcome.error ? ` · ${outcome.error}` : ""}`;
  }
  return `Last refresh · ${outcome.sport} · ${outcome.events_refreshed} events · ${when}`;
}
