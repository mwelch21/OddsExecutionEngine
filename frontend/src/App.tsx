import { useEffect, useMemo, useState } from "react";
import { Bell, CheckCircle2, RadioTower, TrendingUp } from "lucide-react";
import {
  cancelWatch,
  createWatch,
  getRecommendation,
  listWatches,
  refreshQuotes,
  type Recommendation,
  type WatchIntent
} from "./lib/api";
import { demoEventId, marketLines, sportsbookOptions, type MarketLine } from "./lib/fixtures";
import { LineBoard } from "./components/LineBoard";
import { WatchPanel } from "./components/WatchPanel";
import { Panel, Pill } from "./components/primitives";
import { Button } from "./components/primitives";
import { formatAmerican } from "./lib/fixtures";

type LoadState = "idle" | "loading" | "ready" | "error";

export function App() {
  const [lines, setLines] = useState(marketLines);
  const [selectedBook, setSelectedBook] = useState("Best");
  const [recommendations, setRecommendations] = useState<Record<string, Recommendation>>({});
  const [watches, setWatches] = useState<WatchIntent[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [message, setMessage] = useState("Ready");
  const [watchDraft, setWatchDraft] = useState<MarketLine | null>(null);
  const [watchTarget, setWatchTarget] = useState("");

  const bestCount = useMemo(() => Object.values(recommendations).filter((r) => r.fillable).length, [recommendations]);

  async function loadBoard(currentLines = lines) {
    setLoadState("loading");
    setMessage("Refreshing quotes and recommendations");
    try {
      await refreshQuotes(demoEventId);
      const responses = await Promise.all(
        currentLines.map(async (line) => [line.id, await getRecommendation(toIntent(line))] as const)
      );
      setRecommendations(Object.fromEntries(responses));
      const watchResponse = await listWatches(demoEventId);
      setWatches(watchResponse.watch_intents);
      setLoadState("ready");
      setMessage("Market state loaded");
    } catch (error) {
      setLoadState("error");
      setMessage(error instanceof Error ? error.message : "Unable to load market state");
    }
  }

  useEffect(() => {
    void loadBoard(marketLines);
  }, []);

  async function handleCreateWatch(line: MarketLine, targetPrice = line.target_price) {
    setMessage(`Creating watch for ${line.label}`);
    const updatedLines = lines.map((existingLine) =>
      existingLine.id === line.id ? { ...existingLine, target_price: targetPrice } : existingLine
    );
    try {
      await createWatch(toIntent({ ...line, target_price: targetPrice }));
      const watchResponse = await listWatches(demoEventId);
      setLines(updatedLines);
      setWatches(watchResponse.watch_intents);
      setWatchDraft(null);
      setMessage(`Watch created: ${line.label}`);
      void loadBoard(updatedLines);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Watch creation failed");
    }
  }

  async function handleCancelWatch(id: string) {
    try {
      await cancelWatch(id);
      const watchResponse = await listWatches(demoEventId);
      setWatches(watchResponse.watch_intents);
      setMessage("Watch cancelled");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Watch cancel failed");
    }
  }

  function openWatchModal(line: MarketLine) {
    setWatchDraft(line);
    setWatchTarget(String(line.target_price));
  }

  const watchRecommendation = watchDraft ? recommendations[watchDraft.id] : undefined;
  const watchCurrentQuote =
    selectedBook === "Best"
      ? watchRecommendation?.best_quote
      : watchRecommendation?.ranked_quotes.find((quote) => quote.sportsbook === selectedBook) ?? null;

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
        </div>
      </header>

      <main className="workspace">
        <section className="hero-strip">
          <div>
            <Pill tone="accent">Live demo event</Pill>
            <h2>Knicks at Celtics</h2>
            <p>{message} · {bestCount} fillable markets · {sportsbookOptions.length - 1} books</p>
          </div>
        </section>

        <div className="content-grid">
          <LineBoard
            lines={lines}
            recommendations={recommendations}
            selectedBook={selectedBook}
            loading={loadState === "loading"}
            books={sportsbookOptions}
            onBookChange={setSelectedBook}
            onRefresh={() => void loadBoard()}
            onOpenWatch={openWatchModal}
          />
          <aside className="side-rail">
            <WatchPanel watches={watches} onCancel={(id) => void handleCancelWatch(id)} />
            <Panel className="execution-note">
              <CheckCircle2 size={22} />
              <div>
                <strong>Best mode</strong>
                <p>Each market can show a different book. Selected book mode shows that book's line only.</p>
              </div>
            </Panel>
          </aside>
        </div>
      </main>

      {watchDraft && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setWatchDraft(null)}>
          <section className="watch-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-heading">
              <div>
                <Pill tone="accent">Create watch</Pill>
                <h2>{watchDraft.label}</h2>
                <p>{watchDraft.matchup}</p>
              </div>
              <Button variant="ghost" onClick={() => setWatchDraft(null)}>
                x
              </Button>
            </div>
            <div className="modal-quote-card">
              <div className="modal-current-line">
                <span>Current line</span>
                <strong>{formatAmerican(watchCurrentQuote?.price)}</strong>
                <small>
                  {watchCurrentQuote?.sportsbook ?? selectedBook}
                  {watchDraft.line !== undefined ? ` · ${watchDraft.line}` : ""}
                </small>
              </div>
              <div className="modal-target-card">
                <span>Desired watch target</span>
                <label className="modal-target-input">
                  Desired odds
                  <input
                    type="number"
                    value={watchTarget}
                    onChange={(event) => setWatchTarget(event.target.value)}
                  />
                </label>
              </div>
            </div>
            <p className="modal-copy">
              Watch fires when deterministic engine finds this market fillable at desired odds or better.
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

function toIntent(line: MarketLine) {
  return {
    event_id: line.event_id,
    market_type: line.market_type,
    selection: line.selection,
    line: line.line,
    target_price: line.target_price
  };
}
