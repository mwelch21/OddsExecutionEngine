from fastapi import APIRouter
from fastapi.responses import HTMLResponse


def create_test_ui_router() -> APIRouter:
    router = APIRouter(tags=["testing"])

    @router.get("/test-ui", response_class=HTMLResponse)
    def test_ui() -> HTMLResponse:
        return HTMLResponse(content=_build_html())

    return router


def _build_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OddsExecutionEngine Testing Dashboard</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242736;
    --border: #2e3145;
    --text: #e1e4ed;
    --text-dim: #8b8fa3;
    --green: #22c55e;
    --red: #ef4444;
    --orange: #f59e0b;
    --blue: #3b82f6;
    --blue-hover: #2563eb;
    --mono: 'SF Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  header h1 { font-size: 18px; font-weight: 600; }
  .env-badge {
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 4px;
    background: var(--green);
    color: #000;
    font-weight: 600;
    text-transform: uppercase;
  }
  .main {
    display: grid;
    grid-template-columns: 340px 1fr;
    gap: 0;
    height: calc(100vh - 57px);
  }
  .sidebar {
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 16px;
    overflow-y: auto;
  }
  .sidebar h2 {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-dim);
    margin-bottom: 12px;
  }
  .scenario-btn {
    display: block;
    width: 100%;
    text-align: left;
    padding: 10px 12px;
    margin-bottom: 6px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 13px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  .scenario-btn:hover { border-color: var(--blue); background: #1e2235; }
  .scenario-btn.active { border-color: var(--blue); background: #1a2440; }
  .scenario-btn .label { font-weight: 500; }
  .scenario-btn .desc { color: var(--text-dim); font-size: 11px; margin-top: 2px; }
  .divider { border-top: 1px solid var(--border); margin: 16px 0; }
  .custom-section { margin-top: 8px; }
  .custom-section label {
    display: block;
    font-size: 12px;
    color: var(--text-dim);
    margin-bottom: 4px;
    font-weight: 500;
  }
  select, textarea {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-family: var(--mono);
    font-size: 12px;
    padding: 8px;
    margin-bottom: 8px;
    resize: vertical;
  }
  select { font-family: inherit; cursor: pointer; }
  textarea { min-height: 120px; }
  .btn-row { display: flex; gap: 8px; }
  .btn {
    flex: 1;
    padding: 8px 12px;
    border: none;
    border-radius: 4px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn-primary { background: var(--blue); color: #fff; }
  .btn-primary:hover { background: var(--blue-hover); }
  .btn-secondary {
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
  }
  .btn-secondary:hover { background: #2a2d40; }
  .response-panel {
    padding: 24px;
    overflow-y: auto;
  }
  .response-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .status-pill {
    font-size: 13px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 4px;
  }
  .status-200 { background: #14532d; color: var(--green); }
  .status-422 { background: #451a03; color: var(--orange); }
  .status-err { background: #450a0a; color: var(--red); }
  .fill-badge {
    font-size: 12px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 3px;
  }
  .fill-yes { background: #14532d; color: var(--green); }
  .fill-no { background: #450a0a; color: var(--red); }
  .timing { font-size: 12px; color: var(--text-dim); }
  .response-body {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: calc(100vh - 180px);
    overflow-y: auto;
  }
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-dim);
    font-size: 14px;
  }
  .run-all-results {
    margin-top: 16px;
    font-size: 13px;
  }
  .run-all-results .result-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
  }
  .result-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .result-dot.pass { background: var(--green); }
  .result-dot.fail { background: var(--red); }
  .result-dot.pending { background: var(--text-dim); }
  .result-name { flex: 1; }
  .result-status { font-size: 12px; color: var(--text-dim); }
  .json-key { color: #7dd3fc; }
  .json-string { color: #86efac; }
  .json-number { color: #fbbf24; }
  .json-bool { color: #c084fc; }
  .json-null { color: #94a3b8; }
</style>
</head>
<body>
<header>
  <h1>OddsExecutionEngine Testing Dashboard</h1>
  <span class="env-badge">development</span>
</header>
<div class="main">
  <div class="sidebar">
    <h2>Quick Scenarios</h2>
    <div id="scenario-buttons"></div>
    <div class="divider"></div>
    <h2>Custom Request</h2>
    <div class="custom-section">
      <label>Method + Endpoint</label>
      <select id="custom-method-endpoint">
        <option value="POST /execution/recommendation">POST /execution/recommendation</option>
        <option value="POST /ingestion/quotes/refresh">POST /ingestion/quotes/refresh</option>
        <option value="POST /ingestion/quotes/refresh-sport">POST /ingestion/quotes/refresh-sport</option>
        <option value="POST /watch-intents">POST /watch-intents</option>
        <option value="GET /watch-intents">GET /watch-intents</option>
        <option value="DELETE /watch-intents/{id}">DELETE /watch-intents/{id}</option>
        <option value="GET /opportunities">GET /opportunities</option>
        <option value="GET /health">GET /health</option>
      </select>
      <label>Request Body (JSON)</label>
      <textarea id="custom-body">{
  "event_id": "nba-knicks-celtics-2026-04-11",
  "market_type": "moneyline",
  "selection": "knicks",
  "target_price": 121
}</textarea>
      <div class="btn-row">
        <button class="btn btn-primary" onclick="sendCustom()">Send</button>
        <button class="btn btn-secondary" onclick="runAll()">Run All</button>
      </div>
      <div id="run-all-results" class="run-all-results"></div>
    </div>
  </div>
  <div class="response-panel" id="response-panel">
    <div class="empty-state">Select a scenario or send a custom request</div>
  </div>
</div>

<script>
const SCENARIOS = [
  {
    key: "fillable-moneyline",
    label: "Fillable Moneyline",
    desc: "Knicks +121 target (DraftKings has +125)",
    method: "POST",
    endpoint: "/execution/recommendation",
    body: {
      event_id: "nba-knicks-celtics-2026-04-11",
      market_type: "moneyline",
      selection: "knicks",
      target_price: 121
    }
  },
  {
    key: "unfillable-total",
    label: "Unfillable Total",
    desc: "Over 221.5 at -105 (best is -108)",
    method: "POST",
    endpoint: "/execution/recommendation",
    body: {
      event_id: "nba-knicks-celtics-2026-04-11",
      market_type: "total",
      selection: "over",
      line: 221.5,
      target_price: -105
    }
  },
  {
    key: "unmatched-spread",
    label: "Unmatched Spread",
    desc: "Knicks 6.5 at -110 (no quotes at this line)",
    method: "POST",
    endpoint: "/execution/recommendation",
    body: {
      event_id: "nba-knicks-celtics-2026-04-11",
      market_type: "spread",
      selection: "knicks",
      line: 6.5,
      target_price: -110
    }
  },
  {
    key: "quote-refresh",
    label: "Quote Refresh",
    desc: "Refresh quotes for Knicks vs Celtics fixture",
    method: "POST",
    endpoint: "/ingestion/quotes/refresh",
    body: { event_id: "nba-knicks-celtics-2026-04-11" }
  },
  {
    key: "health",
    label: "Health Check",
    desc: "GET /health",
    method: "GET",
    endpoint: "/health",
    body: null
  },
  {
    key: "validation-invalid-total",
    label: "Invalid Total Selection",
    desc: "Expects 422 - selection must be over/under",
    method: "POST",
    endpoint: "/execution/recommendation",
    body: {
      event_id: "nba-knicks-celtics-2026-04-11",
      market_type: "total",
      selection: "knicks",
      line: 221.5,
      target_price: -110
    }
  },
  {
    key: "validation-ml-line",
    label: "Moneyline with Line",
    desc: "Expects 422 - moneyline must omit line",
    method: "POST",
    endpoint: "/execution/recommendation",
    body: {
      event_id: "nba-knicks-celtics-2026-04-11",
      market_type: "moneyline",
      selection: "knicks",
      line: 1.5,
      target_price: 120
    }
  },
  {
    key: "create-watch-intent",
    label: "Create Watch Intent",
    desc: "Watch Knicks ML at -150 (should find opportunities)",
    method: "POST",
    endpoint: "/watch-intents",
    body: {
      event_id: "nba-knicks-celtics-2026-04-11",
      market_type: "moneyline",
      selection: "knicks",
      target_price: -150
    }
  },
  {
    key: "create-watch-spread",
    label: "Create Watch (Spread)",
    desc: "Watch Knicks spread +5.5 at -110",
    method: "POST",
    endpoint: "/watch-intents",
    body: {
      event_id: "nba-knicks-celtics-2026-04-11",
      market_type: "spread",
      selection: "knicks",
      line: 5.5,
      target_price: -110
    }
  },
  {
    key: "list-watch-intents",
    label: "List Watch Intents",
    desc: "GET all active watch intents",
    method: "GET",
    endpoint: "/watch-intents",
    body: null
  },
  {
    key: "list-watch-intents-event",
    label: "List Watch Intents (by event)",
    desc: "Filter watch intents by event_id",
    method: "GET",
    endpoint: "/watch-intents?event_id=nba-knicks-celtics-2026-04-11",
    body: null
  },
  {
    key: "list-opportunities",
    label: "List Opportunities",
    desc: "GET all opportunities with computed validity",
    method: "GET",
    endpoint: "/opportunities",
    body: null
  },
  {
    key: "list-opportunities-event",
    label: "List Opportunities (by event)",
    desc: "Filter opportunities by event_id",
    method: "GET",
    endpoint: "/opportunities?event_id=nba-knicks-celtics-2026-04-11",
    body: null
  },
  {
    key: "validation-watch-ml-line",
    label: "Watch Intent: ML with Line",
    desc: "Expects 422 - moneyline must omit line",
    method: "POST",
    endpoint: "/watch-intents",
    body: {
      event_id: "nba-knicks-celtics-2026-04-11",
      market_type: "moneyline",
      selection: "knicks",
      line: 1.5,
      target_price: 120
    }
  },
  {
    key: "refresh-nhl",
    label: "Refresh NHL (Live)",
    desc: "Fetch all NHL odds from The Odds API",
    method: "POST",
    endpoint: "/ingestion/quotes/refresh-sport",
    body: { sport: "icehockey_nhl" }
  },
  {
    key: "refresh-mlb",
    label: "Refresh MLB (Live)",
    desc: "Fetch all MLB odds from The Odds API",
    method: "POST",
    endpoint: "/ingestion/quotes/refresh-sport",
    body: { sport: "baseball_mlb" }
  }
];

function renderScenarioButtons() {
  const container = document.getElementById("scenario-buttons");
  SCENARIOS.forEach((s, i) => {
    const btn = document.createElement("button");
    btn.className = "scenario-btn";
    btn.innerHTML = '<div class="label">' + escapeHtml(s.label)
      + '</div><div class="desc">' + escapeHtml(s.desc) + '</div>';
    btn.onclick = () => sendScenario(i);
    btn.id = "scenario-btn-" + i;
    container.appendChild(btn);
  });
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

async function sendScenario(index) {
  document.querySelectorAll(".scenario-btn").forEach(b => b.classList.remove("active"));
  const btn = document.getElementById("scenario-btn-" + index);
  if (btn) btn.classList.add("active");

  const s = SCENARIOS[index];
  await sendRequest(s.method, s.endpoint, s.body);
}

async function sendCustom() {
  const sel = document.getElementById("custom-method-endpoint").value;
  const parts = sel.split(" ");
  const method = parts[0];
  let endpoint = parts.slice(1).join(" ");
  let body = null;
  if (method === "DELETE" && endpoint.includes("{id}")) {
    const id = prompt("Enter watch intent ID to cancel:");
    if (!id) return;
    endpoint = endpoint.replace("{id}", id);
  }
  if (method !== "GET" && method !== "DELETE") {
    try {
      body = JSON.parse(document.getElementById("custom-body").value);
    } catch (e) {
      showError("Invalid JSON: " + e.message);
      return;
    }
  }
  await sendRequest(method, endpoint, body);
}

async function sendRequest(method, endpoint, body) {
  const panel = document.getElementById("response-panel");
  panel.innerHTML = '<div class="empty-state">Loading...</div>';

  const startTime = performance.now();
  let response, data, status;
  try {
    const opts = { method, headers: {} };
    if (body !== null && method !== "GET" && method !== "DELETE") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    response = await fetch(endpoint, opts);
    status = response.status;
    data = await response.json();
  } catch (e) {
    showError("Request failed: " + e.message);
    return { status: 0, data: null };
  }
  const elapsed = Math.round(performance.now() - startTime);

  let headerHtml = '';

  const isSuccess = status >= 200 && status < 300;
  const statusClass = isSuccess ? "status-200" : status === 422 ? "status-422" : "status-err";
  headerHtml += '<span class="status-pill ' + statusClass + '">' + status + '</span>';

  if (data && typeof data.fillable === "boolean") {
    const fillClass = data.fillable ? "fill-yes" : "fill-no";
    const fillText = data.fillable ? "FILLABLE" : "NOT FILLABLE";
    headerHtml += '<span class="fill-badge ' + fillClass + '">' + fillText + '</span>';
  }

  if (data && typeof data.events_refreshed === "number") {
    headerHtml += '<span class="fill-badge" style="background:#1e3a5f;color:#7dd3fc">'
      + data.events_refreshed + ' event(s)</span>';
  }
  if (data && Array.isArray(data.watch_intents)) {
    headerHtml += '<span class="fill-badge" style="background:#1e3a5f;color:#7dd3fc">'
      + data.watch_intents.length + ' intent(s)</span>';
  }
  if (data && Array.isArray(data.opportunities)) {
    const valid = data.opportunities.filter(o => o.is_valid).length;
    const total = data.opportunities.length;
    const color = valid > 0 ? "background:#14532d;color:var(--green)" : "background:#451a03;color:var(--orange)";
    headerHtml += '<span class="fill-badge" style="' + color + '">'
      + valid + '/' + total + ' valid</span>';
  }

  headerHtml += '<span class="timing">' + elapsed + 'ms</span>';

  panel.innerHTML = '<div class="response-header">' + headerHtml + '</div>'
    + '<pre class="response-body">' + syntaxHighlight(JSON.stringify(data, null, 2)) + '</pre>';

  return { status, data };
}

function showError(msg) {
  const panel = document.getElementById("response-panel");
  panel.innerHTML = '<div class="response-header">'
    + '<span class="status-pill status-err">ERROR</span></div>'
    + '<pre class="response-body">' + escapeHtml(msg) + '</pre>';
}

function syntaxHighlight(json) {
  return json.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"([^"]+)"(?=\\s*:)/g, '<span class="json-key">"$1"</span>')
    .replace(/: "([^"]*)"/g, ': <span class="json-string">"$1"</span>')
    .replace(/: (-?\\d+\\.?\\d*)/g, ': <span class="json-number">$1</span>')
    .replace(/: (true|false)/g, ': <span class="json-bool">$1</span>')
    .replace(/: (null)/g, ': <span class="json-null">$1</span>');
}

async function runAll() {
  const container = document.getElementById("run-all-results");
  container.innerHTML = SCENARIOS.map((s, i) =>
    '<div class="result-row" id="run-result-' + i + '">'
    + '<span class="result-dot pending"></span>'
    + '<span class="result-name">' + escapeHtml(s.label) + '</span>'
    + '<span class="result-status">pending</span>'
    + '</div>'
  ).join("");

  let passed = 0;
  for (let i = 0; i < SCENARIOS.length; i++) {
    const s = SCENARIOS[i];
    const row = document.getElementById("run-result-" + i);
    const dot = row.querySelector(".result-dot");
    const statusSpan = row.querySelector(".result-status");

    const startTime = performance.now();
    try {
      const opts = { method: s.method, headers: {} };
      if (s.body !== null && s.method !== "GET" && s.method !== "DELETE") {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(s.body);
      }
      const resp = await fetch(s.endpoint, opts);
      const elapsed = Math.round(performance.now() - startTime);
      const expectError = s.key.startsWith("validation-");
      const ok = expectError ? resp.status === 422 : (resp.status >= 200 && resp.status < 300);

      dot.className = "result-dot " + (ok ? "pass" : "fail");
      statusSpan.textContent = resp.status + " " + elapsed + "ms";
      if (ok) passed++;
    } catch (e) {
      dot.className = "result-dot fail";
      statusSpan.textContent = "error";
    }
  }

  container.innerHTML += '<div style="margin-top:12px;font-weight:600;color:'
    + (passed === SCENARIOS.length ? 'var(--green)' : 'var(--red)')
    + '">' + passed + ' / ' + SCENARIOS.length + ' passed</div>';
}

renderScenarioButtons();
</script>
</body>
</html>"""
