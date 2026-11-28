// Direction I: Designing, a picked edge with the source pane, Check (a strength study) and Make (print, CNC).

// ---- Designing: the agent builds, the cue names the feature, the tree runs ----
if (S === "designing") { const k = .7, cy = 352;
  put(`${room(754, 520)}
  ${shot("part", k, 754, cy, (f, w, h) => img("mount-s5", w) + `<svg class="edges" width="${w}" height="${h}"></svg>` + overall(f, w, h))}
  ${topbar(0, { modes: [["Design", "5 of 8 features"], ["Check", "waits for the build"], ["Make", "waits"], ["Document", "waits"]], busy: "Designing · 1 min 12 s", rev: "r01" })}
  ${convo(TITLE, `<div class="you">A mount for a NEMA 17 on a 2020 rail. Aluminium, to be milled. Belt pulls about 250 N.</div>
    <div class="card"><h4>Plan<em>approved by you</em></h4><div class="plan"><div>Base plate with two M5 slots for the rail</div><div>Upright with the NEMA 17 pattern</div><div>Two gussets, then a fillet at the root</div><div>Check strength at 250 N, then machinability</div></div></div>
    <div class="step">${I("book", 15)}Opened NEMA ICS 16, frame 17<span class="num">p. 4</span></div>
    <div class="step">${I("check", 15)}Built Base plate, Upright, Gussets, Pilot bore<span class="num">9 s</span></div>
    <div class="status"><i class="live"></i>Drilling the motor screws<span>4 × Ø3.4 on 31.0</span></div>`,
    "Say something while it builds…", { live: true, stop: true, end: true })}
  <div style="opacity:.45">${dock(0, "cursor")}${cube()}</div>
  <section class="third"><p class="over"><i class="live"></i>Building <i>5 of 8</i></p><h1><span class="num">05</span>Motor screws</h1>
    <div class="track">${D.feats.map((_, i) => `<i class="${i < 4 ? "done" : i === 4 ? "now" : ""}"></i>`).join("")}</div>
    <p class="around"><span>built<b>04</b>Pilot bore</span><span>next<b>06</b>Base slots</span></p></section>
  <aside class="pane glass">${tree({ step: 5 })}
    <div class="insp"><h3>Contract<em>3 of 6 proved so far</em></h3>
      <div class="kv" style="grid-template-columns:16px 1fr auto"><i class="dot ok"></i><span>Pilot bore Ø22.0</span><b class="num">22.000</b><i class="dot ok"></i><span>Plate thickness 6.0</span><b class="num">6.000</b><i class="dot ok"></i><span>Fits a 60 × 66 × 54 billet</span><b class="num">56 × 62 × 52</b>
        <i class="dot run"></i><span>4 × Ø3.4 on a 31.0 square</span><b class="num" style="color:var(--accent)">building</b><i class="dot none"></i><span>2 slots for M5, 26.0 apart</span><b class="num" style="color:var(--ink3)">waits</b><i class="dot none"></i><span>Safety factor ≥ 4 at 250 N</span><b class="num" style="color:var(--ink3)">waits</b></div>
      <p>Each row is measured on the solid by the kernel when its feature lands. Nothing is ticked by the agent.</p></div>
    ${pipe("r01 · building")}</aside>
  <p class="readout num" style="left:386px">56.0 × 52.0 × 62.0 mm<i>·</i>${(META.stages[4].vol_mm3 / 1000).toFixed(2)} cm³<em>as built so far${ev("computed")}</em></p>`); }

