"""The FreeCAD side of the PartDesign export (form/partdesign.py). This file runs inside FreeCADCmd, never in Form
Studio: form/partdesign.py writes it into the export script after the plan (PLAN = {...}), so the script stands alone.

It builds one PartDesign Body from the plan, one step at a time, and checks every step against the solid Form Studio
built for it (a B-rep file next to the script): the symmetric difference of the two solids, relative to the expected
volume, must be within TOL. A native feature that does not recompute, or recomputes to another solid, is taken out
again; the step is then tried in its other variants (a direction reversed, a join kind), and when none matches it is
put in as a frozen solid (two PartDesign Booleans with a tool Body that holds the expected solid), and the report says
so. Only a step whose native feature recomputed to the expected solid is reported editable.

Edges and faces a fillet, chamfer or thickness acts on are found on the previous feature's shape in FreeCAD by their
geometry (centre of mass, length or area, direction), so the names written into the document (Edge12, Face3) are the
ones FreeCAD gives the solid it recomputed. FreeCAD's topological naming is still fragile: after an edit that changes
the topology before such a feature, FreeCAD may attach it to another edge or fail; the report says this too.
"""
# ruff: noqa: E402  (FreeCAD's modules exist only inside FreeCAD; they are imported in run())
import json
import math
import os
import sys

TAG = "FORM_PARTDESIGN_RESULT "
TOL = 2e-4                 # symmetric difference / expected volume at which a step counts as the same solid
SUPERSEDED = "Superseded: "  # the label prefix of a Body a later step had to start again from
TOOL = "Frozen tool: "     # the label of a tool Body that holds a frozen step's solid
MATCH = 2e-3               # mm: an edge's or face's centre of mass is found again within this


def _say(obj):
    sys.stdout.write(TAG + json.dumps(obj) + "\n")
    sys.stdout.flush()


def _stats(shape):
    try:
        bb = shape.optimalBoundingBox(False, False)
    except Exception:
        bb = shape.BoundBox
    return {"volume": float(shape.Volume), "faces": len(shape.Faces), "solids": len(shape.Solids),
            "valid": bool(shape.isValid()),
            "bbox": [[bb.XMin, bb.YMin, bb.ZMin], [bb.XMax, bb.YMax, bb.ZMax]]}


def _dev(actual, expected):
    """|A xor E| / |E|: 0 is the same solid."""
    if actual is None or actual.isNull() or not actual.Solids:
        return 1.0
    va, ve = actual.Volume, expected.Volume
    try:
        common = actual.common(expected).Volume
    except Exception:
        return 1.0
    return abs(va + ve - 2 * common) / max(abs(ve), 1e-9)


def _solid_of(doc):
    """The document's part: its one Body, or every Body's solid together for a design of several parts."""
    import Part
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Label.startswith((TOOL, SUPERSEDED))]
    if len(bodies) == 1:
        return bodies[0].Shape
    return Part.makeCompound([b.Shape for b in bodies if not b.Shape.isNull()])


