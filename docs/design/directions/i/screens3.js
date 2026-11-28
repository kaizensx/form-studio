// Direction I: the Bench open, the overview, the drawing sheet, Home, Settings, the palette.

// ---- The Bench, open: every job the design can be asked for, one sheet, four chapters ----
const BENCH = [["Design", "shape it", [["ok", "Contract", "measured, not ticked", "6 of 6", "computed"],
    ["none", "Make it lighter", "keeps every check passing", "", "", "sel"], ["none", "Optimise", "vary values toward a goal", "", ""], ["ok", "Variants", "saved alternatives", "2", "computed"], ["ok", "Refine", "1 change in r06", "r06", "computed"]]],
  ["Check", "prove it", [["warn", "Geometry checks", "1 wants a look", "15 of 16", "computed"], ["ok", "Mass properties", "centre, inertia", "105.2 g", "computed"], ["ok", "Strength, static", "250 N on the bore", "SF 19.4", "simulated"], ["none", "Vibration modes", "first natural frequencies", "", ""],
    ["ok", "Wall thickness", "thinnest wall", "5.0 mm", "computed"], ["ok", "Machinability", "3-axis, Ø6 tool", "2 setups", "rule"], ["ok", "Fit to NEMA 17", "pilot and screws", "98 %", "modelled"],
    ["none", "Draft for moulding", "needs process: moulding", "", "", "dim"], ["none", "Interference", "needs two parts", "", "", "dim"], ["none", "Motion", "needs joints", "", "", "dim"]]],
  ["Make", "produce it", [["ok", "3D print, FDM", "8 parts, 2 plates", "7 h 52 min", "simulated"], ["none", "Print simulation", "layer by layer, with warnings", "", ""], ["ok", "CNC, 3-axis", "setup 1 of 2", "34 min", "simulated"],
    ["ok", "STEP with PMI", "5 tolerances", "214 kB", "computed"], ["stale", "Photo render", "describes r05", "stale", ""], ["none", "Flat pattern, DXF", "needs a sheet part", "", "", "dim"], ["none", "Robot files", "needs joints", "", "", "dim"], ["none", "Board and enclosure", "needs a board file", "", "", "dim"]]],
  ["Document", "hand it over", [["ok", "Drawing, A4", "dimensioned once", "14 of 14", "computed"], ["ok", "Parts list", "mount, fasteners", "3 lines", "computed"], ["ok", "Standard parts", "M3 × 8, M5 T-nut", "6", "specified"],
    ["none", "Assembly steps", "a PDF, one step a page", "", ""], ["none", "Test plan", "what to measure after making", "", ""], ["none", "Results report", "studies and checks in one file", "", ""], ["none", "Release", "a person approves, never the agent", "", "", "req"]]]];
const bentry = ([d, n, sub, v, e, st]) => `<div class="be ${st || ""}"><i class="dot ${d}"></i><div class="t"><b>${n}</b><span class="sub">${sub}</span></div><div class="r">${v ? `<span class="num" ${d === "stale" ? `style="color:var(--warn)"` : ""}>${v}</span>` : st === "dim" ? "" : `<span class="run">${st === "req" ? "Request" : "Run"}</span>`}${e ? ev(e) : ""}</div></div>`;
if (S === "bench") put(`${room(754, 610, { dim: true })}
  ${topbar(1, { bench: true })}${convo(TITLE, reply + handnote, "Ask, or describe a change…")}
  <section class="sheetp glass deep" style="left:372px;top:76px;right:20px;bottom:20px">
    <header><h2>Bench</h2><span class="num">Motor mount · r07</span><span class="segs" style="margin-left:14px"><b class="on">All 30</b><b>Current 15</b><b>Stale 1</b><b>Not run 8</b><b>Needs something 6</b></span><span class="find">${I("search", 15)}Find a job<kbd>/</kbd></span></header>
    <div class="cols">${BENCH.map(([n, sub, list], i) => `<div class="col"><h3>${n}<span>${sub}</span><em>${list.filter((r) => r[0] === "ok" || r[0] === "warn").length} of ${list.length}</em></h3>${list.map(bentry).join("")}</div>`).join("")}</div>
    <div class="abs card" style="left:26px;right:26px;bottom:22px;grid-template-columns:1fr auto;align-items:center;gap:6px 20px;padding:14px 16px">
      <h4 style="grid-column:1/-1"><i class="dot none"></i>Make it lighter<em>not run · uses your agent · about 3 min</em></h4>
      <p style="color:var(--ink2)">Sends exactly this: <span style="color:var(--ink)">“Reduce the mass of Motor mount r07. Keep the strength safety factor at 4 or more at 250 N and every check passing. Show the change as a draft.”</span></p>
      <div class="acts" style="margin:0"><span class="pill pri">Run</span><span class="pill">Edit the request</span><span class="pill quiet">${I("star", 13)}Pin</span></div></div>
    <div class="legend abs" style="left:34px;bottom:118px"><span><i class="dot ok"></i>current for r07</span><span><i class="dot warn"></i>wants a look</span><span><i class="dot stale"></i>stale: describes an older revision</span><span><i class="dot none"></i>not run</span><span style="opacity:.55"><i class="dot none"></i>dimmed: says what it needs</span></div>
  </section>`);

