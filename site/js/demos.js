// The capability demos below the hero. Each one starts when it comes near the screen and draws real data only.
import { siteData, toolpath, loadGLB, fmtDur, INKS, reducedMotion } from "./data.js";
import { scrubber, drawChart } from "./app.js";

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const brandName = (s) => String(s).replace(/\bFORM\b/g, "Form Studio");
const setRangeFill = (r) => r.style.setProperty("--p", ((r.value - r.min) / (r.max - r.min)) * 100 + "%");

export function whenNear(el, fn) {
  if (!el) return;
  const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); fn(); } }, { rootMargin: "400px 0px" });
  io.observe(el);
}

// ---------- fit: the engine's model over a clearance sweep ----------
export async function initFit() {
  const d = (await siteData()).dock, sw = d.fit_sweep, f = d.fit;
  const svg = $("#fit-svg"), range = $("#fit-c");
  let src = "assumed", shown = null, raf = 0;
  const W = 640, H = 300, x0 = -0.5, x1 = 1.7, X = (x) => 24 + ((x - x0) / (x1 - x0)) * (W - 48), base = H - 40;
  const [lo, hi] = f.window;
  svg.innerHTML = `<defs><clipPath id="fc-l"><rect x="0" y="0" width="${X(lo)}" height="${H}"/></clipPath><clipPath id="fc-m"><rect x="${X(lo)}" y="0" width="${X(hi) - X(lo)}" height="${H}"/></clipPath><clipPath id="fc-r"><rect x="${X(hi)}" y="0" width="${W}" height="${H}"/></clipPath></defs>
    <rect x="${X(lo)}" y="14" width="${X(hi) - X(lo)}" height="${base - 14}" fill="rgba(185,232,215,.05)"/>
    <path id="fa-l" clip-path="url(#fc-l)" fill="rgba(255,111,81,.38)"/><path id="fa-m" clip-path="url(#fc-m)" fill="rgba(134,217,173,.24)"/><path id="fa-r" clip-path="url(#fc-r)" fill="rgba(233,184,96,.34)"/>
    <path id="fa-line" fill="none" stroke="#e8edeb" stroke-width="1.6"/>
    <line id="fa-mu" stroke="#e8edeb" stroke-width="1.2" y2="${base}"/>
    <line x1="${X(lo)}" x2="${X(lo)}" y1="14" y2="${base}" stroke="#b9e8d7" stroke-dasharray="4 4" stroke-opacity=".75"/>
    <line x1="${X(hi)}" x2="${X(hi)}" y1="14" y2="${base}" stroke="#b9e8d7" stroke-dasharray="4 4" stroke-opacity=".75"/>
    <line x1="24" x2="${W - 24}" y1="${base}" y2="${base}" stroke="rgba(255,255,255,.2)"/>
    ${[-0.4, 0, 0.4, 0.8, 1.2, 1.6].map((v) => `<line x1="${X(v)}" x2="${X(v)}" y1="${base}" y2="${base + 5}" stroke="rgba(255,255,255,.25)"/><text x="${X(v)}" y="${base + 20}" fill="#717b78" font-family="Geist Mono" font-size="12" text-anchor="middle">${v.toFixed(1)}</text>`).join("")}
    <text x="${X(lo)}" y="10" fill="#b9e8d7" font-family="Geist Mono" font-size="12" text-anchor="middle">${lo.toFixed(2)}</text>
    <text x="${X(hi)}" y="10" fill="#b9e8d7" font-family="Geist Mono" font-size="12" text-anchor="middle">${hi.toFixed(2)}</text>
    <text x="${W - 24}" y="${base + 36}" fill="#717b78" font-family="Instrument Sans" font-size="12" text-anchor="end">total gap, mm (printed pocket − phone)</text>
    <text id="fa-lbl" fill="#e8edeb" font-family="Geist Mono" font-size="12" text-anchor="middle"></text>`;
  const pathFor = (mu, sd) => {
    const peak = 1 / (0.153 * Math.sqrt(2 * Math.PI)); // scale both curves to the tighter one, so measuring visibly sharpens it
    let s = "";
    for (let i = 0; i <= 120; i++) { const x = x0 + ((x1 - x0) * i) / 120; const y = base - (Math.exp(-0.5 * ((x - mu) / sd) ** 2) / (sd * Math.sqrt(2 * Math.PI)) / peak) * (base - 30); s += (i ? "L" : "M") + X(x).toFixed(1) + "," + y.toFixed(1); }
    return s;
  };
  const row = () => sw[Math.round((range.value - 0.1) / 0.01)][src];
  function draw(mu, sd) {
    const line = pathFor(mu, sd), area = line + `L${X(x1)},${base}L${X(x0)},${base}Z`;
    ["l", "m", "r"].forEach((k) => $("#fa-" + k).setAttribute("d", area));
    $("#fa-line").setAttribute("d", line);
    const peakY = base - (1 / (sd * Math.sqrt(2 * Math.PI)) / (1 / (0.153 * Math.sqrt(2 * Math.PI)))) * (base - 30);
    const mu1 = $("#fa-mu"); mu1.setAttribute("x1", X(mu)); mu1.setAttribute("x2", X(mu)); mu1.setAttribute("y1", peakY);
    const t = $("#fa-lbl"); t.setAttribute("x", X(mu)); t.setAttribute("y", peakY - 10); t.textContent = `expected ${mu.toFixed(2)} mm`;
  }
  function update(animate = true) {
    const r = row(), target = { mu: r.gap, sd: r.sd };
    $("#fit-y").textContent = Math.round(r.y * 100) + "%";
    $("#fit-t").textContent = Math.round(r.tight * 100) + "%";
    $("#fit-l").textContent = Math.round(r.loose * 100) + "%";
    $("#fit-g").textContent = r.gap.toFixed(2) + " mm";
    $("#fit-co").textContent = (+range.value).toFixed(2) + " mm";
    $("#fit-why").textContent = src === "assumed" ? `The phone’s width is a guess, so it drives ${Math.round(f.sources.mating.share * 100)}% of the uncertainty.` : "Measured with calipers: the printer’s own spread now dominates.";
    setRangeFill(range);
    cancelAnimationFrame(raf);
    if (!shown || !animate || reducedMotion()) { shown = target; draw(target.mu, target.sd); return; }
    const from = { ...shown }, t0 = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - t0) / 240), e = 1 - Math.pow(1 - t, 3);
      shown = { mu: from.mu + (target.mu - from.mu) * e, sd: from.sd + (target.sd - from.sd) * e };
      draw(shown.mu, shown.sd); if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  }
  $("#fit-rec").textContent = f.recommended_clearance.toFixed(2) + " mm";
  range.addEventListener("input", () => update());
  for (const [id, s] of [["#fit-a", "assumed"], ["#fit-m", "measured"]]) $(id).addEventListener("click", () => {
    src = s; $("#fit-a").setAttribute("aria-pressed", String(s === "assumed")); $("#fit-m").setAttribute("aria-pressed", String(s === "measured")); update();
  });
  update(false);
}

