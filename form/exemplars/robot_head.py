"""Friendly robot head prop in five parts: a soft-cube head shell lofted from guide curves, a recessed face screen
behind a raised bezel with two big round eyes and a smile, two dial ears that turn on pegs, and an antenna with a
ball tip plugged into a collar on the crown. Modelled in place with an assembly and material zones. A prop or display
piece. Form Studio exemplar design.
"""

from build123d import Align, Axis, Box, Cylinder, Pos, Rot, Sphere

from form import craft
from form.recipes.base import Assembly, Feature, Mate, Param, Part, Recipe, RecipeError, Stage, hinge

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Friendly robot head",
    "category": "assembly",
    "tags": ["robot", "robot head", "prop", "toy", "mascot", "friendly", "cute", "helmet", "antenna", "ears", "face",
             "screen", "eyes", "assembly", "multi-part", "soft cube", "cosplay"],
    "techniques": ["craft.profile_sections + craft.checked_body: a soft cube (n = 3.4) with a superellipse crown",
                   "craft.inset_body hollowing, open at the neck",
                   "face opening cut with craft.two_view_cutter; a bezel as a craft.surface_band ring",
                   "an antenna boss that swallows the loft's crown pole (no surface_band across a pole)",
                   "a recessed screen as its own part: the layer between two inward offsets, behind the wall",
                   "parts placed by ray intersection with the head (ears, antenna), pegs in holes 0.3 mm clear",
                   "assembly(): parts picked by a point inside each, hinge joints for the dial ears, Mates for pegs",
                   "appearance() zones: gloss shell, smoke screen, glowing eyes, metal ears, red antenna ball"],
    "lessons": [
        "Friendly is proportion: a big head with a big face (the screen about 60 % of the front's width), eyes "
        "large, round, set wide and a little below the middle, a small smile, and no sharp edges anywhere. Narrow "
        "slit eyes high on the face read as menacing on the same head.",
        "A soft cube is a superellipse section (n 3-4) with a superellipse crown: square enough to read as a "
        "machine, round enough to read as friendly. profile_sections gives it from three guide curves, so the chin "
        "can tuck in and the back can be fuller than the front. Check the hollow at every size: with a flat crown "
        "(power 3) and few dome sections the loft overshoots its tip and the inset pokes through the top; power "
        "2.5 with 12 dome sections keeps the crown wall at the wall thickness from 150 to 260 mm.",
        "Separate parts need real gaps: the screen sits 1 mm behind the wall it hides behind; ear discs stand 0.4 mm "
        "off the side; pegs run in holes 0.3 mm larger. Declare those as Mates so they are measured, not booleaned.",
        "Place parts from the surface, not by guessing: a ray from the centre finds where each side and the crown "
        "are for this size, so ears and antenna sit right at every parameter value.",
        "Model it in place and say how it goes together: assembly() picks each part by a point inside it (no "
        "counting solids), gives the ears hinge joints (they turn like dials) and exploded offsets for the steps.",
        "Five parts, five materials: gloss shell, smoked screen, glowing eyes, brushed ears, a red antenna ball. One "
        "colour would render as a single blob.",
    ],
}


def _inner(secs, tip, d):
    """The head shrunk by d along the surface normal (the same law craft.inset_body hollows with)."""
    s2, t2 = craft.inflate(secs, -d, tip, normal=True)
    return craft.section_body(s2, tip=(tip[0], tip[1], tip[2] - d))