// ---- The overview of a design (the design capsule): what is known, decided and still open ----
const orow = (a, b, c, d = "ok") => `<div class="be" style="height:46px"><i class="dot ${d}"></i><div class="t"><b>${a}</b><span class="sub">${b}</span></div><div class="r">${c}</div></div>`;
if (S === "overview") put(`${room(754, 610, { dim: true })}
  ${topbar(0)}${convo(TITLE, reply + handnote, "Ask, or describe a change…")}
  <section class="sheetp glass deep" style="left:372px;top:76px;right:20px;bottom:20px">
    <header><h2>Motor mount</h2><span class="num">r07 · unreleased · 3D model, to be milled</span><span class="find">${I("search", 15)}Search this design<kbd>/</kbd></span></header>
    <p style="font-size:14px;line-height:21px;color:var(--ink2);margin-top:12px;max-width:720px">An L-shaped mount that holds a NEMA 17 motor on a 2020 rail, with two gussets. Written by the agent from the brief and the renders; you can edit it.</p>
    <div class="cols" style="grid-template-columns:1.15fr 1fr 1fr">
      <div class="col"><h3>Contract<span>what must be true</span><em>6 of 6</em></h3>
        ${orow("Pilot bore Ø22.0", "specified: NEMA ICS 16", `<span class="num">22.000</span>${ev("computed")}`)}${orow("4 × Ø3.4 on a 31.0 square", "specified: NEMA ICS 16, ISO 273", `<span class="num">31.000</span>${ev("computed")}`)}
        ${orow("Slots for M5, 26.0 apart", "stated by you", `<span class="num">26.000</span>${ev("computed")}`)}${orow("Rail slot is 6.2 wide", "measured by you, calipers", `<span class="num">6.2 mm</span>${ev("measured")}`)}
        ${orow("Fits a 60 × 66 × 54 billet", "stated by you", `<span class="num">56 × 62 × 52</span>${ev("computed")}`)}${orow("Safety factor ≥ 4 at 250 N", "belt pull is assumed, not measured", `<span class="num">19.4</span>${ev("simulated")}`)}</div>
      <div class="col"><h3>Decisions<span>with where they were taken</span><em>3</em></h3>
        ${orow("Two gussets, not a thicker plate", "conversation, 26 Nov · r02", `<span class="num">r02</span>`)}${orow("Root fillet 4.0 mm", "refine, after the first study · r06", `<span class="num">r06</span>`)}${orow("Back face is datum B", "drawing, sheet 1 · r07", `<span class="num">r07</span>`)}
        <h3 style="margin-top:14px">Open questions<span></span><em>2</em></h3>
        ${orow("Is the belt pull steady or cyclic?", "changes whether fatigue matters", `<span class="run">Answer</span>`, "warn")}${orow("Anodised or bare?", "changes the fit of the pilot bore", `<span class="run">Answer</span>`, "warn")}</div>
      <div class="col"><h3>Files<span>by kind</span><em>12</em></h3>
        ${orow("Exports", "STEP with PMI, STL, G-code", `<span class="num">3</span>`)}${orow("Studies", "strength, thickness, machinability, fit", `<span class="num">6</span>`)}${orow("Documents", "drawing, parts list", `<span class="num">2</span>`)}${orow("References", "NEMA ICS 16, frame 17 (PDF)", `<span class="num">1</span>`)}
        <h3 style="margin-top:14px">Family<span></span><em>2</em></h3>
        ${orow("Motor mount", "this design · r07", `<span class="num">105.2 g</span>`)}${orow("Motor mount, lighter", "variant from r05, not checked since", `<span class="num" style="color:var(--warn)">stale</span>`, "stale")}</div>
    </div>
    <div class="abs" style="left:34px;right:34px;bottom:92px"><h3 style="font-size:14px;font-weight:600;display:flex;gap:9px;align-items:baseline">Revisions<span style="font:400 12px var(--sans);color:var(--ink3)">who changed what</span></h3>
      <div style="position:relative;height:74px;margin-top:10px"><i class="abs" style="left:6px;right:14%;top:6px;height:1px;background:var(--line)"></i>${[["r01", "first build", "spark"], ["r02", "gussets", "spark"], ["r03", "bore and screws", "spark"], ["r04", "contract proved", "spark"], ["r05", "slots", "user"], ["r06", "root fillet", "wand"], ["r07", "chamfers", "user"]].map(([r, t, w], i) => `<div class="abs" style="left:${i * 14.3}%;top:0;display:grid;gap:5px;justify-items:start"><i class="dot ${i === 6 ? "run" : "ok"}" style="width:13px;height:13px;background:${i === 6 ? "var(--accent)" : "var(--ink2)"};border:3px solid var(--bg)"></i><b class="num" style="font-size:12px;${i === 6 ? "color:var(--accent)" : ""}">${r}</b><span style="font-size:12px;color:var(--ink2);display:flex;gap:6px;align-items:center;white-space:nowrap">${I(w, 12)}${t}</span></div>`).join("")}</div></div>
    <div class="abs" style="left:34px;right:34px;bottom:26px;display:flex;align-items:center;gap:8px"><span class="pill">Revisions and branches</span><span class="pill">Export as one file</span><span class="pill">Duplicate</span><span class="pill quiet" style="margin-left:auto">${I("trash", 13)}Move to the trash</span></div>
  </section>`);

