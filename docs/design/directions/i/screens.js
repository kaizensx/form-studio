// Direction I: the workspace screens (Design, Designing, Check, Make, Document).

// ---- shared pieces of the conversation ----
const TITLE = "NEMA 17 mount for a 2020 rail";
const reply = `<div class="you">Will it hold a 250 N belt pull?</div>
  <div class="step">${I("pulse", 15)}Ran the strength study on r07<span class="num">41 s</span></div>
  <p class="say">Yes. Peak stress is <span class="num">14.2 MPa</span><sup>1</sup> at the root fillet, against a yield of <span class="num">276 MPa</span><sup>2</sup>: a safety factor of <span class="num">19.4</span>. <span class="evw">Simulated, linear static; discretisation error ≤ 2.8 %.</span></p>
  <p class="say">The mount is far stronger than it needs to be. I can take mass out and keep the factor above 4.</p>
  ${sources([["Strength study on r07", "simulated"], ["6061-T6 yield, material library", "specified"], ["NEMA ICS 16, frame 17 drawing", "opened"]])}`;
const handnote = `<p class="note">${I("user", 14)}<span>By hand since the last reply: <b style="color:var(--ink);font-weight:500">Edge chamfers</b>, 0.8 mm on 2 edges (r07).</span></p>`;
const PART = { k: .8, cx: 754, cy: 432 };
const partShot = (name, layers = () => "", o = {}) => shot("part", PART.k, o.cx || PART.cx, o.cy || PART.cy, (f, w, h) => img(name, w) + (o.noedges ? "" : edges(PART.k, w, h)) + layers(f, w, h));

// ---- Design: the tree, the hand tools, a sketch on a face ----
function sketchLayer(f, w, h) {
  const Y = 46, q = (x, z) => [x, Y, z], arc = (cx, cz, a0, a1) => Array.from({ length: 13 }, (_, i) => { const a = (a0 + (a1 - a0) * i / 12) * Math.PI / 180; return q(cx + 3 * Math.cos(a), cz + 3 * Math.sin(a)); });
  const face = [q(-23, 10), q(23, 10), q(23, 44), q(28, 44), q(28, 61.2), q(-28, 61.2), q(-28, 44), q(-23, 44)];
  const prof = [q(-7, 61.2), q(-7, 55), ...arc(-4, 55, 180, 270), q(4, 52), ...arc(4, 55, 270, 360), q(7, 61.2)];
  const pts = [q(-7, 61.2), q(-7, 55), q(-4, 52), q(4, 52), q(7, 55), q(7, 61.2)].map((p) => f(...p));
  const dW = dimline(f, q(-7, 68), q(7, 68), "14.0"), g = (x, z) => f(...q(x, z));
  const [ex, ey] = g(-13, 56.6), [rx, ry] = g(9.5, 50.5);
  const glyph = (x, z, d) => { const [a, b] = g(x, z); return `<span class="glyph" style="left:${a}px;top:${b}px"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><path d="${d}"/></svg></span>`; };
  return `<svg class="sk" width="${w}" height="${h}"><mask id="occ"><rect width="${w}" height="${h}" fill="#fff"/><path d="${pl(f, [[23, 46, 44], [23, 46, 6], [23, 14, 6]])}Z${pl(f, [[28, 46, 44], [28, 46, 6], [28, 14, 6]])}Z${pl(f, [[23, 46, 44], [28, 46, 44], [28, 14, 6], [23, 14, 6]])}Z" style="fill:#000;stroke:none;filter:none"/></mask><path class="face" mask="url(#occ)" d="${pl(f, face)}Z"/><path class="fill" d="${pl(f, prof)}Z"/>
    <path class="axis" d="${pl(f, [q(0, 8), q(0, 72)])}"/><path d="${pl(f, prof)}"/>
    ${pts.map(([x, y]) => `<circle class="pt" cx="${x}" cy="${y}" r="3.2"/>`).join("")}</svg>
    <svg class="dl" width="${w}" height="${h}">${dW[0]}<path d="${pl(f, [q(-13, 52), q(-13, 61.2)])}"/><path class="wit" d="${pl(f, [q(-7, 62), q(-7, 70)])}${pl(f, [q(7, 62), q(7, 70)])}${pl(f, [q(-8, 52), q(-15, 52)])}${pl(f, [q(-8, 61.2), q(-15, 61.2)])}${pl(f, [q(6.1, 52.9), q(11, 48)])}"/></svg>${dW[1]}
    <span class="dimtag edit" style="left:${ex - 34}px;top:${ey}px">9.0<i></i><em>mm</em></span><span class="dimtag" style="left:${g(14, 45)[0]}px;top:${g(14, 45)[1]}px">R 3.0</span>
    ${glyph(0, 49.4, "M3 6h6")}${glyph(0, 57, "M6 2v8M3 4v4M9 4v4")}`;
}
const designPane = () => `<aside class="pane glass">${tree({ n: 9, after: `<div class="ln sel"><span class="no">09</span><span class="gl">${I("sketch", 13, 1.8)}</span><b>Cable notch</b><span class="who">${I("user", 13)}</span><span class="val" style="color:var(--accent)">sketching</span></div><div class="rb rest"><i></i></div>` })}
  <div class="insp"><h3><span class="no">09</span>Cable notch<em>${I("user", 13)}sketch on Upright, front</em></h3>
    <div class="big"><span class="num">1</span><span>degree of freedom left: the depth</span></div>
    <div class="kv"><span>Width</span><b class="num field">14.0 mm</b>${ev("stated")}<span>Depth</span><b class="num field hot">9.0 mm</b>${ev("typing")}<span>Corner radius</span><b class="num field">3.0 mm</b>${ev("stated")}<span>Wall left to the bore</span><b class="num">6.0 mm</b>${ev("computed")}</div>
    <p><b>4 constraints</b> · symmetric about the bore axis, on the top edge, a horizontal floor, tangent corners. The solver holds them while you drag.</p>
    <div class="acts"><span class="pill pri">${I("cut", 14)}Cut through</span><span class="pill">${I("extrude", 14)}Extrude</span><span class="pill quiet">Finish</span></div></div>
  ${pipe("r07 · 15 pass · 1 review")}</aside>`;
if (S === "design") put(`${room(754, 610)}
  ${partShot("mount-s8", sketchLayer)}
  ${topbar(0)}${convo(TITLE, reply + handnote, "round the floor instead", { scope: "On Sketch 09", typed: true, lit: true })}
  ${dock(0, "sketch")}<div class="opts glass"><b>Sketch 09</b><span class="on">Line</span><span>Arc</span><span>Circle</span><span>Rectangle</span><i class="sep"></i><span>Dimension</span><span>Constrain</span></div>
  ${cube()}${readout()}${hint(`<kbd class="k">Enter</kbd>commits the depth<kbd class="k">Esc</kbd>leaves the sketch`)}
  ${designPane()}`);
