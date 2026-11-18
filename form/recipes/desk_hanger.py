"""Desk hanger: an under-desk hook for headphones, a game controller or a bag, that clamps onto the desk's edge or
screws under it.

One profile, printed on its side, so the arm's layers run along it (its strongest direction) and nothing needs support:
a C-clamp (or a screw plate) at the top, a spine down past the desk's underside, and an arm under the desk with a
lip at its end. The headband rests across the arm's width; every edge it touches is chamfered on both faces.

The clamp's pads sit a little closer than the desk is thick, so its jaws spring open and grip. The load models are
beam estimates with an assumed material strength; they rank designs and flag under-sizing, they are not a rating.
"""
from __future__ import annotations

import math

from build123d import Axis, Plane, Polygon, Pos, Rectangle, chamfer, extrude, fillet

from .base import Feature, Param, Recipe, RecipeError, Stage
from .style import teardrop

E_MPA = 3500.0        # assumed modulus for the clamp-force estimate (PLA is often quoted at 3.5 GPa)
PAD = 10.0            # length of the flat pads at the jaw tips
RELIEF = 0.8          # the jaws stand this far off the desk between the spine and the pads


def foot(shape, w: float = 0.3, h: float = 0.5):
    """Chamfer the edges on the print plate, w in and h up: steeper than 45°, so the faceted chamfer round a curved
    edge never reads as an overhang, and it still hides the first layer's flare."""
    z0 = shape.bounding_box().min.Z
    cs = [f.center() for f in shape.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z - z0) < 1e-6
          and f.normal_at().Z < -0.999]
    for c in cs:
        try:
            f = min((f for f in shape.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z - z0) < 1e-6
                     and f.normal_at().Z < -0.999), key=lambda f: (f.center() - c).length)
            shape = chamfer(f.edges(), length=w, length2=h, reference=f)
        except Exception:
            pass
    return shape


def _at(prof, pts, r):
    """Fillet the profile's vertices nearest each of pts (2D), skipping any OCCT refuses."""
    vs = []
    for x, y in pts:
        near = [p for p in prof.vertices() if abs(p.X - x) < 1e-5 and abs(p.Y - y) < 1e-5]
        vs += near
    if not vs or r <= 0.05:
        return prof
    try:
        return fillet(vs, r)
    except Exception:
        out = prof
        for v_ in vs:
            try:
                out = fillet([p for p in out.vertices() if (p - v_).length < 1e-5], r)
            except Exception:
                pass
        return out


