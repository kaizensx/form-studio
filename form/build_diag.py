"""Build diagnosis: what went wrong when a design did not build, in plain words, with the feature, the line and the
repairs to try, instead of the kernel's own text ("BRep_API: command not done").

    from form import build_diag
    d = build_diag.diagnose(exc, recipe)        # in the kernel worker, inside the except of recipe.build()
    d = {"summary": "The fillet on line 27 could not be built: 2 mm is wider than the faces it joins allow.",
         "operation": "fillet", "feature": "rim", "feature_label": "Rounded rim", "line": 27,
         "code": "body = body.fillet(2.0, body.edges())", "cause": "...", "fixes": ["...", ...],
         "safe": "craft.safe_fillet(body, edges, 2.0)", "operands": [{"name": "body", "valid": True, ...}],
         "kernel_text": "Standard_Failure: BRep_API: command not done", "evidence": "computed"}

The cause comes from three things read together: the exception (type and text), the line of the design's source it
came from (which operation was running: a fillet, a loft, a boolean...), and the shapes that line used, read from the
running frame (are they valid solids, how many, do their boxes overlap or only touch, the shortest edge a fillet has
to fit on). It is a heuristic: the cause is the most likely one, the fixes are ranked, and the kernel's text is kept
for reference. Imports build123d only inside the worker (the shapes it inspects are already built there).
"""
from __future__ import annotations

import os
import re
import traceback

# operation -> (code patterns, kernel-text patterns)
_OPS = [
    ("fillet", (r"\.fillet\(|\bfillet\(|safe_fillet|variable_fillet", ), (r"fillet",)),
    ("chamfer", (r"\.chamfer\(|\bchamfer\(", ), (r"chamfer",)),
    ("loft", (r"\bloft\(|loft_sections|checked_body|section_body|section_shell", ), (r"\bloft",)),
    ("sweep", (r"\bsweep\(|sweep_spline", ), (r"sweep",)),
    ("shell", (r"\boffset\(|\.shell\(|craft\.shell|inset_body|thicken", ), (r"offset|shell|thicken",)),
    ("revolve", (r"\brevolve\(|revolve_profile", ), (r"revol",)),
    ("extrude", (r"\bextrude\(", ), (r"extru|prism",)),
    ("fuse", (r"(?<![-+*/=<>!])\s\+\s|\+=|\.fuse\(|\bfuse\(|safe_union|\bunion", ), (r"fusion|fuse|union",)),
    ("cut", (r"(?<![-+*/=<>!(,\[])\s-\s(?![\d.(])|-=|\.cut\(|\bcut\(|safe_cut", ), (r"\bcut",)),
    ("intersect", (r"\s&\s|\.intersect\(|\bcommon\(", ), (r"intersect|common",)),
    ("face", (r"make_face|Face\(|spline_profile|polygon_profile|Polyline|Spline\(", ), (r"face|wire",)),
]

_SAFE = {
    "fillet": "craft.safe_fillet(shape, edges, radius)  (tries 75 %, 50 %, 25 %, then edge by edge, and notes it)",
    "chamfer": "craft.safe_chamfer(shape, edges, length)  (smaller lengths, then edge by edge, noted)",
    "loft": "craft.safe_loft(sections)  (re-seams and resamples the sections, then ruled, then section by section)",
    "sweep": "craft.sweep_spline(profile, path_points)  (Frenet and right-corner fallbacks)",
    "shell": "craft.safe_shell(solid, thickness, openings)  (arc, intersection, then thinner walls, noted)",
    "fuse": "craft.safe_union(a, b, ...)  (fuzzy booleans, shape repair, a 0.05 mm overlap where parts only touch)",
    "cut": "craft.safe_cut(body, tool)  (fuzzy booleans, shape repair, a nudged tool)",
    "intersect": "craft.safe_intersect(a, b)",
    "revolve": "craft.revolve_profile(points)  (closes the profile along the axis)",
}

