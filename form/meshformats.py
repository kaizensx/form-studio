"""Readers for the mesh and point cloud formats beyond STL, OBJ and 3MF (those live in form/recon/mesh.py): PLY, OFF,
AMF, glTF/GLB, Collada, X3D, VRML, VTK (legacy, VTP, VTU), XYZ, PTS, LAS and E57. numpy only, no kernel, so the MCP
server, the CLI and the worker all read them the same way. form/formats.py is the table of what is read.

    read(path) -> {"parts": [(name, T (m, 3, 3) float64 mm)], "points": P (n, 3) mm or None, "normals": N or None,
                   "format", "units": {"units", "source"}, "axes", "notes": [...]}

Units and axes. A format that states its units (AMF's unit, Collada's <unit meter>) or has them by rule (glTF, LAS
and E57 are metres) is converted to millimetres, and glTF's and Collada's Y-up is turned to Z-up ((x, y, z) ->
(x, -z, y), the inverse of what Form Studio's own GLB export does). The rest carry no units: the numbers are taken
as millimetres and form/triage.py's size test says when that is unlikely. Colours, textures and materials are not
geometry: they are ignored, and the notes say so.
"""
from __future__ import annotations

import base64
import json
import re
import struct
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

import numpy as np

MAX_POINTS_READ = 50_000_000          # a point cloud larger than this is refused before it is read

_PLY_TYPES = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2",
              "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
              "float": "f4", "float32": "f4", "double": "f8", "float64": "f8"}
Y_UP_TO_Z_UP = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])


def _result(fmt, parts=None, points=None, normals=None, units="mm", source="assumed (the format carries no units)",
            axes=None, notes=None) -> dict:
    return {"parts": parts or [], "points": points, "normals": normals, "format": fmt,
            "units": {"units": units, "source": source}, "axes": axes, "notes": notes or []}


def _fan(polys) -> np.ndarray:
    """Triangles (k, 3) from polygons given as index lists (fan triangulation, as exporters expect)."""
    out = []
    for p in polys:
        for k in range(1, len(p) - 1):
            out.append((p[0], p[k], p[k + 1]))
    return np.asarray(out, dtype=np.int64).reshape(-1, 3)