// ---- Design: a picked edge, its handle, and the source that follows ----
function edgeLayer(f, w, h) { const R = 4, n = 14, band = [], e1 = [], e2 = [];
  for (const x of [-23, 23]) { e1.push([x, 46 - R, 6]); e2.push([x, 46, 6 + R]); }
  const arcAt = (x) => Array.from({ length: n + 1 }, (_, i) => { const a = Math.PI / 2 * i / n; return [x, 46 - R + R * Math.sin(a), 6 + R - R * Math.cos(a)]; });
  const mid = [0, 46 - R + R * Math.SQRT1_2, 6 + R - R * Math.SQRT1_2], out = [0, mid[1] - 13, mid[2] + 13], [hx, hy] = f(...out), [mx, my] = f(...mid);
  return `<svg class="sk" width="${w}" height="${h}"><mask id="occ2"><rect width="${w}" height="${h}" fill="#fff"/><path d="${pl(f, [[23, 46, 44], [23, 46, 6], [23, 14, 6]])}Z${pl(f, [[28, 46, 44], [28, 46, 6], [28, 14, 6]])}Z${pl(f, [[23, 46, 44], [28, 46, 44], [28, 14, 6], [23, 14, 6]])}Z" style="fill:#000;stroke:none;filter:none"/></mask><g mask="url(#occ2)"><path class="fill" d="${pl(f, [...arcAt(-23), ...arcAt(23).reverse()])}Z"/><path d="${pl(f, e1)}"/><path d="${pl(f, e2)}"/>
    <path d="${pl(f, arcAt(-23))}"/></g><line x1="${mx}" y1="${my}" x2="${hx}" y2="${hy}"/><circle class="pt" cx="${mx}" cy="${my}" r="3.2"/>
    <circle cx="${hx}" cy="${hy}" r="8" style="fill:var(--accent)"/><circle cx="${hx}" cy="${hy}" r="15" style="stroke-width:1;opacity:.45"/></svg>
    <span class="dimtag edit" style="left:${hx + 62}px;top:${hy - 4}px">R 4.0<i></i><em>mm</em></span>`; }
const CODE = [[38, `<span class="c"># 06 · by hand, r05</span>`], [39, `<span class="kw2">@feature</span>("Base slots")`], [40, `<span class="kw2">def</span> base_slots(self, v, body):`], [41, `    s = Slot(v.slot_l, v.slot_w)`], [42, `    <span class="kw2">return</span> body - self.pair(s, 26.0)`], [43, ``],
  [44, `<span class="c"># 07 · refine, r06</span>`, 1], [45, `<span class="kw2">@feature</span>("Root fillet")`, 1], [46, `<span class="kw2">def</span> root_fillet(self, v, body):`, 1], [47, `    e = self.between(UPRIGHT, BASE)`, 1], [48, `    <span class="kw2">return</span> fillet(e, v.root_r)  <span class="c"># </span><span class="n">4.0</span>`, 1], [49, ``],
  [50, `<span class="c"># 08 · by hand, r07</span>`], [51, `<span class="kw2">@feature</span>("Edge chamfers")`], [52, `<span class="kw2">def</span> edge_chamfers(self, v, body):`], [53, `    e = self.top_edges(UPRIGHT)`], [54, `    <span class="kw2">return</span> chamfer(e, v.chamfer)`]];
if (S === "design-edge") put(`${room(754, 610)}
  ${partShot("mount-s8", edgeLayer)}
  ${topbar(0)}${convo(TITLE, reply + handnote, "Ask, or describe a change…")}
  ${dock(0, "fillet")}<div class="opts glass"><b>Fillet 07</b><span class="on">Radius</span><span>Variable</span><i class="sep"></i><span>2 edges picked</span><span>Add edges</span></div>
  ${cube()}${readout()}${hint(`<kbd class="k">Enter</kbd>commits<kbd class="k">Space</kbd>hold to see before`)}
  <aside class="pane glass">${tree({ sel: 6, code: 1 })}<div class="rb rest"><i></i></div>
    <div class="code">${CODE.map(([n, t, hl]) => `<div class="${hl ? "hl" : ""}"><u>${n}</u><span>${t}</span></div>`).join("")}</div>
    <p style="font-size:12px;line-height:17px;color:var(--ink2);padding:10px 8px 2px">One source. The handle, the slider and this line change the same value: <b class="num" style="color:var(--ink)">root_r</b>.</p>
    ${pipe("r07 · draft: root_r 4.0")}</aside>`);

// ---- Check: a strength study, developed on the part ----
const CHECKS = [["warn", "Geometry checks", "15 of 16", "computed"], ["ok", "Mass properties", "105.2 g", "computed"], ["ok", "Strength, static", "SF 19.4", "simulated", "sel"],
  ["ok", "Wall thickness", "min 5.0 mm", "computed"], ["ok", "Machinability, 3-axis", "2 setups", "rule"], ["ok", "Fit to NEMA 17", "98 %", "modelled"], ["none", "Vibration modes", "", `<span class="need">not run</span>`],
  ["none", "Draft for moulding", "", `<span class="need">needs process: moulding</span>`, "dim"], ["none", "Interference", "", `<span class="need">needs two parts</span>`, "dim"], ["none", "Motion", "", `<span class="need">needs joints</span>`, "dim"]];
