"""Square bearing flange for a deep-groove ball bearing (6000 by default: 10 x 26 x 8): a plate with a raised boss, a
press-fit seat on a stop shoulder with a lead-in chamfer, a spigot on the back to centre it in a bore, and four
counterbored M5 screw holes on a square. Ported from the "A Parametric Bearing Pillow Block" seed in CADEvolve's
hand-written CadQuery examples (kulibinai/CADEvolve, Apache-2.0) and modified: rewritten for build123d and Form
Studio's FeatureDesign, the bearing taken from form.parts.BEARINGS and the fit from craft.bearing_fit. Form Studio
exemplar design."""
from build123d import Align, Axis, Box, Cylinder, GeomType, Pos

from form import craft, parts
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Square bearing flange with counterbored screws",
    "category": "mechanical",
    "tags": ["bearing", "flange", "bearing flange", "flange bearing", "6000", "608", "626", "625", "ball bearing",
             "housing", "press fit", "seat", "shoulder", "spigot", "register", "counterbore", "cbore", "socket head",
             "m5", "shaft support", "plate", "mechanical"],
    "techniques": ["bearing sizes from form.parts.BEARINGS (bore, OD, width, ring shoulders) picked by an index",
                   "seat = OD + a printed oversize, with the ISO housing tolerance from craft.bearing_fit in derived()",
                   "stop shoulder: a through hole under the seat sized between the rings' shoulder diameters",
                   "a spigot on the back face for location, so the screws only clamp",
                   "counterbored holes on a square (ISO 4762 head + clearance)",
                   "lead-in chamfer on the seat mouth, picked as the circle of the seat's diameter at the top"],
    "lessons": [
        "Size the seat from the bearing's published numbers and keep the two fits apart: the machinist's housing "
        "tolerance (craft.bearing_fit: H7 when the outer ring is stationary) and the printed oversize that a test "
        "ring calibrates. derived() reports both.",
        "The shoulder hole must clear the inner ring but stop the outer ring: size it between the inner ring's and "
        "the outer ring's shoulder diameters (form.parts.BEARINGS lists both), never at the OD.",
        "Locate with a spigot, clamp with screws: a register on the back fits the frame's bore, so the bearing's "
        "position does not depend on four clearance holes.",
        "Counterbores come from the screw standard: an M5 socket head (ISO 4762) is 8.5 mm across and 5 mm high, so "
        "the counterbore is 10 x 5.5 mm and the clearance hole 5.5 mm. Keep material under the head.",
        "Pick edges by geometry, not by index: the seat mouth is the circle at the top face whose radius is the "
        "seat's, so the chamfer follows any bearing size.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/cadquery_examples.txt", "seed": "A Parametric Bearing Pillow Block",
               "licence": "Apache-2.0", "modified": "modified (ported to build123d / Form Studio)"},
}

SIZES = ["623", "625", "626", "608", "6000"]         # keys of form.parts.BEARINGS
M5 = (5.5, 10.0, 5.5)              # clearance hole, counterbore diameter, counterbore depth (ISO 4762 M5 + clearance)
BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
SHOULDER = 2.0                     # material under the bearing's outer ring (mm)


