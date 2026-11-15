"""Screw-mounted wall hook with a stated load model.

The strength figures are a cantilever-beam estimate with an assumed material
strength and an assumed knock-down for layer adhesion. They rank designs and
flag obvious under-sizing. They are not a load rating.
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Box, Cone, Cylinder, Pos, Rot, fillet

from .base import Feature, Param, Recipe, RecipeError, Stage

PLA_DENSITY = 1.24e-3     # g/mm³


class WallHook(Recipe):
    id = "hook"
    title = "Wall hook"
    summary = "A two-screw wall hook sized to a load, with a bending-stress estimate and countersunk screw holes fitted to your screws."
    fit = {"cavity": "screw_hole", "mating": "screw_d", "clearance": "screw_clearance",
           "label": "Screw hole ↔ screw shank", "per_side": True, "window": [0.2, 1.0]}

    params = [
        Param("load_kg", "Load", 3.0, 0.1, 20, 0.1, "kg", "brief", "arm", "Heaviest thing you will hang, including a jerk when you hang it."),
        Param("screw_d", "Screw shank diameter", 4.0, 2, 8, 0.05, "mm", "brief", "screws", "Measure the shank, not the thread tips."),
        Param("screw_head_d", "Screw head diameter", 8.0, 4, 16, 0.1, "mm", "brief", "countersinks"),
        Param("screw_clearance", "Screw hole clearance / side", 0.25, 0, 1, 0.05, "mm", "interface", "screws"),
        Param("plate_w", "Plate width", 28, 12, 80, 0.5, "mm", "form", "plate"),
        Param("plate_h", "Plate height", 80, 30, 160, 0.5, "mm", "form", "plate"),
        Param("plate_t", "Plate thickness", 6, 3, 15, 0.1, "mm", "form", "plate"),
        Param("arm_len", "Arm reach", 40, 10, 120, 0.5, "mm", "form", "arm", "From the wall face of the plate to the tip."),
        Param("arm_t", "Arm thickness", 9, 3, 25, 0.1, "mm", "form", "arm", "Vertical depth of the arm; strength grows with its square."),
        Param("tip_h", "Tip height", 14, 4, 50, 0.5, "mm", "form", "tip"),
        Param("tip_t", "Tip thickness", 6, 3, 20, 0.1, "mm", "form", "tip"),
        Param("root_r", "Root fillet", 8, 0, 25, 0.5, "mm", "form", "root", "Spreads the stress where the arm meets the plate."),
        Param("screw_spacing", "Screw spacing", 40, 15, 140, 0.5, "mm", "form", "screws"),
        Param("strength_mpa", "Material strength", 40, 10, 120, 1, "MPa", "process", "arm",
              "Assumed flexural strength of the printed material. PLA is often quoted at 40–60 MPa."),
        Param("layer_factor", "Layer-adhesion factor", 0.5, 0.1, 1.0, 0.05, "", "process", "arm",
              "Fraction of the material strength trusted across layer lines. 0.5 is a common conservative assumption."),
    ]
    features = [
        Feature("plate", "Wall plate", "structure"),
        Feature("arm", "Arm", "structure"),
        Feature("tip", "Tip", "access", "Keeps the load from sliding off."),
        Feature("root", "Root fillet", "structure"),
        Feature("screws", "Screw holes", "interface"),
        Feature("countersinks", "Countersinks", "interface"),
        Feature("soften", "Edge softening", "finish"),
    ]

    @staticmethod
    def g(v):
        hole = v["screw_d"] + 2 * v["screw_clearance"]
        # above the root fillet, and high enough that a screwdriver clears the tip (shaft radius ~4 mm)
        z1 = max(v["arm_t"] + v["root_r"] + v["screw_head_d"] / 2 + 2.5, v["arm_t"] + v["tip_h"] + 4.5)
        z2 = z1 + v["screw_spacing"]
        cs = max(0.0, (v["screw_head_d"] - hole) / 2)            # 90° countersink depth
        return {"hole": hole, "z1": z1, "z2": z2, "cs": cs}

    def constraints(self, v):
        g, out = self.g(v), []
        if g["z2"] + v["screw_head_d"] / 2 + 2 > v["plate_h"]:
            out.append(RecipeError(f"Upper screw sits {g['z2']:.0f} mm up; the plate is {v['plate_h']:.0f} mm tall", "screws",
                                   "Raise the plate height or reduce the screw spacing.", ["plate_h", "screw_spacing"]))
        if v["screw_head_d"] + 3 > v["plate_w"]:
            out.append(RecipeError("Screw heads are wider than the plate allows", "countersinks", "Widen the plate.", ["plate_w", "screw_head_d"]))
        if g["cs"] > v["plate_t"] - 1.2:
            out.append(RecipeError("Countersink would leave under 1.2 mm of plate", "countersinks", "Thicken the plate or use smaller heads.",
                                   ["plate_t", "screw_head_d"]))
        if v["screw_head_d"] <= g["hole"]:
            out.append(RecipeError("Screw head is not larger than the hole", "countersinks", "Check the head and shank diameters.",
                                   ["screw_head_d", "screw_d"]))
        if v["tip_t"] > v["arm_len"] - 4:
            out.append(RecipeError("Tip is thicker than the arm is long", "tip", "Lengthen the arm or thin the tip.", ["tip_t", "arm_len"]))
        if v["root_r"] > min(v["arm_len"] - v["tip_t"] - 1, v["plate_h"] - v["arm_t"] - 1):
            out.append(RecipeError("Root fillet does not fit between plate, arm and tip", "root", "Reduce the root fillet.", ["root_r"]))
        return out

    def build(self, v):
        g = self.g(v)
        W, T = v["plate_w"], v["plate_t"]
        plate = Box(W, T, v["plate_h"], align=(Align.CENTER, Align.MIN, Align.MIN))
        stages = [Stage("plate", plate)]
        arm = Pos(0, T, 0) * Box(W, v["arm_len"], v["arm_t"], align=(Align.CENTER, Align.MIN, Align.MIN))
        s = plate + arm
        stages.append(Stage("arm", s))
        y_tip = T + v["arm_len"] - v["tip_t"]
        tip = Pos(0, y_tip, 0) * Box(W, v["tip_t"], v["arm_t"] + v["tip_h"], align=(Align.CENTER, Align.MIN, Align.MIN))
        s = s + tip
        stages.append(Stage("tip", s))
        if v["root_r"] > 0:
            root = [e for e in s.edges().filter_by(Axis.X)
                    if abs(e.center().Y - T) < 1e-6 and abs(e.center().Z - v["arm_t"]) < 1e-6]
            s = fillet(root, v["root_r"])
            stages.append(Stage("root", s))
        holes = None
        for z in (g["z1"], g["z2"]):
            c = Pos(0, T / 2, z) * Rot(90, 0, 0) * Cylinder(g["hole"] / 2, T + 2)
            holes = c if holes is None else holes + c
        s = s - holes
        stages.append(Stage("screws", s))
        if g["cs"] > 0:
            sinks = None
            for z in (g["z1"], g["z2"]):
                c = Pos(0, T - g["cs"], z) * Rot(-90, 0, 0) * Cone(g["hole"] / 2, v["screw_head_d"] / 2 + 0.01, g["cs"] + 0.01,
                                                                  align=(Align.CENTER, Align.CENTER, Align.MIN))
                sinks = c if sinks is None else sinks + c
            s = s - sinks
            stages.append(Stage("countersinks", s))
        r = min(1.5, v["tip_t"] / 2 - 0.3)
        top_tip = [e for e in s.edges().filter_by(Axis.X) if abs(e.center().Z - (v["arm_t"] + v["tip_h"])) < 1e-6]
        top_plate = [e for e in s.edges().filter_by(Axis.X) if abs(e.center().Z - v["plate_h"]) < 1e-6]
        try:
            s = fillet(top_tip + top_plate, r)
            stages.append(Stage("soften", s))
        except Exception:
            pass
        return stages

    def derived(self, v):
        g = self.g(v)
        return [
            {"key": "screw_hole", "label": "Screw hole diameter", "value": g["hole"], "unit": "mm", "feature": "screws",
             "formula": "shank + 2 × clearance", "interface": True},
            {"key": "upper_screw_z", "label": "Upper screw height", "value": g["z2"], "unit": "mm", "feature": "screws",
             "formula": "above fillet and screwdriver clearance over the tip, + spacing"},
            {"key": "countersink_depth", "label": "Countersink depth", "value": g["cs"], "unit": "mm", "feature": "countersinks",
             "formula": "(head − hole) / 2, 90°"},
        ]

    def measure(self, v, faces_by_feature):
        ds = [max(f.bounding_box().size.X, f.bounding_box().size.Z) for f in faces_by_feature.get("screws", [])
              if f.geom_type.name == "CYLINDER"]
        return [{"key": "screw_hole", "label": "Screw hole diameter", "intended": self.g(v)["hole"], "modelled": max(ds)}] if ds else []

    def statics(self, v, solid_volume_mm3, com):
        F = v["load_kg"] * 9.81
        L = v["arm_len"] - v["tip_t"] / 2                         # load hangs against the tip
        M = F * L                                                  # N·mm at the arm root
        sigma = 6 * M / (v["plate_w"] * v["arm_t"] ** 2)           # MPa, rectangular section
        allow = v["strength_mpa"] * v["layer_factor"]
        sf = allow / sigma if sigma > 0 else float("inf")
        g = self.g(v)
        lever = g["z2"] - v["arm_t"] / 2                           # pivot about the arm's line of action, simplified
        pull = M / max(lever, 1)                                   # N on the upper screw
        mass = solid_volume_mm3 * PLA_DENSITY
        status = "PASS" if sf >= 2 else ("WARN" if sf >= 1.2 else "FAIL")
        return {
            "safety_factor": sf, "root_stress_mpa": sigma, "upper_screw_pull_n": pull, "mass_g_solid": mass,
            "checks": [
                {"id": "strength", "label": "Arm bending safety factor", "status": status, "value": f"{sf:.1f}×",
                 "detail": f"Cantilever estimate: {F:.0f} N at {L:.0f} mm gives {sigma:.1f} MPa at the root against "
                           f"{allow:.0f} MPa allowed ({v['strength_mpa']:.0f} MPa × {v['layer_factor']:.2f} layer factor, both assumed). "
                           "Ignores the root fillet's relief and stress concentration. Target ≥ 2×.",
                 "evidence": "model", "feature": "arm"},
                {"id": "screw_pull", "label": "Upper screw pull-out load", "status": "PASS" if pull < 400 else "WARN",
                 "value": f"{pull:.0f} N",
                 "detail": "Moment divided by the lever to the upper screw. Wall anchors in drywall are often rated around 100–250 N; "
                           "check yours. The 400 N threshold is an assumption.",
                 "evidence": "model", "feature": "screws"},
            ],
        }

    def test_piece(self, v, shape):
        g = self.g(v)
        h = v["screw_head_d"] + 6
        slab = Pos(0, 0, g["z1"] - h / 2) * Box(v["plate_w"] + 2, v["plate_t"] + 2, h, align=(Align.CENTER, Align.MIN, Align.MIN))
        piece = Pos(0, 0, -(g["z1"] - h / 2)) * (shape & slab)
        return piece, {"label": "Screw tab", "doc": "A slice of the plate around the lower screw hole and countersink. "
                       "Checks the screw slides through and the head sits flush.", "height": h}