// ---- Document: a drawing sheet made from the solid (views by the kernel's hidden-line removal) ----
function drawing() { const T = 3.7, ar = (x, y, a) => { const c = Math.cos(a), s = Math.sin(a), p = (dx, dy) => `${(x + dx * c - dy * s).toFixed(2)} ${(y + dx * s + dy * c).toFixed(2)}`; return `<path class="ar" d="M${x} ${y}L${p(2.6, .55)}L${p(2.6, -.55)}Z"/>`; };
  const hd = (x1, x2, y, ya, t) => { const e = y > ya ? 1.2 : -1.2; return `<path class="dm" d="M${x1} ${ya + e}V${y + e}M${x2} ${ya + e}V${y + e}M${x1} ${y}H${x2}"/>${ar(x1, y, 0)}${ar(x2, y, Math.PI)}<text x="${(x1 + x2) / 2}" y="${y - 1.3}" text-anchor="middle">${t}</text>`; };
  const vd = (y1, y2, x, xa, t) => { const e = x > xa ? 1.2 : -1.2; return `<path class="dm" d="M${xa + e} ${y1}H${x + e}M${xa + e} ${y2}H${x + e}M${x} ${y1}V${y2}"/>${ar(x, y1, Math.PI / 2)}${ar(x, y2, -Math.PI / 2)}<text transform="translate(${x - 1.3} ${(y1 + y2) / 2}) rotate(-90)" text-anchor="middle">${t}</text>`; };
  const view = (n, x, y, s = 1) => `<g transform="translate(${x} ${y}) scale(${s})"><path class="hid" d="${HLR[n].hid}"/><path class="vis" d="${HLR[n].vis}"/></g>`;
  const frame = (x, y, cells, sel) => { let cx = x, out = sel ? `<rect class="sel" x="${x - 1.2}" y="${y - 1.2}" width="${cells.reduce((a, c) => a + c[1], 0) + 2.4}" height="8" rx="1"/>` : "";
    for (const [t, wd] of cells) { out += `<rect class="dm" x="${cx}" y="${y}" width="${wd}" height="5.6"/>` + (t === "pos" ? `<circle class="dm" cx="${cx + wd / 2}" cy="${y + 2.8}" r="1.5"/><path class="dm" d="M${cx + wd / 2 - 2.3} ${y + 2.8}h4.6M${cx + wd / 2} ${y + .5}v4.6"/>` : t === "perp" ? `<path class="dm" d="M${cx + wd / 2 - 1.9} ${y + 4.4}h3.8M${cx + wd / 2} ${y + 4.4}v-3.4"/>` : `<text x="${cx + wd / 2}" y="${y + 4.1}" text-anchor="middle">${t}</text>`); cx += wd; } return out; };
  const datum = (x, y, l, dir) => dir === "d" ? `<path class="ar" d="M${x - 1.7} ${y}h3.4l-1.7 2.6z"/><path class="dm" d="M${x} ${y + 2.6}v2.4"/><rect class="dm" x="${x - 2.8}" y="${y + 5}" width="5.6" height="5.6"/><text x="${x}" y="${y + 9.1}" text-anchor="middle">${l}</text>`
    : `<path class="ar" d="M${x} ${y - 1.7}v3.4l2.6-1.7z"/><path class="dm" d="M${x + 2.6} ${y}h2.4"/><rect class="dm" x="${x + 5}" y="${y - 2.8}" width="5.6" height="5.6"/><text x="${x + 7.8}" y="${y + 1.3}" text-anchor="middle">${l}</text>`;
  const F = [78, 128], Tp = [78, 50], R = [158, 128];
  return `<rect class="frame" x="8" y="8" width="281" height="194"/>
    ${view("top", ...Tp)}${view("front", ...F)}${view("right", ...R)}${view("iso", 238, 68, .78)}
    <path class="ctr" d="M62 124h32M78 108v32M58 108.500h9M62.500 104v9M89 108.500h9M93.500 104v9M58 139.500h9M62.500 135v9M89 139.500h9M93.500 135v9M65 45v22M91 45v22M172 124h18"/>
    ${hd(50, 106, 172, 159, "56")}${vd(97, 159, 13.5, 50, "62")}${hd(62.5, 93.5, 90, 108.5, "31")}${vd(108.5, 139.5, 114, 93.5, "31")}
    <path class="dm" d="M87 117.700L108 103h16"/>${ar(87, 117.7, -.61)}<text x="109" y="101.700">⌀22 H7</text>
    <path class="dm" d="M61.300 140.700L50 149H19"/>${ar(61.3, 140.7, 2.51)}<text x="19" y="147.700">4 × ⌀3.4</text>${frame(19, 151, [["pos", 6], ["⌀0.2", 12], ["A", 5.6], ["B", 5.6]], 1)}
    ${datum(96, 159, "A", "d")}
    ${vd(24, 76, 40, 50, "52")}${hd(65, 91, 17, 48, "26")}<path class="dm" d="M93.300 53L111 42h26"/>${ar(93.3, 53, -.56)}<text x="112" y="40.700">2 × 5.5 × 16</text>
    ${hd(178, 184, 90, 97, "6")}${vd(153, 159, 126, 132, "6")}${hd(146, 178, 166, 153, "32")}${vd(124, 159, 196, 184, "35")}
    ${datum(184, 112, "B", "r")}<path class="dm" d="M167.600 106.800H178"/>${ar(178, 106.8, Math.PI)}${frame(148, 104, [["perp", 6], ["0.1", 8], ["A", 5.6]])}
    <rect class="frame" x="187" y="162" width="102" height="40"/><path class="thin" d="M187 176h102M187 189h102M238 176v26M263.500 189v13"/>
    <text class="ttl" x="191" y="171.200">Motor mount</text><text class="ink" x="285" y="170.600" text-anchor="end">r07</text>
    <text class="ink" x="191" y="184">6061-T6</text><text class="ink" x="242" y="184">105.2 g, computed</text>
    <text class="ink" x="191" y="197">ISO 2768-mK</text><text class="ink" x="242" y="197">1 : 1</text><text class="ink" x="267.500" y="197">A4 · 1/1</text>
    <path class="thin" d="M266 16.500h8l6 -2v9l-6 -2h-8zM283 19h.01"/><circle class="thin" cx="284" cy="19" r="2.200"/><circle class="thin" cx="284" cy="19" r="4.400"/>`; }
