"""Layer 2: a feature recipe (build123d source with Params) that rebuilds the mesh. Beta.

From the Layer 1 regions:

- holes: concave cylinders that go all the way round, with their depth, open or blind ends, and a standard size
  (holes.snap; provenance "computed from mesh");
- a base body: one extrusion (every other face is parallel to one direction, between two end faces) or one
  revolution (every surface shares one axis). Its profile is read from the regions themselves: a plane along the
  direction is a line, a cylinder along it an arc, a frozen facet a straight segment; around an axis, a cylinder,
  cone or plane is a line and a torus or sphere an arc;
- patterns: holes of one size on a grid, a line or a circle become one loop with pitch Params;
- symmetry: mirror planes and rotational symmetry of the mesh, reported (tested against the mesh, not assumed).

The source is built in the kernel and compared with the mesh. It is offered as the result only if it is a valid solid
within the limit; otherwise the report says what was found and why it was not enough.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from . import holes as holemod
from .brep import _runs
from .mesh import tri_normals

PAR = 1 - 1e-6           # |cos| above this: parallel
WHY: list = []           # why the last extrude_plan found no extrusion, per direction tried


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def _frame(d):
    t = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    u = _unit(np.cross(t, d))
    w = np.cross(d, u)
    return u, w


def _vdev(reg, V, F) -> float:
    """Largest distance of the region's vertices from its fitted surface (all of them, not the fitting subset)."""
    return float(np.abs(reg.prim.dist(V[np.unique(F[reg.tris])])).max())


def _canon_dir(d):
    d = _unit(d)
    k = int(np.argmax(np.abs(d)))
    return -d if d[k] < 0 else d


# ---- holes -----------------------------------------------------------------------------------------------------------

def find_holes(V, F, regions, tol):
    N, _ = tri_normals(V, F)
    out = []
    for r in regions:
        if r.kind != "cylinder":
            continue
        pr = r.prim
        cen = V[F[r.tris]].mean(axis=1)
        if float(np.einsum("ij,ij->i", N[r.tris], pr.normal(cen)).sum()) >= 0:
            continue                                   # convex: a boss or a rounded edge, not a hole
        o, a, rad = pr.p["o"], pr.p["a"], pr.p["r"]
        vid = np.unique(F[r.tris])
        P = V[vid]
        u, w = _frame(a)
        ang = np.sort(np.arctan2((P - o) @ w, (P - o) @ u))
        gaps = np.diff(np.r_[ang, ang[0] + 2 * np.pi])
        if gaps.max() > math.radians(20):
            continue                                   # not all the way round
        s = (P - o) @ a
        s0, s1 = float(s.min()), float(s.max())
        closed = [False, False]
        bottoms = []
        for q in regions:
            if q.kind != "plane" or abs(q.prim.p["a"] @ a) < PAR:
                continue
            Q = V[np.unique(F[q.tris])]
            d = Q - o
            sq = d @ a
            rho = np.linalg.norm(d - sq[:, None] * a, axis=1)
            if rho.max() <= rad * (1 + 1e-6) + 1e-6:
                lvl = float(sq.mean())
                for k, e in enumerate((s0, s1)):
                    if abs(lvl - e) <= max(tol, 1e-6):
                        closed[k] = True
                        bottoms.append(q.id)
        if closed[0] and closed[1]:
            continue                                   # a closed void, not a hole
        out.append({"region": r.id, "o": o + s0 * a, "a": a, "r": rad, "depth": s1 - s0, "open": [not closed[0], not closed[1]],
                    "bottoms": bottoms, "size": holemod.snap(2 * rad, within=max(2 * tol, 0.02))})
    return out


# ---- profiles --------------------------------------------------------------------------------------------------------

def _arc_from_points(Q, c, rad):
    """An arc of the circle (c, rad) over the angular span of 2-D points Q: (start, mid, end) points, or None if the
    points go all the way round."""
    ang = np.arctan2(Q[:, 1] - c[1], Q[:, 0] - c[0])
    order = np.argsort(ang)
    a = ang[order]
    gaps = np.diff(np.r_[a, a[0] + 2 * np.pi])
    k = int(np.argmax(gaps))
    if gaps[k] < math.radians(20):
        return None
    start = a[(k + 1) % len(a)]
    end = a[k]
    if end < start:
        end += 2 * np.pi
    i0, i1 = order[(k + 1) % len(a)], order[k]
    mid = 0.5 * (start + end)
    pm = c + rad * np.array([math.cos(mid), math.sin(mid)])
    return Q[i0], pm, Q[i1]


