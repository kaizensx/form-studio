// Stage inspectors. Each answers one question about the design.
import { S, A, h, api, P, fmt, trim, dur, ago, toast, head, spec, values, hasDraft } from './core.js';
import { thumbnail } from './viewer.js';

const $ = id => document.getElementById(id);
const pad = n => 'r' + String(n).padStart(2, '0');
const SOURCES = { measured: 'Measured', specified: 'Specified', assumed: 'Assumed', photo: 'From photo' };
const SIGMA = { measured: 0.03, specified: 0.1, assumed: 0.3, photo: 0.6 };

export function renderInspector(viewer) {
  const el = $('inspector');
  const keep = el.scrollTop;
  const body = { brief, shape, fit, prove, release }[S.stage](viewer);
  el.replaceChildren(...body.filter(Boolean), h('div', { id: 'draft' }));
  renderDraft();
  el.scrollTop = keep;
}

// ── parameter row ──────────────────────────────────────────
function paramRow(p, { prov = false } = {}) {
  const v = values()[p.key];
  const pr = { ...(head().provenance[p.key] || { source: 'assumed' }), ...(S.draft.prov[p.key] || {}) };
  const num = h('input', { type: 'number', min: p.min, max: p.max, step: p.step, value: trim(v, 4), 'aria-label': p.label });
  const rng = h('input', { type: 'range', min: p.min, max: p.max, step: p.step, value: v, 'aria-label': p.label + ' slider' });
  rng.addEventListener('input', () => { num.value = trim(+rng.value, 4); A.setParam(p.key, +rng.value); });
  num.addEventListener('change', () => {
    const x = parseFloat(num.value);
    if (!Number.isFinite(x)) { num.value = trim(values()[p.key], 4); return; }
    rng.value = x; A.setParam(p.key, x, true);
  });
  const row = h('div.param', { 'data-key': p.key, class: (p.key in S.draft.values ? 'changed ' : '') + (S.draftError?.params?.includes(p.key) ? 'bad' : '') },
    h('div.top', null, h('label', { title: p.doc }, p.label), num, h('span.unit', null, p.unit)),
    rng, p.doc ? h('div.doc', null, p.doc) : null);
  if (prov) {
    const sel = h('select', { 'aria-label': p.label + ' source', onchange: e => A.setProv(p.key, { source: e.target.value, sigma: SIGMA[e.target.value] }) },
      Object.entries(SOURCES).map(([k, t]) => h('option', { value: k, selected: pr.source === k }, t)));
    const sg = h('input', { type: 'number', step: 0.01, min: 0, max: 5, value: trim(pr.sigma ?? SIGMA[pr.source] ?? 0.3, 3), title: 'Uncertainty (1σ)',
      onchange: e => A.setProv(p.key, { source: sel.value, sigma: Math.max(0, parseFloat(e.target.value) || 0) }) });
    row.append(h('div.prov', null, h('span.tag', { class: pr.source }, SOURCES[pr.source] || pr.source), sel, '±', sg, h('span.unit', null, p.unit)));
  }
  return row;
}

// ── draft / impact (shared footer) ─────────────────────────
export function renderDraft() {
  const box = $('draft');
  if (!box) return;
  if (!hasDraft() && !S.draftError) { box.replaceChildren(); box.className = ''; return; }
  box.className = 'draft';
  const im = S.preview?.impact, kids = [];
  const next = pad(Math.max(...S.data.project.revisions.map(r => r.n)) + 1);
  kids.push(h('div.cap', null, h('span', null, 'Draft change'), h('span', null, S.preview ? `rebuilt in ${Math.round(S.preview.timing.total_s * 1000)} ms` : '')));
  if (S.draftError) {
    kids.push(h('div.err', null, h('b', null, S.draftError.message), S.draftError.hint || '',
      h('div.fine', { style: 'margin-top:4px' }, 'The view still shows the last version that built. Nothing has been saved.')));
  }
  if (im) {
    for (const c of im.params) kids.push(h('div.delta', null, h('span', null, c.label),
      h('span.v', null, h('s', null, trim(c.from)), h('i', null, '→'), trim(c.to), ' ', c.unit)));
    if (im.features.length) {
      kids.push(h('div.sub', null, h('span.cap', null, 'Features touched'),
        h('div.chips', null, im.features.map(f => h('span.tag', { class: f.change, title: f.change === 'trimmed' ? 'Same size and place; its boundary is cut differently by a neighbour' : f.change }, `${f.label} · ${f.change}`)))));
    }
    const ifs = im.derived.filter(d => d.interface), other = im.derived.filter(d => !d.interface);
    if (ifs.length) kids.push(h('div.sub', null, h('span.cap', { style: 'color:var(--signal)' }, 'Interface dimensions change'),
      ifs.map(d => h('div.delta.iface', null, h('span', null, d.label), h('span.v', null, h('s', null, fmt(d.from)), h('i', null, '→'), fmt(d.to), ' ', d.unit)))));
    else if (im.params.length) kids.push(h('div.sub', null, h('span.cap', null, 'Interfaces'), h('div.fine', null, 'No interface dimension changes. Fit is unaffected by this draft.')));
    const rows = [...other.map(d => ({ ...d, d: 2 })), ...im.metrics.map(m => ({ ...m, d: m.unit === '%' ? 0 : 2 }))];
    if (rows.length) kids.push(h('div.sub', null, h('span.cap', null, 'Consequences'),
      rows.map(d => h('div.delta', null, h('span', null, d.label), h('span.v', null, h('s', null, fmt(d.from, d.d)), h('i', null, '→'), fmt(d.to, d.d), ' ', d.unit)))));
    if (im.invalidates.length) kids.push(h('div.sub', null, h('div.stale-note', null, 'Committing makes ', h('b', null, im.invalidates.join(', ')),
      ` stale; they are regenerated for ${next}.`, im.revokes_approval ? h('b', null, ` The release of ${pad(S.data.approval.rev)} will no longer describe the current design.`) : '')));
  }
  for (const [k, v] of Object.entries(S.draft.prov)) {
    kids.push(h('div.delta', null, h('span', null, spec(k).label + ' source'), h('span.v', null, `${SOURCES[v.source]} ±${trim(v.sigma)}`)));
  }
  const note = h('input', { type: 'text', placeholder: 'Why this change? (optional, kept in history)', value: S.draft.note, oninput: e => { S.draft.note = e.target.value; }, style: 'margin-top:10px' });
  kids.push(note, h('div.btns', null,
    h('button.btn.primary', { id: 'commit', disabled: !!S.draftError || (!S.preview && !Object.keys(S.draft.prov).length), onclick: A.commit }, `Commit as ${next}`),
    h('button.btn.quiet', { onclick: A.discard }, 'Discard')));
  box.replaceChildren(...kids);
}