// ---------- checks ----------
export async function initChecks() {
  const d = (await siteData()).dock, cs = d.checks;
  const pass = cs.filter((c) => c.status === "PASS").length, warn = cs.length - pass;
  const evc = cs.reduce((m, c) => ((m[c.evidence] = (m[c.evidence] || 0) + 1), m), {});
  $("#ck-p").textContent = pass; $("#ck-w").textContent = warn;
  $("#ck-ratio").innerHTML = `<i style="flex:${pass};background:var(--pass)"></i><i style="flex:${warn};background:var(--amber)"></i>`;
  $("#ck-ev").textContent = `${evc.computed} computed · ${evc.heuristic} heuristic · ${evc.model} model`;
  const cls = { computed: "t-datum", heuristic: "t-ink", model: "t-amber" };
  const list = $("#ck-list");
  list.innerHTML = cs.map((c, i) => `<li class="check" data-ev="${c.evidence}" data-open="false"><button type="button" aria-expanded="false" aria-controls="ck-${i}">
      <span class="tag ${c.status === "PASS" ? "t-pass" : "t-amber"}">${c.status === "PASS" ? "Pass" : "Warn"}</span><span class="nm">${esc(c.label)}</span><span class="val">${esc(c.value)}</span></button>
      <div class="more" id="ck-${i}"><div><span class="tag ${cls[c.evidence]}">${esc(c.evidence)}</span><p>${esc(brandName(c.detail))}</p></div></div></li>`).join("");
  list.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const li = b.parentElement, open = li.dataset.open !== "true";
    li.dataset.open = String(open); b.setAttribute("aria-expanded", String(open));
  });
  $("#ck-filter").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $("#ck-filter").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    let n = 0;
    list.querySelectorAll(".check").forEach((li) => { const on = b.dataset.f === "all" || li.dataset.ev === b.dataset.f; li.hidden = !on; n += on; });
    $("#ck-count").textContent = `${n} check${n === 1 ? "" : "s"}`;
  });
  const first = list.querySelector(".check:nth-child(10)"); // tip-over: the one worth reading
  if (first) { first.dataset.open = "true"; first.querySelector("button").setAttribute("aria-expanded", "true"); }
}