def _chain(elems, eps):
    """Join 2-D elements end to end into closed loops. Elements: ("line", p0, p1), ("arc", p0, pm, p1),
    ("circle", c, r). Returns list of loops (list of elements, each oriented along the loop) or raises ValueError."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    loops = [[e] for e in elems if e[0] == "circle"]
    rest = [e for e in elems if e[0] != "circle"]
    if not rest:
        return loops
    ends = np.array([p for e in rest for p in (e[1], e[-1])])
    pairs = cKDTree(ends).query_pairs(eps, output_type="ndarray")
    n = len(ends)
    g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])) if len(pairs) else ([], ([], [])), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    at = {}
    for i in range(len(rest)):
        for side in (0, 1):
            at.setdefault(int(lab[2 * i + side]), []).append((i, side))
    if any(len(v) != 2 for v in at.values()):
        raise ValueError("the profile does not close: some ends meet more or fewer than one other end")
    used = [False] * len(rest)
    for i0 in range(len(rest)):
        if used[i0]:
            continue
        loop, i, side = [], i0, 0               # walk forward: enter at `side`, leave at the other end
        while not used[i]:
            used[i] = True
            e = rest[i]
            loop.append(e if side == 0 else (e[0],) + tuple(reversed(e[1:])))
            key = int(lab[2 * i + (1 - side)])
            nxt = [t for t in at[key] if t[0] != i or len(at[key]) == 1]
            j, s = nxt[0] if nxt[0][0] != i else nxt[-1]
            i, side = j, s
        loops.append(loop)
    return loops


def _area2(loop):
    pts = []
    for e in loop:
        if e[0] == "circle":
            return math.pi * e[2] ** 2
        pts += [e[1], e[2]] if e[0] == "arc" else [e[1]]
    P = np.array(pts)
    return 0.5 * float(np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1]))


def extrude_plan(V, F, regions, holes, tol):
    WHY.clear()
    N, A = tri_normals(V, F)
    size = float(np.ptp(V, axis=0).max())
    hole_regions = {h["region"] for h in holes} | {b for h in holes for b in h["bottoms"]}
    cands = []
    for r in sorted(regions, key=lambda r: -r.area):
        if r.kind == "plane":
            cands.append(_canon_dir(r.prim.p["a"]))
        elif r.kind == "cylinder" and r.id not in hole_regions:
            cands.append(_canon_dir(r.prim.p["a"]))
    seen = []
    for d in cands:
        if any(abs(d @ s) > PAR for s in seen):
            continue
        seen.append(d)
        plan, why = _try_extrude(V, F, N, regions, hole_regions, d, tol, size)
        if plan is not None:
            return plan
        WHY.append(f"along {_v(d)}: {why}")
    return None


def _try_extrude(V, F, N, regions, hole_regions, d, tol, size):
    """Is the part one extrusion along d? The profile is the boundary of the end face at the lower level: where it
    meets a plane it is a line, a cylinder an arc (or a circle), a frozen facet the mesh's own edges."""
    from .brep import _loops
    u, w = _frame(d)
    eps = 1e-5 * size
    caps, levels = [], []
    _, Ar = tri_normals(V, F)
    for r in regions:
        if r.id in hole_regions:
            continue
        P = V[np.unique(F[r.tris])]
        lv = P @ d
        if r.kind in ("plane", "facet"):
            if np.ptp(lv) <= eps:                       # across the direction: an end face
                caps.append((r, float(lv.mean())))
                levels.append(float(lv.mean()))
                continue
            # along it: a plane exactly. A frozen facet may lean a little: a tessellated freeform side joins points
            # of the profile at different heights. Whether the extrusion is close enough is decided by comparing
            # the rebuilt part with the mesh.
            if r.kind == "plane":
                Q = np.c_[P @ u, P @ w]
                c2 = Q.mean(axis=0)
                _, _, vt = np.linalg.svd(Q - c2, full_matrices=False)
                if np.abs((Q - c2) @ vt[1]).max() > eps:
                    return None, "a plane that is neither along the direction nor across it"
            elif np.any((np.abs(N[r.tris] @ d) > 0.5) & (Ar[r.tris] > 1e-4 * size * size)):
                return None, "a facet that is neither along the direction nor across it"   # slivers excepted
        elif r.kind == "cylinder" and abs(r.prim.p["a"] @ d) > PAR:
            continue
        else:
            return None, f"a {r.kind} that is not along the direction"
    lv = np.sort(np.array(levels))
    if not len(lv) or lv[-1] - lv[0] < 1e-6 or np.any((lv - lv[0] > eps) & (lv[-1] - lv > eps)):
        return None, "end faces at more than two levels"
    s0 = float(lv[0])
    bottom = [r for r, l in caps if abs(l - s0) <= eps]
    lab = np.empty(len(F), dtype=np.int64)
    for r in regions:
        lab[r.tris] = r.id
    for r in bottom:
        lab[r.tris] = -1
    try:
        loops3 = _loops(F, lab).get(-1, [])
    except ValueError as e:
        return None, str(e)
    byid = {r.id: r for r in regions}
    loops = []
    for loop in loops3:
        nbs = {h[2] for h in loop}
        if nbs <= hole_regions:
            continue                                   # a hole: cut as a feature
        lp = []
        for q, vs, closed in _runs(loop):
            reg = byid[q]
            P = V[vs]
            Q = np.c_[P @ u, P @ w]
            if reg.kind == "cylinder" and q not in hole_regions and _vdev(reg, V, F) <= tol / 20:   # approximations stay as the mesh edges
                o = reg.prim.p["o"]
                c, rad = np.r_[o @ u, o @ w], reg.prim.p["r"]
                if closed:
                    lp.append(("circle", c, rad))
                    continue
                angm = math.atan2(Q[len(Q) // 2, 1] - c[1], Q[len(Q) // 2, 0] - c[0])
                pm = c + rad * np.array([math.cos(angm), math.sin(angm)])
                if len(Q) > 2:
                    lp.append(("arc", Q[0], pm, Q[-1]))
                    continue
                lp.append(("line", Q[0], Q[-1]))
            elif reg.kind == "plane":
                lp.append(("line", Q[0], Q[-1]))
            else:
                lp += [("line", Q[i], Q[i + 1]) for i in range(len(Q) - 1)]
        if lp:
            loops.append(lp)
    if not loops:
        return None, "no profile"
    return {"kind": "extrude", "d": d, "u": u, "w": w, "s0": s0, "length": float(lv[-1] - lv[0]), "loops": loops}, ""


def revolve_plan(V, F, regions, holes, tol):
    size = float(np.ptp(V, axis=0).max())
    axes = [r for r in sorted(regions, key=lambda r: -r.area) if r.kind in ("cylinder", "cone", "torus")]
    tried = []
    for ax in axes:
        o, a = ax.prim.p["o"], _canon_dir(ax.prim.p["a"])
        if any(abs(a @ b) > PAR and np.linalg.norm(np.cross(o - p, b)) < 1e-6 * size for p, b in tried):
            continue
        tried.append((o, a))
        plan = _try_revolve(V, F, regions, holes, o, a, tol, size)
        if plan is not None:
            return plan
    return None


def _coaxial(prim, o, a, size):
    if prim.kind == "sphere":
        c = prim.p["o"]
        return np.linalg.norm(np.cross(c - o, a)) < 1e-5 * size
    if abs(prim.p["a"] @ a) < PAR:
        return False
    return np.linalg.norm(np.cross(prim.p["o"] - o, a)) < 1e-5 * size


def _try_revolve(V, F, regions, holes, o, a, tol, size):
    keep_holes = {h["region"] for h in holes if not (abs(h["a"] @ a) > PAR and np.linalg.norm(np.cross(h["o"] - o, a)) < 1e-5 * size)}
    keep_holes |= {b for h in holes if h["region"] in keep_holes for b in h["bottoms"]}
    elems, radii, levels = [], [], []
    for r in regions:
        if r.id in keep_holes:
            continue
        P = V[np.unique(F[r.tris])]
        d = P - o
        z = d @ a
        rho = np.linalg.norm(d - z[:, None] * a, axis=1)
        if r.kind == "plane" and abs(r.prim.p["a"] @ a) > PAR:
            zl = float(z.mean())
            elems.append(("line", np.r_[rho.min(), zl], np.r_[rho.max(), zl]))
            levels.append(zl)
        elif r.kind in ("cylinder", "cone") and _coaxial(r.prim, o, a, size):
            i0, i1 = int(np.argmin(z)), int(np.argmax(z))
            if r.kind == "cylinder":
                rr = r.prim.p["r"]
                elems.append(("line", np.r_[rr, z[i0]], np.r_[rr, z[i1]]))
                radii.append(rr)
            else:
                elems.append(("line", np.r_[rho[i0], z[i0]], np.r_[rho[i1], z[i1]]))
        elif r.kind in ("torus", "sphere") and _coaxial(r.prim, o, a, size):
            if r.kind == "torus":
                zc = float((r.prim.p["o"] - o) @ a)
                c, rt = np.r_[r.prim.p["R"], zc], r.prim.p["r"]
            else:
                c, rt = np.r_[0.0, float((r.prim.p["o"] - o) @ a)], r.prim.p["r"]
            arc = _arc_from_points(np.c_[rho, z], c, rt)
            if arc is None:
                return None
            elems.append(("arc",) + arc)
        else:
            return None
    eps = max(1e-4 * size, 1e-6)
    # an open profile closes along the axis
    ends = [p for e in elems for p in (e[1], e[-1])]
    on_axis = [p for p in ends if abs(p[0]) < eps]
    if len(on_axis) == 2:
        elems.append(("line", on_axis[0], on_axis[1]))
    try:
        loops = _chain(elems, eps)
    except ValueError:
        return None
    if len(loops) != 1:
        return None
    # snap the profile's radii and levels to the fitted values so the Params substitute exactly
    snapped = []
    for lp in loops:
        out = []
        for e in lp:
            pts = []
            for q in e[1:]:
                q = np.array(q, dtype=np.float64)
                for rr in radii:
                    if abs(q[0] - rr) < eps:
                        q[0] = rr
                for zl in levels:
                    if abs(q[1] - zl) < eps:
                        q[1] = zl
                pts.append(q)
            out.append((e[0],) + tuple(pts))
        snapped.append(out)
    return {"kind": "revolve", "o": o, "a": a, "loops": snapped, "radii": radii, "levels": levels}


# ---- patterns and symmetry -------------------------------------------------------------------------------------------

def patterns(holes, tol):
    """Group holes of one size and direction, and look for a grid, a line or a circle."""
    groups = {}
    for i, h in enumerate(holes):
        k = (round(h["size"]["diameter_mm"], 4), tuple(np.round(_canon_dir(h["a"]), 4)), round(h["depth"], 3), tuple(h["open"]))
        groups.setdefault(k, []).append(i)
    out = []
    for k, idx in groups.items():
        g = {"holes": idx, "diameter_mm": k[0], "kind": "single" if len(idx) == 1 else "set"}
        if len(idx) >= 2:
            a = _canon_dir(holes[idx[0]]["a"])
            C = np.array([holes[i]["o"] - (holes[i]["o"] @ a) * a for i in idx])
            g.update(_grid(C, tol) or (_polar(C, a, tol) if len(idx) >= 3 else None) or {})
        out.append(g)
    return out


def _grid(C, tol):
    m = C.mean(axis=0)
    _, s, vt = np.linalg.svd(C - m, full_matrices=False)
    e1 = vt[0]
    e2 = vt[1] if s[1] > tol else None
    x = (C - m) @ e1
    xs = _cluster(x, tol)
    if e2 is None:
        ys = np.array([0.0])
        y = np.zeros(len(C))
    else:
        y = (C - m) @ e2
        ys = _cluster(y, tol)
    if len(xs) * len(ys) != len(C):
        return None
    for v in (xs, ys):
        if len(v) > 2 and np.ptp(np.diff(v)) > tol:
            return None
    p1 = float(np.diff(xs).mean()) if len(xs) > 1 else 0.0
    p2 = float(np.diff(ys).mean()) if len(ys) > 1 else 0.0
    centre = m + xs.mean() * e1 + (ys.mean() * e2 if e2 is not None else 0)
    return {"kind": "grid" if len(ys) > 1 and len(xs) > 1 else "line", "n1": len(xs), "n2": len(ys), "pitch1_mm": p1, "pitch2_mm": p2,
            "centre": centre, "e1": e1, "e2": e2 if e2 is not None else np.cross(e1, np.array([0, 0, 1.0]))}


def _cluster(x, tol):
    xs = np.sort(x)
    out = [[xs[0]]]
    for v in xs[1:]:
        if v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return np.array([np.mean(c) for c in out])


def _polar(C, a, tol):
    t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    u = _unit(np.cross(t, a))
    w = np.cross(a, u)
    x, y = C @ u, C @ w
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    cx, cy = sol[0], sol[1]
    R = math.sqrt(max(sol[2] + cx * cx + cy * cy, 0))
    if np.abs(np.hypot(x - cx, y - cy) - R).max() > tol or R < tol:
        return None
    ang = np.sort(np.arctan2(y - cy, x - cx))
    n = len(ang)
    step = 2 * math.pi / n
    if np.abs(np.diff(np.r_[ang, ang[0] + 2 * math.pi]) - step).max() > math.radians(0.2):
        return None
    centre = cx * u + cy * w
    return {"kind": "polar", "n": n, "pcd_mm": 2 * R, "centre": centre, "start_deg": math.degrees(ang[0]), "u": u, "w": w}


def symmetry(V, F, tol, axis=None):
    """Mirror planes through the centre of the bounding box (along x, y, z) and n-fold rotation about `axis` that
    map the mesh onto itself within tol, tested on up to 3000 vertices."""
    from .distance import MeshDistance
    md = MeshDistance(V, F)
    rng = np.random.default_rng(1)
    S = V if len(V) <= 3000 else V[rng.choice(len(V), 3000, replace=False)]
    c = 0.5 * (V.min(axis=0) + V.max(axis=0))
    out = []
    for k, nm in enumerate("xyz"):
        R = S.copy()
        R[:, k] = 2 * c[k] - R[:, k]
        if md.closest(R)[0].max() <= tol:
            out.append({"kind": "mirror", "plane": f"{nm} = {c[k]:.4g} mm"})
    if axis is not None:
        o, a = axis
        best = None
        for n in range(64, 1, -1):
            th = 2 * math.pi / n
            K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
            Rm = np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K
            R = (S - o) @ Rm.T + o
            if md.closest(R)[0].max() <= tol:
                best = n
                break
        if best == 64:
            out.append({"kind": "axisymmetric", "note": "maps onto itself at every step tested (down to 360/64 degrees)",
                        "axis": [round(float(x), 6) for x in a], "through": [round(float(x), 4) for x in o]})
        elif best:
            out.append({"kind": "rotation", "n": best, "axis": [round(float(x), 6) for x in a],
                        "through": [round(float(x), 4) for x in o]})
    return out


# ---- source ----------------------------------------------------------------------------------------------------------

def _f(x):
    return f"{float(x):.6f}".rstrip("0").rstrip(".") if abs(float(x)) >= 5e-7 else "0"


def _v(p):
    return "(" + ", ".join(_f(x) for x in p) + ")"


def _loop_code(loop, var, pt):
    """Edges of one profile loop; pt(p) is the code of the 3-D point for profile point p. Runs of lines become one
    Polyline."""
    lines, run = [], []

    def flush():
        if len(run) >= 2:
            lines.append(f"    {var} += Polyline({', '.join(pt(p) for p in run)}).edges()")
        run.clear()
    for e in loop:
        if e[0] == "line":
            if not run:
                run.append(e[1])
            run.append(e[2])
        else:
            flush()
            if e[0] == "arc":
                lines.append(f"    {var}.append(ThreePointArc({pt(e[1])}, {pt(e[2])}, {pt(e[3])}))")
    flush()
    return lines


def source(plan, holes, pats, name, report_line) -> tuple[str, list]:
    """build123d Recipe source for the plan. Returns (text, params) where params lists (key, value, provenance note)."""
    params = []
    L = ['"""' + f"{name}: reconstructed from a mesh by Form Studio (Layer 2, beta)." + "\n\n" + report_line + '\n"""',
         "import math", "",
         "from build123d import (Align, Cylinder, Edge, Location, Plane, Polyline, ThreePointArc, Wire, extrude, make_face,",
         "                       revolve, Axis)", "",
         "from form.recipes.base import Feature, Param, Recipe, Stage", "", ""]
    body = []
    if plan["kind"] == "extrude":
        d, u, w = plan["d"], plan["u"], plan["w"]
        H = plan["length"]
        params.append(("length", H, "Extrusion length", "computed from mesh: distance between the end faces"))
        body += [f"    pl = Plane(origin={_v(plan['s0'] * d)}, x_dir={_v(u)}, z_dir={_v(d)})",
                 "    P = lambda x, y: pl.from_local_coords((x, y))"]
        loops = sorted(plan["loops"], key=lambda lp: -abs(_area2(lp)))
        for i, lp in enumerate(loops):
            if lp[0][0] == "circle":
                c, r = lp[0][1], lp[0][2]
                body.append(f"    w{i} = Wire([Edge.make_circle({_f(r)}, Plane(origin=P{_v(c)}, x_dir=pl.x_dir, z_dir=pl.z_dir))])")
            else:
                body.append(f"    e{i} = []")
                body += _loop_code(lp, f"e{i}", lambda q: f"P{_v(q)}")
                body.append(f"    w{i} = Wire(e{i})")
        body.append("    face = make_face(w0)")
        for i in range(1, len(loops)):
            body.append(f"    face = face - make_face(w{i})")
        body.append('    body = extrude(face, amount=v["length"], dir=pl.z_dir)')
    else:
        o, a = plan["o"], plan["a"]
        u, _ = _frame(a)
        loop = plan["loops"][0]
        pts = [q for e in loop for q in e[1:] if e[0] != "circle"]
        z0 = min(q[1] for q in pts)
        rads = sorted({round(float(r), 6) for r in plan.get("radii", [])})
        lvls = sorted({round(float(z), 6) for z in plan.get("levels", [])})
        rkey = {}
        for i, r in enumerate(rads):
            k = f"d{i + 1}"
            rkey[r] = k
            snap = plan.get("snaps", {}).get(r)
            params.append((k, 2 * r, f"Diameter {i + 1}", "computed from mesh: diameter of a turned surface"
                           + (f", snapped to {snap}" if snap else "")))
        zkey = {}
        for i, z in enumerate(lvls):
            if abs(z - z0) < 1e-6:
                continue
            k = f"h{len(zkey) + 1}"
            zkey[z] = k
            params.append((k, z - z0, f"Height {len(zkey)}", "computed from mesh: height of a face across the axis above the lowest one"))

        def rz(q):
            r, z = round(float(q[0]), 6), round(float(q[1]), 6)
            rs = f"v[{rkey[r]!r}] / 2" if r in rkey else _f(q[0])
            zs = f"{_f(z0)} + v[{zkey[z]!r}]" if z in zkey else _f(q[1])
            return f"({rs}, 0, {zs})"
        body.append("    e0 = []")
        body += _loop_code(loop, "e0", rz)                    # (r, z) on the XZ plane
        body += ["    body = revolve(make_face(Wire(e0)), Axis.Z)",
                 f"    body = Location(Plane(origin={_v(o)}, x_dir={_v(u)}, z_dir={_v(a)})) * body"]
    body.append('    stages = [Stage("body", body)]')
    if holes:
        body.append("    cut = body")
        for gi, g in enumerate(pats):
            key = f"hole{gi + 1}_d"
            h0 = holes[g["holes"][0]]
            sz = h0["size"]
            note = f"computed from mesh: Ø{sz['measured_mm']:.3f} mm measured" + (
                f", snapped to {sz['standard']}" if sz.get("standard") else "")
            params.append((key, sz["diameter_mm"], f"Hole {gi + 1} diameter" + (f" ({len(g['holes'])}×)" if len(g["holes"]) > 1 else ""), note))
            m0 = 1.0 if h0["open"][0] else 0.0
            m1 = 1.0 if h0["open"][1] else 0.0
            a = h0["a"]
            ln = _f(h0["depth"] + m0 + m1)
            if (plan["kind"] == "extrude" and abs(a @ plan["d"]) > PAR and all(h0["open"])
                    and abs(h0["depth"] - plan["length"]) < 1e-4 * max(plan["length"], 1)):
                ln = 'v["length"] + 2'                 # a through hole stays through when the length changes
            if g.get("kind") in ("grid", "line"):
                p1k, p2k = f"hole{gi + 1}_pitch1", f"hole{gi + 1}_pitch2"
                if g["n1"] > 1:
                    params.append((p1k, g["pitch1_mm"], f"Hole {gi + 1} pitch", "computed from mesh: spacing of the hole centres"))
                if g["n2"] > 1:
                    params.append((p2k, g["pitch2_mm"], f"Hole {gi + 1} second pitch", "computed from mesh: spacing of the hole centres"))
                s_ax = float(h0["o"] @ a)
                centre = g["centre"] + s_ax * a
                body += [f"    for i in range({g['n1']}):",
                         f"        for j in range({g['n2']}):",
                         f"            c = tuple(s + (i - {_f((g['n1'] - 1) / 2)}) * {('v[' + repr(p1k) + ']') if g['n1'] > 1 else '0'} * e1"
                         f" + (j - {_f((g['n2'] - 1) / 2)}) * {('v[' + repr(p2k) + ']') if g['n2'] > 1 else '0'} * e2 - {_f(m0)} * ax"
                         f" for s, e1, e2, ax in zip({_v(centre)}, {_v(g['e1'])}, {_v(g['e2'])}, {_v(a)}))",
                         f"            cut = cut - Location(Plane(origin=c, z_dir={_v(a)})) * Cylinder(v[{key!r}] / 2, {ln}, align=(Align.CENTER, Align.CENTER, Align.MIN))"]
            elif g.get("kind") == "polar":
                pk = f"hole{gi + 1}_pcd"
                params.append((pk, g["pcd_mm"], f"Hole {gi + 1} pitch circle diameter", "computed from mesh: circle through the hole centres"))
                s_ax = float(h0["o"] @ a)
                body += [f"    for k in range({g['n']}):",
                         f"        t = math.radians({_f(g['start_deg'])} + k * 360 / {g['n']})",
                         f"        c = tuple(cc + v[{pk!r}] / 2 * (math.cos(t) * uu + math.sin(t) * ww) + ({_f(s_ax - m0)}) * ax"
                         f" for cc, uu, ww, ax in zip({_v(g['centre'])}, {_v(g['u'])}, {_v(g['w'])}, {_v(a)}))",
                         f"        cut = cut - Location(Plane(origin=c, z_dir={_v(a)})) * Cylinder(v[{key!r}] / 2, {ln}, align=(Align.CENTER, Align.CENTER, Align.MIN))"]
            else:
                for hi in g["holes"]:
                    h = holes[hi]
                    org = h["o"] - m0 * h["a"]
                    body.append(f"    cut = cut - Location(Plane(origin={_v(org)}, z_dir={_v(h['a'])})) * Cylinder(v[{key!r}] / 2, {ln}, "
                                "align=(Align.CENTER, Align.CENTER, Align.MIN))")
        body.append('    stages.append(Stage("holes", cut))')
    body.append("    return stages")
    feats = ['Feature("body", "Body", "structure")'] + (['Feature("holes", "Holes", "interface")'] if holes else [])
    L += ["class Design(Recipe):",
          f"    title = {(name + ' (reconstructed)')!r}",
          f"    summary = {('Rebuilt from a mesh as ' + ('an extrusion' if plan['kind'] == 'extrude' else 'a revolution') + (' with holes' if holes else '') + '.')!r}",
          "    params = ["]
    for key, val, label, note in params:
        lo = max(0.01, val * 0.1) if "pitch" not in key else val * 0.25
        hi = val * 4 + 1
        feat = "holes" if key.startswith("hole") else "body"
        L.append(f"        Param({key!r}, {label!r}, {_f(val)}, {_f(lo)}, {_f(hi)}, 0.01, \"mm\", \"form\", {feat!r}, {note!r}, provenance=\"mesh\"),")
    L += ["    ]", f"    features = [{', '.join(feats)}]", "", "    def build(self, v):"]
    L += ["    " + b for b in body]
    return "\n".join(L) + "\n", params


# ---- the layer -------------------------------------------------------------------------------------------------------

def build_source(text: str):
    """Load a design source the way the Studio does and build its defaults. Returns the final shape."""
    from ..recipes import SOURCE_PREFIX, load_source, source_id
    rid = source_id(text)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"{rid[len(SOURCE_PREFIX):]}.py"
        p.write_text(text, encoding="utf-8")
        rec = load_source(p, rid)
        stages = rec.build(rec.validate(rec.defaults()))
    return stages[-1].shape


def recipe(V, F, regions, tol, name="part", limit=None, progress=None) -> dict:
    from . import solid, verify
    say = progress or (lambda d: None)
    limit = tol if limit is None else limit
    hs = find_holes(V, F, regions, tol)
    rep = {"beta": True, "holes": [], "limit_mm": round(limit, 6)}
    plan = revolve_plan(V, F, regions, hs, tol)
    if plan is None:
        plan = extrude_plan(V, F, regions, hs, tol)
    if plan is not None and plan["kind"] == "revolve":
        # a bore on the axis is part of the revolved profile; only the other holes are cut
        o, a = plan["o"], plan["a"]
        size = float(np.ptp(V, axis=0).max())
        coax = [h for h in hs if abs(h["a"] @ a) > PAR and np.linalg.norm(np.cross(h["o"] - o, a)) < 1e-5 * size]
        rep["bores_in_profile"] = [dict(h["size"]) for h in coax]
        plan["snaps"] = {round(float(h["r"]), 6): h["size"]["standard"] for h in coax if h["size"].get("standard")}
        cut = [h for h in hs if h not in coax]
    else:
        cut = hs
    rep["holes"] = [{"diameter_mm": h["size"]["diameter_mm"], "standard": h["size"]["standard"],
                     "measured_mm": h["size"]["measured_mm"], "provenance": "computed from mesh",
                     "depth_mm": round(h["depth"], 4), "through": all(h["open"]),
                     "axis": [round(float(x), 6) for x in h["a"]], "at": [round(float(x), 4) for x in h["o"]]} for h in hs]
    fil = [r for r in regions if r.kind in ("cylinder", "torus") and r.id not in {h["region"] for h in hs}]
    rep["rounds"] = [{"kind": r.kind, "radius_mm": round(float(r.prim.p["r"]), 4), "area_mm2": round(r.area, 3)} for r in fil][:50]
    say({"stage": "layer2", "text": "Checking symmetry", "fraction": 0.2})
    axis = (plan["o"], plan["a"]) if plan and plan["kind"] == "revolve" else None
    if axis is None and plan is not None:
        big = [h for h in hs if abs(h["a"] @ plan["d"]) > PAR]
        if big:
            h = max(big, key=lambda h: h["r"])
            axis = (h["o"], plan["d"])
    try:
        rep["symmetry"] = symmetry(V, F, tol, axis)
    except Exception:                                  # noqa: BLE001
        rep["symmetry"] = []
    if plan is None:
        rep["error"] = ("No single extrusion or revolution explains the part: faces at more than two end levels, curved "
                        "faces across the extrusion direction, or surfaces on more than one axis.")
        rep["tried"] = WHY[:6]
        return {"report": rep}
    pats = patterns(cut, tol)
    rep["kind"] = plan["kind"]
    rep["patterns"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in g.items()
                        if k in ("kind", "holes", "diameter_mm", "n", "n1", "n2", "pitch1_mm", "pitch2_mm", "pcd_mm")} for g in pats]
    if plan["kind"] == "extrude":
        rep["direction"] = [round(float(x), 6) for x in plan["d"]]
        rep["length_mm"] = round(plan["length"], 4)
    else:
        rep["axis"] = [round(float(x), 6) for x in plan["a"]]
        rep["through"] = [round(float(x), 4) for x in plan["o"]]
    cnt = {"line": 0, "arc": 0, "circle": 0}
    for lp in plan["loops"]:
        for e in lp:
            cnt[e[0]] += 1
    rep["profile"] = {"loops": len(plan["loops"]), **{k + "s": v for k, v in cnt.items()}}
    line = (f"Base: {'extrusion' if plan['kind'] == 'extrude' else 'revolution'}; holes: {len(cut)}; values are "
            "computed from the mesh (hole sizes snapped to standard sizes where one is within reach).")
    src, params = source(plan, cut, pats, name, line)
    rep["params"] = [{"key": k, "value": round(v, 4), "label": lab, "provenance": note} for k, v, lab, note in params]
    say({"stage": "layer2", "text": "Building the recipe and comparing it with the mesh", "fraction": 0.5})
    try:
        shape = build_source(src)
    except Exception as e:                             # noqa: BLE001
        rep["error"] = f"The recipe did not build: {type(e).__name__}: {e}"[:400]
        return {"report": rep, "source": src}
    ck = solid.check(shape.wrapped)
    rep.update({"valid": ck["valid"], "solids": ck["solids"], "volume_mm3": round(ck["volume_mm3"], 4)})
    P, T = solid.tessellate(shape, max(tol / 10, 1e-4))
    cmp = verify.compare(V, F, P, T)
    rep.update({k: (round(v, 6) if isinstance(v, float) else v) for k, v in cmp.items() if not k.startswith("_")})
    ok = ck["valid"] and ck["solids"] == 1 and cmp["hausdorff_mm"] <= limit
    rep["verified"] = bool(ok)
    if not ok:
        rep["error"] = (f"The recipe builds, but it is {cmp['hausdorff_mm']:.4f} mm from the mesh (limit {limit:.4f} mm)"
                        if ck["valid"] else "The recipe builds an invalid solid.")
    return {"report": rep, "source": src, "verified": ok, "shape": shape.wrapped, "P": P, "T": T, "cmp": cmp}
