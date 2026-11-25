"""Export the real Form Studio data the website draws: models, checks, the slice, the toolpath and the assembly.

Nothing in the drawn app is invented. Every number, shape and line it shows comes from this script, which makes the
sample project with Form Studio's own engine (the same Studio the app and the CLI use) and asks it for the result.

Run from the repository root, with a scratch data folder and a slicer Form Studio can drive:

    FORM_DATA=.dev/web/data FORM_CONFIG=/nonexistent PYTHONPATH=. .venv/bin/python site/tools/export_site_data.py

The sample is the planetary gearbox exemplar (form/exemplars/planetary_gearbox.py): an original design written as
build123d code, created for printing, with one committed change, then built, checked and sliced. When the data folder
has no such project the script makes it; a design that is not sliced gets no slice and no toolpath in the output, and
the page then draws neither.

Writes into site/assets/data/:
    sample.glb     the sample at its head revision, one mesh per feature plus the kernel's B-rep edges
    ../shots/card-sample.webp   the sample's design card on Home
    box.glb        the hinged box: its two parts, per feature, in the print frame (kept when the folder has no box)
    toolpath.bin   the sample's sliced toolpath, simplified for the browser (layout in site.json -> toolpath)
    site.json      project state, checks, slice summary, revisions, wall-thickness map, assembly
    recon.glb      mesh to CAD: the input mesh, the reconstructed CAD (faces and B-rep edges) of tests/recon_fixtures.py
                   stepped_bracket, the fixture scripts/media/showcase/recon_shots.py pictures
    recon.json     the reconstruction's report: triangles, faces, dimensions and where they sit, deviation per CAD vertex

Only the mesh-to-CAD part, which needs no slicer and no data folder:

    PYTHONPATH=. .venv/bin/python site/tools/export_site_data.py recon

The .glb files are glTF 2.0 with KHR_mesh_quantization: int16 positions, dequantised by the node's scale and
translation. Feature names are the mesh names; extras carry the feature labels.
"""
from __future__ import annotations

import base64
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

from form import config, toolpath
from form.studio import Studio

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "site" / "assets" / "data"
SHOTS = ROOT / "site" / "assets" / "shots"
SAMPLE = "planetary-gearbox"
SAMPLE_EXEMPLAR = "planetary_gearbox"
SAMPLE_NAME = "Planetary gearbox"
SAMPLE_BRIEF = ("A planetary gearbox I can print in one go: a sun, three planets and a ring housing with bolt lugs, "
                "about 1 : 5, with a carrier that pins into the planets.")
# the one change after the first build, committed the way an agent commits it
SAMPLE_CHANGE = ({"backlash": 0.2}, "More backlash, so printed teeth turn freely")
BOX = "hinged-box"
RECON = "stepped_bracket"                      # tests/recon_fixtures.py: a synthetic part, never a file of anyone's
RECON_WORK = Path(os.environ.get("RECON_WORK") or ROOT / ".dev" / "web" / "recon")


def f32(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype=np.float32)


def u32(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype=np.uint32)


