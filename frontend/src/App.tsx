import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, CheckCircle2, RadioTower, TrendingUp } from "lucide-react";
import {
  cancelWatch,
  createWatch,
  getLineBoard,
  getOpportunity,
  getRecommendation,
  listEvents,
  listSports,
  listWatches,
  NotFoundError,
  refreshSport,
  type EventPage,
  type LineBoard as LineBoardData,
  type LineBoardMarket,
  type Opportunity,
  type Recommendation,
  type SupportedSport,
  type WatchIntent
} from "./lib/api";
import { type DeepLink, pushDeepLink, readDeepLink, replaceDeepLink } from "./lib/deepLink";
import { formatAmerican, formatLine, marketLabel, matchupLabel } from "./lib/format";
import { AutoRefreshControl } from "./components/AutoRefreshControl";
import { EventList } from "./components/EventList";
import { LineBoard } from "./components/LineBoard";
import { OpportunityBanner } from "./components/OpportunityBanner";
import { PushToggle } from "./components/PushToggle";
import { WatchPanel } from "./components/WatchPanel";
import { Button, Panel, Pill } from "./components/primitives";

type LoadState = "idle" | "loading" | "ready" | "error";

/**
 * Client-side courtesy gate on the one call that spends credits.
 *
 * This is not a guarantee: cooldown state lives in one browser and knows
 * nothing about anyone else's click. It stops a double-click, not a second
 * user. The server-side floor is the real control (#25).
 */
const REFRESH_COOLDOWN_SECONDS = 15;

