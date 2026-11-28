"""Standard parts placed on a design: pick a hole or a face, and the part, its mating cut and its fit are one action.

A placement is a part from form.catalog (a screw, an insert, a bearing, a motor...) at a point with a direction. It
lives in a block at the end of the design's Python source, the way text on faces (form/engrave.py) and standard
features (form/feature_helpers.py) do, so an agent reads it and it travels with every revision:

    # ---- Form Studio: standard parts (edit in the app or with `form parts place`) ----
    _FORM_PARTS = [{'id': 'std_1', 'spec': {'family': 'iso4762', 'size': 'M3', 'length': 10.0, ...},
                    'at': (0.0, 0.0, 6.0), 'normal': (0.0, 0.0, 1.0), 'depth': 6.0, 'qty': 1, ...}]
    ...
    # ---- end of standard parts ----

The block wraps the design class: build() gets one Stage per placement that cuts the part's mating feature (the
clearance hole and counterbore, the insert pocket, the bearing seat, the motor's pilot and screw holes...) into the
host at that point, and assembly(), when the design declares one, lists each placed part as purchased hardware with
its standard designation. Adding or removing one is ``Studio.update_design``: a new revision, built in the kernel
before it is saved; a cut that does not reach the part is refused with the reason.

Placing snaps first (``snap``, on the B-rep in the worker): a point on a hole's wall snaps to the hole's axis and its
opening, a point on a flat face to the face with its outward normal; either way the host's thickness under the point
is measured, and the cut depth and a screw's stock length are chosen from it. After the revision is built the fit is
checked (``fit``): the part, placed as fitted, is intersected with the cut host on the B-rep (computed), and its
radial clearance is computed from the two tables (the part's and the cut's).
"""
from __future__ import annotations

import json

from .engrave import _python_source, design_class, _vec, _err

START = "# ---- Form Studio: standard parts (edit in the app or with `form parts place`) ----"
END = "# ---- end of standard parts ----"
PREFIX = "std_"
MAX_PARTS = 48
VERSION = 1
EPS_MM3 = 1e-3                 # interference below this (or 1e-5 of the part) is numerical dust, not contact

TEMPLATE = '''
{start}
from form import placement as _form_pl
from form.recipes.base import Feature as _FormFeature, Recipe as _FormRecipe, Stage as _FormStage
_FORM_PARTS = {specs}


def _form_parts(cls):
    build = cls.build
    asm = getattr(cls, "assembly", None)
    asm = None if asm is _FormRecipe.assembly else asm

    def with_parts(self, v):
        stages = list(build(self, v))
        s = stages[-1].shape
        for q in _FORM_PARTS:
            s = _form_pl.apply(s, q)
            stages.append(_FormStage(q["id"], s))
        return stages

    def with_hardware(self, v):
        a = asm(self, v) if asm else None
        if a is not None:
            a.hardware = [h for h in a.hardware if not str(h.note).startswith(_form_pl.NOTE)] + _form_pl.hardware(_FORM_PARTS)
        return a
    cls.build = with_parts
    if asm is not None:
        cls.assembly = with_hardware
    cls.features = [f for f in cls.features if not f.id.startswith("{prefix}")] + [
        _FormFeature(q["id"], _form_pl.label(q), "interface") for q in _FORM_PARTS]
    return cls


{cls} = _form_parts({cls})
{end}
'''
NOTE = "Standard part "


# ---- the source block ---------------------------------------------------------------------------------------------
def split(source: str) -> tuple[str, list]:
    """(the source without the block, the placements it holds)."""
    import ast
    import re
    i = source.find(START)
    if i < 0:
        return source, []
    j = source.find(END, i)
    block = source[i:j if j >= 0 else len(source)]
    m = re.search(r"^_FORM_PARTS = (.*)$", block, re.M)
    specs = ast.literal_eval(m.group(1)) if m else []
    rest = source[:i].rstrip() + "\n" + (source[j + len(END):].lstrip("\n") if j >= 0 else "")
    return rest.rstrip() + "\n", specs


def join(source: str, specs: list) -> str:
    base, _old = split(source)
    if not specs:
        return base
    return base.rstrip() + "\n" + TEMPLATE.format(start=START, end=END, cls=design_class(base), specs=repr(specs),
                                                    prefix=PREFIX)


