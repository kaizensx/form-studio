"""Measuring a contract on the kernel's solid (runs in the kernel worker).

    facts = proving.Facts(shape)                 # sizes, solids, faces by kind, round holes, cylinders: read once
    row = proving.check(assertion, facts)        # {"status", "measured", "measured_text", "evidence", "why"}
    rows = proving.rows(model, assertions)       # the proof sheet's rows for a built model (form/kernel.py op_prove)
    proving.expects(fid, expects, shape)         # a feature's own postconditions: raises RecipeError on a miss

Every number here is read off the boundary representation: a hole is a set of inward-facing cylindrical faces that
share an axis and a radius and close the circle; a bolt circle is the circle through the axes of holes of one size;
the thinnest wall is the kernel's ray-sampled wall thickness (form/kernel.py _thickness, the measure behind the
"Thinnest wall" check), so it is a sampled minimum and says so. Thread presence is a heuristic: helical (B-spline)
faces whose extent around an axis matches the major diameter.

An assertion is an obligation of one feature. rows() measures it on the finished solid (that is the status) and,
when it fails, on the solid as each feature left it, to say where: "never met", or "met after <feature>, lost at
<later feature>".
"""
from __future__ import annotations

import math

from .recipes.base import RecipeError

ROUND = 0.9                  # share of the full circle a set of cylindrical faces must cover to count as a round hole
AXIS_TOL = 1e-3              # radians-ish: how parallel two axes must be to be the same direction
THREAD_BAND = 0.15           # a thread's helical faces span the major diameter within this share
_GEOM = {"PLANE": "plane", "CYLINDER": "cylinder", "CONE": "cone", "SPHERE": "sphere", "TORUS": "torus",
         "BSPLINE": "bspline", "BEZIER": "bspline"}
_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _canon(d):
    """A direction with a fixed sign, so +Z and -Z are one axis."""
    d = _norm(d)
    for c in d:
        if abs(c) > 1e-9:
            return d if c > 0 else (-d[0], -d[1], -d[2])
    return d


def _foot(p, d):
    """The point of the line (p, d) nearest the origin: one name for the whole line."""
    t = _dot(p, d)
    return (p[0] - t * d[0], p[1] - t * d[1], p[2] - t * d[2])


class Facts:
    """What a solid is, read off its B-rep once."""

    def __init__(self, shape):
        self.shape = shape
        bb = shape.bounding_box()
        self.lo = (bb.min.X, bb.min.Y, bb.min.Z)
        self.hi = (bb.max.X, bb.max.Y, bb.max.Z)
        self.size = tuple(self.hi[i] - self.lo[i] for i in range(3))
        self.volume = float(shape.volume)
        self.solids = len(shape.solids())
        self._faces = None
        self._cyl = None
        self._holes = None

    @property
    def faces(self) -> list:
        if self._faces is None:
            out = []
            for f in self.shape.faces():
                try:
                    kind = _GEOM.get(f.geom_type.name, f.geom_type.name.lower())
                except Exception:
                    kind = "other"
                out.append((kind, f))
            self._faces = out
        return self._faces

    def count(self, of: str = "any") -> int:
        return len(self.faces) if of == "any" else sum(1 for k, _f in self.faces if k == of)

    @property
    def cylinders(self) -> list:
        """Cylindrical faces grouped by axis line and radius:
        [{"r", "dir", "at" (a point on the axis), "inward" (a hole), "cover" (share of the circle), "length"}]."""
        if self._cyl is not None:
            return self._cyl
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps
        from OCP.TopAbs import TopAbs_REVERSED
        groups: dict = {}
        for kind, f in self.faces:
            if kind != "cylinder":
                continue
            try:
                srf = BRepAdaptor_Surface(f.wrapped)
                cyl = srf.Cylinder()
                r = float(cyl.Radius())
                ax = cyl.Axis()
                d = _canon((ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()))
                p = (ax.Location().X(), ax.Location().Y(), ax.Location().Z())
                # the surface's own normal points away from the axis; a reversed face has the material outside it
                inward = f.wrapped.Orientation() == TopAbs_REVERSED
                if not cyl.Position().Direct():
                    inward = not inward
                props = GProp_GProps()
                BRepGProp.SurfaceProperties_s(f.wrapped, props)
                area = float(props.Mass())
                u0, u1, v0, v1 = srf.FirstUParameter(), srf.LastUParameter(), srf.FirstVParameter(), srf.LastVParameter()
            except Exception:
                continue
            foot = _foot(p, d)
            key = (round(r, 3), tuple(round(c, 3) for c in d), tuple(round(c, 2) for c in foot), inward)
            base = _dot(p, d)                              # v is measured from the surface's own origin
            sign = 1.0 if _dot((ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()), d) > 0 else -1.0
            a, b = sorted((base + sign * v0, base + sign * v1))
            groups.setdefault(key, {"r": r, "dir": d, "at": foot, "inward": inward, "runs": []})["runs"].append((a, b, area))
        out = []
        for g in groups.values():                          # two bearing seats on one axis are two cylinders
            runs = sorted(g["runs"])
            merged = [list(runs[0])]
            for a, b, area in runs[1:]:
                if a <= merged[-1][1] + 1e-4:
                    merged[-1][1] = max(merged[-1][1], b)
                    merged[-1][2] += area
                else:
                    merged.append([a, b, area])
            for a, b, area in merged:
                length = max(b - a, 1e-9)
                mid = (a + b) / 2
                out.append({"r": g["r"], "dir": g["dir"], "at": g["at"], "inward": g["inward"], "area": area,
                            "v0": a, "v1": b, "length": length, "cover": area / (2 * math.pi * g["r"] * length),
                            "centre": tuple(g["at"][i] + mid * g["dir"][i] for i in range(3))})
        self._cyl = out
        return out

    @property
    def holes(self) -> list:
        """Round holes: inward cylinders that close the circle. [{"d", "dir", "at", "length"}]"""
        if self._holes is None:
            self._holes = [{"d": 2 * g["r"], "dir": g["dir"], "at": g["at"], "length": g["length"]}
                           for g in self.cylinders if g["inward"] and g["cover"] >= ROUND]
        return self._holes


