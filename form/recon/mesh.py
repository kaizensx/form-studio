"""Reading triangle meshes (STL, OBJ, 3MF with named parts, and every other format form/formats.py lists: PLY, OFF,
AMF, glTF, Collada, X3D, VRML, VTK and point clouds, through form/meshformats.py), welding them and reporting what is wrong with them. numpy and scipy only.

Nothing here repairs a mesh behind your back. `weld` merges vertices closer than a tolerance and drops triangles that
collapse to a line or a point; both are counted in the report. `topology` lists open boundaries, non-manifold edges
and edges whose two triangles disagree about which side is outside. `fill_holes` closes open boundaries only when it is
called, and returns what it filled so the caller can say so.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import numpy as np

from ..formats import extensions as _extensions

FORMATS = _extensions("mesh", "pointcloud")      # every format read_parts reads (form/formats.py)


@dataclass
class Mesh:
    V: np.ndarray                      # (n, 3) float64 vertices, mm
    F: np.ndarray                      # (m, 3) int64 triangles, counter-clockwise seen from outside
    info: dict = field(default_factory=dict)

    @property
    def triangles(self) -> np.ndarray:
        return self.V[self.F]


# ---- readers ---------------------------------------------------------------------------------------------------------
#
# STL is read without holding the file twice: a binary STL is mapped and its vertices copied once. A 3MF is read with
# lib3mf (the 3MF Consortium's reader, shipped with the app), which follows the production extension's p:path: the
# layout Bambu Studio, Orca Slicer and MakerWorld write, where 3D/3dmodel.model only places components whose meshes
# live in 3D/Objects/object_N.model. Every build item is one part with its name, world position, plate and colour.
# When lib3mf is missing or refuses a file, a zip/XML reader that also follows p:path takes over.

_STL_REC = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])


@dataclass
class Part:
    """One object of a 3MF (or the whole of an STL/OBJ): its triangles in world millimetres and what it is."""
    name: str
    T: np.ndarray                      # (m, 3, 3) float64, world coordinates, mm
    info: dict = field(default_factory=dict)   # object_id, plate, colour, extruder, transform, components

    def summary(self) -> dict:
        P = self.T.reshape(-1, 3)
        lo, hi = (P.min(axis=0), P.max(axis=0)) if len(P) else (np.zeros(3), np.zeros(3))
        return {"name": self.name, "triangles": int(len(self.T)), "bbox": [lo.round(4).tolist(), hi.round(4).tolist()],
                **{k: v for k, v in self.info.items() if k != "transform"}}


def stl_triangle_count(path: Path) -> int | None:
    """The triangle count of a binary STL from its header, without reading the rest (None for ASCII or a damaged file)."""
    p = Path(path)
    size = p.stat().st_size
    if size < 84:
        return None
    with open(p, "rb") as f:
        f.seek(80)
        n = struct.unpack("<I", f.read(4))[0]
    return n if 84 + 50 * n == size else None


def stl_records(path: Path) -> np.ndarray | None:
    """A binary STL's records, memory-mapped (read-only, nothing copied yet). None for an ASCII STL."""
    n = stl_triangle_count(path)
    if n is None:
        return None
    if n == 0:
        return np.zeros(0, dtype=_STL_REC)
    return np.memmap(path, dtype=_STL_REC, mode="r", offset=84, shape=(n,))


def _stl(path: Path) -> tuple[np.ndarray, str]:
    rec = stl_records(path)
    if rec is not None:
        return np.asarray(rec["v"], dtype=np.float64), "stl (binary)"
    text = Path(path).read_bytes().decode("utf-8", "replace")
    if not text.lstrip().lower().startswith("solid"):
        raise ValueError("Not a readable STL: neither a binary STL of the right length nor ASCII starting with 'solid'.")
    nums = re.findall(r"^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)", text, flags=re.MULTILINE | re.IGNORECASE)
    if not nums or len(nums) % 3:
        raise ValueError("The ASCII STL has no complete facets.")
    return np.asarray(nums, dtype=np.float64).reshape(-1, 3, 3), "stl (ascii)"


