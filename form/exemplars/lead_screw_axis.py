"""Lead-screw axis: a printed flanged nut for a T8 x 8 lead screw (four-start ISO trapezoidal thread, printed in the
nut) and an end bracket that carries the screw's 608 bearing, both screwed to aluminium with stock screws whose
lengths form.parts chooses. The standard-hardware exemplar: real threads, a real bearing, real screws and a BOM with
masses. Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import Assembly, Feature, Hardware, Param, Part, Recipe, RecipeError, Stage, slide

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Lead-screw nut and bearing bracket",
    "category": "mechanical",
    "tags": ["lead screw", "leadscrew", "t8", "tr8x8", "trapezoidal", "acme", "nut", "anti-backlash", "z axis",
             "linear axis", "608", "bearing", "bracket", "end support", "flange nut", "multi-start", "thread",
             "standard hardware", "bom", "screws", "mechanism"],
    "techniques": ["parts.trapezoidal_thread(8, 2, starts=4, external=False) cut through the nut body",
                   "parts.bolted_joint(size, clamp, into='tap') for the flange and bracket screws: counterbore or "
                   "countersink, and a stock screw length chosen from the plate it screws into",
                   "parts.bearing_seat('608') with a lip, parts.bearing('608').bom() for the BOM with its mass",
                   "joint.hardware(qty, after=...) for the screw rows, slide() joint for the nut's travel"],
    "lessons": [
        "Print a lead-screw nut's thread instead of modelling a sleeve for a brass nut: parts.trapezoidal_thread "
        "builds the real four-start Tr8 x 8 profile (lead 8 = pitch 2 x 4 starts) with a named diametral "
        "clearance, and the nut prints flange-down so the thread's flanks lean 15 deg from vertical.",
        "Let the joint pick the screw: bolted_joint knows the counterbore, the clamped thickness and how much thread "
        "the plate below needs (1.5 d into aluminium), and returns a stock ISO length, never one typed in.",
        "A bearing seat is a fit plus a stop: the seat is the 608's 22 mm + a press allowance, the lip under it "
        "stops the outer ring and clears the inner ring, so the screw's shoulder can bear on the inner ring.",
        "The BOM comes from the hardware objects: bearing('608').bom(), joint.hardware(4) carry the standard, the "
        "size and a computed mass, so the bill of materials is never retyped.",
    ],
}


class Design(Recipe):
    title, summary = "Lead-screw axis", "Printed Tr8x8 nut with a flange and a 608 end bracket, on stock screws."
    solids = 2
    params = [
        Param("flange_d", "Nut flange diameter", 40, 36, 56, 0.5, "mm", "form", "flange"),
        Param("flange_t", "Nut flange thickness", 6, 5, 10, 0.5, "mm", "form", "flange"),
        Param("nut_len", "Nut body length", 16, 10, 30, 0.5, "mm", "form", "nut_body"),
        Param("clearance", "Thread clearance (diametral)", 0.3, 0.1, 0.6, 0.05, "mm", "interface", "thread",
              "Each thread moves away from the screw by half of it. 0.3 runs free on most FDM printers."),
        Param("bracket_w", "Bracket width", 56, 46, 80, 1, "mm", "form", "bracket"),
        Param("bracket_t", "Bracket thickness", 11, 9, 16, 0.5, "mm", "form", "bracket"),
        Param("travel", "Nut travel", 200, 50, 400, 5, "mm", "brief", "thread"),
    ]
    features = [Feature("nut_body", "Nut body", "structure"), Feature("flange", "Nut flange", "structure"),
                Feature("thread", "Tr8x8 thread", "interface"), Feature("flange_holes", "Flange screws", "interface"),
                Feature("bracket", "End bracket", "structure"), Feature("seat", "608 bearing seat", "interface"),
                Feature("mounts", "Bracket screws", "interface")]

    NUT_X = 60.0                                     # the nut prints beside the bracket
    PCD = 0.0

    def constraints(self, v):
        if v["flange_d"] < 36:
            return [RecipeError("The flange is too small for its screws", "flange", "Use 36 mm or more.", ["flange_d"])]
        if v["bracket_t"] < 7 + 2:                    # 608 width 7 + a lip under it
            return [RecipeError("The bracket is thinner than the bearing and its lip", "bracket", "Thicken it.", ["bracket_t"])]
        return []

    def _joints(self, v):
        flange = parts.bolted_joint("M3", v["flange_t"], into="tap", head="countersunk")
        mount = parts.bolted_joint("M4", v["bracket_t"] - 4.0, into="tap", head="socket")
        return flange, mount

    def build(self, v):
        D, T, L = v["flange_d"], v["flange_t"], v["nut_len"]
        H = T + L
        x0 = self.NUT_X
        # nut: flange on the bed, body above it, a chamfered top edge so the screw finds the thread
        body = Cylinder(10.0, H, align=BOTTOM)
        body = craft.safe_fillet(body, body.edges().group_by(Axis.Z)[-1], 1.0)
        stages = [Stage("nut_body", Pos(x0, 0, 0) * body)]
        flange = Cylinder(D / 2, T, align=BOTTOM)
        flange = craft.safe_fillet(flange, flange.edges().group_by(Axis.Z)[0], 0.6)
        nut = craft.fuse(body, flange)
        nut = craft.safe_fillet(nut, [e for e in nut.edges() if abs(e.center().Z - T) < 1e-3 and e.radius < 10.5], 1.5)
        stages.append(Stage("flange", Pos(x0, 0, 0) * nut))
        # --- snippet: a printed four-start Tr8x8 thread through the nut
        th = parts.trapezoidal_thread(8, 2, H, starts=4, external=False, clearance=v["clearance"])
        nut = nut - Pos(0, 0, H) * th.shape                       # the cutter opens at z = 0 and goes down
        nut = nut - Pos(0, 0, -0.1) * Cylinder(th["modelled_major_d"] / 2, 0.6, align=BOTTOM)    # elephant-foot relief
        # --- end snippet
        stages.append(Stage("thread", Pos(x0, 0, 0) * nut))
        # --- snippet: flange screws from a bolted joint (countersunk M3 into a tapped aluminium carriage)
        flange_j, mount_j = self._joints(v)
        r = (D / 2 + 10.0) / 2                      # midway between the body and the rim
        for i in range(4):
            a = 45 + 90 * i
            # the joint's z = 0 is the clamped part's top face: here the flange's underside, as the nut is printed
            nut = nut - Rot(0, 0, a) * Pos(r, 0, 0) * Rot(180, 0, 0) * flange_j.top.shape
        # --- end snippet
        stages.append(Stage("flange_holes", Pos(x0, 0, 0) * nut))
        nut = Pos(x0, 0, 0) * nut

        # bracket: a plate with a raised boss around the bearing, mounting ears at both ends
        W, Tb = v["bracket_w"], v["bracket_t"]
        plate = Box(W, 26, Tb - 4, align=BOTTOM)
        plate = craft.safe_fillet(plate, plate.edges().filter_by(Axis.Z), 5.0)
        boss = Cylinder(15.0, Tb, align=BOTTOM)
        br = craft.fuse(plate, boss)
        br = craft.safe_fillet(br, br.edges().group_by(Axis.Z)[-1], 1.0)
        stages.append(Stage("bracket", nut + br))
        seat = parts.bearing_seat("608", fit=0.05, through=Tb - 7 + 0.5)
        br = br - Pos(0, 0, Tb) * seat.shape
        stages.append(Stage("seat", nut + br))
        for x in (-(W / 2 - 7), W / 2 - 7):
            br = br - Pos(x, 0, Tb - 4) * mount_j.top.shape
        stages.append(Stage("mounts", nut + br))
        return parts.checked(stages)

    def derived(self, v):
        flange_j, mount_j = self._joints(v)
        th = parts.trapezoidal_thread(8, 2, 10, starts=4, external=False, clearance=v["clearance"])
        out = th.derived("thread", "thread.", ("modelled_minor_d", "clearance"))
        out += [{"key": "flange_screw", "label": "Flange screw length (M3 countersunk)", "value": flange_j.length,
                 "unit": "mm", "feature": "flange_holes", "formula": "stock ISO 10642 length for the flange + 1.5 d "
                 "into aluminium (parts.bolted_joint)", "interface": True},
                {"key": "mount_screw", "label": "Bracket screw length (M4 socket)", "value": mount_j.length, "unit": "mm",
                 "feature": "mounts", "formula": "stock ISO 4762 length (parts.bolted_joint)", "interface": True}]
        out += parts.bearing_seat("608", fit=0.05).derived("seat", "seat.", ("seat_d",))
        return out

    def assembly(self, v):
        flange_j, mount_j = self._joints(v)
        Tb, T = v["bracket_t"], v["flange_t"]
        lift = Tb + 30.0                                         # nut's flange 30 mm above the bracket, at the axis
        b608 = parts.bearing("608")
        screw = Hardware("T8 lead screw, 4 starts", f"Tr8x8 (P2) x {v['travel'] + 60:g} mm", 1, "ISO 2904 (stock T8)",
                         "Push the screw's end through the bearing.", after="bracket", material="stainless")
        return Assembly(
            parts=[Part("bracket", "End bracket", (v["bracket_w"] / 2 - 2, 10, 2.0), note="Screw the bracket to the frame."),
                   Part("nut", "Lead-screw nut", (self.NUT_X + v["flange_d"] / 2 - 2, 0, 1.0), move=(-self.NUT_X, 0, lift),
                        explode=(0, 0, 30), note="Thread the nut onto the lead screw, flange down.")],
            joints=[slide("nut", (0, 0, 1), (0, float(v["travel"])), 9, id="travel", label="Nut travel")],
            hardware=[b608.bom(1, "Press the 608 into the bracket's seat.", "bracket"), screw]
            + mount_j.hardware(2, after="bracket", note="Screw the bracket down.")
            + flange_j.hardware(4, after="nut", note="Screw the carriage onto the flange."))

    def appearance(self, v):
        return [{"features": ["nut_body", "flange", "thread", "flange_holes"], "finish": "petg", "color": "#c8562b"},
                {"features": ["bracket", "seat", "mounts"], "finish": "matte", "color": "#2f3338"}]