class Design(Recipe):
    title, summary = "Robot head", ("Friendly robot head in five parts: soft-cube shell, recessed face screen with "
                                    "big eyes, dial ears on pegs and a ball-tipped antenna.")
    solids = 5
    photo_color = "#eef0f2"
    params = [
        Param("width", "Head width", 220, 160, 280, 5, "mm", "brief", "head",
              "Wearable heads need about 200 mm inside (head breadth 155 mm + padding)."),
        Param("height", "Head height", 200, 150, 260, 5, "mm", "brief", "head"),
        Param("square", "Squareness", 3.4, 2.4, 4.4, 0.1, "", "form", "head", "Superellipse n: 2 round, 4.4 boxy."),
        Param("wall", "Wall", 3.0, 2.0, 4.0, 0.1, "mm", "form", "head"),
        Param("eye_d", "Eye diameter", 40, 28, 48, 1, "mm", "form", "screen"),
        Param("antenna", "Antenna height", 60, 30, 100, 5, "mm", "form", "antenna"),
    ]
    features = [Feature("head", "Head shell", "structure"), Feature("face", "Face opening and bezel", "access"),
                Feature("grille", "Chin grille", "access"), Feature("sockets", "Ear and antenna sockets", "interface"),
                Feature("screen", "Face screen", "structure"), Feature("eyes", "Eyes and smile", "finish"),
                Feature("ears", "Dial ears", "structure"), Feature("antenna", "Antenna", "structure")]

    def constraints(self, v):
        if v["height"] > v["width"] * 1.25:
            return [RecipeError("Taller than 1.25 x its width reads as a tin can, not a head", "head",
                                "Widen it or lower it.", ["height", "width"])]
        return []

    def form(self, v):
        W, H = v["width"], v["height"]
        D = W * 0.9
        ze = H * 0.52
        front = [(0, D / 2 * 0.86), (H * 0.25, D / 2 * 0.97), (ze, D / 2)]
        back = [(0, -D / 2 * 0.84), (H * 0.25, -D / 2 * 0.97), (ze, -D / 2)]
        half = [(0, W / 2 * 0.86), (H * 0.25, W / 2 * 0.97), (ze, W / 2)]
        secs, tip = craft.profile_sections(front, back, half, z_eq=ze, crown=(0.0, H), levels=6, dome_levels=12,
                                           n=v["square"], power=2.5, seam=180.0)
        return secs, tip, D

    def layout(self, v, outer):
        """Where the parts sit on this head: the side surface at ear height, the crown, the face's front."""
        W, H = v["width"], v["height"]
        z_ear = H * 0.50
        side = max((h[0].Y for h in outer.find_intersection_points(Axis((0, 0, z_ear), (0, 1, 0)))), default=W / 2)
        crown = H                                                 # the loft's crown point (a ray there hits a pole)
        zf = H * 0.37                                             # under the eyes and the smile
        front = max((h[0].X for h in outer.find_intersection_points(Axis((0, 0, zf), (1, 0, 0)))), default=W * 0.45)
        return {"z_ear": z_ear, "side": side, "crown": crown, "zf": zf, "front": front}

    def build(self, v):
        W, H, t = v["width"], v["height"], v["wall"]
        secs, tip, D = self.form(v)
        outer = craft.checked_body(secs, tip, label="head")
        body = craft.cut(outer, craft.inset_body(secs, t, tip=tip))
        stages = [Stage("head", body)]
        P = self.layout(v, outer)

        # face opening: a soft rectangle (n = 4) 62 % of the width, cut through the front; a 6 mm bezel 2.5 mm proud
        fw, fh, fz = W * 0.31, H * 0.24, H * 0.55
        face = [(fw * x, fz + fh * y) for x, y in craft.superellipse(1, 1, 4.0, count=48)]
        side = [(0, -10), (W, -10), (W, H + 10), (0, H + 10)]
        opening = craft.two_view_cutter(side, face, x_range=(D * 0.2, W), smooth=(False, True))
        ring = craft.two_view_cutter(side, craft.grow_outline(face, 7.0), x_range=(D * 0.2, W),
                                     smooth=(False, True)) - opening
        body = craft.fuse(body, craft.surface_band(secs, tip, 2.5, ring, depth=t / 2))
        body = craft.cut(body, opening)
        body = craft.safe_fillet(body, [e for e in body.edges() if e.center().X > D * 0.3 and
                                        abs(e.center().Z - fz) < fh + 12], 1.2)
        stages.append(Stage("face", body))

        # chin grille: five short slots under the face, a speaker
        body = craft.cut(body, craft.slot_grille((D / 2, 0, H * 0.22), (1, 0, 0), count=5, length=16, width=4,
                                                 pitch=9, depth=40, angle=90, taper=0.3))
        stages.append(Stage("grille", body))

        # sockets: a hole each side for the ear pegs, a collar and hole on the crown for the antenna
        zE = P["z_ear"]
        body = craft.cut(body, Pos(0, 0, zE) * Rot(90, 0, 0) * Cylinder(6.3, W + 40))
        # (a plain boss, not a surface_band: the band would be clipped round the loft's crown pole, where booleans
        # fail; a cylinder that swallows the pole whole fuses cleanly, and its foot is a boss under the crown)
        collar = Pos(0, 0, P["crown"] - 12) * Cylinder(15, 15, align=BOTTOM)
        collar = craft.safe_fillet(collar, [e for e in collar.edges() if e.center().Z > P["crown"]], 2.0)
        body = craft.fuse(body, collar)
        body = craft.cut(body, Pos(0, 0, P["crown"] - 20) * Cylinder(4.3, 40, align=BOTTOM))
        stages.append(Stage("sockets", body))

        # --- snippet: a screen behind the wall, as its own part
        # the layer 4-6.5 mm inside the skin, clipped to the opening grown by 6 mm: it sits 1 mm behind the 3 mm wall
        # and overlaps it all round, like a real display behind a bezel. Offsets along the normal, like the hollow:
        # a plan offset is thinner on the sloping crown, and there the screen would run into the wall
        scr_reg = craft.two_view_cutter(side, craft.grow_outline(face, 6.0), x_range=(D * 0.2, W), smooth=(False, True))
        screen = craft.cut(_inner(secs, tip, t + 1.0) & scr_reg, _inner(secs, tip, t + 3.5))
        body = craft.fuse(body, screen, max_solids=2, min_solids=2)
        # --- end snippet
        stages.append(Stage("screen", body))

        # eyes and smile: raised 2.5 mm on the screen, still behind the shell's outer surface
        ez, ey, er = fz + fh * 0.18, fw * 0.45, v["eye_d"] / 2
        eyes = (Pos(0, ey, ez) * Rot(0, 90, 0) * Cylinder(er, W) + Pos(0, -ey, ez) * Rot(0, 90, 0) * Cylinder(er, W))
        sc, sr = fz - fh * 0.05, fh * 0.55                       # the smile: the lower part of a 4 mm ring
        ring4 = Pos(0, 0, sc) * Rot(0, 90, 0) * (Cylinder(sr, W) - Cylinder(sr - 4, W))
        smile = ring4 & Pos(0, 0, sc - sr * 0.55) * Box(2 * W, 2 * W, H, align=(Align.CENTER, Align.CENTER, Align.MAX))
        lights = craft.cut(_inner(secs, tip, t + 0.6) & ((eyes + smile) & scr_reg),
                           _inner(secs, tip, t + 2.0))
        body = craft.fuse(body, lights, max_solids=2, min_solids=2)
        stages.append(Stage("eyes", body))

        # dial ears: a stepped disc 0.4 mm off each side, a ring groove, and a peg into the head's hole (0.3 mm clear)
        for sy in (1, -1):
            y0 = sy * (P["side"] + 0.4)
            ear = (Cylinder(30, 10, align=BOTTOM) + Pos(0, 0, 10) * Cylinder(22, 9, align=BOTTOM)
                   + Pos(0, 0, -16) * Cylinder(6.0, 16.2, align=BOTTOM))
            ear = ear - Pos(0, 0, 14) * (Cylinder(16, 6, align=BOTTOM) - Cylinder(14, 6, align=BOTTOM))
            rims = [e for e in ear.edges() if e.geom_type.name == "CIRCLE" and e.radius > 19]
            ear = craft.safe_fillet(ear, rims, 2.0)
            ear = Pos(0, y0, zE) * Rot(-sy * 90, 0, 0) * ear
            body = craft.fuse(body, ear, max_solids=3 if sy > 0 else 4, min_solids=3 if sy > 0 else 4)
        stages.append(Stage("ears", body))

        # antenna: a flange 0.4 mm above the collar, a stalk down into its hole, a ball on top
        zc = P["crown"] + 3.0 + 0.4                               # collar top, then the gap
        stalk = Pos(0, 0, zc - 14) * Cylinder(4.0, 14 + v["antenna"], align=BOTTOM)
        flange = Pos(0, 0, zc) * Cylinder(12, 4, align=BOTTOM)
        flange = craft.safe_fillet(flange, flange.edges(), 1.5)
        ball = Pos(0, 0, zc + v["antenna"] + 6) * Sphere(10)
        ant = craft.fuse(craft.fuse(stalk, flange), ball)
        body = craft.fuse(body, ant, max_solids=5, min_solids=5)
        stages.append(Stage("antenna", body))
        return stages

    def appearance(self, v):
        return [{"features": ["screen"], "finish": "smoke", "color": "#1b2229"},
                {"features": ["eyes"], "finish": "gloss", "color": "#5fd3f0"},
                {"features": ["ears"], "finish": "metal", "color": "#9aa1aa"},
                {"features": ["antenna"], "finish": "gloss", "color": "#e0452f"},
                {"features": ["face"], "finish": "matte", "color": "#ff9f1c"},
                {"features": ["head", "grille", "sockets"], "finish": "gloss", "color": "#eef0f2"}]

    def assembly(self, v):
        W, H, t = v["width"], v["height"], v["wall"]
        secs, tip, D = self.form(v)
        P = self.layout(v, craft.section_body(secs, tip=tip))
        zE, zc = P["z_ear"], P["crown"] + 3.4
        fz = H * 0.55
        return Assembly(
            parts=[Part("head", "Head shell", (0.0, P["side"] - t / 2, zE + 25), note="Set the head on its neck ring."),
                   Part("screen", "Face screen", (P["front"] - t - 2.2, 0.0, H * 0.55 - H * 0.24 * 0.75),
                        explode=(60, 0, 0), note="Slide the screen in from below and glue its rim behind the bezel."),
                   Part("ear_l", "Left ear", (0.0, P["side"] + 5.0, zE), explode=(0, 40, 0),
                        note="Push the left ear's peg into its hole."),
                   Part("ear_r", "Right ear", (0.0, -P["side"] - 5.0, zE), explode=(0, -40, 0),
                        note="Push the right ear's peg into its hole."),
                   Part("antenna", "Antenna", (0.0, 0.0, zc + v["antenna"] + 6), explode=(0, 0, 50),
                        note="Plug the antenna into the crown collar.")],
            joints=[hinge("ear_l", (0, 1, 0), (0, 0, zE), (0, 180), 7, parent="head", id="ear_l_turn",
                          label="Left ear dial"),
                    hinge("ear_r", (0, -1, 0), (0, 0, zE), (0, 180), 7, parent="head", id="ear_r_turn",
                          label="Right ear dial")],
            mates=[Mate("ear_l", "head", "pin", 0.3, "Left ear peg"),
                   Mate("ear_r", "head", "pin", 0.3, "Right ear peg"),
                   Mate("antenna", "head", "pin", 0.3, "Antenna stalk in the collar"),
                   Mate("screen", "head", "contact", 1.0, "Screen behind the bezel")])

    def derived(self, v):
        return [{"key": "face_w", "label": "Face width", "value": round(v["width"] * 0.62, 1), "unit": "mm",
                 "feature": "face", "formula": "0.62 x head width (friendly proportion)", "interface": False},
                {"key": "peg_clear", "label": "Peg clearance per side", "value": 0.3, "unit": "mm",
                 "feature": "sockets", "formula": "6.3 mm hole on a 6.0 mm peg", "interface": True}]