def _tris(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    if len(F) and (F.min() < 0 or F.max() >= len(V)):
        raise ValueError("A face refers to a vertex the file does not have.")
    return np.asarray(V, dtype=np.float64)[F]


# ---- PLY ---------------------------------------------------------------------------------------------------------------

def _ply(path: Path) -> dict:
    data = path.read_bytes()
    end = re.search(rb"end_header\r?\n", data)
    if not data.startswith(b"ply") or not end:
        raise ValueError("Not a PLY file: it does not start with 'ply' and an 'end_header' line.")
    head = data[:end.start()].decode("ascii", "replace").splitlines()
    body = data[end.end():]
    fmt, elements = "ascii", []
    for ln in head[1:]:
        s = ln.split()
        if not s or s[0] in ("comment", "obj_info"):
            continue
        if s[0] == "format":
            fmt = s[1]
        elif s[0] == "element":
            elements.append({"name": s[1], "count": int(s[2]), "props": []})
        elif s[0] == "property" and elements:
            if s[1] == "list":
                elements[-1]["props"].append((s[4], "list", _PLY_TYPES[s[2]], _PLY_TYPES[s[3]]))
            else:
                elements[-1]["props"].append((s[2], _PLY_TYPES[s[1]], None, None))
    if fmt not in ("ascii", "binary_little_endian", "binary_big_endian"):
        raise ValueError(f"Unknown PLY format {fmt}.")
    tables = {}
    if fmt == "ascii":
        toks = body.split()
        pos = 0
        for el in elements:
            rows = []
            if all(p[1] != "list" for p in el["props"]):
                n = len(el["props"]) * el["count"]
                arr = np.asarray(toks[pos:pos + n], dtype=np.float64).reshape(el["count"], len(el["props"]))
                pos += n
                tables[el["name"]] = {p[0]: arr[:, i] for i, p in enumerate(el["props"])}
                continue
            cols = {p[0]: [] for p in el["props"]}
            for _ in range(el["count"]):
                for p in el["props"]:
                    if p[1] == "list":
                        c = int(float(toks[pos]))
                        cols[p[0]].append([int(float(t)) for t in toks[pos + 1:pos + 1 + c]])
                        pos += 1 + c
                    else:
                        cols[p[0]].append(float(toks[pos]))
                        pos += 1
            rows = cols
            tables[el["name"]] = rows
    else:
        bo = "<" if fmt == "binary_little_endian" else ">"
        pos = 0
        for el in elements:
            props = el["props"]
            if all(p[1] != "list" for p in props):
                dt = np.dtype([(p[0] or f"p{i}", bo + p[1]) for i, p in enumerate(props)])
                arr = np.frombuffer(body, dtype=dt, count=el["count"], offset=pos)
                pos += dt.itemsize * el["count"]
                tables[el["name"]] = {p[0]: arr[p[0]].astype(np.float64) for p in props}
                continue
            # fast path: one list whose count is the same for every row (faces of a triangle mesh)
            done = False
            li = [i for i, p in enumerate(props) if p[1] == "list"]
            if len(li) == 1 and el["count"]:
                pre = sum(np.dtype(p[1]).itemsize for p in props[:li[0]])
                ct = np.dtype(bo + props[li[0]][2])
                c0 = int(np.frombuffer(body, dtype=ct, count=1, offset=pos + pre)[0])
                fields = []
                for i, p in enumerate(props):
                    if p[1] == "list":
                        fields += [("n_", bo + p[2]), (p[0], bo + p[3], (c0,))]
                    else:
                        fields.append((p[0] or f"p{i}", bo + p[1]))
                dt = np.dtype(fields)
                if pos + dt.itemsize * el["count"] <= len(body):
                    arr = np.frombuffer(body, dtype=dt, count=el["count"], offset=pos)
                    if np.all(arr["n_"] == c0):
                        tables[el["name"]] = {props[li[0]][0]: arr[props[li[0]][0]].astype(np.int64)}
                        pos += dt.itemsize * el["count"]
                        done = True
            if not done:
                cols = {p[0]: [] for p in props}
                for _ in range(el["count"]):
                    for p in props:
                        if p[1] == "list":
                            ct, it = np.dtype(bo + p[2]), np.dtype(bo + p[3])
                            c = int(np.frombuffer(body, dtype=ct, count=1, offset=pos)[0])
                            pos += ct.itemsize
                            cols[p[0]].append(np.frombuffer(body, dtype=it, count=c, offset=pos).astype(np.int64).tolist())
                            pos += it.itemsize * c
                        else:
                            t = np.dtype(bo + p[1])
                            cols[p[0]].append(float(np.frombuffer(body, dtype=t, count=1, offset=pos)[0]))
                            pos += t.itemsize
                tables[el["name"]] = cols
    v = tables.get("vertex")
    if not v or "x" not in v:
        raise ValueError("The PLY has no vertex element with x, y and z.")
    V = np.stack([np.asarray(v[k], dtype=np.float64) for k in ("x", "y", "z")], axis=1)
    notes = []
    if all(k in v for k in ("red", "green", "blue")) or "diffuse_red" in v:
        notes.append("vertex colours are in the file; they are not geometry and are not used")
    face = tables.get("face") or {}
    idx = face.get("vertex_indices", face.get("vertex_index"))
    kind = "ply (" + fmt.replace("binary_", "binary ").replace("_endian", " endian") + ")"
    if idx is None or not len(idx):
        N = None
        if all(k in v for k in ("nx", "ny", "nz")):
            N = np.stack([np.asarray(v[k], dtype=np.float64) for k in ("nx", "ny", "nz")], axis=1)
        return _result(kind, points=V, normals=N, notes=notes + ["vertices only: a point cloud"])
    F = idx if isinstance(idx, np.ndarray) and idx.ndim == 2 and idx.shape[1] == 3 else _fan(
        idx.tolist() if isinstance(idx, np.ndarray) else idx)
    return _result(kind, parts=[(path.stem, _tris(V, F))], notes=notes)


# ---- OFF ---------------------------------------------------------------------------------------------------------------

def _off(path: Path) -> dict:
    lines = [ln.split("#")[0].split() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines or not lines[0][0].upper().endswith("OFF"):
        raise ValueError("Not an OFF file: it does not start with OFF.")
    if "4" in lines[0][0] or lines[0][0].upper().startswith("NOFF") and len(lines[0]) == 2:
        raise ValueError("Only 3D OFF files are read.")
    counts = lines[0][1:] or lines[1]
    at = 1 if lines[0][1:] else 2
    nv, nf = int(counts[0]), int(counts[1])
    V = np.asarray([ln[:3] for ln in lines[at:at + nv]], dtype=np.float64)
    polys = []
    for ln in lines[at + nv:at + nv + nf]:
        c = int(ln[0])
        polys.append([int(t) for t in ln[1:1 + c]])
    return _result("off", parts=[(path.stem, _tris(V, _fan(polys)))])


# ---- AMF ---------------------------------------------------------------------------------------------------------------

_AMF_UNITS = {"millimeter": 1.0, "millimetre": 1.0, "inch": 25.4, "feet": 304.8, "foot": 304.8, "meter": 1000.0,
              "metre": 1000.0, "micron": 0.001, "micrometer": 0.001}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _amf(path: Path) -> dict:
    data = path.read_bytes()
    if data[:2] == b"PK":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            pick = next((n for n in names if n.lower().endswith(".amf")), names[0] if names else None)
            if pick is None:
                raise ValueError("The zipped AMF is empty.")
            data = z.read(pick)
    root = ElementTree.fromstring(data)
    unit = (root.get("unit") or "millimeter").lower()
    k = _AMF_UNITS.get(unit)
    if k is None:
        raise ValueError(f"Unknown AMF unit {unit!r}.")
    parts = []
    for obj in root:
        if _local(obj.tag) != "object":
            continue
        name = next((m.text for m in obj.iter() if _local(m.tag) == "metadata" and m.get("type") == "name" and m.text),
                    f"object {obj.get('id', len(parts) + 1)}")
        for mesh in obj:
            if _local(mesh.tag) != "mesh":
                continue
            verts = []
            for vx in mesh.iter():
                if _local(vx.tag) == "coordinates":
                    c = {_local(e.tag): float(e.text) for e in vx}
                    verts.append((c["x"], c["y"], c["z"]))
            V = np.asarray(verts, dtype=np.float64) * k
            F = []
            for vol in mesh:
                if _local(vol.tag) != "volume":
                    continue
                for t in vol:
                    if _local(t.tag) == "triangle":
                        c = {_local(e.tag): int(e.text) for e in t}
                        F.append((c["v1"], c["v2"], c["v3"]))
            if F:
                parts.append((name.strip()[:120], _tris(V, F)))
    if not parts:
        raise ValueError("The AMF holds no triangles.")
    return _result("amf", parts=parts, units=unit, source="the file",
                   notes=["constellations (placed copies) are not expanded; each object is read once"]
                   if any(_local(e.tag) == "constellation" for e in root) else [])


# ---- glTF / GLB --------------------------------------------------------------------------------------------------------

_GL_COMP = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
_GL_N = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _quat(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _gltf(path: Path) -> dict:
    data = path.read_bytes()
    bin_chunk = None
    if data[:4] == b"glTF":
        _magic, _ver, length = struct.unpack_from("<III", data, 0)
        pos, js = 12, None
        while pos + 8 <= min(length, len(data)):
            n, typ = struct.unpack_from("<II", data, pos)
            chunk = data[pos + 8:pos + 8 + n]
            if typ == 0x4E4F534A:
                js = json.loads(chunk.decode("utf-8"))
            elif typ == 0x004E4942:
                bin_chunk = chunk
            pos += 8 + n
        if js is None:
            raise ValueError("The GLB has no JSON chunk.")
        fmt = "glb"
    else:
        js, fmt = json.loads(data.decode("utf-8")), "gltf"
    used = set(js.get("extensionsRequired") or []) | set(js.get("extensionsUsed") or [])
    for ext in ("KHR_draco_mesh_compression", "EXT_meshopt_compression"):
        if ext in used:
            raise ValueError(f"The file's meshes are compressed with {ext}, which Form Studio does not decode. Export "
                             "it again without mesh compression.")
    buffers = []
    for b in js.get("buffers", []):
        uri = b.get("uri")
        if uri is None:
            buffers.append(bin_chunk or b"")
        elif uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            here = path.parent.resolve()
            f = (here / uri.replace("%20", " ")).resolve()
            if not f.is_relative_to(here) or not f.is_file():
                raise ValueError(f"The glTF keeps its data in {uri}, which is not beside it. Send the .glb, or a zip "
                                 "with the .gltf and its .bin.")
            buffers.append(f.read_bytes())
    views, accs = js.get("bufferViews", []), js.get("accessors", [])

    def accessor(i):
        a = accs[i]
        dt = np.dtype(_GL_COMP[a["componentType"]])
        n, count = _GL_N[a["type"]], a["count"]
        if "bufferView" not in a:
            return np.zeros((count, n))
        v = views[a["bufferView"]]
        buf = buffers[v["buffer"]]
        off = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = v.get("byteStride") or dt.itemsize * n
        if stride == dt.itemsize * n:
            arr = np.frombuffer(buf, dtype=dt, count=count * n, offset=off).reshape(count, n)
        else:
            raw = np.frombuffer(buf, dtype=np.uint8, count=stride * (count - 1) + dt.itemsize * n, offset=off)
            arr = np.lib.stride_tricks.as_strided(raw, shape=(count, dt.itemsize * n), strides=(stride, 1))
            arr = np.ascontiguousarray(arr).view(dt).reshape(count, n)
        return arr.astype(np.float64) if dt.kind == "f" else arr.astype(np.int64)

    def prims(mi):
        out = []
        for pr in js["meshes"][mi].get("primitives", []):
            mode = pr.get("mode", 4)
            if mode not in (4, 5, 6) or "POSITION" not in pr.get("attributes", {}):
                continue
            V = accessor(pr["attributes"]["POSITION"])
            idx = accessor(pr["indices"]).reshape(-1) if "indices" in pr else np.arange(len(V))
            if mode == 4:
                F = idx[:len(idx) // 3 * 3].reshape(-1, 3)
            elif mode == 5:
                F = np.array([(idx[i], idx[i + 1], idx[i + 2]) if i % 2 == 0 else (idx[i + 1], idx[i], idx[i + 2])
                              for i in range(len(idx) - 2)], dtype=np.int64).reshape(-1, 3)
            else:
                F = np.array([(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)], dtype=np.int64).reshape(-1, 3)
            out.append(_tris(V, F))
        return out

    nodes = js.get("nodes", [])

    def local(n):
        if "matrix" in n:
            return np.asarray(n["matrix"], dtype=np.float64).reshape(4, 4).T
        M = np.eye(4)
        R = _quat(n.get("rotation", [0, 0, 0, 1]))
        S = np.diag(n.get("scale", [1, 1, 1]))
        M[:3, :3] = R @ S
        M[:3, 3] = n.get("translation", [0, 0, 0])
        return M

    parts = []

    def walk(i, M, depth=0):
        if depth > 64:
            return
        n = nodes[i]
        W = M @ local(n)
        if "mesh" in n:
            for T in prims(n["mesh"]):
                P = T.reshape(-1, 3) @ W[:3, :3].T + W[:3, 3]
                T = P.reshape(-1, 3, 3)
                if np.linalg.det(W[:3, :3]) < 0:
                    T = T[:, ::-1]
                parts.append((n.get("name") or js["meshes"][n["mesh"]].get("name") or f"mesh {n['mesh']}", T))
        for c in n.get("children", []):
            walk(c, W, depth + 1)

    scenes = js.get("scenes") or []
    if scenes:
        for r in scenes[js.get("scene", 0)].get("nodes", []):
            walk(r, np.eye(4))
    elif nodes:
        kids = {c for n in nodes for c in n.get("children", [])}
        for r in (i for i in range(len(nodes)) if i not in kids):
            walk(r, np.eye(4))
    else:
        for mi in range(len(js.get("meshes", []))):
            parts += [(js["meshes"][mi].get("name") or f"mesh {mi}", T) for T in prims(mi)]
    if not parts:
        raise ValueError("The glTF holds no triangle meshes.")
    out = [(nm[:120], (T.reshape(-1, 3) @ Y_UP_TO_Z_UP.T * 1000.0).reshape(-1, 3, 3)) for nm, T in parts]
    notes = ["materials and textures are not geometry and are not used"] if js.get("materials") else []
    return _result(fmt, parts=out, units="m", source="the format (glTF is in metres)",
                   axes="Y up in the file, turned to Z up", notes=notes)


# ---- Collada -----------------------------------------------------------------------------------------------------------

def _dae(path: Path) -> dict:
    root = ElementTree.parse(path).getroot()
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    meter, up = 1.0, "Y_UP"
    asset = root.find(ns + "asset")
    if asset is not None:
        u = asset.find(ns + "unit")
        if u is not None and u.get("meter"):
            meter = float(u.get("meter"))
        a = asset.find(ns + "up_axis")
        if a is not None and a.text:
            up = a.text.strip().upper()
    stated = asset is not None and asset.find(ns + "unit") is not None
    floats = {}
    for fa in root.iter(ns + "float_array"):
        if fa.get("id"):
            floats[fa.get("id")] = np.asarray((fa.text or "").split(), dtype=np.float64)
    sources = {}
    for s in root.iter(ns + "source"):
        fa = s.find(ns + "float_array")
        acc = s.find(f"{ns}technique_common/{ns}accessor")
        if fa is not None and fa.get("id") in floats:
            stride = int(acc.get("stride", 3)) if acc is not None else 3
            arr = floats[fa.get("id")]
            sources[s.get("id")] = arr[:len(arr) // stride * stride].reshape(-1, stride)[:, :3]
    geoms = {}
    for g in root.iter(ns + "geometry"):
        mesh = g.find(ns + "mesh")
        if mesh is None:
            continue
        vmap = {}
        for v in mesh.findall(ns + "vertices"):
            for inp in v.findall(ns + "input"):
                if inp.get("semantic") == "POSITION":
                    vmap[v.get("id")] = inp.get("source", "").lstrip("#")
        tris = []
        for kind in ("triangles", "polylist", "polygons", "trifans", "tristrips"):
            for el in mesh.findall(ns + kind):
                inputs = el.findall(ns + "input")
                stride = max(int(i.get("offset", 0)) for i in inputs) + 1 if inputs else 1
                vin = next((i for i in inputs if i.get("semantic") == "VERTEX"), None)
                if vin is None:
                    continue
                src = vmap.get(vin.get("source", "").lstrip("#"), vin.get("source", "").lstrip("#"))
                V = sources.get(src)
                if V is None:
                    continue
                off = int(vin.get("offset", 0))
                ps = [np.asarray((p.text or "").split(), dtype=np.int64) for p in el.findall(ns + "p")]
                if kind == "triangles":
                    idx = np.concatenate(ps)[off::stride] if ps else np.zeros(0, np.int64)
                    F = idx[:len(idx) // 3 * 3].reshape(-1, 3)
                elif kind == "polylist":
                    vc = np.asarray((el.findtext(ns + "vcount") or "").split(), dtype=np.int64)
                    idx = np.concatenate(ps)[off::stride] if ps else np.zeros(0, np.int64)
                    polys, at = [], 0
                    for c in vc:
                        polys.append(idx[at:at + c].tolist())
                        at += c
                    F = _fan(polys)
                elif kind in ("polygons", "trifans"):
                    F = _fan([p[off::stride].tolist() for p in ps])
                else:
                    F = np.array([(s[i], s[i + 1], s[i + 2]) if i % 2 == 0 else (s[i + 1], s[i], s[i + 2])
                                  for p in ps for s in [p[off::stride]] for i in range(len(s) - 2)],
                                 dtype=np.int64).reshape(-1, 3)
                tris.append(_tris(V, F))
        if tris:
            geoms[g.get("id")] = (g.get("name") or g.get("id"), np.concatenate(tris))

    def local(node):
        M = np.eye(4)
        for t in node:
            tag = _local(t.tag)
            vals = np.asarray((t.text or "").split(), dtype=np.float64)
            if tag == "matrix" and len(vals) == 16:
                M = M @ vals.reshape(4, 4)
            elif tag == "translate" and len(vals) == 3:
                X = np.eye(4)
                X[:3, 3] = vals
                M = M @ X
            elif tag == "scale" and len(vals) == 3:
                M = M @ np.diag([*vals, 1.0])
            elif tag == "rotate" and len(vals) == 4:
                ax = vals[:3] / max(np.linalg.norm(vals[:3]), 1e-12)
                a = np.radians(vals[3])
                K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
                X = np.eye(4)
                X[:3, :3] = np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K
                M = M @ X
        return M

    library_nodes = {n.get("id"): n for ln in root.iter(ns + "library_nodes") for n in ln.findall(ns + "node")}
    parts = []

    def walk(node, M, depth=0):
        if depth > 64:
            return
        W = M @ local(node)
        for ig in node.findall(ns + "instance_geometry"):
            gid = ig.get("url", "").lstrip("#")
            if gid in geoms:
                nm, T = geoms[gid]
                P = T.reshape(-1, 3) @ W[:3, :3].T + W[:3, 3]
                T2 = P.reshape(-1, 3, 3)
                if np.linalg.det(W[:3, :3]) < 0:
                    T2 = T2[:, ::-1]
                parts.append((node.get("name") or nm, T2))
        for inst in node.findall(ns + "instance_node"):
            ref = library_nodes.get(inst.get("url", "").lstrip("#"))
            if ref is not None:
                walk(ref, W, depth + 1)
        for c in node.findall(ns + "node"):
            walk(c, W, depth + 1)

    scenes = list(root.iter(ns + "visual_scene"))
    for vs in scenes[:1]:
        for n in vs.findall(ns + "node"):
            walk(n, np.eye(4))
    if not parts:
        parts = list(geoms.values())
    if not parts:
        raise ValueError("The Collada file holds no triangle meshes.")
    # Collada's axes: Y_UP is right +X, up +Y; X_UP is right -Y, up +X. Both turned to Z up, right-handed.
    R = {"Y_UP": Y_UP_TO_Z_UP, "X_UP": np.array([[0, -1.0, 0], [0, 0, -1.0], [1.0, 0, 0]])}.get(up)
    k = meter * 1000.0
    out = []
    for nm, T in parts:
        P = T.reshape(-1, 3)
        if R is not None:
            P = P @ R.T
        out.append(((nm or "part")[:120], (P * k).reshape(-1, 3, 3)))
    units = {1.0: "m", 0.01: "cm", 0.001: "mm", 0.0254: "in"}.get(round(meter, 6), f"{meter:g} m")
    return _result("dae", parts=out, units=units if stated else "m",
                   source="the file (<unit>)" if stated else "the format (Collada without <unit> is in metres)",
                   axes=f"{up.replace('_', ' ').lower()} in the file" + (", turned to Z up" if R is not None else ""))


# ---- X3D and VRML ------------------------------------------------------------------------------------------------------

def _axis_angle(r) -> np.ndarray:
    ax = np.asarray(r[:3], dtype=np.float64)
    ax = ax / max(np.linalg.norm(ax), 1e-12)
    a = float(r[3])
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


def _trs(translation=None, rotation=None, scale=None, center=None) -> np.ndarray:
    M = np.eye(4)
    T = np.eye(4)
    T[:3, 3] = translation if translation is not None else 0
    C = np.eye(4)
    C[:3, 3] = center if center is not None else 0
    Ci = np.eye(4)
    Ci[:3, 3] = -np.asarray(center if center is not None else [0, 0, 0], dtype=np.float64)
    R = np.eye(4)
    if rotation is not None:
        R[:3, :3] = _axis_angle(rotation)
    S = np.diag([*(scale if scale is not None else [1, 1, 1]), 1.0])
    M = T @ C @ R @ S @ Ci
    return M


def _faces_from_index(idx, ntri=False) -> np.ndarray:
    idx = [int(i) for i in idx]
    if ntri:
        return np.asarray(idx[:len(idx) // 3 * 3], dtype=np.int64).reshape(-1, 3)
    polys, cur = [], []
    for i in idx:
        if i < 0:
            if len(cur) >= 3:
                polys.append(cur)
            cur = []
        else:
            cur.append(i)
    if len(cur) >= 3:
        polys.append(cur)
    return _fan(polys)


def _place(T: np.ndarray, W: np.ndarray) -> np.ndarray:
    P = T.reshape(-1, 3) @ W[:3, :3].T + W[:3, 3]
    T2 = P.reshape(-1, 3, 3)
    return T2[:, ::-1] if np.linalg.det(W[:3, :3]) < 0 else T2


def _nums(s) -> list:
    return [float(x) for x in re.split(r"[\s,]+", (s or "").strip()) if x]


def _x3d(path: Path) -> dict:
    root = ElementTree.parse(path).getroot()
    defs, parts = {}, []

    def resolve(e):
        if e.get("USE"):
            return defs.get(e.get("USE"), e)
        if e.get("DEF"):
            defs[e.get("DEF")] = e
        return e

    def geometry(g):
        tag = _local(g.tag)
        coord = next((resolve(c) for c in g if _local(c.tag) in ("Coordinate", "CoordinateDouble")), None)
        if coord is None:
            return None
        V = np.asarray(_nums(coord.get("point")), dtype=np.float64).reshape(-1, 3)
        if tag == "IndexedFaceSet":
            F = _faces_from_index(_nums(g.get("coordIndex")))
        elif tag == "IndexedTriangleSet":
            F = _faces_from_index(_nums(g.get("index")), ntri=True)
        elif tag == "TriangleSet":
            F = np.arange(len(V) // 3 * 3).reshape(-1, 3)
        else:
            return None
        return _tris(V, F) if len(F) else None

    def walk(e, M, depth=0):
        if depth > 64:
            return
        e = resolve(e)
        tag = _local(e.tag)
        if tag == "Transform":
            M = M @ _trs(_nums(e.get("translation")) or None, _nums(e.get("rotation")) or None,
                         _nums(e.get("scale")) or None, _nums(e.get("center")) or None)
        if tag == "Shape":
            for g in e:
                g = resolve(g)
                T = geometry(g) if _local(g.tag) not in ("Appearance",) else None
                if T is not None:
                    parts.append((e.get("DEF") or g.get("DEF") or f"shape {len(parts) + 1}", _place(T, M)))
            return
        for c in e:
            walk(c, M, depth + 1)

    walk(root, np.eye(4))
    if not parts:
        raise ValueError("The X3D holds no IndexedFaceSet or triangle set.")
    k, unit = 1.0, None
    for u in root.iter():
        if _local(u.tag) == "unit" and (u.get("category") or "").lower() == "length":
            k, unit = float(u.get("conversionFactor", 1.0)) * 1000.0, u.get("name") or "length unit"
    if unit:
        parts = [(n, T * k) for n, T in parts]
        return _result("x3d", parts=parts, units=f"{k / 1000:g} m", source="the file (<unit category='length'>)")
    return _result("x3d", parts=parts, source="assumed (X3D says metres, but CAD exports often write millimetres; the "
                                              "numbers are taken as millimetres)")


_VRML_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[\[\]{}]|[^\s,\[\]{}"#]+|#[^\n]*')


def _wrl(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("#VRML V1"):
        raise ValueError("VRML 1.0 is not read; save it as VRML 2.0 (VRML97).")
    toks = [t for t in _VRML_TOKEN.findall(text) if not t.startswith("#")]
    pos = 0
    defs = {}

    def node():
        nonlocal pos
        name = None
        if toks[pos] == "DEF":
            name = toks[pos + 1]
            pos += 2
        if toks[pos] == "USE":
            pos += 2
            return defs.get(toks[pos - 1])
        typ = toks[pos]
        pos += 1
        if pos >= len(toks) or toks[pos] != "{":
            return None
        pos += 1
        fields = {"_type": typ}
        while pos < len(toks) and toks[pos] != "}":
            key = toks[pos]
            pos += 1
            if key in ("ROUTE",):
                pos += 3
                continue
            fields[key] = value()
        pos += 1
        if name:
            defs[name] = fields
        return fields

    def value():
        nonlocal pos
        t = toks[pos]
        if t == "[":
            pos += 1
            items = []
            while toks[pos] != "]":
                if re.match(r"^[A-Za-z_]", toks[pos]) and toks[pos] not in ("TRUE", "FALSE") and (
                        toks[pos] in ("DEF", "USE") or (pos + 1 < len(toks) and toks[pos + 1] == "{")):
                    items.append(node())
                else:
                    items.append(toks[pos])
                    pos += 1
            pos += 1
            return items
        if t in ("DEF", "USE") or (re.match(r"^[A-Za-z_]", t) and pos + 1 < len(toks) and toks[pos + 1] == "{"):
            return node()
        if t == "NULL":
            pos += 1
            return None
        out = []
        while pos < len(toks) and re.match(r"^[-+.\deE]+$", toks[pos]):
            out.append(toks[pos])
            pos += 1
        if not out:
            pos += 1
            return t
        return out

    roots = []
    while pos < len(toks):
        if toks[pos] in ("PROTO", "EXTERNPROTO"):
            raise ValueError("The VRML uses PROTO definitions, which Form Studio does not expand.")
        if toks[pos] == "ROUTE":
            pos += 4
            continue
        n = node()
        if n is not None:
            roots.append(n)
    parts = []

    def fl(v):
        return [float(x) for x in (v or []) if isinstance(x, str)]

    def walk(n, M, depth=0):
        if not isinstance(n, dict) or depth > 64:
            return
        if n["_type"] == "Transform":
            M = M @ _trs(fl(n.get("translation")) or None, fl(n.get("rotation")) or None, fl(n.get("scale")) or None,
                         fl(n.get("center")) or None)
        if n["_type"] == "Shape":
            g = n.get("geometry")
            if isinstance(g, dict) and g["_type"] == "IndexedFaceSet" and isinstance(g.get("coord"), dict):
                V = np.asarray(fl(g["coord"].get("point")), dtype=np.float64).reshape(-1, 3)
                F = _faces_from_index(fl(g.get("coordIndex")))
                if len(F):
                    parts.append((f"shape {len(parts) + 1}", _place(_tris(V, F), M)))
            return
        for c in (n.get("children") or []) if isinstance(n.get("children"), list) else [n.get("children")]:
            walk(c, M, depth + 1)

    for r in roots:
        walk(r, np.eye(4))
    if not parts:
        raise ValueError("The VRML holds no IndexedFaceSet.")
    return _result("vrml", parts=parts, source="assumed (VRML says metres, but CAD exports often write millimetres; "
                                               "the numbers are taken as millimetres)")


# ---- VTK ---------------------------------------------------------------------------------------------------------------

_VTK_T = {"bit": "u1", "unsigned_char": "u1", "char": "i1", "unsigned_short": "u2", "short": "i2",
          "unsigned_int": "u4", "int": "i4", "unsigned_long": "u8", "long": "i8", "float": "f4", "double": "f8",
          "vtktypeint64": "i8", "vtktypeuint64": "u8", "vtkidtype": "i8"}
_VTX_T = {"Int8": "i1", "UInt8": "u1", "Int16": "i2", "UInt16": "u2", "Int32": "i4", "UInt32": "u4", "Int64": "i8",
          "UInt64": "u8", "Float32": "f4", "Float64": "f8"}
# the faces of the solid cells, in VTK's vertex order, each listed so that it faces out of the cell
_CELL_FACES = {10: [(0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)],
               12: [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)],
               13: [(0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)],
               14: [(0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]}


def _cells_to_tris(cells: list, types) -> tuple[np.ndarray, int]:
    """Triangles from VTK cells: surface cells as they are, solid cells by their outer faces (faces used once)."""
    surf, solid_faces = [], []
    for c, t in zip(cells, types):
        t = int(t)
        if t == 5 or t == 7:                                   # triangle, polygon
            surf.append(list(c))
        elif t == 9:                                           # quad
            surf.append(list(c))
        elif t == 6:                                           # triangle strip
            surf += [[c[i], c[i + 1], c[i + 2]] if i % 2 == 0 else [c[i + 1], c[i], c[i + 2]] for i in range(len(c) - 2)]
        elif t == 8:                                           # pixel: a quad in another vertex order
            surf.append([c[0], c[1], c[3], c[2]])
        elif t in _CELL_FACES:
            solid_faces += [[c[i] for i in f] for f in _CELL_FACES[t]]
        elif t == 11:                                          # voxel
            q = [c[0], c[1], c[3], c[2], c[4], c[5], c[7], c[6]]
            solid_faces += [[q[i] for i in f] for f in _CELL_FACES[12]]
    nsolid = 0
    if solid_faces:
        key = {}
        for f in solid_faces:
            k = tuple(sorted(f))
            key[k] = None if k in key else f
        outer = [f for f in key.values() if f is not None]
        nsolid = len(outer)
        surf += outer
    return _fan(surf), nsolid


def _vtk_legacy(path: Path) -> dict:
    data = path.read_bytes()
    lines = data.split(b"\n", 3)
    if not lines[0].startswith(b"# vtk DataFile"):
        raise ValueError("Not a legacy VTK file.")
    binary = lines[2].strip().upper() == b"BINARY"
    rest = lines[3]
    pos = 0
    V, cells, types, nsolid = None, [], [], 0

    def word():
        nonlocal pos
        m = re.compile(rb"\s*(\S+)").match(rest, pos)
        if not m:
            return None
        pos = m.end()
        return m.group(1).decode("ascii", "replace")

    def numbers(n, dt):
        nonlocal pos
        if binary:
            if rest[pos:pos + 1] == b"\r":
                pos += 1
            if rest[pos:pos + 1] == b"\n":
                pos += 1
            d = np.dtype(">" + dt)
            arr = np.frombuffer(rest, dtype=d, count=n, offset=pos)
            pos += n * d.itemsize
            return arr
        out = []
        rx = re.compile(rb"\s*(\S+)")
        for _ in range(n):
            m = rx.match(rest, pos)
            out.append(m.group(1))
            pos = m.end()
        return np.asarray(out, dtype=np.float64 if dt[0] == "f" else np.int64)

    def legacy_cells(n, size):
        a = numbers(size, "i4").astype(np.int64)
        out, i = [], 0
        for _ in range(n):
            c = int(a[i])
            out.append(a[i + 1:i + 1 + c].tolist())
            i += 1 + c
        return out

    def new_cells(n_off):
        w = word()                                            # OFFSETS
        dt = _VTK_T[word().lower()]
        off = numbers(n_off, dt).astype(np.int64)
        word()                                                # CONNECTIVITY
        dt = _VTK_T[word().lower()]
        conn = numbers(int(off[-1]) if len(off) else 0, dt).astype(np.int64)
        del w
        return [conn[off[i]:off[i + 1]].tolist() for i in range(len(off) - 1)]

    dataset = None
    poly_cells = []
    while True:
        w = word()
        if w is None:
            break
        W = w.upper()
        if W == "DATASET":
            dataset = word().upper()
        elif W == "POINTS":
            n, dt = int(word()), _VTK_T[word().lower()]
            V = numbers(3 * n, dt).astype(np.float64).reshape(-1, 3)
        elif W in ("POLYGONS", "TRIANGLE_STRIPS", "VERTICES", "LINES"):
            a, b = int(word()), int(word())
            peek = rest[pos:pos + 40].split()
            cs = new_cells(a) if peek and peek[0].upper() == b"OFFSETS" else legacy_cells(a, b)
            if W == "POLYGONS":
                poly_cells += [(c, 7) for c in cs]
            elif W == "TRIANGLE_STRIPS":
                poly_cells += [(c, 6) for c in cs]
        elif W == "CELLS":
            a, b = int(word()), int(word())
            peek = rest[pos:pos + 40].split()
            cells = new_cells(a) if peek and peek[0].upper() == b"OFFSETS" else legacy_cells(a, b)
        elif W == "CELL_TYPES":
            types = numbers(int(word()), "i4").astype(np.int64).tolist()
        elif W in ("POINT_DATA", "CELL_DATA", "FIELD", "METADATA"):
            break                                             # attributes follow: the geometry is complete
    if V is None:
        raise ValueError("The VTK file has no POINTS.")
    if dataset not in ("POLYDATA", "UNSTRUCTURED_GRID"):
        raise ValueError(f"VTK {dataset or 'without a DATASET'} is not read; POLYDATA and UNSTRUCTURED_GRID are.")
    if poly_cells:
        cells, types = [c for c, _ in poly_cells], [t for _, t in poly_cells]
    F, nsolid = _cells_to_tris(cells, types)
    if not len(F):
        return _result("vtk", points=V, notes=["no surface cells: read as a point cloud"])
    return _result("vtk (" + ("binary" if binary else "ascii") + ")", parts=[(path.stem, _tris(V, F))],
                   notes=[f"{nsolid} outer faces of solid cells"] if nsolid else [])


def _vtx(path: Path) -> dict:
    data = path.read_bytes()
    app_at = data.find(b"<AppendedData")
    appended = b""
    xml = data
    if app_at >= 0:
        us = data.index(b"_", data.index(b">", app_at)) + 1
        end = data.rfind(b"</AppendedData>")
        appended = data[us:end]
        xml = data[:app_at] + b"<AppendedData/></VTKFile>"
    root = ElementTree.fromstring(xml)
    typ = root.get("type")
    hdr = np.dtype("<" + _VTX_T.get(root.get("header_type", "UInt32"), "u4"))
    if root.get("byte_order", "LittleEndian") != "LittleEndian":
        hdr = hdr.newbyteorder(">")
    zl = root.get("compressor") == "vtkZLibDataCompressor"
    app_enc = None
    for e in root.iter("AppendedData"):
        app_enc = e.get("encoding")
    if app_at >= 0:
        m = re.search(rb'encoding="(\w+)"', data[app_at:app_at + 200])
        app_enc = m.group(1).decode() if m else "raw"

    def decode_block(raw: bytes, from_b64: bool) -> bytes:
        def b64(s):
            return base64.b64decode(s)
        if not zl:
            if from_b64:
                b = b64(raw)
                n = int(np.frombuffer(b, dtype=hdr, count=1)[0])
                return b[hdr.itemsize:hdr.itemsize + n]
            n = int(np.frombuffer(raw, dtype=hdr, count=1)[0])
            return raw[hdr.itemsize:hdr.itemsize + n]
        if from_b64:                                        # the header is base64 on its own, then the blocks
            head = b64(raw[:((3 * hdr.itemsize + 2) // 3) * 4])
            nb = int(np.frombuffer(head, dtype=hdr, count=1)[0])
            hlen = (3 + nb) * hdr.itemsize
            hb = ((hlen + 2) // 3) * 4
            head = b64(raw[:hb])
            sizes = np.frombuffer(head, dtype=hdr, count=3 + nb)[3:]
            body = b64(raw[hb:])
        else:
            nb = int(np.frombuffer(raw, dtype=hdr, count=1)[0])
            sizes = np.frombuffer(raw, dtype=hdr, count=3 + nb, offset=0)[3:]
            body = raw[(3 + nb) * hdr.itemsize:]
        out, at = [], 0
        for s in sizes:
            out.append(zlib.decompress(body[at:at + int(s)]))
            at += int(s)
        return b"".join(out)

    def array(da) -> np.ndarray:
        dt = np.dtype("<" + _VTX_T[da.get("type")])
        fmt = da.get("format", "ascii")
        if fmt == "ascii":
            return np.asarray((da.text or "").split(), dtype=dt)
        if fmt == "binary":
            return np.frombuffer(decode_block((da.text or "").strip().encode(), True), dtype=dt)
        off = int(da.get("offset", 0))
        if app_enc == "base64":
            chunk = appended[off:].split(b"<", 1)[0].strip()
            return np.frombuffer(decode_block(chunk, True), dtype=dt)
        return np.frombuffer(decode_block(appended[off:], False), dtype=dt)

    piece = next(root.iter("Piece"), None)
    if piece is None:
        raise ValueError("The VTK XML file has no Piece.")
    pts = piece.find("Points/DataArray")
    if pts is None:
        raise ValueError("The VTK XML file has no Points.")
    V = array(pts).astype(np.float64).reshape(-1, 3)

    def named(group, name):
        g = piece.find(group)
        if g is None:
            return None
        for da in g.findall("DataArray"):
            if da.get("Name") == name:
                return array(da).astype(np.int64)
        return None

    cells, types = [], []
    if typ == "PolyData":
        for grp, t in (("Polys", 7), ("Strips", 6)):
            conn, off = named(grp, "connectivity"), named(grp, "offsets")
            if conn is not None and off is not None:
                start = np.concatenate([[0], off[:-1]])
                cells += [conn[a:b].tolist() for a, b in zip(start, off)]
                types += [t] * len(off)
    elif typ == "UnstructuredGrid":
        conn, off, ty = named("Cells", "connectivity"), named("Cells", "offsets"), named("Cells", "types")
        if conn is not None and off is not None and ty is not None:
            start = np.concatenate([[0], off[:-1]])
            cells = [conn[a:b].tolist() for a, b in zip(start, off)]
            types = ty.tolist()
    else:
        raise ValueError(f"VTK XML {typ} is not read; PolyData (.vtp) and UnstructuredGrid (.vtu) are.")
    F, nsolid = _cells_to_tris(cells, types)
    if not len(F):
        return _result(path.suffix.lstrip(".").lower(), points=V, notes=["no surface cells: read as a point cloud"])
    return _result(path.suffix.lstrip(".").lower(), parts=[(path.stem, _tris(V, F))],
                   notes=[f"{nsolid} outer faces of solid cells"] if nsolid else [])


# ---- point clouds ------------------------------------------------------------------------------------------------------

def _text_points(path: Path, skip_count_line: bool) -> dict:
    rows = []
    normals = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        first = True
        for ln in fh:
            s = ln.replace(",", " ").replace(";", " ").split()
            if not s or s[0].startswith(("#", "//")):
                continue
            if first and skip_count_line and len(s) == 1:
                first = False
                continue
            first = False
            try:
                vals = [float(x) for x in s[:6]]
            except ValueError:
                continue                                     # a header line of column names
            if len(vals) >= 3:
                rows.append(vals[:3])
                if len(s) == 6 and all(abs(v) <= 1.0001 for v in vals[3:6]) and not skip_count_line:
                    normals.append(vals[3:6])
            if len(rows) > MAX_POINTS_READ:
                raise ValueError(f"More than {MAX_POINTS_READ:,} points: thin the scan out first.")
    if not rows:
        raise ValueError("The file holds no x y z points.")
    P = np.asarray(rows, dtype=np.float64)
    N = np.asarray(normals, dtype=np.float64) if len(normals) == len(rows) else None
    return _result(path.suffix.lstrip(".").lower(), points=P, normals=N)


def _las(path: Path) -> dict:
    with open(path, "rb") as fh:
        h = fh.read(375)
        if h[:4] != b"LASF":
            raise ValueError("Not a LAS file.")
        major, minor = h[24], h[25]
        off_points = struct.unpack_from("<I", h, 96)[0]
        pfmt = h[104]
        if pfmt & 0x80 or pfmt & 0x40:
            raise ValueError("The LAS is compressed (LAZ), which Form Studio does not decompress. Save it as plain LAS, "
                             "E57, PLY or XYZ.")
        rec_len = struct.unpack_from("<H", h, 105)[0]
        n = struct.unpack_from("<I", h, 107)[0]
        if (major, minor) >= (1, 4) and n == 0:
            n = struct.unpack_from("<Q", h, 247)[0]
        sx, sy, sz, ox, oy, oz = struct.unpack_from("<6d", h, 131)
        if n > MAX_POINTS_READ:
            raise ValueError(f"{n:,} points: more than {MAX_POINTS_READ:,}. Thin the scan out first.")
        rec = np.memmap(path, dtype=np.dtype([("xyz", "<i4", 3), ("rest", "u1", rec_len - 12)]), mode="r",
                        offset=off_points, shape=(n,))
        X = rec["xyz"].astype(np.float64)
    P = X * np.array([sx, sy, sz]) + np.array([ox, oy, oz])
    P -= P.min(axis=0)                                       # survey coordinates are far from the origin
    return _result(f"las {major}.{minor} (point format {pfmt})", points=P * 1000.0, units="m",
                   source="the format's convention (LAS coordinates are metres in almost every scanner's export)",
                   notes=["moved to start at the origin (survey coordinates are kilometres from it)"])


# E57 (ASTM E2807): 1024-byte pages, each ending in a 4-byte checksum; an XML section describes the scans, and each
# scan's points are a CompressedVector of bytestreams. Read here: cartesianX/Y/Z as Float or ScaledInteger fields, in
# packets, every scan placed by its pose. Spherical-only scans and images are not read.

def _e57_logical(fh, phys: int, n: int, page: int) -> bytes:
    """n logical bytes starting at a physical offset, the page checksums left out."""
    out = bytearray()
    data_per = page - 4
    while len(out) < n:
        pg, at = divmod(phys, page)
        if at >= data_per:
            phys = (pg + 1) * page
            continue
        fh.seek(phys)
        take = min(data_per - at, n - len(out))
        b = fh.read(take)
        if not b:
            raise ValueError("The E57 file ends early.")
        out += b
        phys += take
    return bytes(out)


def _e57_phys(logical: int, page: int) -> int:
    return (logical // (page - 4)) * page + logical % (page - 4)


def _e57_log(phys: int, page: int) -> int:
    return (phys // page) * (page - 4) + phys % page


def _unpack_bits(raw: bytes, bits: int, count: int) -> np.ndarray:
    if bits == 0:
        return np.zeros(count, dtype=np.int64)
    b = np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder="little")[:count * bits]
    b = b.reshape(count, bits).astype(np.int64)
    return (b << np.arange(bits, dtype=np.int64)).sum(axis=1)


def _e57(path: Path) -> dict:
    with open(path, "rb") as fh:
        h = fh.read(48)
        if h[:8] != b"ASTM-E57":
            raise ValueError("Not an E57 file.")
        _maj, _min, _plen, xml_off, xml_len, page = struct.unpack_from("<IIQQQQ", h, 8)
        xml = _e57_logical(fh, xml_off, xml_len, page)
        root = ElementTree.fromstring(xml)
        ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
        data3d = root.find(ns + "data3D")
        if data3d is None or not len(data3d):
            raise ValueError("The E57 holds no 3D scans.")
        clouds = []
        for scan in data3d:
            pts = scan.find(ns + "points")
            if pts is None:
                continue
            proto = pts.find(ns + "prototype")
            count = int(pts.get("recordCount", 0))
            fields = []
            for f in proto:
                t = f.get("type")
                info = {"name": _local(f.tag), "type": t}
                if t == "Float":
                    info["bytes"] = 4 if f.get("precision") == "single" else 8
                elif t in ("ScaledInteger", "Integer"):
                    lo, hi = int(float(f.get("minimum", -2 ** 63))), int(float(f.get("maximum", 2 ** 63 - 1)))
                    info.update(minimum=lo, bits=int(np.ceil(np.log2(hi - lo + 1))) if hi > lo else 0,
                                scale=float(f.get("scale", 1.0)), offset=float(f.get("offset", 0.0)))
                fields.append(info)
            names = [f["name"] for f in fields]
            if not all(k in names for k in ("cartesianX", "cartesianY", "cartesianZ")):
                raise ValueError("A scan in the E57 has no cartesian points (spherical-only scans are not read).")
            # the CompressedVector's binary section: its header, then data packets
            sec = _e57_logical(fh, int(pts.get("fileOffset")), 32, page)
            _sid, _r, section_len, data_phys, _idx = struct.unpack_from("<B7sQQQ", sec, 0)
            streams = [bytearray() for _ in fields]
            pos = data_phys
            left = section_len - 32
            need = [count * f["bytes"] if f["type"] == "Float" else (count * f.get("bits", 0) + 7) // 8 for f in fields]
            while left > 0 and any(len(streams[i]) < need[i] for i in range(len(fields))):
                hdr = _e57_logical(fh, pos, 6, page)
                ptype, _flags, plen_m1, nstreams = struct.unpack("<BBHH", hdr)
                plen = plen_m1 + 1
                pkt = _e57_logical(fh, pos, plen, page)
                if ptype == 1:                                       # a data packet
                    lens = struct.unpack_from(f"<{nstreams}H", pkt, 6)
                    at = 6 + 2 * nstreams
                    for i, L in enumerate(lens):
                        if i < len(streams):
                            streams[i] += pkt[at:at + L]
                        at += L
                elif ptype not in (0, 2):
                    break
                pos = _e57_phys(_e57_log(pos, page) + plen, page)
                left -= plen
            cols = {}
            for i, f in enumerate(fields):
                raw = bytes(streams[i])
                if f["type"] == "Float":
                    cols[f["name"]] = np.frombuffer(raw, dtype="<f4" if f["bytes"] == 4 else "<f8", count=count).astype(np.float64)
                elif f["type"] in ("ScaledInteger", "Integer"):
                    v = _unpack_bits(raw, f["bits"], count) + f["minimum"]
                    cols[f["name"]] = v * f["scale"] + f["offset"] if f["type"] == "ScaledInteger" else v.astype(np.float64)
            P = np.stack([cols["cartesianX"], cols["cartesianY"], cols["cartesianZ"]], axis=1)
            if "cartesianInvalidState" in cols:
                P = P[cols["cartesianInvalidState"] == 0]
            pose = scan.find(ns + "pose")
            if pose is not None:
                r, t = pose.find(ns + "rotation"), pose.find(ns + "translation")
                if r is not None:
                    w, x, y, z = (float(r.findtext(ns + k) or 0) for k in ("w", "x", "y", "z"))   # empty: zero
                    P = P @ _quat([x, y, z, w]).T
                if t is not None:
                    P = P + np.array([float(t.findtext(ns + k) or 0) for k in ("x", "y", "z")])
            clouds.append(P)
    if not clouds:
        raise ValueError("The E57 holds no points.")
    P = np.concatenate(clouds)
    return _result("e57", points=P * 1000.0, units="m", source="the format (E57 is in metres)",
                   notes=[f"{len(clouds)} scans, placed by their poses"] if len(clouds) > 1 else [])


READERS = {".ply": _ply, ".off": _off, ".amf": _amf, ".glb": _gltf, ".gltf": _gltf, ".dae": _dae, ".x3d": _x3d,
           ".wrl": _wrl, ".vrml": _wrl, ".vtk": _vtk_legacy, ".vtp": _vtx, ".vtu": _vtx,
           ".xyz": lambda p: _text_points(p, False), ".pts": lambda p: _text_points(p, True), ".las": _las,
           ".e57": _e57}


def read(path, ext: str | None = None) -> dict:
    """Read one file of a format in READERS. Raises ValueError with what is wrong."""
    p = Path(path)
    e = (ext or p.suffix).lower()
    if e not in READERS:
        from .formats import unsupported
        raise ValueError(unsupported(p))
    try:
        out = READERS[e](p)
    except (KeyError, IndexError, struct.error, ElementTree.ParseError, zlib.error, zipfile.BadZipFile,
            UnicodeDecodeError, TypeError) as err:
        raise ValueError(f"{p.name} could not be read as {e[1:].upper()}: {type(err).__name__}: {err}") from err
    for _n, T in out["parts"]:
        if not np.all(np.isfinite(T)):
            raise ValueError("The mesh has coordinates that are not finite numbers.")
    if out["points"] is not None:
        P = np.asarray(out["points"], dtype=np.float64)
        keep = np.all(np.isfinite(P), axis=1)
        out["points"] = P[keep]
        if out["normals"] is not None:
            out["normals"] = np.asarray(out["normals"], dtype=np.float64)[keep]
        if not len(out["points"]):
            raise ValueError("The file holds no points.")
    return out