// ---------- print: one layer from above, the slicer's toolpath ----------
export async function initPrint() {
  const tp = await toolpath(), m = tp.meta, n = m.z.length;
  const c = $("#pc"), chart = $("#pc-chart"), cc = $("#pc-chart-c");
  const hidden = new Set();
  let layer = 50, frac = 1, playing = false, raf = 0;
  $("#pc-credit").textContent = `G-code from Bambu Studio ${(await siteData()).dock.slice_meta.slicer_version}: ${(await siteData()).dock.slice.presets.replace(/ @BBL A1M/g, "").replace(/ \/ /g, ", ")}. ${m.segments_in_gcode.toLocaleString("en")} moves, drawn from ${m.points.toLocaleString("en")} points after simplifying to ${m.simplified_mm} mm.`;
  $("#pc-types").innerHTML = m.types.map((t) => `<li><button type="button" data-t="${esc(t)}" aria-pressed="true"><i style="background:${INKS[t]}"></i><span>${esc(t)}</span><span>${(m.type_length_mm[t] / 1000).toFixed(1)} m</span></button></li>`).join("");
  $("#pc-types").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; const t = b.dataset.t; hidden.has(t) ? hidden.delete(t) : hidden.add(t); b.setAttribute("aria-pressed", String(!hidden.has(t))); draw(); });
  const bx = m.bbox, cx = (bx[0][0] + bx[1][0]) / 2, cy = (bx[0][1] + bx[1][1]) / 2, span = Math.max(bx[1][0] - bx[0][0], bx[1][1] - bx[0][1]) * 1.12;
  function draw() {
    const r = c.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
    if (!r.width) return;
    if (c.width !== Math.round(r.width * dpr)) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); }
    const g = c.getContext("2d"), W = c.width, H = c.height, narrow = r.width < 560, s = Math.min(W, H) / (span * (narrow ? 1.32 : 1));
    const P = (x, y) => [W / 2 + (x - cx) * s, H / 2 + (narrow ? H * 0.09 : 0) - (y - cy) * s];
    g.clearRect(0, 0, W, H);
    g.lineCap = "round"; g.lineJoin = "round";
    // the layers below, faint
    if (layer > 0) {
      g.lineWidth = m.width_mm * s; g.strokeStyle = "rgba(255,255,255,.05)"; g.beginPath();
      const a = tp.layerStart[layer - 1], b = tp.layerStart[layer];
      for (let i = a; i < b; i++) if (tp.type[i] < 2) { const [x0, y0] = P(tp.seg[i * 4], tp.seg[i * 4 + 1]), [x1, y1] = P(tp.seg[i * 4 + 2], tp.seg[i * 4 + 3]); g.moveTo(x0, y0); g.lineTo(x1, y1); }
      g.stroke();
    }
    const a = tp.layerStart[layer], b = tp.layerStart[layer + 1], stop = layer + frac;
    g.lineWidth = Math.max(1, m.width_mm * s * 0.92);
    let last = null;
    for (let t = 0; t < m.types.length; t++) {
      if (hidden.has(m.types[t])) continue;
      g.strokeStyle = INKS[m.types[t]]; g.beginPath();
      for (let i = a; i < b; i++) {
        if (tp.type[i] !== t || tp.p0[i] >= stop) continue;
        const f = Math.min(1, (stop - tp.p0[i]) / Math.max(1e-6, tp.p1[i] - tp.p0[i]));
        const [x0, y0] = P(tp.seg[i * 4], tp.seg[i * 4 + 1]);
        const [x1, y1] = P(tp.seg[i * 4] + (tp.seg[i * 4 + 2] - tp.seg[i * 4]) * f, tp.seg[i * 4 + 1] + (tp.seg[i * 4 + 3] - tp.seg[i * 4 + 1]) * f);
        g.moveTo(x0, y0); g.lineTo(x1, y1);
        if (f < 1) last = [x1, y1];
      }
      g.stroke();
    }
    if (last && frac < 1) { g.fillStyle = "rgba(185,232,215,.25)"; g.beginPath(); g.arc(last[0], last[1], 9 * dpr, 0, 7); g.fill(); g.fillStyle = "#b9e8d7"; g.beginPath(); g.arc(last[0], last[1], 3.2 * dpr, 0, 7); g.fill(); }
    const types = [...new Set(Array.from(tp.type.subarray(a, b)))].map((i) => m.types[i]);
    $("#pc-layer").textContent = `Layer ${layer + 1} of ${n}`;
    $("#pc-z").textContent = `z ${m.z[layer].toFixed(2)} mm · ${m.height[layer].toFixed(2)} mm layer`;
    $("#pc-t").textContent = types.includes("Bridge") ? "Bridges in this layer" : "";
    const el = m.t0_s[layer] + frac * m.time_s[layer];
    $("#pc-read").textContent = `${fmtDur(m.time_s[layer])} for this layer · ${fmtDur(el)} elapsed of ${fmtDur(m.total_time_s)}`;
    chart.setAttribute("aria-valuenow", String(layer + 1));
    drawChart(cc, m, layer + frac);
  }
  const setLayer = (l, f = 1) => { layer = Math.max(0, Math.min(n - 1, l)); frac = f; draw(); };
  scrubber(chart, (f) => { stop(); const p = f * n; setLayer(Math.floor(p), 1); });
  const playBtn = $("#pc-play");
  function stop() { playing = false; cancelAnimationFrame(raf); playBtn.innerHTML = `<span class="i" aria-hidden="true">&#xe13c;</span><span>Play</span>`; }
  function play() {
    playing = true; playBtn.innerHTML = `<span class="i" aria-hidden="true">&#xe12e;</span><span>Pause</span>`;
    if (layer >= n - 1 && frac >= 1) setLayer(0, 0);
    if (frac >= 1) { layer = Math.min(n - 1, layer + 1); frac = 0; }
    let t = performance.now();
    const step = (now) => {
      if (!playing) return;
      const dt = (now - t) / 1000; t = now;
      frac += dt / 1.4;               // one layer every 1.4 s, so a layer can be read as it is drawn
      if (frac >= 1) { if (layer >= n - 1) { frac = 1; draw(); return stop(); } layer++; frac = 0; }
      draw(); raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  }
  playBtn.addEventListener("click", () => (playing ? stop() : play()));
  $("#pc-bridge").addEventListener("click", () => { stop(); const nx = m.bridge_layers.find((l) => l > layer) ?? m.bridge_layers[0]; setLayer(nx, 1); });
  new ResizeObserver(draw).observe(c);
  setLayer(m.bridge_layers.find((l) => l >= 40) ?? 50, 1);
}

