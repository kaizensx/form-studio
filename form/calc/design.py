"""From a calculation to a design, and back.

    source(result)                 the design's Python: a FeatureDesign with one Param per dimension the calculator
                                   sized, one feature per solid step (form/calc/shapes.py), and the calculation itself
                                   (calculator and inputs) kept in the source as CALC
    create(st, result, name)       a new project from it (Studio.create_design: built in the kernel before it is saved)
    place(st, p, result, at, n)    the hook or the boss on a face of an existing design, through the standard-feature
                                   machinery (form/feature_helpers.py)
    recompute(calc, values)        the calculator run again on a revision's values: what the Bench entry and the
                                   design's own derived() show, so a changed parameter changes the verdict
    record(source_text)            the CALC of a design's source, or None

The calculation travels with the design. Nothing is stored beside it: when a person drags the hook longer, the next
build's derived dimensions and the Bench's "Engineering calculation" entry are the calculator's answer for the new
length, not a remembered one.
"""
from __future__ import annotations

import ast
import pprint

from . import CalcError, run

# kind -> the design it writes.
#   params: (key, label, lo, hi, step, unit, feature); lo/hi None = a range around the value
#   features: (method, label, role, python expression of the new body; "body" is the solid so far)
#   back: design param -> calculator input, for recompute()
#   show: calculator value keys shown as derived dimensions
KINDS = {
    "snap_cantilever": {
        "title": "Cantilever snap hook", "summary": "A snap hook on a pad, sized by strain (Bayer's snap-fit guide).",
        "params": [("length", "Arm length", None, None, 0.5, "mm", "hook"), ("thickness", "Root thickness", None, None, 0.05, "mm", "hook"),
                   ("width", "Arm width", None, None, 0.5, "mm", "hook"), ("undercut", "Undercut", None, None, 0.05, "mm", "hook"),
                   ("lead_angle", "Lead angle", 10, 60, 1, "deg", "hook"), ("return_angle", "Return angle", 30, 90, 1, "deg", "hook"),
                   ("taper", "Arm design (0 constant, 1 thickness to half, 2 width to a quarter)", 0, 2, 1, "", "hook")],
        "features": [("pad", "Pad", "structure", "shapes.snap_pad(v)"), ("hook", "Snap hook", "interface", "body + shapes.snap_hook(v)")],
        "back": {"length": "length", "thickness": "thickness", "width": "width", "undercut": "undercut",
                 "lead_angle": "lead_angle", "return_angle": "return_angle", "taper": ("taper", ("constant", "thickness_half", "width_quarter"))},
        "show": ("strain", "strain_allow", "deflection_force", "mating_force", "separation_force")},
    "snap_annular": {
        "title": "Annular snap joint", "summary": "A beaded tube and the grooved hub it snaps into, sized by hoop strain.", "solids": 2,
        "params": [("diameter", "Diameter at the joint", None, None, 0.5, "mm", "shaft"), ("undercut", "Undercut on the diameter", None, None, 0.05, "mm", "shaft"),
                   ("wall", "Wall thickness", None, None, 0.1, "mm", "shaft"), ("height", "Height", None, None, 0.5, "mm", "shaft"),
                   ("lead_angle", "Lead angle", 15, 60, 1, "deg", "shaft")],
        "features": [("shaft", "Beaded tube", "interface", "shapes.annular_shaft(v)", 1), ("hub", "Grooved hub", "interface", "body + shapes.annular_hub(v)", 1)],
        "back": {"diameter": "diameter", "undercut": "undercut", "wall": "wall", "lead_angle": "lead_angle"},
        "show": ("strain", "strain_allow", "deflection_force", "mating_force")},
    "living_hinge": {
        "title": "Living hinge", "summary": "Two panels joined by a thin web that folds.",
        "params": [("width", "Hinge width", None, None, 1, "mm", "hinge"), ("gap", "Flexing length of the web", None, None, 0.1, "mm", "hinge"),
                   ("web_t", "Web thickness", None, None, 0.02, "mm", "hinge"), ("panel_t", "Panel thickness", None, None, 0.2, "mm", "hinge"),
                   ("panel_len", "Panel length", None, None, 1, "mm", "hinge"), ("angle", "Fold angle", 5, 360, 5, "deg", "hinge")],
        "features": [("hinge", "Panels and web", "interface", "shapes.living_hinge(v)")],
        "back": {"width": "width", "gap": "length", "web_t": "thickness", "angle": "angle", "panel_t": "panel_thickness", "panel_len": "panel_length"},
        "show": ("strain", "strain_allow", "radius", "moment")},
    "spring_compression": {
        "title": "Compression spring", "summary": "A round-wire compression spring to EN 13906-1; closed ends are eased into the working pitch and ground flat.",
        "params": [("wire_d", "Wire diameter", None, None, 0.05, "mm", "coil"), ("mean_d", "Mean coil diameter", None, None, 0.5, "mm", "coil"),
                   ("active", "Active coils", 1, 60, 0.25, "", "coil"), ("free_l", "Free length", None, None, 0.5, "mm", "coil"),
                   ("closed", "Closed ends (1) or open (0)", 0, 1, 1, "", "coil"), ("ground", "Ground ends (1) or not (0)", 0, 1, 1, "", "coil")],
        "features": [("coil", "Coil", "structure", "shapes.spring_compression(v)")],
        "back": {"wire_d": "wire_d", "mean_d": "mean_d", "active": "active", "free_l": "free_length"},
        "drop": ("rate",), "show": ("rate", "solid_length", "force", "stress", "stress_solid", "buckling_deflection", "frequency")},
    "spring_extension": {
        "title": "Extension spring", "summary": "The close-wound body of an extension spring to EN 13906-2. The hooks are not drawn: their form is the maker's.",
        "params": [("wire_d", "Wire diameter", None, None, 0.05, "mm", "coil"), ("mean_d", "Mean coil diameter", None, None, 0.5, "mm", "coil"),
                   ("coils", "Coils", 2, 120, 0.5, "", "coil")],
        "features": [("coil", "Coil", "structure", "shapes.spring_extension(v)")],
        "back": {"wire_d": "wire_d", "mean_d": "mean_d", "coils": "active"}, "drop": ("rate",),
        "show": ("rate", "body_length", "force", "stress", "hook_stress")},
    "spring_torsion": {
        "title": "Torsion spring", "summary": "A close-wound torsion spring to EN 13906-3 with two straight tangent legs.",
        "params": [("wire_d", "Wire diameter", None, None, 0.05, "mm", "coil"), ("mean_d", "Mean coil diameter", None, None, 0.5, "mm", "coil"),
                   ("coils", "Coils", 1, 60, 0.25, "", "coil"), ("leg1", "First leg", 0, 300, 1, "mm", "coil"), ("leg2", "Second leg", 0, 300, 1, "mm", "coil")],
        "features": [("coil", "Coil and legs", "structure", "shapes.spring_torsion(v)")],
        "back": {"wire_d": "wire_d", "mean_d": "mean_d", "coils": "active", "leg1": "leg1", "leg2": "leg2"}, "drop": ("rate",),
        "show": ("rate", "body_length", "torque", "stress", "wound_d")},
    "bolted_joint": {
        "title": "Bolted joint", "summary": "Two plates drilled for the screws the load calls for (VDI 2230, simplified), side by side as made.", "solids": 2,
        "params": [("top_t", "Top plate thickness", 1, 200, 0.5, "mm", "top"), ("bottom_t", "Bottom plate thickness", 1, 200, 0.5, "mm", "bottom"),
                   ("bolts", "Screws in the row", 1, 12, 1, "", "bottom"), ("pitch", "Screw spacing", None, None, 0.5, "mm", "bottom"),
                   ("engagement", "Thread engagement", 0, 200, 0.5, "mm", "bottom")],
        "const": ("d", "tapped"),
        "features": [("bottom", "Bottom plate", "interface", "shapes.joint_bottom({**v, **CONST})", 1),
                     ("top", "Top plate", "interface", "body + shapes.joint_top({**v, **CONST}, CALC['text']['head'])", 1)],
        "back": {"top_t": "top_t", "bottom_t": "bottom_t", "bolts": "bolts", "pitch": "pitch"},
        "show": ("preload_permissible", "torque", "preload_max", "safety_yield", "engagement_required")},
    "insert_boss": {
        "title": "Boss with a heat-set insert", "summary": "A boss with the insert maker's pocket and least wall.",
        "params": [("boss_d", "Boss outer diameter", None, None, 0.1, "mm", "boss"), ("height", "Boss height", None, None, 0.5, "mm", "boss")],
        "const": ("d", "short"),
        "features": [("base", "Base", "structure", "shapes.insert_base(v)"),
                     ("boss", "Boss", "structure", "body + shapes.insert_boss(v, CALC['text']['size'])[0]"),
                     ("pocket", "Insert pocket", "interface", "body - shapes.insert_boss(v, CALC['text']['size'])[1]")],
        "back": {}, "show": ("hole_d", "min_wall", "pocket_depth", "pullout_bound")},
    "gear_pair": {
        "title": "Involute gear pair", "summary": "Two involute gears in mesh at the working centre distance.", "solids": 2,
        "params": [("module", "Normal module", None, None, 0.05, "mm", "pinion"), ("z1", "Pinion teeth", 6, 400, 1, "", "pinion"),
                   ("z2", "Gear teeth", 6, 800, 1, "", "wheel"), ("x1", "Pinion profile shift", -1, 1.5, 0.01, "", "pinion"),
                   ("x2", "Gear profile shift", -1, 1.5, 0.01, "", "wheel"), ("helix", "Helix angle", 0, 45, 0.5, "deg", "pinion"),
                   ("face", "Face width", None, None, 0.5, "mm", "pinion"), ("backlash", "Tooth thinning for backlash", 0, 2, 0.01, "mm", "pinion"),
                   ("bore1", "Pinion bore", 0, 500, 0.5, "mm", "pinion"), ("bore2", "Gear bore", 0, 2000, 0.5, "mm", "wheel")],
        "const": ("pressure_angle",), "follow": ("centre", "ha1", "ha2", "depth"),
        "features": [("pinion", "Pinion", "interface", "shapes.gear_pinion(GEOM(v))", 1), ("wheel", "Gear", "interface", "body + shapes.gear_wheel(GEOM(v))", 1)],
        "back": {"module": "module", "z1": "z1", "z2": "z2", "x1": "x1", "x2": "x2", "helix": "helix", "face": "face", "backlash": "backlash",
                 "bore1": "bore1", "bore2": "bore2"},
        "show": ("centre_distance", "alpha_wt", "contact_ratio", "total_contact_ratio", "da1", "da2", "backlash_total", "bending_stress")},
    "gear_internal": {
        "title": "Internal gear pair", "summary": "A pinion inside an internal (ring) gear.", "solids": 2,
        "params": [("module", "Module", None, None, 0.05, "mm", "pinion"), ("z1", "Pinion teeth", 6, 400, 1, "", "pinion"),
                   ("z2", "Ring teeth", 20, 800, 1, "", "ring"), ("face", "Face width", None, None, 0.5, "mm", "pinion"),
                   ("backlash", "Tooth thinning for backlash", 0, 2, 0.01, "mm", "pinion"), ("bore1", "Pinion bore", 0, 500, 0.5, "mm", "pinion"),
                   ("rim", "Rim thickness", None, None, 0.5, "mm", "ring")],
        "const": ("pressure_angle", "helix", "x1"), "follow": ("centre",),
        "features": [("pinion", "Pinion", "interface", "shapes.rack_pinion(GEOM(v))", 1), ("ring", "Internal gear", "interface", "body + shapes.gear_ring(GEOM(v))", 1)],
        "back": {"module": "module", "z1": "z1", "z2": "z2", "face": "face", "backlash": "backlash", "bore1": "bore1", "rim": "rim"},
        "show": ("centre_distance", "contact_ratio", "da1", "da2", "bending_stress")},
    "gear_rack": {
        "title": "Rack and pinion", "summary": "An involute pinion on a straight-flanked rack.", "solids": 2,
        "params": [("module", "Module", None, None, 0.05, "mm", "pinion"), ("z1", "Pinion teeth", 6, 400, 1, "", "pinion"),
                   ("x1", "Pinion profile shift", -1, 1.5, 0.01, "", "pinion"), ("face", "Face width", None, None, 0.5, "mm", "pinion"),
                   ("backlash", "Tooth thinning for backlash", 0, 2, 0.01, "mm", "pinion"), ("bore1", "Pinion bore", 0, 500, 0.5, "mm", "pinion"),
                   ("rack_teeth", "Teeth on the rack", 2, 400, 1, "", "rack")],
        "const": ("pressure_angle", "helix"), "follow": ("centre",),
        "features": [("pinion", "Pinion", "interface", "shapes.rack_pinion(GEOM(v))", 1), ("rack", "Rack", "interface", "body + shapes.gear_rack(GEOM(v))", 1)],
        "back": {"module": "module", "z1": "z1", "x1": "x1", "face": "face", "backlash": "backlash", "bore1": "bore1", "rack_teeth": "rack_teeth"},
        "show": ("centre_distance", "contact_ratio", "travel", "rack_pitch", "bending_stress")},
    "cam": {
        "title": "Plate cam", "summary": "A rise-dwell-fall-dwell plate cam for a translating roller follower.",
        "params": [("lift", "Lift", None, None, 0.1, "mm", "cam"), ("rise", "Rise angle", 5, 350, 1, "deg", "cam"), ("dwell", "Dwell at the top", 0, 340, 1, "deg", "cam"),
                   ("fall", "Fall angle", 5, 350, 1, "deg", "cam"), ("base_r", "Base circle radius", None, None, 0.5, "mm", "cam"),
                   ("roller_r", "Roller radius", 0, 200, 0.5, "mm", "cam"), ("thickness", "Plate thickness", None, None, 0.5, "mm", "cam"),
                   ("bore", "Bore", 0, 500, 0.5, "mm", "cam"), ("law", "Motion law (0 cycloidal, 1 harmonic, 2 polynomial 3-4-5)", 0, 2, 1, "", "cam")],
        "features": [("cam", "Cam plate", "interface", "shapes.cam(v)")],
        "back": {"lift": "lift", "rise": "rise", "dwell": "dwell", "fall": "fall", "base_r": "base_radius", "roller_r": "roller_radius",
                 "thickness": "thickness", "bore": "bore", "law": ("law", ("cycloidal", "harmonic", "poly345"))},
        "show": ("pressure_angle", "curvature_min", "velocity_peak", "acceleration_peak", "velocity", "acceleration")},
    "fit_pair": {
        "title": "Fit pair", "summary": "A housing ring and a pin at the middle of their ISO 286 tolerance zones.", "solids": 2,
        "params": [("length", "Length of the fit", None, None, 0.5, "mm", "housing"), ("wall", "Housing wall", None, None, 0.5, "mm", "housing")],
        "const": ("hole_d", "shaft_d"),
        "features": [("housing", "Housing", "interface", "shapes.fit_housing({**v, **CONST})", 1), ("shaft", "Pin", "interface", "body + shapes.fit_shaft({**v, **CONST})", 1)],
        "back": {}, "show": ("clearance_min_20", "clearance_max_20", "clearance_min_span", "clearance_max_span")},
}


