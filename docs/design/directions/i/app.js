// Direction I, "Lightdesk, one bench". The demo design is a NEMA 17 motor mount built by the kernel for these
// mockups (tools/build.py). Where each number comes from is listed in IA.md, "What is real in the pictures".
const S = document.body.dataset.screen, nn = (i) => String(i).padStart(2, "0");
Object.assign(P, {
  enter: "M19 5v7a3 3 0 01-3 3H6M10 11l-4 4 4 4", extrude: "M5 14l7 3.5 7-3.5M5 14v4l7 3.5 7-3.5v-4M12 13V3M8.5 6.5L12 3l3.5 3.5",
  cut: "M4 9h16v10H4zM12 3v10M8.8 10l3.2 3 3.2-3", revolve: "M12 3v18M12 6c5 0 8 2 8 6s-3 6-8 6M17.5 15.5L15 18l2.8 2",
  fillet: "M5 20v-9a6 6 0 016-6h9", chamfer: "M5 20v-9l6-6h9", hole: "M12 4a8 8 0 100 16 8 8 0 000-16zM12 9a3 3 0 100 6 3 3 0 000-6z",
  pattern: "M5 5h5v5H5zM14 5h5v5h-5zM5 14h5v5H5zM14 14h5v5h-5z", shell: "M4 7.5l8-4.5 8 4.5v9L12 21l-8-4.5zM8 10l4-2.2 4 2.2v4.4l-4 2.2-4-2.2z",
  user: "M12 4a3.5 3.5 0 100 7 3.5 3.5 0 000-7zM5 20a7 7 0 0114 0", wand: "M5 19L16 8M14 6l4 4M18.5 2.5v3M17 4h3M6 4.5v3M4.5 6h3",
  bench: "M4 6h3M10 6h10M4 12h3M10 12h10M4 18h3M10 18h10", doc: "M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5",
  mill: "M9 3h6v7H9zM12 10v6M7 20h10M10 16h4", pulse: "M3 12h4l2-6 4 12 2.5-6H21", cube: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14", eye: "M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6zM12 9.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5z",
  orient: "M12 3v18M3 12h18M9.5 5.5L12 3l2.5 2.5M18.5 9.5L21 12l-2.5 2.5", dimension: "M4 7v10M20 7v10M4 12h16M7 9.5L4 12l3 2.5M17 9.5l3 2.5-3 2.5",
  gdt: "M3 8h18v8H3zM9 8v8M15 8v8", text: "M5 6h14M12 6v13", anchor: "M12 8v13M5 14a7 7 0 0014 0M12 3a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM8 12h8",
  x: "M6 6l12 12M18 6L6 18", fold: "M4 5h16v14H4zM9.5 5v14M14.5 10l-2.5 2 2.5 2", newc: "M4 5h16v11H10l-4 4v-4H4zM12 8v5M9.5 10.5h5",
  bolt: "M13 3L5 13.5h6L10 21l9-11h-6.5z", book: "M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3zM5 17a3 3 0 013-3h11", lock: "M7 11V8a5 5 0 0110 0v3M5 11h14v9H5z",
  star: "M12 4l2.4 5 5.6.8-4 3.9.9 5.5-4.9-2.6-4.9 2.6.9-5.5-4-3.9 5.6-.8z", trash: "M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13", key: "M14.5 4a5.5 5.5 0 00-5.3 7L3 17.2V21h4v-2.5h2.5V16H12l1.3-1.3A5.5 5.5 0 1014.5 4zM16 8.5h.01",
  palette: "M12 3a9 9 0 100 18c1.5 0 2-1 2-2s-.6-1.6-.6-2.5c0-1 .8-1.5 1.8-1.5H18a3 3 0 003-3c0-5-4-9-9-9zM7.5 12h.01M9.5 8h.01M14.5 7.5h.01",
  box3: "M4 8l8-4 8 4v8l-8 4-8-4zM4 8l8 4 8-4", info: "M12 3a9 9 0 100 18 9 9 0 000-18zM12 11v6M12 7.5h.01", tri: "M12 5l8 14H4z",
});
const D = {
  name: "Motor mount", rev: "r07", state: "Unreleased",
  dims: ["56.0", "52.0", "62.0"], vol: (META.stages[7].vol_mm3 / 1000).toFixed(2), mass: (META.stages[7].vol_mm3 / 1000 * 2.70).toFixed(1),
  feats: [["Base plate", "extrude", "56 × 52 × 6", "agent"], ["Upright", "extrude", "62 tall", "agent"], ["Gussets", "rib ×2", "5.0", "agent"],
    ["Pilot bore", "hole", "Ø22.0", "agent"], ["Motor screws", "hole ×4", "Ø3.4", "agent"], ["Base slots", "cut ×2", "5.5 × 16", "you"],
    ["Root fillet", "fillet", "r 4.0", "refine"], ["Edge chamfers", "chamfer", "0.8", "you"]],
  modes: [["Design", "8 features"], ["Check", "1 to review", "warn"], ["Make", "2 routes ready"], ["Document", "1 sheet"]],
  agent: "Claude · Fable 5.2", printer: "Bambu Lab A1 mini · 0.4",
};
const WHO = { agent: "spark", you: "user", refine: "wand" };
const ev = (t) => `<span class="ev">${t}</span>`;

