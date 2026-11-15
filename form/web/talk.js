// Talk: chat with Claude inside the bench, and a live feed of what any agent is doing to your designs.
import { S, A, h, api, toast, hasDraft, head } from './core.js';

const $ = id => document.getElementById(id);
const T = {
  open: localStorage.getItem('form.talk') !== '0',
  session: localStorage.getItem('form.session') || null,
  job: null, next: 0, items: [], busy: false, actTs: Date.now() / 1000, tools: {},
};
const VIEW = { iso: 'iso', sheet: 'iso', front: 'front', back: 'back', iso_back: 'back', left: 'side', right: 'side', top: 'top', bottom: 'under' };
const IDEAS = [
  'Design a case for a Raspberry Pi 5 with a snap-on lid',
  'Make me a Gridfinity bin 3×1 for screwdrivers',
  'The lightest wall hook that holds 5 kg safely',
  'A headphone stand that fits my desk edge',
];
const md = s => {
  const esc = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return esc
    .replace(/```[\s\S]*?```/g, m => `<pre>${m.slice(3, -3).replace(/^\w*\n/, '')}</pre>`)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/^\s*[-*] (.*)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, '<ul>$1</ul>')
    .replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
};

export function initTalk(viewer) {
  T.viewer = viewer;
  document.body.classList.toggle('talk-open', T.open);
  $('talk-toggle').onclick = () => {
    T.open = !T.open;
    localStorage.setItem('form.talk', T.open ? '1' : '0');
    document.body.classList.toggle('talk-open', T.open);
    window.dispatchEvent(new Event('resize'));
    renderTalk();
  };
  renderTalk();
  setInterval(pollActivity, 1200);
}

function chatInfo() { return (S.studio && S.studio.chat) || { available: false }; }

export function renderTalk() {
  const c = chatInfo();
  $('talk-toggle').classList.toggle('on', T.open);
  $('talk-toggle').replaceChildren(h('span.dot', { class: T.busy ? 'busy' : (c.available ? '' : 'off') }), 'Claude');
  if (!T.open) return;
  const last = T.items[T.items.length - 1];
  const waiting = T.busy && !(last && last.t === 'tool' && !T.tools[last.id]);
  const feed = h('div.feed', { id: 'feed' }, T.items.length ? T.items.map(item) : intro(c),
    waiting ? h('div.thinking', null, h('i'), h('i'), h('i'), ' ' + liveText()) : null);
  const input = h('textarea', {
    id: 'talk-in', rows: 3, disabled: !c.available,
    placeholder: c.available ? (S.pid ? `Ask about ${S.data?.project.name || 'this design'}, or describe something new…` : 'Describe what you want to print…') : c.note,
    onkeydown: e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value); } },
  });
  $('talk').replaceChildren(
    h('div.talk-head', null,
      h('span.cap', null, 'Claude'), h('span.fine', null, c.available ? `${c.model} · your account${c.web ? ' · web lookup on' : ''}` : 'unavailable'),
      h('span', { style: 'flex:1' }),
      T.busy ? h('button.btn.quiet', { onclick: stop }, 'Stop') : null,
      h('button.btn.quiet', { title: 'Start a fresh conversation', onclick: () => { T.session = null; localStorage.removeItem('form.session'); T.items = []; renderTalk(); } }, 'New chat')),
    feed,
    h('div.talk-foot', null, input,
      h('div.btns', null,
        h('span.fine', null, T.busy ? 'Claude is working. Watch the model change on the right.' : 'Enter to send · Shift+Enter for a new line'),
        h('button.btn', { disabled: T.busy || !c.available, onclick: () => send(input.value) }, T.busy ? 'Working…' : 'Send'))));
  feed.scrollTop = feed.scrollHeight;
}

function liveText() {
  const L = T.live;
  if (!L) return 'Claude is thinking…';
  if (L.kind === 'tool') return L.name === 'create_design' || L.name === 'update_design'
    ? `Writing design code… ${(L.chars / 1000).toFixed(1)} kB` : `Preparing ${L.name}…`;
  if (L.kind === 'text') return L.text ? L.text.slice(-140) : 'Writing…';
  if (L.kind === 'thinking') return `Thinking… (${(L.chars / 1000).toFixed(1)} kB)`;
  return 'Working…';
}