def _range(val: float, lo, hi, step: float) -> tuple[float, float]:
    a = lo if lo is not None else min(val / 8.0, val) if val > 0 else 0.0
    b = hi if hi is not None else max(val * 8.0, val + 10 * step)
    return float(round(min(a, val), 6)), float(round(max(b, val), 6))


def _clean(x):
    return round(float(x), 6)


def source(result: dict) -> str:
    """The Python source of the design a calculation writes."""
    g = result.get("geometry")
    if not g or g.get("kind") not in KINDS:
        raise CalcError("This calculation writes no geometry.", "")
    k = KINDS[g["kind"]]
    vals = {key: _clean(v) for key, v in g["values"].items()}
    const = {c: vals[c] for c in k.get("const", ())}
    follow = k.get("follow", ())
    lines = []
    rows = {r["key"]: r for r in result.get("values", [])}
    eqs = {e["id"]: e["text"] for e in result.get("equations", [])}
    for key, label, lo, hi, step, unit, feat in k["params"]:
        a, b = _range(vals[key], lo, hi, step)
        # how the value is known, from the sheet: a number given in the request is specified; one the calculator
        # sized or defaulted stays assumed until someone confirms it, and its doc says where it came from
        ikey = k["back"].get(key)
        row = rows.get(ikey[0] if isinstance(ikey, tuple) else ikey) or rows.get(key)
        prov, doc = "assumed", ("chosen in the request, or its default" if ikey else "geometry only: not part of the calculation")
        if row:
            prov = "specified" if row["evidence"] == "specified" else "assumed"
            doc = {"computed": "computed by the calculator: " + eqs.get(row["equation"], row["equation"]),
                   "specified": "specified: " + (row["note"] or "given in the request or published"),
                   "assumed": "assumed: " + row["note"]}[row["evidence"]]
        lines.append(f"        Param({key!r}, {label!r}, {vals[key]!r}, {a!r}, {b!r}, {step!r}, {unit!r}, 'form', {feat!r},\n"
                     f"              doc={doc!r}, provenance={prov!r}),")
    calc = {"calculator": result["calculator"], "kind": g["kind"], "version": result.get("version", 1),
            "inputs": result["inputs"], "text": g.get("text") or {}, "headline": result["headline"]}
    feats = []
    for f in k["features"]:
        name, label, role, expr = f[:4]
        parts = f", parts={f[4]}" if len(f) > 4 else ""
        feats.append(f"    @feature({label!r}, role={role!r}{parts})\n    def {name}(self, v, body):\n        return {expr}\n")
    head = '"""' + k["title"] + ", written by Form Studio's " + result["calculator"] + " calculator (" + result["standard"] + ').\n\n' \
        + result["headline"] + "\n\nThe calculation is CALC below: the calculator and the inputs it was run with. Every build runs it again on the\n" \
        "current parameter values (derived()), so the numbers shown belong to this revision. Edit the parameters, not the\n" \
        'derived values. `form calc show <project>` prints the full sheet with its equations and sources.\n"""\n'
    geom = ""
    if follow:
        geom = ("\n\ndef GEOM(v):\n    \"\"\"The values the solids need: the parameters, the constants, and the dimensions that follow from them\n"
                "    by the calculator (centre distance, tooth depth), recomputed for these values.\"\"\"\n"
                "    return {**v, **CONST, **calc_design.following(CALC, {**v, **CONST})}\n")
    elif any("GEOM(" in f[3] for f in k["features"]):
        geom = "\n\ndef GEOM(v):\n    return {**v, **CONST}\n"
    return (head + "from form.calc import design as calc_design\nfrom form.calc import shapes\nfrom form.featureprog import FeatureDesign, feature\n"
            "from form.recipes.base import Param\n\nCALC = " + pprint.pformat(calc, width=110, sort_dicts=True) + "\nCONST = " + repr(const) + geom
            + "\n\nclass Design(FeatureDesign):\n    title, summary = " + repr(k["title"]) + ", " + repr(k["summary"]) + "\n"
            + (f"    solids = {k['solids']}\n" if k.get("solids") else "")
            + "    params = [\n" + "\n".join(lines) + "\n    ]\n\n    def derived(self, v):\n        return calc_design.derived(CALC, {**v, **CONST})\n\n"
            + "\n".join(feats))