// ---- projection: a point of the model, in mm, to the picture (the camera the render used) ----
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const pj = (name, k) => { const p = PROJ[name]; return (x, y, z) => { const d = [x - p.T[0], y - p.T[1], z - p.T[2]];
  return [(p.w / 2 + dot(d, p.right) * p.pxmm) * k, (p.h / 2 - dot(d, p.up) * p.pxmm) * k]; }; };
const pl = (f, pts) => "M" + pts.map((q) => f(...q).map((v) => v.toFixed(1)).join(" ")).join("L");
const img = (n, w, cls = "") => `<img class="${cls}" src="assets/${n}.webp" width="${w}">`;
// A picture of the part with whatever is drawn over it. cx, cy: where the camera's target lands on the screen.
function shot(name, k, cx, cy, layers) { const p = PROJ[name], w = p.w * k, h = p.h * k;
  return `<div class="shot" style="left:${cx - w / 2}px;top:${cy - h / 2}px;width:${w}px;height:${h}px">${layers(pj(name, k), w, h)}</div>`; }
const edges = (k, w, h) => { const p = PROJ.part, s = p.pxmm * k;
  return `<svg class="edges" width="${w}" height="${h}"><g transform="translate(${w / 2} ${h / 2 - 2 * p.up[2] * s}) scale(${s})"><path d="${HLR.iso.vis}"/></g></svg>`; };
const dimline = (f, a, b, t, cls = "") => { const [x1, y1] = f(...a), [x2, y2] = f(...b);
  return [`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/><circle cx="${x1}" cy="${y1}" r="3"/><circle cx="${x2}" cy="${y2}" r="3"/>`,
    `<span class="dimtag ${cls}" style="left:${(x1 + x2) / 2}px;top:${(y1 + y2) / 2}px">${t}</span>`]; };
function overall(f, w, h) { const o = 9, L = [dimline(f, [-28 - o, -o, 0], [-28 - o, -o, 62], "62.0"), dimline(f, [-28, -o, 0], [28, -o, 0], "56.0"), dimline(f, [28 + o, 0, 0], [28 + o, 52, 0], "52.0")];
  return `<svg class="dl" width="${w}" height="${h}">${L.map((l) => l[0]).join("")}</svg>${L.map((l) => l[1]).join("")}`; }

// ---- chrome ----
const topbar = (mode, o = {}) => `
  <div class="cap tl glass">${MARK(18)}<b>${o.name || D.name}</b><span class="num rev">${o.rev || D.rev}</span><span class="tag">${D.state}</span>${I("down", 14)}</div>
  <nav class="modes glass">${(o.modes || D.modes).map(([n, sub, st], i) => `<div class="seg ${i === mode ? "on" : ""}"><b>${n}</b><span class="${i === mode ? "" : st || ""}">${sub}</span></div>`).join("")}</nav>
  <div class="cap tr glass">${o.busy ? `<span class="printer"><i class="live"></i>${o.busy}</span><i class="sep"></i>` : ""}${o.printer ? `<span class="printer">${I("printer", 15)}${D.printer}</span><i class="sep"></i>` : ""}<span class="btn">${I("search", 16)}<kbd>⌘K</kbd></span><span class="btn ${o.bench ? "on" : ""}">${I("bench", 16)}<kbd>⌘B</kbd></span><span class="btn">${I("gear", 16)}</span></div>`;
const TOOLS = { all: ["cursor", "scan", "scissors", "pin"], 0: ["sketch", "extrude", "cut", "revolve", "", "fillet", "chamfer", "hole", "pattern", "shell"],
  1: ["anchor", "layers", "boxes", "eye", "play"], 2: ["orient", "grid", "layers", "mill", "play"], 3: ["dimension", "gdt", "text", "search", "camera"] };
const dock = (mode, on, x) => `<div class="dock glass" ${x != null ? `style="left:${x}px"` : ""}>${[...TOOLS.all, "", ...TOOLS[mode]].map((t) => t ? `<span class="${t === on ? "on" : ""}">${I(t, 18)}</span>` : "<hr>").join("")}</div>`;
const cube = () => `<div class="cube glass"><svg width="44" height="44" viewBox="0 0 44 44" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-width="1.2" style="color:var(--ink2)">
  <path d="M22 4l15 8.5v17L22 38 7 29.5v-17z" fill="var(--glass2)"/><path d="M7 12.5l15 8.5 15-8.5M22 21v17" /><path d="M22 4l15 8.5-15 8.5-15-8.5z" fill="color-mix(in srgb, var(--accent) 22%, transparent)" stroke="var(--accent)"/></svg></div>
  <div class="shade glass"><i></i>Studio${I("down", 12)}</div>`;
