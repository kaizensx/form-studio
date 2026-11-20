"""Split clamp shaft coupler, 5 mm stepper shaft to 8 mm leadscrew: one body with stepped bores, an axial slit, a
cross slot that lets each half clamp its own shaft, and two M3 clamp screws with counterbores and captive nut traps,
heads on opposite sides. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Clamp shaft coupler 5 to 8 mm",
    "category": "mechanical",
    "tags": ["coupler", "coupling", "shaft", "clamp", "split", "stepper", "nema17", "leadscrew", "5mm", "8mm", "m3",
             "nut trap", "counterbore", "slit", "mechanical", "drive"],
    "techniques": ["stepped bores with a named slip clearance", "axial slit + cross slot so each half clamps alone",
                   "tangential M3 clamp screws: parts.clearance_d / parts.head_dims counterbores",
                   "parts.nut_trap turned with Rot(-90, 0, 0) to open on a side face",
                   "screw position computed from the bore so the hole never breaks into it",
                   "end and bore chamfers with craft.attempt fallbacks"],
    "lessons": [
        "Standard numbers first: NEMA 17 steppers have a 5 mm shaft, T8 leadscrews an 8 mm journal; the bores are those "
        "plus a slip clearance (0.1-0.2 mm on a diameter for FDM) so the shafts slide in and the screws do the gripping.",
        "A clamp needs somewhere to go: the axial slit opens the bore on one side, the rest of the ring is the hinge. The "
        "cross slot between the halves stops the stiff 8 mm side from holding the 5 mm side open, so each screw clamps "
        "its own shaft.",
        "The screws run tangentially across the slit, placed from the bore: offset = largest bore radius + clearance + "
        "screw hole radius + a 1.4 mm wall. Compute it; a hole that nicks the bore leaves a ridge on the shaft.",
        "Capture the nut in a hex trap so one hex key does the whole job; alternate heads and nuts between the halves "
        "so the coupler is closer to balanced when it spins.",
        "Print it standing on its end: the bores come out round and the slit needs no support; chamfer the bore "
        "entries so the shafts start and the first-layer squish does not close the bore.",
    ],
}


class Design(Recipe):
    title, summary = "Shaft coupler", "Split clamp coupler for a 5 mm stepper shaft and an 8 mm leadscrew, M3 clamps."
    params = [
        Param("d_motor", "Motor shaft", 5, 3, 8, 0.5, "mm", "brief", "bores", "NEMA 17 stepper shaft: 5 mm.", "specified"),
        Param("d_screw", "Leadscrew journal", 8, 4, 10, 0.5, "mm", "brief", "bores", "T8 leadscrew: 8 mm.", "specified"),
        Param("bore_clearance", "Bore clearance (on diameter)", 0.15, 0.0, 0.4, 0.05, "mm", "interface", "bores",
              "Slip fit for FDM; the clamp closes the rest."),
        Param("od", "Outside diameter", 25, 22, 32, 0.5, "mm", "form", "body"),
        Param("length", "Length", 25, 22, 40, 0.5, "mm", "form", "body"),
        Param("slit", "Slit width", 1.0, 0.6, 2.0, 0.1, "mm", "form", "slit"),
    ]
    features = [Feature("body", "Body", "structure"), Feature("bores", "Shaft bores", "interface"),
                Feature("slit", "Clamp slit", "structure"), Feature("cross_slot", "Cross slot", "structure"),
                Feature("screws", "M3 clamp screws", "interface"), Feature("nut_traps", "Nut traps", "interface")]

    HOLE = parts.clearance_d("M3")[0]
    HEAD_D, HEAD_H = parts.head_dims("M3", "socket")[:2]

    def _layout(self, v):
        rb = max(v["d_motor"], v["d_screw"]) / 2 + v["bore_clearance"] / 2
        xs = rb + self.HOLE / 2 + 1.4                       # screw axis offset from the shaft axis
        ys = v["slit"] / 2 + 4.0                           # head / nut seat: 4 mm of jaw each side of the slit
        R = v["od"] / 2
        y_out = math.sqrt(max(R * R - xs * xs, 0))         # where the outside surface is above the screw
        return rb, xs, ys, R, y_out

    def constraints(self, v):
        rb, xs, ys, R, y_out = self._layout(v)
        errs = []
        if y_out < ys + self.HEAD_H + 0.5:
            errs.append(RecipeError("The screw heads would stand proud of the body", "screws",
                                    "Make the coupler larger in diameter.", ["od", "d_screw"]))
        if xs + (self.HEAD_D + 0.4) / 2 > R - 0.3:
            errs.append(RecipeError("The counterbores run off the side of the body", "screws",
                                    "Make the coupler larger in diameter.", ["od"]))
        if v["length"] < 4 * (self.HEAD_D + 0.4) / 2 + 2 * 1.5 + v["slit"]:
            errs.append(RecipeError("The halves are too short for their clamp screws", "screws", "Make it longer.",
                                    ["length"]))
        return errs

    def build(self, v):
        L, c = v["length"], v["bore_clearance"]
        rb, xs, ys, R, y_out = self._layout(v)
        body = Cylinder(R, L, align=BOTTOM)
        # a chamfer on the bed edge (no overhang, hides elephant's foot), a round on the top edge the hand meets
        body = craft.attempt("bed chamfer", [("1 mm", lambda: body.chamfer(1.0, None, body.edges().group_by(Axis.Z)[0])),
                                             ("sharp", lambda: body)], "", ["od"])
        body = craft.safe_fillet(body, body.edges().group_by(Axis.Z)[-1], 1.5)
        stages = [Stage("body", body)]
        # bores: the motor shaft from the bed up, the leadscrew from the top down, meeting at the middle
        h = L / 2
        b1 = Pos(0, 0, -0.2) * Cylinder((v["d_motor"] + c) / 2, h + 0.4, align=BOTTOM)
        b2 = Pos(0, 0, h) * Cylinder((v["d_screw"] + c) / 2, h + 0.2, align=BOTTOM)
        body = body - b1 - b2
        rims = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and e.radius < rb + 0.01
                and (e.center().Z < 0.01 or e.center().Z > L - 0.01)]
        body = craft.attempt("bore lead-ins", [("0.5 mm chamfer", lambda: body.chamfer(0.5, None, rims)),
                                               ("sharp", lambda: body)], "", ["bore_clearance"])
        stages.append(Stage("bores", body))
        # --- snippet: a clamp that can close: axial slit to one side, cross slot between the two clamping halves
        body = body - Pos(R / 2 + rb / 2, 0, -1) * Box(R, v["slit"], L + 2, align=BOTTOM)
        stages.append(Stage("slit", body))
        body = body - Pos(R / 2 - 0.5, 0, h - v["slit"] / 2) * Box(R + 1.0 + 0.2, 2 * R + 2, v["slit"], align=BOTTOM)
        # --- end snippet
        stages.append(Stage("cross_slot", body))
        # --- snippet: tangential clamp screws, counterbored head on one side, captive hex nut on the other
        nut = parts.nut_trap("M3", "hex", depth=y_out - ys + 2.0)
        z1, z2 = h / 2, h + h / 2
        for z, head_side in ((z1, -1), (z2, 1)):                     # alternate the heads for balance
            body = body - Pos(xs, -R - 1, z) * Rot(-90, 0, 0) * Cylinder(self.HOLE / 2, 2 * R + 2, align=BOTTOM)
            cb = Cylinder((self.HEAD_D + 0.4) / 2, R, align=BOTTOM)    # from the head seat outward
            body = body - Pos(xs, head_side * ys, z) * Rot(-90 * head_side, 0, 0) * cb
        stages.append(Stage("screws", body))
        for z, head_side in ((z1, -1), (z2, 1)):
            nut_side = -head_side
            # nut_trap opens at z = 0 and goes down; Rot(-90, 0, 0) makes it go -Y, Rot(90, 0, 0) +Y
            seat = nut_side * (ys + nut["depth"])
            body = body - Pos(xs, seat, z) * Rot(-90 * nut_side, 0, 0) * Rot(0, 0, 30) * nut.shape
        # --- end snippet
        # soften every edge the cuts left on the outside surface: it spins next to fingers and wires
        rim = [e for e in body.edges() if e.geom_type.name != "CIRCLE"
               and math.hypot(e.center().X, e.center().Y) > R - 0.6 and 0.5 < e.center().Z < L - 0.5]
        body = craft.safe_fillet(body, rim, 0.4)
        stages.append(Stage("nut_traps", body))
        return parts.checked(stages)

    def derived(self, v):
        rb, xs, ys, R, y_out = self._layout(v)
        return [{"key": "screw_offset", "label": "Clamp screw offset from the axis", "value": round(xs, 2), "unit": "mm",
                 "feature": "screws", "formula": "largest bore radius + M3 hole radius + 1.4 mm wall", "interface": False},
                {"key": "bore_motor", "label": "Motor bore", "value": v["d_motor"] + v["bore_clearance"], "unit": "mm",
                 "feature": "bores", "formula": "shaft + clearance", "interface": True},
                {"key": "bore_screw", "label": "Leadscrew bore", "value": v["d_screw"] + v["bore_clearance"], "unit": "mm",
                 "feature": "bores", "formula": "journal + clearance", "interface": True},
                {"key": "screw_len", "label": "Clamp screw length", "value": round(2 * ys + 2.4, 1), "unit": "mm",
                 "feature": "screws", "formula": "seat to seat + nut height (choose the next stock length)",
                 "interface": False}]

    def appearance(self, v):
        return [{"features": ["body", "bores", "slit", "cross_slot", "screws", "nut_traps"], "finish": "metal",
                 "color": "#9aa3ab"}]