function loadLayer(f, w, h) { const [bx, by] = f(0, 46, 35), [ax, ay] = f(0, 14, 35), [px, py] = f(0, 44.2, 8), an = Math.atan2(by - ay, bx - ax);
  const head = (x, y, a, s = 9) => `M${x} ${y}L${x - s * Math.cos(a - .42)} ${y - s * Math.sin(a - .42)}M${x} ${y}L${x - s * Math.cos(a + .42)} ${y - s * Math.sin(a + .42)}`;
  const fix = [[-13, 20, 6], [13, 20, 6]].map((p) => f(...p));
  return `<svg class="sk" width="${w}" height="${h}" style="--accent:var(--ink)"><line x1="${bx}" y1="${by}" x2="${ax}" y2="${ay}"/><path d="${head(ax, ay, an + Math.PI)}"/>
    <circle cx="${px}" cy="${py}" r="7" style="stroke-width:1.5"/><line x1="${px + 5}" y1="${py + 5}" x2="${px + 128}" y2="${py + 112}" style="stroke-width:1;opacity:.6"/></svg>
    <span class="dimtag" style="left:${ax - 6}px;top:${ay + 20}px;color:var(--ink);border-color:var(--edge)">250 N</span>
    ${fix.map(([x, y]) => `<span class="glyph" style="left:${x}px;top:${y}px;color:var(--ink);border-color:var(--edge)">${I("lock", 11, 2)}</span>`).join("")}
    <div class="callout glass" style="left:${px + 128}px;top:${py + 118}px"><b class="num">14.2 MPa</b><span>peak</span></div>`; }