def record(text: str | None) -> dict | None:
    """The CALC dict of a design's source (a literal), or None when the design was not written by a calculator."""
    if not text or "CALC = " not in text:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("CALC", "CONST"):
            try:
                out[n.targets[0].id] = ast.literal_eval(n.value)
            except (ValueError, SyntaxError):
                return None
    c = out.get("CALC")
    if not isinstance(c, dict) or c.get("kind") not in KINDS or not isinstance(c.get("inputs"), dict):
        return None
    return {**c, "const": out.get("CONST") or {}}


def inputs_for(calc: dict, values: dict) -> dict:
    """The calculator's inputs for a revision: the original request with every dimension the design owns replaced by
    the revision's value."""
    k = KINDS[calc["kind"]]
    inp = dict(calc["inputs"])
    for d in k.get("drop", ()):
        inp.pop(d, None)
    for pkey, ikey in k["back"].items():
        if pkey not in values:
            continue
        if isinstance(ikey, tuple):
            ikey, names = ikey
            inp[ikey] = names[int(round(values[pkey]))]
        else:
            inp[ikey] = values[pkey]
    return inp


def recompute(calc: dict, values: dict) -> dict:
    """The calculator's sheet for a revision's values. A CalcError becomes a failed sheet with the reason."""
    try:
        return run(calc["calculator"], inputs_for(calc, values))
    except CalcError as e:
        return {"calculator": calc["calculator"], "status": "FAIL", "headline": str(e), "values": [], "sources": [], "equations": [],
                "checks": [{"id": "calc", "label": "Calculation", "status": "FAIL", "value": "not possible", "detail": (str(e) + " " + e.hint).strip(),
                            "equation": "", "evidence": "computed"}], "error": e.public(), "geometry": None}


