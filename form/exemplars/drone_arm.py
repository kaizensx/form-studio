"""Drone arm: a tapered, lofted arm whose section shrinks from the frame clamp to the motor, with a motor pad for a
16 x 19 mm M3 pattern, lightening windows, a stiffening keel and a wire channel. Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cylinder, Plane, Pos, Rot, SlotOverall, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Drone arm",
    "category": "mechanical",
    "tags": ["drone", "arm", "quadcopter", "motor mount", "loft", "taper", "lightweight", "lightening", "structure",
             "carbon", "rib", "fpv"],
    "techniques": ["craft.loft_sections along X of superellipse sections (tapered beam)", "bolt pattern from the motor "
                   "datasheet", "lightening windows sized to leave flanges", "keel rib (craft.rib) under the arm",
                   "wire channel", "MeshTexture weave on the arm for a carbon look"],
    "lessons": [
        "Shape the beam to the load: bending is largest at the frame, so the section is deepest there and tapers to "
        "the motor. A loft through 4-5 sections along the arm does this in one smooth surface.",
        "Motor patterns are interfaces: 16 x 19 mm M3 is the common 22xx/23xx pattern; take it from the motor's "
        "drawing and mark it specified.",
        "Lightening windows remove the web where the stress is low (the neutral axis) and keep flanges top and bottom.",
        "A keel under the arm adds depth cheaply; a channel inside it carries the motor wires.",
    ],
}


class Design(Recipe):
    title, summary = "Drone arm", "Tapered lofted arm with a 16x19 M3 motor pad, windows, keel and wire channel."
    solids = 1
    photo_color = "#30343a"
    params = [
        Param("length", "Arm length (centre to centre)", 110, 60, 220, 1, "mm", "brief", "arm"),
        Param("root_w", "Root width", 22, 14, 40, 0.5, "mm", "form", "arm"),
        Param("root_h", "Root depth", 11, 6, 20, 0.5, "mm", "form", "arm"),
        Param("tip_w", "Tip width", 14, 10, 30, 0.5, "mm", "form", "arm"),
        Param("tip_h", "Tip depth", 6, 4, 14, 0.5, "mm", "form", "arm"),
        Param("pad_d", "Motor pad diameter", 30, 22, 44, 0.5, "mm", "brief", "motor_pad"),
        Param("weave", "Weave depth", 0.2, 0, 0.5, 0.05, "mm", "form", "arm", "0 = smooth. Mesh texture."),
    ]
    features = [Feature("arm", "Tapered arm", "structure"), Feature("motor_pad", "Motor pad", "interface"),
                Feature("root", "Frame clamp", "interface"), Feature("windows", "Lightening windows", "structure"),
                Feature("keel", "Keel and wire channel", "structure")]

    def constraints(self, v):
        if v["tip_w"] > v["root_w"] or v["tip_h"] > v["root_h"]:
            return [RecipeError("The arm must taper toward the motor", "arm", "Make the tip smaller than the root.",
                                ["tip_w", "tip_h"])]
        return []

    def build(self, v):
        L, pad = v["length"], v["pad_d"]
        k = 3.0                                   # keel height: the keel stands on the bed, the arm rides on it
        # sections along X (plane YZ), their undersides at z = k
        secs = []
        for i, u in enumerate((0.0, 0.3, 0.6, 0.85, 1.0)):
            w = v["root_w"] + (v["tip_w"] - v["root_w"]) * u ** 0.8
            h = v["root_h"] + (v["tip_h"] - v["root_h"]) * u ** 0.9
            f = Plane.YZ.offset(L * u) * craft.superellipse_face(w / 2, h / 2, 3.2, center=(0, k + h / 2))
            secs.append(f)
        arm = craft.loft_sections(secs)
        stages = [Stage("arm", arm)]
        # motor pad: a disc at the tip, the M3 pattern 16 x 19 mm (diagonals) and a centre hole for the shaft clip
        pt = v["tip_h"] + 0.5
        disc = Pos(L, 0, k) * Cylinder(pad / 2, pt, align=BOTTOM)
        body = arm + disc
        body = craft.safe_fillet(body, [e for e in body.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - pad / 2) < 1e-3], 1.0)
        for (dx, dy) in ((8, 0), (-8, 0), (0, 9.5), (0, -9.5)):
            body = body - Pos(L + dx, dy, k - 1) * Cylinder(parts.clearance_d("M3")[0] / 2, pt + 2, align=BOTTOM)
        body = body - Pos(L, 0, k - 1) * Cylinder(4.0, pt + 2, align=BOTTOM)
        stages.append(Stage("motor_pad", body))
        # frame clamp at the root: a block with two M3 holes, 20 mm apart
        root = Pos(-8, 0, 0) * Box(20, v["root_w"] + 6, v["root_h"] + k, align=BOTTOM)
        root = craft.safe_fillet(root, root.edges().filter_by(Axis.Z), 3.0)
        body = body + root
        for dy in (-10, 10):
            body = body - Pos(-8, dy, -1) * Cylinder(parts.clearance_d("M3")[0] / 2, v["root_h"] + k + 2, align=BOTTOM)
        stages.append(Stage("root", body))
        # lightening windows through the web (along Y), between the root and the pad
        x0, x1 = 16, L - pad / 2 - 8
        n = max(1, int((x1 - x0) / 18))
        step = (x1 - x0) / n
        for i in range(n):
            xc = x0 + step * (i + 0.5)
            u = xc / L
            h = v["root_h"] + (v["tip_h"] - v["root_h"]) * u ** 0.9
            wl, wh = step - 5, max(2.0, h * 0.45)
            win = Pos(xc, 0, k + h / 2) * Rot(90, 0, 0) * extrude(SlotOverall(wl, wh), 60, both=True)
            body = body - win
        stages.append(Stage("windows", body))
        # keel under the arm, standing on the bed, with a wire channel along its foot
        keel = Pos(L * 0.45, 0, 0) * craft.rib(L * 0.72, k + 1.5, 4.0)
        body = body + keel
        body = body - Pos(L * 0.45, 0, 0) * Box(L * 0.74, 2.0, 2.4)
        stages.append(Stage("keel", body))
        return parts.checked(stages)

    def mesh_texture(self, v):
        if v["weave"] <= 0:
            return []
        from form.craft import MeshTexture
        return [MeshTexture("weave", amplitude=v["weave"], scale=2.5, features=["arm"], edge_falloff=1.5)]

    def derived(self, v):
        return [{"key": "motor_pattern", "label": "Motor bolt pattern", "value": 19.0, "unit": "mm", "feature": "motor_pad",
                 "formula": "16 x 19 mm M3 (22xx/23xx motors; check the motor drawing)", "interface": True}]