def label(q: dict) -> str:
    from . import catalog
    try:
        return catalog.designation(q["spec"]) + (f" ×{q['qty']}" if q.get("qty", 1) > 1 else "")
    except Exception:                                    # noqa: BLE001 - a table changed: still name the line
        return f"{q['spec'].get('family')} {q['spec'].get('size')}"


def hardware(placements: list) -> list:
    """Assembly Hardware rows for the placements (purchased, with the standard designation)."""
    from . import catalog
    from .recipes.assembly import Hardware
    out = []
    for q in placements:
        it = catalog.resolve(q["spec"])
        f = catalog.family(it["family"])
        cg = f.catalogue_grams(it)
        mk = f.material(it)[0]
        out.append(Hardware(f.designation(it), it.get("size", ""), int(q.get("qty", 1)), f.standard,
                            f"{NOTE}{q['id']}: fit it in its {q.get('snap', 'face')} cut.", "", (), "",
                            grams=round(cg[0], 3) if cg else None, material=(mk or "").lower()))
    return out


# ---- geometry (kernel worker) --------------------------------------------------------------------------------------
def _plane(q):
    from . import marks
    return marks._plane(None, q["at"], q["normal"], q.get("up"))


def placed_shape(q):
    """The purchased part as fitted, in the design's frame. Worker only."""
    from build123d import Pos
    from . import catalog
    it = catalog.resolve(q["spec"])
    p = catalog.build(it)
    shape = p.shape
    f = catalog.family(it["family"])
    if hasattr(f, "fitted_z") and f.fitted_z(it) is None:       # a T-nut: under the host, on its far face
        shape = Pos(0, 0, -float(q["depth"])) * shape
    return _plane(q).location * shape


def cutter(q):
    """The mating cut in the design's frame, or None (the part sits on the surface). Worker only."""
    from . import catalog
    if not q.get("cut", True):
        return None
    c = catalog.mating(q["spec"], float(q["depth"]))
    return None if c is None else _plane(q).location * c.shape


def apply(shape, q):
    """The host with this placement's mating feature cut (build() calls it). Worker only."""
    from .recipes.base import RecipeError
    c = cutter(q)
    if c is None:
        return shape
    before = float(shape.volume)
    try:
        out = shape - c
    except Exception as e:
        raise RecipeError(f"The cut for {label(q)} could not be made ({type(e).__name__})", q.get("id") or "part",
                          "Pick another point on the part.", []) from e
    if not out.is_valid or before - float(out.volume) <= 1e-6 * (1 + before):
        raise RecipeError(f"The cut for {label(q)} does not reach the part", q.get("id") or "part",
                          "Pick a point on the part's surface, on a hole or a flat face.", [])
    return out


