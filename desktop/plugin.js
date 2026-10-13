// Agent Mixer — the desktop half (unified package: this file ships beside plugin.yaml).
// Loads through the desktop-plugins disk door (no build step): plain ESM, jsx()/jsxs() only,
// imports restricted to @hermes/plugin-sdk, react, react/jsx-runtime.
//
// RELEASE-BUILD CONSTRAINT (diagnosed live 2026-10-12): render contributions whose components call
// React hooks from the plugin module realm mount as SILENT NULLS in the shipped desktop release —
// the slot shows nothing, production React logs nothing (hook realm mismatch, recovered unmount).
// Data-only contributions (sidebar.nav / routes) and STATELESS hook-free render trees mount fine.
//
// So this desktop half is deliberately hook-free:
//   - every render contribution is a stateless element tree built from a module-level snapshot,
//   - commands via ctx.rest inside closures; live panel patches via a bounded element morph,
//   - the snapshot polls through ctx.setInterval (outside React), the pill updates imperatively.
//
// Surfaces: composer icon + screen-edge overlay panel (composer.actions), full console page
// (routes), sidebar row (sidebar.nav), status pill (statusBar.right — opens the SAME overlay,
// never navigates). The CLI stays as-is.

import { host } from '@hermes/plugin-sdk'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'

const COMPOSER_ACTIONS = 'composer.actions'
const ROUTES_AREA = 'routes'
const SIDEBAR_NAV_AREA = 'sidebar.nav'
const STATUSBAR_RIGHT = 'statusBar.right'

const TICKS = 20
const EDITS_POS = { plan: 0, ask: 12, auto: 19 }
const DEPS_POS = { block: 0, ask: 12, allow: 19 }
const REFRESH_MS = 4000
const PRESETS = ['auditor', 'builder', 'explorer', 'surgical']
// Mirror of core/presets.py — used for INSTANT optimistic UI when a chip is clicked; the real
// backend response always reconciles right after.
const PRESET_DIALS = {
  builder: { edits: 'auto', scope: [], lines: 0, deps: 'allow' },
  auditor: { edits: 'plan', scope: [], lines: 0, deps: 'ask' },
  explorer: { edits: 'plan', scope: [], lines: 0, deps: 'allow' },
  surgical: { edits: 'auto', scope: ['src/**', 'tests/**'], lines: 30, deps: 'ask' },
}

const el = (tag, props, ...children) => jsx(tag, { ...props, children: children.length === 0 ? props.children : (children.length === 1 ? children[0] : children) })

// ---------- module-level dial snapshot ----------

let snapshot = null
let panelOpen = false
let pageRepaint = null // set by the page render; the poll calls it while the page is visible
let lastReply = null // { ok, text } — persisted across panel rebuilds so the status line survives

