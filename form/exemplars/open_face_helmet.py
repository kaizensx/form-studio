"""Open-face (jet) motorcycle helmet in gloss cream: a shell sized from a head (EN 960 headform, ANSUR II
proportions) that covers the ears and leaves the face open, a visible comfort liner, rubber edge trim, a three-snap
sun peak as its own body, crown intakes, a rear exhaust and chin-strap rivets. A 3D model and form study,
not a certified helmet. Form Studio exemplar design.
"""

from build123d import Align, Axis, Box, Cylinder, Plane, Pos, Rot, Vector, extrude

from form import craft
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Open-face jet helmet with snap peak",
    "category": "helmet",
    "product_class": "helmet_open",
    "tags": ["helmet", "open-face", "open face", "jet", "jet helmet", "three-quarter", "motorcycle", "scooter",
             "retro", "peak", "snaps", "visor", "liner", "trim", "vents", "shell", "wearable", "head", "organic"],
    "techniques": ["craft.helmet_open(kind=\"open\") (head size -> guide curves -> sections)",
                   "craft.checked_body + craft.inset_body hollowing",
                   "side-profile prism cuts the face opening and the lower edge in one line",
                   "a liner as the layer between two inset bodies, recessed behind the shell's edge",
                   "craft.surface_band for trim, intake pads, rivet discs and the peak's snap band",
                   "a peak = surface band + a tilted brim slab minus the shell grown by the gap (fuse min_solids=2)",
                   "snap studs placed on the surface by ray intersection, along the local normal",
                   "appearance() zones: gloss shell, rubber trim, smoke peak, matte liner, metal snaps"],
    "lessons": [
        "Size it from a head: craft.head_form gives the EN 960 headform's length and breadth; an open-face helmet adds "
        "comfort + EPS + shell (about 47 mm a side), so a size J comes out near 293 x 249 x 218 mm, like a real "
        "size M jet helmet. A bowl sized by eye never does.",
        "One side-view line decides an open-face helmet: high across the brow (just above the eyebrows, about the "
        "eye line + 25 mm), dropping steeply in front of the ear to cover the cheek, then running low and nearly "
        "level round the nape. Cut it once as a prism through both walls and every view gets it right.",
        "A thin shell alone reads as a salad bowl. Show the liner: the layer between two inset bodies, recessed 5 mm "
        "behind the shell's edge so the rubber trim reads as the lip. The thickness (EPS + comfort, ~44 mm) is what "
        "makes the opening look like a helmet you can put a head in.",
        "A snap peak is its own body: the shell surface grown by a gap (1.5 mm), a 2.2 mm skin over the brow, plus a "
        "brim slab tilted 12 deg down and trimmed by the grown shell so it hugs the curve. Its snap holes clear the "
        "studs by 0.5 mm a side; craft.fuse(..., min_solids=2) refuses a peak that touches the shell.",
        "Place surface hardware (snaps, rivets) by intersecting a ray with the body and orienting along the plan "
        "normal: hard-coded coordinates float or sink as soon as the head size changes.",
        "Keep every added detail on the surface's own offsets (surface_band) so trim, pads and peak share one design "
        "language and never leave coincident faces in a boolean; round the cut lip (1.2-1.5 mm) where it meets skin.",
    ],
}


def _prism_y(points):
    """A smooth (x, z) outline extruded through the whole width."""
    return extrude(craft.spline_profile(points, plane=Plane.XZ), 400, both=True)


def _shift(points, dz):
    return [(x, z + dz) for x, z in points]


def _surface_point(body, y, z, dirx=1.0):
    """Where a ray along +X (dirx = 1) or -X from (0, y, z) leaves the body: (point, outward plan normal)."""
    hits = body.find_intersection_points(Axis((0, y, z), (dirx, 0, 0)))
    p = max((h[0] for h in hits), key=lambda q: dirx * q.X) if hits else Vector(dirx * 140, y, z)
    n = Vector(p.X, p.Y * 1.35, 0).normalized()          # plan normal of a long oval, good enough for a stud
    return p, n