def _cyl(face):
    """(axis location, direction, radius) of a cylindrical face, or None."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    s = BRepAdaptor_Surface(face.wrapped)
    if s.GetType() != GeomAbs_Cylinder:
        return None
    c = s.Cylinder()
    ax = c.Axis()
    lo, di = ax.Location(), ax.Direction()
    return (lo.X(), lo.Y(), lo.Z()), (di.X(), di.Y(), di.Z()), c.Radius()


def _thickness(shape, at, n, limit=500.0) -> float | None:
    """Material under a surface point, along -n (stepping into the solid, then bisecting its far face)."""
    import numpy as np
    from build123d import Vector
    a, d = np.asarray(at, float), -np.asarray(n, float)
    inside = lambda t: shape.is_inside(Vector(*(a + d * t)), tolerance=1e-4)
    t, step = 0.05, 0.5
    if not inside(t):
        return None
    while t < limit and inside(t + step):
        t += step
    lo, hi = t, t + step
    for _ in range(24):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if inside(m) else (lo, m)
    return round((lo + hi) / 2, 3)


def op_part_snap(key, recipe_id, values, at, normal=None, tol=0.05):
    """Kernel op: what is at the point (a hole or a flat face), where a part goes there and the host's thickness."""
    import numpy as np
    from build123d import Vector
    from .kernel import _get_near
    shape = _get_near(key, recipe_id, values, tol)["shape"]
    p = Vector(*at)
    faces = sorted(shape.faces(), key=lambda f: f.distance_to(p))
    if not faces or faces[0].distance_to(p) > 2.0:
        return {"kind": "none", "reason": "No face of the part within 2 mm of the point."}
    f = faces[0]
    cyl = _cyl(f)
    if cyl is not None:
        o, d, r = (np.asarray(x, float) if not isinstance(x, float) else x for x in cyl)
        q = np.asarray(at, float)
        nrm = np.asarray(tuple(f.normal_at(p)), float)
        foot = o + d * np.dot(q - o, d)
        concave = np.dot(nrm, foot - q) > 0                 # the face's normal points to the axis: a hole
        if concave:
            ts = [float(np.dot(np.asarray(tuple(v), float) - o, d)) for v in f.vertices()] or [0.0]
            if len(set(round(t, 6) for t in ts)) < 2:
                bb = f.bounding_box()
                ts = [float(np.dot(np.asarray(c, float) - o, d)) for c in ((bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z))]
            t0, t1 = min(ts), max(ts)
            ends = []
            for t, sgn in ((t1, 1.0), (t0, -1.0)):
                e = o + d * t
                open_ = not shape.is_inside(Vector(*(e + sgn * d * 0.3)), tolerance=1e-4)
                ends.append((open_, -abs(float(np.dot(q - e, d))), e, sgn))
            ends.sort(key=lambda x: (not x[0], -x[1]))
            _o, _dist, e, sgn = ends[0]
            n = d * sgn
            return {"kind": "hole", "at": [round(float(x), 4) for x in e], "normal": [round(float(x), 6) for x in n],
                    "hole_d": round(2 * float(r), 4), "hole_length": round(t1 - t0, 4),
                    "through": bool(ends[0][0] and ends[1][0]),
                    "thickness": round(t1 - t0, 4) if (ends[0][0] and ends[1][0]) else _thickness(shape, e, n)}
    if f.geom_type.name != "PLANE":
        return {"kind": "none", "reason": f"The nearest face is {f.geom_type.name.lower()}, not flat and not a hole."}
    n = np.asarray(tuple(f.normal_at(p)), float)
    c = np.asarray(tuple(f.center()), float)
    q = np.asarray(at, float)
    on = q - n * float(np.dot(q - c, n))
    return {"kind": "face", "at": [round(float(x), 4) for x in on], "normal": [round(float(x), 6) for x in n],
            "thickness": _thickness(shape, on, n), "area_mm2": round(float(f.area), 3)}


def op_part_fit(key, recipe_id, values, placements, tol=0.05):
    """Kernel op: each placed part as fitted, intersected with the cut host (B-rep)."""
    from .kernel import _get_near
    from .massprops import unit_props
    host = _get_near(key, recipe_id, values, tol)["shape"]
    out = []
    for q in placements:
        try:
            s = placed_shape(q)
            vol = float(unit_props(s)["volume_mm3"])
            inter = host & s
            iv = float(inter.volume) if inter is not None and inter.solids() else 0.0
            bb = s.bounding_box()
            out.append({"id": q["id"], "part_volume_mm3": round(vol, 4), "interference_mm3": round(iv, 4),
                        "bbox": [[round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
                                 [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)]]})
        except Exception as e:                           # noqa: BLE001 - report the one that failed, check the rest
            out.append({"id": q["id"], "error": f"{type(e).__name__}: {getattr(e, 'msg', e)}"})
    return {"version": VERSION, "rows": out}


KERNEL_OPS = {"part_snap": op_part_snap, "part_fit": op_part_fit}