const readout = (note) => `<p class="readout num">${D.dims.join(" × ")} mm<i>·</i>${D.vol} cm³<i>·</i>${D.mass} g<em>${note || `6061-T6 at 2.70 g/cm³`}${ev("computed")}</em></p>`;
const hint = (h) => `<p class="hint" style="text-align:right">${h}</p>`;
const prompt = (ph, o = {}) => `<div class="prompt">${o.scope ? `<span class="scope">${o.scope}</span>` : `<span class="gt">›</span>`}<i class="caret"></i><p class="${o.typed ? "typed" : ""}">${ph}</p></div>`;
const well = (ph, o = {}) => `<div class="well ${o.lit ? "lit" : ""}">${prompt(ph, o)}<footer>${I("clip", 16)}<span class="agent">${I("spark", 15)}${D.agent}${I("down", 12)}</span><span class="send">${I(o.stop ? "stop" : "enter", 15, 2)}</span></footer></div>`;
const convo = (title, body, ph, o = {}) => `<aside class="convo glass"><header>${o.live ? `<i class="live"></i>` : `<i class="dot ok"></i>`}<b>${title}</b>${I("newc", 16)}${I("fold", 16)}</header>
  <div class="msgs ${o.end ? "end" : ""}">${body}</div><div class="foot">${well(ph, o)}</div></aside>`;
const sources = (list) => `<div class="card"><h4>Sources<em>${list.length} · from the tool log</em></h4><div class="src">${list.map(([t, how], i) => `<div><b>${i + 1}</b><span>${t}</span>${ev(how)}</div>`).join("")}</div></div>`;
const revcard = (rev, by, what, acts = ["Compare", "Go back"]) => `<div class="card rev"><h4><b>${rev}</b>${by}</h4><p>${what}</p><div class="acts">${acts.map((a) => `<span class="pill quiet">${a}</span>`).join("")}</div></div>`;
const pipe = (txt) => `<div class="pipe">${["ok", "ok", "ok", "ok", "none"].map((s) => `<i class="dot ${s}"></i>`).join("")}<span class="num">${txt}</span><em>Auto</em><i class="switch"></i></div>`;
// One row grammar for every chapter of the bench: number, name, who or state, the value, how it is known.
const frow = ([name, kind, val, who], i, st = "", extra = "") => `<div class="ln ${st}"><span class="no">${nn(i + 1)}</span><span class="gl">${st === "done" ? I("check", 13, 2.2) : st === "now" ? I("play", 10, 2.4) : ""}</span><b>${name}</b>${extra}<span class="who">${I(WHO[who], 13)}</span><span class="val">${val}</span></div>`;
const srow = (dotc, name, val, e, st = "") => `<div class="ln ${st}"><span class="no"></span><span class="gl"><i class="dot ${dotc}"></i></span><b>${name}</b>${val ? `<span class="val">${val}</span>` : ""}${e.startsWith("<") ? e : ev(e)}</div>`;
const room = (px, py, o = {}) => `<div class="room ${o.dim ? "dimmed" : ""}" style="--px:${px}px;--py:${py}px"></div>${o.pool === false ? "" : `<div class="pool" style="left:${px - 320}px;top:${py - 30}px"></div>`}`;
const put = (html) => document.body.insertAdjacentHTML("beforeend", html.replace(/Ø/g, `<span class="dia">Ø</span>`).replace(/⌀/g, `<tspan font-family="Geist" font-weight="500">Ø</tspan>`) + `<div class="grain"></div>`);
const tree = (o = {}) => { const n = o.count || 8, step = o.step;
  return `<header><b>Tree</b><span class="num">${o.n || 8}</span>${step ? `<em class="num" style="color:var(--accent);display:flex;gap:9px;align-items:center;letter-spacing:.1em"><i class="live"></i>${step} OF 8</em>` : `<div class="tabs"><span class="${o.code ? "" : "on"}">Values</span><span class="${o.code ? "on" : ""}">Source</span></div>`}</header>
  <div class="rows"><i class="rail" style="height:${n * 32 - 8}px"></i>${step ? `<i class="rail lit" style="height:${(step - 1) * 32 + 12}px"></i>` : ""}
  ${D.feats.slice(0, n).map((f, i) => (o.bar === i ? `<div class="rb"><i></i><em>rolled back to ${nn(i)}</em></div>` : "") + frow(f, i, step ? (i + 1 < step ? "done" : i + 1 === step ? "now" : "todo") : o.bar != null && i >= o.bar ? "todo" : o.sel === i ? "sel" : o.off === i ? "off" : "")).join("")}${o.after || ""}</div>`; };
