// The hero: Form Studio's window, drawn in code as Lightdesk (docs/design/directions/h). A studio room with the part
// in a pool of warm light, glass capsules, the features as a program listing that runs line by line, a lower-third
// title while a feature is built, and one bar under the part with numbered suggestions.
//
// Nothing here is typed by hand: the solid is the CAD kernel's own (case.glb, one mesh per feature), and every
// number, check and sentence in the answers comes from case.json, written by site/tools/export_case.py from a real
// engine run. The agent is not run in this page: a suggestion opens what the engine recorded for the revision.
import { loadGLB, reducedMotion } from "./data.js";

const W = 1440, H = 900, CW = 390, CH = 640;        // logical sizes: the window, and the phone layout
const STEP = 1050, LAND = 340, FLASH = 620;         // ms: one program line, a feature landing, its key-light flash
const nn = (i) => String(i).padStart(2, "0");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const easeOut = (t) => 1 - Math.pow(1 - t, 3);
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const lerp = (a, b, t) => a + (b - a) * t;

// the app's own icons (docs/design/directions/assets/shared.js)
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
  search: "M11 4.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM20 20l-4.4-4.4", gear: "M4 7h9M17 7h3M4 17h3M11 17h9M15 4.5v5M9 14.5v5",
  clip: "M20 11.2l-8.4 8.4a5 5 0 01-7.1-7.1L13 4a3.3 3.3 0 014.7 4.7l-8.3 8.4a1.7 1.7 0 01-2.4-2.4L14.8 7",
  down: "M6 9l6 6 6-6", grid: "M4 4h16v16H4zM4 9.3h16M4 14.6h16M9.3 4v16M14.6 4v16", printer: "M7 8V4h10v4M7 17H4V9h16v8h-3M7 14h10v6H7z",
  check: "M5 12.5l4.5 4.5L19 7.5", play: "M8 5l11 7-11 7z", enter: "M19 5v7a3 3 0 01-3 3H6M10 11l-4 4 4 4", x: "M6 6l12 12M18 6L6 18",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z",
};
const I = (n, s = 18, w = 1.6, cls = "") => `<svg class="ic ${cls}" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${P[n]}"/></svg>`;
const MARK = `<svg class="mark" viewBox="8 8 48 48" aria-hidden="true"><path class="f" d="M26 8H52V20H26Z M12 22H24V28H44V40H24V56H12Z" fill="#d8d3c8"/><path class="o" d="M12 8H24V20H12Z" fill="#3ee6ff"/></svg>`;
const TOOLS = ["cursor", "sketch", "pin", "scissors", "scan", "boxes", "history", "layers", "camera", "expand", "ruler"];
const VIEWS = { Iso: [-27, 33], Front: [0, 3], Side: [-90, 3], Top: [0, 89.5], Under: [-27, -55] };

