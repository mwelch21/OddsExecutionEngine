/**
 * PROTOTYPE ONLY: throwaway, lives on branch prototype/notification-ui.
 *
 * Question (map #52, ticket #60): how should the operator experience
 * (1) the Auto-Refresh toggle, (2) iPhone push onboarding, (3) the screen a
 * tapped opportunity notification opens?
 *
 * Three structurally different variants, switchable via `?variant=A|B|C`
 * (open with `?proto=notify`). Reads real events from the API when it is up
 * (free, DB-backed); every mutation is simulated in memory and logged with the
 * public API call it stands for. Use the "Simulate" drawer to push the
 * system into states that are hard to reach for real.
 */
import { useEffect, useState } from "react";
import { getLineBoard, listEvents, type EventPage, type LineBoard } from "../../lib/api";
import { PrototypeSwitcher } from "../../components/PrototypeSwitcher";
import { opportunityFrom, useSim } from "./sim";
import { VariantA } from "./VariantA";
import { VariantB } from "./VariantB";
import { VariantC } from "./VariantC";
import "./prototype.css";

const VARIANTS = [
  { key: "A", name: "Topbar control" },
  { key: "B", name: "Side-rail cockpit" },
  { key: "C", name: "Phone-first" }
];

export function NotificationPrototype() {
  const [variant, setVariant] = useState(new URLSearchParams(window.location.search).get("variant") ?? "A");
  const [state, dispatch] = useSim();
  const [eventPage, setEventPage] = useState<EventPage | null>(null);
  const [board, setBoard] = useState<LineBoard | null>(null);
  const [drawer, setDrawer] = useState(false);

  // Free reads only: stored events and one board, for realistic content.
  useEffect(() => {
    listEvents({ page: 1 })
      .then(async (page) => {
        setEventPage(page);
        const first = page.events.find((e) => e.quotes.quote_count > 0);
        if (first) setBoard(await getLineBoard(first.id));
      })
      .catch(() => undefined);
  }, []);

  return (
    <>
      {variant === "A" && <VariantA state={state} dispatch={dispatch} board={board} eventPage={eventPage} />}
      {variant === "B" && <VariantB state={state} dispatch={dispatch} eventPage={eventPage} />}
      {variant === "C" && <VariantC state={state} dispatch={dispatch} eventPage={eventPage} />}

      <aside className={`proto-drawer ${drawer ? "open" : ""}`}>
        <button className="proto-drawer-tab" onClick={() => setDrawer((v) => !v)}>
          {drawer ? "×" : "Simulate"}
        </button>
        {drawer && (
          <>
            <strong>Simulate</strong>
            <button onClick={() => dispatch({ type: "tapOpportunity", opportunity: opportunityFrom(board) })}>📲 Tap an opportunity notification</button>
            <button onClick={() => dispatch({ type: "quotaDropsBelowFloor" })}>⚠️ Credits cross below floor</button>
            <button onClick={() => dispatch({ type: "outOfCredits" })}>⛔ Out of credits</button>
            <button onClick={() => dispatch({ type: "creditsReset" })}>🔄 Monthly reset</button>
            <button onClick={() => dispatch({ type: "destinationGone", id: "d-iphone" })}>📵 iPhone subscription gone (410)</button>
            <button onClick={() => dispatch({ type: "reset" })}>↺ Reset everything</button>
            <p className="proto-muted">{board ? "Using real stored event data" : "API not reachable: stub data"}</p>
            <strong>API calls</strong>
            <pre>{state.apiLog.join("\n") || "none yet"}</pre>
            <strong>State</strong>
            <pre>
              {JSON.stringify(
                {
                  autoRefresh: { enabled: state.autoRefresh.enabled, status: state.autoRefresh.status, interval: state.autoRefresh.intervalMinutes },
                  credits: state.credits,
                  installed: state.installedToHomeScreen,
                  permission: state.permission,
                  destinations: state.destinations.map((d) => `${d.label}: ${d.status}`),
                  tapped: state.tapped?.id ?? null,
                  notices: state.notices.length
                },
                null,
                1
              )}
            </pre>
          </>
        )}
      </aside>

      <PrototypeSwitcher variants={VARIANTS} current={variant} onChange={setVariant} />
    </>
  );
}
