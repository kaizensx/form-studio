"""Sci-fi character helmet for cosplay and props: a full head shell sized from a head (EN 960 headform), a
wraparound visor as its own body, a raised crest over the crown, ear pods, cheek vents, a jaw plate, panel lines
grooved into the shell and a collar ring. A generic design, no franchise likeness. A prop, not
protective equipment. Form Studio exemplar design.
"""

from build123d import Align, Axis, Box, Cylinder, Plane, Pos, Rot, extrude

from form import craft
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Sci-fi character helmet",
    "category": "helmet",
    "product_class": "helmet_fullface",
    "tags": ["helmet", "sci-fi", "scifi", "science fiction", "cosplay", "prop", "costume", "space", "armor", "visor",
             "wraparound", "crest", "panel lines", "greebles", "ear pods", "vents", "shell", "wearable", "head"],
    "techniques": ["craft.helmet_fullface for head-sized sections (chin bar shortened)",
                   "craft.checked_body + craft.inset_body hollowing",
                   "craft.two_view_cutter for a wraparound visor window (side + front outline)",
                   "visor = offset_body(gap + t) - offset_body(gap) clipped to the grown window (separate solid)",
                   "panel lines = thin two-view strips through a skin layer, cut as grooves",
                   "craft.surface_band for the crest, ear-pod bases, cheek pads and collar",
                   "craft.slot_grille for cheek and chin vents",
                   "appearance() zones: gloss shell, smoke visor, accent crest, metal greebles"],
    "lessons": [
        "Size a prop helmet from the head like a real one: craft.helmet_fullface(head) gives the shell round an EN 960 "
        "headform with 47 mm a side for padding. Cosplay helmets that are sized by eye come out either a bobblehead or "
        "a bucket; real proportions are what make a costume read as believable.",
        "The visor is the face. A wraparound band drawn in two views (side: how far it wraps toward the ears; front: "
        "the slight chevron that gives it a brow) reads as a character; a rectangle cut from the front reads as a "
        "letterbox. Make the visor its own body, the shell's surface grown by a gap, so it can be vac-formed or "
        "printed clear and a person can see out.",
        "Panel lines are grooves, not decals: a 1.2 mm strip drawn in two views, intersected with the skin layer "
        "between the surface grown 1 mm and shrunk 0.8 mm, and cut. They must follow the form's flow (a centre seam "
        "over the crown, a ring round the ear pods, a line under the visor) or they read as scratches.",
        "Greebles need a hierarchy: one dominant feature (the crest), two secondary (ear pods, cheek vents), small "
        "repeats (chin slots). Equal-sized details everywhere is noise.",
        "Keep every addition on the surface's own offsets (surface_band) so nothing floats and no boolean meets a "
        "coincident face; keep the visor >= 1.5 mm off the shell and fuse it with min_solids=2 so it cannot touch.",
        "Give it three materials: gloss shell, smoked visor, one accent colour on the crest; metal on the ear pods. "
        "One colour renders as a blob.",
    ],
}


def _prism_y(points):
    return extrude(craft.spline_profile(points, plane=Plane.XZ), 400, both=True)


def _shift(points, dz):
    return [(x, z + dz) for x, z in points]


