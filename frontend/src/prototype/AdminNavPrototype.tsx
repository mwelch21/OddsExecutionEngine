/**
 * PROTOTYPE, throwaway. Branch prototype/admin-view-nav, never merged.
 *
 * Question (wayfinder ticket #94): how does the operator reach the Admin view,
 * and what stays in the top bar? Three variants of the navigation, switchable
 * via `?variant=A|B|C`, on path-based routes: `/` (lines) and
 * `/admin/systems|credits|controls`. `?attn=none|low|paused|broken` fakes the
 * attention pill. Admin data is stubbed; nothing here calls an admin API.
 */
import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowLeft, Gauge, LineChart, Settings2, ShieldCheck, TrendingUp } from "lucide-react";
import { App } from "../App";
import "./prototype.css";

type Tab = "systems" | "credits" | "controls";
type Attn = "none" | "low" | "paused" | "broken";
type Route = { kind: "lines" } | { kind: "admin"; tab: Tab };

const VARIANTS = [
  { key: "A", name: "Top-bar button + tab strip" },
  { key: "B", name: "Persistent sidebar rail" },
  { key: "C", name: "Separate admin shell" }
];
const ATTNS: Attn[] = ["none", "low", "paused", "broken"];
const TABS: { key: Tab; label: string; icon: ReactNode }[] = [
  { key: "systems", label: "Systems", icon: <ShieldCheck size={16} /> },
  { key: "credits", label: "Credits", icon: <Gauge size={16} /> },
  { key: "controls", label: "Controls", icon: <Settings2 size={16} /> }
];

function readRoute(): Route {
  const m = window.location.pathname.match(/^\/admin(?:\/(systems|credits|controls))?\/?$/);
  if (m) return { kind: "admin", tab: (m[1] as Tab) ?? "systems" };
  return { kind: "lines" };
}

function useLocationState() {
  const [, force] = useState(0);
  useEffect(() => {
    const onPop = () => force((n) => n + 1);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const params = new URLSearchParams(window.location.search);
  const go = (path: string, patch: Record<string, string> = {}) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(patch)) next.set(k, v);
    window.history.pushState(null, "", `${path}?${next}`);
    force((n) => n + 1);
  };
  return {
    route: readRoute(),
    variant: params.get("variant") ?? "A",
    attn: (params.get("attn") as Attn) ?? "low",
    go
  };
}

const ATTN_COPY: Record<Exclude<Attn, "none">, { text: string; tab: Tab }> = {
  low: { text: "Credits low · 41 left", tab: "credits" },
  paused: { text: "Auto-Refresh paused · out of credits", tab: "controls" },
  broken: { text: "System degraded · 3 deliveries failed", tab: "systems" }
};

function AttentionPill({ attn, onOpen }: { attn: Attn; onOpen: (tab: Tab) => void }) {
  if (attn === "none") return null;
  const { text, tab } = ATTN_COPY[attn];
  return (
    <button className="proto-attn" onClick={() => onOpen(tab)} title={`Opens /admin/${tab}`}>
      <AlertTriangle size={14} /> {text}
    </button>
  );
}

function Brand() {
  return (
    <div className="brand-lockup">
      <div className="brand-mark">
        <TrendingUp size={23} />
      </div>
      <div>
        <h1>OddsCafe</h1>
        <p>Fillability, best book, nearest miss, watch signals.</p>
      </div>
    </div>
  );
}

/* ---------- stubbed tab contents (shared; layouts differ per variant) ---------- */

