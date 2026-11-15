// FORM viewport: the object on its plate. Z is up, millimetres throughout.
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

const INK = 0x1b1a18, CLAY = 0xd8d3c8, SIGNAL = 0xe5432a, GHOST = 0x3d4fb8;

function decode(b64, Type) {
  const bin = atob(b64), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Type(bytes.buffer);
}

export function geometryFrom(mesh) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(decode(mesh.positions, Float32Array), 3));
  g.setIndex(new THREE.BufferAttribute(decode(mesh.indices, Uint32Array), 1));
  g.computeVertexNormals();
  return g;
}

export class Viewer {
  constructor(host, { onPick, onHover } = {}) {
    this.host = host;
    this.onPick = onPick || (() => {});
    this.onHover = onHover || (() => {});
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.localClippingEnabled = true;
    this.renderer.toneMapping = THREE.NoToneMapping;
    host.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(26, 1, 1, 5000);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.addEventListener('change', () => this.requestRender());

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xb9b2a4, 1.15));
    const key = new THREE.DirectionalLight(0xffffff, 1.9);
    key.position.set(-120, -180, 260);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -160, right: 160, top: 160, bottom: -160, near: 10, far: 700 });
    key.shadow.radius = 6;
    key.shadow.bias = -0.0005;
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xfff4e6, 0.55);
    fill.position.set(200, 120, 90);
    this.scene.add(fill);

    this.plate = new THREE.Group();
    this.model = new THREE.Group();
    this.ghost = new THREE.Group();
    this.aux = new THREE.Group();
    this.scene.add(this.plate, this.model, this.ghost, this.aux);
    this.clip = new THREE.Plane(new THREE.Vector3(0, 0, -1), 1e6);
    this.section = null;
    this.features = new Map();
    this.selected = null;
    this.hovered = null;
    this.flagged = new Set();
    this.bounds = new THREE.Box3(new THREE.Vector3(-40, -40, 0), new THREE.Vector3(40, 40, 40));
    this.shift = new THREE.Vector3();
    this._buildPlate(180, 180);

    this.ray = new THREE.Raycaster();
    const el = this.renderer.domElement;
    let down = null;
    el.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
    el.addEventListener('pointerup', e => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 4) this.onPick(this._hit(e));
      down = null;
    });
    el.addEventListener('pointermove', e => {
      if (e.buttons) return;
      const f = this._hit(e);
      if (f !== this.hovered) { this.hovered = f; this._paint(); this.onHover(f, e); }
      el.style.cursor = f ? 'pointer' : 'grab';
    });
    el.addEventListener('pointerleave', () => { if (this.hovered) { this.hovered = null; this._paint(); this.onHover(null); } });
    new ResizeObserver(() => this.resize()).observe(host);
    this.resize();
    this.setView('iso', false);
    const loop = () => { requestAnimationFrame(loop); this._tick(); };
    loop();
  }

  requestRender() { this._dirty = true; }

  _tick() {
    if (this._tween) {
      const t = Math.min(1, (performance.now() - this._tween.t0) / this._tween.ms);
      const k = 1 - Math.pow(1 - t, 3);
      this.camera.position.lerpVectors(this._tween.p0, this._tween.p1, k);
      this.controls.target.lerpVectors(this._tween.c0, this._tween.c1, k);
      if (t >= 1) this._tween = null;
      this._dirty = true;
    }
    if (this.controls.update() || this._dirty) {
      this._dirty = false;
      this.renderer.render(this.scene, this.camera);
    }
  }

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = w + 'px';
    this.renderer.domElement.style.height = h + 'px';
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.requestRender();
  }

  _buildPlate(w, d) {
    this.plate.clear();
    const mat = new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.09 });
    const strong = new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.32 });
    const pts = [];
    for (let x = -w / 2; x <= w / 2 + 1e-6; x += 10) pts.push(x, -d / 2, 0, x, d / 2, 0);
    for (let y = -d / 2; y <= d / 2 + 1e-6; y += 10) pts.push(-w / 2, y, 0, w / 2, y, 0);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    this.plate.add(new THREE.LineSegments(g, mat));
    const o = new THREE.BufferGeometry();
    o.setAttribute('position', new THREE.Float32BufferAttribute(
      [-w / 2, -d / 2, 0, w / 2, -d / 2, 0, w / 2, -d / 2, 0, w / 2, d / 2, 0, w / 2, d / 2, 0, -w / 2, d / 2, 0, -w / 2, d / 2, 0, -w / 2, -d / 2, 0], 3));
    this.plate.add(new THREE.LineSegments(o, strong));
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(w * 3, d * 3), new THREE.ShadowMaterial({ opacity: 0.16 }));
    shadow.receiveShadow = true;
    shadow.position.z = -0.02;
    this.plate.add(shadow);
  }

  // ---- model -------------------------------------------------------------
  setModel(view) {
    this.model.clear();
    this.features.clear();
    const box = new THREE.Box3();
    for (const m of view.mesh) {
      const geo = geometryFrom(m);
      const mat = new THREE.MeshStandardMaterial({
        color: CLAY, roughness: 0.82, metalness: 0, side: THREE.DoubleSide,
        clippingPlanes: [this.clip], polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
      });
      mat.onBeforeCompile = s => {   // cut faces read as solid ink: back faces are the section
        s.fragmentShader = s.fragmentShader.replace('#include <dithering_fragment>',
          '#include <dithering_fragment>\n if (!gl_FrontFacing) gl_FragColor = vec4(0.16, 0.155, 0.15, 1.0);');
      };
      const mesh = new THREE.Mesh(geo, mat);
      mesh.castShadow = true;
      mesh.userData.feature = m.feature;
      this.model.add(mesh);
      this.features.set(m.feature, mesh);
      geo.computeBoundingBox();
      box.union(geo.boundingBox);
    }
    if (view.edges) {
      const eg = new THREE.BufferGeometry();
      eg.setAttribute('position', new THREE.BufferAttribute(decode(view.edges, Float32Array), 3));
      const lines = new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.5, clippingPlanes: [this.clip] }));
      this.model.add(lines);
    }
    // centre the design on the plate; every design-frame overlay shares the shift
    const cx = (box.min.x + box.max.x) / 2, cy = (box.min.y + box.max.y) / 2;
    this.shift = new THREE.Vector3(-cx, -cy, -box.min.z);
    for (const g of [this.model, this.ghost, this.aux]) g.position.copy(this.shift);
    this.bounds = box.clone().translate(this.shift);
    this.companions = view.companions || [];
    this._companions();
    this._paint();
    this.requestRender();
  }

  _companions() {
    if (this._comp) { this.aux.remove(this._comp); this._comp = null; }
    if (!this.showCompanions || !this.companions.length) return;
    const grp = new THREE.Group();
    for (const c of this.companions) {
      const [w, t, l] = c.size;
      const geo = new THREE.BoxGeometry(w, t, l);
      geo.translate(0, 0, l / 2);
      const holder = new THREE.Group();
      holder.position.set(...c.origin);
      holder.rotation.x = THREE.MathUtils.degToRad(c.rot_x_deg || 0);
      holder.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: GHOST, transparent: true, opacity: 0.07, depthWrite: false })));
      holder.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: GHOST, transparent: true, opacity: 0.6 })));
      grp.add(holder);
    }
    this._comp = grp;
    this.aux.add(grp);
  }

  setCompanions(on) { this.showCompanions = on; this._companions(); this.requestRender(); }

  setGhost(view) {
    this.ghost.clear();
    if (view && view.edges) {
      const eg = new THREE.BufferGeometry();
      eg.setAttribute('position', new THREE.BufferAttribute(decode(view.edges, Float32Array), 3));
      const l = new THREE.LineSegments(eg, new THREE.LineDashedMaterial({ color: GHOST, dashSize: 2.2, gapSize: 1.6, transparent: true, opacity: 0.85, depthTest: false }));
      l.computeLineDistances();
      l.renderOrder = 5;
      this.ghost.add(l);
    }
    this.requestRender();
  }

  _paint() {
    for (const [id, mesh] of this.features) {
      const sel = id === this.selected, hov = id === this.hovered, flag = this.flagged.has(id);
      const c = sel ? 0xf0755f : flag ? 0xecc9a0 : hov ? 0xe9e5dc : CLAY;
      mesh.material.color.setHex(c);
      mesh.material.emissive.setHex(sel ? 0x3a0d05 : 0x000000);
    }
    this.requestRender();
  }

  select(id) { this.selected = id; this._paint(); }
  flag(ids) { this.flagged = new Set(ids || []); this._paint(); }

  featureBox(id) {
    const m = this.features.get(id);
    if (!m) return null;
    m.geometry.computeBoundingBox();
    return m.geometry.boundingBox.clone().translate(this.shift);
  }

  _hit(e) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const p = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.ray.setFromCamera(p, this.camera);
    const hits = this.ray.intersectObjects([...this.features.values()], false);
    for (const h of hits) {
      if (this.section && this.clip.distanceToPoint(h.point) < 0) continue;
      return h.object.userData.feature;
    }
    return null;
  }

  // ---- camera ------------------------------------------------------------
  setView(name, animate = true, box = null) {
    const b = box || this.bounds;
    const c = b.getCenter(new THREE.Vector3());
    const size = b.getSize(new THREE.Vector3());
    const r = Math.max(size.length() / 2, 12);
    const dist = r / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2)) * (box ? 1.25 : 1.5);
    const dirs = { iso: [-0.62, -0.92, 0.6], front: [0, -1, 0.06], side: [1, 0, 0.06], back: [0.5, 1, 0.55], top: [0, -0.001, 1], under: [-0.5, -0.7, -0.75] };
    const d = new THREE.Vector3(...(dirs[name] || dirs.iso)).normalize();
    const pos = c.clone().addScaledVector(d, dist);
    if (!animate) {
      this.camera.position.copy(pos);
      this.controls.target.copy(c);
      this.controls.update();
      this.requestRender();
    } else {
      this._tween = { t0: performance.now(), ms: 420, p0: this.camera.position.clone(), p1: pos, c0: this.controls.target.clone(), c1: c };
    }
    this.viewName = name;
  }

  focusFeature(id) {
    const b = this.featureBox(id);
    if (!b) return;
    const d = this.camera.position.clone().sub(this.controls.target).normalize();
    const c = b.getCenter(new THREE.Vector3());
    const r = Math.max(b.getSize(new THREE.Vector3()).length() / 2, 14);
    const dist = r / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2)) * 1.9;
    this._tween = { t0: performance.now(), ms: 420, p0: this.camera.position.clone(), p1: c.clone().addScaledVector(d, dist), c0: this.controls.target.clone(), c1: c };
  }

  // ---- section -----------------------------------------------------------
  setSection(axis, t = 0.5) {
    this.section = axis;
    if (!axis) { this.clip.set(new THREE.Vector3(0, 0, -1), 1e6); this.requestRender(); return; }
    const b = this.bounds, i = { x: 0, y: 1, z: 2 }[axis];
    const lo = b.min.getComponent(i), hi = b.max.getComponent(i);
    const at = lo + (hi - lo) * t;
    const n = new THREE.Vector3();
    n.setComponent(i, axis === 'y' ? 1 : -1);          // y: remove the front, keep the back
    this.clip.set(n, axis === 'y' ? -at : at);
    this.sectionAt = at;
    this.requestRender();
  }

  // ---- markers -----------------------------------------------------------
  setMarker(seg) {
    if (this._marker) { this.aux.remove(this._marker); this._marker = null; }
    if (seg) {
      const g = new THREE.Group();
      const a = new THREE.Vector3(...seg.at), b = new THREE.Vector3(...seg.to);
      const lg = new THREE.BufferGeometry().setFromPoints([a, b]);
      const line = new THREE.Line(lg, new THREE.LineBasicMaterial({ color: SIGNAL, depthTest: false }));
      line.renderOrder = 10;
      g.add(line);
      for (const p of [a, b]) {
        const s = new THREE.Mesh(new THREE.SphereGeometry(0.9, 16, 12), new THREE.MeshBasicMaterial({ color: SIGNAL, depthTest: false }));
        s.position.copy(p);
        s.renderOrder = 10;
        g.add(s);
      }
      this._marker = g;
      this.aux.add(g);
      const box = new THREE.Box3().setFromPoints([a, b]).expandByScalar(18).translate(this.shift);
      this.setView(this.viewName || 'iso', true, box);
    }
    this.requestRender();
  }

  project(v3) {
    const p = new THREE.Vector3(...v3).add(this.shift).project(this.camera);
    const r = this.renderer.domElement.getBoundingClientRect();
    return [(p.x + 1) / 2 * r.width, (1 - p.y) / 2 * r.height];
  }

  snapshot() { this.renderer.render(this.scene, this.camera); return this.renderer.domElement.toDataURL('image/png'); }
}

