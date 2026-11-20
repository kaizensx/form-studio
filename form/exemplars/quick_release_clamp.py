"""Quick-release tube clamp: a split collar with two ears, closed by an over-centre cam lever turning on an M5 pin.
The cam is an eccentric whose lift squeezes the ears by the collar's closing gap. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Box, Cylinder, Pos, Rot

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Quick-release clamp",
    "category": "mechanical",
    "tags": ["clamp", "quick-release", "cam", "lever", "tube", "collar", "bike", "seatpost", "mechanism", "split",
             "over-centre"],
    "techniques": ["split collar with a closing gap", "eccentric cam head with a cross pin and a bolt slot",
                   "pin through ears from form.parts clearance holes", "ribbed ears", "lever swept with a "
                   "superellipse section", "two printed parts with an assembly() hinge"],
    "lessons": [
        "Size the mechanism from the job: to grip, the split must close by 2 pi x the bore clearance, so the bolt must be "
        "pulled at least that far; the cam's throw (2 x its eccentricity) is chosen with a margin over it.",
        "The lever is a bike-style quick release: an M5 bolt through both ears ends in a cross hole; a 3 mm pin through "
        "the lever's cam head and that hole sits off the cam's centre, so turning the lever draws the bolt and goes "
        "over centre, holding itself shut. Throw and closing gap are in derived().",
        "Print the collar standing (the bore along Z, layers around the hoop take the hoop stress) and the lever flat.",
        "Give the lever a real section (a soft superellipse, thicker at the cam) and the ears a rib, not just "
        "rectangles.",
    ],
}


class Design(Recipe):
    title, summary = "Quick-release clamp", "Split tube collar with ribbed ears and an eccentric cam lever on an M5 pin."
    solids = 2
    params = [
        Param("tube_d", "Tube diameter", 25.4, 10, 50, 0.1, "mm", "brief", "collar", "Measure the tube."),
        Param("fit", "Bore clearance / side", 0.2, 0, 0.6, 0.05, "mm", "interface", "collar"),
        Param("height", "Collar height", 16, 8, 40, 0.5, "mm", "form", "collar"),
        Param("wall", "Collar wall", 4.0, 2.4, 8, 0.1, "mm", "form", "collar"),
        Param("gap", "Split gap", 2.0, 1.0, 5, 0.1, "mm", "form", "split"),
        Param("eccentric", "Cam eccentricity", 1.6, 0.6, 3, 0.1, "mm", "interface", "lever"),
    ]
    features = [Feature("collar", "Collar", "structure"), Feature("ears", "Ears", "structure"),
                Feature("split", "Split", "interface"), Feature("pin_hole", "Pin hole", "interface"),
                Feature("lever", "Cam lever", "interface")]

    def constraints(self, v):
        squeeze = v["gap"] * 0.6
        if v["eccentric"] < 0.5 * squeeze:
            return [RecipeError("The cam's throw is too small to close the split", "lever", "Raise the eccentricity.",
                                ["eccentric", "gap"])]
        return []

    def build(self, v):
        R = v["tube_d"] / 2 + v["fit"]
        H, t, g = v["height"], v["wall"], v["gap"]
        Ro = R + t
        collar = Cylinder(Ro, H, align=BOTTOM) - Pos(0, 0, -1) * Cylinder(R, H + 2, align=BOTTOM)
        collar = craft.safe_fillet(collar, [e for e in collar.edges() if e.geom_type.name == "CIRCLE" and e.radius > Ro - 0.01], 1.2)
        stages = [Stage("collar", collar)]
        # ears on +X: two blocks either side of the split, joined to the collar, with a rib each
        ear_l, ear_w = 14.0, 7.0
        ears = Pos(Ro + ear_l / 2 - 3, 0, 0) * Box(ear_l + 6, 2 * ear_w + g, H, align=BOTTOM)
        ears = craft.safe_fillet(ears, ears.edges().filter_by(Axis.Z).group_by(Axis.X)[-1], 3.0)
        body = collar + ears
        body = body - Pos(0, 0, -1) * Cylinder(R, H + 2, align=BOTTOM)
        stages.append(Stage("ears", body))
        body = body - Pos(Ro + ear_l / 2, 0, H / 2) * Box(ear_l + 2 * t + 6, g, H + 2) - Pos(R + t / 2, 0, H / 2) * Box(t + 2, g, H + 2)
        stages.append(Stage("split", body))
        px = Ro + ear_l * 0.55
        pin_d = parts.clearance_d("M5")[0]
        body = body - Pos(px, 0, H / 2) * Rot(90, 0, 0) * Cylinder(pin_d / 2, 2 * ear_w + g + 4)
        stages.append(Stage("pin_hole", body))
        # lever, printed flat beside the collar. Its cam head is a disc split by a slot for the M5 bolt; a 3 mm cross
        # pin through both cheeks sits `eccentric` off the disc centre, so turning the lever pulls the bolt by the throw.
        e = v["eccentric"]
        cam_r, cam_t, slot_w = 9.0, 12.0, 5.6
        lx, ly = 0.0, -(Ro + cam_r + 12)
        cam = Pos(lx, ly, 0) * Cylinder(cam_r, cam_t, align=BOTTOM)
        cam = craft.safe_fillet(cam, cam.edges(), 1.2)
        handle = craft.sweep_spline(craft.superellipse_face(4.0, 4.8, 2.6),    # thinner than the cam: no coincident faces
                                    [(lx + cam_r - 3, ly, cam_t / 2), (lx + cam_r + 22, ly - 3, cam_t / 2),
                                     (lx + cam_r + 52, ly - 1, cam_t / 2)])
        tip = handle.edges().group_by(Axis.X)[-1]
        handle = craft.safe_fillet(handle, tip, 3.0)                      # a rounded thumb end, not a cut-off tube
        lever = cam + handle
        # bolt slot from the pin out through the cam face on -X, between two cheeks
        lever = lever - Pos(lx - cam_r / 2 - 1 + e, ly, cam_t / 2) * Box(cam_r + 2, 20, slot_w)
        lever = lever - Pos(lx + e, ly, -1) * Cylinder(3.2 / 2, cam_t + 2, align=BOTTOM)
        body = body + lever
        stages.append(Stage("lever", body))
        return parts.checked(stages)

    def derived(self, v):
        R = v["tube_d"] / 2 + v["fit"]
        return [{"key": "closing", "label": "Gap closed to grip the tube", "value": 2 * math.pi * v["fit"], "unit": "mm",
                 "feature": "split", "formula": "2 pi x bore clearance", "interface": True},
                {"key": "cam_throw", "label": "Cam throw", "value": 2 * v["eccentric"], "unit": "mm", "feature": "lever",
                 "formula": "2 x eccentricity (open to over-centre)", "interface": True},
                {"key": "bore_d", "label": "Bore", "value": 2 * R, "unit": "mm", "feature": "collar",
                 "formula": "tube + 2 x clearance", "interface": True}]
