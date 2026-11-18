// The hero: Form Studio's workspace recreated 1:1 (Workspace.qml, Talk.qml, Pipeline.qml, the five stages,
// PrintSimBar.qml), driven by the sample project's real data, playing a short story the visitor can take over.
import { siteData, loadGLB, toolpath, fmtDur, INKS, reducedMotion } from "./data.js";
import { Viewport } from "./scene.js";

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const brandName = (s) => String(s).replace(/\bFORM\b/g, "Form Studio");
const ev = (k) => ({ computed: "t-datum", specified: "t-datum", heuristic: "t-ink", model: "t-amber", modelled: "t-amber", assumed: "t-amber", simulated: "t-amber", measured: "t-pass", PASS: "t-pass", WARN: "t-amber", FAIL: "t-signal" })[k] || "t-ink";
const icon = (cp) => `<span class="i" aria-hidden="true">&#x${cp};</span>`;
const I = { check: "e06c", spin: "e10a", cube: "e524", eye: "e0ba", commit: "e0e3", chevR: "e06f", chevD: "e06d", arrowR: "e049", play: "e13c", pause: "e12e", layers: "e529", dl: "e0b2", shield: "e1ff", back: "e048", skip: "e160", repeat: "e146", compare: "e359", ghost: "e20e", expand: "e21a", pencil: "e4f1", grid: "e0e9" };