# ---- glTF writer (positions int16 normalised, indices uint16/uint32, lines for edges) -----------------------
class GLB:
    def __init__(self):
        self.bin = bytearray()
        self.views, self.accessors, self.meshes, self.nodes = [], [], [], []

    def _view(self, data: bytes, target: int | None) -> int:
        while len(self.bin) % 4:
            self.bin += b"\0"
        v = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            v["target"] = target
        self.bin += data
        self.views.append(v)
        return len(self.views) - 1

    def _acc(self, view: int, ctype: int, count: int, typ: str, normalized=False, mn=None, mx=None) -> int:
        a = {"bufferView": view, "componentType": ctype, "count": count, "type": typ}
        if normalized:
            a["normalized"] = True
        if mn is not None:
            a["min"], a["max"] = mn, mx
        self.accessors.append(a)
        return len(self.accessors) - 1

    def add(self, name: str, P: np.ndarray, T: np.ndarray | None, lo, span, extras: dict, lines=False) -> None:
        """P in millimetres. Quantised to int16 over [lo, lo + span]; the node scales it back."""
        q = np.round((P - lo) / span * 65534 - 32767).clip(-32767, 32767).astype("<i2")
        pad = np.zeros((len(q), 1), "<i2")                      # int16 VEC3 needs 4-byte aligned elements
        data = np.hstack([q, pad]).tobytes()
        v = self._view(data, 34962)
        self.views[v]["byteStride"] = 8
        mn, mx = q.min(axis=0).tolist(), q.max(axis=0).tolist()
        pos = self._acc(v, 5122, len(q), "VEC3", True, [x / 32767 for x in mn], [x / 32767 for x in mx])
        prim = {"attributes": {"POSITION": pos}, "mode": 1 if lines else 4}
        if T is not None:
            wide = len(P) > 65535
            iv = self._view(T.astype("<u4" if wide else "<u2").tobytes(), 34963)
            prim["indices"] = self._acc(iv, 5125 if wide else 5123, int(T.size), "SCALAR")
        self.meshes.append({"name": name, "primitives": [prim]})
        half = (np.asarray(span) / 2).tolist()
        centre = (np.asarray(lo) + np.asarray(span) / 2).tolist()
        self.nodes.append({"name": name, "mesh": len(self.meshes) - 1, "translation": centre, "scale": half, "extras": extras})

    def write(self, path: Path, extras: dict) -> int:
        doc = {"asset": {"version": "2.0", "generator": "FORM site/tools/export_site_data.py"},
               "extensionsUsed": ["KHR_mesh_quantization"], "extensionsRequired": ["KHR_mesh_quantization"],
               "scene": 0, "scenes": [{"nodes": list(range(len(self.nodes))), "extras": extras}],
               "nodes": self.nodes, "meshes": self.meshes, "accessors": self.accessors, "bufferViews": self.views,
               "buffers": [{"byteLength": len(self.bin)}]}
        js = json.dumps(doc, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        bn = bytes(self.bin) + b"\0" * (-len(self.bin) % 4)
        out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bn))
        out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bn), 0x004E4942) + bn
        path.write_bytes(out)
        return len(out)


def feature_meshes(view: dict) -> dict:
    groups: dict = {}
    for m in view["mesh"]:
        key = (m["feature"], m.get("part") or "")
        P = f32(m["positions"]).reshape(-1, 3)
        T = u32(m["indices"]).reshape(-1, 3)
        g = groups.setdefault(key, [[], [], 0])
        g[0].append(P)
        g[1].append(T + g[2])
        g[2] += len(P)
    return {k: (np.concatenate(v[0]), np.concatenate(v[1])) for k, v in groups.items()}


