// FORM studio — boot, viewport wiring, draft flow, pipeline rail.
import { Viewer } from './viewer.js';
import { S, A, h, api, P, fmt, trim, dur, ago, toast, head, hasDraft, values } from './core.js';
import { renderInspector, renderDraft, openProjects, openAlternatives } from './panels.js';

const $ = id => document.getElementById(id);
const STAGES = [
  ['brief', 'Brief', 'What it is for, what is known'],
  ['shape', 'Shape', 'Select a feature, change it'],
  ['fit', 'Fit', 'Clearance under uncertainty'],
  ['prove', 'Prove', 'Checks and the slice'],
  ['release', 'Release', 'Gate, history, files'],
];
let viewer, previewSeq = 0, previewTimer = null, pollTimer = null;

// ── loading ────────────────────────────────────────────────
async function boot() {
  viewer = new Viewer($('viewport'), {
    onPick: f => { if (S.stage !== 'shape' && f) S.stage = 'shape'; A.select(f); },
    onHover: (f, e) => {
      const chip = $('chip');
      if (!f) { chip.hidden = true; return; }
      const feat = S.data.recipe.features.find(x => x.id === f);
      chip.replaceChildren(feat.label, h('small', null, feat.role));
      const r = $('viewport').getBoundingClientRect();
      chip.style.left = (e.clientX - r.left) + 'px';
      chip.style.top = (e.clientY - r.top) + 'px';
      chip.hidden = false;
    },
  });
  window.__form = { S, viewer, A };
  $('mark').onclick = () => openProjects();
  try {
    S.studio = await api('/studio');
  } catch (e) { return fatal(e); }
  const link = fromHash();
  const want = link.p || new URLSearchParams(location.search).get('p') || localStorage.getItem('form.project');
  const found = S.studio.projects.find(p => p.id === want && !p.error) || S.studio.projects.find(p => !p.error);
  if (found) { await A.open(found.id); if (link.tab) A.stage(link.tab); } else { renderBar(); openProjects(true); }
  window.addEventListener('hashchange', async () => {
    const l = fromHash();
    if (l.p && l.p !== S.pid) { S.studio = await api('/studio'); await A.open(l.p); }
    if (l.tab) A.stage(l.tab);
  });
  watch();
}

