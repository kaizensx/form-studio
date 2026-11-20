"""Sculpted half-face prop mask for cosplay: a 2.5 mm shell that follows a face (sized from an ANSUR II head) from
the forehead to the upper lip, with a hollow sculpted nose, almond eye openings cut in two views, raised brow ridges,
a rolled rim and strap slots at the temples. A prop. Form Studio exemplar design.
"""

from build123d import Axis, Plane, SlotOverall, Vector, extrude

from form import craft
from form.craft import MeshTexture
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

META = {
    "title": "Sculpted half-face mask",
    "category": "organic",
    "tags": ["mask", "half mask", "face mask", "masquerade", "cosplay", "prop", "costume", "face", "sculpted",
             "organic", "eye openings", "brow", "nose", "strap", "wearable", "leather"],
    "techniques": ["craft.profile_sections: a face from side, front and plan guide curves (no crown)",
                   "mask = craft.offset_body(gap + t) - craft.offset_body(gap), clipped to a front-view outline",
                   "a hollow nose: lofted sections, the same sections shrunk by the wall subtracted",
                   "craft.two_view_cutter almond eye openings (front shape, side depth)",
                   "a raised rim by cutting the field down inside craft.grow_outline(outline, -5) (no fuse on the "
                   "edge)",
                   "brow ridges: a surface band on the field (offset_body & crescent region, minus the root)",
                   "strap slots cut along Y through the temple tabs; MeshTexture leather grain outside"],
    "lessons": [
        "A mask is a skin of the face, not a shape of its own: describe the face (ANSUR II head: 199 x 155 mm, eyes "
        "about 64 mm apart), grow it by a comfort gap (3 mm) and the wall, and take the layer between. Then it sits "
        "on a real face at every point, which a mask drawn freehand never does.",
        "The front view decides it: the outline (forehead arch, temple tabs, the cheekbone line sweeping in under the "
        "eyes to the nose) and the eyes. Cut the eyes in two views: the front outline is the almond with a lifted "
        "outer corner, the side outline keeps the cut to the front so it does not pierce the temple tabs.",
        "Eye openings sit on the pupils: centres 32 mm either side of the middle (mean interpupillary distance 63-64 "
        "mm) and wide enough (36 mm) for peripheral vision; a mask whose holes are 'about right' blinds its wearer.",
        "A nose that reads is lofted and hollow: narrow at the bridge, widest at the wings, projecting about 20 mm; "
        "the same sections shrunk by the wall leave room for the wearer's nose and keep the wall even.",
        "Sculpted reads as relief: brow ridges 3-4 mm proud and a 1.5 mm raised rim, each bordered by a crisp line. "
        "Make the rim by recessing the field (cut a thin layer inside the outline shrunk 5 mm), not by fusing a band "
        "that shares the cut edge with the shell: that fuse fails. A flat shell with holes reads as a stencil.",
        "Strap slots go through the temple tabs along the wall's normal, 4 x 18 mm for a 15 mm elastic, at least "
        "6 mm in from the edge so the tab does not tear.",
    ],
}

X0 = 40.0                                                    # the mask's back edge (temples), x
EZ = 52.0                                                    # eye line above the mask's lowest point


def _mirror(half):
    """A closed front outline from its +y half [(y, z), ...] (top centre first, bottom centre last)."""
    return half + [(-y, z) for y, z in reversed(half[1:-1])]


def _dense(points, n):
    """A closed outline resampled as n points on the periodic B-spline through it: smooth to the eye, but cut as a
    polygon. Booleans with a fine polygon prism are more robust than with one long spline face (the spline version of
    the rim band below lost most of its volume in the boolean; the polygon one is exact)."""
    from build123d import Spline, Vector
    sp = Spline(*[Vector(x, y, 0) for x, y in points], periodic=True)
    return [(sp.position_at(i / n).X, sp.position_at(i / n).Y) for i in range(n)]