function makeApi(ctx) {
  // Teknium review: never invent a session id ('SESS-DESKTOP' wrote a phantom store
  // record the hooks would never read). The durable id the hooks actually receive is
  // host.state.focusedStoredSessionId; focusedSessionId is the ephemeral runtime uuid.
  // With nothing focused, panel actions are refused with an explanation instead.
  const sessionOf = () => {
    try {
      const focused = host.state.focusedStoredSessionId.get()
      if (focused) return focused
    } catch { /* host.state can be unreachable early — fall through */ }
    return null
  }
  const send = async (command) => {
    const session = sessionOf()
    if (!session) return { ok: false, text: 'no focused session in the desktop yet — focus a chat first' }
    try {
      const res = await ctx.rest('/command', {
        method: 'POST',
        // The desktop bridge serialises opts.body itself — pass the OBJECT (a pre-stringified
        // body arrives as a JSON string and FastAPI rejects it with 422).
        body: { command, session },
        timeoutMs: 8000,
      })
      if (sessionOf() !== session) { snapshot = null; return { ok: false, text: "focused chat changed; refresh the panel" } }
      if (res && res.state && res.state.dials) snapshot = res.state
      return { ok: res && res.ok !== false, text: (res && res.reply) || 'done' }
    } catch (error) {
      return { ok: false, text: String((error && error.message) || error) }
    }
  }
  const get = async () => {
    const session = sessionOf()
    if (!session) {
      snapshot = null
      return { error: 'no focused session in the desktop yet — focus a chat first' }
    }
    if (snapshot && snapshot.session !== session) snapshot = null
    try {
      const data = await ctx.rest('/state?session=' + encodeURIComponent(session) + '&saved=false', { timeoutMs: 8000 })
      if (sessionOf() !== session) { snapshot = null; return { error: "focused chat changed; refresh the panel" } }
      if (data && data.dials) snapshot = data
      return snapshot
    } catch (error) {
      snapshot = null
      return { error: String((error && error.message) || error) }
    }
  }
  const sendRefresh = async (command) => {
    const res = await send(command)
    if (res && res.state && res.state.dials) {
      // send() already stored the fresh state — skip the extra /state round trip.
    } else {
      await get()
    }
    if (pageRepaint) pageRepaint() // also rebuilds the panel (status line re-rendered from reply)
    if (panelOpen) refreshOpenPanel(ctx)
    const panelEl = document.getElementById('mixer-panel')
    if (panelEl && panelEl.__setStatus) {
      panelEl.__setStatus((res.ok ? '' : '! ') + (res.text || 'done'), res.ok ? 'ok' : 'err')
    }
    return res
  }
  return { send, get, sendRefresh, sessionOf }
}

function nearest(mapping, i) {
  let best = null
  let bd = Infinity
  for (const n of Object.keys(mapping)) {
    const d = Math.abs(mapping[n] - i)
    if (d < bd) { bd = d; best = n }
  }
  return best
}

function summaryOf(d) {
  return [d.edits.value, d.scope.value.length ? 'scoped' : 'unscoped',
    d.lines.value > 0 ? `${d.lines.value} lines` : 'lines off', d.deps.value].join(' · ')
}

// ---------- shared stateless widgets ----------

function sliderTicks(pos, onPick) {
  const ticks = []
  for (let i = 0; i < TICKS; i++) {
    ticks.push(el('i', {
      key: i,
      style: {
        flex: '1', height: '8px', borderRadius: '2px',
        background: i <= pos ? '#4ade80' : '#3a4750',
        opacity: i <= pos ? 0.9 : 0.5,
        cursor: 'pointer',
      },
      onClick: () => onPick(i),
    }))
  }
  return el('div', { style: { display: 'flex', gap: '2px', width: '100%' } }, ...ticks)
}

function dialRow(d, num, nameText, pos, onPick, valueNode) {
  return el('div', { key: num, style: { display: 'grid', gridTemplateColumns: '96px 1fr 110px', gap: 10, alignItems: 'center' } },
    el('div', {},
      el('div', { style: { color: '#f97316', fontWeight: 700, fontSize: 10, fontFamily: 'var(--ui-font-mono, monospace)' } }, num),
      el('div', { style: { color: '#4ade80', fontWeight: 600, fontSize: 12 } }, nameText)),
    el('div', { style: { display: 'flex', flexDirection: 'column', gap: 2 } }, sliderTicks(pos, onPick)),
    valueNode)
}

