// Agent Mixer — the desktop half (unified package: this file ships beside plugin.yaml).
// Loads through the desktop-plugins disk door (no build step): plain ESM, jsx()/jsxs() only,
// imports restricted to @hermes/plugin-sdk, react, react/jsx-runtime.
//
// Surfaces:
//   1. STATUSBAR_AREAS.right pill — the dials at a glance ("auto · src/** · 30 · ask"), click
//      opens the console page.
//   2. ROUTES_AREA '/agent-mixer' — the retro steering console as a native page. Sliders are
//      live: every change POSTs to the plugin backend (dashboard/plugin_api.py) and lands in
//      the same store the CLI hooks enforce.
//   3. SIDEBAR_NAV_AREA row so the page is reachable from the rail.
//
// The Settings ▸ Plugins form (from the manifest's config_schema) stays the config path; this
// page is a live view + quick-tweak over the same dials.

import { host } from '@hermes/plugin-sdk'
import { useState, useEffect, useCallback } from 'react'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'

// Area ids as literal strings (the proven disk-plugin pattern — stewardship uses literals too;
// importing the SDK's area constants is unnecessary and one more thing that can fail to resolve).
const ROUTES_AREA = 'routes'
const SIDEBAR_NAV_AREA = 'sidebar.nav'
const STATUSBAR_RIGHT = 'statusBar.right'

const TICKS = 20
const EDITS_POS = { plan: 0, ask: 12, auto: 19 } // LESS CONSERVATIVE -> MORE FREEDOM
const DEPS_POS = { block: 0, ask: 12, allow: 19 } // STRICT -> MORE PERMISSIVE
const REFRESH_MS = 4000

// ---------- tiny react helpers (no JSX on the disk door) ----------

const el = (tag, props, ...children) => jsx(tag, { ...props }, ...children)
const frag = (...children) => jsx(Fragment, {}, ...children)

function useMixerState(ctx) {
  const [state, setState] = useState({ pending: true })
  const [log, setLog] = useState(null)
  const refresh = useCallback(async () => {
    try {
      const data = await ctx.rest('/state?session=SESS-DESKTOP', { timeoutMs: 8000 })
      setState(data && data.dials ? data : { error: 'unexpected backend response: ' + JSON.stringify(data).slice(0, 140) })
    } catch (error) {
      setState({ error: String((error && error.message) || error) })
    }
  }, [ctx])
  const send = useCallback(async (command) => {
    try {
      const res = await ctx.rest('/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, session: 'SESS-DESKTOP' }),
        timeoutMs: 8000,
      })
      if (res && res.state && res.state.dials) setState(res.state)
      setLog({ ok: res && res.ok !== false, text: (res && res.reply) || 'done' })
    } catch (error) {
      setLog({ ok: false, text: String((error && error.message) || error) })
      setState({ error: String((error && error.message) || error) })
    }
  }, [ctx])
  useEffect(() => {
    refresh()
    const timer = ctx.setInterval(refresh, REFRESH_MS)
    return timer
  }, [refresh])
  return { state, log, send, refresh }
}

// ---------- the retro console page ----------

function Slider({ dial, pos, onPick, endLeft, endRight }) {
  const ticks = []
  for (let i = 0; i < TICKS; i++) {
    ticks.push(el('i', {
      key: i,
      style: {
        flex: '1', height: '10px', borderRadius: '2px',
        background: i <= pos ? 'var(--ui-status-bar-background, #4ade80)' : 'var(--ui-text-tertiary)',
        opacity: i <= pos ? 0.9 : 0.35,
        cursor: 'pointer',
      },
      onClick: () => onPick(i),
    }))
  }
  return el('div', { style: { display: 'flex', flexDirection: 'column', gap: '6px', flex: 1 } },
    el('div', { style: { position: 'relative', display: 'flex', alignItems: 'center', height: '22px' } },
      el('div', { style: { display: 'flex', gap: '3px', width: '100%' } }, ticks),
      el('div', {
        style: {
          position: 'absolute', left: `${(pos / (TICKS - 1)) * 100}%`, top: '50%',
          transform: 'translate(-50%,-50%)', width: '8px', height: '22px', borderRadius: '3px',
          background: '#f97316', boxShadow: '0 0 10px rgba(249,115,22,.8)',
        },
      })),
    el('div', { style: { display: 'flex', justifyContent: 'space-between', fontSize: '9px', letterSpacing: '.14em', color: 'var(--ui-text-tertiary)' } },
      el('span', {}, endLeft), el('span', {}, endRight)))
}