export async function initHero() {
  const app = $("#app"), frame = $("#app-frame");
  const d = (await siteData()).dock;
  const compact = { matches: false };   // the window is always drawn at its real 1440 x 880 layout, then scaled

  // ---------- scale the 1440 x 880 window to the column, like a picture of the real window ----------
  const fit = () => {
    const s = Math.min(1, frame.clientWidth / 1440);
    frame.style.setProperty("--s", s.toFixed(4));
  };
  new ResizeObserver(fit).observe(frame); fit();

  // ---------- 3D ----------
  const vp = new Viewport($("#gl"), $("#labels"), { onInteract: () => story.takeover(), touchPanY: true });
  const parts = await loadGLB("assets/data/dock.glb");
  vp.setPart(parts, d);
  vp.view("iso", false);

  // ---------- state ----------
  const S = { built: false, checked: false, sliced: false, stage: "prove", map: false, sim: false, simP: 127, playing: false, speed: 64, hidden: new Set(), acks: [false, false], dims: true, device: true };
  const checks = d.checks;
  const warns = checks.filter((c) => c.status === "WARN"), passes = checks.filter((c) => c.status === "PASS");
  const evCount = checks.reduce((m, c) => ((m[c.evidence] = (m[c.evidence] || 0) + 1), m), {});
  const sliceH = fmtDur(d.slice_meta.time_s);
  const hm = (s) => { const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h ? `${h} h ${m} min` : `${m} min`; };
  const fitY = Math.round(d.fit.yield * 100);

  // ---------- stage tabs ----------
  const STAGES = [
    ["brief", "Brief", () => (S.built ? "0/4 measured" : "4 assumed"), ""],
    ["shape", "Shape", () => (S.built ? `${d.features.length} features` : "—"), ""],
    ["fit", "Fit", () => (S.built ? `${fitY}% modelled` : "—"), "am"],
    ["prove", "Prove", () => (S.checked ? `${warns.length} to review` : "—"), "am"],
    ["release", "Release", () => (S.sliced ? "Ready" : "—"), ""],
  ];
  const tabs = $("#tabs");
  tabs.innerHTML = STAGES.map(([id, nm], i) => `<button class="tab" role="tab" id="tab-${id}" aria-controls="panel" data-stage="${id}" aria-selected="false" tabindex="-1"><span class="t"><em>0${i + 1}</em>${nm}</span><span class="u"></span></button>`).join("");
  const renderTabs = () => STAGES.forEach(([id, , sub, tone]) => {
    const b = $("#tab-" + id), u = b.querySelector(".u"), txt = sub();
    u.textContent = txt; u.className = "u " + (txt !== "—" && tone ? tone : "");
    b.setAttribute("aria-selected", String(S.stage === id)); b.tabIndex = S.stage === id ? 0 : -1;
  });
  tabs.addEventListener("click", (e) => { const b = e.target.closest(".tab"); if (b) { story.takeover(); setStage(b.dataset.stage); } });
  tabs.addEventListener("keydown", (e) => {
    const i = STAGES.findIndex(([id]) => id === S.stage);
    const j = e.key === "ArrowRight" ? (i + 1) % 5 : e.key === "ArrowLeft" ? (i + 4) % 5 : -1;
    if (j >= 0) { e.preventDefault(); story.takeover(); setStage(STAGES[j][0]); $("#tab-" + STAGES[j][0]).focus(); }
  });

  // ---------- panels ----------
  const wrap = $("#panel-wrap");
  const tag = (t, cls) => `<span class="tag ${cls || ev(t)}">${esc(t)}</span>`;
  const note = (txt, c) => `<div class="note" style="--nc:var(--${c || "amber"})">${esc(txt)}</div>`;
  const bell = (w, h, f) => {
    const [lo, hi] = f.window, mu = f.expected_gap, sd = f.sd;
    const x0 = mu - 3.6 * sd, x1 = mu + 3.6 * sd, X = (x) => ((x - x0) / (x1 - x0)) * w, pdf = (x) => Math.exp(-0.5 * ((x - mu) / sd) ** 2);
    const Y = (x) => h - 18 - pdf(x) * (h - 30);
    const path = (a, b) => { let s = `M${X(a).toFixed(1)},${h - 18}`; for (let i = 0; i <= 60; i++) { const x = a + ((b - a) * i) / 60; s += `L${X(x).toFixed(1)},${Y(x).toFixed(1)}`; } return s + `L${X(b).toFixed(1)},${h - 18}Z`; };
    return `<svg viewBox="0 0 ${w} ${h}" width="100%" aria-hidden="true">
      <path d="${path(x0, lo)}" fill="rgba(255,111,81,.35)"/><path d="${path(lo, hi)}" fill="rgba(134,217,173,.22)"/><path d="${path(hi, x1)}" fill="rgba(233,184,96,.32)"/>
      <rect x="${X(lo)}" y="6" width="${X(hi) - X(lo)}" height="${h - 24}" fill="rgba(185,232,215,.04)"/>
      <line x1="${X(lo)}" x2="${X(lo)}" y1="6" y2="${h - 18}" stroke="#b9e8d7" stroke-dasharray="3 3" stroke-opacity=".7"/><line x1="${X(hi)}" x2="${X(hi)}" y1="6" y2="${h - 18}" stroke="#b9e8d7" stroke-dasharray="3 3" stroke-opacity=".7"/>
      <path d="${path(x0, x1).replace(/Z$/, "")}" fill="none" stroke="#e8edeb" stroke-width="1.4"/>
      <line x1="${X(mu)}" x2="${X(mu)}" y1="${Y(mu)}" y2="${h - 18}" stroke="#e8edeb" stroke-width="1.2"/>
      <line x1="0" x2="${w}" y1="${h - 18}" y2="${h - 18}" stroke="rgba(255,255,255,.2)"/>
      <text x="${X(lo)}" y="${h - 4}" fill="#b9e8d7" font-family="Geist Mono" font-size="10" text-anchor="middle">${lo.toFixed(2)}</text>
      <text x="${X(hi)}" y="${h - 4}" fill="#b9e8d7" font-family="Geist Mono" font-size="10" text-anchor="middle">${hi.toFixed(2)}</text></svg>`;
  };
  const P = {
    brief: () => {
      const keys = ["device_width", "device_thickness", "device_height", "device_mass"];
      return `${note("Anything not measured is carried as an assumption, all the way to release.")}
      <div class="sec"><div class="bigq"><b>0/4</b><span>dimensions of the object measured<br><small class="small">4 assumed</small></span></div><div class="segbars"><i></i><i></i><i></i><i></i></div></div>
      <div class="sec"><span class="cap">Intent</span><div class="intent">${esc(d.brief)}</div></div>
      <div class="sec"><div class="sec-h"><span class="cap">Known about the object</span><small>value · source · ±1σ</small></div>
      ${keys.map((k) => { const p = d.params[k], v = d.values[k], pc = ((v - p.min) / (p.max - p.min)) * 100; return `<div class="prm"><div class="r"><b>${esc(p.label)}</b><span class="box">${v}<small>${esc(p.unit)}</small></span></div><div class="trk"><i style="left:${pc.toFixed(1)}%"></i></div><div class="dc">${esc(p.doc)}</div><div class="r" style="justify-content:flex-start;gap:8px">${tag("Assumed")}<span class="small">±${k === "device_mass" ? "0.3 g" : "0.3 mm"}</span></div></div>`; }).join("")}</div>`;
    },
    shape: () => S.built ? `${note(`${d.features.length} features in build order. Select one here or on the model to change it.`, "ink3")}
      <div class="sec"><div class="sec-h"><span class="cap">Features</span><small>build order</small></div>
      <div>${d.features.map((f, i) => `<div class="feat" data-f="${f.id}" style="animation-delay:${i * 45}ms"><i></i><span class="nm">${esc(f.label)}</span><span class="tag ${f.role === "interface" ? "ifc" : ""}">${esc(f.role)}</span><span class="i chev" aria-hidden="true">&#x${I.chevR};</span><span class="dc">${esc(f.doc)}</span></div>`).join("")}</div></div>
      <div class="sec"><span class="cap">Explore</span><p style="font-size:13px;line-height:1.55">Build a grid of real candidates and rank them against objectives you weight.</p><div class="pbtns"><span class="pbtn">${icon(I.compare)}Compare alternatives</span><span class="pbtn quiet">${icon(I.grid)}Variants</span></div></div>`
      : `<p class="empty-insp">Nothing is built yet. Describe the part in the conversation.</p>`,
    fit: () => {
      const f = d.fit;
      return `${note(`${fitY}% of prints are modelled to fit, from what is known today.`)}
      <div class="sec"><h4 style="margin:0;font-size:20px;font-weight:620;letter-spacing:-.01em">${esc(f.label)}</h4><p style="font-size:13px;color:var(--ink2)">Will it slide in without rattling? A model built from stated inputs, shown with where each came from.</p></div>
      <div class="fitbig"><b>${fitY}%</b><span>modelled chance the gap lands in your window</span><span></span>${tag("Modelled")}</div>
      <div>${bell(360, 120, f)}</div>
      <div class="fit3"><div><b style="color:var(--signal)">${Math.round(f.p_tight * 100)}%</b><span>too tight</span></div><div><b>${f.expected_gap.toFixed(2)} mm</b><span>expected gap ±${(2 * f.sd).toFixed(2)}</span></div><div><b style="color:var(--amber)">${Math.round(f.p_loose * 100)}%</b><span>too loose</span></div></div>
      <div class="sec"><span class="cap">Where the uncertainty comes from</span>
      <div class="src"><div><b>${esc(f.mating_label)}</b><span>${f.mating.toFixed(2)} mm ±${f.sources.mating.sigma.toFixed(2)} · ${Math.round(f.sources.mating.share * 100)}% of variance</span></div>${tag("Assumed")}</div>
      <div class="src"><div><b>Printed pocket</b><span>${f.cavity_nominal.toFixed(2)} mm +${f.sources.printer.bias.toFixed(3)} bias ±${f.sources.printer.sigma.toFixed(2)} · ${Math.round(f.sources.printer.share * 100)}% of variance</span></div>${tag("Assumed")}</div></div>
      <div class="sec"><div class="sec-h"><span class="cap">Most useful next step</span><small>by modelled yield gained</small></div>
      ${d.next_actions.slice(0, 2).map((a, i) => `<div class="nx"><em>0${i + 1}</em><b>${esc(a.do)}</b><p>${esc(a.why)} ${fitY}% → ${esc(a.yield_after)}, ${esc(a.cost)}.</p></div>`).join("")}</div>`;
    },
    prove: () => {
      if (!S.checked) return `<p class="empty-insp">Checks run when the solid is built.</p>`;
      return `${note(`${warns.length} checks of ${checks.length} need a look for r04. None failed.`)}
      <div class="sec"><div class="big3"><div class="p"><b data-count="${passes.length}">${passes.length}</b><span class="cap">Pass</span></div><div class="w"><b data-count="${warns.length}">${warns.length}</b><span class="cap">To review</span></div><div class="f"><b>0</b><span class="cap">Failed</span></div></div>
      <div class="bars"><i style="flex:${passes.length};background:var(--pass)"></i><i style="flex:${warns.length};background:var(--amber)"></i></div>
      <p class="small">Checks for r04 · ${evCount.computed} computed · ${evCount.heuristic} heuristic · ${evCount.model} model. Each says how it is known.</p></div>
      <div class="sec"><span class="cap">To review</span>${warns.map((c, i) => `<div class="chk" style="animation-delay:${i * 45}ms">${tag("Warn", "t-amber")}<span class="nm">${esc(c.label)}</span><span class="v">${esc(c.value)}</span><span class="tg2">${tag(c.evidence)}</span><span class="dt">${esc(brandName(c.detail))}</span></div>`).join("")}</div>
      <div><div class="fold"><span class="cap">${icon(I.chevD)}Passed</span><small>${passes.length} · ${evCount.computed} computed · ${evCount.heuristic} heuristic</small></div>
      ${passes.map((c, i) => `<div class="chk mini" style="animation-delay:${80 + i * 30}ms">${icon(I.check)}<span class="nm">${esc(c.label)}</span><span class="v">${esc(c.value)}</span></div>`).join("")}</div>
      ${S.sliced ? `<div class="sec"><div class="sec-h"><span class="cap">Slice of r04</span>${tag("Simulated")}</div>
      <div class="k3"><div><b>${hm(d.slice_meta.time_s)}</b><span>estimated print time</span></div><div><b>${d.slice_meta.filament_g.toFixed(1)} g</b><span>PLA</span></div><div><b>${d.toolpath.z.length}</b><span>layers to ${d.toolpath.z.at(-1).toFixed(1)} mm</span></div></div>
      <div class="pbtns"><button class="pbtn" type="button" id="watch">${icon(I.play)}Watch it print</button><span class="pbtn quiet">${icon(I.dl)}Save sliced 3MF…</span></div>
      <p class="small">A slice shows the toolpaths Bambu Studio would send with these presets. It is not a print: adhesion, warping and fit are only known after printing.</p></div>` : ""}`;
    },
    release: () => {
      if (!S.sliced) return `<p class="empty-insp">The gate opens when the slice is current.</p>`;
      const ok = S.acks.every(Boolean);
      return `${note(`r04 is ready to approve. ${warns.length} warnings to acknowledge first.`, "ink3")}
      <div class="gate"><span class="sh">${icon(I.shield)}</span><div><h4>Ready, with warnings</h4><p>Gate for r04 · ${esc(d.gate.evidence.replace(/; /g, " · "))}</p></div></div>
      <p class="small">A release is a frozen copy of files whose hashes match the revision they claim to be. Acknowledge each warning to release with it.</p>
      <div>${warns.map((c, i) => `<button type="button" class="ack ${S.acks[i] ? "on" : ""}" data-ack="${i}" aria-pressed="${S.acks[i]}" style="text-align:left;width:100%"><span class="bx">${icon(I.check)}</span><b>${esc(c.label)}</b><span>${esc(c.value)}</span></button>`).join("")}</div>
      <div class="fieldx">Release note (optional)</div>
      <div class="pbtns"><button class="pbtn primary" type="button" id="approve" ${ok ? "" : "disabled"}>${icon(I.shield)}Approve and release r04</button></div>
      <p class="small" id="approve-note">${ok ? "Only a person can approve. Agents can do everything else." : ""}</p>
      <div class="sec"><div class="sec-h"><span class="cap">Revisions</span><small>${d.revisions.length} · head r04</small></div>
      ${[...d.revisions].reverse().map((r) => `<div class="revrow ${r.n === d.head ? "head" : ""}"><span class="n">r0${r.n}</span><b>${esc(r.summary || r.note)}</b><small>${new Date(r.ts * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</small><span>${r.n > 1 ? "from r0" + (r.n - 1) : "from the building block"}${r.origin.startsWith("proposal") ? " · by an agent" : ""}</span></div>`).join("")}</div>`;
    },
  };
  let panelEl = null;
  function renderPanel(anim = true) {
    const el = document.createElement("div");
    el.className = "panel" + (anim && !reducedMotion() ? " in" : ""); el.id = "panel"; el.setAttribute("role", "tabpanel");
    el.setAttribute("aria-labelledby", "tab-" + S.stage);
    el.innerHTML = (Object.prototype.hasOwnProperty.call(P, S.stage) ? P[S.stage] : P.shape)();
    if (panelEl) panelEl.remove();
    wrap.appendChild(el); panelEl = el;
    if (S.stage === "prove" && anim) countUp(el);
  }
  function countUp(el) {
    if (reducedMotion()) return;
    el.querySelectorAll("[data-count]").forEach((b) => {
      const n = +b.dataset.count, t0 = performance.now();
      const step = (now) => { const t = Math.min(1, (now - t0) / 700); b.textContent = Math.round(n * (1 - Math.pow(1 - t, 3))); if (t < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    });
  }
  function setStage(id, anim = true) {
    if (!Object.prototype.hasOwnProperty.call(P, id)) return;      // only the stages drawn above
    if (S.sim && id !== "prove") setSim(false);
    S.stage = id; renderTabs(); renderPanel(anim);
  }
  wrap.addEventListener("click", (e) => {
    const t = e.target.closest("#watch, [data-ack], #approve");
    if (!t) return;
    story.takeover();
    if (t.id === "watch") setSim(true, true);
    else if (t.dataset.ack) { S.acks[+t.dataset.ack] = !S.acks[+t.dataset.ack]; renderPanel(false); }
    else if (t.id === "approve") $("#approve-note").textContent = "In the app this freezes r04 and its files as a release. Here it does nothing: only a person approves, on their own computer.";
  });
  wrap.addEventListener("pointerover", (e) => { const f = e.target.closest(".feat"); vp.highlight(f ? f.dataset.f : null); if (f) wrap.querySelectorAll(".feat").forEach((x) => x.classList.toggle("on", x === f)); });
  wrap.addEventListener("pointerleave", () => { vp.highlight(null); wrap.querySelectorAll(".feat.on").forEach((x) => x.classList.remove("on")); });

  // ---------- pipeline strip ----------
  const NODES = [["params", "Parameters"], ["geometry", "Solid"], ["exports", "Exports"], ["checks", "Checks"], ["slice", "Slice"], ["release", "Release"]];
  const pipe = $("#pipe");
  pipe.innerHTML = NODES.map(([id, l]) => `<button type="button" class="pn" role="listitem" data-n="${id}" data-s="missing"><span class="l"><span class="d"></span>${l}</span><span class="s"></span></button>`).join("") + `<div class="auto"><span class="cap">Auto</span><span class="tgl"></span></div>`;
  const SAY = { params: "r04", geometry: `${d.faces} faces`, exports: ".step .stl .3mf", checks: `${passes.length} pass · ${warns.length} review`, slice: hm(d.slice_meta.time_s), release: "ready" };
  function node(id, s) {
    const b = pipe.querySelector(`[data-n="${id}"]`), was = b.dataset.s;
    b.dataset.s = s;
    const sEl = b.querySelector(".s");
    sEl.textContent = s === "current" ? SAY[id] : s === "running" ? "working…" : "not made";
    sEl.classList.toggle("word", s !== "current" || id === "release");
    if (was === "running" && s === "current" && !reducedMotion()) { const dEl = b.querySelector(".d"); dEl.classList.remove("settle"); void dEl.offsetWidth; dEl.classList.add("settle"); }
  }
  pipe.addEventListener("click", (e) => {
    const b = e.target.closest(".pn"); if (!b) return;
    story.takeover();
    setStage({ params: "shape", geometry: "shape", exports: "release", checks: "prove", slice: "prove", release: "release" }[b.dataset.n]);
  });

  // ---------- readout under the part ----------
  const sz = d.size;
  $("#dims-read").innerHTML = `${sz[0].toFixed(1)} <span class="x">×</span> ${sz[1].toFixed(1)} <span class="x">×</span> ${sz[2].toFixed(1)} mm <span class="x">·</span> ${d.volume_cm3.toFixed(1)} cm³ <span class="x">·</span> <span class="pl">plate 180 × 180</span>`;

  // ---------- rail and view switcher ----------
  const rail = $(".rail");
  const press = (sel, on) => { const b = rail.querySelector(`[data-tool="${sel}"]`); if (b) b.setAttribute("aria-pressed", String(on)); };
  rail.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const t = b.dataset.tool;
    if (!["analyze", "sim", "frame", "dims", "device"].includes(t)) return;
    story.takeover();
    if (t === "analyze") setMap(!S.map);
    else if (t === "sim") setSim(!S.sim, true);
    else if (t === "frame") vp.frame(true);
    else if (t === "dims") { S.dims = !S.dims; press("dims", S.dims); if (!S.sim) vp.setDims(S.dims); }
    else if (t === "device") { S.device = !S.device; press("device", S.device); if (!S.sim) vp.setDevice(S.device); }
  });
  const vseg = $(".vseg");
  vseg.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; story.takeover(); setView(b.dataset.v); });
  function setView(v, anim = true) {
    vseg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.v === v)));
    vp.view(v, anim && !reducedMotion());
  }
  $("#clear-map").addEventListener("click", () => { story.takeover(); setMap(false); });

  // wall thickness (Analyze)
  const th = d.thickness, legend = $("#legend");
  legend.innerHTML = `<div class="hd"><span class="cap">${esc(th.label)}</span>${tag("Computed")}</div>
    ${th.legend.stops.map((s) => `<div class="stop"><i style="background:${s.color}"></i><b>${esc(s.label)}</b><span>${esc(s.note)}</span></div>`).join("")}
    <div class="rule"></div>
    <div class="kv"><span>Thinnest sample</span><b>${th.stats.min_mm.toFixed(2)} mm</b></div>
    <div class="kv"><span>Median</span><b>${th.stats.median_mm.toFixed(2)} mm</b></div>
    <div class="kv"><span>Under 2 perimeters</span><b>${th.stats.under_two_perimeters_pct.toFixed(1)}% of surface</b></div>
    <div class="kv"><span>Check “Thinnest wall”</span><b>${checks.find((c) => c.id === "wall").value}</b></div>
    <div class="not">Not a strength analysis.</div>`;
  function setMap(on) {
    if (S.sim && on) setSim(false);
    S.map = on; press("analyze", on);
    $("#mseg").classList.toggle("on", on); legend.classList.toggle("on", on);
    vp.setThickness(th, on && S.built);
  }

  // ---------- print simulation ----------
  let TP = null;
  const simbar = $("#simbar"), typesHud = $("#types-hud");
  async function ensureTP() {
    if (TP) return TP;
    TP = await toolpath();
    vp.setToolpath(TP);
    const m = TP.meta;
    typesHud.innerHTML = `<div class="hd"><span class="cap">Line types</span><span class="small">m of path</span></div><ul>${m.types.map((t) => `<li><button type="button" data-t="${esc(t)}" aria-pressed="true"><i style="background:${INKS[t]}"></i><span>${esc(t)}</span><em>${(m.type_length_mm[t] / 1000).toFixed(1)}</em></button></li>`).join("")}</ul>`;
    simbar.innerHTML = `<div class="r1"><button type="button" class="play" id="sb-play">${icon(I.play)}<span>Play</span></button>
      <div class="speeds" role="group" aria-label="Speed">${[1, 4, 16, 64].map((x) => `<button type="button" data-x="${x}" aria-pressed="${x === S.speed}">${x}×</button>`).join("")}</div>
      <div class="read"><div class="a"><span id="sb-layer"></span><span id="sb-z"></span><span><span class="dt" id="sb-dot"></span><span class="ty" id="sb-type"></span></span></div><div class="b"><span id="sb-el"></span><span id="sb-rem"></span>${tag("Slicer estimate")}</div></div></div>
      <div class="chart" id="sb-chart" role="slider" tabindex="0" aria-label="Layer" aria-valuemin="1" aria-valuemax="${m.z.length}"><canvas></canvas></div>
      <div class="r3"><span class="lt" id="sb-lt"></span><span style="flex:1"></span><button type="button" class="nb" id="sb-bridge">${icon(I.skip)}Next bridge</button><button type="button" class="nb" id="sb-over">${icon(I.skip)}Next overhang wall</button></div>`;
    typesHud.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return; story.takeover();
      const t = b.dataset.t; S.hidden.has(t) ? S.hidden.delete(t) : S.hidden.add(t);
      b.setAttribute("aria-pressed", String(!S.hidden.has(t))); vp.setHidden(S.hidden);
    });
    $("#sb-play").addEventListener("click", () => { story.takeover(); if (S.simP >= m.z.length - 0.001) setP(0); setPlaying(!S.playing); });
    simbar.querySelector(".speeds").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; story.takeover(); S.speed = +b.dataset.x; simbar.querySelectorAll(".speeds button").forEach((x) => x.setAttribute("aria-pressed", String(x === b))); });
    const jump = (list) => { story.takeover(); setPlaying(false); const cur = Math.floor(S.simP); const nx = list.find((l) => l > cur) ?? list[0]; if (nx !== undefined) setP(nx + 1); };
    $("#sb-bridge").addEventListener("click", () => jump(m.bridge_layers));
    $("#sb-over").addEventListener("click", () => jump(m.overhang_layers));
    scrubber($("#sb-chart"), (f) => { story.takeover(); setPlaying(false); setP(f * m.z.length); });
    return TP;
  }
  const tAt = (p) => { const m = TP.meta, l = Math.min(Math.floor(p), m.z.length - 1); return p >= m.z.length ? m.total_time_s : m.t0_s[l] + (p - l) * m.time_s[l]; };
  const pAtT = (s) => { const m = TP.meta; if (s >= m.total_time_s) return m.z.length; let lo = 0, hi = m.z.length - 1; while (lo < hi) { const mid = (lo + hi + 1) >> 1; m.t0_s[mid] <= s ? (lo = mid) : (hi = mid - 1); } return lo + (m.time_s[lo] > 0 ? Math.min(0.9999, (s - m.t0_s[lo]) / m.time_s[lo]) : 0); };
  function here(p) {
    const m = TP.meta, l = Math.min(Math.floor(p), m.z.length - 1);
    let a = TP.layerStart[l], b = TP.layerStart[l + 1] - 1;
    if (p >= m.z.length) { const i = TP.layerStart[m.z.length] - 1; return { x: TP.seg[i * 4 + 2], y: TP.seg[i * 4 + 3], z: m.z[l], type: m.types[TP.type[i]] }; }
    while (a < b) { const mid = (a + b) >> 1; TP.p1[mid] < p ? (a = mid + 1) : (b = mid); }
    const i = a, f = Math.max(0, Math.min(1, (p - TP.p0[i]) / Math.max(1e-6, TP.p1[i] - TP.p0[i])));
    return { x: TP.seg[i * 4] + (TP.seg[i * 4 + 2] - TP.seg[i * 4]) * f, y: TP.seg[i * 4 + 1] + (TP.seg[i * 4 + 3] - TP.seg[i * 4 + 1]) * f, z: m.z[l], type: m.types[TP.type[i]] };
  }
  function setP(p) {
    const m = TP.meta; S.simP = Math.max(0, Math.min(m.z.length, p));
    const h = here(S.simP), l = Math.min(Math.floor(S.simP), m.z.length - 1), el = tAt(S.simP);
    vp.setSimNow(S.simP, h);
    $("#sb-layer").textContent = `Layer ${l + 1} / ${m.z.length}`;
    $("#sb-z").textContent = `· z ${m.z[l].toFixed(2)} mm`;
    $("#sb-dot").style.background = INKS[h.type] || "#a8b2af"; $("#sb-type").textContent = h.type;
    $("#sb-el").textContent = `${fmtDur(el)} elapsed`; $("#sb-rem").textContent = `· ${fmtDur(m.total_time_s - el)} remaining`;
    $("#sb-lt").textContent = `Layer ${l + 1}: ${fmtDur(m.time_s[l])} · ${(m.length_mm[l] / 1000).toFixed(2)} m of path`;
    $("#sb-chart").setAttribute("aria-valuenow", String(l + 1));
    drawChart($("#sb-chart canvas"), m, S.simP);
  }
  let last = 0;
  function setPlaying(on) {
    S.playing = on;
    const b = $("#sb-play"); if (b) b.innerHTML = `${icon(on ? I.pause : I.play)}<span>${on ? "Pause" : "Play"}</span>`;
    last = performance.now();
    vp.tick = on ? (now) => {
      const dt = Math.min(0.1, (now - last) / 1000); last = now;
      const t = tAt(S.simP) + dt * (S.speedOverride || S.speed);
      setP(pAtT(t));
      if (S.simP >= TP.meta.z.length) { setPlaying(false); S.onSimEnd && S.onSimEnd(); }
    } : null;
    vp.kick();
  }
  async function setSim(on, fromUser) {
    if (on) {
      await ensureTP();
      if (S.map) setMap(false);
      if (S.stage !== "prove") setStage("prove", false);
    } else setPlaying(false);
    S.sim = on; press("sim", on);
    [simbar, typesHud, $("#badge-sim")].forEach((x) => x.classList.toggle("on", on));
    $("#mseg").classList.remove("on");
    $(".vseg").style.opacity = on ? "0" : ""; $(".vseg").style.pointerEvents = on ? "none" : "";
    $("#dims-read").style.opacity = on ? "0" : "";
    vp.setSim(on); vp.setPartVisible(!on); vp.setDims(!on && S.dims); vp.setDevice(!on && S.device);
    if (on) { setP(fromUser && S.simP >= TP.meta.z.length ? TP.meta.z.length : S.simP); if (fromUser) { S.speedOverride = 0; } }
  }
  $("#sim-back").addEventListener("click", () => { story.takeover(); setSim(false); });

  // ---------- conversation ----------
  const scroll = $("#talk-scroll"), field = $("#composer-field"), send = $("#send");
  const emptyState = () => `<div class="empty"><h3>Ask about this design,<br>or describe a change.</h3><p>The agent works on the design with Form Studio’s tools. Changes arrive as a draft or a new revision you can compare and undo.</p></div>`;
  const STEPS = [
    { tool: "create_project", text: "Started from the dock building block", icon: I.cube, rich: true },
    { tool: "render", text: "Looked at the iso view", icon: I.eye, rich: true, img: true },
    { tool: "preview_change", text: "depth=92", rich: false },
    { tool: "commit_change", text: "Committed a revision", icon: I.commit, rich: true },
    { tool: "run_pipeline", text: "solid, exports, checks, slice", rich: false },
  ];
  const ANSWER = [
    `I started from the dock building block and sized the pocket for a ${d.values.device_width} × ${d.values.device_thickness} mm phone with ${d.values.clearance} mm of clearance per side. At 78 mm deep the dock tipped backwards when the screen was tapped, so the base is now ${d.values.depth} mm deep. The cable leaves through a bridged channel at the back.`,
    `${passes.length} checks pass and ${warns.length} need a look. Tip-over resistance is ${warns[0].value}, a model that assumes the infill mass. The fit is ${fitY}% modelled because the phone’s width is assumed: measure it with calipers and the model gives ${d.next_actions[0].yield_after}. The slice is simulated: ${hm(d.slice_meta.time_s)} and ${d.slice_meta.filament_g.toFixed(1)} g of PLA on your A1 mini.`,
  ];
  let stepsEl = null;
  function addUser(text) {
    const el = document.createElement("div"); el.className = "msg-user"; el.textContent = text;
    el.animate?.([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 240, easing: "cubic-bezier(.23,1,.32,1)" });
    scroll.appendChild(el);
  }
  function stepsGroup() {
    stepsEl = document.createElement("div"); stepsEl.className = "steps";
    stepsEl.innerHTML = `<div class="steps-h">${icon(I.chevD)}<span class="n">1 step</span><span class="f"></span></div>`;
    scroll.appendChild(stepsEl);
  }
  function addStep(s, i) {
    const el = document.createElement("div"); el.className = "step run";
    el.innerHTML = `${icon(I.spin)}<span class="${s.rich ? "" : "mono"}" style="${s.rich ? "" : "font-size:11px;color:var(--ink3)"}">${esc(s.rich ? s.text : s.tool)}</span><span class="tool">${esc(s.rich ? s.tool : s.text)}</span>`;
    el.animate?.([{ opacity: 0 }, { opacity: 1 }], { duration: 170 });
    stepsEl.appendChild(el);
    stepsEl.querySelector(".n").textContent = `${i + 1} step${i ? "s" : ""}`;
    return el;
  }
  function doneStep(el, s) {
    el.classList.remove("run");
    el.querySelector(".i").innerHTML = `&#x${s.rich ? s.icon : I.check};`;
    if (!s.rich) el.querySelector(".i").style.color = "var(--ink4)";
    if (s.img) {
      const box = document.createElement("div"); box.className = "step-img";
      const c = document.createElement("canvas"); box.appendChild(c); el.after(box);
      snapshot(c);
    }
  }
  function snapshot(c) {   // the render the agent looked at: the same kernel mesh, on the app's light sheet background
    const src = vp.renderer.domElement; vp.renderer.render(vp.scene, vp.camera);
    const W = 440, H = 330; c.width = W; c.height = H;
    const g = c.getContext("2d"); g.fillStyle = "#e9e6df"; g.fillRect(0, 0, W, H);
    const r = Math.min(W / src.width, H / src.height) * 1.3;
    g.drawImage(src, (W - src.width * r) / 2, (H - src.height * r) / 2 - 10, src.width * r, src.height * r);
  }
  async function streamAnswer(wait) {
    const box = document.createElement("div"); box.className = "answer"; scroll.appendChild(box);
    for (const para of ANSWER) {
      const p = document.createElement("p"); box.appendChild(p);
      const words = para.split(" ");
      p.innerHTML = words.map((w) => `<span class="w pre">${esc(w)} </span>`).join("");
      const spans = p.querySelectorAll(".w");
      for (let i = 0; i < spans.length; i += 3) {
        for (let j = i; j < Math.min(i + 3, spans.length); j++) spans[j].classList.remove("pre");
        keepBottom();
        await wait(55);
      }
      await wait(160);
    }
  }
  function keepBottom() {
    const body = $("#talk-body"), over = scroll.scrollHeight - (body.clientHeight - 28);
    scroll.style.transform = over > 0 ? `translateY(${-over}px)` : "";
  }

  // ---------- the pointer that plays the visitor during the story ----------
  const ptr = $("#ptr"); let ptrXY = [900, 500];
  const appRect = () => app.getBoundingClientRect();
  async function pointTo(el, wait, dx = 0.5, dy = 0.5) {
    if (!el || compact.matches) return;
    const a = appRect(), r = el.getBoundingClientRect(), s = a.width / 1440;
    const to = [(r.left - a.left + r.width * dx) / s, (r.top - a.top + r.height * dy) / s];
    ptr.classList.add("on");
    const dist = Math.hypot(to[0] - ptrXY[0], to[1] - ptrXY[1]), ms = Math.min(900, 380 + dist * 0.5);
    ptr.animate([{ transform: `translate(${ptrXY[0]}px, ${ptrXY[1]}px)` }, { transform: `translate(${to[0]}px, ${to[1]}px)` }], { duration: ms, easing: "cubic-bezier(.65,0,.25,1)", fill: "forwards" });
    ptrXY = to; await wait(ms + 60);
  }
  async function click(wait) { ptr.classList.add("press"); await wait(110); ptr.classList.remove("press"); await wait(60); }

  // ---------- reset and the finished state ----------
  function reset() {
    S.built = S.checked = S.sliced = false; S.acks = [false, false];
    if (S.sim) setSim(false); if (S.map) setMap(false);
    NODES.forEach(([id]) => node(id, "missing"));
    vp.hideFeatures(); vp.setDims(false); vp.setDevice(false);
    scroll.innerHTML = emptyState(); scroll.style.transform = "";
    field.textContent = "Ask about Hallway phone dock, or describe a change…"; field.className = "field ph"; send.classList.remove("on");
    $("#talk-title").textContent = "New conversation"; $("#tb-state").textContent = "Unreleased";
    $("#dims-read").style.opacity = "0";
    setView("iso", false); vp.orbitBy(-0.5);
    S.stage = "shape"; renderTabs(); renderPanel(false);
    ptr.classList.remove("on");
  }
  function finished() {
    S.built = S.checked = S.sliced = true;
    NODES.forEach(([id]) => node(id, "current"));
    vp.showAll(); vp.setDims(S.dims); vp.setDevice(S.device);
    $("#dims-read").style.opacity = "";
    scroll.innerHTML = ""; addUser(d.brief); stepsGroup();
    STEPS.forEach((s, i) => { const el = addStep(s, i); doneStep(el, s); });
    stepsEl.querySelector(".f").textContent = "";
    const box = document.createElement("div"); box.className = "answer"; box.innerHTML = ANSWER.map((p) => `<p>${esc(p)}</p>`).join(""); scroll.appendChild(box);
    $("#talk-title").textContent = "A dock for my phone on the hallway shelf";
    requestAnimationFrame(keepBottom);
    setView("iso", false);
    S.stage = "prove"; renderTabs(); renderPanel(false);
  }

  // ---------- screens: Home (Home.qml) and the workspace ----------
  const seg = document.querySelector(".scr-seg");
  const homeField = $("#home-field"), homeGo = $("#home-go");
  let screen = "work", skipHome = false;
  function setScreen(s) {
    screen = s;
    app.classList.toggle("on-home", s === "home");
    if (s === "home") app.classList.remove("blank");
    seg?.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.scr === s)));
    closeMenu();
    if (s === "work") requestAnimationFrame(() => vp.kick());
  }
  const greet = () => { const h = new Date().getHours(); return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };
  $("#home-greet").textContent = greet();
  seg?.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; story.takeover(); if (b.dataset.scr === "work" && !S.built) finished(); setScreen(b.dataset.scr); });
  $("#tb-home").addEventListener("click", () => { story.takeover(); setScreen("home"); });
  const goState = () => homeGo.classList.toggle("on", homeField.value.trim().length > 0);
  homeField.addEventListener("input", () => { story.takeover(); goState(); });
  homeField.addEventListener("focus", () => story.takeover());
  homeField.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); homeGo.click(); } });
  homeGo.addEventListener("click", () => {
    if (!homeField.value.trim()) return;
    // the page has one sample project: it opens, and the conversation that made it plays from the request on
    story.takeover(); homeField.value = ""; goState();
    skipHome = true; story.start();
  });
  const LEAD = { print: "Describe it, drop a photo or a part, sketch it, or paste a link. It becomes real CAD, checked and sliced for your printer.",
    model: "Describe it, drop a photo or a part, sketch it, or paste a link. It becomes real CAD you can check and export." };
  document.querySelector(".hseg").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return; story.takeover();
    document.querySelectorAll(".hseg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $("#home-lead").textContent = LEAD[b.dataset.p]; $("#home-printer").style.display = b.dataset.p === "print" ? "" : "none";
  });
  const openDock = () => { story.takeover(); app.classList.remove("blank"); finished(); setScreen("work"); };
  $("#home-cont").addEventListener("click", openDock);
  $("#home-scr").addEventListener("click", (e) => {
    const c = e.target.closest(".hcard"); if (!c) return;
    if (c.dataset.open === "dock") openDock();
    else { story.takeover(); document.getElementById("assemblies")?.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth" }); }
  });
  $("#home-blank").addEventListener("click", () => { story.takeover(); reset(); app.classList.add("blank"); $("#talk-title").textContent = "New conversation"; setScreen("work"); });

  // ---------- the model menu (TalkModelPicker.qml), as the app shows it on a computer with three agent apps ----------
  const AGENTS = [
    { id: "claude", label: "Claude Code", note: "your account", efforts: ["default", "low", "medium", "high", "xhigh", "max"],
      models: [{ id: "default", label: "Default", note: "Claude Code chooses for your account. Its version shows here after a reply with Default." },
        ...["fable", "opus", "sonnet", "haiku"].map((a) => ({ id: a, label: a[0].toUpperCase() + a.slice(1), note: `Alias for the latest ${a} model. The version shows here after its first reply.` }))] },
    { id: "codex", label: "Codex", note: "your account · no cost figure", models: [{ id: "default", label: "Default", note: "Whatever Codex is set to use" }] },
    { id: "gemini", label: "Gemini CLI", note: "your account · no cost figure", models: [{ id: "default", label: "Default", note: "Whatever Gemini CLI is set to use" }] },
  ];
  const pick = { agent: "claude", model: "default", effort: "default" };
  const menu = $("#mmenu");
  let menuFor = null;
  const chipText = () => { const a = AGENTS.find((x) => x.id === pick.agent), m = a.models.find((x) => x.id === pick.model) || a.models[0]; return `${a.label} · ${m.label}`; };
  function renderMenu() {
    const a = AGENTS.find((x) => x.id === pick.agent);
    menu.innerHTML = `<span class="mm-cap">Agent apps</span>
      ${AGENTS.map((x) => `<button type="button" class="mm-ag ${x.id === pick.agent ? "on" : ""}" data-ag="${x.id}" role="radio" aria-checked="${x.id === pick.agent}"><span class="rd"></span><b>${esc(x.label)}</b><small>${esc(x.note)}</small></button>`).join("")}
      <div class="mm-add">${icon("e13d")}Add an agent, an API key, a provider or a local model…</div>
      <div class="mm-rule"></div><span class="mm-cap">Model</span>
      ${a.models.map((m) => `<button type="button" class="mm-mo ${m.id === pick.model ? "on" : ""}" data-mo="${m.id}" title="${esc(m.note)}"><b>${esc(m.label)}</b><span>${esc(m.note)}</span>${icon(I.check)}</button>`).join("")}
      ${pick.agent === "claude" ? `<div class="mm-custom">Custom model id</div><div class="mm-rule"></div><span class="mm-cap">Effort</span>
      <div class="mm-eff">${a.efforts.map((e) => `<button type="button" data-ef="${e}" aria-pressed="${e === pick.effort}">${e}</button>`).join("")}</div>` : ""}`;
    document.querySelectorAll(".mpick .ml").forEach((l) => { l.textContent = chipText(); });
  }
  function placeMenu(anchor) {
    const a = app.getBoundingClientRect(), r = anchor.getBoundingClientRect(), s = compact.matches ? 1 : a.width / 1440;
    const x = (r.left - a.left + r.width / 2) / s, top = (r.top - a.top) / s, bottom = (r.bottom - a.top) / s;
    menu.style.left = `${Math.max(10, Math.min(1440 - 390, x - 190))}px`;
    if (anchor.id === "talk-model") { menu.style.top = ""; menu.style.bottom = `${(a.height / s) - top + 8}px`; menu.style.transformOrigin = "bottom center"; }
    else { menu.style.bottom = ""; menu.style.top = `${bottom + 6}px`; menu.style.transformOrigin = "top center"; }
    menu.style.maxHeight = compact.matches ? "" : `${Math.min(560, Math.max(220, anchor.id === "talk-model" ? top - 60 : 880 - bottom - 18))}px`;
  }
  function openMenu(anchor) {
    if (menuFor === anchor) return closeMenu();
    closeMenu(); renderMenu(); menu.hidden = false; placeMenu(anchor); menuFor = anchor; anchor.setAttribute("aria-expanded", "true");
  }
  function closeMenu() { if (!menuFor) return; menu.hidden = true; menuFor.setAttribute("aria-expanded", "false"); menuFor = null; }
  document.querySelectorAll(".mpick").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); story.takeover(); openMenu(b); }));
  menu.addEventListener("click", (e) => {
    e.stopPropagation();
    const ag = e.target.closest("[data-ag]"), mo = e.target.closest("[data-mo]"), ef = e.target.closest("[data-ef]");
    if (ag) { pick.agent = ag.dataset.ag; pick.model = "default"; pick.effort = "default"; renderMenu(); }
    else if (mo) { pick.model = mo.dataset.mo; renderMenu(); closeMenu(); }
    else if (ef) { pick.effort = ef.dataset.ef; renderMenu(); }
  });
  document.addEventListener("click", (e) => { if (menuFor && !menu.contains(e.target)) closeMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  renderMenu();

  // ---------- the story ----------
  const story = makeStory(async (wait) => {
    reset();
    if (!skipHome) {
      // the visitor's request, on Home: typed into the composer, then Design it
      setScreen("home");
      await wait(1100);
      await pointTo(homeField, wait, 0.25, 0.4);
      await click(wait);
      for (let i = 0; i <= d.brief.length; i += 3) { homeField.value = d.brief.slice(0, i); goState(); await wait(26); }
      homeField.value = d.brief; goState();
      await wait(300);
      await pointTo(homeGo, wait); await click(wait);
      homeField.value = ""; goState();
    }
    skipHome = false;
    setScreen("work");
    scroll.innerHTML = ""; addUser(d.brief);
    $("#talk-title").textContent = "A dock for my phone on the hallway shelf";
    ptr.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 300, fill: "forwards" }); setTimeout(() => ptr.classList.remove("on"), 300); ptr.getAnimations().forEach((a) => a.id === "f" && a.cancel());
    await wait(500);
    stepsGroup();
    // 1: the design, from the building block; the kernel builds it feature by feature
    let el = addStep(STEPS[0], 0); node("params", "running");
    await wait(700); node("params", "current"); node("geometry", "running");
    const order = d.features.map((f) => f.id).filter((id) => vp.features.has(id));
    for (const id of order) { vp.revealFeature(id); await wait(230); }
    vp.revealEdges(); await wait(300);
    vp.setDims(true); vp.setDevice(true); $("#dims-read").style.opacity = "";
    node("geometry", "current"); S.built = true; doneStep(el, STEPS[0]);
    setStage("shape");
    await wait(900);
    // 2: it looks at what it made
    el = addStep(STEPS[1], 1); await wait(650); doneStep(el, STEPS[1]); keepBottom(); await wait(700);
    // 3: a deeper base so a tap does not tip it; previewed, then committed
    el = addStep(STEPS[2], 2); setView("side"); await wait(1100); doneStep(el, STEPS[2]);
    el = addStep(STEPS[3], 3); await wait(600); doneStep(el, STEPS[3]); setView("iso"); keepBottom();
    // 4: the pipeline: exports, checks, slice
    el = addStep(STEPS[4], 4); node("exports", "running"); await wait(600); node("exports", "current");
    node("checks", "running"); await wait(800); node("checks", "current"); S.checked = true;
    await pointTo($("#tab-prove"), wait); await click(wait); setStage("prove");
    node("slice", "running"); await wait(1500); node("slice", "current"); S.sliced = true; node("release", "current");
    doneStep(el, STEPS[4]); stepsEl.querySelector(".f").textContent = "2 folded"; renderTabs(); renderPanel(false);
    await wait(300);
    await streamAnswer(wait);
    await wait(1200);
    // the print, layer by layer
    await pointTo($("#watch"), wait); await click(wait);
    await setSim(true); setP(0); await wait(400);
    S.speedOverride = 640; setPlaying(true);
    await new Promise((res) => { S.onSimEnd = res; });
    S.onSimEnd = null; S.speedOverride = 0;
    await wait(1600);
    await pointTo($("#sim-back"), wait); await click(wait); setSim(false);
    await wait(600);
    // fit, then the release gate: acknowledged by a person, approved by a person
    await pointTo($("#tab-fit"), wait); await click(wait); setStage("fit"); await wait(2600);
    await pointTo($("#tab-release"), wait); await click(wait); setStage("release"); await wait(900);
    for (const i of [0, 1]) { await pointTo(wrap.querySelector(`[data-ack="${i}"] .bx`), wait); await click(wait); S.acks[i] = true; renderPanel(false); await wait(350); }
    await pointTo($("#approve"), wait, 0.4, 0.5);
    await wait(3600);
    ptr.classList.remove("on");
  }, { onState: (st, frac) => {
    const b = $("#story-ctl"), lbl = b.querySelector(".lbl"), ic = b.querySelector(".i");
    lbl.textContent = st === "playing" ? "Pause" : st === "taken" ? "Replay story" : "Play story";
    ic.innerHTML = st === "playing" ? `&#x${I.pause};` : `&#x${I.play};`;
    b.setAttribute("aria-pressed", String(st !== "playing"));
  }, onProgress: (f) => { $("#story-bar").style.transform = `scaleX(${f})`; }, onTakeover: () => { if (S.playing && S.speedOverride) { setPlaying(false); S.speedOverride = 0; } ptr.classList.remove("on"); } });

  $("#story-ctl").addEventListener("click", () => story.toggle());
  // hovering the window with a moving pointer holds the story; it carries on when the pointer rests or leaves
  let restT = 0;
  app.addEventListener("pointermove", (e) => { if (e.pointerType !== "mouse") return; story.hold(true); clearTimeout(restT); restT = setTimeout(() => story.hold(false), 2600); });
  app.addEventListener("pointerleave", () => { clearTimeout(restT); story.hold(false); });
  $("#gl").addEventListener("keydown", (e) => {
    const k = { 1: "iso", 2: "front", 3: "side", 4: "top", 5: "under" }[e.key];
    if (k) { story.takeover(); setView(k); }
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { story.takeover(); vp.orbitBy(e.key === "ArrowLeft" ? -0.15 : 0.15); }
  });
  new IntersectionObserver(([e]) => story.hold(!e.isIntersecting, "offscreen"), { threshold: 0.15 }).observe(app);
  document.addEventListener("visibilitychange", () => story.hold(document.hidden, "hidden"));

  // ?still (or reduced motion) shows the finished state; ?stage=fit, ?sim=60, ?map open a given view of it
  const q = new URLSearchParams(location.search);
  if (reducedMotion() || q.has("still") || q.has("home") || q.has("stage") || q.has("sim") || q.has("map")) {
    finished(); story.idle();
    if (q.has("home")) setScreen("home");
    if (q.get("home") === "menu") openMenu($("#home-model"));
    if (q.get("stage")) setStage(q.get("stage"), false);
    if (q.has("map")) setMap(true);
    if (q.has("sim")) { await setSim(true); setP(+q.get("sim") || TP.meta.z.length); }
  } else story.start();
  return { finished };
}