// ---------- assembly: the hinged box ----------
export async function initAssembly() {
  const THREE = await import("three");
  const { OrbitControls } = await import("../vendor/OrbitControls.js");
  const b = (await siteData()).box, parts = await loadGLB("assets/data/box.glb");
  const canvas = $("#asm-c"), view = $("#asm-view");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setClearColor(0, 0); renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(30, 1, 5, 3000);
  scene.add(new THREE.HemisphereLight(0xf2f4f3, 0x3b4246, 1.55));
  const key = new THREE.DirectionalLight(0xffffff, 1.9); key.position.set(-180, 320, 260); scene.add(key);
  const fill = new THREE.DirectionalLight(0xdfe8ff, 0.5); fill.position.set(260, 120, -200); scene.add(fill);
  const world = new THREE.Group(); world.rotation.x = -Math.PI / 2; scene.add(world);
  const grid = new THREE.GridHelper(400, 40, 0xffffff, 0xffffff); grid.material.transparent = true; grid.material.opacity = 0.05; grid.rotation.x = Math.PI / 2; world.add(grid);
  const groups = {}, info = {};
  for (const p of b.parts) { groups[p.id] = new THREE.Group(); world.add(groups[p.id]); info[p.id] = p; }
  const tint = { body: 0xd8d3c8, lid: 0xcfcbc1 };
  for (const p of parts) {
    const part = p.extras.part, geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(p.pos, 3));
    let o;
    if (p.lines) o = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x0b0d0e, transparent: true, opacity: 0.5 }));
    else { geo.setIndex(new THREE.BufferAttribute(p.index, 1)); geo.computeVertexNormals(); o = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: tint[part] || 0xd8d3c8, roughness: 0.82, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 })); }
    groups[part].add(o);
  }
  // each part's printed frame -> assembled placement (a 3x4 matrix from the engine), plus explode and the hinge
  const placeM = (pl) => new THREE.Matrix4().set(...pl.m[0], ...pl.m[1], ...pl.m[2], 0, 0, 0, 1);
  const hinge = b.joints[0];
  const st = { mode: "assembled", k: 0, angle: 0 };
  const shown = { k: 0, explode: 0, angle: 0 };
  const lidPrint = new THREE.Vector3(...[0, 1, 2].map((i) => (info.lid.print_bbox[0][i] + info.lid.print_bbox[1][i]) / 2));
  function apply() {
    for (const id of Object.keys(groups)) {
      const p = info[id], g = groups[id];
      const A = placeM(p.placement);
      // blend between the print layout (identity) and the assembled placement
      const I4 = new THREE.Matrix4();
      const pa = new THREE.Vector3(), qa = new THREE.Quaternion(), sa = new THREE.Vector3(); A.decompose(pa, qa, sa);
      const pos = new THREE.Vector3().lerpVectors(new THREE.Vector3(), pa, 1 - shown.k), q = new THREE.Quaternion().slerpQuaternions(qa, new THREE.Quaternion(), shown.k);
      let M = new THREE.Matrix4().compose(pos, q, new THREE.Vector3(1, 1, 1));
      if (id === hinge.part && shown.angle) {
        const o = new THREE.Vector3(...hinge.origin), ax = new THREE.Vector3(...hinge.axis).normalize();
        const R = new THREE.Matrix4().makeTranslation(o.x, o.y, o.z).multiply(new THREE.Matrix4().makeRotationAxis(ax, (shown.angle * Math.PI) / 180 * (1 - shown.k))).multiply(new THREE.Matrix4().makeTranslation(-o.x, -o.y, -o.z));
        M = R.multiply(M);
      }
      const e = new THREE.Vector3(...p.explode).multiplyScalar(shown.explode * (1 - shown.k));
      M = new THREE.Matrix4().makeTranslation(e.x, e.y, e.z).multiply(M);
      g.matrixAutoUpdate = false; g.matrix.copy(M); g.matrixWorldNeedsUpdate = true;
      void I4;
    }
    const bb = shown.k > 0.5 ? [[-32, -30, 0], [104, 30, 10]] : b.bbox_exploded;
    target.set((bb[0][0] + bb[1][0]) / 2, (bb[0][2] + bb[1][2]) / 2 * 0.6, -(bb[0][1] + bb[1][1]) / 2);
    dirty = true;
  }
  const target = new THREE.Vector3();
  const controls = new OrbitControls(camera, canvas);
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.09, enablePan: false, enableZoom: false, rotateSpeed: 0.75 });
  canvas.style.touchAction = "pan-y";
  let dirty = true, raf = 0, onscreen = false, anim = null;
  controls.addEventListener("change", () => (dirty = true));
  function resize() { const w = view.clientWidth, h = view.clientHeight; renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1)); renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); dirty = true; kick(); }
  function kick() { if (!raf && onscreen && !document.hidden) raf = requestAnimationFrame(loop); }
  function loop(now) {
    raf = 0;
    if (anim) { const t = Math.min(1, (now - anim.t0) / anim.ms), e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; for (const k in anim.to) shown[k] = anim.from[k] + (anim.to[k] - anim.from[k]) * e; apply(); if (t >= 1) anim = null; }
    controls.target.lerp(target, 0.12);
    let adj = false;
    { const want = st.mode === "print" ? 300 : st.mode === "exploded" ? 250 : 205, off = camera.position.clone().sub(controls.target), d = off.length(); if (Math.abs(d - want) > 0.5) { off.setLength(d + (want - d) * 0.12); camera.position.copy(controls.target).add(off); dirty = true; adj = true; } }
    const moving = controls.update();
    if (dirty || moving || anim) { renderer.render(scene, camera); dirty = false; }
    if (anim || moving || adj || controls.target.distanceTo(target) > 0.05) raf = requestAnimationFrame(loop);
  }
  function go(ms = 300) {
    const to = { k: st.mode === "print" ? 1 : 0, explode: st.mode === "exploded" ? 1 : 0, angle: st.angle };
    if (reducedMotion() || !ms) { Object.assign(shown, to); apply(); kick(); return; }
    anim = { t0: performance.now(), ms, from: { ...shown }, to }; kick();
  }
  controls.target.set(0, 10, 0); target.copy(controls.target); camera.position.set(-0.6, 0.5, 0.75).setLength(205).add(controls.target);
  new ResizeObserver(resize).observe(view);
  new IntersectionObserver(([e]) => { onscreen = e.isIntersecting; kick(); }).observe(view);
  $("#asm-mode").addEventListener("click", (e) => { const btn = e.target.closest("button"); if (!btn) return; st.mode = btn.dataset.m; $("#asm-mode").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === btn))); go(420); });
  const hr = $("#asm-hinge");
  $("#asm-hinge").max = hinge.range[1]; hr.nextElementSibling;
  hr.addEventListener("input", () => { st.angle = +hr.value; $("#asm-ho").textContent = hr.value + "°"; setRangeFill(hr); if (st.mode === "print") { st.mode = "assembled"; $("#asm-mode").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.m === "assembled"))); go(300); } else { shown.angle = st.angle; apply(); kick(); } });
  setRangeFill(hr);
  $("#asm-hw").innerHTML = b.hardware.map((h) => `<li><b>${esc(h.name)}, ${esc(h.size)} × ${h.qty}</b><span>${esc(h.source)}</span><span>${esc(h.note)}</span></li>`).join("");
  hr.closest(".ctl").querySelector("small").textContent = `Range ${hinge.range[0]} to ${hinge.range[1]}°, checked at ${hinge.samples} positions for collisions.`;
  apply(); resize();
  // a short, quiet demonstration of the hinge the first time it is seen
  if (!reducedMotion()) {
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return; io.disconnect();
      setTimeout(() => { st.angle = 100; hr.value = 100; $("#asm-ho").textContent = "100°"; setRangeFill(hr); go(1100); setTimeout(() => { st.angle = 0; hr.value = 0; $("#asm-ho").textContent = "0°"; setRangeFill(hr); go(900); }, 1900); }, 500);
    }, { threshold: 0.6 });
    io.observe(view);
  }
}

