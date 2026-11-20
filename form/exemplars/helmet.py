"""Full-face motorcycle-style helmet shell: lofted head form, eye port, chin bar vents, crown scoops, rear spoiler,
visor pivots, and a carbon-like twill mesh texture on the outside. Form Studio exemplar design (a 3D model).
"""

from build123d import Align, Axis, Box, Cylinder, Plane, Pos, Rot, SlotOverall, Wire, extrude, make_face

from form import craft
from form.craft import MeshTexture
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

META = {
    "title": "Textured full-face helmet shell",
    "tags": ["helmet", "motorcycle", "shell", "organic", "texture", "textured", "carbon", "vents", "visor", "loft",
             "mesh texture", "styled", "wearable"],
    "techniques": ["craft.section_body of superellipse sections with a crown point", "craft.dome_sections",
                   "craft.section_shell (inset sections) before cutting openings", "side-profile cutter for the lower "
                   "edge", "pads that follow the surface (craft.inflate sections, clipped to a footprint, minus the "
                   "inside)", "MeshTexture weave with facing='out'"],
    "lessons": [
        "Start from the head, not from a dome: a head is about 200 x 160 mm; the shell and liner add 45-50 mm a side, "
        "so the outer form is about 300 x 250 mm, crown behind centre, widest just above the ears.",
        "Describe the form by sections that follow laws (an ellipse in elevation, egg-shaped in plan, the chin "
        "projecting forward low down). Hand-picked boxes and spheres never read as a helmet.",
        "Hollow the closed form first, then cut the eye port and the lower edge through both walls. A lofted dome's "
        "crown point defeats offsets, so hollow it with craft.section_shell: the same sections inset by the wall.",
        "The lower edge is a side-profile curve (low at the chin, rising at the jaw, dipping at the nape) cut as a "
        "prism along Y, so the silhouette has the swoop real helmets have.",
        "Details that follow the surface (crown scoops, the chin intake, the spoiler) are the outer form grown a few mm "
        "(craft.inflate), clipped to a footprint, minus the inside: they always sit on the shell, in one design "
        "language of raised pads with slots.",
        "Texture is a mesh texture (twill weave, outside only): the STEP stays the smooth surface for tooling; STL, "
        "GLB and renders carry the weave.",
    ],
}


def _prism_y(points, half_w=200):
    """A prism of an (x, z) outline, centred on Y and 2 x half_w wide."""
    f = make_face(Wire.make_polygon([Plane.XZ.from_local_coords((x, z, 0)) for x, z in points], close=True)).faces()[0]
    return Pos(0, half_w, 0) * extrude(f, 2 * half_w)


