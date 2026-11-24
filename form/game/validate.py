"""Checks a game asset (a GLB) against its budgets and the usual engine import problems. Pure numpy: no Blender, no
GPU, so it runs in CI and on any machine.

    parse_glb(data)                 the GLB read back: nodes with positions, normals, UVs, triangles, extras
    validate(data, budgets, ...)    {"ok", "checks": [...], "lods": [...], "collision": [...]}

Checks, per LOD (every value is computed from the file, evidence "computed"; the thresholds are proposed targets):

    glb          the file parses: magic, version, chunk lengths, accessors inside their buffer views, indices in range
    budget       triangles at most the budget + 2%
    manifold     after welding coincident points: no open edge (one face) and no edge shared by three or more faces
    normals      no flipped faces: every shared edge runs once each way (consistent winding), each closed shell
                 encloses positive volume, and no face points against its stored vertex normals
    uv_bounds    every UV inside 0..1
    uv_overlap   UV islands overlap on at most 0.5% of the covered texels (the UV triangles rasterised at 1024 x 1024)
    texel        texel density spread (95th / 5th area-weighted percentile of texture px per metre) at most 2.0
    scale        (when the expected size is given) the GLB's bounding box is 0.001 x the design's millimetres

and, for LOD1 and up, how faithful the LOD is to LOD0 (lod_fidelity, pure numpy as well):

    lod_silhouette  the LOD's silhouette against LOD0's from 8 fixed views (orthographic, rasterised at 512 x 512 on
                 LOD0's frame): the worst view's intersection over union at least 0.985 / 0.96 / 0.90 (LOD1 / 2 / 3)
    lod_distance the symmetric Hausdorff distance between the LOD's surface and LOD0's, as a share of LOD0's bounding
                 box diagonal: at most 0.5% / 1% / 2.5% (LOD1 / 2 / 3). Measured from every point and area samples of
                 each surface to the other's triangles (exact point-to-triangle distances), so it can miss a deviation
                 between samples but never reports less than one it found
"""
from __future__ import annotations

import json
import re
import struct

import numpy as np

