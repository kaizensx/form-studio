// How it works: a Form Studio window pinned while four beats scroll past. Each beat is a screen of the app drawn in
// code from the sample project's real data: the brief typed on Home, the solid the CAD kernel built (dock.glb),
// the checks Form Studio's engine ran, and the toolpath Bambu Studio wrote (toolpath.bin). The scroll is the clock.
import { siteData, loadGLB, toolpath, fmtDur, INKS } from "./data.js";
import { scrub, span, clamp, easeOut, easeInOut } from "./motion.js";

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export async function initHow() {
  const track = $("#how-track");
  if (!track) return;
  const d = (await siteData()).dock;
  const steps = [...document.querySelectorAll("#how-steps li")];
  const scenes = [...document.querySelectorAll("#how-win .scene")];
  const prog = [...document.querySelectorAll("#how-win .win-prog i")];
  const rev = `r${String(d.head).padStart(2, "0")}`;
  const bar = [
    { name: "New design", rev: "", tag: ["Home", "t-ink"] },
    { name: d.name, rev: "r01", tag: ["Building", "t-datum"] },
    { name: d.name, rev, tag: ["Prove", "t-datum"] },
    { name: d.name, rev, tag: ["Simulated", "t-amber"] },
  ];
  const draw = [home(d), cad(d), checks(d), print(d)];
  let beat = -1;

  scrub(track, (p) => {
    const P = p * 4, b = Math.min(3, Math.floor(P)), f = b === 3 ? Math.min(1, P - 3) : P - b;
    const g = span(f, 0.06, 0.82);                       // each beat finishes, then rests before the next
    if (b !== beat) {
      beat = b;
      scenes.forEach((s, i) => { s.classList.toggle("on", i === b); s.classList.toggle("past", i < b); });
      steps.forEach((s, i) => s.classList.toggle("on", i === b));
      $("#hw-name").textContent = bar[b].name; $("#hw-rev").textContent = bar[b].rev;
      const t = $("#hw-stage"); t.textContent = bar[b].tag[0]; t.className = `tag ${bar[b].tag[1]}`;
      if (b > 0) draw[b - 1](1);                         // the screen leaving shows its finished state
      if (b < 3) draw[b + 1](0);                         // and the next one is ready from its start
    }
    steps.forEach((s, i) => s.style.setProperty("--f", i < b ? 1 : i === b ? f.toFixed(3) : 0));
    prog.forEach((s, i) => s.style.setProperty("--f", i < b ? 1 : i === b ? f.toFixed(3) : 0));
    draw[b](g);
  }, { smooth: 9 });
}

// ---------- 1. Home: the brief typed into the composer, then Design it ----------
function home(d) {
  const out = $("#hw-type"), go = $("#hw-go");
  $("#hw-printer").textContent = d.slice_meta.presets.machine.name;
  const h = new Date().getHours();
  $("#how-win .greet").textContent = h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  let shown = -1;
  return (g) => {
    const n = Math.round(span(g, 0, 0.8) * d.brief.length);
    if (n !== shown) {
      shown = n;
      out.innerHTML = n ? `${esc(d.brief.slice(0, n))}<span class="caret"></span>` : '<span class="ph">A knob like the one in my photo…</span>';
    }
    go.classList.toggle("on", n > 0);
    go.classList.toggle("press", g > 0.9 && g < 0.98);
  };
}

