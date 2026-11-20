"""Pillow block for a 608 bearing (8 x 22 x 7): a housing on a pedestal with a press-fit seat and stop lip, a foot
with two slotted mounting holes, three ribs carrying the housing to the foot, and the ISO housing tolerance from
craft.bearing_fit beside the printed seat. Form Studio exemplar design."""
from build123d import Align, Axis, Box, Circle, Plane, Pos, Rot, SlotOverall, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "608 bearing pillow block",
    "category": "mechanical",
    "tags": ["pillow block", "bearing", "608", "housing", "shaft support", "8mm", "skateboard bearing", "press fit",
             "slot", "rib", "mount", "plummer", "mechanical", "iso fit"],
    "techniques": ["parts.bearing_seat (published 608 dims) with a stop lip", "craft.bearing_fit / iso_fit "
                   "housing tolerance in derived() next to the printed oversize", "pedestal + housing as one XZ "
                   "profile extruded, flat back face to print on", "three craft.gusset-style ribs in front of the "
                   "housing", "SlotOverall mounting slots across the shaft line", "lead-in chamfer on the seat"],
    "lessons": [
        "Use the bearing's published numbers: a 608 is 8 x 22 x 7 mm (ISO 15). parts.bearing_seat cuts the seat and a "
        "lip whose hole sits between the inner ring's shoulder and the housing shoulder, so the outer ring stops on it "
        "and the inner ring turns free.",
        "The fit has two numbers and both are worth showing: craft.bearing_fit gives the machinist's H7 (+0 / +21 "
        "microns on 22 mm, stationary outer ring) and the printed seat is the bearing OD plus a calibrated oversize, "
        "because FDM holes print small. Calibrate that one number with a test ring.",
        "Print it on its flat back face, not its foot: the bore is then a true circle in the layers (a horizontal "
        "22 mm bore prints oval and sags at the top), and the ribs stand up as 45 deg-ish triangles.",
        "Slots run along the foot, across the shaft line, so two blocks can be aligned on one shaft before the screws "
        "are tightened; a pair of blocks is never perfectly placed by holes.",
        "The load goes housing -> pedestal -> foot: the pedestal is tangent to the housing (no notch), its roots are "
        "filleted, and ribs in front of the housing take the axial push.",
        "OCCT fillets run along every tangent-continuous edge: one foot edge pulls the round round the corner arcs, "
        "the root fillet and the pedestal onto the rim. Round the housing rim on the housing alone before the ribs "
        "split it, and leave the print face's edges out of every selection.",
    ],
}