# ---- radial clearance from the tables (no kernel) --------------------------------------------------------------------
def gaps(spec: dict, depth: float) -> list[dict]:
    """Designed gaps per side between the part and its cut, from the part's table and the cut's dimensions."""
    from . import catalog
    it = catalog.resolve(spec)
    f = catalog.family(it["family"])
    d, m = f.dims(it), f.mating_dims(it, depth)
    v = lambda t, k: t[k]["value"]
    rows = []

    def add(name, part, cut, what):
        rows.append({"name": name, "part_mm": round(part, 4), "cut_mm": round(cut, 4), "per_side_mm": round((cut - part) / 2, 4),
                     "what": what})
    fid = it["family"]
    if fid in ("iso4762", "din912", "iso7380", "iso10642"):
        add("shank", v(d, "d"), v(m, "hole_d"), "shank in the clearance hole")
        if "recess_d" in m:
            add("head", v(d, "head_d"), v(m, "recess_d"), "head in its counterbore or sink")
    elif fid == "iso4032":
        add("nut", v(d, "across_flats"), v(m, "pocket_af"), "nut across flats in the trap")
    elif fid == "heat_insert":
        add("insert", v(d, "outer_d"), v(m, "hole_d"), "insert in its pocket (negative: the plastic it displaces)")
    elif fid == "bearing":
        add("outer ring", v(d, "outer_d"), v(m, "seat_d"), "outer ring in the seat")
    elif fid == "lm_uu":
        add("sleeve", v(d, "outer_d"), v(m, "bore_d"), "bushing in the housing bore")
    elif fid in ("dowel", "linear_rod"):
        add("pin", v(d, "d"), v(m, "hole_d"), "pin or shaft in its hole (negative: press fit)")
    elif fid == "magnet":
        add("magnet", v(d, "d"), v(m, "pocket_d"), "magnet in its pocket")
    elif fid == "nema":
        add("pilot", v(d, "pilot_d"), v(m, "pilot_pocket_d"), "motor pilot in its pocket")
        add("shaft", v(d, "shaft_d"), v(m, "shaft_hole_d"), "shaft through the plate")
    elif fid == "oring":
        add("section", v(d, "section"), v(m, "groove_width"), "O-ring section across its groove")
    elif fid == "tnut":
        add("screw", 5.0, v(m, "hole_d"), "M5 screw in the clearance hole")
    return rows


# ---- the design ---------------------------------------------------------------------------------------------------
def list_parts(st, p) -> list:
    try:
        return split(_python_source(st, p))[1]
    except Exception:                                    # noqa: BLE001
        return []


def _geom(st, p, rev=None):
    r = st.rev(p, rev)
    return r, st.keys(p, r["n"])["geometry"]


def snap(st, p, at, normal=None, rev=None) -> dict:
    """What is at the point: a hole (snapped to its axis and opening) or a flat face, and the host's thickness there."""
    r, gk = _geom(st, p, rev)
    at = _vec(at, "The point")
    out = st._k("part_snap", timeout=120, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"],
                at=list(at), normal=list(_vec(normal, "The normal")) if normal is not None else None)
    out["evidence"] = "computed"
    return out


def _commit(st, p, specs: list, note: str, expect_head, origin):
    for i, q in enumerate(specs):
        q["id"] = f"{PREFIX}{i + 1}"
    src = join(_python_source(st, p), specs)
    p = st.update_design(p, src, note=note, origin=origin, expect_head=expect_head)
    return p, specs


def place(st, p, spec: dict, at, normal=None, depth: float | None = None, qty: int = 1, cut: bool = True,
          snap_to: bool = True, up=None, expect_head=None, origin="you", check: bool = True) -> dict:
    """Place a standard part: snap, cut its mating feature into the host, record it as purchased, check its fit.

    spec: {family, size, ...} (form.catalog). at: a point on the part (a hole's wall or a flat face); normal: the
    outward direction (needed when snap_to=False). depth: the host thickness the cut goes through (default: measured
    under the point). A screw without a length gets the shortest stock length that passes the host and engages one
    diameter beyond it. Returns the new head, the placement, what it snapped to and the fit rows."""
    from . import catalog
    _python_source(st, p)                               # refuse built-in recipes and OpenSCAD before any kernel call
    specs = list_parts(st, p)
    if len(specs) >= MAX_PARTS:
        raise _err(f"A design carries at most {MAX_PARTS} placed parts.", "Remove one first.")
    it = catalog.resolve(spec)
    f = catalog.family(it["family"])
    got = None
    if snap_to:
        got = snap(st, p, at, normal)
        if got.get("kind") == "none":
            raise _err("Nothing to place on there: " + got.get("reason", ""), "Pick a point on a hole or a flat face.")
        at, normal = got["at"], got["normal"]
    elif normal is None:
        raise _err("A placement without snapping needs normal (the outward direction).")
    n = _vec(normal, "The normal")
    if sum(c * c for c in n) < 0.5:
        raise _err("The normal is not a direction.")
    th = (got or {}).get("thickness")
    dep = float(depth) if depth is not None else (float(th) if th else f.default_depth(it))
    if dep <= 0:
        raise _err("The host has no material under that point.", "Pick a point on the part's surface.")
    if isinstance(f, catalog._Screw) and not it.get("length"):
        it["length"] = f.choose_length(it, dep)
        it = catalog.resolve(it)
    q = {"id": "", "spec": it, "at": tuple(round(float(x), 4) for x in at), "normal": tuple(round(float(x), 6) for x in n),
         "depth": round(dep, 3), "qty": max(1, int(qty)), "cut": bool(cut),
         "snap": (got or {}).get("kind", "given"), **({"up": _vec(up, "The up direction")} if up is not None else {})}
    if got and got.get("kind") == "hole":
        q["hole_d"] = got.get("hole_d")
    p, specs = _commit(st, p, specs + [q], "Placed " + label(q), expect_head, origin)
    q = specs[-1]
    out = {"head": p["head"], "placement": q, "designation": catalog.designation(it), "snapped": got,
           "describe": catalog.describe(it, dep)}
    if check:
        out["fit"] = fit(st, p, only=q["id"])
    return out


