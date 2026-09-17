import { ChevronLeft, ChevronRight, RefreshCcw } from "lucide-react";
import type { EventPage, SupportedSport } from "../lib/api";
import { formatStart, matchupLabel, summarizeFreshness } from "../lib/format";
import { Button, EmptyState, Pill } from "./primitives";

type Props = {
  page: EventPage | null;
  sports: SupportedSport[];
  league: string | null;
  includeStarted: boolean;
  refreshSport: string;
  loading: boolean;
  refreshing: boolean;
  /** Seconds left on the client-side refresh cooldown; 0 when ready. */
  cooldown: number;
  onLeagueChange: (league: string | null) => void;
  onIncludeStartedChange: (includeStarted: boolean) => void;
  onRefreshSportChange: (sport: string) => void;
  onRefresh: () => void;
  onPageChange: (page: number) => void;
  onSelectEvent: (eventId: string) => void;
};

export function EventList({
  page,
  sports,
  league,
  includeStarted,
  refreshSport,
  loading,
  refreshing,
  cooldown,
  onLeagueChange,
  onIncludeStartedChange,
  onRefreshSportChange,
  onRefresh,
  onPageChange,
  onSelectEvent
}: Props) {
  const leagues = sports
    .map((sport) => sport.league)
    .filter((value): value is string => Boolean(value))
    .sort();

  const refreshLabel = refreshing
    ? "Refreshing"
    : cooldown > 0
      ? `Refresh (${cooldown}s)`
      : "Refresh sport";

  return (
    <section className="event-list">
      <div className="panel-heading">
        <div>
          <Pill tone="accent">Events</Pill>
          <h2>Browse stored events</h2>
          <p>
            Listing is free. Only the refresh below spends upstream credits, billed per
            market per region.
          </p>
        </div>
        <div className="board-actions">
          <label className="select-shell">
            Refresh
            <select
              value={refreshSport}
              onChange={(event) => onRefreshSportChange(event.target.value)}
            >
              {sports.map((sport) => (
                <option key={sport.key} value={sport.key}>
                  {sport.league ?? sport.sport}
                </option>
              ))}
            </select>
          </label>
          <Button
            variant="primary"
            onClick={onRefresh}
            disabled={refreshing || cooldown > 0 || sports.length === 0}
            title={
              cooldown > 0
                ? "Cooling down so a double-click cannot spend twice"
                : "Pull this sport from the provider"
            }
          >
            <RefreshCcw size={16} />
            {refreshLabel}
          </Button>
        </div>
      </div>

      <div className="filter-row">
        <label className="select-shell">
          League
          <select
            value={league ?? ""}
            onChange={(event) => onLeagueChange(event.target.value || null)}
          >
            <option value="">All leagues</option>
            {leagues.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox-shell">
          <input
            type="checkbox"
            checked={includeStarted}
            onChange={(event) => onIncludeStartedChange(event.target.checked)}
          />
          Include started
        </label>
        {page && (
          <span className="result-count">
            {page.total_events} event{page.total_events === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {loading && <div className="loading-note">Loading events</div>}

      {!loading && page && page.events.length === 0 && (
        <EmptyState>
          <RefreshCcw size={22} />
          Nothing stored for this filter yet. Refresh a sport to populate it.
        </EmptyState>
      )}

      <div className="event-stack">
        {page?.events.map((event) => {
          const freshness = summarizeFreshness(event.quotes);
          return (
            <button
              className="event-card"
              key={event.id}
              onClick={() => onSelectEvent(event.id)}
            >
              <div className="event-card-main">
                <span className="league">
                  {event.league ?? event.sport ?? "Unknown league"}
                </span>
                <strong>{matchupLabel(event)}</strong>
                <small>{formatStart(event.starts_at)}</small>
              </div>
              <div className="event-card-freshness">
                <Pill tone={freshness.tone === "warn" ? "warn" : "good"}>
                  {freshness.pulled}
                </Pill>
                <small>{freshness.lines}</small>
                <small>
                  {event.quotes.book_count} book
                  {event.quotes.book_count === 1 ? "" : "s"} ·{" "}
                  {event.quotes.quote_count} quotes
                </small>
                {freshness.unknownNote && (
                  <small className="unknown-note">{freshness.unknownNote}</small>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {page && page.total_pages > 1 && (
        <div className="pager">
          <Button
            variant="ghost"
            disabled={page.page <= 1}
            onClick={() => onPageChange(page.page - 1)}
          >
            <ChevronLeft size={16} />
            Previous
          </Button>
          <span>
            Page {page.page} of {page.total_pages}
          </span>
          <Button
            variant="ghost"
            disabled={page.page >= page.total_pages}
            onClick={() => onPageChange(page.page + 1)}
          >
            Next
            <ChevronRight size={16} />
          </Button>
        </div>
      )}
    </section>
  );
}
