"""More hand features (kernel side; runs in the worker): sweep, loft, rib, mirror, draft, move face, thicken, boolean,
split, variable-radius fillet, and datum planes and axes.

Like form/handfeat.py and form/handsketch.py, each feature is one named method in the design's source that calls one
function here (form/modelling.py writes it), with its sizes as parameters and the geometry it acts on as stable
queries (the features that made a face or edge, its class, direction and place) or as a sketch literal:

    @feature("Mirror 1", role="structure")
    def mirror_1(self, v, body):
        from form import handmore
        return handmore.mirror(body, self._form_trail, {"datum": "YZ", "offset": 0}, None, v, "mirror_1")

Planes (mirror, split, draft's neutral plane, sketches) are a datum ({"datum": "XY", "offset": mm}), a picked flat
face ({"face": query}) or a datum plane feature, written as its definition with a "ref" to it so the tree knows
who reads it ({"ref": "datum_plane_1", "base": "XY", "offset": "datum_plane_1_offset"}: a parameter key is read from
the values, so changing the datum plane's offset moves every sketch on it). form/handsketch.resolve_plane builds them.

Every function either makes the feature at the sizes it is given or raises a RecipeError saying what does not fit
(the feature is then left out of the build and the Program pane says why). Nothing is shrunk or guessed.

Multi-body: a sketch extruded with mode "new", a thicken with new=True and a split that keeps both sides leave the
design with several solids (form/modelling.py raises the class's `solids` declaration with them); boolean() then
combines, subtracts or intersects two of them, each named by a point inside it.
"""
from __future__ import annotations

import math

from .recipes.base import RecipeError

EVIDENCE = "computed (B-rep)"
SWEEP_MODES = ("add", "cut", "new")
BOOLEAN_OPS = ("combine", "subtract", "intersect")
SPLIT_KEEP = ("both", "above", "below")
TWIST_STEP = 15.0       # degrees of twist between the sections a twisted sweep is lofted through


def _say(what, msg, hint=""):
    return RecipeError(f"{what}: {msg}", what, hint)


def _vec3(p):
    from build123d import Vector
    return Vector(*[float(x) for x in p])


def _plane(spec, body, trail, v, what):
    from . import handsketch
    return handsketch.resolve_plane(spec, body, trail, what, v)


def _merge(body, tool, mode, what):
    from build123d import Compound

    from .craft import safe_cut, safe_union
    if tool is None or not tool.solids() or tool.volume <= 1e-9:
        raise _say(what, "it makes no solid", "Check the profile and the path or sections.")
    if not tool.is_valid:
        raise _say(what, "it makes a solid that is not valid (it folds over itself)",
                   "Make the profile smaller than the path's tightest bend, or change the sections.")
    if body is None:
        if mode == "cut":
            raise _say(what, "a cut needs a body to cut", "Make the body first.")
        return tool
    if mode == "new":
        return Compound(list(body.solids()) + list(tool.solids()))
    try:
        return safe_union(body, tool) if mode == "add" else safe_cut(body, tool)
    except RecipeError as e:
        raise _say(what, str(e), e.hint or "It does not meet the part.")


def _delta(trail, of, what):
    """What feature `of` added and cut, read from the trail (as pattern() does)."""
    ids = [s.feature for s in trail]
    if of not in ids:
        raise _say(what, f"it repeats {of}, which is not built before it", f"Restore {of} or move this after it.")
    i = ids.index(of)
    if i == 0:
        return trail[0].shape, None
    before, after = trail[i - 1].shape, trail[i].shape
    added, removed = after - before, before - after
    add = added if added is not None and sum(s.volume for s in added.solids()) > 1e-6 else None
    rem = removed if removed is not None and sum(s.volume for s in removed.solids()) > 1e-6 else None
    if add is None and rem is None:
        raise _say(what, f"{of} changes no volume, so there is nothing to mirror", "Pick another feature.")
    return add, rem


# ---- datum planes and axes ------------------------------------------------------------------------------------------

def datum_plane(body, trail, spec: dict, v: dict, what: str = "datum_plane"):
    """A reference plane: the body passes through unchanged; the plane is checked to exist (three points not in a row,
    a face still on the part). Sketches, mirrors and splits on it carry its definition (see the module text)."""
    _plane(spec, body, trail, v, what)
    return body