def weld(P: np.ndarray, T: np.ndarray, tol=1e-4):
    """Merge duplicate vertices so the browser can compute smooth normals within a face (positions only)."""
    key = np.round(P / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return P[first], inv.reshape(-1)[T]


# ---- the toolpath, simplified --------------------------------------------------------------------------------
def dp(pts: np.ndarray, eps: float) -> np.ndarray:
    """Douglas-Peucker on a polyline; keeps the ends."""
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        p, q = pts[a], pts[b]
        d = q - p
        L = np.hypot(*d)
        seg = pts[a + 1:b]
        dist = np.abs(d[0] * (seg[:, 1] - p[1]) - d[1] * (seg[:, 0] - p[0])) / L if L > 1e-9 else np.hypot(*(seg - p).T)
        i = int(np.argmax(dist))
        if dist[i] > eps:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return pts[keep]


def export_toolpath(tp, eps=0.04, res=0.01):
    x0, y0 = tp.bbox[0][0], tp.bbox[0][1]
    layer_runs, rtype, rcount, pts = [0], [], [], []
    for l in range(tp.layers):
        a, b = int(tp.start[l]), int(tp.start[l + 1])
        seg, typ = tp.seg[a:b], tp.seg_type[a:b]
        i = 0
        while i < len(seg):
            j = i + 1
            while j < len(seg) and typ[j] == typ[i] and abs(seg[j, 0] - seg[j - 1, 2]) < 1e-3 and abs(seg[j, 1] - seg[j - 1, 3]) < 1e-3:
                j += 1
            poly = np.vstack([seg[i:j, :2], seg[j - 1, 2:4][None]])
            poly = dp(poly.astype(np.float64), eps)
            q = np.round((poly - [x0, y0]) / res).astype("<u2")
            rtype.append(int(typ[i]))
            rcount.append(len(q))
            pts.append(q)
            i = j
        layer_runs.append(len(rtype))
    P = np.concatenate(pts)
    blob = bytearray()
    lay = {}
    def put(name, arr):
        while len(blob) % 4:
            blob.extend(b"\0")
        lay[name] = [len(blob), int(arr.size)]
        blob.extend(arr.tobytes())
    put("points", P.reshape(-1))
    put("run_count", np.asarray(rcount, "<u2"))
    put("run_type", np.asarray(rtype, "u1"))
    put("layer_runs", np.asarray(layer_runs, "<u4"))
    summ = tp.summary()
    meta = {"layout": lay, "origin": [x0, y0], "res_mm": res, "simplified_mm": eps, "runs": len(rtype), "points": int(len(P)),
            "segments_in_gcode": int(len(tp.seg)), "types": tp.types, "z": summ["z"], "height": summ["height"],
            "length_mm": summ["length_mm"], "time_s": summ["time_s"], "t0_s": summ["t0_s"], "total_time_s": summ["total_time_s"],
            "time_source": summ["time_source"], "time_note": summ["time_note"], "bridge_layers": summ["bridge_layers"],
            "overhang_layers": summ["overhang_layers"], "type_length_mm": summ["type_length_mm"], "width_mm": tp.width,
            "bbox": tp.bbox, "note": summ["note"]}
    return bytes(blob), meta


def cli(*args) -> dict:
    r = subprocess.run([sys.executable, "-m", "form", *args], capture_output=True, text=True, env=dict(os.environ), cwd=ROOT)
    return {"cmd": "form " + " ".join(args), "out": r.stdout.strip()}


def ensure_sample(s: Studio) -> dict:
    """The sample project, made here when the data folder does not have it: the design, one change, the pipeline."""
    from form import exemplars
    from form.studio import StudioError
    try:
        p = s.load(SAMPLE)
    except StudioError:
        p = s.create_design(SAMPLE_NAME, exemplars.get(SAMPLE_EXEMPLAR)["source"], SAMPLE_BRIEF, purpose="print")
        if p["id"] != SAMPLE:
            raise SystemExit(f"the sample was created as {p['id']}, expected {SAMPLE}")
        s.run_sync(p["id"])
        values, note = SAMPLE_CHANGE
        p = s.commit(s.load(p["id"]), values, note=note, origin="proposal:agent")
    j = s.run_sync(p["id"])
    if j["state"] != "done":
        bad = next((x for x in j["steps"] if x.get("error")), {})
        print("pipeline:", j["state"], (bad.get("error") or {}).get("message", ""))
    return s.load(p["id"])


def export_recon() -> None:
    """Mesh to CAD on the synthetic stepped bracket: the engine's own reconstruction, as the page's wipe draws it.

    The mesh is the fixture's STL as the engine loads it. The CAD is the reconstruction's tessellation from its deviation
    map (so each vertex carries its measured distance from the mesh) and the STEP's B-rep edges. Each dimension is placed
    at the centre of the feature it drives: the solid that feature adds or removes in the reconstructed recipe."""
    import importlib.util
    sys.path.insert(0, str(ROOT / "tests"))
    import recon_fixtures as fx
    from build123d import import_step
    from form import kernel
    from form.recon import pipeline
    d = RECON_WORK / RECON
    d.mkdir(parents=True, exist_ok=True)
    stl, _solid, _facts = fx.export(RECON, d)
    rep_f = d / f"{RECON}_report.json"
    if not rep_f.exists():
        pipeline.reconstruct(stl, d, name=RECON, tolerance=0.02)
    rep = json.loads(rep_f.read_text(encoding="utf-8"))
    res = rep["result"]
    V, F = (np.asarray(x) for x in pipeline.load(stl)[:2])
    V, F = V.astype(np.float64), F.astype(np.int64)
    dev = json.loads((d / res["deviation_map"]).read_text(encoding="utf-8"))
    P, T, val = f32(dev["positions"]).reshape(-1, 3), u32(dev["indices"]).reshape(-1, 3), f32(dev["values"])
    shape = import_step(str(d / res["step"]))
    E = np.asarray(kernel._edges(shape), np.float32).reshape(-1, 3)
    lo = np.minimum(V.min(0), P.min(0)); span = np.maximum(np.maximum(V.max(0), P.max(0)) - lo, 1e-6)
    g = GLB()
    g.add("mesh", V, F, lo, span, {"role": "mesh"})
    g.add("cad", P.astype(np.float64), T, lo, span, {"role": "cad"})
    g.add("cad_edges", E.astype(np.float64), None, lo, span, {"edges": True}, lines=True)
    nb = g.write(OUT / "recon.glb", {"fixture": RECON})
    # where each dimension sits: the centre of what its feature adds to or removes from the solid
    spec = importlib.util.spec_from_file_location("recon_recipe", d / res["recipe"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rec = mod.Design()
    values = {q.key: q.default for q in rec.params}
    stages = rec.build(values)
    where, prev = {}, None
    for st in stages:
        region = st.shape if prev is None else (st.shape - prev) + (prev - st.shape)
        try:
            c = region.center()
            where[st.feature] = [round(float(c.X), 2), round(float(c.Y), 2), round(float(c.Z), 2)]
        except Exception:                                    # nothing changed: keep the last place this feature had
            pass
        prev = st.shape
    dims = [{"key": q.key, "label": q.label, "value": q.default, "unit": q.unit, "feature": q.feature, "at": where.get(q.feature)}
            for q in rec.params]
    missing = [x["key"] for x in dims if x["at"] is None]
    if missing:
        raise SystemExit(f"no place for the dimensions {missing}")
    out = {"fixture": RECON, "tolerance_mm": rep["tolerance_mm"], "triangles": int(len(F)), "faces": len(shape.faces()),
           "hausdorff_mm": res["hausdorff_mm"], "dimensions": res["dimensions"], "editable_pct": res["editable_pct"],
           "headline": res["headline"], "dims": dims,
           "deviation_nm": [int(round(float(x) * 1e6)) for x in val],          # per vertex of the CAD mesh, in order
           "deviation_max_mm": dev["stats"]["max_mm"], "evidence": dev["evidence"]}
    (OUT / "recon.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print("recon.glb", nb, "bytes;", out["triangles"], "triangles in,", out["faces"], "faces,",
          f"{res['dimensions']['movable']} of {res['dimensions']['params']} dimensions,", res["hausdorff_mm"], "mm")


def main() -> int:
    if sys.argv[1:] == ["recon"]:
        OUT.mkdir(parents=True, exist_ok=True)
        export_recon()
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    old = json.loads((OUT / "site.json").read_text(encoding="utf-8")) if (OUT / "site.json").exists() else {}
    s = Studio(config.load())
    site: dict = {}
    try:
        # ---- the sample ----
        p = ensure_sample(s)
        rev = s.rev(p)
        v = s.view(p)
        recipe = s.recipe(p)
        feats = {f.id: {"label": f.label, "role": f.role, "doc": f.doc} for f in recipe.features}
        order = [f.id for f in recipe.features]
        lo = np.asarray(v["bbox"][0]); hi = np.asarray(v["bbox"][1]); span = np.maximum(hi - lo, 1e-6)
        g = GLB()
        by_feature: dict = {}
        for (fid, _part), (P, T) in feature_meshes(v).items():     # a feature that spans several parts is one mesh here
            Ps, Ts, n = by_feature.setdefault(fid, ([], [], [0]))
            Ps.append(P); Ts.append(T + n[0]); n[0] += len(P)
        for fid in sorted(by_feature, key=lambda k: order.index(k) if k in order else 99):
            P, T = weld(np.concatenate(by_feature[fid][0]), np.concatenate(by_feature[fid][1]))
            g.add(fid, P, T, lo, span, {"feature": fid, **feats.get(fid, {})})
        E = f32(v["edges"]).reshape(-1, 3)
        g.add("edges", E, None, lo, span, {"edges": True}, lines=True)
        nb = g.write(OUT / "sample.glb", {"project": SAMPLE, "rev": rev["n"]})
        print("sample.glb", nb, "bytes")
        # the design card on Home: the engine's own headless render of the head revision, in the app's dark colours
        from form import render as rendering
        rendering.PAPER, rendering.INK, rendering.PALETTE = (25, 30, 34), (11, 13, 14), [(216, 211, 200)]
        card = rendering.render_png(v, [{"id": i, "label": feats[i]["label"]} for i in order], camera=(-58.0, 34.0), size=(560, 415),
                                    overlay=False, as_image=True)
        card.save(SHOTS / "card-sample.webp", "WEBP", quality=84, method=6)

        checks = s.read(p, "checks", s.keys(p)["checks"])["checks"]
        state = json.loads(cli("state", SAMPLE)["out"])
        prov = rev["provenance"]
        purpose = p.get("purpose") if isinstance(p.get("purpose"), str) else (p.get("purpose") or {}).get("purpose")
        purpose = purpose or "model"
        asm = v.get("assembly") or {}
        site["sample"] = {
            "id": SAMPLE, "name": p.get("name") or state["name"], "head": rev["n"], "values": rev["values"], "purpose": purpose,
            "provenance": {k: x.get("source") for k, x in prov.items()},
            "params": [{"key": sp.key, "label": sp.label, "unit": sp.unit, "min": sp.min, "max": sp.max, "doc": sp.doc, "group": sp.group}
                       for sp in recipe.params],
            "brief": state["brief"], "features": [{"id": i, **feats[i]} for i in order],
            "bbox": v["bbox"], "size": [round(float(x), 1) for x in span], "volume_cm3": round(v["volume_mm3"] / 1000, 1),
            "faces": v["faces"], "build_ms": round(v["timing"]["build_s"] * 1000), "kernel": v["kernel"],
            "parts": [{"id": x["id"], "label": x["label"]} for x in asm.get("parts", [])],
            "derived": v["derived"], "checks": checks, "gate": state["release_gate"],
            "revisions": [{"n": r["n"], "note": r.get("note", ""), "summary": r.get("summary", ""), "origin": r.get("origin"), "ts": r.get("ts")}
                          for r in p["revisions"]],
        }
        try:
            th = json.loads(cli("analyze", SAMPLE, "--map", "thickness")["out"])
            site["sample"]["thickness"] = {k: th[k] for k in ("label", "evidence", "legend", "stats", "markers", "sample_spacing_mm", "samples")}
        except (ValueError, KeyError) as e:
            print("no wall-thickness map:", e)

        # a slice and its toolpath only for a print design that really was sliced
        slice_meta = s.read(p, "slice", s.keys(p)["slice"]) if purpose == "print" else None
        if slice_meta:
            plate = 1 if slice_meta.get("plates") else None
            m1, _folder, _gcode = s.plate_meta(p, plate)
            tp = toolpath.for_project(s, p, plate)
            blob, tmeta = export_toolpath(tp)
            (OUT / "toolpath.bin").write_bytes(blob)
            tmeta["bytes"] = len(blob)
            site["sample"]["toolpath"] = tmeta
            site["sample"]["slice"] = state.get("slice_simulated")
            site["sample"]["slice_meta"] = {**{k: m1.get(k) for k in ("time_s", "filament_g", "filament_mm", "layers", "slicer_version", "presets")},
                                            "plates": len(slice_meta.get("plates") or []) or 1, "profile": s.profile(p)}
            print("toolpath.bin", len(blob), "bytes,", tmeta["runs"], "runs,", tmeta["points"], "points from", tmeta["segments_in_gcode"], "moves")
        elif (OUT / "toolpath.bin").exists():
            (OUT / "toolpath.bin").unlink()

        # ---- the hinged box (assembly) ----
        try:
            pb = s.load(BOX)
        except Exception:
            pb = None
        if pb is None:
            if "box" not in old or not (OUT / "box.glb").exists():
                raise SystemExit(f"the data folder has no {BOX} project and site/assets/data has no published box to keep")
            site["box"] = old["box"]
            print("box.glb kept as published")
        else:
            vb = s.view(pb)
            asm = vb["assembly"]
            lo = np.asarray(vb["bbox"][0]); hi = np.asarray(vb["bbox"][1]); span = np.maximum(hi - lo, 1e-6)
            gb = GLB()
            rb = s.recipe(pb)
            bfeats = {f.id: {"label": f.label, "role": f.role} for f in rb.features}
            for (fid, part), (P, T) in feature_meshes(vb).items():
                P, T = weld(P, T)
                gb.add(f"{part}:{fid}", P, T, lo, span, {"feature": fid, "part": part, **bfeats.get(fid, {})})
            for part in asm["parts"]:
                E = f32(part["edges"]).reshape(-1, 3)
                gb.add(f"{part['id']}:edges", E, None, lo, span, {"edges": True, "part": part["id"]}, lines=True)
            nb = gb.write(OUT / "box.glb", {"project": BOX})
            print("box.glb", nb, "bytes")
            site["box"] = {"id": BOX, "name": pb.get("name"), "parts": [{k: x[k] for k in ("id", "label", "note", "placement", "explode", "bbox", "print_bbox", "volume_mm3")}
                                                                      for x in asm["parts"]],
                           "joints": asm["joints"], "hardware": asm["hardware"], "bbox": asm["bbox"], "bbox_exploded": asm["bbox_exploded"]}
    finally:
        s.kernel.stop()
    export_recon()
    (OUT / "site.json").write_text(json.dumps(site, separators=(",", ":"), ensure_ascii=False, default=float), encoding="utf-8")
    print("site.json", (OUT / "site.json").stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
