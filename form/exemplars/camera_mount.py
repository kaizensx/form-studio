"""Arca-Swiss compatible quick-release plate and a matching clamp jaw: a 38 mm dovetail with 45 deg flanks, a
1/4"-20 screw slot with a counterbore, a grip-textured top and a safety stop. Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cylinder, Plane, Pos, Rot, SlotOverall, Wire, extrude, make_face

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Camera mount with dovetail",
    "tags": ["camera", "mount", "arca", "arca-swiss", "dovetail", "quick-release", "plate", "tripod", "clamp", "slot",
             "1/4-20", "photography"],
    "techniques": ["dovetail cross-section from the published standard (38 mm, 45 deg)", "craft.dovetail for the "
                   "clamp's mating slot with clearance", "1/4\"-20 slot with counterbore from the underside",
                   "craft.emboss_cells grip on the top", "safety stop screw boss"],
    "lessons": [
        "Interfaces with a standard come from the standard: Arca-Swiss plates are 38 mm wide with 45 deg dovetail flanks; "
        "say where the number comes from and mark it 'specified'.",
        "The camera screw needs a slot, not a hole (cameras put the tripod socket in different places) and a counterbore "
        "so the screw head sits below the clamp's jaws.",
        "A raised grip pattern (B-rep, it does work: friction against the camera base) on the top; the dovetail faces "
        "stay smooth and exact.",
        "The tongue is narrow at its root and wide at the bottom, so it slides into the jaw's undercut slot from the "
        "end and cannot lift out; the slot is craft.dovetail's cutter, the same profile grown by a named clearance.",
    ],
}


class Design(Recipe):
    title, summary = "Arca-type camera plate", "38 mm dovetail plate with a 1/4\"-20 slot, grip top and a matching jaw."
    solids = 2
    params = [
        Param("length", "Plate length", 70, 40, 160, 1, "mm", "form", "plate"),
        Param("width", "Dovetail width", 38, 38, 38, 0.1, "mm", "brief", "plate", "Arca-Swiss standard.", "specified"),
        Param("height", "Plate height", 10, 8, 14, 0.5, "mm", "form", "plate"),
        Param("slot_len", "Screw slot length", 36, 10, 120, 1, "mm", "form", "slot"),
        Param("fit", "Jaw clearance / side", 0.15, 0.05, 0.4, 0.01, "mm", "interface", "jaw"),
    ]
    features = [Feature("plate", "Dovetail plate", "interface"), Feature("slot", "1/4-20 slot", "interface"),
                Feature("grip", "Grip top", "finish"), Feature("stop", "Safety stop", "interface"),
                Feature("jaw", "Clamp jaw", "interface")]

    def constraints(self, v):
        if v["slot_len"] > v["length"] - 16:
            return [RecipeError("The slot runs into the plate's ends", "slot", "Shorten the slot.", ["slot_len"])]
        return []

    def _profile(self, W, H, dt):
        """Cross-section (y, z): the dovetail tongue at the bottom, W wide at z = 0 and narrowing at 45 deg to its root
        at z = dt; above it a ledge and the plate body, W wide with softened top corners."""
        return [(-W / 2, 0), (W / 2, 0), (W / 2 - dt, dt), (W / 2, dt), (W / 2, H - 1.0), (W / 2 - 1.0, H),
                (-W / 2 + 1.0, H), (-W / 2, H - 1.0), (-W / 2, dt), (-W / 2 + dt, dt)]

    def build(self, v):
        L, W, H = v["length"], v["width"], v["height"]
        dt = 4.0
        f = make_face(Wire.make_polygon([Plane.YZ.from_local_coords((y, z, 0)) for y, z in self._profile(W, H, dt)],
                                        close=True)).faces()[0]
        plate = Pos(-L / 2, 0, 0) * extrude(f, L)
        plate = craft.safe_fillet(plate, plate.edges().filter_by(Axis.Z), 3.0)
        stages = [Stage("plate", plate)]
        sl = v["slot_len"]
        body = plate - Pos(0, 0, -1) * extrude(SlotOverall(sl + 6.6, 6.6), H + 2)
        body = body - Pos(0, 0, -0.01) * extrude(SlotOverall(sl + 13, 13), 4.0)        # counterbore for the screw head
        stages.append(Stage("slot", body))
        grip = Pos(0, 0, H - 0.01) * craft.emboss_cells(L - 10, W - 8, cell=4.0, height=0.6, kind="pyramids", gap=0.6)
        grip = grip - Pos(0, 0, H - 1) * extrude(SlotOverall(sl + 10, 10), 4)
        body = body + grip
        stages.append(Stage("grip", body))
        # safety stop: a boss at one end of the underside for an M4 screw that rides in the clamp's groove
        body = body - Pos(L / 2 - 6, 0, -0.01) * Cylinder(parts.clearance_d("M4")[0] / 2 - 0.4, 8, align=BOTTOM)
        stages.append(Stage("stop", body))
        # jaw: a clamp block with the dovetail slot (craft.dovetail cutter: 45 deg flanks, clearance per side)
        jaw_w, jaw_h, jaw_l = W + 20, 14.0, 50.0
        dv = craft.dovetail(length=jaw_l, width=W, height=dt, angle=45, clearance=v["fit"])
        jaw = Box(jaw_l, jaw_w, jaw_h, align=BOTTOM)
        jaw = craft.safe_fillet(jaw, jaw.edges().filter_by(Axis.Z), 3.0)
        cutter = Pos(0, 0, jaw_h) * Rot(0, 0, 90) * dv.shapes["slot_cutter"]
        jaw = jaw - cutter
        jaw = jaw - Pos(0, 0, -1) * Cylinder(parts.clearance_d("M6")[0] / 2, jaw_h, align=BOTTOM)
        body = body + Pos(0, W + 30, 0) * jaw
        stages.append(Stage("jaw", body))
        self._dv = dv
        return parts.checked(stages)

    def derived(self, v):
        return [{"key": "dovetail_w", "label": "Dovetail width", "value": v["width"], "unit": "mm", "feature": "plate",
                 "formula": "Arca-Swiss standard (specified)", "interface": True},
                {"key": "jaw_fit", "label": "Jaw clearance per side", "value": v["fit"], "unit": "mm", "feature": "jaw",
                 "formula": "assumed; calibrate with a coupon", "interface": True}]