// ---------- agents and slicers (facts from the README's works-with table) ----------
const AGENTS = [
  { id: "claude", name: "Claude Code", sub: "Chat in the app · MCP", body: "<b>In the app:</b> each message runs Claude Code with Form Studio’s tools on your own account; sign in from the app. Pick the model under the message box.<br><b>From a terminal:</b> <code>claude mcp add --scope user form -- form-mcp</code>, or let <code>form setup</code> register it. Thirteen design skills install as a Claude Code plugin.", tags: [["In-app chat", "t-datum"], ["MCP", "t-blue"], ["Skills plugin", "t-ink"]] },
  { id: "codex", name: "Codex", sub: "Chat in the app · MCP", body: "<b>In the app:</b> pick Codex for a conversation and it works on the same design.<br><b>From a terminal:</b> <code>codex mcp add form -- form-mcp</code>. The open app follows its drafts and commits live.", tags: [["In-app chat", "t-datum"], ["MCP", "t-blue"]] },
  { id: "gemini", name: "Gemini CLI", sub: "Chat in the app · MCP", body: "<b>In the app:</b> sign in, or paste a Gemini API key once in Settings › Chat; it is stored privately and never shown again.<br><b>From a terminal:</b> <code>form setup</code> adds Form Studio to <code>~/.gemini/settings.json</code>.", tags: [["In-app chat", "t-datum"], ["MCP", "t-blue"]] },
  { id: "cursor", name: "Cursor", sub: "Cursor CLI in the app · MCP in the editor", body: "<b>In the app:</b> choose Cursor CLI for a conversation.<br><b>In the editor:</b> add <code>form-mcp</code> to <code>~/.cursor/mcp.json</code>. Cursor gets the same 44 tools, and the open app follows what it changes.", tags: [["In-app chat", "t-datum"], ["MCP", "t-blue"]] },
  { id: "more", name: "OpenCode, Qwen Code, Copilot CLI", sub: "Chat in the app · MCP", body: "Each can run a conversation inside the app with Form Studio’s tools, and each speaks MCP from its own terminal with the same <code>form-mcp</code> entry.", tags: [["In-app chat", "t-datum"], ["MCP", "t-blue"]] },
  { id: "mcp", name: "Any MCP client", sub: "Claude Desktop and others", body: "Form Studio is a standard MCP server over stdio: <code>{ \"mcpServers\": { \"form\": { \"command\": \"form-mcp\" } } }</code>. 44 tools for designing, checking, slicing, simulating and preparing a release. Only a person approves a release.", tags: [["MCP", "t-blue"]] },
];
const SLICERS = [
  { id: "bambu", name: "Bambu Studio", sub: "Your printer, filament and process presets", body: "Slices with the presets selected in Bambu Studio, or the ones pinned in Settings. The sample project on this page was sliced by Bambu Studio 02.09.01.70 for a Bambu Lab A1 mini.", tags: [["Linux · CI real slice", "t-pass"], ["Windows · CI real slice", "t-pass"], ["macOS", "t-ink"]] },
  { id: "orca", name: "OrcaSlicer", sub: "Reads OrcaSlicer 2.5’s packed profiles", body: "Reads the packed vendor profiles (<code>.opc</code>) OrcaSlicer 2.5 ships, so every printer it knows is available without exporting anything.", tags: [["Linux · CI real slice", "t-pass"], ["Windows · CI real slice", "t-pass"], ["macOS", "t-ink"]] },
  { id: "prusa", name: "PrusaSlicer", sub: "Bundled vendor profiles", body: "A full slice, layers, print simulation and cost, with presets resolved from the profiles PrusaSlicer ships.", tags: [["Linux · CI real slice", "t-pass"], ["Windows · CI real slice", "t-pass"], ["macOS", "t-ink"]] },
  { id: "super", name: "SuperSlicer", sub: "Same workflow", body: "Slices with your SuperSlicer configuration.", tags: [["Linux · CI real slice", "t-pass"], ["Windows · CI real slice", "t-pass"], ["macOS", "t-ink"]] },
  { id: "qidi", name: "QIDISlicer", sub: "Same workflow", body: "Slices with your QIDISlicer configuration.", tags: [["Linux · CI real slice", "t-pass"], ["Windows · CI real slice", "t-pass"], ["macOS", "t-ink"]] },
  { id: "forks", name: "Creality Print, Elegoo, Anycubic", sub: "The OrcaSlicer family", body: "Slicers built on OrcaSlicer work the same way: Creality Print, Elegoo Slicer and Anycubic Slicer Next, with the printers you configured in them.", tags: [["Supported", "t-ink"]] },
];
function picker(listSel, detailSel, items) {
  const list = $(listSel), detail = $(detailSel);
  list.innerHTML = items.map((a, i) => `<li><button type="button" data-i="${i}" aria-pressed="${i === 0}"><span><span class="nm">${esc(a.name)}</span><span class="sub">${esc(a.sub)}</span></span><span class="i" aria-hidden="true" style="color:var(--ink4)">&#xe06f;</span></button></li>`).join("");
  const show = (i) => {
    const a = items[i];
    list.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(+b.dataset.i === i)));
    detail.innerHTML = `<div>${a.body}</div>${a.tags.length ? `<div class="row">${a.tags.map(([t, c]) => `<span class="tag ${c}">${esc(t)}</span>`).join("")}</div>` : ""}`;
    if (!reducedMotion()) detail.animate([{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "none" }], { duration: 170, easing: "cubic-bezier(.23,1,.32,1)" });
  };
  list.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) show(+b.dataset.i); });
  show(0);
}
export function initWorks() { picker("#ag-list", "#ag-detail", AGENTS); picker("#sl-list", "#sl-detail", SLICERS); }