def _parallel(d, axis: str) -> bool:
    return not axis or abs(abs(_dot(d, _AXES[axis])) - 1.0) <= AXIS_TOL


def _fmt(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


def _row(ok, measured, text: str, evidence: str = "computed", why: str = "") -> dict:
    return {"status": "PASS" if ok else "FAIL", "measured": measured, "measured_text": text, "evidence": evidence,
            **({"why": why} if why and not ok else {})}


def _unproven(why: str) -> dict:
    return {"status": "UNPROVEN", "measured": None, "measured_text": "not measured", "evidence": "none", "why": why}


def _cmp(got: float, want: float, op: str, tol: float) -> bool:
    if op == "min":
        return got >= want - tol
    if op == "max":
        return got <= want + tol
    return abs(got - want) <= tol


def _circle3(a, b, c):
    """Centre and radius of the circle through three points of a plane (2D), or None when they are in line."""
    ax, ay, bx, by, cx, cy = *a, *b, *c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def _plane_basis(d):
    ref = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _norm((d[1] * ref[2] - d[2] * ref[1], d[2] * ref[0] - d[0] * ref[2], d[0] * ref[1] - d[1] * ref[0]))
    v = (d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0])
    return u, v


def _bolt_circle(holes: list, count: int, circle_d: float, tol: float):
    """(holes on the best circle of about that diameter, its measured diameter) among holes of one direction."""
    best = (0, None)
    dirs: dict = {}
    for h in holes:
        dirs.setdefault(tuple(round(c, 3) for c in h["dir"]), []).append(h)
    for d, hs in dirs.items():
        u, v = _plane_basis(d)
        pts = [(_dot(h["at"], u), _dot(h["at"], v)) for h in hs]
        cands = []
        n = len(pts)
        if n >= 3:
            lim = min(n, 14)
            for i in range(lim):
                for j in range(i + 1, lim):
                    for k in range(j + 1, lim):
                        c = _circle3(pts[i], pts[j], pts[k])
                        if c:
                            cands.append(c)
        if n >= 2:                                         # two holes: the circle on their distance as a diameter
            for i in range(min(n, 14)):
                for j in range(i + 1, min(n, 14)):
                    cands.append((((pts[i][0] + pts[j][0]) / 2, (pts[i][1] + pts[j][1]) / 2),
                                  math.dist(pts[i], pts[j]) / 2))
        for (cx, cy), r in cands:
            on = [p for p in pts if abs(math.hypot(p[0] - cx, p[1] - cy) - r) <= tol / 2 + 1e-6]
            score = (len(on) == count, -abs(2 * r - circle_d), len(on))
            if best[1] is None or score > best[2]:
                best = (len(on), 2 * r, score)
    return best[0], best[1]


