"""Unit cells: the implicit functions of the TPMS, the struts of the truss lattices, and what follows from them
alone (relative density, wall thickness, pore size, surface area). numpy only: no kernel.

TPMS, as the usual nodal (trigonometric level-set) approximations with X = 2 pi x / a:

    gyroid      sin X cos Y + sin Y cos Z + sin Z cos X
    schwarz_p   cos X + cos Y + cos Z
    schwarz_d   sin X sin Y sin Z + sin X cos Y cos Z + cos X sin Y cos Z + cos X cos Y sin Z      ("diamond")
    neovius     3 (cos X + cos Y + cos Z) + 4 cos X cos Y cos Z

Two solids from one function f: a **sheet** |f| <= c (a wall about the surface, both sides open) and a **network**
f <= c (one of the two channel systems filled). Each f changes sign under a rigid motion of space (a half-period
shift, or the point reflection for the gyroid), so the network at c = 0 fills exactly half: relative density 0.5.

Strut lattices, nodes in units of the cell a:

    bcc      centre to the 8 corners
    fcc      each face centre to that face's 4 corners
    octet    fcc plus the 12 struts between neighbouring face centres (Deshpande, Fleck and Ashby 2001)
    kelvin   the 36 edges of the truncated octahedron (0, ±1, ±2) a / 4 about the cell centre

A strut is a cylinder of radius r with a sphere of radius r on each node: the union of capsules. To first order the
relative density is pi r² L / a³ with L the strut length per cell (4√3 a, 6√2 a, 12√2 a, 6√2 a); the overlap at the
nodes makes the real value lower, so density() measures the union itself.
"""
from __future__ import annotations

import itertools
import math

import numpy as np

TPMS = ("gyroid", "schwarz_p", "schwarz_d", "neovius")
STRUT = ("bcc", "fcc", "octet", "kelvin")
KINDS = TPMS + STRUT
ALIASES = {"diamond": "schwarz_d", "schwarz-d": "schwarz_d", "schwarzd": "schwarz_d", "d": "schwarz_d",
           "schwarz-p": "schwarz_p", "schwarzp": "schwarz_p", "primitive": "schwarz_p", "p": "schwarz_p",
           "g": "gyroid", "octet_truss": "octet", "octet-truss": "octet", "tetrakaidecahedron": "kelvin"}
LABEL = {"gyroid": "Gyroid", "schwarz_p": "Schwarz P", "schwarz_d": "Schwarz D (diamond)", "neovius": "Neovius",
         "bcc": "BCC", "fcc": "FCC", "octet": "Octet truss", "kelvin": "Kelvin cell"}
FORMS = ("sheet", "network")
# the largest |f| of each function: a level beyond it is all solid (network) or leaves no wall to open (sheet)
F_MAX = {"gyroid": 1.5, "schwarz_p": 3.0, "schwarz_d": math.sqrt(2.0), "neovius": 13.0}
# Area of the minimal surface in a unit cube of the cell (dimensionless, A a² per cell), for the three whose value is
# published: Schoen, "Infinite periodic minimal surfaces without self-intersections", NASA TN D-5541 (1970), as
# tabulated in Jung and Torquato, Phys. Rev. E 72, 056319 (2005), Table I. The nodal approximation above is not the
# minimal surface itself: its area differs by under 1 % (tests/test_lattice.py measures it).
PUBLISHED_AREA = {"schwarz_p": 2.3451, "gyroid": 3.0915, "schwarz_d": 3.8378}
AREA_SOURCE = "Schoen 1970 (NASA TN D-5541); Jung and Torquato 2005, Phys. Rev. E 72, 056319, Table I"


class LatticeError(ValueError):
    """A lattice that cannot be specified or built, with a way forward."""

    def __init__(self, msg: str, hint: str = "", params=None):
        super().__init__(msg)
        self.hint = hint
        self.params = list(params or [])