function presetChips(send) {
  return el('div', { style: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' } },
    el('span', { style: { fontSize: 8.5, letterSpacing: '.18em', color: '#7c8890' } }, 'PRESETS'),
    ...PRESETS.map((name) => el('button', {
      key: name, type: 'button',
      onClick: () => send('preset ' + name),
      style: {
        padding: '4px 10px', borderRadius: 999, border: '1px solid #3a4750',
        background: 'rgba(22,32,40,.85)', color: '#d7e4ec', cursor: 'pointer', fontSize: 11,
      },
    }, name)))
}

function actionButtons(send) {
  return el('div', { style: { display: 'flex', gap: 8 } },
    el('button', {
      type: 'button', onClick: () => send('reset'),
      style: { flex: 1, padding: '6px 12px', borderRadius: 8, border: '1px solid #3a4750', background: 'rgba(22,32,40,.85)', color: '#d7e4ec', cursor: 'pointer', fontSize: 12 },
    }, 'Reset session'),
    el('button', {
      type: 'button', onClick: () => send('save'),
      style: { flex: 1, padding: '6px 12px', borderRadius: 8, border: 0, background: 'linear-gradient(180deg,#7ef0a8,#3fd97e)', color: '#04120a', fontWeight: 600, cursor: 'pointer', fontSize: 12 },
    }, 'Save as default'))
}

// ---------- bounded React-element → DOM morph (only touches nodes WE created) ----------

function morph(dst, srcEl) {
  if (srcEl === null || srcEl === undefined || typeof srcEl !== 'object' || !srcEl.type || typeof srcEl.type !== 'string') {
    return
  }
  if (dst.tagName.toLowerCase() !== srcEl.type) {
    const repl = document.createElement(srcEl.type)
    dst.parentNode.replaceChild(repl, dst)
    dst = repl
  }
  const props = srcEl.props || {}
  const srcStyle = props.style || {}
  for (const k of Object.keys(srcStyle)) {
    const v = typeof srcStyle[k] === 'number' && !['zIndex', 'opacity', 'fontWeight', 'width', 'height', 'maxWidth', 'maxHeight', 'gap', 'padding', 'fontSize'].includes(k) ? `${srcStyle[k]}px` : srcStyle[k]
    if (dst.style[k] !== v) dst.style[k] = v
  }
  if (props.id && dst.id !== props.id) dst.id = props.id
  if (props.title && dst.title !== props.title) dst.title = props.title
  // Re-attach event handlers after morph: morph-built nodes are plain DOM, so React's synthetic
  // event system never sees them — copy the handler props onto the node directly.
  for (const [h, fn] of Object.entries(props)) {
    if (!/^on[A-Z]/.test(h) || typeof fn !== 'function') continue
    const evName = h.slice(2).toLowerCase()
    dst.__mixerHandlers = dst.__mixerHandlers || {}
    if (dst.__mixerHandlers[h] !== fn) {
      if (dst.__mixerHandlers[h]) dst.removeEventListener(evName, dst.__mixerHandlers[h])
      dst.addEventListener(evName, fn)
      dst.__mixerHandlers[h] = fn
    }
  }
  const srcKids = Array.isArray(props.children) ? props.children : (props.children !== undefined && props.children !== null ? [props.children] : [])
  // flatten fragments/arrays one level (our own builder only produces these shapes)
  const flat = []
  for (const k of srcKids) {
    if (Array.isArray(k)) flat.push(...k)
    else if (k && k.type === Fragment) flat.push(...(Array.isArray(k.props.children) ? k.props.children : [k.props.children]))
    else flat.push(k)
  }
  const dstKids = Array.from(dst.childNodes)
  for (let i = 0; i < Math.max(flat.length, dstKids.length); i++) {
    const s = flat[i]
    const t = dstKids[i]
    if (s === undefined || s === null) {
      if (t) t.remove()
      continue
    }
    if (s.type && typeof s.type === 'string') {
      let target = t && t.nodeType === 1 ? t : null
      if (!target) {
        target = document.createElement(s.type)
        if (t) dst.replaceChild(target, t)
        else dst.appendChild(target)
      } else if (t.tagName.toLowerCase() !== s.type) {
        const repl = document.createElement(s.type)
        if (t.firstChild) repl.appendChild(t.firstChild)
        dst.replaceChild(repl, t)
        target = repl
      }
      morph(target, s)
    } else {
      const txt = String(s ?? '')
      if (t && t.nodeType === 3) { if (t.textContent !== txt) t.textContent = txt }
      else {
        const tn = document.createTextNode(txt)
        if (t) dst.replaceChild(tn, t)
        else dst.appendChild(tn)
      }
    }
  }
}

// ---------- composer icon + overlay panelhosted on document.body ----------
//
// (c) WHY fixed-position ON BODY: an absolutely-positioned panel inside the composer subtree is
// clipped/stacked by the composer's own chrome (the reported "shadow but no foreground" symptom).
// The overlay lives on <body> with position:fixed, positioned over the trigger from its
// bounding rect. Works from BOTH triggers: composer icon and status pill.

let panelEl = null
let outsideCloser = null
let lastTrigger = null

function ensurePanel() {
  if (panelEl && panelEl.isConnected) return panelEl
  panelEl = document.createElement('div')
  panelEl.id = 'mixer-panel'
  panelEl.setAttribute('style', [
    'position:fixed', 'z-index:9999', 'width:404px',
    'padding:12px', 'border:1px solid #2a3a44', 'border-radius:12px',
    'background:rgba(11,19,25,.98)', 'box-shadow:0 14px 40px rgba(0,0,0,.55)',
    'display:none', 'flex-direction:column', 'gap:10px',
    'font-family:var(--ui-font-sans, system-ui)', 'font-size:12px', 'color:#d7e4ec',
  ].join(';'))
  panelEl.addEventListener('mousedown', (e) => e.stopPropagation())
  document.body.appendChild(panelEl)
  return panelEl
}

function closePanel() {
  panelOpen = false
  if (panelEl) panelEl.style.display = 'none'
  syncIconState()
  if (outsideCloser) {
    document.removeEventListener('mousedown', outsideCloser, true)
    outsideCloser = null
  }
}

function syncIconState() {
  const icon = document.getElementById('mixer-composer-icon')
  if (icon) icon.style.color = panelOpen ? '#4ade80' : 'var(--ui-text-secondary, #b9c6cf)'
}

function positionPanel() {
  if (!panelEl) return
  const w = Math.min(404, window.innerWidth - 24)
  panelEl.style.width = `${w}px`
  const h = panelEl.offsetHeight
  const r = (lastTrigger && lastTrigger.isConnected ? lastTrigger : null)
  const anchor = r ? r.getBoundingClientRect() : { top: window.innerHeight / 2, bottom: window.innerHeight / 2, right: window.innerWidth / 2, left: window.innerWidth / 2 }
  let left = Math.round(Math.min(Math.max(12, anchor.right - w), window.innerWidth - w - 12))
  let top = Math.round(anchor.top - h - 10) // prefer ABOVE the trigger (voice-equaliser feel)
  if (top < 12) top = Math.round(Math.min(anchor.bottom + 10, window.innerHeight - h - 12))
  panelEl.style.left = `${Math.max(12, left)}px`
  panelEl.style.top = `${Math.max(12, top)}px`
  panelEl.style.right = 'auto'
  panelEl.style.bottom = 'auto'
}

async function togglePanel(trigger, api) {
  panelOpen = !panelOpen
  lastTrigger = trigger
  syncIconState()
  if (!panelOpen) {
    if (panelEl) panelEl.style.display = 'none'
    if (outsideCloser) {
      document.removeEventListener('mousedown', outsideCloser, true)
      outsideCloser = null
    }
    return
  }
  const panel = ensurePanel()
  buildPanelChildren(panel, api) // render with the current snapshot so the box has real height
  panel.style.display = 'flex'
  positionPanel()
  await api.get() // refresh from the backend
  buildPanelChildren(panel, api)
  positionPanel()
  if (outsideCloser) document.removeEventListener('mousedown', outsideCloser, true)
  outsideCloser = (ev) => {
    if (!panelEl || panelEl.contains(ev.target)) return
    if (trigger && trigger.contains(ev.target)) return
    closePanel()
  }
  setTimeout(() => document.addEventListener('mousedown', outsideCloser, true), 0)
}

function refreshOpenPanel(api) {
  if (!panelOpen || !panelEl || !panelEl.isConnected) return
  buildPanelChildren(panelEl, api)
  positionPanel()
}

// (b) BIGGER, CLEARER icon: 32x30 hit area, 19px sliders-horizontal SVG
// (two rails with knobs) instead of the dim ⇋ glyph.
function ComposerSlot({ api }) {
  return el('span', { id: 'mixer-panel-anchor' },
    el('button', {
      type: 'button',
      id: 'mixer-composer-icon',
      'aria-label': 'Agent Mixer steering dials',
      title: 'Agent Mixer — steering dials',
      onClick: (e) => {
        e.preventDefault()
        e.stopPropagation()
        togglePanel(e.currentTarget, api)
      },
      style: {
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: 32, height: 30, borderRadius: 7, border: 0, background: 'transparent',
        color: panelOpen ? '#4ade80' : 'var(--ui-text-secondary, #b9c6cf)',
        cursor: 'pointer', padding: 0,
      },
    },
      el('svg', { width: 19, height: 19, viewBox: '0 0 16 16', 'aria-hidden': true, style: { display: 'block' } },
        el('line', { x1: 1, y1: 4, x2: 15, y2: 4, stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' }),
        el('circle', { cx: 10.5, cy: 4, r: 2.2, fill: 'var(--ui-background, #10181e)', stroke: 'currentColor', strokeWidth: 1.5 }),
        el('line', { x1: 1, y1: 11.5, x2: 15, y2: 11.5, stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' }),
        el('circle', { cx: 5.5, cy: 11.5, r: 2.2, fill: 'var(--ui-background, #10181e)', stroke: 'currentColor', strokeWidth: 1.5 }))))
}

// DOM builder for the panel children (plain DOM nodes with REAL listeners).
function buildPanelChildren(panel, api) {
  panel.textContent = ''
  const d = snapshot && snapshot.dials
  const styles = (s) => Object.entries(s).map(([k, v]) => {
    const pxKeys = ['width', 'height', 'padding', 'gap', 'fontSize', 'borderRadius', 'maxWidth', 'maxHeight']
    const val = (typeof v === 'number' && !['zIndex', 'opacity', 'fontWeight', 'flex'].includes(k)) || (pxKeys.includes(k) && typeof v === 'number') ? `${v}px` : v
    return `${k.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase())}:${val}`
  }).join(';')
  const node = (tag, styleObj, text, handlers) => {
    const n = document.createElement(tag)
    if (styleObj) n.setAttribute('style', styles(styleObj))
    if (text !== undefined && text !== null) n.textContent = text
    for (const [h, fn] of Object.entries(handlers || {})) {
      n.addEventListener(h.slice(2).toLowerCase(), fn)
    }
    return n
  }
  const root = document.createDocumentFragment()
  root.appendChild(node('div', { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }, null, null))
  const titleRow = root.lastChild
  titleRow.appendChild(node('span', { fontWeight: 700, letterSpacing: '.14em', color: '#4ade80', fontFamily: 'var(--ui-font-mono, monospace)', fontSize: 13 }, 'AGENT MIXER'))
  titleRow.appendChild(node('span', { fontSize: 9.5, letterSpacing: '.2em', color: '#7c8890' }, 'SESSION ' + String((snapshot && snapshot.session) || '—')))
  if (!d) {
    root.appendChild(node('span', { color: '#7c8890', fontSize: 11 }, 'Loading dials…'))
    panel.appendChild(root)
    return
  }
  const flash = (text) => { if (panel.__setStatus) panel.__setStatus(text) }
  const optimistic = (dial, value) => {
    if (!snapshot || !snapshot.dials) return
    const patch = { ...snapshot.dials[dial], value, source: 'session' }
    snapshot = { ...snapshot, dials: { ...snapshot.dials, [dial]: patch } }
  }
  const dialDefs = [
    ['01', 'Edits', EDITS_POS[d.edits.value] ?? 12,
      (i) => { const v = nearest(EDITS_POS, i); optimistic('edits', v); flash('edits → ' + v + '…'); api.sendRefresh('edits ' + v) },
      () => d.edits.value, '#4ade80'],
    ['02', 'Change scope', d.scope.value.length ? 8 : 0, () => { flash('scope…'); api.send('scope show') },
      () => (d.scope.value.length ? d.scope.value.join(', ') : '(no limit)'), '#d7e4ec'],
    ['03', 'Lines per turn', d.lines.value > 0 ? Math.round(Math.log2(d.lines.value + 1) / Math.log2(401) * (TICKS - 1)) : 0,
      (i) => { const v = i <= 0 ? 'off' : Math.max(1, Math.round(Math.pow(2, (i / (TICKS - 1)) * Math.log2(401)) - 1)); optimistic('lines', v); flash('lines → ' + v + '…'); api.sendRefresh('lines ' + v) },
      () => (d.lines.value > 0 ? String(d.lines.value) : 'off'), '#d7e4ec'],
    ['04', 'New libraries', DEPS_POS[d.deps.value] ?? 12,
      (i) => { const v = nearest(DEPS_POS, i); optimistic('deps', v); flash('deps → ' + v + '…'); api.sendRefresh('deps ' + v) },
      () => d.deps.value, '#4ade80'],
  ]
  for (const [num, name, pos, onPick, valFn, valColor] of dialDefs) {
    const row = node('div', { display: 'grid', gridTemplateColumns: '96px 1fr 110px', gap: 10, alignItems: 'center' }, null, null)
    const label = node('div', {}, null, null)
    label.appendChild(node('div', { color: '#f97316', fontWeight: 700, fontSize: 10, fontFamily: 'var(--ui-font-mono, monospace)' }, num))
    label.appendChild(node('div', { color: '#4ade80', fontWeight: 600, fontSize: 12 }, name))
    row.appendChild(label)
    const sliderCol = node('div', { display: 'flex', flexDirection: 'column', gap: 2 }, null, null)
    const ticks = node('div', { display: 'flex', gap: 2, width: '100%' }, null, null)
    for (let i = 0; i < TICKS; i++) {
      ticks.appendChild(node('i', {
        flex: '1', height: 8, borderRadius: 2, cursor: 'pointer',
        background: i <= pos ? '#4ade80' : '#3a4750', opacity: i <= pos ? 0.9 : 0.5,
      }, null, { onClick: () => onPick(i) }))
    }
    sliderCol.appendChild(ticks)
    row.appendChild(sliderCol)
    row.appendChild(node('span', { color: valColor, fontFamily: 'var(--ui-font-mono, monospace)', fontSize: 11, textAlign: 'center', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, valFn()))
    root.appendChild(row)
  }
  // Which preset (if any) matches the CURRENT dial values — the active chip gets lit immediately.
  const currentPreset = d
    ? Object.keys(PRESET_DIALS).find((n) => {
        const p = PRESET_DIALS[n]
        return p.edits === d.edits.value && p.deps === d.deps.value
          && p.lines === d.lines.value
          && JSON.stringify(p.scope) === JSON.stringify(d.scope.value)
      })
    : null
  const chips = node('div', { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }, null, null)
  chips.appendChild(node('span', { fontSize: 8.5, letterSpacing: '.18em', color: '#7c8890' }, 'PRESETS'))
  for (const name of PRESETS) {
    const active = name === currentPreset
    chips.appendChild(node('button', {
      padding: '4px 10px', borderRadius: 999,
      border: active ? '1px solid #4ade80' : '1px solid #3a4750',
      background: active ? 'rgba(74,222,128,.18)' : 'rgba(22,32,40,.85)',
      color: active ? '#4ade80' : '#d7e4ec', cursor: 'pointer', fontSize: 11,
      fontWeight: active ? 700 : 400,
    }, name, {
      // INSTANT feedback: light the chip + optimistic dials + status line BEFORE the round trip.
      onClick: () => {
        const preset = PRESET_DIALS[name]
        if (snapshot && snapshot.dials && preset) {
          snapshot = { ...snapshot, dials: { ...snapshot.dials,
            edits: { ...snapshot.dials.edits, value: preset.edits, source: 'session' },
            scope: { ...snapshot.dials.scope, value: preset.scope, source: 'session' },
            lines: { ...snapshot.dials.lines, value: preset.lines, source: 'session' },
            deps: { ...snapshot.dials.deps, value: preset.deps, source: 'session' } } }
          panel.__renderChildren && panel.__renderChildren(api) // redraw rows instantly
        }
        api.sendRefresh('preset ' + name) // reconciles with the real response on arrival
      },
    }))
  }
  root.appendChild(chips)
  // live status line right under the chips: appears instantly, replaced by the backend reply.
  // lastReply survives rebuilds (the 4s poll rebuilds the panel and would otherwise wipe it).
  const status = node('div', { minHeight: 14, fontSize: 10.5, fontFamily: 'var(--ui-font-mono, monospace)',
    color: lastReply ? (lastReply.ok ? '#4ade80' : '#fb923c') : '#7c8890', overflow: 'hidden' },
    lastReply ? (lastReply.ok ? '' : '! ') + (lastReply.text || '') : null, null)
  root.appendChild(status)
  panel.__setStatus = (text, tone) => {
    lastReply = { ok: tone !== 'err', text }
    status.textContent = text
    status.style.color = tone === 'err' ? '#fb923c' : (tone === 'ok' ? '#4ade80' : '#7c8890')
  }
  const btns = node('div', { display: 'flex', gap: 8 }, null, null)
  btns.appendChild(node('button', {
    flex: 1, padding: '6px 12px', borderRadius: 8, border: '1px solid #3a4750',
    background: 'rgba(22,32,40,.85)', color: '#d7e4ec', cursor: 'pointer', fontSize: 12,
  }, 'Reset session', { onClick: () => { flash('reset to saved defaults…'); api.sendRefresh('reset') } }))
  const save = node('button', {
    flex: 1, padding: '6px 12px', borderRadius: 8, border: '0px solid #000',
    background: 'linear-gradient(180deg,#7ef0a8,#3fd97e)', color: '#04120a', fontWeight: 600, cursor: 'pointer', fontSize: 12,
  }, 'Save as default', { onClick: () => { flash('saving as default…'); api.sendRefresh('save') } })
  btns.appendChild(save)
  root.appendChild(btns)
  panel.appendChild(root)
  panel.__renderChildren = (a) => buildPanelChildren(panel, a || api)
  panel.__api = api
}

// ---------- full console page (stateless; repaint via morph on poll/commands) ----------

function ConsolePage({ api }) {
  const rootId = 'mixer-page-root'
  const repaint = () => {
    const existing = document.getElementById(rootId)
    if (!existing) return
    const d = snapshot && snapshot.dials
    // React elements are trees, not DOM nodes: compose the whole tree, children inline, then morph.
    const body = !d
      ? el('div', { style: { color: '#fb923c', fontSize: 13 } },
          'Loading dials… (or backend unavailable — check plugins.enabled, gateway restart, plugin_api.py)')
      : el('div', {},
          el('div', { style: { display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 12 } },
            dialRow(d, '01', 'Edits', EDITS_POS[d.edits.value] ?? 12, (i) => api.sendRefresh('edits ' + nearest(EDITS_POS, i)),
              el('span', { style: { color: '#4ade80', fontFamily: 'var(--ui-font-mono, monospace)', fontSize: 12 } }, d.edits.value)),
            dialRow(d, '02', 'Change scope', d.scope.value.length ? 8 : 0, () => api.send('scope show'),
              el('span', { style: { color: '#d7e4ec', fontSize: 11 } }, d.scope.value.length ? d.scope.value.join(', ') : '(no limit)')),
            dialRow(d, '03', 'Lines per turn', d.lines.value > 0 ? Math.round(Math.log2(d.lines.value + 1) / Math.log2(401) * (TICKS - 1)) : 0,
              (i) => api.sendRefresh('lines ' + (i <= 0 ? 'off' : Math.max(1, Math.round(Math.pow(2, (i / (TICKS - 1)) * Math.log2(401)) - 1)))),
              el('span', { style: { color: '#d7e4ec', fontFamily: 'var(--ui-font-mono, monospace)', fontSize: 12 } },
                d.lines.value > 0 ? String(d.lines.value) : 'off')),
            dialRow(d, '04', 'New libraries', DEPS_POS[d.deps.value] ?? 12, (i) => api.sendRefresh('deps ' + nearest(DEPS_POS, i)),
              el('span', { style: { color: '#4ade80', fontFamily: 'var(--ui-font-mono, monospace)', fontSize: 12 } }, d.deps.value))),
          presetChips(api.sendRefresh),
          actionButtons(api.sendRefresh),
          el('div', { style: { marginTop: 14, fontSize: 11, color: '#7c8890' } },
            'Changes apply to the live session immediately and are enforced by the hooks on the next tool call.'))
    const fresh = el('div', { id: rootId, style: { padding: '24px 28px', maxWidth: 980, margin: '0 auto', color: '#d7e4ec', fontFamily: 'var(--ui-font-sans, system-ui)' } },
      el('div', { style: { marginBottom: 18 } },
        el('div', { style: { fontFamily: 'var(--ui-font-mono, monospace)', fontWeight: 700, fontSize: 26, letterSpacing: '.14em', color: '#4ade80' } }, 'AGENT MIXER'),
        el('div', { style: { fontSize: 12, color: '#7c8890', letterSpacing: '.28em', marginTop: 4 } },
          '// STEERING CONSOLE — session ' + String((snapshot && snapshot.session) || '—'))),
      body)
    morph(existing, fresh)
  }
  pageRepaint = repaint
  // initial tree: rendered synchronously from whatever we have; the first poll fills it in.
  return el('div', { id: rootId, style: { padding: '24px 28px', maxWidth: 980, margin: '0 auto', color: '#d7e4ec' } },
    el('div', { style: { fontFamily: 'var(--ui-font-mono, monospace)', fontWeight: 700, fontSize: 26, letterSpacing: '.14em', color: '#4ade80' } }, 'AGENT MIXER'),
    el('div', { style: { fontSize: 12, color: '#7c8890', letterSpacing: '.28em', marginTop: 4 } }, '// STEERING CONSOLE — loading…'))
}

// ---------- status pill (stateless shell; interval updates text imperatively) ----------

function Pill({ api }) {
  return el('span', {
    id: 'mixer-pill',
    title: 'Agent Mixer — click to adjust the dials',
    // (a) pill click opens the SAME overlay as the composer icon; no navigation.
    onClick: (e) => {
      e.preventDefault()
      e.stopPropagation()
      togglePanel(e.currentTarget, api)
    },
    style: {
      padding: '0 8px', fontSize: 11, border: 0, background: 'transparent', cursor: 'pointer',
      color: '#4ade80', fontFamily: 'var(--ui-font-mono, monospace)', display: 'inline-block',
    },
  }, '🎛 …')
}

// ---------- registration ----------

export default {
  id: 'hermes-agent-mixer', // MUST match the gateway-side plugin id — ctx.rest is namespaced by it
  name: 'Agent Mixer',
  description: 'Steering console for the Agent Mixer dials — composer icon with a compact equaliser panel, live sliders over the same store the hooks enforce.',
  register(ctx) {
    const api = makeApi(ctx)
    ctx.registerMany([
      {
        id: 'composer-icon',
        area: COMPOSER_ACTIONS,
        order: 10,
        render: () => jsx(ComposerSlot, { api }),
      },
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/agent-mixer' },
        render: () => ConsolePage({ api }),
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
        // plain-element return (no nested component) — statusbar slot proved flaky with
        // plugin-realm component children; the interval poll updates the text imperatively.
        render: () => Pill({ api }),
      },
    ])
    // Poll OUTSIDE React: keeps snapshot + pill + open panel + page fresh without hooks.
    ctx.setInterval(async () => {
      await api.get()
      const pill = document.getElementById('mixer-pill')
      if (pill && snapshot && snapshot.dials) pill.textContent = '🎛 ' + summaryOf(snapshot.dials)
      const panel = document.getElementById('mixer-panel')
      if (panel && !panel.__renderChildren) buildPanelChildren(panel, api) // bootstrap after React mount
      if (panelOpen) refreshOpenPanel(api)
      if (document.getElementById('mixer-page-root') && pageRepaint) pageRepaint()
    }, REFRESH_MS)
  },
}