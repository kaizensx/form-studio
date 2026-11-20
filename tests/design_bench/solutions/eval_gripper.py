"""Robotic gripper finger on a four-bar linkage: a palm with two ground pivots, a driven crank (servo D-shaft), a
rocker, and the finger as the coupler, with a ribbed contact pad. Near-parallelogram proportions keep the pad close
to parallel as the finger closes. Modelled at one crank angle, links stacked in layers with pins along Z.

Reference solution for the design bench: written in a design evaluation through Form Studio's tools only (design_brief, plan_design, create_design, update_design, critique), the way an agent connected to Form Studio works. It is a bench reference, not a recipe and not an exemplar."""
import math

from build123d import Align, Axis, Box, Cylinder, Plane, Pos, Rot, extrude

from form import craft
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Four-bar gripper finger", "Gripper finger driven through a four-bar linkage, with a ribbed pad."
    solids = 4
    params = [
        Param("ground", "Ground pivot spacing", 22, 12, 40, 0.5, "mm", "form", "palm"),
        Param("crank", "Crank length", 45, 25, 70, 0.5, "mm", "form", "crank"),
        Param("coupler", "Coupler pivot spacing", 22, 12, 40, 0.5, "mm", "form", "finger"),
        Param("rocker", "Rocker length", 46, 25, 70, 0.5, "mm", "form", "rocker"),
        Param("crank_deg", "Crank angle as modelled", 72, 30, 120, 1, "deg", "form", "crank"),
        Param("pin_d", "Pin diameter", 3.0, 2, 5, 0.1, "mm", "brief", "finger", "3 mm dowel pins or printed pins."),
        Param("pin_clear", "Pin clearance / side", 0.2, 0.1, 0.4, 0.05, "mm", "interface", "finger"),
        Param("shaft_d", "Servo shaft", 5.0, 3, 6, 0.05, "mm", "brief", "crank", "Measure the servo output shaft."),
    ]
    features = [Feature("palm", "Palm with ground pivots", "structure"), Feature("crank", "Driven crank", "structure"),
                Feature("rocker", "Rocker", "structure"), Feature("finger", "Finger (coupler)", "structure"),
                Feature("pad", "Ribbed contact pad", "finish")]

    T = 4.0                                            # link thickness
    G = 0.3                                            # gap between layers

    def constraints(self, v):
        L = sorted([v["ground"], v["crank"], v["coupler"], v["rocker"]])
        if L[0] + L[3] > L[1] + L[2] + 4:                    # a finger needs a range, not a full turn
            return [RecipeError("The linkage locks up well before closing the finger", "crank",
                                "Bring the four lengths closer to a parallelogram.", ["ground", "crank", "coupler", "rocker"])]
        return []

    def _pose(self, v):
        return craft.four_bar_pose(v["ground"], v["crank"], v["coupler"], v["rocker"], v["crank_deg"])

    def build(self, v):
        T, G = self.T, self.G
        P = self._pose(v)
        A, B, C, D = P["A"], P["B"], P["C"], P["D"]
        hole = v["pin_d"] + 2 * v["pin_clear"]
        z1, z2 = T + G, 2 * T + 2 * G                   # links layer, finger layer
        # palm: a soft plate round both ground pivots with a mounting tail and two M3 holes
        gx = v["ground"]
        palm = craft.spline_profile([(-14, -34), (gx + 14, -34), (gx + 13, 6), (gx / 2, 13), (-13, 6)], plane=Plane.XY)
        palm = extrude(palm, T)
        palm = palm - Pos(0, 0, -0.1) * Cylinder(v["shaft_d"] / 2 + 1.0, T + 1, align=BOTTOM)     # servo shaft passes
        for x in (2, gx - 2):
            palm = palm - Pos(x, -24, -0.1) * Cylinder(1.7, T + 1, align=BOTTOM)
        palm = craft.safe_fillet(palm, palm.edges().group_by(Axis.Z)[-1], 1.2)
        palm = palm + Pos(D[0], D[1], T - 0.1) * Cylinder(v["pin_d"] / 2, T + G + 0.1, align=BOTTOM)  # pin at D
        stages = [Stage("palm", palm)]
        # crank: driven at A by the servo's D-shaft, out to B
        crank = craft.link_between(A, B, 10, T, hole, z=z1)
        d = v["shaft_d"] + 0.1
        dbore = Cylinder(d / 2, T + 2, align=BOTTOM) - Pos(d / 2 - 0.5 + 5, 0, 0) * Box(10, 10, 20, align=BOTTOM)
        crank = crank + Pos(0, 0, z1) * Cylinder(6.0, T, align=BOTTOM)
        crank = crank - Pos(0, 0, z1 - 1) * dbore
        body = palm + crank
        stages.append(Stage("crank", body))
        rocker = craft.link_between(D, C, 9, T, hole, z=z1)
        body = body + rocker
        stages.append(Stage("rocker", body))
        # finger: the coupler grown into a finger that reaches up past C, the pad on its +X side
        bx, by = B
        cx, cy = C
        ang = math.radians(P["coupler_deg"])
        outline = [(bx - 7, by - 6), (cx + 6, cy - 6), (cx + 9, cy + 18), (cx + 10, cy + 52), (cx + 4, cy + 62),
                   (cx - 5, cy + 60), (bx + 6, by + 30), (bx - 7, by + 8)]
        finger = Pos(0, 0, z2) * extrude(craft.spline_profile(outline, plane=Plane.XY), 12)
        finger = craft.safe_fillet(finger, finger.edges().group_by(Axis.Z)[-1] + finger.edges().group_by(Axis.Z)[0], 2.5)
        for (px, py) in (B, C):                                                    # pins down into the links
            finger = finger + Pos(px, py, z1 + 0.05) * Cylinder(v["pin_d"] / 2, z2 - z1 + 0.1, align=BOTTOM)
        body = body + finger
        stages.append(Stage("finger", body))
        # pad: ribs across the contact face, proud by 1.2 mm, on the finger's +X flank
        for i in range(9):
            rib = Pos(cx + 9.4, cy + 22 + i * 3.4, z2 + 1.5) * Box(2.6, 1.4, 9, align=(Align.MIN, Align.CENTER, Align.MIN))
            body = body + rib
        stages.append(Stage("pad", body))
        self._P = P
        return stages

    def derived(self, v):
        fb = craft.four_bar(v["ground"], v["crank"], v["coupler"], v["rocker"])
        P = self._pose(v)
        return [{"key": "linkage", "label": "Linkage class", "value": 1.0 if fb["grashof"] else 0.0, "unit": "",
                 "feature": "crank", "formula": fb.info["kind"] + " (1 = Grashof)", "interface": False},
                {"key": "rocker_swing", "label": "Rocker swing", "value": fb["rocker_swing_deg"], "unit": "deg",
                 "feature": "rocker", "formula": "four_bar() sampled loop", "interface": False},
                {"key": "transmission", "label": "Transmission angle as modelled", "value": P["transmission_deg"],
                 "unit": "deg", "feature": "finger", "formula": "angle between coupler and rocker", "interface": False},
                {"key": "pad_tilt", "label": "Pad tilt from parallel", "value": round(P["coupler_deg"], 2), "unit": "deg",
                 "feature": "pad", "formula": "coupler angle (0 = parallel to the ground link)", "interface": False}]

    def assembly(self, v):
        P = self._pose(v)
        T, G = self.T, self.G
        z1, z2 = T + G, 2 * T + 2 * G
        (bx, by), (cx, cy), (dx, dy) = P["B"], P["C"], P["D"]
        mid = lambda p, q: ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        cm, rm = mid((0, 0), P["B"]), mid(P["D"], P["C"])
        c = v["pin_clear"]
        return Assembly(
            parts=[Part("palm", "Palm", (dx / 2, -28, T / 2), note="Screw the palm to the gripper body (2 x M3)."),
                   Part("crank", "Crank", (cm[0], cm[1], z1 + T / 2), explode=(0, 0, 12), note="Press the crank onto the servo shaft."),
                   Part("rocker", "Rocker", (rm[0], rm[1], z1 + T / 2), explode=(0, 0, 12), note="Drop the rocker on the palm pin."),
                   Part("finger", "Finger", (cx - 2, cy + 30, z2 + 6), explode=(0, 0, 28), note="Press the finger's pins into the crank and rocker.")],
            mates=[Mate("palm", "rocker", "pin", c, "Palm pin in rocker"),
                   Mate("finger", "crank", "pin", c, "Finger pin in crank"),
                   Mate("finger", "rocker", "pin", c, "Finger pin in rocker")])