// ── 01 brief ───────────────────────────────────────────────
function brief() {
  const d = S.data, p = d.project, env = S.studio.env, sl = env.slicer;
  const known = d.recipe.params.filter(x => x.group === 'brief');
  const ta = h('textarea', { rows: 4, placeholder: 'What is it for? Where does it live? What must it hold, clear, or survive?', value: p.brief.text,
    onblur: e => { if (e.target.value !== p.brief.text) A.settings({ brief: e.target.value }); } });
  const refs = p.brief.references || [];
  return [
    h('header', null, h('h1', null, 'Brief', h('small', null, 'Intent and what is actually known. Anything not measured is carried as an assumption all the way to release.'))),
    h('section', null, h('div.cap', null, 'Intent'), ta,
      S.studio.assistant.available ? h('div.btns', null, h('button.btn.quiet', { disabled: S.proposalBusy || !p.brief.text.trim(), onclick: () => ask(p.brief.text, null, 'default') }, S.proposalBusy ? 'Asking…' : `Propose parameters from brief · ${S.studio.assistant.default}`)) : null,
      proposalCard()),
    known.length ? h('section', null, h('div.cap', null, h('span', null, 'Known about the object'), h('span', null, 'value · source · ±1σ')),
      known.map(x => paramRow(x, { prov: true }))) : null,
    h('section', null, h('div.cap', null, h('span', null, 'Reference photos'), h('span', null, refs.length ? `${refs.length} attached` : '')),
      h('p.fine', null, 'A photo can give a rough dimension once you mark a known length in it. FORM treats photo values as ±0.6 mm or worse and never as a fit-critical measurement.'),
      refs.map(r => h('div.row', null, h('span.k', null, r.file, h('small', null, r.scale_mm_per_px ? `scale set · ${r.measurements.length} measurement(s)` : 'no scale yet')),
        h('button.btn.quiet', { onclick: () => openPhoto(r) }, 'Measure'))),
      h('div.btns', null, h('label.btn.quiet', null, 'Attach photo', h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', hidden: true, onchange: attachPhoto })))),
    h('section', null, h('div.cap', null, 'Printer context'),
      sl.available ? [
        h('div.row', null, h('span.k', null, 'Printer'), h('span.v', null, sl.presets.machine.name)),
        h('div.row', null, h('span.k', null, 'Material'), h('span.v', null, sl.presets.filament.name)),
        h('div.row', null, h('span.k', null, 'Process'), h('span.v', null, sl.presets.process.name)),
        h('div.row', null, h('span.k', null, 'Walls · infill · supports'), h('span.v', null, `${sl.summary.walls} · ${sl.summary.infill} · ${sl.summary.supports === '1' ? 'on' : 'off'}`)),
        h('p.fine', { style: 'margin-top:8px' }, `Read from Bambu Studio ${sl.version} (${sl.source.machine}). Change the selection there, or pin presets in studio.toml; the slice goes stale when they change.`),
        h('div.btns', null, h('button.btn.quiet', { onclick: async () => { await api('/studio/refresh', {}); await A.reloadStudio(); await A.refresh(); toast('Presets re-read from Bambu Studio'); } }, 'Re-read presets')),
      ] : h('div.err', null, h('b', null, 'Slicer unavailable'), sl.reason)),
  ];
}

// ── 02 shape ───────────────────────────────────────────────
function shape() {
  const d = S.data, f = d.recipe.features.find(x => x.id === S.feature);
  const cur = S.preview || S.view;
  if (!f) {
    const loose = d.recipe.params.filter(p => p.group !== 'brief' && !d.recipe.features.some(x => x.id === p.feature));
    return [
      h('header', null, h('h1', null, 'Shape', h('small', null, 'Click a feature on the model, or pick one here. Changes stay a draft until you commit them.'))),
      h('section', null, h('div.cap', null, h('span', null, 'Features'), h('span', null, 'build order')),
        d.recipe.features.map(x => {
          const n = d.recipe.params.filter(p => p.feature === x.id && p.group !== 'brief').length;
          const touched = n && d.recipe.params.some(p => p.feature === x.id && p.key in S.draft.values);
          return h('button.feat', { class: x.role, onclick: () => A.select(x.id), onmouseenter: () => A.hover(x.id), onmouseleave: () => A.hover(null) },
            h('span.sw'), h('span.t', null, x.label, touched ? ' ●' : '', h('span.d', null, x.doc)), h('span.tag', { class: x.role }, x.role));
        })),
      loose.length ? h('section', null, h('div.cap', null, 'General'), loose.map(p => paramRow(p))) : null,
      h('section', null, h('div.cap', null, 'Explore'),
        h('p', null, 'Build a grid of real candidates and rank them against objectives you weight.'),
        h('div.btns', null, h('button.btn', { onclick: A.alternatives, disabled: hasDraft() }, 'Compare alternatives'))),
      intentSection(null),
    ];
  }
  const params = d.recipe.params.filter(p => p.feature === f.id);
  const derived = (cur?.derived || []).filter(x => x.feature === f.id);
  return [
    h('header', null, h('button.back', { onclick: () => A.select(null) }, '← All features'),
      h('h1', null, f.label, ' ', h('span.tag', { class: f.role, style: 'vertical-align:5px' }, f.role), h('small', null, f.doc))),
    params.length ? h('section', null, h('div.cap', null, h('span', null, 'Drives this feature'), h('span', null, `${params.length} parameter${params.length > 1 ? 's' : ''}`)),
      params.map(p => paramRow(p, { prov: p.group === 'brief' }))) : h('section', null, h('p.fine', null, 'This feature has no parameters of its own; it follows the features around it.')),
    derived.length ? h('section', null, h('div.cap', null, h('span', null, 'Follows from them'), h('span', null, 'not editable')),
      derived.map(x => h('div.row', null, h('span.k', null, x.label, x.interface ? h('span.tag.interface', { style: 'margin-left:6px' }, 'interface') : null, h('small', null, x.formula)),
        h('span.v', null, fmt(x.value), ' ', x.unit)))) : null,
    intentSection(f),
  ];
}

function intentSection(f) {
  if (S.studio.chat && S.studio.chat.available) return null;      // the Claude panel on the left replaces this box
  const as = S.studio.assistant;
  const input = h('input', { type: 'text', id: 'intent', placeholder: f ? `e.g. “make the ${f.label.toLowerCase()} a bit ${f.role === 'interface' ? 'looser' : 'bolder'}”` : 'e.g. “make it harder to tip over”',
    onkeydown: e => { if (e.key === 'Enter') ask(input.value, f?.id, 'rule'); } });
  return h('section', null, h('div.cap', null, h('span', null, f ? 'Describe a change to this feature' : 'Describe a change'), h('span', null, 'proposal only')),
    input,
    h('div.btns', null,
      h('button.btn', { disabled: S.proposalBusy, onclick: () => ask(input.value, f?.id, 'rule') }, 'Read'),
      as.available ? h('button.btn.quiet', { disabled: S.proposalBusy, title: 'One tool-less call to the everyday model through the installed claude client', onclick: () => ask(input.value, f?.id, 'default') }, S.proposalBusy ? 'Asking…' : `Ask ${as.default}`) : null,
      as.available && as.specialist ? h('button.btn.quiet', { disabled: S.proposalBusy, title: `Specialist consultation, capped at $${S.studio.env.models.specialist_budget_usd}. Use for a hard trade-off, not routine edits.`, onclick: () => ask(input.value, f?.id, 'specialist') }, `Consult ${as.specialist}`) : null),
    h('p.fine', { style: 'margin-top:8px' }, '“Read” parses simple requests locally. A model only proposes parameter values; the kernel rebuilds and you decide.'),
    proposalCard());
}

async function ask(text, feature, tier) {
  if (!text?.trim()) return;
  if (hasDraft()) { toast('Commit or discard the current draft first.', '', true); return; }
  S.proposalBusy = true; S.proposal = null; A.render();
  try {
    const r = await P('/intent', { text, feature, tier });
    S.proposal = r.proposal || { none: true, message: r.message };
    S.proposal.text = text;
  } catch (e) { S.proposal = { failed: e }; }
  S.proposalBusy = false;
  A.render();
  const i = $('intent'); if (i) i.value = text;
}

function proposalCard() {
  const p = S.proposal;
  if (!p) return null;
  if (p.failed) return h('div.err', null, h('b', null, p.failed.message), p.failed.hint || '');
  if (p.none) return h('div.note.amber', null, p.message, S.studio.assistant.available ? ' Try “Ask” to let the model interpret it, or name a parameter and an amount.' : ' Name a parameter and an amount.');
  const who = p.source === 'rule' ? 'Read locally' : `${p.requested_model}${p.resolved_models?.length ? ' (' + p.resolved_models.join(', ') + ')' : ''} · ${p.seconds}s${p.cost_usd != null ? ' · $' + p.cost_usd.toFixed(3) : ''}`;
  return h('div.note', { id: 'proposal' }, h('div.cap', { style: 'margin-bottom:6px;color:var(--model)' }, 'Proposal · ' + who),
    h('div', { style: 'font-weight:600' }, p.summary),
    p.changes.map(c => h('div', { style: 'margin-top:6px' }, h('div.delta', null, h('span', null, c.label), h('span.v', null, h('s', null, trim(c.from)), h('i', null, '→'), trim(c.to), ' ', c.unit)), h('div.fine', null, c.reason))),
    p.cautions?.length ? h('div.fine', { style: 'margin-top:6px' }, p.cautions.map(c => h('div', null, '△ ' + c))) : null,
    p.buildable === false ? h('div.err', null, h('b', null, 'This proposal does not build'), p.build_error.message + ' ' + (p.build_error.hint || '')) : null,
    !p.changes.length ? null : h('div.btns', null,
      h('button.btn', { disabled: p.buildable === false, onclick: () => { const v = Object.fromEntries(p.changes.map(c => [c.key, c.to])); S.draft.origin = p.source === 'rule' ? 'user' : 'proposal:' + p.requested_model; S.draft.note = p.source === 'rule' ? '' : `${p.requested_model}: ${p.summary}`.slice(0, 200); S.proposal = null; A.loadDraft({ ...head().values, ...v }); } }, 'Load as draft'),
      h('button.btn.quiet', { onclick: () => { S.proposal = null; A.render(); } }, 'Dismiss')));
}

// ── 03 fit ─────────────────────────────────────────────────
function fitChart(f) {
  const W = 366, H = 132, m = { l: 6, r: 6, t: 10, b: 26 };
  const [lo, hi] = f.window, mu = f.expected_gap, sd = Math.max(f.sd, 1e-4);
  const x0 = Math.min(lo - 0.25, mu - 3.6 * sd, -0.05), x1 = Math.max(hi + 0.25, mu + 3.6 * sd);
  const X = x => m.l + (x - x0) / (x1 - x0) * (W - m.l - m.r), Y = y => H - m.b - y * (H - m.t - m.b);
  const pdf = x => Math.exp(-0.5 * ((x - mu) / sd) ** 2);
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('width', '100%');
  const add = (tag, a, text) => { const e = document.createElementNS(ns, tag); for (const k in a) e.setAttribute(k, a[k]); if (text) e.textContent = text; svg.append(e); return e; };
  const area = (a, b, fill) => { let dd = `M${X(a)},${Y(0)}`; for (let i = 0; i <= 60; i++) { const x = a + (b - a) * i / 60; dd += `L${X(x)},${Y(pdf(x))}`; } add('path', { d: dd + `L${X(b)},${Y(0)}Z`, fill }); };
  add('rect', { x: X(lo), y: m.t - 4, width: X(hi) - X(lo), height: H - m.b - m.t + 4, fill: '#2f6b3c', opacity: 0.09 });
  area(x0, Math.min(lo, x1), '#e5432a55'); area(Math.max(hi, x0), x1, '#a8690a55'); area(Math.max(lo, x0), Math.min(hi, x1), '#3d4fb833');
  let dd = ''; for (let i = 0; i <= 160; i++) { const x = x0 + (x1 - x0) * i / 160; dd += (i ? 'L' : 'M') + X(x) + ',' + Y(pdf(x)); }
  add('path', { d: dd, fill: 'none', stroke: '#1b1a18', 'stroke-width': 1.4 });
  add('line', { x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: '#1b1a18', 'stroke-width': 1 });
  for (const [x, label, anchor] of [[lo, fmt(lo), 'end'], [hi, fmt(hi), 'start']]) {
    add('line', { x1: X(x), x2: X(x), y1: m.t - 4, y2: Y(0) + 4, stroke: '#2f6b3c', 'stroke-width': 1, 'stroke-dasharray': '3 2' });
    add('text', { x: X(x) + (anchor === 'end' ? -3 : 3), y: H - 12, 'text-anchor': anchor }, label);
  }
  add('line', { x1: X(mu), x2: X(mu), y1: Y(1), y2: Y(0) + 4, stroke: '#1b1a18', 'stroke-width': 1 });
  add('text', { x: X(mu), y: H - 1, 'text-anchor': 'middle', style: 'fill:#1b1a18' }, `expected ${fmt(mu)} mm`);
  if (x0 < 0) { add('line', { x1: X(0), x2: X(0), y1: Y(0) - 3, y2: Y(0) + 4, stroke: '#c2281a' }); if (X(lo) - X(0) > 44) add('text', { x: X(0), y: H - 12, 'text-anchor': 'middle', style: 'fill:#c2281a' }, '0'); }
  return svg;
}

function fit() {
  const d = S.data, f = S.preview?.fit || d.fit, cal = d.calibration, c = cal.correction;
  const calSection = h('section', null, h('div.cap', null, h('span', null, 'Printer accuracy on this profile'), h('span.tag', { class: c.source === 'calibrated' ? 'calibrated' : 'assumed' }, c.source)),
    h('div.fine', { style: 'margin-bottom:8px' }, cal.profile),
    h('div.row', null, h('span.k', null, 'Bias on internal widths'), h('span.v', null, (c.bias >= 0 ? '+' : '') + fmt(c.bias, 3), ' mm')),
    h('div.row', null, h('span.k', null, 'Spread (1σ)'), h('span.v', null, '±' + fmt(c.sigma, 3), ' mm')),
    h('p.fine', { style: 'margin-top:8px' }, c.note, ' Measurements from any project on this profile are pooled and reused.'),
    cal.records.length ? h('table', { style: 'margin-top:8px' }, h('tr', null, h('th', null, 'Recorded'), h('th', null, 'Source'), h('th.n', null, 'Widths'), h('th.n', null, 'Mean Δ'), h('th')),
      cal.records.map(r => h('tr', null, h('td', null, ago(r.ts)), h('td', null, r.source), h('td.n', null, r.pairs.length),
        h('td.n', null, fmt(r.pairs.reduce((a, x) => a + x.measured - x.nominal, 0) / r.pairs.length, 3)),
        h('td', null, h('button.btn.quiet', { style: 'padding:3px 6px', title: 'Remove this record', onclick: async () => { const j = await P('/calibration_remove', { id: r.id }); A.track(j.job); await A.refresh(); } }, '×'))))) : null);

  if (!d.recipe.fit) {   // the coupon: its job is to feed calibration
    const slots = (S.view?.derived || []).filter(x => x.interface);
    const inputs = slots.map(s => h('input', { type: 'number', step: 0.01, placeholder: fmt(s.value), 'aria-label': s.label + ' measured' }));
    return [
      h('header', null, h('h1', null, 'Calibrate', h('small', null, 'Print this coupon on the profile below, measure each slot with caliper inside jaws, and enter what you read.'))),
      h('section', null, h('div.cap', null, h('span', null, 'Measured slot widths'), h('span.tag.physical', null, 'physical')),
        h('table', null, h('tr', null, h('th', null, 'Slot'), h('th.n', null, 'Nominal'), h('th.n', null, 'Measured mm')),
          slots.map((s, i) => h('tr', null, h('td', null, s.label), h('td.n', null, fmt(s.value)), h('td.n', null, inputs[i])))),
        h('p.fine', { style: 'margin-top:8px' }, 'Leave blank any slot you did not measure. Only enter numbers read from a real print.'),
        h('div.btns', null, h('button.btn.primary', { onclick: () => recordWidths(slots.map((s, i) => ({ nominal: s.value, measured: parseFloat(inputs[i].value) })).filter(x => Number.isFinite(x.measured)), 'coupon') }, 'Record measurements'))),
      calSection,
    ];
  }
  const y = Math.round(f.yield * 100);
  const lo = h('input.mini', { type: 'number', step: 0.05, value: trim(f.window[0]), 'aria-label': 'Minimum total gap' });
  const hi = h('input.mini', { type: 'number', step: 0.05, value: trim(f.window[1]), 'aria-label': 'Maximum total gap' });
  const setWin = () => A.settings({ fit: { gap_min: parseFloat(lo.value), gap_max: parseFloat(hi.value) } });
  lo.onchange = hi.onchange = setWin;
  const src = f.sources, tp = d.costs.test_piece;
  const cav = (S.preview || S.view)?.derived.find(x => x.key === f.cavity_key);
  const meas = h('input.mini', { type: 'number', step: 0.01, style: 'width:84px', placeholder: fmt(f.cavity_nominal), 'aria-label': 'Measured pocket width' });
  return [
    h('header', null, h('h1', null, f.label, h('small', null, 'Will it slide in without rattling? A model built from stated inputs, shown with where each came from.'))),
    h('section', null,
      h('div.big', null, y + '%', h('small', null, 'modelled chance the gap lands in your window')),
      fitChart(f),
      h('div.kv', null,
        h('div', null, h('b', null, fmt(f.p_tight * 100, 0) + '%'), h('span', null, 'too tight')),
        h('div', null, h('b', null, fmt(f.expected_gap) + ' mm'), h('span', null, `expected total gap ±${fmt(2 * f.sd)}`)),
        h('div', null, h('b', null, fmt(f.p_loose * 100, 0) + '%'), h('span', null, 'too loose'))),
      S.preview ? h('p.fine', { style: 'margin-top:8px' }, 'Showing the draft.') : null),
    h('section', null, h('div.cap', null, 'Where the uncertainty comes from'),
      h('div.row', null, h('span.k', null, f.mating_label || 'Device width', h('small', null, `${fmt(f.mating)} mm ±${fmt(src.mating.sigma)} · ${Math.round(src.mating.share * 100)}% of variance`)), h('span.tag', { class: src.mating.source }, src.mating.source)),
      h('div.row', null, h('span.k', null, 'Printed pocket', h('small', null, `${fmt(f.cavity_nominal)} mm ${src.printer.bias >= 0 ? '+' : ''}${fmt(src.printer.bias, 3)} bias ±${fmt(src.printer.sigma)} · ${Math.round(src.printer.share * 100)}% of variance`)), h('span.tag', { class: src.printer.source === 'calibrated' ? 'calibrated' : 'assumed' }, src.printer.source)),
      h('div.row', null, h('span.k', null, 'Acceptable total gap', h('small', null, 'your definition of a good fit')), h('span', null, lo, ' – ', hi, ' mm')),
      h('p.fine', { style: 'margin-top:8px' }, f.model)),
    h('section', null, h('div.cap', null, h('span', null, 'Most useful next step'), h('span', null, 'by modelled yield gained')),
      d.actions.map((a, i) => h('div.act', { class: i === 0 ? 'first' : '' }, h('span.i', null, String(i + 1).padStart(2, '0')),
        h('div', null, h('div.t', null, a.title), h('div.w', null, a.why),
          h('div.bar2', null, h('i', { style: `width:${f.yield * 100}%` }), a.gain > 0.005 ? h('u', { style: `left:${f.yield * 100}%;width:${a.gain * 100}%` }) : null),
          h('div.m', null, h('span', null, a.gain > 0.005 ? `${y}% → ${Math.round(a.after * 100)}%` : `${Math.round(a.after * 100)}%`), h('span', null, a.cost)),
          a.change ? h('div.btns', null, h('button.btn.quiet', { disabled: hasDraft(), onclick: () => { A.stage('shape'); A.loadDraft({ ...head().values, ...a.change }); } }, 'Load as draft')) : null,
          a.id === 'measure' ? h('div.btns', null, h('button.btn.quiet', { onclick: () => A.stage('brief') }, 'Enter the measurement')) : null)))),
    h('section', null, h('div.cap', null, h('span', null, 'Pocket ring test piece'), tp ? h('span.tag.simulated', null, 'sliced') : null),
      h('p', null, 'A 6 mm slice of this revision’s real pocket with 3 mm walls: the cheapest physical test of this exact interface.'),
      tp ? h('div.row', null, h('span.k', null, 'Slicer estimate'), h('span.v', null, `${dur(tp.time_s)} · ${fmt(tp.filament_g, 1)} g`)) : null,
      h('div.btns', null, h('button.btn', { id: 'ring', onclick: sliceRing }, tp ? 'Files' : 'Cut and slice it'))),
    h('section', null, h('div.cap', null, h('span', null, `Record a printed result for ${pad(d.project.head)}`), h('span.tag.physical', null, 'physical')),
      h('div.row', null, h('span.k', null, 'Measured pocket width', h('small', null, `nominal ${fmt(cav?.value)} mm; feeds calibration`)), h('span', null, meas, ' mm')),
      h('div.btns', null, h('button.btn', { onclick: () => recordWidths([{ nominal: f.cavity_nominal, measured: parseFloat(meas.value) }].filter(x => Number.isFinite(x.measured)), 'part') }, 'Record width'),
        ['too_tight', 'good', 'too_loose'].map(r => h('button.btn.quiet', { onclick: () => recordFit(r) }, r.replace('_', ' ')))),
      d.project.evidence.filter(e => e.rev === d.project.head && (e.kind === 'fit' || e.source === 'part')).map(e => h('div.note.green', null, `${ago(e.ts)} · ` + (e.kind === 'fit' ? `fit was ${e.result.replace('_', ' ')}` : e.pairs.map(x => `${fmt(x.nominal)} → ${fmt(x.measured)} mm`).join(', '))))),
    calSection,
  ];
}

async function recordWidths(pairs, source) {
  if (!pairs.length) return toast('Enter at least one measured width.', '', true);
  try { const r = await P('/evidence', { kind: 'widths', pairs, source }); A.track(r.job); toast('Recorded', 'Calibration updated; checks are being recomputed.'); await A.refresh(); }
  catch (e) { toast(e.message, e.hint, true); }
}
async function recordFit(result) {
  try { const r = await P('/evidence', { kind: 'fit', result }); A.track(r.job); toast('Recorded physical result'); await A.refresh(); }
  catch (e) { toast(e.message, e.hint, true); }
}
async function sliceRing() {
  const b = $('ring'); b.disabled = true; b.textContent = 'Cutting and slicing…';
  try {
    const r = await P('/test_piece', {});
    await A.refresh();
    sheet('Pocket ring', [
      h('p', null, r.piece.doc),
      h('div.row', null, h('span.k', null, 'Size'), h('span.v', null, r.piece.bbox.map(x => fmt(x, 1)).join(' × ') + ' mm')),
      h('div.row', null, h('span.k', null, 'Slicer estimate', h('small', null, 'simulated, with the presets shown in the header')), h('span.v', null, `${dur(r.time_s)} · ${fmt(r.filament_g, 1)} g · ${r.layers} layers`)),
      h('div.btns', null, h('a.btn', { href: `/api/projects/${S.pid}/file/side/${r.key}/${r.stl}` }, 'Download STL'),
        r.threemf ? h('a.btn', { href: `/api/projects/${S.pid}/file/side/${r.key}/${r.threemf}` }, 'Download sliced 3MF') : null),
      h('p.fine', { style: 'margin-top:10px' }, 'FORM does not send anything to the printer. Open the 3MF in Bambu Studio to print it, then record the measured width under Fit.'),
    ]);
  } catch (e) { toast(e.message, e.hint, true); A.render(); }
}

// ── 04 prove ───────────────────────────────────────────────
function prove(viewer) {
  const d = S.data, ch = d.checks, sl = d.slice, st = d.status;
  const out = [h('header', null, h('h1', null, 'Prove', h('small', null, 'What has been established about this revision, and by what kind of evidence.')))];
  if (!ch) {
    const n = st.checks;
    out.push(h('section', null, h('div.note.amber', null, n.state === 'failed' ? n.error.message : n.state === 'stale' ? `The last checks were made for ${pad(n.last_rev)} and do not describe ${pad(d.project.head)}.` : 'Checks have not been produced for this revision.'),
      h('div.btns', null, h('button.btn.primary', { disabled: !!S.job, onclick: () => A.run() }, S.job ? 'Working…' : 'Run pipeline'))));
  } else {
    out.push(h('section', null, h('div.cap', null, h('span', null, `Checks for ${pad(ch.rev)}`), h('span', null, `${ch.rollup.PASS} pass · ${ch.rollup.WARN} review · ${ch.rollup.FAIL} fail`)),
      ch.checks.map(c => h('button.check', { class: c.at || c.feature ? 'link' : '', onclick: () => { if (c.at) viewer.setMarker({ at: c.at, to: c.to }); else if (c.feature) { viewer.setMarker(null); viewer.select(c.feature); viewer.focusFeature(c.feature); } } },
        h('span.st', { class: c.status }, c.status), h('span', null, h('span.top', null, h('span.l', null, c.label), h('span.v', null, c.value)), h('div.d', null, h('span.tag', { class: c.evidence }, c.evidence), ' ', c.detail))))));
    out.push(h('section', null, h('div.cap', null, h('span', null, 'Print orientation'), h('span', null, 'computed from the solid')),
      h('table', null, h('tr', null, h('th', null, 'Lay it'), h('th.n', null, 'Height'), h('th.n', null, 'On plate'), h('th.n', null, 'Overhang'), h('th.n', null, 'Ceilings')),
        ch.orientation_table.map(o => h('tr.pick', { class: o.id === d.project.orientation ? 'on' : '', title: 'Use this orientation (re-exports the STL and re-slices)', onclick: () => o.id !== d.project.orientation && A.settings({ orientation: o.id }) },
          h('td', null, o.label), h('td.n', null, fmt(o.height_mm, 0)), h('td.n', null, fmt(o.contact_mm2, 0)), h('td.n', null, fmt(o.steep_mm2, 0)), h('td.n', null, fmt(o.ceiling_mm2, 0))))),
      h('p.fine', { style: 'margin-top:8px' }, 'Areas in mm². Overhang is surface steeper than 45°; ceilings are flat faces that must bridge or be supported. Changing orientation makes the exports, checks and slice stale.')));
  }
  const n = st.slice;
  if (sl) {
    out.push(h('section', null, h('div.cap', null, h('span', null, `Slice of ${pad(sl.rev)}`), h('span.tag.simulated', null, 'simulated')),
      h('div.kv', null, h('div', null, h('b', null, dur(sl.time_s)), h('span', null, 'estimated print time')), h('div', null, h('b', null, fmt(sl.filament_g, 1) + ' g'), h('span', null, `${fmt(sl.filament_mm / 1000, 1)} m filament`)), h('div', null, h('b', null, sl.layers), h('span', null, `layers to ${fmt(sl.max_z_mm, 1)} mm`))),
      h('div.row', { style: 'margin-top:10px' }, h('span.k', null, 'Supports generated'), h('span.v', null, sl.support_used ? 'yes' : 'none')),
      h('div.row', null, h('span.k', null, 'Presets'), h('span', { style: 'text-align:right;font-size:12px' }, Object.values(sl.presets).map(x => h('div', null, x.name)))),
      h('div.row', null, h('span.k', null, 'Slicer'), h('span.v', null, `Bambu Studio ${sl.slicer_version} · ${sl.seconds}s`)),
      (sl.plate_warnings || []).length ? h('div.fine', { style: 'margin-top:6px' }, 'Slicer notes: ' + [...new Set(sl.plate_warnings)].join(', ')) : null,
      sl.images?.includes('plate_1.png') ? h('img', { src: `/api/projects/${S.pid}/file/slice/current/plate_1.png?k=${n.key}`, alt: 'Plate preview rendered by Bambu Studio', style: 'width:100%;margin-top:10px;border:1px solid var(--rule);background:#fff' }) : null,
      h('div.btns', null, h('button.btn', { id: 'inspect', onclick: () => toggleLayers() }, S.layers ? 'Back to 3D' : 'Inspect layers'),
        h('a.btn.quiet', { href: `/api/projects/${S.pid}/file/slice/current/${sl.threemf}` }, 'Sliced 3MF')),
      h('p.fine', { style: 'margin-top:8px' }, 'A slice shows the toolpaths Bambu Studio would send with these presets. It is not a print: adhesion, warping and fit are only known after printing.')));
  } else {
    out.push(h('section', null, h('div.cap', null, 'Slice'),
      n.unavailable ? h('div.err', null, h('b', null, 'Blocked'), n.unavailable) :
        h('div.note.amber', null, n.state === 'failed' ? h('span', null, h('b', null, n.error.message), ' ', n.error.hint || '') : n.state === 'stale' ? `The last slice was of ${pad(n.last_rev)}; it does not describe ${pad(d.project.head)}.` : 'Not sliced yet.'),
      h('div.btns', null, h('button.btn', { disabled: !!S.job || !!n.unavailable, onclick: () => A.run(['geometry', 'exports', 'checks', 'slice'], n.state === 'failed') }, n.state === 'failed' ? 'Try again' : 'Slice now'))));
  }
  return out;
}

const TYPE_COLOR = { 'Outer wall': '#1b1a18', 'Inner wall': '#8b877f', 'Sparse infill': '#d9a441', 'Internal solid infill': '#3d4fb8', 'Top surface': '#0f7b73', 'Bottom surface': '#0a5550', 'Bridge': '#e5432a', 'Overhang wall': '#e5432a', 'Gap infill': '#b9b4a8', 'Support': '#2f6b3c', 'Support interface': '#2f6b3c', 'Floating vertical shell': '#c2281a' };

async function toggleLayers(force) {
  const cv = $('layers');
  if (S.layers && !force) { S.layers = null; cv.hidden = true; $('hud-bc').replaceChildren(); document.body.classList.remove('layers'); A.render(); return; }
  try {
    const meta = await P('/layers');
    S.layers = { ...meta, n: Math.min(meta.count - 1, 3), cache: {} };
  } catch (e) { return toast(e.message, e.hint, true); }
  cv.hidden = false;
  document.body.classList.add('layers');
  A.render();
  const slider = h('input.slider-wide', { type: 'range', min: 0, max: S.layers.count - 1, step: 1, value: S.layers.n, 'aria-label': 'Layer', oninput: e => { S.layers.n = +e.target.value; drawLayer(); } });
  const label = h('div.readout', { id: 'layer-label' });
  $('hud-bc').replaceChildren(h('div', { style: 'display:flex;flex-direction:column;align-items:center;gap:6px' },
    h('div', { style: 'display:flex;gap:10px;align-items:center' }, label, slider),
    h('div.legend', null, S.layers.types.map(t => h('span', null, h('i', { style: `background:${TYPE_COLOR[t] || '#777'}` }), t)))));
  drawLayer();
}

async function drawLayer() {
  const L = S.layers; if (!L) return;
  const n = L.n;
  if (!L.cache[n]) L.cache[n] = await P(`/layers?n=${n}`);
  if (!S.layers || S.layers.n !== n) return;
  const layer = L.cache[n], cv = $('layers'), r = cv.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
  cv.width = r.width * dpr; cv.height = r.height * dpr;
  const c = cv.getContext('2d'); c.scale(dpr, dpr);
  let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
  if (!L.box) {
    for (const p of layer.paths) for (let i = 0; i < p.p.length; i += 2) { x0 = Math.min(x0, p.p[i]); x1 = Math.max(x1, p.p[i]); y0 = Math.min(y0, p.p[i + 1]); y1 = Math.max(y1, p.p[i + 1]); }
    const padmm = 14; L.box = [x0 - padmm, x1 + padmm, y0 - padmm, y1 + padmm];
  }
  [x0, x1, y0, y1] = L.box;
  const s = Math.min(r.width / (x1 - x0), (r.height - 90) / (y1 - y0));
  const ox = (r.width - (x1 - x0) * s) / 2, oy = (r.height - 70 - (y1 - y0) * s) / 2;
  const X = x => ox + (x - x0) * s, Y = y => r.height - 70 - oy - (y - y0) * s;
  c.strokeStyle = 'rgba(27,26,24,.07)'; c.lineWidth = 1;
  for (let g = Math.ceil(x0 / 10) * 10; g <= x1; g += 10) { c.beginPath(); c.moveTo(X(g), Y(y0)); c.lineTo(X(g), Y(y1)); c.stroke(); }
  for (let g = Math.ceil(y0 / 10) * 10; g <= y1; g += 10) { c.beginPath(); c.moveTo(X(x0), Y(g)); c.lineTo(X(x1), Y(g)); c.stroke(); }
  c.lineWidth = Math.max(0.8, 0.42 * s * 0.9); c.lineCap = 'round'; c.lineJoin = 'round';
  for (const p of layer.paths) {
    c.strokeStyle = TYPE_COLOR[p.t] || '#777'; c.beginPath();
    for (let i = 0; i < p.p.length; i += 2) i ? c.lineTo(X(p.p[i]), Y(p.p[i + 1])) : c.moveTo(X(p.p[i]), Y(p.p[i + 1]));
    c.stroke();
  }
  const types = [...new Set(layer.paths.map(p => p.t))];
  const lab = $('layer-label');
  if (lab) lab.replaceChildren('Layer ', h('b', null, `${n + 1} / ${L.count}`), '  ·  z ', h('b', null, fmt(layer.z)), ' mm  ·  ', types.includes('Bridge') ? h('b', { style: 'color:var(--signal)' }, 'bridge here') : `${layer.paths.length} paths`);
}

// ── 05 release ─────────────────────────────────────────────
function release(viewer) {
  const d = S.data, g = d.gate, ap = d.approval, p = d.project;
  const note = h('input', { type: 'text', placeholder: 'Release note (optional)' });
  const gate = [];
  if (ap.state === 'approved') gate.push(h('div.note.green', null, h('b', null, `${pad(ap.rev)} is released.`), ` Approved ${ago(ap.ts)} as ${ap.release}. ${g.evidence_level}.`));
  else {
    if (ap.state === 'superseded') gate.push(h('div.note.amber', null, h('b', null, `${pad(ap.rev)} was released; ${pad(p.head)} has not been.`), ` Changed since: ${ap.changed.join(', ')}. The earlier release folder is intact but is a different design.`));
    if (g.reasons.length) gate.push(h('div.err', null, h('b', null, 'Not ready'), g.reasons.map(r => h('div', null, r))));
    if (g.warnings.length) gate.push(h('div', { style: 'margin:8px 0' }, h('div.cap', { style: 'margin-bottom:6px' }, 'Acknowledge each warning to release with it'),
      g.warnings.map(w => h('label', { style: 'display:flex;gap:8px;padding:4px 0;align-items:baseline' },
        h('input', { type: 'checkbox', checked: S.ack.has(w.id), onchange: e => { e.target.checked ? S.ack.add(w.id) : S.ack.delete(w.id); A.render(); } }),
        h('span', null, h('b', null, w.label), ` — ${w.value}`)))));
    gate.push(h('p.fine', null, `Releasing states: ${g.evidence_level}.`), note,
      h('div.btns', null, h('button.btn.primary', { id: 'approve', disabled: !g.ready || g.warnings.some(w => !S.ack.has(w.id)) || hasDraft(), onclick: async () => {
        try { const r = await P('/approve', { acknowledged: [...S.ack], note: note.value }); toast(`Released ${r.release}`, 'Files copied with a hash manifest.'); await A.refresh(); }
        catch (e) { toast(e.message, e.hint, true); }
      } }, `Approve and release ${pad(p.head)}`)));
  }
  const revs = [...p.revisions].sort((a, b) => b.n - a.n);
  return [
    h('header', null, h('h1', null, 'Release', h('small', null, 'A release is a frozen copy of files whose hashes match the revision they claim to be.'))),
    h('section', null, h('div.cap', null, `Gate for ${pad(p.head)}`), gate),
    d.releases.length ? h('section', null, h('div.cap', null, 'Releases'),
      [...d.releases].reverse().map(r => h('div.row', null, h('span.k', null, r, h('small', { id: 'v-' + r }, ap.release === r && ap.state === 'approved' ? 'matches the current design' : 'an earlier design')),
        h('span', null, h('button.btn.quiet', { onclick: async () => { const v = await P('/release/' + r); $('v-' + r).textContent = (v.intact ? 'files intact' : 'FILES ALTERED: ' + v.files.filter(f => !f.ok).map(f => f.file).join(', ')) + (v.matches_head ? ' · matches the current design' : ' · not the current design'); } }, 'Verify'),
          ' ', h('a.btn.quiet', { href: `/api/projects/${S.pid}/file/releases/${r}/REPORT.md` }, 'Report'))))) : null,
    d.exports ? h('section', null, h('div.cap', null, h('span', null, `Working files for ${pad(d.exports.rev)}`), h('span', null, 'not a release')),
      Object.values(d.exports.files).map(f => h('div.row', null, h('span.k', null, f.name, h('small', null, `${(f.bytes / 1024).toFixed(0)} kB · sha256 ${f.sha256.slice(0, 12)}…`)),
        h('a.btn.quiet', { href: `/api/projects/${S.pid}/file/exports/current/${f.name}` }, 'Download')))) : null,
    h('section', null, h('div.cap', null, h('span', null, 'Revisions'), h('span', null, `${revs.length} · head ${pad(p.head)}`)),
      revs.map(r => h('div', { style: 'padding:9px 0;border-top:1px dotted var(--rule)' },
        h('div', { style: 'display:flex;gap:8px;align-items:baseline' }, h('span.rev', { style: r.n === p.head ? 'background:var(--ink);color:var(--paper)' : '' }, pad(r.n)),
          h('span', { style: 'flex:1;font-weight:600' }, r.note), h('span.fine', null, ago(r.ts))),
        h('div.fine', { style: 'margin:3px 0 0 42px' }, r.origin === 'user' || r.origin === 'recipe' ? '' : r.origin.startsWith('agent') ? `by ${r.origin.replace('agent:', '') || 'agent'} · ` : r.origin === 'cli' ? 'from the command line · ' : `via ${r.origin.replace('proposal:', '')} proposal · `, r.parent ? `from ${pad(r.parent)}` : 'start',
          p.approvals.some(a => a.rev === r.n) ? ' · released' : ''),
        r.n !== p.head ? h('div.btns', { style: 'margin:6px 0 0 42px' },
          h('button.btn.quiet', { onclick: () => compare(r.n, viewer) }, S.compare?.rev === r.n ? 'Hide comparison' : 'Compare with head'),
          h('button.btn.quiet', { onclick: () => A.checkout(r.n) }, 'Make head')) : null,
        S.compare?.rev === r.n ? diffCard(S.compare) : null))),
    h('section', null, h('div.cap', null, 'Decision log'),
      [...p.decisions].reverse().slice(0, 12).map(x => h('div.fine', { style: 'padding:4px 0;border-top:1px dotted var(--rule)' }, h('b', { style: 'color:var(--ink-2)' }, `${pad(x.rev)} · ${x.kind}`), ' — ', x.text, x.cost_usd != null ? ` ($${x.cost_usd.toFixed(3)})` : '')),
      p.decisions.length ? null : h('p.fine', null, 'Approvals, model consultations, orientation changes and physical results are logged here.')),
    h('section', null, h('div.cap', null, 'Project file'),
      h('p', null, 'Everything in one archive: revisions, provenance, artifacts, releases.'),
      h('div.btns', null, h('a.btn', { href: `/api/projects/${S.pid}/archive` }, 'Save .formproj'))),
  ];
}

async function compare(n, viewer) {
  if (S.compare?.rev === n) { S.compare = null; viewer.setGhost(null); return A.render(); }
  try {
    const [view, diff] = await Promise.all([P(`/view?rev=${n}`), P(`/diff?a=${n}&b=${S.data.project.head}`)]);
    S.compare = { rev: n, view, diff };
    viewer.setGhost(view);
    viewer.flag(diff.impact.features.filter(f => f.change !== 'trimmed').map(f => f.id));
    A.render();
  } catch (e) { toast(e.message, e.hint, true); }
}

function diffCard(c) {
  const im = c.diff.impact;
  const rows = [...im.derived.map(d => ({ ...d, d: 2 })), ...im.metrics.map(m => ({ ...m, d: m.unit === '%' ? 0 : 2 }))];
  return h('div.note', { style: 'margin:8px 0 0 42px' },
    h('div.cap', { style: 'color:var(--model);margin-bottom:6px' }, `${pad(c.rev)} → ${pad(S.data.project.head)}`),
    im.params.length ? im.params.map(x => h('div.delta', null, h('span', null, x.label), h('span.v', null, h('s', null, trim(x.from)), h('i', null, '→'), trim(x.to), ' ', x.unit))) : h('div.fine', null, 'Same parameters.'),
    im.features.length ? h('div.chips', null, im.features.map(f => h('span.tag', { class: f.change }, `${f.label} · ${f.change}`))) : null,
    im.interfaces_touched.length ? h('div', { style: 'color:var(--signal);font-weight:600;margin:4px 0' }, 'Interface changed: ' + im.interfaces_touched.join(', ')) : (im.params.length ? h('div.fine', null, 'No interface dimension differs between these revisions.') : null),
    rows.map(d => h('div.delta', null, h('span', null, d.label), h('span.v', null, h('s', null, fmt(d.from, d.d)), h('i', null, '→'), fmt(d.to, d.d), ' ', d.unit))));
}

// ── sheets ─────────────────────────────────────────────────
function sheet(title, body, wide) {
  const s = $('sheet');
  s.replaceChildren(h('div.sheet', { style: wide ? '' : 'width:min(620px,92vw)', role: 'dialog', 'aria-label': title },
    h('header', null, h('h2', null, title), S.data ? h('button.btn.quiet', { onclick: () => { s.hidden = true; } }, 'Close') : null),
    h('div.body', null, body)));
  s.hidden = false;
  s.onclick = e => { if (e.target === s && S.data) s.hidden = true; };
}

export function openProjects(first) {
  const st = S.studio;
  const name = h('input', { type: 'text', placeholder: 'Name, e.g. “Hallway phone dock”', id: 'new-name' });
  const recipe = h('select.field', { id: 'new-recipe', style: 'width:100%;padding:8px' }, st.recipes.map(r => h('option', { value: r.id }, `${r.title} — ${r.summary}`)));
  const brief = h('textarea', { rows: 3, placeholder: 'What is it for? (optional; you can write this later)' });
  const file = h('input', { type: 'file', accept: '.formproj,.zip', hidden: true, onchange: async e => {
    const f = e.target.files[0]; if (!f) return;
    try { const r = await api('/import', await f.arrayBuffer(), true); S.studio = await api('/studio'); $('sheet').hidden = true; await A.open(r.id); toast('Project restored', 'Artifacts were re-verified against this machine’s kernel and presets.'); }
    catch (err) { toast(err.message, err.hint, true); }
  } });
  sheet(first ? 'Start a project' : 'Projects', h('div.cols', null,
    h('div', null, h('div.cap', { style: 'margin-bottom:8px' }, 'New'), name, h('div', { style: 'height:8px' }), recipe, h('div', { style: 'height:8px' }), brief,
      h('div.btns', null, h('button.btn.primary', { id: 'create', onclick: async () => {
        try { const r = await api('/projects', { name: name.value || recipe.selectedOptions[0].textContent.split(' — ')[0], recipe: recipe.value, brief: brief.value }); S.studio = await api('/studio'); $('sheet').hidden = true; S.stage = 'brief'; await A.open(r.id); A.track(r.job); }
        catch (e) { toast(e.message, e.hint, true); }
      } }, 'Create'), h('label.btn.quiet', null, 'Restore .formproj', file)),
      h('p.fine', { style: 'margin-top:12px' }, 'Inputs FORM works from: a written brief, dimensions you measure, and reference photos with a marked scale. It does not reconstruct geometry from photos or scans.')),
    h('div.plist', null, h('div.cap', { style: 'margin-bottom:4px' }, 'Open'),
      st.projects.length ? st.projects.map(p => p.error ? h('div.err', null, h('b', null, p.id), p.error) :
        h('button', { onclick: async () => { $('sheet').hidden = true; await A.open(p.id); } },
          h('span', null, h('b', null, p.name), h('small', null, `${st.recipes.find(r => r.id === p.recipe)?.title} · ${p.revisions} revision${p.revisions > 1 ? 's' : ''} · ${ago(p.updated)}`)),
          h('span.rev', null, pad(p.head)))) : h('p.fine', null, 'No projects yet.'))), true);
}

export function openAlternatives() {
  const d = S.data, v = head().values;
  const cand = d.recipe.params.filter(p => p.group !== 'brief');
  const pick = (id, def) => h('select.field', { id, style: 'width:100%;padding:7px' }, cand.map(p => h('option', { value: p.key, selected: p.key === def }, p.label)));
  const defaults = d.recipe.id === 'dock' ? ['depth', 'lean'] : [cand[0].key, cand[1]?.key];
  const a1 = pick('ax1', defaults[0]), a2 = pick('ax2', defaults[1]);
  const span = key => { const p = spec(key), x = v[key]; const dlt = Math.max(p.step * 2, Math.abs(x) * 0.18); const r = n => Math.round(Math.min(p.max, Math.max(p.min, n)) / p.step) * p.step; return [r(x - dlt), r(x), r(x + dlt)].map(n => trim(n, 3)).join(', '); };
  const v1 = h('input', { type: 'text', value: span(a1.value) }), v2 = h('input', { type: 'text', value: span(a2.value) });
  a1.onchange = () => { v1.value = span(a1.value); }; a2.onchange = () => { v2.value = span(a2.value); };
  const W = { material: 1, stability: 2, fit: 0, footprint: 1 };
  const names = { material: 'Less material', stability: 'Harder to tip', fit: 'Fit yield', footprint: 'Smaller footprint' };
  const wrows = Object.keys(W).map(k => h('div.row', null, h('span.k', null, names[k]), h('input', { type: 'range', min: 0, max: 3, step: 1, value: W[k], style: 'width:120px', oninput: e => { W[k] = +e.target.value; } })));
  const out = h('div', { id: 'alts', style: 'margin-top:16px' });
  const go = h('button.btn.primary', { id: 'build-alts', onclick: async () => {
    go.disabled = true; go.textContent = 'Building candidates…';
    const parse = t => t.split(/[,\s]+/).map(Number).filter(Number.isFinite);
    const axes = [{ key: a1.value, values: parse(v1.value) }];
    if (a2.value !== a1.value) axes.push({ key: a2.value, values: parse(v2.value) });
    try {
      const t0 = performance.now();
      const r = await P('/alternatives', { axes, weights: W });
      const ok = r.rows.filter(x => x.ok);
      const frame = Math.max(...ok.map(x => Math.hypot(x.bbox[1][0] - x.bbox[0][0], x.bbox[1][1] - x.bbox[0][1], x.bbox[1][2] - x.bbox[0][2]) / 2), 1);
      out.replaceChildren(
        h('div.cap', { style: 'margin-bottom:8px;display:flex;justify-content:space-between' }, h('span', null, `${ok.length} built · ${r.rows.length - ok.length} infeasible`), h('span', null, `${((performance.now() - t0) / 1000).toFixed(1)} s`)),
        h('div.cards', null, r.rows.map(x => {
          const title = r.axes.map(a => `${a.label.split(' ')[0]} ${trim(x.changes[a.key])}`).join(' · ');
          if (!x.ok) return h('div.card.bad', null, h('div.t', null, title), h('div.fine', { style: 'margin-top:6px' }, x.error.message));
          const m = x.metrics;
          return h('button.card', { class: x.best ? 'best' : '', onclick: () => { $('sheet').hidden = true; A.stage('shape'); A.loadDraft({ ...v, ...x.changes }); } },
            h('div.flags', null, x.best ? h('span.tag.interface', null, 'best score') : null, x.is_current ? h('span.tag', null, 'current') : null, x.pareto && !x.best ? h('span.tag', { title: 'No other candidate is better on every weighted objective' }, 'frontier') : null),
            h('img', { src: thumbnail(x.mesh, 220, frame), alt: title }), h('div.t', null, title),
            h('div.m', null, h('span', null, 'Material'), h('span.num', null, fmt(m.material, 1) + ' cm³')),
            m.stability != null ? h('div.m', null, h('span', null, 'Tip force'), h('span.num', null, fmt(m.stability) + ' N')) : null,
            m.fit != null ? h('div.m', null, h('span', null, 'Fit yield'), h('span.num', null, fmt(m.fit, 0) + ' %')) : null,
            h('div.m', null, h('span', null, 'Footprint'), h('span.num', null, fmt(m.footprint, 0) + ' cm²')),
            h('div.bar2', { title: 'Weighted score' }, h('i', { style: `width:${x.score * 100}%;background:var(--ink)` })));
        })),
        h('p.fine', { style: 'margin-top:10px' }, r.note + ' Click a candidate to load it as a draft.'));
    } catch (e) { out.replaceChildren(h('div.err', null, h('b', null, e.message), e.hint || '')); }
    go.disabled = false; go.textContent = 'Build candidates';
  } }, 'Build candidates');
  sheet('Compare alternatives', [
    h('div.cols', null,
      h('div', null, h('div.cap', { style: 'margin-bottom:8px' }, 'Vary'), a1, h('div', { style: 'height:6px' }), v1, h('div', { style: 'height:12px' }), a2, h('div', { style: 'height:6px' }), v2,
        h('p.fine', { style: 'margin-top:8px' }, 'Up to five values per parameter, comma-separated. Interfaces stay as committed unless you vary them.')),
      h('div', null, h('div.cap', { style: 'margin-bottom:8px' }, 'Weight the objectives'), wrows, h('div.btns', null, go))),
    out], true);
}

// ── reference photo: scale, then measure ───────────────────
async function attachPhoto(e) {
  const f = e.target.files[0]; if (!f) return;
  const data = await new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f); });
  try { await P('/reference', { data }); await A.refresh(); toast('Photo attached', 'Mark a known length in it to measure from it.'); }
  catch (err) { toast(err.message, err.hint, true); }
}

