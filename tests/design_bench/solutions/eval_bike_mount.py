"""Parametric bike phone mount: a two-piece bar clamp sized for any bar from 22 to 35 mm (a rubber liner takes up
the rest), bolted with two M4 screws into captured nuts, a raised neck, and a bayonet head that takes a quarter-turn
adapter glued to the phone case.

Reference solution for the design bench: written in a design evaluation through Form Studio's tools only (design_brief, plan_design, create_design, update_design, critique), the way an agent connected to Form Studio works. It is a bench reference, not a recipe and not an exemplar."""
import math

from build123d import Align, Axis, Box, Cylinder, Plane, Pos, Rot, extrude

from form import craft, parts
from form.recipes.base import Assembly, Feature, Hardware, Mate, Param, Part, Recipe, RecipeError, Stage, hinge

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title, summary = "Bike phone mount", "Two-piece bar clamp for 22-35 mm bars with a quarter-turn bayonet phone head."
    solids = 3
    params = [
        Param("bar_d", "Handlebar diameter", 31.8, 22, 35, 0.1, "mm", "brief", "clamp", "Measure the bar where it mounts (22.2, 25.4, 31.8 and 35 are common)."),
        Param("liner", "Rubber liner thickness", 1.5, 0, 3, 0.1, "mm", "interface", "clamp", "1-2 mm rubber strip."),
        Param("width", "Clamp width", 22, 16, 30, 0.5, "mm", "form", "clamp"),
        Param("wall", "Clamp wall", 5, 3.5, 8, 0.1, "mm", "form", "clamp"),
        Param("rise", "Head height above the bar", 22, 12, 40, 0.5, "mm", "form", "neck"),
        Param("head_d", "Head diameter", 44, 36, 56, 0.5, "mm", "form", "head"),
        Param("gap", "Clamp gap (squeeze)", 2.0, 1, 4, 0.1, "mm", "interface", "clamp"),
    ]
    features = [Feature("clamp", "Clamp halves", "structure"), Feature("ears", "Bolt ears with nut traps", "interface"),
                Feature("neck", "Neck", "structure"), Feature("head", "Bayonet head", "interface"),
                Feature("adapter", "Phone adapter (bayonet male)", "interface")]

    def constraints(self, v):
        if v["bar_d"] + 2 * v["liner"] > 38:
            return [RecipeError("Bar plus liner is too big for this clamp", "clamp", "Use a thinner liner.", ["bar_d", "liner"])]
        return []

    def _geo(self, v):
        ri = v["bar_d"] / 2 + v["liner"]
        ro = ri + v["wall"]
        return ri, ro, ri + 4.5 + 2.2                       # ear bolt axis distance from the bar axis

    def build(self, v):
        W, g = v["width"], v["gap"]
        ri, ro, eb = self._geo(v)
        # the bar runs along Y; clamp split on the horizontal plane through the bar axis (z = 0)
        ring = Rot(90, 0, 0) * (Cylinder(ro, W) - Cylinder(ri, W + 1))
        ears = Box(2 * (eb + 6), W, 16, align=(Align.CENTER, Align.CENTER, Align.CENTER))   # 8 mm per half: the head and nut need it
        ears = craft.safe_fillet(ears, ears.edges().filter_by(Axis.Y), 4.0)
        body = ring + (ears - Rot(90, 0, 0) * Cylinder(ri + 0.01, W + 1))
        upper = body & Pos(0, 0, g / 2) * Box(4 * ro, 2 * W, 2 * ro, align=BOTTOM)
        lower = body & Pos(0, 0, -g / 2) * Box(4 * ro, 2 * W, 2 * ro, align=(Align.CENTER, Align.CENTER, Align.MAX))
        stages = [Stage("clamp", upper + lower)]
        # ears: M4 clearance through both, socket head counterbore on top, hex nut trap underneath
        scr = parts.screw_clearance("M4", 20, head="socket")
        nut = parts.nut_trap("M4", "hex")
        for sx in (-1, 1):
            upper = upper - Pos(sx * eb, 0, 8.0) * scr.shape
            lower = lower - Pos(sx * eb, 0, -8.0) * Rot(180, 0, 0) * nut.shape
            lower = lower - Pos(sx * eb, 0, -5) * Cylinder(scr["hole_d"] / 2 if "hole_d" in scr.dims else 2.25, 10)
        stages.append(Stage("ears", upper + lower))
        # neck: a flared post from the upper half up to the head
        H = ro + v["rise"]
        neck = craft.revolve_profile([(10.0, ro - 3), (8.0, ro + 2), (7.5, H - 6), (11.0, H - 1.5), (11.0, H)], spline=True)
        upper = upper + neck
        stages.append(Stage("neck", upper + lower))
        # head: a disc with the bayonet socket, edge rounded
        hd = v["head_d"]
        bay = craft.bayonet(d=26, height=7, lugs=3, lug_w=7, lug_h=2.2, lug_depth=1.8, twist=35, clearance=0.25)
        self._bay = bay
        head = Pos(0, 0, H) * Cylinder(hd / 2, 9, align=BOTTOM)
        head = craft.safe_fillet(head, head.edges(), 2.5)
        head = head - Pos(0, 0, H + 9 - 7 + 0.01) * bay["female_cutter"]
        upper = upper + head
        stages.append(Stage("head", upper + lower))
        # adapter: the male bayonet on a thin plate that glues to the phone case, modelled in the head, locked
        plate = Pos(0, 0, H + 9.5) * Cylinder(hd / 2 - 2, 2.0, align=BOTTOM)
        plate = craft.safe_fillet(plate, plate.edges(), 0.8)
        # male and cutter share one frame: same placement, then turned by the twist into the locking slots
        male = Pos(0, 0, H + 2.01) * Rot(0, 0, 33) * bay["male"]
        spacer = Pos(0, 0, H + 8.9) * (Cylinder(12.6, 0.7, align=BOTTOM) - Cylinder(13 - 2.4, 1, align=BOTTOM))
        adapter = plate + spacer + male
        stages.append(Stage("adapter", upper + lower + adapter))
        return stages

    def derived(self, v):
        ri, ro, eb = self._geo(v)
        return [{"key": "clamp_bore", "label": "Clamp bore", "value": round(2 * ri, 2), "unit": "mm", "feature": "clamp",
                 "formula": "bar + 2 x liner", "interface": True},
                {"key": "squeeze", "label": "Squeeze available", "value": v["gap"], "unit": "mm", "feature": "clamp",
                 "formula": "gap between the halves closes as the screws tighten", "interface": True},
                {"key": "bar_range", "label": "Bars this print fits", "value": round(2 * ri - 2 * 3.0, 1), "unit": "mm",
                 "formula": f"{2 * ri - 6:.1f} to {2 * ri:.1f} mm with a 0-3 mm liner", "feature": "clamp", "interface": False}]

    def assembly(self, v):
        ri, ro, eb = self._geo(v)
        H = ro + v["rise"]
        return Assembly(
            parts=[Part("lower", "Clamp lower", (0, 0, -ro + 1), explode=(0, 0, -25), note="Put the nuts in the lower half."),
                   Part("upper", "Clamp upper and head", (0, 0, ro - 1), note="Wrap the bar in the liner, close the halves, two M4 x 20."),
                   Part("adapter", "Phone adapter", (hd_x := v["head_d"] / 2 - 5, 0, H + 10.5), explode=(0, 0, 30),
                        note="Glue the adapter to the phone case; push in and turn a quarter to lock.")],
            joints=[hinge("adapter", (0, 0, 1), (0, 0, H), (-33, 0), 8, parent="upper", id="lock", label="Bayonet lock")],
            hardware=[Hardware("Socket head cap screw", "M4 x 20", 2, "ISO 4762", "Clamp", after="upper"),
                      Hardware("Hex nut", "M4", 2, "ISO 4032", "In the lower half's traps", after="lower")])
