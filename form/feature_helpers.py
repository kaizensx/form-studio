"""Standard features at a picked face: screw bosses and snap-fit hooks, written into the design's source as code.

A point picked on a flat face (and that face's normal, from ``form.selection``) becomes a feature spec. The specs live
in a block at the end of the design's Python source, between two marker lines, the same way text on faces does
(form/engrave.py), so an agent reads them, they are in every revision and they travel with the design:

    # ---- Form Studio: standard features (edit in the app or with `form feature`) ----
    _FORM_FEATURES = [{'id': 'boss_1', 'kind': 'boss', 'at': (0.0, 0.0, 10.0), 'normal': (0.0, 0.0, 1.0), ...}]
    ...
    # ---- end of standard features ----

The block wraps the design class's build(): after the design's own stages it adds one Stage per feature, built here
with build123d, so each one is a named feature in the viewport and the checks. Adding or removing one is
``Studio.update_design``: a new revision, built in the kernel before it is saved; a feature that does not sit on the
part is refused with the reason.

Numbers and where they come from:
  * Boss holes: "tapped" uses the ISO metric coarse tap-drill diameter, "clearance" ISO 273 medium clearance, "insert"
    a typical brass heat-set insert hole (check your insert's datasheet; pass hole_d to override any of them).
  * Boss wall = (outer diameter - hole) / 2, compared with the nozzle (computed).
  * Snap hook strain = 1.5 * t * y / L^2, the constant-section rectangular cantilever formula of snap-fit design
    guides (computed), compared with an allowable strain you can give; the default is a rule of thumb (heuristic).
"""
from __future__ import annotations

import math

from .engrave import _python_source, design_class, _vec, _err

START = "# ---- Form Studio: standard features (edit in the app or with `form feature`) ----"
END = "# ---- end of standard features ----"
MAX_FEATURES = 24
OVERLAP = 0.05
KINDS = ("boss", "snap_hook")

# hole diameters by screw size (mm)
TAP_DRILL = {"M2": 1.6, "M2.5": 2.05, "M3": 2.5, "M4": 3.3, "M5": 4.2}          # ISO metric coarse tap drill
CLEARANCE = {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5}           # ISO 273 medium
INSERT = {"M2": 3.2, "M2.5": 3.6, "M3": 4.0, "M4": 5.6, "M5": 6.4}              # typical heat-set insert hole
HOLES = {"tapped": TAP_DRILL, "clearance": CLEARANCE, "insert": INSERT}
HOLE_SOURCE = {"tapped": "ISO metric coarse tap-drill diameter", "clearance": "ISO 273 medium clearance hole",
               "insert": "typical brass heat-set insert hole; check your insert's datasheet"}
ALLOW_STRAIN = 0.02          # rule of thumb for a printed cantilever bending along its layers (heuristic, shown as such)

TEMPLATE = '''
{start}
from form import feature_helpers as _form_fh
from form.recipes.base import Feature as _FormFeature, Stage as _FormStage
_FORM_FEATURES = {specs}


def _form_features(cls):
    build = cls.build

    def with_features(self, v):
        stages = list(build(self, v))
        s = stages[-1].shape
        for f in _FORM_FEATURES:
            s = _form_fh.apply(s, f)
            stages.append(_FormStage(f["id"], s))
        return stages
    cls.build = with_features
    cls.features = [f for f in cls.features if not f.id.startswith(("boss_", "hook_"))] + [
        _FormFeature(f["id"], _form_fh.label(f), "structure") for f in _FORM_FEATURES]
    return cls


{cls} = _form_features({cls})
{end}
'''


# ---- the source block ---------------------------------------------------------------------------------------------
def split(source: str) -> tuple[str, list]:
    """(the source without the block, the feature specs it holds)."""
    import ast
    import re
    i = source.find(START)
    if i < 0:
        return source, []
    j = source.find(END, i)
    block = source[i:j if j >= 0 else len(source)]
    m = re.search(r"^_FORM_FEATURES = (.*)$", block, re.M)
    specs = ast.literal_eval(m.group(1)) if m else []
    rest = source[:i].rstrip() + "\n" + (source[j + len(END):].lstrip("\n") if j >= 0 else "")
    return rest.rstrip() + "\n", specs


def join(source: str, specs: list) -> str:
    base, _old = split(source)
    if not specs:
        return base
    return base.rstrip() + "\n" + TEMPLATE.format(start=START, end=END, cls=design_class(base), specs=repr(specs))


def label(f: dict) -> str:
    if f["kind"] == "boss":
        return f"{f['size']} screw boss ({f['hole']}), {f['height']:g} mm"
    return f"Snap-fit hook, {f['length']:g} mm"