def kind_of(name: str) -> str:
    k = str(name or "").strip().lower().replace(" ", "_")
    k = ALIASES.get(k, k)
    if k not in KINDS:
        raise ValueError(f"Unknown lattice “{name}”. TPMS: {', '.join(TPMS)} (diamond is schwarz_d). "
                         f"Struts: {', '.join(STRUT)}.")
    return k


def is_tpms(kind: str) -> bool:
    return kind in TPMS


# ── TPMS ───────────────────────────────────────────────────────────────────────────────────────────────────────

def tpms(kind: str, X, Y, Z):
    """f at phases X, Y, Z (radians: 2 pi x / a)."""
    sx, sy, sz, cx, cy, cz = np.sin(X), np.sin(Y), np.sin(Z), np.cos(X), np.cos(Y), np.cos(Z)
    if kind == "gyroid":
        return sx * cy + sy * cz + sz * cx
    if kind == "schwarz_p":
        return cx + cy + cz
    if kind == "schwarz_d":
        return sx * sy * sz + sx * cy * cz + cx * sy * cz + cx * cy * sz
    if kind == "neovius":
        return 3.0 * (cx + cy + cz) + 4.0 * cx * cy * cz
    raise ValueError(kind)


def tpms_gradient(kind: str, X, Y, Z):
    """grad f with respect to the phases, as three arrays (multiply by 2 pi / a for mm)."""
    sx, sy, sz, cx, cy, cz = np.sin(X), np.sin(Y), np.sin(Z), np.cos(X), np.cos(Y), np.cos(Z)
    if kind == "gyroid":
        g = (cx * cy - sz * sx, -sx * sy + cy * cz, -sy * sz + cz * cx)
    elif kind == "schwarz_p":
        g = (-sx, -sy, -sz)
    elif kind == "schwarz_d":
        g = (cx * sy * sz + cx * cy * cz - sx * sy * cz - sx * cy * sz,
             sx * cy * sz - sx * sy * cz + cx * cy * cz - cx * sy * sz,
             sx * sy * cz - sx * cy * sz - cx * sy * sz + cx * cy * cz)
    elif kind == "neovius":
        g = (-3.0 * sx - 4.0 * sx * cy * cz, -3.0 * sy - 4.0 * cx * sy * cz, -3.0 * sz - 4.0 * cx * cy * sz)
    else:
        raise ValueError(kind)
    return g


def tpms_grad(kind: str, X, Y, Z):
    """|grad f| with respect to the phases (multiply by 2 pi / a for mm)."""
    g = tpms_gradient(kind, X, Y, Z)
    return np.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2)


def _phase_grid(n: int):
    t = (np.arange(n) + 0.5) * (2.0 * math.pi / n)
    return np.meshgrid(t, t, t, indexing="ij")


def _soft(d, h):
    """Volume fraction of a cell of size h whose centre is at signed distance d from the surface (negative inside):
    a linear ramp over one cell, which makes the sum second-order in h."""
    return np.clip(0.5 - d / h, 0.0, 1.0)


def tpms_solid(kind: str, form: str, X, Y, Z, c):
    """The implicit function of the solid: negative inside. c may be an array (a graded lattice)."""
    f = tpms(kind, X, Y, Z)
    return (np.abs(f) - c) if form == "sheet" else (f - c)


def tpms_density(kind: str, form: str, c: float, n: int = 72) -> float:
    """Relative density of the sheet |f| <= c or the network f <= c, by a smoothed count on n³ points of one cell."""
    X, Y, Z = _phase_grid(n)
    g = np.maximum(tpms_grad(kind, X, Y, Z), 1e-9)
    d = tpms_solid(kind, form, X, Y, Z, c) / g              # distance in phase units, first order
    return float(_soft(d, 2.0 * math.pi / n).mean())


_LEVELS: dict = {}


def _level_table(kind: str, form: str):
    key = (kind, form)
    if key not in _LEVELS:
        top = F_MAX[kind]
        cs = np.linspace(0.0 if form == "sheet" else -top, top, 49)
        _LEVELS[key] = (cs, np.array([tpms_density(kind, form, float(c), 48) for c in cs]))
    return _LEVELS[key]