def axis_of(spec: dict, body, trail, v: dict | None, what: str):
    """(origin, unit direction) of a datum axis: through two points, a base axis (X, Y, Z) moved by offset, or a
    picked straight edge, or the line where two planes meet."""
    from build123d import Vector
    if "through" in spec:
        a, b = (_vec3(p) for p in spec["through"])
        if (b - a).length < 1e-6:
            raise _say(what, "the two points are the same, so they make no axis", "Pick two different points.")
        return a, (b - a).normalized()
    if "base" in spec:
        d = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}.get(str(spec["base"]).upper())
        if d is None:
            raise _say(what, f"unknown base axis {spec['base']!r}", "X, Y or Z.")
        return _vec3(spec.get("origin") or (0, 0, 0)), Vector(*d)
    if "edge" in spec:
        from . import handfeat
        if body is None:
            raise _say(what, "an axis on an edge needs a body", "Use a base axis.")
        e = handfeat.find_edges(body, trail, [spec["edge"]], what)[0]
        if e.geom_type.name != "LINE":
            raise _say(what, "its edge is not straight", "Pick a straight edge.")
        a, b = e.position_at(0), e.position_at(1)
        return a, (b - a).normalized()
    if "planes" in spec:
        p1, p2 = (_plane(s, body, trail, v, what) for s in spec["planes"])
        d = p1.z_dir.cross(p2.z_dir)
        if d.length < 1e-9:
            raise _say(what, "the two planes are parallel, so they do not meet in a line", "Pick planes that cross.")
        d = d.normalized()
        # the point on both planes nearest the first plane's origin
        n1, n2 = p1.z_dir, p2.z_dir
        h1, h2 = n1.dot(p1.origin), n2.dot(p2.origin)
        c = n1.dot(n2)
        k = 1 - c * c
        o = n1 * ((h1 - h2 * c) / k) + n2 * ((h2 - h1 * c) / k)
        return o, d
    raise _say(what, "an axis is through two points, a base axis, a straight edge or where two planes meet", "")


def datum_axis(body, trail, spec: dict, v: dict, what: str = "datum_axis"):
    """A reference axis: the body passes through unchanged; the axis is checked to exist."""
    axis_of(spec, body, trail, v, what)
    return body


# ---- sweep, loft, rib -----------------------------------------------------------------------------------------------

def _path(path, body, trail, v, what):
    """The sweep's path: a sketch (lines and arcs, open or closed) or a chain of the body's edges (queries)."""
    from build123d import Wire

    from . import handfeat, handsketch
    if isinstance(path, dict) and "edges" in path:
        if body is None:
            raise _say(what, "a path along edges needs a body", "Sketch the path instead.")
        es = handfeat.find_edges(body, trail, path["edges"], what)
        try:
            ws = Wire.combine(es)
        except Exception as e:                                # noqa: BLE001
            raise _say(what, f"its edges do not join ({type(e).__name__})", "Pick edges that meet end to end.")
        if len(ws) != 1:
            raise _say(what, f"its edges make {len(ws)} chains, not one", "Pick edges that meet end to end.")
        return ws[0]
    d = handsketch.check(path)
    return handsketch.open_wire(d, v, what + "_path_", handsketch.plane_of(d, body, trail, what, v), what)