_CAUSES = {
    "fillet": ("the radius is larger than the faces next to the edge allow (a fillet cannot be wider than the "
               "shortest face it joins), or one edge in the set is a seam, a tangent edge or ends at a corner the "
               "fillet cannot close",
               ["Make the radius smaller than half the shortest face width next to the edges.",
                "Fillet fewer edges at once: select them with filter_by / group_by instead of all edges.",
                "Fillet before the cuts and holes that make short edges, not after.",
                "Use craft.safe_fillet, which reduces the radius and goes edge by edge instead of failing."]),
    "chamfer": ("the length is larger than a face next to the edge, or the edges meet at a corner the chamfer "
                "cannot close",
                ["Use a shorter chamfer.", "Chamfer fewer edges at once.",
                 "Use craft.safe_chamfer, which reduces the length and goes edge by edge."]),
    "loft": ("the sections cannot be joined by one smooth skin: they have different point counts or start points "
             "(the skin twists), a section crosses the next one, two sections are in the same plane, or a section is "
             "not a closed planar face",
             ["Give every section the same number of points, starting at the same angle (craft.superellipse(..., "
              "seam=0) or craft.section_at keep this).",
              "Keep sections in order along the loft and apart from each other by at least 0.5 mm.",
              "Loft fewer sections at once, or a ruled loft between neighbours.",
              "Use craft.safe_loft, which re-seams and resamples the sections, then tries ruled and pairwise lofts."]),
    "sweep": ("the path bends more sharply than the profile is wide, or the profile is not perpendicular to the "
              "path at its start",
              ["Make the path's tightest bend larger than the profile's half-width.",
               "Place the profile at the start of the path, normal to it (craft.plane_on_path).",
               "Use craft.sweep_spline, which tries Frenet and right-corner sweeps."]),
    "shell": ("the wall is thicker than the smallest inside radius of the body, so the offset surface folds over "
              "itself",
              ["Use a thinner wall, or round the body's tight corners first.",
               "Hollow a lofted body by lofting inset sections (craft.section_shell / craft.inset_body) instead of "
               "offsetting the solid.", "Use craft.safe_shell, which tries an intersection offset and thinner walls."]),
    "fuse": ("the parts do not overlap: they only touch along a face or an edge, or one is not a valid solid, so "
             "OCCT cannot merge them into one body",
             ["Sink the added part into the body by 0.2 mm or more instead of letting faces just touch.",
              "Check each part is a valid solid before fusing (shape.is_valid); fix the one that is not first.",
              "Use craft.safe_union, which tries fuzzy booleans, repairs the shapes, and closes a touching gap."]),
    "cut": ("the cutting tool grazes a face of the body (coincident or tangent faces), cuts along a loft seam, or "
            "one of the shapes is not a valid solid",
            ["Make the tool cross the face clearly (0.2 mm past it), not end exactly on it.",
             "Move the cut off a loft seam or a tangent face.",
             "Use craft.safe_cut, which tries fuzzy booleans, repairs the shapes and nudges the tool."]),
    "intersect": ("the shapes do not overlap, or one is not a valid solid",
                  ["Check the shapes overlap where you expect (print their bounding boxes).",
                   "Use craft.safe_intersect."]),
    "revolve": ("the profile crosses the axis or itself, or it is not closed",
                ["Keep the whole profile on one side of the axis (r >= 0).",
                 "Use craft.revolve_profile, which closes the profile along the axis."]),
    "extrude": ("the profile is not a closed face (open wire, self-crossing outline), or the distance is zero",
                ["Close the outline (make_face of a closed wire), and check it does not cross itself.",
                 "Give extrude a non-zero amount."]),
    "face": ("the outline is open, crosses itself, or its points are not in one plane, so no face can be made "
             "from it", ["Close the outline: the last point must meet the first.",
                         "Remove points that double back on the outline (a self-crossing outline has no inside).",
                         "Draw it on one plane (Plane.XY, Plane.XZ...)."]),
}

