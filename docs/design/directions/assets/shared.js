// Shared by the three direction mockups: the real data, the icons, the part pictures and the token sheet.
// Every value below is read off the app's own screenshots of 2026-11 (Sensor case r01, Built box r01, Home):
// nothing is invented. The part pictures are the app's 3D view, cut out by tools/cutout.py.

const LIGHT = new URLSearchParams(location.search).get("theme") === "light";
document.documentElement.classList.add(LIGHT ? "light" : "dark");
const THEME = LIGHT ? "light" : "dark";

const DATA = {
  design: { name: "Sensor case", rev: "r01", state: "Unreleased", printer: "Bambu Lab A1 mini 0.4 nozzle",
    dims: ["108.0", "160.0", "32.0"], volume: "61.2", note: "as printed, 2 parts" },
  stages: [["01", "Describe", "0/10 measured", ""], ["02", "Design", "13 features", "on"], ["03", "Fit", "99% modelled", "pass"],
    ["04", "Review", "2 to review", "warn"], ["05", "Make", "Ready", ""]],
  features: [["Shell", "Structure"], ["Cavity", "Access"], ["Corner bosses", "Structure"],
    ["Insert / screw holes", "Interface", "Heat-set insert pockets or self-tap pilot holes"], ["PCB standoffs", "Interface"],
    ["Board screw holes", "Interface"], ["USB-C openings", "Access"], ["Round holes", "Access"], ["Lid", "Structure"],
    ["Lid lip", "Interface", "Keeps the lid square on the box."], ["Lid screw holes", "Interface"], ["Vent slots", "Access"],
    ["Label and stamp", "Finish"]],
  pipeline: [["Parameters", "r01", "pass"], ["Solid", "131 faces", "pass"], ["Exports", ".step .stl .obj .glb", "pass"],
    ["Checks", "15 pass · 2 review", "pass"], ["Slice", "1 h 36 min", "pass"], ["Release", "ready", "idle"]],
  chat: { title: "New conversation", lead: "Ask about this design, or describe a change.",
    body: "The agent works on the design with Form Studio’s tools. Changes arrive as a draft or a new revision you can compare and undo.",
    suggestions: ["Explain the 2 warnings on r01", "Review r01: design, engineering, print", "Make it lighter without failing a check",
      "What should I measure before printing?"],
    placeholder: "Ask about Sensor case, or describe a change…", agent: "Test agent · Default",
    hint: "Enter sends · Shift+Enter for a new line · drop files to attach" },
  views: ["Iso", "Front", "Side", "Top", "Under"],
  tools: [["cursor", "Select"], ["sketch", "Sketch"], ["pin", "Annotate"], ["scissors", "Section"], ["scan", "Measure"],
    ["boxes", "Assembly"], ["history", "History"], ["layers", "Print layers"], ["camera", "Render"], ["expand", "Fit view"],
    ["ruler", "Dimensions"]],
  build: { name: "Built box", rev: "r01", state: "Unreleased", step: 6, of: 12, feature: "Board screw holes",
    dims: ["108.0", "160.0", "32.0"], volume: "61.2", note: "as modelled, 2 parts",
    stages: [["01", "Describe", "0/10 measured", ""], ["02", "Design", "13 features", "on"], ["03", "Review", "All pass", "pass"],
      ["04", "Make", "Ready", ""]],
    pipeline: [["Parameters", "r01", "pass"], ["Solid", "131 faces", "pass"], ["Exports", ".step .stl .obj .glb", "pass"],
      ["Checks", "12 pass", "pass"], ["Release", "ready", "idle"]],
    suggestions: ["Review r01: design and engineering", "Make it lighter without failing a check", "Which dimensions are still assumed?"],
    placeholder: "Ask about Built box, or describe a change…" },
  home: { hello: "Good afternoon", ask: "What do you want to make?",
    placeholder: "A planetary gearbox for a NEMA 17 motor, about 1:16", attach: [["clip", "Photo or file"], ["pen", "Sketch"], ["link", "Link"]],
    go: "Design it", purposes: ["Anything", "Game asset"], agent: "Test agent · Default",
    starts: [["square", "Start blank"], ["wrench", "Replace a broken part"]], resume: "Continue “Echo dock” · r01 · just now",
    count: "7", released: "1 released", filters: ["All", "In progress", "Released"], sort: "Last changed",
    designs: [["Echo dock", "Device dock", "r01", "Released", "echo-dock"], ["Kilo box", "Electronics enclosure", "r01", "", "kilo-box"],
      ["Bravo bin", "Gridfinity-style bin", "r01", "", "bravo-bin"]],
    extra: ["Delta coupon", "Fit coupon", "r01", "", ""],
    foot: "Every design is built in a real CAD kernel and checked. Nothing uploads on its own." },
};

