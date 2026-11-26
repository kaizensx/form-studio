"""Analysis you can see on the model: maps, measurements and print orientations, all computed from the real geometry.

Nothing here is a strength analysis and nothing is invented. Every result says how it is known (`computed`),
on which tessellation, and what it does not tell you.

Maps (per-vertex scalar fields on a refined copy of the kernel tessellation, so the viewport can colour the part):
  thickness  opposing-wall distance by casting a ray inward from each sample: the same ray the "Thinnest wall" check casts
  overhang   angle past vertical in the chosen print orientation; plate contact and bridged ceilings are distinct classes
  section    area of the horizontal slice at each height (a chart), with the weakest neck marked on the model
  features   things smaller than the nozzle can print: small holes, narrow gaps, walls under one nozzle width

Measure: distances between points, what is under a point (face type, area, tilt to the bed, exact hole diameter from
the B-rep), and a circle fitted to mesh edges where there is no B-rep.

Orient: every way the part can rest on a flat face of its convex hull, ranked by a score whose terms are shown.

The top of this file is plain numpy and safe to import anywhere. Functions that take a kernel `model` run inside the
kernel worker only (form/kernel.py registers `KERNEL_OPS`).
"""
from __future__ import annotations

import base64
import io
import math

import numpy as np
from . import fsutil

ANALYSIS_VERSION = 6
MAPS = ("thickness", "overhang", "section", "features")
MAP_LABEL = {"thickness": "Wall thickness", "overhang": "Overhangs", "section": "Layer cross-section", "features": "Small features"}
TOL = 0.05                       # tessellation tolerance (mm) every map and mesh measurement is computed on

# colours (sRGB). The same values as the app's Theme: clay = fine, amber = review, signal = fail, datum = settled.
CLAY, CLAY_DEEP = (216, 211, 200), (122, 148, 150)
AMBER, SIGNAL, DATUM, BLUEPRINT = (233, 184, 96), (255, 111, 81), (62, 230, 255), (134, 168, 255)

NAMED = {"as_modelled": (0, 0), "on_back": (90, 0), "on_front": (-90, 0), "on_left": (0, 90), "on_right": (0, -90), "inverted": (180, 0)}
NAMED_LABEL = {"as_modelled": "Base down", "on_back": "On its back", "on_front": "On its front",
               "on_left": "On left side", "on_right": "On right side", "inverted": "Upside down"}

# auto-orient: the score is a weighted sum of these terms, each scaled 0..1 across the candidates (0 = best candidate).
ORIENT_WEIGHTS = {"support": 0.35, "overhang": 0.20, "contact": 0.15, "height": 0.10, "layers": 0.20}
ORIENT_TERMS = {
    "support": "support volume: overhanging area times its height above the plate (mm³, an upper bound)",
    "overhang": "surface steeper than 45° that is not on the plate (mm²)",
    "contact": "flat area on the plate (mm², more is better)",
    "height": "print height (mm)",
    "layers": "smallest layer cross-section through the structure features (mm², more is better; geometry, not strength)",
}
ORIENT_FORMULA = ("score = " + " + ".join(f"{w:.2f}·{k}" for k, w in ORIENT_WEIGHTS.items())
                  + ", each term scaled 0–1 across the candidates; lower is better")


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _unb64(text: str, dtype, cols: int) -> np.ndarray:
    return np.frombuffer(base64.b64decode(text), dtype=dtype).reshape(-1, cols)


# ── print orientation ─────────────────────────────────────────────────────────
# An orientation is one of the six named ones, or "down:x,y,z": the design-frame direction that faces the plate.

def parse_down(orientation: str):
    """The unit vector of a "down:x,y,z" orientation, or None when it is not one (or not valid)."""
    if not isinstance(orientation, str) or not orientation.startswith("down:"):
        return None
    try:
        v = np.array([float(x) for x in orientation[5:].split(",")], dtype=np.float64)
    except ValueError:
        return None
    if v.shape != (3,) or not np.all(np.isfinite(v)) or np.linalg.norm(v) < 1e-9:
        return None
    return v / np.linalg.norm(v)


def valid_orientation(orientation) -> bool:
    return orientation in NAMED or parse_down(orientation) is not None


def down_id(d) -> str:
    d = np.asarray(d, dtype=np.float64)
    d = d / np.linalg.norm(d)
    return "down:" + ",".join(f"{0.0 if abs(x) < 5e-5 else x:.4f}" for x in d)


def axis_angle(orientation: str):
    """((ax, ay, az), degrees) of the single rotation a "down:" orientation applies; None for the named ones."""
    d = parse_down(orientation)
    if d is None:
        return None
    z = np.array([0.0, 0.0, -1.0])
    c = float(np.clip(d @ z, -1, 1))
    axis = np.cross(d, z)
    if np.linalg.norm(axis) < 1e-9:
        return ((1.0, 0.0, 0.0), 0.0 if c > 0 else 180.0)
    axis = axis / np.linalg.norm(axis)
    return (tuple(float(x) for x in axis), math.degrees(math.acos(c)))


def orientation_matrix(orientation: str) -> np.ndarray:
    """R with p_print = R @ p_design (before the part is dropped onto the plate)."""
    if orientation in NAMED:
        rx, ry = NAMED[orientation]
        ax, ay = math.radians(rx), math.radians(ry)
        Rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
        Ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
        return Ry @ Rx
    aa = axis_angle(orientation)
    if aa is None:
        raise ValueError(f"Unknown orientation “{orientation}”.")
    (x, y, z), deg = aa
    a = math.radians(deg)
    K = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * (K @ K)


def orientation_down(orientation: str) -> np.ndarray:
    """The design-frame direction that faces the plate."""
    return orientation_matrix(orientation).T @ np.array([0.0, 0.0, -1.0])


def orientation_label(orientation: str) -> str:
    if orientation in NAMED_LABEL:
        return NAMED_LABEL[orientation]
    d = parse_down(orientation)
    if d is None:
        return str(orientation)
    return "Face (" + ", ".join(f"{0.0 if abs(x) < 5e-3 else x:.2f}" for x in d) + ") down"


def quaternion(R: np.ndarray) -> list:
    """Rotation matrix → [w, x, y, z]."""
    t = R[0, 0] + R[1, 1] + R[2, 2]
    if t > 0:
        s = math.sqrt(t + 1) * 2
        q = [s / 4, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [(R[2, 1] - R[1, 2]) / s, s / 4, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s]
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, s / 4, (R[1, 2] + R[2, 1]) / s]
    else:
        s = math.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, s / 4]
    return [float(x) for x in q]


# ── mesh helpers ──────────────────────────────────────────────────────────────

def tri_normals(P, T):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    area = np.linalg.norm(n, axis=1) / 2
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12), area, (a + b + c) / 3


def orientation_row(P, T, orientation: str, feature_of_tri=None) -> dict:
    """What the orientation table tabulates for one orientation, plus the support volume. P, T in the design frame.

    contact   flat downward faces lying on the plate
    overhang  everything facing down more steeply than 45° that is not contact
    ceiling   flat downward faces above the plate (bridges, or supported)
    steep     overhang that is not a flat ceiling
    support   overhang area projected on the plate times its height above the plate (mm³): the column of support under
              it if nothing of the part were in the way, so an upper bound
    """
    R = orientation_matrix(orientation)
    n, area, cen = tri_normals(P, T)
    nn, cc, pp = n @ R.T, cen @ R.T, P @ R.T
    zmin = pp[:, 2].min()
    size = pp.max(axis=0) - pp.min(axis=0)
    down = -nn[:, 2]
    contact = (down > 0.999) & (cc[:, 2] - zmin < 0.05)
    over = (down > math.cos(math.radians(45)) + 1e-6) & ~contact
    ceilings = (down > 0.999) & ~contact
    return {"id": orientation, "label": orientation_label(orientation), "height_mm": float(size[2]),
            "footprint_mm": [float(size[0]), float(size[1])],
            "contact_mm2": float(area[contact].sum()), "overhang_mm2": float(area[over].sum()),
            "ceiling_mm2": float(area[ceilings].sum()), "steep_mm2": float(area[over & ~ceilings].sum()),
            "support_mm3": float((area[over] * down[over] * (cc[over, 2] - zmin)).sum())}


