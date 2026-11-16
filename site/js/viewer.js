// The hero's 3D view: a real FORM build on the graphite plate, with the app's dimension lines.
// Z is up and units are millimetres, as in the kernel. Geometry comes from site/tools/export_parts.py.
import * as THREE from "three";
import { OrbitControls } from "../vendor/OrbitControls.js";

const C = {
  plate: 0x0e1113, grid: 0x1b2226, bed: 0x46525a, clay: 0xd8d3c8, edge: 0x1d2224,
  datum: 0xb9e8d7, blueprint: 0x86a8ff, draft: 0xb3bde4,
};
const OFF = 10;          // dimension lines sit one grid square off the part
const VIEW_DIR = new THREE.Vector3(0.74, -1, 0.66).normalize();

export function create({ canvas, labels, reduce, still }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.setClearColor(C.plate);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(C.plate, 400, 1100);
  const camera = new THREE.PerspectiveCamera(30, 1, 2, 5000);
  camera.up.set(0, 0, 1);

  // light: one key with a shadow, sky/ground fill. No environment map; the part is matte clay.
  const hemi = new THREE.HemisphereLight(0xe9f0f1, 0x1b2125, 1.0);
  hemi.position.set(0, 0, 1);
  const key = new THREE.DirectionalLight(0xffffff, 2.05);
  key.position.set(-150, -190, 300);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.6;
  key.shadow.radius = 5;
  Object.assign(key.shadow.camera, { left: -170, right: 170, top: 170, bottom: -170, near: 10, far: 900 });
  const fill = new THREE.DirectionalLight(0xc8d8ff, 0.45);
  fill.position.set(220, 60, 120);
  scene.add(hemi, key, fill);

  // the plate: a 10 mm grid, the 180 x 180 bed outline, a shadow catcher
  const g = [];
  for (let i = -60; i <= 60; i++) g.push(i * 10, -600, 0, i * 10, 600, 0, -600, i * 10, 0, 600, i * 10, 0);
  const grid = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(g, 3)),
    new THREE.LineBasicMaterial({ color: C.grid }));
  const b = 90;
  const bed = new THREE.LineLoop(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute([-b, -b, 0.05, b, -b, 0.05, b, b, 0.05, -b, b, 0.05], 3)),
    new THREE.LineBasicMaterial({ color: C.bed }));
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(1600, 1600), new THREE.ShadowMaterial({ opacity: 0.42 }));
  floor.position.z = -0.05;
  floor.receiveShadow = true;
  scene.add(floor, grid, bed);

  const clay = new THREE.MeshStandardMaterial({ color: C.clay, roughness: 0.86, metalness: 0, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
  const edgeMat = new THREE.LineBasicMaterial({ color: C.edge, transparent: true, opacity: 0.62 });
  const body = new THREE.Mesh(new THREE.BufferGeometry(), clay);
  body.castShadow = true;
  body.receiveShadow = true;
  const edges = new THREE.LineSegments(new THREE.BufferGeometry(), edgeMat);
  const part = new THREE.Group();
  part.add(body, edges);
  scene.add(part);

  // dimension lines: 3 dimensions x (line + 2 extension lines + 2 ticks) = 15 segments
  const dimPos = new Float32Array(15 * 6);
  const dimGeo = new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(dimPos, 3));
  const dimLines = new THREE.LineSegments(dimGeo, new THREE.LineBasicMaterial({ color: C.datum, transparent: true, opacity: 0.8, depthTest: false }));
  dimLines.renderOrder = 5;
  dimLines.frustumCulled = false;
  scene.add(dimLines);

  const mk = (cls) => { const s = document.createElement("span"); if (cls) s.className = cls; labels.append(s); return s; };
  const lab = { x: mk(), y: mk(), z: mk() };
  const anchors = { x: new THREE.Vector3(), y: new THREE.Vector3(), z: new THREE.Vector3() };

  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enablePan = false;
  controls.enableZoom = false;                       // the page keeps its scroll wheel
  controls.minPolarAngle = 0.2;
  controls.maxPolarAngle = Math.PI / 2 - 0.06;       // never under the plate
  controls.rotateSpeed = 0.7;
  controls.autoRotate = !reduce && !still;
  controls.autoRotateSpeed = 0.55;
  canvas.style.touchAction = "pan-y";                // vertical swipes scroll the page, horizontal drags orbit
  const stopAuto = () => { controls.autoRotate = false; };
  let resting = false;
  setTimeout(() => { resting = true; }, 4500);       // a short turn to show it is 3D, then it slows to rest
  canvas.addEventListener("pointerdown", stopAuto);
  canvas.addEventListener("keydown", (e) => {
    const d = { ArrowLeft: [-0.16, 0], ArrowRight: [0.16, 0], ArrowUp: [0, -0.1], ArrowDown: [0, 0.1] }[e.key];
    if (!d) return;
    e.preventDefault();
    stopAuto();
    const o = camera.position.clone().sub(controls.target), r = o.length();
    const az = Math.atan2(o.y, o.x) + d[0];
    const pol = Math.min(controls.maxPolarAngle, Math.max(controls.minPolarAngle, Math.acos(o.z / r) + d[1]));
    camera.position.set(Math.sin(pol) * Math.cos(az), Math.sin(pol) * Math.sin(az), Math.cos(pol)).multiplyScalar(r).add(controls.target);
    dirty = true;
  });

  // ---- state
  let cur = null;            // { part, buf, geo: [] }
  let dirty = true, visible = true, raf = 0;
  const ext = { x: 40, y: 40, z: 30 }, extTo = { x: 40, y: 40, z: 30 };   // shown and target size, mm
  let draft = 0, draftTo = 0;
  let dist = 400, distK = 1;
  const clayC = new THREE.Color(C.clay), draftC = new THREE.Color(C.draft), edgeC = new THREE.Color(C.edge), blueC = new THREE.Color(C.blueprint);

  function geometry(i) {
    if (cur.geo[i]) return cur.geo[i];
    const { part: p, buf } = cur, st = p.steps[i];
    const span = p.hi.map((h, k) => h - p.lo[k]);
    const dq = (off, n) => {
      const q = new Uint16Array(buf, off, n), out = new Float32Array(n);
      for (let j = 0; j < n; j++) out[j] = p.lo[j % 3] + (q[j] / 65535) * span[j % 3];
      return out;
    };
    const mesh = new THREE.BufferGeometry();
    mesh.setAttribute("position", new THREE.BufferAttribute(dq(st.v[0], st.v[1] * 3), 3));
    const idx = st.i[2] === 4 ? new Uint32Array(buf.slice(st.i[0], st.i[0] + st.i[1] * 4)) : new Uint16Array(buf, st.i[0], st.i[1]);
    mesh.setIndex(new THREE.BufferAttribute(idx, 1));
    mesh.computeVertexNormals();
    const line = new THREE.BufferGeometry();
    line.setAttribute("position", new THREE.BufferAttribute(dq(st.e[0], st.e[1] * 6), 3));
    return (cur.geo[i] = { mesh, line });
  }

  function frame() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * renderer.getPixelRatio()) || canvas.height !== Math.round(h * renderer.getPixelRatio())) renderer.setSize(w, h, false);
    camera.aspect = w / h;
    const wide = w > 1000;
    // on a wide screen the headline owns the left third, so the picture is shifted right and a little up
    if (wide) camera.setViewOffset(w, h, -w * 0.2, h * 0.012, w, h); else camera.setViewOffset(w, h, 0, -h * 0.02, w, h);
    camera.updateProjectionMatrix();
    dirty = true;
  }

  function fit(p) {
    const s = p.hi.map((h, k) => h - p.lo[k]);
    const r = 0.5 * Math.hypot(s[0], s[1], s[2]);
    const a = canvas.clientWidth / Math.max(1, canvas.clientHeight);
    const vf = THREE.MathUtils.degToRad(camera.fov) / 2;
    const hf = Math.atan(Math.tan(vf) * a);
    const k = canvas.clientWidth > 1000 ? 0.92 : 1.2;            // the bounding sphere is a loose fit; this tightens it
    dist = (r + OFF * 2) / Math.sin(Math.min(vf, hf)) / k;
    scene.fog.near = dist * 1.05;
    scene.fog.far = dist * 2.9;
    controls.minDistance = controls.maxDistance = dist;
  }

  function writeDims() {
    const hx = ext.x / 2, hy = ext.y / 2, z = ext.z, t = 2.2, k = 0.3;
    const yy = -hy - OFF, xx = hx + OFF, zx = -hx - OFF;
    const seg = [
      // width, along X, in front of the part
      -hx, yy, k, hx, yy, k, -hx, -hy - 2, k, -hx, yy - 3, k, hx, -hy - 2, k, hx, yy - 3, k,
      -hx - t, yy - t, k, -hx + t, yy + t, k, hx - t, yy - t, k, hx + t, yy + t, k,
      // depth, along Y, to the right
      xx, -hy, k, xx, hy, k, hx + 2, -hy, k, xx + 3, -hy, k, hx + 2, hy, k, xx + 3, hy, k,
      xx - t, -hy - t, k, xx + t, -hy + t, k, xx - t, hy - t, k, xx + t, hy + t, k,
      // height, along Z, at the front left corner
      zx, -hy, 0, zx, -hy, z, -hx - 2, -hy, 0, zx - 3, -hy, 0, -hx - 2, -hy, z, zx - 3, -hy, z,
      zx - t, -hy, -t, zx + t, -hy, t, zx - t, -hy, z - t, zx + t, -hy, z + t,
    ];
    dimPos.set(seg);
    dimGeo.attributes.position.needsUpdate = true;
    anchors.x.set(0, yy, k); anchors.y.set(xx, 0, k); anchors.z.set(zx, -hy, z / 2);
    lab.x.textContent = ext.x.toFixed(1); lab.y.textContent = ext.y.toFixed(1); lab.z.textContent = ext.z.toFixed(1);
  }

  const v = new THREE.Vector3();
  function placeLabels() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    for (const key of Object.keys(lab)) {
      v.copy(anchors[key]).project(camera);
      const x = (v.x * 0.5 + 0.5) * w, y = (-v.y * 0.5 + 0.5) * h;
      lab[key].style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -50%)`;
      lab[key].style.visibility = v.z < 1 ? "visible" : "hidden";
    }
  }

  let last = performance.now();
  function loop(now) {
    raf = requestAnimationFrame(loop);
    if (!visible || !cur) return;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const ease = reduce ? 1 : 1 - Math.exp(-dt * 16);     // exponential ease-out, about 180 ms to settle
    let moving = false;
    for (const key of ["x", "y", "z"]) {
      const d = extTo[key] - ext[key];
      if (Math.abs(d) > 0.02) { ext[key] += d * ease; moving = true; } else ext[key] = extTo[key];
    }
    if (Math.abs(draftTo - draft) > 0.004) { draft += (draftTo - draft) * (reduce ? 1 : 1 - Math.exp(-dt * (draftTo ? 26 : 7))); moving = true; } else draft = draftTo;
    if (distK > 1.0005) { distK = 1 + (distK - 1) * Math.exp(-dt * 4.5); controls.minDistance = controls.maxDistance = dist * distK; moving = true; }
    if (moving) {
      writeDims();
      clay.color.copy(clayC).lerp(draftC, draft);
      edgeMat.color.copy(edgeC).lerp(blueC, draft);
      dirty = true;
    }
    if (resting && controls.autoRotate) { controls.autoRotateSpeed *= Math.exp(-dt * 2.5); if (controls.autoRotateSpeed < 0.02) controls.autoRotate = false; }
    if (controls.update() || dirty) {
      renderer.render(scene, camera);
      placeLabels();
      dirty = false;
    }
  }

  const ro = new ResizeObserver(() => { frame(); if (cur) fit(cur.part); });
  ro.observe(canvas);
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; last = performance.now(); });
  io.observe(canvas);

  return {
    setPart(p, buf, i) {
      if (cur) cur.geo.forEach((gm) => { if (gm) { gm.mesh.dispose(); gm.line.dispose(); } });
      const first = !cur;
      cur = { part: p, buf, geo: [] };
      frame(); fit(p);
      if (first) {
        controls.target.set(0, 0, (p.hi[2] - p.lo[2]) * 0.42);
        camera.position.copy(VIEW_DIR).multiplyScalar(dist).add(controls.target);
        if (!reduce && !still) distK = 1.14;                // one short glide in, then it rests
        raf = requestAnimationFrame(loop);
      } else {
        controls.target.z = (p.hi[2] - p.lo[2]) * 0.42;
      }
      this.setStep(i, false, true);
    },
    setStep(i, isDraft, jump) {
      if (!cur) return;
      const gm = geometry(i), st = cur.part.steps[i], bb = st.bbox;
      body.geometry = gm.mesh;
      edges.geometry = gm.line;
      part.position.set(-(bb[0][0] + bb[1][0]) / 2, -(bb[0][1] + bb[1][1]) / 2, -bb[0][2]);
      extTo.x = st.size[0]; extTo.y = st.size[1]; extTo.z = st.size[2];
      if (jump) { Object.assign(ext, extTo); writeDims(); }
      draftTo = isDraft ? 1 : 0;
      dirty = true;
    },
    settle() { draftTo = 0; dirty = true; },
    renderNow() { controls.update(); renderer.render(scene, camera); placeLabels(); },
    dispose() { cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); controls.dispose(); renderer.dispose(); },
  };
}
