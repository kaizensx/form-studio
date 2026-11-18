"""Shelf bracket: an L-bracket for a shelf of measured depth, with a sweeping web and a stated load model.

Printed on its side: the bracket's outline lies flat on the plate and is extruded up by the bracket's width, so
every layer is a complete L and the load runs along the extrusion lines instead of pulling layers apart. That makes
the screw holes horizontal in the print: they are teardrops, and the countersinks are 90° cones whose steepest face
is exactly 45°.

Frame (as printed, which is also how the model is drawn): the wall is the plane x = 0, "up" in use is +Y, the
shelf rests on the arm's top face at y = H, and the bracket's width runs along Z from the plate.

The strength figures are beam estimates with assumed material strength and layer factor; they rank designs and
flag under-sizing. They are not a load rating.
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Box, Cone, Plane, Polygon, Pos, Rot, extrude, fillet

from .base import Feature, Hardware, Param, Recipe, RecipeError, Stage
from .assembly import Access, Assembly, Part
from .style import FOOT, foot_chamfer, teardrop

PLA_DENSITY = 1.24e-3
SINK_HALF = 48.0      # countersink half-angle, degrees. 90° heads sit on its rim; the cone's top stays under 45° past
                      # vertical when the hole runs sideways in the print (a 90° cone is exactly 45°, and its facets tip over)


def sink(top_d: float, hole_d: float):
    """A countersink cone, wide end at z = 0 (top_d across), narrowing along +Z to the hole."""
    h = (top_d - hole_d) / 2 / math.tan(math.radians(SINK_HALF))
    return Cone(top_d / 2, hole_d / 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


class ShelfBracket(Recipe):
    id = "shelf_bracket"
    title = "Shelf bracket"
    summary = ("An L-bracket for a shelf of measured depth: a sweeping web, countersunk wall screws and a screw up "
               "into the shelf, printed on its side for strength, with a load estimate.")
    category = "Wall & desk"
    tags = ("shelf", "bracket", "wall", "mount", "load", "screws")
    fit = {"cavity": "screw_hole", "mating": "screw_d", "clearance": "screw_clearance",
           "label": "Wall screw hole ↔ screw shank", "per_side": True, "window": [0.2, 2.0]}

    params = [
        Param("shelf_depth", "Shelf depth", 200, 80, 400, 1, "mm", "brief", "arm",
              "Front to back. Measure the board; the arm reaches most of the way."),
        Param("shelf_t", "Shelf thickness", 18, 6, 40, 0.5, "mm", "brief", "shelf_screw",
              "Measure the board. Sets the length of the screw up into it."),
        Param("load_kg", "Load per bracket", 8, 0.5, 40, 0.5, "kg", "brief", "arm",
              "Half the shelf's contents for two brackets, including the shelf itself."),
        Param("screw_d", "Wall screw shank", 4.0, 3, 6, 0.05, "mm", "brief", "screws", "Measure the shank, not the thread tips."),
        Param("screw_head_d", "Wall screw head", 8.0, 5.5, 12, 0.1, "mm", "brief", "screws", "Countersunk (flat) head diameter."),
        Param("screw_clearance", "Screw hole clearance / side", 0.5, 0.1, 1.0, 0.05, "mm", "interface", "screws"),
        Param("arm", "Arm length", 160, 60, 170, 1, "mm", "form", "arm", "Along the shelf from the wall. About 0.8 × the shelf depth."),
        Param("height", "Wall leg height", 140, 60, 170, 1, "mm", "form", "leg"),
        Param("width", "Bracket width", 24, 12, 50, 1, "mm", "form", "leg", "Across the bracket; the printed height."),
        Param("arm_t", "Arm thickness", 10, 6, 25, 0.5, "mm", "form", "arm", "Vertical depth of the arm; strength grows with its square."),
        Param("leg_t", "Leg thickness", 9, 6, 25, 0.5, "mm", "form", "leg", "Against the wall."),
        Param("web_r", "Web radius", 55, 15, 120, 1, "mm", "form", "web",
              "The concave sweep filling the corner. Larger spreads the stress and looks calmer."),
        Param("edge_r", "Edge radius", 2.0, 0.6, 4, 0.1, "mm", "form", "soften"),
        Param("strength_mpa", "Material strength", 40, 10, 120, 1, "MPa", "process", "arm",
              "Assumed flexural strength of the printed material. PLA is often quoted at 40–60 MPa."),
        Param("layer_factor", "Layer-adhesion factor", 0.8, 0.1, 1.0, 0.05, "", "process", "arm",
              "Fraction of the material strength trusted. Printed on its side the load runs along the lines, so 0.8 rather than 0.5."),
    ]
    features = [
        Feature("leg", "Wall leg", "structure"),
        Feature("arm", "Shelf arm", "structure"),
        Feature("web", "Web", "structure", "Concave sweep from leg to arm."),
        Feature("screws", "Wall screw holes", "interface", "Teardrop clearance holes with 90° countersinks."),
        Feature("shelf_screw", "Shelf screw hole", "interface", "Up through the arm into the shelf."),
        Feature("soften", "Edge softening", "finish"),
    ]

    @staticmethod
    def g(v):
        hole = v["screw_d"] + 2 * v["screw_clearance"]
        H, T, L, tl, R = v["height"], v["arm_t"], v["arm"], v["leg_t"], v["web_r"]
        y_web = H - T - R                    # where the web starts on the leg
        y_low = min(14 + v["screw_head_d"] / 2, y_web * 0.35)
        y_up = H - T - R * 0.42              # through the web, as high as the sweep allows
        cs = max(0.0, (v["screw_head_d"] - hole) / 2)
        x_sh = tl + R + max(12.0, (L - tl - R) * 0.45)
        return {"hole": hole, "H": H, "T": T, "L": L, "tl": tl, "R": R, "y_web": y_web, "y_low": y_low, "y_up": y_up,
                "cs": cs, "x_sh": x_sh, "sh_hole": 3.5 + 2 * 0.25}

    def constraints(self, v):
        g, out = self.g(v), []
        if g["y_web"] < 20:
            out.append(RecipeError(f"The web reaches {g['H'] - g['y_web']:.0f} mm down a {g['H']:.0f} mm leg", "web",
                                   "Make the leg taller or the web radius smaller.", ["height", "web_r"]))
        if g["tl"] + g["R"] > g["L"] - 25:
            out.append(RecipeError("The web reaches past the arm", "web", "Lengthen the arm or reduce the web radius.", ["arm", "web_r"]))
        if v["arm"] > v["shelf_depth"]:
            out.append(RecipeError("The arm is longer than the shelf is deep", "arm", "Shorten the arm.", ["arm", "shelf_depth"]))
        if v["screw_head_d"] + 4 > v["width"]:
            out.append(RecipeError("Screw heads are too wide for the bracket", "screws", "Widen the bracket or use smaller screws.",
                                   ["width", "screw_head_d"]))
        if g["cs"] > v["leg_t"] - 2.4:
            out.append(RecipeError("Countersink leaves under 2.4 mm of leg", "screws", "Thicken the leg or use smaller heads.",
                                   ["leg_t", "screw_head_d"]))
        if v["screw_head_d"] <= g["hole"] + 0.5:
            out.append(RecipeError("Screw head is not larger than the hole", "screws", "Check the head and shank diameters.",
                                   ["screw_head_d", "screw_d"]))
        if g["y_up"] - g["y_low"] < 25:
            out.append(RecipeError("The two wall screws are under 25 mm apart", "screws", "Make the leg taller.", ["height"]))
        return out

    # the countersunk hole along -X from the leg's inner face (x = leg_t) through to the wall, and for the upper screw
    # a teardrop tunnel from the leg face out through the web so a driver reaches it
    def _wall_hole(self, v, y, tunnel: bool):
        g = self.g(v)
        z = v["width"] / 2
        tl = g["tl"]
        hole = Pos(tl / 2, y, z) * teardrop(g["hole"], tl + 2, Plane.YZ)
        cs = Pos(tl + 0.01, y, z) * Rot(0, -90, 0) * sink(v["screw_head_d"] + 0.4, g["hole"])
        cut = hole + cs
        if tunnel:
            d = v["screw_head_d"] + 1.0
            cut = cut + Pos(tl + g["R"] / 2 + 2, y, z) * teardrop(d, g["R"] + 4, Plane.YZ)
        return cut

    def build(self, v):
        g = self.g(v)
        H, T, L, tl, R, W = g["H"], g["T"], g["L"], g["tl"], g["R"], v["width"]
        rl = min(tl * 0.5, 6)
        leg_prof = Plane.XY * Polygon((0, 0), (tl, 0), (tl, H), (0, H), align=None)
        leg = extrude(leg_prof, W)
        stages = [Stage("leg", leg)]
        arm_prof = Plane.XY * Polygon((0, H - T), (L, H - T), (L, H), (0, H), align=None)
        s = leg + extrude(arm_prof, W)
        stages.append(Stage("arm", s))
        # web: the corner square minus a quarter circle centred out in the open
        from build123d import Circle
        sq = Plane.XY * Polygon((tl - 0.01, g["y_web"]), (tl + R, g["y_web"]), (tl + R, H - T + 0.01), (tl - 0.01, H - T + 0.01), align=None)
        web_prof = sq - Plane.XY * Pos(tl + R, g["y_web"]) * Circle(R)
        s = s + extrude(web_prof, W)
        stages.append(Stage("web", s))
        # round the arm tip underside and the leg foot (in plan: these are vertical edges of the print)
        tips = [e for e in s.edges().filter_by(Axis.Z)
                if (abs(e.center().X - L) < 1e-3 and abs(e.center().Y - (H - T)) < 1e-3)
                or (abs(e.center().X - tl) < 1e-3 and abs(e.center().Y) < 1e-3)]
        try:
            s = fillet(tips, min(T * 0.6, rl * 1.5))
        except Exception:
            pass
        s = s - self._wall_hole(v, g["y_low"], False) - self._wall_hole(v, g["y_up"], True)
        stages.append(Stage("screws", s))
        # shelf screw: up through the arm, countersunk from below
        z = W / 2
        sh = Pos(g["x_sh"], H - T / 2, z) * teardrop(g["sh_hole"], T + 2, Plane.XZ)
        cone = Pos(g["x_sh"], H - T - 0.01, z) * Rot(-90, 0, 0) * sink(7.4, g["sh_hole"])
        s = s - sh - cone
        stages.append(Stage("shelf_screw", s))
        # soften: round the outline on the top face, chamfer the plate face (45°: no overhang)
        r = min(v["edge_r"], W / 6, T / 4, tl / 4)
        top = [e for e in s.edges() if abs(e.center().Z - W) < 1e-4 and e.bounding_box().size.Z < 1e-4]
        for rr in (r, r * 0.5):
            try:
                s = fillet(top, rr)
                break
            except Exception:
                pass
        s = foot_chamfer(s, FOOT)
        stages.append(Stage("soften", s))
        return stages

    def derived(self, v):
        g = self.g(v)
        return [
            {"key": "screw_hole", "label": "Wall screw hole", "value": g["hole"], "unit": "mm", "feature": "screws",
             "formula": "shank + 2 × clearance", "interface": True},
            {"key": "screw_spacing", "label": "Wall screw spacing", "value": g["y_up"] - g["y_low"], "unit": "mm", "feature": "screws",
             "formula": "upper screw in the web, lower near the foot", "interface": False},
            {"key": "shelf_screw_len", "label": "Shelf screw length", "value": v["arm_t"] + 0.6 * v["shelf_t"], "unit": "mm",
             "feature": "shelf_screw", "formula": "arm + 0.6 × shelf thickness (round down to a stock length)", "interface": False},
        ]

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        ds = []
        for f in faces_by_feature.get("screws", []):
            if f.geom_type.name == "CYLINDER" and abs(f.center().X - g["tl"] / 2) < g["tl"]:
                bb = f.bounding_box()
                if bb.size.X > 1:              # the clearance hole, not the tunnel or cone
                    ds.append(2 * f.radius if hasattr(f, "radius") else bb.size.Y)
        ds = [d for d in ds if abs(d - g["hole"]) < 1.0]
        return [{"key": "screw_hole", "label": "Wall screw hole", "intended": g["hole"], "modelled": ds[0]}] if ds else []

    def statics(self, v, solid_volume_mm3, com):
        g = self.g(v)
        F = v["load_kg"] * 9.81
        d = v["shelf_depth"]
        w = F / d                                                  # N/mm, shelf load spread evenly front to back
        x0 = g["tl"] + g["R"]                                      # where the web ends: the arm's critical section
        M_arm = w * max(d - x0, 0) ** 2 / 2 if x0 < d else 0.0
        sigma = 6 * M_arm / (v["width"] * v["arm_t"] ** 2)
        allow = v["strength_mpa"] * v["layer_factor"]
        sf = allow / sigma if sigma > 0 else float("inf")
        M0 = F * d / 2                                             # about the leg's foot, where it presses the wall
        yl, yu = g["y_low"], g["y_up"]
        pull = M0 * yu / (yu ** 2 + yl ** 2)                       # screws share the moment in proportion to their lever
        status = "PASS" if sf >= 2 else ("WARN" if sf >= 1.2 else "FAIL")
        return {
            "safety_factor": sf, "arm_stress_mpa": sigma, "upper_screw_pull_n": pull, "mass_g_solid": solid_volume_mm3 * PLA_DENSITY,
            "checks": [
                {"id": "strength", "label": "Arm bending safety factor", "status": status, "value": f"{sf:.1f}×",
                 "detail": f"Beam estimate: {F:.0f} N spread over a {d:.0f} mm shelf gives {sigma:.1f} MPa in the arm where the web "
                           f"ends ({x0:.0f} mm from the wall) against {allow:.0f} MPa allowed ({v['strength_mpa']:.0f} MPa × "
                           f"{v['layer_factor']:.2f}, both assumed). Ignores stress concentration at the shelf screw. Target ≥ 2×.",
                 "evidence": "model", "feature": "arm"},
                {"id": "screw_pull", "label": "Upper screw pull-out load", "status": "PASS" if pull < 400 else "WARN",
                 "value": f"{pull:.0f} N",
                 "detail": "Moment about the leg's foot shared by the two wall screws in proportion to their height. "
                           "Plugs in masonry hold far more; drywall anchors are often rated 100–250 N, check yours. "
                           "The 400 N threshold is an assumption.",
                 "evidence": "model", "feature": "screws"},
            ],
        }

    def companions(self, v):
        return [{"label": "Shelf", "size": [v["width"] + 160, v["shelf_t"], v["shelf_depth"]],
                 "origin": [v["shelf_depth"] / 2, v["height"] + v["shelf_t"] / 2, v["width"] / 2], "rot_x_deg": 0, "anchor": "center"}]

    def assembly(self, v):
        g = self.g(v)
        z = v["width"] / 2
        return Assembly(
            parts=[Part("bracket", "Bracket", 0, note="Hold the bracket against the wall, arm level, and mark the two holes.")],
            hardware=[Hardware("Wall screw", f"Ø{v['screw_d']:g} countersunk, ≥ {v['leg_t'] + 30:.0f} mm", 2,
                               "Wood screw into a stud, or with a plug or anchor rated for the load",
                               "Drive the lower screw, level the bracket, then the upper one through the web.", after="bracket",
                               access=(Access(at=(g["tl"], g["y_up"], z), axis=(-1, 0, 0), tool_d=6, length=g["R"] + 10),)),
                      Hardware("Shelf screw", f"Ø3.5 × {math.floor((v['arm_t'] + 0.6 * v['shelf_t']) / 5) * 5:.0f} countersunk", 1,
                               "Chipboard screw", "Lay the shelf on and screw up through the arm.", after="bracket")])
