// Shared state, DOM helper, API client, formatting.
export const S = {
  studio: null, pid: null, data: null, view: null,
  stage: 'shape', feature: null,
  draft: { values: {}, prov: {}, note: '' }, preview: null, draftError: null,
  proposal: null, proposalBusy: false,
  job: null, running: {}, ack: new Set(),
  compare: null, layers: null, section: null, companions: true,
};
export const A = {};   // actions, filled in by app.js

export function h(tag, attrs, ...kids) {
  const [name, ...cls] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (cls.length) el.className = cls.join(' ');
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className += (el.className ? ' ' : '') + v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'hidden') el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export class ApiError extends Error {
  constructor(e, status) { super(e.message || 'Request failed'); Object.assign(this, e); this.status = status; }
}

export async function api(path, body, raw) {
  const opt = body === undefined ? {} : {
    method: 'POST',
    headers: raw ? { 'Content-Type': 'application/octet-stream' } : { 'Content-Type': 'application/json' },
    body: raw ? body : JSON.stringify(body),
  };
  let res;
  try { res = await fetch('/api' + path, opt); }
  catch { throw new ApiError({ message: 'The studio server is not answering.', hint: 'Start it again with ./run.sh — your projects are saved on disk.' }, 0); }
  const data = await res.json().catch(() => ({ error: { message: `Unexpected response (${res.status})` } }));
  if (!res.ok || data.error) throw new ApiError(data.error || { message: res.statusText }, res.status);
  return data;
}
export const P = (rest = '', body, raw) => api(`/projects/${S.pid}${rest}`, body, raw);

export const fmt = (v, d = 2) => (v == null || Number.isNaN(v)) ? '—' : Number(v).toFixed(d);
export const trim = (v, d = 3) => (v == null) ? '—' : String(parseFloat(Number(v).toFixed(d)));
export function dur(s) {
  if (s == null) return '—';
  const m = Math.round(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`;
}
export function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
export function toast(msg, hint, bad) {
  const t = h('div.toast', { class: bad ? 'bad' : '' }, msg, hint ? h('small', null, hint) : null);
  document.getElementById('toasts').append(t);
  setTimeout(() => t.remove(), bad ? 7000 : 3200);
}
export const head = () => S.data.project.revisions.find(r => r.n === S.data.project.head);
export const spec = key => S.data.recipe.params.find(p => p.key === key);
export const values = () => ({ ...head().values, ...S.draft.values });
export const hasDraft = () => Object.keys(S.draft.values).length > 0 || Object.keys(S.draft.prov).length > 0;