const P = {
  cursor: "M5 4l6.5 15 2.2-6.3L20 10.5z", sketch: "M4 20l1-4.5L16 4.5l3.5 3.5L8.5 19zM13.5 7l3.5 3.5",
  pin: "M12 21s-6.5-5.6-6.5-10.5a6.5 6.5 0 0113 0C18.5 15.4 12 21 12 21zM12 8.5a2 2 0 100 4 2 2 0 000-4z",
  scissors: "M6 3.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM6 15.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM8 8l12 10.5M8 16L20 5.5",
  scan: "M4 8V5h3M17 5h3v3M20 16v3h-3M7 19H4v-3M8 12h8",
  boxes: "M12 3l4 2.2v4.4L12 12 8 9.6V5.2zM7 12l4 2.2v4.4L7 21l-4-2.4v-4.4zM17 12l4 2.2v4.4L17 21l-4-2.4v-4.4z",
  history: "M4.5 12A7.5 7.5 0 1012 4.5 7.6 7.6 0 006.6 6.9L4.5 9M4.5 4.5V9H9M12 8v4.2l2.8 1.6",
  layers: "M12 3.5l8.5 4.5-8.5 4.5L3.5 8zM3.5 12l8.5 4.5 8.5-4.5M3.5 16l8.5 4.5 8.5-4.5",
  camera: "M4 8h3.2l1.6-2.5h6.4L16.8 8H20v11H4zM12 10.2a3.3 3.3 0 100 6.6 3.3 3.3 0 000-6.6z",
  expand: "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7", ruler: "M3 16L16 3l5 5L8 21zM7 12l2 2M10 9l2 2M13 6l2 2",
  search: "M11 4.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM20 20l-4.4-4.4",
  gear: "M4 7h9M17 7h3M4 17h3M11 17h9M15 4.5v5M9 14.5v5",
  clip: "M20 11.2l-8.4 8.4a5 5 0 01-7.1-7.1L13 4a3.3 3.3 0 014.7 4.7l-8.3 8.4a1.7 1.7 0 01-2.4-2.4L14.8 7",
  right: "M5 12h14M13 6l6 6-6 6", up: "M12 19V5M6 11l6-6 6 6", down: "M6 9l6 6 6-6", chev: "M9 6l6 6-6 6", plus: "M12 5v14M5 12h14",
  mic: "M12 3a3 3 0 00-3 3v5a3 3 0 006 0V6a3 3 0 00-3-3zM5.5 11a6.5 6.5 0 0013 0M12 17.5V21",
  link: "M10 14a4.5 4.5 0 006.4 0l3-3A4.5 4.5 0 0013 4.6l-1.2 1.2M14 10a4.5 4.5 0 00-6.4 0l-3 3A4.5 4.5 0 0011 19.4l1.2-1.2",
  pen: "M4 20l1-4.5L16 4.5l3.5 3.5L8.5 19z", folder: "M3.5 6.5h6l2 2.5h9v10.5h-17z", import: "M12 4v10M8 10.5l4 4 4-4M4 16v4h16v-4",
  sort: "M7 4v16M3.5 16.5L7 20l3.5-3.5M17 20V4M13.5 7.5L17 4l3.5 3.5", grid: "M4 4h16v16H4zM4 9.3h16M4 14.6h16M9.3 4v16M14.6 4v16",
  printer: "M7 8V4h10v4M7 17H4V9h16v8h-3M7 14h10v6H7z", panel: "M4 5h16v14H4zM9.5 5v14", stop: "M7 7h10v10H7z",
  check: "M5 12.5l4.5 4.5L19 7.5", spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z",
  wrench: "M14.5 6.5a4 4 0 005 5L10 21l-3-3 9.5-9.5a4 4 0 00-2-2zM14.5 6.5l3-3 3 3-3 3", square: "M5 5h14v14H5z",
  chat: "M4 5h16v11H10l-4 4v-4H4z", play: "M8 5l11 7-11 7z", dot: "M12 10a2 2 0 100 4 2 2 0 000-4z",
};
const I = (n, s = 18, w = 1.6) => `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"><path d="${P[n]}"/></svg>`;