// ---------- 2. CAD: the kernel's solid, feature by feature, turning as you scroll ----------
function cad(d) {
  const canvas = $("#hw-gl"), list = $("#hw-feats");
  $("#hw-cad").textContent = `${d.size.map((v) => v.toFixed(1)).join(" × ")} mm · ${d.faces} faces · ${d.volume_cm3} cm³ · built in ${d.build_ms} ms · ${d.kernel}`;
  let ready = null, three = null, last = -1;
  const boot = () => (ready ||= (async () => {
    const THREE = await import("three");
    const parts = await loadGLB("assets/data/dock.glb");
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setClearColor(0, 0); renderer.outputColorSpace = THREE.SRGBColorSpace;
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(28, 1, 5, 3000);
    scene.add(new THREE.HemisphereLight(0xf2f4f3, 0x3b4246, 1.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.9); key.position.set(-180, 320, 260); scene.add(key);
    const fill = new THREE.DirectionalLight(0xdfe8ff, 0.55); fill.position.set(260, 120, -200); scene.add(fill);
    const world = new THREE.Group(); world.rotation.x = -Math.PI / 2; scene.add(world);
    const grid = new THREE.GridHelper(420, 42, 0xffffff, 0xffffff); grid.material.transparent = true; grid.material.opacity = 0.05; grid.rotation.x = Math.PI / 2; world.add(grid);
    const feats = [];
    let edges = null;
    for (const p of parts) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(p.pos, 3));
      if (p.lines) { edges = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x0b0d0e, transparent: true, opacity: 0 })); world.add(edges); continue; }
      geo.setIndex(new THREE.BufferAttribute(p.index, 1)); geo.computeVertexNormals();
      const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0xd8d3c8, roughness: 0.82, side: THREE.DoubleSide, transparent: true, opacity: 0, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
      world.add(m); feats.push({ mesh: m, label: p.extras.label || p.name });
    }
    list.innerHTML = feats.map((f) => `<li><i></i>${esc(f.label)}</li>`).join("");
    const bb = d.bbox, c = new THREE.Vector3((bb[0][0] + bb[1][0]) / 2, (bb[0][2] + bb[1][2]) * 0.32, -(bb[0][1] + bb[1][1]) / 2);
    const R = Math.hypot(...d.size) * 1.85;
    const resize = () => { const w = canvas.clientWidth, h = canvas.clientHeight; if (!w) return; renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1)); renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); render(last < 0 ? 0 : last); };
    function render(g) {
      const n = feats.length, lis = list.children;
      feats.forEach((f, i) => {
        const k = easeOut(span(g, i / (n + 1), (i + 1) / (n + 1)));
        f.mesh.material.opacity = k; f.mesh.material.transparent = k < 1; f.mesh.visible = k > 0.001; f.mesh.position.z = 8 * (1 - k);
        lis[i] && lis[i].classList.toggle("on", k > 0.5);
      });
      if (edges) edges.material.opacity = 0.55 * span(g, n / (n + 1), 1);
      const az = (-48 + 62 * easeInOut(g)) * Math.PI / 180, el = (30 - 6 * g) * Math.PI / 180;
      const r = R * (1.12 - 0.12 * easeOut(g)) / Math.max(0.75, Math.min(1.25, camera.aspect / 1.4));
      camera.position.set(c.x + r * Math.cos(el) * Math.sin(az), c.y + r * Math.sin(el), c.z + r * Math.cos(el) * Math.cos(az));
      camera.lookAt(c);
      renderer.render(scene, camera);
    }
    new ResizeObserver(resize).observe(canvas); resize();
    three = render;
  })());
  return (g) => { last = g; if (three) three(g); else boot().then(() => three && three(last)); };
}

// ---------- 3. Checks: the twelve the engine ran on revision 4, ticking in ----------
function checks(d) {
  const list = $("#hw-checks"), cs = d.checks;
  const ev = { computed: "t-datum", heuristic: "t-ink", model: "t-amber", modelled: "t-amber" };
  list.innerHTML = cs.map((c) => `<li><span class="tag ${c.status === "PASS" ? "t-pass" : "t-amber"}">${c.status === "PASS" ? "Pass" : "Warn"}</span><span class="nm">${esc(c.label)}</span><span class="val">${esc(c.value)}</span><span class="tag ${ev[c.evidence] || "t-ink"}">${esc(c.evidence)}</span></li>`).join("");
  const lis = [...list.children], pass = $("#hw-pass"), warn = $("#hw-warn");
  let shown = -1;
  return (g) => {
    const n = Math.round(span(g, 0, 0.9) * cs.length);
    if (n === shown) return;
    shown = n;
    lis.forEach((li, i) => { li.classList.toggle("on", i < n); li.classList.toggle("now", i === n - 1 && n < cs.length); });
    pass.textContent = cs.slice(0, n).filter((c) => c.status === "PASS").length;
    warn.textContent = cs.slice(0, n).filter((c) => c.status !== "PASS").length;
  };
}