function intro(c) {
  return [h('div.intro', null,
    h('h3', null, 'Describe the part you need.'),
    h('p', null, 'Claude designs it in the CAD kernel. You watch it appear here, with checks, fit and a real slice. Nothing prints or uploads.'),
    c.available ? h('div.ideas', null, IDEAS.map(t => h('button.idea', { onclick: () => send(t) }, t))) : h('div.note.amber', null, c.note))];
}

function item(it) {
  if (it.t === 'user') return h('div.msg.you', null, it.text);
  if (it.t === 'text') { const d = h('div.msg.ai'); d.innerHTML = md(it.text); return d; }
  if (it.t === 'tool') {
    const r = T.tools[it.id];
    return h('div.toolrow', { class: r ? (r.ok ? 'ok' : 'bad') : 'run', title: (it.input || '') + (r && r.text ? '\n\n' + r.text : '') },
      h('span.k', null, it.name), h('span.v', null, it.input || ''),
      h('span.s', null, r ? (r.ok ? (r.image ? 'looked' : 'done') : 'error') : '…'));
  }
  if (it.t === 'act') return h('div.actrow', null, h('b', null, it.by), ' ', it.text);
  if (it.t === 'end') return h('div.endrow', null, `${it.turns || ''} steps · $${(it.cost_usd || 0).toFixed(2)}`);
  if (it.t === 'error') return h('div.note.red', null, it.text);
  return null;
}

async function send(text) {
  text = (text || '').trim();
  if (!text || T.busy) return;
  T.busy = true;
  T.items.push({ t: 'user', text });
  renderTalk();
  try {
    const r = await api('/chat', { message: text, project: S.pid, session: T.session });
    T.job = r.id; T.next = 1;
    poll();
  } catch (e) { T.busy = false; T.items.push({ t: 'error', text: e.message }); renderTalk(); }
}

async function poll() {
  if (!T.job) return;
  let r;
  try { r = await api(`/chat/${T.job}?from=${T.next}`); } catch { setTimeout(poll, 1500); return; }
  for (const ev of r.events) {
    if (ev.t === 'result') T.tools[ev.id] = ev; else if (ev.t !== 'start') T.items.push(ev);
  }
  T.next = r.next;
  T.live = r.live;
  if (r.session) { T.session = r.session; localStorage.setItem('form.session', r.session); }
  if (r.state === 'running') { renderTalk(); setTimeout(poll, 700); return; }
  T.busy = false; T.job = null;
  if (r.state === 'failed') T.items.push({ t: 'error', text: r.error || 'Claude stopped with an error.' });
  renderTalk();
  await A.reloadStudio();
  if (S.pid) await A.refresh(true);
}

async function stop() { if (T.job) await api(`/chat/${T.job}/stop`, {}); }

// ── follow agents: Claude here, Claude Code, Codex, CLI — anything that writes the activity log ──
async function pollActivity() {
  if (document.hidden) return;
  let r;
  try { r = await api('/activity?since=' + T.actTs); } catch { return; }
  for (const ev of r.events) {
    T.actTs = Math.max(T.actTs, ev.ts);
    if (ev.by === 'you') continue;
    if (!T.busy) { T.items.push({ t: 'act', by: ev.by, text: ev.text }); if (T.open) renderTalk(); }
    await follow(ev);
  }
}

async function follow(ev) {
  if (!ev.project) return;
  if (ev.project !== S.pid && ['commit', 'draft', 'look', 'search'].includes(ev.kind)) {
    await A.reloadStudio();
    await A.open(ev.project);
    toast(`Following ${ev.by}`, ev.text);
    return;
  }
  if (ev.project !== S.pid) return;
  const userDraft = hasDraft() && !S.draft.agent;
  if (ev.kind === 'commit') {
    if (S.draft.agent) A.discard();
    await A.refresh(true);
  } else if (ev.values && Object.keys(ev.values).length && !userDraft) {
    A.loadDraft({ ...head().values, ...ev.values });
    S.draft.agent = ev.by;
    S.draft.origin = 'agent:' + ev.by;
  } else if (userDraft && ev.values) {
    toast(`${ev.by} is trying a change`, 'Your own draft is kept; discard it to watch.');
  }
  if (ev.kind === 'look' && ev.view && VIEW[ev.view]) T.viewer.setView(VIEW[ev.view]);
  if (ev.kind === 'look' && ev.highlight) A.select(ev.highlight);
}
