"""Right-hand ergonomic mouse, top shell and scroll wheel: a palm-grip form sized from the hand (ANSUR II), with a
thumb groove, two primary buttons split from the body, a rubber-tyred wheel, two side buttons, a DPI button, rubber
grip panels on both flanks and a parting line round the skirt. A form study and visual model.
"""
from build123d import Align, Box, Cylinder, Plane, Pos, Rot, Sphere, extrude, scale

from form import craft
from form.craft import MeshTexture
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


META = {
    "title": "Ergonomic mouse",
    "tags": ["mouse", "computer mouse", "ergonomic", "palm grip", "shell", "organic", "wheel", "buttons", "grip",
             "texture", "rubber", "styled", "hand", "loft", "consumer electronics"],
    "techniques": ["craft.mouse_form (hand -> guide curves -> sections)", "craft.checked_body", "craft.inset_body",
                   "thumb scoop shaped outside then hollowed", "plan-curve split lines", "craft.surface_band for side "
                   "buttons, DPI button and grips", "a separate rubber-tyred wheel (fuse min_solids=2)",
                   "MeshTexture grain on the grips", "appearance() zones: matte body, rubber grips and wheel"],
    "lessons": [
        "Size it from the hand: ANSUR II's mean male hand is 194 x 90 mm; a palm-grip mouse is about 0.65 x the hand "
        "long and 0.7 x its breadth wide (craft.mouse_form does this). Real ones: 125 x 62-84 x 40-51 mm.",
        "The side view decides it: an almost upright skirt (no undercut, or it reads as a pebble), the hump about 40 % "
        "from the back, a long gentle slope down the buttons to the nose and a steeper fall to the tail.",
        "What makes a smooth dome read as a mouse is break-up: two buttons split from the body, a wheel standing proud "
        "in its opening, side buttons, a parting line round the skirt, rubber grips in another material. Without "
        "the wheel the opening reads as a hole.",
        "Shape the outside first (the thumb groove), then hollow with the same scoop grown by the wall, so the wall "
        "stays even.",
        "Keep screw bosses clear of split lines and grooves: a post that meets a 0.9 mm split leaves a boolean OCCT "
        "cannot close.",
        "Declare appearance() zones: matte body, rubber grips and wheel, gloss side buttons. Render from three angles.",
    ],
}


