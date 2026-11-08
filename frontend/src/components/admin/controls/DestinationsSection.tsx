import { useEffect, useRef, useState } from "react";
import { ageLabel } from "../../../lib/format";
import {
  listDestinations,
  removeDestination,
  sendTestNotification,
  updateDestination,
  type Destination
} from "../../../lib/push";
import { Button, Pill } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

const CHANNEL_LABELS: Record<Destination["channel"], string> = { web_push: "Web Push" };

type DestinationStatus = "active" | "user_removed" | "gone";

const STATUS: Record<DestinationStatus, { label: string; tone: "good" | "neutral" | "warn" }> = {
  active: { label: "Active", tone: "good" },
  user_removed: { label: "Removed", tone: "neutral" },
  gone: { label: "Gone", tone: "warn" }
};

/**
 * The operator's devices (#70): label, channel, status and last delivery, with
 * Test, Rename, Remove and Re-enable. Remove is a soft-disable, so history stays.
 * A gone device cannot be re-enabled here; it needs a fresh subscription.
 */
export function DestinationsSection() {
  const [destinations, setDestinations] = useState<Destination[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listDestinations()
      .then((loaded) => {
        if (!cancelled) setDestinations(loaded);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function replace(next: Destination) {
    setDestinations((current) =>
      current?.map((destination) => (destination.id === next.id ? next : destination)) ?? null
    );
  }

  return (
    <AdminPanel title="Devices">
      {destinations === null && !error && <p className="admin-muted">Loading…</p>}
      {destinations?.length === 0 && (
        <p className="admin-muted">No devices yet. Enable notifications on a device to add it.</p>
      )}
      {destinations && destinations.length > 0 && (
        <ul className="destination-list">
          {destinations.map((destination) => (
            <DestinationRow
              key={destination.id}
              destination={destination}
              onChange={replace}
            />
          ))}
        </ul>
      )}
      {error && <p className="admin-warn">{error}</p>}
    </AdminPanel>
  );
}

function DestinationRow({
  destination,
  onChange
}: {
  destination: Destination;
  onChange: (next: Destination) => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(destination.label);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; warn: boolean } | null>(null);
  // Escape unmounts the focused input, and a blur fired on the way out must not save.
  const cancelled = useRef(false);
  const status: DestinationStatus = destination.active
    ? "active"
    : (destination.disabled_reason ?? "user_removed");

  async function run(action: () => Promise<Destination | void>, done?: string) {
    setBusy(true);
    setNote(null);
    try {
      const next = await action();
      if (next) onChange(next);
      if (done) setNote({ text: done, warn: false });
    } catch (reason) {
      setNote({ text: reason instanceof Error ? reason.message : "Failed", warn: true });
    } finally {
      setBusy(false);
    }
  }

  function saveLabel() {
    const label = draft.trim();
    setRenaming(false);
    if (cancelled.current || !label || label === destination.label) {
      setDraft(destination.label);
      return;
    }
    void run(() => updateDestination(destination.id, { label }));
  }

  return (
    <li className="destination-row">
      <div className="destination-heading">
        {renaming ? (
          <input
            className="destination-label-input"
            aria-label="Device name"
            value={draft}
            maxLength={128}
            autoFocus
            onChange={(event) => setDraft(event.target.value)}
            onBlur={saveLabel}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
              if (event.key === "Escape") {
                cancelled.current = true;
                setDraft(destination.label);
                setRenaming(false);
              }
            }}
          />
        ) : (
          <strong>{destination.label}</strong>
        )}
        <Pill tone={STATUS[status].tone}>{STATUS[status].label}</Pill>
      </div>
      <p className="admin-muted">
        {CHANNEL_LABELS[destination.channel]} · Last delivered{" "}
        {ageLabel(destination.last_delivered_at) ?? "never"}
      </p>
      {status === "gone" && (
        <p className="admin-warn">
          The push service rejected this device. Enable notifications on it again to resubscribe.
        </p>
      )}
      <div className="admin-row">
        {destination.active && (
          <Button
            disabled={busy}
            onClick={() => void run(() => sendTestNotification(destination.id), "Test sent")}
          >
            Test
          </Button>
        )}
        <Button
          disabled={busy || renaming}
          onClick={() => {
            cancelled.current = false;
            setDraft(destination.label);
            setRenaming(true);
          }}
        >
          Rename
        </Button>
        {destination.active && (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => void run(() => removeDestination(destination.id))}
          >
            Remove
          </Button>
        )}
        {status === "user_removed" && (
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => void run(() => updateDestination(destination.id, { active: true }))}
          >
            Re-enable
          </Button>
        )}
      </div>
      {note && <p className={note.warn ? "admin-warn" : "admin-muted"}>{note.text}</p>}
    </li>
  );
}