_PY = {
    "NameError": ("the code uses a name that is not defined (a typo, or an import that is missing)",
                  ["Define or import the name; craft helpers are craft.<name> after `from form import craft`."]),
    "AttributeError": ("the code asks an object for something it does not have (a wrong method name, or a result "
                       "that is a different type than expected, such as a ShapeList instead of a Solid)",
                       ["Check the method name against build123d's API, or pick one item: shape.solids()[0]."]),
    "TypeError": ("a function got the wrong kind or number of arguments",
                  ["Check the call's arguments against the function's signature (design_guide lists the craft ones)."]),
    "ImportError": ("an import failed: the module or name does not exist here",
                    ["Use build123d and form.craft only (form.parts for hardware); check the name."]),
    "ModuleNotFoundError": ("an import failed: the module is not installed in Form Studio",
                            ["Use build123d, numpy and form.craft only."]),
    "KeyError": ("the code reads a key that is not there, usually a parameter name in v[...] that params does "
                 "not define", ["Make every v['name'] match a Param key exactly."]),
    "IndexError": ("the code picks an item that does not exist: a selection (faces, edges, solids) came back "
                   "shorter than expected, often empty because an earlier operation failed quietly",
                   ["Check the selection is not empty before indexing it, and that the shape before it is a valid "
                    "solid.", "Select by position or type (sort_by, filter_by) rather than by a fixed index."]),
    "ZeroDivisionError": ("a parameter combination divides by zero", ["Guard the division, or narrow the range."]),
    "ValueError": ("a value the code computed or passed is out of range for the operation", []),
}

_KERNEL = [   # kernel text -> plain words (added to the cause)
    (r"BRep_API: command not done", "the kernel's operation gave up without a result"),
    (r"StdFail_NotDone", "the kernel's operation gave up without a result"),
    (r"Standard_ConstructionError|gp_VectorWithNullMagnitude", "a zero-length direction or a degenerate shape "
     "(two points in the same place, a zero radius)"),
    (r"Standard_DomainError", "a value outside what the operation accepts"),
    (r"Standard_NullObject|null shape|Null TopoDS_Shape|IsNull", "an operation returned nothing and the next one "
     "used that empty result"),
    (r"Failed creating a fillet with radius of ([\d.]+)", "OCCT could not fit a {0} mm fillet"),
    (r"Failed creating a chamfer", "OCCT could not fit the chamfer"),
    (r"No pending wires|Unable to build face|Can't create face", "no face could be made from the outline"),
    (r"not a valid solid|valid=False", "a boolean left a broken solid"),
]


def _design_frames(exc: BaseException, recipe) -> list:
    """Traceback frames that run the design's own source file (not build123d, OCCT or form)."""
    srcs = set()
    for c in type(recipe).__mro__:
        if c.__module__ in ("builtins",) or c.__module__.startswith("form."):
            continue
        for f in vars(c).values():
            if hasattr(f, "__code__"):
                srcs.add(os.path.realpath(f.__code__.co_filename))
    out = []
    tb = exc.__traceback__
    while tb is not None:
        if os.path.realpath(tb.tb_frame.f_code.co_filename) in srcs:
            out.append(tb)
        tb = tb.tb_next
    return out


def _source_line(tb) -> str:
    try:
        import linecache
        return linecache.getline(tb.tb_frame.f_code.co_filename, tb.tb_lineno).strip()
    except Exception:
        return ""


def _is_shape(x) -> bool:
    return hasattr(x, "wrapped") and hasattr(x, "bounding_box") and hasattr(x, "is_valid")