def _obj(data: bytes, default: str = "part") -> list[Part]:
    """Triangles of an OBJ, one part per `o` object (or per `g` group when there are no objects)."""
    verts, groups, order = [], {}, []
    has_o = re.search(rb"^o\s", data, flags=re.MULTILINE) is not None
    cur = default
    for ln in data.decode("utf-8", "replace").splitlines():
        s = ln.split()
        if not s:
            continue
        if s[0] == "v" and len(s) >= 4:
            verts.append((float(s[1]), float(s[2]), float(s[3])))
        elif s[0] == ("o" if has_o else "g") and len(s) >= 2:
            cur = " ".join(s[1:])[:120]
        elif s[0] == "f" and len(s) >= 4:
            idx = []
            for tok in s[1:]:
                i = int(tok.split("/")[0])
                idx.append(i - 1 if i > 0 else len(verts) + i)
            if cur not in groups:
                groups[cur] = []
                order.append(cur)
            for k in range(1, len(idx) - 1):           # fan-triangulate polygons (convex faces, as OBJ exporters write)
                groups[cur].append((idx[0], idx[k], idx[k + 1]))
    if not any(groups.values()):
        raise ValueError("The OBJ has no faces.")
    V = np.asarray(verts, dtype=np.float64)
    parts = []
    for name in order:
        F = np.asarray(groups[name], dtype=np.int64)
        if F.min() < 0 or F.max() >= len(V):
            raise ValueError("The OBJ refers to vertices it does not define.")
        parts.append(Part(name, V[F], {}))
    return parts


_UNIT_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}
_PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def _xf(s: str | None) -> np.ndarray:
    M = np.eye(4)
    if s:
        v = [float(x) for x in s.split()]
        if len(v) == 12:
            M[:3, :3] = np.array(v[:9]).reshape(3, 3)          # rows m00 m01 m02 / m10 ... (3MF uses row vectors)
            M[3, :3] = v[9:]
    return M


def _apply(T: np.ndarray, M: np.ndarray) -> np.ndarray:
    P = T.reshape(-1, 3)
    return (P @ M[:3, :3] + M[3, :3]).reshape(-1, 3, 3)


def _bambu_settings(z: zipfile.ZipFile) -> dict:
    """What Bambu Studio and Orca keep beside the geometry: object and part names, part kinds (a modifier is not
    geometry), plates and filament colours. Empty for other writers."""
    out = {"objects": {}, "plates": {}, "colours": []}
    names = set(z.namelist())
    if "Metadata/model_settings.config" in names:
        try:
            root = ElementTree.fromstring(z.read("Metadata/model_settings.config"))
        except ElementTree.ParseError:
            root = None
        if root is not None:
            for o in root.iter("object"):
                meta = {m.get("key"): m.get("value") for m in o.findall("metadata")}
                parts = {}
                for p in o.findall("part"):
                    pm = {m.get("key"): m.get("value") for m in p.findall("metadata")}
                    parts[p.get("id")] = {"name": pm.get("name"), "subtype": p.get("subtype") or "normal_part"}
                out["objects"][o.get("id")] = {"name": meta.get("name"), "extruder": meta.get("extruder"), "parts": parts}
            for pl in root.iter("plate"):
                pm = {m.get("key"): m.get("value") for m in pl.findall("metadata")}
                for inst in pl.iter("model_instance"):
                    im = {m.get("key"): m.get("value") for m in inst.findall("metadata")}
                    if im.get("object_id"):
                        out["plates"].setdefault(im["object_id"], pm.get("plater_id"))
    if "Metadata/project_settings.config" in names:
        try:
            js = json.loads(z.read("Metadata/project_settings.config"))
            out["colours"] = [str(c) for c in js.get("filament_colour") or []]
        except (ValueError, AttributeError):
            pass
    return out


def _decorate(parts: list[Part], bambu: dict) -> None:
    """Names, plates and colours from Bambu/Orca metadata, where the model file itself has none."""
    for p in parts:
        oid = str(p.info.get("object_id"))
        o = bambu["objects"].get(oid) or {}
        if o.get("name") and (not p.name or p.name.startswith("Object ")):
            p.name = o["name"]
        try:
            if bambu["plates"].get(oid):
                p.info["plate"] = int(bambu["plates"][oid])
            if o.get("extruder"):
                ex = int(o["extruder"])
                p.info["extruder"] = ex
                if not p.info.get("colour") and 0 < ex <= len(bambu["colours"]):
                    p.info["colour"] = bambu["colours"][ex - 1]
        except ValueError:
            pass


def _skip_part(bambu: dict, root_id, sub_id) -> bool:
    """A Bambu/Orca modifier, negative volume or support blocker is not part of the object's shape."""
    sub = ((bambu["objects"].get(str(root_id)) or {}).get("parts") or {}).get(str(sub_id))
    return bool(sub) and sub["subtype"] != "normal_part"


