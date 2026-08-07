/* Shared helpers for all three pages: data loading, formatting, the SVG
   micro-helpers the charts and the map both use, and the detail drawer.

   Everything is plain ES modules against static JSON — there is no server, so
   the only performance lever is what gets fetched and when. establishments.json
   loads on every page; inspections.json (the big one) is fetched the first time
   somebody actually opens a detail view. */

export const fmt = n => (n === null || n === undefined || Number.isNaN(n)) ? '—' : n.toLocaleString('en-US');
export const S = 'http://www.w3.org/2000/svg';
export const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

export function el(name, attrs = {}, text) {
  const e = document.createElementNS(S, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}

export function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const k in attrs) {
    if (k === 'class') e.className = attrs[k];
    else if (k === 'html') e.innerHTML = attrs[k];
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), attrs[k]);
    else e.setAttribute(k, attrs[k]);
  }
  kids.flat().forEach(c => e.append(c?.nodeType ? c : document.createTextNode(c)));
  return e;
}

const BASE = new URL('.', import.meta.url).href.replace(/assets\/$/, '');
const cache = {};
export async function data(name) {
  if (!cache[name]) {
    cache[name] = fetch(`${BASE}data/${name}.json`).then(r => {
      if (!r.ok) throw new Error(`${name}.json — ${r.status}`);
      return r.json();
    });
  }
  return cache[name];
}

/* ---------------- score presentation ----------------
   Bands are for reading a number at a glance, not a grade LFCHD assigns. */
export function band(score) {
  if (score === null || score === undefined) return '';
  if (score >= 97) return 'good';
  if (score >= 90) return 'ok';
  return 'bad';
}

export function tipper(tipEl, hostEl) {
  return {
    show(html, x, y) {
      tipEl.innerHTML = html;
      tipEl.style.opacity = 1;
      const w = hostEl.clientWidth;
      tipEl.style.left = Math.min(Math.max(4, x + 14), Math.max(4, w - tipEl.offsetWidth - 4)) + 'px';
      tipEl.style.top = Math.max(2, y - tipEl.offsetHeight - 12) + 'px';
    },
    hide() { tipEl.style.opacity = 0; }
  };
}

/* ---------------- the shared detail drawer ---------------- */
let drawerEls = null, codeMap = null, lastTrigger = null;

function buildDrawer() {
  if (drawerEls) return drawerEls;
  const backdrop = h('div', { class: 'drawer-backdrop', onclick: closeDrawer });
  const body = h('div', { class: 'db' });
  const head = h('div', { class: 'dh' });
  const close = h('button', { class: 'close', 'aria-label': 'Close', onclick: closeDrawer }, '×');
  const drawer = h('div', { class: 'drawer', role: 'dialog', 'aria-modal': 'true' }, close, head, body);
  // `inert` takes the panel out of hit-testing AND the focus order the instant
  // it closes, without waiting on a transition. The CSS visibility/pointer-events
  // rules still apply; this is what makes the closed state unambiguous.
  drawer.inert = true;
  backdrop.inert = true;
  document.body.append(backdrop, drawer);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
  drawerEls = { backdrop, drawer, head, body, close };
  return drawerEls;
}

export function closeDrawer() {
  if (!drawerEls) return;
  drawerEls.drawer.classList.remove('open');
  drawerEls.backdrop.classList.remove('open');
  drawerEls.drawer.inert = true;
  drawerEls.backdrop.inert = true;
  // Focus would otherwise be stranded inside a panel nobody can see.
  if (lastTrigger && document.contains(lastTrigger)) lastTrigger.focus();
  else document.activeElement?.blur?.();
}

export async function openDetail(place) {
  const { backdrop, drawer, head, body, close } = buildDrawer();
  lastTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  drawer.inert = false;
  backdrop.inert = false;
  head.innerHTML = '';
  head.append(
    h('h2', {}, place.n || `Permit ${place.p}`),
    h('div', { class: 'addr' },
      [place.a, place.z].filter(Boolean).join(', ') || 'No street address on record')
  );

  const gap = (place.l !== null && place.w !== null) ? +(place.l - place.w).toFixed(1) : null;
  body.innerHTML = '';
  body.append(
    h('div', { class: 'dstats' },
      stat('Latest', place.l, band(place.l)),
      stat('Weighted history', place.w, band(place.w)),
      stat('All-time avg', place.v, ''),
      stat('Worst', place.x, band(place.x)),
    ),
    h('p', { class: 'dsub' },
      `${fmt(place.c)} scored inspections · ${place.f} to ${place.t}` +
      (gap !== null ? ` · gap ${gap > 0 ? '+' : ''}${gap}` : '')),
    h('div', { class: 'loading' }, 'Loading inspection history…')
  );

  drawer.classList.add('open');
  backdrop.classList.add('open');
  close.focus();

  try {
    if (!codeMap) codeMap = (await data('insights')).codes || {};
    const all = await data('inspections');
    const rows = (all[place.p] || []).slice().reverse();
    body.lastChild.replaceWith(renderHistory(rows));
  } catch (e) {
    body.lastChild.replaceWith(h('div', { class: 'empty' }, `Could not load history — ${e.message}`));
  }
}

function stat(label, value, cls) {
  return h('div', { class: 'dstat' },
    h('div', { class: 'l' }, label),
    h('div', { class: 'v' + (cls ? ' ' + cls : '') },
      value === null || value === undefined ? '—' : String(value)));
}

function renderHistory(rows) {
  if (!rows.length) return h('div', { class: 'empty' }, 'No inspection history recorded.');
  const wrap = h('div', { class: 'hist' });
  rows.forEach(r => {
    const codes = h('div', { class: 'vcodes' });
    (r.v || []).forEach(c => {
      const info = codeMap[c];
      codes.append(h('span', {
        class: 'vcode',
        title: info ? `${c} — ${info.t} (${info.c})` : `Code ${c}`
      }, info ? info.t : `Code ${c}`));
    });
    wrap.append(h('div', { class: 'row' },
      h('div', { class: 'd mono' }, r.d),
      h('div', { class: 't' }, r.t || ''),
      h('div', { class: 's' }, r.s === null ? '—' : String(r.s)),
      h('div', { class: 'v' }, (r.v && r.v.length) ? codes
        : h('span', { style: 'color:var(--ink-3)' }, r.s === null ? 'not scored' : 'no violations'))
    ));
  });
  return wrap;
}

/* ---------------- nav ---------------- */
export function markNav() {
  const here = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('nav a').forEach(a => {
    if ((a.getAttribute('href') || '').split('/').pop() === here) a.setAttribute('aria-current', 'page');
  });
}

export async function stampAsOf(sel = '.asof') {
  try {
    const e = await data('establishments');
    document.querySelectorAll(sel).forEach(n => {
      n.textContent = `Data through ${e.asof}`;
    });
  } catch { /* the page still works without the stamp */ }
}