def tpms_level(kind: str, form: str, density) -> np.ndarray | float:
    """The level c that gives a relative density: the inverse of tpms_density. One number: from a table of 49 levels,
    then three secant steps on the density itself (to about 0.0005). An array (a graded lattice): the table alone,
    linear between its levels (to about 0.005)."""
    cs, rho = _level_table(kind, form)
    out = np.interp(np.asarray(density, float), rho, cs)
    if np.ndim(out):
        return out
    c0, want = float(out), float(density)
    d0 = tpms_density(kind, form, c0, 48)
    c1 = c0 + (want - d0) * float(np.gradient(cs, rho)[np.argmin(np.abs(cs - c0))])
    for _ in range(3):
        d1 = tpms_density(kind, form, c1, 48)
        if abs(d1 - want) < 2e-4 or abs(d1 - d0) < 1e-12:
            break
        c0, d0, c1 = c1, d1, c1 + (want - d1) * (c1 - c0) / (d1 - d0)
    return float(c1)


def tpms_wall(kind: str, c: float, cell: float, n: int = 64) -> dict:
    """The wall of a sheet |f| <= c in mm: to first order 2 c / |grad f| at each point of the surface f = 0."""
    X, Y, Z = _phase_grid(n)
    f = tpms(kind, X, Y, Z)
    g = tpms_grad(kind, X, Y, Z)
    near = np.abs(f) < np.maximum(g, 1e-9) * (2.0 * math.pi / n)       # within one cell of the surface
    gs = g[near] * (2.0 * math.pi / cell)
    t = 2.0 * c / np.maximum(gs, 1e-12)
    return {"min_mm": float(t.min()), "mean_mm": float(t.mean()), "max_mm": float(np.percentile(t, 99))}


def tpms_level_for_wall(kind: str, wall: float, cell: float) -> float:
    """The level whose mean wall is `wall` mm (the wall is linear in c to first order)."""
    unit = tpms_wall(kind, 1.0, cell)["mean_mm"]
    return float(wall) / unit


def tpms_area(kind: str, n: int = 64) -> float:
    """Area of the surface f = 0 in a unit cube of the cell (A a² per cell), measured on its marching-tetrahedra mesh
    (n cells along the cube; the facets under-read a curved surface by about (1 / n)²)."""
    t = np.linspace(0.0, 2.0 * math.pi, n + 1)
    X, Y, Z = np.meshgrid(t, t, t, indexing="ij")
    V, F = iso_mesh(tpms(kind, X, Y, Z), (0.0, 0.0, 0.0), 1.0 / n)
    return mesh_area(V, F)


def tpms_pore(kind: str, form: str, c: float, cell: float, n: int = 64) -> float:
    """Diameter (mm) of the largest sphere that fits in the open space, first order: twice the largest distance to
    the solid, with the distance taken as (value of the implicit function) / |grad|, capped by the grid."""
    X, Y, Z = _phase_grid(n)
    s = tpms_solid(kind, form, X, Y, Z, c)
    void = s > 0
    if not void.any():
        return 0.0
    return 2.0 * float(_edt(void).max()) * cell / n


def _edt(mask: np.ndarray) -> np.ndarray:
    """Distance (in cells) from each True cell to the nearest False one, on a periodic grid: exact Euclidean by the
    separable lower-envelope pass in each axis (Felzenszwalb and Huttenlocher 2012), done here by brute force over the
    axis, which is fine at 64³."""
    n = mask.shape[0]
    big = float(4 * n * n)
    d2 = np.where(mask, big, 0.0)
    off = np.arange(n)
    k = np.minimum(off, n - off).astype(float) ** 2            # periodic squared offsets
    for ax in range(3):
        d2 = np.moveaxis(d2, ax, -1)
        idx = (np.arange(n)[:, None] + np.arange(n)[None, :]) % n      # (i, j): cell i + offset j
        d2 = (d2[..., idx] + k[None, :]).min(axis=-1)
        d2 = np.moveaxis(d2, -1, ax)
    return np.sqrt(d2)


