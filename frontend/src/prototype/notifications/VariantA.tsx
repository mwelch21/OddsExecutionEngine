/**
 * PROTOTYPE ONLY. Variant A, "Topbar control":
 * - Auto-Refresh lives in the topbar as a switch with a popover
 * - push onboarding is a modal wizard opened from a bell button
 * - a tapped notification opens the real line board with the opportunity pinned on top
 */
import { useState } from "react";
import { Bell, BellRing, Check, Share, Smartphone, X, Zap } from "lucide-react";
import type { LineBoard as LineBoardData } from "../../lib/api";
import { LineBoard } from "../../components/LineBoard";
import { EventList } from "../../components/EventList";
import type { EventPage } from "../../lib/api";
import { Button, Pill } from "../../components/primitives";
import { ApiTag, CreditMeter, ago, price, statusLabel } from "./shared";
import type { Dispatch, SimState } from "./sim";

export function VariantA({
  state,
  dispatch,
  board,
  eventPage
}: {
  state: SimState;
  dispatch: Dispatch;
  board: LineBoardData | null;
  eventPage: EventPage | null;
}) {
  const [popover, setPopover] = useState(false);
  const [wizard, setWizard] = useState(false);
  const ar = state.autoRefresh;
  const low = state.credits.remaining < state.credits.floor;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">
            <Zap size={23} />
          </div>
          <div>
            <h1>OddsCafe</h1>
            <p>Variant A · everything in the topbar</p>
          </div>
        </div>
        <div className="topbar-status proto-a-controls">
          {low && <Pill tone="warn">⚠ {state.credits.remaining} credits left</Pill>}
          <button className={`proto-a-switch ${ar.enabled ? "on" : ""} ${ar.status === "paused_out_of_credits" ? "paused" : ""}`} onClick={() => setPopover((v) => !v)}>
            <span className="dot" /> Auto-Refresh {ar.enabled ? (ar.status === "paused_out_of_credits" ? "paused" : "on") : "off"}
          </button>
          <Button variant="ghost" onClick={() => setWizard(true)} aria-label="Notifications">
            {state.destinations.some((d) => d.status === "active" && d.id === "d-iphone") ? <BellRing size={18} /> : <Bell size={18} />}
          </Button>
          {popover && (
            <div className="proto-popover">
              <div className="proto-row">
                <strong>Auto-Refresh</strong>
                <Button variant={ar.enabled ? "danger" : "primary"} onClick={() => dispatch({ type: "toggleAutoRefresh" })}>
                  {ar.enabled ? "Turn off" : "Turn on"}
                </Button>
              </div>
              <p className="proto-muted">{statusLabel(state)}</p>
              <label className="proto-row">
                Every
                <select value={ar.intervalMinutes} onChange={(e) => dispatch({ type: "setInterval", minutes: Number(e.target.value) })}>
                  {[1, 2, 5, 10, 15, 30, 60].map((m) => (
                    <option key={m} value={m}>
                      {m} min
                    </option>
                  ))}
                </select>
              </label>
              <CreditMeter credits={state.credits} />
              <p className="proto-muted">
                {state.credits.remaining} credits left · warning below {state.credits.floor} · ~{Math.round((3 * 60) / ar.intervalMinutes) * 3} credits per 3h per sport
              </p>
              <p className="proto-muted">Last refresh: {ar.lastTick ? `${ar.lastTick.outcome} · ${ago(ar.lastTick.at)}` : "none yet"}</p>
              <ApiTag>GET/PUT /auto-refresh</ApiTag>
            </div>
          )}
        </div>
      </header>

      <main className="workspace">
        {state.tapped ? (
          <>
            <section className="proto-a-banner">
              <div>
                <Pill tone="good">Opportunity · fillable</Pill>
                <h2>
                  {state.tapped.selection} {state.tapped.marketLabel} {state.tapped.line} {price(state.tapped.best.price)} @ {state.tapped.best.sportsbook}
                </h2>
                <p>
                  Target {price(state.tapped.targetPrice)} · {state.tapped.matching.length} books fillable · book quoted {ago(state.tapped.best.quotedAt)} · valid ~{Math.round(state.tapped.validMinutesLeft / 60)}h
                </p>
              </div>
              <Button variant="ghost" onClick={() => dispatch({ type: "closeOpportunity" })}>
                <X size={16} />
              </Button>
            </section>
            <LineBoard board={board} loading={false} onBack={() => dispatch({ type: "closeOpportunity" })} onOpenWatch={() => undefined} />
          </>
        ) : (
          <EventList
            page={eventPage}
            sports={[]}
            league={null}
            includeStarted={false}
            refreshSport=""
            loading={false}
            refreshing={false}
            cooldown={0}
            onLeagueChange={() => undefined}
            onIncludeStartedChange={() => undefined}
            onRefreshSportChange={() => undefined}
            onRefresh={() => undefined}
            onPageChange={() => undefined}
            onSelectEvent={() => undefined}
          />
        )}
      </main>

      {wizard && (
        <div className="modal-backdrop" onMouseDown={() => setWizard(false)}>
          <section className="watch-modal proto-wizard" onMouseDown={(e) => e.stopPropagation()}>
            <div className="modal-heading">
              <div>
                <Pill tone="accent">Notifications on this device</Pill>
                <h2>Step {Math.min(state.onboardingStep + 1, 3)} of 3</h2>
              </div>
              <Button variant="ghost" onClick={() => setWizard(false)}>
                <X size={16} />
              </Button>
            </div>
            <ol className="proto-steps">
              <li className={state.installedToHomeScreen ? "done" : "current"}>
                <Smartphone size={16} /> Add to Home Screen: tap <Share size={14} /> then “Add to Home Screen”, then open the app from the icon.
                {!state.installedToHomeScreen && (
                  <Button onClick={() => dispatch({ type: "install" })}>Simulate: opened from Home Screen</Button>
                )}
              </li>
              <li className={state.permission === "granted" ? "done" : state.installedToHomeScreen ? "current" : ""}>
                <Bell size={16} /> Allow notifications
                {state.installedToHomeScreen && state.permission !== "granted" && (
                  <Button variant="primary" onClick={() => dispatch({ type: "grantPermission" })}>
                    Enable notifications
                  </Button>
                )}
                <ApiTag>GET /push/vapid-public-key → POST /destinations/web-push</ApiTag>
              </li>
              <li className={state.onboardingStep >= 3 ? "done" : state.permission === "granted" ? "current" : ""}>
                <Check size={16} /> Send a test
                {state.permission === "granted" && (
                  <Button onClick={() => dispatch({ type: "sendTest", destinationId: "d-iphone" })}>Send test notification</Button>
                )}
                <ApiTag>POST /destinations/:id/test</ApiTag>
              </li>
            </ol>
            <h3 className="proto-subhead">Devices</h3>
            {state.destinations.map((d) => (
              <div key={d.id} className="proto-row proto-device">
                <span>
                  {d.label} · <em>{d.status}</em> · last {ago(d.lastDeliveredAt)}
                </span>
                {d.status === "active" && (
                  <Button variant="ghost" onClick={() => dispatch({ type: "removeDestination", id: d.id })}>
                    Remove
                  </Button>
                )}
                {d.status === "gone" && <span className="proto-muted">Re-open the app to re-subscribe</span>}
              </div>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}