const RAMP = "linear-gradient(90deg,#ccc3b3 0%,#99a8a8 10%,#29809e 30%,#0db8e6 55%,#4debff 78%,#fff 100%)";
const conv = `<svg width="296" height="52" viewBox="0 0 296 52" fill="none" style="margin:2px 0"><path d="M0 46.500h296" stroke="var(--line)"/><path d="M14 36L110 17L206 12" stroke="var(--ink2)" stroke-width="1.5"/><path d="M206 12L282 10.500" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="3 3"/>
  ${[[14, 36], [110, 17], [206, 12]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3" fill="var(--ink)"/>`).join("")}<circle cx="282" cy="10.500" r="3.5" fill="var(--accent)"/></svg>
  <div class="ticks" style="margin-top:-6px"><span>12.9</span><span style="left:110px">13.9</span><span style="left:206px">14.1</span><span class="r" style="left:296px"><b>14.2 MPa</b></span></div>`;
if (S === "study") put(`${room(754, 560)}
  ${shot("part", .8, 754, 426, (f, w, h) => img("mount-heat", w) + img("mount-glow", w, "bloom") + loadLayer(f, w, h))}
  ${topbar(1)}${convo(TITLE, reply, "Ask, or describe a change…")}
  ${dock(1, "cursor")}<div class="opts glass"><b>Strength</b><span class="on">Stress</span><span>Displacement</span><span>Safety factor</span><i class="sep"></i><span>Deformed × 200</span></div>${cube()}
  <div class="strip glass"><header><b>von Mises stress</b><span>MPa · r07 · 6061-T6</span>${ev("simulated · linear static")}</header>
    <div><div class="bar" style="background:${RAMP}"><i style="left:calc(100% - 2px)"></i></div></div>
    <div class="ticks"><span>0</span><span style="left:25%">3.6</span><span style="left:50%">7.1</span><span style="left:75%">10.7</span><span class="r" style="left:100%"><b>14.2 peak</b></span></div>
    <p><b>Discretisation error ≤ 2.8 %</b> after 3 refinements; reactions balance the load to 0.04 %. Yield, 276 MPa, is off this scale. Not told here: fatigue, buckling, bolt preload.</p></div>
  <aside class="pane glass"><header><b>Check</b><span class="num">10</span><em>r07 · 6 current</em></header>
    <div class="rows">${CHECKS.map(([d, n, v, e, st]) => srow(d, n, v, e, st)).join("")}</div>
    <div class="insp"><h3>Strength, static<em><i class="dot ok"></i>current for r07</em></h3>
      <div class="big"><span class="num">19.4</span><span>safety factor against yield</span></div>
      <div class="kv"><span>Peak stress</span><b class="num">14.2 MPa</b>${ev("simulated")}<span>Yield, 6061-T6</span><b class="num">276 MPa</b>${ev("specified")}<span>Largest movement</span><b class="num">0.006 mm</b>${ev("simulated")}<span>Hand estimate</span><b class="num">21.6 MPa</b>${ev("computed")}</div>
      <div>${conv}</div><p>Hand estimate: a plain 56 × 6 plate with no gussets, so it reads high.</p>
      <div class="acts"><span class="pill pri">Make it lighter</span><span class="pill">Add to report</span><span class="pill quiet">Setup</span></div></div>
    ${pipe("r07 · 15 pass · 1 review")}</aside>`);

// ---- Make ----
const ROUTES = (sel) => [["ok", "3D print, FDM", "7 h 52 min", "simulated"], ["none", "Print simulation", "", `<span class="need">not run</span>`], ["ok", "CNC, 3-axis", "34 min", "simulated"], ["ok", "STEP with PMI", "214 kB", "computed"], ["stale", "Photo render", "", `<span class="need" style="color:var(--warn)">describes r05</span>`],
  ["none", "Flat pattern, DXF", "", `<span class="need">needs a sheet part</span>`, "dim"], ["none", "Robot files", "", `<span class="need">needs joints</span>`, "dim"], ["none", "Board and enclosure", "", `<span class="need">needs a board file</span>`, "dim"]].map((r, i) => srow(r[0], r[1], r[2], r[3], i === sel ? "sel" : r[4] || "")).join("");
const makePane = (sel, insp) => `<aside class="pane glass"><header><b>Make</b><span class="num">8</span><em>r07 · 3 current</em></header><div class="rows">${ROUTES(sel)}</div>${insp}${pipe("r07 · not released")}</aside>`;
if (S === "make-print") put(`${room(754, 520)}
  ${shot("plate", .76, 740, 380, (f, w, h) => img("plate-1", w))}
  ${topbar(2, { printer: true })}${convo(TITLE, `<div class="you">Print eight as prototypes before we mill.</div>
    <div class="step">${I("orient", 15)}Oriented back face down<span class="num">no supports</span></div><div class="step">${I("grid", 15)}Packed 8 parts on 2 plates<span class="num">180 × 180</span></div><div class="step">${I("layers", 15)}Sliced both plates in OrcaSlicer<span class="num">38 s</span></div>
    <p class="say">Eight fit on two plates: <span class="num">7 h 52 min</span><sup>1</sup> and <span class="num">198 g</span><sup>1</sup> of PETG. <span class="evw">Both are the slicer's simulation, not a print.</span></p>
    <p class="say">One thing to know: printed this way, the motor screws pull across the layers. Fine for a fit check, not for the belt load.</p>
    ${sources([["Slice of plates 1 and 2, r07", "simulated"], ["PETG profile, A1 mini 0.4", "specified"]])}`, "Ask, or describe a change…")}
  ${dock(2, "grid")}<div class="opts glass"><b>Plates</b><span class="on">Auto-pack</span><span>Gap 4 mm</span><i class="sep"></i><span>Add plate</span></div>${cube()}
  <div class="strip glass" style="padding-bottom:14px"><header><b>Plate 1 of 2</b><span>6 parts · 260 layers at 0.20 mm</span>${ev("simulated · slice")}</header>
    <div class="tline"><div class="ops"><span class="now" style="flex:5.8;--at:100%"><b style="font-weight:500">Plate 1</b>&nbsp;· 5 h 48 min · 149 g</span><span style="flex:2.07">Plate 2 · 2 h 04 min</span></div></div>
    <p><b>8 of 8 placed.</b> Nothing is sent to the printer from here: you open the plate in your slicer and start it there.</p></div>
  ${makePane(0, `<div class="insp"><h3>3D print, FDM<em><i class="dot ok"></i>current for r07</em></h3>
    <div class="big"><span class="num">7 h 52</span><span>min for 8 parts on 2 plates</span></div>
    <div class="kv"><span>Filament, PETG</span><b class="num">198 g</b>${ev("simulated")}<span>Supports</span><b class="num">none</b>${ev("computed")}<span>Layers</span><b class="num">260 × 0.20 mm</b>${ev("specified")}<span>Layer direction</span><b class="num" style="color:var(--warn)">review</b>${ev("heuristic")}</div>
    <p>Orientation is chosen for no supports. <b>Strength as printed is not simulated</b>; the study on Check is for a solid aluminium part.</p>
    <div class="acts"><span class="pill pri">Open in OrcaSlicer</span><span class="pill">${I("play", 12)}Watch it print</span></div></div>`)}`);
function pathLayer(f, w, h) { const z = 8.15, pts = []; let s = 1;
  for (let y = 0; y <= 30; y += 3) { pts.push([-19 * s, y, z], [19 * s, y, z]); s = -s; }
  const tool = f(6, 30, z);
  return `<svg class="sk" width="${w}" height="${h}"><path style="stroke-width:1.2;opacity:.9" d="${pl(f, pts.slice(0, -1).concat([[6, 30, z]]))}"/><circle class="pt" cx="${tool[0]}" cy="${tool[1]}" r="3"/></svg>`; }
if (S === "make-cam") put(`${room(754, 540)}
  ${shot("cam", 1, 754, 420, (f, w, h) => img("cam-stock", w) + pathLayer(f, w, h))}
  ${topbar(2)}${convo(TITLE, `<div class="you">Now the real one. Mill it from a 60 × 66 × 54 billet.</div>
    <div class="step">${I("mill", 15)}Planned 2 setups, 5 operations<span class="num">T1, T2</span></div><div class="step">${I("play", 15)}Simulated the stock, setup 1<span class="num">12 s</span></div>
    <p class="say">Setup 1 machines everything you can reach from the front: <span class="num">34 min</span><sup>1</sup>, no gouges found. The slots' far side needs setup 2.</p>
    <p class="say">Roughing leaves 2 mm steps on the gussets; the finishing pass takes them to size.</p>
    ${sources([["Stock simulation, setup 1, r07", "simulated"], ["Feeds for 6061, Ø6 carbide", "rule"]])}`, "Ask, or describe a change…")}
  ${dock(2, "mill")}<div class="opts glass"><b>Toolpath</b><span class="on">Stock</span><span>Paths</span><span>Left to cut</span><i class="sep"></i><span>Setup 1 of 2</span></div>${cube()}
  <div class="strip glass" style="padding-bottom:14px"><header><b>Setup 1 · Rough</b><span>T1 · Ø6 flat, 3 flutes · step down 2.0 mm</span>${ev("simulated · cell 0.1 mm")}</header>
    <div class="tline"><div class="ops"><span class="done" style="flex:1">Face</span><span class="now" style="flex:3.2;--at:98%"><b style="font-weight:500">Rough</b>&nbsp;· 98 %</span><span style="flex:1.7">Finish walls</span><span style="flex:1.5">Finish floor</span><span style="flex:1.2">Drill × 4</span><span style="flex:1">Bore</span></div></div>
    <p><b>Removed ${(CAM.removed_frac * CAM.stock_cm3).toFixed(1)} of ${CAM.stock_cm3.toFixed(1)} cm³.</b> Teal is within one step of the final surface. Nothing is sent to a machine from here.</p></div>
  ${makePane(2, `<div class="insp"><h3>CNC, 3-axis<em><i class="dot ok"></i>current for r07</em></h3>
    <div class="big"><span class="num">34</span><span>min, setup 1 of 2</span></div>
    <div class="kv"><span>Billet</span><b class="num">60 × 66 × 54 mm</b>${ev("stated")}<span>Allowance</span><b class="num">0.4 mm</b>${ev("specified")}<span>Gouges</span><b class="num">none found</b>${ev("simulated")}<span>Out of reach</span><b class="num">2 slot faces</b>${ev("computed")}</div>
    <p>The stock is a height map at 0.1 mm. <b>It does not model</b> tool deflection, chatter or clamping.</p>
    <div class="acts"><span class="pill pri">Export G-code</span><span class="pill">${I("play", 12)}Play</span><span class="pill quiet">Tools</span></div></div>`)}`);
