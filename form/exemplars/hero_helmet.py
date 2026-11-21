"""Original hero helmet in separate parts: a full-face shell sized from a head and fitted as one B-spline skin, a
magnetic faceplate that rests on a lip, two lenses that clip in behind it on magnets, a crest, ear pods, a chin
grille and a hex panel texture. An original Form Studio design: it imitates no comic, film or game character.
Form Studio exemplar design (a 3D model and prop, not protective equipment).
"""

from build123d import Compound, Plane, Pos, extrude, offset

from form import craft
from form.craft import MeshTexture, subd
from form.recipes.base import Assembly, Feature, Hardware, Mate, Param, Part, Recipe, RecipeError, Stage

META = {
    "title": "Original hero helmet: magnetic faceplate, two lenses",
    "category": "helmet",
    "product_class": "helmet_fullface",
    "tags": ["helmet", "full-face", "full face", "hero", "original", "prop", "cosplay", "costume", "wearable", "head",
             "faceplate", "face plate", "magnetic", "magnets", "magnet", "lens", "lenses", "eyes", "separate parts",
             "parts", "multi-part", "assembly", "split", "lip", "texture", "textured", "hex", "hexagon", "panels",
             "crest", "skin", "b-spline", "nurbs", "shell"],
    "techniques": ["craft.skin_from_sections (the helmet_fullface section stack fitted as one B-spline grid, with "
                   "its deviation measured)", "Skin.shell (three faces: outside, inside, rim)",
                   "Skin.band (crest and ear pods as true offsets of the skin, no shared faces)",
                   "craft.split (faceplate out of the shell, resting on a lip, gap all round)",
                   "Split.magnets (coaxial pocket pairs from the MAGNETS stock table, 0.6 mm floor)",
                   "craft.lens (lenses as their own parts from the inner offset skin)",
                   "craft.magnet_pair (lens magnets)", "craft.parts (separate parts with a measured clearance)",
                   "craft.part_list for assembly()", "MeshTexture hex panels outside only"],
    "lessons": [
        "Fit the skin once, then offset it: craft.skin_from_sections turns helmet_fullface's 20 sections into one "
        "B-spline grid (its deviation from the sections is measured and reported), and every other surface (the "
        "inside, the crest, the ledge, the lenses) is that grid offset along its normal. The shell is three faces, "
        "so each boolean after it takes a fraction of a second.",
        "Separate parts are never fused: craft.parts(shell=..., faceplate=..., lens_l=..., lens_r=...) returns them "
        "as one result and measures every pair against the clearance. fuse(a, b, max_solids=2, min_solids=2) fails "
        "the moment two parts touch.",
        "A removable panel in a curved shell rests on a lip: craft.split cuts the opening, leaves a ledge at the "
        "bottom of the wall reaching under the panel, and makes the panel the outer part of the wall over the ledge, "
        "with the same gap everywhere.",
        "Magnets come from stock (MAGNETS: 6x2, 6x3, 8x3, 10x3 mm) with a named fit (press, glue, printed); every "
        "pocket leaves 0.6 mm behind the magnet. Each pair is built from one point and one axis, so the two pockets "
        "line up by construction. The pull force is unknown until a datasheet value is given.",
        "Count the depth before choosing a magnet: the faceplate's flange over the ledge is wall - ledge - gap thick "
        "and must hold the pocket plus the floor. The body's side is too thin, so a boss grows under the ledge.",
        "Lenses are their own parts that follow the inside: the skin offset by the faceplate's wall plus the gap, a "
        "few mm thick, clipped to the eye outline grown by a rim that carries the lens magnets.",
        "Design an original character: pick the shapes yourself (here pill-shaped lenses tilted up, a centre crest, "
        "round ear pods, a hex panel texture) and never copy a known hero's mask, colours or emblem.",
    ],
}

STOCKS = list(craft.MAGNETS)                       # 0: 6x2, 1: 6x3, 2: 8x3, 3: 10x3
FITS = list(craft.MAGNET_FITS)                     # 0: press, 1: glue, 2: printed


def _front_x(F, y, z):
    """x of the helmet's front surface at (y, z), from its sections (numbers only, no kernel)."""
    import numpy as np
    secs = F["sections"]
    k = max(0, min(len(secs) - 2, max(i for i, s in enumerate(secs) if s["z"] <= z)))
    a, b = secs[k], secs[k + 1]
    w = (z - a["z"]) / (b["z"] - a["z"])
    s = {key: a[key] + w * (b[key] - a[key]) for key in ("a", "b", "n", "cx", "cy", "squash")}
    th = np.linspace(-1.5, 1.5, 3001)
    P = subd._section_points({**s, "z": z}, th)
    return float(P[np.argmin(np.abs(P[:, 1] - y)), 0])


