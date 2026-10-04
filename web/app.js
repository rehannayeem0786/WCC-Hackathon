const $ = (id) => document.getElementById(id);
let RULES = { nodes: [], edges: [] };
let FIRINGS = {};   // rule_id -> how many findings it produced this run
let METRICS = null; // last /api/metrics payload
let BUSY = false;   // guards double-clicks while a request is in flight

/* ---------- helpers ---------------------------------------------------- */
function esc(v) {
  return String(v).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const rupee = (n) => "₹" + Number(n).toLocaleString("en-IN");

function toast(msg, kind = "ok") {
  const t = $("toast");
  t.textContent = msg;
  t.dataset.kind = kind;
  t.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { t.hidden = true; }, 4200);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* noop */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ---------- rendering -------------------------------------------------- */
function render(s) {
  $("agent").textContent = s.agent.mode === "llm"
    ? `agent: ${s.agent.provider} · ${s.agent.model}`
    : "agent: offline (deterministic)";

  const open = s.findings.filter((f) => f.status === "open").length;
  const decided = s.findings.length - open;
  $("countBadge").textContent = `${open} open · ${decided} decided`;

  const sm = s.summary;
  $("cards").innerHTML = [
    ["Invoices", sm.invoices], ["Findings", sm.findings],
    ["Errors", sm.errors], ["Warnings", sm.warnings],
    ["₹ at risk", rupee(sm.amount_at_risk)],
    ["Minutes saved*", sm.minutes_saved_estimate],
  ].map(([k, v]) => `<div class="card"><b>${esc(v)}</b><small>${esc(k)}</small></div>`).join("");

  FIRINGS = {};
  for (const f of s.findings) FIRINGS[f.rule_id] = (FIRINGS[f.rule_id] || 0) + 1;

  $("findings").innerHTML = s.findings.length ? s.findings.map(findingHTML).join("")
    : '<p class="muted">No findings — the books are clean.</p>';

  $("ledger").innerHTML = `<table><caption class="sr-only">Ledger entries</caption><tr>
      <th scope="col">Date</th><th scope="col">Vendor</th><th scope="col">Ref</th><th scope="col">Amount</th></tr>` +
    s.ledger.map((e) => `<tr><td>${esc(e.date)}</td><td>${esc(e.vendor)}</td>
      <td>${esc(e.reference)}</td><td>${rupee(e.amount)}</td></tr>`).join("") + "</table>";

  $("audit").innerHTML = s.audit.slice().reverse().map((a) =>
    `<div class="muted" style="font-size:13px">${esc(a.at)} — <code>${esc(a.action)}</code> ${esc(a.finding_id || "")}</div>`
  ).join("") || '<p class="muted">No actions yet.</p>';

  renderKpis(s);
  renderBars(s);
  refreshMetrics();
  drawGraph();
}

/* ---------- KPIs, bars, trust line -------------------------------------- */
function renderKpis(s) {
  const k = $("kpis");
  if (!k) return;
  const sm = s.summary;
  const items = [
    [sm.invoices, "Invoices", false],
    [sm.findings, "Findings", false],
    [sm.errors, "Errors", sm.errors > 0],
    [sm.minutes_saved_estimate, "Minutes saved", false],
  ];
  k.innerHTML = items.map(([v, label, alert]) =>
    `<div class="kpi${alert ? " alert" : ""}"><b>${esc(v)}</b><small>${esc(label)}</small></div>`).join("");
}

function renderBars(s) {
  const box = $("bars");
  if (!box) return;
  if (!s.findings.length) {
    box.innerHTML = '<p class="muted">No findings — the books are clean.</p>';
    return;
  }
  const counts = {}, sev = {};
  for (const f of s.findings) {
    counts[f.rule_id] = (counts[f.rule_id] || 0) + 1;
    sev[f.rule_id] = f.severity;
  }
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = rows[0][1];
  box.innerHTML = rows.map(([rid, n]) =>
    `<div class="bar ${esc(sev[rid])}"><span>${esc(rid)}</span>
     <i style="width:${Math.max(6, Math.round((n / max) * 100))}%"></i><span>${n}</span></div>`).join("");
}

async function refreshMetrics() {
  try {
    METRICS = await api("/api/metrics");
    const t = $("trust");
    if (t) {
      t.textContent = `${METRICS.auto_writes} automatic writes · ${METRICS.decisions.approved} approved · `
        + `${METRICS.approvals_reversed} reversed · ${METRICS.audit_events} audit events`;
    }
    const c = $("countBadge");
    if (c) c.textContent += ` · ${METRICS.auto_writes} auto-writes`;
  } catch (_) { /* metrics are supplementary */ }
}

function findingHTML(f) {
  const decided = f.status !== "open";
  const buttons = decided
    ? `<button data-act="revoke" data-id="${esc(f.id)}">Undo this decision</button>`
    : `<button class="primary" data-act="approve" data-id="${esc(f.id)}">Approve fix</button>
       <button data-act="reject" data-id="${esc(f.id)}">Reject</button>`;
  return `<article class="finding ${esc(f.severity)} ${esc(f.status)}" aria-label="${esc(f.title)}">
    <div class="ftop">
      <strong>${esc(f.title)}</strong>
      <span class="tags">
        <span class="tag">${esc(f.rule_id)}</span>
        <span class="tag">${esc(f.severity)}</span>
        <span class="tag">${esc(f.status)}</span>
      </span>
    </div>
    <p class="why">${esc(f.why)}</p>
    <p class="fix">➜ ${esc(f.suggestion)}</p>
    <details><summary class="muted">evidence &amp; proposed change</summary>
      <div class="evidence">${esc(JSON.stringify({ evidence: f.evidence, proposed_action: f.proposed_action }, null, 2))}</div>
    </details>
    <div class="row" style="margin:9px 0 0">${buttons}</div>
  </article>`;
}

/* ---------- rule knowledge graph --------------------------------------- */
function drawGraph() {
  const svg = $("ruleGraph");
  if (!svg) return;
  const nodes = RULES.nodes || [];
  if (!nodes.length) { svg.innerHTML = ""; return; }

  const W = Math.max(svg.clientWidth || 900, 640);
  const H = 230;
  const cx = W / 2, cy = H / 2, rad = Math.min(W * 0.42, H / 2 - 46);
  const pos = {};
  nodes.forEach((nd, i) => {
    const a = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    pos[nd.id] = { x: cx + rad * Math.cos(a), y: cy + rad * Math.sin(a) };
  });

  const sevColor = { error: "#f87171", warn: "#fbbf24", info: "#60a5fa" };
  let parts = "";

  for (const e of RULES.edges) {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) continue;
    parts += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
      stroke="#3a3f4a" stroke-width="1.5" stroke-dasharray="4 4" />`;
  }

  for (const nd of nodes) {
    const p = pos[nd.id];
    const fired = FIRINGS[nd.id] || 0;
    const color = sevColor[nd.severity] || "#9aa0a6";
    parts += `<g class="node" tabindex="0" role="button"
        aria-label="${nd.id}: ${nd.name}${fired ? ", fired " + fired + " times" : ""}"
        data-rule="${nd.id}">
      <circle cx="${p.x}" cy="${p.y}" r="24" fill="${fired ? color : "#12151b"}"
        stroke="${color}" stroke-width="${fired ? 3 : 1.5}" ${fired ? "" : 'opacity="0.6"'} />
      <text x="${p.x}" y="${p.y + 4}" text-anchor="middle" font-size="11"
        font-family="ui-monospace,monospace" fill="${fired ? "#0b0d12" : "#e8eaed"}"
        font-weight="${fired ? 700 : 400}">${nd.id}</text>
      ${fired ? `<text x="${p.x}" y="${p.y - 30}" text-anchor="middle" font-size="11"
        fill="${color}">×${fired}</text>` : ""}
    </g>`;
  }
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = parts;
}

function explain(ruleId) {
  const nd = (RULES.nodes || []).find((n) => n.id === ruleId);
  if (!nd) return;
  const links = (RULES.edges || [])
    .filter((e) => e.source === ruleId || e.target === ruleId)
    .map((e) => (e.source === ruleId ? e.target : e.source));
  const fired = FIRINGS[ruleId] || 0;
  $("explain").innerHTML = `
    <strong>${esc(nd.id)} — ${esc(nd.name)}</strong>
    <span class="tag">${esc(nd.severity)}</span> <span class="tag">${esc(nd.category)}</span>
    <p style="margin:7px 0 3px">${esc(nd.description)}</p>
    <p class="muted" style="margin:0">
      ${links.length ? "Connects to: " + links.map((l) => `<code>${esc(l)}</code>`).join(", ")
                     : "No related rules — it stands alone."}
      · Fired <strong>${fired}</strong> time${fired === 1 ? "" : "s"} this run.</p>`;
}

/* ---------- actions ---------------------------------------------------- */
async function refresh() { render(await api("/api/state")); }
async function loadSample() { render(await api("/api/load-sample", { method: "POST" })); toast("Sample books loaded."); }
async function runReconcile() { render(await api("/api/reconcile", { method: "POST" })); toast("Reconciled."); }

async function decide(id, act) {
  try {
    const path = act === "revoke"
      ? `/api/findings/${encodeURIComponent(id)}/revoke`
      : `/api/findings/${encodeURIComponent(id)}/${act}`;
    render(await api(path, { method: "POST" }));
    toast(act === "revoke" ? "Decision undone — books rolled back."
        : act === "approve" ? "Fix applied and logged." : "Finding rejected.");
  } catch (err) { toast(err.message, "error"); }
}

async function uploadCSV(file) {
  const body = new FormData();
  body.append("file", file);
  try {
    render(await api("/api/ingest", { method: "POST", body }));
    toast(`Loaded ${file.name}.`);
  } catch (err) { toast(err.message, "error"); }
}

async function purge() {
  if (!confirm("Permanently delete all invoices, findings and history? This cannot be undone.")) return;
  try { render(await api("/api/purge", { method: "POST" })); toast("All data deleted."); }
  catch (err) { toast(err.message, "error"); }
}

/* ---------- approve with an explicit BEFORE/AFTER confirmation ---------- */
function fmtVal(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  return String(v);
}

function askConfirm(preview, finding) {
  return new Promise((resolve) => {
    const dlg = $("confirm");
    $("confirmTitle").textContent = finding ? `Approve: ${finding.title}` : "Approve this change?";
    $("confirmBody").innerHTML = (preview.changes_data && preview.before !== null)
      ? `<div class="diff">
           <div class="before"><small>Before</small><b>${esc(fmtVal(preview.before))}</b></div>
           <div class="arrow">→</div>
           <div class="after"><small>After</small><b>${esc(fmtVal(preview.after))}</b></div>
         </div>
         <p class="muted" style="margin:0;font-size:13px">${esc(preview.entity)}${
           preview.delta != null ? ` · change ${preview.delta > 0 ? "+" : ""}${preview.delta}` : ""}</p>`
      : `<p style="margin:14px 0 0">${esc(preview.entity)} — <strong>no data will be modified.</strong></p>`;

    let settled = false;
    const cleanup = () => {
      $("confirmYes").removeEventListener("click", onYes);
      $("confirmNo").removeEventListener("click", onNo);
    };
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      cleanup();
      dlg.close();
      resolve(ok);
    };
    const onYes = () => finish(true);
    const onNo = () => finish(false);
    $("confirmYes").addEventListener("click", onYes);
    $("confirmNo").addEventListener("click", onNo);
    dlg.addEventListener("close", () => finish(false), { once: true });

    if (typeof dlg.showModal === "function") dlg.showModal();
    else dlg.setAttribute("open", "");
    $("confirmYes").focus();
  });
}

async function approveWithConfirm(id) {
  if (BUSY) return;
  BUSY = true;
  try {
    const snap = await api("/api/state");
    const finding = snap.findings.find((f) => f.id === id);
    const preview = await api(`/api/findings/${encodeURIComponent(id)}/preview`);
    if (await askConfirm(preview, finding)) await decide(id, "approve");
  } catch (err) { toast(err.message, "error"); }
  finally { BUSY = false; }
}

/* ---------- guided demo (one button, no misclicks) ---------------------- */
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function scrollToEl(sel) {
  const el = document.querySelector(sel);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  await wait(650);
}

async function runGuidedDemo() {
  if (BUSY) return;
  BUSY = true;
  const btn = $("demoBtn");
  const label = btn.textContent;
  btn.disabled = true;
  try {
    btn.textContent = "1/6 · Loading 8 sample bills…";
    await loadSample(); await wait(700);

    btn.textContent = "2/6 · Reconciling against the rule graph…";
    await runReconcile(); await wait(900);

    btn.textContent = "3/6 · Here are the 8 problems found";
    await scrollToEl("#findings"); await wait(1700);

    const snap = await api("/api/state");
    const t = snap.findings.find((f) => f.rule_id === "R2.2");
    if (t) {
      await scrollToEl(`button[data-id="${CSS.escape(t.id)}"]`);
      btn.textContent = "⏸ 4/6 · Your approval is required — that's the point";
      await approveWithConfirm(t.id);
      await wait(700);

      btn.textContent = "5/6 · Undoing it — nothing here is permanent";
      await api(`/api/findings/${encodeURIComponent(t.id)}/revoke`, { method: "POST" }).then(render);
      await wait(1400);
    }

    btn.textContent = "6/6 · Done — now try your own CSV ↑";
    toast("Guided demo complete. Your turn.");
  } catch (err) { toast(err.message, "error"); }
  finally { btn.disabled = false; btn.textContent = label; BUSY = false; }
}

/* ---------- wiring ------------------------------------------------------ */
document.addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (btn) {
    if (btn.dataset.act === "approve") approveWithConfirm(btn.dataset.id);
    else decide(btn.dataset.id, btn.dataset.act);
    return;
  }
  const node = ev.target.closest(".node");
  if (node) explain(node.dataset.rule);
});
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter" && ev.key !== " ") return;
  const node = ev.target.closest && ev.target.closest(".node");
  if (node) { ev.preventDefault(); explain(node.dataset.rule); }
});

$("load").onclick = loadSample;
$("run").onclick = runReconcile;
$("refresh").onclick = refresh;
$("purge").onclick = purge;
$("demoBtn").onclick = runGuidedDemo;
$("file").onchange = (e) => { if (e.target.files[0]) uploadCSV(e.target.files[0]); e.target.value = ""; };

window.addEventListener("resize", () => drawGraph());

(async () => {
  try { RULES = await api("/api/rule-graph"); } catch (_) { /* graph is optional */ }
  try {
    const s = await api("/api/state");
    render(s);
    if (!s.summary.invoices) toast("Start with “Load sample books” or upload your own CSV.");
  } catch (err) { toast(err.message, "error"); }
})();