def _shape_info(name: str, s) -> dict:
    out = {"name": name}
    try:
        out["type"] = type(s).__name__
        bb = s.bounding_box()
        out["bbox"] = [[round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
                       [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)]]
    except Exception:
        out["bbox"] = None
    for k, fn in (("valid", lambda: bool(s.is_valid)), ("solids", lambda: len(s.solids())),
                  ("faces", lambda: len(s.faces())), ("volume_mm3", lambda: round(float(s.volume), 3))):
        try:
            out[k] = fn()
        except Exception:
            pass
    try:                                                  # the shortest edge: what a fillet or chamfer must fit on
        es = s.edges()
        if 0 < len(es) <= 4000:
            out["shortest_edge_mm"] = round(min(e.length for e in es), 3)
    except Exception:
        pass
    if out.get("valid") is False:
        out["faults"] = _faults(s)
    return out


def _faults(s) -> list:
    """What BRepCheck finds wrong with a shape, by kind (a few names), for a shape that is not valid."""
    try:
        from OCP.BRepCheck import BRepCheck_Analyzer, BRepCheck_ListOfStatus  # noqa: F401
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_WIRE
        from OCP.TopExp import TopExp_Explorer
        an = BRepCheck_Analyzer(s.wrapped)
        names = {TopAbs_FACE: "face", TopAbs_EDGE: "edge", TopAbs_WIRE: "wire", TopAbs_SHELL: "shell"}
        bad = {}
        for kind, label in names.items():
            ex = TopExp_Explorer(s.wrapped, kind)
            n = 0
            while ex.More():
                try:
                    if not an.IsValid(ex.Current()):
                        n += 1
                except Exception:
                    pass
                ex.Next()
            if n:
                bad[label] = n
        return [f"{n} invalid {k}{'s' if n > 1 else ''}" for k, n in bad.items()]
    except Exception:
        return []


def _boxes_relation(a: dict, b: dict) -> dict | None:
    """How two bounding boxes sit: overlapping by how much, or apart by how much (mm)."""
    try:
        (alo, ahi), (blo, bhi) = a["bbox"], b["bbox"]
    except (KeyError, TypeError):
        return None
    gaps = [max(blo[i] - ahi[i], alo[i] - bhi[i]) for i in range(3)]
    g = max(gaps)
    if g > 1e-6:
        return {"apart_mm": round(g, 3), "note": f"{a['name']} and {b['name']} do not reach each other: "
                                                  f"{g:.3g} mm apart"}
    over = min(-x for x in gaps)
    if over < 0.05:
        return {"overlap_mm": round(over, 3), "note": f"{a['name']} and {b['name']} only touch "
                                                       f"({over:.3g} mm of overlap): faces that just touch are the "
                                                       "classic cause of a failed boolean"}
    return {"overlap_mm": round(over, 3)}


def _operands(tb, code: str) -> list[dict]:
    """The shapes named on the failing line, read from the running frame."""
    out = []
    try:
        loc = tb.tb_frame.f_locals
    except Exception:
        return out
    names = []
    for m in re.finditer(r"\b([A-Za-z_]\w*)\b", code):
        n = m.group(1)
        if n not in names:
            names.append(n)
    for n in names:
        v = loc.get(n)
        if _is_shape(v):
            out.append(_shape_info(n, v))
        elif isinstance(v, (list, tuple)) and v and len(v) <= 64 and all(_is_shape(x) for x in v):
            infos = [_shape_info(f"{n}[{i}]", x) for i, x in enumerate(v[:8])]
            out.extend(infos)
        if len(out) >= 6:
            break
    return out


