"""Export the real FORM data the website draws: models, checks, fit, toolpath and CLI output.

Nothing on the home page is invented. Every number, shape and line it shows comes from this script,
which asks FORM's own engine (the same Studio the app and the CLI use) for a sample project.

Run from the repository root with a data folder that holds the sample projects:

    FORM_DATA=.dev/web/data FORM_CONFIG=/nonexistent PYTHONPATH=. .venv/bin/python site/tools/export_site_data.py

Writes into site/assets/data/:
    dock.glb       the phone dock at its head revision, one mesh per feature plus the kernel's B-rep edges
    box.glb        the hinged box: its two parts, per feature, in the print frame
    toolpath.bin   the dock's sliced toolpath, simplified for the browser (layout in site.json -> toolpath)
    site.json      project state, checks, fit model over a clearance sweep, slice summary, assembly, CLI output

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
DOCK = "hallway-phone-dock"
BOX = "hinged-box"


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
    env = dict(os.environ)
    r = subprocess.run([str(ROOT / ".venv" / "bin" / "form"), *args], capture_output=True, text=True, env=env, cwd=ROOT)
    return {"cmd": "form " + " ".join(args), "out": r.stdout.strip()}


def trim_json(text: str, keep: list[str]) -> str:
    d = json.loads(text)
    return json.dumps({k: d[k] for k in keep if k in d}, indent=1, ensure_ascii=False)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Studio(config.load())
    site: dict = {}
    try:
        # ---- the dock ----
        p = s.load(DOCK)
        rev = s.rev(p)
        v = s.view(p)
        recipe = s.recipe(p)
        feats = {f.id: {"label": f.label, "role": f.role, "doc": f.doc} for f in recipe.features}
        order = [f.id for f in recipe.features]
        lo = np.asarray(v["bbox"][0]); hi = np.asarray(v["bbox"][1]); span = np.maximum(hi - lo, 1e-6)
        g = GLB()
        meshes = feature_meshes(v)
        for (fid, _), (P, T) in sorted(meshes.items(), key=lambda kv: order.index(kv[0][0]) if kv[0][0] in order else 99):
            P, T = weld(P, T)
            g.add(fid, P, T, lo, span, {"feature": fid, **feats.get(fid, {})})
        E = f32(v["edges"]).reshape(-1, 3)
        g.add("edges", E, None, lo, span, {"edges": True}, lines=True)
        nb = g.write(OUT / "dock.glb", {"project": DOCK, "rev": rev["n"]})
        print("dock.glb", nb, "bytes", sum(len(m[0]) for m in meshes.values()), "vertices before weld")

        checks = s.read(p, "checks", s.keys(p)["checks"])["checks"]
        state = json.loads(cli("state", DOCK)["out"])
        fit_now = s.fit(p)
        prov = rev["provenance"]
        sweep = []
        for c in np.round(np.arange(0.10, 0.5001, 0.01), 3):
            row = {"c": float(c)}
            for tag, pv in (("assumed", prov), ("measured", {**prov, "device_width": {"source": "measured"}})):
                f = s.fit(p, {**rev["values"], "clearance": float(c)}, pv)
                row[tag] = {"gap": round(f["expected_gap"], 4), "sd": round(f["sd"], 4), "y": round(f["yield"], 4),
                            "tight": round(f["p_tight"], 4), "loose": round(f["p_loose"], 4)}
            sweep.append(row)
        f_meas = s.fit(p, None, {**prov, "device_width": {"source": "measured"}})

        tp = toolpath.for_project(s, p)
        blob, tmeta = export_toolpath(tp)
        (OUT / "toolpath.bin").write_bytes(blob)
        tmeta["bytes"] = len(blob)
        slice_meta = s.read(p, "slice", s.keys(p)["slice"])
        print("toolpath.bin", len(blob), "bytes,", tmeta["runs"], "runs,", tmeta["points"], "points from", tmeta["segments_in_gcode"], "moves")

        site["dock"] = {
            "id": DOCK, "name": p.get("name") or state["name"], "head": rev["n"], "values": rev["values"],
            "provenance": {k: x.get("source") for k, x in prov.items()},
            "params": {sp.key: {"label": sp.label, "unit": sp.unit, "min": sp.min, "max": sp.max, "doc": sp.doc} for sp in recipe.params},
            "brief": state["brief"], "features": [{"id": i, **feats[i]} for i in order],
            "bbox": v["bbox"], "size": [round(float(x), 1) for x in span], "volume_cm3": round(v["volume_mm3"] / 1000, 1),
            "faces": v["faces"], "build_ms": round(v["timing"]["build_s"] * 1000), "kernel": v["kernel"],
            "companions": v["companions"], "derived": v["derived"], "statics": v.get("statics"),
            "checks": checks, "gate": state["release_gate"], "fit": fit_now, "fit_measured": {"yield": f_meas["yield"], "sd": f_meas["sd"]},
            "fit_sweep": sweep, "next_actions": state["next_best_actions"], "slice": state["slice_simulated"],
            "slice_meta": {k: slice_meta.get(k) for k in ("time_s", "filament_g", "filament_m", "layers", "slicer", "slicer_version", "presets")},
            "revisions": [{"n": r["n"], "note": r.get("note", ""), "summary": r.get("summary", ""), "origin": r.get("origin"), "ts": r.get("ts")}
                          for r in p["revisions"]],
            "toolpath": tmeta,
        }
        th = json.loads(cli("analyze", DOCK, "--map", "thickness")["out"])
        site["dock"]["thickness"] = {k: th[k] for k in ("label", "evidence", "legend", "stats", "markers", "sample_spacing_mm", "samples")}

        # ---- the hinged box (assembly) ----
        pb = s.load(BOX)
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

    # ---- CLI output, captured as run ----
    pv = cli("preview", DOCK, "lean=19")
    sim = cli("simulate", DOCK, "--layer", "51")
    cost = cli("cost", DOCK)
    st = cli("state", DOCK)
    site["cli"] = [
        {"cmd": st["cmd"], "out": trim_json(st["out"], ["project", "head", "outputs", "release_gate", "slice_simulated"])},
        {"cmd": pv["cmd"], "out": pv["out"]},
        {"cmd": sim["cmd"], "out": json.dumps({"at": {k: json.loads(sim["out"])["at"][k] for k in
                                                     ("layer", "z_mm", "types_in_layer", "has_bridge", "elapsed_s", "remaining_s", "evidence")},
                                              "label": json.loads(sim["out"])["label"]}, indent=1, ensure_ascii=False)},
        {"cmd": cost["cmd"], "out": json.dumps({"filament": {k: json.loads(cost["out"])["filament"][k] for k in ("grams", "price_per_kg", "price_source", "cost", "evidence")},
                                                "electricity": {"needs": json.loads(cost["out"])["electricity"]["needs"]}}, indent=1, ensure_ascii=False)},
    ]
    (OUT / "site.json").write_text(json.dumps(site, separators=(",", ":"), ensure_ascii=False, default=float), encoding="utf-8")
    print("site.json", (OUT / "site.json").stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
