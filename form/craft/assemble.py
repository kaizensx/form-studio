"""Multi-part designs: separate parts with a measured clearance, a split with a lip, magnets from stock, lenses.

A design that prints as several parts returns them side by side in its last stage. Never fuse separate parts (a
fuse that must keep two solids fails as soon as they touch); name them instead:

    from form import craft
    out = craft.parts(shell=body, faceplate=plate, lens_l=a, lens_r=b, clearance=0.15)   # measured, or a RecipeError
    craft.part_list(out)                     # [Part(...)] for Recipe.assembly(), each found by a point inside it

    sp = craft.split(body, skin, wall=4, region=region, gap=0.2, lip=14)      # region(g): the insert grown by g
    sp = sp.magnets([spot, ...], stock="6x2", fit="glue")                               # coaxial pocket pairs
    lens = craft.lens(skin, window, depth=4.2, thickness=3)                             # its own part

Magnets come from MAGNETS (common N35-N52 disc stock, nominal sizes) with the pocket clearances in MAGNET_FITS
(FDM assumptions). Every pocket leaves at least MAGNET_FLOOR (0.6 mm) of material behind the magnet, so it never
shows through a face, and both pockets of a pair are built from one point and one axis, so they are coaxial by
construction. The pull force is unknown unless you give a datasheet value (pull_n, with its source): it depends on
grade, gap and the other magnet, and Form Studio never invents it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ._common import attempt, fail, need, note, num, one

#: Disc magnet stock: nominal diameter x thickness in mm (the sizes sold for prop and case making). Dimensions are
#: nominal catalogue sizes ("specified"); check your batch with calipers, tolerances are often +-0.05 to 0.1 mm.
MAGNETS = {"6x2": {"d": 6.0, "t": 2.0}, "6x3": {"d": 6.0, "t": 3.0}, "8x3": {"d": 8.0, "t": 3.0},
           "10x3": {"d": 10.0, "t": 3.0}}
#: Pocket clearances per side (radial) and in depth, mm. FDM assumptions, not measured: tune with a test coupon.
#: press: pushed in, held by interference of the printed wall; glue: a film of CA or epoxy; printed: dropped in
#: during a paused print and printed over (the depth includes room for the first layer bridging over it).
MAGNET_FITS = {"press": {"radial": 0.05, "depth": 0.10}, "glue": {"radial": 0.15, "depth": 0.20},
               "printed": {"radial": 0.25, "depth": 0.30}}
#: Material left behind every magnet, mm.
MAGNET_FLOOR = 0.6


def magnet(stock: str = "6x2", fit: str = "glue", pull_n: float | None = None, source: str = "") -> dict:
    """One stock magnet with its pocket: {"stock", "d", "t", "fit", "pocket_d", "pocket_depth", "floor", "pull"}.
    pull is {"value": None, "provenance": "unknown"} unless a datasheet value pull_n (newtons) is given with its
    source, then {"value", "unit": "N", "provenance": "specified", "source"}."""
    need(stock in MAGNETS, f"magnet: unknown stock {stock!r}", "Use one of: " + ", ".join(MAGNETS), ["stock"])
    need(fit in MAGNET_FITS, f"magnet: unknown fit {fit!r}", "Use one of: " + ", ".join(MAGNET_FITS), ["fit"])
    m, f = MAGNETS[stock], MAGNET_FITS[fit]
    if pull_n is None:
        pull = {"value": None, "unit": "N", "provenance": "unknown",
                "note": "pull force depends on grade, gap and the mating magnet; give a datasheet value"}
    else:
        need(bool(source), "magnet: a pull force needs its source", "Name the datasheet the value comes from.",
             ["source"])
        pull = {"value": num(pull_n, "pull_n", positive=True), "unit": "N", "provenance": "specified", "source": source}
    return {"stock": stock, "d": m["d"], "t": m["t"], "fit": fit, "pocket_d": round(m["d"] + 2 * f["radial"], 3),
            "pocket_depth": round(m["t"] + f["depth"], 3), "floor": MAGNET_FLOOR, "pull": pull}


def _cyl(base, axis, d: float, h: float):
    """A cylinder of diameter d from base along axis for h mm."""
    from build123d import Cylinder, Plane, Pos
    pl = Plane(origin=tuple(float(x) for x in base), z_dir=tuple(float(x) for x in axis))
    return pl.location * Pos(0, 0, h / 2) * Cylinder(d / 2, h)


@dataclass
class MagnetPair:
    """Two magnet pockets on one axis: part A's opens on its contact face at `at` and goes against `axis`; part B's
    opens `gap` mm further along the axis (B's contact face) and goes along it. Built from one point and one axis,
    the two pockets are coaxial by construction."""
    at: tuple
    axis: tuple
    spec: dict
    gap: float = 0.0

    def _u(self):
        u = np.asarray(self.axis, float)
        return u / (np.linalg.norm(u) or 1.0)

    def pocket_a(self):
        """The cutter for part A: the pocket depth back into A from its contact face, reaching 1 mm past B's contact
        face (cut it from A only), so a curved contact face never leaves a skin over the pocket."""
        u, p = self._u(), np.asarray(self.at, float)
        lead = self.gap + 1.0
        return _cyl(p + u * lead, -u, self.spec["pocket_d"], self.spec["pocket_depth"] + lead)

    def pocket_b(self):
        """The cutter for part B: the pocket depth into B from its contact face (gap mm along the axis from at),
        starting 1 mm behind A's contact face (cut it from B only)."""
        u, p = self._u(), np.asarray(self.at, float)
        lead = self.gap + 1.0
        return _cyl(p - u * 1.0, u, self.spec["pocket_d"], self.spec["pocket_depth"] + lead)

    def floor(self, part, side: str = "a", rays: int = 9) -> float:
        """The material measured behind the pocket on the built part (mm): rays from the pocket's floor (its centre
        and points round its rim) along the pocket's axis to the part's far surface; the smallest. On a curved part
        it is less than the flat-plate figure, so check it against MAGNET_FLOOR."""
        from .organic import surface_point
        u, p = self._u(), np.asarray(self.at, float)
        s = -1.0 if side == "a" else 1.0
        base = p + s * u * (self.spec["pocket_depth"] + (0.0 if side == "a" else self.gap))
        ref = np.array([0, 0, 1.0]) if abs(u[2]) < 0.9 else np.array([1.0, 0, 0])
        e1 = np.cross(u, ref)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(u, e1)
        r = self.spec["pocket_d"] / 2 * 0.98
        pts = [base] + [base + r * (math.cos(a) * e1 + math.sin(a) * e2)
                        for a in np.linspace(0, 2 * math.pi, rays - 1, endpoint=False)]
        best = float("inf")
        for q in pts:
            try:
                hit, _ = surface_point(part, tuple(q + s * u * 1e-3), tuple(s * u))
            except Exception:
                continue
            best = min(best, float(np.linalg.norm(np.asarray(hit) - q)))
        return best

    def boss(self, side: str = "a", start: float = 0.3, wall: float = 1.6):
        """A round boss that carries the pocket where the part is thinner than the pocket plus the floor: from
        `start` mm behind the contact face to the pocket's floor, magnet + 2 x wall wide. Fuse it before cutting."""
        u, p = self._u(), np.asarray(self.at, float)
        s = -1.0 if side == "a" else 1.0
        base = p + s * u * (start if side == "a" else self.gap + start)
        h = self.spec["pocket_depth"] + MAGNET_FLOOR - start
        return _cyl(base, s * u, self.spec["pocket_d"] + 2 * wall, h)

    def public(self) -> dict:
        return {"at": [round(x, 3) for x in self.at], "axis": [round(x, 4) for x in self._u()], "gap": self.gap,
                **{k: self.spec[k] for k in ("stock", "fit", "pocket_d", "pocket_depth", "floor", "pull")}}


def magnet_pair(at, axis, stock: str = "6x2", fit: str = "glue", gap: float = 0.0, room_a: float | None = None,
                room_b: float | None = None, pull_n: float | None = None, source: str = "") -> MagnetPair:
    """A coaxial pair of magnet pockets across a joint. at: a point on part A's contact face; axis: from A into B;
    gap: the designed gap between the two contact faces. room_a / room_b: the material behind each contact face
    (mm); a side with less room than pocket depth + MAGNET_FLOOR raises, so grow a boss there (MagnetPair.boss)
    and pass room=None for it."""
    spec = magnet(stock, fit, pull_n, source)
    g = num(gap, "gap", lo=0.0, hi=5.0)
    need_mm = spec["pocket_depth"] + MAGNET_FLOOR
    for side, room in (("A", room_a), ("B", room_b)):
        if room is not None:
            need(room >= need_mm - 1e-6, f"magnet_pair: part {side} has {room:.2f} mm behind its contact face; a {stock} "
                 f"magnet ({spec['fit']} fit) needs {need_mm:.2f} mm (pocket {spec['pocket_depth']:g} + floor "
                 f"{MAGNET_FLOOR:g})", "Use a thinner magnet, a thicker wall, or grow a boss on that side.",
                 ["stock", "wall"])
    return MagnetPair(tuple(float(x) for x in at), tuple(float(x) for x in axis), spec, g)


def pocket_axes(shape, diameter: float, tol: float = 0.02) -> list[tuple[np.ndarray, np.ndarray]]:
    """The axes (point, unit direction) of the cylindrical faces of `shape` with this diameter: where its magnet
    pockets are, measured on the built B-rep."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    out = []
    for f in shape.faces():
        ad = BRepAdaptor_Surface(f.wrapped)
        if ad.GetType() != GeomAbs_Cylinder:
            continue
        cy = ad.Cylinder()
        if abs(2 * cy.Radius() - diameter) > tol:
            continue
        ax = cy.Axis()
        p, d = ax.Location(), ax.Direction()
        out.append((np.array([p.X(), p.Y(), p.Z()]), np.array([d.X(), d.Y(), d.Z()])))
    return out


def coaxial_error(pair: MagnetPair, part_a, part_b) -> dict:
    """How far apart the two pockets' measured axes are: {"offset_mm", "angle_deg"} (0, 0 for a perfect pair), from
    the cylindrical faces found nearest the pair on each built part."""
    d = pair.spec["pocket_d"]
    at = np.asarray(pair.at, float)

    def near(shape):
        axes = pocket_axes(shape, d)
        need(bool(axes), "coaxial_error: no pocket of that diameter on the part", "Cut the pockets first.", [])

        def dist(a):
            p, u = a
            v = at - p
            return np.linalg.norm(v - np.dot(v, u) * u)
        return min(axes, key=dist)
    (pa, ua), (pb, ub) = near(part_a), near(part_b)
    ang = math.degrees(math.acos(min(1.0, abs(float(np.dot(ua, ub))))))
    v = pb - pa
    off = float(np.linalg.norm(v - np.dot(v, ua) * ua))
    return {"offset_mm": round(off, 4), "angle_deg": round(ang, 4)}


# ---- separate parts ------------------------------------------------------------------------------------------------

GAP_TOL = 0.02          # tessellation deflection (mm) used to find where two parts come closest


def _mesh(s, tol: float = GAP_TOL, max_edge: float = 3.0):
    """Vertices (n, 3) with their face index, and triangles (m, 3, 3) with theirs, face by face; long triangles are
    split until no edge is over max_edge. Returns (V, vface, T, tface, faces, unmeshed): faces the mesher could not
    triangulate are listed in unmeshed (their distance is taken on the exact B-rep instead)."""
    faces = s.faces()
    Vs, vf, Ts, tf, bad = [], [], [], [], []
    for k, f in enumerate(faces):
        try:
            v, t = f.tessellate(tol, 0.2)
        except Exception:
            bad.append(f)
            continue
        if not t:
            bad.append(f)
            continue
        V = np.array([(p.X, p.Y, p.Z) for p in v], float)
        T = V[np.asarray(t, int)]
        for _ in range(8):
            e = np.max(np.linalg.norm(T - np.roll(T, 1, axis=1), axis=2), axis=1)
            big = e > max_edge
            if not big.any():
                break
            B = T[big]
            m01, m12, m20 = (B[:, 0] + B[:, 1]) / 2, (B[:, 1] + B[:, 2]) / 2, (B[:, 2] + B[:, 0]) / 2
            T = np.concatenate([T[~big], np.stack([B[:, 0], m01, m20], 1), np.stack([m01, B[:, 1], m12], 1),
                                np.stack([m20, m12, B[:, 2]], 1), np.stack([m01, m12, m20], 1)])
        Vs.append(V)
        vf.append(np.full(len(V), k))
        Ts.append(T)
        tf.append(np.full(len(T), k))
    if not Vs:
        return np.zeros((0, 3)), np.zeros(0, int), np.zeros((0, 3, 3)), np.zeros(0, int), faces, bad
    return np.concatenate(Vs), np.concatenate(vf), np.concatenate(Ts), np.concatenate(tf), faces, bad


def _point_tri(P, A, B, C):
    """Distance from points P (n, 3) to triangles (A, B, C each (n, 3)), Ericson's closest-point regions."""
    ab, ac, ap = B - A, C - A, P - A
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = P - B
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = P - C
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = np.where(np.abs(va + vb + vc) > 1e-30, va + vb + vc, 1e-30)
    v, w = vb / den, vc / den
    Q = A + ab * v[:, None] + ac * w[:, None]                          # inside the face
    eps = 1e-30

    def seg(X, Y, t):
        return X + (Y - X) * np.clip(t, 0, 1)[:, None]
    r_a = (d1 <= 0) & (d2 <= 0)
    r_b = (d3 >= 0) & (d4 <= d3)
    r_c = (d6 >= 0) & (d5 <= d6)
    r_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    r_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    r_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    Q = np.where(r_bc[:, None], seg(B, C, (d4 - d3) / np.maximum((d4 - d3) + (d5 - d6), eps)), Q)
    Q = np.where(r_ac[:, None], seg(A, C, d2 / np.maximum(d2 - d6, eps)), Q)
    Q = np.where(r_ab[:, None], seg(A, B, d1 / np.maximum(d1 - d3, eps)), Q)
    Q = np.where(r_c[:, None], C, Q)
    Q = np.where(r_b[:, None], B, Q)
    Q = np.where(r_a[:, None], A, Q)
    return np.linalg.norm(P - Q, axis=1)


def _one_way(MA, MB, reach: float, k: int = 12):
    """Mesh distance from every vertex of A (within reach of B's box) to B's triangles: (points, their A face,
    distance, nearest B face)."""
    from scipy.spatial import cKDTree
    Va, vfa = MA[0], MA[1]
    Tb, tfb = MB[2], MB[3]
    if not len(Tb) or not len(Va):
        return Va[:0], vfa[:0], np.zeros(0), np.zeros(0, int)
    lo, hi = Tb.reshape(-1, 3).min(0) - reach, Tb.reshape(-1, 3).max(0) + reach
    sel = np.all((Va >= lo) & (Va <= hi), axis=1)
    P, fa = Va[sel], vfa[sel]
    if not len(P):
        return P, fa, np.zeros(0), np.zeros(0, int)
    tree = cKDTree(Tb.mean(1))
    _, idx = tree.query(P, k=min(k, len(Tb)))
    idx = idx[:, None] if idx.ndim == 1 else idx
    best = np.full(len(P), np.inf)
    fb = np.zeros(len(P), int)
    for j in range(idx.shape[1]):
        tri = Tb[idx[:, j]]
        d = _point_tri(P, tri[:, 0], tri[:, 1], tri[:, 2])
        better = d < best
        best = np.where(better, d, best)
        fb = np.where(better, tfb[idx[:, j]], fb)
    return P, fa, best, fb


def _project(p, face):
    """The closest point of a face to p (exact, BRepExtrema) and its distance."""
    from build123d import Vertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    ext = BRepExtrema_DistShapeShape(Vertex(*map(float, p)).wrapped, face.wrapped)
    ext.Perform()
    q = ext.PointOnShape2(1)
    return np.array([q.X(), q.Y(), q.Z()]), float(ext.Value())


def _gap(a, b, reach: float = 5.0, candidates: int = 10) -> float:
    """Smallest distance between the surfaces of two solids. The tessellations (deflection GAP_TOL) find where the
    parts come closest, point to triangle both ways; each of the closest spots is then refined on the exact B-rep
    (alternating closest points between the two faces, BRepExtrema point to face). One BRepExtrema call on the whole
    shapes is far slower here: parallel offset skins have a whole surface of minima. inf when farther than reach."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    MA, MB = _mesh(a), _mesh(b)
    best = float("inf")
    exact = float("inf")
    for faces, other in ((MA[5], b), (MB[5], a)):            # faces the mesher skipped: exact, face by face
        for f in faces:
            ext = BRepExtrema_DistShapeShape(f.wrapped, other.wrapped)
            ext.Perform()
            if ext.IsDone():
                exact = min(exact, float(ext.Value()))
    rows = []
    for M1, M2, flip in ((MA, MB, False), (MB, MA, True)):
        P, f1, d, f2 = _one_way(M1, M2, reach)
        if len(d):
            best = min(best, float(d.min()))
            for i in np.argsort(d)[: candidates * 4]:
                rows.append((float(d[i]), P[i], (M2[4][f2[i]], M1[4][f1[i]]) if flip else (M1[4][f1[i]], M2[4][f2[i]])))
    if not rows:
        return min(best, exact)
    rows.sort(key=lambda r: r[0])
    picked = []
    for r in rows:                                          # spatially distinct spots
        if all(np.linalg.norm(r[1] - q[1]) > 2.0 for q in picked):
            picked.append(r)
        if len(picked) >= candidates:
            break
    for _, p, (fa, fb) in picked:
        pa = _project(p, fa)[0]
        for _ in range(3):
            qb, _d = _project(pa, fb)
            pa, dd = _project(qb, fa)
        exact = min(exact, dd)
    return exact


def _nested(a, b) -> bool:
    """One solid wholly inside the other (their surfaces never meet, so the gap alone cannot tell)."""
    from build123d import Vector
    for x, y in ((a, b), (b, a)):
        p = x.vertices()[0] if x.vertices() else None
        if p is not None and y.is_inside(Vector(p.X, p.Y, p.Z)):
            return True
    return False


def _overlap(a, b) -> float:
    try:
        r = a & b
        return float(sum(s.volume for s in r.solids()))
    except Exception:
        return 0.0


def _bbox_gap(a, b) -> float:
    A, B = a.bounding_box(), b.bounding_box()
    d = [max(0.0, max(getattr(A.min, k) - getattr(B.max, k), getattr(B.min, k) - getattr(A.max, k))) for k in "XYZ"]
    return math.sqrt(sum(x * x for x in d))


def parts(clearance: float = 0.2, touching=(), **named):
    """Separate parts as one result (a Compound, each solid labelled with its name): parts(shell=a, visor=b).
    Every pair is measured: two parts that overlap, or come closer than `clearance` mm, raise a RecipeError naming the
    pair and the measured gap. touching: pairs [("a", "b")] that may rest on each other (a lid on a box). The gaps
    are left as a craft note. This replaces fuse(a, b, max_solids=2, min_solids=2), which fails when parts touch."""
    from build123d import Compound
    need(len(named) >= 1, "parts: give at least one part, by name", "parts(shell=body, visor=visor)", [])
    c = num(clearance, "clearance", lo=0.0, hi=20.0)
    ok_touch = {frozenset(p) for p in touching}
    solids = {}
    for name, s in named.items():
        sol = s.solids() if hasattr(s, "solids") else []
        need(len(sol) >= 1, f"parts: {name} has no solid", f"Pass a solid for {name}.", [name])
        need(all(x.is_valid for x in sol), f"parts: {name} is not a valid solid", "Repair it (craft.repair) first.",
             [name])
        solids[name] = sol
    names = list(solids)
    gaps = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            lo = None
            for sa in solids[a]:
                for sb in solids[b]:
                    g = _bbox_gap(sa, sb)
                    if g <= max(c, 0.01) + 1e-6:
                        g = _gap(sa, sb, reach=max(c, 0.01) + 1.0)
                        vol = _overlap(sa, sb) if g < 1e-3 or _nested(sa, sb) else 0.0
                        need(vol < 1e-3, f"parts: {a} and {b} overlap ({vol:.1f} mm3)",
                             f"Separate {a} and {b} by at least {c:g} mm.", [a, b])
                    if g != float("inf"):
                        lo = g if lo is None else min(lo, g)
            gaps[(a, b)] = lo
            if lo is not None and lo < c - 1e-3 and frozenset((a, b)) not in ok_touch:
                raise fail(f"parts: {a} and {b} are {lo:.3f} mm apart, under the {c:g} mm clearance",
                           f"Open the gap between {a} and {b}, or list the pair in touching if they rest on each other.",
                           [a, b])
    close = [f"{a}-{b} {g:.2f} mm" for (a, b), g in gaps.items() if g is not None and g < 5]
    if close:
        note("parts: measured gaps " + ", ".join(close))
    flat, labels = [], []
    for name, sol in solids.items():
        for k, s in enumerate(sol):
            s.label = name if len(sol) == 1 else f"{name}_{k + 1}"
            flat.append(s)
            labels.append(s.label)
    out = Compound(flat)
    out.label = "parts"
    out.part_names = labels                     # in the order of out.solids()
    out.part_gaps = {f"{a}-{b}": (None if g is None else round(g, 3)) for (a, b), g in gaps.items()}
    return out


def named_parts(result) -> dict:
    """{name: solid} of a parts() result (its solids in order, by the names given)."""
    sol = result.solids()
    names = getattr(result, "part_names", None) or [s.label or f"part_{i + 1}" for i, s in enumerate(sol)]
    return dict(zip(names, sol))


def inside_point(solid) -> tuple:
    """A point inside the solid (a shell's centre is in its hollow, so step in from a face)."""
    c = solid.center()
    if solid.is_inside(c):
        return (c.X, c.Y, c.Z)
    for f in sorted(solid.faces(), key=lambda f: -f.area)[:6]:
        p = f.position_at(0.5, 0.5)
        n = f.normal_at(p)
        for e in (0.15, 0.4, 0.8, 1.5):
            q = p - n * e
            if solid.is_inside(q):
                return (q.X, q.Y, q.Z)
    raise fail("inside_point: no point found inside the solid", "Check that the part is a closed solid.", [])


def part_list(result, labels: dict | None = None, notes: dict | None = None, explode: dict | None = None) -> list:
    """Assembly Parts for the result of parts(): each is found by a point inside it, so nobody counts solids.
    labels / notes / explode: {name: value} for the part's label, assembly step and exploded offset."""
    from ..recipes.assembly import Part
    out = []
    for name, s in named_parts(result).items():
        out.append(Part(name, (labels or {}).get(name, name.replace("_", " ").capitalize()), inside_point(s),
                        explode=tuple((explode or {}).get(name, (0.0, 0.0, 0.0))), note=(notes or {}).get(name, "")))
    return out


# ---- a split with a lip --------------------------------------------------------------------------------------------

@dataclass
class Split:
    """The result of split(): the body with its opening and ledge, the insert that fills the opening, and the depths
    (offsets from the skin, mm) of the joint. magnets() adds coaxial pocket pairs across the ledge."""
    body: object
    insert: object
    ledge: object
    skin: object
    contact: float                       # the ledge's top: offset from the skin (negative: under it)
    gap: float
    room_body: float                     # the ledge's thickness (a boss under it carries the body's pocket)
    room_insert: float                   # the insert's flange over the ledge
    pairs: list = field(default_factory=list)

    def magnets(self, spots, stock: str = "6x2", fit: str = "glue", boss_wall: float = 1.6, pull_n=None,
                source: str = "") -> "Split":
        """Magnet pairs across the ledge. spots: [(origin, direction), ...] rays that meet the skin over the ledge
        (from inside the body outward). Each ray finds the ledge's top (the contact face) and its normal; the body's
        pocket sits in a boss grown under the ledge, the insert's in its flange. Raises if the flange is too thin."""
        from .surfaces import cut, fuse
        body, ins = self.body, self.insert
        for origin, direction in spots:
            p, nrm = self.skin.ray(origin, direction, self.contact)
            need(self.ledge.is_inside(_v(np.asarray(p) - np.asarray(nrm) * min(0.3, self.room_body / 2))),
                 f"split.magnets: the spot at ({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f}) is not over the ledge",
                 "Aim the ray at the middle of the lip.", ["spots"])
            pr = magnet_pair(p, nrm, stock, fit, self.gap, room_b=self.room_insert, pull_n=pull_n, source=source)
            # the boss starts inside the ledge, deep enough that its flat top stays under a curved contact face
            body = fuse(body, pr.boss("a", start=0.6 * self.room_body, wall=boss_wall))
            body = cut(body, pr.pocket_a())
            ins = cut(ins, pr.pocket_b())
            self.pairs.append(pr)
        self.body, self.insert = one(body), one(ins)
        for pr in self.pairs:
            for side, part in (("a", self.body), ("b", self.insert)):
                fl = pr.floor(part, side)
                need(fl >= MAGNET_FLOOR - 0.02, f"split.magnets: {fl:.2f} mm behind the {pr.spec['stock']} pocket at "
                     f"({pr.at[0]:.1f}, {pr.at[1]:.1f}, {pr.at[2]:.1f}), under the {MAGNET_FLOOR:g} mm floor",
                     "Use a thinner magnet, a thicker wall, or move the spot where the skin is flatter.",
                     ["stock", "wall", "spots"])
        return self


def _v(p):
    from build123d import Vector
    return Vector(*map(float, p))


def split(body, skin, wall: float, region, gap: float = 0.2, lip: float = 12.0, ledge: float = 1.0,
          overlap: float = 0.5) -> Split:
    """Split an insert (a faceplate, a hatch, a lid in a curved shell) out of a skin shell, with a lip it rests on.

    body: the shell (skin.shell(wall), with whatever was cut or added since); region(g): a function returning the
    insert's region grown by g mm (negative shrinks). Grow it with a true 2D offset, so the gap is the same all
    round (grow_outline only moves the points, and a spline through them can come within a tenth of the gap):
        face = craft.spline_profile(side, plane=Plane.XZ)
        region = lambda g: extrude(offset(face, g).faces()[0] if g else face, 400, both=True)
    The body loses region(gap); a ledge `ledge` mm thick at the bottom of the wall
    reaches `lip` mm under the insert; the insert is the outer part of the wall over the lip (wall - ledge - gap
    thick) and the full wall inside it, `gap` mm clear of the body everywhere. Returns a Split."""
    from .surfaces import cut, fuse
    t, g = num(wall, "wall", positive=True), num(gap, "gap", lo=0.05, hi=3.0)
    lp, lg = num(lip, "lip", lo=2.0), num(ledge, "ledge", lo=0.4)
    need(lg + g < t - 0.4, f"split: a {lg:g} mm ledge and a {g:g} mm gap leave no flange in a {t:g} mm wall",
         "Use a thinner ledge or a thicker wall.", ["ledge", "wall"])
    r0, r_out, r_in, r_core = region(0.0), region(g), region(-lp), region(-(lp + g))
    contact = -t + lg
    opened = cut(body, r_out)
    ring = attempt("split", [("ledge ring", lambda: one(region(overlap) - r_in))],
                   "The region is smaller than the lip; use a smaller lip.", ["lip", "region"])
    led = attempt("split", [("ledge", lambda: one(skin.layer(-t, contact) & ring))],
                  "The ledge region does not meet the skin.", ["region"])
    new = fuse(opened, led)
    flange = attempt("split", [("flange", lambda: one(skin.layer(contact + g, 0.0) & r0))],
                     "The region does not meet the skin.", ["region"])
    core = attempt("split", [("core", lambda: one(skin.layer(-t, contact + g + 0.3) & r_core))],
                   "The lip is wider than the region.", ["lip", "region"])
    insert = fuse(flange, core)
    return Split(one(new), one(insert), led, skin, contact, g, lg, t - lg - g)


def lens(skin, region, depth: float, thickness: float = 3.0):
    """A lens (or any panel) as its own part, following the skin's inside: the layer from depth to depth + thickness
    mm under the skin, clipped to region. A lens behind a faceplate `wall` thick with a gap: depth = wall + gap."""
    d, th = num(depth, "depth", lo=0.0), num(thickness, "thickness", positive=True)
    lay = skin.layer(-(d + th), -d)
    return attempt("lens", [("clip", lambda: lay & region)], "The lens region does not reach the skin.", ["region"])
