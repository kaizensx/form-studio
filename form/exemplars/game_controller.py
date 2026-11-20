"""Ergonomic two-handed game controller shell: one smooth body lofted left to right through side-view sections, so
the two grips swell out of the body and droop toward the palms without a seam, split into a top and a bottom shell
with a locating lip, thumbstick wells, a D-pad, four face buttons, centre buttons and trigger openings. A shell and form
study; electronics not included. Form Studio exemplar design.
"""

from build123d import Align, Box, Cylinder, Plane, Pos, Rot, SlotOverall, Vertex, extrude

from form import craft
from form.craft import MeshTexture
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
ZP = 15.0          # the parting plane; also the centre height of the grip-end sections, so it cuts their dome at its
                   # equator (a plane near the top of a shrinking section is tangent to it there: the split fails)

META = {
    "title": "Ergonomic game controller",
    "category": "consumer",
    "tags": ["game controller", "gamepad", "controller", "joypad", "console", "ergonomic", "grips", "thumbstick",
             "d-pad", "buttons", "shell", "split", "loft", "consumer electronics", "handheld", "two-part"],
    "techniques": ["one loft along Y through tilted side-view (XZ) superellipse sections: grips blend into the body",
                   "the plan outline (the notch between the grips) comes from each section's back edge",
                   "hollow by lofting the same sections shrunk by the wall (exact, never an offset of a loft)",
                   "top / bottom split with a 0.4 mm gap and a locating lip 0.3 mm off the top's wall",
                   "collars that follow the top: (grown loft & ring) - loft",
                   "craft.cut for the stick, D-pad, face-button and trigger openings; MeshTexture grain on the grips",
                   "assembly() with the two shells; appearance() zones"],
    "lessons": [
        "Choose the loft direction from the plan: a controller is a U in plan (two grips toward the user), which no "
        "stack of horizontal sections can describe. Loft left to right through side-view sections instead: each "
        "section's back edge traces the notch between the grips, its tilt makes the grips droop 15-20 deg toward the "
        "palms, and the grips grow out of the body in one skin with no fillet to fail.",
        "Size it from the hand: grips about 30-35 mm across where the palm wraps them (power-grip studies), the body "
        "150-160 mm wide and the sticks about 75-85 mm apart, under the thumbs' resting arc. Real pads: 153-160 x "
        "100-108 x 55-65 mm.",
        "Thumbstick wells sit on the thumbs' arc: left stick high and outboard, D-pad low and inboard (and the face "
        "buttons and right stick mirrored), so each thumb reaches both by pivoting, not sliding.",
        "Hollow a loft by lofting the same sections shrunk by the wall, not by offsetting the skin: exact, fast and "
        "it cannot fail at the grip ends where the curvature is tight.",
        "A two-part shell needs a gap at the split (0.3-0.5 mm) and a locating lip on one half that clears the other "
        "half's wall by 0.3 mm. Two halves that touch are one solid to the kernel, and a slicer, and a mould. Put "
        "the parting plane where the walls cross it steeply: through the equator of the end domes, never just under "
        "the top of a section, where the plane grazes the skin and the split and lip booleans fail.",
        "Details that sit on a curved top (stick collars, button rings) are the skin grown a millimetre or two, "
        "intersected with the ring: they follow the surface exactly, wherever the sections move.",
    ],
}