class Design(Recipe):
    title, summary = "Full-face helmet shell", ("Lofted full-face helmet shell with eye port, chin and crown vents, rear "
                                                 "spoiler, visor pivots and a twill mesh texture.")
    solids = 1
    photo_color = "#2b2d31"
    params = [
        Param("length", "Shell length", 300, 260, 340, 1, "mm", "brief", "shell", "Front to back, outside."),
        Param("width", "Shell width", 248, 220, 290, 1, "mm", "brief", "shell"),
        Param("height", "Shell height", 270, 230, 310, 1, "mm", "brief", "shell"),
        Param("wall", "Shell wall", 3.5, 2, 6, 0.1, "mm", "form", "shell"),
        Param("port_w", "Eye port width", 190, 150, 220, 1, "mm", "form", "eye_port"),
        Param("port_h", "Eye port height", 72, 55, 95, 1, "mm", "form", "eye_port"),
        Param("texture", "Twill texture depth", 0.35, 0, 0.8, 0.05, "mm", "form", "shell", "0 = smooth. Mesh texture."),
    ]
    features = [Feature("shell", "Shell", "structure"), Feature("lower_edge", "Lower edge", "structure"),
                Feature("eye_port", "Eye port", "access"), Feature("crown_scoops", "Crown scoops", "finish"),
                Feature("spoiler", "Rear spoiler", "finish"), Feature("chin_vents", "Chin vents", "access"),
                Feature("pivots", "Visor pivots", "interface")]

    def constraints(self, v):
        if v["port_w"] > v["width"] - 40:
            return [RecipeError("The eye port is wider than the shell allows", "eye_port", "Narrow the port.", ["port_w"])]
        return []

    # ---- the outer form ----
    def _outer(self, v):
        L, W, H = v["length"], v["width"], v["height"]
        lower = H * 0.48                                          # straight-ish lower walls up to the temples
        a0, b0 = L / 2, W / 2
        # the lower sections tuck in (a narrower neck opening) and move forward (the chin bar projects)
        secs = [dict(z=0.0, a=a0 * 0.89, b=b0 * 0.80, n=2.3, cx=L * 0.06, squash=0.30),
                dict(z=lower * 0.33, a=a0 * 0.955, b=b0 * 0.90, n=2.3, cx=L * 0.045, squash=0.24),
                dict(z=lower * 0.70, a=a0 * 0.995, b=b0 * 0.985, n=2.25, cx=L * 0.015, squash=0.16)]
        dome, tip = craft.dome_sections(L, W, H - lower, levels=8, crown_back=L * 0.045, squash_front=0.12, z0=lower,
                                        n_base=2.2, n_top=2.05)
        return secs + dome, tip

    def _grown(self, secs, tip, amount):
        """The outer form grown by amount (inflated sections: a near-offset that never fails)."""
        s2, t2 = craft.inflate(secs, amount, tip)
        return craft.section_body(s2, tip=t2, count=72)

    def build(self, v):
        L, W, H, t = v["length"], v["width"], v["height"], v["wall"]
        secs, tip = self._outer(v)
        outer, shell = craft.section_shell(secs, t, tip=tip, count=72)     # robust where an offset of a crown point fails
        void = outer - shell                                                # the inside of the helmet
        stages = [Stage("shell", shell)]

        # lower edge: low at the chin, up at the jaw, a dip at the nape, cut along Y through both walls
        xf, xb = L * 0.62, -L * 0.62
        edge = [(xf, 3), (L * 0.5, 4.5), (L * 0.38, 9), (L * 0.2, 34), (0, 40), (-L * 0.2, 30), (-L * 0.36, 20),
                (-L * 0.5, 30), (xb, 40), (xb, -20), (xf, -20)]
        cut = _prism_y(edge)
        body = shell - cut
        stages.append(Stage("lower_edge", body))

        # eye port: a soft rectangle seen from the front, cut through the front half only
        zc = H * 0.555
        port = Plane.YZ.offset(L * 0.05) * craft.superellipse_face(v["port_w"] / 2, v["port_h"] / 2, 3.4,
                                                                     center=(0, zc), count=72)
        port_cut = extrude(port, L)
        body = body - port_cut
        port_edges = [e for e in body.edges() if e.center().X > L * 0.15 and abs(e.center().Z - zc) < v["port_h"] / 2 + 6
                      and abs(e.center().Y) < v["port_w"] / 2 + 6]
        body = craft.safe_fillet(body, port_edges, min(1.4, t * 0.4))
        stages.append(Stage("eye_port", body))

        # crown scoops: two pads that follow the crown, each with a slot through the shell
        grown = self._grown(secs, tip, 4.0)
        for sy in (-1, 1):
            foot = Pos(L * 0.16, sy * W * 0.13, H * 0.6) * extrude(craft.superellipse_face(34, 12, 3.0, rotate=sy * 6), H)
            pad = (grown & foot) - void
            body = body + pad
            slot = Pos(L * 0.17, sy * W * 0.13, H * 0.6) * Rot(0, 0, sy * 6) * extrude(SlotOverall(40, 5.5), H)
            body = body - slot
        stages.append(Stage("crown_scoops", body))

        # rear spoiler: a band that wraps the back of the head, 6 mm proud, its lower edge a crisp lip over three
        # exhaust slots. The footprint is a soft rectangle seen from behind, extruded forward through the back half.
        zs = H * 0.66
        band = Plane.YZ.offset(-L) * craft.superellipse_face(W * 0.30, 20, 4.0, center=(0, zs), count=72)
        foot = extrude(band, L * 0.78)                                   # from x = -L to x = -0.22 L
        spoiler = (self._grown(secs, tip, 6.0) & foot) - void
        body = body + spoiler
        for yy in (-W * 0.11, 0.0, W * 0.11):
            ex = Pos(-L * 0.62, yy, zs - 27) * Rot(0, 90, 0) * extrude(SlotOverall(22, 5.0), L * 0.3)
            body = body - ex
        stages.append(Stage("spoiler", body))

        # chin intake: a pad on the chin bar (the same language as the crown scoops) with three slots through it
        zc0 = H * 0.2
        face = Plane.YZ.offset(L * 0.25) * craft.superellipse_face(30, 17, 3.2, center=(0, zc0), count=64)
        chin = (self._grown(secs, tip, 3.0) & extrude(face, L)) - void
        body = body + chin
        for i, zz in enumerate((zc0 - 8, zc0, zc0 + 8)):
            slot = Pos(L * 0.3, 0, zz) * Rot(0, 90, 0) * Rot(0, 0, 90) * extrude(SlotOverall(40 - 6 * abs(i - 1), 3.6), L * 0.4)
            body = body - slot
        stages.append(Stage("chin_vents", body))

        # visor pivots: a raised disc on each side at the temple, with a recess for the visor plate and a screw hole
        for sy in (-1, 1):
            hit = outer.find_intersection_points(Axis((L * 0.12, 0, zc), (0, sy, 0)))
            y_s = max(abs(p[0].Y) for p in hit) if hit else W / 2
            # the disc starts inside the wall (never reaching the inside surface, so no faces coincide)
            sink = min(2.0, t * 0.6)
            boss = Pos(L * 0.12, sy * (y_s - sink), zc) * Rot(-90 * sy, 0, 0) * Cylinder(21, sink + 2.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
            body = body + boss
            body = body - Pos(L * 0.12, sy * (y_s + 2.2), zc) * Rot(-90 * sy, 0, 0) * Cylinder(15, 4)
            body = body - Pos(L * 0.12, sy * y_s, zc) * Rot(90, 0, 0) * Cylinder(2.6, 40)
        stages.append(Stage("pivots", body))
        return stages

    def mesh_texture(self, v):
        if v["texture"] <= 0:
            return []
        return [MeshTexture("weave", amplitude=v["texture"], scale=4.0, features=["shell"], facing="out",
                            edge_falloff=2.5)]

    def derived(self, v):
        return [{"key": "head_room", "label": "Inside length (head + liner)", "value": v["length"] - 2 * v["wall"],
                 "unit": "mm", "feature": "shell", "formula": "length - 2 x wall", "interface": True}]