function openPhoto(ref) {
  const img = new Image();
  const cv = h('canvas');
  const st = { pts: [], scale: ref.scale_mm_per_px, list: [...(ref.measurements || [])], mode: ref.scale_mm_per_px ? 'measure' : 'scale' };
  const info = h('div', { style: 'margin-top:10px' });
  const draw = () => {
    const c = cv.getContext('2d'); c.drawImage(img, 0, 0);
    const lw = Math.max(2, img.width / 500);
    const seg = (a, b, col, text) => { c.strokeStyle = col; c.fillStyle = col; c.lineWidth = lw; c.beginPath(); c.moveTo(...a); c.lineTo(...b); c.stroke(); for (const p of [a, b]) { c.beginPath(); c.arc(p[0], p[1], lw * 2.2, 0, 7); c.fill(); } if (text) { c.font = `600 ${lw * 9}px ui-monospace, monospace`; c.fillText(text, (a[0] + b[0]) / 2 + lw * 4, (a[1] + b[1]) / 2 - lw * 4); } };
    for (const m of st.list) seg(m.a, m.b, '#3d4fb8', `${fmt(m.mm, 1)} mm`);
    if (st.pts.length === 2) seg(st.pts[0], st.pts[1], '#e5432a');
    else if (st.pts.length === 1) { c.fillStyle = '#e5432a'; c.beginPath(); c.arc(st.pts[0][0], st.pts[0][1], lw * 2.2, 0, 7); c.fill(); }
  };
  const save = () => P('/reference_update', { file: ref.file, scale_mm_per_px: st.scale, measurements: st.list });
  const ui = () => {
    const kids = [];
    const px = st.pts.length === 2 ? Math.hypot(st.pts[1][0] - st.pts[0][0], st.pts[1][1] - st.pts[0][1]) : 0;
    if (st.mode === 'scale') {
      const len = h('input', { type: 'number', step: 0.1, placeholder: 'mm', style: 'width:90px;padding:5px' });
      kids.push(h('div.note.amber', null, h('b', null, 'Step 1 — set the scale. '), 'Click both ends of something whose real length you know (a ruler, a card: 85.6 mm), lying in the same plane as the object.'),
        px ? h('div.btns', null, 'That length is', len, 'mm', h('button.btn', { onclick: () => { const mm = parseFloat(len.value); if (mm > 0) { st.scale = mm / px; st.pts = []; st.mode = 'measure'; save(); draw(); ui(); } } }, 'Set scale')) : null);
    } else {
      const mm = px * st.scale, sig = Math.max(0.6, mm * 0.02 + 2 * st.scale);
      const target = h('select.field', null, S.data.recipe.params.filter(p => p.unit === 'mm' && p.group === 'brief').map(p => h('option', { value: p.key }, p.label)));
      kids.push(h('div.note', null, h('b', null, 'Step 2 — measure. '), `Scale ${fmt(st.scale, 4)} mm per pixel. Click two points. Perspective and lens distortion are not corrected, so treat results as rough.`),
        px ? h('div.btns', null, h('b.num', null, `${fmt(mm, 1)} mm ±${fmt(sig, 1)}`), 'use as', target,
          h('button.btn', { onclick: () => { st.list.push({ a: st.pts[0], b: st.pts[1], mm, sigma: sig, param: target.value }); save(); $('sheet').hidden = true; A.stage('brief'); S.draft.prov[target.value] = { source: 'photo', sigma: +sig.toFixed(2) }; A.setParam(target.value, +mm.toFixed(1), true); A.render(); toast('Loaded as a draft', 'Marked “from photo”. Replace with a caliper measurement before trusting the fit.'); } }, 'Load as draft'),
          h('button.btn.quiet', { onclick: () => { st.list.push({ a: st.pts[0], b: st.pts[1], mm, sigma: sig }); st.pts = []; save(); draw(); ui(); } }, 'Keep on photo')) : null,
        h('div.btns', null, h('button.btn.quiet', { onclick: () => { st.mode = 'scale'; st.pts = []; draw(); ui(); } }, 'Reset scale')));
    }
    info.replaceChildren(...kids);
  };
  cv.addEventListener('click', e => {
    const r = cv.getBoundingClientRect(), p = [(e.clientX - r.left) / r.width * img.width, (e.clientY - r.top) / r.height * img.height];
    st.pts = st.pts.length >= 2 ? [p] : [...st.pts, p];
    draw(); ui();
  });
  img.onload = () => { cv.width = img.width; cv.height = img.height; draw(); ui(); };
  img.src = `/api/projects/${S.pid}/file/references/${ref.file}`;
  sheet('Measure from photo', [h('div.photo', null, cv), info], true);
}