def run(plan, here, out_path):
    import FreeCAD as App
    import Part
    import Sketcher

    V = App.Vector
    rep = {"ok": False, "version": ".".join(str(x) for x in App.Version()[:3]), "steps": [], "bound": [],
           "notes": []}
    doc = App.newDocument(plan.get("doc") or "FormStudio")
    # Element names written in full, not as string-hasher ids: with the hasher, a fillet made by script lost its
    # edges on the first edit of the sketch before it (FreeCAD 1.1.4); with full names it keeps them.
    if "UseHasher" in doc.PropertiesList:
        doc.UseHasher = False
    sheet = doc.addObject("Spreadsheet::Sheet", "Params")
    sheet.Label = "Params"
    for col, head in zip("ABCDEFG", ("Parameter", "Key", "Value", "Unit", "Source", "Min", "Max")):
        sheet.set(col + "1", head)
    alias = {}
    for i, p in enumerate(plan.get("params") or [], start=2):
        sheet.set("A%d" % i, str(p["label"]))
        sheet.set("B%d" % i, str(p["key"]))
        sheet.set("C%d" % i, repr(float(p["value"])))
        sheet.set("D%d" % i, str(p.get("unit") or ""))
        sheet.set("E%d" % i, str(p.get("source") or ""))
        if p.get("min") is not None:
            sheet.set("F%d" % i, repr(float(p["min"])))
        if p.get("max") is not None:
            sheet.set("G%d" % i, repr(float(p["max"])))
        try:
            sheet.setAlias("C%d" % i, p["alias"])
            alias[p["key"]] = p["alias"]
        except Exception as e:
            rep["notes"].append("parameter %s has no cell name in FreeCAD (%s)" % (p["key"], e))
    doc.recompute()
    body = doc.addObject("PartDesign::Body", "Body")
    body.Label = plan.get("label") or "Body"
    origin = {f.Role: f for f in body.Origin.OriginFeatures}
    objs = {}
    bound_now = []

    def bind(obj, prop, key, scale=""):
        if key and key in alias:
            obj.setExpression(prop, "Params." + alias[key] + scale)
            bound_now.append(key)

    def load(name):
        if not name:
            return None
        s = Part.Shape()
        s.read(os.path.join(here, name))
        return s

    def placement(o, x, z):
        x, z = V(*x), V(*z)
        y = z.cross(x)
        m = App.Matrix(x.x, y.x, z.x, o[0], x.y, y.y, z.y, o[1], x.z, y.z, z.z, o[2], 0, 0, 0, 1)
        return App.Placement(m)

    def same_placement(a, b):
        return (a.Base - b.Base).Length < 1e-6 and all(
            (a.Rotation.multVec(V(*e)) - b.Rotation.multVec(V(*e))).Length < 1e-6 for e in ((1, 0, 0), (0, 0, 1)))

    def sketch(name, sk, made):
        s = body.newObject("Sketcher::SketchObject", name)
        made.append(s)
        pl = sk["plane"]
        want = placement(pl["origin"], pl["x"], pl["z"])
        if pl.get("ref") and objs.get(pl["ref"]) is not None:
            s.AttachmentSupport = [(objs[pl["ref"]], "")]
            s.MapMode = "FlatFace"
            s.recompute()
            if not same_placement(s.Placement, want):
                s.MapMode = "Deactivated"
                s.AttachmentSupport = []
                s.Placement = want
                rep["notes"].append("%s: the sketch is placed on %s's plane, not attached (FreeCAD orients it "
                                    "differently)" % (name, pl["ref"]))
        elif pl.get("datum"):
            s.AttachmentSupport = [(origin[pl["datum"] + "_Plane"], "")]
            s.MapMode = "FlatFace"
            s.AttachmentOffset = App.Placement(V(0, 0, float(pl.get("offset") or 0)), App.Rotation())
            s.recompute()
            if not same_placement(s.Placement, want):
                s.MapMode = "Deactivated"
                s.AttachmentSupport = []
                s.Placement = want
                rep["notes"].append("%s: FreeCAD's %s plane is oriented differently; the sketch is placed, not "
                                    "attached" % (name, pl["datum"]))
        else:
            s.MapMode = "Deactivated"
            s.Placement = want
        for g in sk["geometry"]:
            t = g["t"]
            if t == "line":
                geo = Part.LineSegment(V(g["a"][0], g["a"][1], 0), V(g["b"][0], g["b"][1], 0))
            elif t == "circle":
                geo = Part.Circle(V(g["o"][0], g["o"][1], 0), V(0, 0, 1), g["r"])
            elif t == "arc":
                geo = Part.ArcOfCircle(Part.Circle(V(g["o"][0], g["o"][1], 0), V(0, 0, 1), g["r"]), g["a0"], g["a1"])
            else:
                geo = Part.Point(V(g["p"][0], g["p"][1], 0))
            s.addGeometry(geo, bool(g.get("c")))
        for c in sk.get("constraints") or []:
            args = list(c["a"])
            if "v" in c:
                args.append(math.radians(c["v"]) if c.get("angle") else float(c["v"]))
            try:
                k = s.addConstraint(Sketcher.Constraint(c["t"], *args))
            except Exception as e:
                rep["notes"].append("%s: a %s constraint was not taken (%s)" % (name, c["t"], e))
                continue
            if c.get("name"):
                try:
                    s.renameConstraint(k, c["name"])
                    if c.get("bind") in alias:
                        s.setExpression("Constraints." + c["name"], "Params." + alias[c["bind"]] +
                                        (" * 1 deg" if c.get("angle") else ""))
                        bound_now.append(c["bind"])
                except Exception as e:
                    rep["notes"].append("%s: dimension %s is not bound (%s)" % (name, c["name"], e))
        try:
            red = list(s.RedundantConstraints or []) + list(s.ConflictingConstraints or [])
        except Exception:
            red = []
        if s.solve() != 0 or red:
            for k in sorted(set(red), reverse=True):
                s.delConstraint(k - 1)
            if red:
                rep["notes"].append("%s: %d redundant constraint(s) left out" % (name, len(set(red))))
        return s

    def match_edges(shape, sigs):
        names = []
        for sig in sigs:
            best = None
            for i, e in enumerate(shape.Edges):
                d = (e.CenterOfMass - V(*sig["c"])).Length + abs(e.Length - sig["l"])
                if best is None or d < best[0]:
                    best = (d, i)
            if best is None or best[0] > MATCH * max(1.0, sig["l"]):
                raise RuntimeError("an edge (at %.2f, %.2f, %.2f) is not on FreeCAD's solid" % tuple(sig["c"]))
            names.append("Edge%d" % (best[1] + 1))
        return names

    def match_faces(shape, sigs):
        names = []
        for sig in sigs:
            best = None
            for i, f in enumerate(shape.Faces):
                d = (f.CenterOfMass - V(*sig["c"])).Length + abs(f.Area - sig["a"]) / max(1.0, sig["a"])
                if best is None or d < best[0]:
                    best = (d, i)
            if best is None or best[0] > MATCH * 10:
                raise RuntimeError("a face (at %.2f, %.2f, %.2f) is not on FreeCAD's solid" % tuple(sig["c"]))
            names.append("Face%d" % (best[1] + 1))
        return names

    def axis_ref(ax, at, made):
        ax = [float(a) for a in ax]
        at = [float(a) for a in (at or (0, 0, 0))]
        if max(abs(a) for a in at) < 1e-9:
            for i, role in enumerate(("X_Axis", "Y_Axis", "Z_Axis")):
                if abs(abs(ax[i]) - 1) < 1e-9:
                    return (origin[role], [""]), ax[i] < 0
        d = body.newObject("PartDesign::Line", "Axis")
        made.append(d)
        d.MapMode = "Deactivated"
        d.Placement = App.Placement(V(*at), App.Rotation(V(0, 0, 1), V(*ax)))
        return (d, [""]), False

    def apply(o, variant):
        for k, v in (variant or {}).items():
            setattr(o, k, v)

    def pad_or_pocket(st, made, variant, sk, depth, key, kind, through=False, mid=False, name=None):
        s = sketch((name or st["feature"]) + "_sketch", sk, made)
        o = body.newObject("PartDesign::Pad" if kind == "pad" else "PartDesign::Pocket", name or st["feature"])
        made.append(o)
        o.Profile = s
        if through:
            o.Type = "ThroughAll"
            o.Midplane = bool(mid)
        else:
            o.Length = float(depth)
            bind(o, "Length", key)
        apply(o, variant)
        return o

    def plane_link(pl, prev, made):
        """A plane a mirror or draft names: an origin plane, a datum plane feature, a face, or a Plane placed there."""
        if pl.get("origin_plane"):
            return (origin[pl["origin_plane"] + "_Plane"], [""])
        if pl.get("ref") and objs.get(pl["ref"]) is not None:
            return (objs[pl["ref"]], [""])
        if pl.get("face"):
            return (prev, match_faces(prev.Shape, [pl["face"]]))
        d = body.newObject("PartDesign::Plane", "Plane")
        made.append(d)
        d.MapMode = "Deactivated"
        d.Placement = placement(pl["origin"], pl["x"], pl["z"])
        return (d, [""])

    def ends(st, o, variant, prev):
        bd = st.get("bind", {})
        ft = -1.0 if (variant or {}).get("flip_taper") else 1.0
        fo = -1.0 if (variant or {}).get("flip_offset") else 1.0
        two = "side2" in st
        if two:
            o.SideType = "Two sides"
        elif st.get("midplane"):
            o.SideType = "Symmetric"
        for n, sd in ((1, st["side1"]), (2, st.get("side2"))):
            if sd is None:
                continue
            suf = "" if n == 1 else "2"
            setattr(o, "Type" + suf, sd["Type"])
            if "Length" in sd:
                setattr(o, "Length" + suf, float(sd["Length"]))
                if not sd.get("computed"):
                    bind(o, "Length" + suf, bd.get("depth" if n == 1 else "depth2"))
            if sd.get("face"):
                setattr(o, "UpToFace" + suf, (prev, match_faces(prev.Shape, [sd["face"]])))
            off = st.get("offset" if n == 1 else "offset2") or 0.0
            if off:
                setattr(o, "Offset" + suf, -fo * float(off))
                bind(o, "Offset" + suf, bd.get("offset" if n == 1 else "offset2"), " * -1" if fo > 0 else "")
            tp = st.get("taper" if n == 1 else "taper2") or 0.0
            if tp:
                setattr(o, "TaperAngle" + suf, ft * float(tp))
                bind(o, "TaperAngle" + suf, bd.get("draft" if n == 1 else "draft2"),
                     " * 1 deg" if ft > 0 else " * -1 deg")
        if st.get("reversed"):
            o.Reversed = True

    def build(st, variant, made):
        k, fid = st["kind"], st["feature"]
        prev = body.Tip
        if k in ("pad", "pocket") and st.get("ends"):
            s = sketch(fid + "_sketch", st["sketch"], made)
            o = body.newObject("PartDesign::Pad" if k == "pad" else "PartDesign::Pocket", fid)
            made.append(o)
            o.Profile = s
            ends(st, o, variant, prev)
            return o
        if k in ("pad", "pocket"):
            return pad_or_pocket(st, made, variant, st["sketch"], st.get("depth"), st.get("bind", {}).get("depth"), k,
                                 through=st.get("through", False), mid=st.get("midplane", False))
        if k == "pipe":
            s = sketch(fid + "_sketch", st["sketch"], made)
            o = body.newObject("PartDesign::SubtractivePipe" if st.get("cut") else "PartDesign::AdditivePipe", fid)
            made.append(o)
            o.Profile = s
            if st.get("spine"):
                sp = sketch(fid + "_path", st["spine"], made)
                sp.Visibility = False
                o.Spine = (sp, ["Edge%d" % (i + 1) for i, g in enumerate(st["spine"]["geometry"]) if not g.get("c")])
            else:
                o.Spine = (prev, match_edges(prev.Shape, st["spine_edges"]))
            o.Mode = "Frenet" if st.get("frenet") else "Standard"
            apply(o, variant)
            return o
        if k == "loft":
            secs = [sketch("%s_s%d" % (fid, i + 1), sk, made) for i, sk in enumerate(st["sections"])]
            o = body.newObject("PartDesign::SubtractiveLoft" if st.get("cut") else "PartDesign::AdditiveLoft", fid)
            made.append(o)
            o.Profile = secs[0]
            o.Sections = secs[1:]
            o.Ruled = bool(st.get("ruled"))
            apply(o, variant)
            return o
        if k == "mirrored":
            o = body.newObject("PartDesign::Mirrored", fid)
            made.append(o)
            if st.get("of"):
                missing = [f for f in st["of"] if objs.get(f) is None]
                if missing:
                    raise RuntimeError("it mirrors %s, which is not a native feature here" % ", ".join(missing))
                o.Originals = [objs[f] for f in st["of"]]
            else:
                o.TransformMode = "Whole shape"
            o.MirrorPlane = plane_link(st["plane"], prev, made)
            apply(o, variant)
            return o
        if k == "draft":
            o = body.newObject("PartDesign::Draft", fid)
            made.append(o)
            o.Base = (prev, match_faces(prev.Shape, st["faces"]))
            o.NeutralPlane = plane_link(st["plane"], prev, made)
            o.Angle = float(st["angle"])
            bind(o, "Angle", st.get("bind", {}).get("angle"), " * 1 deg")
            if st.get("flip"):
                o.Reversed = not o.Reversed
            apply(o, {kk: (not o.Reversed if kk == "Reversed" else vv) for kk, vv in (variant or {}).items()})
            return o
        if k in ("revolution", "groove"):
            s = sketch(fid + "_sketch", st["sketch"], made)
            o = body.newObject("PartDesign::Revolution" if k == "revolution" else "PartDesign::Groove", fid)
            made.append(o)
            o.Profile = s
            o.ReferenceAxis = (s, [st["axis_ref"]])
            o.Angle = float(st["angle"])
            bind(o, "Angle", st.get("bind", {}).get("angle"), " * 1 deg")
            if st.get("upto_face"):
                o.Type = "UpToFace"
                o.UpToFace = (prev, match_faces(prev.Shape, [st["upto_face"]]))
            if st.get("angle2"):
                o.Type = "TwoAngles"
                o.Angle2 = float(st["angle2"])
                bind(o, "Angle2", st.get("bind", {}).get("angle2"), " * 1 deg")
            if st.get("midplane"):
                o.Midplane = True
            apply(o, variant)
            return o
        if k in ("fillet", "chamfer"):
            names = match_edges(prev.Shape, st["edges"])
            o = body.newObject("PartDesign::Fillet" if k == "fillet" else "PartDesign::Chamfer", fid)
            made.append(o)
            o.Base = (prev, names)
            if k == "fillet":
                o.Radius = float(st["size"])
                bind(o, "Radius", st.get("bind", {}).get("size"))
            else:
                o.ChamferType = "Equal distance"
                o.Size = float(st["size"])
                bind(o, "Size", st.get("bind", {}).get("size"))
            apply(o, variant)
            return o
        if k == "thickness":
            names = match_faces(prev.Shape, st["faces"])
            o = body.newObject("PartDesign::Thickness", fid)
            made.append(o)
            o.Base = (prev, names)
            o.Value = float(st["thickness"])
            o.Mode = "Skin"
            bind(o, "Value", st.get("bind", {}).get("thickness"))
            apply(o, variant)
            return o
        if k == "hole":
            sk = {"plane": {"origin": st["origin"], "x": st["x"], "z": st["normal"]},
                  "geometry": [{"t": "circle", "o": [0, 0], "r": st["d"] / 2}], "constraints": []}
            s = sketch(fid + "_sketch", sk, made)
            o = body.newObject("PartDesign::Hole", fid)
            made.append(o)
            o.Profile = s
            iso = (variant or {}).get("iso")
            if iso:
                o.ThreadType = "ISOMetricProfile"
                size = next((z for z in o.getEnumerationsOfProperty("ThreadSize") if z.split("x")[0] == iso["size"]), None)
                if size is None:
                    raise RuntimeError("FreeCAD has no ISO size " + iso["size"])
                o.ThreadSize = size
                o.Threaded = bool(iso.get("threaded"))
                if not o.Threaded:
                    o.ThreadFit = iso["fit"]
            else:
                o.ThreadType = "None"
                o.Diameter = float(st["d"])
                bind(o, "Diameter", st.get("bind", {}).get("d"))
            if st.get("depth"):
                o.DepthType = "Dimension"
                o.Depth = float(st["depth"])
                bind(o, "Depth", st.get("bind", {}).get("depth"))
            else:
                o.DepthType = "ThroughAll"
            o.DrillPoint = "Flat"
            style = st.get("style") or "plain"
            if style == "counterbore":
                o.HoleCutType = "Counterbore"
                o.HoleCutDiameter = float(st["head_d"])
                o.HoleCutDepth = float(st["head_depth"])
                bind(o, "HoleCutDiameter", st.get("bind", {}).get("head_d"))
                bind(o, "HoleCutDepth", st.get("bind", {}).get("head_depth"))
            elif style == "countersink":
                o.HoleCutType = "Countersink"
                o.HoleCutDiameter = float(st["head_d"])
                o.HoleCutCountersinkAngle = 90.0
                bind(o, "HoleCutDiameter", st.get("bind", {}).get("head_d"))
            o.recompute()
            if iso and abs(o.Diameter.Value - st["d"]) > 1e-3:
                raise RuntimeError("FreeCAD's %s %s hole is Ø%.3f, not Ø%.3f" % (iso["size"], iso.get("fit", ""),
                                                                                  o.Diameter.Value, st["d"]))
            return o
        if k in ("linear_pattern", "polar_pattern"):
            orig = objs.get(st["of"])
            if orig is None:
                raise RuntimeError("it repeats %s, which is not a native feature here" % st["of"])
            lin = k == "linear_pattern"
            ref, rev = axis_ref(st["axis"], None if lin else st.get("origin"), made)
            o = body.newObject("PartDesign::LinearPattern" if lin else "PartDesign::PolarPattern", fid)
            made.append(o)
            o.Originals = [orig]
            if lin:
                o.Direction = ref
            else:
                o.Axis = ref
            o.Reversed = rev
            o.Mode = "Spacing"
            o.Offset = float(st["step"])
            o.Occurrences = int(st["count"])
            bind(o, "Offset", st.get("bind", {}).get("step"), "" if lin else " * 1 deg")
            bind(o, "Occurrences", st.get("bind", {}).get("count"))
            apply(o, {kk: (not rev if kk == "Reversed" and vv == "flip" else vv) for kk, vv in (variant or {}).items()})
            return o
        if k == "prism":
            last = None
            for j, part in enumerate(st["parts"]):
                last = pad_or_pocket(st, made, None, part["sketch"], part["length"], None, part["op"],
                                     name="%s_%s%d" % (fid, part["op"], j + 1))
            return last
        raise RuntimeError("no FreeCAD feature for kind " + k)

    def datum_plane(st):
        pl = st["plane"]
        want = placement(pl["origin"], pl["x"], pl["z"])
        d = body.newObject("PartDesign::Plane", st["feature"])
        at = st.get("attach")
        how = "placed"
        if at:
            d.AttachmentSupport = [(origin[at["datum"] + "_Plane"], "")]
            d.MapMode = "FlatFace"
            ax = V(1, 0, 0) if at.get("about", "x") == "x" else V(0, 1, 0)
            rot = App.Rotation(ax, float(at.get("angle") or 0))
            d.AttachmentOffset = App.Placement(rot.multVec(V(0, 0, float(at.get("offset") or 0))), rot)
            if not float(at.get("angle") or 0) and at.get("bind_offset"):
                bind(d, ".AttachmentOffset.Base.z", at["bind_offset"])
            elif not float(at.get("offset") or 0) and at.get("bind_angle"):
                bind(d, ".AttachmentOffset.Rotation.Angle", at["bind_angle"], " * 1 deg")
            doc.recompute()
            z_ok = (d.Placement.Rotation.multVec(V(0, 0, 1)) - want.Rotation.multVec(V(0, 0, 1))).Length < 1e-6
            on = abs((d.Placement.Base - want.Base).dot(want.Rotation.multVec(V(0, 0, 1)))) < 1e-6
            how = "native" if z_ok and on else "placed"
        if how == "placed":
            for e in list(d.ExpressionEngine):
                d.setExpression(e[0], None)
            bound_now.clear()
            d.MapMode = "Deactivated"
            d.AttachmentSupport = []
            d.Placement = want
            doc.recompute()
        objs[st["feature"]] = d
        rep["bound"] += [b for b in bound_now if b not in rep["bound"]]
        return {"status": "native", "objects": [d.Name], "bound": sorted(set(bound_now)), "dev": 0.0,
                "attached": how == "native"}

    def remove(made):
        for o in reversed(made):
            try:
                body.removeObject(o)
            except Exception:
                pass
            try:
                doc.removeObject(o.Name)
            except Exception:
                pass
        made.clear()
        doc.recompute()

    def broken(made):
        return [o.Name for o in made if not o.isValid() or "Invalid" in (o.State or [])]

    def restart(st, expected):
        """The last resort: a new Body that starts from this step's solid. The Body before it stays in the file,
        hidden and labelled superseded; its features no longer drive the part."""
        nonlocal body, origin
        old = body
        old.Label = SUPERSEDED + old.Label
        old.Visibility = False
        body = doc.addObject("PartDesign::Body", "Body")
        body.Label = plan.get("label") or "Body"
        origin = {f.Role: f for f in body.Origin.OriginFeatures}
        f = doc.addObject("Part::Feature", st["feature"] + "_solid")
        f.Shape = expected
        body.BaseFeature = f
        doc.recompute()
        rep["restart_at"] = st["i"]
        rep["notes"].append("%s: FreeCAD could not combine this step's solid with the features before it, so a new "
                            "Body starts from it; the features before it stay in the file (%s), but no longer drive "
                            "the part" % (st["feature"], old.Name))
        return [body, f]

    def frozen(st, expected):
        made = []
        tip = body.Tip
        if tip is not None and (tip.Shape.isNull() or not tip.Shape.Solids):
            return restart(st, expected)
        if tip is None or tip.Shape.isNull() or not tip.Shape.Solids:
            if body.BaseFeature is None and not [o for o in body.Group if o.isDerivedFrom("PartDesign::Feature")]:
                f = doc.addObject("Part::Feature", st["feature"] + "_solid")
                f.Shape = expected
                body.BaseFeature = f
                doc.recompute()
                return [f]
            raise RuntimeError("no solid to combine with")
        prev = tip.Shape

        def booleans(ops):
            made = []
            for op, shape in ops:
                tool = doc.addObject("PartDesign::Body", "%s_%s_tool" % (st["feature"], op.lower()))
                solid = doc.addObject("Part::Feature", "%s_%s_solid" % (st["feature"], op.lower()))
                solid.Shape = shape
                tool.BaseFeature = solid
                tool.Visibility = False
                tool.Label = TOOL + st["feature"]
                b = body.newObject("PartDesign::Boolean", "%s_%s" % (st["feature"], op.lower()))
                b.Type = op
                b.addObject(tool)
                body.Tip = b
                made += [b, tool, solid]
                doc.recompute()
            return made
        # first what the step added and cut (the earlier features stay live under it), else the whole solid
        eps = 1e-6 * max(expected.Volume, 1.0)
        ops = []
        try:
            add, cut = expected.cut(prev), prev.cut(expected)
            ops = [(op, sh) for op, sh in (("Fuse", add), ("Cut", cut)) if sh.Solids and sh.Volume > eps]
        except Exception:
            ops = []
        made = booleans(ops) if ops else []
        if not ops or _dev(body.Tip.Shape, expected) > TOL:
            remove(made)
            made = booleans([("Fuse", expected), ("Common", expected)])
            if _dev(body.Tip.Shape, expected) > TOL:
                remove(made)
                made = restart(st, expected)
        return made

    for part in plan.get("parts") or []:             # a design of several solids: one Body each, frozen
        pb = doc.addObject("PartDesign::Body", part["feature"])
        pb.Label = part["label"]
        f = doc.addObject("Part::Feature", part["feature"] + "_solid")
        f.Shape = load(part["brep"])
        pb.BaseFeature = f
        doc.recompute()
        rep["steps"].append({"i": part["i"], "feature": part["feature"], "label": part["label"], "kind": "frozen",
                             "status": "frozen", "dev": _dev(pb.Shape, f.Shape), "objects": [pb.Name, f.Name]})
    if plan.get("parts"):
        doc.removeObject(body.Name)
        body = None
    for st in plan["steps"]:
        row = {"i": st["i"], "feature": st["feature"], "label": st.get("label", ""), "kind": st["kind"],
               "source": st.get("source", "")}
        if st["kind"] in ("suppressed", "skipped", "empty"):
            row["status"] = st["kind"]
            rep["steps"].append(row)
            continue
        if st["kind"] == "datum_plane":
            bound_now.clear()
            try:
                row.update(datum_plane(st))
            except Exception as e:
                row.update(status="failed", error=str(e)[:300])
            rep["steps"].append(row)
            continue
        expected = load(st.get("brep"))
        made, tried = [], []
        ok = False
        if st["kind"] != "frozen":
            for vi, variant in enumerate(st.get("variants") or [{}]):
                bound_now.clear()
                try:
                    main = build(st, variant, made)
                    if body.Tip is not main:            # a pattern made by script does not move the tip itself
                        body.Tip = main
                    doc.recompute()
                    bad = broken(made)
                    if bad:
                        raise RuntimeError("did not recompute: " + ", ".join(bad))
                    dev = _dev(body.Tip.Shape, expected) if expected is not None else 0.0
                    if dev > TOL:
                        raise RuntimeError("recomputed to another solid (%.4f%% of the volume differs)" % (dev * 100))
                    ok = True
                    objs[st["feature"]] = main
                    row.update(status="decomposed" if st["kind"] == "prism" else "native", variant=vi, dev=dev,
                               objects=[o.Name for o in made], bound=sorted(set(bound_now)))
                    if (variant or {}).get("iso"):
                        row["iso"] = variant["iso"]
                    rep["bound"] += [b for b in bound_now if b not in rep["bound"]]
                    break
                except Exception as e:
                    tried.append(str(e)[:300])
                    remove(made)
        if not ok:
            try:
                made = frozen(st, expected)
                dev = _dev(body.Tip.Shape, expected)
                row.update(status="frozen" if dev <= TOL else "failed", dev=dev, objects=[o.Name for o in made])
            except Exception as e:
                row.update(status="failed", error=str(e)[:300])
        if tried:
            row["tried"] = tried
        rep["steps"].append(row)
    doc.recompute()
    final = _solid_of(doc)
    rep["freecad"] = _stats(final) if not final.isNull() else None
    exp = load(plan.get("final_brep"))
    if exp is not None and not final.isNull():
        rep["final_dev"] = _dev(final, exp)
    rep["invalid"] = [o.Name for o in doc.Objects if not o.isValid()]
    doc.saveAs(out_path)
    rep["file"] = out_path
    rep["ok"] = True
    return rep


def edit(path, cells):
    """Open a saved export, set spreadsheet cells by their alias, recompute: what FreeCAD makes of the edit."""
    import FreeCAD as App
    doc = App.openDocument(path)
    sheet = doc.getObject("Params")
    for name, value in cells.items():
        cell = sheet.getCellFromAlias(name)
        if not cell:
            raise RuntimeError("no cell named " + name)
        sheet.set(cell, repr(float(value)))
    doc.recompute()
    out = {"ok": True, "freecad": _stats(_solid_of(doc)), "invalid": [o.Name for o in doc.Objects if not o.isValid()]}
    App.closeDocument(doc.Name)
    return out


def main(plan, edit_cells=None):
    here = os.path.dirname(os.path.abspath(globals().get("__file__") or plan.get("script") or "."))
    if plan.get("here"):
        here = plan["here"]
    out = os.path.join(here, plan["fcstd"]) if not os.path.isabs(plan["fcstd"]) else plan["fcstd"]
    try:
        rep = run(plan, here, out)
        if edit_cells:
            rep["edit"] = edit(out, edit_cells)
    except Exception as e:
        import traceback
        rep = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "trace": traceback.format_exc()[-1500:]}
    _say(rep)
    return rep