class Design(Recipe):
    title, summary = "Open-face helmet", ("Jet helmet shell sized from a head, with a visible liner, rubber edge trim, "
                                          "a three-snap sun peak, crown intakes, a rear exhaust and strap rivets.")
    solids = 2
    photo_color = "#e9e1cf"
    params = [
        Param("head", "Head circumference", 570, 520, 620, 10, "mm", "brief", "shell",
              "EN 960 headform sizes: E 540, J 570, M 600, O 620."),
        Param("cephalic", "Head breadth / length", 0.78, 0.74, 0.84, 0.01, "", "brief", "shell",
              "0.78 ANSUR II mean (long oval); 0.83 a round head."),
        Param("wall", "Shell wall", 3.2, 2.0, 5.0, 0.1, "mm", "form", "shell", "ABS / fibreglass jet shells 2.5-4 mm."),
        Param("liner", "Liner thickness", 40, 20, 46, 1, "mm", "form", "liner",
              "EPS + comfort liner (HELMET_LAYERS: 34 + 10 mm). Stays below the 47 mm build-up."),
        Param("peak_gap", "Peak gap", 1.5, 1.0, 3.0, 0.1, "mm", "interface", "peak",
              "Air between the peak and the shell; the snaps carry it."),
        Param("peak_reach", "Peak reach", 30, 18, 50, 1, "mm", "form", "peak",
              "How far the brim projects past the brow; jet sun peaks run 25-40 mm."),
    ]
    features = [Feature("shell", "Shell", "structure"), Feature("opening", "Face opening and lower edge", "structure"),
                Feature("liner", "Comfort liner", "finish"), Feature("trim", "Rubber edge trim", "finish"),
                Feature("intakes", "Crown intakes", "access"), Feature("exhaust", "Rear exhaust", "access"),
                Feature("rivets", "Chin-strap rivets", "interface"), Feature("snaps", "Peak snap studs", "interface"),
                Feature("peak", "Sun peak", "structure")]

    def constraints(self, v):
        if v["wall"] + v["liner"] > 50:
            return [RecipeError("Shell and liner are thicker than the helmet's build-up round the head", "liner",
                                "Thin the liner or the wall.", ["liner", "wall"])]
        return []

    def form(self, v):
        return craft.helmet_open(v["head"], kind="open", cephalic=v["cephalic"])

    def build(self, v):
        F = self.form(v)
        L, W, H, t = F["L"], F["W"], F["H"], v["wall"]
        hl = L / 2
        secs, tip = F["sections"], F["tip"]
        edge = F["edge"]
        # --- snippet: hollow a lofted helmet and cut its face opening with one side-view line
        outer = craft.checked_body(secs, tip, label="shell")
        inner = craft.inset_body(secs, t, tip=tip)
        body = craft.cut(outer, inner)
        stages = [Stage("shell", body)]

        cut = _prism_y(edge)
        body = craft.cut(body, cut)
        lip = [e for e in body.edges() if e.center().Z < 0.45 * H and abs(e.center().Y) < W]
        body = craft.safe_fillet(body, lip, 1.4)
        stages.append(Stage("opening", body))
        # --- end snippet

        # comfort liner: the layer between the shell's inside and an inset of (wall + liner), recessed 5 mm behind the
        # shell's edge; 0.3 mm into the shell so the fuse never meets coincident faces
        # (the head cavity: sections shrunk in plan by wall + liner, the small crown sections dropped, the crown point
        # lowered by the same amount; an inset along the normal cannot shrink a 45 mm crown section by 43 mm)
        T = t + v["liner"]
        cav = [{**s, "a": s["a"] - T, "b": s["b"] - T} for s in secs if min(s["a"], s["b"]) > T + 12]
        cav.insert(0, {**cav[0], "z": cav[0]["z"] - 2.0})
        cavity = craft.section_body(cav, tip=(tip[0], tip[1], tip[2] - T))
        liner = craft.cut(craft.inset_body(secs, t - 0.3, tip=tip), cavity)
        liner = craft.cut(liner, _prism_y(_shift(edge, 5)))
        liner = craft.safe_fillet(liner, [e for e in liner.edges() if e.center().Z < 0.5 * H], 3.0)
        body = craft.fuse(body, liner)
        stages.append(Stage("liner", body))

        # rubber trim: a 2 mm band round the whole cut line (brow, cheeks, nape)
        band = _prism_y(_shift(edge, 9)) - cut
        trim = craft.surface_band(secs, tip, 2.0, band, depth=t / 2)
        body = craft.fuse(body, trim)
        stages.append(Stage("trim", body))

        # crown intakes: two slender pads either side of the centre line, each with three forward slots
        zc = H * 0.86
        pads, slots = None, None
        for sy in (-1, 1):
            foot = Pos(L * 0.20, sy * W * 0.12, zc) * extrude(craft.superellipse_face(30, 9, 3.0, rotate=-sy * 6), H)
            foot = Pos(0, 0, -H * 0.5) * foot
            pad = craft.surface_band(secs, tip, 3.0, foot, depth=t / 2)
            pads = pad if pads is None else pads + pad
            g = craft.slot_grille((L * 0.20, sy * W * 0.12, H * 0.9), (0.25, 0, 1), count=2, length=40, width=3,
                                  pitch=7, depth=30, angle=90)
            slots = g if slots is None else slots + g
        body = craft.cut(craft.fuse(body, pads), slots)
        stages.append(Stage("intakes", body))

        # rear exhaust: a lens-shaped pad at the back of the crown with four slots
        ze = H * 0.62
        lens = [(36 * x, ze + 11 * y) for x, y in craft.superellipse(1, 1, 2.6, count=16)]
        reg = craft.two_view_cutter([(-L, ze - 14), (-hl * 0.5, ze - 14), (-hl * 0.5, ze + 14), (-L, ze + 14)], lens,
                                    x_range=(-L, 0), smooth=(False, True))
        body = craft.fuse(body, craft.surface_band(secs, tip, 2.5, reg, depth=t / 2))
        body = craft.cut(body, craft.slot_grille((-hl, 0, ze), (-1, 0, 0), count=4, length=44, width=3, pitch=6,
                                                 depth=40, angle=90, taper=0.3))
        stages.append(Stage("exhaust", body))

        # chin-strap rivets: a raised disc low on each cheek with a domed rivet head (the D-ring strap hangs here)
        zr = 34.0
        discs = Pos(hl * 0.12, 0, zr) * Rot(90, 0, 0) * Cylinder(11, W + 40)
        body = craft.fuse(body, craft.surface_band(secs, tip, 1.5, discs, depth=t / 2))
        for sy in (-1, 1):
            hits = outer.find_intersection_points(Axis((hl * 0.12, 0, zr), (0, sy, 0)))
            y = max((sy * h[0].Y for h in hits), default=W / 2) * sy
            head = Pos(hl * 0.12, y + sy * 1.2, zr) * Rot(90, 0, 0) * Cylinder(4.5, 3.0)
            body = craft.fuse(body, craft.safe_fillet(head, head.edges(), 1.2))
        stages.append(Stage("rivets", body))

        # --- snippet: a separate snap-on peak that hugs the shell at a gap
        g = v["peak_gap"]
        # the brim root sits 2.5 mm above the top of the brow trim, measured, not assumed (the edge is a spline and
        # rises between its points)
        brow = trim & Pos(hl * 0.35, 0, H / 2) * Box(L, 2 * W, 2 * H, align=(Align.MIN, Align.CENTER, Align.CENTER))
        zb = brow.bounding_box().max.Z + 2.5
        studs, holes = None, None
        for y in (-W * 0.24, 0.0, W * 0.24):
            p, n = _surface_point(outer, y, zb + 14)
            pl = Plane(origin=p, z_dir=n)
            stud = pl * Pos(0, 0, -t * 0.5) * Cylinder(3.6, t * 0.5 + 4.0, align=BOTTOM)
            stud = craft.safe_fillet(stud, [e for e in stud.edges() if (e.center() - p).dot(n) > 2], 1.0)
            studs = stud if studs is None else studs + stud
            hole = pl * Pos(0, 0, -2) * Cylinder(4.1, 12, align=BOTTOM)
            holes = hole if holes is None else holes + hole
        body = craft.fuse(body, studs)
        stages.append(Stage("snaps", body))

        skin_reg = craft.two_view_cutter([(hl * 0.40, zb - 1), (L, zb - 1), (L, zb + 28), (hl * 0.55, zb + 26)],
                                         [(-W * 0.36, zb - 30), (W * 0.36, zb - 30), (W * 0.33, zb + 26),
                                          (-W * 0.33, zb + 26)], x_range=(0, L), smooth=(False, False))
        hi_, lo_ = craft.offset_body(secs, tip, g + 2.2), craft.offset_body(secs, tip, g)
        skin = craft.cut(hi_ & skin_reg, lo_)
        r = v["peak_reach"]
        brim_plan = [(hl * 0.3, -W * 0.37), (hl * 0.8 + r * 0.5, -W * 0.30), (hl + r * 0.85, -W * 0.14), (hl + r, 0),
                     (hl + r * 0.85, W * 0.14), (hl * 0.8 + r * 0.5, W * 0.30), (hl * 0.3, W * 0.37)]
        brim = extrude(craft.spline_profile(brim_plan), 2.4)
        brim = Pos(0, 0, zb) * (Pos(hl, 0, 0) * Rot(0, 12, 0) * Pos(-hl, 0, 0) * brim)
        brim = craft.cut(brim, lo_)
        peak = craft.fuse(skin, brim)
        peak = craft.safe_fillet(peak, [e for e in peak.edges() if e.center().X > hl + 4], 1.0)
        peak = craft.cut(peak, holes)
        body = craft.fuse(body, peak, max_solids=2, min_solids=2)
        stages.append(Stage("peak", body))
        # --- end snippet
        return stages

    def appearance(self, v):
        return [{"features": ["trim"], "finish": "rubber", "color": "#141516"},
                {"features": ["liner"], "finish": "matte", "color": "#3b2f27"},
                {"features": ["peak"], "finish": "smoke", "color": "#2a3138"},
                {"features": ["snaps", "rivets"], "finish": "metal", "color": "#b8bcc2"},
                {"features": ["intakes", "exhaust"], "finish": "matte", "color": "#1d1f22"},
                {"features": ["shell", "opening"], "finish": "gloss", "color": "#e9e1cf"}]

    def derived(self, v):
        F = self.form(v)
        hd = F["head"]
        return [{"key": "shell_length", "label": "Shell length", "value": F["L"], "unit": "mm", "feature": "shell",
                 "formula": "head length + 2 x (comfort + EPS + shell)", "interface": False},
                {"key": "shell_width", "label": "Shell width", "value": F["W"], "unit": "mm", "feature": "shell",
                 "formula": "head breadth + 2 x (comfort + EPS + shell)", "interface": False},
                {"key": "head_length", "label": "Head length", "value": hd["length"], "unit": "mm", "feature": "shell",
                 "formula": hd["source"], "interface": True}]