# ── struts ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _cell_edges(kind: str) -> list:
    """The struts written for one cell, as pairs of points in units of a (duplicates between cells removed later)."""
    c = (0.5, 0.5, 0.5)
    corners = list(itertools.product((0.0, 1.0), repeat=3))
    faces = []
    for ax in range(3):
        for s in (0.0, 1.0):
            fc = [0.5, 0.5, 0.5]
            fc[ax] = s
            faces.append(tuple(fc))
    if kind == "bcc":
        return [(c, p) for p in corners]
    fcc = [(f, p) for f in faces for p in corners if sum(abs(f[i] - p[i]) < 1e-9 for i in range(3)) == 1
           and abs(sum((f[i] - p[i]) ** 2 for i in range(3)) - 0.5) < 1e-9]
    if kind == "fcc":
        return fcc
    if kind == "octet":
        inner = [(f, g) for f, g in itertools.combinations(faces, 2)
                 if abs(sum((f[i] - g[i]) ** 2 for i in range(3)) - 0.5) < 1e-9]
        return fcc + inner
    if kind == "kelvin":
        vs = set()
        for perm in itertools.permutations((0, 1, 2)):
            for s1 in (-1, 1):
                for s2 in (-1, 1):
                    v = [0.0, 0.0, 0.0]
                    v[perm[1]] = s1 * 0.25
                    v[perm[2]] = s2 * 0.5
                    vs.add(tuple(round(x + 0.5, 9) for x in v))
        vs = sorted(vs)
        return [(p, q) for p, q in itertools.combinations(vs, 2)
                if abs(sum((p[i] - q[i]) ** 2 for i in range(3)) - 0.125) < 1e-9]
    raise ValueError(kind)


def struts(kind: str, counts=(1, 1, 1)) -> np.ndarray:
    """Every strut of a block of cells, once: (m, 2, 3) end points in units of a."""
    base = np.array(_cell_edges(kind), float)                          # (e, 2, 3)
    out = []
    for i in range(int(counts[0])):
        for j in range(int(counts[1])):
            for k in range(int(counts[2])):
                out.append(base + np.array([i, j, k], float))
    S = np.concatenate(out)
    key = np.where(_lex_less(S[:, 0], S[:, 1])[:, None, None], S, S[:, ::-1])
    _, first = np.unique(np.round(key.reshape(len(key), 6), 6), axis=0, return_index=True)
    return key[np.sort(first)]


def _lex_less(A, B):
    A, B = np.round(A, 6), np.round(B, 6)
    out = np.zeros(len(A), bool)
    done = np.zeros(len(A), bool)
    for i in range(3):
        lt, gt = (A[:, i] < B[:, i]) & ~done, (A[:, i] > B[:, i]) & ~done
        out |= lt
        done |= lt | gt
    return out


def strut_length_per_cell(kind: str) -> float:
    """Total strut length that belongs to one cell of an endless lattice, in units of a: each strut counted by the
    share of it that lies in the cell (a strut on a face is shared by two cells, on an edge by four)."""
    S = struts(kind, (3, 3, 3)) - 1.0                                  # the middle cell is [0, 1]³
    t = (np.arange(64) + 0.5) / 64
    P = S[:, 0, None, :] + t[None, :, None] * (S[:, 1] - S[:, 0])[:, None, :]      # points along each strut
    w = np.ones(P.shape[:2])
    for ax in range(3):
        x = P[..., ax]
        w *= np.where((x > 1e-9) & (x < 1 - 1e-9), 1.0, np.where((np.abs(x) < 1e-9) | (np.abs(x - 1) < 1e-9), 0.5, 0.0))
    L = np.linalg.norm(S[:, 1] - S[:, 0], axis=1)
    return float((w.mean(axis=1) * L).sum())