class DeskHanger(Recipe):
    id = "desk_hanger"
    title = "Under-desk hanger"
    summary = ("An under-desk hook for headphones or a controller that clamps onto the desk's edge or screws under it. "
               "Printed on its side for strength; no supports.")
    category = "Wall & desk"
    tags = ("headphones", "headset", "controller", "desk", "under desk", "hanger", "hook", "clamp", "gaming")

    params = [
        Param("mount", "Mount", 0, 0, 1, 1, "", "form", "clamp",
              "0 = clamp onto the desk's edge (no tools), 1 = screw plate under the desk."),
        Param("desk_t", "Desk thickness", 25, 10, 60, 0.1, "mm", "brief", "clamp",
              "Clamp: measure the desk top's edge with calipers or a ruler."),
        Param("grip", "Grip / side", -0.3, -0.8, 0.3, 0.05, "mm", "interface", "clamp",
              "Clamp: gap between each pad and the desk. Negative = interference, so the jaws spring onto the desk."),
        Param("jaw", "Jaw length", 40, 20, 80, 0.5, "mm", "form", "clamp", "Clamp: how far the jaws reach over the desk."),
        Param("jaw_t", "Jaw thickness", 4.5, 3, 10, 0.1, "mm", "form", "clamp"),
        Param("width", "Width", 40, 20, 70, 0.5, "mm", "brief", "arm",
              "Along the desk edge: at least the headband's width. Most headbands are 30–45 mm."),
        Param("drop", "Clearance under the desk", 40, 15, 80, 0.5, "mm", "brief", "spine",
              "From the desk's underside to the top of the arm: the headband's thickness plus room to lift it off."),
        Param("reach", "Arm reach", 60, 30, 120, 0.5, "mm", "form", "arm", "From the spine to the end of the lip."),
        Param("arm_t", "Arm thickness", 8, 6, 20, 0.5, "mm", "form", "arm", "Strength grows with its square."),
        Param("lip_h", "Lip height", 12, 4, 30, 0.5, "mm", "form", "lip", "Keeps the headband from sliding off the end."),
        Param("spine_t", "Spine thickness", 6, 4, 14, 0.5, "mm", "form", "spine"),
        Param("plate_len", "Screw plate length", 50, 30, 90, 0.5, "mm", "form", "plate", "Screw mount: forward of the spine."),
        Param("plate_t", "Screw plate thickness", 6, 4, 12, 0.5, "mm", "form", "plate"),
        Param("screw_d", "Screw diameter", 4.0, 3.0, 5.0, 0.1, "mm", "brief", "screws",
              "Screw mount: shank of a pan- or washer-head wood screw.", "specified"),
        Param("edge", "Edge softening", 1.2, 0.4, 3.0, 0.1, "mm", "form", "soften",
              "Chamfer on both faces of every edge, so the headband rests on no sharp corner."),
        Param("load_kg", "Load", 0.5, 0.1, 5, 0.05, "kg", "brief", "arm",
              "Heaviest thing it will hold. Headphones are 0.2–0.4 kg."),
        Param("strength_mpa", "Material strength", 40, 10, 120, 1, "MPa", "process", "arm",
              "Assumed flexural strength of the printed material (PLA is often quoted at 40–60 MPa)."),
    ]
    features = [
        Feature("clamp", "Desk clamp", "interface", "Two jaws whose flat pads spring onto the desk edge."),
        Feature("plate", "Screw plate", "interface", "Lies against the desk's underside."),
        Feature("screws", "Screw holes", "interface", "Teardrop holes: they print across the plate without support."),
        Feature("spine", "Spine", "structure"),
        Feature("arm", "Arm", "structure", "The headband rests across it."),
        Feature("lip", "Lip", "access", "Keeps what hangs from sliding off."),
        Feature("soften", "Edges", "finish"),
    ]

    # ---- helpers ------------------------------------------------------------------------------------------------
    def g(self, v) -> dict:
        m = int(round(v["mount"]))
        G = v["desk_t"] + 2 * v["grip"]
        sp, at = v["spine_t"], v["arm_t"]
        under = -v["jaw_t"] if m == 0 else -v["plate_t"]       # underside of the lower jaw or the plate
        ya = -v["drop"] if m == 0 else -v["drop"]               # arm top, below the desk's underside (y = 0)
        ya = min(ya, under - 4)
        lip_t = max(5.0, at * 0.6)
        holes = []
        if m == 1:
            e = max(8.0, v["screw_d"] * 2)
            holes = [-sp - e, -sp - v["plate_len"] + e]
        return {"m": m, "G": G, "sp": sp, "at": at, "under": under, "ya": ya, "lip_t": lip_t, "holes": holes,
                "saddle": v["reach"] - lip_t}

    def constraints(self, v):
        if abs(v["mount"] - round(v["mount"])) > 1e-9:
            return [RecipeError("Mount must be 0 or 1", "clamp", "Use 0 (clamp) or 1 (screw plate).", ["mount"])]
        g, out = self.g(v), []
        if g["saddle"] < 20:
            out.append(RecipeError("The arm leaves under 20 mm to hang anything on", "arm", "Lengthen the arm.", ["reach", "arm_t"]))
        if v["edge"] * 2 > min(v["arm_t"], v["width"]) / 2:
            out.append(RecipeError("The edge chamfer is too large for the arm", "soften", "Reduce the edge softening.", ["edge"]))
        if g["m"] == 0:
            if g["G"] < 6:
                out.append(RecipeError("The jaw gap is under 6 mm", "clamp", "Check the desk thickness.", ["desk_t", "grip"]))
            if v["jaw"] < PAD + 6:
                out.append(RecipeError("The jaws are too short for their pads", "clamp", "Lengthen the jaws.", ["jaw"]))
        else:
            if v["plate_len"] < 2 * max(8.0, v["screw_d"] * 2) + 6:
                out.append(RecipeError("The screw plate is too short for two screws", "screws", "Lengthen the plate.", ["plate_len"]))
            if v["plate_len"] + v["spine_t"] + v["reach"] > 175:
                out.append(RecipeError(f"The hanger is {v['plate_len'] + v['spine_t'] + v['reach']:.0f} mm long; keep it under 175 mm "
                                       "so it fits a small printer's bed", "plate", "Shorten the plate or the arm.",
                                       ["plate_len", "reach"]))
            if v["screw_d"] + 3 > v["width"]:
                out.append(RecipeError("The screw is wider than the plate allows", "screws", "Widen the hanger.", ["width", "screw_d"]))
        return out

    # ---- geometry: the profile in X (into the desk) and Y (up); the desk's underside at y = 0, its edge at x = 0 ----
    def build(self, v):
        g = self.g(v)
        W, sp, at, ya = v["width"], g["sp"], g["at"], g["ya"]
        ex = lambda prof: extrude(prof, W, dir=(0, 0, 1))
        stages = []
        if g["m"] == 0:
            G, jt, jaw = g["G"], v["jaw_t"], v["jaw"]
            top = Polygon((-sp, -jt), (jaw, -jt), (jaw, 0), (jaw - PAD, 0), (jaw - PAD, -RELIEF), (0, -RELIEF), (0, G + RELIEF),
                          (jaw - PAD, G + RELIEF), (jaw - PAD, G), (jaw, G), (jaw, G + jt), (-sp, G + jt), align=None)
            # the clamp's own corners: round outside, a root fillet inside, a lead-in at each pad
            top = _at(top, [(-sp, G + jt), (jaw, G + jt), (jaw, -jt)], min(jt / 2 - 0.05, 3.0))
            top = _at(top, [(0, -RELIEF), (0, G + RELIEF)], min(4.0, jaw - PAD - 1))
            top = chamfer([p for p in top.vertices() if (abs(p.X - jaw) < 1e-5 and abs(p.Y - G) < 1e-5)
                           or (abs(p.X - jaw) < 1e-5 and abs(p.Y) < 1e-5)], 1.2)
            stages.append(Stage("clamp", ex(top)))
            head = top
            y_head = -jt
        else:
            pl, pt = v["plate_len"], v["plate_t"]
            head = Pos(-sp - pl / 2 + 0.01, -pt / 2) * Rectangle(pl + sp, pt)
            head = _at(head, [(-sp - pl, 0), (-sp - pl, -pt)], min(pt / 2 - 0.05, 3.0))
            stages.append(Stage("plate", ex(head)))
            y_head = -pt
        spine = Pos(-sp / 2, (y_head + ya - at) / 2 + 0.01) * Rectangle(sp, y_head - (ya - at) + 0.02)
        prof = head + spine
        stages.append(Stage("spine", ex(prof)))
        arm = Pos((v["reach"] - sp) / 2, ya - at / 2) * Rectangle(v["reach"] + sp, at)
        prof = prof + arm
        r_root = min(12.0, (y_head - ya) * 0.6, g["saddle"] * 0.4)
        prof = _at(prof, [(0, ya)], r_root)                     # inside corner, spine to arm
        if g["m"] == 0:
            prof = _at(prof, [(0, y_head)], min(3.0, (y_head - ya) * 0.3))
        prof = _at(prof, [(-sp, ya - at)], min(at, 8.0))         # the hanger's lowest outside corner
        stages.append(Stage("arm", ex(prof)))
        lt = g["lip_t"]
        lip = Pos(v["reach"] - lt / 2, ya - at + (at + v["lip_h"]) / 2) * Rectangle(lt, at + v["lip_h"])
        prof = prof + lip
        prof = _at(prof, [(v["reach"], ya - at)], min(at / 2, 6.0))
        prof = _at(prof, [(v["reach"], ya + v["lip_h"]), (v["reach"] - lt, ya + v["lip_h"])], lt / 2 - 0.05)
        prof = _at(prof, [(v["reach"] - lt, ya)], min(v["lip_h"] * 0.6, 6.0))
        s = ex(prof)
        stages.append(Stage("lip", s))
        if g["m"] == 1:
            pt = v["plate_t"]
            for x in g["holes"]:
                pl_ = Plane(origin=(x, -pt / 2, W / 2), x_dir=(-1, 0, 0), z_dir=(0, 1, 0))
                s = s - teardrop(v["screw_d"] + 0.5, pt + 2, pl_)
            stages.append(Stage("screws", s))
        s = foot(s, w=v["edge"] * 0.75, h=v["edge"])
        try:
            s = chamfer(s.edges().group_by(Axis.Z)[-1], v["edge"])
        except Exception:
            pass
        stages.append(Stage("soften", s))
        return stages

    # ---- interfaces ---------------------------------------------------------------------------------------------
    def derived(self, v):
        g = self.g(v)
        out = [{"key": "saddle", "label": "Saddle length", "value": g["saddle"], "unit": "mm", "feature": "arm",
                "formula": "arm reach − lip thickness", "interface": False}]
        if g["m"] == 0:
            out.insert(0, {"key": "jaw_gap", "label": "Jaw gap at the pads", "value": g["G"], "unit": "mm", "feature": "clamp",
                           "formula": "desk thickness + 2 × grip", "interface": True})
        else:
            out.insert(0, {"key": "screw_hole", "label": "Screw hole", "value": v["screw_d"] + 0.5, "unit": "mm",
                           "feature": "screws", "formula": "screw + 0.5", "interface": True})
        return out

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        if g["m"] == 0:
            pads = [f for f in faces_by_feature.get("clamp", []) if f.geom_type.name == "PLANE"
                    and abs(abs(f.normal_at().Y) - 1) < 1e-6 and -0.01 < f.center().Y < g["G"] + 0.01]
            ys = sorted(f.center().Y for f in pads)
            return [{"key": "jaw_gap", "label": "Jaw gap at the pads", "intended": g["G"], "modelled": ys[-1] - ys[0]}] \
                if len(ys) >= 2 else []
        rs = [f.radius for f in faces_by_feature.get("screws", []) if f.geom_type.name == "CYLINDER"]
        return [{"key": "screw_hole", "label": "Screw hole", "intended": v["screw_d"] + 0.5, "modelled": 2 * max(rs)}] if rs else []

    # ---- load model ---------------------------------------------------------------------------------------------
    def statics(self, v, solid_volume_mm3, com):
        g = self.g(v)
        F = v["load_kg"] * 9.81
        W = v["width"]
        x_load = g["saddle"] / 2                                # the headband rests about mid-saddle
        allow = v["strength_mpa"] * 0.8                          # printed on its side: the arm bends along its layers
        M = F * x_load
        sig = 6 * M / (W * g["at"] ** 2)
        sf = allow / sig if sig > 0 else float("inf")
        st = lambda k: "PASS" if k >= 2 else ("WARN" if k >= 1.2 else "FAIL")
        checks = [{"id": "strength", "label": "Arm bending safety factor", "status": st(sf), "value": f"{sf:.1f}×",
                   "detail": f"Cantilever: {F:.1f} N at {x_load:.0f} mm from the spine on a {W:g} × {g['at']:g} mm arm gives "
                             f"{sig:.2f} MPa at the root against {allow:.0f} MPa ({v['strength_mpa']:.0f} MPa × 0.8, assumed; printed "
                             "on its side the arm bends along its layers). Ignores the root fillet's relief. Target ≥ 2×.",
                   "evidence": "model", "feature": "arm"}]
        out = {"safety_factor": sf, "arm_stress_mpa": sig}
        if g["m"] == 0:
            x_p = v["jaw"] - PAD / 2
            s_j = 6 * F * x_p / (W * v["jaw_t"] ** 2)
            sf_j = allow / s_j if s_j > 0 else float("inf")
            d = max(0.0, -v["grip"])
            I = W * v["jaw_t"] ** 3 / 12
            Fc = 3 * E_MPA * I * d / (v["jaw"] - PAD / 2) ** 3
            out["safety_factor"] = min(sf, sf_j)
            out["clamp_force_n"] = Fc
            checks.append({"id": "jaw", "label": "Upper jaw safety factor", "status": st(sf_j), "value": f"{sf_j:.1f}×",
                           "detail": f"The upper jaw carries the load from its pad, {x_p:.0f} mm from the spine: {s_j:.2f} MPa "
                                     f"against {allow:.0f} MPa (assumed). A beam estimate. Target ≥ 2×.",
                           "evidence": "model", "feature": "clamp"})
            checks.append({"id": "clamp", "label": "Clamp grip", "status": "PASS" if Fc >= 5 or d == 0 else "WARN",
                           "value": f"{Fc:.0f} N",
                           "detail": f"The pads are {2 * d:.2f} mm closer than the desk is thick; each jaw opens {d:.2f} mm and "
                                     f"presses about {Fc:.0f} N on the desk (E = {E_MPA:.0f} MPa assumed). Measure the desk: "
                                     "the grip is only as good as that number.", "evidence": "model", "feature": "clamp"})
        else:
            xs = g["holes"]
            front = -g["sp"] - v["plate_len"]                    # the plate tips about its front edge
            arm_ = F * (x_load - front)
            T = arm_ * max(x - front for x in xs) / sum((x - front) ** 2 for x in xs)
            out["screw_pull_n"] = T
            checks.append({"id": "screw_pull", "label": "Screw pull-out load", "status": "PASS" if T < 200 else "WARN",
                           "value": f"{T:.0f} N",
                           "detail": "The plate tips about its front edge; the screw nearest the spine takes most of it. Wood screws "
                                     "in a particle-board desk hold a few hundred newtons; the 200 N threshold is an assumption.",
                           "evidence": "model", "feature": "screws"})
        out["checks"] = checks
        return out
