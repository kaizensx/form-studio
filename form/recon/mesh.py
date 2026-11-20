"""Reading triangle meshes (STL, OBJ, 3MF), welding them and reporting what is wrong with them. numpy and scipy only.

Nothing here repairs a mesh behind your back. `weld` merges vertices closer than a tolerance and drops triangles that
collapse to a line or a point; both are counted in the report. `topology` lists open boundaries, non-manifold edges
and edges whose two triangles disagree about which side is outside. `fill_holes` closes open boundaries only when it is
called, and returns what it filled so the caller can say so.
"""
from __future__ import annotations

import hashlib
import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import numpy as np

FORMATS = (".stl", ".obj", ".3mf")


@dataclass
class Mesh:
    V: np.ndarray                      # (n, 3) float64 vertices, mm
    F: np.ndarray                      # (m, 3) int64 triangles, counter-clockwise seen from outside
    info: dict = field(default_factory=dict)

    @property
    def triangles(self) -> np.ndarray:
        return self.V[self.F]


# ---- readers ---------------------------------------------------------------------------------------------------------

def _stl(data: bytes) -> tuple[np.ndarray, str]:
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n == len(data):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
            return rec["v"].astype(np.float64), "stl (binary)"
    text = data.decode("utf-8", "replace")
    if not text.lstrip().lower().startswith("solid"):
        raise ValueError("Not a readable STL: neither a binary STL of the right length nor ASCII starting with 'solid'.")
    nums = re.findall(r"^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)", text, flags=re.MULTILINE | re.IGNORECASE)
    if not nums or len(nums) % 3:
        raise ValueError("The ASCII STL has no complete facets.")
    return np.asarray(nums, dtype=np.float64).reshape(-1, 3, 3), "stl (ascii)"


def _obj(data: bytes) -> np.ndarray:
    verts, faces = [], []
    for ln in data.decode("utf-8", "replace").splitlines():
        s = ln.split()
        if not s:
            continue
        if s[0] == "v" and len(s) >= 4:
            verts.append((float(s[1]), float(s[2]), float(s[3])))
        elif s[0] == "f" and len(s) >= 4:
            idx = []
            for tok in s[1:]:
                i = int(tok.split("/")[0])
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):           # fan-triangulate polygons (convex faces, as OBJ exporters write)
                faces.append((idx[0], idx[k], idx[k + 1]))
    if not faces:
        raise ValueError("The OBJ has no faces.")
    V = np.asarray(verts, dtype=np.float64)
    F = np.asarray(faces, dtype=np.int64)
    if F.min() < 0 or F.max() >= len(V):
        raise ValueError("The OBJ refers to vertices it does not define.")
    return V[F]


_UNIT_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}


def _3mf(data: bytes) -> tuple[np.ndarray, str]:
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".model")]
        if not names:
            raise ValueError("The 3MF has no 3D model part.")
        tris, unit = [], "millimeter"
        for n in names:
            root = ElementTree.fromstring(z.read(n))
            unit = root.get("unit", unit)
            ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
            objects = {o.get("id"): o for o in root.iter(f"{ns}object")}
            meshes = {}
            for oid, o in objects.items():
                m = o.find(f"{ns}mesh")
                if m is None:
                    continue
                V = np.array([[float(v.get(a)) for a in "xyz"] for v in m.iter(f"{ns}vertex")], dtype=np.float64)
                F = np.array([[int(t.get(a)) for a in ("v1", "v2", "v3")] for t in m.iter(f"{ns}triangle")], dtype=np.int64)
                if len(F):
                    meshes[oid] = V[F]
            build = root.find(f"{ns}build")
            items = list(build.iter(f"{ns}item")) if build is not None else []
            if not items:
                tris += list(meshes.values())
            for it in items:
                t = _expand(objects, meshes, it.get("objectid"), _xf(it.get("transform")), ns)
                tris += t
        if not tris:
            raise ValueError("The 3MF holds no triangles.")
    T = np.concatenate(tris) * _UNIT_MM.get(unit, 1.0)
    return T, f"3mf ({unit})"


def _xf(s: str | None) -> np.ndarray:
    M = np.eye(4)
    if s:
        v = [float(x) for x in s.split()]
        if len(v) == 12:
            M[:3, :3] = np.array(v[:9]).reshape(3, 3)          # rows m00 m01 m02 / m10 ... (3MF uses row vectors)
            M[3, :3] = v[9:]
    return M


def _expand(objects, meshes, oid, M, ns, depth=0) -> list:
    if depth > 16 or oid not in objects:
        return []
    out = []
    if oid in meshes:
        T = meshes[oid].reshape(-1, 3)
        out.append((np.c_[T, np.ones(len(T))] @ M)[:, :3].reshape(-1, 3, 3))
    comps = objects[oid].find(f"{ns}components")
    if comps is not None:
        for c in comps.iter(f"{ns}component"):
            out += _expand(objects, meshes, c.get("objectid"), _xf(c.get("transform")) @ M, ns, depth + 1)
    return out


def read_triangles(path: Path, fmt: str | None = None) -> tuple[np.ndarray, dict]:
    """(triangles (m, 3, 3) float64, info) from an STL (binary or ASCII), OBJ or 3MF file. Units: mm."""
    p = Path(path)
    data = p.read_bytes()
    ext = (fmt or p.suffix).lower()                  # fmt: for a file whose name is not its format (a .tmp copy)
    if ext == ".stl":
        T, fmt = _stl(data)
    elif ext == ".obj":
        T, fmt = _obj(data), "obj"
    elif ext == ".3mf":
        T, fmt = _3mf(data)
    else:
        raise ValueError(f"Unsupported mesh format {ext or '(none)'}; use STL, OBJ or 3MF.")
    if not np.all(np.isfinite(T)):
        raise ValueError("The mesh has coordinates that are not finite numbers.")
    return T, {"file": p.name, "format": fmt, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
               "triangles_in": int(len(T)), "units": "mm" + ("" if fmt.startswith("3mf") else " (assumed)")}


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
    """Open boundaries as vertex loops, following each boundary half-edge in its triangle's direction."""
    bset = set(np.flatnonzero(cnt == 1).tolist())
    nxt = {}
    for i in np.flatnonzero(np.isin(eo, list(bset))):
        a, b = int(he[i, 0]), int(he[i, 1])
        nxt.setdefault(a, []).append(b)
    loops, seen = [], set()
    for start in list(nxt):
        if start in seen:
            continue
        loop, v = [], start
        while v not in seen and v in nxt:
            seen.add(v)
            loop.append(v)
            v = nxt[v][0] if len(nxt[v]) == 1 else nxt[v].pop(0)
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def fill_holes(V: np.ndarray, F: np.ndarray, loops: list[list[int]]) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Close each open boundary loop with a fan around its centroid. Returns the new mesh and one record per fill."""
    V2, newF, rec = [V], [F], []
    n = len(V)
    for loop in loops:
        P = V[loop]
        c = P.mean(axis=0)
        ci = n
        n += 1
        V2.append(c[None])
        k = len(loop)
        # the boundary half-edges run a->b in their triangle; the patch must use b->a
        tris = np.array([[loop[(i + 1) % k], loop[i], ci] for i in range(k)], dtype=np.int64)
        newF.append(tris)
        span = float(np.linalg.norm(P - c, axis=1).max())
        rec.append({"repair": "filled hole", "edges": k, "span_mm": round(2 * span, 4), "at": [round(float(x), 4) for x in c]})
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
