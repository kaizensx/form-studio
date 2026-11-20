"""Motorcycle helmet (bench reference, rebuilt in design evaluation 12 through Form Studio's tools: design_brief,
plan_design, design_examples, create_design, update_design, critique, render_photo). Full-face helmet in carbon twill: a shell sized from a head (EN 960 headform, ANSUR II proportions),
shaped in three views by guide curves, with an eye port cut in two views, a smoked visor on two pivots, rubber trim on
the lower edge and round the port, chin and brow intakes, crown scoops, a ducktail spoiler over two exhausts, and a
carbon twill on the outside. Form Studio exemplar design (a 3D model and form study, not a certified helmet).
"""

from build123d import Axis, Cylinder, Plane, Pos, Rot, extrude

from form import craft
from form.craft import MeshTexture
from form.recipes.base import Assembly, Feature, Param, Part, Recipe, RecipeError, Stage, hinge

def _prism_y(points):
    """A smooth (x, z) outline extruded through the whole width."""
    return extrude(craft.spline_profile(points, plane=Plane.XZ), 400, both=True)


def _shift(points, dz):
    return [(x, z + dz) for x, z in points]


class Design(Recipe):
    title, summary = "Carbon full-face helmet", ("Full-face helmet shell sized from a head: eye port, smoked visor on "
                                                  "pivots, rubber trim, chin and brow intakes, crown scoops, ducktail "
                                                  "spoiler and a carbon twill.")
    solids = 2
    photo_color = "#2a2c30"
    params = [
        Param("head", "Head circumference", 570, 500, 620, 10, "mm", "brief", "shell",
              "EN 960 headform sizes: A 500, E 540, J 570, M 600, O 620."),
        Param("cephalic", "Head breadth / length", 0.78, 0.72, 0.86, 0.01, "", "brief", "shell",
              "0.78 ANSUR II mean (long oval); 0.83+ a round head."),
        Param("wall", "Shell wall", 3.5, 2, 6, 0.1, "mm", "form", "shell"),
        Param("chin", "Chin bar projection", 1.25, 0.6, 1.4, 0.05, "", "form", "shell"),
        Param("visor_gap", "Visor gap", 2.0, 1.2, 3.5, 0.1, "mm", "interface", "visor"),
        Param("texture", "Twill depth", 0.06, 0, 0.6, 0.02, "mm", "form", "shell",
              "0 = smooth. Mesh texture; a clear-coated carbon shell is nearly smooth."),
    ]
    features = [Feature("shell", "Carbon shell", "structure"), Feature("lower_edge", "Lower edge", "structure"),
                Feature("eye_port", "Eye port", "access"), Feature("trim", "Rubber trim", "finish"),
                Feature("pivots", "Visor pivot plates", "interface"), Feature("chin_vent", "Chin intake", "access"),
                Feature("brow_vents", "Brow intakes", "access"), Feature("crown_scoops", "Crown scoops", "access"),
                Feature("spoiler", "Ducktail spoiler", "finish"), Feature("exhaust", "Rear exhausts", "access"),
                Feature("visor", "Smoked visor", "structure")]

    def constraints(self, v):
        if v["wall"] > 5 and v["head"] < 520:
            return [RecipeError("A 5 mm wall on the smallest shell leaves no room for the liner", "shell",
                                "Use a thinner wall.", ["wall"])]
        return []

    def form(self, v):
        return craft.helmet_fullface(v["head"], cephalic=v["cephalic"], chin=v["chin"])

    def build(self, v):
        F = self.form(v)
        L, W, H, t = F["L"], F["W"], F["H"], v["wall"]
        hl = L / 2
        secs, tip = F["sections"], F["tip"]
        outer = craft.checked_body(secs, tip, label="shell")
        inner = craft.inset_body(secs, t, tip=tip)
        body = craft.cut(outer, inner)
        stages = [Stage("shell", body)]

        # the lower edge: a side-profile cut through both walls, its lip rounded
        cut = _prism_y(F["edge"])
        body = craft.cut(body, cut)
        lip = [e for e in body.edges() if e.center().Z < 0.2 * H]
        body = craft.safe_fillet(body, lip, 1.4)
        stages.append(Stage("lower_edge", body))

        # the eye port, drawn in two views, cut through the front half only
        port = craft.two_view_cutter(F["port_side"], F["port_front"], x_range=(0, L))
        body = craft.cut(body, port)
        pb, pt = F["port_z"]
        rim = [e for e in body.edges() if e.center().X > 0 and pb - 12 < e.center().Z < pt + 12]
        body = craft.safe_fillet(body, rim, 1.2)
        stages.append(Stage("eye_port", body))

        # rubber trim: a 2 mm band along the lower edge and a 1.5 mm gasket round the port (it shows through the visor)
        edge_band = _prism_y(_shift(F["edge"], 11)) - cut
        trim = craft.surface_band(secs, tip, 2.0, edge_band, depth=t / 2)
        grown_port = craft.two_view_cutter(craft.grow_outline(F["port_side"], 7), craft.grow_outline(F["port_front"], 7),
                                           x_range=(0, L))
        trim = trim + craft.surface_band(secs, tip, 1.0, grown_port - port, depth=t / 2)
        body = craft.fuse(body, trim)
        stages.append(Stage("trim", body))

        # pivot plates: a raised disc each side where the visor turns
        px, pz = F["pivot"]
        disc = Pos(px, 0, pz) * Rot(90, 0, 0) * Cylinder(26, W + 40)
        # 1.3 mm: not the gasket's 1.0 (two bands on the same offset surface share faces where they meet)
        body = craft.fuse(body, craft.surface_band(secs, tip, 1.3, disc, depth=t / 2.5))
        stages.append(Stage("pivots", body))

        # chin intake: a pad on the chin bar with a lens-shaped grille of horizontal slots
        zc = 0.155 * H
        chin_reg = craft.two_view_cutter([(hl * 0.55, zc - 22), (hl * 1.3, zc - 26), (hl * 1.3, zc + 26),
                                          (hl * 0.55, zc + 18)],
                                         [(0, zc - 24), (34, zc - 18), (40, zc), (34, zc + 18), (0, zc + 23),
                                          (-34, zc + 18), (-40, zc), (-34, zc - 18)], x_range=(0, L),
                                         smooth=(False, True))
        body = craft.fuse(body, craft.surface_band(secs, tip, 3.0, chin_reg, depth=t / 2))
        body = craft.cut(body, craft.slot_grille((hl * 1.02, 0, zc), (1, 0, 0), count=4, length=58, width=4.2, pitch=9,
                                                 depth=hl * 0.7, taper=0.35, angle=90))
        stages.append(Stage("chin_vent", body))

        # brow intake: one slender pad above the port, centred, with three slots facing the wind
        zb = pt + 36
        oval = [(32 * x, zb + 7 * y) for x, y in craft.superellipse(1, 1, 3.0, count=16)]
        reg = craft.two_view_cutter([(0, zb - 9), (hl * 1.3, zb - 9), (hl * 1.3, zb + 9), (0, zb + 9)], oval,
                                    x_range=(0, L), smooth=(False, True))
        body = craft.fuse(body, craft.surface_band(secs, tip, 2.0, reg, depth=t / 2))
        body = craft.cut(body, craft.slot_grille((hl, 0, zb), (1, 0, 0.45), count=3, length=12, width=3.0, pitch=16,
                                                 depth=60, angle=0))
        stages.append(Stage("brow_vents", body))

        # crown scoops: two raised fins on top, each with a forward-facing intake slot
        feet = [Pos(L * 0.06, sy * W * 0.11, H * 0.5) * extrude(craft.superellipse_face(40, 11, 3.2, rotate=sy * 5), H)
                for sy in (-1, 1)]
        scoops = craft.surface_band(secs, tip, 5.5, feet[0] + feet[1], depth=t / 2)
        top = [e for e in scoops.edges() if e.center().Z > H * 0.82]          # soften the scoops' top edges
        body = craft.fuse(body, craft.safe_fillet(scoops, top, 1.6))
        slots = [craft.slot_grille((L * 0.17, sy * W * 0.11, H - 18), (0.55, 0, 1), count=1, length=20, width=5,
                                   pitch=8, depth=40, angle=90) for sy in (-1, 1)]
        body = craft.cut(body, slots[0] + slots[1])
        stages.append(Stage("crown_scoops", body))

        # ducktail spoiler: a crescent band over the back of the crown, its leading edge rounded into the shell and a
        # crisp trailing lip over the exhausts
        zs = H * 0.62
        cres = craft.spline_profile([(-hl * 0.20, zs + 60), (-hl * 0.70, zs + 42), (-hl * 1.3, zs + 10),
                                     (-hl * 1.3, zs - 12), (-hl * 0.85, zs + 8), (-hl * 0.45, zs + 38)], plane=Plane.XZ)
        reg = extrude(cres, W * 0.34, both=True)
        spoiler = craft.surface_band(secs, tip, 3.5, reg, depth=t / 2)
        spoiler = craft.safe_fillet(spoiler, [e for e in spoiler.edges() if e.center().X > -hl * 0.9], 1.5)
        body = craft.fuse(body, spoiler)
        stages.append(Stage("spoiler", body))

        # rear exhausts: two short grilles under the spoiler's lip
        g1, g2 = (craft.slot_grille((-hl, sy * W * 0.12, zs - 26), (-1, 0, 0), count=3, length=22, width=3.5,
                                    pitch=7.5, depth=60, angle=90 + sy * 8) for sy in (-1, 1))
        body = craft.cut(body, g1 + g2)
        stages.append(Stage("exhaust", body))

        # smoked visor: the shell's surface grown by the gap, 2.5 mm thick, clipped to its outline in two views
        g = v["visor_gap"]
        window = craft.two_view_cutter(F["visor_side"], [(-W, -50), (W, -50), (W, H + 50), (-W, H + 50)],
                                       x_range=(px - 40, L), smooth=(True, False))
        hi = craft.offset_body(secs, tip, g + 2.5)
        visor = (hi & (window + Pos(px, 0, pz) * Rot(90, 0, 0) * Cylinder(21, W + 40))) - craft.offset_body(secs, tip, g)
        visor = visor - Pos(px, 0, pz) * Rot(90, 0, 0) * Cylinder(5, W + 40)
        visor = craft.safe_fillet(visor, [e for e in visor.edges() if e.length > 25], 0.9)
        body = craft.fuse(body, visor, max_solids=2, min_solids=2)
        stages.append(Stage("visor", body))
        return stages

    def mesh_texture(self, v):
        if v["texture"] <= 0:
            return []
        return [MeshTexture("weave", amplitude=v["texture"], scale=3.0, features=["shell", "spoiler", "crown_scoops"],
                            facing="out", edge_falloff=2.0)]

    def appearance(self, v):
        return [{"features": ["visor"], "finish": "smoke", "color": "#2c333b"},
                {"features": ["trim"], "finish": "rubber", "color": "#151617"},
                {"features": ["chin_vent", "brow_vents", "exhaust", "pivots"], "finish": "matte", "color": "#1d1f22"},
                {"features": ["shell", "lower_edge", "eye_port", "crown_scoops", "spoiler"], "finish": "carbon",
                 "color": "#2a2c30"}]

    def derived(self, v):
        F = self.form(v)
        hd = F["head"]
        return [{"key": "shell_length", "label": "Shell length", "value": F["L"], "unit": "mm", "feature": "shell",
                 "formula": "head length + 2 x (comfort + EPS + shell)", "interface": False},
                {"key": "shell_width", "label": "Shell width", "value": F["W"], "unit": "mm", "feature": "shell",
                 "formula": "head breadth + 2 x (comfort + EPS + shell)", "interface": False},
                {"key": "head_length", "label": "Head length", "value": hd["length"], "unit": "mm", "feature": "shell",
                 "formula": hd["source"], "interface": True}]

    def assembly(self, v):
        F = self.form(v)
        px, pz = F["pivot"]
        return Assembly(parts=[Part("shell", "Shell", (0, 0, F["H"] * 0.5), note="The carbon shell."),
                               Part("visor", "Visor", (F["L"] / 2, 0, F["z_eye"]), explode=(60, 0, 0),
                                    note="Set the visor's discs over the pivot plates.")],
                        joints=[hinge("visor", (0, 1, 0), (px, 0, pz), (-35, 0), 8, parent="shell", id="visor_up",
                                      label="Visor")])