class Design(Recipe):
    title, summary = "608 pillow block", "Bearing housing for a 608 with a press-fit seat, ribs and slotted feet."
    params = [
        Param("centre_h", "Shaft centre height", 22, 18, 40, 0.5, "mm", "brief", "housing"),
        Param("seat_fit", "Seat oversize (printed)", 0.05, -0.05, 0.2, 0.01, "mm", "interface", "seat",
              "Added to the 22 mm OD; 0-0.1 is a light press on most FDM printers. Calibrate."),
        Param("wall", "Housing wall", 5, 4.5, 8, 0.5, "mm", "form", "housing"),
        Param("foot_len", "Foot length", 80, 74, 120, 1, "mm", "form", "foot"),
        Param("foot_depth", "Foot depth", 22, 16, 32, 0.5, "mm", "form", "foot"),
        Param("screw", "Mounting screw", 5, 4, 6, 1, "", "brief", "foot", "Metric diameter."),
    ]
    features = [Feature("housing", "Housing and pedestal", "structure"), Feature("foot", "Foot", "structure"),
                Feature("ribs", "Ribs", "structure"), Feature("seat", "608 bearing seat", "interface"),
                Feature("slots", "Mounting slots", "interface")]

    FOOT_T, HOUSE_D = 6.0, 10.0                                   # foot thickness, housing depth along the shaft

    def constraints(self, v):
        Rh = 11 + v["wall"]
        errs = []
        if v["centre_h"] < Rh + 1:
            errs.append(RecipeError("The housing would sink into the base", "housing", "Raise the centre or thin the wall.",
                                    ["centre_h", "wall"]))
        d = parts.clearance_d(f"M{int(v['screw'])}")[0]
        if v["foot_len"] / 2 - 4 - (d + 6) < Rh + 5:
            errs.append(RecipeError("The slots run into the pedestal", "slots", "Make the foot longer.",
                                    ["foot_len", "wall", "screw"]))
        return errs

    def build(self, v):
        Hc, Rh, L, Wf, tf, Wh = v["centre_h"], 11 + v["wall"], v["foot_len"], v["foot_depth"], self.FOOT_T, self.HOUSE_D
        # --- snippet: housing + pedestal as one profile in XZ (tangent sides, no notch), extruded along the shaft (+Y)
        ped = craft.polygon_profile([(-Rh, tf - 0.2), (Rh, tf - 0.2), (Rh, Hc), (-Rh, Hc)], plane=Plane.XZ)
        prof = ped + Pos(0, 0, Hc) * Rot(90, 0, 0) * Circle(Rh)
        house = extrude(prof, -Wh)                                     # Plane.XZ faces -Y: extrude toward +Y
        bb = house.bounding_box()
        house = Pos(0, -bb.min.Y, 0) * house
        # --- end snippet
        # round the housing's front rim now, while it is one clean arc (ribs fused later would split it); the back face
        # is the print face and stays flat and sharp
        rim = [e for e in house.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Y - Wh) < 1e-3]
        house = craft.safe_fillet(house, rim, 1.0)
        stages = [Stage("housing", house)]
        foot = Pos(0, Wf / 2, 0) * Box(L, Wf, tf, align=BOTTOM)
        foot = craft.safe_fillet(foot, foot.edges().filter_by(Axis.Z), 6.0)
        body = craft.fuse(foot, house)
        roots = [e for e in body.edges().filter_by(Axis.Y) if abs(e.center().Z - tf) < 1e-3 and abs(abs(e.center().X) - Rh) < 1e-3]
        body = craft.safe_fillet(body, roots, 4.0)
        stages.append(Stage("foot", body))
        # ribs in front of the housing, down to the foot: two at the sides, one under the bore
        for x, top in ((-(Rh - 2.35), Hc), (Rh - 2.35, Hc), (0, Hc - 11 - 1.5)):     # inside the rim round
            if top - tf < 3:                                          # no room for the middle rib under a low bore
                continue
            rib = craft.gusset(Wf - Wh - 1.0, top - tf, t=2.5, at=(0, 0, 0))
            rib = Pos(x, Wh - 0.2, tf - 0.2) * Rot(0, 0, 90) * Rot(0, 0, 0) * rib
            body = craft.fuse(body, rib)
        stages.append(Stage("ribs", body))
        # --- snippet: the 608 seat from the front face, a stop lip behind it, a lead-in chamfer
        seat = parts.bearing_seat("608", fit=v["seat_fit"], through=Wh - 7 + 0.4, lip=True)
        body = body - Pos(0, Wh, Hc) * Rot(-90, 0, 0) * seat.shape
        rim = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Y - Wh) < 1e-3
               and abs(e.radius - seat["seat_d"] / 2) < 1e-3]
        body = craft.attempt("seat lead-in", [("0.6 mm chamfer", lambda: body.chamfer(0.6, None, rim)),
                                              ("sharp", lambda: body)], "", ["seat_fit"])
        # --- end snippet
        stages.append(Stage("seat", body))
        d = parts.clearance_d(f"M{int(v['screw'])}")[0]
        sl = d + 6                                                     # 6 mm of adjustment
        xs = L / 2 - 4 - sl / 2
        for x in (-xs, xs):
            body = body - Pos(x, Wf / 2, -1) * extrude(SlotOverall(sl, d), tf + 2)
        # round the slot rims only. The foot's top perimeter stays sharp on purpose: a fillet there propagates round
        # the tangent chain (corner arcs -> back edge -> root fillet -> pedestal -> rim) onto the back, the print face
        top = [e for e in body.edges() if abs(e.center().Z - tf) < 1e-3 and abs(abs(e.center().X) - xs) < sl / 2 + 0.01
               and abs(e.center().Y - Wf / 2) < d / 2 + 0.01]
        body = craft.safe_fillet(body, top, 0.8)
        stages.append(Stage("slots", body))
        self._seat = seat
        return parts.checked(stages)

    def derived(self, v):
        b = craft.bearing_fit("608", "housing", "inner")
        f = craft.iso_fit("H7/h6", 22)
        seat = parts.bearing_seat("608", fit=v["seat_fit"], through=3.4)
        return seat.derived("seat", "seat.") + [
            {"key": "iso_housing", "label": f"Housing tolerance (machined, {b['tolerance']})",
             "value": f"{b['limits'][0]:.3f} - {b['limits'][1]:.3f}", "unit": "mm", "feature": "seat",
             "formula": b["why"], "interface": True},
            {"key": "iso_clearance", "label": "H7 on a 22 mm ring: clearance range", "value": f"{f['clearance'][0]:.3f} - "
             f"{f['clearance'][1]:.3f}", "unit": "mm", "feature": "seat", "formula": "ISO 286 H7/h6 (outer ring ~h6)",
             "interface": True},
            {"key": "printed_seat", "label": "Printed seat diameter", "value": 22 + v["seat_fit"], "unit": "mm",
             "feature": "seat", "formula": "608 OD + calibrated oversize (assumed)", "interface": True}]

    def appearance(self, v):
        return [{"features": ["housing", "foot", "ribs", "seat", "slots"], "finish": "petg", "color": "#e3a21a"}]
