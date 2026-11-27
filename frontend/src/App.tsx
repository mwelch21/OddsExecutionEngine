import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bell, CheckCircle2, LineChart, RadioTower, ShieldCheck, TrendingUp } from "lucide-react";
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
  type EventListStatus,
  type EventPage,
  type LineBoard as LineBoardData,
  type LineBoardMarket,
  type Opportunity,
  type Recommendation,
  type SupportedSport,
  type WatchIntent,
  type WatchWindow
} from "./lib/api";
import { getAutoRefresh, onSportFocusSaved } from "./lib/adminApi";
import {
  canonicalizeLocation,
  HOME,
  pushRoute,
  replaceRoute,
  type AdminTab,
  type Route
} from "./lib/deepLink";
import {
  WATCH_WINDOWS,
  formatAmerican,
  formatLine,
  marketLabel,
  matchupLabel,
  windowLabel
} from "./lib/format";
import { AdminView } from "./components/admin/AdminView";
import { AttentionPill } from "./components/admin/systems/AttentionPill";
import { invalidateSystemStatus } from "./components/admin/systems/systemStatus";
import { EventList } from "./components/EventList";
import { LineBoard } from "./components/LineBoard";
import { OpportunityBanner } from "./components/OpportunityBanner";
import { WatchPanel } from "./components/WatchPanel";
import { Button, CollapseToggle, Panel, Pill, useCollapsed } from "./components/primitives";

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
  // Seeded from the URL so a notification link or a reload lands on its screen,
  // after rewriting an old query link or a bare `/admin` to its route.
  const [route, setRoute] = useState<Route>(canonicalizeLocation);
  const selectedEventId = route.view === "event" ? route.eventId : null;
  const pinnedOpportunityId = route.view === "event" ? route.opportunityId : null;
  const adminTab = route.view === "admin" ? route.tab : null;
  const [sports, setSports] = useState<SupportedSport[]>([]);
  const [refreshSportKey, setRefreshSportKey] = useState("");
  const [league, setLeague] = useState<string | null>(null);
  // All is upcoming plus live; ended events never list (#38).
  const [eventStatus, setEventStatus] = useState<EventListStatus>("all");
  const [page, setPage] = useState(1);
  // The stored sport focus (#132), and whether the operator cleared it in this view.
  // Null until the one read on mount settles, so the list does not flash every
  // sport first. Clearing here changes only this view, never the stored focus.
  // `unavailable`: the read failed, so every sport shows, and the view says so.
  const [sportFocus, setSportFocus] = useState<{
    stored: string[];
    cleared: boolean;
    unavailable?: boolean;
  } | null>(null);
  // The latest focus, for the saved-focus listener to compare against.
  const sportFocusRef = useRef(sportFocus);
  sportFocusRef.current = sportFocus;
  // Each events read takes a number; only the newest one may write the page, so a
  // slow, superseded response never overwrites a newer one.
  const eventsRequest = useRef(0);
  const [eventPage, setEventPage] = useState<EventPage | null>(null);

  const [board, setBoard] = useState<LineBoardData | null>(null);
  const [boardLoading, setBoardLoading] = useState(false);

  const [opportunity, setOpportunity] = useState<Opportunity | null>(null);
  const [opportunityNote, setOpportunityNote] = useState<string | null>(null);

  const [watches, setWatches] = useState<WatchIntent[]>([]);
  const [expiredWatches, setExpiredWatches] = useState<WatchIntent[]>([]);
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
  // Empty means "let the server pick from the event's status" (ADR-017).
  const [watchWindow, setWatchWindow] = useState<WatchWindow | "">("");

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

  // Read once: settings only, from the database. If it fails, show every sport.
  // A focus saved in Admin arrives through `onSportFocusSaved`, no polling; it
  // keeps a clear the operator made here, and wins over a mount read still out.
  useEffect(() => {
    let cancelled = false;
    let saved = false;
    const unsubscribe = onSportFocusSaved((stored) => {
      saved = true;
      const current = sportFocusRef.current;
      // An interval or switch save repeats the same focus: keep the state, no reload.
      if (current && !current.unavailable && current.stored.join(",") === stored.join(",")) return;
      setSportFocus({ stored, cleared: current?.cleared ?? false });
      // A new filter: page 2 of the old one may not exist under it.
      setPage(1);
    });
    getAutoRefresh()
      .then((response) => {
        if (!cancelled && !saved) setSportFocus({ stored: response.sport_focus, cleared: false });
      })
      .catch(() => {
        // Fall back to every sport, but not silently: the chip says the focus is unknown.
        if (!cancelled && !saved) setSportFocus({ stored: [], cleared: false, unavailable: true });
      });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  const focusApplied = sportFocus !== null && sportFocus.stored.length > 0 && !sportFocus.cleared;
  const sportKeys = useMemo(
    () => (sportFocus === null ? null : focusApplied ? sportFocus.stored : []),
    [sportFocus, focusApplied]
  );

  const loadEvents = useCallback(async () => {
    if (sportKeys === null) return;
    const request = ++eventsRequest.current;
    setLoadState("loading");
    try {
      const response = await listEvents({ league, sportKeys, status: eventStatus, page });
      if (request !== eventsRequest.current) return;
      setEventPage(response);
      setLoadState("ready");
      setMessage(`${response.total_events} events stored`);
    } catch (error) {
      if (request !== eventsRequest.current) return;
      setLoadState("error");
      setMessage(error instanceof Error ? error.message : "Unable to load events");
    }
  }, [league, sportKeys, eventStatus, page]);

  // Navigation only. Nothing here contacts the provider, and there is no timer.
  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  // The loader for the filter on screen now. Code that awaits first (a refresh)
  // reads it after the await, so a filter changed meanwhile is the one reloaded.
  const loadEventsRef = useRef(loadEvents);
  loadEventsRef.current = loadEvents;

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const loadBoard = useCallback(async (eventId: string) => {
    setBoardLoading(true);
    try {
      const [boardResponse, watchResponse, expiredResponse] = await Promise.all([
        getLineBoard(eventId),
        listWatches(eventId),
        listWatches(eventId, "expired")
      ]);
      setBoard(boardResponse);
      setWatches(watchResponse.watch_intents);
      setExpiredWatches(expiredResponse.watch_intents);
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

  const applyRoute = useCallback(
    (route: Route) => {
      setRoute(route);
      if (route.view !== "event") setWatches([]);
      if (route.view === "home") void loadEvents();
    },
    [loadEvents]
  );

  // Back and Forward retrace the entries pushed below.
  useEffect(() => {
    const onPopState = () => applyRoute(canonicalizeLocation());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [applyRoute]);

  function handleSelectEvent(eventId: string) {
    const route: Route = { view: "event", eventId, opportunityId: null };
    pushRoute(route);
    applyRoute(route);
  }

  function handleBack() {
    pushRoute(HOME);
    applyRoute(HOME);
  }

  function handleOpenAdmin(tab: AdminTab = "systems") {
    const route: Route = { view: "admin", tab };
    pushRoute(route);
    applyRoute(route);
  }

  function handleDismissOpportunity() {
    if (route.view !== "event") return;
    const unpinned: Route = { ...route, opportunityId: null };
    replaceRoute(unpinned);
    setRoute(unpinned);
  }

  async function handleRefresh() {
    if (refreshInFlight.current || cooldown > 0 || !refreshSportKey) return;
    refreshInFlight.current = true;
    setRefreshing(true);
    setMessage(`Pulling ${refreshSportKey} from the provider`);
    try {
      // A refresh, failed or not, can move the provider row and the credits: tell
      // the status readers as soon as it settles, before the browse reads below.
      const result = await refreshSport(refreshSportKey).finally(invalidateSystemStatus);
      setMessage(`Refreshed ${result.events_refreshed} events for ${result.sport}`);
      setCooldown(REFRESH_COOLDOWN_SECONDS);
      await loadEventsRef.current();
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
        target_price: targetPrice,
        // Sent only when picked: the server's policy owns the default.
        ...(watchWindow ? { window: watchWindow } : {})
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
    setWatchWindow("");
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
            <p>{adminTab ? "Admin view" : "Fillability, best book, nearest miss, watch signals."}</p>
          </div>
        </div>
        <div className="topbar-status">
          {/* Operator only. Until auth (#14) every viewer is the operator, as the
              admin router's hook is a no-op; #14 gates this with it. */}
          <AttentionPill
            routeKey={adminTab ?? selectedEventId ?? "home"}
            onOpen={handleOpenAdmin}
          />
          {adminTab ? (
            // Lines always goes Home; a notification can cold-launch here with no history.
            <Button variant="secondary" onClick={handleBack}>
              <LineChart size={15} />
              Lines
            </Button>
          ) : (
            <>
              <Pill tone={loadState === "error" ? "warn" : "good"}>
                <RadioTower size={14} />
                {loadState}
              </Pill>
              <Pill>
                <Bell size={14} />
                {watches.length}
                <span className="topbar-label"> watches</span>
              </Pill>
              <Button
                variant="secondary"
                className="topbar-admin"
                aria-label="Admin view"
                title="Admin view"
                onClick={() => handleOpenAdmin()}
              >
                <ShieldCheck size={15} />
                <span className="topbar-label">Admin view</span>
              </Button>
            </>
          )}
        </div>
      </header>

      {adminTab ? (
        <AdminView tab={adminTab} onSelectTab={handleOpenAdmin} />
      ) : (
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
                status={eventStatus}
                sportFocus={sportFocus?.stored ?? []}
                focusApplied={focusApplied}
                focusUnavailable={sportFocus?.unavailable ?? false}
                refreshSport={refreshSportKey}
                loading={loadState === "loading"}
                refreshing={refreshing}
                cooldown={cooldown}
                onLeagueChange={(value) => {
                  setLeague(value);
                  setPage(1);
                }}
                onStatusChange={(value) => {
                  setEventStatus(value);
                  setPage(1);
                }}
                onClearFocus={() => {
                  setSportFocus((current) => current && { ...current, cleared: true });
                  setPage(1);
                }}
                onApplyFocus={() => {
                  setSportFocus((current) => current && { ...current, cleared: false });
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
                <WatchPanel
                  watches={watches}
                  expired={expiredWatches}
                  onCancel={(id) => void handleCancelWatch(id)}
                />
              )}
              <ExecutionNote />
            </aside>
          </div>
        </main>
      )}

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
            <label className="select-shell watch-window-select">
              Window
              <select
                value={watchWindow}
                onChange={(event) => setWatchWindow(event.target.value as WatchWindow | "")}
              >
                <option value="">Default (from event status)</option>
                {WATCH_WINDOWS.map((option) => (
                  <option key={option} value={option}>
                    {windowLabel(option)}
                  </option>
                ))}
              </select>
            </label>
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

function ExecutionNote() {
  const [collapsed, toggle] = useCollapsed("browsing-note");
  return (
    <Panel className="execution-note">
      <CheckCircle2 size={22} />
      <div>
        <div className="section-title">
          <strong>Browsing is free</strong>
          <CollapseToggle collapsed={collapsed} onToggle={toggle} label="browsing note" />
        </div>
        {!collapsed && (
          <p>
            Events and boards are read from the database. Only the refresh control
            contacts the provider, and it is billed per market per region.
          </p>
        )}
      </div>
    </Panel>
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