export async function initDesk() {
  const frame = document.getElementById("desk-frame"), root = document.getElementById("desk");
  if (!frame || !root) return;
  const RM = reducedMotion();
  const d = await (await fetch("assets/data/case.json")).json();
  const rev = `r${nn(d.rev)}`, feats = d.features, run = feats.filter((f) => f.built), of = run.length;
  const warn = d.rollup.WARN || 0, pass = d.rollup.PASS || 0;
  const size = (b) => [b[1][0] - b[0][0], b[1][1] - b[0][1], b[1][2] - b[0][2]].map((v) => v.toFixed(1));
  const sugg = [`Explain the ${warn} warning${warn === 1 ? "" : "s"} on ${rev}`, `Review ${rev}: design, engineering, print`, "What should I measure before printing?", "Run the program again"];

  // ---------- the window ----------
  root.innerHTML = `
    <div class="d-room"></div><div class="d-pool"></div>
    <canvas class="d-gl" id="d-gl" tabindex="0" role="img" aria-label="${esc(d.name)}, the solid the CAD kernel built: ${size(d.bbox).join(" by ")} millimetres, ${d.faces} faces. Drag to turn it."></canvas>
    <svg class="d-dims" id="d-dims" aria-hidden="true">${[0, 1, 2].map(() => "<line/><circle r='3'/><circle r='3'/>").join("")}</svg>
    ${[0, 1, 2].map((i) => `<span class="d-dim" data-i="${i}" aria-hidden="true"></span>`).join("")}
    <div class="d-cap tl d-glass">${MARK}<b>${esc(d.name)}</b><span class="mono rev">${rev}</span><span class="d-tag">Unreleased</span>${I("down", 14)}</div>
    <nav class="d-stages d-glass" aria-label="Stages">${["Describe", "Design", "Fit", "Review", "Make"].map((s, i) => `<div class="d-seg ${i === 1 ? "on" : ""}"><b>${s}</b><span id="d-st${i}"></span></div>`).join("")}</nav>
    <div class="d-cap tr d-glass">${d.slice ? `<span class="printer">${I("printer", 15)}${esc(d.slice.printer)}</span><i></i>` : ""}<span class="d-b">${I("search", 16)}<kbd>⌘K</kbd></span><span class="d-b">${I("gear", 16)}</span></div>
    <div class="d-dock d-glass" aria-hidden="true">${TOOLS.map((ic, i) => `${i === 7 || i === 9 ? "<hr>" : ""}<span class="${i ? "" : "on"}">${I(ic, 18)}</span>`).join("")}</div>
    <aside class="d-program d-glass" id="d-program" aria-label="Program: the features in build order">
      <header><b>Program</b><span class="mono">${feats.length}</span><em class="rest">build order</em><em class="mono run"><i class="d-live a"></i><span id="d-run"></span></em></header>
      <i class="d-pc" id="d-pc"></i>
      ${feats.map((f, i) => `<button type="button" class="d-ln ${f.built ? "" : "off"}" data-i="${i}" ${f.built ? "" : "disabled"}><span class="mono no">${nn(i + 1)}</span><span class="gl">${I("check", 13, 2.2, "ck")}${I("play", 10, 2.4, "pl")}</span><b>${esc(f.label)}</b><span class="mono kw">${esc(f.built ? f.role : "off")}</span></button>`).join("")}
    </aside>
    <p class="d-readout mono" id="d-readout"></p>
    <div class="d-views d-glass" role="group" aria-label="View">${I("grid", 15)}${Object.keys(VIEWS).map((v, i) => `<button type="button" data-v="${v}" aria-pressed="${!i}">${v}</button>`).join("")}</div>
    <div class="d-pipe d-glass" id="d-pipe" aria-label="Pipeline">${["Parameters", "Solid", "Exports", "Checks", "Slice", "Release"].filter((n) => n !== "Slice" || d.slice).map((n) => `<div data-n="${n}"><b><i></i>${n}</b><span class="mono"></span></div>`).join("")}<div class="auto"><b>Auto</b><span class="d-switch"></span></div></div>
    <p class="d-pick" id="d-pick"></p>
    <section class="d-third" id="d-third" aria-live="polite">
      <p class="over mono"><span class="d-live a"></span>Building<i id="d-of"></i></p>
      <h3 id="d-title"></h3>
      <div class="d-track" id="d-track" style="grid-template-columns:repeat(${of},1fr)">${run.map(() => "<i></i>").join("")}</div>
      <p class="d-around"><span id="d-prev"></span><span id="d-next"></span></p>
    </section>
    <section class="d-talk">
      <div class="d-answer d-glass" id="d-answer" role="region" aria-live="polite" aria-label="Answer"></div>
      <p class="d-lead"><span class="d-live"></span>Ask about this design, or describe a change.</p>
      <div class="d-cmd d-glass">
        <div class="d-sugg" id="d-sugg">${sugg.map((s, i) => `<button type="button" data-k="${i + 1}" aria-pressed="false"><kbd class="d-k">${i + 1}</kbd>${esc(s)}</button>`).join("")}</div>
        <div class="d-well"><div class="d-prompt" id="d-prompt"><span class="d-gt mono">›</span><i class="d-caret"></i><p></p></div>
          <footer>${I("clip", 17)}<span class="d-agent">${I("spark", 15)}Claude Code · Default${I("down", 13)}</span><em>Press 1 to 4 · drag the part to turn it</em><span class="d-send">${I("enter", 17, 2)}</span></footer></div>
      </div>
    </section>`;
  const $ = (s) => root.querySelector(s);
  const lines = [...root.querySelectorAll(".d-ln")], track = [...$("#d-track").children];
  const prompt = $("#d-prompt"), answer = $("#d-answer"), program = $("#d-program");
  const placeholder = `Ask about ${d.name}, or describe a change…`;
  const stepOf = feats.map((f) => (f.built ? run.indexOf(f) + 1 : 0));          // program line -> build step (0: not built)
  const lineOf = run.map((f) => feats.indexOf(f));                              // build step - 1 -> program line

  // ---------- layout: the frame scales the window; a phone gets its own arrangement ----------
  let compact = false, LW = W, LH = H;
  const layout = () => {
    const w = frame.clientWidth;
    compact = w < 760;
    frame.classList.toggle("compact", compact);
    LW = compact ? CW : W; LH = compact ? CH : H;
    frame.style.setProperty("--s", (w / LW).toFixed(5));
    scene && scene.resize();
  };

  // ---------- the 3D view ----------
  let scene = null;
  const st = { az: VIEWS.Iso[0], el: VIEWS.Iso[1], building: false, t: 0, step: 0, sel: -1, k: 0, visible: false, need: true, tween: null, zoom: 0, drag: null };
  const light = () => getComputedStyle(root).getPropertyValue("--d-light").trim() === "1";

  async function boot() {
    const THREE = await import("three");
    const parts = await loadGLB("assets/data/case.glb");
    const canvas = $("#d-gl");
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
    renderer.setClearColor(0, 0); renderer.outputColorSpace = THREE.SRGBColorSpace;
    const sc = new THREE.Scene(), cam = new THREE.PerspectiveCamera(22, W / H, 10, 4000);
    cam.up.set(0, 0, 1);
    const hemi = new THREE.HemisphereLight(0xffffff, 0x3a3836, 1.05); hemi.position.set(0, 0, 1); sc.add(hemi);
    const key = new THREE.DirectionalLight(0xfff3e4, 1.85); key.position.set(-260, -180, 420); sc.add(key);
    const fill = new THREE.DirectionalLight(0xc9d4ff, 0.5); fill.position.set(300, 160, 120); sc.add(fill);

    const mesh = {}, bbs = [];
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x1a1816, transparent: true, opacity: 0.55 });
    for (const p of parts) {
      if (p.lines) continue;
      const geo = creased(THREE, p.pos, p.index, 32);
      const mat = new THREE.MeshStandardMaterial({ color: 0xd3cec4, roughness: 0.82, metalness: 0, side: THREE.DoubleSide, transparent: true, opacity: 0,
        emissive: 0xffe9cf, emissiveIntensity: 0, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
      const m = new THREE.Mesh(geo, mat);
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 28), edgeMat.clone());
      m.add(e); m.visible = false; sc.add(m);
      geo.computeBoundingBox();
      mesh[p.name] = { m, e, part: p.extras.part, bb: geo.boundingBox.clone() };
    }
    // the size built so far, after each line of the program
    const acc = new THREE.Box3();
    for (const f of run) { acc.union(mesh[f.id].bb); bbs.push(acc.clone()); }
    const full = bbs[bbs.length - 1], centre = full.getCenter(new THREE.Vector3()), R = full.getSize(new THREE.Vector3()).length() / 2;

    // a soft cast under each part, as the studio's key light would leave it
    const shadows = {};
    const tex = (() => {
      const c = document.createElement("canvas"); c.width = c.height = 256;
      const x = c.getContext("2d"); x.shadowColor = "#000"; x.shadowBlur = 34; x.shadowOffsetX = 600; x.fillStyle = "#000";
      x.beginPath(); x.roundRect(-600 + 52, 52, 152, 152, 22); x.fill();
      return new THREE.CanvasTexture(c);
    })();
    for (const pid of [...new Set(run.map((f) => f.part))]) {
      const b = new THREE.Box3(); run.filter((f) => f.part === pid).forEach((f) => b.union(mesh[f.id].bb));
      const s = b.getSize(new THREE.Vector3()), c = b.getCenter(new THREE.Vector3());
      const pl = new THREE.Mesh(new THREE.PlaneGeometry(s.x * 1.72, s.y * 1.72), new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0, depthWrite: false }));
      pl.position.set(c.x + 7, c.y - 5, -0.2); sc.add(pl); shadows[pid] = pl;
    }

    const dimSvg = $("#d-dims"), dl = [...dimSvg.querySelectorAll("line")], dc = [...dimSvg.querySelectorAll("circle")], dt = [...root.querySelectorAll(".d-dim")];
    const cur = bbs[0].clone();                                 // the box the dimension lines follow, eased towards the built size
    const v = new THREE.Vector3();
    const px = (x, y, z) => { v.set(x, y, z).project(cam); return [(v.x + 1) / 2 * LW, (1 - v.y) / 2 * LH]; };

    function place() {
      const a = st.az * Math.PI / 180, e = st.el * Math.PI / 180;
      const hf = 2 * Math.atan(Math.tan(cam.fov * Math.PI / 360) * cam.aspect);
      const fit = Math.max(R / Math.sin(cam.fov * Math.PI / 360), R / Math.sin(hf / 2));
      const dist = fit * (compact ? 1.16 : 1.2) * (1 + (compact ? 0.1 : 0.16) * st.zoom);
      cam.position.set(centre.x + dist * Math.cos(e) * Math.sin(a), centre.y - dist * Math.cos(e) * Math.cos(a), centre.z + dist * Math.sin(e));
      cam.lookAt(centre);
      // the part sits left of the listing and above the bar; while it builds it rises to leave room for the title
      const ox = compact ? 0 : 88, oy = compact ? lerp(44, 64, st.zoom) : lerp(128, 168, st.zoom);
      cam.setViewOffset(LW, LH, ox, oy, LW, LH);
      cam.updateMatrixWorld();
    }

    function dims() {
      const m = 9, b = cur, x0 = b.min.x, x1 = b.max.x, y0 = b.min.y, y1 = b.max.y, z1 = b.max.z;
      const segs = [[[x0 - m, y1, 0], [x0 - m, y1, z1]], [[x0 - m, y1, 0], [x0 - m, y0, 0]], [[x0, y0 - m, 0], [x1, y0 - m, 0]]];
      const txt = [z1, y1 - y0, x1 - x0];
      segs.forEach(([p, q], i) => {
        const [ax, ay] = px(...p), [bx, by] = px(...q);
        dl[i].setAttribute("x1", ax); dl[i].setAttribute("y1", ay); dl[i].setAttribute("x2", bx); dl[i].setAttribute("y2", by);
        dc[i * 2].setAttribute("cx", ax); dc[i * 2].setAttribute("cy", ay); dc[i * 2 + 1].setAttribute("cx", bx); dc[i * 2 + 1].setAttribute("cy", by);
        dt[i].style.transform = `translate(${((ax + bx) / 2).toFixed(1)}px, ${((ay + by) / 2).toFixed(1)}px) translate(-50%, -50%)`;
        dt[i].textContent = txt[i].toFixed(1);
      });
    }

    let wasLight = null;
    function theme() {
      const L = light();
      if (L === wasLight) return; wasLight = L;
      hemi.intensity = L ? 1.55 : 1.05; hemi.groundColor.set(L ? 0x8d8a85 : 0x3a3836); key.intensity = L ? 1.7 : 1.85; key.color.set(L ? 0xffffff : 0xfff3e4);
      for (const k in mesh) { mesh[k].m.material.color.set(L ? 0xe2ded5 : 0xd3cec4); mesh[k].e.material.color.set(L ? 0x34312d : 0x1a1816); }
      st.need = true;
    }

    // one frame: where each feature is in its landing, the size so far, the camera
    function draw(now) {
      theme();
      const step = st.building ? Math.min(of, Math.floor(st.t / STEP) + 1) : of;
      const accent = light() ? 0x06708d : 0x3ee6ff;
      run.forEach((f, i) => {
        const o = mesh[f.id], since = st.building ? st.t - i * STEP : 1e9;
        const k = easeOut(clamp(since / LAND)), fl = RM ? 0 : 1 - clamp(since / FLASH);
        o.m.visible = k > 0.001; o.m.material.opacity = k; o.m.material.transparent = k < 1; o.m.material.depthWrite = k > 0.6;
        o.m.position.z = RM ? 0 : 7 * (1 - k); o.e.material.opacity = 0.55 * k;
        const picked = !st.building && st.sel === lineOf[i];
        o.m.material.emissive.set(picked ? accent : 0xffe9cf);
        o.m.material.emissiveIntensity = picked ? (light() ? 0.5 : 0.42) : 0.55 * fl * fl;
      });
      for (const pid in shadows) {
        const first = run.findIndex((f) => f.part === pid), since = st.building ? st.t - first * STEP : 1e9;
        shadows[pid].material.opacity = (light() ? 0.26 : 0.62) * easeOut(clamp(since / 700)) * clamp((st.el + 4) / 12);
      }
      const target = bbs[step - 1], sp = RM || !st.building ? 1 : 0.16;
      cur.min.lerp(target.min, sp); cur.max.lerp(target.max, sp);
      const settled = cur.min.distanceTo(target.min) + cur.max.distanceTo(target.max) < 0.02;
      if (settled) cur.copy(target);
      place(); dims();
      renderer.render(sc, cam);
      return settled;
    }

    function resize() {
      const s = frame.clientWidth / LW, dpr = Math.min(2, devicePixelRatio || 1);
      renderer.setPixelRatio(Math.max(1, Math.min(2.5, dpr * s)));
      renderer.setSize(LW, LH, false);
      cam.aspect = LW / LH; cam.updateProjectionMatrix(); st.need = true; kick();
    }
    scene = { draw, resize, bbs };
    new MutationObserver(() => { st.need = true; kick(); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { st.need = true; kick(); });
    resize();
  }

  // ---------- the clock ----------
  let raf = 0, last = 0;
  function tick(now) {
    raf = 0;
    const dt = Math.min(64, now - (last || now)); last = now;
    let moving = false;
    if (st.building && st.visible) {
      st.t += dt; moving = true;
      const step = Math.min(of, Math.floor(st.t / STEP) + 1);
      if (step !== st.step) cue(step);
      if (st.t > of * STEP + 500) finish();
    } else if (st.building) moving = false;
    const zt = st.building ? 1 : 0;
    if (Math.abs(st.zoom - zt) > 0.002) { st.zoom = RM ? zt : st.zoom + (zt - st.zoom) * (1 - Math.exp(-dt / 190)); moving = true; } else st.zoom = zt;
    if (st.tween) {
      const tw = st.tween, k = clamp((now - tw.t0) / tw.ms), e = easeInOut(k);
      st.az = lerp(tw.a0, tw.a1, e); st.el = lerp(tw.e0, tw.e1, e);
      if (k >= 1) st.tween = null; else moving = true;
    }
    if (scene && (moving || st.need || st.drag)) { st.need = false; if (!scene.draw(now)) moving = true; }
    if (moving || st.drag) kick(); else last = 0;
  }
  function kick() { if (!raf) raf = requestAnimationFrame(tick); }

  // ---------- states ----------
  const stage = (i, text, cls = "") => { const el = $(`#d-st${i}`); el.textContent = text; el.className = cls; };
  const pipe = (n, text, cls = "") => { const el = root.querySelector(`#d-pipe [data-n="${n}"]`); if (el) { el.className = cls; el.lastElementChild.textContent = text; } };
  function readout(step) {
    const done = step >= of && !st.building, b = scene ? scene.bbs[Math.max(0, step - 1)] : null;
    const dims = b && !done ? [b.max.x - b.min.x, b.max.y - b.min.y, b.max.z - b.min.z].map((v) => v.toFixed(1)) : size(d.bbox);
    $("#d-readout").innerHTML = `${dims.join(" × ")} mm${done ? `<i>·</i>${d.volume_cm3} cm³` : ""}<em>${done ? `as printed, ${d.parts.length} parts` : "as modelled so far"}</em>`;
  }
  function values(done) {
    stage(0, `${d.known.measured}/${d.known.of} measured`);
    stage(1, done ? `${feats.length} features` : `${st.step} of ${of}`);
    stage(2, done && d.fit ? `${Math.floor(d.fit.yield * 100)}% modelled` : "—", done ? "pass" : "");
    stage(3, done ? (warn ? `${warn} to review` : "All pass") : "—", done ? (warn ? "warn" : "pass") : "");
    stage(4, done ? (d.gate && d.gate.ready ? "Ready" : "Not ready") : "—");
    pipe("Parameters", rev);
    pipe("Solid", done ? `${d.faces} faces` : "building", done ? "" : "run");
    pipe("Exports", done ? (d.exports || []).sort((a, b) => ["step", "stl", "obj", "glb"].indexOf(a) - ["step", "stl", "obj", "glb"].indexOf(b)).map((e) => "." + e).join(" ") : "waiting", done ? "" : "idle");
    pipe("Checks", done ? `${pass} pass${warn ? ` · ${warn} review` : ""}` : "waiting", done ? "" : "idle");
    pipe("Slice", done && d.slice ? d.slice.time : "waiting", done ? "" : "idle");
    pipe("Release", done ? "ready" : "waiting", "idle");
  }
  function cue(step) {
    st.step = step;
    const li = lineOf[step - 1], f = feats[li];
    lines.forEach((ln, i) => { const s = stepOf[i]; ln.classList.remove("sel"); ln.classList.toggle("done", s > 0 && s < step); ln.classList.toggle("now", s === step); ln.classList.toggle("todo", s === 0 || s > step); ln.querySelector(".kw").textContent = s === step ? "building" : feats[i].built ? feats[i].role : "off"; });
    $("#d-pc").style.height = `${li * 32 + 16}px`;
    $("#d-run").textContent = `${step} of ${of}`; $("#d-of").textContent = `${step} of ${of}`;
    const h = $("#d-title"); h.innerHTML = `<span class="mono">${nn(li + 1)}</span>${esc(f.label)}`;
    h.classList.remove("swap"); void h.offsetWidth; h.classList.add("swap");
    track.forEach((el, i) => { el.className = i + 1 < step ? "done" : i + 1 === step ? "now" : ""; });
    const pv = step > 1 ? lineOf[step - 2] : -1, nx = step < of ? lineOf[step] : -1;
    $("#d-prev").innerHTML = pv >= 0 ? `built<b class="mono">${nn(pv + 1)}</b>${esc(feats[pv].label)}` : "";
    $("#d-next").innerHTML = nx >= 0 ? `next<b class="mono">${nn(nx + 1)}</b>${esc(feats[nx].label)}` : "then<b class=\"mono\">→</b>checks";
    values(false); readout(step);
  }
  function build(from = 0) {
    say(""); pick(-1);
    st.building = true; st.t = from; st.step = 0;
    root.classList.add("building"); program.classList.add("running");
    prompt.querySelector("p").textContent = placeholder;
    cue(Math.min(of, Math.floor(from / STEP) + 1)); kick();
  }
  function finish() {
    st.building = false; st.step = of; st.t = 1e9;
    root.classList.remove("building"); program.classList.remove("running");
    lines.forEach((ln, i) => { ln.classList.remove("done", "now", "todo"); ln.querySelector(".kw").textContent = feats[i].built ? feats[i].role : "off"; });
    values(true); readout(of); st.need = true; kick();
  }

  // ---------- the listing: choose a line to see the faces that feature made ----------
  function pick(i) {
    st.sel = st.sel === i ? -1 : i;
    lines.forEach((ln, k) => ln.classList.toggle("sel", k === st.sel));
    program.classList.toggle("picked", st.sel >= 0);
    const el = $("#d-pick"), f = feats[st.sel];
    el.classList.toggle("on", !!f);
    if (f) el.innerHTML = `<span class="mono">${nn(st.sel + 1)}</span><b>${esc(f.label)}</b><span>${esc(f.doc || `The faces this feature made, on the ${f.part}.`)}</span>`;
    st.need = true; kick();
  }
  lines.forEach((ln, i) => ln.addEventListener("click", () => { if (!st.building && feats[i].built) pick(i); }));

  // ---------- the bar: a suggestion opens what the engine recorded ----------
  const row = (c) => `<li><span class="st ${c.status === "PASS" ? "" : "warn"}">${c.status === "PASS" ? "Pass" : "Review"}</span><b>${esc(c.label)}</b><span class="v">${esc(c.value)}</span>`;
  const answers = {
    1: () => { const ws = d.checks.filter((c) => c.status !== "PASS"); return [`${ws.length} to review · ${rev}`, "Nothing failed. These want a look.", `<ul>${ws.map((c) => `${row(c)}<p>${esc(c.detail)}</p></li>`).join("")}</ul>`, `Computed by the engine on the solid of ${rev}. ${esc(d.gate && d.gate.evidence || "")}`]; },
    2: () => { const ev = {}; d.checks.forEach((c) => (ev[c.evidence] = (ev[c.evidence] || 0) + 1)); return [`${pass} pass · ${warn} review`, `Review of ${rev}`, `<ul class="two">${d.checks.map((c) => `${row(c)}</li>`).join("")}</ul>`, `${Object.entries(ev).map(([k, n]) => `${n} ${k}`).join(" · ")}. A slice is a simulation, not a print.`]; },
    3: () => { const as = d.actions.filter((a) => a.id !== "print"); return [`${d.known.measured} of ${d.known.of} measured`, "Before you print", `<ul>${as.map((a) => `<li><span class="st warn">${esc(a.id)}</span><b>${esc(a.title)}</b><span class="v">${esc(a.cost)}</span><p>${esc(a.why)}</p></li>`).join("")}</ul>`, d.fit ? esc(d.fit.model) : ""]; },
  };
  function say(k) {
    root.querySelectorAll(".d-sugg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.k === String(k))));
    const on = !!answers[k];
    answer.classList.toggle("on", on);
    prompt.classList.toggle("said", on);
    prompt.querySelector("p").textContent = on ? sugg[k - 1] : placeholder;
    if (!on) return;
    const [kick_, title, body, foot] = answers[k]();
    answer.innerHTML = `<header><span class="mono">${esc(kick_)}</span><b>${esc(title)}</b><button type="button" class="x" aria-label="Close">${I("x", 15, 2)}</button></header>${body}${foot ? `<p>${foot}</p>` : ""}`;
    answer.querySelector(".x").addEventListener("click", () => say(""));
  }
  function choose(k) {
    if (st.building) return;
    if (k === 4) return build();
    say(answer.classList.contains("on") && prompt.querySelector("p").textContent === sugg[k - 1] ? "" : k);
  }
  root.querySelectorAll(".d-sugg button").forEach((b) => b.addEventListener("click", () => choose(+b.dataset.k)));
  let hot = false;
  frame.addEventListener("pointerenter", () => (hot = true)); frame.addEventListener("pointerleave", () => (hot = false));
  addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (!(hot || frame.contains(document.activeElement))) return;
    if (e.key >= "1" && e.key <= "4") { choose(+e.key); e.preventDefault(); }
    else if (e.key === "Escape") { say(""); if (st.sel >= 0) pick(st.sel); }
  });

  // ---------- turning the part ----------
  const gl = $("#d-gl");
  const setView = (name) => root.querySelectorAll(".d-views button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === name)));
  const glide = (a1, e1, ms = 520) => { let da = ((a1 - st.az + 540) % 360) - 180; st.tween = RM ? null : { a0: st.az, a1: st.az + da, e0: st.el, e1, t0: performance.now(), ms }; if (RM) { st.az = a1; st.el = e1; } st.need = true; kick(); };
  root.querySelectorAll(".d-views button").forEach((b) => b.addEventListener("click", () => { setView(b.dataset.v); glide(...VIEWS[b.dataset.v]); }));
  gl.addEventListener("pointerdown", (e) => { st.drag = { x: e.clientX, y: e.clientY, az: st.az, el: st.el, moved: false }; st.tween = null; gl.setPointerCapture(e.pointerId); });
  gl.addEventListener("pointermove", (e) => {
    if (!st.drag) return;
    const s = frame.clientWidth / LW, dx = (e.clientX - st.drag.x) / s, dy = (e.clientY - st.drag.y) / s;
    if (!st.drag.moved && Math.hypot(dx, dy) < 4) return;
    if (!st.drag.moved && e.pointerType === "touch" && Math.abs(dy) > Math.abs(dx)) { st.drag = null; return; }   // a vertical swipe scrolls the page
    st.drag.moved = true; root.classList.add("orbiting"); setView("");
    st.az = st.drag.az - dx * 0.32; st.el = clamp(st.drag.el + dy * 0.26, -70, 89.5); kick();
  });
  const drop = () => { st.drag = null; root.classList.remove("orbiting"); st.need = true; kick(); };
  gl.addEventListener("pointerup", drop); gl.addEventListener("pointercancel", drop);
  gl.addEventListener("keydown", (e) => {
    const m = { ArrowLeft: [8, 0], ArrowRight: [-8, 0], ArrowUp: [0, 6], ArrowDown: [0, -6] }[e.key];
    if (!m) return;
    e.preventDefault(); setView(""); st.az += m[0]; st.el = clamp(st.el + m[1], -70, 89.5); st.need = true; kick();
  });

  // ---------- start ----------
  const replay = document.getElementById("desk-replay");
  replay && replay.addEventListener("click", () => build());
  layout(); new ResizeObserver(layout).observe(frame);
  say(""); finish();                                 // the finished design is the resting state, and what shows without WebGL
  const q = new URLSearchParams(location.search).get("desk") || "";   // desk=build:6, desk=answer:2, desk=rest: a fixed moment, for pictures
  try { await boot(); } catch (err) { console.error(err); frame.classList.add("no-gl"); }
  readout(of);
  if (q.startsWith("build")) { const n = clamp(+(q.split(/[:-]/)[1] || 6), 1, of); st.visible = false; build((n - 1) * STEP + STEP * 0.6); scene && scene.draw(0); for (let i = 0; i < 60; i++) scene && scene.draw(0); return; }
  if (q.startsWith("answer")) { say(+(q.split(/[:-]/)[1] || 1)); kick(); return; }
  if (q.startsWith("pick")) { pick(clamp(+(q.split(/[:-]/)[1] || 6), 1, feats.length) - 1); return; }
  const io = new IntersectionObserver(([e]) => {
    st.visible = e.isIntersecting && e.intersectionRatio > 0.35;
    if (st.visible && !io.played && !RM && !q) { io.played = true; build(); }
    if (st.visible) kick();
  }, { threshold: [0, 0.35, 0.6] });
  io.observe(frame);
  kick();
}