class Design(Recipe):
    title, summary = "Sci-fi helmet", ("Cosplay helmet sized from a head: wraparound visor, crest, ear pods, cheek "
                                       "vents, jaw plate, panel lines and a collar ring.")
    solids = 2
    photo_color = "#e8e9ec"
    params = [
        Param("head", "Head circumference", 570, 520, 620, 10, "mm", "brief", "shell",
              "EN 960 headform sizes: E 540, J 570, M 600, O 620."),
        Param("wall", "Shell wall", 3.0, 2.0, 5.0, 0.1, "mm", "form", "shell",
              "Printed cosplay shells: 2-3 mm PLA/PETG, sanded and primed."),
        Param("visor_h", "Visor height", 46, 32, 60, 1, "mm", "form", "visor", "At the centre line."),
        Param("visor_gap", "Visor gap", 2.0, 1.5, 3.5, 0.1, "mm", "interface", "visor"),
        Param("crest_h", "Crest height", 9, 4, 16, 0.5, "mm", "form", "crest"),
        Param("chin", "Jaw projection", 0.75, 0.6, 1.0, 0.05, "", "form", "shell",
              "Scales craft.helmet_fullface's chin bar; lower is a rounder, less motorcycle face."),
    ]
    features = [Feature("shell", "Shell", "structure"), Feature("collar", "Lower edge and collar", "structure"),
                Feature("visor_port", "Visor window", "access"), Feature("crest", "Crest", "finish"),
                Feature("panels", "Panel lines", "finish"), Feature("ear_pods", "Ear pods", "finish"),
                Feature("cheek_vents", "Cheek vents", "access"),
                Feature("chin_grille", "Jaw plate and grille", "access"),
                Feature("visor", "Visor", "structure")]

    def constraints(self, v):
        if v["visor_h"] > 52 and v["head"] < 540:
            return [RecipeError("A visor that tall leaves no brow on a small shell", "visor", "Lower the visor.",
                                ["visor_h"])]
        return []

    def form(self, v):
        return craft.helmet_fullface(v["head"], chin=v["chin"], tail=1.1)

    def window(self, F, v, grow=0.0):
        """The visor window in two views: wraps back to just ahead of the ear pods; a shallow chevron in front."""
        L, W, ze = F["L"], F["W"], F["z_eye"]
        hl, h = L / 2, v["visor_h"]
        zb, zt = ze - h * 0.55, ze + h * 0.45
        xe = F["pivot"][0] + 46                                 # the wrap stops ahead of the ear pod (r 30)
        side = [(hl * 1.4, zb - 8), (hl * 0.75, zb - 2), (xe + 22, zb + 4), (xe + 6, zb + h * 0.22),
                (xe, ze), (xe + 6, zt - h * 0.18), (xe + 22, zt + 2), (hl * 0.75, zt + 4), (hl * 1.4, zt + 6)]
        pw = W * 0.65
        front = [(0.0, zb - 6), (pw * 0.3, zb - 1), (pw, zb + 4), (pw, zt + 2), (pw * 0.3, zt + 3), (0.0, zt - 3),
                 (-pw * 0.3, zt + 3), (-pw, zt + 2), (-pw, zb + 4), (-pw * 0.3, zb - 1)]
        if grow:
            side, front = craft.grow_outline(side, grow), craft.grow_outline(front, grow)
        return craft.two_view_cutter(side, front, x_range=(0, L), smooth=(True, False))

    def build(self, v):
        F = self.form(v)
        L, W, H, t, ze = F["L"], F["W"], F["H"], v["wall"], F["z_eye"]
        hl = L / 2
        secs, tip = F["sections"], F["tip"]
        outer = craft.checked_body(secs, tip, label="shell")
        body = craft.cut(outer, craft.inset_body(secs, t, tip=tip))
        stages = [Stage("shell", body)]

        # lower edge: nearly level (a neck ring, not a motorcycle's scoop), then a 3 mm collar band 14 mm tall
        edge = [(hl * 1.4, -30.0), (hl * 1.4, 18.0), (hl * 0.6, 22.0), (0.0, 30.0), (-hl * 0.6, 34.0),
                (-hl * 1.4, 36.0), (-hl * 1.4, -30.0)]
        cut = _prism_y(edge)
        body = craft.cut(body, cut)
        collar = craft.surface_band(secs, tip, 3.0, _prism_y(_shift(edge, 14)) - cut, depth=t / 2)
        body = craft.fuse(body, collar)
        body = craft.safe_fillet(body, [e for e in body.edges() if e.center().Z < 34 and e.center().X > -hl * 1.2
                                        and e.center().Z < 0.25 * H], 1.0)
        stages.append(Stage("collar", body))

        port = self.window(F, v)
        body = craft.cut(body, port)
        stages.append(Stage("visor_port", body))

        # crest: a fin 24 mm wide over the crown (tapering to 16 in front view), rising from the brow and running
        # down the back
        ch = v["crest_h"]
        zt = ze + v["visor_h"] * 0.45
        fin_side = [(hl * 0.62, zt + 30), (hl * 0.2, H * 0.97), (-hl * 0.5, H * 0.94), (-hl * 0.95, H * 0.55),
                    (-hl * 1.4, H * 0.45), (-hl * 1.4, H * 1.3), (hl * 1.4, H * 1.3)]
        fin_front = [(-12, 0), (12, 0), (8, H * 1.3), (-8, H * 1.3)]
        reg = craft.two_view_cutter(fin_side, fin_front, x_range=(-L, L), smooth=(True, False))
        # surface_band's construction, with the root taken off through craft.cut: the band runs over the loft's
        # crown pole, where the plain boolean comes back invalid for some heights and the fuzzy fallback closes it
        crest = craft.cut(craft.offset_body(secs, tip, ch) & reg, craft.offset_body(secs, tip, -t / 2))
        body = craft.fuse(body, crest)
        stages.append(Stage("crest", body))

        # --- snippet: panel lines as grooves that follow the surface
        skin = craft.cut(craft.offset_body(secs, tip, 1.0), craft.offset_body(secs, tip, -0.8))
        # two seams over the crown either side of the crest (a groove under the crest would cut its root)
        seam = (Pos(0, 26, zt + 34) * Box(L * 1.4, 1.2, H, align=BOTTOM)
                + Pos(0, -26, zt + 34) * Box(L * 1.4, 1.2, H, align=BOTTOM))
        ring = Pos(F["pivot"][0], 0, F["pivot"][1]) * Rot(90, 0, 0) * (Cylinder(35, W + 40) - Cylinder(33.8, W + 40))
        brow = craft.two_view_cutter([(hl * 0.2, zt + 22), (L, zt + 22), (L, zt + 23.2), (hl * 0.2, zt + 23.2)],
                                     [(-W, zt), (W, zt), (W, zt + 40), (-W, zt + 40)], x_range=(0, L),
                                     smooth=(False, False))
        grooves = skin & (seam + ring + brow)
        body = craft.cut(body, grooves)
        # --- end snippet
        stages.append(Stage("panels", body))

        # ear pods: a raised disc base on each side with a stepped round boss and a ring groove (greebles)
        px, pz = F["pivot"]
        base = Pos(px, 0, pz) * Rot(90, 0, 0) * Cylinder(30, W + 60)
        body = craft.fuse(body, craft.surface_band(secs, tip, 3.5, base, depth=t / 2))
        for sy in (-1, 1):
            hits = outer.find_intersection_points(Axis((px, 0, pz), (0, sy, 0)))
            y = max((sy * h[0].Y for h in hits), default=W / 2) * sy
            boss = Pos(px, y, pz) * Rot(-sy * 90, 0, 0) * (Cylinder(21, 18, align=BOTTOM)
                                                            + Pos(0, 0, 18) * Cylinder(14, 4, align=BOTTOM))
            boss = Pos(0, -sy * 6, 0) * boss                       # 6 mm sunk into the shell and its base
            boss = boss - Pos(px, y, pz) * Rot(-sy * 90, 0, 0) * Pos(0, 0, 12) * (Cylinder(22, 1.2, align=BOTTOM)
                                                                                   - Cylinder(18.5, 1.2, align=BOTTOM))
            boss = craft.safe_fillet(boss, [e for e in boss.edges() if abs(abs(e.center().Y) - abs(y)) > 6], 1.0)
            body = craft.fuse(body, boss)
        stages.append(Stage("ear_pods", body))

        # cheek vents: a raked pad on each cheek, outboard of the jaw plate, with three horizontal slots centred on
        # the surface (found by a ray: a grille centred off the surface cuts only part of its slots)
        zc = ze - v["visor_h"] * 0.55 - 34
        for sy in (-1, 1):
            pad_side = [(hl * 0.52, zc - 14), (hl * 0.95, zc - 4), (hl * 0.9, zc + 10), (hl * 0.48, zc + 6)]
            front = [(sy * W * 0.33, -50), (sy * W, -50), (sy * W, H), (sy * W * 0.33, H)]
            reg = craft.two_view_cutter(pad_side, front, x_range=(0, L), smooth=(False, False))
            body = craft.fuse(body, craft.surface_band(secs, tip, 2.5, reg, depth=t / 2))
            xs = hl * 0.70
            hits = outer.find_intersection_points(Axis((xs, 0, zc - 1), (0, sy, 0)))
            ys = max((sy * h[0].Y for h in hits), default=W * 0.3) * sy
            body = craft.cut(body, craft.slot_grille((xs, ys, zc - 1), (0.55, sy, 0), count=3, length=24, width=3.0,
                                                     pitch=6.0, depth=20, angle=0))
        stages.append(Stage("cheek_vents", body))

        # jaw plate: a dark plate 3 mm proud over the chin, between the collar and the visor, narrowing downward
        # (it gives the face its "mouth"), with five vertical slots
        jtop, jbot = ze - v["visor_h"] * 0.55 - 24, 40.0
        zg = (jtop + jbot) / 2
        jaw_side = [(hl * 0.45, jbot), (L, jbot), (L, jtop), (hl * 0.45, jtop)]
        jaw_front = [(-W * 0.19, jbot), (W * 0.19, jbot), (W * 0.29, jtop), (-W * 0.29, jtop)]
        reg = craft.two_view_cutter(jaw_side, jaw_front, x_range=(0, L), smooth=(False, False))
        body = craft.fuse(body, craft.surface_band(secs, tip, 3.0, reg, depth=t / 2))
        body = craft.cut(body, craft.slot_grille((hl, 0, zg), (1, 0, 0), count=5, length=min(24.0, jtop - jbot - 12),
                                                 width=3.0, pitch=7,
                                                 depth=60, angle=90, taper=0.4))
        stages.append(Stage("chin_grille", body))

        # --- snippet: a wraparound visor as its own body, off the shell by a gap
        g = v["visor_gap"]
        lens = craft.cut(craft.offset_body(secs, tip, g + 2.5), craft.offset_body(secs, tip, g))
        visor = lens & self.window(F, v, grow=7.0)
        visor = craft.safe_fillet(visor, [e for e in visor.edges() if e.length > 30], 0.8)
        body = craft.fuse(body, visor, max_solids=2, min_solids=2)
        # --- end snippet
        stages.append(Stage("visor", body))
        return stages

    def appearance(self, v):
        return [{"features": ["visor"], "finish": "smoke", "color": "#1c2229"},
                {"features": ["crest"], "finish": "matte", "color": "#d9632b"},
                {"features": ["ear_pods"], "finish": "metal", "color": "#8d939b"},
                {"features": ["cheek_vents", "chin_grille", "collar"], "finish": "matte", "color": "#2a2d31"},
                {"features": ["shell", "visor_port", "panels"], "finish": "gloss", "color": "#e8e9ec"}]

    def derived(self, v):
        F = self.form(v)
        return [{"key": "shell_length", "label": "Shell length", "value": F["L"], "unit": "mm", "feature": "shell",
                 "formula": "head length + 2 x (comfort + EPS + shell)", "interface": False},
                {"key": "head_length", "label": "Head length", "value": F["head"]["length"], "unit": "mm",
                 "feature": "shell", "formula": F["head"]["source"], "interface": True}]