const DOCS = [["ok", "Drawing, A4", "14 of 14", "computed", "sel"], ["ok", "Parts list", "3 lines", "computed"], ["ok", "Standard parts", "6", "specified"], ["none", "Assembly steps", "", `<span class="need">not run</span>`], ["none", "Test plan", "", `<span class="need">not run</span>`], ["none", "Results report", "", `<span class="need">not run</span>`], ["none", "Release", "", `<span class="need">not requested</span>`]];
if (S === "drawing") put(`${room(540, 560, { pool: false })}
  ${topbar(3)}${dock(3, "gdt", 20)}
  <div class="paper ${document.body.dataset.paper ? "day" : ""}" style="left:96px;top:84px;width:891px;height:630px"><svg viewBox="0 0 297 210" width="891" height="630">${drawing()}</svg></div>
  <p class="readout num" style="left:98px;bottom:142px">Sheet 1 of 1<i>·</i>A4 landscape<i>·</i>1 : 1<i>·</i>third angle</p>
  <p class="hint" style="left:500px;width:487px;bottom:142px;text-align:right"><kbd class="k">Space</kbd>hold to see the part<kbd class="k">P</kbd>paper preview</p>
  <div class="abs glass" style="left:241px;width:600px;bottom:20px;border-radius:26px;padding:6px"><div class="well" style="display:flex;align-items:center;padding:8px 8px 8px 14px">${prompt("tighten the hole pattern to 0.1", { scope: "On 1 tolerance", typed: true })}<span class="agent" style="display:flex;gap:7px;align-items:center;font-size:12.5px;color:var(--ink2);margin:0 12px;white-space:nowrap">${I("spark", 15)}${D.agent}</span><span class="send">${I("enter", 15, 2)}</span></div></div>
  <aside class="pane glass"><header><b>Document</b><span class="num">7</span><em>r07 · 3 current</em></header><div class="rows">${DOCS.map(([d, n, v, e, st]) => srow(d, n, v, e, st)).join("")}</div>
    <div class="insp"><h3>Drawing, sheet 1<em><i class="dot ok"></i>current for r07</em></h3>
      <div class="big"><span class="num">14 of 14</span><span>dimensioned once</span></div>
      <div class="kv"><span>Hole position</span><b class="num field hot">Ø0.2 | A | B</b>${ev("specified")}<span>Squareness</span><b class="num">0.1 | A</b>${ev("specified")}<span>General</span><b class="num">ISO 2768-mK</b>${ev("specified")}<span>In the STEP</span><b class="num">5 of 5</b>${ev("computed")}</div>
      <p><b>Made from the solid.</b> Views are the kernel's hidden-line projection; change the part and the sheet follows. A tolerance is a statement to the shop: nothing here says a made part meets it.</p>
      <div class="acts"><span class="pill pri">Export PDF</span><span class="pill">DXF</span><span class="pill quiet">Check a drawing…</span></div></div>
    ${pipe("r07 · not released")}</aside>`);

