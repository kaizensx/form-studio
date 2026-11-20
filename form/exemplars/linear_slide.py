"""Printed linear slide: a dovetail rail with counterbored mounting holes and a fixed end stop, and a carriage that
rides on the dovetail flanks with a named running clearance, lead-in chamfers, heat-set inserts on top and a screw
for the second stop. The slider-mechanism exemplar. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Plane, Pos, Rot, extrude

from form import craft, parts
from form.recipes.base import (Assembly, Feature, Hardware, Param, Part, Recipe, RecipeError, Stage, slide)

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Linear slide with dovetail carriage",
    "category": "mechanical",
    "tags": ["linear", "slide", "slider", "rail", "carriage", "dovetail", "guide", "prismatic", "mechanism", "travel",
             "end stop", "clearance", "anti-lift", "assembly", "heat-set insert", "counterbore"],
    "techniques": ["craft.dovetail for the rail tongue; the carriage slot is the same section offset by the clearance",
                   "relief neck under the tongue so the carriage bears only on the flanks",
                   "carriage printed top-down beside the rail, placed by assembly() with Rot(180, 0, 0)",
                   "slide() joint whose range is computed from the stops",
                   "parts.screw_clearance counterbores and parts.heat_insert_pocket in the carriage",
                   "lead-in chamfers on the slot ends with a fallback"],
    "lessons": [
        "Anti-lift comes from the section, not from screws: a dovetail tongue (wide at the top, narrow at the root) "
        "traps the carriage, so it can only move along the rail. Its flanks at 60 deg also centre it sideways under load.",
        "Name the running clearance and apply it normal to every bearing face: each flank moves out by c / sin(angle) "
        "horizontally and keeps its angle, the top moves up by c. Extend the cutter past the opening along the same "
        "flank lines, not straight down, or the flanks tilt and the gap shrinks toward the top (check it: the assembly "
        "check should measure exactly c). 0.15-0.25 mm per side slides on FDM; print a 20 mm coupon first.",
        "Break every acute edge a dovetail makes (the tongue's top corners, the slot's mouth): a 60 deg knife edge "
        "chips, prints as a sub-nozzle wall and is what binds first.",
        "A carriage must never bear on the rail's base as well as its flanks (over-constrained, it binds on the first "
        "warp). A short neck under the tongue lifts the dovetail, so the carriage skirts float a gap above the base.",
        "Print each part where its overhangs are easy: the rail base-down, the carriage on its flat top so the slot's "
        "flanks lean only 30 deg from vertical. assembly() turns the carriage back over with Rot(180, 0, 0).",
        "Two stops, one removable: a printed stop at one end, a screw head at the other, so the carriage can be slid "
        "on. The joint's travel is computed from where they are, never typed in.",
        "Counterbore the rail's mounting screws so their heads sit below the tongue top; the carriage rides over them.",
    ],
}


class Design(Recipe):
    title, summary = "Linear slide", "Dovetail rail with stops and mounting holes, and a carriage on a named clearance."
    solids = 2
    params = [
        Param("rail_len", "Rail length", 160, 100, 400, 5, "mm", "brief", "rail"),
        Param("rail_w", "Rail base width", 26, 22, 40, 0.5, "mm", "form", "rail"),
        Param("tongue_w", "Dovetail width (top)", 16, 15, 22, 0.5, "mm", "form", "dovetail"),
        Param("tongue_h", "Dovetail height", 5, 4, 6, 0.5, "mm", "form", "dovetail"),
        Param("angle", "Flank angle", 60, 55, 70, 1, "deg", "form", "dovetail",
              "Flank to base; 60 deg is the usual dovetail, steeper holds less against lift."),
        Param("clearance", "Running clearance / side", 0.2, 0.1, 0.4, 0.01, "mm", "interface", "slot",
              "Normal to every flank. FDM sliding fit 0.15-0.25 mm; calibrate with a coupon."),
        Param("car_len", "Carriage length", 50, 30, 90, 1, "mm", "form", "carriage",
              "Longer than about 2 x its width so it does not rack."),
        Param("hole_pitch", "Mounting hole pitch", 50, 25, 100, 1, "mm", "brief", "mounting"),
    ]
    features = [Feature("rail", "Rail base", "structure"), Feature("dovetail", "Dovetail tongue", "interface"),
                Feature("mounting", "Mounting holes", "interface"), Feature("stops", "End stops", "interface"),
                Feature("carriage", "Carriage", "structure"), Feature("slot", "Dovetail slot", "interface"),
                Feature("inserts", "Insert pockets", "interface")]

    BASE_H, NECK, TOP_T, STOP_L = 5.0, 0.6, 6.0, 8.0

    def constraints(self, v):
        root = v["tongue_w"] - 2 * v["tongue_h"] / math.tan(math.radians(v["angle"]))
        errs = []
        if root < 8.6:
            errs.append(RecipeError(f"The dovetail root is {root:.1f} mm, too narrow for the M4 counterbores", "dovetail",
                                    "Make the dovetail wider or lower, or steepen the flanks.",
                                    ["tongue_w", "tongue_h", "angle"]))
        if v["tongue_w"] > v["rail_w"] - 4:
            errs.append(RecipeError("The dovetail is wider than the rail base", "dovetail", "Widen the base.",
                                    ["tongue_w", "rail_w"]))
        if self._travel(v)[1] - self._travel(v)[0] < 10:
            errs.append(RecipeError("The carriage has under 10 mm of travel between the stops", "carriage",
                                    "Lengthen the rail or shorten the carriage.", ["rail_len", "car_len"]))
        return errs

    def _dims(self, v):
        W, H, a, c = v["tongue_w"], v["tongue_h"], v["angle"], v["clearance"]
        ci = c / math.sin(math.radians(a))                      # horizontal offset that gives c normal to a flank
        car_w = W + 2 * 10.0                                    # 10 mm skirts carry the inserts
        car_h = H + c + self.TOP_T
        z0 = self.BASE_H + self.NECK                            # dovetail root = carriage underside
        return W, H, a, c, ci, car_w, car_h, z0

    def _travel(self, v):
        """Carriage centre limits along X: the printed stop at -X, the stop screw's head (5.5 mm) at +X."""
        L, Lc = v["rail_len"], v["car_len"]
        lo = -(L / 2 - self.STOP_L - Lc / 2 - 0.5)
        x_screw = L / 2 - 6.0
        hi = x_screw - 5.5 / 2 - Lc / 2 - 0.5
        return lo, hi, x_screw

    def build(self, v):
        L, Wr, Lc = v["rail_len"], v["rail_w"], v["car_len"]
        W, H, a, c, ci, car_w, car_h, z0 = self._dims(v)
        hb = self.BASE_H
        dv = craft.dovetail(length=L, width=W, height=H, angle=a, clearance=c)
        root = dv["root_w"]
        # rail base: a plate with soft plan corners and a 1 mm round on its top edges
        base = Box(L, Wr, hb, align=BOTTOM)
        base = craft.safe_fillet(base, base.edges().filter_by(Axis.Z), 2.0)
        base = craft.safe_fillet(base, base.edges().group_by(Axis.Z)[-1], 1.0)
        stages = [Stage("rail", base)]
        # --- snippet: dovetail rail on a relief neck, so the carriage bears only on the flanks
        neck = Pos(0, 0, hb - 0.2) * Box(L, root, self.NECK + 0.4, align=BOTTOM)
        tongue = Pos(0, 0, z0) * Rot(0, 0, 90) * dv.shapes["male"]          # craft.dovetail runs along Y; turn it to X
        rail = craft.fuse(base, neck + tongue)
        # the tongue's top corners are 60 deg knife edges: break them so they neither chip nor print as a thin wall
        knife = [e for e in rail.edges().filter_by(Axis.X) if abs(e.center().Z - (z0 + H)) < 1e-3]
        rail = craft.attempt("tongue edge break", [("0.5 mm chamfer", lambda: rail.chamfer(0.5, None, knife)),
                                                   ("left sharp", lambda: rail)], "", ["tongue_w"])
        # --- end snippet
        stages.append(Stage("dovetail", rail))
        # mounting: M4 socket screws down through the tongue, heads counterbored below its top
        top = z0 + H
        lo, hi, x_screw = self._travel(v)
        n = max(2, int((L - 2 * self.STOP_L - 10) // v["hole_pitch"]) + 1)
        span = (n - 1) * v["hole_pitch"]
        screw = parts.screw_clearance("M4", top, head="socket")
        for i in range(n):
            rail = rail - Pos(-span / 2 + i * v["hole_pitch"], 0, top) * screw.shape
        stages.append(Stage("mounting", rail))
        # stops: a printed block at -X standing above the tongue; an M3 screw at +X (pilot hole) the carriage meets
        stop = Pos(-L / 2 + self.STOP_L / 2, 0, hb - 0.2) * Box(self.STOP_L, Wr, top + 3 - hb + 0.2, align=BOTTOM)
        stop = craft.safe_fillet(stop, stop.edges().group_by(Axis.Z)[-1], 1.5)
        rail = craft.fuse(rail, stop)
        rail = rail - Pos(x_screw, 0, top) * parts.self_tap_pilot("M3", 8).shape
        stages.append(Stage("stops", rail))

        # carriage, modelled as it sits (slot opening down at z = 0), then printed top-down beside the rail
        car = Box(Lc, car_w, car_h, align=BOTTOM)
        car = craft.safe_fillet(car, car.edges().filter_by(Axis.Z), 3.0)
        car = craft.safe_fillet(car, car.edges().group_by(Axis.Z)[-1], 1.2)
        yc = Wr / 2 + 10 + car_w / 2
        place = lambda s: Pos(0, yc, car_h) * Rot(180, 0, 0) * s
        stages.append(Stage("carriage", rail + place(car)))
        # --- snippet: the mating slot is the tongue's section offset by the clearance normal to every face
        # Each flank moves out by c / sin(a) horizontally and keeps its angle; the top moves up by c. The opening
        # overshoots 0.2 mm below the carriage along the same flank lines, so the gap is c on every bearing face.
        r = dv["root_w"] / 2 + ci
        t = 1 / math.tan(math.radians(a))
        sec = [(-(r - 0.2 * t), -0.2), (r - 0.2 * t, -0.2), (r + (H + c) * t, H + c), (-(r + (H + c) * t), H + c)]
        slot = Pos(-(Lc + 2) / 2, 0, 0) * extrude(craft.polygon_profile(sec, plane=Plane.YZ), Lc + 2)
        car = craft.cut(car, slot)
        ends = [e for e in car.edges() if abs(abs(e.center().X) - Lc / 2) < 1e-3 and abs(e.center().Y) < W / 2 + ci + 0.05
                and 0.05 < e.center().Z < H + c + 0.05]
        car = craft.attempt("slot lead-in", [("0.8 mm chamfer", lambda: car.chamfer(0.8, None, ends)),
                                             ("0.4 mm chamfer", lambda: car.chamfer(0.4, None, ends)),
                                             ("no lead-in", lambda: car)], "Shorten the chamfer.", ["clearance"])
        mouth = [e for e in car.edges().filter_by(Axis.X) if abs(e.center().Z) < 1e-3 and abs(e.center().Y) < W / 2]
        car = craft.attempt("slot mouth edge break", [("0.4 mm chamfer", lambda: car.chamfer(0.4, None, mouth)),
                                                      ("left sharp", lambda: car)], "", ["clearance"])
        # --- end snippet
        stages.append(Stage("slot", rail + place(car)))
        # four M3 heat-set inserts in the skirts, where the top has its full depth
        ins = parts.heat_insert_pocket("M3")
        ys, xs = W / 2 + 5.0, Lc / 2 - 7.0
        for x in (-xs, xs):
            for y in (-ys, ys):
                car = car - Pos(x, y, car_h) * ins.shape
        stages.append(Stage("inserts", rail + place(car)))
        return parts.checked(stages)

    def derived(self, v):
        W, H, a, c, ci, car_w, car_h, z0 = self._dims(v)
        lo, hi, _ = self._travel(v)
        return [{"key": "travel", "label": "Carriage travel", "value": round(hi - lo, 2), "unit": "mm", "feature": "stops",
                 "formula": "between the printed stop and the M3 stop screw's head", "interface": False},
                {"key": "flank_offset", "label": "Slot growth across the flank", "value": round(ci, 3), "unit": "mm",
                 "feature": "slot", "formula": "clearance / sin(flank angle)", "interface": True},
                {"key": "skirt_gap", "label": "Gap under the carriage skirts", "value": self.NECK, "unit": "mm",
                 "feature": "dovetail", "formula": "relief neck height (carriage bears on the flanks only)",
                 "interface": True},
                {"key": "root_w", "label": "Dovetail root width", "value": round(W - 2 * H / math.tan(math.radians(a)), 2),
                 "unit": "mm", "feature": "dovetail", "formula": "top width - 2 h / tan(angle)", "interface": True}]

    def assembly(self, v):
        W, H, a, c, ci, car_w, car_h, z0 = self._dims(v)
        yc = v["rail_w"] / 2 + 10 + car_w / 2
        lo, hi, x_screw = self._travel(v)
        top = z0 + H
        return Assembly(
            parts=[Part("rail", "Rail", (0, 0, 1.0), note="Screw the rail down through its counterbored holes."),
                   Part("carriage", "Carriage", (0, yc, 1.0), move=(0, yc, car_h + z0), rotate=(180, 0, 0),
                        explode=(0, 0, 25), note="Slide the carriage onto the rail from the open end.")],
            joints=[slide("carriage", (1, 0, 0), (round(lo, 2), round(hi, 2)), 7, id="travel", label="Carriage travel")],
            hardware=[Hardware("M4 socket head screw", "M4 x 12", max(2, int((v["rail_len"] - 26) // v["hole_pitch"]) + 1),
                               "ISO 4762", "Mount the rail.", after="rail"),
                      Hardware("M3 socket head screw (stop)", "M3 x 8", 1, "ISO 4762",
                               "Drive the stop screw in after the carriage is on; leave its head standing.",
                               after="carriage"),
                      Hardware("M3 heat-set insert", "M3 x 5.7", 4, "CNC Kitchen", "Press the inserts into the carriage.",
                               after="carriage")])

    def appearance(self, v):
        return [{"features": ["carriage", "slot", "inserts"], "finish": "petg", "color": "#c8562b"},
                {"features": ["rail", "dovetail", "mounting", "stops"], "finish": "matte", "color": "#2f3338"}]