def _thread_faces(facts: Facts, major: float) -> int:
    """Helical faces whose extent across some axis is the major diameter (within THREAD_BAND): a count, 0 for none."""
    n = 0
    for kind, f in facts.faces:
        if kind != "bspline":
            continue
        try:
            bb = f.bounding_box()
        except Exception:
            continue
        s = sorted((bb.size.X, bb.size.Y, bb.size.Z))
        # a turn of thread is as wide as the thread in the two directions across its axis
        if any(abs(a - major) <= THREAD_BAND * major and abs(b - major) <= THREAD_BAND * major
               for a, b in ((s[0], s[1]), (s[1], s[2]), (s[0], s[2]))):
            n += 1
    return n


def check(a: dict, facts: Facts, model: dict | None = None) -> dict:
    """One assertion measured on one solid. model: the built model, needed only for min_wall (the finished solid)."""
    k = a["kind"]
    tol = float(a.get("tol") or 0.0)
    try:
        if k == "bbox":
            got = list(facts.size)
            want = list(a["size"])
            if a.get("any_order"):
                ok = all(abs(g - w) <= tol for g, w in zip(sorted(got), sorted(want)))
            else:
                ok = all(abs(g - w) <= tol for g, w in zip(got, want))
            return _row(ok, [round(g, 4) for g in got], " x ".join(_fmt(g) for g in got) + " mm",
                        why="wanted " + " x ".join(_fmt(w) for w in want) + " mm")
        if k == "extent":
            got = list(facts.size)
            pick = ["xyz".index(a["axis"])] if a.get("axis") else [0, 1, 2]
            best = min((got[i] for i in pick), key=lambda g: abs(g - a["mm"]))
            return _row(abs(best - a["mm"]) <= tol, round(best, 4),
                        (f"{_fmt(best)} mm" + ("" if a.get("axis") else " (nearest of " + " x ".join(_fmt(g) for g in got) + ")")),
                        why=f"wanted {_fmt(a['mm'])} mm")
        if k == "volume":
            ok = _cmp(facts.volume, a["mm3"], a.get("op", "max"), tol)
            return _row(ok, round(facts.volume, 3), f"{_fmt(facts.volume)} mm³", why=f"wanted {a['text']}")
        if k == "part_count":
            return _row(facts.solids == a["count"], facts.solids, f"{facts.solids} solid(s)",
                        why=f"wanted {a['count']}")
        if k == "face_count":
            n = facts.count(a.get("of", "any"))
            return _row(_cmp(n, a["count"], a.get("op", "eq"), 0), n, f"{n} face(s)", why=f"wanted {a['text']}")
        if k == "hole_count":
            hs = [h for h in facts.holes if _parallel(h["dir"], a.get("axis", ""))]
            hit = [h for h in hs if abs(h["d"] - a["d"]) <= tol]
            near = sorted({round(h["d"], 3) for h in hs}, key=lambda d: abs(d - a["d"]))[:4]
            return _row(len(hit) == a["count"], len(hit), f"{len(hit)} hole(s) Ø{_fmt(a['d'])}"
                        + (f" (round holes found: {', '.join('Ø' + _fmt(d) for d in near)})" if len(hit) != a["count"] and near else ""),
                        why=f"wanted {a['count']}" + ("; the design has no round hole" if not hs else ""))
        if k == "cylinder":
            cs = [g for g in facts.cylinders if _parallel(g["dir"], a.get("axis", ""))
                  and (a.get("of", "any") == "any" or (a["of"] == "bore") == g["inward"])]
            if a.get("length") is not None:                # a blind bore is the right diameter and the wrong length
                lt = float(a.get("length_tol") if a.get("length_tol") is not None else tol)
                right = [g for g in cs if abs(2 * g["r"] - a["d"]) <= tol]
                long_ = [g for g in right if abs(g["length"] - a["length"]) <= lt and g["cover"] >= ROUND]
                want_n = a.get("count")
                ok = (len(long_) == want_n) if want_n is not None else bool(long_)
                near = min(right, key=lambda g: abs(g["length"] - a["length"]), default=None)
                return _row(ok, len(long_), f"{len(long_)} x Ø{_fmt(a['d'])}, {_fmt(a['length'])} mm long"
                            + (f" (found Ø{_fmt(2 * near['r'])}, {_fmt(near['length'])} mm long)" if near and not ok else ""),
                            why=f"wanted {want_n if want_n is not None else 'one'}")
            if not cs:
                return _row(False, None, "no cylindrical face" + ("" if a.get("of", "any") == "any" else f" that is a {a['of']}"),
                            why=f"wanted Ø{_fmt(a['d'])}")
            best = min(cs, key=lambda g: abs(2 * g["r"] - a["d"]))
            if a.get("count") is not None:
                n = sum(1 for g in cs if abs(2 * g["r"] - a["d"]) <= tol and g["cover"] >= ROUND)
                return _row(n == a["count"], n, f"{n} x Ø{_fmt(a['d'])}" + (f" (nearest Ø{_fmt(2 * best['r'])})" if not n else ""),
                            why=f"wanted {a['count']}")
            return _row(abs(2 * best["r"] - a["d"]) <= tol, round(2 * best["r"], 4), f"Ø{_fmt(2 * best['r'])} mm (nearest)",
                        why=f"wanted Ø{_fmt(a['d'])}")
        if k == "bolt_circle":
            hs = [h for h in facts.holes if abs(h["d"] - a["hole_d"]) <= tol]
            allh = sorted({round(h["d"], 3) for h in facts.holes}, key=lambda d: abs(d - a["hole_d"]))[:4]
            if len(hs) < min(a["count"], 2):
                return _row(False, {"holes": len(hs)}, f"{len(hs)} hole(s) Ø{_fmt(a['hole_d'])}"
                            + (f" (round holes found: {', '.join('Ø' + _fmt(d) for d in allh)})" if allh else " (no round hole)"),
                            why=f"wanted {a['count']} x Ø{_fmt(a['hole_d'])}")
            n, d = _bolt_circle(hs, a["count"], a["circle_d"], tol)
            ok = n == a["count"] and d is not None and abs(d - a["circle_d"]) <= tol
            return _row(ok, {"holes": n, "circle_d": round(d, 4) if d else None},
                        f"{n} x Ø{_fmt(a['hole_d'])} on Ø{_fmt(d) if d else '?'}",
                        why=f"wanted {a['count']} on Ø{_fmt(a['circle_d'])}")
        if k == "pattern":
            hs = [h for h in facts.holes if abs(h["d"] - a["hole_d"]) <= tol]
            best = 0
            for i, h in enumerate(hs):
                for j, g in enumerate(hs):
                    if i == j or tuple(round(c, 3) for c in h["dir"]) != tuple(round(c, 3) for c in g["dir"]):
                        continue
                    step = _sub(g["at"], h["at"])
                    if abs(math.sqrt(_dot(step, step)) - a["pitch"]) > tol:
                        continue
                    n, cur = 2, g["at"]
                    while True:
                        nxt = (cur[0] + step[0], cur[1] + step[1], cur[2] + step[2])
                        if not any(math.dist(nxt, x["at"]) <= tol for x in hs):
                            break
                        n, cur = n + 1, nxt
                    best = max(best, n)
            best = best or min(len(hs), 1)
            return _row(best == a["count"], best, f"{best} x Ø{_fmt(a['hole_d'])} at {_fmt(a['pitch'])} mm",
                        why=f"wanted {a['count']}")
        if k == "min_wall":
            if model is None:
                return _unproven("walls are measured on the finished solid")
            if getattr(model.get("recipe"), "mesh", False):
                return _unproven("not available for a mesh design")
            from . import kernel
            thin, hist = kernel._thickness(model)
            if not hist or thin["t"] == float("inf"):
                return _unproven("no opposing walls were found to measure")
            r = _row(thin["t"] >= a["t"] - tol, round(thin["t"], 4), f"{_fmt(thin['t'])} mm thinnest of {len(hist)} samples",
                     why=f"wanted at least {_fmt(a['t'])} mm")
            r["method"] = "opposing-wall rays from surface samples (a sampled minimum)"
            if thin.get("at"):
                r["at"] = [round(x, 3) for x in thin["at"]]
            if thin.get("feature") and r["status"] == "FAIL":
                r["found_in"] = thin["feature"]
            return r
        if k == "thread":
            n = _thread_faces(facts, a["major"])
            r = _row(n > 0, n, f"{n} helical face(s) at Ø{_fmt(a['major'])}" if n else f"no helical face at Ø{_fmt(a['major'])}",
                     "heuristic", f"wanted an M{_fmt(a['major'])} thread; a plain bore or shaft has none")
            r["method"] = "helical faces whose extent across an axis matches the major diameter"
            return r
    except Exception as e:                                 # noqa: BLE001 - a row that cannot be measured says so
        return _unproven(f"could not be measured ({type(e).__name__}: {e})"[:200])
    return _unproven(f"unknown kind {k}")