function ValueBox({ label, children }) {
  return el('div', {
    style: {
      border: '1px solid var(--ui-status-bar-background, #4ade80)', borderRadius: '8px',
      padding: '8px 12px', minWidth: '150px', color: 'var(--ui-status-bar-background, #4ade80)',
      fontFamily: 'var(--ui-font-mono, monospace)', fontSize: '13px',
    },
  },
    el('div', { style: { fontSize: '8.5px', letterSpacing: '.18em', color: 'var(--ui-text-tertiary)', marginBottom: '3px' } }, label),
    children)
}

function Row({ num, name, desc, source, slider, value }) {
  return el('div', {
    style: {
      display: 'grid', gridTemplateColumns: '190px 1fr 170px', gap: '18px', alignItems: 'center',
      border: '1px solid var(--ui-border, #16232c)', borderRadius: '12px', padding: '14px 18px',
      background: 'var(--ui-background-secondary, rgba(11,19,25,.85))',
    },
  },
    el('div', {},
      el('div', { style: { display: 'flex', gap: '12px', alignItems: 'baseline' } },
        el('span', { style: { fontFamily: 'var(--ui-font-mono, monospace)', color: '#f97316', fontWeight: 700, fontSize: '13px' } }, num),
        el('div', {},
          el('div', { style: { color: 'var(--ui-status-bar-background, #4ade80)', fontWeight: 600 } }, name),
          el('div', { style: { color: 'var(--ui-text-tertiary)', fontSize: '12px', marginTop: '2px' } }, desc))),
      el('div', { style: { fontSize: '9px', letterSpacing: '.14em', color: 'var(--ui-text-tertiary)', marginTop: '4px' } },
        'FROM ' + String(source || '?').toUpperCase())),
    slider, value)
}

