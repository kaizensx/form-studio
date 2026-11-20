"""analyze_assembly: how several meshes go together and move, measured on the meshes in the positions they were given.

1. Mating surfaces: points sampled on each part's surface, their exact distance to every other part. Where they touch
   (within 0.05 mm) or nearly touch (within `near` mm) the surfaces mate; they are grouped by facing direction and
   reported with their area, gap and place.
2. Travel: every part but the fixed one (the first given) is moved along +/-X, Y and Z, and turned about the axes of
   round faces it shares with the fixed part, in small steps. A step is free while no more of its surface goes inside
   the fixed part than at rest (inside-or-outside on a voxel grid, with the surface moved in by the grid's size so
   touching faces do not count). The free distance each way is the range of travel; a direction that never meets
   anything within the parts' size is free (the part lifts off that way).
3. Joints: a part that slides one way and is blocked across it is a slide along that axis; one that turns about a
   round face is a hinge about it. Two moving parts that nearly touch are coupled: a slide against a part that turns
   is a rack on a gear (or a cam), with the ratio from the distance of the contact to the axis; a slide against a
   leaning face is a ramp, with how far one pushes the other.

Evidence: computed on the meshes as given (grid spacing and sample spacing are reported). Motion is simulated as rigid
parts in their given positions; it does not know about springs, flexing or gravity.
"""
from __future__ import annotations

import math
import time

import numpy as np

from .analyze import AXES, _r, where

CONTACT = 0.05


class _Part:
    def __init__(self, name, V, F, spacing):
        from ..recon.distance import MeshDistance, sample_surface
        from .occupancy import Occupancy
        self.name, self.V, self.F = name, V, F
        self.lo, self.hi = V.min(0), V.max(0)
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        n = np.cross(b - a, c - a)
        ar = np.linalg.norm(n, axis=1)
        self.N = n / np.maximum(ar, 1e-300)[:, None]
        self.S, self.tri, self.spacing = sample_surface(V, F, spacing, cap=250_000)
        per = np.bincount(self.tri, minlength=len(F)).astype(np.float64)
        self.w = (ar / 2 / np.maximum(per, 1))[self.tri]          # area each sample stands for
        self.SN = self.N[self.tri]
        self.md = MeshDistance(V, F)
        self.occ = Occupancy(V, F, h=max(float(np.ptp(V, axis=0).max()) / 600, 0.05))
        self.volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def _clusters(N, w, cos=0.985):
    """Group unit normals by direction (greedy, heaviest first). Returns labels."""
    lab = -np.ones(len(N), dtype=np.int64)
    k = 0
    order = np.argsort(-w)
    for i in order:
        if lab[i] >= 0:
            continue
        m = (lab < 0) & (N @ N[i] > cos)
        if not m.any():
            continue
        d = (N[m] * w[m, None]).sum(0)
        d /= max(np.linalg.norm(d), 1e-12)
        m = (lab < 0) & (N @ d > cos)
        lab[m] = k
        k += 1
    return lab


def _facing(n):
    j = int(np.argmax(np.abs(n)))
    if abs(n[j]) > 0.9998:
        return ("+" if n[j] > 0 else "-") + AXES[j]
    return _r(n, 4)


def mating(A: _Part, B: _Part, near: float) -> list:
    d, _, _ = B.md.closest(A.S)
    m = d < near
    if not m.any():
        return []
    lab = -np.ones(len(d), dtype=np.int64)
    lab[m] = _clusters(A.SN[m], A.w[m])
    rows = []
    lo = np.minimum(A.lo, B.lo)
    hi = np.maximum(A.hi, B.hi)
    for k in np.unique(lab[m]):
        s = lab == k
        area = float(A.w[s].sum())
        if area < 0.5:
            continue
        n = (A.SN[s] * A.w[s, None]).sum(0)
        n /= max(np.linalg.norm(n), 1e-12)
        flat = bool(np.all(A.SN[s] @ n > 0.9998))
        P = A.S[s]
        g = d[s]
        rows.append({"between": [A.name, B.name], "facing": _facing(n), "_n": n, "surface": "flat" if flat else "curved",
                     "area_mm2": round(area, 2), "touching": bool(np.median(g) < CONTACT),
                     "gap_mm": {"min": round(float(g.min()), 3), "median": round(float(np.median(g)), 3),
                                "max": round(float(g.max()), 3)},
                     "box": [_r(P.min(0)), _r(P.max(0))], "at": _r(P.mean(0)), "where": where(P.mean(0), lo, hi),
                     "_P": P, "_g": g})
    rows.sort(key=lambda r: -r["area_mm2"])
    if rows:
        rows[0]["_all"] = (A.S[m], A.SN[m])
    return rows