STRUT_LENGTH = {"bcc": 4 * math.sqrt(3), "fcc": 6 * math.sqrt(2), "octet": 12 * math.sqrt(2), "kelvin": 6 * math.sqrt(2)}


def strut_density_first_order(kind: str, radius: float, cell: float) -> float:
    """pi r² L / a³: thin struts, the overlap at the nodes not taken off."""
    return math.pi * (radius / cell) ** 2 * STRUT_LENGTH[kind]


def capsule_distance(P: np.ndarray, S: np.ndarray, r) -> np.ndarray:
    """Signed distance from points P (n, 3) to the union of capsules about segments S (m, 2, 3): negative inside.
    r is one radius or one per strut."""
    A, B = S[:, 0], S[:, 1]
    AB = B - A
    L2 = np.maximum((AB * AB).sum(axis=1), 1e-18)
    rr = np.broadcast_to(np.asarray(r, float), (len(S),))
    out = np.full(len(P), np.inf)
    for i in range(0, len(P), 20000):
        Q = P[i:i + 20000]
        best = np.full(len(Q), np.inf)
        for j in range(0, len(S), 256):
            a, ab, l2, rj = A[j:j + 256], AB[j:j + 256], L2[j:j + 256], rr[j:j + 256]
            t = np.clip(((Q[:, None, :] - a[None]) * ab[None]).sum(axis=2) / l2[None], 0.0, 1.0)
            d = np.linalg.norm(Q[:, None, :] - (a[None] + t[..., None] * ab[None]), axis=2) - rj[None]
            best = np.minimum(best, d.min(axis=1))
        out[i:i + 20000] = best
    return out


def strut_density(kind: str, radius: float, cell: float, n: int = 56) -> float:
    """Relative density of the union of capsules in an endless lattice, by a smoothed count on n³ points of a cell."""
    S = struts(kind, (3, 3, 3)) - 1.0
    r = radius / cell
    keep = (np.minimum(S[:, 0], S[:, 1]) < 1 + r).all(axis=1) & (np.maximum(S[:, 0], S[:, 1]) > -r).all(axis=1)
    t = (np.arange(n) + 0.5) / n
    P = np.stack(np.meshgrid(t, t, t, indexing="ij"), axis=-1).reshape(-1, 3)
    d = capsule_distance(P, S[keep], r)
    return float(_soft(d, 1.0 / n).mean())


def strut_radius_for_density(kind: str, density: float, cell: float) -> float:
    """The strut radius (mm) that gives a relative density: bisection on strut_density."""
    lo, hi = 1e-3 * cell, 0.5 * cell
    for _ in range(26):
        mid = 0.5 * (lo + hi)
        if strut_density(kind, mid, cell, 28) < density:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def strut_pore(kind: str, radius: float, cell: float, n: int = 40) -> float:
    """Diameter (mm) of the largest sphere that fits between the struts of an endless lattice."""
    S = struts(kind, (3, 3, 3)) - 1.0
    t = (np.arange(n) + 0.5) / n
    P = np.stack(np.meshgrid(t, t, t, indexing="ij"), axis=-1).reshape(-1, 3)
    d = capsule_distance(P, S, radius / cell)
    return max(0.0, 2.0 * float(d.max()) * cell)


def strut_min_length(kind: str) -> float:
    S = np.array(_cell_edges(kind), float)
    return float(np.linalg.norm(S[:, 1] - S[:, 0], axis=1).min())


# ── a mesh of an implicit function on a grid: marching tetrahedra ───────────────────────────────────────────────

_CUBE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]])
_TETS = np.array([[0, 1, 3, 7], [0, 1, 5, 7], [0, 2, 3, 7], [0, 2, 6, 7], [0, 4, 5, 7], [0, 4, 6, 7]])