def following(calc: dict, values: dict) -> dict:
    """The geometry values that follow from the parameters by the calculator (KINDS[...]["follow"])."""
    r = recompute(calc, values)
    if r.get("error"):
        from ..recipes.base import RecipeError
        raise RecipeError(r["headline"], "", r["error"].get("hint", ""), r["error"].get("params", []))
    g = r["geometry"]["values"]
    return {k: g[k] for k in KINDS[calc["kind"]].get("follow", ())}


def derived(calc: dict, values: dict) -> list:
    """Derived dimensions of the design: the calculator's headline numbers for these values, and its checks."""
    r = recompute(calc, values)
    k = KINDS[calc["kind"]]
    feat = k["features"][-1][0]
    rows = {v["key"]: v for v in r["values"]}
    eqs = {e["id"]: e["text"] for e in r.get("equations", [])}
    out = []
    for key in k["show"]:
        v = rows.get(key)
        if v is None or not isinstance(v["value"], (int, float)):
            continue
        val, unit = v["value"], v["unit"]
        if key.startswith("strain"):
            val, unit = round(100 * val, 3), "%"
        out.append({"key": "calc_" + key, "label": v["label"], "value": val, "unit": unit, "feature": feat,
                    "formula": (eqs.get(v["equation"]) or v.get("source") or v["evidence"]) + f" [{v['evidence']}]", "interface": False})
    for c in r["checks"]:
        if c["status"] in ("FAIL", "WARN"):
            out.append({"key": "calc_check_" + c["id"], "label": f"{c['status']}: {c['label']}", "value": 0 if c["status"] == "FAIL" else 1,
                        "unit": "", "feature": feat, "formula": c["value"] + ". " + c["detail"], "interface": False})
    return out