def _3mf_lib3mf(path: Path, bambu: dict) -> tuple[list[Part], str]:
    import ctypes

    import lib3mf
    w = lib3mf.get_wrapper()
    model = w.CreateModel()
    reader = model.QueryReader("3mf")
    try:
        reader.SetStrictModeActive(False)
    except Exception:
        pass
    reader.ReadFromFile(str(path))
    unit = {lib3mf.ModelUnit.MicroMeter: "micron", lib3mf.ModelUnit.MilliMeter: "millimeter",
            lib3mf.ModelUnit.CentiMeter: "centimeter", lib3mf.ModelUnit.Inch: "inch", lib3mf.ModelUnit.Foot: "foot",
            lib3mf.ModelUnit.Meter: "meter"}.get(model.GetUnit(), "millimeter")
    lib = w.lib
    cache: dict[int, np.ndarray] = {}

    def xf(t) -> np.ndarray:
        M = np.eye(4)
        F = np.array([[t.Fields[r][c] for c in range(3)] for r in range(4)], dtype=np.float64)
        M[:3, :3], M[3, :3] = F[:3], F[3]
        return M

    def mesh_tris(obj) -> np.ndarray:
        uid = obj.GetUniqueResourceID()
        if uid not in cache:                          # whole arrays through the C API: no Python object per vertex
            m = model.GetMeshObjectByID(uid)
            nv, nt = m.GetVertexCount(), m.GetTriangleCount()
            need = ctypes.c_uint64(0)
            vb = (lib3mf.Position * nv)()
            w.checkError(m, lib.lib3mf_meshobject_getvertices(m._handle, ctypes.c_uint64(nv), need, vb))
            tb = (lib3mf.Triangle * nt)()
            w.checkError(m, lib.lib3mf_meshobject_gettriangleindices(m._handle, ctypes.c_uint64(nt), need, tb))
            V = np.frombuffer(vb, dtype=np.float32).reshape(-1, 3).astype(np.float64)
            F = np.frombuffer(tb, dtype=np.uint32).reshape(-1, 3).astype(np.int64)
            if len(F) and F.max() >= len(V):
                raise ValueError("A 3MF mesh refers to vertices it does not define.")
            cache[uid] = V[F] if len(F) else np.zeros((0, 3, 3))
        return cache[uid]

    def colour(obj) -> str | None:
        try:
            m = model.GetMeshObjectByID(obj.GetUniqueResourceID())
            rid, pid, has = m.GetObjectLevelProperty()
            if not has:
                return None
            kind = model.GetPropertyTypeByID(rid)
            if kind == lib3mf.PropertyType.BaseMaterial:
                c = model.GetBaseMaterialGroupByID(rid).GetDisplayColor(pid)
            elif kind == lib3mf.PropertyType.Colors:
                c = model.GetColorGroupByID(rid).GetColor(pid)
            else:
                return None
            return f"#{c.Red:02X}{c.Green:02X}{c.Blue:02X}"
        except Exception:
            return None

    def expand(obj, M, root_id, depth, out, comps):
        if depth > 16:
            return
        if obj.IsMeshObject():
            T = mesh_tris(obj)
            if len(T):
                out.append(_apply(T, M))
                comps.append(obj.GetName() or f"mesh {obj.GetModelResourceID()}")
            return
        if obj.IsComponentsObject():
            co = model.GetComponentsObjectByID(obj.GetUniqueResourceID())
            for i in range(co.GetComponentCount()):
                c = co.GetComponent(i)
                sub = c.GetObjectResource()
                if depth == 0 and _skip_part(bambu, root_id, sub.GetModelResourceID()):
                    continue
                Mc = xf(c.GetTransform()) if c.HasTransform() else np.eye(4)
                expand(sub, Mc @ M, root_id, depth + 1, out, comps)

    parts = []
    items = model.GetBuildItems()
    while items.MoveNext():
        it = items.GetCurrent()
        obj = it.GetObjectResource()
        M = xf(it.GetObjectTransform()) if it.HasObjectTransform() else np.eye(4)
        rid = obj.GetModelResourceID()
        out, comps = [], []
        expand(obj, M, rid, 0, out, comps)
        if not out:
            continue
        info = {"object_id": rid, "components": len(comps), "transform": M[:, :3].round(6).tolist()}
        col = colour(obj) if obj.IsMeshObject() else None
        if col:
            info["colour"] = col
        parts.append(Part(obj.GetName() or f"Object {rid}", np.concatenate(out), info))
    if not parts:                                     # no build section: every mesh object, where it is
        objs = model.GetMeshObjects()
        while objs.MoveNext():
            o = objs.GetCurrent()
            T = mesh_tris(o)
            if len(T):
                parts.append(Part(o.GetName() or f"Object {o.GetModelResourceID()}", T, {"object_id": o.GetModelResourceID()}))
    return parts, unit