// Normals that stay sharp across an edge and smooth around a curve: each corner averages the faces that meet at its
// vertex within the crease angle. The exporter welds positions, so a box would otherwise shade like a pillow.
function creased(THREE, pos, index, deg) {
  const n = index.length / 3, fn = new Float32Array(n * 3), cos = Math.cos(deg * Math.PI / 180);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const at = Array.from({ length: pos.length / 3 }, () => []);
  for (let f = 0; f < n; f++) {
    const i0 = index[f * 3], i1 = index[f * 3 + 1], i2 = index[f * 3 + 2];
    a.fromArray(pos, i0 * 3); b.fromArray(pos, i1 * 3).sub(a); c.fromArray(pos, i2 * 3).sub(a); b.cross(c);   // area-weighted
    fn[f * 3] = b.x; fn[f * 3 + 1] = b.y; fn[f * 3 + 2] = b.z;
    at[i0].push(f); at[i1].push(f); at[i2].push(f);
  }
  const P = new Float32Array(n * 9), N = new Float32Array(n * 9);
  for (let f = 0; f < n; f++) {
    a.fromArray(fn, f * 3); const la = a.length() || 1;
    for (let k = 0; k < 3; k++) {
      const vi = index[f * 3 + k];
      c.set(0, 0, 0);
      for (const g of at[vi]) { b.fromArray(fn, g * 3); if (b.dot(a) / ((b.length() || 1) * la) >= cos) c.add(b); }
      c.normalize();
      P.set([pos[vi * 3], pos[vi * 3 + 1], pos[vi * 3 + 2]], f * 9 + k * 3); N.set([c.x, c.y, c.z], f * 9 + k * 3);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(P, 3)); geo.setAttribute("normal", new THREE.BufferAttribute(N, 3));
  return geo;
}