export function App() {
  const [sports, setSports] = useState<SupportedSport[]>([]);
  const [refreshSportKey, setRefreshSportKey] = useState("");
  const [league, setLeague] = useState<string | null>(null);
  const [includeStarted, setIncludeStarted] = useState(false);
  const [page, setPage] = useState(1);
  const [eventPage, setEventPage] = useState<EventPage | null>(null);

  // Seeded from the URL so a notification link or a reload lands on its screen.
  const [selectedEventId, setSelectedEventId] = useState<string | null>(
    () => readDeepLink().eventId
  );
  const [board, setBoard] = useState<LineBoardData | null>(null);
  const [boardLoading, setBoardLoading] = useState(false);

  const [pinnedOpportunityId, setPinnedOpportunityId] = useState<string | null>(
    () => readDeepLink().opportunityId
  );
  const [opportunity, setOpportunity] = useState<Opportunity | null>(null);
  const [opportunityNote, setOpportunityNote] = useState<string | null>(null);

  const [watches, setWatches] = useState<WatchIntent[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [message, setMessage] = useState("Ready");

  const [refreshing, setRefreshing] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  // Guards against a second click landing between the click and the state
  // update React has not flushed yet.
  const refreshInFlight = useRef(false);

  const [watchDraft, setWatchDraft] = useState<LineBoardMarket | null>(null);
  const [watchTarget, setWatchTarget] = useState("");
  const [watchCheck, setWatchCheck] = useState<Recommendation | null>(null);

  useEffect(() => {
    let cancelled = false;
    listSports()
      .then((response) => {
        if (cancelled) return;
        setSports(response.sports);
        setRefreshSportKey((current) => current || (response.sports[0]?.key ?? ""));
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setMessage(error instanceof Error ? error.message : "Unable to load sports");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadEvents = useCallback(async () => {
    setLoadState("loading");
    try {
      const response = await listEvents({ league, includeStarted, page });
      setEventPage(response);
      setLoadState("ready");
      setMessage(`${response.total_events} events stored`);
    } catch (error) {
      setLoadState("error");
      setMessage(error instanceof Error ? error.message : "Unable to load events");
    }
  }, [league, includeStarted, page]);

  // Navigation only. Nothing here contacts the provider, and there is no timer.
  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const loadBoard = useCallback(async (eventId: string) => {
    setBoardLoading(true);
    try {
      const [boardResponse, watchResponse] = await Promise.all([
        getLineBoard(eventId),
        listWatches(eventId)
      ]);
      setBoard(boardResponse);
      setWatches(watchResponse.watch_intents);
      setMessage(`${boardResponse.markets.length} markets on the board`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load line board");
    } finally {
      setBoardLoading(false);
    }
  }, []);

  // Keyed on the event alone, so pinning or dismissing an opportunity keeps the board.
  useEffect(() => {
    setBoard(null);
    if (selectedEventId) void loadBoard(selectedEventId);
  }, [selectedEventId, loadBoard]);

  // A DB read, like the board: opening a notification spends no credits.
  useEffect(() => {
    setOpportunity(null);
    setOpportunityNote(null);
    if (!selectedEventId || !pinnedOpportunityId) return;
    let cancelled = false;
    getOpportunity(pinnedOpportunityId)
      .then((response) => {
        if (cancelled) return;
        if (response.event_id !== selectedEventId) {
          setOpportunityNote("That opportunity belongs to another event. Showing this board only.");
        } else if (!response.is_valid) {
          setOpportunityNote(
            `Opportunity no longer valid (${invalidReasonLabel(response.invalid_reason)}). ` +
              `It was ${formatAmerican(response.best_price)} @ ${response.best_sportsbook} ` +
              `against a ${formatAmerican(response.target_price)} target.`
          );
        } else {
          setOpportunity(response);
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setOpportunityNote(
          error instanceof NotFoundError
            ? "Opportunity not found. Showing this board only."
            : "Could not load the opportunity. Showing this board only."
        );
      });
    return () => {
      cancelled = true;
    };
  }, [selectedEventId, pinnedOpportunityId]);

  const applyLink = useCallback(
    (link: DeepLink) => {
      setSelectedEventId(link.eventId);
      setPinnedOpportunityId(link.opportunityId);
      if (!link.eventId) {
        setWatches([]);
        void loadEvents();
      }
    },
    [loadEvents]
  );

  // Back and Forward retrace the entries pushed below.
  useEffect(() => {
    const onPopState = () => applyLink(readDeepLink());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [applyLink]);

  function handleSelectEvent(eventId: string) {
    const link = { eventId, opportunityId: null };
    pushDeepLink(link);
    applyLink(link);
  }

  function handleBack() {
    const link = { eventId: null, opportunityId: null };
    pushDeepLink(link);
    applyLink(link);
  }

  function handleDismissOpportunity() {
    replaceDeepLink({ eventId: selectedEventId, opportunityId: null });
    setPinnedOpportunityId(null);
  }

  async function handleRefresh() {
    if (refreshInFlight.current || cooldown > 0 || !refreshSportKey) return;
    refreshInFlight.current = true;
    setRefreshing(true);
    setMessage(`Pulling ${refreshSportKey} from the provider`);
    try {
      const result = await refreshSport(refreshSportKey);
      setMessage(`Refreshed ${result.events_refreshed} events for ${result.sport}`);
      setCooldown(REFRESH_COOLDOWN_SECONDS);
      await loadEvents();
      if (selectedEventId) await loadBoard(selectedEventId);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Refresh failed");
    } finally {
      refreshInFlight.current = false;
      setRefreshing(false);
    }
  }

  async function handleCreateWatch(market: LineBoardMarket, targetPrice: number) {
    if (!selectedEventId) return;
    try {
      await createWatch({
        event_id: selectedEventId,
        market_type: market.market_type,
        selection: market.selection,
        line: market.line,
        target_price: targetPrice
      });
      const watchResponse = await listWatches(selectedEventId);
      setWatches(watchResponse.watch_intents);
      setWatchDraft(null);
      setWatchCheck(null);
      setMessage(`Watch created: ${market.selection} at ${formatAmerican(targetPrice)}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Watch creation failed");
    }
  }

  async function handleCancelWatch(id: string) {
    if (!selectedEventId) return;
    try {
      await cancelWatch(id);
      const watchResponse = await listWatches(selectedEventId);
      setWatches(watchResponse.watch_intents);
      setMessage("Watch cancelled");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Watch cancel failed");
    }
  }

  function openWatchModal(market: LineBoardMarket) {
    setWatchDraft(market);
    setWatchTarget(String(market.best_price ?? 0));
    setWatchCheck(null);
  }

  /** Free, DB-backed: answers "is this fillable right now" before arming a watch. */
  async function checkFillability(market: LineBoardMarket, targetPrice: number) {
    if (!selectedEventId || Number.isNaN(targetPrice)) return;
    try {
      setWatchCheck(
        await getRecommendation({
          event_id: selectedEventId,
          market_type: market.market_type,
          selection: market.selection,
          line: market.line,
          target_price: targetPrice
        })
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Fillability check failed");
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">
            <TrendingUp size={23} />
          </div>
          <div>
            <h1>OddsCafe</h1>
            <p>Fillability, best book, nearest miss, watch signals.</p>
          </div>
        </div>
        <div className="topbar-status">
          <Pill tone={loadState === "error" ? "warn" : "good"}>
            <RadioTower size={14} />
            {loadState}
          </Pill>
          <Pill>
            <Bell size={14} />
            {watches.length} watches
          </Pill>
          <AutoRefreshControl />
          <PushToggle />
        </div>
      </header>

      <main className="workspace">
        <section className="hero-strip">
          <div>
            <Pill tone="accent">{selectedEventId ? "Line board" : "Event browser"}</Pill>
            <h2>{board ? matchupLabel(board.event) : "Stored events"}</h2>
            <p>{message}</p>
          </div>
        </section>

        {selectedEventId && opportunity && (
          <OpportunityBanner
            opportunity={opportunity}
            board={board}
            onDismiss={handleDismissOpportunity}
          />
        )}
        {selectedEventId && opportunityNote && (
          <div className="opportunity-note" role="status">
            <p>{opportunityNote}</p>
            <Button variant="ghost" title="Dismiss" onClick={handleDismissOpportunity}>
              x
            </Button>
          </div>
        )}

        <div className="content-grid">
          {selectedEventId ? (
            <LineBoard
              board={board}
              loading={boardLoading}
              onBack={handleBack}
              onOpenWatch={openWatchModal}
              pinnedMarket={opportunity}
            />
          ) : (
            <EventList
              page={eventPage}
              sports={sports}
              league={league}
              includeStarted={includeStarted}
              refreshSport={refreshSportKey}
              loading={loadState === "loading"}
              refreshing={refreshing}
              cooldown={cooldown}
              onLeagueChange={(value) => {
                setLeague(value);
                setPage(1);
              }}
              onIncludeStartedChange={(value) => {
                setIncludeStarted(value);
                setPage(1);
              }}
              onRefreshSportChange={setRefreshSportKey}
              onRefresh={() => void handleRefresh()}
              onPageChange={setPage}
              onSelectEvent={handleSelectEvent}
            />
          )}

          <aside className="side-rail">
            {selectedEventId && (
              <WatchPanel watches={watches} onCancel={(id) => void handleCancelWatch(id)} />
            )}
            <Panel className="execution-note">
              <CheckCircle2 size={22} />
              <div>
                <strong>Browsing is free</strong>
                <p>
                  Events and boards are read from the database. Only the refresh control
                  contacts the provider, and it is billed per market per region.
                </p>
              </div>
            </Panel>
          </aside>
        </div>
      </main>

      {watchDraft && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setWatchDraft(null)}>
          <section
            className="watch-modal"
            role="dialog"
            aria-modal="true"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-heading">
              <div>
                <Pill tone="accent">Create watch</Pill>
                <h2>
                  {marketLabel(watchDraft)} {watchDraft.selection} {formatLine(watchDraft)}
                </h2>
                <p>{board ? matchupLabel(board.event) : ""}</p>
              </div>
              <Button variant="ghost" onClick={() => setWatchDraft(null)}>
                x
              </Button>
            </div>
            <div className="modal-quote-card">
              <div className="modal-current-line">
                <span>Best line now</span>
                <strong>{formatAmerican(watchDraft.best_price)}</strong>
                <small>{watchDraft.best_sportsbook ?? "No book quoting"}</small>
              </div>
              <div className="modal-target-card">
                <span>Desired watch target</span>
                <label className="modal-target-input">
                  Desired odds
                  <input
                    type="number"
                    value={watchTarget}
                    onChange={(event) => setWatchTarget(event.target.value)}
                    onBlur={() => void checkFillability(watchDraft, Number(watchTarget))}
                  />
                </label>
              </div>
            </div>
            {watchCheck && (
              <p className={watchCheck.fillable ? "fill-note good" : "fill-note"}>
                {watchCheck.fillable
                  ? `Fillable now at ${formatAmerican(watchCheck.best_quote?.price)} on ${watchCheck.best_quote?.sportsbook}`
                  : `Not fillable. Nearest miss ${formatAmerican(watchCheck.nearest_miss?.price)} on ${watchCheck.nearest_miss?.sportsbook ?? "no book"}`}
              </p>
            )}
            <p className="modal-copy">
              Watch fires when the deterministic engine finds this market fillable at the
              desired odds or better.
            </p>
            <Button
              variant="primary"
              className="modal-submit"
              onClick={() => void handleCreateWatch(watchDraft, Number(watchTarget))}
            >
              <Bell size={16} />
              Set price watch
            </Button>
          </section>
        </div>
      )}
    </div>
  );
}

const INVALID_REASONS: Record<string, string> = {
  expired: "expired",
  quote_superseded: "the book has moved since",
  quote_removed: "the book stopped quoting",
  missing_timestamp: "no detection time"
};

function invalidReasonLabel(reason: string | null) {
  return (reason && INVALID_REASONS[reason]) ?? reason ?? "unknown reason";
}
