"""The lattice as geometry, inside a region of a body. Kernel worker only (OCCT, and manifold3d for the mesh route).

    out = fill(shape, spec)        # the body with the region's inside replaced by the lattice, a skin left around it

The region is the body (or the part of it inside a box); the inner region is the region offset inward by the skin
(an OCCT offset, exact). The open space of the lattice inside the inner region is cut out of the body, so the skin
and everything outside the region stay the body's own exact faces:

    result = body - (inner - lattice)

What the lattice is built as:

  struts       B-rep route: every strut a cylinder, every node a sphere (a little larger than the strut, so the
               surfaces cross instead of touching), one general fuse; the result is an exact B-rep solid, written to
               STEP. Above BREP_STRUTS struts that fuse takes minutes, so the mesh route is used: the same cylinders
               and spheres as facets, combined by manifold3d.
  TPMS         there is no closed-form B-rep of a level set of sines. Its open space is meshed on a grid by marching
               tetrahedra (form/lattice/cells.py), each of a sheet's two channel systems on its own, and the
               facets' distance from the true level set is measured. Up to BREP_FACETS_INSIDE triangles (BREP_FACETS when
               there is no skin and the open space reaches the body's surface) that mesh is made a
               solid of planar faces and cut from the exact body in OCCT ("faceted B-rep": a valid solid, exact
               outside the lattice, flat triangles where the lattice is); above that everything is facets, combined
               by manifold3d (a mesh body).

The report says which was produced and why, with the measured relative density of the core, the thinnest strut, the
facet deviation and the closed voids left inside (trapped powder or resin).
"""
from __future__ import annotations

import hashlib
import json
import math
import time

import numpy as np

from . import cells as C

BREP_STRUTS = 900            # the general fuse of this many struts takes about half a minute
BREP_FACETS = 6000           # facets of a void that reaches the body's surface: above this OCCT's cut takes minutes
BREP_FACETS_INSIDE = 60000   # facets of a void wholly inside a skin: nothing to intersect, the cut takes seconds
MESH_TRIANGLES = 1_500_000   # the mesh route's ceiling
GRID_POINTS = 14_000_000     # the TPMS grid's ceiling (points)
STRUT_SEGMENTS = 16          # facets round a strut on the mesh route
SIMPLIFY_MM = 0.02           # a TPMS mesh's facets are merged where that moves the surface by less than this
REPORTS: dict = {}
LatticeError = C.LatticeError