def _prism_y(points):
    """A smooth (x, z) outline extruded through the whole width."""
    return extrude(craft.spline_profile(points, plane=Plane.XZ), 400, both=True)


class Design(Recipe):
    title, summary = "Original hero helmet", ("Full-face hero helmet in four parts: a B-spline skin shell with a crest, "
                                              "ear pods and a chin grille, a magnetic faceplate on a lip, two lenses "
                                              "on magnets behind it, and a hex panel texture.")
    solids = 4
    photo_color = "#2e3238"
    params = [
        Param("head", "Head circumference", 570, 520, 620, 10, "mm", "brief", "shell",
              "EN 960 headform sizes: E 540, J 570, M 600, O 620."),
        Param("wall", "Shell wall", 4.2, 3.4, 6.0, 0.1, "mm", "form", "shell",
              "The faceplate's flange (wall - ledge - gap) must hold a magnet pocket plus 0.6 mm."),
        Param("gap", "Part gap", 0.2, 0.1, 0.6, 0.05, "mm", "interface", "faceplate",
              "Clearance between the faceplate, the shell and the lenses."),
        Param("lip", "Faceplate lip", 14.0, 10.0, 24.0, 0.5, "mm", "interface", "faceplate",
              "How far the ledge reaches under the faceplate."),
        Param("ledge", "Ledge thickness", 1.0, 0.6, 2.0, 0.1, "mm", "interface", "faceplate"),
        Param("magnet", "Magnet stock", 0, 0, 3, 1, "", "interface", "magnets",
              "0 = 6x2, 1 = 6x3, 2 = 8x3, 3 = 10x3 mm discs (craft.MAGNETS)."),
        Param("fit", "Magnet fit", 1, 0, 2, 1, "", "interface", "magnets", "0 = press, 1 = glue, 2 = printed in."),
        Param("lens_t", "Lens thickness", 3.0, 2.4, 5.0, 0.1, "mm", "form", "lenses",
              "Holds the lens magnet's pocket plus 0.6 mm."),
        Param("texture", "Hex relief", 0.35, 0.0, 0.8, 0.05, "mm", "form", "shell",
              "0 = smooth. A mesh texture: STL, GLB and renders; the STEP is the smooth skin."),
    ]
    features = [Feature("shell", "Skin shell", "structure"), Feature("lower_edge", "Lower edge", "structure"),
                Feature("crest", "Crest", "finish"), Feature("ear_pods", "Ear pods", "finish"),
                Feature("chin_vent", "Chin grille", "access"), Feature("faceplate", "Faceplate on a lip", "interface"),
                Feature("magnets", "Faceplate magnets", "interface"), Feature("eyes", "Eye openings", "access"),
                Feature("lenses", "Lenses", "structure"), Feature("lens_magnets", "Lens magnets", "interface")]

    def _magnet(self, v):
        return craft.magnet(STOCKS[int(round(v["magnet"]))], FITS[int(round(v["fit"]))])

    def constraints(self, v):
        m = self._magnet(v)
        need = m["pocket_depth"] + m["floor"]
        if v["wall"] - v["ledge"] - v["gap"] < need + 0.1:
            return [RecipeError(f"The faceplate flange ({v['wall'] - v['ledge'] - v['gap']:.2f} mm) cannot hold a "
                                f"{m['stock']} pocket and its 0.6 mm floor ({need:.2f} mm)", "magnets",
                                "Use a thicker wall, a thinner ledge or a thinner magnet.", ["wall", "ledge", "magnet"])]
        if v["lens_t"] < need:
            return [RecipeError(f"The lens ({v['lens_t']:g} mm) cannot hold a {m['stock']} pocket and its floor",
                                "lenses", "Make the lens thicker or use a thinner magnet.", ["lens_t", "magnet"])]
        return []

    def form(self, v):
        F = craft.helmet_fullface(v["head"], chin=1.15)
        hl, H, ze = F["L"] / 2, F["H"], F["z_eye"]
        zb, zt = ze - 0.16 * H, ze + 0.13 * H + 24
        # the faceplate in side view: from the brow down past the cheeks, back to a third of the way to the ears
        F["plate_side"] = [(hl * 1.4, zb), (hl * 0.95, zb - 3), (hl * 0.62, zb + 2), (hl * 0.42, zb + 14),
                           (hl * 0.33, (zb + zt) / 2 - 4), (hl * 0.38, zt - 16), (hl * 0.58, zt - 2),
                           (hl * 0.9, zt + 4), (hl * 1.4, zt + 6)]
        # the eyes in front view: pill-shaped, tilted up toward the temples
        eye = []
        for sy in (1, -1):
            pts = craft.superellipse(35, 15, 3.8, count=48, rotate=sy * 12)
            eye.append([(sy * 49 + x, ze + 4 + y) for x, y in pts])
        F["eyes"] = eye
        F["plate_z"] = (zb, zt)
        return F

    def build(self, v):
        F = self.form(v)
        L, W, H, t, g = F["L"], F["W"], F["H"], v["wall"], v["gap"]
        hl, ze = L / 2, F["z_eye"]
        skin = craft.skin_from_sections(F["sections"], F["tip"], n=22, label="helmet skin")
        self._dev = skin.deviation
        # --- snippet: shell from one fitted skin
        body = skin.shell(t)                                    # outside, inside, rim: three faces
        # --- end snippet
        stages = [Stage("shell", body)]

        body = craft.cut(body, _prism_y(F["edge"]))             # the lower edge, side view
        stages.append(Stage("lower_edge", body))

        # --- snippet: crest and ear pods as offsets of the skin
        top = craft.superellipse_face(hl * 0.78, 10, 3.0, center=(-hl * 0.32, 0))
        crest = skin.band(4.5, Pos(0, 0, H * 0.42) * extrude(top, H), depth=t * 0.5)
        body = craft.fuse(body, crest)
        stages.append(Stage("crest", body))
        px, pz = -hl * 0.08, ze + 8
        pods = [Pos(px, 0, pz) * extrude(craft.superellipse_face(28, 30, 2.0, plane=Plane.XZ), W, both=True)]
        caps = [Pos(px, 0, pz) * extrude(craft.superellipse_face(15, 16, 2.0, plane=Plane.XZ), W, both=True)]
        body = craft.fuse(body, skin.band(4.0, pods, depth=t * 0.5))
        body = craft.fuse(body, skin.band(6.5, caps, depth=t * 0.4))
        # --- end snippet
        stages.append(Stage("ear_pods", body))

        zc = 0.17 * H
        body = craft.cut(body, craft.slot_grille((hl * 1.02, 0, zc), (1, 0, 0), count=4, length=56, width=4.0,
                                                 pitch=8.5, depth=hl * 0.7, taper=0.3, angle=90))
        stages.append(Stage("chin_vent", body))

        # --- snippet: a faceplate split out on a lip, held by coaxial magnet pairs
        side = F["plate_side"]
        plate_face = craft.spline_profile(side, plane=Plane.XZ)

        def region(grow):                                       # the faceplate grown by `grow` mm: a true 2D offset
            f = offset(plate_face, grow).faces()[0] if grow else plate_face
            return extrude(f, 400, both=True)
        sp = craft.split(body, skin, t, region, gap=g, lip=v["lip"], ledge=v["ledge"])
        # a raised frame round the faceplate's border: it stands 1.6 mm proud of the shell, so the plate reads as a
        # separate armoured piece
        sp.insert = craft.fuse(sp.insert, skin.band(1.6, region(-1.2) - region(-9.0), depth=1.0))
        stages.append(Stage("faceplate", Compound([sp.body, sp.insert])))
        m = self._magnet(v)
        mid = craft.grow_outline(side, -v["lip"] / 2)           # the lip's middle line in side view
        zb, zt = F["plate_z"]
        spots = []
        for zt_ in (zb + v["lip"] / 2, zt - v["lip"] / 2):
            x, z = min(mid, key=lambda p: abs(p[0] - hl * 0.6) + 3 * abs(p[1] - zt_))
            spots += [((x, 0, z), (0, sy, 0)) for sy in (1, -1)]
        sp.magnets(spots, stock=m["stock"], fit=m["fit"])
        # --- end snippet
        self._pairs = list(sp.pairs)
        stages.append(Stage("magnets", Compound([sp.body, sp.insert])))

        eye_cut = [Pos(0, 0, 0) * extrude(craft.polygon_profile(e, plane=Plane.YZ), L) for e in F["eyes"]]
        plate = craft.cut(sp.insert, eye_cut[0] + eye_cut[1])
        stages.append(Stage("eyes", Compound([sp.body, plate])))

        # --- snippet: lenses as their own parts from the inner offset skin, on magnets
        rim = 9.0
        lenses = []
        for e in F["eyes"]:
            win = extrude(craft.spline_profile(craft.grow_outline(e, rim), plane=Plane.YZ), L)
            lenses.append(craft.lens(skin, win, depth=t + g, thickness=v["lens_t"]).solids()[0])
        stages.append(Stage("lenses", Compound([sp.body, plate, *lenses])))
        for k, e in enumerate(F["eyes"]):
            ring = craft.grow_outline(e, rim / 2)
            for y, z in (max(ring, key=lambda p: abs(p[0])), min(ring, key=lambda p: abs(p[0]))):
                at, nrm = skin.ray((0, y, z), (1, 0, 0), -t)            # the faceplate's inside
                pr = craft.magnet_pair(at, [-c for c in nrm], m["stock"], m["fit"], gap=g, room_a=t,
                                       room_b=v["lens_t"])
                plate = craft.cut(plate, pr.pocket_a())
                lenses[k] = craft.cut(lenses[k], pr.pocket_b())
                self._pairs.append(pr)
        for pr, k in zip(self._pairs[4:], (0, 0, 1, 1)):                 # measured on the built parts
            for side, part in (("a", plate), ("b", lenses[k])):
                if pr.floor(part, side) < craft.MAGNET_FLOOR - 0.02:
                    raise RecipeError("A lens magnet pocket leaves less than 0.6 mm behind it", "lens_magnets",
                                      "Use a thinner magnet or a thicker lens.", ["magnet", "lens_t"])
        out = craft.parts(shell=sp.body, faceplate=plate, lens_l=lenses[0], lens_r=lenses[1], clearance=0.15)
        # --- end snippet
        stages.append(Stage("lens_magnets", out))
        return stages

    def assembly(self, v):
        """Parts found by a point inside each (no solid counting); pure numbers, no kernel needed."""
        F = self.form(v)
        t, g, ze = v["wall"], v["gap"], F["z_eye"]
        tip = F["tip"]
        m = self._magnet(v)
        lens_x = _front_x(F, 49.0, ze + 4) - (t + g + v["lens_t"] / 2) * 1.06
        parts = [Part("shell", "Shell", (tip[0], 0.0, tip[2] - t / 2), note="Glue the shell's four magnets into the "
                      "lip, all with the same pole out."),
                 Part("faceplate", "Faceplate", (_front_x(F, 0.0, ze + 4) - t / 2, 0.0, ze + 4), explode=(70, 0, 0),
                      note="Glue the faceplate's magnets in (opposite pole out), then set it on the lip."),
                 Part("lens_l", "Left lens", (lens_x, 49.0, ze + 4), explode=(35, 0, 0), attach="faceplate",
                      note="Glue the lens magnets in; the left lens clicks onto the faceplate from behind."),
                 Part("lens_r", "Right lens", (lens_x, -49.0, ze + 4), explode=(35, 0, 0), attach="faceplate",
                      note="The right lens clicks onto the faceplate from behind.")]
        return Assembly(parts=parts,
                        mates=[Mate("shell", "faceplate", "contact", g), Mate("faceplate", "lens_l", "contact", g),
                               Mate("faceplate", "lens_r", "contact", g)],
                        hardware=[Hardware(f"{m['stock']} mm disc magnet", f"Ø{m['d']:g} x {m['t']:g} mm", 16,
                                           "craft.MAGNETS (nominal stock size)",
                                           f"{m['fit']} fit; pull force unknown (no datasheet value given)")])

    def mesh_texture(self, v):
        if v["texture"] <= 0:
            return []
        return [MeshTexture("hex", amplitude=v["texture"], scale=9.0, groove=0.14,
                            features=["shell", "lower_edge", "crest"], facing="out", edge_falloff=2.0)]

    def appearance(self, v):
        return [{"features": ["lenses", "lens_magnets"], "finish": "smoke", "color": "#2f6f86"},
                {"features": ["faceplate", "magnets", "eyes"], "finish": "metal", "color": "#b9bdc3"},
                {"features": ["crest", "ear_pods"], "finish": "gloss", "color": "#d0632a"},
                {"features": ["shell", "lower_edge", "chin_vent"], "finish": "matte", "color": "#2e3238"}]

    def derived(self, v):
        F = craft.helmet_fullface(v["head"], chin=1.15)
        m = self._magnet(v)
        out = [{"key": "shell_length", "label": "Shell length", "value": F["L"], "unit": "mm", "feature": "shell",
                "formula": "head length + 2 x (comfort + EPS + shell)", "interface": False},
               {"key": "pocket_d", "label": "Magnet pocket diameter", "value": m["pocket_d"], "unit": "mm",
                "feature": "magnets", "formula": f"{m['stock']} magnet + 2 x {m['fit']} clearance", "interface": True},
               {"key": "pocket_depth", "label": "Magnet pocket depth", "value": m["pocket_depth"], "unit": "mm",
                "feature": "magnets", "formula": "magnet thickness + depth clearance; 0.6 mm floor behind",
                "interface": True},
               {"key": "flange", "label": "Faceplate flange", "value": round(v["wall"] - v["ledge"] - v["gap"], 2),
                "unit": "mm", "feature": "faceplate", "formula": "wall - ledge - gap", "interface": True},
               {"key": "pull", "label": "Magnet pull force", "value": "unknown", "unit": "",
                "feature": "magnets", "formula": "no datasheet value given", "interface": False}]
        dev = getattr(self, "_dev", None)
        if dev:
            out.append({"key": "skin_deviation", "label": "Skin fit deviation (max)", "value": dev["max_mm"],
                        "unit": "mm", "feature": "shell", "formula": "measured: section points to the fitted skin",
                        "interface": False})
        return out
