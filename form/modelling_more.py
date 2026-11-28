"""The edit ops that add the further hand features (form/handmore.py) and the end conditions of a sketch feature.

form/modelling.py's plan() hands these kinds here. Each returns the same plan as a picked feature: the ops that add one
named feature method and its parameters, a summary, and what was picked (read in the kernel, op model_pick):

    sweep            sketch (the profile) along path (a sketch) or path_picks (points on a chain of the body's edges);
                     twist (degrees; a parameter), cut / new_body
    loft             sections: [sketch, sketch, ...] (2 or more, each on its own plane), ruled; cut / new_body
    rib              sketch (an open line), thickness (a parameter), direction parallel | normal, flip
    mirror           plane, of (feature ids; none: the whole body)
    draft            picks on the faces to tilt, angle (a parameter), neutral (a plane), flip
    move_face        picks on the faces to push or pull, distance (a parameter; negative pushes in)
    thicken          one pick on a face, or sketch; thickness (a parameter), both, new_body
    boolean          op combine | subtract | intersect, target and tools: points inside the bodies (or picks: the
                     first is the target)
    split            plane, keep both | above | below
    variable_fillet  picks near edges, r_start and r_end (parameters); the end that gets r_start is the end of the
                     first picked edge nearest `start` (default: that edge's first end at the pick)
    datum_plane      base XY | XZ | YZ or one pick on a flat face, offset and angle (parameters), about x | y; or
                     through: three points
    datum_axis       through: two points; base X | Y | Z with origin; one pick on a straight edge; or planes: two

A plane is "XY", "XZ" or "YZ" (with plane_offset), a datum plane feature's id ("datum_plane_1": its definition is
copied in, with a ref the tree reads), or {"at": [x, y, z]} on a flat face.

Nothing here imports the kernel.
"""
from __future__ import annotations

import ast

from . import featureprog

KINDS = ("sweep", "loft", "rib", "mirror", "draft", "move_face", "thicken", "boolean", "split", "variable_fillet",
         "datum_plane", "datum_axis")
ROLES = {"draft": "finish", "variable_fillet": "finish", "datum_plane": "structure", "datum_axis": "structure"}
# the options of a sketch feature's end conditions, and of these kinds (form/modelling_api.py and the MCP tool)
END_OPTIONS = ("end", "to", "to_at", "offset", "reverse", "draft", "end2", "depth2", "to2", "to2_at", "offset2",
               "draft2", "thin", "thin_mode", "thin2", "new_body", "angle2", "mid")
OPTIONS = ("path", "path_picks", "sections", "twist", "ruled", "cut", "new_body", "direction", "flip", "plane",
           "plane_offset", "neutral", "distance", "both", "op", "target", "tools", "keep", "r_start", "r_end", "start",
           "base", "about", "through", "planes", "edge_at", "frenet")


def _m():
    from . import modelling
    return modelling


def _err(msg, hint="", **kw):
    return _m()._err(msg, hint, **kw)


def _q(s):
    return _m()._q(s)


def _lit(x):
    from . import handsketch
    return handsketch._py(x)


def _pt(x, what):
    try:
        p = [float(t) for t in x]
        assert len(p) == 3
        return p
    except (TypeError, ValueError, AssertionError):
        raise _err(f"{what} is not a point.", "A point is [x, y, z] in design millimetres.")


def _pick(st, p, c, kind, picks, opts=None):
    vals = st.rev(p)["values"]
    return st._k("model_pick", key=st.geometry_key(p, c["rid"], vals), recipe_id=c["rid"], values=vals, kind=kind,
                 picks=[{"at": _pt(pk.get("at") if isinstance(pk, dict) else pk, "A pick")} for pk in picks],
                 opts=opts or {}, p=p)


def _face_q(st, p, c, at, flat=True):
    got = _pick(st, p, c, "hole" if flat else "shell", [{"at": at}])
    return got["face"]["query"]