def _loft_sections(tb, code: str) -> str:
    """What is wrong with a loft's sections, read from the frame: edge counts that differ, sections in one plane."""
    try:
        loc = tb.tb_frame.f_locals
    except Exception:
        return ""
    def face(x):
        if hasattr(x, "outer_wire"):
            return x
        try:
            fs = x.faces()
            return fs[0] if len(fs) == 1 else None
        except Exception:
            return None
    secs = None
    names = list(dict.fromkeys(re.findall(r"\b([A-Za-z_]\w*)\b", code)))
    for n in names:
        v = loc.get(n)
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            fs = [face(x) for x in v]
            if all(f is not None for f in fs):
                secs = fs
                break
    if secs is None:
        fs = [face(loc[n]) for n in names if _is_shape(loc.get(n))]
        fs = [f for f in fs if f is not None]
        secs = fs if len(fs) >= 2 else None
    if not secs:
        return ""
    try:
        counts = [len(f.outer_wire().edges()) for f in secs]
        cs = [f.center() for f in secs]
        same = [i for i in range(len(cs) - 1) if (cs[i + 1] - cs[i]).length < 0.05]
        out = []
        if len(set(counts)) > 1:
            out.append("the sections have " + ", ".join(str(c) for c in counts) + " edges (different counts make the "
                       "skin twist: resample them to one count, craft.reseam)")
        if same:
            out.append(f"sections {same[0] + 1} and {same[0] + 2} are in the same place")
        holes = [len(f.inner_wires()) for f in secs]
        if len(set(holes)) > 1:
            out.append("the sections have different numbers of holes (" + ", ".join(map(str, holes)) + ")")
        return "; ".join(out)
    except Exception:
        return ""


def _split_bodies(tb) -> dict | None:
    """A shape in the failing frame that holds several separate solids (a fuse that did not join): how many, and how
    far apart the nearest two are. Read when the failing line itself names no shape (the design raised on a count)."""
    try:
        loc = tb.tb_frame.f_locals
    except Exception:
        return None
    for n, v in loc.items():
        if not _is_shape(v):
            continue
        try:
            ss = v.solids()
            if not 1 < len(ss) <= 12:
                continue
            gaps = []
            for i in range(len(ss)):
                for j in range(i + 1, len(ss)):
                    try:
                        gaps.append(float(ss[i].distance_to(ss[j])))
                    except Exception:
                        pass
            g = min(gaps) if gaps else 0.0
            near = sorted(gaps)[:1]
            how = (f"the nearest two are {g:.3g} mm apart" if g > 1e-6 else "they touch without joining (faces or edges "
                   "that only meet)")
            return {"name": n, "solids": len(ss), "gap_mm": round(g, 4), "gaps": [round(x, 4) for x in near],
                    "note": f"{n} is {len(ss)} separate solids, not one: {how}"}
        except Exception:
            continue
    return None


