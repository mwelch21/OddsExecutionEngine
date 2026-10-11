/**
 * PROTOTYPE ONLY. Variant B, "Side-rail cockpit":
 * - Auto-Refresh is an always-visible Monitoring panel: big switch, credit meter,
 *   per-sport cooldown countdowns, last refresh outcome
 * - Devices panel with an inline checklist for adding this phone
 * - a tapped notification opens a dedicated full-width Opportunity screen
 */
import { Activity, AlertTriangle, ArrowLeft, Bell, Clock, Plus, Power, Smartphone, Zap } from "lucide-react";
import type { EventPage } from "../../lib/api";
import { EventList } from "../../components/EventList";
import { Button, Panel, Pill } from "../../components/primitives";
import { ApiTag, CreditMeter, ago, price, statusLabel } from "./shared";
import type { Dispatch, SimState } from "./sim";

export function VariantB({
  state,
  dispatch,
  eventPage
}: {
  state: SimState;
  dispatch: Dispatch;
  eventPage: EventPage | null;
}) {
  const ar = state.autoRefresh;
  const opp = state.tapped;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">
            <Zap size={23} />
          </div>
          <div>
            <h1>OddsCafe</h1>
            <p>Variant B · side-rail cockpit</p>
          </div>
        </div>
      </header>

      <main className="workspace">
        {opp ? (
          <section className="proto-b-opp">
            <Button variant="ghost" onClick={() => dispatch({ type: "closeOpportunity" })}>
              <ArrowLeft size={16} /> Events
            </Button>
            <Pill tone="good">Fillable now</Pill>
            <p className="proto-muted">{opp.eventLabel}</p>
            <h2>
              {opp.selection} {opp.marketLabel} {opp.line}
            </h2>
            <div className="proto-b-pricepair">
              <div>
                <span>Best</span>
                <strong>{price(opp.best.price)}</strong>
                <small>{opp.best.sportsbook} · quoted {ago(opp.best.quotedAt)}</small>
              </div>
              <div className="proto-b-vs">vs</div>
              <div>
                <span>Your target</span>
                <strong>{price(opp.targetPrice)}</strong>
                <small>+{opp.best.price - opp.targetPrice} better than target</small>
              </div>
            </div>
            <table className="proto-table">
              <thead>
                <tr>
                  <th>Book</th>
                  <th>Price</th>
                </tr>
              </thead>
              <tbody>
                {opp.matching.map((m) => (
                  <tr key={m.sportsbook}>
                    <td>{m.sportsbook}</td>
                    <td>{price(m.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="proto-muted">
              <Clock size={14} /> Opportunity valid for ~{Math.round(opp.validMinutesLeft / 60)}h · this watch has fired and won't fire again
            </p>
            <div className="proto-row">
              <Button variant="primary">Open line board</Button>
              <Button>Watch again at a new target</Button>
            </div>
            <ApiTag>GET /opportunities/:id · GET /events/:id/quotes · POST /watch-intents</ApiTag>
          </section>
        ) : (
          <div className="content-grid">
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
            <aside className="side-rail">
              <Panel className="proto-b-panel">
                <div className="proto-row">
                  <strong>
                    <Activity size={16} /> Monitoring
                  </strong>
                  <button
                    className={`proto-b-power ${ar.enabled ? "on" : ""}`}
                    onClick={() => dispatch({ type: "toggleAutoRefresh" })}
                    aria-label="Toggle Auto-Refresh"
                  >
                    <Power size={18} />
                  </button>
                </div>
                <p className={ar.status === "paused_out_of_credits" ? "proto-warn" : "proto-muted"}>{statusLabel(state)}</p>
                <div className="proto-row">
                  <span>Interval</span>
                  <div className="proto-seg">
                    {[2, 5, 10, 15].map((m) => (
                      <button key={m} className={m === ar.intervalMinutes ? "active" : ""} onClick={() => dispatch({ type: "setInterval", minutes: m })}>
                        {m}m
                      </button>
                    ))}
                  </div>
                </div>
                <CreditMeter credits={state.credits} />
                <p className="proto-muted">
                  {state.credits.remaining}/{state.credits.remaining + state.credits.used} credits · warns below {state.credits.floor}
                </p>
                {state.credits.remaining < state.credits.floor && (
                  <p className="proto-warn">
                    <AlertTriangle size={14} /> Low credits. Auto-Refresh keeps running until zero, then pauses.
                  </p>
                )}
                <ul className="proto-b-sports">
                  {ar.sports.map((s) => {
                    const due = ar.intervalMinutes - s.lastRefreshedMinutesAgo;
                    return (
                      <li key={s.key}>
                        <span>{s.key}</span>
                        <span className="proto-muted">
                          {s.watches} watches · {!ar.enabled ? "manual" : due <= 0 ? "due now" : `next in ${due}m`}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <p className="proto-muted">Last: {ar.lastTick ? `${ar.lastTick.outcome} (${ago(ar.lastTick.at)})` : "none"}</p>
                <ApiTag>GET/PUT /auto-refresh</ApiTag>
              </Panel>

              <Panel className="proto-b-panel">
                <strong>
                  <Bell size={16} /> Devices
                </strong>
                {state.destinations.map((d) => (
                  <div key={d.id} className="proto-row proto-device">
                    <span>
                      <Smartphone size={14} /> {d.label}
                      <br />
                      <small className={d.status === "active" ? "proto-muted" : "proto-warn"}>
                        {d.status === "gone" ? "Stopped receiving: reopen the app to fix" : d.status === "user_removed" ? "Removed" : `Last ping ${ago(d.lastDeliveredAt)}`}
                      </small>
                    </span>
                    {d.status === "active" && (
                      <span>
                        <Button variant="ghost" onClick={() => dispatch({ type: "sendTest", destinationId: d.id })}>
                          Test
                        </Button>
                        <Button variant="ghost" onClick={() => dispatch({ type: "removeDestination", id: d.id })}>
                          ×
                        </Button>
                      </span>
                    )}
                  </div>
                ))}
                {state.permission !== "granted" && (
                  <div className="proto-b-checklist">
                    <strong>
                      <Plus size={14} /> Add this iPhone
                    </strong>
                    <label>
                      <input type="checkbox" checked={state.installedToHomeScreen} onChange={() => dispatch({ type: "install" })} /> Added to Home
                      Screen &amp; opened from icon
                    </label>
                    <Button variant="primary" disabled={!state.installedToHomeScreen} onClick={() => dispatch({ type: "grantPermission" })}>
                      Allow notifications
                    </Button>
                    <ApiTag>POST /destinations/web-push</ApiTag>
                  </div>
                )}
              </Panel>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}