def datum_spec(source: str, fid: str) -> dict:
    """The definition a datum plane or axis feature holds (`spec = {...}` in its method)."""
    tree = ast.parse(featureprog.strip_partial(source))
    c = featureprog._feature_class(tree)
    fn = next((n for n in (c.body if c else []) if isinstance(n, ast.FunctionDef) and n.name == fid), None)
    if fn is None:
        raise _err(f"No feature “{fid}” in this design.")
    for x in ast.walk(fn):
        if isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "spec" for t in x.targets):
            return ast.literal_eval(x.value)
    raise _err(f"{fid} is not a datum plane or axis.", "A datum feature holds `spec = {...}` in its method.")


def plane_opt(st, p, c, val, offset=None) -> dict:
    """A plane option as the literal the kernel resolves (see the module text)."""
    if isinstance(val, dict) and "at" in val:
        return {"face": _face_q(st, p, c, val["at"])}
    if isinstance(val, str) and val.upper() in ("XY", "XZ", "YZ"):
        return {"datum": val.upper(), "offset": float(offset or 0)}
    if isinstance(val, str) and val in featureprog.feature_ids(c["source"]):
        spec = datum_spec(c["source"], val)
        if "dir" in spec or "edge" in spec or ("base" in spec and str(spec["base"]).upper() in ("X", "Y", "Z")):
            raise _err(f"{val} is an axis, not a plane.")
        return {"ref": val, **spec}
    raise _err(f"Unknown plane {val!r}.", "XY, XZ or YZ (with plane_offset), a datum plane's id, or {\"at\": [x, y, z]} "
               "on a flat face.")


def expand_sketch_plane(c, data: dict) -> dict:
    """A sketch whose plane is {"ref": "datum_plane_1"} gets the datum plane's definition copied in."""
    pl = (data or {}).get("plane") or {}
    if isinstance(pl, dict) and pl.get("ref") and not any(k in pl for k in ("base", "through")):
        spec = datum_spec(c["source"], pl["ref"])
        return {**data, "plane": {"ref": pl["ref"], **spec}}
    return data


def _sketch(c, data, what, closed=True):
    from . import handsketch
    if not isinstance(data, dict):
        raise _err(f"{what} is needed.", "A sketch: {plane, points, entities, constraints} (get_sketch shows the form).")
    d = handsketch.check(expand_sketch_plane(c, data))
    sol = handsketch.solve(d)
    if not sol["ok"]:
        raise _err(f"{what} does not solve: {sol['error']}", sol.get("hint") or "")
    if closed is None:
        return d
    if closed and not sol["closed"]:
        raise _err(f"{what} has no closed profile.", "Join its lines end to end into a closed loop (or draw a circle).")
    if not closed and sol["closed"]:
        raise _err(f"{what} is closed; it should be an open line.", "Draw an open line or chain.")
    return d


def _solids_ops(st, p, c, more: int) -> list:
    """The op that raises the class's `solids` declaration so a feature may leave `more` extra bodies."""
    import re
    head = st.rev(p)
    log = head.get("build_log") or []
    now = int(log[-1].get("solids") or 1) if log else 1
    src = c["source"]
    m = re.search(r"^(\s+)solids\s*=\s*(\d+)\s*$", src, re.M)
    want = now + more
    if m:
        if int(m.group(2)) >= want:
            return []
        return [{"op": "replace", "find": m.group(0), "with": f"{m.group(1)}solids = {want}"}]
    m = re.search(r"^(\s+)params\s*=\s*\[", src, re.M)
    if not m or len(re.findall(r"^\s+params\s*=\s*\[", src, re.M)) != 1:
        raise _err("This design keeps one body; it cannot say it has more here.",
                   "Add `solids = 2` (the number of bodies) to the design class, then try again.")
    return [{"op": "replace", "find": m.group(0), "with": f"{m.group(1)}solids = {want}\n{m.group(0)}"}]


def _num(o, k, lo, hi, what, default=None):
    return _m()._num(o, k, lo, hi, what, default)


def _param(*a, **k):
    return _m()._param(*a, **k)


def _code(fid, label, role, lines: list, call: str) -> str:
    body = "".join(f"    {ln}\n" for ln in lines)
    return (f"@feature({_q(label)}, role={_q(role)})\ndef {fid}(self, v, body):\n    from form import handmore\n"
            f"{body}    return {call}\n")


