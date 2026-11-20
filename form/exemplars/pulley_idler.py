"""Belt idler: a crowned flat-belt pulley on a 608 bearing, with flanges, a spoked web and a slotted tensioner arm
printed beside it. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Cylinder, Edge, Pos, Rot, SlotOverall, Spline, Vector, Wire, extrude, make_face, revolve

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Pulley and belt idler",
    "category": "mechanical",
    "tags": ["pulley", "idler", "belt", "bearing", "608", "tensioner", "wheel", "spokes", "crown", "revolve", "mechanism"],
    "techniques": ["revolve_profile of the rim with a crowned face and flanges", "bearing seat from form.parts",
                   "spokes as cut windows with filleted corners", "ISO fit for the bearing seat (fits.bearing_fit)",
                   "slotted arm for tension adjustment"],
    "lessons": [
        "A flat-belt pulley is crowned (the face bulges 0.5-1 % of its width) so the belt tracks to the centre; flanges "
        "only for toothed belts or as a safety lip, chamfered so the belt cannot catch.",
        "Draw the rim, web and hub as one revolve profile, then cut the spoke windows: one boolean, smooth transitions.",
        "The bearing seat comes from form.parts (published 608 dimensions) with a lip to stop it; the fit is printed "
        "slightly under and pressed, never guessed.",
        "An idler needs adjustment: the arm carries a slot as long as the belt stretch you expect.",
    ],
}


class Design(Recipe):
    title, summary = "Belt idler", "Crowned 608-bearing idler pulley with flanges and spokes, and a slotted arm."
    solids = 2
    params = [
        Param("od", "Pulley diameter (belt face)", 60, 44, 120, 0.5, "mm", "form", "rim"),
        Param("face_w", "Belt width", 12, 6, 30, 0.5, "mm", "brief", "rim"),
        Param("flange", "Flange height", 2.0, 0, 4, 0.1, "mm", "form", "rim"),
        Param("crown", "Crown", 0.25, 0, 0.8, 0.05, "mm", "form", "rim", "Radial bulge at the middle of the face."),
        Param("spokes", "Spokes", 5, 3, 8, 1, "", "form", "web"),
        Param("slot", "Tension slot", 14, 4, 40, 0.5, "mm", "interface", "arm"),
    ]
    features = [Feature("rim", "Rim and flanges", "structure"), Feature("web", "Spoked web", "structure"),
                Feature("seat", "608 bearing seat", "interface"), Feature("arm", "Tensioner arm", "structure")]

    def constraints(self, v):
        if v["od"] / 2 - 4 < 11 + 4:
            return [RecipeError("The pulley is too small around a 608 bearing", "seat", "Use a larger diameter.", ["od"])]
        return []

    def build(self, v):
        R, W, fl, cr = v["od"] / 2, v["face_w"], v["flange"], v["crown"]
        H = W + 2 * 1.6                                   # flange thickness 1.6 each side
        rim_in = R - 3.5
        hub_r = 11 + 2.5
        # profile (r, z): hub, web, rim with a crowned face between two chamfered flanges
        # straight segments everywhere except the belt face, which is one smooth crowned spline
        lo = [(hub_r - 3.0, 0.0), (R + fl, 0.0), (R + fl, 0.6), (R + 0.2, 1.6), (R, 1.6)]
        crown = [(R + cr * math.sin(math.pi * i / 6), 1.6 + W * i / 6) for i in range(7)]
        hi = [(R, 1.6 + W), (R + 0.2, 1.6 + W), (R + fl, H - 0.6), (R + fl, H), (rim_in, H), (rim_in, H * 0.5 + 1.5),
              (hub_r, H * 0.5 + 1.5), (hub_r, H), (hub_r - 3.0, H), (hub_r - 3.0, 0.0)]
        P3 = lambda p: Vector(p[0], 0, p[1])
        edges = [Edge.make_line(P3(a), P3(b)) for a, b in zip(lo, lo[1:])]
        edges.append(Spline(*[P3(p) for p in crown]))
        edges += [Edge.make_line(P3(a), P3(b)) for a, b in zip(hi, hi[1:]) if a != b]
        rim = revolve(make_face(Wire(edges)), Axis.Z).solids()[0]
        stages = [Stage("rim", rim)]
        # spoke windows in the web: rounded trapezoids between hub and rim
        n = int(v["spokes"])
        body = rim
        for i in range(n):
            a = 360 * i / n + 180 / n
            r0, r1 = hub_r + 2.0, rim_in - 2.0
            span0, span1 = 2 * math.pi * r0 / n - 6, 2 * math.pi * r1 / n - 6
            win = craft.polygon_profile([(r0, -span0 / 2), (r1, -span1 / 2), (r1, span1 / 2), (r0, span0 / 2)])
            w = extrude(win, H)
            w = craft.safe_fillet(w, w.edges().filter_by(Axis.Z), 2.0)
            body = body - Rot(0, 0, a) * Pos(0, 0, -0.5) * w
        stages.append(Stage("web", body))
        seat = parts.bearing_seat("608", fit=0.05, through=3.0)
        body = body - Pos(0, 0, H) * seat.shape
        body = body - Pos(0, 0, -0.2) * Cylinder(5.0, H, align=BOTTOM)
        stages.append(Stage("seat", body))
        # arm: a tapered bar with a boss for the axle (M8) and a slot for the mounting screw (M5)
        ax = R + 30
        L = 60 + v["slot"]
        arm = extrude(craft.polygon_profile([(0, -11), (L, -7), (L, 7), (0, 11)]), 6)
        arm = arm + Cylinder(11, 6, align=BOTTOM) + Pos(L, 0, 0) * Cylinder(7, 6, align=BOTTOM)
        arm = arm - Pos(0, 0, -1) * Cylinder(parts.clearance_d("M8")[0] / 2, 8, align=BOTTOM)
        arm = arm - Pos(L - v["slot"] / 2, 0, -1) * extrude(SlotOverall(v["slot"] + 5.5, 5.5), 8)
        arm = arm + Pos(L / 2 - 6, 0, 6) * craft.rib(L - 30, 3.0, 3.0, angle=0)
        arm = craft.safe_fillet(arm, arm.edges().group_by(Axis.Z)[-1], 0.8)
        body = body + Pos(ax, 0, 0) * arm
        stages.append(Stage("arm", body))
        return parts.checked(stages)

    def derived(self, v):
        b = craft.bearing_fit("608", "housing", "outer")
        return [{"key": "seat_iso", "label": "Bearing housing tolerance (machined)", "value": b["limits"][1], "unit": "mm",
                 "feature": "seat", "formula": f"{b['tolerance']} upper limit, {b['why']}", "interface": True},
                {"key": "crown_pct", "label": "Crown", "value": 100 * v["crown"] / v["face_w"], "unit": "%",
                 "feature": "rim", "formula": "crown / face width", "interface": False}]