def _numbers_on(code: str, tb) -> list[float]:
    """Numbers the failing line passes (literals and simple names), e.g. a fillet radius."""
    vals = []
    try:
        loc = tb.tb_frame.f_locals
    except Exception:
        loc = {}
    m = re.search(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*$", code)
    args = m.group(1) if m else code
    for tok in re.split(r",", args):
        tok = tok.strip().split("=")[-1].strip()
        try:
            vals.append(float(tok))
            continue
        except ValueError:
            pass
        v = loc.get(tok)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals.append(float(v))
        elif "[" in tok:
            base = tok.split("[")[0]
            key = re.findall(r"\[['\"](\w+)['\"]\]", tok)
            d = loc.get(base)
            if isinstance(d, dict) and key and isinstance(d.get(key[0]), (int, float)):
                vals.append(float(d[key[0]]))
    return vals


def _stage_of_line(tb, ids: list[str]) -> str | None:
    """The feature whose Stage(...) uses the variable the failing line assigns, read from the source below it."""
    import linecache
    f, n = tb.tb_frame.f_code.co_filename, tb.tb_lineno
    m = re.match(r"\s*([A-Za-z_]\w*)\s*(?:[-+*]?=)(?!=)", linecache.getline(f, n))
    if not m:
        return None
    var = re.compile(r"\b" + re.escape(m.group(1)) + r"\b")
    for k in range(n + 1, n + 120):
        line = linecache.getline(f, k)
        if not line:
            break
        for st in re.finditer(r"Stage\(\s*[\"'](\w+)[\"']\s*,([^()]*(?:\([^()]*\)[^()]*)*)\)", line):
            if st.group(1) in ids and var.search(st.group(2)):
                return st.group(1)
    return None


def _failing_feature(exc: BaseException, recipe) -> tuple[str, str]:
    """The feature being built when it failed: the one after the last Stage the build appended (read from the
    build() frame), else the design's first feature that has no stage yet."""
    feats = [(f.id, f.label) for f in getattr(recipe, "features", []) or []]
    if not feats:
        return "", ""
    done = []
    tb = exc.__traceback__
    while tb is not None:
        try:
            for v in tb.tb_frame.f_locals.values():
                if isinstance(v, list) and v and all(type(x).__name__ == "Stage" for x in v):
                    done = [x.feature for x in v]
        except Exception:
            pass
        tb = tb.tb_next
    ids = [f for f, _ in feats]
    frames = _design_frames(exc, recipe)
    via = _stage_of_line(frames[-1], ids) if frames else None
    if via:                                          # the Stage the failing line's result goes into
        return next(f for f in feats if f[0] == via)
    if done and done[-1] in ids:
        i = ids.index(done[-1]) + 1
        if i < len(ids):
            return feats[i]
        return feats[-1]
    return feats[0] if not done else ("", "")


def classify(text: str, code: str = "") -> str:
    """The operation that failed: from the line of code first (it says what was running), then the error text."""
    for op, cpat, _t in _OPS:
        if any(re.search(p, code) for p in cpat):
            return op
    for op, _c, tpat in _OPS:
        if any(re.search(p, text, re.I) for p in tpat):
            return op
    return ""


def _kernel_words(text: str) -> str:
    for pat, words in _KERNEL:
        m = re.search(pat, text, re.I)
        if m:
            return words.format(*m.groups()) if m.groups() else words
    return ""


def diagnose(exc: BaseException, recipe=None) -> dict:
    """A structured diagnosis of an exception raised by recipe.build() (see the module docstring)."""
    etype = type(exc).__name__
    text = f"{etype}: {exc}".strip().rstrip(":")
    frames = _design_frames(exc, recipe) if recipe is not None else []
    tb = frames[-1] if frames else None
    code = _source_line(tb) if tb is not None else ""
    line = tb.tb_lineno if tb is not None else None
    ctx = exc.__cause__ or exc.__context__
    full = text + (f" {type(ctx).__name__}: {ctx}" if ctx is not None else "")
    if code.lstrip().startswith("raise"):          # the design raised on its own check: its words say what failed
        op = classify(full, "") or classify(full, re.sub(r"([\"']).*?\1", "", code))
    else:
        op = classify(full, code)
    feature, label = _failing_feature(exc, recipe) if recipe is not None else ("", "")
    if getattr(exc, "feature", ""):
        feature = exc.feature
        label = next((f.label for f in getattr(recipe, "features", []) if f.id == feature), label)
    operands = _operands(tb, code) if tb is not None else []
    rel = None
    if op in ("fuse", "cut", "intersect") and len(operands) >= 2:
        rel = _boxes_relation(operands[0], operands[1])
    kw = _kernel_words(full)
    py = etype in _PY and not (etype == "ValueError" and op)
    if py and etype != "ValueError":
        cause, fixes = _PY[etype]
        what = "the code"
    elif op:
        cause, fixes = _CAUSES.get(op, ("", []))
        what = f"the {op}"
    else:
        cause, fixes = _PY.get(etype, ("the kernel could not complete an operation", []))
        what = "this step"
    fixes = list(fixes)
    facts = []
    for o in operands:
        if o.get("valid") is False:
            facts.append(f"{o['name']} is not a valid solid" + (f" ({', '.join(o['faults'])})" if o.get("faults") else "")
                         + ": the step that made it is the real culprit")
        elif o.get("solids") == 0 and o.get("type") not in ("Face", "Wire", "Edge", "Sketch", "Vertex"):
            facts.append(f"{o['name']} holds no solid (an earlier boolean returned nothing)")
    if rel and rel.get("note"):
        facts.append(rel["note"])
    if op == "loft" and tb is not None:
        f = _loft_sections(tb, code)
        if f:
            facts.append(f)
    split = _split_bodies(tb) if (tb is not None and op in ("fuse", "cut", "")) else None
    if split:
        facts.append(split["note"])
        if split["gap_mm"] > 0:
            rel = rel or {}
            rel.setdefault("apart_mm", split["gap_mm"])
    nums =_numbers_on(code, tb) if (tb is not None and op in ("fillet", "chamfer")) else []
    if op in ("fillet", "chamfer") and nums:
        r = max(nums)
        short = min((o["shortest_edge_mm"] for o in operands if "shortest_edge_mm" in o), default=None)
        if short is not None and r >= short / 2:
            facts.append(f"the {op} size {r:g} mm is at least half the shortest edge on {operands[0]['name']} "
                         f"({short:g} mm)")
            fixes.insert(0, f"Use a {op} size under {short / 2:.2g} mm here, or {op} before the step that made the "
                            f"{short:g} mm edge.")
    if any("not a valid solid" in f for f in facts):
        fixes.insert(0, "Fix the step that made the invalid shape first (look one or two lines up); this line only "
                        "inherited it.")
    if rel and rel.get("apart_mm") and rel["apart_mm"] <= 0.05:
        fixes.insert(0, f"The gap is only {rel['apart_mm']:g} mm: overlap the parts by 0.2 mm, or fuse with "
                        "craft.safe_union, which closes a gap this small and notes it.")
    elif rel and rel.get("apart_mm"):
        fixes.insert(0, f"Move the parts together: they are {rel['apart_mm']:g} mm apart, so there is nothing to "
                        "join (or declare solids = N and an assembly() if they are separate parts).")
    elif rel and "overlap_mm" in rel and rel["overlap_mm"] < 0.05:
        fixes.insert(0, "Overlap the parts by 0.2 mm or more (or use craft.safe_union / craft.safe_cut).")
    where = f" on line {line}" if line else ""
    feat = f" ({label or feature})" if (label or feature) else ""
    reason = cause.split(",")[0] if cause else ""
    summary = (f"{what[0].upper() + what[1:]}{where}{feat} could not be built"
               + (f": {facts[0]}" if facts else (f": {reason}" if reason else "")) + ".")
    if py and etype != "ValueError":
        summary = f"The design's code failed{where}{feat}: {etype} ({str(exc)[:160]}). {cause[0].upper() + cause[1:]}."
    d = {"summary": summary, "operation": op or ("python" if py else ""), "feature": feature, "feature_label": label,
         "line": line, "code": code[:200], "cause": (cause + (f"; the kernel says {kw}" if kw else "")).strip("; "),
         "facts": facts, "fixes": _dedupe(fixes)[:5], "safe": _SAFE.get(op, ""), "operands": operands[:6],
         "kernel_text": text[:400], "evidence": "heuristic"}
    return d


def _dedupe(xs):
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def stage_counts(stages, want: int) -> dict:
    """A diagnosis for a result with the wrong number of solids: the stage where the count went wrong."""
    counts = []
    for s in stages:
        try:
            n, vol, valid = len(s.shape.solids()), float(s.shape.volume), bool(s.shape.is_valid)
        except Exception:
            n, vol, valid = 0, 0.0, False
        counts.append({"feature": s.feature, "solids": n, "volume_mm3": round(vol, 2), "valid": valid})
    empty = next((c for c in counts if c["solids"] == 0 or c["volume_mm3"] <= 1e-9), None)
    if empty:
        f = empty["feature"]
        return {"summary": f"The {f} step left no solid: a boolean failed and returned nothing.", "operation": "boolean",
                "feature": f, "stages": counts, "fixes": [
                    "Overlap the shapes by 0.2 mm instead of letting them touch.",
                    "Move the cut off a loft seam or a tangent face.",
                    "Use craft.safe_union / craft.safe_cut, which retry with fuzzy booleans and shape repair."],
                "safe": _SAFE["fuse"], "evidence": "computed"}
    changed = [counts[i]["feature"] for i in range(1, len(counts)) if counts[i]["solids"] != counts[i - 1]["solids"]]
    f = changed[-1] if changed else counts[0]["feature"]
    final = counts[-1]["solids"]
    more = final > want
    return {"summary": f"The result is {final} solids where the design declares {want}; the count last changed at "
                       f"the {f} step.", "operation": "solid count", "feature": f, "stages": counts,
            "fixes": (["A piece added at this step does not reach the body: sink it in by 0.2 mm (craft.safe_union "
                       "closes small gaps and says so).", "A cut split the body in two: make it shallower or move it.",
                       "If the pieces really are separate parts, declare solids = N and an assembly()."] if more else
                      ["Parts that should stay separate touch or overlap and fused: leave a 0.3 mm gap.",
                       "A part was not added: check the step's boolean returned it."]),
            "safe": _SAFE["fuse"] if more else "", "evidence": "computed"}


def text(d: dict) -> str:
    """A diagnosis as a few lines for an agent: summary, cause, fixes, and the repair helper."""
    lines = [d.get("summary", "")]
    if d.get("code"):
        lines.append(f"Line {d.get('line')}: {d['code']}")
    if d.get("cause"):
        lines.append("Likely cause: " + d["cause"] + ".")
    for f in d.get("facts", [])[1:]:
        lines.append("Also: " + f + ".")
    if d.get("fixes"):
        lines.append("Try: " + " | ".join(d["fixes"][:3]))
    if d.get("safe"):
        lines.append("Robust helper: " + d["safe"])
    return "\n".join(x for x in lines if x)


def format_trace(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc)).strip()


