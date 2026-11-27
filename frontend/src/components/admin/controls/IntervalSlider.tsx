import { useEffect, useRef, useState } from "react";
import { Button } from "../../primitives";

/** Credits per sport-wide pull: `h2h,spreads,totals` x `us`. */
const CREDITS_PER_PULL = 3;

/** Projected credits per hour for one sport refreshed every `minutes`. */
export function creditsPerHour(minutes: number) {
  return Math.round((CREDITS_PER_PULL * 60) / minutes);
}

/**
 * A 1-60 minute slider that commits only on Enter or Save (#128).
 *
 * Dragging moves the draft and its credits projection, nothing else: no request
 * is sent until the operator presses Enter on the slider or clicks Save. While a
 * draft is unsaved, a server value arriving never replaces it.
 */
export function IntervalSlider({
  label,
  value,
  min,
  max,
  disabled,
  onCommit
}: {
  label: string;
  value: number | null;
  min: number;
  max: number;
  disabled: boolean;
  /** Resolves `true` once the server accepts the value. */
  onCommit: (value: number) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState(value ?? min);
  const [held, setHeld] = useState(value);
  const [saving, setSaving] = useState(false);
  const dirty = useRef(false);

  useEffect(() => {
    setHeld(value);
    if (!dirty.current && value != null) setDraft(value);
  }, [value]);

  const changed = held != null && draft !== held;

  function commit() {
    if (!changed || saving) return;
    const sent = draft;
    setSaving(true);
    void onCommit(sent).then((accepted) => {
      setSaving(false);
      if (accepted) {
        setHeld(sent);
        dirty.current = false;
      }
    });
  }

  const id = `interval-${label.toLowerCase()}`;
  return (
    <div className="admin-slider">
      <label htmlFor={id} className="admin-slider-label">
        <span>{label}</span>
        <strong>{value == null ? "…" : `${draft} min`}</strong>
        <span className="admin-muted">~{creditsPerHour(draft)} credits/hr per sport</span>
      </label>
      <div className="admin-slider-row">
        <input
          id={id}
          type="range"
          min={min}
          max={max}
          step={1}
          value={draft}
          disabled={disabled}
          aria-valuetext={`${draft} minutes, about ${creditsPerHour(draft)} credits per hour`}
          onChange={(event) => {
            dirty.current = true;
            setDraft(Number(event.target.value));
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
          }}
        />
        <Button
          type="button"
          variant="secondary"
          disabled={disabled || !changed || saving}
          aria-busy={saving}
          onClick={commit}
        >
          Save
        </Button>
      </div>
    </div>
  );
}