function Systems({ attn }: { attn: Attn }) {
  const verdict = attn === "broken" ? "degraded" : attn === "paused" ? "degraded" : "healthy";
  return (
    <div className="proto-stack">
      <div className={`proto-verdict proto-verdict-${verdict}`}>
        <strong>{verdict.toUpperCase()}</strong>
        <span>
          {verdict === "healthy"
            ? "Last refresh 3 min ago · deliveries OK · credits above floor"
            : attn === "paused"
              ? "Auto-Refresh paused: out of credits"
              : "3 deliveries failed in the last hour (1 device gone)"}
        </span>
      </div>
      <h3>Refresh log</h3>
      <table className="proto-table">
        <thead><tr><th>Time</th><th>Sport</th><th>Trigger</th><th>Cost</th><th>Outcome</th></tr></thead>
        <tbody>
          <tr><td>14:32</td><td>basketball_nba</td><td>auto</td><td>3</td><td>ok · 11 events</td></tr>
          <tr><td>14:27</td><td>basketball_nba</td><td>auto</td><td>3</td><td>ok · 11 events</td></tr>
          <tr><td>14:05</td><td>americanfootball_nfl</td><td>manual</td><td>3</td><td>ok · 14 events</td></tr>
          <tr><td>13:50</td><td>icehockey_nhl</td><td>manual</td><td>0</td><td className="proto-bad">refused · OUT_OF_USAGE_CREDITS</td></tr>
        </tbody>
      </table>
      <h3>Delivery log</h3>
      <table className="proto-table">
        <thead><tr><th>Time</th><th>Event</th><th>Device</th><th>Status</th></tr></thead>
        <tbody>
          <tr><td>14:32</td><td>opportunity · Knicks ML +125</td><td>iPhone</td><td>delivered</td></tr>
          <tr><td>14:32</td><td>opportunity · Knicks ML +125</td><td>MacBook Chrome</td><td className="proto-bad">failed · 410 gone</td></tr>
          <tr><td>12:10</td><td>quota.warning</td><td>iPhone</td><td>delivered</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function Credits() {
  return (
    <div className="proto-stack">
      <div className="proto-meter"><div style={{ width: "8%" }} /><span className="proto-floor" style={{ left: "10%" }} /></div>
      <p><strong>41</strong> of 500 left · floor 50 · resets Dec 1</p>
      <h3>Quota history (stub)</h3>
      <div className="proto-bars">
        {[480, 440, 400, 330, 260, 190, 120, 70, 41].map((v, i) => (
          <div key={i} style={{ height: `${v / 5}px` }} title={`${v}`} />
        ))}
      </div>
      <h3>Burn per sport, this month</h3>
      <table className="proto-table">
        <tbody>
          <tr><td>basketball_nba</td><td>312</td></tr>
          <tr><td>americanfootball_nfl</td><td>120</td></tr>
          <tr><td>icehockey_nhl</td><td>27</td></tr>
        </tbody>
      </table>
    </div>
  );
}

function Controls({ attn }: { attn: Attn }) {
  return (
    <div className="proto-stack">
      <h3>Auto-Refresh</h3>
      <div className="proto-row">
        <label><input type="checkbox" defaultChecked /> On{attn === "paused" ? " (paused: out of credits)" : ""}</label>
        <label>Interval <input type="number" defaultValue={5} style={{ width: 50 }} /> min</label>
        <label>Warn below <input type="number" defaultValue={50} style={{ width: 60 }} /> credits</label>
      </div>
      <h3>Devices</h3>
      <table className="proto-table">
        <thead><tr><th>Label</th><th>Channel</th><th>Status</th><th>Last delivered</th><th /></tr></thead>
        <tbody>
          <tr><td>iPhone</td><td>web push</td><td>active</td><td>14:32</td><td><button>Test</button> <button>Rename</button> <button>Remove</button></td></tr>
          <tr><td>MacBook Chrome</td><td>web push</td><td className="proto-bad">gone</td><td>yesterday</td><td><button disabled>Re-enable</button></td></tr>
        </tbody>
      </table>
      <p><button>Enable notifications on this browser</button> <em>(temporary home until onboarding lands)</em></p>
    </div>
  );
}

function TabBody({ tab, attn }: { tab: Tab; attn: Attn }) {
  if (tab === "systems") return <Systems attn={attn} />;
  if (tab === "credits") return <Credits />;
  return <Controls attn={attn} />;
}

/* ---------- variants ---------- */

type VariantProps = { route: Route; attn: Attn; go: (path: string) => void };

function VariantA({ route, attn, go }: VariantProps) {
  const topbar = (
    <header className="topbar">
      <Brand />
      <div className="topbar-status">
        <AttentionPill attn={attn} onOpen={(t) => go(`/admin/${t}`)} />
        {route.kind === "lines" ? (
          <button className="proto-btn" onClick={() => go("/admin/systems")}>
            <ShieldCheck size={15} /> Admin view
          </button>
        ) : (
          <button className="proto-btn" onClick={() => go("/")}>
            <LineChart size={15} /> Lines
          </button>
        )}
      </div>
    </header>
  );
  if (route.kind === "lines") return <App topbar={topbar} />;
  return (
    <div className="app-shell">
      {topbar}
      <main className="workspace proto-admin">
        <nav className="proto-tabstrip">
          {TABS.map((t) => (
            <button key={t.key} className={route.tab === t.key ? "active" : ""} onClick={() => go(`/admin/${t.key}`)}>
              {t.icon} {t.label}
            </button>
          ))}
        </nav>
        <TabBody tab={route.tab} attn={attn} />
      </main>
    </div>
  );
}

function VariantB({ route, attn, go }: VariantProps) {
  const dot = (tab: Tab) => attn !== "none" && ATTN_COPY[attn].tab === tab;
  const topbar = (
    <header className="topbar">
      <Brand />
      <div className="topbar-status">
        <AttentionPill attn={attn} onOpen={(t) => go(`/admin/${t}`)} />
      </div>
    </header>
  );
  return (
    <div className="proto-rail-layout">
      <aside className="proto-rail">
        <button className={route.kind === "lines" ? "active" : ""} onClick={() => go("/")}>
          <LineChart size={16} /> Lines
        </button>
        <div className="proto-rail-heading">Admin view</div>
        {TABS.map((t) => (
          <button
            key={t.key}
            className={route.kind === "admin" && route.tab === t.key ? "active" : ""}
            onClick={() => go(`/admin/${t.key}`)}
          >
            {t.icon} {t.label} {dot(t.key) && <span className="proto-dot" />}
          </button>
        ))}
      </aside>
      <div className="proto-rail-main">
        {route.kind === "lines" ? (
          <App topbar={topbar} />
        ) : (
          <div className="app-shell">
            {topbar}
            <main className="workspace proto-admin">
              <TabBody tab={route.tab} attn={attn} />
            </main>
          </div>
        )}
      </div>
    </div>
  );
}

function VariantC({ route, attn, go }: VariantProps) {
  if (route.kind === "lines") {
    const topbar = (
      <header className="topbar">
        <Brand />
        <div className="topbar-status">
          <AttentionPill attn={attn} onOpen={(t) => go(`/admin/${t}`)} />
          <button className="proto-icon-btn" title="Admin view" onClick={() => go("/admin/systems")}>
            <ShieldCheck size={18} />
          </button>
        </div>
      </header>
    );
    return <App topbar={topbar} />;
  }
  return (
    <div className="proto-c-shell">
      <header className="proto-c-header">
        <button className="proto-btn" onClick={() => go("/")}>
          <ArrowLeft size={15} /> Exit to lines
        </button>
        <strong>Admin view</strong>
        <span className="proto-c-sub">OddsCafe · operator only</span>
      </header>
      {attn !== "none" && (
        <div className="proto-c-banner" onClick={() => go(`/admin/${ATTN_COPY[attn].tab}`)}>
          <AlertTriangle size={15} /> {ATTN_COPY[attn].text}
        </div>
      )}
      <div className="proto-c-body">
        <nav className="proto-c-tabs">
          {TABS.map((t) => (
            <button key={t.key} className={route.tab === t.key ? "active" : ""} onClick={() => go(`/admin/${t.key}`)}>
              {t.icon} {t.label}
            </button>
          ))}
        </nav>
        <main className="proto-c-main">
          <TabBody tab={route.tab} attn={attn} />
        </main>
      </div>
    </div>
  );
}

/* ---------- switcher ---------- */

export function AdminNavPrototype() {
  const { route, variant, attn, go } = useLocationState();
  const idx = Math.max(0, VARIANTS.findIndex((v) => v.key === variant));
  const nav = (path: string) => go(path);
  const cycle = (d: number) =>
    go(window.location.pathname, { variant: VARIANTS[(idx + d + VARIANTS.length) % VARIANTS.length].key });
  const cycleAttn = () => go(window.location.pathname, { attn: ATTNS[(ATTNS.indexOf(attn) + 1) % ATTNS.length] });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "ArrowLeft") cycle(-1);
      if (e.key === "ArrowRight") cycle(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const props = { route, attn, go: nav };
  return (
    <>
      {variant === "B" ? <VariantB {...props} /> : variant === "C" ? <VariantC {...props} /> : <VariantA {...props} />}
      <div className="proto-switcher">
        <button onClick={() => cycle(-1)}>←</button>
        <span>
          {VARIANTS[idx].key} ({VARIANTS[idx].name})
        </span>
        <button onClick={() => cycle(1)}>→</button>
        <span className="proto-sep" />
        <button onClick={cycleAttn}>attention: {attn}</button>
        <span className="proto-path">{window.location.pathname}</span>
      </div>
    </>
  );
}
