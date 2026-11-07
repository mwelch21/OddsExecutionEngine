/**
 * PROTOTYPE, throwaway. Branch prototype/admin-view-layout, never merged.
 *
 * Question (wayfinder ticket #95): what should the Admin view's three tabs look
 * like? Shell is the chosen nav (Variant A from #94). Three content layouts,
 * switchable via `?variant=A|B|C`; `?scenario=normal|notifier|credits|empty`
 * fakes the data so empty and failure states can be judged. All data is stubbed.
 */
import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, Gauge, LineChart, Settings2, ShieldCheck, TrendingUp } from "lucide-react";
import { App } from "../App";
import { Button, EmptyState, Panel, Pill } from "../components/primitives";
import "./layout-prototype.css";

type Tab = "systems" | "credits" | "controls";
type Scenario = "normal" | "notifier" | "credits" | "empty";
type Tone = "good" | "warn" | "neutral" | "danger";

const VARIANTS = [
  { key: "A", name: "Panels" },
  { key: "B", name: "Activity feed" },
  { key: "C", name: "Needs-a-look first" }
];
const SCENARIOS: Scenario[] = ["normal", "notifier", "credits", "empty"];
const TABS: { key: Tab; label: string; icon: ReactNode }[] = [
  { key: "systems", label: "Systems", icon: <ShieldCheck size={16} /> },
  { key: "credits", label: "Credits", icon: <Gauge size={16} /> },
  { key: "controls", label: "Controls", icon: <Settings2 size={16} /> }
];

/* ---------------- stub data, shaped like the #93 endpoints ---------------- */

type Component = { name: string; state: string; tone: Tone; note: string };
type RefreshRow = { at: string; scope: string; trigger: string; cost: number | null; outcome: string; bad?: boolean };
type DeliveryRow = { at: string; subject: string; device: string; status: string; bad?: boolean; error?: string };

function data(s: Scenario) {
  const empty = s === "empty";
  const components: Component[] = [
    { name: "API", state: "Healthy", tone: "good", note: "this page loaded" },
    { name: "Database", state: "Healthy", tone: "good", note: "/api/health" },
    s === "notifier"
      ? { name: "Notifier", state: "Disconnected", tone: "danger", note: "no listener in pg_stat_activity" }
      : { name: "Notifier", state: "Connected", tone: "good", note: "listening since 09:12" },
    empty
      ? { name: "Odds provider", state: "Unknown", tone: "neutral", note: "no upstream call yet" }
      : { name: "Odds provider", state: "Healthy", tone: "good", note: "last answer 14:32" }
  ];
  const refreshes: RefreshRow[] = empty
    ? []
    : [
        { at: "14:32", scope: "NBA", trigger: "auto", cost: 3, outcome: "succeeded · 11 events" },
        { at: "14:27", scope: "NBA", trigger: "auto", cost: 3, outcome: "succeeded · 11 events" },
        { at: "14:05", scope: "Knicks @ Celtics", trigger: "manual", cost: 3, outcome: "succeeded · 1 event" },
        s === "credits"
          ? { at: "13:50", scope: "NHL", trigger: "manual", cost: 0, outcome: "refused · out of credits", bad: true }
          : { at: "13:50", scope: "NHL", trigger: "manual", cost: null, outcome: "failed · provider timeout", bad: true }
      ];
  const deliveries: DeliveryRow[] = empty
    ? []
    : [
        { at: "14:32", subject: "Knicks ML +125 @ FanDuel · fillable", device: "iPhone", status: "delivered" },
        { at: "14:32", subject: "Knicks ML +125 @ FanDuel · fillable", device: "MacBook Chrome", status: "gone", bad: true, error: "410 from push service" },
        ...(s === "notifier"
          ? [{ at: "14:40", subject: "Over 221.5 -108 @ DK · fillable", device: "iPhone", status: "pending 9 min", bad: true }]
          : []),
        { at: "12:10", subject: "Credits low · 41 left", device: "iPhone", status: "delivered" }
      ];
  const credits =
    s === "credits"
      ? { remaining: 0, used: 500, floor: 50, out: true }
      : empty
        ? null
        : { remaining: 41, used: 459, floor: 50, out: false };
  return {
    components,
    refreshes,
    deliveries,
    credits,
    metrics: {
      lastSuccess: empty ? "never" : "14:32 · NBA · 3 min ago",
      counts: empty ? "none in last 24h" : "18 delivered · 1 gone · 0 failed · 0 expired (last 24h)",
      pending: s === "notifier" ? "1 pending · oldest 9 min" : "0 pending"
    },
    burn: empty ? [] : [["NBA", 312], ["NFL", 120], ["NHL", 27]] as [string, number][],
    history: empty ? [] : [500, 470, 440, 400, 330, 260, 190, 120, 70, 41].map((v) => (s === "credits" ? Math.max(0, v - 41) : v))
  };
}
type Data = ReturnType<typeof data>;