def _rot(axis, ang):
    a = axis / np.linalg.norm(axis)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K


BUMP = 1.0              # mm: interference up to this deep, over a small area, is a bump, a detent or a flexing arm


def _inside_moved(B: _Part, A: _Part, M=None, t=None, o=None):
    """Which of B's samples (moved in a little, so faces that touch do not count) are inside A after B is moved,
    and the moved points."""
    P = B.S - B.SN * (0.75 * A.occ.h + CONTACT)
    if M is not None:
        P = (P - o) @ M.T + o
    if t is not None:
        P = P + t
    return A.occ.inside(P), P


def _new(B: _Part, A: _Part, rest, **mv):
    """Samples newly inside A (not already inside at rest), how deep the deepest is, and where they are."""
    ins, P = _inside_moved(B, A, **mv)
    nw = ins & ~rest
    n = int(nw.sum())
    if not n:
        return 0, 0.0, None
    Q = P[nw]
    if len(Q) > 3000:
        Q = Q[np.random.default_rng(0).choice(len(Q), 3000, replace=False)]
    d = np.sort(A.md.closest(Q)[0])[::-1]
    k = max(4, int(0.0002 * len(B.S)) * len(Q) // max(n, 1))
    depth = float(d[min(k, len(d) - 1)])            # robust: the depth that more than a handful of samples reach
    return n, depth, Q.mean(0)


def sweep(B: _Part, A: _Part, move, limit, step):
    """Walk a motion: move(x) gives the keyword arguments of one position. Returns the free distance (first new
    contact), the distance through bumps (first interference deeper than BUMP) and the obstacles met on the way."""
    rest, _ = _inside_moved(B, A)
    allow = max(4, int(0.0002 * len(B.S)))
    first, hard, obstacles = None, None, []
    x = 0.0
    while x < limit:
        x = min(limit, x + step)
        n, depth, at = _new(B, A, rest, **move(x))
        if n > allow:
            if first is None:
                first = x - step
            if not obstacles or obstacles[-1]["to"] < x - 1.5 * step:
                obstacles.append({"from": round(x - step, 2), "to": round(x, 2), "deepest_mm": round(depth, 3), "_at": at})
            else:
                obstacles[-1]["to"] = round(x, 2)
                obstacles[-1]["deepest_mm"] = max(obstacles[-1]["deepest_mm"], round(depth, 3))
            if depth > BUMP or n > 0.02 * len(B.S):         # deep, or a large area: a hard stop
                hard = x - step
                break
    return (limit if first is None else max(first, 0.0)), (limit if hard is None else max(hard, 0.0)), obstacles


def travel(B: _Part, A: _Part, d, limit, step=1.0):
    return sweep(B, A, lambda x: {"t": d * x}, limit, step)


def turning(B: _Part, A: _Part, o, a, limit_deg=180.0, step_deg=3.0):
    return [sweep(B, A, lambda x, s=s: {"M": _rot(a, math.radians(s * x)), "o": o}, limit_deg, step_deg) for s in (1, -1)]


def round_axes(P, N, min_cover=120.0):
    """Axes of round faces among points P with normals N: for each world axis, the points whose normals are across it,
    in connected groups, fitted with circles. Returns [(origin, axis, radius, coverage_deg)]."""
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    out = []
    if len(P) < 12:
        return out
    for k in range(3):
        m = np.abs(N[:, k]) < 0.05
        if m.sum() < 12:
            continue
        Q, NQ = P[m], N[m]
        u, v = [x for x in range(3) if x != k]
        tree = cKDTree(Q[:, [u, v]])
        g = tree.sparse_distance_matrix(tree, 0.8, output_type="coo_matrix")
        _, lab = connected_components(g, directed=False)
        for l in np.unique(lab):
            s = lab == l
            if s.sum() < 12:
                continue
            x, y = Q[s, u], Q[s, v]
            M = np.c_[x, y, np.ones_like(x)]
            sol, *_ = np.linalg.lstsq(M, -(x * x + y * y), rcond=None)
            cx, cy = -sol[0] / 2, -sol[1] / 2
            r = math.sqrt(max(cx * cx + cy * cy - sol[2], 0.0))
            if r <= 0 or np.abs(np.hypot(x - cx, y - cy) - r).max() > max(0.1, 0.02 * r):
                continue
            ang = np.degrees(np.arctan2(y - cy, x - cx))
            cover = float(np.mean(np.bincount(((ang + 180) // 5).astype(int) % 72, minlength=72) > 0) * 360)
            if cover < min_cover:
                continue
            o = np.zeros(3)
            o[u], o[v], o[k] = cx, cy, float(Q[s, k].mean())
            out.append((o, np.eye(3)[k], r, cover))
    return out


def analyse(parts: list, fixed: str | None = None, near: float = 1.0) -> dict:
    """parts: [(name, V, F)]. The first (or `fixed`) stays still; the others are moved against it."""
    t0 = time.perf_counter()
    size = max(float(np.ptp(np.vstack([p[1] for p in parts]), axis=0).max()), 1.0)
    spacing = max(size / 220, 0.2)
    P = [_Part(n, V, F, spacing) for n, V, F in parts]
    names = [p.name for p in P]
    fx = names.index(fixed) if fixed in names else 0
    A = P[fx]
    out = {"evidence": "computed (on the meshes in the positions given; rigid parts, no springs or gravity)",
           "fixed": A.name, "sample_spacing_mm": round(P[0].spacing, 3), "near_mm": near,
           "parts": [{"name": p.name, "size_mm": _r(p.hi - p.lo), "volume_mm3": round(p.volume, 1),
                      "bbox": [_r(p.lo), _r(p.hi)]} for p in P]}
    mates = []
    pairs = {}
    for i in range(len(P)):
        for j in range(i + 1, len(P)):
            rows = mating(P[i], P[j], near)
            pairs[(i, j)] = rows
            mates += rows
    out["mating_surfaces"] = [{k: v for k, v in r.items() if not k.startswith("_")} for r in mates[:40]]
    clear = {}
    for (i, j), rows in pairs.items():
        g = [r["gap_mm"]["min"] for r in rows if not r["touching"]]
        t = [r for r in rows if r["touching"]]
        if rows:
            clear[f"{P[i].name} / {P[j].name}"] = {
                "touching_area_mm2": round(sum(r["area_mm2"] for r in t), 1),
                "smallest_clearance_mm": round(min(g), 3) if g else None,
                "near_area_mm2": round(sum(r["area_mm2"] for r in rows), 1)}
    out["clearances"] = clear
    # ---- motion of each part against the fixed one
    joints = []
    motion = {}
    for k, B in enumerate(P):
        if k == fx:
            continue
        lim = float(np.ptp(np.vstack([A.V, B.V]), axis=0).max())
        key = (min(k, fx), max(k, fx))
        # the faces of the fixed part that B rests on or runs along (A's outward normals), for "comes away"
        sgn_n = 1.0 if key[0] == fx else -1.0
        faces_n = [(sgn_n * r["_n"], r["area_mm2"]) for r in pairs.get(key, []) if r["area_mm2"] >= 1.0]
        blo, bhi = np.minimum(A.lo, B.lo), np.maximum(A.hi, B.hi)

        def obs(rows_):
            return [{**{k2: v for k2, v in o_.items() if k2 != "_at"},
                     **({"at": _r(o_["_at"]), "where": where(o_["_at"], blo, bhi)} if o_.get("_at") is not None else {})}
                    for o_ in rows_[:6]]
        rows = {}
        for ax in range(3):
            for sgn in (1, -1):
                d = np.zeros(3)
                d[ax] = sgn
                ext = float(np.ptp(np.r_[A.V @ d, B.V @ d]))   # far enough for B to clear A along d
                free, hard, ob = travel(B, A, d, ext + 1.0)
                if hard >= ext + 1.0 - 1e-6:
                    free, hard = (lim if free >= ext + 1.0 - 1e-6 else free), lim
                rows[("+" if sgn > 0 else "-") + AXES[ax]] = {"free_mm": round(free, 2), "past_bumps_mm": round(hard, 2),
                                                              "stopped": hard < lim, "obstacles": obs(ob)}
        mv = {"translate": rows}
        # round faces of B near A: candidate turning axes
        rows_k = pairs.get(key, [])
        turns = []
        if rows_k and "_all" in rows_k[0]:
            Q, NQ = rows_k[0]["_all"]
            for o, a, rad, cover in round_axes(Q, NQ)[:3]:
                (fp, hp, op), (fn, hn, on) = turning(B, A, o, a)
                turns.append({"axis": AXES[int(np.argmax(np.abs(a)))], "through": _r(o), "radius_mm": round(rad, 3),
                              "contact_cover_deg": round(cover), "free_deg": {"+": round(fp, 1), "-": round(fn, 1)},
                              "past_bumps_deg": {"+": round(hp, 1), "-": round(hn, 1)},
                              "stopped": {"+": hp < 180, "-": hn < 180}, "obstacles": {"+": obs(op), "-": obs(on)},
                              "_o": o, "_a": a})
        mv["turn"] = [{k2: v for k2, v in t.items() if not k2.startswith("_")} for t in turns]
        motion[B.name] = mv
        # what joint this is: the axis with the longest travel past bumps, held across it
        # a direction it moves in without touching anything is where it comes away (lifts off), not a guided slide
        def away(dn):
            dv = np.zeros(3)
            dv["xyz".index(dn[1])] = 1.0 if dn[0] == "+" else -1.0
            return any(float(n @ dv) > 0.7 for n, _ in faces_n)
        reach = {d: (0.0 if (v["free_mm"] >= lim - 1e-6 and away(d)) else v["past_bumps_mm"]) for d, v in rows.items()}
        mv["comes_away"] = [d for d, v in rows.items() if v["free_mm"] >= lim - 1e-6 and away(d)]
        blocked = {d for d, v in rows.items() if v["past_bumps_mm"] < 3.0}
        best = None
        for ax in range(3):
            plus, minus = reach["+" + AXES[ax]], reach["-" + AXES[ax]]
            others = [x for x in range(3) if x != ax]
            cross_ok = all(("+" + AXES[x]) in blocked or ("-" + AXES[x]) in blocked for x in others)
            span = plus + minus
            if span > 3.0 and cross_ok and (best is None or span > best[1]):
                best = (ax, span, plus, minus)
        turn_span = lambda t: t["past_bumps_deg"]["+"] + t["past_bumps_deg"]["-"]
        if turns and any(turn_span(t) > 5 for t in turns) and (best is None or best[1] < 1.0):
            t = max(turns, key=turn_span)
            joints.append({"part": B.name, "kind": "hinge", "relative_to": A.name, "axis": t["axis"], "through": t["through"],
                           "range_deg": [-t["free_deg"]["-"], t["free_deg"]["+"]],
                           "past_bumps_deg": [-t["past_bumps_deg"]["-"], t["past_bumps_deg"]["+"]],
                           "bearing_radius_mm": t["radius_mm"],
                           "_o": t["_o"], "_a": t["_a"],
                           "note": "turns on a round face it shares with the fixed part" +
                                   ("" if all(t["stopped"].values()) else "; a direction with no stop turns freely up to 180°")})
        elif best is not None:
            ax, span, plus, minus = best
            stop_p, stop_m = rows["+" + AXES[ax]]["stopped"], rows["-" + AXES[ax]]["stopped"]
            joints.append({"part": B.name, "kind": "slide", "relative_to": A.name, "axis": AXES[ax],
                           "range_mm": [-round(minus, 2), round(plus, 2)], "travel_mm": round(span, 2),
                           "free_without_touching_mm": [-rows["-" + AXES[ax]]["free_mm"], rows["+" + AXES[ax]]["free_mm"]],
                           "stops": {"+": stop_p, "-": stop_m}, "_d": np.eye(3)[ax],
                           "note": (f"slides along {AXES[ax]} over {span:.1f} mm and is held across it"
                                    + ("" if stop_p and stop_m else "; no hard stop within the parts' size at "
                                       + ("either end" if not (stop_p or stop_m) else "one end")
                                       + " (the stops may be flexible, or come from another part)")
                                    + ("; it passes bumps on the way (detents, snaps or flexing arms: see obstacles)"
                                       if any(len(rows[s_ + AXES[ax]]["obstacles"]) > int(rows[s_ + AXES[ax]]["stopped"]) for s_ in "+-") else ""))})
        else:
            joints.append({"part": B.name, "kind": "held" if len(blocked) >= 5 else "loose", "relative_to": A.name,
                           "note": "no clear slide or turn against the fixed part" if len(blocked) >= 5 else
                                   "comes away from the fixed part in several directions"})
    out["motion"] = motion
    # ---- couplings between moving parts
    coup = []
    jby = {j["part"]: j for j in joints}
    for (i, j), rows in pairs.items():
        if fx in (i, j) or not rows:
            continue
        a_, b_ = P[i].name, P[j].name
        ja, jb = jby.get(a_), jby.get(b_)
        if not ja or not jb:
            continue
        Q = np.vstack([r["_P"] for r in rows])
        for s, h in ((ja, jb), (jb, ja)):
            if s["kind"] == "slide" and h["kind"] == "hinge":
                o, ax = h["_o"], h["_a"]
                dd = Q - o
                rho = np.linalg.norm(dd - (dd @ ax)[:, None] * ax, axis=1)
                r = float(np.median(rho))
                bounded = all(s["stops"].values())
                deg = math.degrees(s["travel_mm"] / max(r, 1e-6))
                hinge_span = h["range_deg"][1] - h["range_deg"][0]
                coup.append({"kind": "rack and gear (or cam)", "driver": s["part"], "driven": h["part"],
                             "contact_radius_mm": round(r, 2), "ratio_deg_per_mm": round(math.degrees(1 / r), 3),
                             **({"over_full_travel_deg": round(deg, 1)} if bounded else {}),
                             "slide_for_driven_range_mm": round(math.radians(hinge_span) * r, 2), "at": _r(Q.mean(0)),
                             "note": f"{s['part']} sliding along {s['axis']} meets {h['part']} {r:.1f} mm from its axis: "
                                     f"each mm of slide turns it about {math.degrees(1 / r):.2f}°, so its "
                                     f"{hinge_span:.0f}° of free turn takes about {math.radians(hinge_span) * r:.1f} mm of "
                                     "slide (if teeth or a cam keep contact all the way; look at the sections)"})
                break
            if s["kind"] == "slide" and h["kind"] == "slide":
                ns = [r["_n"] for r in rows if r["surface"] == "flat"]
                for n in ns:
                    ds, dh = s["_d"], h["_d"]
                    if abs(n @ ds) > 0.05 and abs(n @ dh) > 0.05:
                        ratio = abs((n @ ds) / (n @ dh))
                        coup.append({"kind": "ramp", "driver": s["part"], "driven": h["part"],
                                     "lift_per_mm": round(ratio, 3), "over_full_travel_mm": round(ratio * s["travel_mm"], 2),
                                     "ramp_angle_deg": round(math.degrees(math.atan(ratio)), 2),
                                     "note": f"a ramp: {s['part']} moving 1 mm along {s['axis']} pushes {h['part']} "
                                             f"{ratio:.2f} mm along {h['axis']}"})
                        break
                break
    out["joints"] = [{k: v for k, v in j.items() if not k.startswith("_")} for j in joints]
    out["couplings"] = coup
    out["summary"] = _summary(out)
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def _summary(out) -> str:
    s = []
    for j in out["joints"]:
        if j["kind"] == "slide":
            s.append(f"{j['part']} slides along {j['axis']} in {j['relative_to']} over {j['travel_mm']} mm "
                     f"({j['range_mm'][0]} to +{j['range_mm'][1]} mm from where it is).")
        elif j["kind"] == "hinge":
            s.append(f"{j['part']} turns about {j['axis']} through {j['through']} on {j['relative_to']} "
                     f"({j['range_deg'][0]}° to +{j['range_deg'][1]}°).")
        else:
            s.append(f"{j['part']}: {j['note']}.")
    for c in out["couplings"]:
        s.append(c["note"] + ".")
    return " ".join(s)