function ConsolePage({ ctx }) {
  const { state, log, send } = useMixerState(ctx)
  if (state.error) {
    return el('div', { style: { padding: 24 } },
      el('div', { style: { fontWeight: 700, letterSpacing: '.14em', marginBottom: 8 } }, 'AGENT MIXER'),
      el('div', { style: { color: '#fb923c', marginBottom: 8 } }, 'Backend unavailable: ' + state.error),
      el('div', { style: { color: 'var(--ui-text-tertiary)', fontSize: 13 } },
        'Check plugins.enabled in config.yaml, restart the gateway, and confirm dashboard/plugin_api.py is deployed beside plugin.yaml.'))
  }
  if (state.pending || !state.dials) {
    return el('div', { style: { padding: 24, color: 'var(--ui-text-tertiary)' } },
      el('div', { style: { fontWeight: 700, letterSpacing: '.14em', marginBottom: 8 } }, 'AGENT MIXER'),
      'Loading dials (v3)…')
  }
  const dials = state.dials
  const pick = (dial, mapping, i) => {
    const names = Object.keys(mapping)
    let best = names[0]
    for (const n of names) if (Math.abs(mapping[n] - i) < Math.abs(mapping[best] - i)) best = n
    send(dial + ' ' + best)
  }
  return el('div', { style: { padding: '24px 28px', maxWidth: 980, margin: '0 auto' } },
    el('div', { style: { marginBottom: 18 } },
      el('div', {
        style: {
          fontFamily: 'var(--ui-font-mono, monospace)', fontWeight: 700, fontSize: 26,
          letterSpacing: '.14em', color: 'var(--ui-status-bar-background, #4ade80)',
        },
      }, 'AGENT MIXER'),
      el('div', { style: { fontSize: 12, color: 'var(--ui-text-tertiary)', letterSpacing: '.28em', marginTop: 4 } },
        '// STEERING CONSOLE — session ' + state.session)),
    state.warnings && state.warnings.length
      ? el('div', { style: { color: '#fb923c', fontSize: 12, marginBottom: 12 } }, '! ' + state.warnings.join(' · '))
      : null,
    el('div', { style: { display: 'flex', flexDirection: 'column', gap: 12 } },
      Row({ num: '01', name: 'Edits', desc: 'what file changes may do', source: dials.edits.source,
        slider: Slider({ dial: 'edits', pos: EDITS_POS[dials.edits.value] ?? 12,
          onPick: (i) => pick('edits', EDITS_POS, i),
          endLeft: 'LESS CONSERVATIVE', endRight: 'MORE FREEDOM' }),
        value: ValueBox('VALUE', el('select', {
          value: dials.edits.value,
          onChange: (e) => send('edits ' + e.target.value),
          style: { background: 'transparent', border: 0, color: 'inherit', font: 'inherit', outline: 'none' },
        }, dials.edits.choices.map((c) => el('option', { key: c, value: c }, c)))) }),
      Row({ num: '02', name: 'Change scope', desc: 'which folders it may touch', source: dials.scope.source,
        slider: Slider({ dial: 'scope', pos: dials.scope.value.length ? 8 : 0,
          onPick: () => {}, // scope is list-valued; edited via the chips below
          endLeft: 'NARROW', endRight: 'BROADER' }),
        value: ValueBox('VALUE', el('span', {},
          dials.scope.value.length ? dials.scope.value.join(', ') : '(no limit)')) }),
      Row({ num: '03', name: 'Lines per turn', desc: 'how much it may change in one go', source: dials.lines.source,
        slider: Slider({ dial: 'lines',
          pos: dials.lines.value > 0 ? Math.round(Math.log2(dials.lines.value + 1) / Math.log2(401) * (TICKS - 1)) : 0,
          onPick: (i) => send('lines ' + (i <= 0 ? 'off' : Math.max(1, Math.round(Math.pow(2, (i / (TICKS - 1)) * Math.log2(401)) - 1)))),
          endLeft: 'OFF', endRight: 'LARGER' }),
        value: ValueBox('VALUE', el('span', {}, dials.lines.value > 0 ? String(dials.lines.value) : 'off')) }),
      Row({ num: '04', name: 'New libraries', desc: 'adding dependencies needs your OK', source: dials.deps.source,
        slider: Slider({ dial: 'deps', pos: DEPS_POS[dials.deps.value] ?? 12,
          onPick: (i) => pick('deps', DEPS_POS, i),
          endLeft: 'STRICT', endRight: 'MORE PERMISSIVE' }),
        value: ValueBox('VALUE', el('select', {
          value: dials.deps.value,
          onChange: (e) => send('deps ' + e.target.value),
          style: { background: 'transparent', border: 0, color: 'inherit', font: 'inherit', outline: 'none' },
        }, dials.deps.choices.map((c) => el('option', { key: c, value: c }, c)))) })),
    log ? el('div', { style: { fontFamily: 'var(--ui-font-mono, monospace)', fontSize: 12, margin: '12px 2px', color: log.ok ? 'var(--ui-status-bar-background, #4ade80)' : '#fb923c' } }, log.text) : null,
    el('div', { style: { display: 'flex', gap: 10, marginTop: 8 } },
      el('button', {
        onClick: () => send('preset show'),
        style: { flex: 1, padding: '10px 16px', borderRadius: 10, border: '1px solid var(--ui-border, #22383c)', background: 'transparent', color: 'var(--ui-text-secondary)', cursor: 'pointer' },
      }, 'List presets'),
      el('button', {
        onClick: () => send('reset'),
        style: { flex: 1, padding: '10px 16px', borderRadius: 10, border: '1px solid var(--ui-border, #22383c)', background: 'transparent', color: 'var(--ui-text-secondary)', cursor: 'pointer' },
      }, 'Reset session dials'),
      el('button', {
        onClick: () => send('save'),
        style: { flex: 1, padding: '10px 16px', borderRadius: 10, border: 0, background: 'linear-gradient(180deg,#7ef0a8,#3fd97e)', color: '#04120a', fontWeight: 600, cursor: 'pointer' },
      }, 'Save as default')),
    el('div', { style: { marginTop: 14, fontSize: 11, color: 'var(--ui-text-tertiary)' } },
      'Changes apply to the live session immediately and are enforced by the hooks on the next tool call. The saved defaults are edited in Settings ▸ Plugins or with /mixer save.'))
}

// ---------- status-bar pill: the dials at a glance ----------

function Pill({ ctx }) {
  const { state } = useMixerState(ctx)
  if (!state || state.error || state.pending || !state.dials) return null
  const d = state.dials
  const summary = [d.edits.value, d.scope.value.length ? 'scoped' : 'unscoped',
    d.lines.value > 0 ? `${d.lines.left ?? d.lines.value} left` : 'lines off', d.deps.value].join(' · ')
  return el('button', {
    type: 'button',
    title: 'Agent Mixer: ' + summary + ' — click to open the console',
    onClick: () => host.navigate('/agent-mixer'),
    style: {
      padding: '0 8px', fontSize: '11px', border: 0, background: 'transparent', cursor: 'pointer',
      color: 'var(--ui-status-bar-background, #4ade80)', fontFamily: 'var(--ui-font-mono, monospace)',
    },
  }, '🎛 ' + summary)
}

// ---------- the plugin ----------

export default {
  id: 'agent-mixer',
  name: 'Agent Mixer',
  description: 'Steering console for the Agent Mixer dials — status-bar summary and live sliders over the same store the hooks enforce.',
  register(ctx) {
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/agent-mixer' },
        render: () => jsx(ConsolePage, { ctx }),
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: '/agent-mixer', label: 'Mixer Console', codicon: 'sliders-horizontal' },
      },
      {
        id: 'pill',
        area: STATUSBAR_RIGHT,
        order: 120,
        render: () => jsx(Pill, { ctx }),
      },
    ])
  },
}
