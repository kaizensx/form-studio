"""Print-in-place planetary gearbox stage: involute sun, three planets and a ring housing with a bolt flange, plus a
carrier with pins printed beside it. Ratio 1 + Zr/Zs with the ring fixed. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Cylinder, Pos, RegularPolygon, Rot, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Planetary gearbox",
    "tags": ["gear", "gears", "gearbox", "planetary", "reduction", "mechanism", "print-in-place", "carrier", "ring gear",
             "involute", "transmission"],
    "techniques": ["craft.planetary (py_gearworks involute profiles via form.parts)", "assembly condition checks",
                   "ring housing with a bolt flange", "carrier pins sized from the planet bores", "derived ratio"],
    "lessons": [
        "Choose tooth counts from the assembly conditions first: Zr = Zs + 2 Zp, and (Zs + Zr) divisible by the number of "
        "planets so they space evenly. craft.planetary refuses anything else with the reason.",
        "Gears come from a real involute generator (form.parts / py_gearworks), never from hand-drawn teeth; the overlap "
        "of every planet with the sun and ring is computed from the solids and reported.",
        "Print-in-place: the sun, planets and ring are separate solids in mesh with the backlash as the gap. The carrier "
        "prints beside them and its pins press into the planet bores (pin = bore - 2 x clearance).",
        "The ring is a housing, not just a gear: a flange with bolt lugs, chamfered edges, and the ratio in derived().",
        "Several stages stack in one ring: craft.planetary(..., ring_height=all stages) and the same gear set placed "
        "at each stage's height; each carrier carries the next stage's sun. Name the parts in assembly() by a point "
        "inside each (Part(solid=(x, y, z))): coaxial parts cannot be told apart by counting.",
    ],
}


class Design(Recipe):
    title, summary = "Planetary gearbox", "Sun, three planets and a flanged ring housing in mesh, plus a pinned carrier."
    solids = 6
    params = [
        Param("module", "Module", 1.5, 1.0, 3.0, 0.25, "mm", "form", "ring"),
        Param("sun", "Sun teeth", 12, 9, 30, 1, "", "form", "sun"),
        Param("planet", "Planet teeth", 18, 9, 40, 1, "", "form", "planets"),
        Param("thickness", "Gear thickness", 8, 4, 20, 0.5, "mm", "form", "ring"),
        Param("backlash", "Backlash", 0.15, 0.05, 0.4, 0.01, "mm", "interface", "planets", "Total, along the line of action."),
        Param("pin_clearance", "Carrier pin clearance / side", 0.15, 0.05, 0.4, 0.01, "mm", "interface", "carrier"),
    ]
    features = [Feature("ring", "Ring housing", "structure"), Feature("flange", "Bolt flange", "interface"),
                Feature("sun", "Sun gear", "structure"), Feature("planets", "Planets", "structure"),
                Feature("carrier", "Carrier", "structure")]

    def constraints(self, v):
        zs, zp = int(v["sun"]), int(v["planet"])
        zr = zs + 2 * zp
        if (zs + zr) % 3:
            return [RecipeError(f"Three planets cannot be spaced evenly (sun {zs} + ring {zr} is not divisible by 3)",
                                "planets", "Change the sun or planet teeth by one.", ["sun", "planet"])]
        return []

    def _set(self, v):
        return craft.planetary(v["module"], int(v["sun"]), int(v["planet"]), 3, v["thickness"], ring_rim=4.0,
                               backlash=v["backlash"], sun_bore=0, planet_bore=4.0)

    def build(self, v):
        m, T = v["module"], v["thickness"]
        ps = self._set(v)
        S = ps.shapes
        ring = S["ring"]
        rd = ps["ring_od"]
        ring = ring.chamfer(0.5, None, [e for e in ring.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - rd / 2) < 1e-3])
        stages = [Stage("ring", ring)]
        # flange: three lugs with M4 clearance holes, blended into the housing
        lug_r = rd / 2 + 7
        flange = ring
        for i in range(3):
            a = 60 + 120 * i
            # a tapered lug from the housing out to a round boss, 4 mm thick, standing on the bed
            web = craft.polygon_profile([(rd / 2 - 3, -9), (lug_r, -6.5), (lug_r, 6.5), (rd / 2 - 3, 9)])
            lug = Rot(0, 0, a) * (extrude(web, 4) + Pos(lug_r, 0, 0) * Cylinder(6.5, 4, align=BOTTOM))
            flange = flange + lug
            flange = flange - Rot(0, 0, a) * Pos(lug_r, 0, -1) * Cylinder(parts.clearance_d("M4")[0] / 2, 8, align=BOTTOM)
        stages.append(Stage("flange", flange))
        # sun with a hex drive socket for a 1/4" bit (6.35 mm across flats + 0.2 clearance)
        sun = S["sun"] - Pos(0, 0, -0.5) * extrude(RegularPolygon(6.55 / 2, 6, major_radius=False), T + 1)
        body = flange + sun
        stages.append(Stage("sun", body))
        for i in range(3):
            body = body + S[f"planet{i}"]
        stages.append(Stage("planets", body))
        # carrier: a three-armed plate with pins that press into the planet bores, printed beside the set
        a_r = ps["carrier_r"]
        pin_d = 4.0 - 2 * v["pin_clearance"]
        cx = rd / 2 + lug_r + 12 + a_r
        plate = Cylinder(a_r * 0.55, 3.0, align=BOTTOM)
        for px, py in ps.info["planet_centres"]:
            ang = math.degrees(math.atan2(py, px))
            arm = extrude(craft.polygon_profile([(0, -4.5), (a_r, -4.5), (a_r, 4.5), (0, 4.5)]), 3.0)
            plate = plate + Rot(0, 0, ang) * (arm + Pos(a_r, 0, 0) * Cylinder(5.5, 3.0, align=BOTTOM))
            plate = plate + Rot(0, 0, ang) * Pos(a_r, 0, 3.0) * Cylinder(pin_d / 2, T - 1.0, align=BOTTOM)
        plate = plate + Pos(0, 0, 3.0) * Cylinder(5, 6, align=BOTTOM)
        plate = plate - Pos(0, 0, -1) * extrude(RegularPolygon(6.55 / 2, 6, major_radius=False), 12)
        plate = craft.safe_fillet(plate, [e for e in plate.edges().filter_by(Axis.Z) if e.length < 3.5], 1.5)
        body = body + Pos(cx, 0, 0) * plate
        stages.append(Stage("carrier", body))
        return parts.checked(stages)

    def derived(self, v):
        zs, zp = int(v["sun"]), int(v["planet"])
        zr = zs + 2 * zp
        return [{"key": "ratio", "label": "Reduction (ring fixed, sun in, carrier out)", "value": 1 + zr / zs, "unit": "",
                 "feature": "planets", "formula": "1 + Zr / Zs", "interface": False},
                {"key": "ring_teeth", "label": "Ring teeth", "value": zr, "unit": "", "feature": "ring",
                 "formula": "Zs + 2 Zp", "interface": False},
                {"key": "carrier_r", "label": "Planet circle radius", "value": v["module"] * (zs + zp) / 2, "unit": "mm",
                 "feature": "carrier", "formula": "m (Zs + Zp) / 2", "interface": True}]