def sweep(body, trail, profile: dict, path, v: dict, what: str = "sweep", mode: str = "add", twist: float = 0.0,
          frenet: bool = False):
    """The profile sketch swept along the path (a sketch, or {"edges": [queries]} along the body), turning by twist
    degrees from start to end. mode add | cut | new. The profile is where it is drawn: draw it across the path's
    start. Named dimensions of the profile are parameters "<feature>_<name>", of the path "<feature>_path_<name>"."""
    from build123d import Location, Transition
    from build123d import sweep as _sweep

    from . import handsketch
    if mode not in SWEEP_MODES:
        raise _say(what, f"mode is add, cut or new, not {mode!r}")
    pd = handsketch.check(profile)
    face = handsketch.profile(pd, v, what + "_", handsketch.plane_of(pd, body, trail, what, v))
    wire = _path(path, body, trail, v, what)
    if not wire.is_closed and float(face.distance_to(wire.position_at(1))) < float(face.distance_to(wire.position_at(0))):
        wire = _walk_back(wire)                          # the profile sits at the other end: walk the path from there
    start = wire.position_at(0)
    gap = float(face.distance_to(start))
    if gap > max(1e-3, 0.02 * wire.length):
        raise _say(what, f"the profile is {gap:.2f} mm from the path's start",
                   "Draw the profile on a plane through the path's start (a datum plane at the path's end).")
    try:
        if abs(float(twist or 0)) > 1e-9:
            # the profile carried along the path and turned a share of the twist, every TWIST_STEP degrees at most
            n = max(2, math.ceil(abs(float(twist)) / TWIST_STEP))
            l0 = wire.location_at(0)
            secs = [face] + [(wire.location_at(k / n) * Location((0, 0, 0), (0, 0, 1), float(twist) * k / n)
                              * l0.inverse()) * face for k in range(1, n + 1)]
            tool = _sweep(secs, path=wire, multisection=True, is_frenet=bool(frenet))
        else:
            tool = _sweep(face, path=wire, is_frenet=bool(frenet), transition=Transition.RIGHT)
    except Exception as e:                                    # noqa: BLE001
        raise _say(what, f"OCCT could not sweep this profile along this path ({type(e).__name__})",
                   "Make the profile smaller than the path's tightest bend, or smooth the path's corners.")
    return _merge(body, tool, mode, what)


def _walk_back(wire):
    """The same path walked from its other end (each edge rebuilt from its points, so no orientation flag is left
    for position_at to read the old way)."""
    from build123d import Edge, Wire
    out = []
    for e in reversed(wire.ordered_edges() if hasattr(wire, "ordered_edges") else wire.edges()):
        a, m, b = e.position_at(0), e.position_at(0.5), e.position_at(1)
        if e.geom_type.name == "LINE":
            out.append(Edge.make_line(b, a))
        elif e.geom_type.name == "CIRCLE":
            out.append(Edge.make_three_point_arc(b, m, a))
        else:
            out.append(Edge.make_spline([e.position_at(1 - k / 16) for k in range(17)]))
    return Wire(out)


def loft(body, trail, sections: list, v: dict, what: str = "loft", mode: str = "add", ruled: bool = False):
    """A solid through two or more closed profile sketches, in the order given (on parallel or offset planes, or
    turned ones), ruled (straight between sections) or smooth. Named dimensions are "<feature>_s<i>_<name>"."""
    from build123d import loft as _loft

    from . import handsketch
    if mode not in SWEEP_MODES:
        raise _say(what, f"mode is add, cut or new, not {mode!r}")
    if not isinstance(sections, (list, tuple)) or len(sections) < 2:
        raise _say(what, "a loft needs two or more profile sketches", "Give sections: [sketch, sketch, ...].")
    faces = []
    for i, s in enumerate(sections, 1):
        d = handsketch.check(s)
        f = handsketch.profile(d, v, f"{what}_s{i}_", handsketch.plane_of(d, body, trail, what, v))
        if len(f.faces()) != 1:
            raise _say(what, f"section {i} has {len(f.faces())} separate regions; a loft section is one",
                       "Draw one closed outline per section.")
        faces.append(f.faces()[0])
    for i in range(1, len(faces)):
        n0 = faces[i - 1].normal_at()
        if abs(faces[i].normal_at().dot(n0)) > 1 - 1e-9 and abs((faces[i].center() - faces[i - 1].center()).dot(n0)) < 1e-6:
            raise _say(what, f"sections {i} and {i + 1} lie on the same plane", "Put each section on its own plane.")
    try:
        tool = _loft(faces, ruled=bool(ruled))
    except Exception as e:                                    # noqa: BLE001
        raise _say(what, f"OCCT could not loft these sections ({type(e).__name__})",
                   "Give the sections the same number of edges, or make them less twisted.")
    return _merge(body, tool, mode, what)


