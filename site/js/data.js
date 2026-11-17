// Real data exported from Form Studio's engine by site/tools/export_site_data.py. Loaded once, shared.

let site, tp;
export const siteData = () => (site ||= fetch("assets/data/site.json").then((r) => r.json()));

// glTF 2.0 binary with KHR_mesh_quantization, as written by the exporter: int16 normalised positions,
// dequantised with each node's translation and scale. Returns plain arrays; no loader library needed.
export async function loadGLB(url) {
  const buf = await (await fetch(url)).arrayBuffer();
  const dv = new DataView(buf);
  if (dv.getUint32(0, true) !== 0x46546c67) throw new Error("not a glb: " + url);
  const jl = dv.getUint32(12, true);
  const doc = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jl)));
  const binStart = 20 + jl + 8;
  const view = (i) => doc.bufferViews[i];
  const out = [];
  for (const node of doc.nodes) {
    const prim = doc.meshes[node.mesh].primitives[0];
    const pa = doc.accessors[prim.attributes.POSITION], pv = view(pa.bufferView);
    const stride = (pv.byteStride || 6) / 2;
    const src = new Int16Array(buf, binStart + (pv.byteOffset || 0), (pv.byteLength) / 2);
    const [tx, ty, tz] = node.translation, [sx, sy, sz] = node.scale;
    const pos = new Float32Array(pa.count * 3);
    for (let i = 0; i < pa.count; i++) {
      pos[i * 3] = tx + (src[i * stride] / 32767) * sx;
      pos[i * 3 + 1] = ty + (src[i * stride + 1] / 32767) * sy;
      pos[i * 3 + 2] = tz + (src[i * stride + 2] / 32767) * sz;
    }
    let index = null;
    if (prim.indices !== undefined) {
      const ia = doc.accessors[prim.indices], iv = view(ia.bufferView);
      const C = ia.componentType === 5125 ? Uint32Array : Uint16Array;
      index = new C(buf.slice(binStart + (iv.byteOffset || 0), binStart + (iv.byteOffset || 0) + iv.byteLength));
    }
    out.push({ name: node.name, extras: node.extras || {}, pos, index, lines: prim.mode === 1 });
  }
  return out;
}

// The sliced toolpath, simplified by the exporter: per layer, runs of one line type as polylines (uint16, 0.01 mm).
// Decoded into flat segments with, for each, its layer and its progress through the layer (by path length),
// the same way the app times its print simulation.
export const toolpath = () => (tp ||= Promise.all([siteData(), fetch("assets/data/toolpath.bin").then((r) => r.arrayBuffer())]).then(([d, buf]) => {
  const m = d.dock.toolpath, L = m.layout;
  const pts = new Uint16Array(buf, L.points[0], L.points[1]);
  const rc = new Uint16Array(buf, L.run_count[0], L.run_count[1]);
  const rt = new Uint8Array(buf, L.run_type[0], L.run_type[1]);
  const lr = new Uint32Array(buf, L.layer_runs[0], L.layer_runs[1]);
  const res = m.res_mm, [ox, oy] = m.origin;
  let nseg = 0;
  for (let r = 0; r < rc.length; r++) nseg += rc[r] - 1;
  const seg = new Float32Array(nseg * 4), type = new Uint8Array(nseg), layer = new Uint16Array(nseg);
  const p0 = new Float32Array(nseg), p1 = new Float32Array(nseg);
  const layerStart = new Uint32Array(m.z.length + 1);
  let k = 0, pi = 0;
  for (let l = 0; l < m.z.length; l++) {
    layerStart[l] = k;
    const k0 = k;
    let cum = 0;
    for (let r = lr[l]; r < lr[l + 1]; r++) {
      for (let j = 0; j < rc[r]; j++, pi++) {
        if (j === 0) continue;
        const x0 = ox + pts[(pi - 1) * 2] * res, y0 = oy + pts[(pi - 1) * 2 + 1] * res;
        const x1 = ox + pts[pi * 2] * res, y1 = oy + pts[pi * 2 + 1] * res;
        seg.set([x0, y0, x1, y1], k * 4);
        type[k] = rt[r]; layer[k] = l;
        p0[k] = cum; cum += Math.hypot(x1 - x0, y1 - y0); p1[k] = cum;
        k++;
      }
    }
    for (let i = k0; i < k; i++) { p0[i] = l + p0[i] / (cum || 1); p1[i] = l + p1[i] / (cum || 1); }
  }
  layerStart[m.z.length] = k;
  return { meta: m, seg, type, layer, p0, p1, layerStart, count: k };
}));

export const fmtDur = (s) => {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), mn = Math.floor((s % 3600) / 60), sc = s % 60;
  return h ? `${h}:${String(mn).padStart(2, "0")}:${String(sc).padStart(2, "0")}` : `${mn}:${String(sc).padStart(2, "0")}`;
};

// line-type inks, exactly as LayerView.qml
export const INKS = {
  "Outer wall": "#e8edeb", "Inner wall": "#717b78", "Sparse infill": "#e9b860", "Internal solid infill": "#86a8ff",
  "Top surface": "#b9e8d7", "Bottom surface": "#6c887e", "Bridge": "#ff6f51", "Overhang wall": "#ff6f51",
  "Floating vertical shell": "#ff8a65", "Gap infill": "#49524f",
};

export const reducedMotion = () => document.documentElement.classList.contains("reduce") || matchMedia("(prefers-reduced-motion: reduce)").matches;