/* ---------------- small shared pieces (content, not layout) ---------------- */

function StateTag({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`lp-tag lp-tag-${tone}`}>{children}</span>;
}

function CreditMeter({ c }: { c: NonNullable<Data["credits"]> }) {
  const total = c.remaining + c.used;
  const low = c.remaining < c.floor;
  return (
    <div className="credit-meter">
      <div className="credit-meter-track">
        <div className={low ? "credit-meter-fill low" : "credit-meter-fill"} style={{ width: `${(c.remaining / total) * 100}%` }} />
        <div className="credit-meter-floor" style={{ left: `${(c.floor / total) * 100}%` }} />
      </div>
      <span className={low ? "auto-refresh-warn" : "auto-refresh-muted"}>
        {c.out ? "Out of credits · Auto-Refresh paused" : `${c.remaining} of ${total} left`} · warns below {c.floor} · resets Dec 1
      </span>
    </div>
  );
}

function HistoryBars({ values }: { values: number[] }) {
  if (!values.length) return <EmptyState>No quota observations yet. The first refresh records one.</EmptyState>;
  const max = Math.max(...values, 1);
  return (
    <div className="lp-bars">
      {values.map((v, i) => (
        <div key={i} title={`${v} left`} style={{ height: `${(v / max) * 100}%` }} />
      ))}
    </div>
  );
}