// Deep links from agents: #p=<project>&tab=<brief|shape|fit|prove|release>
function fromHash() {
  const q = new URLSearchParams(location.hash.replace(/^#/, ''));
  return { p: q.get('p'), tab: q.get('tab') };
}

// An agent (MCP or CLI) may change the project while this page is open. Follow it.
let stamp = null;
function watch() {
  setInterval(async () => {
    if (!S.pid || S.job || document.hidden) return;
    let s;
    try { s = await P('/stamp'); } catch { return; }
    const key = `${s.head}:${s.updated}`;
    if (stamp && key !== stamp && !hasDraft()) {
      const last = s.last || {};
      if (last.origin && last.origin.startsWith('agent')) toast(`r${String(s.head).padStart(2, '0')} by ${last.origin.replace('agent:', '')}`, last.note || '');
      await A.refresh(true);
    }
    stamp = key;
  }, 2000);
}

function fatal(e) {
  $('inspector').replaceChildren(h('section', null, h('div.err', null, h('b', null, e.message), e.hint || '')));
}

A.open = async pid => {
  S.pid = pid;
  localStorage.setItem('form.project', pid);
  Object.assign(S, { draft: { values: {}, prov: {}, note: '' }, preview: null, draftError: null, proposal: null, feature: null, compare: null, layers: null, section: null });
  S.ack = new Set();
  $('layers').hidden = true;
  await A.refresh(true);
  viewer.setView('iso', false);
  const st = S.data.status;
  if (S.data.project.auto_run !== false && Object.values(st).some(n => n.state !== 'current') && !S.job) A.run();
};

A.refresh = async (withView) => {
  S.data = await P();
  if (S.data.recovered) toast('Project recovered', S.data.recovered);
  if (withView || !S.view || S.view.rev !== S.data.project.head) {
    try {
      S.view = await P('/view');
      S.view.rev = S.data.project.head;
    } catch (e) { toast(e.message, e.hint, true); }
  }
  if (!hasDraft()) showHead();
  render();
};

function showHead() {
  if (!S.view) return;
  viewer.setModel(S.view);
  viewer.setGhost(S.compare ? S.compare.view : null);
  viewer.select(S.feature);
  applyStageView();
}

// ── draft: live preview with computed impact ───────────────
A.setParam = (key, value, immediate) => {
  const base = head().values[key];
  if (Math.abs(value - base) < 1e-9) delete S.draft.values[key]; else S.draft.values[key] = value;
  S.proposal = null;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(runPreview, immediate ? 0 : 70);
};
A.setProv = (key, prov) => { S.draft.prov[key] = prov; render(); };
A.loadDraft = vals => {
  S.draft.values = {};
  for (const [k, v] of Object.entries(vals)) if (Math.abs(v - head().values[k]) > 1e-9) S.draft.values[k] = v;
  runPreview(true);
};

async function runPreview(full) {
  const seq = ++previewSeq;
  if (!Object.keys(S.draft.values).length) {
    S.preview = null; S.draftError = null; showHead(); viewer.flag([]);
    full ? render() : renderDraft();
    if (full) return; else return renderHud();
  }
  try {
    const pv = await P('/preview', { values: S.draft.values });
    if (seq !== previewSeq) return;
    S.preview = pv; S.draftError = null;
    viewer.setModel(pv);
    viewer.setGhost(S.view);
    viewer.select(S.feature);
    viewer.flag(pv.impact.features.filter(f => f.change !== 'trimmed').map(f => f.id));
    applyStageView();
  } catch (e) {
    if (seq !== previewSeq) return;
    S.draftError = e;      // keep showing the last geometry that built
    viewer.flag(e.feature ? [e.feature] : []);
  }
  full ? render() : (renderDraft(), renderHud(), markParams());
}

function markParams() {
  const bad = new Set(S.draftError?.params || []);
  document.querySelectorAll('.param[data-key]').forEach(el => {
    el.classList.toggle('changed', el.dataset.key in S.draft.values);
    el.classList.toggle('bad', bad.has(el.dataset.key));
  });
}

A.discard = () => {
  S.draft = { values: {}, prov: {}, note: '' }; S.preview = null; S.draftError = null; S.proposal = null;
  previewSeq++; viewer.flag([]); showHead(); render();
};

A.commit = async () => {
  try {
    const r = await P('/commit', { values: S.draft.values, provenance: S.draft.prov, note: S.draft.note, origin: S.draft.origin || 'user' });
    S.draft = { values: {}, prov: {}, note: '' }; S.preview = null; S.proposal = null; S.ack = new Set();
    viewer.flag([]);
    toast(`Committed as r${String(r.head).padStart(2, '0')}`, r.job ? 'Regenerating solid, exports, checks and slice.' : 'Auto-regenerate is off: outputs are now stale.');
    if (r.job) track(r.job);
    await A.refresh(true);
  } catch (e) { S.draftError = e; render(); }
};

A.checkout = async n => {
  if (hasDraft()) return toast('Commit or discard the draft first.', '', true);
  const r = await P('/checkout', { rev: n });
  S.compare = null; S.ack = new Set();
  if (r.job) track(r.job);
  await A.refresh(true);
  toast(`Head is now r${String(n).padStart(2, '0')}`);
};

A.select = f => {
  S.feature = f;
  viewer.select(f);
  if (f) viewer.focusFeature(f); else viewer.setView(viewer.viewName || 'iso');
  S.proposal = null;
  render();
};
A.hover = f => { viewer.hovered = f; viewer._paint(); };

// ── pipeline ───────────────────────────────────────────────
A.run = async (nodes, force) => {
  try { track((await P('/run', { nodes: nodes || [], force: !!force })).job); }
  catch (e) { toast(e.message, e.hint, true); }
};
A.settings = async body => {
  try { const r = await P('/settings', body); if (r.job) track(r.job); await A.refresh(); }
  catch (e) { toast(e.message, e.hint, true); }
};
A.track = id => { if (id) track(id); };

function track(id) {
  S.job = id;
  clearTimeout(pollTimer);
  const tick = async () => {
    let job;
    try { job = await P('/job/' + id); } catch { S.job = null; S.running = {}; return renderGraph(); }
    S.running = Object.fromEntries(job.steps.map(s => [s.node, s.state]));
    renderGraph();
    if (job.state === 'running') { pollTimer = setTimeout(tick, 140); return; }
    S.job = null; S.running = {};
    const bad = job.steps.find(s => s.state === 'failed' || s.state === 'blocked') || (job.error && { label: 'Pipeline', error: job.error });
    if (bad) toast(`${bad.label}: ${bad.error?.message || 'stopped'}`, bad.error?.hint, true);
    S.layers = null;
    await A.refresh(true);
  };
  tick();
}

// ── chrome ─────────────────────────────────────────────────
function renderBar() {
  const env = S.studio.env, sl = env.slicer;
  if (S.data) {
    const p = S.data.project, ap = S.data.approval;
    const rev = 'r' + String(p.head).padStart(2, '0');
    let stamp;
    if (hasDraft()) stamp = h('span.stamp.draft', null, 'Uncommitted draft');
    else if (ap.state === 'approved') stamp = h('span.stamp.approved', null, `Released ${rev}`);
    else if (ap.state === 'superseded') stamp = h('span.stamp.superseded', { title: 'Changed since release: ' + ap.changed.join(', ') }, `r${String(ap.rev).padStart(2, '0')} released · ${rev} is not`);
    else stamp = h('span.stamp.none', null, 'Unreleased');
    $('proj').replaceChildren(h('span.name', null, p.name), h('span.recipe', null, S.data.recipe.title), h('span.rev', { title: 'Head revision' }, rev), stamp);
  } else $('proj').replaceChildren(h('span.name', null, 'No project open'));
  const bits = sl.available
    ? [h('span.dot'), h('b', null, sl.presets.machine.name), h('span.sep', null, '/'), sl.presets.filament.name, h('span.sep', null, '/'), sl.presets.process.name]
    : [h('span.dot.off'), h('b', null, 'Slicer unavailable'), h('span', { title: sl.reason }, '— ' + (sl.reason || '').slice(0, 60))];
  $('ctx').replaceChildren(...bits);
  $('ctx').title = sl.available ? `Bambu Studio ${sl.version} — presets follow ${sl.source.machine}. ${env.kernel}.` : sl.reason;
}

function stageNote(id) {
  const d = S.data, roll = d.checks?.rollup;
  if (id === 'brief') {
    const k = d.recipe.params.filter(p => p.group === 'brief');
    const m = k.filter(p => head().provenance[p.key]?.source === 'measured').length;
    return k.length ? [`${m}/${k.length} measured`, m === k.length ? 'ok' : ''] : ['', ''];
  }
  if (id === 'shape') return [hasDraft() ? 'Draft open' : `${d.recipe.features.length} features`, hasDraft() ? 'warn' : ''];
  if (id === 'fit') return d.fit ? [`${Math.round(d.fit.yield * 100)}% modelled`, d.fit.yield >= 0.95 ? 'ok' : 'warn'] : ['Calibration', ''];
  if (id === 'prove') {
    if (!roll) return ['Not current', 'warn'];
    return roll.FAIL ? [`${roll.FAIL} failed`, 'fail'] : roll.WARN ? [`${roll.WARN} to review`, 'warn'] : ['All pass', 'ok'];
  }
  if (id === 'release') return d.approval.state === 'approved' ? ['Released', 'ok'] : d.gate.ready ? ['Ready to approve', ''] : ['Not ready', ''];
  return ['', ''];
}

function renderRail() {
  const kids = STAGES.map(([id, title], i) => {
    const [note, cls] = stageNote(id);
    return h('button', { class: S.stage === id ? 'on' : '', onclick: () => A.stage(id) },
      h('span.n', null, '0' + (i + 1)), h('span.t', null, title), h('span.s', { class: cls }, note));
  });
  $('rail').replaceChildren(...kids, h('div.gap'),
    h('div.foot', null, `FORM ${S.studio.env.version}`, h('br'), 'Local only. Nothing is uploaded or printed.'));
}

A.stage = id => {
  S.stage = id;
  S.section = null;
  document.body.classList.remove('layers');
  if (id !== 'prove') { S.layers = null; $('layers').hidden = true; }
  if (id !== 'release') { if (S.compare) { S.compare = null; viewer.setGhost(hasDraft() ? S.view : null); } }
  viewer.setMarker(null);
  applyStageView();
  render();
};

function sectionNow() {
  if (S.section) return S.section.axis ? S.section : null;
  if (S.stage === 'fit' && S.data?.recipe.fit) {   // cut through the middle of the fit feature
    const fid = S.data.recipe.params.find(p => p.key === S.data.recipe.fit.clearance).feature;
    const fb = viewer.featureBox(fid), b = viewer.bounds;
    const t = fb ? ((fb.min.y + fb.max.y) / 2 - b.min.y) / (b.max.y - b.min.y) : 0.2;
    return { axis: 'y', t: Math.min(0.9, Math.max(0.05, t)) };
  }
  return null;
}

function applyStageView() {
  // each stage looks at the object the way its question needs
  viewer.setCompanions(S.stage === 'fit' ? true : (S.companions && S.stage !== 'prove'));
  const s = sectionNow();
  viewer.setSection(s ? s.axis : null, s ? s.t : 0.5);
}

function renderHud() {
  const v = S.preview || S.view;
  const views = ['iso', 'front', 'side', 'top', 'under'];
  const sn = sectionNow(), sec = sn?.axis || null;
  $('hud-tr').replaceChildren(
    h('div.seg', { title: 'Section' }, ['x', 'y', 'z'].map(ax => h('button', {
      class: sec === ax ? 'on' : '', onclick: () => { S.section = sec === ax ? { axis: null } : { axis: ax, t: 0.5 }; applyStageView(); renderHud(); },
    }, 'Cut ' + ax))),
    h('div.seg', null, views.map(n => h('button', { class: viewer.viewName === n ? 'on' : '', onclick: () => { viewer.setView(n); renderHud(); } }, n))));
  const bl = [];
  if (v) {
    const b = v.bbox;
    bl.push(h('div.readout', null, h('b', null, `${fmt(b[1][0] - b[0][0], 1)} × ${fmt(b[1][1] - b[0][1], 1)} × ${fmt(b[1][2] - b[0][2], 1)}`), ' mm  ·  ',
      h('b', null, fmt(v.volume_mm3 / 1000, 1)), ' cm³  ·  plate 180 × 180'));
    if (v.companions?.length) bl.push(h('div.seg', null, h('button', { class: viewer.showCompanions ? 'on' : '', onclick: () => { S.companions = !viewer.showCompanions; viewer.setCompanions(S.companions); renderHud(); } }, 'Device')));
  }
  $('hud-bl').replaceChildren(...bl);
  const bc = [];
  if (sec && !S.layers) {
    $('hud-tr').append(h('input.slider-wide', { type: 'range', min: 0.02, max: 0.98, step: 0.01, value: sn.t, 'aria-label': 'Section position',
      oninput: e => { S.section = { axis: sec, t: +e.target.value }; viewer.setSection(sec, +e.target.value); } }));
  }
  if (!S.layers) $('hud-bc').replaceChildren(...bc);
  const tl = [];
  if (hasDraft() && S.preview) tl.push(h('div.banner', null, h('span.cap', null, 'Draft — not committed'),
    'Solid shows the draft. ', h('b', { style: 'color:var(--model)' }, 'Dashed blue'), ` is r${String(S.data.project.head).padStart(2, '0')}. Exports and checks still describe the committed revision.`));
  if (S.compare) tl.push(h('div.banner.blue', null, h('span.cap', null, 'Comparing'),
    `Solid is r${String(S.data.project.head).padStart(2, '0')} (head). Dashed blue is r${String(S.compare.rev).padStart(2, '0')}.`));
  $('hud-tl').replaceChildren(...tl);
}

function renderGraph() {
  if (!S.data) return $('graph').replaceChildren();
  const d = S.data, st = d.status, p = d.project;
  const rev = 'r' + String(p.head).padStart(2, '0');
  const node = (id, meta, onclick) => {
    const n = st[id];
    let state = n.state;
    const run = S.running[id];
    if (run === 'running' || run === 'queued') state = 'running';
    else if (n.blocked && state !== 'current' && state !== 'failed') state = state === 'stale' ? 'stale' : 'blocked';
    const label = { current: 'Current', stale: `Stale · made for r${String(n.last_rev || 0).padStart(2, '0')}`, failed: 'Failed', missing: 'Not made', blocked: 'Waiting', running: run === 'queued' ? 'Queued' : 'Working' }[state];
    return h('button.node', { class: state, onclick, title: n.error?.message || '' },
      h('div.h', null, h('span.t', null, n.label), h('span.s', null, label)),
      h('div.m', null, state === 'current' ? meta : n.error ? n.error.message : n.unavailable && id === 'slice' ? n.unavailable : state === 'stale' ? 'Does not describe ' + rev : '—'),
      h('div.k', null, n.key));
  };
  const roll = d.checks?.rollup, sl = d.slice, ex = d.exports;
  const ap = d.approval;
  const dirty = Object.values(st).some(n => n.state !== 'current');
  $('graph').replaceChildren(
    h('div.node.src', null, h('div.h', null, h('span.t', null, 'Parameters'), h('span.s', { style: 'color:var(--ink)' }, rev)),
      h('div.m', null, head().summary || head().note), h('div.k', null, ago(head().ts))),
    node('geometry', S.view ? `${S.view.faces} faces · ${S.view.kernel.split(' /')[0]}` : '', () => A.stage('shape')),
    node('exports', ex ? `${ex.files.step.name.split('.')[0]} · .step .stl` : '', () => A.stage('release')),
    node('checks', roll ? `${roll.PASS} pass · ${roll.WARN} review · ${roll.FAIL} fail` : '', () => A.stage('prove')),
    node('slice', sl ? `${dur(sl.time_s)} · ${fmt(sl.filament_g, 1)} g · ${sl.layers} layers` : '', () => A.stage('prove')),
    h('button.node.rel', { class: ap.state, onclick: () => (dirty && !S.job ? A.run() : A.stage('release')) },
      h('div.h', null, h('span.t', null, 'Release'), h('span.s', null, ap.state === 'approved' ? 'Approved' : ap.state === 'superseded' ? 'Superseded' : 'None')),
      h('div.m', null, ap.state === 'approved' ? ap.release : ap.state === 'superseded' ? `${ap.release} is an earlier design` : d.gate.ready ? 'Ready for approval' : d.gate.reasons[0] || ''),
      h('div.k', null, dirty && !S.job ? 'Click to regenerate' : d.gate.evidence_level)),
    h('button.node.auto', { class: p.auto_run === false ? 'off' : 'on', title: 'When on, every commit regenerates the solid, exports, checks and slice. When off they stay stale until you run them.',
      onclick: () => A.settings({ auto_run: p.auto_run === false }) },
      h('div.h', null, h('span.t', null, 'Auto')), h('div.m', null, p.auto_run === false ? 'off' : 'on'), h('div.k', null, 'regenerate')));
}

export function render() {
  renderBar(); renderRail(); renderGraph(); renderHud();
  if (S.data) renderInspector(viewer);
}
A.render = render;
A.viewer = () => viewer;
A.alternatives = () => openAlternatives();
A.reloadStudio = async () => { S.studio = await api('/studio'); };

window.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (!$('sheet').hidden) { if (S.data) $('sheet').hidden = true; }
    else if (S.feature) A.select(null);
  }
});
boot();