def _3mf_xml(z: zipfile.ZipFile, bambu: dict) -> tuple[list[Part], str]:
    """The fallback reader: plain zip and XML, following the production extension's p:path between model files."""
    models = [n for n in z.namelist() if n.lower().endswith(".model")]
    if not models:
        raise ValueError("The 3MF has no 3D model part.")
    root_name = next((n for n in models if n.lower() == "3d/3dmodel.model"), models[0])
    files: dict[str, tuple] = {}

    def load(name: str):
        key = name.lstrip("/")
        if key not in files:
            try:
                root = ElementTree.fromstring(z.read(key))
            except KeyError:
                raise ValueError(f"The 3MF refers to {name}, which it does not contain.")
            ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
            files[key] = (root, ns, {o.get("id"): o for o in root.iter(f"{ns}object")}, {})
        return files[key]

    def mesh(fname, oid):
        root, ns, objects, meshes = load(fname)
        if oid not in meshes:
            m = objects[oid].find(f"{ns}mesh")
            if m is None:
                meshes[oid] = None
            else:
                V = np.array([[float(v.get(a)) for a in "xyz"] for v in m.iter(f"{ns}vertex")], dtype=np.float64)
                F = np.array([[int(t.get(a)) for a in ("v1", "v2", "v3")] for t in m.iter(f"{ns}triangle")], dtype=np.int64)
                meshes[oid] = V[F] if len(F) else None
        return meshes[oid]

    def expand(fname, oid, M, root_id, depth, out):
        root, ns, objects, _ = load(fname)
        if depth > 16 or oid not in objects:
            return
        T = mesh(fname, oid)
        if T is not None:
            out.append(_apply(T, M))
        comps = objects[oid].find(f"{ns}components")
        if comps is not None:
            for c in comps.iter(f"{ns}component"):
                sub = c.get("objectid")
                if depth == 0 and _skip_part(bambu, root_id, sub):
                    continue
                path = c.get(f"{{{_PROD_NS}}}path") or c.get("path")
                expand(path.lstrip("/") if path else fname, sub, _xf(c.get("transform")) @ M, root_id, depth + 1, out)

    root, ns, objects, _ = load(root_name)
    unit = root.get("unit", "millimeter")
    parts = []
    build = root.find(f"{ns}build")
    items = list(build.iter(f"{ns}item")) if build is not None else []
    for it in items:
        oid = it.get("objectid")
        out = []
        expand(root_name, oid, _xf(it.get("transform")), oid, 0, out)
        if out:
            o = objects.get(oid)
            parts.append(Part((o.get("name") if o is not None else None) or f"Object {oid}", np.concatenate(out),
                              {"object_id": int(oid) if str(oid).isdigit() else oid}))
    if not items:
        for oid in objects:
            T = mesh(root_name, oid)
            if T is not None:
                parts.append(Part(objects[oid].get("name") or f"Object {oid}", T, {"object_id": oid}))
    return parts, unit


def _3mf(path: Path) -> tuple[list[Part], str]:
    with zipfile.ZipFile(path) as z:
        bambu = _bambu_settings(z)
        reader = "lib3mf"
        try:
            parts, unit = _3mf_lib3mf(path, bambu)
        except Exception:                                # not installed, or a file it will not read: the plain reader
            parts, reader = None, "xml"
        if parts is None:
            parts, unit = _3mf_xml(z, bambu)
    if not parts:
        raise ValueError("The 3MF holds no triangles.")
    k = _UNIT_MM.get(unit, 1.0)
    for p in parts:
        if k != 1.0:
            p.T = p.T * k
        p.info["reader"] = reader
    _decorate(parts, bambu)
    return parts, f"3mf ({unit})"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_parts(path: Path, fmt: str | None = None) -> tuple[list[Part], dict]:
    """(parts, info) from an STL, OBJ or 3MF. A 3MF gives one part per build item (named, placed, with its plate and
    colour); an OBJ one per named object; an STL one part. Units: mm."""
    p = Path(path)
    ext = (fmt or p.suffix).lower()                  # fmt: for a file whose name is not its format (a .tmp copy)
    if ext == ".stl":
        T, kind = _stl(p)
        parts = [Part(p.stem, T, {})]
    elif ext == ".obj":
        parts, kind = _obj(p.read_bytes(), p.stem), "obj"
    elif ext == ".3mf":
        parts, kind = _3mf(p)
    elif ext in FORMATS:
        return _other(p, ext)
    else:
        from ..formats import unsupported
        raise ValueError(unsupported(p))
    for part in parts:
        if not np.all(np.isfinite(part.T)):
            raise ValueError("The mesh has coordinates that are not finite numbers.")
    info = {"file": p.name, "format": kind, "bytes": p.stat().st_size, "sha256": sha256_file(p),
            "triangles_in": int(sum(len(x.T) for x in parts)),
            "units": "mm" + ("" if kind.startswith("3mf") else " (assumed)")}
    if ext == ".3mf" or len(parts) > 1:
        info["parts"] = [x.summary() for x in parts]
    return parts, info