// Small offscreen renderer for candidate thumbnails: same light, same clay.
let thumbRenderer = null;
export function thumbnail(mesh, size = 220, frame = null) {
  if (!thumbRenderer) {
    thumbRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    thumbRenderer.setPixelRatio(2);
    thumbRenderer.setSize(size, size * 0.72, false);
  }
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb9b2a4, 1.2));
  const key = new THREE.DirectionalLight(0xffffff, 1.9);
  key.position.set(-120, -180, 260);
  scene.add(key);
  const geo = geometryFrom(mesh);
  const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: CLAY, roughness: 0.82, flatShading: false, side: THREE.DoubleSide }));
  scene.add(m);
  scene.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 28), new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.45 })));
  geo.computeBoundingBox();
  const b = geo.boundingBox, c = b.getCenter(new THREE.Vector3()), r = frame || b.getSize(new THREE.Vector3()).length() / 2;
  const cam = new THREE.PerspectiveCamera(26, 1 / 0.72, 1, 5000);
  cam.up.set(0, 0, 1);
  cam.position.copy(c).addScaledVector(new THREE.Vector3(-0.62, -0.92, 0.6).normalize(), r / Math.sin(THREE.MathUtils.degToRad(13)) * 1.05);
  cam.lookAt(c);
  thumbRenderer.render(scene, cam);
  const url = thumbRenderer.domElement.toDataURL('image/png');
  geo.dispose();
  return url;
}