function RefreshTable({ rows, compact }: { rows: RefreshRow[]; compact?: boolean }) {
  if (!rows.length) return <EmptyState>No refreshes yet. Refresh a sport from Home, or turn Auto-Refresh on.</EmptyState>;
  return (
    <table className={compact ? "lp-table lp-compact" : "lp-table"}>
      <thead>
        <tr><th>Time</th><th>Scope</th><th>Trigger</th><th>Cost</th><th>Outcome</th></tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={r.bad ? "lp-row-bad" : undefined}>
            <td>{r.at}</td><td>{r.scope}</td><td>{r.trigger}</td><td>{r.cost ?? "—"}</td><td>{r.outcome}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DeliveryTable({ rows, compact }: { rows: DeliveryRow[]; compact?: boolean }) {
  if (!rows.length) return <EmptyState>No notifications sent yet.</EmptyState>;
  return (
    <table className={compact ? "lp-table lp-compact" : "lp-table"}>
      <thead>
        <tr><th>Time</th><th>Notification</th><th>Device</th><th>Status</th></tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={r.bad ? "lp-row-bad" : undefined} title={r.error}>
            <td>{r.at}</td><td>{r.subject}</td><td>{r.device}</td><td>{r.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BurnTable({ rows }: { rows: [string, number][] }) {
  if (!rows.length) return <EmptyState>No credits spent this month.</EmptyState>;
  const max = Math.max(...rows.map((r) => r[1]));
  return (
    <div className="lp-burn">
      {rows.map(([sport, n]) => (
        <div key={sport} className="lp-burn-row">
          <span>{sport}</span>
          <div><i style={{ width: `${(n / max) * 100}%` }} /></div>
          <strong>{n}</strong>
        </div>
      ))}
    </div>
  );
}

function Controls({ d }: { d: Data }) {
  return (
    <div className="lp-controls">
      <Panel>
        <div className="panel-heading compact"><h2>Auto-Refresh</h2></div>
        <div className="lp-form">
          <label className="lp-switch"><input type="checkbox" defaultChecked /> On{d.credits?.out ? " · paused, out of credits" : ""}</label>
          <label>Interval <input className="target-input" type="number" defaultValue={5} /> min</label>
          <label>Warn below <input className="target-input" type="number" defaultValue={50} /> credits</label>
        </div>
      </Panel>
      <Panel>
        <div className="panel-heading compact"><h2>Devices</h2></div>
        <table className="lp-table">
          <thead><tr><th>Label</th><th>Channel</th><th>Status</th><th>Last delivered</th><th /></tr></thead>
          <tbody>
            <tr><td>iPhone</td><td>Web Push</td><td><StateTag tone="good">active</StateTag></td><td>14:32</td>
              <td className="lp-actions"><Button variant="ghost">Test</Button><Button variant="ghost">Rename</Button><Button variant="ghost">Remove</Button></td></tr>
            <tr><td>MacBook Chrome</td><td>Web Push</td><td><StateTag tone="danger">gone</StateTag></td><td>yesterday</td>
              <td className="lp-actions"><span className="auto-refresh-muted">needs a new subscription</span></td></tr>
          </tbody>
        </table>
        <div className="lp-temp">
          <Button variant="secondary">Enable notifications on this browser</Button>
          <span className="auto-refresh-muted">Temporary home until onboarding lands.</span>
        </div>
      </Panel>
    </div>
  );
}

/* ---------------- Variant A: panels ---------------- */

function SystemsA({ d }: { d: Data }) {
  return (
    <>
      <div className="lp-status-grid">
        {d.components.map((c) => (
          <Panel key={c.name} className="metric-card">
            <span>{c.name}</span>
            <StateTag tone={c.tone}>{c.state}</StateTag>
            <small className="auto-refresh-muted">{c.note}</small>
          </Panel>
        ))}
      </div>
      <Panel className="lp-metrics">
        <div><span>Last successful refresh</span><strong>{d.metrics.lastSuccess}</strong></div>
        <div><span>Deliveries</span><strong>{d.metrics.counts}</strong></div>
        <div><span>Pending</span><strong>{d.metrics.pending}</strong></div>
      </Panel>
      <div className="lp-two">
        <Panel><div className="panel-heading compact"><h2>Refresh log</h2></div><RefreshTable rows={d.refreshes} /></Panel>
        <Panel><div className="panel-heading compact"><h2>Delivery log</h2></div><DeliveryTable rows={d.deliveries} /></Panel>
      </div>
    </>
  );
}
function CreditsA({ d }: { d: Data }) {
  return (
    <div className="lp-two">
      <Panel>
        <div className="panel-heading compact"><h2>Credits</h2></div>
        {d.credits ? <CreditMeter c={d.credits} /> : <EmptyState>No quota observations yet.</EmptyState>}
        <h3 className="lp-h3">Last 30 days</h3>
        <HistoryBars values={d.history} />
      </Panel>
      <Panel><div className="panel-heading compact"><h2>Burn per sport · November</h2></div><BurnTable rows={d.burn} /></Panel>
    </div>
  );
}

/* ---------------- Variant B: activity feed ---------------- */

function SystemsB({ d }: { d: Data }) {
  const [failuresOnly, setFailuresOnly] = useState(false);
  const feed = [
    ...d.refreshes.map((r) => ({ at: r.at, kind: "Refresh", text: `${r.scope} · ${r.trigger} · ${r.outcome}`, cost: r.cost, bad: r.bad })),
    ...d.deliveries.map((r) => ({ at: r.at, kind: "Delivery", text: `${r.subject} → ${r.device} · ${r.status}`, cost: null, bad: r.bad }))
  ]
    .sort((a, b) => b.at.localeCompare(a.at))
    .filter((e) => !failuresOnly || e.bad);
  return (
    <div className="lp-sidebar-layout">
      <aside className="lp-side">
        <Panel>
          <div className="panel-heading compact"><h2>Components</h2></div>
          {d.components.map((c) => (
            <div key={c.name} className="lp-side-row"><span>{c.name}</span><StateTag tone={c.tone}>{c.state}</StateTag></div>
          ))}
        </Panel>
        <Panel>
          <div className="panel-heading compact"><h2>Metrics</h2></div>
          <div className="lp-side-row"><span>Last success</span><strong>{d.metrics.lastSuccess}</strong></div>
          <div className="lp-side-row"><span>Pending</span><strong>{d.metrics.pending}</strong></div>
          {d.credits && <CreditMeter c={d.credits} />}
        </Panel>
      </aside>
      <Panel className="lp-feed">
        <div className="panel-heading compact">
          <h2>Activity</h2>
          <label className="checkbox-shell"><input type="checkbox" checked={failuresOnly} onChange={(e) => setFailuresOnly(e.target.checked)} /> Failures only</label>
        </div>
        {feed.length === 0 ? (
          <EmptyState>{failuresOnly ? "No failures." : "Nothing has happened yet."}</EmptyState>
        ) : (
          feed.map((e, i) => (
            <div key={i} className={e.bad ? "lp-feed-row lp-row-bad" : "lp-feed-row"}>
              <span className="lp-feed-at">{e.at}</span>
              <Pill tone={e.kind === "Refresh" ? "accent" : "neutral"}>{e.kind}</Pill>
              <span>{e.text}</span>
              {e.cost != null && <span className="auto-refresh-muted">{e.cost} cr</span>}
            </div>
          ))
        )}
      </Panel>
    </div>
  );
}
function CreditsB({ d }: { d: Data }) {
  return (
    <Panel className="lp-credits-hero">
      <div className="lp-big">
        <strong>{d.credits ? d.credits.remaining : "—"}</strong>
        <span>credits left</span>
      </div>
      {d.credits && <CreditMeter c={d.credits} />}
      <div className="lp-two">
        <div><h3 className="lp-h3">Last 30 days</h3><HistoryBars values={d.history} /></div>
        <div><h3 className="lp-h3">Burn per sport · November</h3><BurnTable rows={d.burn} /></div>
      </div>
    </Panel>
  );
}

/* ---------------- Variant C: needs-a-look first ---------------- */

function SystemsC({ d }: { d: Data }) {
  const bad = [
    ...d.components.filter((c) => c.tone === "danger").map((c) => `${c.name} ${c.state.toLowerCase()}: ${c.note}`),
    ...d.refreshes.filter((r) => r.bad).map((r) => `Refresh ${r.scope} ${r.at}: ${r.outcome}`),
    ...d.deliveries.filter((r) => r.bad).map((r) => `Delivery to ${r.device} ${r.at}: ${r.status}`)
  ];
  return (
    <>
      <div className="lp-strip">
        {d.components.map((c) => (
          <span key={c.name} className="lp-strip-item">{c.name} <StateTag tone={c.tone}>{c.state}</StateTag></span>
        ))}
        <span className="lp-strip-item auto-refresh-muted">Last success {d.metrics.lastSuccess} · {d.metrics.pending}</span>
      </div>
      <Panel className={bad.length ? "lp-look lp-look-bad" : "lp-look"}>
        <div className="panel-heading compact"><h2>Needs a look</h2><span className="auto-refresh-muted">{bad.length} item(s)</span></div>
        {bad.length ? (
          <ul>{bad.map((b, i) => <li key={i}><AlertTriangle size={14} /> {b}</li>)}</ul>
        ) : (
          <EmptyState>Nothing failed. Logs below are for reference.</EmptyState>
        )}
      </Panel>
      <details className="lp-details" open>
        <summary>Refresh log ({d.refreshes.length})</summary>
        <RefreshTable rows={d.refreshes} compact />
      </details>
      <details className="lp-details">
        <summary>Delivery log ({d.deliveries.length}) · {d.metrics.counts}</summary>
        <DeliveryTable rows={d.deliveries} compact />
      </details>
    </>
  );
}

/* ---------------- shell (Variant A nav from #94) + switcher ---------------- */

function readTab(): Tab | null {
  const m = window.location.pathname.match(/^\/admin(?:\/(systems|credits|controls))?\/?$/);
  return m ? ((m[1] as Tab) ?? "systems") : null;
}

export function AdminLayoutPrototype() {
  const [, force] = useState(0);
  useEffect(() => {
    const onPop = () => force((n) => n + 1);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const params = new URLSearchParams(window.location.search);
  const variant = params.get("variant") ?? "A";
  const scenario = (params.get("scenario") as Scenario) ?? "normal";
  const tab = readTab();
  const d = data(scenario);
  const go = (path: string, patch: Record<string, string> = {}) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(patch)) next.set(k, v);
    window.history.pushState(null, "", `${path}?${next}`);
    force((n) => n + 1);
  };
  const idx = Math.max(0, VARIANTS.findIndex((v) => v.key === variant));
  const cycle = (dir: number) => go(window.location.pathname, { variant: VARIANTS[(idx + dir + 3) % 3].key });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "ArrowLeft") cycle(-1);
      if (e.key === "ArrowRight") cycle(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const attention =
    d.components.some((c) => c.tone === "danger")
      ? { text: "Notifier disconnected", tab: "systems" as Tab }
      : d.credits && d.credits.remaining < d.credits.floor
        ? { text: d.credits.out ? "Out of credits" : `Credits low · ${d.credits.remaining} left`, tab: "credits" as Tab }
        : null;

  const topbar = (
    <header className="topbar">
      <div className="brand-lockup">
        <div className="brand-mark"><TrendingUp size={23} /></div>
        <div><h1>OddsCafe</h1><p>{tab ? "Admin view" : "Fillability, best book, nearest miss, watch signals."}</p></div>
      </div>
      <div className="topbar-status">
        {attention && (
          <button className="lp-attn" onClick={() => go(`/admin/${attention.tab}`)}>
            <AlertTriangle size={14} /> {attention.text}
          </button>
        )}
        {tab ? (
          <Button variant="secondary" onClick={() => go("/")}><LineChart size={15} /> Lines</Button>
        ) : (
          <Button variant="secondary" onClick={() => go("/admin/systems")}><ShieldCheck size={15} /> Admin view</Button>
        )}
      </div>
    </header>
  );

  const body = !tab ? null : tab === "controls" ? (
    <Controls d={d} />
  ) : tab === "credits" ? (
    variant === "B" ? <CreditsB d={d} /> : <CreditsA d={d} />
  ) : variant === "B" ? (
    <SystemsB d={d} />
  ) : variant === "C" ? (
    <SystemsC d={d} />
  ) : (
    <SystemsA d={d} />
  );

  return (
    <>
      {!tab ? (
        <App topbar={topbar} />
      ) : (
        <div className="app-shell">
          {topbar}
          <main className="workspace lp-admin">
            <nav className="lp-tabstrip">
              {TABS.map((t) => (
                <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => go(`/admin/${t.key}`)}>
                  {t.icon} {t.label}
                </button>
              ))}
            </nav>
            {body}
          </main>
        </div>
      )}
      <div className="lp-switcher">
        <button onClick={() => cycle(-1)}>←</button>
        <span>{VARIANTS[idx].key} ({VARIANTS[idx].name})</span>
        <button onClick={() => cycle(1)}>→</button>
        <span className="lp-sep" />
        <button onClick={() => go(window.location.pathname, { scenario: SCENARIOS[(SCENARIOS.indexOf(scenario) + 1) % SCENARIOS.length] })}>
          scenario: {scenario}
        </button>
        <span className="lp-path">{window.location.pathname}</span>
      </div>
    </>
  );
}
