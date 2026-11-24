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
    if budgets:
        for k in range(len(budgets)):
            if k not in by_lod:
                add("budget", f"LOD{k} is present", False, "missing", f"No node named *_LOD{k}.", k)
    col = [{"name": n["name"], "triangles": int(len(n["T"])), "points": int(len(n["P"]))} for n in coll]
    return {"ok": all(c["status"] == "PASS" for c in checks), "checks": checks, "lods": lods, "collision": col}


def failed(report: dict) -> list[str]:
    return sorted({c["id"] for c in report["checks"] if c["status"] != "PASS"})