def rib(body, trail, sketch: dict, v: dict, thickness: float, what: str = "rib", direction: str = "parallel",
        flip: bool = False):
    """A rib or web from an open sketch line (or chain), thickness mm thick, grown out to the faces of the body.
    direction parallel: the material grows in the sketch plane, away from the line (the usual web in a corner),
    thickness centred on the sketch plane; normal: it grows along the plane's normal, thickness centred on the line.
    flip: grow to the other side. Refused when the rib does not meet the body on that side."""
    from build123d import Vector, extrude

    from . import handsketch
    from .craft import safe_union
    if body is None:
        raise _say(what, "a rib needs a body to meet", "Make the body first.")
    t = float(thickness)
    if t <= 0:
        raise _say(what, "a rib needs a thickness above 0", "Set its thickness.")
    if direction not in ("parallel", "normal"):
        raise _say(what, f"direction is parallel or normal, not {direction!r}")
    d = handsketch.check(sketch)
    plane = handsketch.plane_of(d, body, trail, what, v)
    wire = handsketch.open_wire(d, v, what + "_", plane, what)
    if wire.is_closed:
        raise _say(what, "a rib's line is open; this one closes", "Draw an open line, or extrude a closed profile.")
    n = plane.z_dir
    a, b = wire.position_at(0), wire.position_at(1)
    chord = b - a
    if chord.length < 1e-6:
        raise _say(what, "its line starts and ends at one point", "Draw an open line.")
    side = n.cross(chord).normalized() * (-1.0 if flip else 1.0)   # in the plane, perpendicular to the line
    bb = body.bounding_box()
    L = 2 * math.dist((bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z)) + 4
    # the slab the rib is cut from: the line swept far to one side, thickness t
    if direction == "parallel":
        sheet = _band(wire, side * L)
        slab = extrude(sheet.moved(_loc(n * (-t / 2))), amount=t, dir=n)
        grow = side
    else:
        sheet = _band(wire.moved(_loc(side * (-t / 2))), side * t)
        slab = extrude(sheet, amount=L, dir=n * (-1.0 if flip else 1.0))
        grow = n * (-1.0 if flip else 1.0)
    pieces = slab - body
    probe = wire.position_at(0.5) + grow * min(0.05, t / 4)
    keep = [s for s in (pieces.solids() if pieces is not None else []) if s.is_inside(probe)]
    if not keep:
        raise _say(what, "its line is inside the part, so there is no room for a rib on that side",
                   "Flip it, or draw the line where the rib should start.")
    piece = keep[0]
    ext = max((Vector(*q.center()) - a).dot(grow) for q in piece.vertices())
    if ext > L * 0.9:
        raise _say(what, "it meets no face on that side: it would run off the part",
                   "Flip it, or draw the line facing the faces it should reach.")
    return safe_union(body, piece)


def _band(wire, vec):
    """The flat face between a wire and its copy moved by vec (the wire and vec in one plane)."""
    from build123d import Edge, Face, Wire
    a, b = wire.position_at(0), wire.position_at(1)
    moved = wire.moved(_loc(vec))
    w = Wire.combine(list(wire.edges()) + [Edge.make_line(b, b + vec)] + list(moved.edges())
                     + [Edge.make_line(a + vec, a)])
    return Face(w[0])


def _loc(vec):
    from build123d import Location
    return Location(tuple(vec))


# ---- mirror, draft, move face, thicken ------------------------------------------------------------------------------

def mirror(body, trail, plane: dict, of, v: dict, what: str = "mirror"):
    """The whole body (of None) or what the named features added and cut (of [ids]), mirrored about the plane and
    joined: the mirrored body must meet the original (a mirror that leaves two parts is refused by the build)."""
    from .craft import safe_cut, safe_union
    pl = _plane(plane, body, trail, v, what)
    if body is None:
        raise _say(what, "a mirror needs a body", "Make the body first.")
    if not of:
        m = body.mirror(pl)
        try:
            return safe_union(body, m)
        except RecipeError as e:
            raise _say(what, f"the mirrored body does not join the original ({e})",
                       "Mirror about a face of the part, or a plane that touches it.")
    out = body
    for fid in ([of] if isinstance(of, str) else list(of)):
        add, rem = _delta(trail, fid, what)
        if add is not None:
            out = safe_union(out, add.mirror(pl))
        if rem is not None:
            out = safe_cut(out, rem.mirror(pl))
    return out