def expects(fid: str, wanted: list, shape) -> None:
    """A feature's postconditions (@feature(..., expects=[...])): raise a RecipeError naming every one the solid
    the feature returned does not meet, with measured against wanted. min_wall is measured on the finished design
    only (the proof sheet), so it is not a postcondition here."""
    if not wanted:
        return
    from . import contract
    facts = None
    misses = []
    for raw in wanted:
        try:
            a = contract.normalise(raw, {"source": f"expects= of {fid}", "basis": "stated"})
        except contract.ContractError as e:
            raise RecipeError(f"The {fid} feature's expects= is not a usable assertion: {e}", fid,
                              "Use form.contract's constructors: holes, bolt_circle, cylinder, bbox, part_count, ...")
        if a["kind"] == "min_wall":
            continue
        facts = facts or Facts(shape)
        r = check(a, facts)
        if r["status"] != "PASS":
            misses.append(f"{a['text']}: measured {r['measured_text']}" + (f" ({r['why']})" if r.get("why") else ""))
    if misses:
        raise RecipeError(f"The {fid} feature does not meet what it promises ({len(misses)} postcondition(s)): "
                          + "; ".join(misses), fid,
                          "Fix this feature (its checkpoint and the features before it are kept), or correct expects= "
                          "if the requirement changed.")


