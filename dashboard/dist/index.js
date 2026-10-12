/**
 * Agent Mixer — Dashboard Plugin (web dashboard tab)
 *
 * Plain IIFE, no build step. Uses window.__HERMES_PLUGIN_SDK__ for React and
 * shadcn primitives; talks to the plugin backend at /api/plugins/hermes-agent-mixer/
 * (the same store and grammar the CLI and hooks use — no drift possible).
 *
 * Renders the retro steering console as a dashboard tab: the four dials as
 * segmented sliders, a live steering-policy preview, and quick actions.
 */
(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;

  const React = SDK.React || window.React;
  const h = React ? React.createElement : null;
  const { useState, useEffect, useCallback, useRef } = SDK.hooks || {};
  const { Badge, Button, Input, Label, Select, SelectOption } = SDK.components || {};
  if (!h || !useState) return;

  const TICKS = 20;
  const EDITS_POS = { plan: 0, ask: 12, auto: 19 }; // LESS CONSERVATIVE -> MORE FREEDOM
  const DEPS_POS = { block: 0, ask: 12, allow: 19 }; // STRICT -> MORE PERMISSIVE
  const REFRESH_MS = 4000;

  // ------------------------------------------------------------------ styles
  const css = `
  .amx-wrap { max-width: 980px; margin: 0 auto; padding: 20px 8px; }
  .amx-title { font-weight: 700; letter-spacing: .14em; color: #4ade80; font-size: 20px; }
  .amx-sub { color: var(--muted-foreground, #6b7280); font-size: 12px; letter-spacing: .22em; margin-left: 10px; }
  .amx-row { display: grid; grid-template-columns: 190px 1fr 170px; gap: 18px; align-items: center;
             border: 1px solid var(--border, #26303a); border-radius: 12px; padding: 14px 18px;
             background: var(--card, rgba(11,19,25,.6)); }
  .amx-num { color: #f97316; font-weight: 700; font-family: ui-monospace, monospace; font-size: 13px; }
  .amx-name { color: #4ade80; font-weight: 600; }
  .amx-desc { color: var(--muted-foreground, #6b7280); font-size: 12px; margin-top: 2px; }
  .amx-src { color: var(--muted-foreground, #6b7280); font-size: 9px; letter-spacing: .14em; margin-top: 4px; }
  .amx-ticks { display: flex; gap: 3px; width: 100%; }
  .amx-tick { flex: 1; height: 10px; border-radius: 2px; background: rgba(120,140,150,.25); cursor: pointer; }
  .amx-tick.on { background: #4ade80; box-shadow: 0 0 8px rgba(74,222,128,.45); }
  .amx-handle { position: absolute; top: 50%; transform: translate(-50%,-50%); width: 8px; height: 22px;
                border-radius: 3px; background: #f97316; box-shadow: 0 0 10px rgba(249,115,22,.7); }
  .amx-slider { position: relative; height: 22px; display: flex; align-items: center; }
  .amx-ends { display: flex; justify-content: space-between; font-size: 9px; letter-spacing: .14em;
              color: var(--muted-foreground, #6b7280); margin-top: 4px; }
  .amx-value { border: 1px solid rgba(74,222,128,.5); border-radius: 8px; padding: 8px 12px;
               color: #4ade80; font-family: ui-monospace, monospace; font-size: 13px; }
  .amx-k { display: block; font-size: 8.5px; letter-spacing: .18em; color: var(--muted-foreground, #6b7280); margin-bottom: 3px; }
  .amx-log { font-family: ui-monospace, monospace; font-size: 12px; margin: 10px 2px; min-height: 16px; }
  .amx-log.ok { color: #4ade80; } .amx-log.err { color: #f97316; }
  .amx-btn { padding: 9px 16px; border-radius: 10px; border: 1px solid #3a4a56;
             background: rgba(22,32,40,.85); color: #d7e4ec; cursor: pointer; font-size: 13px; }
  .amx-btn:hover { border-color: #4ade80; color: #eaffef; }
  .amx-btn.amx-btn-action { min-width: 130px; text-align: center; }
  .amx-select { background: transparent; border: 0; color: #4ade80; font: inherit; outline: none; }
  .amx-select option { background: #10181e; color: #d7e4ec; }
  .amx-preset-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 4px; }
  .amx-preset-label { font-size: 8.5px; letter-spacing: .18em; color: #6b7280; margin-right: 2px; }
  .amx-preset-chip { padding: 7px 13px; border-radius: 999px; border: 1px solid #3a4a56;
             background: rgba(22,32,40,.85); color: #d7e4ec; cursor: pointer; font-size: 12px; }
  .amx-preset-chip:hover { border-color: #4ade80; color: #eaffef; }
  .amx-preset-chip.active { background: rgba(74,222,128,.16); border-color: #4ade80; color: #4ade80; }
  .amx-btn.primary { background: linear-gradient(180deg,#7ef0a8,#3fd97e); color: #04120a; font-weight: 600; border: 0; }
  .amx-warn { color: #f97316; font-size: 12px; margin-bottom: 10px; }
  .amx-cbar { border: 1px solid var(--border, #26303a); border-radius: 10px; padding: 8px 14px;
              background: rgba(11,19,25,.55); margin: 10px auto 0; max-width: 980px; }
  .amx-cbar-head { display: flex; align-items: center; gap: 10px; }
  .amx-cbar-icon { width: 26px; height: 26px; border-radius: 6px; border: 1px solid #3a4a56;
              background: rgba(22,32,40,.85); color: #d7e4ec; cursor: pointer; font-size: 13px; line-height: 1; }
  .amx-cbar-icon:hover { border-color: #4ade80; color: #4ade80; }
  .amx-cbar-label { font-weight: 700; letter-spacing: .14em; color: #4ade80; font-size: 11px; }
  .amx-cbar-summary { font-family: ui-monospace, monospace; font-size: 11px; color: #d7e4ec; }
  .amx-cbar-hint { margin-left: auto; font-size: 10px; color: var(--muted-foreground, #6b7280); }
  .amx-cbar-panel { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border, #26303a);
              display: flex; flex-direction: column; gap: 8px; }
  @media (max-width: 860px) { .amx-row { grid-template-columns: 1fr; } }`;
  const styleEl = document.createElement("style");
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  // ------------------------------------------------------------------ state
  let state = null;
  let log = null;
  let rerender = null;

  // Auth: the dashboard session token is injected into index.html; plugin API
  // routes require it even on ungated loopback serves. Mirror the SPA's own
  // wrapper: X-Hermes-Session-Token when present.
  function authHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    const tok = window.__HERMES_SESSION_TOKEN__;
    if (tok) headers["X-Hermes-Session-Token"] = tok;
    return headers;
  }

  async function refresh() {
    try {
      const res = await fetch("/api/plugins/hermes-agent-mixer/state?session=dashboard", {
        credentials: "same-origin",
        headers: authHeaders(),
      });
      if (!res.ok) { state = { error: "backend " + res.status }; }
      else { state = await res.json(); }
    } catch (e) { state = { error: String(e && e.message || e) }; }
    if (rerender) rerender();
  }

  async function send(command) {
    try {
      const res = await fetch("/api/plugins/hermes-agent-mixer/command", {
        method: "POST", credentials: "same-origin",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ command, session: "dashboard" }),
      });
      const data = await res.json();
      if (data.state) state = data.state;
      log = { ok: data.ok !== false, text: data.reply || "done" };
    } catch (e) { log = { ok: false, text: String(e && e.message || e) }; }
    if (rerender) rerender();
  }

  // ------------------------------------------------------------------ pieces
  function slider(onCount, onPick, endL, endR) {
    const ticks = [];
    for (let i = 0; i < TICKS; i++) {
      ticks.push(h("i", {
        key: i, className: "amx-tick" + (i <= onCount ? " on" : ""),
        onClick: function () { onPick(i); },
      }));
    }
    return h("div", { className: "amx-slide-wrap" },
      h("div", { className: "amx-slider" },
        h("div", { className: "amx-ticks" }, ticks),
        h("div", { className: "amx-handle", style: { left: ((onCount / (TICKS - 1)) * 100) + "%" } })),
      h("div", { className: "amx-ends" }, h("span", {}, endL), h("span", {}, endR)));
  }

  function valueBox(label, inner) {
    return h("div", { className: "amx-value" }, h("span", { className: "amx-k" }, label), inner);
  }

  function choicePos(map, value) {
    const names = Object.keys(map);
    let best = names[0];
    for (const n of names) if (Math.abs(map[n] - 0) >= 0) { /* noop */ }
    return map[value] !== undefined ? map[value] : 12;
  }

  function row(num, name, desc, source, sliderEl, valueEl) {
    return h("div", { className: "amx-row", key: num },
      h("div", {},
        h("div", { style: { display: "flex", gap: "12px", alignItems: "baseline" } },
          h("span", { className: "amx-num" }, num),
          h("div", {},
            h("div", { className: "amx-name" }, name),
            h("div", { className: "amx-desc" }, desc))),
        h("div", { className: "amx-src" }, "FROM " + String(source || "?").toUpperCase())),
      sliderEl, valueBox("VALUE", valueEl));
  }

  function ConsolePage() {
    const [, force] = useState(0);
    rerender = function () { force(function (n) { return n + 1; }); };
    useEffect(function () {
      refresh();
      const t = setInterval(refresh, REFRESH_MS);
      return function () { clearInterval(t); };
    }, []);

    if (!state) return h("div", { className: "amx-wrap" }, "Loading dials…");
    if (state.error) {
      return h("div", { className: "amx-wrap" },
        h("div", { className: "amx-title" }, "AGENT MIXER"),
        h("div", { className: "amx-warn" }, "Backend unavailable: " + state.error),
        h("div", { style: { color: "var(--muted-foreground, #6b7280)", fontSize: "13px" } },
          "Check plugins.enabled in config.yaml and restart the gateway."));
    }
    const d = state.dials;
    if (!d) return h("div", { className: "amx-wrap" }, "Unexpected backend response.");

    const sel = function (dial, choices, value) {
      return h("select", {
        value: value, onChange: function (e) { send(dial + " " + e.target.value); },
        className: "amx-select",
      }, choices.map(function (c) { return h("option", { key: c, value: c }, c); }));
    };

    const scopeChips = (d.scope.value || []).map(function (g) {
      return h("span", { key: g, className: "amx-chip", style: { marginRight: 6 } }, g + " ×");
    });

    return h("div", { className: "amx-wrap" },
      h("div", { style: { marginBottom: 14 } },
        h("span", { className: "amx-title" }, "AGENT MIXER"),
        h("span", { className: "amx-sub" }, "// STEERING CONSOLE — " + state.session)),
      state.warnings && state.warnings.length
        ? h("div", { className: "amx-warn" }, "! " + state.warnings.join("  ·  "))
        : null,
      h("div", { style: { display: "flex", flexDirection: "column", gap: 12 } },
        row("01", "Edits", "what file changes may do", d.edits.source,
          slider(EDITS_POS[d.edits.value] !== undefined ? EDITS_POS[d.edits.value] : 12,
            function (i) {
              const names = Object.keys(EDITS_POS);
              let best = names[0];
              for (const n of names) if (Math.abs(EDITS_POS[n] - i) < Math.abs(EDITS_POS[best] - i)) best = n;
              send("edits " + best);
            }, "LESS CONSERVATIVE", "MORE FREEDOM"),
          sel("edits", d.edits.choices, d.edits.value)),
        row("02", "Change scope", "which folders it may touch", d.scope.source,
          slider(d.scope.value.length ? 8 : 0, function () { send("scope show"); }, "NARROW", "BROADER"),
          h("div", {}, d.scope.value.length ? d.scope.value.join(", ") : "(no limit)")),
        row("03", "Lines per turn", "how much it may change in one go", d.lines.source,
          slider(d.lines.value > 0 ? Math.round(Math.log2(d.lines.value + 1) / Math.log2(401) * (TICKS - 1)) : 0,
            function (i) { send("lines " + (i <= 0 ? "off" : Math.max(1, Math.round(Math.pow(2, (i / (TICKS - 1)) * Math.log2(401)) - 1)))); },
            "OFF", "LARGER"),
          h("span", {}, d.lines.value > 0 ? String(d.lines.value) : "off")),
        row("04", "New libraries", "adding dependencies needs your OK", d.deps.source,
          slider(DEPS_POS[d.deps.value] !== undefined ? DEPS_POS[d.deps.value] : 12,
            function (i) {
              const names = Object.keys(DEPS_POS);
              let best = names[0];
              for (const n of names) if (Math.abs(DEPS_POS[n] - i) < Math.abs(DEPS_POS[best] - i)) best = n;
              send("deps " + best);
            }, "STRICT", "MORE PERMISSIVE"),
          sel("deps", d.deps.choices, d.deps.value))),
      log ? h("div", { className: "amx-log " + (log.ok ? "ok" : "err") }, log.text) : null,
      h("div", { className: "amx-preset-bar" },
        h("span", { className: "amx-preset-label" }, "PRESETS"),
        ["auditor", "builder", "explorer", "surgical"].map(function (name) {
          return h("button", {
            key: name, className: "amx-preset-chip", onClick: function () { send("preset " + name); },
          }, name);
        })),
      h("div", { style: { display: "flex", gap: 10, marginTop: 10 } },
        h("button", { className: "amx-btn amx-btn-action", onClick: function () { send("preset show"); } }, "List presets"),
        h("button", { className: "amx-btn amx-btn-action", onClick: function () { send("reset"); } }, "Reset session dials"),
        h("button", { className: "amx-btn primary", onClick: function () { send("save"); } }, "Save as default")),
      h("div", { style: { marginTop: 12, fontSize: 11, color: "var(--muted-foreground, #6b7280)" } },
        "Changes apply to the dashboard session immediately and are enforced by the hooks on the next tool call."));
  }

  // ------------------------------------------------------------------ composer-adjacent bar
  // The chat window's plugin seam under the composer is the 'chat:bottom' slot
  // (the web SPA has no in-composer slot). A slim bar sits directly under the
  // input; clicking the icon expands the compact dial panel in place.
  function compactDialRow(num, nameText, dname, sliderEl, valueEl) {
    return h("div", { style: { display: "grid", gridTemplateColumns: "120px 1fr 130px", gap: 10, alignItems: "center" } },
      h("span", { className: "amx-name", style: { fontSize: 12 } }, num + " " + nameText),
      sliderEl,
      h("div", { className: "amx-value", style: { padding: "4px 8px", fontSize: 12, textAlign: "center" } }, valueEl));
  }

  function MixerBar() {
    const [, force] = useState(0);
    const [open, setOpen] = useState(false);
    useEffect(function () {
      refresh();
      const t = setInterval(function () { return refresh(); }, REFRESH_MS);
      return function () { clearInterval(t); };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    if (!state || !state.dials) return null;
    const d = state.dials;
    function nearest(map, i) {
      let best = null; let bd = Infinity;
      for (const n of Object.keys(map)) {
        const dist = Math.abs(map[n] - i);
        if (dist < bd) { bd = dist; best = n; }
      }
      return best;
    }
    const summary = [d.edits.value, d.scope.value.length ? "scoped" : "unscoped",
      d.lines.value > 0 ? String(d.lines.value) + " lines" : "lines off", d.deps.value].join(" · ");
    return h("div", { className: "amx-cbar" },
      h("div", { className: "amx-cbar-head" },
        h("button", { className: "amx-cbar-icon", title: "Agent Mixer — steering dials",
          onClick: function () { setOpen(function (v) { return !v; }); } }, "⇋"),
        h("span", { className: "amx-cbar-label" }, "AGENT MIXER"),
        h("span", { className: "amx-cbar-summary" }, summary),
        h("span", { className: "amx-cbar-hint" }, "changes apply to this session immediately")),
      open
        ? h("div", { className: "amx-cbar-panel" },
            compactDialRow("01", "Edits", "edits",
              slider(EDITS_POS[d.edits.value] !== undefined ? EDITS_POS[d.edits.value] : 12,
                function (i) { send("edits " + nearest(EDITS_POS, i)); }, "", ""),
              sel("edits", d.edits.choices, d.edits.value)),
            compactDialRow("02", "Change scope", "scope",
              slider(d.scope.value.length ? 8 : 0, function () { send("scope show"); }, "", ""),
              h("span", {}, d.scope.value.length ? d.scope.value.join(", ") : "(no limit)")),
            compactDialRow("03", "Lines per turn", "lines",
              slider(d.lines.value > 0 ? Math.round(Math.log2(d.lines.value + 1) / Math.log2(401) * (TICKS - 1)) : 0,
                function (i) { send("lines " + (i <= 0 ? "off" : Math.max(1, Math.round(Math.pow(2, (i / (TICKS - 1)) * Math.log2(401)) - 1)))); },
                "", ""),
              h("span", {}, d.lines.value > 0 ? String(d.lines.value) : "off")),
            compactDialRow("04", "New libraries", "deps",
              slider(DEPS_POS[d.deps.value] !== undefined ? DEPS_POS[d.deps.value] : 12,
                function (i) { send("deps " + nearest(DEPS_POS, i)); }, "", ""),
              sel("deps", d.deps.choices, d.deps.value)),
            log ? h("div", { className: "amx-log " + (log.ok ? "ok" : "err") }, log.text) : null,
            h("div", { style: { display: "flex", gap: 8, flexWrap: "wrap" } },
              h("button", { className: "amx-btn amx-btn-action", style: { padding: "5px 12px", fontSize: 12 },
                onClick: function () { send("reset"); } }, "Reset session"),
              h("button", { className: "amx-btn primary", style: { padding: "5px 12px", fontSize: 12 },
                onClick: function () { send("save"); } }, "Save as default"),
              h("button", { className: "amx-btn amx-btn-action", style: { padding: "5px 12px", fontSize: 12 },
                onClick: function () { window.location.assign("/agent-mixer"); } }, "Full console →")))
        : null);
  }

  // ------------------------------------------------------------------ register
  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("hermes-agent-mixer", ConsolePage);
  }
  // Chat-window bar: register into the 'chat:bottom' slot when the SPA exposes it.
  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.registerSlot === "function") {
    window.__HERMES_PLUGINS__.registerSlot("hermes-agent-mixer", "chat:bottom", MixerBar);
  }
})();