def _other(p: Path, ext: str) -> tuple[list[Part], dict]:
    """A format of form/meshformats.py; a point cloud becomes a surface first (form/pointcloud.py)."""
    from .. import meshformats, pointcloud
    r = meshformats.read(p, ext)
    sha = sha256_file(p)
    info = {"file": p.name, "format": r["format"], "bytes": p.stat().st_size, "sha256": sha}
    u = r["units"]
    info["units"] = u["units"] + ("" if not u["source"].startswith("assumed") else " (assumed)")
    info["units_source"] = u["source"]
    if r["axes"]:
        info["axes"] = r["axes"]
    if r["notes"]:
        info["notes"] = r["notes"]
    if r["points"] is not None:
        V, F, rep = pointcloud.surface_cached(r["points"], r["normals"], sha)
        parts = [Part(p.stem, V[F], {})]
        info["pointcloud"] = rep
    else:
        parts = [Part(name, T, {}) for name, T in r["parts"] if len(T)]
        if not parts:
            raise ValueError("The file holds no triangles.")
    info["triangles_in"] = int(sum(len(x.T) for x in parts))
    if len(parts) > 1:
        info["parts"] = [x.summary() for x in parts]
    return parts, info


def read_triangles(path: Path, fmt: str | None = None) -> tuple[np.ndarray, dict]:
    """(triangles (m, 3, 3) float64, info) from an STL (binary or ASCII), OBJ or 3MF file: every part, in world
    coordinates. Units: mm. info["parts"] names the parts of a 3MF or a multi-object OBJ (read_parts keeps them apart)."""
    parts, info = read_parts(path, fmt)
    T = parts[0].T if len(parts) == 1 else np.concatenate([x.T for x in parts])
    if not len(T):
        raise ValueError("The mesh holds no triangles.")
    return T, info


# ---- weld and topology -----------------------------------------------------------------------------------------------

