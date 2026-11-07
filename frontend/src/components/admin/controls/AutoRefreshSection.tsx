import { useEffect, useRef, useState } from "react";
import { getAutoRefresh, putAutoRefresh, type AutoRefresh, type AutoRefreshSettings } from "../../../lib/adminApi";
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
  // Saves run one at a time, each on the settings the last one returned, so an
  // edit made while another is in flight is sent after it, not dropped.
  const latest = useRef<AutoRefresh | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    let cancelled = false;
    getAutoRefresh()
      .then((response) => {
        if (cancelled) return;
        latest.current = response;
        setStatus(response);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /**
   * `change` may read the settings as they stand once earlier saves land.
   * Resolves `true` once the server accepts it, `false` if it fails.
   */
  function save(
    change: Partial<AutoRefreshSettings> | ((current: AutoRefresh) => Partial<AutoRefreshSettings>)
  ): Promise<boolean> {
    const step = queue.current.then(async () => {
      const current = latest.current;
      if (!current) return false;
      setSaving(true);
      try {
        const next = await putAutoRefresh({
          enabled: current.enabled,
          interval_minutes: current.interval_minutes,
          quota_floor: current.quota_floor,
          ...(typeof change === "function" ? change(current) : change)
        });
        latest.current = next;
        setStatus(next);
        setError(null);
        return true;
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Save failed");
        return false;
      } finally {
        setSaving(false);
      }
    });
    queue.current = step.then(() => undefined);
    return step;
  }

  const enabled = status?.enabled ?? false;
  const paused = status?.paused ?? false;
  // Nothing is disabled while saving. Disabling a focused field blurs it, and a
  // blur's save would disable the switch before a click on it lands; the queue
  // orders them instead.
  const loaded = status !== null;
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
          aria-busy={saving}
          disabled={!loaded}
          onClick={() => void save((current) => ({ enabled: !current.enabled }))}
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
          disabled={!loaded}
          onCommit={(value) => save({ interval_minutes: value ?? MIN_INTERVAL })}
          onInvalid={() => setError(`Interval must be ${MIN_INTERVAL}-${MAX_INTERVAL} minutes`)}
        />
        <NumberField
          label="Warn below"
          unit="credits"
          value={status?.quota_floor ?? null}
          // Empty means "derive it": show the floor the server derived.
          placeholder={status?.quota?.floor != null ? `auto · ${status.quota.floor}` : "auto"}
          min={0}
          disabled={!loaded}
          onCommit={(value) => save({ quota_floor: value })}
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
 * While the user is editing, a server value arriving never replaces the draft.
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
  /** Resolves `true` once the server accepts the value. */
  onCommit: (value: number | null) => Promise<boolean>;
  onInvalid: () => void;
}) {
  const [draft, setDraft] = useState(toText(value));
  // Typed but not yet committed: the draft is the user's, not the server's.
  const dirty = useRef(false);
  // The server's acknowledged value, and the one in flight. A failed save
  // clears `pending`, so the same draft can be sent again.
  const held = useRef(value);
  const pending = useRef<number | null | undefined>(undefined);
  useEffect(() => {
    if (dirty.current) return;
    held.current = value;
    setDraft(toText(value));
  }, [value]);

  function commit() {
    dirty.current = false;
    const text = draft.trim();
    const parsed = text === "" && !required ? null : Number(text);
    if (
      parsed !== null &&
      (text === "" || !Number.isInteger(parsed) || parsed < min || (max != null && parsed > max))
    ) {
      setDraft(toText(pending.current !== undefined ? pending.current : held.current));
      onInvalid();
      return;
    }
    if (pending.current !== undefined ? parsed === pending.current : parsed === held.current) {
      return;
    }
    pending.current = parsed;
    void onCommit(parsed).then((accepted) => {
      if (pending.current !== parsed) return; // a later commit owns the field now
      pending.current = undefined;
      if (accepted) held.current = parsed;
    });
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
          onChange={(event) => {
            dirty.current = true;
            setDraft(event.target.value);
          }}
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

function toText(value: number | null) {
  return value == null ? "" : String(value);
}

function outcomeLabel(outcome: AutoRefresh["last_outcome"]) {
  if (!outcome) return "Last refresh: none yet";
  const when = ageLabel(outcome.at) ?? "at an unknown time";
  if (outcome.status === "failed") {
    return `Last refresh failed · ${outcome.sport} · ${when}${outcome.error ? ` · ${outcome.error}` : ""}`;
  }
  return `Last refresh · ${outcome.sport} · ${outcome.events_refreshed} events · ${when}`;
}
