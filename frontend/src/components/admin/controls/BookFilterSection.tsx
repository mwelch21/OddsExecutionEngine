import { useEffect, useRef, useState } from "react";
import { getBookFilter, putBookFilter, type BookFilter } from "../../../lib/adminApi";
import { AdminPanel } from "../AdminPanel";
import { Button } from "../../primitives";

/**
 * Allowed books (#136): the sportsbooks the operator can bet at.
 *
 * Quotes from other books are still pulled and stored; the line board, the
 * events list, recommendations and watches use only the allowed ones. No checks
 * means all books. Options are the books seen in stored quotes, a DB read.
 *
 * Checking moves the draft only; Save sends it. Saving re-evaluates nothing: the
 * next refresh or new watch uses the new list, and fired alerts stay as they are.
 */
export function BookFilterSection() {
  const [status, setStatus] = useState<BookFilter | null>(null);
  const [draft, setDraft] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = useRef(false);

  useEffect(() => {
    let cancelled = false;
    getBookFilter()
      .then((response) => {
        if (cancelled) return;
        setStatus(response);
        if (!dirty.current) setDraft(response.sportsbooks);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const held = status?.sportsbooks ?? null;
  const changed = held != null && !sameBooks(draft, held);
  // A held book that no stored quote has any more still shows, so it can be unchecked.
  const available = status?.available_sportsbooks ?? [];
  const stale = [...new Set([...(held ?? []), ...draft])].filter((book) => !available.includes(book));

  function toggle(book: string) {
    dirty.current = true;
    setDraft((current) =>
      current.includes(book) ? current.filter((item) => item !== book) : [...current, book].sort()
    );
  }

  function commit() {
    if (!changed || saving) return;
    const sent = draft;
    setSaving(true);
    putBookFilter(sent)
      .then((saved) => {
        setStatus(saved);
        setDraft(saved.sportsbooks);
        dirty.current = false;
        setError(null);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Save failed");
      })
      .finally(() => setSaving(false));
  }

  return (
    <AdminPanel title="Allowed books">
      <p className="admin-muted">
        Only these books are shown, ranked and used to fire a watch. Every book is still pulled and
        stored, at no extra credit cost. Saving re-checks nothing: the next refresh or new watch uses
        the new list.
      </p>
      <fieldset className="admin-focus" disabled={status == null || saving} aria-busy={saving}>
        <legend className="admin-slider-label">
          <span>Books</span>
          <strong>{held == null ? "…" : booksLabel(held)}</strong>
          {changed && <span className="admin-muted">(unsaved)</span>}
        </legend>
        <div className="admin-focus-row">
          <div className="admin-focus-options">
            {available.map((book) => (
              <label key={book} className="admin-focus-option">
                <input type="checkbox" checked={draft.includes(book)} onChange={() => toggle(book)} />
                {book}
              </label>
            ))}
            {stale.map((book) => (
              <label key={book} className="admin-focus-option">
                <input type="checkbox" checked={draft.includes(book)} onChange={() => toggle(book)} />
                {`${book} (no stored quotes)`}
              </label>
            ))}
            {status != null && available.length === 0 && stale.length === 0 && (
              <span className="admin-muted">No stored quotes yet. Refresh a sport to list its books.</span>
            )}
          </div>
          <Button
            type="button"
            variant="secondary"
            disabled={status == null || !changed || saving}
            aria-busy={saving}
            onClick={commit}
          >
            Save
          </Button>
        </div>
      </fieldset>
      {error && <p className="admin-warn">{error}</p>}
    </AdminPanel>
  );
}

export function booksLabel(books: string[]) {
  return books.length === 0 ? "All books" : books.join(", ");
}

function sameBooks(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const sortedRight = [...right].sort();
  return [...left].sort().every((book, index) => book === sortedRight[index]);
}
