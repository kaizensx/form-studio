// The 3D viewport of the recreated app (Viewport.qml): the kernel's mesh in clay, its B-rep edges, the plate,
// overall dimensions, what the part holds (in blueprint), the wall-thickness marker and the print simulation.
// Renders on demand: nothing draws while nothing moves, the page is hidden, or the viewport is off-screen.
import * as THREE from "three";
import { OrbitControls } from "../vendor/OrbitControls.js";
import { INKS } from "./data.js";

const CLAY = 0xd8d3c8, DATUM = 0xb9e8d7, BLUE = 0x86a8ff, SIGNAL = 0xff6f51;
const easeMove = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);   // close to Theme.easeMove
const easeOut = (t) => 1 - Math.pow(1 - t, 3.2);
const cad = (x, y, z) => new THREE.Vector3(x, z, -y);                                  // CAD Z-up to three Y-up

export const VIEWS = { iso: [-1, -1.12, 0.92], front: [0, -1, 0.1], side: [1, 0, 0.1], top: [0.0001, -0.0001, 1], under: [0.0001, -0.0001, -1] };

export class Viewport {
  constructor(canvas, labels, opts = {}) {
    this.canvas = canvas; this.labels = labels; this.opts = opts;
    this._loop = this._loop.bind(this); this.onscreen = true;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 5, 4000);
    this.world = new THREE.Group();                       // CAD frame
    this.world.rotation.x = -Math.PI / 2;
    this.scene.add(this.world);
    this.scene.add(new THREE.HemisphereLight(0xf2f4f3, 0x3b4246, 1.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.9); key.position.set(-180, 320, 260); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xdfe8ff, 0.55); fill.position.set(260, 120, -200); this.scene.add(fill);
    this.anims = [];
    this.features = new Map();
    this.visible = true; this.onscreen = true; this.dirty = true;
    this.controls = new OrbitControls(this.camera, canvas);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.09, enablePan: false, enableZoom: !!opts.zoom, rotateSpeed: 0.75 });
    this.controls.addEventListener("change", () => (this.dirty = true));
    this.controls.addEventListener("start", () => { this.userDriving = true; this.anims = this.anims.filter((a) => a.kind !== "camera"); opts.onInteract && opts.onInteract(); });
    this.controls.addEventListener("end", () => (this.userDriving = false));
    if (opts.touchPanY) canvas.style.touchAction = "pan-y";
    this._plate();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    new IntersectionObserver(([e]) => { this.onscreen = e.isIntersecting; this.kick(); }, { rootMargin: "100px" }).observe(canvas);
    document.addEventListener("visibilitychange", () => this.kick());
    this.resize();
  }

  get dirty() { return this._dirty; }
  set dirty(v) { this._dirty = v; if (v) this.kick(); }

  // ---------- plate and grid (the bench) ----------
  _plate() {
    const g = new THREE.Group();
    const R = 380, step = 10, pos = [], col = [];
    for (let v = -R; v <= R; v += step) {
      for (const [a, b] of [[[v, -R], [v, R]], [[-R, v], [R, v]]]) {
        const N = 24;
        for (let i = 0; i < N; i++) {
          const t0 = i / N, t1 = (i + 1) / N;
          const p0 = [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0], p1 = [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1];
          for (const p of [p0, p1]) {
            const d = Math.hypot(p[0], p[1]);
            const inPlate = Math.abs(p[0]) <= 90.01 && Math.abs(p[1]) <= 90.01;
            const al = Math.max(0, 1 - d / R) ** 1.6 * (inPlate ? 0.11 : 0.07);
            pos.push(p[0], p[1], 0); col.push(1, 1, 1, al);
          }
        }
      }
    }
    const gg = new THREE.BufferGeometry();
    gg.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    gg.setAttribute("color", new THREE.Float32BufferAttribute(col, 4));
    g.add(new THREE.LineSegments(gg, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false })));
    const fillM = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.025, depthWrite: false });
    const fill = new THREE.Mesh(new THREE.PlaneGeometry(180, 180), fillM); fill.position.z = -0.05; g.add(fill);
    this.plateG = g; this.plateRim = [fill];
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(180, 180)), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.16 }));
    g.add(edge); this.plateRim.push(edge);
    g.renderOrder = -1;
    this.world.add(g);
  }

  // ---------- the part ----------
  setPart(parts, info) {
    this.info = info;
    const bb = info.bbox;
    this.centre = new THREE.Vector3((bb[0][0] + bb[1][0]) / 2, (bb[0][1] + bb[1][1]) / 2, (bb[0][2] + bb[1][2]) / 2);
    this.size = new THREE.Vector3(bb[1][0] - bb[0][0], bb[1][1] - bb[0][1], bb[1][2] - bb[0][2]);
    // several parts as modelled can be wider than one plate (the slicer lays them out): the plate then sits under the
    // middle of the design and its outline shows only with the sliced toolpath, which is where the parts really print
    this.laidOut = this.size.x > 180 || this.size.y > 180;
    if (this.laidOut) { this.plateG.position.set(this.centre.x, this.centre.y, 0); this.plateRim.forEach((o) => { o.visible = false; }); }
    this.part = new THREE.Group(); this.world.add(this.part);
    for (const p of parts) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(p.pos, 3));
      if (p.lines) {
        const m = new THREE.LineBasicMaterial({ color: 0x0b0d0e, transparent: true, opacity: 0.55 });
        this.edges = new THREE.LineSegments(geo, m); this.edges.renderOrder = 2; this.part.add(this.edges);
        continue;
      }
      geo.setIndex(new THREE.BufferAttribute(p.index, 1));
      geo.computeVertexNormals();
      const mat = new THREE.MeshStandardMaterial({ color: CLAY, roughness: 0.82, metalness: 0, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.userData = p.extras;
      this.features.set(p.name, mesh);
      this.part.add(mesh);
    }
    this._dims(); this._device();
    this.frame(false);
    this.dirty = true;
  }

  _line(points, color, opacity, parent) {
    const g = new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(...p)));
    const l = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthTest: true }));
    (parent || this.world).add(l); return l;
  }
  _label(text, cls) { const el = document.createElement("div"); el.className = "lbl3 " + (cls || ""); el.textContent = text; this.labels.appendChild(el); return el; }

  _dims() {
    const [a, b] = this.info.bbox, off = 14, t = 4;
    const [x0, y0, z0] = a, [x1, y1, z1] = b;
    this.dims = new THREE.Group(); this.world.add(this.dims);
    const L = (pts) => this._line(pts, DATUM, 0.55, this.dims);
    // width along the front edge, depth along the left edge, height at the back-left corner
    L([[x0, y0 - off, 0], [x1, y0 - off, 0], [x0, y0 - off + t, 0], [x0, y0 - off - t, 0], [x1, y0 - off + t, 0], [x1, y0 - off - t, 0], [x0, y0 - 2, 0], [x0, y0 - off - 2, 0], [x1, y0 - 2, 0], [x1, y0 - off - 2, 0]]);
    L([[x0 - off, y0, 0], [x0 - off, y1, 0], [x0 - off + t, y0, 0], [x0 - off - t, y0, 0], [x0 - off + t, y1, 0], [x0 - off - t, y1, 0], [x0 - 2, y0, 0], [x0 - off - 2, y0, 0], [x0 - 2, y1, 0], [x0 - off - 2, y1, 0]]);
    L([[x0 - off, y1, z0], [x0 - off, y1, z1], [x0 - off - t, y1, z1], [x0 - off + t, y1, z1], [x0 - 2, y1, z1], [x0 - off - 2, y1, z1]]);
    const f = (v) => v.toFixed(1);
    this.dimLabels = [
      [this._label(f(x1 - x0)), new THREE.Vector3((x0 + x1) / 2, y0 - off, 0)],
      [this._label(f(y1 - y0)), new THREE.Vector3(x0 - off, (y0 + y1) / 2, 0)],
      [this._label(f(z1 - z0)), new THREE.Vector3(x0 - off, y1, (z0 + z1) / 2)],
    ];
  }

  _device() {
    const c = this.info.companions && this.info.companions[0];
    if (!c) return;
    const [w, th, h] = c.size;
    const g = new THREE.Group();
    const box = new THREE.BoxGeometry(w, th, h); box.translate(0, 0, h / 2);
    g.add(new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: BLUE, transparent: true, opacity: 0.5 })));
    g.add(new THREE.Mesh(box, new THREE.MeshBasicMaterial({ color: BLUE, transparent: true, opacity: 0.022, depthWrite: false, side: THREE.DoubleSide })));
    g.position.set(...c.origin); g.rotation.x = (c.rot_x_deg * Math.PI) / 180;
    this.world.add(g); this.device = g;
    this.deviceLabel = [this._label(`${c.label} · ${h} mm tall · not printed`, "dev"), new THREE.Vector3(0, 0, h * 0.62)];
    this._deviceAnchor = g;
  }

  setDims(on) { this.dims.visible = on; this.dimLabels.forEach(([el]) => el.classList.toggle("hide", !on)); this.dirty = true; }
  setDevice(on) { if (!this.device) return; this.device.visible = on; this.deviceLabel[0].classList.toggle("hide", !on); this.dirty = true; }
  setPartVisible(on) { this.part.visible = on; this.dirty = true; }

  // thickness: every sample is 1.2 mm or more on this design, so the map is clay everywhere; the thinnest sample is marked
  setThickness(th, on) {
    if (!this.thin && th) {
      const m = th.markers[0];
      this.thin = this._line([m.at, m.to], SIGNAL, 1);
      const dotG = new THREE.SphereGeometry(0.9, 12, 8);
      const d1 = new THREE.Mesh(dotG, new THREE.MeshBasicMaterial({ color: SIGNAL })); d1.position.set(...m.at); this.thin.add(d1);
      const d2 = d1.clone(); d2.position.set(...m.to); this.thin.add(d2);
      this.thinLabel = [this._label(m.label, "thin"), new THREE.Vector3(...m.at)];
    }
    if (!this.thin) return;
    this.thin.visible = on; this.thinLabel[0].classList.toggle("hide", !on);
    this.features.forEach((mesh) => { mesh.material.depthTest = true; });
    this.dirty = true;
  }

  highlight(id) {
    this.features.forEach((mesh, name) => {
      const on = id && name === id;
      mesh.material.emissive.setHex(on ? 0x2a5a4a : 0x000000);
      mesh.material.color.setHex(on ? 0xcfe3da : CLAY);
    });
    this.dirty = true;
  }

  // features appear in build order: a short rise and fade (Theme.cross)
  hideFeatures() { this.features.forEach((m) => { m.visible = false; }); if (this.edges) this.edges.visible = false; this.dirty = true; }
  showAll() { this.features.forEach((m) => { m.visible = true; m.position.z = 0; m.material.opacity = 1; m.material.transparent = false; }); if (this.edges) { this.edges.visible = true; this.edges.material.opacity = 0.55; } this.dirty = true; }
  revealFeature(name, ms = 420) {
    const m = this.features.get(name);
    if (!m) return;
    m.visible = true; m.material.transparent = true; m.material.opacity = 0; m.position.z = 6;
    this.tween(ms, (t) => { const e = easeOut(t); m.material.opacity = e; m.position.z = 6 * (1 - e); }, () => { m.material.transparent = false; m.material.opacity = 1; });
  }
  revealEdges(ms = 400) {
    if (!this.edges) return;
    this.edges.visible = true;
    this.tween(ms, (t) => (this.edges.material.opacity = 0.55 * easeOut(t)));
  }

  tween(ms, fn, done, kind) { this.anims.push({ t0: performance.now(), ms, fn, done, kind }); this.kick(); }

  // ---------- camera ----------
  _target() { return cad(this.centre.x, this.centre.y, this.centre.z * 0.7); }
  // the distance at which the part's box, seen from dir, spans FILL of the viewport's width or height (whichever binds);
  // fitted to the box's projection, not to its bounding sphere, so a flat part fills the view as much as a tall one
  _dist(dir) {
    const FILL = this.camera.aspect < 1 ? 0.7 : 0.55;
    const fwd = dir.clone().negate(), right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0));
    if (right.lengthSq() < 1e-8) right.set(1, 0, 0);
    right.normalize();
    const up = new THREE.Vector3().crossVectors(right, fwd).normalize(), t = this._target();
    let hx = 0, hy = 0, near = 0;
    const [a, b] = this.info.bbox;
    for (const x of [a[0], b[0]]) for (const y of [a[1], b[1]]) for (const z of [a[2], b[2]]) {
      const c = cad(x, y, z).sub(t);
      hx = Math.max(hx, Math.abs(c.dot(right))); hy = Math.max(hy, Math.abs(c.dot(up))); near = Math.max(near, c.dot(dir));
    }
    const tv = Math.tan((this.camera.fov * Math.PI) / 360), th = tv * this.camera.aspect;
    return near + Math.max(hx / (FILL * th), hy / (FILL * tv));
  }
  view(name, animate = true) {
    this.currentView = name;
    const d = VIEWS[name]; if (!d) return;
    const dir = cad(...d).normalize();
    const target = this._target();
    const to = target.clone().add(dir.clone().multiplyScalar(this._dist(dir)));
    this.glide(to, target, animate);
  }
  frame(animate = true) { this.view(this.currentView || "iso", animate); }
  glide(to, target, animate = true, ms = 420) {
    this.anims = this.anims.filter((a) => a.kind !== "camera");
    if (!animate) { this.camera.position.copy(to); this.controls.target.copy(target); this.camera.up.set(0, 1, 0); this.controls.update(); this.dirty = true; return; }
    const from = this.camera.position.clone(), t0 = this.controls.target.clone();
    // glide on the sphere around the target, not through the part
    const a = from.clone().sub(t0), b = to.clone().sub(target);
    const ra = a.length(), rb = b.length(); a.normalize(); b.normalize();
    this.tween(ms, (t) => {
      const e = easeMove(t);
      const dir = a.clone().lerp(b, e).normalize();
      if (dir.lengthSq() < 1e-6) dir.copy(b);
      this.controls.target.lerpVectors(t0, target, e);
      this.camera.position.copy(this.controls.target).add(dir.multiplyScalar(ra + (rb - ra) * e));
      this.controls.update();
    }, null, "camera");
  }
  orbitBy(rad) { // slow turn used by the story while the part builds
    const off = this.camera.position.clone().sub(this.controls.target);
    off.applyAxisAngle(new THREE.Vector3(0, 1, 0), rad);
    this.camera.position.copy(this.controls.target).add(off); this.controls.update(); this.dirty = true;
  }

  // ---------- print simulation: one instanced ribbon per toolpath segment, revealed by a single uniform ----------
  setToolpath(tp) {
    if (this.sim) return;
    this.tp = tp;
    const n = tp.count, m = tp.meta;
    const base = new THREE.BoxGeometry(1, 1, 1); base.translate(0.5, 0, -0.5);
    base.deleteAttribute("uv");
    const geo = new THREE.InstancedBufferGeometry(); geo.index = base.index;
    geo.setAttribute("position", base.getAttribute("position")); geo.setAttribute("normal", base.getAttribute("normal"));
    const cx = (m.bbox[0][0] + m.bbox[1][0]) / 2 - this.centre.x, cy = (m.bbox[0][1] + m.bbox[1][1]) / 2 - this.centre.y;
    const segA = new Float32Array(n * 4), zh = new Float32Array(n * 3), pp = new Float32Array(n * 2);
    for (let i = 0; i < n; i++) {
      segA[i * 4] = tp.seg[i * 4] - cx; segA[i * 4 + 1] = tp.seg[i * 4 + 1] - cy; segA[i * 4 + 2] = tp.seg[i * 4 + 2] - cx; segA[i * 4 + 3] = tp.seg[i * 4 + 3] - cy;
      const l = tp.layer[i]; zh[i * 3] = m.z[l]; zh[i * 3 + 1] = m.height[l]; zh[i * 3 + 2] = tp.type[i];
      pp[i * 2] = tp.p0[i]; pp[i * 2 + 1] = tp.p1[i];
    }
    this.simOffset = [cx, cy];
    geo.setAttribute("aSeg", new THREE.InstancedBufferAttribute(segA, 4));
    geo.setAttribute("aZH", new THREE.InstancedBufferAttribute(zh, 3));
    geo.setAttribute("aP", new THREE.InstancedBufferAttribute(pp, 2));
    geo.instanceCount = n;
    const cols = m.types.map((t) => new THREE.Color(INKS[t] || "#a8b2af"));
    while (cols.length < 16) cols.push(new THREE.Color(0xa8b2af));
    this.simU = { uNow: { value: 0 }, uW: { value: m.width_mm || 0.42 }, uCol: { value: cols }, uHide: { value: new Array(16).fill(0) }, uTop: { value: 0 } };
    const mat = new THREE.ShaderMaterial({
      uniforms: this.simU,
      vertexShader: `
        attribute vec4 aSeg; attribute vec3 aZH; attribute vec2 aP;
        uniform float uNow, uW; uniform vec3 uCol[16]; uniform float uHide[16]; uniform float uTop;
        varying vec3 vC; varying vec3 vN; varying float vTop;
        void main() {
          int ty = int(aZH.z + 0.5);
          float f = clamp((uNow - aP.x) / max(aP.y - aP.x, 1e-6), 0.0, 1.0);
          if (f <= 0.0 || uHide[ty] > 0.5) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
          vec2 a = aSeg.xy, b = aSeg.zw, d = b - a; float L = length(d);
          vec2 u = L > 1e-6 ? d / L : vec2(1.0, 0.0); vec2 v = vec2(-u.y, u.x);
          float ext = uW * 0.5;
          vec2 xy = a - u * ext + u * position.x * (L * f + uW) + v * position.y * uW;
          float z = aZH.x + position.z * aZH.y * 0.98;
          vec3 p = vec3(xy, z);
          vN = normalize(normalMatrix * mat3(vec3(u, 0.0), vec3(v, 0.0), vec3(0.0, 0.0, 1.0)) * normal);
          float lay = floor(uNow);
          vTop = step(lay - 0.5, floor(aP.x)) ;
          vC = uCol[ty];
          gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        }`,
      fragmentShader: `
        varying vec3 vC; varying vec3 vN; varying float vTop;
        void main() {
          vec3 l1 = normalize(vec3(-0.35, 0.8, 0.5)); vec3 l2 = normalize(vec3(0.6, 0.2, -0.4));
          float d = 0.42 + 0.5 * max(dot(vN, l1), 0.0) + 0.16 * max(dot(vN, l2), 0.0);
          vec3 c = vC * d * mix(0.86, 1.08, vTop);
          gl_FragColor = vec4(c, 1.0);
          #include <colorspace_fragment>
        }`,
    });
    this.sim = new THREE.Mesh(geo, mat); this.sim.frustumCulled = false; this.sim.visible = false;
    this.sim.position.set(0, 0, 0);
    this.world.add(this.sim);
    const noz = new THREE.Group();
    noz.add(new THREE.Mesh(new THREE.SphereGeometry(0.9, 16, 12), new THREE.MeshBasicMaterial({ color: DATUM })));
    const halo = new THREE.Mesh(new THREE.SphereGeometry(2.6, 16, 12), new THREE.MeshBasicMaterial({ color: DATUM, transparent: true, opacity: 0.22, depthWrite: false }));
    noz.add(halo);
    const cone = new THREE.Mesh(new THREE.ConeGeometry(2.2, 6, 20, 1, true), new THREE.MeshBasicMaterial({ color: DATUM, transparent: true, opacity: 0.16, depthWrite: false, side: THREE.DoubleSide }));
    cone.rotation.x = -Math.PI / 2; cone.position.z = 4.2; noz.add(cone);
    this.nozzle = noz; noz.visible = false; this.world.add(noz);
  }
  setSim(on) { if (!this.sim) return; this.sim.visible = on; this.nozzle.visible = on; if (this.laidOut) this.plateRim.forEach((o) => { o.visible = on; }); this.dirty = true; }
  setSimNow(p, here) {
    if (!this.sim) return;
    this.simU.uNow.value = p;
    if (here) this.nozzle.position.set(here.x - this.simOffset[0], here.y - this.simOffset[1], here.z + 0.1);
    this.dirty = true;
  }
  setHidden(types) { if (!this.sim) return; const h = this.simU.uHide.value; this.tp.meta.types.forEach((t, i) => (h[i] = types.has(t) ? 1 : 0)); this.dirty = true; }

  // ---------- frame loop ----------
  resize() {
    const el = this.canvas.parentElement, w = el.clientWidth, h = el.clientHeight;
    if (!w || !h) return;
    const s = parseFloat(getComputedStyle(this.canvas.closest(".app-frame") || el).getPropertyValue("--s")) || 1;
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1) * Math.min(1, s * 1.05));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    this.w = w; this.h = h;
    if (this.centre && !this.userDriving && !this.anims.some((a) => a.kind === "camera")) this.frame(false);
    this.dirty = true; this.kick();
  }
  kick() { if (!this.raf && this.onscreen && !document.hidden && this.controls) this.raf = requestAnimationFrame(this._loop); }
  _loop(now) {
    this.raf = 0;
    if (!this.onscreen || document.hidden) return;
    if (this.anims.length) {
      this.anims = this.anims.filter((a) => {
        const t = Math.min(1, (now - a.t0) / a.ms); a.fn(t);
        if (t >= 1) { a.done && a.done(); return false; }
        return true;
      });
      this.dirty = true;
    }
    if (this.tick) this.tick(now);
    const moving = this.controls.update();
    if (this.dirty || moving) { this.renderer.render(this.scene, this.camera); this._place(); this.dirty = false; }
    if (this.anims.length || this.tick || moving || this.userDriving) this.kick();
  }
  _place() {
    const v = new THREE.Vector3(), place = ([el, p], obj) => {
      v.copy(p); (obj || this.world).localToWorld(v); v.project(this.camera);
      const x = (v.x * 0.5 + 0.5) * this.w, y = (-v.y * 0.5 + 0.5) * this.h;
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    };
    if (this.dimLabels && this.dims.visible && this.part.visible) this.dimLabels.forEach((l) => place(l));
    if (this.deviceLabel && this.device.visible) place(this.deviceLabel, this.device);
    if (this.thinLabel && this.thin.visible) place(this.thinLabel);
  }
}