def iso_mesh(f: np.ndarray, origin, h: float):
    """The surface f = 0 of values on a regular grid (f[i, j, k] at origin + h (i, j, k)), as welded triangles facing
    where f grows (out of the solid, f < 0 inside). Six tetrahedra per cube, all sharing the cube's long diagonal, so
    neighbouring cubes agree and a solid that does not reach the grid's border comes out closed. A value of exactly 0
    is nudged to a tiny positive number, so no triangle collapses onto a grid point."""
    f = np.where(f == 0.0, 1e-12, np.asarray(f, float))
    nx, ny, nz = f.shape
    fl = f.reshape(-1)
    inside = f < 0
    # the cubes the surface passes through
    m = np.zeros((nx - 1, ny - 1, nz - 1), np.int8)
    for dx, dy, dz in _CUBE:
        m += inside[dx:nx - 1 + dx, dy:ny - 1 + dy, dz:nz - 1 + dz]
    ijk = np.argwhere((m > 0) & (m < 8))
    if not len(ijk):
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    corners = ijk[:, None, :] + _CUBE[None]
    vid = (corners[..., 0] * ny + corners[..., 1]) * nz + corners[..., 2]            # (c, 8) grid vertex ids
    tv = vid[:, _TETS].reshape(-1, 4)
    ins = fl[tv] < 0
    code = ins @ np.array([1, 2, 4, 8])
    ok = (code > 0) & (code < 15)
    tv, code = tv[ok], code[ok]
    nv = fl.size
    G = lambda ids: np.stack([ids // (ny * nz), (ids // nz) % ny, ids % nz], axis=-1).astype(float)   # noqa: E731

    def ek(a, b):
        return np.minimum(a, b) * nv + np.maximum(a, b)

    tris, outward = [], []
    for c in range(1, 15):
        t = tv[code == c]
        if not len(t):
            continue
        i_in = [i for i in range(4) if c >> i & 1]
        i_out = [i for i in range(4) if not c >> i & 1]
        go = G(t[:, i_out]).mean(axis=1) - G(t[:, i_in]).mean(axis=1)
        if len(i_in) in (1, 3):
            lone, rest = (i_in[0], i_out) if len(i_in) == 1 else (i_out[0], i_in)
            tris.append(np.stack([ek(t[:, lone], t[:, r]) for r in rest], axis=1))
            outward.append(go)
        else:
            a, b = i_in
            c1, d1 = i_out
            e = [ek(t[:, a], t[:, c1]), ek(t[:, a], t[:, d1]), ek(t[:, b], t[:, d1]), ek(t[:, b], t[:, c1])]
            tris.append(np.stack([e[0], e[1], e[2]], axis=1))
            tris.append(np.stack([e[0], e[2], e[3]], axis=1))
            outward += [go, go]
    K = np.concatenate(tris)
    out = np.concatenate(outward)
    uk, Fl = np.unique(K.reshape(-1), return_inverse=True)
    F = Fl.reshape(-1, 3).astype(np.int64)
    ea, eb = uk // nv, uk % nv
    fa, fb = fl[ea], fl[eb]
    s = fa / (fa - fb)
    V = (G(ea) + s[:, None] * (G(eb) - G(ea))) * h + np.asarray(origin, float)
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    flip = np.einsum("ij,ij->i", n, out) < 0
    F[flip] = F[flip][:, ::-1]
    keep = np.linalg.norm(n, axis=1) > 1e-14 * h * h
    return V, F[keep]


def mesh_volume(V: np.ndarray, F: np.ndarray) -> float:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def mesh_area(V: np.ndarray, F: np.ndarray) -> float:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2.0)


__all__ = ["LatticeError", "TPMS", "STRUT", "KINDS", "LABEL", "FORMS", "PUBLISHED_AREA", "AREA_SOURCE", "kind_of", "is_tpms", "tpms",
           "tpms_gradient", "tpms_grad", "tpms_solid", "tpms_density", "tpms_level", "tpms_wall", "tpms_level_for_wall", "tpms_area",
           "tpms_pore", "struts", "strut_length_per_cell", "STRUT_LENGTH", "strut_density_first_order",
           "capsule_distance", "strut_density", "strut_radius_for_density", "strut_pore", "strut_min_length",
           "iso_mesh", "mesh_volume", "mesh_area"]