class Design(Recipe):
    title, summary = "Ergonomic mouse", ("Right-hand palm-grip mouse shell with thumb groove, split buttons, rubber "
                                         "wheel, side buttons and rubber grips.")
    solids = 2
    params = [
        Param("length", "Length", 126, 110, 135, 0.5, "mm", "brief", "shell", "0.65 x hand length (ANSUR II 194 mm)."),
        Param("width", "Width", 66, 58, 76, 0.5, "mm", "brief", "shell"),
        Param("height", "Height", 42, 36, 48, 0.5, "mm", "brief", "shell"),
        Param("hump", "Hump from the back", 0.40, 0.3, 0.5, 0.01, "", "form", "shell", "Fraction of the length."),
        Param("tilt", "Lean toward the thumb", 0.12, 0, 0.25, 0.01, "", "form", "shell"),
        Param("wall", "Wall", 1.8, 1.2, 3, 0.1, "mm", "form", "shell"),
        Param("thumb_depth", "Thumb groove depth", 6.0, 0, 8, 0.25, "mm", "form", "thumb"),
        Param("grain", "Grip grain depth", 0.18, 0, 0.4, 0.02, "mm", "form", "grips", "Mesh texture on the grips."),
    ]
    features = [Feature("shell", "Palm shell", "structure"), Feature("thumb", "Thumb groove", "finish"),
                Feature("skirt", "Parting line", "finish"), Feature("buttons", "Button splits", "access"),
                Feature("wheel_slot", "Wheel opening", "access"), Feature("side_buttons", "Side buttons", "access"),
                Feature("dpi", "DPI button", "access"), Feature("grips", "Rubber grips", "finish"),
                Feature("bosses", "Screw bosses", "interface"), Feature("wheel", "Scroll wheel", "structure")]

    def constraints(self, v):
        if v["height"] > v["width"] * 0.75:
            return [RecipeError("Taller than three quarters of its width reads as a dome, not a mouse", "shell",
                                "Lower the height or widen it.", ["height", "width"])]
        return []

    def form(self, v):
        return craft.mouse_form(v["length"], v["width"], v["height"], hand="right", hump=v["hump"], tilt=v["tilt"],
                                flare=3.0, nose=0.34)

    def build(self, v):
        F = self.form(v)
        L, W, H, t = F["L"], F["W"], F["H"], v["wall"]
        hl = L / 2
        secs, tip = F["sections"], F["tip"]
        outer = craft.checked_body(secs, tip, label="shell")
        inner = craft.inset_body(secs, t, tip=tip)
        body = craft.cut(outer, inner)
        stages = [Stage("shell", body)]

        # thumb groove: a flattened ellipsoid pressed into the thumb flank, the outside rounded, the inside following
        scoop = None
        if v["thumb_depth"] > 0:
            r = 30.0
            at = Pos(-L * 0.04, W / 2 + r - v["thumb_depth"], H * 0.40)
            scoop = at * scale(Sphere(r), (1.25, 1.0, 0.45))
            o2 = craft.cut(outer, scoop)
            edge = [e for e in o2.edges() if e.center().Y > W * 0.2 and 2 < e.center().Z < H * 0.85]
            o2 = craft.safe_fillet(o2, edge, 5.0)
            grown = at * scale(Sphere(r + t), ((1.25 * r + t) / (r + t), 1.0, (0.45 * r + t) / (r + t)))
            body = craft.cut(o2, craft.cut(inner, grown))
            outer = o2
        stages.append(Stage("thumb", body))

        # parting line: a 0.8 mm groove round the skirt, 4 mm up, where a base plate would meet the shell
        s_out, t_out = craft.inflate(secs, 1.0, tip)
        s_in, t_in = craft.inflate(secs, -0.6, tip)
        ring = (craft.section_body(s_out, tip=t_out) - craft.section_body(s_in, tip=t_in)) & Pos(0, 0, 3.6) * Box(
            2 * L, 2 * W, 0.8, align=BOTTOM)
        body = craft.cut(body, ring)
        stages.append(Stage("skirt", body))

        # button splits: a centre split from the nose back to the palm, and a seam down each side of the button panel
        x0 = hl - L * 0.46
        zc = H * 0.45
        body = craft.cut(body, Pos((x0 + hl) / 2 + 8, 0, zc) * Box(hl - x0 + 16, 0.9, H, align=BOTTOM))
        for sy, yy in ((1, W * 0.27), (-1, -W * 0.31)):
            plan = [(x0, yy), (hl * 0.3, yy * 1.04), (hl * 0.8, yy * 0.98), (hl + 8, yy * 0.88)]
            strip = craft.spline_profile([(x, y + 0.45) for x, y in plan] + [(x, y - 0.45) for x, y in reversed(plan)],
                                         closed=True)
            body = craft.cut(body, Pos(0, 0, zc) * extrude(strip, H))
        stages.append(Stage("buttons", body))

        # wheel opening between the buttons
        xw = hl - L * 0.21
        slot = Pos(xw, 0, H * 0.4) * Box(25, 10.5, H, align=BOTTOM)
        slot = craft.safe_fillet(slot, slot.edges().filter_by(lambda e: abs(e.tangent_at(0.5).Z) > 0.99), 4.5)
        body = craft.cut(body, slot)
        stages.append(Stage("wheel_slot", body))

        # side buttons: two raised pills above the thumb groove, crisp-edged
        zs = H * 0.70                                 # above the thumb groove
        for x_c in (L * 0.07, -L * 0.10):
            pill = [(x_c + 9.5 * x, zs + 3.4 * y) for x, y in craft.superellipse(1, 1, 3.5, count=20)]
            reg = craft.two_view_cutter(pill, [(W * 0.3, -10), (W, -10), (W, H), (W * 0.3, H)], x_range=(-L, L),
                                        smooth=(True, False))
            band = craft.surface_band(secs, tip, 1.4, reg, depth=t / 2)
            body = craft.fuse(body, band if scoop is None else craft.cut(band, scoop))
        stages.append(Stage("side_buttons", body))

        # DPI button behind the wheel
        dpi = Pos(xw - 22, 0, 0) * extrude(craft.superellipse_face(5.5, 3.2, 3.0), 2 * H)
        body = craft.fuse(body, craft.surface_band(secs, tip, 0.9, dpi, depth=t / 2))
        stages.append(Stage("dpi", body))

        # rubber grips: a raised panel low on each flank (the thumb side under the groove, the little-finger side)
        for sy in (1, -1):
            side = [(-L * 0.30, 6.5), (L * 0.22, 6.5), (L * 0.30, H * 0.26), (L * 0.05, H * 0.33), (-L * 0.24, H * 0.30)]
            front = ([(W * 0.15, -10), (W, -10), (W, H), (W * 0.15, H)] if sy > 0 else
                     [(-W, -10), (-W * 0.15, -10), (-W * 0.15, H), (-W, H)])
            reg = craft.two_view_cutter(side, front, x_range=(-L, L), smooth=(True, False))
            band = craft.surface_band(secs, tip, 0.4, reg, depth=t / 2)
            if scoop is not None and sy > 0:                  # the bands follow the sections: keep the groove open
                band = craft.cut(band, scoop)
            body = craft.fuse(body, band)
        stages.append(Stage("grips", body))

        # screw bosses: posts from the inside of the dome down to the base plane, 2.5 mm self-tap pilots
        mid = inner                                   # the post runs up to the inside of the shell
        for bx, by in ((-L * 0.28, 0), (L * 0.14, -W * 0.22), (L * 0.14, W * 0.18)):
            post = (Pos(bx, by, 1.0) * Cylinder(3.2, H, align=BOTTOM)) & mid
            post = post - Pos(bx, by, 0.5) * Cylinder(1.25, 12, align=BOTTOM)
            body = craft.fuse(body, post)
        stages.append(Stage("bosses", body))

        # scroll wheel: a rubber-tyred wheel in the opening, 0.8 mm clear, standing 3 mm proud of the buttons
        hit = outer.find_intersection_points(craft_axis(xw, 0))
        ztop = max(p[0].Z for p in hit) if hit else H * 0.85
        rw = 11.0
        wheel = Pos(xw, 0, ztop + 3.0 - rw) * Rot(90, 0, 0) * Cylinder(rw, 7.0)
        for i in range(24):
            wheel = wheel - Pos(xw, 0, ztop + 3.0 - rw) * Rot(0, i * 15, 0) * Pos(0, 0, rw) * Box(1.1, 8, 1.4)
        wheel = craft.safe_fillet(wheel, [e for e in wheel.edges() if abs(abs(e.center().Y) - 3.5) < 0.01], 0.8)
        body = craft.fuse(body, wheel, max_solids=2, min_solids=2)
        stages.append(Stage("wheel", body))
        return stages

    def mesh_texture(self, v):
        if v["grain"] <= 0:
            return []
        return [MeshTexture("grain", amplitude=v["grain"], scale=1.0, features=["grips"], facing="out",
                            edge_falloff=1.2)]

    def appearance(self, v):
        return [{"features": ["grips", "wheel"], "finish": "rubber", "color": "#1a1b1d"},
                {"features": ["side_buttons", "dpi"], "finish": "gloss", "color": "#202226"},
                {"features": ["shell", "thumb", "skirt", "buttons", "wheel_slot", "bosses"], "finish": "matte",
                 "color": "#2b2d31"}]

    def derived(self, v):
        F = self.form(v)
        return [{"key": "hump_x", "label": "Hump from the back", "value": round(v["hump"] * F["L"], 1), "unit": "mm",
                 "feature": "shell", "formula": "hump x length", "interface": False}]


def craft_axis(x, y):
    from build123d import Axis
    return Axis((x, y, 0), (0, 0, 1))