def _crescent(y_in, y_out, z0, n=14):
    """A brow crescent in the front view, as a fine polygon: its lower edge arches over the eye and lifts to the
    temple; it is thickest a third of the way out and tapers to blunt tips. (A closed spline through a few points
    with sharp tips overshoots into a loop; a dense polygon does not.)"""
    import math
    low, up = [], []
    for i in range(n + 1):
        u = i / n
        y = y_in + (y_out - y_in) * u
        zl = z0 + 5.0 * math.sin(math.pi * u) + 2.0 * u
        th = 1.5 + 9.0 * math.sin(math.pi * u ** 0.8) ** 0.8
        low.append((y, zl))
        up.append((y, zl + th))
    return low + list(reversed(up))


def _band(secs, amount, region, depth):
    """craft.surface_band, with its last boolean through craft.cut: on this open-ended face form the plain
    `piece - root` comes back invalid and craft.cut's fuzzy fallback closes it."""
    piece = craft.offset_body(secs, None, amount) & region
    return craft.cut(piece, craft.offset_body(secs, None, -depth))


class Design(Recipe):
    title, summary = "Half-face mask", ("Sculpted half-face prop mask on a face from ANSUR II proportions: hollow "
                                        "nose, two-view eye openings, brow ridges, a rolled rim and strap slots.")
    solids = 1
    photo_color = "#6e3b2a"
    params = [
        Param("face_w", "Face breadth", 146, 130, 160, 1, "mm", "brief", "shell",
              "Bizygomatic breadth (cheekbone to cheekbone); ANSUR II mean male 141, female 131 mm. Plus 5 mm skin."),
        Param("wall", "Wall", 2.5, 1.6, 4.0, 0.1, "mm", "form", "shell", "Printed or cast prop shells 2-3 mm."),
        Param("gap", "Comfort gap", 3.0, 1.0, 6.0, 0.5, "mm", "interface", "shell", "Air (or foam) over the skin."),
        Param("eye_w", "Eye opening width", 36, 28, 42, 1, "mm", "form", "eyes"),
        Param("ipd", "Eye spacing", 64, 56, 72, 1, "mm", "brief", "eyes",
              "Interpupillary distance: mean adult 63-64 mm (ANSUR II)."),
        Param("nose", "Nose projection", 20, 12, 28, 1, "mm", "form", "nose"),
        Param("brow", "Brow ridge height", 3.5, 1.5, 6.0, 0.25, "mm", "form", "brow"),
        Param("grain", "Leather grain depth", 0.15, 0, 0.4, 0.05, "mm", "form", "shell", "Mesh texture; 0 = smooth."),
    ]
    features = [Feature("shell", "Mask shell (its outer skin is the raised rim)", "structure"),
                Feature("field", "Recessed field", "finish"),
                Feature("nose", "Nose", "structure"), Feature("eyes", "Eye openings", "access"),
                Feature("brow", "Brow ridges", "finish"), Feature("straps", "Strap slots", "interface")]

    def constraints(self, v):
        if v["ipd"] / 2 + v["eye_w"] * 0.6 > v["face_w"] / 2 - 10:
            return [RecipeError("The eye openings run past the temples", "eyes", "Narrow the eyes or the spacing.",
                                ["eye_w", "ipd"])]
        return []

    def face(self, v):
        """The face surface (skin) as sections: forehead, brow, eye, cheek and upper-lip heights, egg-shaped in plan
        (narrowing toward the front), from z = -15 to the hairline."""
        hw = v["face_w"] / 2
        front = [(-15, 92.0), (EZ - 30, 95.0), (EZ - 6, 95.5), (EZ + 14, 99.5), (EZ + 40, 96.0), (EZ + 75, 86.0)]
        back = [(-15, -60.0), (EZ + 75, -60.0)]
        half = [(-15, hw * 0.82), (EZ - 20, hw * 0.94), (EZ + 10, hw), (EZ + 40, hw * 0.98), (EZ + 75, hw * 0.88)]
        squash = [(-15, 0.42), (EZ, 0.36), (EZ + 75, 0.28)]
        secs, _ = craft.profile_sections(front, back, half, levels=12, n=2.3, squash=squash, seam=180.0)
        return secs

    def outline(self, v):
        """The mask in the front view, (y, z)."""
        hw = v["face_w"] / 2
        return _dense(_mirror([(0, EZ + 60), (hw * 0.50, EZ + 56), (hw * 0.80, EZ + 42), (hw * 0.93, EZ + 18),
                               (hw * 0.91, EZ - 4), (hw * 0.78, EZ - 24), (hw * 0.52, EZ - 32), (hw * 0.30, 12.0),
                               (hw * 0.20, 2.0), (0, 4.0)]), 72)

    def eye(self, v, sy, grow=0.0):
        y0, w = sy * v["ipd"] / 2, v["eye_w"] / 2
        al = [(y0 - sy * w, EZ - 1), (y0 - sy * w * 0.5, EZ + 7), (y0 + sy * w * 0.3, EZ + 9.5), (y0 + sy * w, EZ + 6),
              (y0 + sy * w * 1.08, EZ + 2), (y0 + sy * w * 0.5, EZ - 6), (y0 - sy * w * 0.3, EZ - 7)]
        if sy < 0:
            al = list(reversed(al))
        if grow:
            al = craft.grow_outline(al, grow)
        # a smooth spline almond (two lip edges per eye, which a fillet can round; a polygon gives dozens it cannot)
        return craft.two_view_cutter([(40, EZ - 25), (200, EZ - 25), (200, EZ + 25), (40, EZ + 25)], al,
                                     x_range=(30, 200), smooth=(False, True))

    def build(self, v):
        secs = self.face(v)
        t, g = v["wall"], v["gap"]
        out_line = self.outline(v)
        # --- snippet: a mask as the layer between two offsets of a face, clipped to its front outline
        # the side view stops it at the temples (x = 40: a half mask, not a wrap round to the ears)
        region = craft.two_view_cutter([(X0, -40), (200, -40), (200, 200), (X0, 200)], out_line, x_range=(X0, 200),
                                       smooth=(False, False))
        R = 1.5                                                   # the rim stands this far proud of the field
        skin_out, skin_in = craft.offset_body(secs, None, g + t + R), craft.offset_body(secs, None, g)
        shell = craft.cut(skin_out & region, skin_in)
        # --- end snippet
        stages = [Stage("shell", shell)]

        # --- snippet: a raised rim by recessing the field, not by fusing a band on the edge
        # The shell is cast R thicker, then the field inside the outline shrunk by 5 mm is cut down by R. A band fused
        # onto the edge would share the edge's cut faces with the shell, and that fuse fails; a cut of a thin layer
        # whose border lies inside the part never meets a coincident face.
        field = craft.two_view_cutter([(X0 - 1, -40), (200, -40), (200, 200), (X0 - 1, 200)],
                                      craft.grow_outline(out_line, -5.0), x_range=(X0 - 1, 200), smooth=(False, False))
        layer = craft.cut(craft.offset_body(secs, None, g + t + R + 2) & field, craft.offset_body(secs, None, g + t))
        shell = craft.cut(shell, layer)
        shell = craft.safe_fillet(shell, [e for e in shell.edges() if e.center().X > X0 + 2], 0.3)
        # --- end snippet
        stages.append(Stage("field", shell))
        msecs, _ = craft.inflate(secs, g + t)                     # the field's surface: nose and brows grow from it

        # nose: lofted sections from the wings (z = 6) to the bridge, hollowed by the same sections shrunk by the wall
        P = v["nose"]
        xs = 95.5 + g                                             # the face surface (inflated) at the nose
        nose_secs = []
        for z, proj, half_w in ((3.0, P * 0.55, 15.0), (9.0, P, 13.5), (18.0, P * 0.86, 10.5), (30.0, P * 0.6, 8.5),
                                (EZ - 8, P * 0.28, 7.5), (EZ + 2, 1.0, 8.5)):
            back = xs - 14.0
            a = (xs + t + proj - back) / 2
            nose_secs.append({"z": z, "a": a, "b": half_w, "n": 2.0, "cx": back + a, "squash": 0.45, "seam": 180.0})
        nose_out = craft.section_body(nose_secs)
        # the cavity only where the nose stands well proud (z <= 30): higher up an inset would break through the mask
        inner = [{**s, "a": s["a"] - t, "b": s["b"] - t} for s in nose_secs if s["z"] <= 30.0]
        inner.insert(0, {**inner[0], "z": inner[0]["z"] - 3.0})
        nose_in = craft.section_body(inner)
        body = craft.fuse(shell, craft.cut(nose_out & region, skin_in))
        body = craft.cut(body, nose_in)
        stages.append(Stage("nose", body))

        # eye openings (their lips are left crisp: the cut crosses the faceted rim recess, and a fillet over dozens
        # of short edges mostly fails; sand them on the print)
        eyes = self.eye(v, 1) + self.eye(v, -1)
        body = craft.cut(body, eyes)
        stages.append(Stage("eyes", body))

        # brow ridges: a crescent over each eye, grown from the field (msecs), its top rounded
        brows = None
        for sy in (1, -1):
            y0, w = sy * v["ipd"] / 2, v["eye_w"] / 2
            cr = _crescent(sy * 7.0, y0 + sy * w * 1.35, EZ + 11)
            reg = craft.two_view_cutter([(0, EZ), (200, EZ), (200, EZ + 40), (0, EZ + 40)], cr, x_range=(0, 200),
                                        smooth=(False, False))
            b = _band(msecs, v["brow"], reg, t / 2)
            brows = b if brows is None else brows + b
        brows = craft.safe_fillet(brows, brows.edges(), min(0.75, v["brow"] * 0.3))
        body = craft.fuse(body, brows)
        stages.append(Stage("brow", body))

        # strap slots: one through each temple tab 10 mm in from its edge, cut along the wall's normal there; vertical,
        # 18 x 4 mm for a 15 mm elastic strap
        hw = v["face_w"] / 2
        slots = None
        for sy in (1, -1):
            y = sy * (hw * 0.93 - 12)
            hits = craft.offset_body(secs, None, g + t).find_intersection_points(Axis((X0, y, EZ + 8), (1, 0, 0)))
            x = max((h[0].X for h in hits), default=X0 + 20)
            s0 = next(iter(sorted(msecs, key=lambda q: abs(q["z"] - EZ - 8))))
            n = Vector((x - s0["cx"]) / s0["a"] ** 2, y / s0["b"] ** 2, 0).normalized()   # the ellipse's normal
            pl = Plane(origin=(x, y, EZ + 8), x_dir=(0, 0, 1), z_dir=n)
            sl = pl * extrude(SlotOverall(18, 4), 8, both=True)
            slots = sl if slots is None else slots + sl
        body = craft.cut(body, slots)
        stages.append(Stage("straps", body))
        return stages

    def mesh_texture(self, v):
        if v["grain"] <= 0:
            return []
        return [MeshTexture("grain", amplitude=v["grain"], scale=1.2, features=["field", "nose"],
                            facing="out", edge_falloff=1.0)]

    def appearance(self, v):
        # what the field cut leaves of the shell's outer skin is the rim: brows and rim gold, field and nose leather
        return [{"features": ["brow", "shell"], "finish": "silk", "color": "#b08a3e"},
                {"features": ["field", "nose", "eyes", "straps"], "finish": "matte", "color": "#6e3b2a"}]

    def derived(self, v):
        return [{"key": "eye_centres", "label": "Eye opening centres", "value": v["ipd"], "unit": "mm",
                 "feature": "eyes", "formula": "interpupillary distance (ANSUR II mean 63-64 mm)", "interface": True},
                {"key": "offset", "label": "Mask off the skin", "value": v["gap"], "unit": "mm", "feature": "shell",
                 "formula": "comfort gap", "interface": True}]