// The logo is the brand's own lockup, unchanged (brand/lockup.svg, brand/lockup-light.svg).
const LOGO = (h = 16) => `<img class="logo" alt="Form Studio" height="${h}" src="../assets/${LIGHT ? "lockup-light" : "lockup"}.svg">`;
const MARK = (h = 18) => `<img class="mark" alt="" height="${h}" src="../assets/mark.svg">`;

// A part picture with its dimension lines. Coordinates are in the cut-out's own pixels (1.44 per CSS pixel of the app).
const PARTS = {
  case: { src: "part-sensor-case", w: 989, h: 695,
    dims: [[-35, 55, -35, 212, "32.0"], [-35, 220, 446, 708, "160.0"], [456, 712, 1012, 596, "108.0"]] },
  build: { src: "part-build-6of12", w: 740, h: 424,
    dims: [[-35, 55, -35, 212, "32.0"], [-35, 220, 134, 423, "76.0"], [144, 428, 732, 348, "108.0"]] },
};
function part(kind, width, { dims = true, shadow = true } = {}) {
  const p = PARTS[kind], k = width / p.w, src = `../assets/${p.src}-${THEME}.png`;
  const lines = !dims ? "" : `<svg class="dimlines" viewBox="0 0 ${p.w} ${p.h}" width="${width}" height="${p.h * k}">` +
    p.dims.map(([a, b, c, d]) => `<line x1="${a}" y1="${b}" x2="${c}" y2="${d}"/><circle cx="${a}" cy="${b}" r="3.5"/><circle cx="${c}" cy="${d}" r="3.5"/>`).join("") + "</svg>" +
    p.dims.map(([a, b, c, d, t]) => `<span class="dim" style="left:${(a + c) / 2 * k}px;top:${(b + d) / 2 * k}px">${t}</span>`).join("");
  return `<div class="part" style="width:${width}px;height:${p.h * k}px">${shadow ? `<img class="cast" src="${src}" width="${width}">` : ""}<img class="solid" src="${src}" width="${width}">${lines}</div>`;
}
const thumb = (slug, width) => slug ? `<img class="thumb" src="../assets/thumb-${slug}-dark.png" width="${width}">` : "";

// The token sheet, the same layout for every direction: the direction fills it in and styles it with its own tokens.
function tokenSheet(t) {
  const sw = (list) => list.map(([n, v, note]) => `<div class="sw"><i style="background:${v}"></i><b>${n}</b><code>${v}</code><span>${note || ""}</span></div>`).join("");
  return `<div class="tokens">
    <header><div>${LOGO(18)}<p class="over">Direction ${t.letter}</p><h1>${t.name}</h1></div><p class="why">${t.why}</p></header>
    <div class="col"><section class="type"><h2>Type</h2>${t.type.map(([cls, sample, spec]) => `<div class="spec"><span class="${cls}">${sample}</span><code>${spec}</code></div>`).join("")}</section>
      <section><h2>Depth</h2><div class="depth">${t.depth.map(([cls, n, note]) => `<div class="lvl ${cls}"><b>${n}</b><span>${note}</span></div>`).join("")}</div></section>
      <section><h2>Shape</h2><p class="note">${t.shape}</p></section>
      <section><h2>Signature</h2><p class="note">${t.signature}</p></section>
      <section><h2>Qt Quick</h2><p class="note">${t.qt}</p></section></div>
    <div class="col"><section><h2>Colour, dark (primary)</h2><div class="sws">${sw(t.dark)}</div></section>
      <section><h2>Colour, light</h2><div class="sws lightrow">${sw(t.light)}</div></section>
      <section><h2>Motion</h2><ul>${t.motion.map(([n, v]) => `<li><b>${n}</b><span>${v}</span></li>`).join("")}</ul></section></div>
  </div>`;
}