class Design(Recipe):
    title, summary = "Game controller", ("Two-handed controller shell lofted in one skin, split top and bottom, with "
                                         "stick wells, D-pad, face buttons, centre buttons and trigger openings.")
    solids = 2
    photo_color = "#e6e6e2"
    params = [
        Param("width", "Overall width", 156, 145, 170, 1, "mm", "brief", "body", "Real pads 153-160 mm."),
        Param("grip_d", "Grip thickness", 34, 28, 38, 1, "mm", "brief", "body",
              "Where the palm wraps the grip; power-grip optimum 31-38 mm."),
        Param("droop", "Grip droop", 16, 6, 24, 1, "deg", "form", "body", "How far the grips tilt down to the palms."),
        Param("wall", "Wall", 2.0, 1.6, 3.0, 0.1, "mm", "form", "shell", "Injection-moulded ABS shells 1.8-2.2 mm."),
        Param("gap", "Split gap", 0.4, 0.3, 0.8, 0.05, "mm", "interface", "split"),
        Param("stick_d", "Stick well diameter", 24, 20, 28, 0.5, "mm", "interface", "sticks",
              "Opening for a standard 3D analogue stick cap (about 20 mm) with its throw."),
    ]
    features = [Feature("body", "Lofted body", "structure"), Feature("shell", "Hollow", "structure"),
                Feature("split", "Top / bottom split", "interface"), Feature("lip", "Locating lip", "interface"),
                Feature("sticks", "Thumbstick wells", "access"), Feature("dpad", "D-pad opening", "access"),
                Feature("face_buttons", "Face buttons", "access"), Feature("centre", "Centre buttons", "access"),
                Feature("triggers", "Trigger openings", "access")]

    def constraints(self, v):
        if v["grip_d"] > v["width"] * 0.25:
            return [RecipeError("Grips that thick crowd the centre", "body", "Thin the grips or widen the body.",
                                ["grip_d"])]
        return []

    def sections(self, v, d=0.0):
        """Side-view sections (x along the depth, z up) from the right grip's flank to the left's; d grows (+) or
        shrinks (-) every one. Rows: y fraction of the half width, front x, back x, centre z, half thickness, tilt
        fraction. Past y = 0.86 the flank closes as a dome (each section scaled by k = sqrt(1 - u^2)), so the loft
        ends round instead of in a flat cap."""
        s, g = v["width"] / 156.0, v["grip_d"] / 34.0
        rows = [(0.00, 46, -18, 18.0, 14.0, 0.0), (0.28, 47, -24, 18.0, 14.5, 0.10), (0.48, 48, -42, 16.0, 16.0, 0.35),
                (0.64, 47, -68, 15.0, 17.5 * g, 0.75), (0.76, 44, -86, 15.0, 17.5 * g, 0.95),
                (0.86, 37, -92, ZP, 16.0 * g, 1.0)]
        half = v["width"] / 2
        sec = [(fy * half, (xf - xb) / 2 * s + d, (xf + xb) / 2 * s, cz, b + d, tf) for fy, xf, xb, cz, b, tf in rows]
        y0, a, cx, cz, b, tf = sec[-1]
        for u in (0.45, 0.7, 0.86, 0.95, 0.99):                  # the dome over the flank, out to half + d
            k = (1 - u * u) ** 0.5
            sec.append((y0 + (half + d - y0) * u, a * k, cx, cz, b * k, tf))
        out = []
        for sy in (-1, 1):
            for y, a, cx, cz, b, tf in sec:
                if sy < 0 and y == 0:
                    continue
                out.append({"y": sy * y, "a": a, "b": b, "cx": cx, "cz": cz, "rot": v["droop"] * tf,
                            "n": 2.7 - 0.4 * tf})
        out.sort(key=lambda q: q["y"])
        return out

    def loft(self, v, d=0.0):
        """The body grown by d (> 0) or shrunk (< 0), closed at both flanks by a tip point after the dome rows."""
        half = v["width"] / 2
        secs = self.sections(v, d)
        faces = [craft.superellipse_face(q["a"], q["b"], q["n"], z=-q["y"], plane=Plane.XZ, center=(q["cx"], q["cz"]),
                                         rotate=q["rot"], seam=270.0, count=64) for q in secs]
        ty = half + d
        ends = [Vertex(secs[0]["cx"], -ty, secs[0]["cz"]), Vertex(secs[-1]["cx"], ty, secs[-1]["cz"])]
        return craft.loft_sections([ends[0]] + faces + [ends[1]])

    def build(self, v):
        t, gap = v["wall"], v["gap"]
        # --- snippet: a U-shaped product as one loft through side-view sections, hollowed by shrunk sections
        outer = self.loft(v)
        stages = [Stage("body", outer)]
        inner = self.loft(v, -t)
        body = craft.cut(outer, inner)
        # --- end snippet
        stages.append(Stage("shell", body))

        zp = ZP                                                # parting plane: the flank domes' equator
        big = 400
        top = craft.cut(body, Pos(0, 0, zp + gap / 2 - big) * Box(big, big, big, align=BOTTOM))
        bot = craft.cut(body, Pos(0, 0, zp - gap / 2) * Box(big, big, big, align=BOTTOM))
        stages.append(Stage("split", top + bot))

        # locating lip on the bottom shell: a 1.2 mm ring standing 2.5 mm above the split, 0.3 mm clear of the top's
        # wall; below the split it widens 0.3 mm into the bottom's own wall, so it is fused to it, not floating
        # (one ring, then the clearance cut from it by a tool that reaches past its outside: no two pieces sharing a
        # face, which is what made a fuse of two rings fail)
        # It runs along the front and back of the body only (|y| < 0.65 of the half width), where the walls are
        # steep: out at the grip ends the split plane passes the dome's pole and the ring degenerates.
        ring = craft.cut(self.loft(v, -t + 0.3), self.loft(v, -t - 1.5))
        lip = ring & Pos(0, 0, zp - 3.0) * Box(big, v["width"] * 0.65, 5.5, align=BOTTOM)
        clear = craft.cut(self.loft(v, -t + 1.0), self.loft(v, -t - 0.3))
        lip = craft.cut(lip, clear & Pos(0, 0, zp - gap / 2) * Box(big, big, 10, align=BOTTOM))
        bot = craft.fuse(bot, lip)
        stages.append(Stage("lip", top + bot))

        # thumbstick wells: a collar 1.5 mm proud round each opening (the grown skin & a ring), then the opening
        half = v["width"] / 2
        grown = self.loft(v, 1.5)
        rs = v["stick_d"] / 2
        left_stick, right_stick = (20.0, 0.27 * half * 2), (-6.0, -0.19 * half * 2)
        collars, holes = None, None
        for x, y in (left_stick, right_stick):
            c = Pos(x, y, 0) * (Cylinder(rs + 5, 120) - Cylinder(rs, 120))
            collars = c if collars is None else collars + c
            h = Pos(x, y, 0) * Cylinder(rs, 120)
            holes = h if holes is None else holes + h
        # its root is the skin shrunk by half the wall, inside the wall: a collar whose root were the skin itself would
        # only touch the shell, and that fuse is a coin toss
        col = craft.cut(grown & collars & Pos(0, 0, zp + 2) * Box(big, big, big, align=BOTTOM), self.loft(v, -t / 2))
        col = craft.safe_fillet(col, [e for e in col.edges() if e.center().Z > zp + 6], 0.6)
        top = craft.cut(craft.fuse(top, col), holes)
        stages.append(Stage("sticks", top + bot))

        # D-pad: a cross opening low and inboard on the left
        dx, dy = -6.0, 0.19 * half * 2
        cross = Pos(dx, dy, 30) * (extrude(SlotOverall(27, 9.5), 60, both=True)
                                   + Rot(0, 0, 90) * extrude(SlotOverall(27, 9.5), 60, both=True))
        top = craft.cut(top, cross)
        stages.append(Stage("dpad", top + bot))

        # face buttons: four 10.5 mm holes in a diamond at 13 mm pitch, high and outboard on the right
        fx, fy = 20.0, -0.27 * half * 2
        btn = None
        for ox, oy in ((9, 0), (-9, 0), (0, 9), (0, -9)):
            c = Pos(fx + ox, fy + oy, 0) * Cylinder(5.25, 120)
            btn = c if btn is None else btn + c
        top = craft.cut(top, btn)
        stages.append(Stage("face_buttons", top + bot))

        # centre: a home button and two small menu buttons
        cen = Pos(30, 0, 0) * Cylinder(6.5, 120) + Pos(10, 15, 0) * Cylinder(3.2, 120) + Pos(10, -15, 0) * Cylinder(
            3.2, 120)
        top = craft.cut(top, cen)
        stages.append(Stage("centre", top + bot))

        # trigger openings: a 26 x 8 mm slot through the front wall of each shoulder, just above the split, cut
        # along +X only (from inside the wall outward) so it never reaches the top surface
        trig = None
        for sy in (1, -1):
            sl = Pos(34, sy * 0.33 * half * 2, zp + 5.5) * extrude(Plane.YZ * SlotOverall(26, 8), 40)
            trig = sl if trig is None else trig + sl
        top = craft.cut(top, trig)
        stages.append(Stage("triggers", craft.fuse(top, bot, max_solids=2, min_solids=2)))
        return stages

    def mesh_texture(self, v):
        return [MeshTexture("grain", amplitude=0.12, scale=1.0, features=["split", "lip"], facing="out",
                            edge_falloff=1.0, region=((-200, -200, -60), (-30, 200, 60)))]

    def appearance(self, v):
        return [{"features": ["split", "lip"], "finish": "matte", "color": "#2b2d31"},
                {"features": ["body", "shell", "sticks", "dpad", "face_buttons", "centre", "triggers"],
                 "finish": "gloss", "color": "#e6e6e2"}]

    def assembly(self, v):
        return Assembly(parts=[Part("bottom", "Bottom shell", (14.0 * v["width"] / 156, 0.0, 5.0),
                                    note="Bottom shell, lip up; boards and sticks go in."),
                               Part("top", "Top shell", (14.0 * v["width"] / 156, 0.0, 31.0), explode=(0, 0, 30),
                                    note="Press the top shell over the lip.")])

    def derived(self, v):
        return [{"key": "stick_spacing", "label": "Stick spacing (centres)", "value": round(
            ((20 + 6) ** 2 + (0.46 * v["width"]) ** 2) ** 0.5, 1), "unit": "mm", "feature": "sticks",
                 "formula": "diagonal between the left and right stick", "interface": False},
                {"key": "split_gap", "label": "Split gap", "value": v["gap"], "unit": "mm", "feature": "split",
                 "formula": "parting gap (assumed)", "interface": True}]