// A pausable script: wait() resolves only while the story is playing. takeover() stops it where it is;
// start() plays it from the beginning, and it loops calmly until taken over.
function makeStory(script, { onState, onProgress, onTakeover }) {
  let epoch = 0, state = "idle", holds = new Set(), clock = 0, lastNow = 0, total = 52000;
  const playing = () => state === "playing" && holds.size === 0;
  const tickClock = () => { const now = performance.now(); if (playing()) clock += now - lastNow; lastNow = now; onProgress(Math.min(1, clock / total)); };
  setInterval(tickClock, 200);
  const wait = (ms) => new Promise((res, rej) => {
    const my = epoch; let left = ms, t = performance.now();
    const step = () => {
      if (my !== epoch) return rej(new Error("stopped"));
      const now = performance.now(); if (playing()) left -= now - t; t = now;
      if (left <= 0) res(); else setTimeout(step, Math.min(left, 50));
    };
    step();
  });
  const run = async () => {
    const my = ++epoch;
    while (my === epoch) {
      clock = 0; lastNow = performance.now();
      try { await script(wait); } catch (e) { if (e.message !== "stopped") console.error(e); return; }
      if (my !== epoch) return;
      total = Math.max(total, clock);
      try { await wait(1200); } catch { return; }
    }
  };
  const api = {
    start() { state = "playing"; onState(state); run(); },
    idle() { state = "idle"; epoch++; onState(state); onProgress(0); },
    takeover() { if (state !== "playing") return; state = "taken"; epoch++; onTakeover(); onState(state); },
    hold(on, why = "hover") { on ? holds.add(why) : holds.delete(why); },
    toggle() { if (state === "playing") { state = "paused"; onState(state); } else if (state === "paused") { state = "playing"; onState(state); } else api.start(); },
  };
  return api;
}

