/**
 * PROTOTYPE ONLY. Variant C, "Phone-first":
 * - the app at iPhone width with a bottom tab bar (Events · Alerts · Settings)
 * - Auto-Refresh and devices are rows in an iOS-style Settings tab
 * - an Alerts inbox keeps every notification; the quota warning is a banner there
 * - push onboarding is a full-screen stepper; a tapped notification opens a bottom sheet
 */
import { useState } from "react";
import { AlertTriangle, Bell, ChevronRight, List, Settings, Share, Smartphone, SquarePlus, X } from "lucide-react";
import type { EventPage } from "../../lib/api";
import { matchupLabel } from "../../lib/format";
import { Button } from "../../components/primitives";
import { ApiTag, CreditMeter, ago, price } from "./shared";
import type { Dispatch, SimState } from "./sim";

type Tab = "events" | "alerts" | "settings";

export function VariantC({
  state,
  dispatch,
  eventPage
}: {
  state: SimState;
  dispatch: Dispatch;
  eventPage: EventPage | null;
}) {
  const [tab, setTab] = useState<Tab>("settings");
  const [onboarding, setOnboarding] = useState(false);
  const ar = state.autoRefresh;
  const unread = state.notices.length;
  const low = state.credits.remaining < state.credits.floor;

  return (
    <div className="proto-c-stage">
      <div className="proto-c-phone">
        <div className="proto-c-screen">
          {tab === "events" && (
            <>
              <h2 className="proto-c-title">Events</h2>
              {(eventPage?.events ?? []).slice(0, 8).map((e) => (
                <div key={e.id} className="proto-c-cell">
                  <span>{matchupLabel(e)}</span>
                  <ChevronRight size={16} />
                </div>
              ))}
              {!eventPage && <p className="proto-muted">No API: stub list empty</p>}
            </>
          )}

          {tab === "alerts" && (
            <>
              <h2 className="proto-c-title">Alerts</h2>
              {low && (
                <div className="proto-c-banner">
                  <AlertTriangle size={16} /> {state.credits.remaining} credits left this month. Auto-Refresh keeps going until zero.
                </div>
              )}
              {state.notices.length === 0 && <p className="proto-muted">Nothing yet. Fired watches and warnings land here.</p>}
              {state.notices.map((n) => (
                <button key={n.id} className="proto-c-cell">
                  <span>
                    <strong>{n.kind === "opportunity" ? "🎯" : n.kind === "quota" ? "⚠️" : "🔔"}</strong> {n.text}
                    <br />
                    <small className="proto-muted">{ago(n.at)}</small>
                  </span>
                  <ChevronRight size={16} />
                </button>
              ))}
              <ApiTag>GET /opportunities · (quota warnings: needs a read API)</ApiTag>
            </>
          )}

          {tab === "settings" && (
            <>
              <h2 className="proto-c-title">Settings</h2>
              <p className="proto-c-section">MONITORING</p>
              <div className="proto-c-group">
                <div className="proto-c-cell">
                  <span>Auto-Refresh</span>
                  <button className={`proto-c-toggle ${ar.enabled ? "on" : ""}`} onClick={() => dispatch({ type: "toggleAutoRefresh" })} aria-label="Auto-Refresh" />
                </div>
                <div className="proto-c-cell">
                  <span>Every</span>
                  <select value={ar.intervalMinutes} onChange={(e) => dispatch({ type: "setInterval", minutes: Number(e.target.value) })}>
                    {[1, 2, 5, 10, 15, 30, 60].map((m) => (
                      <option key={m} value={m}>
                        {m} min
                      </option>
                    ))}
                  </select>
                </div>
                <div className="proto-c-cell proto-c-stack">
                  <span>
                    Credits · {state.credits.remaining} left
                    {ar.status === "paused_out_of_credits" && <em className="proto-warn"> · paused until the 1st</em>}
                  </span>
                  <CreditMeter credits={state.credits} />
                </div>
              </div>
              <p className="proto-c-foot">
                Refreshes {ar.sports.length} sports you have watches on. Last: {ar.lastTick ? ago(ar.lastTick.at) : "never"}. <ApiTag>PUT /auto-refresh</ApiTag>
              </p>

              <p className="proto-c-section">NOTIFICATIONS</p>
              <div className="proto-c-group">
                {state.destinations.map((d) => (
                  <div key={d.id} className="proto-c-cell">
                    <span>
                      <Smartphone size={14} /> {d.label}
                      <br />
                      <small className={d.status === "active" ? "proto-muted" : "proto-warn"}>
                        {d.status === "active" ? `on · last ${ago(d.lastDeliveredAt)}` : d.status === "gone" ? "stopped: reopen to fix" : "removed"}
                      </small>
                    </span>
                    {d.status === "active" && (
                      <Button variant="ghost" onClick={() => dispatch({ type: "sendTest", destinationId: d.id })}>
                        Test
                      </Button>
                    )}
                  </div>
                ))}
                {state.permission !== "granted" && (
                  <button className="proto-c-cell proto-c-link" onClick={() => setOnboarding(true)}>
                    <span>Turn on notifications for this iPhone</span>
                    <ChevronRight size={16} />
                  </button>
                )}
              </div>
            </>
          )}
        </div>

        {onboarding && (
          <div className="proto-c-fullscreen">
            <button className="proto-c-close" onClick={() => setOnboarding(false)} aria-label="Close">
              <X size={18} />
            </button>
            {!state.installedToHomeScreen ? (
              <>
                <h2>1 · Add to Home Screen</h2>
                <p>iPhone only delivers notifications to apps opened from the Home Screen.</p>
                <div className="proto-c-illus">
                  <Share size={28} /> → <SquarePlus size={28} /> “Add to Home Screen”
                </div>
                <Button variant="primary" onClick={() => dispatch({ type: "install" })}>
                  Simulate: reopened from icon
                </Button>
              </>
            ) : state.permission !== "granted" ? (
              <>
                <h2>2 · Allow notifications</h2>
                <p>You'll get a ping when a watched price becomes fillable, and a warning when credits run low.</p>
                <Button variant="primary" onClick={() => dispatch({ type: "grantPermission" })}>
                  <Bell size={16} /> Allow
                </Button>
                <ApiTag>POST /destinations/web-push</ApiTag>
              </>
            ) : (
              <>
                <h2>3 · Try it</h2>
                <p>Lock your phone, then send a test.</p>
                <Button
                  variant="primary"
                  onClick={() => {
                    dispatch({ type: "sendTest", destinationId: "d-iphone" });
                    setOnboarding(false);
                  }}
                >
                  Send test notification
                </Button>
                <ApiTag>POST /destinations/:id/test</ApiTag>
              </>
            )}
          </div>
        )}

        {state.tapped && (
          <div className="proto-c-sheet-backdrop" onClick={() => dispatch({ type: "closeOpportunity" })}>
            <div className="proto-c-sheet" onClick={(e) => e.stopPropagation()}>
              <div className="proto-c-grabber" />
              <p className="proto-muted">{state.tapped.eventLabel}</p>
              <h2>
                {state.tapped.selection} {state.tapped.marketLabel} {state.tapped.line}
              </h2>
              <div className="proto-c-bigprice">
                {price(state.tapped.best.price)} <small>@ {state.tapped.best.sportsbook}</small>
              </div>
              <p className="proto-muted">
                target {price(state.tapped.targetPrice)} · fillable · quoted {ago(state.tapped.best.quotedAt)}
              </p>
              <div className="proto-c-chips">
                {state.tapped.matching.map((m) => (
                  <span key={m.sportsbook}>
                    {m.sportsbook} {price(m.price)}
                  </span>
                ))}
              </div>
              <Button variant="primary">Open line board</Button>
              <ApiTag>GET /opportunities/:id</ApiTag>
            </div>
          </div>
        )}

        <nav className="proto-c-tabs">
          <button className={tab === "events" ? "active" : ""} onClick={() => setTab("events")}>
            <List size={18} />
            Events
          </button>
          <button className={tab === "alerts" ? "active" : ""} onClick={() => setTab("alerts")}>
            <Bell size={18} />
            Alerts{unread > 0 && <span className="proto-c-badge">{unread}</span>}
          </button>
          <button className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}>
            <Settings size={18} />
            Settings
          </button>
        </nav>
      </div>
    </div>
  );
}
