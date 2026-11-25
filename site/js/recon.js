// Mesh to CAD as one picture with a line through it: the input mesh (its triangles) on the left of the line, the
// engine's reconstruction (its faces and B-rep edges) on the right. The readouts count what each side shows:
// triangles left of the line, dimensions whose feature lies right of it, and the largest measured distance from the
// mesh among the CAD surface right of it. Every number comes from site/assets/data/recon.json (site/tools/export_site_data.py).
import * as THREE from "three";
import { loadGLB, reducedMotion } from "./data.js";

const $ = (s) => document.querySelector(s);
const BG = 0x101417, CLAY = 0xd8d3c8, WIRE = 0xb4beba, SLATE = 0x4a5250;
const fmt = (n) => n.toLocaleString("en-US");
const easeMove = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const upper = (a, x) => { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] <= x) lo = m + 1; else hi = m; } return lo; };

function lights(scene) {
  scene.add(new THREE.HemisphereLight(0xf2f4f3, 0x30363a, 1.5));
  const key = new THREE.DirectionalLight(0xffffff, 1.8); key.position.set(-120, -160, 260); scene.add(key);
  const fill = new THREE.DirectionalLight(0xdfe8ff, 0.5); fill.position.set(200, 80, 60); scene.add(fill);
}

function geometry(node) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(node.pos, 3));
  if (node.index) g.setIndex(new THREE.BufferAttribute(node.index, 1));
  return g;
}

// without WebGL: the engine's two pictures of the same part, with the same line
function fallback(frame, range) {
  frame.querySelector("canvas").remove();
  frame.classList.add("ba-frame", "ready");
  frame.insertAdjacentHTML("afterbegin",
    '<img src="assets/shots/recon-cad.webp" width="1100" height="693" alt="The bracket as CAD: clean faces, a pocket, a counterbored hole and fillets.">' +
    '<div class="ba-top"><img src="assets/shots/recon-mesh.webp" width="1100" height="693" alt="The bracket as a triangle mesh."></div>');
  const set = () => frame.style.setProperty("--p", `${range.value / 10}%`);
  range.addEventListener("input", set); set();
}