// ---- Home ----
if (S === "home") { const th = (slug, w) => slug === "motor-mount" ? `<img class="thumb" src="assets/thumb-motor-mount.webp" width="${w + 62}" style="margin:-30px 0 -26px">` : thumb(slug, w);
  put(`<div class="room home"></div>
  <div class="cap tl bare">${LOGO(17)}</div><div class="cap tr glass"><span class="btn">${I("search", 16)}<kbd>⌘K</kbd></span><span class="btn">${I("gear", 16)}</span></div>
  <section class="ask"><p class="over">Good evening</p><h1>What do you want to make?</h1>
    <div class="cmd glass"><div class="well">${prompt("A planetary gearbox for a NEMA 17 motor, about 1:16")}<footer><span class="att">${I("clip", 16)}Photo or file</span><span class="att">${I("pen", 16)}Sketch</span><span class="att">${I("link", 16)}Link</span><span class="att">${I("mic", 16)}</span><span class="go">Design it${I("enter", 15, 2)}</span></footer></div>
      <div class="sugg"><span><kbd class="k">1</kbd>Start blank</span><span><kbd class="k">2</kbd>Replace a broken part</span><span><kbd class="k">3</kbd>Continue “Motor mount” · r07 · 2 min ago</span></div></div>
    <div class="under"><span>Make it for<span class="segs"><b class="on">Anything</b><b>My printer</b><b>A mill</b></span></span><span>${I("spark", 15)}${D.agent}${I("down", 12)}</span></div></section>
  <section class="shelf"><header><h2>Designs</h2><span class="num">8 · 1 released</span><span class="segs"><b class="on">All</b><b>In progress</b><b>Released</b></span><span class="link">${I("sort", 15)}Last changed</span><span class="link">${I("import", 15)}Import…</span><span class="link">${I("trash", 15)}Trash · 2</span></header>
    <div class="objects">${[["Motor mount", "r07", "", "motor-mount", `<i class="dot warn"></i>1 check to review · 2 min ago`], ["Echo dock", "r01", "Released", "echo-dock", "Device dock · yesterday"], ["Kilo box", "r01", "", "kilo-box", "Electronics enclosure · 3 days ago"]].map(([n, rev, st, slug, sub]) =>
      `<figure><div class="plinth">${th(slug, 188)}</div><figcaption><b>${n}</b><span class="num">${rev}</span>${st ? `<span class="tag ok">${st}</span>` : ""}<em>${sub}</em></figcaption></figure>`).join("")}
      <figure><div class="plinth"><div class="glass" style="width:124px;height:124px;border-radius:50%;display:grid;place-items:center;position:relative"><b class="num" style="font-size:22px;font-weight:500;color:var(--ink2)">+5</b></div></div><figcaption><b>All 8 designs</b>${I("right", 13)}<em>Bravo bin and four more</em></figcaption></figure></div></section>`); }