# ---- specs ----------------------------------------------------------------------------------------------------------
def _num(x, lo, hi, what):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise _err(f"{what} must be a number.")
    if not (lo <= v <= hi):
        raise _err(f"{what} must be between {lo:g} and {hi:g} mm.")
    return round(v, 3)


def _d(o, k, default):
    return default if o.get(k) is None or o.get(k) == "" else o[k]


def spec(kind: str, at, normal, **o) -> dict:
    """A checked feature spec. boss: size (M2..M5), hole (tapped | clearance | insert), height, outer_d, hole_d,
    hole_depth. snap_hook: length, thickness, width, lip (the undercut), lip_height."""
    n = _vec(normal, "The face normal")
    if sum(c * c for c in n) < 0.5:
        raise _err("The face normal is not a direction.", "Pick a point on a flat face again.")
    out = {"id": "", "kind": kind, "at": _vec(at, "The point"), "normal": n}
    if o.get("up") is not None:
        out["up"] = _vec(o["up"], "The up direction")
    if kind == "boss":
        size = str(_d(o, "size", "M3"))
        hole = str(o.get("hole") or "tapped")
        if size not in TAP_DRILL:
            raise _err(f"Unknown screw size “{size}”.", "Use one of " + ", ".join(TAP_DRILL) + ".")
        if hole not in HOLES:
            raise _err(f"Unknown hole kind “{hole}”.", "Use tapped, clearance or insert.")
        hd = _num(o["hole_d"], 0.5, 30, "The hole diameter") if o.get("hole_d") else HOLES[hole][size]
        od = _num(o["outer_d"], 1, 60, "The outer diameter") if o.get("outer_d") else round(2 * hd + 0.8, 1)
        h = _num(_d(o, "height", 8), 1, 100, "The boss height")
        if od <= hd + 0.2:
            raise _err("The boss must be wider than its hole.", f"Make the outer diameter more than {hd + 0.2:g} mm.")
        dep = _num(o["hole_depth"], 0.5, 100, "The hole depth") if o.get("hole_depth") else h
        out.update(size=size, hole=hole, hole_d=hd, outer_d=od, height=h, hole_depth=min(dep, h))
    elif kind == "snap_hook":
        L = _num(_d(o, "length", 12), 3, 80, "The hook length")
        t = _num(_d(o, "thickness", 1.6), 0.4, 10, "The hook thickness")
        w = _num(_d(o, "width", 6), 1, 60, "The hook width")
        y = _num(_d(o, "lip", 1.0), 0.2, 10, "The lip (undercut)")
        lh = _num(_d(o, "lip_height", round(max(1.5, 2 * y), 2)), 0.5, L, "The lip height")
        out.update(length=L, thickness=t, width=w, lip=y, lip_height=min(lh, L))
    else:
        raise _err(f"Unknown feature “{kind}”.", "Use boss or snap_hook.")
    return out


def checks(f: dict, nozzle: float | None = None, allow_strain: float | None = None) -> list[dict]:
    """Check rows for one spec: wall against the nozzle (computed), hook strain against an allowable (computed vs heuristic)."""
    nz = float(nozzle) if nozzle else 0.4
    nzs = f"{nz:g} mm nozzle" + ("" if nozzle else " (assumed)")
    if f["kind"] == "boss":
        wall = (f["outer_d"] - f["hole_d"]) / 2
        st = "FAIL" if wall < nz else ("WARN" if wall < 2 * nz else "PASS")
        return [{"id": "boss_wall", "label": "Boss wall", "status": st, "value": f"{wall:.2f} mm",
                 "detail": f"(Ø{f['outer_d']:g} − Ø{f['hole_d']:g}) / 2. Hole: {HOLE_SOURCE[f['hole']]}. A {nzs} needs "
                           f"at least {2 * nz:g} mm for two perimeters.", "evidence": "computed"}]
    t, y, L = f["thickness"], f["lip"], f["length"]
    eps = 1.5 * t * y / (L * L)
    allow = float(allow_strain) if allow_strain else ALLOW_STRAIN
    st = "FAIL" if eps > allow else ("WARN" if eps > 0.8 * allow else "PASS")
    tst = "FAIL" if t < nz else ("WARN" if t < 2 * nz else "PASS")
    return [{"id": "hook_strain", "label": "Hook strain when it snaps", "status": st, "value": f"{100 * eps:.2f} %",
             "strain": round(eps, 5), "allowable": allow,
             "detail": f"ε = 1.5 · t · y / L² = 1.5 · {t:g} · {y:g} / {L:g}² (rectangular cantilever). Allowed "
                       f"{100 * allow:g} %" + (" (your value)." if allow_strain else
                                               " (a rule of thumb for printed hooks; give your material's value).")
                       + " Lengthen the hook or thin it to lower the strain.",
             "evidence": "computed" if allow_strain else "heuristic"},
            {"id": "hook_thickness", "label": "Hook thickness", "status": tst, "value": f"{t:.2f} mm",
             "detail": f"A {nzs} draws walls of at least {nz:g} mm; under {2 * nz:g} mm the hook is one line.",
             "evidence": "computed"}]