def refine(P, T, h: float, max_passes: int = 24):
    """Split triangles at the midpoint of their longest edge until no edge is longer than h.

    New vertices lie on existing edges, so the surface is unchanged; only the sampling gets denser. Returns
    (P, T, parent) where parent[i] is the index of the input triangle that triangle i came from.
    """
    P = np.asarray(P, dtype=np.float64)
    T = np.asarray(T, dtype=np.int64)
    parent = np.arange(len(T))
    for _ in range(max_passes):
        if not len(T):
            break
        e = np.stack([np.linalg.norm(P[T[:, 1]] - P[T[:, 0]], axis=1), np.linalg.norm(P[T[:, 2]] - P[T[:, 1]], axis=1),
                      np.linalg.norm(P[T[:, 0]] - P[T[:, 2]], axis=1)], axis=1)
        k = np.argmax(e, axis=1)
        split = e[np.arange(len(T)), k] > h
        if not split.any():
            break
        S, ks = T[split], k[split]
        r = np.arange(len(S))
        i0, i1, i2 = S[r, ks], S[r, (ks + 1) % 3], S[r, (ks + 2) % 3]        # longest edge is i0–i1
        key = np.stack([np.minimum(i0, i1), np.maximum(i0, i1)], axis=1)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        mid = len(P) + inv.reshape(-1)
        P = np.concatenate([P, (P[uniq[:, 0]] + P[uniq[:, 1]]) / 2])
        T = np.concatenate([T[~split], np.stack([i0, mid, i2], axis=1), np.stack([mid, i1, i2], axis=1)])
        parent = np.concatenate([parent[~split], parent[split], parent[split]])
    return P, T, parent


def section_profile(P, T, orientation: str = "as_modelled", step: float = 0.2, max_levels: int = 400) -> dict:
    """Area of the horizontal slice of a closed mesh at each height, in the given print orientation.

    Each level is taken at the middle of a slab `step` thick. The area comes from the slice outline (Green's theorem on
    the segments where triangles cross the plane), so it is exact for the tessellation and no better than it.
    """
    R = orientation_matrix(orientation)
    Q = np.asarray(P, dtype=np.float64) @ R.T
    T = np.asarray(T, dtype=np.int64)
    n, _area, _c = tri_normals(Q, T)
    zmin, zmax = float(Q[:, 2].min()), float(Q[:, 2].max())
    height = zmax - zmin
    levels = int(min(max_levels, max(1, math.ceil(height / max(step, 1e-6)))))
    step = height / levels if levels else 0.0
    zs = zmin + (np.arange(levels) + 0.5) * step
    tz = Q[:, 2][T]
    tmin, tmax = tz.min(axis=1), tz.max(axis=1)
    out = np.zeros(levels)
    for i, z in enumerate(zs):
        z = z + 1e-7                                       # never exactly through a vertex
        m = (tmin < z) & (tmax > z)
        if not m.any():
            continue
        tri = T[m]
        d = Q[:, 2][tri] - z                               # signed distance of each corner
        pts = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            cross = (d[:, a] > 0) != (d[:, b] > 0)
            t = np.where(cross, d[:, a] / np.where(cross, d[:, a] - d[:, b], 1.0), 0.0)
            pts.append((cross, Q[tri[:, a], :2] + (Q[tri[:, b], :2] - Q[tri[:, a], :2]) * t[:, None]))
        # each crossing triangle has exactly two crossing edges: take them in order
        c0, c1, c2 = pts[0][0], pts[1][0], pts[2][0]
        p = np.where(c0[:, None], pts[0][1], pts[1][1])
        q = np.where((c0 & c1)[:, None], pts[1][1], pts[2][1])
        q = np.where((~c0)[:, None], pts[2][1], q)
        nm = n[m]
        flip = (q - p)[:, 0] * -nm[:, 1] + (q - p)[:, 1] * nm[:, 0] < 0        # walk with the solid on the left
        p2, q2 = np.where(flip[:, None], q, p), np.where(flip[:, None], p, q)
        out[i] = abs(0.5 * float(np.sum(p2[:, 0] * q2[:, 1] - q2[:, 0] * p2[:, 1])))
    return {"z": [round(float(z - zmin), 4) for z in zs], "area": [round(float(a), 3) for a in out], "step_mm": round(step, 4),
            "height_mm": round(height, 4), "neck": neck(zs - zmin, out), "orientation": orientation}


def slice_outline(P, T, orientation: str, z_print: float) -> np.ndarray:
    """The outline of the slice at print height z_print (above the lowest point), as (n, 6) segments in the design frame."""
    R = orientation_matrix(orientation)
    Q = np.asarray(P, dtype=np.float64) @ R.T
    T = np.asarray(T, dtype=np.int64)
    z = float(Q[:, 2].min()) + z_print + 1e-7
    tz = Q[:, 2][T]
    tri = T[(tz.min(axis=1) < z) & (tz.max(axis=1) > z)]
    if not len(tri):
        return np.zeros((0, 6), dtype=np.float32)
    d = Q[:, 2][tri] - z
    ends = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        cross = (d[:, a] > 0) != (d[:, b] > 0)
        t = np.where(cross, d[:, a] / np.where(cross, d[:, a] - d[:, b], 1.0), 0.0)
        ends.append((cross, Q[tri[:, a]] + (Q[tri[:, b]] - Q[tri[:, a]]) * t[:, None]))
    c0, c1 = ends[0][0], ends[1][0]
    p = np.where(c0[:, None], ends[0][1], ends[1][1])
    q = np.where((c0 & c1)[:, None], ends[1][1], ends[2][1])
    return np.hstack([p @ R, q @ R]).astype(np.float32)        # back to the design frame (R is orthonormal)


def neck(z, area, ratio: float = 1.25, zrange=None):
    """The weakest neck: the smallest slice that has clearly more material (≥ ratio×) somewhere below it and above it.

    None when the section only grows or only shrinks with height (there is no neck, only a tip or a base).
    """
    a = np.asarray(area, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    if len(a) < 3:
        return None
    below = np.maximum.accumulate(a)
    above = np.maximum.accumulate(a[::-1])[::-1]
    ok = (below >= ratio * a) & (above >= ratio * a) & (a > 0)
    if zrange is not None:
        ok &= (z >= zrange[0]) & (z <= zrange[1])
    if not ok.any():
        return None
    i = int(np.argmin(np.where(ok, a, np.inf)))
    return {"z_mm": round(float(z[i]), 3), "area_mm2": round(float(a[i]), 3), "index": i,
            "below_mm2": round(float(below[i]), 3), "above_mm2": round(float(above[i]), 3)}


def fit_circle(points) -> dict | None:
    """Least-squares circle through 3D points: plane by SVD, then an algebraic circle fit in that plane."""
    X = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(X) < 3:
        return None
    c0 = X.mean(axis=0)
    _u, s, vt = np.linalg.svd(X - c0)
    if s[1] < 1e-9:
        return None                                        # collinear
    u, v, nrm = vt[0], vt[1], vt[2]
    x, y = (X - c0) @ u, (X - c0) @ v
    A = np.stack([2 * x, 2 * y, np.ones(len(x))], axis=1)
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    r2 = sol[2] + sol[0] ** 2 + sol[1] ** 2
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    res = np.hypot(x - sol[0], y - sol[1]) - r
    centre = c0 + sol[0] * u + sol[1] * v
    return {"center": [float(t) for t in centre], "normal": [float(t) for t in nrm], "radius": float(r),
            "rms": float(np.sqrt(np.mean(res ** 2 + ((X - c0) @ nrm) ** 2))), "points": int(len(X))}


def closest_on_triangles(p, A, B, C):
    """Closest point on each triangle (A, B, C) to p. Returns (points, distances). Ericson, Real-Time Collision Detection."""
    p = np.asarray(p, dtype=np.float64)
    ab, ac, ap = B - A, C - A, p - A
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - B
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - C
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = np.where(np.abs(va + vb + vc) < 1e-30, 1.0, va + vb + vc)
    v, w = vb / den, vc / den
    out = A + ab * v[:, None] + ac * w[:, None]            # interior
    safe = lambda a, b: a / np.where(np.abs(b) < 1e-30, 1.0, b)
    m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)        # edge BC
    out[m] = (B + (C - B) * safe(d4 - d3, (d4 - d3) + (d5 - d6))[:, None])[m]
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)                  # edge AC
    out[m] = (A + ac * safe(d2, d2 - d6)[:, None])[m]
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)                  # edge AB
    out[m] = (A + ab * safe(d1, d1 - d3)[:, None])[m]
    m = (d6 >= 0) & (d5 <= d6)
    out[m] = C[m]
    m = (d3 >= 0) & (d4 <= d3)
    out[m] = B[m]
    m = (d1 <= 0) & (d2 <= 0)
    out[m] = A[m]
    return out, np.linalg.norm(out - p, axis=1)