// ---------- terminal: real commands, real output ----------
export async function initTerminal() {
  const cli = (await siteData()).cli, out = $("#term-out"), tabs = $("#term-tabs");
  tabs.innerHTML = cli.map((c, i) => `<button type="button" role="tab" aria-selected="${i === 0}" data-i="${i}">${esc(c.cmd.replace(/^form /, "").split(" ")[0])}</button>`).join("");
  const hl = (s) => esc(s).replace(/(&quot;[^&]*?&quot;)(\s*:)/g, '<span class="k">$1</span>$2').replace(/:\s(&quot;.*?&quot;)/g, ': <span class="s">$1</span>').replace(/(:\s|\[\s*|,\s)(-?\d+\.?\d*)/g, '$1<span class="n">$2</span>').replace(/\b(true|false|null)\b/g, '<span class="b">$1</span>');
  let job = 0;
  async function show(i, typing = true) {
    const my = ++job, c = cli[i];
    tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(+b.dataset.i === i)));
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    if (!typing || reducedMotion()) { out.innerHTML = `<span class="ps">$ </span><span class="cmd">${esc(c.cmd)}</span>\n${hl(brandName(c.out))}\n<span class="ps">$ </span><span class="caret"></span>`; return; }
    out.innerHTML = `<span class="ps">$ </span><span class="cmd"></span><span class="caret"></span>`;
    const cmd = out.querySelector(".cmd");
    for (let k = 1; k <= c.cmd.length; k++) { if (my !== job) return; cmd.textContent = c.cmd.slice(0, k); await sleep(28 + Math.random() * 30); }
    await sleep(380); if (my !== job) return;
    const lines = hl(brandName(c.out)).split("\n");
    out.querySelector(".caret").remove();
    let html = out.innerHTML + "\n";
    for (let k = 0; k < lines.length; k++) { if (my !== job) return; html += lines[k] + "\n"; out.innerHTML = html; if (k % 2) await sleep(16); }
    out.innerHTML = html + `<span class="ps">$ </span><span class="caret"></span>`;
    if (my === job && auto) { await sleep(3200); if (my === job && auto) show((i + 1) % cli.length); }
  }
  let auto = true;
  tabs.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; auto = false; show(+b.dataset.i, false); });
  tabs.addEventListener("keydown", (e) => { const cur = cli.findIndex((_, i) => tabs.children[i].getAttribute("aria-selected") === "true"); const n = e.key === "ArrowRight" ? (cur + 1) % cli.length : e.key === "ArrowLeft" ? (cur + cli.length - 1) % cli.length : -1; if (n >= 0) { auto = false; show(n, false); tabs.children[n].focus(); } });
  show(0);
}