def create(st, result: dict, name: str = "", purpose: str | None = None) -> dict:
    """A new project from a calculation's geometry. Built in the kernel before it is saved; returns the project."""
    g = result["geometry"]
    src = source(result)
    brief = f"{result['title']} ({result['standard']}). {result['headline']}"
    return st.create_design(name or g["name"], src, brief=brief, purpose=purpose)


def place(st, p: dict, result: dict, at, normal, expect_head=None, origin: str = "agent") -> dict:
    """Put the calculated hook or boss on a flat face of an existing design: a standard feature in its source."""
    g = result.get("geometry") or {}
    pl = g.get("place")
    if not pl:
        raise CalcError("This calculation has nothing to place on a face.",
                        "A snap hook (snapfit, cantilever) or an insert boss (fastener, kind=boss) can be placed; the rest are designs of their own.")
    from .. import feature_helpers
    return feature_helpers.add(st, p, pl["feature"], at, normal, expect_head=expect_head, origin=origin, **pl["options"])


def fea_definition(result: dict) -> dict | None:
    """A static strength study that checks a cantilever hook by finite elements: the pad's underside held, the
    deflection force on the lip's outer face, pushed back along -X. None for anything else.

    "expect" is what beam theory says the study should find, for a constant-section arm: the peak stress at the root,
    E · ε, and the largest displacement, at the top of the hook, which is past the point the force acts on:
    y(a) + θ(a) · (top − a) with y(a) = P a³ / (3 E I), θ(a) = P a² / (2 E I), a the height of the lip's face.
    The solid adds what the beam leaves out (the root's and the pad's give, shear), so it moves a few per cent more."""
    import math
    g = result.get("geometry") or {}
    v = {r["key"]: r["value"] for r in result.get("values", [])}
    if g.get("kind") != "snap_cantilever" or "deflection_force" not in v:
        return None
    gv = g["values"]
    L, t, w, y = gv["length"], gv["thickness"], gv["width"], gv["undercut"]
    ret_h = 0.0 if gv["return_angle"] >= 89.999 else y / math.tan(math.radians(gv["return_angle"]))
    flat = max(0.4, 0.2 * t)
    a = L + ret_h + flat / 2
    top = L + ret_h + flat + y / math.tan(math.radians(gv["lead_angle"]))
    P = float(v["deflection_force"])
    E = v.get("E") or v.get("E_datasheet")
    expect = {"deflection_at_the_arm_length_mm": y, "strain": v.get("strain"),
              "note": "Beam theory (the guide) against the solid: expect the solid to move a few per cent more (the "
                      "root's give, shear) and its peak stress to sit at the root."}
    if E and int(round(gv.get("taper", 0))) == 0:
        EI = E * w * t ** 3 / 12
        expect.update({"peak_stress_MPa": E * v["strain"],
                       "max_displacement_mm": P * a ** 3 / (3 * EI) + P * a * a / (2 * EI) * (top - a),
                       "accepted": {"peak_stress": 0.05, "max_displacement": 0.10}})
    return {"kind": "static", "name": "Snap hook at full deflection force",
            "fixtures": [{"type": "fixed", "faces": [[t / 2, 0.0, -2.0]]}],
            "loads": [{"type": "force", "faces": [[t + y, 0.0, a]], "vector": [-P, 0.0, 0.0]}],
            "expect": expect}