def spec_key(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ── density over the region ──────────────────────────────────────────────────────────────────────────────────────

def _trilinear(grid: dict, P: np.ndarray) -> np.ndarray:
    shp = [int(x) for x in grid["shape"]]
    V = np.asarray(grid["values"], float).reshape(shp)
    o, s = np.asarray(grid["origin"], float), np.asarray(grid["step"], float)
    q = (P - o) / np.where(s > 0, s, 1.0)
    i0 = [np.clip(np.floor(q[:, k]).astype(int), 0, max(shp[k] - 2, 0)) for k in range(3)]
    t = [np.clip(q[:, k] - i0[k], 0.0, 1.0) if shp[k] > 1 else np.zeros(len(P)) for k in range(3)]
    out = np.zeros(len(P))
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                ix = np.minimum(i0[0] + dx, shp[0] - 1)
                iy = np.minimum(i0[1] + dy, shp[1] - 1)
                iz = np.minimum(i0[2] + dz, shp[2] - 1)
                w = (t[0] if dx else 1 - t[0]) * (t[1] if dy else 1 - t[1]) * (t[2] if dz else 1 - t[2])
                out += w * V[ix, iy, iz]
    return out


def density_at(spec: dict, P: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray | None:
    """The target relative density at points P (n, 3) for a graded lattice; None for a uniform one. lo, hi: the inner
    region's bounding box."""
    g = spec.get("grading") or {}
    mode = g.get("mode", "uniform")
    if mode == "uniform":
        return None
    d0, d1 = (float(x) for x in g["density"])
    if mode == "distance":
        ref = g.get("from", "boundary")
        if ref == "boundary":
            dist = np.minimum(P - lo, hi - P).min(axis=1)
        elif isinstance(ref, dict) and "point" in ref:
            dist = np.linalg.norm(P - np.asarray(ref["point"], float), axis=1)
        elif isinstance(ref, dict) and "plane" in ref:
            n = np.asarray(ref["plane"]["normal"], float)
            dist = np.abs((P - np.asarray(ref["plane"]["origin"], float)) @ (n / np.linalg.norm(n)))
        else:
            raise LatticeError("grading.from is \"boundary\", {\"point\": [x, y, z]} or {\"plane\": {origin, normal}}.")
        s = np.clip(dist / float(g["over"]), 0.0, 1.0)
    elif mode == "stress":
        s = np.clip(_trilinear(g["grid"], P), 0.0, 1.0) ** float(g.get("exponent", 1.0))
    else:
        raise LatticeError(f"Unknown grading “{mode}”.", "uniform, distance or stress.")
    return d0 + (d1 - d0) * s


_RADIUS_TABLE: dict = {}


def _radius_for_density(kind: str, rho: np.ndarray, cell: float, node: float) -> np.ndarray:
    """Strut radius (mm) for a relative density: a table of ten measured radii, linear between them."""
    if (kind, node) not in _RADIUS_TABLE:
        rs = np.array([0.01, 0.02, 0.035, 0.05, 0.07, 0.09, 0.12, 0.15, 0.19, 0.24])
        rs = rs[rs * node < 0.98 * C.strut_min_length(kind)]
        _RADIUS_TABLE[(kind, node)] = (np.array([strut_density(kind, r, 1.0, node, 28) for r in rs]), rs)
    d, rs = _RADIUS_TABLE[(kind, node)]
    return np.interp(rho, d, rs) * cell


def strut_density(kind: str, radius: float, cell: float, node: float = 1.25, n: int = 48) -> float:
    """Relative density of an endless strut lattice with node spheres of radius node * r, measured on the union by
    a smoothed count on n³ points. A strut under 2.5 points across cannot be counted that way: there the thin-strut
    limit pi r² L / a³ is returned (what is left out, the overlap and the spheres at the nodes, is of order (r / a)³)."""
    if radius / cell * n < 1.25:
        if n < 96:
            return strut_density(kind, radius, cell, node, 96)
        return C.strut_density_first_order(kind, radius, cell)
    S, R = _with_nodes(C.struts(kind, (3, 3, 3)) - 1.0, radius / cell, node)
    t = (np.arange(n) + 0.5) / n
    P = np.stack(np.meshgrid(t, t, t, indexing="ij"), axis=-1).reshape(-1, 3)
    near = (np.minimum(S[:, 0], S[:, 1]) < 1 + R[:, None]).all(axis=1) & (np.maximum(S[:, 0], S[:, 1]) > -R[:, None]).all(axis=1)
    d = C.capsule_distance(P, S[near], R[near])
    return float(np.clip(0.5 - d * n, 0.0, 1.0).mean())


def _with_nodes(S: np.ndarray, r, node: float):
    """Struts plus their nodes as zero-length capsules of the node radius: (segments, radii)."""
    r = np.broadcast_to(np.asarray(r, float), (len(S),)).copy()
    pts = np.round(S.reshape(-1, 3), 6)
    uniq, inv = np.unique(pts, axis=0, return_inverse=True)
    nr = np.zeros(len(uniq))
    np.maximum.at(nr, inv.reshape(-1), np.repeat(r, 2))
    N = np.stack([uniq, uniq], axis=1)
    return np.concatenate([S, N]), np.concatenate([r, nr * node])


# ── the region ───────────────────────────────────────────────────────────────────────────────────────────────────

def _bbox(shape):
    b = shape.bounding_box()
    return np.array([b.min.X, b.min.Y, b.min.Z]), np.array([b.max.X, b.max.Y, b.max.Z])


def _one_solid(shape, what: str):
    ss = shape.solids()
    if len(ss) != 1:
        raise LatticeError(f"{what} is {len(ss)} bodies: a lattice fills one solid.",
                           "Fill one part, or give region={\"min\": [...], \"max\": [...]} inside one body.")
    return ss[0]


def region_of(shape, spec: dict):
    """(body, zone, inner): the solid, the part of it the lattice replaces, and that part shrunk by the skin."""
    from build123d import Align, Box, Pos, offset
    body = _one_solid(shape, "The design")
    zone = body
    reg = spec.get("region")
    if reg:
        lo, hi = np.asarray(reg["min"], float), np.asarray(reg["max"], float)
        if (hi - lo).min() <= 0:
            raise LatticeError("region.max must be greater than region.min on every axis.", params=["region"])
        box = Pos(*lo) * Box(*(hi - lo), align=(Align.MIN,) * 3)
        cut = body & box
        if cut is None or not cut.solids() or cut.volume < 1e-9:
            raise LatticeError("The region box does not meet the body.", "Give a box that overlaps the part.", ["region"])
        zone = _one_solid(cut, "The region inside the body")
    skin = float(spec.get("skin") or 0.0)
    if skin <= 0:
        return body, zone, zone
    lo, hi = _bbox(zone)
    if (hi - lo).min() <= 2 * skin + 1e-6:
        raise LatticeError(f"A {skin:g} mm skin leaves nothing inside a region {(hi - lo).min():.2f} mm thick.",
                           "Use a thinner skin or a larger region.", ["skin"])
    why = ""
    try:
        inner = offset(zone, amount=-skin)
        ss = inner.solids()
        ok = len(ss) == 1 and 0 < ss[0].volume < zone.volume and ss[0].is_valid
    except Exception as e:                                      # noqa: BLE001 - OCCT's offset raises many things
        ok, ss = False, []
        why = f" ({type(e).__name__})"
    if not ok:
        raise LatticeError(f"The region could not be offset inward by the {skin:g} mm skin{why}.",
                           "Give a simpler region (region={\"min\", \"max\"}: a box inside the part), or skin=0.", ["skin"])
    return body, zone, ss[0]


def _is_box(inner, lo, hi) -> bool:
    return abs(inner.volume - float(np.prod(hi - lo))) <= 1e-6 * float(np.prod(hi - lo))


# ── counting, before anything is built ───────────────────────────────────────────────────────────────────────────

def _cells(lo, hi, cell: float):
    return np.maximum(1, np.ceil((hi - lo) / cell - 1e-9).astype(int))


def _struts_in(spec: dict, lo, hi):
    """Struts that reach into the box, with their radii: (S (m, 2, 3) mm, r (m,))."""
    cell = float(spec["cell"])
    n = _cells(lo, hi, cell)
    if float(np.prod(n)) > 40000:
        raise LatticeError(f"{int(np.prod(n)):,} cells are too many.", "Use a larger cell or a smaller region.", ["cell"])
    S = C.struts(spec["kind"], tuple(int(x) for x in n)) * cell + lo
    rho = density_at(spec, S.mean(axis=1), lo, hi)
    if rho is None:
        r = np.full(len(S), float(spec["strut_d"]) / 2.0)
    else:
        r = _radius_for_density(spec["kind"], rho, cell, float(spec["node"]))
    R = r * float(spec["node"])
    keep = (np.minimum(S[:, 0], S[:, 1]) < hi + R[:, None]).all(axis=1) & (np.maximum(S[:, 0], S[:, 1]) > lo - R[:, None]).all(axis=1)
    return S[keep], r[keep]


def _tpms_grid(spec: dict, lo, hi):
    """Grid step, point counts and a note: `resolution` points per cell, fewer when the grid would be too large."""
    cell = float(spec["cell"])
    res = int(spec.get("resolution") or 14)
    note = ""
    h = cell / res
    n = np.ceil((hi - lo) / h).astype(int) + 8
    if float(np.prod(n)) > GRID_POINTS:
        f = (float(np.prod(n)) / GRID_POINTS) ** (1.0 / 3.0)
        res2 = max(6, int(res / f))
        note = (f"resolution lowered from {res} to {res2} points per cell to keep the grid under {GRID_POINTS:,} "
                f"points (see the measured deviation)")
        h = cell / res2
        n = np.ceil((hi - lo) / h).astype(int) + 8
        if float(np.prod(n)) > GRID_POINTS:
            raise LatticeError(f"{int(np.prod(_cells(lo, hi, cell))):,} cells are too many to mesh.",
                               "Use a larger cell or a smaller region.", ["cell"])
    return h, n, note


def brep_facets(spec: dict) -> int:
    """How many facets the B-rep route takes: with a skin the open space lies wholly inside the body, so OCCT's cut
    has nothing to intersect and tens of thousands of faces take seconds; without one every facet on the region's
    boundary meets a face of the body."""
    return BREP_FACETS_INSIDE if float(spec.get("skin") or 0.0) > 0 else BREP_FACETS


def plan(shape, spec: dict) -> dict:
    """What a fill would produce, decided without building it: the output (B-rep or mesh) and why."""
    _body, zone, inner = region_of(shape, spec)
    lo, hi = _bbox(inner)
    cell = float(spec["cell"])
    n = _cells(lo, hi, cell)
    want = spec.get("output") or "auto"
    out = {"cells": [int(x) for x in n], "inner_box_mm": [[round(float(x), 4) for x in lo], [round(float(x), 4) for x in hi]],
           "inner_volume_mm3": float(inner.volume), "zone_volume_mm3": float(zone.volume)}
    if C.is_tpms(spec["kind"]):
        h, _grid, note = _tpms_grid(spec, lo, hi)
        area = (C.PUBLISHED_AREA.get(spec["kind"]) or C.tpms_area(spec["kind"], 32)) / cell * float(inner.volume)
        tris = int((2 if spec.get("form", "sheet") == "sheet" else 1) * area / (h * h) * 4.5)   # marching tetrahedra, merged within SIMPLIFY_MM
        out.update(estimated_triangles=tris, grid_mm=round(h, 5), note=note)
        limit = brep_facets(spec)
        if want == "brep" and tris > 3 * limit:
            raise LatticeError(f"About {tris:,} facets: too many to make a B-rep of and cut from the body (about "
                               f"{limit:,} is practical here).", "Use output=\"mesh\", fewer cells, or a thicker wall.",
                               ["output"])
        if want == "mesh" or (want == "auto" and tris > limit):
            out.update(output="mesh", why=("asked for" if want == "mesh" else
                                           f"about {tris:,} facets is above the {limit:,} that OCCT cuts from the "
                                           f"body in reasonable time") + "; a TPMS has no exact B-rep, so its surface "
                                          "is facets either way")
        else:
            out.update(output="brep", why=f"about {tris:,} facets: made a solid of planar faces and cut from the exact "
                                          f"body (a faceted B-rep: a TPMS has no exact one)")
    else:
        S, _r = _struts_in(spec, lo, hi)
        out.update(struts=int(len(S)))
        if want == "mesh" or (want == "auto" and len(S) > BREP_STRUTS):
            out.update(output="mesh", why="asked for" if want == "mesh" else
                       f"{len(S):,} struts is above the {BREP_STRUTS} whose fuse OCCT finishes in about half a minute")
        else:
            out.update(output="brep", why=f"{len(S):,} struts: exact cylinders and node spheres, fused in OCCT")
    if out["output"] == "mesh" and not _has_manifold():
        raise LatticeError("The mesh route needs manifold3d, which is not installed.",
                           "pip install 'form-studio[organic]', or fewer cells so the B-rep route applies.")
    return out


def _has_manifold() -> bool:
    import importlib.util
    return importlib.util.find_spec("manifold3d") is not None


# ── building ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _boolean(cls, args, tools):
    from OCP.collections import List_TopoDS_Shape
    la, lt = List_TopoDS_Shape(), List_TopoDS_Shape()
    for x in args:
        la.Append(x)
    for x in tools:
        lt.Append(x)
    op = cls()
    op.SetArguments(la)
    op.SetTools(lt)
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        raise LatticeError("OCCT could not combine the lattice.", "Try output=\"mesh\".")
    return op.Shape()


def _solid_of(wrapped, what: str):
    from build123d import Compound, Shape
    ss = Shape(wrapped).solids()
    if not ss:
        raise LatticeError(f"{what} is empty.", "Check the cell size against the region.")
    return ss[0] if len(ss) == 1 else Compound(ss)


def _strut_brep(S, r, node: float):
    from build123d import Align, Cylinder, Plane, Pos, Sphere
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    parts = []
    for (a, b), ri in zip(S, r):
        d = b - a
        L = float(np.linalg.norm(d))
        parts.append((Plane(origin=tuple(a), z_dir=tuple(d / L)) * Cylinder(float(ri), L, align=(Align.CENTER, Align.CENTER, Align.MIN))).wrapped)
    N, R = _with_nodes(S, r, node)
    for (p, _q), rn in zip(N[len(S):], R[len(S):]):
        parts.append((Pos(*p) * Sphere(float(rn))).wrapped)
    return _boolean(BRepAlgoAPI_Fuse, parts[:1], parts[1:])


def _frame(a, b):
    d = b - a
    L = float(np.linalg.norm(d))
    z = d / L
    x = np.cross(z, [0.0, 0.0, 1.0] if abs(z[2]) < 0.9 else [1.0, 0.0, 0.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.column_stack([x, y, z, a]), L


def _strut_mesh(S, r, node: float):
    import manifold3d as m3
    parts = []
    for (a, b), ri in zip(S, r):
        M, L = _frame(a, b)
        parts.append(m3.Manifold.cylinder(L, float(ri), float(ri), STRUT_SEGMENTS).transform(M))
    N, R = _with_nodes(S, r, node)
    for (p, _q), rn in zip(N[len(S):], R[len(S):]):
        parts.append(m3.Manifold.sphere(float(rn), STRUT_SEGMENTS).translate(tuple(float(x) for x in p)))
    return m3.Manifold.batch_boolean(parts, m3.OpType.Add)


def _tpms_void(spec: dict, lo, hi, exact_box: bool, level: float | None = None):
    """The open space of the TPMS on its grid, as implicit functions (negative in the void), in about millimetres.
    A sheet |f| <= c leaves two channel systems, f > c and f < -c: each is the level set of a smooth function, so
    each is meshed on its own (one function |f| - c would have a crease in the middle of the wall, and the facets
    would misplace the surface by a fraction of the grid). They are cut to a box a little larger than the inner
    region, which manifold3d then cuts exactly (to the box, or to the region's own surface); exact_box cuts them to
    the box here instead, for when manifold3d is not installed (the cut edge is then placed by interpolation).
    Returns (functions, origin, h, note, info for the deviation, signs, margin)."""
    kind, form, cell = spec["kind"], spec.get("form", "sheet"), float(spec["cell"])
    h, n, note = _tpms_grid(spec, lo, hi)
    origin = lo - 3.37 * h                                             # off the box's planes: no grid point lies on a cut face
    ax = [origin[k] + h * np.arange(n[k]) for k in range(3)]
    X, Y, Z = np.meshgrid(*ax, indexing="ij")
    w = 2.0 * math.pi / cell
    ph = [(X - lo[0]) * w, (Y - lo[1]) * w, (Z - lo[2]) * w]
    rho = density_at(spec, np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1), lo, hi)
    c = (float(spec["level"]) if level is None else level) if rho is None else C.tpms_level(kind, form, rho).reshape(X.shape)
    f = C.tpms(kind, *ph)
    voids = [(c - f) / w, (f + c) / w] if form == "sheet" else [(c - f) / w]      # |grad f| is of order 1 per radian
    m = 0.0 if exact_box else 1.5 * h
    box = np.maximum.reduce([lo[0] - m - X, X - hi[0] - m, lo[1] - m - Y, Y - hi[1] - m, lo[2] - m - Z, Z - hi[2] - m])
    signs = [-1.0, 1.0] if form == "sheet" else [-1.0]                 # each function is (sign f + c) / w
    return [np.maximum(v, box) for v in voids], origin, h, note, (kind, form, cell, c, lo), signs, m


_FACET_LEVEL: dict = {}


def facet_level(spec: dict, h: float) -> float:
    """The level to mesh at so that the *faceted* solid has the density of the true one. Flat facets with their
    corners on a curved surface cut the corners off the open channels, so a mesh of the level c itself comes out a
    few percent too dense at practical grids. One cell is meshed at the same grid step and the level is moved (two
    secant steps) until that cell's faceted density equals the true density of level c."""
    kind, form, cell = spec["kind"], spec.get("form", "sheet"), float(spec["cell"])
    c = float(spec["level"])
    key = (kind, form, round(c, 6), round(cell / h, 4))
    if key in _FACET_LEVEL:
        return _FACET_LEVEL[key]
    one = {**spec, "resolution": max(6, int(round(cell / h))), "grading": None}
    lo, hi = np.zeros(3), np.full(3, cell)
    target = C.tpms_density(kind, form, c)
    use_m3 = _has_manifold()

    def dens(level):
        try:
            V, F, *_ = _tpms_mesh(one, lo, hi, not use_m3, level)
        except LatticeError:
            return 1.0
        if not use_m3:
            return 1.0 - C.mesh_volume(V, F) / cell ** 3
        import manifold3d as m3
        return 1.0 - float(_box_cut(_manifold(V, F, m3), lo, hi, m3).volume()) / cell ** 3

    c0, d0 = c, dens(c)
    slope = (C.tpms_density(kind, form, c + 0.02) - target) / 0.02
    c1 = c0 + (target - d0) / max(slope, 1e-6)
    d1 = dens(c1)
    if abs(d1 - d0) > 1e-9:
        c2 = c1 + (target - d1) * (c1 - c0) / (d1 - d0)
        if abs(dens(c2) - target) < abs(d1 - target):
            c1 = c2
    _FACET_LEVEL[key] = float(c1)
    return float(c1)


def _box_cut(man, lo, hi, m3):
    size = tuple(float(x) for x in (hi - lo))
    return man ^ m3.Manifold.cube(size).translate(tuple(float(x) for x in lo))


def _tpms_mesh(spec: dict, lo, hi, exact_box: bool, level: float | None = None):
    fields, origin, h, note, info, signs, m = _tpms_void(spec, lo, hi, exact_box, level)
    Vs, Fs, n = [], [], 0
    for f, sign in zip(fields, signs):
        V, F = C.iso_mesh(f, origin, h)
        if len(F):
            V, F = _merge(V, F, 1e-6 * h)
            V = _onto_level(V, info, sign, lo - m, hi + m, h)
            Vs.append(V)
            Fs.append(F + n)
            n += len(V)
    if not Fs:
        raise LatticeError("The lattice leaves no open space in this region.", "Use a thinner wall, a lower density "
                           "or a larger cell.", ["density", "wall"])
    if level is not None:                              # the deviation is measured against the level asked for
        info = (*info[:3], float(spec["level"]), info[4])
    return np.concatenate(Vs), np.concatenate(Fs), h, note, info


def _onto_level(V, info, sign: float, lo, hi, h: float):
    """Move the mesh's vertices onto the true level set (two Newton steps along the gradient; marching tetrahedra
    place them by linear interpolation, which is off by a fraction of the grid where the function curves). Vertices
    on the cutting box stay where they are, and no vertex moves more than half a grid step."""
    kind, _form, cell, c, lo0 = info
    if np.ndim(c):
        return V                                       # a graded level: left as interpolated
    w = 2.0 * math.pi / cell
    free = ((V > lo + 1e-6 * h) & (V < hi - 1e-6 * h)).all(axis=1)
    P = V[free].copy()
    for _ in range(2):
        ph = [(P[:, k] - lo0[k]) * w for k in range(3)]
        val = sign * C.tpms(kind, *ph) + c
        g = np.stack(C.tpms_gradient(kind, *ph), axis=1) * sign * w
        g2 = (g * g).sum(axis=1)
        step = np.where(g2 > (0.2 * w) ** 2, val / np.maximum(g2, 1e-12), 0.0)[:, None] * g
        n = np.linalg.norm(step, axis=1)
        step *= np.minimum(1.0, 0.5 * h / np.maximum(n, 1e-12))[:, None]
        P -= step
    out = V.copy()
    out[free] = np.clip(P, lo, hi)
    return out


def _merge(V, F, tol: float):
    """Edges shorter than tol collapsed (their two ends made one vertex) and the triangles that collapse with them
    dropped. Only vertices joined by an edge are merged: two sheets of the surface that touch at a point keep their
    own vertices there, so the mesh stays a closed manifold (merging by position alone would pinch it)."""
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    short = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1) < tol
    if not short.any():
        return V, F
    parent = np.arange(len(V))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in E[short].tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    root = np.array([find(i) for i in range(len(V))])
    F = root[F]
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    return _compact(V, F)


def _tpms_deviation(V, F, lo, hi, info, h: float) -> dict:
    """Distance of the facets' centroids from the true level set (first order: value / |gradient|), away from the
    box's cut faces."""
    kind, form, cell, c, lo0 = info
    if np.ndim(c):
        return {"max_mm": None, "mean_mm": None, "note": "graded level: not measured"}
    cen = V[F].mean(axis=1)
    cen = cen[((cen > lo + 2.0 * h) & (cen < hi - 2.0 * h)).all(axis=1)]
    if not len(cen):
        return {"max_mm": 0.0, "mean_mm": 0.0}
    w = 2.0 * math.pi / cell
    ph = [(cen[:, k] - lo0[k]) * w for k in range(3)]
    g = C.tpms_grad(kind, *ph) * w
    ok = g > 0.2 * w                                                   # not at a flat point of f, where value / gradient means nothing
    d = np.abs(C.tpms_solid(kind, form, *ph, c))[ok] / g[ok]
    if not len(d):
        return {"max_mm": None, "mean_mm": None}
    return {"max_mm": float(d.max()), "mean_mm": float(d.mean()),
            "note": "facet centroids against the level set, first order (value / |gradient|)"}


def _brep_voids(shape) -> int:
    return int(sum(max(0, len(s.shells()) - 1) for s in shape.solids()))


def _mesh_of(shape, tol: float = 0.02):
    from ..meshbody import MeshBody
    return MeshBody.from_shape(shape, tol).man


def _manifold(V, F, m3):
    man = m3.Manifold(m3.Mesh(vert_properties=np.asarray(V, np.float32), tri_verts=np.asarray(F, np.uint32)))
    if man.status() != m3.Error.NoError:
        raise LatticeError(f"The lattice mesh did not close ({man.status()}).", "Raise resolution, or change the cell.")
    return man


def _arrays(man):
    mesh = man.to_mesh64() if hasattr(man, "to_mesh64") else man.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3].astype(np.float64), np.asarray(mesh.tri_verts).astype(np.int64)


def _pieces(V, F):
    """The mesh's connected closed surfaces with their signed volumes: [(faces, volume)], largest first."""
    from ..recon import mesh as meshmod
    top = meshmod.topology(V, F)
    piece = np.asarray(top["_piece_of"])
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    vol = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    out = [(F[piece == k], float(vol[piece == k].sum())) for k in range(int(top["pieces"]))]
    return sorted(out, key=lambda t: -abs(t[1]))


def _compact(V, F):
    used = np.unique(F)
    remap = -np.ones(len(V), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return V[used], remap[F]


def _from_manifold(man):
    """A manifold3d body as one kernel solid of planar faces: the outside surface as its shell and every closed
    void inside as an inner shell (so the volume is the material's, and the voids can be counted). Pieces that
    touch nothing (a fragment of lattice cut off at the region's edge) are left out and counted."""
    from build123d import Solid
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS, TopoDS_Solid
    from ..recipes.meshsolid import solid_from_mesh
    V, F = _arrays(man)
    V, F = _merge(V, F, 1e-6)                         # manifold3d keeps coincident vertices apart; the kernel wants one
    if len(F) > MESH_TRIANGLES:
        raise LatticeError(f"The lattice is {len(F):,} triangles (limit {MESH_TRIANGLES:,}).",
                           "Use a larger cell, a smaller region or a lower resolution.", ["cell"])
    parts = _pieces(V, F)
    solids = [(Fk, v) for Fk, v in parts if v > 0]
    voids = [(Fk, v) for Fk, v in parts if v < 0]
    if not solids:
        raise LatticeError("The lattice left no material.", "Use a higher density or a thicker wall.")
    main, islands = solids[0], solids[1:]
    B = BRep_Builder()
    so = TopoDS_Solid()
    B.MakeSolid(so)
    B.Add(so, solid_from_mesh(*_compact(V, main[0])).shells()[0].wrapped)
    for Fk, _v in voids:
        sh = solid_from_mesh(*_compact(V, Fk[:, ::-1])).shells()[0].wrapped       # built facing out, then turned in
        B.Add(so, TopoDS.Shell_s(sh.Reversed()) if hasattr(TopoDS, "Shell_s") else TopoDS.Shell(sh.Reversed()))
    solid = Solid(so)
    want = main[1] + sum(v for _f, v in voids)
    if abs(solid.volume - want) > 1e-6 * abs(want) + 1e-6:
        raise LatticeError("The mesh body's shells did not assemble into one solid.", "Try another cell size or output.")
    info = {"triangles": int(len(main[0]) + sum(len(f) for f, _v in voids)), "trapped_voids": len(voids)}
    if islands:
        info["fragments_removed"] = {"count": len(islands), "volume_mm3": float(sum(v for _f, v in islands)),
                                     "note": "pieces of lattice cut off at the region's edge that touched nothing"}
    return solid, info


def _main_solid(shape, rep: dict):
    """The largest solid of a B-rep result; smaller ones (lattice cut off at the region's edge, touching nothing) are
    left out and counted in the report."""
    ss = sorted(shape.solids(), key=lambda x: -x.volume)
    if len(ss) > 1:
        rep["fragments_removed"] = {"count": len(ss) - 1, "volume_mm3": float(sum(x.volume for x in ss[1:])),
                                    "note": "pieces of lattice cut off at the region's edge that touched nothing"}
    return ss[0]


def fill(shape, spec: dict):
    """The body with the lattice in its region. Returns the kernel solid; the report is kept in REPORTS[spec_key]
    (and noted on the build). A lattice that cannot be built is a RecipeError on the feature "lattice"."""
    from ..recipes.base import RecipeError
    try:
        return _fill(shape, spec)
    except LatticeError as e:
        raise RecipeError(str(e), "lattice", e.hint, e.params) from None


def _fill(shape, spec: dict):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    t0 = time.perf_counter()
    kind = spec["kind"]
    output = spec.get("output") or "brep"
    if output == "auto":
        output = plan(shape, spec)["output"]
    body, zone, inner = region_of(shape, spec)
    lo, hi = _bbox(inner)
    skin = float(spec.get("skin") or 0.0)
    rep = {"kind": kind, "output": output, "cells": [int(x) for x in _cells(lo, hi, float(spec["cell"]))],
           "inner_volume_mm3": float(inner.volume), "skin_mm": skin, "volume_before_mm3": float(body.volume)}
    if output == "mesh" and not _has_manifold():
        raise LatticeError("The mesh route needs manifold3d, which is not installed.", "pip install 'form-studio[organic]'.")
    if not C.is_tpms(kind):
        S, r = _struts_in(spec, lo, hi)
        if not len(S):
            raise LatticeError("No strut falls inside the region.", "Use a smaller cell.", ["cell"])
        rep.update(struts=int(len(S)), strut_d_mm=[float(2 * r.min()), float(2 * r.max())],
                   node_d_mm=[float(2 * r.min() * spec["node"]), float(2 * r.max() * spec["node"])])
        if output == "brep":
            from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
            lat = _strut_brep(S, r, float(spec["node"]))
            if skin > 0:                                   # the open space lies inside the body: cut it out
                void = _solid_of(_boolean(BRepAlgoAPI_Cut, [inner.wrapped], [lat]), "The open space of the lattice")
                void_volume = float(void.volume)
                out = _solid_of(_boolean(BRepAlgoAPI_Cut, [body.wrapped], [x.wrapped for x in void.solids()]),
                                "The lattice in the body")
            else:                                          # no skin: the lattice cut to the region, joined to the rest
                core = _solid_of(_boolean(BRepAlgoAPI_Common, [lat], [inner.wrapped]), "The lattice inside the region")
                void_volume = float(inner.volume) - float(core.volume)
                rest = None if zone is body else body - zone
                if rest is None or not rest.solids() or rest.volume < 1e-9:
                    out = core
                else:
                    out = _solid_of(_boolean(BRepAlgoAPI_Fuse, [rest.wrapped], [x.wrapped for x in core.solids()]),
                                    "The lattice joined to the body")
            out = _main_solid(out, rep)
            if not out.is_valid:
                raise LatticeError("OCCT made an invalid solid from these struts.", "Try output=\"mesh\", or change "
                                   "node (the node sphere's size against the strut) a little.", ["output", "node"])
            rep.update(representation="exact B-rep: cylinders and node spheres fused in OCCT and cut into the body; "
                       "written to STEP", faces=len(out.faces()), trapped_voids=_brep_voids(out),
                       deviation={"max_mm": 0.0, "note": "exact surfaces"})
        else:
            void = _mesh_of(inner) - _strut_mesh(S, r, float(spec["node"]))
            void_volume = float(void.volume())
            out, rep2 = _from_manifold(_mesh_of(body) - void)
            rep.update(rep2, representation=f"mesh body: struts as {STRUT_SEGMENTS}-sided prisms and faceted spheres, "
                       "combined by manifold3d; not written to STEP",
                       deviation={"max_mm": float(r.max()) * (1.0 - math.cos(math.pi / STRUT_SEGMENTS)),
                                  "note": "sag of the facets under the round strut (computed); the body's own faces "
                                          "are tessellated at 0.02 mm"})
    else:
        boxed = _is_box(inner, lo, hi)
        use_m3 = _has_manifold()
        if not boxed and not use_m3:
            raise LatticeError("Cutting a TPMS to a region that is not a box needs manifold3d.",
                               "pip install 'form-studio[organic]', or give region={\"min\", \"max\"} with skin=0.")
        level = None
        if not spec.get("grading"):
            level = facet_level(spec, _tpms_grid(spec, lo, hi)[0])
        V, F, h, note, info = _tpms_mesh(spec, lo, hi, not use_m3, level)
        dev = _tpms_deviation(V, F, lo, hi, info, h)
        rep.update(level=float(spec["level"]), level_meshed=level,
                   level_note="meshed at a level moved so that the faceted solid has the true cell's density"
                   if level is not None else "a graded level is meshed as it is: the facets read a little dense",
                   grid_mm=round(h, 5), grid_note=note)
        void = None
        if use_m3:
            import manifold3d as m3
            void = _manifold(V, F, m3)
            void = _box_cut(void, lo, hi, m3) if boxed else void ^ _mesh_of(inner)
            if hasattr(void, "simplify"):
                void = void.simplify(SIMPLIFY_MM)
                if dev.get("max_mm") is not None:
                    dev = {**dev, "max_mm": dev["max_mm"] + SIMPLIFY_MM,
                           "note": dev["note"] + f"; then facets merged within {SIMPLIFY_MM:g} mm"}
            V, F = _merge(*_arrays(void), 1e-6)
        rep.update(lattice_facets=int(len(F)), deviation=dev)
        if output == "brep":
            from ..recipes.meshsolid import solid_from_mesh
            tools = [solid_from_mesh(*_compact(V, Fk)) for Fk, v in _pieces(V, F) if v > 0]
            void_volume = float(sum(t.volume for t in tools))
            out = _main_solid(_solid_of(_boolean(BRepAlgoAPI_Cut, [body.wrapped], [t.wrapped for t in tools]),
                                        "The lattice in the body"), rep)
            if not out.is_valid:
                raise LatticeError("OCCT made an invalid solid cutting the faceted lattice from the body.",
                                   "Use output=\"mesh\".", ["output"])
            rep.update(representation="faceted B-rep: the TPMS as planar triangles, cut into the exact body in OCCT; "
                       "a valid solid, written to STEP with facets where the lattice is",
                       faces=len(out.faces()), trapped_voids=_brep_voids(out))
        else:
            void_volume = float(void.volume())
            out, rep2 = _from_manifold(_mesh_of(body) - void)
            rep.update(rep2, representation="mesh body: the TPMS as marching-tetrahedra facets, combined with the "
                       "body's facets by manifold3d; not written to STEP")
    rep["core_volume_mm3"] = float(inner.volume) - void_volume
    rep["relative_density_measured"] = rep["core_volume_mm3"] / float(inner.volume) if inner.volume > 0 else None
    rep["volume_mm3"] = float(out.volume)
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    REPORTS[spec_key(spec)] = rep
    try:
        from ..craft._common import note as _note
        _note(f"Lattice ({C.LABEL[kind]}): {rep['representation'].split(':')[0]}; core relative density "
              f"{rep['relative_density_measured']:.3f} (measured on the built solid).")
    except Exception:                                          # noqa: BLE001 - outside a build there is nowhere to note it
        pass
    return out


# ── worker ops ───────────────────────────────────────────────────────────────────────────────────────────────────

def op_lattice_plan(key, recipe_id, values, spec, tol=0.05):
    """Decide the output for a lattice in the head revision's body (worker)."""
    from .. import kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    base = getattr(model["recipe"], "_form_lattice_base", None)
    shape = model["shape"]
    if base is not None:                                   # the design already carries a lattice: plan on its body
        shape = base(model["values"])
    try:
        return plan(shape, spec)
    except LatticeError as e:
        return {"error": str(e), "hint": e.hint, "params": e.params}


def op_lattice_report(key, recipe_id, values, tol=0.05):
    """The report of the lattice the head revision carries (worker): from the build that made it, or built again."""
    from .. import kernel
    model = kernel._get_near(key, recipe_id, values, tol)
    recipe = model["recipe"]
    spec = getattr(recipe, "_form_lattice", None)
    if not spec:
        return {"error": "This design carries no lattice."}
    k = spec_key(spec)
    if k not in REPORTS:
        recipe.build(model["values"])                     # the wrapped build runs fill() again and records it
    return {"spec": spec, "report": REPORTS.get(k)}


KERNEL_OPS = {"lattice_plan": op_lattice_plan, "lattice_report": op_lattice_report}