// ---------- 4. Print: the slicer's toolpath stacked layer by layer in an oblique view ----------
function print(d) {
  const c = $("#hw-pc");
  const sm = d.slice_meta;
  let tp = null, loading = null, layers = null, last = 0;
  const load = () => (loading ||= toolpath().then((t) => { tp = t; build(); draw(last); }));
  const ISO = (x, y, z) => [(x - y) * 0.866, (x + y) * 0.5 - z * 1.15];
  function build() {
    // one Path2D per layer for the walls (what shows the part's form), in projected millimetres
    const m = tp.meta, wallT = new Set([m.types.indexOf("Outer wall"), m.types.indexOf("Overhang wall")]);
    layers = [];
    let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
    for (let l = 0; l < m.z.length; l++) {
      const path = new Path2D(), z = m.z[l];
      for (let i = tp.layerStart[l]; i < tp.layerStart[l + 1]; i++) {
        const [ax, ay] = ISO(tp.seg[i * 4], tp.seg[i * 4 + 1], z), [bx, by] = ISO(tp.seg[i * 4 + 2], tp.seg[i * 4 + 3], z);
        if (wallT.has(tp.type[i])) { path.moveTo(ax, ay); path.lineTo(bx, by); }
        x0 = Math.min(x0, ax, bx); x1 = Math.max(x1, ax, bx); y0 = Math.min(y0, ay, by); y1 = Math.max(y1, ay, by);
      }
      layers.push(path);
    }
    tp.box = [x0, y0, x1, y1];
  }
  function draw(g) {
    last = g;
    if (!tp) { load(); return; }
    const m = tp.meta, n = m.z.length, r = c.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
    if (!r.width) return;
    if (c.width !== Math.round(r.width * dpr) || c.height !== Math.round(r.height * dpr)) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); }
    const W = c.width, H = c.height, [x0, y0, x1, y1] = tp.box;
    const s = Math.min(W / (x1 - x0), H / (y1 - y0)) * 0.78, ox = W / 2 - ((x0 + x1) / 2) * s, oy = H / 2 + H * 0.03 - ((y0 + y1) / 2) * s;
    const P = g * n, cur = Math.min(n - 1, Math.floor(P)), frac = P >= n ? 1 : P - cur;
    const ctx = c.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H);
    ctx.setTransform(s, 0, 0, s, ox, oy);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    // the layers already printed: walls in clay, lighter towards the top
    ctx.lineWidth = Math.max(m.width_mm, 1.1 / s);
    for (let l = 0; l < cur; l++) { ctx.strokeStyle = `rgba(216,211,200,${0.16 + 0.42 * (l / n)})`; ctx.stroke(layers[l]); }
    // the layer being printed: every line type in the slicer's inks, drawn up to where the nozzle is
    const a = tp.layerStart[cur], b = tp.layerStart[cur + 1], stop = cur + frac, z = m.z[cur];
    ctx.lineWidth = Math.max(m.width_mm * 1.1, 1.4 / s);
    let head = null;
    for (let t = 0; t < m.types.length; t++) {
      ctx.strokeStyle = INKS[m.types[t]] || "#a8b2af"; ctx.beginPath();
      for (let i = a; i < b; i++) {
        if (tp.type[i] !== t || tp.p0[i] >= stop) continue;
        const f = Math.min(1, (stop - tp.p0[i]) / Math.max(1e-6, tp.p1[i] - tp.p0[i]));
        const sx = tp.seg[i * 4], sy = tp.seg[i * 4 + 1], ex = sx + (tp.seg[i * 4 + 2] - sx) * f, ey = sy + (tp.seg[i * 4 + 3] - sy) * f;
        const [px, py] = ISO(sx, sy, z), [qx, qy] = ISO(ex, ey, z);
        ctx.moveTo(px, py); ctx.lineTo(qx, qy);
        if (f < 1) head = [qx, qy];
      }
      ctx.stroke();
    }
    if (head && frac < 1) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      const hx = ox + head[0] * s, hy = oy + head[1] * s;
      ctx.fillStyle = "rgba(185,232,215,.22)"; ctx.beginPath(); ctx.arc(hx, hy, 9 * dpr, 0, 7); ctx.fill();
      ctx.fillStyle = "#b9e8d7"; ctx.beginPath(); ctx.arc(hx, hy, 3 * dpr, 0, 7); ctx.fill();
    }
    const elapsed = m.t0_s[cur] + frac * m.time_s[cur];
    $("#hw-layer").textContent = `Layer ${cur + 1} of ${n}`;
    $("#hw-z").textContent = `z ${m.z[cur].toFixed(2)} mm`;
    $("#hw-pbar").style.setProperty("--f", clamp(elapsed / m.total_time_s).toFixed(4));
    $("#hw-read").textContent = `${fmtDur(elapsed)} of ${fmtDur(m.total_time_s)} · ${sm.filament_g} g · Bambu Studio ${sm.slicer_version}, ${sm.presets.machine.name}`;
  }
  new ResizeObserver(() => tp && draw(last)).observe(c);
  return draw;
}