def _recipe_error():
    from .recipes.base import RecipeError
    return RecipeError


class BuildError(_recipe_error()):
    """A RecipeError that carries a diagnosis (public() includes it, so it reaches the agent and the app)."""

    def __init__(self, message: str, feature: str = "", hint: str = "", params=None, diagnosis: dict | None = None):
        super().__init__(message, feature, hint, params)
        self.diagnosis = diagnosis or {}

    def public(self) -> dict:
        return {**super().public(), "diagnosis": self.diagnosis}


def error(exc: BaseException, recipe) -> "BuildError":
    """The BuildError for an exception raised by recipe.build(): message = the plain summary plus the failing line,
    hint = the ranked fixes."""
    d = diagnose(exc, recipe)
    msg = d["summary"]
    if d.get("code") and d["code"] not in msg:
        msg += f" (line {d['line']}: {d['code'][:120]})"
    hint = " ".join(d["fixes"][:3]) or "Step back toward the last value that built, then change one parameter at a time."
    if d.get("safe"):
        hint += f" Robust helper: {d['safe']}."
    return BuildError(msg[:700], d.get("feature", ""), hint[:900], list(getattr(exc, "params", []) or []), d)


def wrap(e, recipe):
    """A RecipeError raised inside build() (by the design, form.craft or parts.checked) with a diagnosis attached:
    the line it came from and the feature, keeping its own message and hint."""
    if getattr(e, "diagnosis", None):
        return e
    d = diagnose(e, recipe)
    msg = str(e)
    if d.get("line") and "line " not in msg:
        msg += f" (line {d['line']}: {d['code'][:120]})"
    d["summary"] = msg
    hint = e.hint or " ".join(d["fixes"][:2])
    return BuildError(msg[:700], e.feature or d.get("feature", ""), hint, e.params, d)
