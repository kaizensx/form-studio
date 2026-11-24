"""Small closed cages for the kit: lathes, boxes, prisms, rings and sweeps, joined and moved as plain arrays.

A Shell is points V (n, 3) in millimetres, polygons F (point indices, outward by the right-hand rule) and creases
[[a, b, weight 0..1], ...] (Blender's edge crease; 1 is sharp after subdivision). Every builder here returns closed,
consistently oriented shells (each directed edge used once), so a part made of them is a valid subdivision cage.

Plain numpy and math: no Blender, no OCCT.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

EPS = 1e-9


@dataclass
class Shell:
    V: np.ndarray
    F: list
    C: list = field(default_factory=list)

    def __post_init__(self):
        self.V = np.asarray(self.V, dtype=np.float64).reshape(-1, 3)
        self.F = [[int(i) for i in f] for f in self.F]
        self.C = [[int(a), int(b), float(w)] for a, b, w in self.C]

    def moved(self, R=None, t=(0.0, 0.0, 0.0), s=1.0) -> "Shell":
        """Scaled (scalar or per axis), then rotated by R (3x3, det > 0 keeps the orientation), then moved by t."""
        V = self.V * np.asarray(s, dtype=np.float64)
        F = self.F
        if np.ndim(s) and np.prod(np.sign(s)) < 0:            # a mirror flips every polygon
            F = [list(reversed(f)) for f in F]
        if R is not None:
            V = V @ np.asarray(R, dtype=np.float64).T
        return Shell(V + np.asarray(t, dtype=np.float64), F, self.C)


def join(*shells: Shell) -> Shell:
    V, F, C, off = [], [], [], 0
    for s in shells:
        V.append(s.V)
        F += [[i + off for i in f] for f in s.F]
        C += [[a + off, b + off, w] for a, b, w in s.C]
        off += len(s.V)
    return Shell(np.concatenate(V) if V else np.zeros((0, 3)), F, C)


def rot(axis, deg: float) -> np.ndarray:
    """Rotation matrix about an axis through the origin (right-hand rule, degrees)."""
    a = np.asarray(axis, dtype=np.float64)
    a = a / np.linalg.norm(a)
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    x, y, z = a
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def align(src, dst) -> np.ndarray:
    """The rotation taking direction src to direction dst (the shortest one)."""
    a = np.asarray(src, float) / np.linalg.norm(src)
    b = np.asarray(dst, float) / np.linalg.norm(dst)
    c = float(np.clip(a @ b, -1, 1))
    ax = np.cross(a, b)
    if np.linalg.norm(ax) < 1e-12:
        if c > 0:
            return np.eye(3)
        ax = np.cross(a, [1.0, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1.0, 0])
    return rot(ax, math.degrees(math.acos(c)))


# ---- builders ------------------------------------------------------------------------------------------------------

def lathe(profile, n: int, phase: float = 0.0, closed: bool = False, ring_crease: dict | None = None,
          meridian_crease: float = 0.0, base_crease: float = 1.0) -> Shell:
    """A profile [(r, z), ...] turned about +Z in n steps (first step at `phase` degrees).

    base_crease: the crease on the rim of the first point's cap (an open profile's foot), so it stays flat.

    Open profile: it runs from the bottom round to the top with the solid on its left (counter-clockwise in the r-z
    plane); an end at r > 0 is closed by a flat polygon, an end at r = 0 by a fan of triangles. Closed profile: a
    ring (torus topology, all quads); its winding is fixed here. ring_crease {profile index: weight} creases the
    ring of edges at that profile point; meridian_crease creases the edges along the profile (faceted lathes)."""
    P = [(float(r), float(z)) for r, z in profile]
    if closed:
        area = sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))
        if area < 0:                                          # counter-clockwise in (r, z): the solid on the left
            P = P[::-1]
            if ring_crease:
                ring_crease = {len(P) - 1 - k: w for k, w in ring_crease.items()}
    m = len(P)
    ang = [math.radians(phase) + 2 * math.pi * k / n for k in range(n)]
    V, F, C, ring = [], [], [], []
    for r, z in P:
        if r <= EPS and not closed:
            ring.append([len(V)] * n)
            V.append((0.0, 0.0, z))
        else:
            ring.append(list(range(len(V), len(V) + n)))
            V += [(r * math.cos(a), r * math.sin(a), z) for a in ang]
    rows = m if closed else m - 1
    for i in range(rows):
        a, b = ring[i], ring[(i + 1) % m]
        for k in range(n):
            q = [a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]]
            q = [x for j, x in enumerate(q) if x != q[j - 1]] if len(set(q)) < 4 else q
            if len(q) >= 3:
                F.append(q)
    if not closed:
        if len(set(ring[0])) > 1:
            F.append(list(reversed(ring[0])))
        if len(set(ring[-1])) > 1:
            F.append(list(ring[-1]))
    rc = dict(ring_crease or {})
    if not closed and base_crease > 0 and len(set(ring[0])) > 1:
        rc[0] = max(rc.get(0, 0.0), base_crease)              # a flat foot: the base cap keeps its rim
    for i, w in rc.items():
        if w > 0 and len(set(ring[i])) > 1:
            C += [[ring[i][k], ring[i][(k + 1) % n], w] for k in range(n)]
    if meridian_crease > 0:
        for i in range(rows):
            a, b = ring[i], ring[(i + 1) % m]
            C += [[a[k], b[k], meridian_crease] for k in range(n) if a[k] != b[k]]
    return Shell(V, F, C)


def box(size, center=(0.0, 0.0, 0.0), crease: float = 1.0) -> Shell:
    sx, sy, sz = (float(s) / 2 for s in size)
    V = [(-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
         (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)]
    F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    E = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
    C = [[a, b, crease] for a, b in E] if crease > 0 else []
    return Shell(np.asarray(V) + np.asarray(center, float), F, C)


def _ccw(poly):
    P = [(float(x), float(y)) for x, y in poly]
    area = sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))
    return P if area > 0 else P[::-1]


def prism(poly, z0: float, z1: float, rim_crease: float = 1.0, side_crease: float = 0.0) -> Shell:
    """A polygon (x, y) pushed from z0 to z1: side quads, flat polygon caps."""
    P = _ccw(poly)
    n = len(P)
    V = [(x, y, z0) for x, y in P] + [(x, y, z1) for x, y in P]
    F = [[k, (k + 1) % n, n + (k + 1) % n, n + k] for k in range(n)]
    F += [list(range(n - 1, -1, -1)), list(range(n, 2 * n))]
    C = []
    if rim_crease > 0:
        C += [[k, (k + 1) % n, rim_crease] for k in range(n)] + [[n + k, n + (k + 1) % n, rim_crease] for k in range(n)]
    if side_crease > 0:
        C += [[k, n + k, side_crease] for k in range(n)]
    return Shell(V, F, C)


def ring_prism(outer, inner, z0: float, z1: float, crease: float = 1.0) -> Shell:
    """A flat ring: the area between two polygons with the same point count (inner inside outer), from z0 to z1.
    Torus topology, all quads."""
    O, I = _ccw(outer), _ccw(inner)
    n = len(O)
    if len(I) != n:
        raise ValueError("ring_prism needs the same number of points inside and out")
    V = [(x, y, z) for ring, z in ((O, z0), (O, z1), (I, z0), (I, z1)) for x, y in ring]
    o0, o1, i0, i1 = 0, n, 2 * n, 3 * n
    F = []
    for k in range(n):
        j = (k + 1) % n
        F += [[o0 + k, o0 + j, o1 + j, o1 + k], [i0 + j, i0 + k, i1 + k, i1 + j],
              [o1 + k, o1 + j, i1 + j, i1 + k], [o0 + k, i0 + k, i0 + j, o0 + j]]
    C = []
    if crease > 0:
        for base in (o0, o1, i0, i1):
            C += [[base + k, base + (k + 1) % n, crease] for k in range(n)]
    return Shell(V, F, C)


def circle(r: float, n: int, phase: float = 0.0, c=(0.0, 0.0)):
    return [(c[0] + r * math.cos(math.radians(phase) + 2 * math.pi * k / n),
             c[1] + r * math.sin(math.radians(phase) + 2 * math.pi * k / n)) for k in range(n)]


def rounded_rect(w: float, h: float, r: float, steps: int = 2):
    """A rectangle (centred) with round corners, 4 * (steps + 1) points, counter-clockwise."""
    r = min(r, w / 2 - 1e-6, h / 2 - 1e-6)
    out = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180),
                       (w / 2 - r, -h / 2 + r, 270)):
        for s in range(steps + 1):
            a = math.radians(a0 + 90 * s / steps)
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def fillet(path, r: float, steps: int = 3):
    """A polyline with every inner corner replaced by a circular arc of radius r (clamped to the legs)."""
    P = [np.asarray(p, float) for p in path]
    out = [P[0]]
    for i in range(1, len(P) - 1):
        a, b, c = P[i - 1], P[i], P[i + 1]
        u, v = a - b, c - b
        lu, lv = np.linalg.norm(u), np.linalg.norm(v)
        u, v = u / lu, v / lv
        cosang = float(np.clip(u @ v, -1, 1))
        half = math.acos(cosang) / 2
        if math.sin(half) < 1e-6 or abs(cosang) > 0.9999:
            out.append(b)
            continue
        d = min(r / math.tan(half), 0.49 * lu, 0.49 * lv)
        rr = d * math.tan(half)
        p0, p1 = b + u * d, b + v * d
        bis = (u + v) / np.linalg.norm(u + v)
        ctr = b + bis * (rr / math.sin(half))
        e0, e1 = p0 - ctr, p1 - ctr
        ang = math.acos(float(np.clip(e0 @ e1 / (np.linalg.norm(e0) * np.linalg.norm(e1)), -1, 1)))
        ax = np.cross(e0, e1)
        ax = ax / np.linalg.norm(ax)
        for s in range(steps + 1):
            out.append(ctr + rot(ax, math.degrees(ang * s / steps)) @ e0)
    out.append(P[-1])
    return out


def sweep(path, profile, closed: bool = False, scales=None, crease: dict | None = None, cap_crease: float = 0.0,
          up=None) -> Shell:
    """A closed profile [(u, v), ...] carried along a path [(x, y, z), ...] by parallel transport (no twist).

    Open path: flat polygon caps at both ends. Closed path: a ring (planar closed paths close without a seam twist).
    scales: one factor per path point (tapers). crease {profile index: weight} creases the lines along the path
    through that profile point; cap_crease creases the cap rims."""
    P = np.asarray(path, dtype=np.float64)
    prof = _ccw(profile)
    q = len(prof)
    m = len(P)
    seg = [(P[(i + 1) % m] - P[i]) for i in range(m if closed else m - 1)]
    seg = [s / np.linalg.norm(s) for s in seg]
    T = []
    for i in range(m):
        if closed:
            t = seg[i - 1] + seg[i]
        else:
            t = seg[0] if i == 0 else seg[-1] if i == m - 1 else seg[i - 1] + seg[i]
        T.append(t / np.linalg.norm(t))
    if closed:                                            # the plane's normal: transported unchanged round a plane
        nrm = np.zeros(3)
        for i in range(m):
            a, b = P[i], P[(i + 1) % m]
            nrm += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]),
                             (a[0] - b[0]) * (a[1] + b[1])])
        N0 = nrm / np.linalg.norm(nrm) if np.linalg.norm(nrm) > 1e-12 else None
    else:
        N0 = None
    if N0 is None or abs(N0 @ T[0]) > 1e-6:
        ref = np.asarray(up, float) if up is not None else np.array([0, 0, 1.0])
        if abs(ref @ T[0]) > 0.99:
            ref = np.array([1.0, 0, 0])
        N0 = ref - T[0] * (ref @ T[0])
        N0 /= np.linalg.norm(N0)
    N = [N0]
    for i in range(1, m):                                 # parallel transport: rotate by the tangent's turn
        R = align(T[i - 1], T[i])
        n = R @ N[-1]
        n = n - T[i] * (n @ T[i])
        N.append(n / np.linalg.norm(n))
    V = []
    for i in range(m):
        B = np.cross(T[i], N[i])
        s = 1.0 if scales is None else float(scales[i])
        # miter: in the plane of the bend the ring is stretched so the walls keep their thickness
        k = 1.0
        if 0 < i < m - 1 or closed:
            a, b = seg[i - 1], seg[i % len(seg)]
            c = float(np.clip(a @ b, -1, 1))
            k = 1.0 / max(math.cos(math.acos(c) / 2), 0.2)
        bend = (seg[i % len(seg)] - seg[i - 1]) if (0 < i < m - 1 or closed) else np.zeros(3)
        bl = np.linalg.norm(bend)
        bend = bend / bl if bl > 1e-9 else None
        for u, v in prof:
            off = (N[i] * u + B * v) * s
            if bend is not None:
                off = off + bend * (off @ bend) * (k - 1.0)
            V.append(P[i] + off)
    F = []
    rows = m if closed else m - 1
    for i in range(rows):
        a, b = i * q, ((i + 1) % m) * q
        for k in range(q):
            # profile counter-clockwise in (N, B) and N x B = T: the side faces point outward
            F.append([a + k, a + (k + 1) % q, b + (k + 1) % q, b + k])
    C = []
    if not closed:
        F.append(list(range(q - 1, -1, -1)))
        F.append([(m - 1) * q + k for k in range(q)])
        if cap_crease > 0:
            for base in (0, (m - 1) * q):
                C += [[base + k, base + (k + 1) % q, cap_crease] for k in range(q)]
    for j, w in (crease or {}).items():
        if w > 0:
            C += [[i * q + j, ((i + 1) % m) * q + j, w] for i in range(rows)]
    return Shell(V, F, C)


# ---- checks --------------------------------------------------------------------------------------------------------

def closed_and_oriented(F) -> bool:
    """Every directed edge used once and its reverse once: closed, manifold along edges, consistently oriented."""
    seen: dict = {}
    for f in F:
        for k in range(len(f)):
            e = (f[k], f[(k + 1) % len(f)])
            if e[0] == e[1]:
                return False
            seen[e] = seen.get(e, 0) + 1
    return all(c == 1 and seen.get((b, a)) == 1 for (a, b), c in seen.items())


def volume(V, F) -> float:
    """Signed volume (positive when the polygons face outward)."""
    V = np.asarray(V, float)
    vol = 0.0
    for f in F:
        a = V[f[0]]
        for k in range(1, len(f) - 1):
            vol += float(np.dot(a, np.cross(V[f[k]], V[f[k + 1]])))
    return vol / 6.0


def shells(F) -> list[list[int]]:
    """Face indices of each connected shell (faces that share a point)."""
    parent: dict = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for f in F:
        for v in f[1:]:
            ra, rb = find(f[0]), find(v)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups: dict = {}
    for i, f in enumerate(F):
        groups.setdefault(find(f[0]), []).append(i)
    return [groups[k] for k in sorted(groups)]
