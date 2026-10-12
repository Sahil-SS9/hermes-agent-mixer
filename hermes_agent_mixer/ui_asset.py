"""The console page, as one string so the package stays a single wheel with no data files.

Design: the "Retro agent steering console" approved by Sahil on 12/10/26 — glowing green
AGENT MIXER // STEERING CONSOLE header, telemetry status bar, four segmented-slider dial rows
with orange handles and VALUE boxes, a live STEERING POLICY (PREVIEW) JSON panel and the
glowing copy / terminal buttons. Static art only; state arrives from /api/state.
"""
from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Mixer — Steering Console</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#050a0e; --card-edge:#16232c; --grid:rgba(45,212,191,.05);
    --green:#4ade80; --orange:#fb923c; --orange-deep:#f97316; --teal-off:#12333a;
    --ink:#e8f0ea; --muted:#5f7a72; --label:#435b54;
    --mono:"JetBrains Mono",ui-monospace,Menlo,monospace;
    --disp:"Space Grotesk",Inter,sans-serif;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    background:
      radial-gradient(1200px 700px at 50% 30%, rgba(16,42,38,.35), transparent 60%),
      linear-gradient(var(--grid) 1px, transparent 1px) 0 0/44px 44px,
      linear-gradient(90deg, var(--grid) 1px, transparent 1px) 0 0/44px 44px,
      var(--bg);
    color:var(--ink); font-family:Inter,"Segoe UI",sans-serif;
    display:flex; align-items:center; justify-content:center; min-height:100vh;
    padding:56px 24px; position:relative;
  }
  body::after{content:"";position:fixed;inset:0;pointer-events:none;
    background:repeating-linear-gradient(0deg, rgba(0,0,0,.16) 0 1px, transparent 1px 3px),
      radial-gradient(120% 90% at 50% 40%, transparent 55%, rgba(0,0,0,.5) 100%);}
  .console{position:relative;width:min(980px,100%);
    background:linear-gradient(180deg, rgba(13,22,28,.92), rgba(9,15,20,.96));
    border:1px solid var(--card-edge); border-radius:18px; padding:34px 38px 30px;
    box-shadow:0 0 0 1px rgba(74,222,128,.05), 0 30px 80px rgba(0,0,0,.65), 0 0 120px rgba(20,80,60,.12);}
  .rivet{position:absolute;width:9px;height:9px;border-radius:50%;
    background:radial-gradient(circle at 35% 30%, #2c3f3a, #0c1412 70%);
    box-shadow:inset 0 1px 1px rgba(255,255,255,.15), 0 0 4px rgba(0,0,0,.8)}
  .rivet.tl{top:12px;left:12px}.rivet.tr{top:12px;right:12px}
  .rivet.bl{bottom:12px;left:12px}.rivet.br{bottom:12px;right:12px}
  .bracket{position:absolute;width:26px;height:26px;border:2px solid rgba(74,222,128,.4)}
  .bracket.tl{top:-2px;left:-2px;border-right:0;border-bottom:0;border-radius:8px 0 0 0}
  .bracket.tr{top:-2px;right:-2px;border-left:0;border-bottom:0;border-radius:0 8px 0 0}
  .bracket.bl{bottom:-2px;left:-2px;border-right:0;border-top:0;border-radius:0 0 0 8px}
  .bracket.br{bottom:-2px;right:-2px;border-left:0;border-top:0;border-radius:0 0 8px 0}
  header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px}
  .title-block{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
  h1{font-family:var(--disp);font-weight:700;font-size:34px;letter-spacing:.14em;
    color:var(--green);text-shadow:0 0 18px rgba(74,222,128,.55), 0 0 46px rgba(74,222,128,.25);}
  .subtitle{font-family:var(--mono);font-size:13px;letter-spacing:.28em;color:var(--muted)}
  .head-right{display:flex;align-items:center;gap:16px}
  .pill{display:inline-flex;align-items:center;gap:8px;padding:8px 16px;border-radius:999px;
    background:rgba(10,26,18,.7);border:1px solid rgba(74,222,128,.35);
    font-family:var(--mono);font-size:12.5px;font-weight:500;letter-spacing:.08em;color:var(--green);}
  .pill .dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green);
    animation:pulse 2.2s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
  .signal{display:flex;align-items:flex-end;gap:3px;height:18px}
  .signal i{width:4px;border-radius:1px;background:var(--orange-deep);display:block}
  .signal i:nth-child(1){height:5px;opacity:.45}
  .signal i:nth-child(2){height:9px;opacity:.65}
  .signal i:nth-child(3){height:13px;opacity:.85}
  .signal i:nth-child(4){height:18px;box-shadow:0 0 8px rgba(249,115,22,.7)}
  .statusbar{display:flex;align-items:center;border:1px solid var(--card-edge);border-radius:10px;
    background:rgba(8,14,18,.8); padding:10px 6px;margin-bottom:26px;
    font-family:var(--mono);font-size:12.5px;letter-spacing:.06em;flex-wrap:wrap;gap:6px;}
  .stat{display:flex;align-items:center;gap:8px;padding:0 18px}
  .stat+.stat{border-left:1px solid #142028}
  .stat .k{color:var(--label)}
  .stat .v{color:#c9d6cf}
  .stat .v.green{color:var(--green);text-shadow:0 0 8px rgba(74,222,128,.5)}
  .stat .v.orange{color:var(--orange)}
  .rows{display:flex;flex-direction:column;gap:14px;margin-bottom:24px}
  .crow{display:grid;grid-template-columns:200px 1fr 148px;gap:22px;align-items:center;
    background:rgba(11,19,25,.85); border:1px solid var(--card-edge);border-radius:12px; padding:16px 20px;}
  .crow .num{font-family:var(--mono);font-size:13px;font-weight:700;color:var(--orange-deep);letter-spacing:.1em}
  .crow .name{font-family:var(--disp);font-size:17px;font-weight:600;color:var(--green);letter-spacing:.03em;
    text-shadow:0 0 10px rgba(74,222,128,.35)}
  .crow .desc{font-size:12.5px;color:var(--muted);margin-top:3px}
  .crow .num-name{display:flex;gap:14px;align-items:baseline}
  .crow .src{font-family:var(--mono);font-size:9px;letter-spacing:.14em;color:var(--label);margin-top:4px}
  .slide-wrap{display:flex;flex-direction:column;gap:8px}
  .slider{position:relative;height:22px;display:flex;align-items:center;cursor:pointer}
  .ticks{display:flex;gap:3px;width:100%}
  .ticks i{flex:1;height:10px;border-radius:2px;background:var(--teal-off);
    box-shadow:inset 0 0 0 1px rgba(255,255,255,.03);transition:background .12s}
  .ticks i.on{background:var(--green);box-shadow:0 0 8px rgba(74,222,128,.55)}
  .handle{position:absolute;top:50%;transform:translate(-50%,-50%);width:8px;height:22px;border-radius:3px;
    background:var(--orange-deep);box-shadow:0 0 10px rgba(249,115,22,.8), 0 0 2px rgba(0,0,0,.9);
    transition:left .12s}
  .ends{display:flex;justify-content:space-between;
    font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;color:var(--label)}
  .value{display:flex;align-items:center;justify-content:space-between;gap:10px;
    border:1px solid rgba(74,222,128,.5);border-radius:8px; background:rgba(6,18,13,.75); padding:10px 12px;
    font-family:var(--mono);font-size:13.5px;font-weight:500;color:var(--green);
    text-shadow:0 0 8px rgba(74,222,128,.4);}
  .value .chev{color:rgba(74,222,128,.6);font-size:10px}
  .value .k{display:block;font-size:8.5px;letter-spacing:.18em;color:var(--label);margin-bottom:3px}
  .value select{width:100%;background:transparent;border:0;color:var(--green);
    font-family:var(--mono);font-size:13.5px;font-weight:500;outline:none;cursor:pointer;
    text-shadow:0 0 8px rgba(74,222,128,.4)}
  .value select option{background:#0b1218;color:#e8f0ea}
  .lines-value{display:flex;align-items:center;gap:8px}
  .lines-value input{width:74px;background:transparent;border:0;border-bottom:1px solid rgba(74,222,128,.4);
    color:var(--green);font-family:var(--mono);font-size:13.5px;text-align:right;outline:none;
    text-shadow:0 0 8px rgba(74,222,128,.4)}
  .chip{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;color:var(--muted);
    border:1px solid #1d2f33;border-radius:5px;padding:2px 7px;background:rgba(255,255,255,.03)}
  .chip-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  .chip-row .chip{cursor:pointer}
  .chip-row .chip:hover{color:var(--green);border-color:rgba(74,222,128,.5)}
  .codebox{border:1px solid var(--card-edge);border-radius:12px;overflow:hidden;
    background:rgba(7,12,16,.92);margin-bottom:20px;}
  .codebox .bar{display:flex;align-items:center;justify-content:space-between;
    padding:10px 16px;border-bottom:1px solid var(--card-edge);
    font-family:var(--mono);font-size:11px;letter-spacing:.16em;color:var(--muted);
    background:rgba(10,17,22,.9);}
  .codebox .bar .left{display:flex;align-items:center;gap:10px}
  .codebox .bar .tri{color:var(--orange);font-size:9px}
  .codebox .bar .right{display:flex;align-items:center;gap:10px;color:var(--label)}
  .codebox .bar .cp{width:14px;height:14px;stroke:var(--muted);stroke-width:1.6;fill:none;cursor:pointer}
  .codebox .bar .cp:hover{stroke:var(--green)}
  .code{padding:16px 18px;font-family:var(--mono);font-size:14px;line-height:1.75;white-space:pre}
  .code .ln{display:inline-block;width:26px;color:#2e423c;user-select:none}
  .code .p{color:#8fa6b3}
  .code .key{color:#e8f0ea}
  .code .val{color:var(--green);text-shadow:0 0 8px rgba(74,222,128,.35)}
  .code .num{color:var(--orange)}
  .console-log{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin:-8px 0 20px;
    min-height:18px}
  .console-log .err{color:var(--orange)}
  .console-log .ok{color:var(--green)}
  .actions{display:flex;gap:14px}
  .btn{flex:1;display:flex;align-items:center;justify-content:center;gap:12px;
    padding:15px 18px;border-radius:12px;cursor:pointer;font-family:Inter,sans-serif;
    font-size:14.5px;font-weight:600;border:1px solid transparent;}
  .btn .kbd{font-family:var(--mono);font-size:10.5px;padding:3px 7px;border-radius:5px;letter-spacing:.06em}
  .btn.primary{background:linear-gradient(180deg,#7ef0a8,#3fd97e); color:#04120a;border-color:#8ff5b6;
    box-shadow:0 0 24px rgba(74,222,128,.4), inset 0 1px 0 rgba(255,255,255,.5);}
  .btn.primary:hover{box-shadow:0 0 34px rgba(74,222,128,.6), inset 0 1px 0 rgba(255,255,255,.5)}
  .btn.primary .kbd{background:rgba(4,18,10,.15);color:#0a3520;border:1px solid rgba(4,18,10,.25)}
  .btn.primary .ic{stroke:#04120a}
  .btn.ghost{background:rgba(13,22,28,.7);color:#9fb4ab;border-color:#1d2f33;}
  .btn.ghost:hover{color:var(--ink)}
  .btn.ghost .kbd{background:rgba(255,255,255,.04);color:#6b857c;border:1px solid #22383c}
  .btn .ic{width:16px;height:16px;stroke:currentColor;stroke-width:1.8;fill:none}
  .warn{font-family:var(--mono);font-size:11px;color:var(--orange);margin:-10px 0 16px}
  @media (max-width:860px){
    .crow{grid-template-columns:1fr;gap:12px}
    .actions{flex-direction:column}
  }
</style>
</head>
<body>
<main class="console">
  <span class="bracket tl"></span><span class="bracket tr"></span>
  <span class="bracket bl"></span><span class="bracket br"></span>
  <span class="rivet tl"></span><span class="rivet tr"></span>
  <span class="rivet bl"></span><span class="rivet br"></span>

  <header>
    <div class="title-block">
      <h1>AGENT MIXER</h1>
      <span class="subtitle">// STEERING CONSOLE</span>
    </div>
    <div class="head-right">
      <span class="pill"><span class="dot"></span>Running</span>
      <span class="signal" title="agent signal"><i></i><i></i><i></i><i></i></span>
    </div>
  </header>

  <div class="statusbar">
    <div class="stat"><span class="k">AGENT</span><span class="v green">ONLINE</span></div>
    <div class="stat"><span class="k">TARGET</span><span class="v" id="s-target">…</span></div>
    <div class="stat"><span class="k">VERSION</span><span class="v" id="s-version">…</span></div>
  </div>

  <div class="warn" id="warnings" hidden></div>

  <section class="rows">
    <div class="crow">
      <div>
        <div class="num-name"><span class="num">01</span>
          <div><div class="name">Edits</div><div class="desc">what file changes may do</div></div>
        </div>
        <div class="src" id="src-edits"></div>
      </div>
      <div class="slide-wrap">
        <div class="slider" data-dial="edits">
          <div class="ticks" id="ticks-edits"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
          <div class="handle" id="handle-edits" style="left:50%"></div>
        </div>
        <div class="ends"><span>LESS CONSERVATIVE</span><span>MORE FREEDOM</span></div>
      </div>
      <div class="value"><span><span class="k">VALUE</span>
        <select id="sel-edits" data-dial="edits" aria-label="edits mode">
          <option value="ask">ask</option><option value="auto">auto</option><option value="plan">plan</option>
        </select></span><span class="chev">▼</span></div>
    </div>

    <div class="crow">
      <div>
        <div class="num-name"><span class="num">02</span>
          <div><div class="name">Change scope</div><div class="desc">which folders it may touch</div></div>
        </div>
        <div class="src" id="src-scope"></div>
      </div>
      <div class="slide-wrap">
        <div class="slider" data-dial="scope">
          <div class="ticks" id="ticks-scope"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
          <div class="handle" id="handle-scope" style="left:8%"></div>
        </div>
        <div class="ends"><span>NARROW</span><span>BROADER</span></div>
        <div class="chip-row" id="scope-chips"></div>
      </div>
      <div class="value"><span><span class="k">VALUE</span><span id="val-scope">…</span></span><span class="chev">▼</span></div>
    </div>

    <div class="crow">
      <div>
        <div class="num-name"><span class="num">03</span>
          <div><div class="name">Lines per turn</div><div class="desc">how much it may change in one go</div></div>
        </div>
        <div class="src" id="src-lines"></div>
      </div>
      <div class="slide-wrap">
        <div class="slider" data-dial="lines">
          <div class="ticks" id="ticks-lines"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
          <div class="handle" id="handle-lines" style="left:8%"></div>
        </div>
        <div class="ends"><span>OFF</span><span>LARGER</span></div>
      </div>
      <div class="value"><span class="lines-value"><span class="k">VALUE</span>
        <input id="in-lines" inputmode="numeric" aria-label="lines per turn" placeholder="off">
        <button class="chip" id="btn-lines-set" type="button">SET</button></span></div>
    </div>

    <div class="crow">
      <div>
        <div class="num-name"><span class="num">04</span>
          <div><div class="name">New libraries</div><div class="desc">adding dependencies needs your OK</div></div>
        </div>
        <div class="src" id="src-deps"></div>
      </div>
      <div class="slide-wrap">
        <div class="slider" data-dial="deps">
          <div class="ticks" id="ticks-deps"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
          <div class="handle" id="handle-deps" style="left:50%"></div>
        </div>
        <div class="ends"><span>STRICT</span><span>MORE PERMISSIVE</span></div>
      </div>
      <div class="value"><span><span class="k">VALUE</span>
        <select id="sel-deps" data-dial="deps" aria-label="deps mode">
          <option value="block">block</option><option value="ask">ask</option><option value="allow">allow</option>
        </select></span><span class="chev">▼</span></div>
    </div>
  </section>

  <section class="codebox">
    <div class="bar">
      <div class="left"><span class="tri">▼</span> STEERING POLICY (PREVIEW)</div>
      <div class="right">GENERATED FROM CONTROLS
        <svg class="cp" id="btn-copy-json" viewBox="0 0 24 24" role="button" aria-label="copy policy">
          <rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>
      </div>
    </div>
    <div class="code" id="policy"></div>
  </section>

  <div class="console-log" id="log" role="status" aria-live="polite"></div>

  <div class="actions">
    <button class="btn primary" type="button" id="btn-copy">
      <svg class="ic" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>
      Copy steering policy <span class="kbd">⌘C</span>
    </button>
    <button class="btn ghost" type="button" id="btn-board">
      <svg class="ic" viewBox="0 0 24 24"><path d="M4 17l6-5-6-5"/><path d="M12 19h8"/></svg>
      Open in terminal — agent-mixer board <span class="kbd">⌘B</span>
    </button>
    <button class="btn ghost" type="button" id="btn-save">
      <svg class="ic" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>
      Save as default <span class="kbd">⌘S</span>
    </button>
    <button class="btn ghost" type="button" id="btn-reset">
      <svg class="ic" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>
      Reset session <span class="kbd">⌘R</span>
    </button>
  </div>
</main>

<script>
"use strict";
const TOKEN = "__TOKEN__";
const TICKS = 20;

const state = { edits: "auto", deps: "ask", lines: 0, scope: [], left: null };

const $ = (id) => document.getElementById(id);
const pct = (i) => (i / (TICKS - 1)) * 100;

function ticks(el, on) {
  el.innerHTML = "";
  for (let i = 0; i < TICKS; i++) {
    const b = document.createElement("i");
    if (i <= on) b.className = "on";
    el.appendChild(b);
  }
}

function setSlider(dial, on) {
  ticks($("ticks-" + dial), on);
  $("handle-" + dial).style.left = pct(on) + "%";
}

const CHOICE_POS = { edits: { ask: 0, auto: 12, plan: 19 }, deps: { block: 0, ask: 12, allow: 19 } };

function draw() {
  $("s-target").textContent = state.session || "…";
  $("s-version").textContent = "v" + (state.version || "?");
  $("val-scope").textContent = state.scope.length ? state.scope.join(", ") : "(no limit)";
  for (const d of ["edits", "deps", "lines", "scope"]) {
    $("src-" + d).textContent = "FROM " + (state.sources && state.sources[d] ? state.sources[d].toUpperCase() : "?");
  }
  setSlider("edits", CHOICE_POS.edits[state.edits] ?? 12);
  setSlider("deps", CHOICE_POS.deps[state.deps] ?? 12);
  setSlider("lines", state.lines > 0 ? Math.max(1, Math.round(Math.log2(state.lines + 1) / Math.log2(401) * (TICKS - 1))) : 0);
  $("sel-edits").value = state.edits;
  $("sel-deps").value = state.deps;
  $("in-lines").value = state.lines > 0 ? state.lines : "";
  $("in-lines").placeholder = state.lines > 0 ? String(state.lines) : "off";
  const chips = $("scope-chips");
  chips.innerHTML = "";
  if (!state.scope.length) {
    const none = document.createElement("span");
    none.className = "chip"; none.textContent = "(no limit)"; chips.appendChild(none);
  }
  for (const g of state.scope) {
    const c = document.createElement("span");
    c.className = "chip"; c.textContent = g + " ×"; c.title = "remove " + g;
    c.onclick = () => send("scope remove " + g);
    chips.appendChild(c);
  }
  const w = $("warnings");
  if (state.warnings && state.warnings.length) {
    w.hidden = false; w.textContent = "! " + state.warnings.join("  ·  ");
  } else { w.hidden = true; }
  const p = state.policy || {};
  $("policy").innerHTML =
    '<span class="ln">1</span><span class="p">{</span>\n' +
    '<span class="ln">2</span>  <span class="key">"edits"</span><span class="p">:</span> <span class="val">"' + state.edits + '"</span><span class="p">,</span>\n' +
    '<span class="ln">3</span>  <span class="key">"change_scope"</span><span class="p">:</span> <span class="val">' +
      (state.scope.length ? JSON.stringify(state.scope) : "[]") + '</span><span class="p">,</span>\n' +
    '<span class="ln">4</span>  <span class="key">"lines_per_turn"</span><span class="p">:</span> <span class="num">' + state.lines + '</span><span class="p">,</span>\n' +
    '<span class="ln">5</span>  <span class="key">"new_libraries"</span><span class="p">:</span> <span class="val">"' + state.deps + '"</span>\n' +
    '<span class="ln">6</span><span class="p">}</span>';
}

function log(text, cls) {
  const el = $("log");
  el.innerHTML = "";
  const span = document.createElement("span");
  span.className = cls || ""; span.textContent = text;
  el.appendChild(span);
}

async function refresh() {
  const r = await fetch("/api/state", { headers: { "X-Mixer-Token": TOKEN } });
  if (!r.ok) { log("state unavailable (" + r.status + ")", "err"); return; }
  const data = await r.json();
  Object.assign(state, data.dials ? {
    edits: data.dials.edits.value, deps: data.dials.deps.value,
    lines: data.dials.lines.value, left: data.dials.lines.left,
    scope: data.dials.scope.value,
    sources: { edits: data.dials.edits.source, deps: data.dials.deps.source,
               lines: data.dials.lines.source, scope: data.dials.scope.source },
    warnings: data.warnings, session: data.session, version: data.version,
    policy: data.board,
  } : {});
  draw();
}

async function send(command) {
  log("> " + command);
  const r = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Mixer-Token": TOKEN },
    body: JSON.stringify({ token: TOKEN, command }),
  });
  const data = await r.json().catch(() => ({}));
  if (data.reply) log(data.reply, data.ok === false ? "err" : "ok");
  await refresh();
}

// interactions: click a slider tick, pick from a value box, type a lines budget, click a scope chip
document.querySelectorAll(".slider").forEach((el) => {
  el.addEventListener("click", (ev) => {
    if (ev.target.closest(".chip-row")) return;
    const dial = el.dataset.dial;
    const rect = el.getBoundingClientRect();
    const i = Math.round(((ev.clientX - rect.left) / rect.width) * (TICKS - 1));
    apply(dial, i);
  });
});

function apply(dial, i) {
  if (dial === "edits") send("edits " + (Object.keys(CHOICE_POS.edits).find(k => CHOICE_POS.edits[k] === i) || nearestChoice(CHOICE_POS.edits, i)));
  else if (dial === "deps") send("deps " + (Object.keys(CHOICE_POS.deps).find(k => CHOICE_POS.deps[k] === i) || nearestChoice(CHOICE_POS.deps, i)));
  else if (dial === "lines") send("lines " + (i <= 0 ? "off" : linesFromTick(i)));
  else if (dial === "scope") log("pick a scope with 'add folder' below; ticks show (no limit) vs scoped", "");
}

function nearestChoice(pos, i) {
  return Object.keys(pos).reduce((best, k) =>
    Math.abs(pos[k] - i) < Math.abs(pos[best] - i) ? k : best);
}
function linesFromTick(i) {
  const v = Math.round(Math.pow(2, (i / (TICKS - 1)) * Math.log2(401)) - 1);
  return Math.max(1, v);
}

$("sel-edits").onchange = (e) => send("edits " + e.target.value);
$("sel-deps").onchange = (e) => send("deps " + e.target.value);
$("btn-lines-set").onclick = () => {
  const v = $("in-lines").value.trim().toLowerCase();
  send("lines " + (v === "" || v === "off" ? "off" : v));
};
$("in-lines").onkeydown = (e) => { if (e.key === "Enter") $("btn-lines-set").onclick(); };

const policyText = () => JSON.stringify({
  edits: state.edits, change_scope: state.scope, lines_per_turn: state.lines, new_libraries: state.deps,
}, null, 2);

async function copyPolicy() {
  try { await navigator.clipboard.writeText(policyText()); log("steering policy copied", "ok"); }
  catch { log("copy failed — select the JSON panel text", "err"); }
}
$("btn-copy").onclick = copyPolicy;
$("btn-copy-json").onclick = copyPolicy;
$("btn-save").onclick = () => send("save");
$("btn-reset").onclick = () => send("reset");
$("btn-board").onclick = () => send("show");
document.addEventListener("keydown", (e) => {
  if (!(e.metaKey || e.ctrlKey)) return;
  const k = e.key.toLowerCase();
  if (k === "c" && !window.getSelection().toString()) { e.preventDefault(); copyPolicy(); }
  else if (k === "s") { e.preventDefault(); send("save"); }
  else if (k === "r") { e.preventDefault(); send("reset"); }
  else if (k === "b") { e.preventDefault(); send("show"); }
});

refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>
"""