def weld(T: np.ndarray, tol: float = 1e-6) -> tuple[np.ndarray, np.ndarray, dict]:
    """Share vertices closer than tol (mm) and drop triangles that collapse. Returns (V, F, counts)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    flat = T.reshape(-1, 3)
    exact, inv = np.unique(flat, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    pairs = cKDTree(exact).query_pairs(tol, output_type="ndarray") if tol > 0 and len(exact) > 1 else np.zeros((0, 2), int)
    if len(pairs):
        g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(exact), len(exact)))
        k, lab = connected_components(g, directed=False)
        V = np.zeros((k, 3))
        np.add.at(V, lab, exact)
        V /= np.bincount(lab, minlength=k)[:, None]
        idx = lab[inv]
    else:
        V, idx = exact, inv
    F = idx.reshape(-1, 3).astype(np.int64)
    collapsed = (F[:, 0] == F[:, 1]) | (F[:, 1] == F[:, 2]) | (F[:, 0] == F[:, 2])
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    area2 = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    sliver = ~collapsed & (area2 <= 1e-14 * max(1.0, float(np.ptp(V, axis=0).max()) ** 2))
    keep = ~(collapsed | sliver)
    F = F[keep]
    srt = np.sort(F, axis=1)
    _, first, cnt = np.unique(srt, axis=0, return_index=True, return_counts=True)
    dup = int((cnt > 1).sum())
    F = F[np.sort(first)]
    used = np.unique(F)
    remap = -np.ones(len(V), dtype=np.int64)
    remap[used] = np.arange(len(used))
    V, F = V[used], remap[F]
    return V, F, {"weld_tolerance_mm": tol, "vertices": int(len(V)), "triangles": int(len(F)),
                  "distinct_input_vertices": int(len(exact)), "merged_near_vertices": int(len(exact) - len(np.unique(idx))),
                  "dropped_collapsed": int(collapsed.sum()), "dropped_zero_area": int(sliver.sum()), "dropped_duplicate": dup}


def edges(F: np.ndarray):
    """Undirected edges: (E (k, 2) sorted vertex pairs, tri_of (3m,), edge_of (3m,) index into E, directed (3m, 2))."""
    he = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    tri = np.tile(np.arange(len(F)), 3)
    key = np.sort(he, axis=1)
    E, inv = np.unique(key, axis=0, return_inverse=True)
    return E, tri, inv.reshape(-1), he


def topology(V: np.ndarray, F: np.ndarray) -> dict:
    """What the mesh is: open boundary loops, non-manifold edges, flipped neighbours, separate pieces, volume."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    E, tri, eo, he = edges(F)
    cnt = np.bincount(eo, minlength=len(E))
    boundary = np.flatnonzero(cnt == 1)
    nonman = np.flatnonzero(cnt > 2)
    # an edge used twice in the same direction: the two triangles disagree about the outside
    fwd = he[:, 0] < he[:, 1]
    same = np.zeros(len(E), dtype=np.int64)
    np.add.at(same, eo, np.where(fwd, 1, -1))
    flipped = int(np.sum((cnt == 2) & (np.abs(same) == 2)))
    two = np.flatnonzero(cnt == 2)
    # pieces: triangles connected through shared edges
    order = np.argsort(eo, kind="stable")
    eo_s, tri_s = eo[order], tri[order]
    nb = eo_s[1:] == eo_s[:-1]                       # consecutive entries of one edge: neighbouring triangles
    r, c = tri_s[:-1][nb], tri_s[1:][nb]
    g = coo_matrix((np.ones(len(r)), (r, c)), shape=(len(F), len(F)))
    pieces, lab = connected_components(g, directed=False)
    loops = boundary_loops(E[boundary], he, eo, cnt) if len(boundary) else []
    a, b, c3 = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    vol = float(np.einsum("ij,ij->i", a, np.cross(b, c3)).sum() / 6.0)
    area = float(np.linalg.norm(np.cross(b - a, c3 - a), axis=1).sum() / 2)
    lo, hi = V.min(axis=0), V.max(axis=0)
    return {"closed": bool(len(boundary) == 0 and len(nonman) == 0), "boundary_edges": int(len(boundary)),
            "boundary_loops": len(loops), "non_manifold_edges": int(len(nonman)), "flipped_edges": flipped,
            "pieces": int(pieces), "manifold_edges": int(len(two)), "volume_mm3": vol, "area_mm2": area,
            "bbox": [lo.tolist(), hi.tolist()], "_loops": loops, "_piece_of": lab,
            "_non_manifold_at": V[E[nonman[:20]]].mean(axis=1).tolist() if len(nonman) else []}


def boundary_loops(bE: np.ndarray, he: np.ndarray, eo: np.ndarray, cnt: np.ndarray) -> list[list[int]]:
    """Open boundaries as vertex loops, following each boundary half-edge in its triangle's direction.

    Every boundary half-edge is used once. Two holes that touch at one vertex (a "figure 8") are two loops: a walk that
    comes back to a vertex already on it closes the loop there and goes on from that vertex."""
    out_of: dict[int, list[int]] = {}
    for i in np.flatnonzero(cnt[eo] == 1):
        out_of.setdefault(int(he[i, 0]), []).append(int(he[i, 1]))
    loops = []
    for start in list(out_of):
        while out_of.get(start):
            path, pos = [start], {start: 0}
            v = start
            while out_of.get(v):
                w = out_of[v].pop()
                if w in pos:                            # back on the walk: what lies between is one loop
                    i = pos[w]
                    if len(path) - i >= 3:
                        loops.append(path[i:])
                    for u in path[i + 1:]:
                        del pos[u]
                    del path[i + 1:]
                    v = w
                    if w == start and not out_of.get(w):
                        break
                    continue
                pos[w] = len(path)
                path.append(w)
                v = w
    return loops


HOLE_SPAN_FRAC = 0.5       # a hole (of more than three edges) wider than this share of the bounding-box diagonal is
                           # large: not filled
HOLE_AREA_FRAC = 0.02      # nor one whose fill would be more than this share of the mesh's surface (a missing single
                           # triangle is always put back: it is not a guess)