def remove(st, p, part_id: str, expect_head=None, origin="you") -> dict:
    specs = list_parts(st, p)
    left = [q for q in specs if q.get("id") != part_id]
    if len(left) == len(specs):
        ids = [q.get("id") for q in specs]
        raise _err(f"No placed part “{part_id}” on this design.", ("Placed: " + ", ".join(ids) + ".") if ids else "None placed.")
    gone = next(q for q in specs if q.get("id") == part_id)
    p, specs = _commit(st, p, left, "Removed " + label(gone), expect_head, origin)
    return {"head": p["head"], "placements": specs, "removed": part_id}


def fit(st, p, rev=None, only: str | None = None) -> dict:
    """Every placed part checked against its cut host: interference on the B-rep (computed) and the designed
    clearance per side from the tables (computed). Stored by the geometry key."""
    from . import catalog, fsutil
    from .studio import H
    r, gk = _geom(st, p, rev)
    specs = split(st.source_text(p, r["n"]) or "")[1]
    if only:
        specs = [q for q in specs if q["id"] == only]
    if not specs:
        return {"rev": r["n"], "rows": [], "headline": "No standard parts placed", "evidence": "computed", "ok": True}
    key = H("partfit", VERSION, catalog.VERSION, gk, only or "")
    path = st.dir(p["id"]) / "artifacts" / "parts" / f"fit-{key[:20]}.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    raw = st._k("part_fit", timeout=300, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"],
                placements=specs)
    by = {x["id"]: x for x in raw["rows"]}
    rows, bad = [], 0
    for q in specs:
        it = catalog.resolve(q["spec"])
        f = catalog.family(it["family"])
        k = by.get(q["id"], {"error": "not measured"})
        row = {"id": q["id"], "designation": f.designation(it), "mate": f.mate, "gaps": gaps(it, q["depth"])}
        if "error" in k:
            row.update(status="FAIL", detail="The part could not be checked: " + k["error"])
        else:
            iv, pv = k["interference_mm3"], k["part_volume_mm3"]
            dust = max(EPS_MM3, 1e-5 * pv)
            row.update(interference_mm3=iv, part_volume_mm3=pv)
            if f.mate == "press":
                ok = iv > dust
                row["status"] = "PASS" if ok else "WARN"
                row["detail"] = (f"Press fit as designed: {iv:.3f} mm³ of host material is displaced by the part."
                                 if ok else "The part does not grip its hole (no interference): it will be loose.")
            else:
                ok = iv <= dust
                row["status"] = "PASS" if ok else "FAIL"
                neg = [g for g in row["gaps"] if g["per_side_mm"] < 0]
                row["detail"] = ("The part clears its cut: no interference with the host." if ok else
                                 f"The part runs into the host: {iv:.3f} mm³ of overlap" +
                                 (f" ({neg[0]['what']}: {neg[0]['per_side_mm']:g} mm per side)." if neg else "."))
        row["evidence"] = "computed (B-rep boolean; gaps from the tables)"
        bad += row["status"] == "FAIL"
        rows.append(row)
    n = len(rows)
    out = {"rev": r["n"], "rows": rows, "ok": bad == 0, "evidence": "computed",
           "headline": f"{n} placed · " + ("fit checked, all clear" if bad == 0 else f"{bad} interfere")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    fsutil.replace(tmp, path)
    return out