def distance(a, b, orientation: str = "as_modelled") -> dict:
    """Straight-line distance between two design-frame points, with its components along the design axes."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.shape != (3,) or b.shape != (3,) or not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
        raise ValueError("A measurement needs two points, each x,y,z in millimetres.")
    d = b - a
    dp = orientation_matrix(orientation) @ d
    return {"from": [float(x) for x in a], "to": [float(x) for x in b], "distance_mm": float(np.linalg.norm(d)),
            "dx_mm": float(d[0]), "dy_mm": float(d[1]), "dz_mm": float(d[2]),
            "layers_dz_mm": float(dp[2]), "evidence": "computed"}


# ── colour ────────────────────────────────────────────────────────────────────

def _lerp(c0, c1, t):
    t = np.clip(np.asarray(t, dtype=np.float64), 0, 1)[..., None]
    return np.asarray(c0, dtype=np.float64) * (1 - t) + np.asarray(c1, dtype=np.float64) * t


def _rgba(rgb) -> np.ndarray:
    rgb = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    return np.concatenate([rgb, np.full((len(rgb), 1), 255, dtype=np.uint8)], axis=1)


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(x) for x in c)


def thickness_bands(nozzle: float) -> dict:
    """The thresholds the Thinnest-wall check uses: under two perimeters fails, under three is marginal."""
    return {"fail_below": 2 * nozzle, "fine_from": 3 * nozzle}


def thickness_colours(t, nozzle: float) -> np.ndarray:
    """Three classes, the ones a nozzle cares about. Everything from three perimeters up is one plain colour: how
    much thicker than "fine" a wall is says nothing about printing it, and shading it (a 30 mm block next to a 3 mm
    rib, or the distance to whichever face a ray happens to meet) only painted patches that meant nothing."""
    b = thickness_bands(nozzle)
    t = np.asarray(t, dtype=np.float64)
    tt = np.where(np.isfinite(t), t, 1e9)
    fine = np.broadcast_to(np.asarray(CLAY, dtype=np.float64), (len(tt), 3))
    rgb = np.where((tt < b["fine_from"])[:, None], np.asarray(AMBER, dtype=np.float64), fine)
    rgb = np.where((tt < b["fail_below"])[:, None], np.asarray(SIGNAL, dtype=np.float64), rgb)
    rgb = np.where(np.isfinite(t)[:, None], rgb, np.asarray(CLAY, dtype=np.float64))
    return _rgba(rgb)


# overhang classes, per vertex
OH_OK, OH_STEEP, OH_CEILING, OH_CONTACT = 0, 1, 2, 3


def overhang_field(normals_design, z_print, zmin, R):
    """(angle past vertical in degrees, class) for surface normals in the design frame.

    Angle: 0° is a vertical wall, 90° a flat face looking straight down; negative faces upward.
    Same rules as the Unsupported-overhangs check: over 45° and not on the plate is an overhang; a flat downward face
    above the plate is a ceiling (a bridge); a flat downward face on the plate is contact.
    """
    down = -(np.asarray(normals_design) @ R.T)[:, 2]
    angle = np.degrees(np.arcsin(np.clip(down, -1, 1)))
    cls = np.full(len(down), OH_OK)
    flat = down > 0.999
    cls[(down > math.cos(math.radians(45)) + 1e-6)] = OH_STEEP
    cls[flat] = OH_CEILING
    cls[flat & (np.asarray(z_print) - zmin < 0.05)] = OH_CONTACT
    return angle, cls


def overhang_colours(angle, cls) -> np.ndarray:
    rgb = np.tile(np.asarray(CLAY, dtype=np.float64), (len(angle), 1))
    steep = cls == OH_STEEP
    rgb[steep] = _lerp(AMBER, SIGNAL, (np.asarray(angle)[steep] - 45) / 40)
    rgb[cls == OH_CEILING] = BLUEPRINT
    rgb[cls == OH_CONTACT] = DATUM
    return _rgba(rgb)


# ── kernel side: rays on the B-rep ────────────────────────────────────────────

WALL_PARALLEL = 0.866        # cos 30°: a wall's two faces are close to parallel; anything wider is a wedge at an edge


def wall_hit(inter, p, n, outward: bool = False, want_face: bool = False):
    """One ray from surface point p along −n (into the material) or +n (across a gap) to the nearest opposing face.

    Returns (distance, hit point) or None. A hit whose face is not within 30° of parallel to the start face is discarded:
    that is a wedge where two faces meet at an edge or chamfer (a slanted side running into the plate face), not a
    wall, and the slicer prints it as a tapered edge. This is the single ray both the Thinnest-wall check and the
    thickness map cast.
    """
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from build123d import Face, Vector
    s = 1.0 if outward else -1.0
    d = (s * n[0], s * n[1], s * n[2])
    o = (p[0] + d[0] * 1e-4, p[1] + d[1] * 1e-4, p[2] + d[2] * 1e-4)
    inter.Perform(gp_Lin(gp_Pnt(*o), gp_Dir(*d)), 1e-4, 1e4)
    hit = None
    for j in range(1, inter.NbPnt() + 1):
        w = inter.WParameter(j)
        if w > 1e-3 and (hit is None or w < hit[0]):
            hit = (w, j)
    if hit is None:
        return None
    w, j = hit
    q = inter.Pnt(j)
    try:
        m = Face(inter.Face(j)).normal_at(Vector(q.X(), q.Y(), q.Z()))
        opposed = -(m.X * n[0] + m.Y * n[1] + m.Z * n[2])
    except Exception:
        opposed = 1.0
    if opposed < WALL_PARALLEL:
        return None
    if want_face:
        return float(w), (q.X(), q.Y(), q.Z()), inter.Face(j)
    return float(w), (q.X(), q.Y(), q.Z())


def wall_intersectors(model):
    """face -> the intersector a wall ray from that face should use.

    A wall is measured inside one part. In a design of several parts (a bolt in its nut, a lid on its box) a ray that
    leaves one part's material and meets the next part's surface measures the contact between them, not a wall: so
    each part gets an intersector of its own solid. One solid: the whole shape, as before."""
    shape = model["shape"]
    try:
        solids = shape.solids()
    except Exception:
        solids = []
    whole = intersector(shape)
    if len(solids) <= 1:
        return lambda face: whole
    own = [None] * len(solids)
    owner = {}
    for i, sol in enumerate(solids):
        for fc in sol.faces():
            owner[hash(fc.wrapped)] = i

    def pick(face):
        i = owner.get(hash(face.wrapped))
        if i is None:
            return whole
        if own[i] is None:
            own[i] = intersector(solids[i])
        return own[i]
    return pick


def intersector(shape):
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape.wrapped, 1e-6)
    return inter


_fields: dict = {}          # geometry key -> sampled field (kept small; lives in the kernel worker)


def _field(key, model, rays: int = 30000):
    """A refined copy of the model's tessellation with a true surface normal at every vertex. Rays are added on demand.

    The kernel triangulates a flat face with long thin triangles, so refining to an edge length gives many vertices that
    sit almost on top of each other. Rays are cast once per `cell` (a cube of surface about half the edge length, per
    face) and shared by the vertices in it: the sample spacing is the cell size, however the triangles fall.
    """
    f = _fields.get(key)
    if f is not None:
        return f
    from build123d import Vector
    area = sum(x["area"] for x in model["faces"]) or 1.0
    cell = max(0.3, math.sqrt(area / rays))
    h = 2 * cell
    while True:
        Ps, Ts, face_of, off = [], [], [], 0
        for i, x in enumerate(model["faces"]):
            P, T, _par = refine(x["P"], x["T"], h)
            Ps.append(P)
            Ts.append(T + off)
            face_of.append(np.full(len(P), i))
            off += len(P)
        P, T, face_of = np.concatenate(Ps), np.concatenate(Ts), np.concatenate(face_of)
        if len(P) <= 130000:
            break
        h *= 1.3
    # sample a hair inside each face, so a vertex on a B-rep edge does not send its ray along the neighbouring face
    cen = (P[T[:, 0]] + P[T[:, 1]] + P[T[:, 2]]) / 3
    acc, cnt = np.zeros_like(P), np.zeros(len(P))
    for k in range(3):
        np.add.at(acc, T[:, k], cen)
        np.add.at(cnt, T[:, k], 1)
    inward = acc / np.maximum(cnt, 1)[:, None] - P
    ln = np.linalg.norm(inward, axis=1, keepdims=True)
    S = P + inward / np.maximum(ln, 1e-12) * np.minimum(ln, 0.02)
    # normals: the B-rep's own. A plane has one normal; a curved face is asked per vertex.
    tn, ta, _c = tri_normals(P, T)
    N = np.zeros_like(P)
    for k in range(3):
        np.add.at(N, T[:, k], tn * ta[:, None])
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    for i, x in enumerate(model["faces"]):
        idx = np.flatnonzero(face_of == i)
        if not len(idx):
            continue
        face = x["face"]
        try:
            if face.geom_type.name == "PLANE":
                n = face.normal_at(Vector(*S[idx[0]]))
                N[idx] = (n.X, n.Y, n.Z)
            else:
                for j in idx:
                    n = face.normal_at(Vector(*S[j]))
                    N[j] = (n.X, n.Y, n.Z)
        except Exception:
            pass                                           # keep the tessellation normal
    cells = np.concatenate([face_of[:, None], np.floor(S / cell).astype(np.int64)], axis=1)
    _u, first, group = np.unique(cells, axis=0, return_index=True, return_inverse=True)
    f = {"P": P, "T": T, "S": S, "N": N, "face_of": face_of, "h": h, "cell": cell, "rep": first, "group": group.reshape(-1),
         "feature": [x["feature"] for x in model["faces"]]}
    if len(_fields) > 3:
        _fields.pop(next(iter(_fields)))
    _fields[key] = f
    return f


def _rays(f, model, outward: bool = False):
    """Distance to the opposing face for every sample (NaN where there is none), and where the ray landed.

    Outward rays measure gaps. A gap is between two faces that do not touch: where the two faces meet (the inside of a
    groove, the cusp where a round boss runs into a wall) the distance goes to zero by construction and is left out.
    Faces closer than 0.02 mm anywhere count as touching.
    """
    name = "gap" if outward else "wall"
    if name not in f:
        inter = intersector(model["shape"])
        per_part = None if outward else wall_intersectors(model)     # a wall stays inside its own part
        S, N, reps = f["S"], f["N"], f["rep"]
        t = np.full(len(reps), np.nan)
        to = np.full((len(reps), 3), np.nan)
        index = {hash(x["face"].wrapped): i for i, x in enumerate(model["faces"])} if outward else {}
        touching = {}
        for g, i in enumerate(reps):
            ray = per_part(model["faces"][int(f["face_of"][i])]["face"]) if per_part else inter
            hit = wall_hit(ray, S[i], N[i], outward, want_face=outward)
            if hit is None:
                continue
            if outward:
                me, other = int(f["face_of"][i]), index.get(hash(hit[2]), -1)
                pair = (min(me, other), max(me, other))
                if pair not in touching:
                    try:
                        touching[pair] = other < 0 or me == other or \
                            float(model["faces"][me]["face"].distance_to(model["faces"][other]["face"])) < 0.02
                    except Exception:
                        touching[pair] = True
                if touching[pair]:
                    continue
            t[g], to[g] = hit[0], hit[1]
        f[name], f[name + "_to"] = t[f["group"]], to[f["group"]]
    return f[name], f[name + "_to"]


def _markers(P, to, values, mask, kind, label, cell: float = 4.0, limit: int = 24) -> list:
    """One marker per `cell` mm cube, the worst sample in it; the worst `limit` cells overall."""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    keys = np.floor(P[idx] / cell).astype(np.int64)
    best = {}
    for i, k in zip(idx, map(tuple, keys)):
        if k not in best or values[i] < values[best[k]]:
            best[k] = i
    picks = sorted(best.values(), key=lambda i: values[i])[:limit]
    return [{"kind": kind, "at": [round(float(x), 3) for x in P[i]], "to": [round(float(x), 3) for x in to[i]],
             "value_mm": round(float(values[i]), 3), "label": label.format(v=float(values[i]))} for i in picks]


def _holes(model) -> list:
    """Cylindrical holes of the B-rep, exact: one entry per distinct axis and radius."""
    out = {}
    for x in model["faces"]:
        face = x["face"]
        try:
            if face.geom_type.name != "CYLINDER":
                continue
            ax, r = face.axis_of_rotation, float(face.radius)
            c = face.center()
            n = face.normal_at(c)
            o, d = np.array([ax.position.X, ax.position.Y, ax.position.Z]), np.array([ax.direction.X, ax.direction.Y, ax.direction.Z])
            pc = np.array([c.X, c.Y, c.Z])
            foot = o + d * float((pc - o) @ d)             # the point of the axis nearest the face centre
            radial = pc - foot
            if np.linalg.norm(radial) > 1e-9 and float(np.array([n.X, n.Y, n.Z]) @ radial) > 0:
                continue                                   # normal points away from the axis: a pin or boss, not a hole
            if d[np.argmax(np.abs(d))] < 0:
                d = -d
            base = o - d * float(o @ d)                    # where the axis passes closest to the origin
            key = (tuple(np.round(base, 2)), tuple(np.round(d, 3)), round(r, 3))
            h = out.setdefault(key, {"diameter_mm": 2 * r, "axis": [float(t) for t in d], "feature": x["feature"],
                                     "at": [float(t) for t in foot], "on": [float(t) for t in pc], "lo": 1e18, "hi": -1e18})
            s = x["P"] @ d
            h["lo"], h["hi"] = min(h["lo"], float(s.min())), max(h["hi"], float(s.max()))
        except Exception:
            continue
    holes = []
    for h in out.values():
        h["depth_mm"] = round(h.pop("hi") - h.pop("lo"), 3)
        holes.append(h)
    return sorted(holes, key=lambda h: h["diameter_mm"])


def _legend(title, unit, stops, what, not_, **extra) -> dict:
    return {"title": title, "unit": unit, "evidence": "computed", "stops": stops, "what": what, "not": not_, **extra}


def _share(area, mask) -> float:
    tot = float(area.sum()) or 1.0
    return round(100 * float(area[mask].sum()) / tot, 2)


def op_analysis(key, recipe_id, values, map="thickness", nozzle=0.4, orientation="as_modelled", layer=0.2, tol=TOL):
    """One analysis map of a design. Positions are in the design frame, like the view."""
    from . import kernel
    if map not in MAPS:
        raise ValueError(f"Unknown map “{map}”. Choose one of: {', '.join(MAPS)}.")
    model = kernel._get(key, recipe_id, values, tol)
    f = _field((key, tol), model)
    P, T = f["P"], f["T"]
    mesh_design = bool(getattr(model["recipe"], "mesh", False))
    tri_n, tri_a, _c = tri_normals(P, T)
    out = {"map": map, "label": MAP_LABEL[map], "version": ANALYSIS_VERSION, "evidence": "computed",
           "tessellation_mm": tol, "sample_spacing_mm": round(f["h"], 3), "samples": int(len(f["rep"])), "vertices": int(len(P)),
           "triangles": int(len(T)),
           "orientation": orientation, "orientation_label": orientation_label(orientation), "nozzle_mm": nozzle,
           "bbox": model["bbox"], "markers": [], "mesh_design": mesh_design}
    vals = np.full(len(P), np.nan)

    if map == "thickness":
        t, to = _rays(f, model)
        vals = t
        b = thickness_bands(nozzle)
        col = thickness_colours(t, nozzle)
        ok = np.isfinite(t)
        tv = np.where(np.isfinite(t), t, np.inf)[T].min(axis=1)                    # a triangle is as thin as its thinnest corner
        with np.errstate(invalid="ignore"):
            under, marg = tv < b["fail_below"], (tv >= b["fail_below"]) & (tv < b["fine_from"])
        stats = {"samples_with_wall": int(ok[f["rep"]].sum()), "under_two_perimeters_pct": _share(tri_a, under), "marginal_pct": _share(tri_a, marg)}
        if ok.any():
            i = int(np.nanargmin(t))
            src = f["S"][f["rep"][f["group"][i]]]          # the sample the ray was cast from
            stats.update({"min_mm": round(float(t[i]), 3), "median_mm": round(float(np.nanmedian(t)), 3),
                          "p05_mm": round(float(np.nanpercentile(t, 5)), 3),
                          "thinnest": {"t": round(float(t[i]), 3), "at": [float(x) for x in src], "to": [float(x) for x in to[i]],
                                       "feature": f["feature"][int(f["face_of"][i])]}})
            out["markers"] = [{"kind": "thin", "at": stats["thinnest"]["at"], "to": stats["thinnest"]["to"],
                               "value_mm": stats["thinnest"]["t"], "label": f"{stats['thinnest']['t']:.2f} mm thinnest sample"}]
        out["stats"] = stats
        out["legend"] = _legend(
            "Wall thickness", "mm",
            [{"color": _hex(SIGNAL), "label": f"under {b['fail_below']:.1f} mm", "note": "cannot hold two perimeters"},
             {"color": _hex(AMBER), "label": f"{b['fail_below']:.1f} to {b['fine_from']:.1f} mm", "note": "marginal"},
             {"color": _hex(CLAY), "label": f"{b['fine_from']:.1f} mm and over", "note": "fine: three perimeters or more"}],
            f"Distance through the material to the opposing face, from {len(f['rep']):,} surface samples at most {f['h']:.1f} mm apart"
            + (" on the mesh" if mesh_design else "") + f". Thresholds are for a {nozzle:g} mm nozzle.",
            "Not a strength analysis. It does not see infill, layer adhesion or load, and a feature narrower than the "
            "sample spacing can fall between samples.", hover="{v} mm wall", none="no opposing wall")
    elif map == "overhang":
        R = orientation_matrix(orientation)
        zp = P @ R.T[:, 2]
        angle, cls = overhang_field(f["N"], zp, float(zp.min()), R)
        vals = angle
        col = overhang_colours(angle, cls)
        P0, T0 = kernel._mesh_arrays(model)
        row = orientation_row(P0, T0, orientation)
        out["stats"] = {k: round(row[k], 2) for k in ("contact_mm2", "steep_mm2", "ceiling_mm2", "overhang_mm2", "support_mm3", "height_mm")}
        out["classes"] = _b64(cls.astype(np.uint8))
        dn = orientation_down(orientation)
        out["down"] = [float(x) for x in dn]
        out["legend"] = _legend(
            "Overhangs", "° past vertical",
            [{"color": _hex(AMBER), "to": _hex(SIGNAL), "label": "45° to 90°", "note": f"unsupported overhang · {row['steep_mm2']:.0f} mm²"},
             {"color": _hex(BLUEPRINT), "label": "flat ceiling", "note": f"bridges or needs support · {row['ceiling_mm2']:.0f} mm²"},
             {"color": _hex(DATUM), "label": "on the plate", "note": f"{row['contact_mm2']:.0f} mm²"},
             {"color": _hex(CLAY), "label": "under 45°", "note": "prints without support"}],
            "Angle of each surface past vertical when printed in this orientation; areas are the ones the overhang check reports.",
            "Not a slice. It does not know your support settings, bridging distance or cooling; confirm in the sliced preview.",
            hover="{v}° past vertical", none="")
    elif map == "section":
        P0, T0 = kernel._mesh_arrays(model)
        prof = section_profile(P0, T0, orientation, step=layer)
        nk = prof["neck"]
        R = orientation_matrix(orientation)
        zp = P @ R.T[:, 2]
        zp = zp - zp.min()
        vals = np.interp(zp, prof["z"], prof["area"]) if prof["z"] else vals
        amax = max(float(np.max(prof["area"])) if prof["z"] else 0.0, 1e-9)
        col = _rgba(_lerp(CLAY, CLAY_DEEP, 1 - np.nan_to_num(vals) / amax))       # less material in the slice reads darker
        if nk:
            out["lines"] = _b64(slice_outline(P0, T0, orientation, nk["z_mm"]))
            out["line_color"] = _hex(AMBER)
            seg = _unb64(out["lines"], np.float32, 6)
            a_pt = seg[:, :3].mean(axis=0) if len(seg) else np.zeros(3)
            out["markers"] = [{"kind": "neck", "at": [float(x) for x in a_pt], "to": [float(x) for x in a_pt], "value_mm": nk["area_mm2"],
                               "label": f"neck {nk['area_mm2']:.0f} mm² at {nk['z_mm']:.1f} mm"}]
        a = np.asarray(prof["area"])
        out["chart"] = prof
        out["stats"] = {"levels": len(prof["z"]), "step_mm": prof["step_mm"], "height_mm": prof["height_mm"],
                        "max_mm2": round(float(a.max()), 2) if len(a) else None, "neck": nk}
        out["legend"] = _legend(
            "Layer cross-section", "mm²",
            ([{"color": _hex(AMBER), "label": "weakest neck", "note": f"{nk['area_mm2']:.0f} mm² at {nk['z_mm']:.1f} mm, outlined on the part"}] if nk else [])
            + [{"color": _hex(CLAY_DEEP), "to": _hex(CLAY), "label": f"0 to {amax:.0f} mm²", "note": "area of the slice at that height"
                + ("" if nk else "; no neck: it never narrows between two wider regions")}],
            f"Area of the horizontal slice every {prof['step_mm']:.2f} mm up the print, from the tessellation ({tol:g} mm)."
            + (f" The plate holds {len(model['shape'].solids())} bodies: a slice is the sum over all of them." if len(model["shape"].solids()) > 1 else ""),
            "Computed geometry, not a strength analysis. A small section across the layers is where a print is easiest to "
            "snap, but how strong it is depends on material, infill and the load, none of which are in this number.",
            hover="{v} mm² slice at this height", none="")
    else:                                                  # features
        t, to = _rays(f, model)
        g, gto = _rays(f, model, outward=True)
        rgb = np.tile(np.asarray(CLAY, dtype=np.float64), (len(P), 1))
        with np.errstate(invalid="ignore"):
            thin, gap = np.round(t, 3) < nozzle, np.round(g, 3) < nozzle
        rgb[gap] = AMBER
        rgb[thin] = SIGNAL
        src = f["S"][f["rep"][f["group"]]]
        marks = _markers(src, to, np.where(thin, t, np.inf), thin, "thin", "{v:.2f} mm wall or edge")
        marks += _markers(src, gto, np.where(gap, g, np.inf), gap, "gap", "{v:.2f} mm gap")
        holes = [] if mesh_design else _holes(model)
        small = [h for h in holes if h["diameter_mm"] < 5 * nozzle]
        for h in small:
            closes = h["diameter_mm"] < 2 * nozzle
            marks.append({"kind": "hole", "at": h["on"], "to": h["at"], "value_mm": round(h["diameter_mm"], 3), "severity": "fail" if closes else "review",
                          "label": f"Ø{h['diameter_mm']:.2f} mm hole"})
        vals = np.fmin(t, g)
        col = _rgba(rgb)
        out["markers"] = marks
        out["holes"] = [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in h.items()} for h in holes]
        out["stats"] = {"thin_markers": sum(m["kind"] == "thin" for m in marks), "gap_markers": sum(m["kind"] == "gap" for m in marks),
                        "small_holes": len(small), "holes": len(holes), "thin_pct": _share(tri_a, np.any(thin[T], axis=1)),
                        "gap_pct": _share(tri_a, np.any(gap[T], axis=1))}
        out["legend"] = _legend(
            "Small features", "mm",
            [{"color": _hex(SIGNAL), "label": f"wall or edge under {nozzle:g} mm", "note": "thinner than one nozzle width"},
             {"color": _hex(AMBER), "label": f"gap under {nozzle:g} mm", "note": "facing walls may fuse"},
             {"color": _hex(BLUEPRINT), "label": f"hole under Ø{5 * nozzle:g} mm", "note": "prints undersized; under Ø" + f"{2 * nozzle:g} may close"}],
            f"Sizes are computed: walls and gaps by ray from {len(f['rep']):,} surface samples at most {f['h']:.1f} mm apart"
            + ("; hole diameters are not available for a mesh design." if mesh_design else ", hole diameters exact from the CAD solid.")
            + f" The limits are rules of thumb for a {nozzle:g} mm nozzle.",
            "Not a print result. Whether a small feature survives depends on the slicer and the printer; check the slice. "
            "Sharp edges always taper to nothing and are flagged where they do.",
            hover="{v} mm", none="")
    out["positions"], out["indices"] = _b64(P.astype(np.float32)), _b64(T.astype(np.uint32))
    out["values"], out["colors"] = _b64(np.asarray(vals, dtype=np.float32)), _b64(col)
    return out


# ── kernel side: what is under a point ────────────────────────────────────────

def _region(P, T, seed: int, cos_tol: float = 0.9994):
    """Triangles connected to `seed` through shared edges whose normals stay within about 2° of it (a flat region of a mesh)."""
    q = np.round(P / 1e-4).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    V = inv.reshape(-1)[T]
    n, area, _c = tri_normals(P, T)
    ok = np.flatnonzero(n @ n[seed] >= cos_tol)
    edges = {}
    for t in ok:
        for a, b in ((0, 1), (1, 2), (2, 0)):
            edges.setdefault((min(V[t, a], V[t, b]), max(V[t, a], V[t, b])), []).append(t)
    adj = {}
    for ts in edges.values():
        for a in ts:
            for b in ts:
                if a != b:
                    adj.setdefault(a, set()).add(b)
    seen, todo = {seed}, [seed]
    while todo:
        for b in adj.get(todo.pop(), ()):
            if b not in seen:
                seen.add(b)
                todo.append(b)
    idx = np.array(sorted(seen))
    return idx, float(area[idx].sum()), n[seed]


def _loops(E):
    """Connected chains of mesh crease segments (n, 6) → list of (m, 3) point arrays."""
    if not len(E):
        return []
    pts = E.reshape(-1, 3).astype(np.float64)
    q = np.round(pts / 1e-3).astype(np.int64)
    uniq, inv = np.unique(q, axis=0, return_inverse=True)
    inv = inv.reshape(-1, 2)
    parent = np.arange(len(uniq))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in inv:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(i) for i in range(len(uniq))])
    first = np.zeros((len(uniq), 3))
    first[inv.reshape(-1)] = pts
    return [first[roots == r] for r in np.unique(roots)]


def op_probe(key, recipe_id, values, at, orientation="as_modelled", tol=TOL):
    """What is at a point of the part: the nearest face (type, area, tilt to the bed, radius) and edge, and snap points.

    Exact from the B-rep where there is one. For a mesh design the face is the flat region around the nearest triangle
    and a diameter is a circle fitted to the nearest loop of crease edges (reported as "fitted").
    """
    from . import kernel
    from build123d import Vector
    p = np.asarray(at, dtype=np.float64)
    if p.shape != (3,) or not np.all(np.isfinite(p)):
        raise ValueError("A point is x,y,z in millimetres.")
    model = kernel._get_near(key, recipe_id, values, tol)
    mesh_design = bool(getattr(model["recipe"], "mesh", False))
    best = None
    for i, x in enumerate(model["faces"]):
        lo, hi = x["P"].min(axis=0), x["P"].max(axis=0)
        if best is not None and np.any(p < lo - best[0]) | np.any(p > hi + best[0]):
            continue
        A, B, C = x["P"][x["T"][:, 0]], x["P"][x["T"][:, 1]], x["P"][x["T"][:, 2]]
        pts, d = closest_on_triangles(p, A, B, C)
        k = int(np.argmin(d))
        if best is None or d[k] < best[0]:
            best = (float(d[k]), i, pts[k], k)
    if best is None:
        raise ValueError("The design has no surface.")
    dist, fi, on, tk = best
    x = model["faces"][fi]
    face = x["face"]
    R = orientation_matrix(orientation)
    out = {"at": [float(t) for t in p], "on": [float(t) for t in on], "off_surface_mm": round(dist, 4), "feature": x["feature"],
           "evidence": "computed", "tessellation_mm": model.get("tol", tol), "orientation": orientation, "mesh_design": mesh_design, "snaps": []}

    def tilt(n):
        up = float(np.clip((R @ np.asarray(n))[2], -1, 1))
        deg = math.degrees(math.acos(up))
        return round(deg, 2), ("faces up, parallel to the bed" if deg < 0.5 else "faces down, parallel to the bed" if deg > 179.5
                               else "vertical wall" if abs(deg - 90) < 0.5 else
                               f"leans {'up' if deg < 90 else 'down'}, {abs(90 - deg):.1f}° from vertical")

    if mesh_design:
        P, T = kernel._mesh_arrays(model)
        off = sum(len(y["P"]) for y in model["faces"][:fi])
        seed = int(np.flatnonzero((T == (x["T"][tk] + off)).all(axis=1))[0])
        idx, area, n = _region(P, T, seed)
        deg, words = tilt(n)
        out["face"] = {"type": "flat region of the mesh" if len(idx) > 1 else "triangle", "area_mm2": round(area, 3), "normal": [float(t) for t in n],
                       "tilt_deg": deg, "tilt": words, "method": "computed from the mesh", "triangles": int(len(idx))}
        near = None
        for lp in _loops(kernel._mesh_edges(P, T)):
            d = float(np.min(np.linalg.norm(lp - on, axis=1)))
            if near is None or d < near[0]:
                near = (d, lp)
        if near is not None and len(near[1]) >= 6:
            c = fit_circle(near[1])
            if c and c["rms"] <= max(0.05, 0.03 * c["radius"]):
                out["circle"] = {"diameter_mm": round(2 * c["radius"], 3), "radius_mm": round(c["radius"], 4), "center": c["center"],
                                 "axis": c["normal"], "method": "fitted", "rms_mm": round(c["rms"], 4), "points": c["points"],
                                 "edge_distance_mm": round(near[0], 3)}
        return out

    try:
        nv = face.normal_at(Vector(*on))
        n = (nv.X, nv.Y, nv.Z)
    except Exception:
        n = tuple(tri_normals(x["P"], x["T"])[0][tk])
    kind = face.geom_type.name
    deg, words = tilt(n)
    fc = face.center()
    out["face"] = {"type": kind.lower(), "area_mm2": round(float(face.area), 3), "normal": [float(t) for t in n], "tilt_deg": deg,
                   "tilt": words if kind == "PLANE" else words + " at this point", "method": "exact (CAD solid)"}
    out["snaps"].append({"kind": "face centre", "at": [fc.X, fc.Y, fc.Z]})
    if kind in ("CYLINDER", "SPHERE"):
        try:
            r = float(face.radius)
            ax = face.axis_of_rotation if kind == "CYLINDER" else None
            c = {"diameter_mm": round(2 * r, 4), "radius_mm": round(r, 4), "method": "exact (CAD solid)", "surface": kind.lower()}
            if ax is not None:
                o, d = np.array([ax.position.X, ax.position.Y, ax.position.Z]), np.array([ax.direction.X, ax.direction.Y, ax.direction.Z])
                foot = o + d * float((np.asarray(on) - o) @ d)
                c.update({"center": [float(t) for t in foot], "axis": [float(t) for t in d],
                          "hole": bool(float(np.asarray(n) @ (np.asarray(on) - foot)) < 0)})
            out["circle"] = c
        except Exception:
            pass
    near = None
    for e in face.edges():
        try:
            d = float(e.distance_to(Vector(*on)))
        except Exception:
            continue
        if near is None or d < near[0]:
            near = (d, e)
        try:
            m = e.position_at(0.5)
            out["snaps"].append({"kind": "edge midpoint", "at": [m.X, m.Y, m.Z]})
        except Exception:
            pass
    for v in face.vertices():
        out["snaps"].append({"kind": "vertex", "at": [v.X, v.Y, v.Z]})
    if near is not None:
        d, e = near
        ek = e.geom_type.name
        edge = {"type": ek.lower(), "length_mm": round(float(e.length), 4), "distance_mm": round(d, 4)}
        if ek == "CIRCLE":
            try:
                r = float(e.radius)
                c = e.arc_center
                edge.update({"radius_mm": round(r, 4), "diameter_mm": round(2 * r, 4), "center": [c.X, c.Y, c.Z],
                             "full_circle": bool(abs(e.length - 2 * math.pi * r) < 1e-6 * max(1.0, r))})
                out["snaps"].append({"kind": "circle centre", "at": [c.X, c.Y, c.Z]})
                if "circle" not in out:
                    nrm = e.normal()
                    out["circle"] = {"diameter_mm": edge["diameter_mm"], "radius_mm": edge["radius_mm"], "center": edge["center"],
                                     "axis": [nrm.X, nrm.Y, nrm.Z], "method": "exact (CAD solid)", "surface": "circular edge",
                                     "edge_distance_mm": edge["distance_mm"]}
            except Exception:
                pass
        out["edge"] = edge
    for s in out["snaps"]:
        s["at"] = [round(float(t), 5) for t in s["at"]]
        s["distance_mm"] = round(float(np.linalg.norm(np.asarray(s["at"]) - on)), 4)
    out["snaps"].sort(key=lambda s: s["distance_mm"])
    out["snaps"] = out["snaps"][:40]
    return out


# ── kernel side: print orientations ───────────────────────────────────────────

def rest_directions(P, T, min_contact: float = 4.0, limit: int = 24) -> list:
    """Every direction in which the part can rest on a flat face: the flat faces that lie on its convex hull.

    A face is on the hull when no vertex of the part is beyond its plane. Hull facets that touch the part only at
    points or edges are left out: there is no flat area on the plate, so they are not ways to print it.
    """
    n, area, cen = tri_normals(P, T)
    keys = np.round(n, 3)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    tot = np.bincount(inv, weights=area, minlength=len(uniq))
    out = []
    for i in np.argsort(-tot)[:400]:
        if tot[i] < min_contact:
            break
        m = inv == i
        d = (n[m] * area[m, None]).sum(axis=0)
        d /= np.linalg.norm(d)
        support = float((P @ d).max())
        on = m & (cen @ d > support - 0.05)
        a = float(area[on].sum())
        if a >= min_contact:
            out.append((a, d))
    out.sort(key=lambda t: -t[0])
    keep = []
    for a, d in out:
        if all(float(d @ k) < 0.9995 for _a, k in keep):
            keep.append((a, d))
    return [d for _a, d in keep[:limit]]


def rank_orientations(P, T, tri_feature, structure, envelope, margin, layer=0.4, extra=()) -> dict:
    """Score every candidate orientation. Pure numpy on the tessellation; see ORIENT_FORMULA."""
    cands, downs = [], []
    for name in NAMED:
        cands.append(name)
        downs.append(orientation_down(name))
    for d in rest_directions(P, T):
        if all(float(d @ k) < 0.9995 for k in downs):
            cands.append(down_id(d))
            downs.append(d)
    for name in extra:
        if name not in cands and valid_orientation(name) and all(float(orientation_down(name) @ k) < 0.9995 for k in downs):
            cands.append(name)
            downs.append(orientation_down(name))
    n, area, cen = tri_normals(P, T)
    smask = np.isin(np.asarray(tri_feature), list(structure)) if structure else np.zeros(len(T), dtype=bool)
    rows = []
    for name in cands:
        row = orientation_row(P, T, name)
        R = orientation_matrix(name)
        prof = section_profile(P, T, name, step=max(layer, row["height_mm"] / 120), max_levels=120)
        z = np.asarray(prof["z"])
        a = np.asarray(prof["area"])
        zr, scope = None, "whole part"
        if smask.any():
            zs = (P @ R.T[:, 2])[T[smask]].reshape(-1)
            z0 = float((P @ R.T[:, 2]).min())
            zr, scope = (float(zs.min() - z0), float(zs.max() - z0)), "structure features"
        nk = neck(z, a, zrange=zr)
        env_ok = (row["footprint_mm"][0] <= envelope[0] - 2 * margin and row["footprint_mm"][1] <= envelope[1] - 2 * margin
                  and row["height_mm"] <= envelope[2])
        swap_ok = (row["footprint_mm"][1] <= envelope[0] - 2 * margin and row["footprint_mm"][0] <= envelope[1] - 2 * margin
                   and row["height_mm"] <= envelope[2])
        Q = P @ R.T
        row.update({"down": [round(float(x), 4) for x in orientation_down(name)], "quaternion": quaternion(R),
                    "drop": [float(-(Q[:, 0].min() + Q[:, 0].max()) / 2), float(-(Q[:, 1].min() + Q[:, 1].max()) / 2), float(-Q[:, 2].min())],
                    "named": name in NAMED, "fits": bool(env_ok or (swap_ok and name not in NAMED)),
                    "neck": nk, "neck_scope": scope,
                    "min_layer_mm2": nk["area_mm2"] if nk else None})
        rows.append(row)

    def scale(vals, better_high=False):
        v = np.array([np.nan if x is None else x for x in vals], dtype=np.float64)
        if np.all(np.isnan(v)):
            return np.zeros(len(v))
        lo, hi = np.nanmin(v), np.nanmax(v)
        s = np.zeros(len(v)) if hi - lo < 1e-9 else (v - lo) / (hi - lo)
        s = 1 - s if better_high else s
        return np.where(np.isnan(v), 0.0, s)             # no neck in this orientation: nothing to penalise
    terms = {"support": scale([r["support_mm3"] for r in rows]), "overhang": scale([r["steep_mm2"] for r in rows]),
             "contact": scale([r["contact_mm2"] for r in rows], True), "height": scale([r["height_mm"] for r in rows]),
             "layers": scale([r["min_layer_mm2"] for r in rows], True)}
    for i, r in enumerate(rows):
        r["terms"] = {k: round(float(ORIENT_WEIGHTS[k] * terms[k][i]), 4) for k in ORIENT_WEIGHTS}
        r["score"] = round(float(sum(r["terms"].values())), 4)
    rows.sort(key=lambda r: (not r["fits"], r["score"], not r["named"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return {"candidates": rows, "weights": ORIENT_WEIGHTS, "terms": ORIENT_TERMS, "formula": ORIENT_FORMULA, "evidence": "computed",
            "not": "A ranking of computed geometry. It is not a print-success prediction and not a strength analysis: "
                   "it does not know your supports, cooling, material or the load. Slice the chosen orientation to confirm.",
            "structure_features": sorted(structure)}


def op_orient(key, recipe_id, values, envelope=(180, 180, 180), margin=2.0, layer=0.2, current="as_modelled", tol=TOL):
    from . import kernel
    model = kernel._get(key, recipe_id, values, tol)
    P, T = kernel._mesh_arrays(model)
    tri_feature = np.concatenate([np.full(len(x["T"]), x["feature"], dtype=object) for x in model["faces"]])
    structure = {f.id for f in model["recipe"].features if f.role == "structure"}
    out = rank_orientations(P, T, tri_feature, structure, list(envelope), margin, layer, extra=(current,))
    for r in out["candidates"]:
        if not r["named"]:                                 # name the face it rests on
            R = orientation_matrix(r["id"])
            n, area, cen = tri_normals(P, T)
            down = -(n @ R.T)[:, 2]
            zc = cen @ R.T[:, 2]
            on = (down > 0.999) & (zc - (P @ R.T[:, 2]).min() < 0.05)
            if on.any():
                feats = np.unique(tri_feature[on].astype(str))
                best = max(feats, key=lambda fid: float(area[on & (tri_feature == fid)].sum()))
                lab = next((f.label for f in model["recipe"].features if f.id == best), str(best))
                r["label"] = f"On a face of {lab}"
                r["rests_on"] = str(best)
        r["current"] = r["id"] == current or (float(np.asarray(r["down"]) @ orientation_down(current)) > 0.9995)
    out["current"] = current
    out["tessellation_mm"] = tol
    return out


KERNEL_OPS = {"analysis": op_analysis, "probe": op_probe, "orient": op_orient}


# ── engine side (server, CLI and MCP call these with a Studio) ────────────────

def _nozzle(st, p=None) -> tuple:
    s = st.slicer_info(p=p)            # the design's own printer (form/printers.py), else the slicer's selection
    return float(s.get("nozzle_mm", 0.4)), not s.get("available")


def _cached(st, p, name: str, key: str, make):
    import json
    path = st.dir(p["id"]) / "artifacts" / "analysis" / f"{name}-{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    out = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    fsutil.replace(tmp, path)
    return out


def run_map(st, p: dict, map: str = "thickness", rev: int | None = None) -> dict:
    """One analysis map of a revision (head by default), cached by geometry like every other artifact."""
    from .studio import H, StudioError
    if map not in MAPS:
        raise StudioError(f"Unknown map “{map}”.", "Maps: " + ", ".join(MAPS) + ".")
    r = st.rev(p, rev)
    gk = st.keys(p, r["n"])["geometry"]
    nozzle, assumed = _nozzle(st, p)
    orientation = p["orientation"]
    key = H("analysis", ANALYSIS_VERSION, gk, map, nozzle, orientation if map in ("overhang", "section") else None)
    out = _cached(st, p, map, key, lambda: st._k("analysis", timeout=300, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"],
                                                  map=map, nozzle=nozzle, orientation=orientation, p=p))
    out.update({"rev": r["n"], "project": p["id"], "nozzle_assumed": assumed})
    if assumed:
        out["legend"] = {**out["legend"], "what": out["legend"]["what"] + " No slicer is connected, so the nozzle size is assumed."}
    return out


def probe(st, p: dict, at, rev: int | None = None) -> dict:
    from .studio import StudioError
    r = st.rev(p, rev)
    try:
        pt = [float(x) for x in at]
        if len(pt) != 3:
            raise ValueError
    except (TypeError, ValueError):
        raise StudioError("A point is three numbers: x, y, z in millimetres (design frame).")
    return st._k("probe", key=st.keys(p, r["n"])["geometry"], recipe_id=st.rid(p, r["n"]), values=r["values"], at=pt,
                 orientation=p["orientation"], p=p)


def measure(st, p: dict, a, b, rev: int | None = None, a_on=None, b_on=None) -> dict:
    """Distance between two points, and what each of them is on.

    a and b are where the distance is taken. In an assembled or exploded view that is the arranged frame, while the
    surface under each end is looked up on the part as printed: a_on and b_on, when given, are those points."""
    from .studio import StudioError
    try:
        out = distance([float(x) for x in a], [float(x) for x in b], p["orientation"])
        ons = [[float(x) for x in q] if q is not None else None for q in (a_on, b_on)]
    except (TypeError, ValueError):
        raise StudioError("A measurement needs two points, each x,y,z in millimetres (design frame).")
    ends = []
    for pt in (ons[0] or out["from"], ons[1] or out["to"]):
        pr = probe(st, p, pt, rev)
        ends.append({"off_surface_mm": pr["off_surface_mm"], "feature": pr["feature"], "face": pr["face"]["type"]})
    out.update({"from_on": ends[0], "to_on": ends[1], "tessellation_mm": TOL, "rev": st.rev(p, rev)["n"],
                "note": "Straight-line distance between the two points given. off_surface_mm says how far each point is from "
                        f"the part's surface (tessellated at {TOL:g} mm)."})
    return out


def orientations(st, p: dict) -> dict:
    """Every way the head revision can rest on the plate, ranked. Cached by geometry and printer."""
    from .studio import H
    r = st.rev(p)
    gk = st.keys(p)["geometry"]
    pe = st.printer_env(p)                                       # the design's printer bed (form/printers.py)
    env, margin = list(pe["envelope"]), pe["margin"]
    cur = p["orientation"]
    key = H("orient", ANALYSIS_VERSION, gk, env, margin, cur if cur not in NAMED else None)
    out = _cached(st, p, "orient", key, lambda: st._k("orient", timeout=300, key=gk, recipe_id=st.rid(p), values=r["values"],
                                                       envelope=env, margin=margin, current=cur, p=p))
    dn = orientation_down(cur)
    for c in out["candidates"]:
        c["current"] = c["id"] == cur or float(np.asarray(c["down"]) @ dn) > 0.9995
    out.update({"current": cur, "current_label": orientation_label(cur), "rev": r["n"], "project": p["id"],
                "printer": pe["name"], "envelope_mm": env})
    return out


def orientation_thumbs(st, p: dict, result: dict, top: int = 3, size=(300, 240)) -> bytes:
    """The top candidates drawn as printed, side by side (for agents; the app draws its own in 3D)."""
    from . import render
    v = st.view(p)
    feats = [{"id": f.id, "label": f.label} for f in st.recipe(p).features]
    pngs = []
    for c in result["candidates"][:top]:
        R = orientation_matrix(c["id"])
        vd = {"mesh": [{**m, "positions": _b64((_unb64(m["positions"], np.float32, 3).astype(np.float64) @ R.T).astype(np.float32))}
                       for m in v["mesh"]]}
        pngs.append(render.render_png(vd, feats, "iso", size=size, overlay=False, title=f"{c['rank']}. {c['label']}",
                                      caption=f"score {c['score']:.3f} | {c['height_mm']:.0f} mm tall | {c['contact_mm2']:.0f} mm2 on plate"))
    return render.contact_sheet(pngs, cols=len(pngs))


def orientation_digest(result: dict, top: int = 8) -> dict:
    keep = ("rank", "id", "label", "score", "terms", "fits", "current", "height_mm", "footprint_mm", "contact_mm2", "steep_mm2",
            "ceiling_mm2", "support_mm3", "min_layer_mm2", "neck_scope")
    return {"current": result["current"], "current_label": result.get("current_label"), "formula": result["formula"],
            "terms": result["terms"], "evidence": result["evidence"], "not": result["not"], "tessellation_mm": result["tessellation_mm"],
            "structure_features": result["structure_features"], "candidates_evaluated": len(result["candidates"]),
            "candidates": [{k: (round(c[k], 2) if isinstance(c.get(k), float) and k not in ("score",) else c.get(k)) for k in keep}
                           for c in result["candidates"][:top]]}


# ── headless pictures ─────────────────────────────────────────────────────────

def chart_image(prof: dict, size=(420, 300), ink=(28, 27, 25), muted=(118, 114, 106), paper=(244, 241, 234)):
    """The section-area chart: area along x, height up, the neck marked."""
    from PIL import Image, ImageDraw
    from .render import _font
    W, H = size
    im = Image.new("RGB", size, paper)
    d = ImageDraw.Draw(im)
    f = _font(12)
    z, a = np.asarray(prof["z"]), np.asarray(prof["area"])
    l, r, t, b = 46, W - 16, 30, H - 34
    d.text((l, 8), "Slice area by height (geometry, not strength)", fill=ink, font=f)
    if len(z):
        amax, zmax = max(float(a.max()), 1e-9), max(float(prof["height_mm"]), 1e-9)
        pts = [(l + (r - l) * float(x) / amax, b - (b - t) * float(y) / zmax) for x, y in zip(a, z)]
        d.polygon([(l, b)] + pts + [(l, t)], fill=(214, 209, 198))
        d.line(pts, fill=ink, width=2)
        nk = prof.get("neck")
        if nk:
            y = b - (b - t) * nk["z_mm"] / zmax
            x = l + (r - l) * nk["area_mm2"] / amax
            d.line([(l, y), (r, y)], fill=SIGNAL, width=1)
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=SIGNAL)
            d.text((min(x + 8, r - 150), y - 16), f"neck {nk['area_mm2']:.0f} mm2 at {nk['z_mm']:.1f} mm", fill=SIGNAL, font=f)
        d.text((l, b + 6), "0", fill=muted, font=f)
        d.text((r - 60, b + 6), f"{amax:.0f} mm2", fill=muted, font=f)
        d.text((6, t - 4), f"{zmax:.0f}", fill=muted, font=f)
        d.text((6, b - 12), "0 mm", fill=muted, font=f)
    d.line([(l, t), (l, b), (r, b)], fill=ink, width=1)
    return im


def render_map_png(result: dict, title: str = "", view: str = "iso", size=(1100, 760), edges: str | None = None) -> bytes:
    """A picture of a map an agent can look at: the coloured part, the legend with units, and what it does not tell you."""
    from PIL import Image, ImageDraw
    from . import render
    W, H = size
    panel = 330
    vd = {"mesh": [{"feature": "map", "positions": result["positions"], "indices": result["indices"], "colors": result["colors"]}]}
    if edges:
        vd["edges"] = edges
    cam, below = None, False
    if result["map"] in ("overhang", "section"):           # draw these as printed; overhangs are seen from under the plate
        R = orientation_matrix(result["orientation"])
        P = _unb64(result["positions"], np.float32, 3).astype(np.float64) @ R.T
        vd["mesh"][0]["positions"] = _b64(P.astype(np.float32))
        if edges:
            E = _unb64(edges, np.float32, 6).astype(np.float64)
            vd["edges"] = _b64(np.hstack([E[:, :3] @ R.T, E[:, 3:] @ R.T]).astype(np.float32))
        below = result["map"] == "overhang" and view == "iso"
        cam = (-55.0, -24.0) if below else None
    lines = None
    if result.get("lines"):
        L = _unb64(result["lines"], np.float32, 6).astype(np.float64)
        if result["map"] in ("overhang", "section"):
            L = np.hstack([L[:, :3] @ R.T, L[:, 3:] @ R.T])
        lines = [(L, AMBER)]
    img = render.render_png(vd, [], view, size=(W - panel, H), title=title, camera=cam, overlay=False, as_image=True, lines=lines,
                            caption=f"{result['label']} · computed on the {result['tessellation_mm']:g} mm tessellation"
                                    + (f" · as printed ({result['orientation_label']})" if result["map"] in ("overhang", "section") else "")
                                    + (", seen from below" if below else ""))
    out = Image.new("RGB", (W, H), render.PAPER)
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    _text = d.text
    plain = lambda t: t.replace("–", "-").replace("²", "2").replace("³", "3").replace("·", "|").replace("Ø", "dia ").replace("“", '"').replace("”", '"')
    d.text = lambda xy, t, **kw: _text(xy, plain(t), **kw)      # Pillow's built-in font has no en dash, superscripts or middle dot
    f_t, f_s = render._font(16), render._font(12)
    x, y = W - panel + 8, 16
    lg = result["legend"]
    d.text((x, y), lg["title"], fill=render.INK, font=f_t)
    y += 24
    d.text((x, y), f"{lg['unit']} · {lg['evidence']}" + (f" · printed {result['orientation_label']}" if result["map"] in ("overhang", "section") else ""),
           fill=render.MUTED, font=f_s)
    y += 24

    def wrap(text, width):
        words, line, lines = text.split(), "", []
        for w in words:
            if d.textlength((line + " " + w).strip(), font=f_s) > width:
                lines.append(line)
                line = w
            else:
                line = (line + " " + w).strip()
        return lines + [line]
    for s in lg["stops"]:
        c0 = tuple(int(s["color"][i:i + 2], 16) for i in (1, 3, 5))
        c1 = tuple(int(s["to"][i:i + 2], 16) for i in (1, 3, 5)) if s.get("to") else c0
        for k in range(28):
            d.line([(x + k, y), (x + k, y + 13)], fill=tuple(int(c0[j] + (c1[j] - c0[j]) * k / 27) for j in range(3)))
        d.rectangle([x, y, x + 28, y + 13], outline=render.INK)
        d.text((x + 36, y - 1), s["label"], fill=render.INK, font=f_s)
        y += 17
        for ln in wrap(s.get("note", ""), panel - 52):
            d.text((x + 36, y), ln, fill=render.MUTED, font=f_s)
            y += 15
        y += 5
    y += 6
    for k, v in (result.get("stats") or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            d.text((x, y), f"{k.replace('_', ' ')}: {v:g}", fill=render.INK, font=f_s)
            y += 16
    y += 8
    for ln in wrap(lg["what"], panel - 20):
        d.text((x, y), ln, fill=render.INK, font=f_s)
        y += 15
    y += 8
    for ln in wrap(lg["not"], panel - 20):
        d.text((x, y), ln, fill=render.MUTED, font=f_s)
        y += 15
    if result.get("chart"):
        ch = chart_image(result["chart"], size=(panel - 16, 240))
        out.paste(ch, (x, min(y + 12, H - 250)))
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def digest(result: dict) -> dict:
    """A map without its arrays: what the CLI prints and MCP returns next to the picture."""
    drop = ("positions", "indices", "values", "colors", "classes")
    out = {k: v for k, v in result.items() if k not in drop}
    if out.get("chart"):
        ch = out["chart"]
        n = max(1, len(ch["z"]) // 60)
        out["chart"] = {**ch, "z": ch["z"][::n], "area": ch["area"][::n], "sampled_every": n}
    out["markers"] = out.get("markers", [])[:30]
    return out