def draft(body, trail, faces: list, angle: float, neutral: dict, v: dict, what: str = "draft", flip: bool = False):
    """The picked faces tilted by angle degrees about where they meet the neutral plane, against the pull direction
    (the neutral plane's normal; flip reverses it), as a mould needs. Flat, cylindrical and conical faces."""
    from build123d import Plane
    from . import handfeat
    if body is None:
        raise _say(what, "a draft needs a body")
    a = float(angle)
    if not 0 < abs(a) < 45:
        raise _say(what, f"the draft angle is {a:g}°; it is between 0 and 45", "Use a few degrees, as moulding does.")
    if not faces:
        raise _say(what, "a draft needs at least one picked face", "Pick the side faces.")
    fs = [handfeat.find_face(body, trail, q, what) for q in faces]
    npl = _plane(neutral, body, trail, v, what)
    pull = npl.z_dir * (-1.0 if flip else 1.0)
    for i, f in enumerate(fs, 1):
        if f.geom_type.name == "PLANE" and abs(f.normal_at(f.center()).dot(pull)) > 1 - 1e-6:
            raise _say(what, f"face {i} faces the pull direction; a draft tilts the faces along it",
                       "Pick the side faces, not the top or bottom.")
    try:
        sl = body.solids()
        if len(sl) != 1:
            raise _say(what, "a draft works on a body of one solid", "Combine the bodies first.")
        out = sl[0].draft(fs, Plane(origin=npl.origin, z_dir=pull), a)
    except RecipeError:
        raise
    except Exception as e:                                    # noqa: BLE001
        raise _say(what, f"OCCT could not draft these faces at {a:g}° ({type(e).__name__}: {str(e)[:120]})",
                   "Pick flat, cylindrical or conical faces that meet the neutral plane, or use a smaller angle.")
    if not out.is_valid:
        raise _say(what, "the drafted solid is not valid", "Use a smaller angle or fewer faces.")
    return out


def move_face(body, trail, faces: list, distance: float, what: str = "move_face"):
    """Push or pull the picked faces along their normals by distance mm (positive outward), the faces around them
    stretched to follow: a direct edit, written as a parametric offset. A flat face whose neighbours all run along
    its normal (a prismatic face: the usual case) moves by an exact extrusion of itself, added or cut; any other face
    by OCCT's BRepOffset with one offset per face. Both give the same solid where both apply."""
    from build123d import Solid
    from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
    from OCP.GeomAbs import GeomAbs_Intersection

    from . import handfeat
    if body is None:
        raise _say(what, "moving a face needs a body")
    dist = float(distance)
    if abs(dist) < 1e-6:
        raise _say(what, "the distance is 0", "Give the distance (negative pushes the face in).")
    if not faces:
        raise _say(what, "pick the face to move")
    fs = [handfeat.find_face(body, trail, q, what) for q in faces]
    solids = body.solids()
    if len(solids) != 1:
        raise _say(what, "moving a face works on a body of one solid", "Combine the bodies first.")
    if all(_prismatic(body, f) for f in fs):
        from build123d import extrude

        from .craft import safe_cut, safe_union
        out = body
        for f in fs:
            n = f.normal_at(f.center())
            tool = extrude(f, amount=abs(dist), dir=n if dist > 0 else -n)
            try:
                out = safe_union(out, tool) if dist > 0 else safe_cut(out, tool)
            except RecipeError as e:
                raise _say(what, f"moving the face by {dist:g} mm does not work here ({e})", "Use a smaller distance.")
        sl = out.solids()
        if len(sl) != 1 or not sl[0].is_valid:
            raise _say(what, f"moving the face by {dist:g} mm leaves {len(sl)} pieces or an invalid solid",
                       "Use a smaller distance: the face went through the part.")
        return sl[0]
    mk = BRepOffset_MakeOffset()
    mk.Initialize(solids[0].wrapped, 0.0, 1e-6, BRepOffset_Skin, False, False, GeomAbs_Intersection, False)
    for f in fs:
        mk.SetOffsetOnFace(f.wrapped, dist)
    try:
        mk.MakeOffsetShape()
        ok = mk.IsDone()
    except Exception:                                         # noqa: BLE001
        ok = False
    if not ok:
        raise _say(what, f"OCCT could not move the face{'s' if len(fs) > 1 else ''} by {dist:g} mm",
                   "Use a smaller distance, or move a face whose neighbours can stretch (no fillet around it).")
    out = Solid(mk.Shape()) if mk.Shape().ShapeType().name.endswith("SOLID") else None
    if out is None:
        from build123d import Shape
        shp = Shape.cast(mk.Shape())
        sl = shp.solids()
        out = sl[0] if len(sl) == 1 else None
    if out is None or not out.is_valid or out.volume <= 1e-9:
        raise _say(what, f"moving the face by {dist:g} mm leaves no valid solid", "Use a smaller distance.")
    return out