# ---- geometry (runs in the kernel worker) ---------------------------------------------------------------------------
def _plane(f):
    from . import marks
    return marks._plane(None, f["at"], f["normal"], f.get("up"))


def solid_of(f):
    """(added solid, removed solid or None) for one spec."""
    from build123d import Align, Cylinder, Plane, Polygon, Box, extrude
    pl = _plane(f)
    C = (Align.CENTER, Align.CENTER, Align.MIN)
    if f["kind"] == "boss":
        add = pl.offset(-OVERLAP) * Cylinder(f["outer_d"] / 2, f["height"] + OVERLAP, align=C)
        cut = pl.offset(f["height"] - f["hole_depth"]) * Cylinder(f["hole_d"] / 2, f["hole_depth"] + 0.01, align=C)
        return add, cut
    L, t, w, y, lh = f["length"], f["thickness"], f["width"], f["lip"], f["lip_height"]
    beam = pl.offset(-OVERLAP) * Box(w, t, L + OVERLAP, align=C)
    side = Plane(origin=pl.origin, x_dir=pl.y_dir, z_dir=pl.x_dir)        # local (y, z) of the hook in its own plane
    tri = Polygon((t / 2 - 0.01, L - lh), (t / 2 + y, L - lh), (t / 2 - 0.01, L), align=None)
    lip = extrude(side * tri, amount=w / 2, both=True)
    return beam + lip, None


def apply(shape, f):
    from .recipes.base import RecipeError
    add, cut = solid_of(f)
    before = len(shape.solids())
    try:
        out = shape + add
        if cut is not None:
            out = out - cut
    except Exception as e:
        raise RecipeError(f"The {label(f)} could not be added ({type(e).__name__})", f.get("id") or "feature",
                          "Pick another spot on a flat face.", []) from e
    if not out.is_valid or len(out.solids()) != before or out.volume <= shape.volume - 1e-6 * (1 + shape.volume):
        raise RecipeError(f"The {label(f)} does not sit on the part", f.get("id") or "feature",
                          "Pick a point on a flat face of the part, with room around it.", [])
    return out


def volumes(f) -> dict:
    """The spec's own added and removed volume, computed on its solids (no part needed)."""
    add, cut = solid_of(f)
    return {"added_mm3": round(add.volume, 3), "hole_mm3": round(cut.volume, 3) if cut is not None else 0.0}


# ---- the design ---------------------------------------------------------------------------------------------------
def list_features(st, p) -> list:
    try:
        return split(_python_source(st, p))[1]
    except Exception:
        return []


def _commit(st, p, specs: list, note: str, expect_head, origin):
    n = {"boss": 0, "snap_hook": 0}
    for f in specs:
        n[f["kind"]] += 1
        f["id"] = ("boss_" if f["kind"] == "boss" else "hook_") + str(n[f["kind"]])
    src = join(_python_source(st, p), specs)
    p = st.update_design(p, src, note=note, origin=origin, expect_head=expect_head)
    return {"head": p["head"], "features": specs}


def add(st, p, kind, at, normal, expect_head=None, origin="you", **o) -> dict:
    specs = split(_python_source(st, p))[1]
    if len(specs) >= MAX_FEATURES:
        raise _err(f"A design carries at most {MAX_FEATURES} standard features.", "Remove one first.")
    f = spec(kind, at, normal, **o)
    return _commit(st, p, specs + [f], "Added " + label(f), expect_head, origin)


def remove(st, p, feature_id: str, expect_head=None, origin="you") -> dict:
    specs = split(_python_source(st, p))[1]
    left = [f for f in specs if f.get("id") != feature_id]
    if len(left) == len(specs):
        raise _err(f"No feature “{feature_id}” on this design.", "List them with `form feature <project> --list`.")
    gone = next(f for f in specs if f.get("id") == feature_id)
    return _commit(st, p, left, "Removed " + label(gone), expect_head, origin)


def preview(kind, normal=(0, 0, 1), nozzle=None, allow_strain=None, **o) -> dict:
    """The spec with its check rows, without touching a design (the sheet calls this as you type)."""
    f = spec(kind, (0, 0, 0), normal, **o)
    out = {"spec": f, "checks": checks(f, nozzle, allow_strain)}
    if kind == "boss":
        out["hole_source"] = HOLE_SOURCE[f["hole"]]
    return out


def strain(t, y, L) -> float:
    return 1.5 * t * y / (L * L) if L > 0 else math.inf