UV_OVERLAP_MAX = 0.005           # fraction of covered texels
TEXEL_SPREAD_MAX = 2.0           # p95 / p5 of texel density
FLIPPED_MAX = 0.001              # fraction of faces that point against their stored normals
SCALE_TOL = 0.005                # relative bounding-box error
RASTER = 1024
NORMAL_INWARD_MAX = 0.005        # LOD0 area whose baked tangent normal points into the surface (proposed)
LOD_IOU_MIN = (1.0, 0.985, 0.96, 0.90)          # worst-view silhouette IoU against LOD0, LOD0..LOD3 (proposed)
LOD_HAUSDORFF_MAX = (0.0, 0.005, 0.01, 0.025)   # Hausdorff distance to LOD0 over LOD0's diagonal (proposed)
SILHOUETTE_PX = 512
HAUSDORFF_SAMPLES = 12000
LOD_RE = re.compile(r"_LOD(\d+)$")
COLLISION_RE = re.compile(r"^UCX_|-convcolonly$|-colonly$|_collider$|_collision_\d+$")
COMP = {5126: ("<f4", 4), 5125: ("<u4", 4), 5123: ("<u2", 2), 5121: ("u1", 1), 5122: ("<i2", 2), 5120: ("i1", 1)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class GLBError(ValueError):
    pass


# ---- reading ---------------------------------------------------------------------------------------------------

def _accessor(gltf: dict, binc: bytes, i: int) -> np.ndarray:
    try:
        a = gltf["accessors"][i]
        bv = gltf["bufferViews"][a["bufferView"]]
        dt, size = COMP[a["componentType"]]
        nc = NCOMP[a["type"]]
    except (KeyError, IndexError, TypeError) as e:
        raise GLBError(f"accessor {i} is incomplete ({e})")
    count = int(a["count"])
    off = int(bv.get("byteOffset", 0)) + int(a.get("byteOffset", 0))
    stride = int(bv.get("byteStride") or size * nc)
    need = off + stride * (count - 1) + size * nc if count else off
    if need > int(bv.get("byteOffset", 0)) + int(bv["byteLength"]) or need > len(binc):
        raise GLBError(f"accessor {i} reads past its buffer view")
    if stride == size * nc:
        arr = np.frombuffer(binc, dtype=dt, count=count * nc, offset=off)
    else:
        rows = [np.frombuffer(binc, dtype=dt, count=nc, offset=off + k * stride) for k in range(count)]
        arr = np.concatenate(rows) if rows else np.zeros(0, dt)
    arr = arr.astype(np.float64 if dt.endswith("f4") else np.int64)
    return arr.reshape(count, nc) if nc > 1 else arr


def _quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _node_matrix(n: dict) -> np.ndarray:
    if "matrix" in n:
        return np.asarray(n["matrix"], dtype=np.float64).reshape(4, 4).T
    M = np.eye(4)
    S = np.diag(list(n.get("scale", [1, 1, 1])) + [1])
    R = np.eye(4)
    R[:3, :3] = _quat_mat(n.get("rotation", [0, 0, 0, 1]))
    M[:3, 3] = n.get("translation", [0, 0, 0])
    return M @ R @ S


def parse_glb(data: bytes) -> dict:
    """{"gltf": json, "nodes": [{"name", "P", "N", "UV", "T", "extras", "material"}], "images": n}. Positions are in
    the file's own units and axes (world transforms applied). Raises GLBError naming what is wrong."""
    if len(data) < 20:
        raise GLBError("too short to be a GLB")
    magic, ver, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise GLBError("not a GLB (wrong magic)")
    if ver != 2:
        raise GLBError(f"glTF version {ver}, not 2")
    if length != len(data):
        raise GLBError(f"the header says {length} bytes, the file has {len(data)}")
    off, js, binc = 12, None, b""
    while off < len(data):
        if off + 8 > len(data):
            raise GLBError("a chunk header is cut off")
        clen, ctype = struct.unpack_from("<II", data, off)
        if off + 8 + clen > len(data):
            raise GLBError("a chunk runs past the end of the file")
        chunk = data[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = chunk
        elif ctype == 0x004E4942:
            binc = chunk
        off += 8 + clen
    if js is None:
        raise GLBError("no JSON chunk")
    try:
        gltf = json.loads(js.decode("utf-8"))
    except ValueError as e:
        raise GLBError(f"the JSON chunk does not parse: {e}")
    if str(gltf.get("asset", {}).get("version")) != "2.0":
        raise GLBError("asset.version is not 2.0")
    nodes_in = gltf.get("nodes") or []
    out = []

    def walk(ni, parent):
        if not 0 <= ni < len(nodes_in):
            raise GLBError(f"node {ni} does not exist")
        n = nodes_in[ni]
        M = parent @ _node_matrix(n)
        if "mesh" in n:
            mesh = gltf["meshes"][n["mesh"]]
            for prim in mesh.get("primitives", []):
                if prim.get("mode", 4) != 4:
                    raise GLBError(f"node {n.get('name')}: only triangle primitives are read")
                at = prim["attributes"]
                P = _accessor(gltf, binc, at["POSITION"])
                T = (_accessor(gltf, binc, prim["indices"]) if "indices" in prim else np.arange(len(P)))
                if T.size % 3:
                    raise GLBError(f"node {n.get('name')}: {T.size} indices is not whole triangles")
                T = T.reshape(-1, 3)
                if len(T) and (T.min() < 0 or T.max() >= len(P)):
                    raise GLBError(f"node {n.get('name')}: an index points past its {len(P)} points")
                P = (np.c_[P, np.ones(len(P))] @ M.T)[:, :3]
                N = _accessor(gltf, binc, at["NORMAL"]) if "NORMAL" in at else None
                if N is not None:
                    N = N @ np.linalg.inv(M[:3, :3])
                UV = _accessor(gltf, binc, at["TEXCOORD_0"]) if "TEXCOORD_0" in at else None
                out.append({"name": n.get("name", ""), "P": P, "N": N, "UV": UV, "T": T,
                            "extras": n.get("extras") or {}, "material": prim.get("material")})
        for c in n.get("children", []):
            walk(c, M)

    scene = (gltf.get("scenes") or [{"nodes": list(range(len(nodes_in)))}])[gltf.get("scene", 0)]
    for ni in scene.get("nodes", []):
        walk(ni, np.eye(4))
    return {"gltf": gltf, "nodes": out, "images": len(gltf.get("images") or [])}


# ---- geometry measures -----------------------------------------------------------------------------------------

def weld(P: np.ndarray, T: np.ndarray, rel: float = 1e-6) -> tuple[np.ndarray, np.ndarray]:
    """Points that coincide (to rel x the bounding box diagonal) merged: UV and normal seams split points in a GLB,
    the surface itself is still closed."""
    if not len(P):
        return P, T
    tol = max(float(np.linalg.norm(P.max(0) - P.min(0))) * rel, 1e-12)
    key = np.round(P / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return P[first], inv.reshape(-1)[T]


def edge_stats(T: np.ndarray) -> dict:
    """Open edges (one face), non-manifold edges (three or more) and winding errors (two faces, same direction)."""
    if not len(T):
        return {"edges": 0, "open": 0, "nonmanifold": 0, "inconsistent": 0}
    d = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    d = d[d[:, 0] != d[:, 1]]
    und = np.sort(d, axis=1)
    fwd = (d[:, 0] < d[:, 1]).astype(np.int64)
    u, inv, cnt = np.unique(und, axis=0, return_inverse=True, return_counts=True)
    nf = np.bincount(inv.reshape(-1), weights=fwd, minlength=len(u))
    two = cnt == 2
    return {"edges": int(len(u)), "open": int((cnt == 1).sum()), "nonmanifold": int((cnt > 2).sum()),
            "inconsistent": int((two & (nf != 1)).sum())}


def components(n: int, T: np.ndarray) -> np.ndarray:
    """A component label per point (union-find over triangle edges)."""
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b, c in T:
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[find(rc)] = ra
    return np.array([find(i) for i in range(n)])


def signed_volumes(P: np.ndarray, T: np.ndarray) -> list[float]:
    """Signed volume of each connected shell (positive: outward winding)."""
    if not len(T):
        return []
    lab = components(len(P), T)[T[:, 0]]
    v = np.einsum("ij,ij->i", P[T[:, 0]], np.cross(P[T[:, 1]], P[T[:, 2]])) / 6.0
    return [float(v[lab == k].sum()) for k in np.unique(lab)]


def flipped_faces(P: np.ndarray, T: np.ndarray, N: np.ndarray | None) -> int:
    """Faces whose winding normal points against the mean of their three stored vertex normals."""
    if N is None or not len(T):
        return 0
    fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    vn = N[T].sum(axis=1)
    ok = np.linalg.norm(fn, axis=1) > 1e-20
    return int(((np.einsum("ij,ij->i", fn, vn) < 0) & ok).sum())


def uv_overlap(UV: np.ndarray, T: np.ndarray, res: int = RASTER) -> dict:
    """Rasterise the UV triangles (texel centres strictly inside a triangle count; shared edges are not doubled) and
    count texels covered more than once. {"covered", "overlap", "fraction"} (fraction of covered texels)."""
    grid = np.zeros(res * res, dtype=np.int32)
    tri = UV[T] * res                      # (t, 3, 2) in texels
    for a, b, c in tri:
        x0, y0 = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        x1, y1 = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, res), min(y1, res)
        if x1 <= x0 or y1 <= y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(area) < 1e-12:
            continue
        w0 = ((b[0] - xs) * (c[1] - ys) - (b[1] - ys) * (c[0] - xs)) / area
        w1 = ((c[0] - xs) * (a[1] - ys) - (c[1] - ys) * (a[0] - xs)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 > 0) & (w1 > 0) & (w2 > 0)
        if inside.any():
            idx = (ys[inside].astype(int)) * res + xs[inside].astype(int)
            np.add.at(grid, idx, 1)
    covered = int((grid > 0).sum())
    over = int((grid > 1).sum())
    return {"covered": covered, "overlap": over, "fraction": over / covered if covered else 0.0}


def texel_density(P_m: np.ndarray, UV: np.ndarray, T: np.ndarray, px: int) -> dict:
    """Texture pixels per metre on each triangle; area-weighted 5th, 50th, 95th percentiles and their spread."""
    a3 = 0.5 * np.linalg.norm(np.cross(P_m[T[:, 1]] - P_m[T[:, 0]], P_m[T[:, 2]] - P_m[T[:, 0]]), axis=1)
    u = UV[T]
    a2 = 0.5 * np.abs((u[:, 1, 0] - u[:, 0, 0]) * (u[:, 2, 1] - u[:, 0, 1]) - (u[:, 1, 1] - u[:, 0, 1]) * (u[:, 2, 0] - u[:, 0, 0]))
    ok = a3 > 1e-14
    if not ok.any():
        return {"p5": 0.0, "p50": 0.0, "p95": 0.0, "spread": float("inf")}
    d = np.sqrt(a2[ok] / a3[ok]) * px
    w = a3[ok]
    o = np.argsort(d)
    cw = np.cumsum(w[o]) / w.sum()

    def q(x):
        return float(d[o][min(np.searchsorted(cw, x), len(o) - 1)])
    p5, p50, p95 = q(0.05), q(0.5), q(0.95)
    return {"p5": round(p5, 2), "p50": round(p50, 2), "p95": round(p95, 2),
            "spread": round(p95 / p5, 3) if p5 > 0 else float("inf")}


# ---- LOD fidelity: silhouettes and surface distance against LOD0 ---------------------------------------------------

def silhouette_views(up: int = 1) -> list[tuple[str, np.ndarray]]:
    """The 8 fixed view directions (unit vectors; up is axis `up`, glTF's Y): four around the side (0, 45, 90, 135
    degrees: an orthographic silhouette is the same from the opposite side), three from 40 degrees above (30, 150, 270)
    and one from straight above."""
    out = []
    for az, el in ((0, 0), (45, 0), (90, 0), (135, 0), (30, 40), (150, 40), (270, 40), (0, 90)):
        a, e = np.radians(az), np.radians(el)
        h = [np.cos(e) * np.cos(a), np.cos(e) * np.sin(a)]
        d = np.zeros(3)
        d[up] = np.sin(e)
        d[[k for k in range(3) if k != up]] = h
        out.append((f"az {az} el {el}", d / np.linalg.norm(d)))
    return out


def _basis(d: np.ndarray, up: int = 1) -> tuple[np.ndarray, np.ndarray]:
    a = np.zeros(3)
    a[up] = 1.0
    if abs(float(d @ a)) > 0.9:
        a = np.zeros(3)
        a[(up + 1) % 3] = 1.0
    e1 = np.cross(a, d)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(d, e1)


def rasterise(Q: np.ndarray, T: np.ndarray, res: int) -> np.ndarray:
    """Triangles in pixel coordinates (Q: n x 2) filled into a res x res mask (a pixel is in when its centre is inside
    or on a triangle). Vectorised in batches of triangles with bounding boxes of the same size class."""
    mask = np.zeros(res * res, dtype=bool)
    if not len(T):
        return mask.reshape(res, res)
    t = Q[T]
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    lo = np.clip(np.floor(t.min(1)), 0, res).astype(np.int64)
    hi = np.clip(np.ceil(t.max(1)), 0, res).astype(np.int64)
    span = (hi - lo).max(1)
    ok = (np.abs(area) > 1e-12) & ((hi - lo).min(1) > 0)
    prev = 0
    size = 2
    while prev < res:
        sel = np.nonzero(ok & (span > prev) & (span <= size))[0]
        oy, ox = np.divmod(np.arange(size * size), size)
        step = max(1, 1_500_000 // (size * size))
        for s0 in range(0, len(sel), step):
            i = sel[s0:s0 + step]
            px = lo[i, 0][:, None] + ox[None, :]
            py = lo[i, 1][:, None] + oy[None, :]
            x, y = px + 0.5, py + 0.5
            sg = np.sign(area[i])[:, None]
            A, B, C = a[i], b[i], c[i]

            def edge(p, q):
                return ((q[:, 0] - p[:, 0])[:, None] * (y - p[:, 1][:, None])
                        - (q[:, 1] - p[:, 1])[:, None] * (x - p[:, 0][:, None])) * sg
            inside = (edge(A, B) >= 0) & (edge(B, C) >= 0) & (edge(C, A) >= 0)
            inside &= (px < hi[i, 0][:, None]) & (py < hi[i, 1][:, None])
            mask[(py * res + px)[inside]] = True
        prev, size = size, size * 2
    return mask.reshape(res, res)


def silhouette_iou(P0: np.ndarray, T0: np.ndarray, P1: np.ndarray, T1: np.ndarray, res: int = SILHOUETTE_PX,
                   up: int = 1, cache: dict | None = None) -> list[dict]:
    """Per view: the intersection over union of the two silhouettes, both drawn on LOD0's frame (its projected
    bounding square plus 2%). cache keeps LOD0's masks between LODs."""
    out = []
    for name, d in silhouette_views(up):
        e1, e2 = _basis(d, up)
        u0 = np.c_[P0 @ e1, P0 @ e2]
        mn, mx = u0.min(0), u0.max(0)
        half = float((mx - mn).max()) / 2 * 1.04 or 1.0
        mid = (mn + mx) / 2

        def px(P):
            return (np.c_[P @ e1, P @ e2] - mid + half) / (2 * half) * res
        key = (name, res)
        if cache is not None and key in cache:
            m0 = cache[key]
        else:
            m0 = rasterise(px(P0), T0, res)
            if cache is not None:
                cache[key] = m0
        m1 = rasterise(px(P1), T1, res)
        union = int((m0 | m1).sum())
        out.append({"view": name, "iou": float((m0 & m1).sum()) / union if union else 1.0})
    return out


def point_triangle_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Distance from each point p[i] to the triangle (a[i], b[i], c[i]) (closest point by Voronoi region, Ericson)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        v_ab = np.nan_to_num(d1 / (d1 - d3))
        w_ac = np.nan_to_num(d2 / (d2 - d6))
        w_bc = np.nan_to_num((d4 - d3) / ((d4 - d3) + (d5 - d6)))
        den = va + vb + vc
        den = np.where(np.abs(den) > 1e-300, den, 1.0)
        v, w = vb / den, vc / den
    conds = [(d1 <= 0) & (d2 <= 0), (d3 >= 0) & (d4 <= d3), (vc <= 0) & (d1 >= 0) & (d3 <= 0),
             (d6 >= 0) & (d5 <= d6), (vb <= 0) & (d2 >= 0) & (d6 <= 0),
             (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)]
    choices = [a, b, a + v_ab[:, None] * ab, c, a + w_ac[:, None] * ac, b + w_bc[:, None] * (c - b)]
    q = a + v[:, None] * ab + w[:, None] * ac
    for cnd, ch in reversed(list(zip(conds, choices))):
        q = np.where(cnd[:, None], ch, q)
    return np.linalg.norm(p - q, axis=1)


def distance_to_mesh(Q: np.ndarray, P: np.ndarray, T: np.ndarray, reach: float) -> np.ndarray:
    """Each query point's distance to the triangle mesh (P, T), exact up to `reach`: triangles are bucketed in a grid
    of cells `reach` wide and each point is measured against the triangles in its own and the 26 neighbouring cells.
    A point farther than `reach` from every triangle reads inf (or a distance above `reach`)."""
    out = np.full(len(Q), np.inf)
    if not len(T) or not len(Q):
        return out
    origin = np.minimum(P.min(0), Q.min(0)) - reach
    dims = np.floor((np.maximum(P.max(0), Q.max(0)) - origin) / reach).astype(np.int64) + 3

    def key(ijk):
        return (ijk[..., 0] * dims[1] + ijk[..., 1]) * dims[2] + ijk[..., 2]
    tri = P[T]
    lo = np.floor((tri.min(1) - origin) / reach).astype(np.int64)
    hi = np.floor((tri.max(1) - origin) / reach).astype(np.int64)
    n = np.prod(hi - lo + 1, axis=1)
    owner = np.repeat(np.arange(len(T)), n)
    local = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
    ext = (hi - lo + 1)[owner]
    k2 = local % ext[:, 2]
    k1 = (local // ext[:, 2]) % ext[:, 1]
    k0 = local // (ext[:, 2] * ext[:, 1])
    cells = key(lo[owner] + np.c_[k0, k1, k2])
    order = np.argsort(cells, kind="stable")
    cells, owner = cells[order], owner[order]
    nb = np.array([[i, j, k] for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)])
    qc = np.floor((Q - origin) / reach).astype(np.int64)
    chunk = 1500
    for s in range(0, len(Q), chunk):
        qk = key(qc[s:s + chunk, None, :] + nb[None, :, :])
        st = np.searchsorted(cells, qk, "left").reshape(-1)
        cnt = np.searchsorted(cells, qk, "right").reshape(-1) - st
        if not cnt.sum():
            continue
        qi = np.repeat(np.repeat(np.arange(len(qk)), 27), cnt)
        idx = np.repeat(st, cnt) + (np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt))
        ti = T[owner[idx]]
        d = point_triangle_distance(Q[s + qi], P[ti[:, 0]], P[ti[:, 1]], P[ti[:, 2]])
        res = np.full(len(qk), np.inf)
        np.minimum.at(res, qi, d)
        out[s:s + chunk] = res
    return out


def surface_samples(P: np.ndarray, T: np.ndarray, n: int = HAUSDORFF_SAMPLES, seed: int = 0) -> np.ndarray:
    """Every point a triangle uses, and n points spread over the surface by area (a fixed seed: the same mesh gives
    the same samples)."""
    if not len(T):
        return P[:0]
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    ar = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    rng = np.random.default_rng(seed)
    if ar.sum() <= 0:
        return P[np.unique(T)]
    k = rng.choice(len(T), size=n, p=ar / ar.sum())
    r1, r2 = np.sqrt(rng.random(n)), rng.random(n)
    s = (1 - r1)[:, None] * a[k] + (r1 * (1 - r2))[:, None] * b[k] + (r1 * r2)[:, None] * c[k]
    return np.concatenate([P[np.unique(T)], s])


def hausdorff(P0: np.ndarray, T0: np.ndarray, P1: np.ndarray, T1: np.ndarray, reach: float) -> dict:
    """The symmetric Hausdorff distance between two surfaces, measured from samples of each (surface_samples) to the
    other's triangles. Distances beyond `reach` read inf."""
    d01 = distance_to_mesh(surface_samples(P0, T0), P1, T1, reach)
    d10 = distance_to_mesh(surface_samples(P1, T1), P0, T0, reach)
    return {"lod0_to_lod": float(d01.max()) if len(d01) else 0.0, "lod_to_lod0": float(d10.max()) if len(d10) else 0.0,
            "max": float(max(d01.max() if len(d01) else 0.0, d10.max() if len(d10) else 0.0))}


def lod_fidelity(P0: np.ndarray, T0: np.ndarray, P: np.ndarray, T: np.ndarray, up: int = 1,
                 cache: dict | None = None) -> dict:
    """{"iou_min", "worst_view", "views": [...], "hausdorff": distance, "hausdorff_rel": share of LOD0's diagonal}."""
    P0, P = np.asarray(P0, np.float64), np.asarray(P, np.float64)
    T0, T = np.asarray(T0, np.int64), np.asarray(T, np.int64)
    diag = float(np.linalg.norm(P0.max(0) - P0.min(0))) or 1.0
    views = silhouette_iou(P0, T0, P, T, up=up, cache=cache)
    worst = min(views, key=lambda v: v["iou"])
    h = hausdorff(P0, T0, P, T, reach=diag * 0.03)
    return {"iou_min": round(worst["iou"], 5), "worst_view": worst["view"],
            "views": [{"view": v["view"], "iou": round(v["iou"], 5)} for v in views],
            "hausdorff": h["max"], "hausdorff_rel": h["max"] / diag, "diagonal": diag}


# ---- the report ------------------------------------------------------------------------------------------------

def _lod_index(nd: dict) -> int | None:
    ex = nd.get("extras") or {}
    if isinstance(ex.get("lod"), int):
        return ex["lod"]
    m = LOD_RE.search(nd["name"])
    return int(m.group(1)) if m else None


def _is_collision(nd: dict) -> bool:
    return (nd.get("extras") or {}).get("form") == "collision" or bool(COLLISION_RE.search(nd["name"]))


def validate(data: bytes, budgets: list[int] | None = None, texture_px: int = 1024, expect_size_mm=None,
             up: str = "Y", unit_scale: float = 0.001) -> dict:
    """Check a GLB. budgets: triangles per LOD (LOD0 first). expect_size_mm: the design's bounding box size (x, y, z)
    in millimetres, Z up; the GLB's must be unit_scale times it (glTF: 0.001, Y up)."""
    from .presets import BUDGET_TOLERANCE
    checks: list[dict] = []

    def add(cid, label, ok, value, detail, lod=None):
        checks.append({"id": cid, "label": label, "status": "PASS" if ok else "FAIL", "value": value,
                       "detail": detail, "evidence": "computed", **({"lod": lod} if lod is not None else {})})
    try:
        g = parse_glb(data)
    except (GLBError, KeyError, IndexError, TypeError, ValueError, struct.error) as e:
        add("glb", "The GLB parses", False, "unreadable", str(e))
        return {"ok": False, "checks": checks, "lods": [], "collision": []}
    add("glb", "The GLB parses", True, f"{len(g['nodes'])} meshes, {g['images']} images",
        "Header, chunks, accessors and indices are consistent.")
    coll = [n for n in g["nodes"] if _is_collision(n)]
    rest = [n for n in g["nodes"] if not _is_collision(n)]
    by_lod: dict = {}
    for n in rest:
        k = _lod_index(n)
        by_lod.setdefault(0 if k is None else k, []).append(n)
    lods = []
    geo: dict = {}
    for k in sorted(by_lod):
        ns = by_lod[k]
        P = np.concatenate([n["P"] for n in ns])
        offs = np.cumsum([0] + [len(n["P"]) for n in ns])[:-1]
        T = np.concatenate([n["T"] + o for n, o in zip(ns, offs)])
        N = np.concatenate([n["N"] for n in ns]) if all(n["N"] is not None for n in ns) else None
        UV = np.concatenate([n["UV"] for n in ns]) if all(n["UV"] is not None for n in ns) else None
        tris = int(len(T))
        info = {"lod": k, "nodes": [n["name"] for n in ns], "triangles": tris}
        name = f"LOD{k}"
        if budgets and k < len(budgets):
            b = int(budgets[k])
            info.update(budget=b, fill=round(tris / b, 4))
            add("budget", f"{name} within its triangle budget", tris <= b * (1 + BUDGET_TOLERANCE),
                f"{tris} / {b} triangles ({tris / b * 100:.1f}%)",
                f"A budget is a ceiling; up to {BUDGET_TOLERANCE * 100:g}% over passes.", k)
        Pw, Tw = weld(P, T)
        es = edge_stats(Tw)
        info["edges"] = es
        add("manifold", f"{name} is closed and manifold", es["open"] == 0 and es["nonmanifold"] == 0,
            f"{es['open']} open, {es['nonmanifold']} non-manifold edges",
            "Measured after welding coincident points (UV and normal seams split points in a GLB).", k)
        vols = signed_volumes(Pw, Tw) if es["open"] == 0 else []
        inverted = sum(1 for v in vols if v < 0)
        flips = flipped_faces(P, T, N)
        info.update(inverted_shells=inverted, flipped_faces=flips)
        add("normals", f"{name} has no flipped faces",
            es["inconsistent"] == 0 and inverted == 0 and flips <= FLIPPED_MAX * max(tris, 1),
            f"{es['inconsistent']} winding errors, {inverted} inside-out shells, {flips} faces against their normals",
            "Shared edges must run once each way; closed shells must enclose positive volume.", k)
        if UV is None:
            add("uv_bounds", f"{name} has UVs", False, "no TEXCOORD_0", "A textured game asset needs UVs.", k)
        else:
            out = float(((UV < -1e-6) | (UV > 1 + 1e-6)).any(axis=1).mean()) if len(UV) else 0.0
            info["uv_outside"] = round(out, 6)
            add("uv_bounds", f"{name} UVs inside 0..1", out == 0.0, f"{out * 100:.3f}% of UV points outside",
                "Points outside 0..1 wrap around and sample the wrong texels.", k)
            ov = uv_overlap(UV, T)
            info["uv_overlap"] = round(ov["fraction"], 6)
            info["uv_coverage"] = round(ov["covered"] / RASTER ** 2, 4)
            add("uv_overlap", f"{name} UV islands do not overlap", ov["fraction"] <= UV_OVERLAP_MAX,
                f"{ov['fraction'] * 100:.3f}% of covered texels",
                f"Rasterised at {RASTER} x {RASTER}; at most {UV_OVERLAP_MAX * 100:g}% (proposed). Overlaps bake two "
                f"surfaces into one texel. Coverage {ov['covered'] / RASTER ** 2 * 100:.1f}% of the square.", k)
            if k == 0:
                Pm = P * (1.0 if unit_scale == 0.001 else 0.001 / unit_scale)
                td = texel_density(Pm, UV, T, texture_px)
                info["texel_density"] = td
                add("texel", "LOD0 texel density is even", td["spread"] <= TEXEL_SPREAD_MAX,
                    f"spread {td['spread']} (p5 {td['p5']}, p50 {td['p50']}, p95 {td['p95']} px/m at {texture_px} px)",
                    f"95th over 5th percentile, area-weighted; at most {TEXEL_SPREAD_MAX} (proposed).", k)
        if k == 0 and expect_size_mm is not None:
            size = P.max(0) - P.min(0)
            if up == "Y":
                size = np.array([size[0], size[2], size[1]])
            want = np.asarray(expect_size_mm, dtype=np.float64) * unit_scale
            err = float(np.max(np.abs(size - want) / np.maximum(want, 1e-12)))
            info["size"] = [round(float(x), 6) for x in size]
            add("scale", "LOD0 is the design's size", err <= SCALE_TOL,
                f"{' x '.join(f'{x:.4g}' for x in size)} (expected {' x '.join(f'{x:.4g}' for x in want)}), "
                f"error {err * 100:.3f}%", f"{unit_scale:g} x millimetres, {up} up.", 0)
        lods.append(info)
        geo[k] = (Pw, Tw)
    if 0 in geo and len(geo) > 1:
        cache: dict = {}
        P0, T0 = geo[0]
        for info in lods:
            k = info["lod"]
            if k == 0:
                continue
            f = lod_fidelity(P0, T0, *geo[k], up=1 if up == "Y" else 2, cache=cache)
            j = min(k, len(LOD_IOU_MIN) - 1)
            info["fidelity"] = {"iou_min": f["iou_min"], "worst_view": f["worst_view"], "views": f["views"],
                                "hausdorff_rel": round(f["hausdorff_rel"], 6)}
            add("lod_silhouette", f"LOD{k} keeps LOD0's silhouette", f["iou_min"] >= LOD_IOU_MIN[j],
                f"IoU {f['iou_min']:.4f} at worst ({f['worst_view']})",
                f"Silhouettes from 8 views, {SILHOUETTE_PX} px on LOD0's frame; the worst view at least "
                f"{LOD_IOU_MIN[j]:g} (proposed).", k)
            hr = f["hausdorff_rel"]
            add("lod_distance", f"LOD{k} stays close to LOD0's surface", hr <= LOD_HAUSDORFF_MAX[j],
                (f"{hr * 100:.3f}%" if np.isfinite(hr) else "over 3%") + " of the diagonal (Hausdorff)",
                f"Symmetric Hausdorff distance from points and area samples of each surface to the other's "
                f"triangles; at most {LOD_HAUSDORFF_MAX[j] * 100:g}% of LOD0's diagonal (proposed).", k)
    if budgets:
        for k in range(len(budgets)):
            if k not in by_lod:
                add("budget", f"LOD{k} is present", False, "missing", f"No node named *_LOD{k}.", k)
    col = [{"name": n["name"], "triangles": int(len(n["T"])), "points": int(len(n["P"]))} for n in coll]
    return {"ok": all(c["status"] == "PASS" for c in checks), "checks": checks, "lods": lods, "collision": col}


def normal_map_inward(rgb: np.ndarray, UV: np.ndarray, T: np.ndarray, samples: int = 4) -> dict:
    """Share of a LOD's area whose tangent-space normal map points into the surface (blue below 0.5, so z < 0).
    A sound bake never does that: such texels come from a bake ray that hit another surface from behind (a lid
    resting on a box, a part nested in another) or a flipped high poly. rgb: the map, H x W x 3 in 0..1, row 0 at the
    top; UV: Blender's convention (v up). Each triangle is sampled at `samples` interior points, area-weighted."""
    rgb = np.asarray(rgb, dtype=np.float64)
    h, w = rgb.shape[:2]
    U = np.asarray(UV, dtype=np.float64)[np.asarray(T)]
    bary = np.array([[1 / 3, 1 / 3, 1 / 3], [2 / 3, 1 / 6, 1 / 6], [1 / 6, 2 / 3, 1 / 6], [1 / 6, 1 / 6, 2 / 3]])[:samples]
    pts = np.einsum("sk,tkd->tsd", bary, U)
    x = np.clip((pts[..., 0] * w).astype(int), 0, w - 1)
    y = np.clip(((1 - pts[..., 1]) * h).astype(int), 0, h - 1)
    inward = (rgb[y, x, 2] < 0.5).mean(axis=1)
    e1, e2 = U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]
    area = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2
    tot = float(area.sum()) or 1.0
    return {"fraction": round(float((inward * area).sum() / tot), 6), "triangles": int((inward > 0.5).sum())}


def normal_map_check(png, UV: np.ndarray, T: np.ndarray) -> dict:
    """The check for a baked normal map (PNG bytes or a path; Pillow decodes it)."""
    import io
    from PIL import Image
    src = io.BytesIO(png) if isinstance(png, (bytes, bytearray)) else png
    rgb = np.asarray(Image.open(src).convert("RGB"), dtype=np.float64) / 255.0
    r = normal_map_inward(rgb, UV, T)
    return {"id": "normal_map", "label": "LOD0's baked normals face out of the surface",
            "status": "PASS" if r["fraction"] <= NORMAL_INWARD_MAX else "FAIL",
            "value": f"{r['fraction'] * 100:.3f}% of LOD0's UV area points inward ({r['triangles']} triangles)",
            "detail": f"Tangent-space blue below 0.5 means a bake ray hit another surface from behind; at most "
                      f"{NORMAL_INWARD_MAX * 100:g}% (proposed).", "evidence": "computed", "lod": 0}


def failed(report: dict) -> list[str]:
    return sorted({c["id"] for c in report["checks"] if c["status"] != "PASS"})
