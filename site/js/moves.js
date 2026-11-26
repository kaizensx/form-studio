// Parts that move: the hinged box from the CAD kernel (box.glb), placed by the engine's assembly data. The scroll
// swings the lid through the joint's declared range, then pulls the parts apart along their explode vectors.
import { siteData, loadGLB } from "./data.js";
import { scrub, span, easeInOut } from "./motion.js";

const $ = (s) => document.querySelector(s);

export async function initMoves() {
  const track = $("#moves-track"), canvas = $("#mv-c");
  if (!track || !canvas) return;
  const b = (await siteData()).box, hinge = b.joints[0];
  $("#mv-range").textContent = `${hinge.range[0]}–${hinge.range[1]}°`;
  $("#mv-samples").textContent = String(hinge.samples);

  const THREE = await import("three");
  const parts = await loadGLB("assets/data/box.glb");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setClearColor(0, 0); renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(28, 1, 5, 3000);
  scene.add(new THREE.HemisphereLight(0xf2f4f3, 0x3b4246, 1.55));
  const key = new THREE.DirectionalLight(0xffffff, 1.9); key.position.set(-180, 320, 260); scene.add(key);
  const fill = new THREE.DirectionalLight(0xdfe8ff, 0.5); fill.position.set(260, 120, -200); scene.add(fill);
  const world = new THREE.Group(); world.rotation.x = -Math.PI / 2; scene.add(world);

  const groups = {}, info = {};
  for (const p of b.parts) { groups[p.id] = new THREE.Group(); groups[p.id].matrixAutoUpdate = false; world.add(groups[p.id]); info[p.id] = p; }
  const tint = { body: 0xd8d3c8, lid: 0xcfcbc1 };
  for (const p of parts) {
    const part = p.extras.part, geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(p.pos, 3));
    let o;
    if (p.lines) o = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x080809, transparent: true, opacity: 0.5 }));
    else { geo.setIndex(new THREE.BufferAttribute(p.index, 1)); geo.computeVertexNormals(); o = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: tint[part] || 0xd8d3c8, roughness: 0.82, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 })); }
    groups[part].add(o);
  }
  const placeM = (pl) => new THREE.Matrix4().set(...pl.m[0], ...pl.m[1], ...pl.m[2], 0, 0, 0, 1);
  const o = new THREE.Vector3(...hinge.origin), ax = new THREE.Vector3(...hinge.axis).normalize();
  const bb = b.bbox, target = new THREE.Vector3((bb[0][0] + bb[1][0]) / 2, (bb[1][2] - bb[0][2]) * 0.45, -(bb[0][1] + bb[1][1]) / 2);
  const R = Math.hypot(bb[1][0] - bb[0][0], bb[1][1] - bb[0][1], bb[1][2] - bb[0][2]) * 2.75;

  const hud = document.querySelector(".mv-hud"), deg = $("#mv-deg"), read = $("#mv-angle"), segA = $("#mv-a"), segE = $("#mv-e");
  let last = 0;
  function render(p) {
    last = p;
    const angle = hinge.range[1] * easeInOut(span(p, 0.04, 0.5)), ex = easeInOut(span(p, 0.6, 0.92));
    for (const id of Object.keys(groups)) {
      let M = placeM(info[id].placement);
      if (id === hinge.part && angle) {
        const Rm = new THREE.Matrix4().makeTranslation(o.x, o.y, o.z).multiply(new THREE.Matrix4().makeRotationAxis(ax, angle * Math.PI / 180)).multiply(new THREE.Matrix4().makeTranslation(-o.x, -o.y, -o.z));
        M = Rm.multiply(M);
      }
      const e = new THREE.Vector3(...info[id].explode).multiplyScalar(ex);
      groups[id].matrix.copy(new THREE.Matrix4().makeTranslation(e.x, e.y, e.z).multiply(M));
      groups[id].matrixWorldNeedsUpdate = true;
    }
    const az = (-38 + 24 * p) * Math.PI / 180, el = (26 + 8 * ex) * Math.PI / 180, r = R * (1 + 0.1 * (angle / hinge.range[1]) + 0.3 * ex) / Math.max(0.8, Math.min(1.2, camera.aspect / 1.33));
    const t = target.clone().add(new THREE.Vector3(0, 14 * (angle / hinge.range[1]) + 18 * ex, 0));
    camera.position.set(t.x + r * Math.cos(el) * Math.sin(az), t.y + r * Math.sin(el), t.z + r * Math.cos(el) * Math.cos(az));
    camera.lookAt(t);
    renderer.render(scene, camera);
    const a = Math.round(angle);
    hud.style.setProperty("--f", (angle / hinge.range[1]).toFixed(4));
    deg.textContent = read.textContent = `${a}°`;
    segA.classList.toggle("on", ex < 0.5); segE.classList.toggle("on", ex >= 0.5);
  }
  const resize = () => { const w = canvas.clientWidth, h = canvas.clientHeight; if (!w) return; renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1)); renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); render(last); };
  new ResizeObserver(resize).observe(canvas); resize();
  scrub(track, render, { smooth: 8 });
}