export async function initRecon() {
  const frame = $("#wipe-frame"), canvas = $("#wipe-c"), range = $("#wipe-r");
  if (!frame || !canvas) return;
  const out = { tri: $("#rc-tri"), dim: $("#rc-dim"), dev: $("#rc-dev") };
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true }); } catch { fallback(frame, range); return; }
  renderer.setClearColor(BG, 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const [nodes, info] = await Promise.all([loadGLB("assets/data/recon.glb"), fetch("assets/data/recon.json").then((r) => r.json())]);
  const node = (n) => nodes.find((x) => x.name === n);
  const nDims = info.dims.length;
  if (matchMedia("(hover: none)").matches) $(".wipe-hint").textContent = "Drag across it";
  $("#rc-ntri").textContent = fmt(info.triangles); $("#rc-nfaces").textContent = fmt(info.faces); $("#rc-ndims").textContent = fmt(nDims);

  // left of the line: the mesh, every triangle drawn
  const meshScene = new THREE.Scene(); lights(meshScene);
  const mg = geometry(node("mesh"));
  meshScene.add(new THREE.Mesh(mg, new THREE.MeshStandardMaterial({ color: SLATE, roughness: 0.9, flatShading: true, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 })));
  meshScene.add(new THREE.LineSegments(new THREE.WireframeGeometry(mg), new THREE.LineBasicMaterial({ color: WIRE, transparent: true, opacity: 0.78 })));
  // right of it: the CAD, its faces in clay and its B-rep edges, as the app draws a design
  const cadScene = new THREE.Scene(); lights(cadScene);
  const cg = geometry(node("cad")); cg.computeVertexNormals();
  cadScene.add(new THREE.Mesh(cg, new THREE.MeshStandardMaterial({ color: CLAY, roughness: 0.82, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 })));
  cadScene.add(new THREE.LineSegments(geometry(node("cad_edges")), new THREE.LineBasicMaterial({ color: 0x0b0d0e, transparent: true, opacity: 0.6 })));

  // the camera looks from the front left and above, CAD Z up, and fits the part's box to the frame
  mg.computeBoundingBox();
  const box = mg.boundingBox, centre = box.getCenter(new THREE.Vector3());
  const camera = new THREE.PerspectiveCamera(26, 1, 1, 2000); camera.up.set(0, 0, 1);
  const dir = new THREE.Vector3(-0.78, -1.1, 0.95).normalize();
  const fit = () => {
    const fwd = dir.clone().negate(), right = new THREE.Vector3().crossVectors(fwd, camera.up).normalize(), up = new THREE.Vector3().crossVectors(right, fwd);
    let hx = 0, hy = 0, near = 0;
    for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
      const c = new THREE.Vector3(x, y, z).sub(centre);
      hx = Math.max(hx, Math.abs(c.dot(right))); hy = Math.max(hy, Math.abs(c.dot(up))); near = Math.max(near, c.dot(dir));
    }
    const fill = camera.aspect < 1.2 ? 0.86 : 0.84, tv = Math.tan((camera.fov * Math.PI) / 360);
    camera.position.copy(centre).addScaledVector(dir, near + Math.max(hx / (fill * tv * camera.aspect), hy / (fill * tv)));
    camera.lookAt(centre); camera.updateMatrixWorld();
  };

  // where things fall on screen, sorted by x: triangle centres (mesh), CAD vertices with their deviation, dimensions
  const P = node("mesh").pos, I = node("mesh").index, C = node("cad").pos, dev = info.deviation_nm;
  let triX, cadX, devSuffix, dimX, W = 1, H = 1;
  const v = new THREE.Vector3(), sx = (x, y, z) => (v.set(x, y, z).project(camera).x * 0.5 + 0.5) * W;
  const project = () => {
    triX = new Float32Array(I.length / 3);
    for (let t = 0; t < triX.length; t++) {
      const a = I[t * 3] * 3, b = I[t * 3 + 1] * 3, c = I[t * 3 + 2] * 3;
      triX[t] = sx((P[a] + P[b] + P[c]) / 3, (P[a + 1] + P[b + 1] + P[c + 1]) / 3, (P[a + 2] + P[b + 2] + P[c + 2]) / 3);
    }
    triX.sort();
    const n = C.length / 3, order = new Uint32Array(n).map((_, i) => i), xs = new Float32Array(n);
    for (let i = 0; i < n; i++) xs[i] = sx(C[i * 3], C[i * 3 + 1], C[i * 3 + 2]);
    order.sort((a, b) => xs[a] - xs[b]);
    cadX = Float32Array.from(order, (i) => xs[i]);
    devSuffix = new Float32Array(n + 1).fill(-1);
    for (let k = n - 1; k >= 0; k--) devSuffix[k] = Math.max(devSuffix[k + 1], dev[order[k]]);
    dimX = Float32Array.from(info.dims.map((d) => sx(...d.at))).sort();
  };

  let p = 0.5, ready = false;
  const read = () => {
    const X = p * W;
    const tri = upper(triX, X), dims = nDims - upper(dimX, X), d = devSuffix[upper(cadX, X)];
    out.tri.textContent = fmt(tri);
    out.dim.textContent = `${dims} of ${nDims}`;
    out.dev.textContent = d < 0 ? "–" : `${(d / 1e6).toFixed(4)} mm`;
    range.setAttribute("aria-valuetext", `${fmt(tri)} triangles of mesh, ${dims} of ${nDims} dimensions of CAD`);
  };
  const draw = () => {
    const X = Math.round(p * W);
    renderer.setScissorTest(true);
    renderer.setScissor(0, 0, X, H); renderer.render(meshScene, camera);
    renderer.setScissor(X, 0, W - X, H); renderer.render(cadScene, camera);
    renderer.setScissorTest(false);
  };
  let raf = 0;
  const set = (q) => {
    p = Math.min(1, Math.max(0, q));
    frame.style.setProperty("--p", `${(p * 100).toFixed(2)}%`);
    range.value = String(Math.round(p * 1000));
    if (!ready) return;
    read();
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); });
  };
  const resize = () => {
    W = frame.clientWidth; H = frame.clientHeight;
    if (!W || !H) return;
    renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
    renderer.setSize(W, H, false);
    camera.aspect = W / H; camera.updateProjectionMatrix(); fit(); project();
    set(p);
  };
  new ResizeObserver(resize).observe(frame);
  ready = true; resize();
  frame.classList.add("ready");

  // the line follows the pointer; the range input under it carries the keyboard and touch
  let touched = false, intro = 0;
  const own = () => { touched = true; cancelAnimationFrame(intro); };
  frame.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse") return;
    own();
    const r = frame.getBoundingClientRect();
    set((e.clientX - r.left) / r.width);
  });
  range.addEventListener("input", () => { own(); set(range.value / 1000); });

  // first sight: the line crosses from the mesh side to the middle, once
  if (reducedMotion()) { set(0.5); return; }
  set(0.97);
  const io = new IntersectionObserver(([e]) => {
    if (!e.isIntersecting) return; io.disconnect();
    if (touched) return;
    const t0 = performance.now(), from = p, to = 0.5, ms = 1600;
    const step = (now) => {
      if (touched) return;
      const k = Math.min(1, (now - t0) / ms);
      set(from + (to - from) * easeMove(k));
      if (k < 1) intro = requestAnimationFrame(step);
    };
    intro = requestAnimationFrame(step);
  }, { threshold: 0.55 });
  io.observe(frame);
}