def rows(model: dict, assertions: list) -> list:
    """The proof sheet's rows for a built model: each contract assertion and each feature's expects=, measured on the
    finished solid, and for a failure where along the features it was (never) met."""
    from . import contract
    final = Facts(model["shape"])
    stages = model.get("stages") or []
    stage_facts: dict = {}

    def at_stage(i: int) -> Facts:
        if i not in stage_facts:
            stage_facts[i] = Facts(stages[i][1])
        return stage_facts[i]
    order = [f for f, _s in stages]
    out = []
    todo = [(a, "contract") for a in assertions]
    meta = getattr(type(model["recipe"]), "_form_meta", {}) or {}
    for fid, m in meta.items():
        for raw in m.get("expects") or []:
            try:
                a = contract.normalise(raw, {"source": f"expects= of {fid}", "basis": "stated"})
            except contract.ContractError:
                continue
            if any(x.get("feature") == fid and contract._same_subject(a, x) and contract._same_value(a, x) for x, _s in todo):
                continue                                   # the contract already holds this feature to it
            a["feature"] = fid
            todo.append((a, "expects"))
    for n, (a, source) in enumerate(todo, 1):
        r = check(a, final, model)
        fid = a.get("feature", "")
        row = {"id": a.get("id") or f"e{n}", "requirement": a["text"], "kind": a["kind"], "tolerance": a.get("tol"),
               "feature": fid, "assigned": a.get("assigned", "expects" if source == "expects" else ""),
               "provenance": a.get("provenance") or {}, "source": source, **r}
        if r["status"] == "FAIL" and a["kind"] != "min_wall" and stages:
            idx = [i for i, f in enumerate(order) if f == fid]
            start = idx[-1] if idx else 0
            met, lost = None, None
            for i in range(start, len(stages)):
                ok = check(a, at_stage(i))["status"] == "PASS"
                if ok and met is None:
                    met = order[i]
                elif not ok and met is not None:
                    lost = order[i]
                    break
            if met is None:
                row["where"] = f"not met when {fid} finished, nor after any later feature" if fid else "never met"
                row["repair"] = fid
            else:
                row["where"] = f"met after {met}, lost at {lost}"
                row["repair"] = lost or fid
        elif r["status"] == "FAIL":
            row["repair"] = r.get("found_in") or fid
        out.append(row)
    return out