def _sk_lit(d, name):
    from . import handsketch
    return f"{name} = {handsketch.literal(d, '        ')}"


def plan(st, p, c, kind, fid, n, picks, o) -> dict:
    from . import handsketch
    label = o.get("label") or f"{kind.replace('_', ' ').capitalize()} {n}"
    role = ROLES.get(kind, "structure")
    params, lines, extra_ops, picked = [], [], [], None
    mode = "cut" if o.get("cut") else "new" if o.get("new_body") else "add"
    if mode == "new":
        extra_ops += _solids_ops(st, p, c, 1)
    if kind == "sweep":
        prof = _sketch(c, o.get("sketch"), "The profile sketch")
        if o.get("path_picks"):
            picked = _pick(st, p, c, "fillet", o["path_picks"])
            path = {"edges": [e["query"] for e in picked["edges"]]}
            lines.append(f"path = {_lit(path)}")
        else:
            path = _sketch(c, o.get("path"), "The path sketch", closed=None)
            lines.append(_sk_lit(path, "path"))
            params += handsketch.params(path, fid + "_path")
        params += handsketch.params(prof, fid)
        tw = _num(o, "twist", -3600, 3600, "The twist", 0.0)
        params.append(_param(f"{fid}_twist", f"{label} twist", tw, min(tw, -360), max(tw, 360), fid,
                             "degrees the profile turns from the path's start to its end", step=1, unit="°"))
        lines.insert(0, _sk_lit(prof, "sketch"))
        call = (f"handmore.sweep(body, self._form_trail, sketch, path, v, {_q(fid)}, {_q(mode)}, v[{_q(fid + '_twist')}]"
                + (", frenet=True" if o.get("frenet") else "") + ")")
        summary = f"{label}: the profile swept along {'the picked edges' if o.get('path_picks') else 'the path'}" + \
            (f", turning {tw:g}°" if tw else "")
    elif kind == "loft":
        secs = o.get("sections")
        if not isinstance(secs, list) or len(secs) < 2:
            raise _err("A loft needs two or more section sketches.", "sections: [sketch, sketch, ...]")
        ds = [_sketch(c, s, f"Section {i}") for i, s in enumerate(secs, 1)]
        for i, d in enumerate(ds, 1):
            params += handsketch.params(d, f"{fid}_s{i}")
        lit = ",\n        ".join(handsketch.literal(d, "        ") for d in ds)
        lines.append(f"sections = [\n        {lit}]")
        call = (f"handmore.loft(body, self._form_trail, sections, v, {_q(fid)}, {_q(mode)}"
                + (", ruled=True" if o.get("ruled") else "") + ")")
        summary = f"{label}: {'ruled' if o.get('ruled') else 'smooth'} through {len(ds)} sections"
    elif kind == "rib":
        d = _sketch(c, o.get("sketch"), "The rib's line", closed=False)
        t = _num(o, "thickness", 0.1, 200, "The rib thickness", None)
        direction = o.get("direction") or "parallel"
        if direction not in ("parallel", "normal"):
            raise _err(f"Unknown rib direction “{direction}”.", "parallel or normal.")
        params += handsketch.params(d, fid)
        params.append(_param(f"{fid}_t", f"{label} thickness", t, max(0.1, t * 0.25), t * 5, fid, "rib thickness"))
        lines.append(_sk_lit(d, "sketch"))
        call = (f"handmore.rib(body, self._form_trail, sketch, v, v[{_q(fid + '_t')}], {_q(fid)}, {_q(direction)}"
                + (", flip=True" if o.get("flip") else "") + ")")
        summary = f"{label}: {t:g} mm, out to the faces it meets"
    elif kind == "mirror":
        pl = plane_opt(st, p, c, o.get("plane") or "YZ", o.get("plane_offset"))
        of = o.get("of")
        of = [of] if isinstance(of, str) and of else list(of or [])
        ids = featureprog.feature_ids(c["source"])
        for f in of:
            if f not in ids:
                raise _err(f"No feature “{f}” to mirror.", "of names features: " + ", ".join(ids) + ".")
        call = f"handmore.mirror(body, self._form_trail, {_lit(pl)}, {_lit(of or None)}, v, {_q(fid)})"
        summary = f"{label}: {'the whole body' if not of else ', '.join(of)} mirrored"
    elif kind == "draft":
        if not picks:
            raise _err("A draft needs the picked faces.", "Pick the side faces to tilt.")
        faces = [_face_q(st, p, c, pk.get("at") if isinstance(pk, dict) else pk, flat=False) for pk in picks]
        ang = _num(o, "angle", 0.01, 44.9, "The draft angle", None)
        pl = plane_opt(st, p, c, o.get("neutral") or o.get("plane") or "XY", o.get("plane_offset"))
        params.append(_param(f"{fid}_angle", f"{label} angle", ang, 0.1, 30, fid, "degrees against the pull direction",
                             step=0.1, unit="°"))
        call = (f"handmore.draft(body, self._form_trail, {_lit(faces)}, v[{_q(fid + '_angle')}], {_lit(pl)}, v, {_q(fid)}"
                + (", flip=True" if o.get("flip") else "") + ")")
        summary = f"{label}: {len(faces)} face{'s' if len(faces) != 1 else ''} at {ang:g}°"
    elif kind == "move_face":
        if not picks:
            raise _err("Pick the face to move.")
        faces = [_face_q(st, p, c, pk.get("at") if isinstance(pk, dict) else pk, flat=False) for pk in picks]
        dist = _num(o, "distance", -1000, 1000, "The distance", None)
        if abs(dist) < 1e-6:
            raise _err("The distance is 0.", "Give the distance (negative pushes the face in).")
        params.append(_param(f"{fid}_d", f"{label} distance", dist, min(dist * 3, -abs(dist)), max(dist * 3, abs(dist)),
                             fid, "along the face's normal (negative: into the part)"))
        call = f"handmore.move_face(body, self._form_trail, {_lit(faces)}, v[{_q(fid + '_d')}], {_q(fid)})"
        summary = f"{label}: {len(faces)} face{'s' if len(faces) != 1 else ''} moved {dist:g} mm"
    elif kind == "thicken":
        t = _num(o, "thickness", 0.01, 500, "The thickness", None)
        if picks:
            src = {"face": _face_q(st, p, c, picks[0].get("at") if isinstance(picks[0], dict) else picks[0], flat=False)}
            lines.append(f"surface = {_lit(src)}")
        else:
            d = _sketch(c, o.get("sketch"), "The surface (a pick on a face, or a sketch)")
            params += handsketch.params(d, fid)
            lines.append(_sk_lit(d, "surface"))
        params.append(_param(f"{fid}_t", f"{label} thickness", t, max(0.01, t * 0.25), t * 5, fid,
                             "along the surface's normal" + (", half each side" if o.get("both") else "")))
        call = (f"handmore.thicken(body, self._form_trail, surface, v[{_q(fid + '_t')}], v, {_q(fid)}"
                + (", both=True" if o.get("both") else "") + (", new=True" if mode == "new" else "") + ")")
        summary = f"{label}: {t:g} mm" + (", a new body" if mode == "new" else "")
    elif kind == "boolean":
        op = o.get("op") or "combine"
        if op not in ("combine", "subtract", "intersect"):
            raise _err(f"Unknown boolean “{op}”.", "combine, subtract or intersect.")
        pts = [(pk.get("at") if isinstance(pk, dict) else pk) for pk in picks or []]
        target = o.get("target") or (pts[0] if pts else None)
        tools = o.get("tools") or pts[1:]
        if target is None or not tools:
            raise _err("A boolean needs the target body and at least one tool body.",
                       "target: a point inside it; tools: points inside the others (or picks, the target first).")
        target = [round(x, 4) for x in _pt(target, "The target")]
        tools = [[round(x, 4) for x in _pt(t, f"Tool {i}")] for i, t in enumerate(tools, 1)]
        call = f"handmore.boolean(body, self._form_trail, {_q(op)}, {_lit(target)}, {_lit(tools)}, {_q(fid)})"
        label = o.get("label") or f"{op.capitalize()} {n}"
        summary = f"{label}: {op} of {len(tools) + 1} bodies"
    elif kind == "split":
        keep = o.get("keep") or "both"
        if keep not in ("both", "above", "below"):
            raise _err(f"Unknown keep “{keep}”.", "both, above or below.")
        if keep == "both":
            extra_ops += _solids_ops(st, p, c, 1)
        pl = plane_opt(st, p, c, o.get("plane") or "XY", o.get("plane_offset"))
        call = f"handmore.split(body, self._form_trail, {_lit(pl)}, v, {_q(keep)}, {_q(fid)})"
        summary = f"{label}: split, " + ("both sides kept as bodies" if keep == "both" else f"the side {keep} kept")
    elif kind == "variable_fillet":
        picked = _pick(st, p, c, "fillet", picks or [])
        r0 = _num(o, "r_start", 0.05, 200, "The start radius", None)
        r1 = _num(o, "r_end", 0.05, 200, "The end radius", None)
        es = picked["edges"]
        starts = [e["ends"][0] for e in es]
        if o.get("start") is not None:
            s = _pt(o["start"], "The start")
            import math
            starts = [min(e["ends"], key=lambda q: math.dist(q, s)) for e in es]
        hi = max(r0, r1) * 4
        params.append(_param(f"{fid}_r0", f"{label} start radius", r0, 0.05, hi, fid, "at the start end of each edge"))
        params.append(_param(f"{fid}_r1", f"{label} end radius", r1, 0.05, hi, fid, "at the other end"))
        q = ",\n            ".join(_m()._lit(e["query"]) for e in es)
        call = (f"handmore.variable_fillet(body, self._form_trail, [\n            {q}], v[{_q(fid + '_r0')}], "
                f"v[{_q(fid + '_r1')}], {_lit(starts)}, {_q(fid)})")
        summary = f"{label}: {len(es)} edge{'s' if len(es) != 1 else ''}, r{r0:g} to r{r1:g} mm"
    elif kind == "datum_plane":
        if o.get("through"):
            pts = [[round(x, 4) for x in _pt(t, "A point")] for t in o["through"]]
            if len(pts) != 3:
                raise _err("A plane through points needs three points.")
            spec = {"through": pts}
            summary = f"{label}: through three points"
        else:
            if picks:
                base = {"face": _face_q(st, p, c, picks[0].get("at") if isinstance(picks[0], dict) else picks[0])}
            else:
                base = str(o.get("base") or "XY").upper()
                if base not in ("XY", "XZ", "YZ"):
                    raise _err(f"Unknown base plane “{base}”.", "XY, XZ or YZ, or a pick on a flat face.")
            off = _num(o, "offset", -10000, 10000, "The offset", 0.0)
            ang = _num(o, "angle", -180, 180, "The angle", 0.0)
            about = o.get("about") or "x"
            if about not in ("x", "y"):
                raise _err("about is x or y: the base plane's axis the angle turns about.")
            spec = {"base": base, "offset": f"{fid}_offset", "angle": f"{fid}_angle", "about": about}
            params.append(_param(f"{fid}_offset", f"{label} offset", off, min(off, 0) - 100, max(off, 0) + 100, fid,
                                 "along the plane's normal"))
            params.append(_param(f"{fid}_angle", f"{label} angle", ang, -180, 180, fid,
                                 f"degrees about the base plane's {about} axis", step=0.5, unit="°"))
            summary = (f"{label}: {base if isinstance(base, str) else 'a face'}"
                       + (f", turned {ang:g}°" if ang else "") + (f", offset {off:g} mm" if off else ""))
        lines.append(f"spec = {_lit(spec)}")
        call = f"handmore.datum_plane(body, self._form_trail, spec, v, {_q(fid)})"
    elif kind == "datum_axis":
        if o.get("through"):
            pts = [[round(x, 4) for x in _pt(t, "A point")] for t in o["through"]]
            if len(pts) != 2:
                raise _err("An axis through points needs two points.")
            spec = {"through": pts}
            summary = f"{label}: through two points"
        elif picks or o.get("edge_at"):
            at = o.get("edge_at") or (picks[0].get("at") if isinstance(picks[0], dict) else picks[0])
            picked = _pick(st, p, c, "fillet", [{"at": at}])
            spec = {"edge": picked["edges"][0]["query"]}
            summary = f"{label}: along a picked edge"
        elif o.get("planes"):
            if len(o["planes"]) != 2:
                raise _err("An axis where planes meet needs two planes.")
            spec = {"planes": [plane_opt(st, p, c, x) for x in o["planes"]]}
            summary = f"{label}: where two planes meet"
        else:
            base = str(o.get("base") or "Z").upper()
            if base not in ("X", "Y", "Z"):
                raise _err(f"Unknown base axis “{base}”.", "X, Y or Z.")
            spec = {"base": base, "origin": _pt(o.get("origin") or [0, 0, 0], "The origin")}
            summary = f"{label}: parallel to {base}"
        lines.append(f"spec = {_lit(spec)}")
        call = f"handmore.datum_axis(body, self._form_trail, spec, v, {_q(fid)})"
    else:
        raise _err(f"Unknown feature kind “{kind}”.")
    code = _code(fid, label, role, lines, call)
    ops = list(extra_ops) + [{"op": "insert", "param": prm} for prm in params]
    ops.append({"op": "insert", "feature": fid, "code": code, "label": label, "role": role,
                **({"after": o["after"]} if o.get("after") else {})})
    return {"feature": fid, "label": label, "kind": kind, "summary": summary, "ops": ops, "picked": picked,
            "params": params, "evidence": _m().EVIDENCE}