HOLE_DP_MAX = 60           # loops up to this many edges get the best triangulation (dynamic programming)
FLAT_FRAC = 1e-3           # a loop within this share of its span of its best-fit plane is planar


def _fan(V, loop, ci):
    k = len(loop)
    return [[loop[(i + 1) % k], loop[i], ci] for i in range(k)]


def _tri_area_normal(a, b, c):
    n = np.cross(b - a, c - a)
    ln = float(np.linalg.norm(n))
    return 0.5 * ln, (n / ln if ln > 1e-300 else np.zeros(3))


def _best_triangulation(V, R, nbr):
    """Triangles over the polygon R (vertex ids, already in the fill's orientation) that make the least area, each
    weighted by how far it bends from the existing triangles across its edges on the hole's border (so a hole across
    a crease is filled with the crease, not cut across it). nbr[(a, b)] is the normal of the triangle on the other side
    of the border edge a -> b. Dynamic programming over the polygon's diagonals, O(k^3): the classic hole-filling
    triangulation (Barequet and Sharir 1995, Liepa 2003), written here from the description."""
    m = len(R)
    P = V[R]
    INF = float("inf")
    W = [[0.0] * m for _ in range(m)]
    J = [[-1] * m for _ in range(m)]
    for span in range(2, m):
        for i in range(0, m - span):
            k = i + span
            best, bj = INF, -1
            for j in range(i + 1, k):
                ar, n = _tri_area_normal(P[i], P[j], P[k])
                if ar <= 1e-18:
                    c = 1e6 * (1.0 + float(np.linalg.norm(P[k] - P[i])))  # degenerate: only when nothing else does
                else:
                    bend = 0.0
                    for x, y in ((i, j), (j, k), (k, i)):
                        if (y - x) % m == 1:                # an edge on the hole's border
                            nb = nbr.get((R[x], R[y]))
                            if nb is not None:
                                bend = max(bend, 1.0 - float(n @ nb))
                    c = ar * (1.0 + 4.0 * bend)
                tot = W[i][j] + W[j][k] + c
                if tot < best:
                    best, bj = tot, j
            W[i][k], J[i][k] = best, bj
    tris, stack = [], [(0, m - 1)]
    while stack:
        i, k = stack.pop()
        if k - i < 2:
            continue
        j = J[i][k]
        tris.append([R[i], R[j], R[k]])
        stack += [(i, j), (j, k)]
    return tris