// ---- Settings ----
const ENG = [["ok", "CAD kernel", "every design: build123d on OCCT", "Apache-2.0", "in the app", "Installed"], ["ok", "Strength solver", "studies with a stated error: Netgen, scikit-fem", "LGPL-2.1, BSD-3", "138 MB", "Installed"],
  ["ok", "Toolpaths", "3-axis CAM and the stock simulation", "MIT", "22 MB", "Installed"], ["ok", "OrcaSlicer", "slices on your printer's own profiles, as its own program", "AGPL-3.0", "your copy", "Found"],
  ["none", "CalculiX", "a second opinion on strength, run as its own program", "GPL-2.0", "41 MB", "Install"], ["none", "Blender", "photoreal renders, as its own program", "GPL-3.0", "your copy", "Not found"], ["none", "KiCad", "boards and their enclosures, as its own program", "GPL-3.0", "your copy", "Not found"]];
if (S === "settings") put(`<div class="room dimmed" style="--px:720px;--py:300px"></div>
  <div class="cap tl bare">${LOGO(17)}</div><div class="cap tr glass"><span class="btn">${I("search", 16)}<kbd>⌘K</kbd></span><span class="btn on">${I("gear", 16)}</span></div>
  <section class="sheetp glass deep set" style="left:120px;right:120px;top:76px;bottom:28px;display:grid;grid-template-columns:208px 1fr;gap:0 30px;padding:22px 30px 22px 18px">
    <div><h2 style="font:600 24px/36px var(--sans);letter-spacing:-.03em;padding:0 12px 14px">Settings</h2><div class="nav">${[["gear", "General", 1], ["spark", "Agents and models"], ["box3", "Engines"], ["printer", "Printing"], ["mill", "Machining"], ["layers", "Materials"], ["palette", "Appearance"], ["key", "Keys"], ["lock", "Privacy"], ["info", "About"]].map(([ic, n, on]) => `<span class="${on ? "on" : ""}">${I(ic, 16)}${n}</span>`).join("")}</div></div>
    <div style="padding-top:6px"><h3>Set up for</h3><p>What this copy of Form Studio is for. Each choice installs only what it needs, after you click.</p>
      <div class="tiles">${[["Parametric CAD", "always on", "Describe it, build it, edit it. The kernel ships with the app.", 1], ["Strength and checks", "138 MB", "Studies with a stated error, mass, machinability.", 1], ["Machining", "22 MB", "Toolpaths and a stock simulation for a 3-axis mill.", 1],
        ["3D printing", "your slicer", "Plates, slices and print simulation. Off until you turn it on.", 1], ["Photoreal renders", "needs Blender", "Product pictures of a design.", 0], ["Boards", "needs KiCad", "A board and its enclosure, kept in step.", 0]].map(([n, sz, p, on]) => `<div class="tile ${on ? "on" : ""}"><b>${n}</b><i class="switch ${on ? "" : "off"}"></i><p>${p} <span class="num">${sz}</span></p></div>`).join("")}</div>
      <h3 style="margin-top:26px">Engines</h3><p>Named with their licence and size. Nothing is downloaded until you choose Install.</p>
      <div style="margin-top:12px">${ENG.map(([d, n, what, lic, sz, st]) => `<div class="erow"><i class="dot ${d}"></i><b>${n}</b><span>${what}</span><span class="num" style="text-align:left">${lic} · ${sz}</span><span class="pill ${st === "Install" ? "" : "quiet"}">${st}</span></div>`).join("")}</div>
      <p class="note" style="margin-top:16px;font-size:12.5px;align-items:center">${I("lock", 15)}<span>Designs stay on this Mac. No usage data is collected. Form Studio never starts a print, a machine or an upload.</span></p>
    </div></section>`);