def _prismatic(body, f) -> bool:
    """A flat face whose neighbours all run along its normal (flat faces at right angles, cylinders whose axis is
    the normal): moving it is an extrusion of the face itself."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    if f.geom_type.name != "PLANE":
        return False
    n = f.normal_at(f.center())
    edges = {hash(e) for e in f.edges()}
    for g in body.faces():
        if g.is_same(f) or not any(hash(e) in edges for e in g.edges()):
            continue
        s = BRepAdaptor_Surface(g.wrapped)
        t = s.GetType()
        if t == GeomAbs_Plane:
            if abs(g.normal_at(g.center()).dot(n)) > 1e-7:
                return False
        elif t == GeomAbs_Cylinder:
            a = s.Cylinder().Axis().Direction()
            if abs(abs(a.X() * n.X + a.Y() * n.Y + a.Z() * n.Z) - 1) > 1e-7:
                return False
        else:
            return False
    return True


def thicken(body, trail, face, thickness: float, v: dict, what: str = "thicken", both: bool = False,
            new: bool = False):
    """A surface made solid: a picked face of the body ({"face": query}, any shape: flat, curved) or a sketch
    profile, thickness mm along its normal (both: half each side). It joins the body, or is a new body (new=True)."""
    from build123d import Compound
    from build123d import thicken as _thicken

    from . import handfeat, handsketch
    from .craft import safe_union
    t = float(thickness)
    if t <= 0:
        raise _say(what, "a thicken needs a thickness above 0", "Set its thickness.")
    if isinstance(face, dict) and "face" in face:
        if body is None:
            raise _say(what, "thickening a face needs a body")
        f = handfeat.find_face(body, trail, face["face"], what)
    else:
        d = handsketch.check(face)
        f = handsketch.profile(d, v, what + "_", handsketch.plane_of(d, body, trail, what, v))
    try:
        tool = _thicken(f, amount=t / 2 if both else t, both=bool(both))
    except Exception as e:                                    # noqa: BLE001
        raise _say(what, f"OCCT could not thicken this surface by {t:g} mm ({type(e).__name__})",
                   "Use less than the surface's smallest bend radius.")
    if tool is None or not tool.solids() or not tool.is_valid:
        raise _say(what, f"thickening by {t:g} mm leaves no valid solid", "Use a smaller thickness.")
    if body is None:
        return tool
    if new:
        return Compound(list(body.solids()) + list(tool.solids()))
    return safe_union(body, tool)


# ---- multi-body: boolean and split ----------------------------------------------------------------------------------

def _solid_at(solids, at, what, role):
    p = _vec3(at)
    hit = [s for s in solids if s.is_inside(p)]
    if not hit:
        raise _say(what, f"no body is at {role} point ({p.X:.2f}, {p.Y:.2f}, {p.Z:.2f})",
                   "Pick a point inside the body (the bodies may have moved: pick them again).")
    return hit[0]


def boolean(body, trail, op: str, target, tools: list, what: str = "boolean"):
    """Combine, subtract or intersect bodies of a multi-body design: target and each tool named by a point inside
    it. The result replaces target and the tools; the other bodies stay as they are."""
    from build123d import Compound
    if op not in BOOLEAN_OPS:
        raise _say(what, f"the operation is combine, subtract or intersect, not {op!r}")
    solids = list(body.solids()) if body is not None else []
    if len(solids) < 2:
        raise _say(what, f"the design has {len(solids)} body; a boolean needs two or more",
                   "Make another body first (a sketch extruded as a new body, or a split).")
    a = _solid_at(solids, target, what, "the target")
    used = [a]
    out = a
    for i, at in enumerate(tools or [], 1):
        b = _solid_at(solids, at, what, f"tool {i}")
        if any(b.is_same(u) for u in used):
            raise _say(what, f"tool {i} is the same body as the target or another tool", "Pick another body.")
        used.append(b)
        out = out.fuse(b) if op == "combine" else out.cut(b) if op == "subtract" else out.intersect(b)
    if len(used) < 2:
        raise _say(what, "a boolean needs at least one tool body", "Pick the tool body.")
    res = list(out.solids()) if out is not None else []
    if not res or sum(s.volume for s in res) <= 1e-9:
        raise _say(what, f"the {op} leaves nothing", "The bodies do not overlap: move them, or combine instead.")
    if op == "combine" and len(res) > 1:
        raise _say(what, "the bodies do not touch, so combining them still leaves separate bodies",
                   "Move them to overlap.")
    rest = [s for s in solids if not any(s.is_same(u) for u in used)]
    allofit = rest + res
    return allofit[0] if len(allofit) == 1 else Compound(allofit)


def split(body, trail, plane: dict, v: dict, keep: str = "both", what: str = "split"):
    """The body cut in two by a plane (a datum, a flat face or a datum plane): keep both (two bodies), or only the
    side above the plane (along its normal) or below it."""
    from build123d import Compound, Keep
    from build123d import split as _split
    if body is None:
        raise _say(what, "a split needs a body")
    if keep not in SPLIT_KEEP:
        raise _say(what, f"keep is both, above or below, not {keep!r}")
    pl = _plane(plane, body, trail, v, what)
    up = _split(body, bisect_by=pl, keep=Keep.TOP)
    dn = _split(body, bisect_by=pl, keep=Keep.BOTTOM)
    vu = sum(s.volume for s in up.solids()) if up is not None else 0.0
    vd = sum(s.volume for s in dn.solids()) if dn is not None else 0.0
    if vu <= 1e-6 or vd <= 1e-6:
        raise _say(what, "the plane does not cross the part, so nothing is split", "Move the plane into the part.")
    if keep == "above":
        return up
    if keep == "below":
        return dn
    return Compound(list(up.solids()) + list(dn.solids()))


# ---- variable-radius fillet -----------------------------------------------------------------------------------------

def variable_fillet(body, trail, edges: list, r_start: float, r_end: float, starts: list | None = None,
                    what: str = "variable_fillet"):
    """Round the picked edges with a radius that runs linearly from r_start to r_end along each (OCCT
    BRepFilletAPI_MakeFillet with two radii). starts: per edge, a point near the end that gets r_start (the edge's
    own orientation is not stable across rebuilds, so the end is found by place). Made at these sizes or refused."""
    from build123d import Shape
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    from . import handfeat
    r0, r1 = float(r_start), float(r_end)
    if min(r0, r1) <= 0:
        raise _say(what, "both radii must be above 0", "A radius of 0 is a sharp edge: use two fillets.")
    es = handfeat.find_edges(body, trail, edges, what)
    mk = BRepFilletAPI_MakeFillet(body.wrapped)
    for i, e in enumerate(es):
        a, b = e.position_at(0), e.position_at(1)
        s = (starts or [None] * len(es))[i] if starts and i < len(starts) else None
        flip = s is not None and (_vec3(s) - b).length < (_vec3(s) - a).length
        # OCCT's two radii run along the edge's parameter, which follows its orientation in the solid
        if e.wrapped.Orientation().name == "TopAbs_REVERSED":
            flip = not flip
        mk.Add(r1 if flip else r0, r0 if flip else r1, e.wrapped)
    try:
        mk.Build()
        ok = mk.IsDone()
    except Exception:                                         # noqa: BLE001
        ok = False
    if not ok:
        raise _say(what, f"a {r0:g} to {r1:g} mm variable fillet does not fit these {len(es)} edge(s)",
                   "Make the radii smaller than the faces the edges run between.")
    out = Shape.cast(mk.Shape())
    sl = out.solids()
    if len(sl) != 1 or not sl[0].is_valid:
        raise _say(what, "the variable fillet leaves an invalid solid", "Make the radii smaller.")
    return sl[0]