class Design(FeatureDesign):
    title, summary = "Bearing flange", ("A square flange with a raised boss, a press-fit bearing seat on a stop "
                                        "shoulder, a centring spigot and four counterbored screws.")
    params = [
        Param("bearing", "Bearing", 4, 0, 4, 1, "", "interface", "seat", "0 = 623, 1 = 625, 2 = 626, 3 = 608, 4 = 6000."),
        Param("oversize", "Printed seat oversize", 0.15, 0.0, 0.4, 0.01, "mm", "interface", "seat",
              "Holes print small; calibrate with a test ring."),
        Param("side", "Plate side", 56, 36, 120, 1, "mm", "brief", "plate"),
        Param("t", "Plate thickness", 7, 6, 16, 0.5, "mm", "form", "plate"),
        Param("boss_wall", "Boss wall", 4, 2.5, 12, 0.5, "mm", "form", "boss"),
        Param("spigot_h", "Spigot height", 3, 0, 8, 0.5, "mm", "interface", "spigot"),
        Param("screw_sq", "Screw square", 40, 26, 100, 0.5, "mm", "interface", "screws"),
        Param("r", "Corner radius", 6, 1, 15, 0.5, "mm", "form", "edges"),
    ]

    def setup(self, v):
        name = SIZES[int(round(v["bearing"]))]
        bore, od, width, in_sh, out_sh = parts.BEARINGS[name]
        seat = od + v["oversize"]
        boss_d = seat + 2 * v["boss_wall"]
        return {"name": name, "od": od, "width": width, "seat": seat, "stop_d": (in_sh + out_sh) / 2,
                "boss_h": max(width + SHOULDER - v["t"], 0.0), "boss_d": boss_d}

    def constraints(self, v):
        ctx = self.setup(v)
        s = v["screw_sq"] / 2
        out = []
        if s * 2 ** 0.5 - M5[1] / 2 < ctx["boss_d"] / 2 + 1.0:
            out.append(RecipeError("The counterbores cut into the boss", "screws",
                                   "Spread the screws or use a smaller bearing.", ["screw_sq", "bearing", "boss_wall"]))
        if s + M5[1] / 2 + 1.5 > v["side"] / 2:
            out.append(RecipeError("The counterbores run off the plate", "screws",
                                   "Bring the screws in or make the plate larger.", ["screw_sq", "side"]))
        if v["t"] < M5[2] + 1.5:
            out.append(RecipeError("Too little plate under the screw heads", "screws", "Make the plate thicker.", ["t"]))
        return out

    def derived(self, v):
        ctx = self.setup(v)
        b = craft.bearing_fit(ctx["name"], "housing", "inner")
        return [{"key": "printed_seat", "label": f"Printed seat diameter ({ctx['name']})", "value": round(ctx["seat"], 3),
                 "unit": "mm", "feature": "seat", "formula": "bearing OD + calibrated oversize (assumed)",
                 "interface": True},
                {"key": "iso_housing", "label": f"Housing tolerance (machined, {b['tolerance']})",
                 "value": f"{b['limits'][0]:.3f} - {b['limits'][1]:.3f}", "unit": "mm", "feature": "seat",
                 "formula": b["why"], "interface": True}]

    @feature("Plate")                                       # the skeleton: the plate, back face on z = 0
    def plate(self, v, body):
        return Box(v["side"], v["side"], v["t"], align=BOTTOM)

    @feature("Boss")
    def boss(self, v, body):
        h = self.ctx["boss_h"]
        if h <= 0:
            return body
        return craft.safe_union(body, Pos(0, 0, v["t"] - 0.01) * Cylinder(self.ctx["boss_d"] / 2, h + 0.01, align=BOTTOM))

    @feature("Spigot", role="interface")
    def spigot(self, v, body):
        if v["spigot_h"] <= 0:
            return body
        return craft.safe_union(body, Pos(0, 0, 0.01) * Cylinder(self.ctx["boss_d"] / 2, v["spigot_h"],
                                                                  align=(Align.CENTER, Align.CENTER, Align.MAX)))

    @feature("Bearing seat", role="interface")
    def seat(self, v, body):
        c = self.ctx
        top = v["t"] + c["boss_h"]
        body = body - Pos(0, 0, top - c["width"]) * Cylinder(c["seat"] / 2, c["width"] + 1, align=BOTTOM)
        body = body - Pos(0, 0, -v["spigot_h"] - 1) * Cylinder(c["stop_d"] / 2, top + v["spigot_h"] + 2, align=BOTTOM)
        mouth = [e for e in body.edges().filter_by(GeomType.CIRCLE)
                 if abs(e.center().Z - top) < 0.01 and abs(e.radius - c["seat"] / 2) < 0.01]
        return craft.safe_chamfer(body, mouth, 0.6)

    @feature("Counterbored screws", role="interface")
    def screws(self, v, body):
        clear, cb_d, cb_h = M5
        s = v["screw_sq"] / 2
        for x, y in ((s, s), (-s, s), (-s, -s), (s, -s)):
            body = body - Pos(x, y, -1) * Cylinder(clear / 2, v["t"] + 2, align=BOTTOM)
            body = body - Pos(x, y, v["t"] - cb_h) * Cylinder(cb_d / 2, cb_h + 1, align=BOTTOM)
        return body

    @feature("Edges", role="finish")
    def edges(self, v, body):
        corners = [e for e in body.edges().filter_by(Axis.Z)
                   if abs(abs(e.center().X) - v["side"] / 2) < 0.01 and abs(abs(e.center().Y) - v["side"] / 2) < 0.01]
        return craft.safe_fillet(body, corners, v["r"])