// drag/click/keys on a chart = scrub (shared with the print demo)
export function scrubber(el, onF) {
  const f = (e) => { const r = el.getBoundingClientRect(); return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); };
  el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); onF(f(e)); const mv = (ev) => onF(f(ev)); el.addEventListener("pointermove", mv); el.addEventListener("pointerup", () => el.removeEventListener("pointermove", mv), { once: true }); });
  el.addEventListener("keydown", (e) => {
    const now = +el.getAttribute("aria-valuenow") || 1, max = +el.getAttribute("aria-valuemax");
    const n = e.key === "ArrowRight" ? now + 1 : e.key === "ArrowLeft" ? now - 1 : e.key === "PageUp" ? now + 10 : e.key === "PageDown" ? now - 10 : e.key === "Home" ? 1 : e.key === "End" ? max : null;
    if (n === null) return; e.preventDefault(); onF((Math.max(1, Math.min(max, n)) - 0.0001) / max);
  });
}

// time per layer, the slicer's estimate; bridge and overhang layers marked above (PrintSimChart.qml)
export function drawChart(c, m, p) {
  const r = c.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
  if (!r.width) return;
  if (c.width !== Math.round(r.width * dpr)) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); }
  const g = c.getContext("2d"), W = c.width, H = c.height, n = m.z.length, bw = W / n, top = 9 * dpr;
  g.clearRect(0, 0, W, H);
  const max = Math.max(...m.time_s.slice(1));
  const cur = Math.min(Math.floor(p), n - 1);
  for (let i = 0; i < n; i++) {
    const h = Math.max(2 * dpr, Math.min(1, m.time_s[i] / max) * (H - top - 2 * dpr));
    g.fillStyle = i < cur ? "rgba(168,178,175,.75)" : i === cur ? "#b9e8d7" : "rgba(168,178,175,.28)";
    g.fillRect(i * bw + 0.5 * dpr, H - h, Math.max(1, bw - 1 * dpr), h);
  }
  g.fillStyle = "#ff6f51";
  for (const l of m.bridge_layers) g.fillRect(l * bw, 2 * dpr, Math.max(1, bw - dpr), 2 * dpr);
  g.fillStyle = "#ff8a65";
  for (const l of m.overhang_layers) g.fillRect(l * bw, 5 * dpr, Math.max(1, bw - dpr), 2 * dpr);
  g.fillStyle = "#e8edeb"; g.fillRect(Math.min(W - dpr, (p / n) * W), top - 2 * dpr, 1.2 * dpr, H - top + 2 * dpr);
}
