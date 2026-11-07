import { useEffect, useState } from "react";
import { getAutoRefresh, putAutoRefresh, type AutoRefresh } from "../../../lib/adminApi";
import { ageLabel } from "../../../lib/format";
import { AdminPanel } from "../AdminPanel";

const MIN_INTERVAL = 1;
const MAX_INTERVAL = 60;

/**
 * The Auto-Refresh switch, interval and warn-below floor (ADR-016).
 *
 * It drives `GET/PUT /api/v1/admin/auto-refresh` only. Nothing here refreshes or
 * polls: the worker does, and only while the switch is on and a watch needs fresh
 * lines. The status is read once, when the tab opens.
 */
export function AutoRefreshSection() {
  const [status, setStatus] = useState<AutoRefresh | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  async function save(change: Partial<Pick<AutoRefresh, "enabled" | "interval_minutes" | "quota_floor">>) {
    if (!status || saving) return;
    setSaving(true);
    try {
      setStatus(
        await putAutoRefresh({
          enabled: status.enabled,
          interval_minutes: status.interval_minutes,
          quota_floor: status.quota_floor,
          ...change
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
  const paused = status?.paused ?? false;
  const disabled = !status || saving;
  const stateLabel = !status ? "…" : !enabled ? "Off" : paused ? "On · paused, out of credits" : "On";

  return (
    <AdminPanel
      title="Auto-Refresh"
      actions={
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label="Auto-Refresh"
          className={enabled ? "admin-switch on" : "admin-switch"}
          disabled={disabled}
          onClick={() => void save({ enabled: !enabled })}
        >
          <span className="admin-switch-thumb" />
          {stateLabel}
        </button>
      }
    >
      <p className="admin-muted">
        {enabled
          ? "Refreshes each sport with an active watch about once per interval. Idle when nothing is watched."
          : "Off. Nothing refreshes on its own; manual refresh still works."}
      </p>
      {enabled && paused && (
        <p className="admin-warn">
          Paused: out of credits. Stays on and resumes by itself once credits return.
        </p>
      )}

      <div className="admin-form">
        <NumberField
          label="Every"
          unit="min"
          value={status?.interval_minutes ?? null}
          min={MIN_INTERVAL}
          max={MAX_INTERVAL}
          required
          disabled={disabled}
          onCommit={(value) => void save({ interval_minutes: value ?? MIN_INTERVAL })}
          onInvalid={() => setError(`Interval must be ${MIN_INTERVAL}-${MAX_INTERVAL} minutes`)}
        />
        <NumberField
          label="Warn below"
          unit="credits"
          value={status?.quota_floor ?? null}
          // Empty means "derive it": show the floor the server derived.
          placeholder={status?.quota?.floor != null ? `auto · ${status.quota.floor}` : "auto"}
          min={0}
          disabled={disabled}
          onCommit={(value) => void save({ quota_floor: value })}
          onInvalid={() => setError("Warn-below floor must be 0 or more credits")}
        />
      </div>
      <p className="admin-muted">
        ~3 credits per refresh per watched sport. Leave the floor empty to warn below 10% of
        the plan.
      </p>

      <p className={status?.last_outcome?.status === "failed" ? "admin-warn" : "admin-muted"}>
        {outcomeLabel(status?.last_outcome ?? null)}
      </p>
      {error && <p className="admin-warn">{error}</p>}
    </AdminPanel>
  );
}

/**
 * A whole-number input that saves on blur or Enter, not on every keystroke.
 * An empty optional field commits `null`; a bad value reverts and reports.
 */
function NumberField({
  label,
  unit,
  value,
  placeholder,
  min,
  max,
  required = false,
  disabled,
  onCommit,
  onInvalid
}: {
  label: string;
  unit: string;
  value: number | null;
  placeholder?: string;
  min: number;
  max?: number;
  required?: boolean;
  disabled: boolean;
  onCommit: (value: number | null) => void;
  onInvalid: () => void;
}) {
  const [draft, setDraft] = useState(value == null ? "" : String(value));
  useEffect(() => setDraft(value == null ? "" : String(value)), [value]);

  function commit() {
    const text = draft.trim();
    if (text === "" && !required) {
      if (value !== null) onCommit(null);
      return;
    }
    const parsed = Number(text);
    if (text === "" || !Number.isInteger(parsed) || parsed < min || (max != null && parsed > max)) {
      setDraft(value == null ? "" : String(value));
      onInvalid();
      return;
    }
    if (parsed !== value) onCommit(parsed);
  }

  return (
    <label className="admin-field">
      {label}
      <span className="target-input">
        <input
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          value={draft}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
      </span>
      {unit}
    </label>
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
