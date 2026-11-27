import type { EventStatus, LinePhase } from "../lib/api";

/** Marks an event the provider still offers after its start. */
export function LiveBadge({ status }: { status: EventStatus }) {
  if (status !== "live") return null;
  return (
    <span className="live-badge" title="Started, and the provider still offers it">
      <span className="live-dot" aria-hidden="true" />
      Live
    </span>
  );
}

/**
 * Says which kind of line a quote is on a live board. A pre-game row a book left
 * behind at kickoff cannot fill, so it is labelled rather than passed off as live.
 */
export function LinePhaseBadge({ phase }: { phase: LinePhase | null }) {
  if (phase === "live") {
    return (
      <span className="live-badge live-badge-small" title="Pulled while the event was live">
        <span className="live-dot" aria-hidden="true" />
        Live line
      </span>
    );
  }
  return (
    <span className="phase-badge" title="Pulled before kickoff; cannot fill now">
      Pre-game
    </span>
  );
}
