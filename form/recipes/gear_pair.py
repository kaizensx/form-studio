"""Spur gear pair on a plate: two involute gears with axle bores, and a plate with axle pegs at the centre distance.

Gears come from py_gearworks (via form/parts.py; needs the [parts] extra). Backlash is made by thinning the
teeth, so the axles sit at the standard centre distance m (z1 + z2) / 2. The tooth-strength figure is a Lewis
bending estimate with an assumed material strength: it ranks designs, it is not a rating.
"""
from __future__ import annotations

import math

from build123d import Align, Box, Cone, Cylinder, Pos

from .. import parts
from .base import Feature, Param, Recipe, RecipeError, Stage
from ..parts import checked

A = (Align.CENTER, Align.CENTER, Align.MIN)
GAP = 6.0


class GearPair(Recipe):
    id = "gear_pair"
    title = "Spur gear pair"
    summary = ("Two printable involute spur gears and a plate with axle pegs at the right centre distance, "
               "with a mesh check (centre distance, backlash, contact ratio) and a tooth-strength estimate.")
    solids = 3
    fit = {"cavity": "gear_bore", "mating": "axle_d", "clearance": "bore_clearance",
           "label": "Gear bore ↔ axle", "per_side": True, "window": [0.2, 0.8]}

    params = [
        Param("module", "Module", 1.5, 0.8, 4, 0.1, "mm", "form", "gear_a",
              "Tooth size: pitch diameter = module × teeth. 1.5 or more prints cleanly with a 0.4 mm nozzle."),
        Param("teeth_a", "Teeth, small gear", 15, 8, 60, 1, "", "form", "gear_a"),
        Param("teeth_b", "Teeth, large gear", 30, 8, 120, 1, "", "form", "gear_b"),
        Param("thickness", "Gear thickness", 6, 3, 20, 0.5, "mm", "form", "gear_a", "Face width."),
        Param("backlash", "Backlash", 0.25, 0.0, 0.8, 0.05, "mm", "interface", "gear_b",
              "Total play between teeth, along the line of action. Printed teeth need some; 0.2–0.4 mm is a common start."),
        Param("axle_d", "Axle diameter", 5, 2, 12, 0.05, "mm", "brief", "pegs",
              "Printed peg diameter, or the metal pin you will use (measure it)."),
        Param("bore_clearance", "Bore clearance / side", 0.25, 0, 0.6, 0.05, "mm", "interface", "bores"),
        Param("pegs", "Axles", 1, 0, 1, 1, "", "interface", "pegs", "1 = pegs printed on the plate, 0 = holes for metal pins."),
        Param("pin_press", "Pin press / side", 0.05, 0, 0.3, 0.01, "mm", "interface", "pegs",
              "With metal pins: the plate hole is this much smaller per side than the pin."),
        Param("plate_t", "Plate thickness", 4, 2, 12, 0.5, "mm", "form", "plate"),
        Param("plate_margin", "Plate margin", 4, 1, 20, 0.5, "mm", "form", "plate", "Beyond the gear tips."),
        Param("torque", "Torque on the small gear", 150, 0, 5000, 10, "N·mm", "brief", "gear_a",
              "What the small gear drives. 150 N·mm is about a small geared hobby motor."),
        Param("strength_mpa", "Material strength", 40, 10, 120, 1, "MPa", "process", "gear_a",
              "Assumed bending strength of the printed teeth (PLA is often quoted at 40–60 MPa)."),
    ]
    features = [
        Feature("plate", "Plate", "structure"),
        Feature("pegs", "Axle pegs", "interface"),
        Feature("gear_a", "Small gear", "structure"),
        Feature("gear_b", "Large gear", "structure"),
        Feature("bores", "Gear bores", "interface"),
    ]

    @staticmethod
    def g(v):
        m, za, zb = v["module"], int(round(v["teeth_a"])), int(round(v["teeth_b"]))
        C = parts.centre_distance(m, za, zb)
        ra, rb = m * (za + 2) / 2, m * (zb + 2) / 2
        bore = v["axle_d"] + 2 * v["bore_clearance"]
        collar_h = 0.6
        Ra, Rb = ra + v["plate_margin"], rb + v["plate_margin"]
        eps, eps_src = (parts.contact_ratio_modelled(m, za, zb, round(v["backlash"], 4)) if min(za, zb) >= 6
                        else (parts.contact_ratio(m, za, zb), "standard formula"))
        y_gears = -(max(Ra, Rb) + GAP + max(ra, rb))            # gears printed in a row in front of the plate
        return {"eps": eps, "eps_src": eps_src, "m": m, "za": za, "zb": zb, "C": C, "ra": ra, "rb": rb, "bore": bore, "collar_h": collar_h,
                "Ra": Ra, "Rb": Rb, "y_gears": y_gears, "xb_print": ra + GAP + rb,
                "peg_h": collar_h + v["thickness"] + 1.0}

    def constraints(self, v):
        out = []
        for k in ("teeth_a", "teeth_b", "pegs"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        if out:
            return out
        g = self.g(v)
        if v["teeth_b"] < v["teeth_a"]:
            out.append(RecipeError("The large gear has fewer teeth than the small one", "gear_b", "Swap the tooth counts.",
                                   ["teeth_a", "teeth_b"]))
        root_a = g["m"] * (g["za"] - 2.4)
        if g["bore"] > root_a - 2.4:
            out.append(RecipeError(f"The Ø{g['bore']:.1f} bore leaves under 1.2 mm below the small gear's teeth", "bores",
                                   "Use a thinner axle, more teeth or a bigger module.", ["axle_d", "teeth_a", "module"]))
        if v["module"] * min(g["za"], g["zb"]) < 8:
            out.append(RecipeError("Small gear is too small to print", "gear_a", "Use more teeth or a bigger module.",
                                   ["teeth_a", "module"]))
        width = g["Ra"] + g["C"] + g["Rb"]
        depth = 2 * max(g["Ra"], g["Rb"]) + GAP + 2 * max(g["ra"], g["rb"])
        if width > 250 or depth > 250:
            out.append(RecipeError(f"Plate and gears need {width:.0f} × {depth:.0f} mm of bed", "plate",
                                   "Use fewer teeth or a smaller module.", ["teeth_b", "module"]))
        if g["eps"] < 1.0:
            out.append(RecipeError(f"Contact ratio {g['eps']:.2f} is below 1: the gears would lose contact", "gear_a",
                                   "Use more teeth.", ["teeth_a", "teeth_b"]))
        if v["axle_d"] < 3 and v["pegs"]:
            out.append(RecipeError("Printed pegs under 3 mm snap easily", "pegs", "Use a thicker axle or metal pins.", ["axle_d", "pegs"]))
        return out

    def _pair(self, v):
        g = self.g(v)
        return parts.gear_pair(g["m"], g["za"], g["zb"], v["thickness"], 0, 0, v["backlash"])

    def build(self, v):
        g = self.g(v)
        C, t = g["C"], v["plate_t"]
        # plate: two discs under the axles joined by a web
        web_h = 2 * min(g["Ra"], g["Rb"])
        plate = Cylinder(g["Ra"], t, align=A) + Pos(C, 0, 0) * Cylinder(g["Rb"], t, align=A) \
            + Pos(C / 2, 0, 0) * Box(C, web_h, t, align=A)
        stages = [Stage("plate", plate)]
        s = plate
        if v["pegs"]:
            pegs = None
            for x in (0.0, C):
                p = Pos(x, 0, t - 0.01) * Cylinder(v["axle_d"] / 2 + 1.5, g["collar_h"] + 0.01, align=A)
                p = p + Pos(x, 0, t) * Cylinder(v["axle_d"] / 2, g["peg_h"] - 0.5, align=A)
                p = p + Pos(x, 0, t + g["peg_h"] - 0.5 - 0.01) * Cone(v["axle_d"] / 2, v["axle_d"] / 2 - 0.5, 0.51, align=A)
                pegs = p if pegs is None else pegs + p
            s = s + pegs
        else:
            hole = v["axle_d"] - 2 * v["pin_press"]
            holes = Pos(0, 0, -0.1) * Cylinder(hole / 2, t + 0.2, align=A) + Pos(C, 0, -0.1) * Cylinder(hole / 2, t + 0.2, align=A)
            s = s - holes
        stages.append(Stage("pegs", s))

        pair = self._pair(v)
        ya = g["y_gears"]
        ga = Pos(0, ya, 0) * pair.a.shape
        s = s + ga
        stages.append(Stage("gear_a", s))
        gb = Pos(g["xb_print"] - C, ya, 0) * pair.b.shape          # move b out of mesh to print apart
        s = s + gb
        stages.append(Stage("gear_b", s))
        bores = None
        for x in (0.0, g["xb_print"]):
            c = Pos(x, ya, -0.1) * Cylinder(g["bore"] / 2, v["thickness"] + 0.2, align=A)
            bores = c if bores is None else bores + c
        s = s - bores
        stages.append(Stage("bores", s))
        return checked(stages)

    def derived(self, v):
        g = self.g(v)
        m = g["m"]
        return [
            {"key": "centre_distance", "label": "Centre distance", "value": g["C"], "unit": "mm", "feature": "pegs",
             "formula": "module × (z1 + z2) / 2"},
            {"key": "ratio", "label": "Gear ratio", "value": g["zb"] / g["za"], "unit": "", "feature": "gear_b", "formula": "z2 / z1"},
            {"key": "pitch_d_a", "label": "Small gear pitch diameter", "value": m * g["za"], "unit": "mm", "feature": "gear_a",
             "formula": "module × z1"},
            {"key": "pitch_d_b", "label": "Large gear pitch diameter", "value": m * g["zb"], "unit": "mm", "feature": "gear_b",
             "formula": "module × z2"},
            {"key": "tip_d_b", "label": "Large gear outside diameter", "value": 2 * g["rb"], "unit": "mm", "feature": "gear_b",
             "formula": "module × (z2 + 2)"},
            {"key": "contact_ratio", "label": "Contact ratio", "value": g["eps"], "unit": "", "feature": "gear_a",
             "formula": g["eps_src"]},
            {"key": "gear_bore", "label": "Gear bore", "value": g["bore"], "unit": "mm", "feature": "bores",
             "formula": "axle + 2 × clearance", "interface": True},
        ]

    def measure(self, v, faces_by_feature):
        g = self.g(v)
        out = []
        ds = [max(f.bounding_box().size.X, f.bounding_box().size.Y) for f in faces_by_feature.get("bores", [])
              if f.geom_type.name == "CYLINDER"]
        if ds:
            out.append({"key": "gear_bore", "label": "Gear bore", "intended": g["bore"], "modelled": min(ds)})
        xs = sorted({round(f.center().X, 3) for f in faces_by_feature.get("pegs", []) if f.geom_type.name == "CYLINDER"
                     and abs(max(f.bounding_box().size.X, f.bounding_box().size.Y) - (v["axle_d"] if v["pegs"] else
                                                                                        v["axle_d"] - 2 * v["pin_press"])) < 0.02})
        if len(xs) >= 2:
            out.append({"key": "centre_distance", "label": "Axle spacing", "intended": g["C"], "modelled": xs[-1] - xs[0]})
        return out

    def statics(self, v, solid_volume_mm3, com):
        g = self.g(v)
        m, za = g["m"], g["za"]
        d_a = m * za
        Ft = 2 * v["torque"] / d_a                                   # N, tangential load at the pitch circle
        Y = max(0.05, 0.154 - 0.912 / za)                           # Lewis form factor, 20° full depth (approximation)
        sigma = Ft / (v["thickness"] * m * Y) if Ft > 0 else 0.0
        sf = v["strength_mpa"] / sigma if sigma > 0 else float("inf")
        bl = v["backlash"]
        eps = g["eps"]
        checks = [
            {"id": "mesh_centre", "label": "Axle spacing = centre distance", "status": "PASS", "value": f"{g['C']:.2f} mm",
             "detail": f"Pegs are placed at m (z1 + z2) / 2 = {m:g} × ({za} + {g['zb']}) / 2. Backlash comes from thinner teeth, "
                       "so the spacing stays standard. The measured axle spacing is in the interface audit.",
             "evidence": "computed", "feature": "pegs"},
            {"id": "mesh_backlash", "label": "Backlash", "value": f"{bl:.2f} mm",
             "status": "PASS" if 0.15 <= bl <= 0.5 else "WARN",
             "detail": "Window 0.15–0.5 mm is an assumption for FDM gears: less can bind once the print's own error is added, "
                       "more rattles. Print the pair and turn it by hand.",
             "evidence": "heuristic", "feature": "gear_b"},
            {"id": "mesh_contact", "label": "Contact ratio", "value": f"{eps:.2f}",
             "status": "PASS" if eps >= 1.2 else ("WARN" if eps >= 1.0 else "FAIL"),
             "detail": "Teeth in contact on average. Under 1.2 runs rough; under 1 loses contact. Computed by "
                       f"{g['eps_src']}; no profile shift.", "evidence": "computed", "feature": "gear_a"},
            {"id": "tooth_strength", "label": "Tooth bending safety factor",
             "value": "no load" if sigma == 0 else f"{sf:.1f}×",
             "status": "PASS" if sf >= 2 else ("WARN" if sf >= 1.2 else "FAIL"),
             "detail": f"Lewis estimate on the small gear: {Ft:.0f} N at the pitch circle, form factor {Y:.3f}, "
                       f"{sigma:.1f} MPa against {v['strength_mpa']:.0f} MPa (assumed). Ignores dynamic load and wear. Target ≥ 2×.",
             "evidence": "model", "feature": "gear_a"},
        ]
        if za < 17:
            checks.append({"id": "undercut", "label": "Undercut", "status": "WARN" if za < 12 else "PASS",
                           "value": f"{za} teeth",
                           "detail": "Under 17 teeth (20°) the tooth roots are undercut. The gear library models it, which "
                                     "weakens the root; fewer than 12 teeth is fragile when printed.",
                           "evidence": "computed", "feature": "gear_a"})
        return {"centre_distance_mm": g["C"], "ratio": g["zb"] / za, "contact_ratio": eps, "safety_factor": sf,
                "tooth_stress_mpa": sigma, "checks": checks}

    def test_piece(self, v, shape):
        g = self.g(v)
        h = min(3.0, v["thickness"])
        R = g["ra"] + 1
        slab = Pos(0, g["y_gears"], 0) * Box(2 * R, 2 * R, h, align=A)
        return shape & slab, {"label": "Small gear slice", "doc": f"The bottom {h:g} mm of the small gear. Checks the bore "
                              "slides on the axle and the teeth come out clean.", "height": h}