def _ear_clip(Q, R):
    """Ear clipping of the simple 2D polygon Q (counter-clockwise) with vertex ids R. None when it is not simple."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    idx = list(range(len(Q)))
    tris, guard = [], 0
    while len(idx) > 3 and guard < 4 * len(Q) ** 2:
        guard += 1
        n = len(idx)
        for t in range(n):
            i0, i1, i2 = idx[(t - 1) % n], idx[t], idx[(t + 1) % n]
            a, b, c = Q[i0], Q[i1], Q[i2]
            if cross(a, b, c) <= 1e-15:
                continue
            if any(cross(a, b, Q[p]) >= 0 and cross(b, c, Q[p]) >= 0 and cross(c, a, Q[p]) >= 0
                   for p in idx if p not in (i0, i1, i2)):
                continue
            tris.append([R[i0], R[i1], R[i2]])
            idx.pop(t)
            break
        else:
            return None
    if len(idx) == 3:
        tris.append([R[idx[0]], R[idx[1]], R[idx[2]]])
    return tris


def _simple(Q) -> bool:
    """No two non-neighbouring edges of the closed 2D polygon Q cross."""
    k = len(Q)
    A, B = Q, np.roll(Q, -1, axis=0)
    for i in range(k):
        for j in range(i + 2, k):
            if i == 0 and j == k - 1:
                continue
            p, r, q, s = A[i], B[i] - A[i], A[j], B[j] - A[j]
            den = r[0] * s[1] - r[1] * s[0]
            if abs(den) < 1e-18:
                continue
            t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / den
            u = ((q[0] - p[0]) * r[1] - (q[1] - p[1]) * r[0]) / den
            if 0 < t < 1 and 0 < u < 1:
                return False
    return True


def fill_holes(V: np.ndarray, F: np.ndarray, loops: list[list[int]],
               max_span: float | None = None, max_area: float | None = None) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Close each open boundary loop. Returns the new mesh and one record per hole (filled or left open).

    A loop of three edges gets the one triangle it is missing. Up to HOLE_DP_MAX edges, the triangulation with the least
    area and the least bend away from its neighbours (so a hole across a crease keeps the crease); a larger loop that is
    planar or near-planar is ear-clipped in its plane; anything else gets a fan around its centroid. A hole wider than
    `max_span` mm or whose fill would cover more than `max_area` mm2 (three edges: never) is large: it is left open and listed with
    "filled": False, so the caller can refuse the mesh and say why."""
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    he = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    tri = np.tile(np.arange(len(F)), 3)
    N, _ = tri_normals(V, F)
    border = {int(v) for loop in loops for v in loop}
    nbr = {}                                            # fill edge b -> a: normal of the triangle that has a -> b
    keep = np.isin(he[:, 0], list(border)) & np.isin(he[:, 1], list(border))
    for (a, b), t in zip(he[keep].tolist(), tri[keep].tolist()):
        nbr[(b, a)] = N[t]
    existing = {tuple(sorted(e)) for e in he.tolist()}
    V2, newF, rec = [V], [F], []
    n = len(V)
    for loop in loops:
        P = V[loop]
        c = P.mean(axis=0)
        k = len(loop)
        span = float(2 * np.linalg.norm(P - c, axis=1).max())
        _, _, vt = np.linalg.svd(P - c, full_matrices=False)
        nrm = vt[-1]
        flat = float(np.abs((P - c) @ nrm).max())
        planar = flat <= FLAT_FRAC * max(span, 1e-9)
        R = list(loop[::-1])                            # the fill runs against the border's half-edges
        tris, how = None, None
        if k == 3:
            tris, how = [R], "the one missing triangle"
        elif k <= HOLE_DP_MAX:
            tris, how = _best_triangulation(V, R, nbr), "least-area, least-bend triangulation"
        else:
            u = vt[0]
            w = np.cross(nrm, u)
            Q = np.c_[(V[R] - c) @ u, (V[R] - c) @ w]
            if np.sum(Q[:, 0] * np.roll(Q[:, 1], -1) - np.roll(Q[:, 0], -1) * Q[:, 1]) < 0:
                Q[:, 1] *= -1                           # mirrored to counter-clockwise: triangles keep R's order
            if flat <= 0.05 * span and _simple(Q):
                tris = _ear_clip(Q, R)
                how = "planar ear clipping" if planar else "near-planar ear clipping"
        if tris is not None and k > 3:                  # a diagonal the mesh already has would make a non-manifold edge
            diag = {tuple(sorted(e)) for t in tris for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))}
            ring = {tuple(sorted((loop[i], loop[(i + 1) % k]))) for i in range(k)}
            if (diag - ring) & existing:
                tris = None
        area = 0.0
        if tris is not None:
            T = np.asarray(tris, dtype=np.int64)
            area = float(0.5 * np.linalg.norm(np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]]), axis=1).sum())
        else:
            area = float(sum(_tri_area_normal(P[i], P[(i + 1) % k], c)[0] for i in range(k)))
        r = {"repair": "filled hole", "edges": k, "span_mm": round(span, 4), "at": [round(float(x), 4) for x in c],
             "area_mm2": round(area, 4), "planar": bool(planar), "flatness_mm": round(flat, 6)}
        if k > 3 and ((max_span is not None and span > max_span) or (max_area is not None and area > max_area)):
            rec.append({**r, "repair": "hole left open (large)", "filled": False})
            continue
        if tris is None:
            tris, how = _fan(V, loop, n), "fan around its centroid"
            V2.append(c[None])
            n += 1
        newF.append(np.asarray(tris, dtype=np.int64))
        for t in tris:
            existing.update(tuple(sorted(e)) for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])))
        rec.append({**r, "method": how, "filled": True})
    return np.concatenate(V2), np.concatenate(newF), rec


def tri_normals(V: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    n = np.cross(b - a, c - a)
    ar = np.linalg.norm(n, axis=1)
    return n / np.maximum(ar, 1e-300)[:, None], ar / 2


def write_stl(path: Path, V: np.ndarray, F: np.ndarray, name: str = "form") -> None:
    """Binary STL (for tests and for handing a mesh on)."""
    T = V[F].astype("<f4")
    n, _ = tri_normals(V, F)
    rec = np.zeros(len(F), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    rec["n"], rec["v"] = n, T
    hdr = (name.encode()[:80]).ljust(80, b" ")
    Path(path).write_bytes(hdr + struct.pack("<I", len(F)) + rec.tobytes())
