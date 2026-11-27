import { useEffect, useRef, useState } from "react";
import type { SupportedSport } from "../../../lib/api";
import { Button } from "../../primitives";

/**
 * The sport focus: a multi-select of catalog sports that commits only on Save (#132).
 *
 * Checking or unchecking moves the draft, nothing else: no request is sent until
 * the operator clicks Save. While a draft is unsaved, a server value arriving
 * never replaces it. While its save is in flight the checkboxes are locked, so
 * the draft cannot move away from what was sent. No checks means no focus.
 */
export function SportFocusPicker({
  sports,
  value,
  disabled,
  onCommit
}: {
  sports: SupportedSport[];
  /** The stored focus; `null` while loading. */
  value: string[] | null;
  disabled: boolean;
  /** Resolves `true` once the server accepts the value. */
  onCommit: (value: string[]) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<string[]>(value ?? []);
  const [held, setHeld] = useState<string[] | null>(value);
  const [saving, setSaving] = useState(false);
  const dirty = useRef(false);

  useEffect(() => {
    setHeld(value);
    if (!dirty.current && value != null) setDraft(value);
  }, [value]);

  const changed = held != null && !sameKeys(draft, held);

  function toggle(key: string) {
    dirty.current = true;
    setDraft((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key].sort()
    );
  }

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

  return (
    <fieldset className="admin-focus" disabled={disabled || saving} aria-busy={saving}>
      <legend className="admin-slider-label">
        <span>Sport focus</span>
        <strong>{held == null ? "…" : focusLabel(held, sports)}</strong>
        {changed && <span className="admin-muted">(unsaved)</span>}
      </legend>
      <div className="admin-focus-row">
        <div className="admin-focus-options">
          {sports.map((sport) => (
            <label key={sport.key} className="admin-focus-option">
              <input
                type="checkbox"
                checked={draft.includes(sport.key)}
                onChange={() => toggle(sport.key)}
              />
              {sportLabel(sport.key, sports)}
            </label>
          ))}
          {sports.length === 0 && <span className="admin-muted">No sports in the catalog.</span>}
        </div>
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
    </fieldset>
  );
}

/** A catalog key as the operator reads it: the league, else the sport, else the key. */
export function sportLabel(key: string, sports: SupportedSport[]) {
  const sport = sports.find((entry) => entry.key === key);
  return sport ? (sport.league ?? sport.sport) : key;
}

export function focusLabel(keys: string[], sports: SupportedSport[]) {
  return keys.length === 0 ? "All sports" : keys.map((key) => sportLabel(key, sports)).join(", ");
}

function sameKeys(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const sortedRight = [...right].sort();
  return [...left].sort().every((key, index) => key === sortedRight[index]);
}