def axis_from_datum(source: str, fid: str, values: dict | None = None) -> tuple[list, list] | None:
    """(origin, direction) of a datum axis written by points or a base axis (read from the source, no kernel); None
    for an axis on an edge or where planes meet (the kernel resolves those)."""
    spec = datum_spec(source, fid)
    if "through" in spec:
        a, b = spec["through"]
        d = [y - x for x, y in zip(a, b)]
        return list(a), d
    if "base" in spec and str(spec["base"]).upper() in ("X", "Y", "Z"):
        d = [1.0 if k == str(spec["base"]).upper() else 0.0 for k in "XYZ"]
        return list(spec.get("origin") or [0, 0, 0]), d
    return None


# ---- end conditions of a sketch feature (extrude, cut, revolve) ----------------------------------------------------

def end_args(st, p, c, kind, fid, label, o) -> tuple[str, list, str]:
    """(the keyword arguments the feature's call gets, the parameters they read, a summary suffix)."""
    kw, params, said = [], [], []
    if kind == "revolve":
        end = o.get("end") or "angle"
        if end not in ("angle", "face"):
            raise _err(f"Unknown revolve end “{end}”.", "angle or face.")
        if end == "face":
            if not o.get("to_at") and not isinstance(o.get("to"), dict):
                raise _err("Up to face needs to_at: a point on the face.")
            q = _face_q(st, p, c, o["to_at"]) if o.get("to_at") else o["to"]     # a face already found (a redefine)
            kw.append(f"end=\"face\", to={_lit(q)}")
            said.append("up to a face")
        if o.get("angle2"):
            a2 = _num(o, "angle2", 0.1, 359.9, "The second angle", None)
            params.append(_param(f"{fid}_angle2", f"{label} angle, other way", a2, 0.1, 360, fid,
                                 "degrees turned the other way", step=1, unit="°"))
            kw.append(f"angle2=v[{_q(fid + '_angle2')}]")
            said.append(f"and {a2:g}° the other way")
        if o.get("mid"):
            kw.append("mid=True")
            said.append("mid-plane")
        if o.get("reverse"):
            kw.append("reverse=True")
            said.append("reversed")
        return ("".join(", " + k for k in kw), params, ", ".join(said))
    from .handsketch import END_CONDITIONS, THIN_MODES

    def side(n, end_k, depth_k, to_k, off_k, draft_k):
        e = o.get(end_k)
        if not e:
            return
        if e not in END_CONDITIONS:
            raise _err(f"Unknown end condition “{e}”.", ", ".join(END_CONDITIONS) + ".")
        suf = "" if n == 1 else "2"
        kw.append(f"{end_k}={_q(e)}")
        if n == 2 and e in ("blind", "mid"):
            d2 = _num(o, "depth2", 0.01, 5000, "The second depth", None)
            params.append(_param(f"{fid}_depth2", f"{label} depth, direction 2", d2, 0.01, max(d2 * 5, 50), fid,
                                 "the other way from the sketch"))
            kw.append(f"depth2=v[{_q(fid + '_depth2')}]")
        if e in ("face", "offset"):
            at = o.get(to_k + "_at") or o.get(to_k)
            if not at:
                raise _err(f"Up to face needs {to_k}_at: a point on the face.")
            q = at if isinstance(at, dict) and not o.get(to_k + "_at") else _face_q(st, p, c, at)  # found: a redefine
            kw.append(f"{to_k}={_lit(q)}")
        if e == "vertex":
            if not o.get(to_k):
                raise _err(f"Up to vertex needs {to_k}: the vertex [x, y, z].")
            kw.append(f"{to_k}={_lit([round(x, 4) for x in _pt(o[to_k], 'The vertex')])}")
        if e == "offset":
            off = _num(o, off_k, -1000, 1000, "The offset", 0.0)
            params.append(_param(f"{fid}_offset{suf}", f"{label} offset from face" + (" 2" if suf else ""), off,
                                 min(off, 0) - 50, max(off, 0) + 50, fid, "short of the face"))
            kw.append(f"{off_k}=v[{_q(fid + '_offset' + suf)}]")
        if o.get(draft_k):
            dr = _num(o, draft_k, -45, 45, "The draft angle", None)
            params.append(_param(f"{fid}_draft{suf}", f"{label} draft" + (" 2" if suf else ""), dr, -30, 30, fid,
                                 "degrees of taper (positive narrows)", step=0.1, unit="°"))
            kw.append(f"{draft_k}=v[{_q(fid + '_draft' + suf)}]")
        said.append({"blind": "blind", "through": "through all", "next": "up to next", "face": "up to a face",
                     "vertex": "up to a vertex", "offset": "offset from a face", "mid": "mid-plane"}[e]
                    + (" (direction 2)" if n == 2 else ""))
    side(1, "end", "depth", "to", "offset", "draft")
    if not o.get("end") and o.get("draft"):
        dr = _num(o, "draft", -45, 45, "The draft angle", None)
        params.append(_param(f"{fid}_draft", f"{label} draft", dr, -30, 30, fid, "degrees of taper (positive narrows)",
                             step=0.1, unit="°"))
        kw.append(f"draft=v[{_q(fid + '_draft')}]")
    side(2, "end2", "depth2", "to2", "offset2", "draft2")
    if o.get("reverse"):
        kw.append("reverse=True")
        said.append("reversed")
    if o.get("thin"):
        t = _num(o, "thin", 0.01, 500, "The wall thickness", None)
        mode = o.get("thin_mode") or "one"
        if mode not in THIN_MODES:
            raise _err(f"Unknown thin mode “{mode}”.", "one, mid or two.")
        params.append(_param(f"{fid}_thin", f"{label} wall", t, max(0.01, t * 0.25), t * 5, fid, "thin feature wall"))
        kw.append(f"thin=v[{_q(fid + '_thin')}], thin_mode={_q(mode)}")
        if mode == "two":
            t2 = _num(o, "thin2", 0.01, 500, "The inside wall thickness", None)
            params.append(_param(f"{fid}_thin2", f"{label} wall inside", t2, max(0.01, t2 * 0.25), t2 * 5, fid,
                                 "thin feature wall, inside"))
            kw.append(f"thin2=v[{_q(fid + '_thin2')}]")
        said.append(f"thin {t:g} mm ({mode})")
    return ("".join(", " + k for k in kw), params, ", ".join(said))