// ---- The command palette ----
const PAL = [["Tools", [["fillet", "<mark>Fil</mark>let edges", "", `<kbd class="k">F</kbd>`, 1], ["scan", "Measure a <mark>fil</mark>let radius", "", `<kbd class="k">M</kbd>`]]],
  ["In Motor mount", [["cube", "07 Root <mark>fil</mark>let", "feature · r 4.0 mm", ev("refine, r06")], ["pulse", "Strength, static", "peak is at the root <mark>fil</mark>let", `<span class="num">SF 19.4</span>`], ["printer", "<mark>Fil</mark>ament, PETG", "3D print route", `<span class="num">198 g</span>`]]],
  ["Everywhere", [["chat", "“…a larger <mark>fil</mark>let would move the peak…”", "conversation, 26 Nov", ""], ["folder", "Open a <mark>fil</mark>e…", "STEP, STL, 3MF, PDF, a Form Studio design", `<kbd class="k">⌘O</kbd>`], ["gear", "Settings › Printing › <mark>Fil</mark>aments", "", ""]]]];
if (S === "palette") put(`${room(754, 610)}${partShot("mount-s8")}
  ${topbar(0)}${convo(TITLE, reply + handnote, "Ask, or describe a change…")}${dock(0, "cursor")}${cube()}${readout()}
  <aside class="pane glass">${tree({})}<div class="rb rest"><i></i></div><div class="insp"><h3>Motor mount<em>r07 · 30 faces</em></h3><p>Pick a feature here or on the part to change it. Drag the bar to step back in time.</p></div>${pipe("r07 · 15 pass · 1 review")}</aside>
  <div class="veil"></div>
  <div class="pal glass deep"><div class="well lit">${prompt("fil", { typed: true })}<span class="tag">Motor mount</span></div>
    ${PAL.map(([g, rows]) => `<div class="grp">${g}</div>` + rows.map(([ic, t, sub, r, sel]) => `<div class="pr ${sel ? "sel" : ""}">${I(ic, 16)}<b>${t}${sub ? `<span>${sub}</span>` : ""}</b><i></i>${r}</div>`).join("")).join("")}
    <footer><span><kbd class="k">↑</kbd><kbd class="k">↓</kbd>move</span><span><kbd class="k">Enter</kbd>run</span><span><kbd class="k">Tab</kbd>search everywhere</span><span><kbd class="k">?</kbd>every key</span></footer></div>`);
