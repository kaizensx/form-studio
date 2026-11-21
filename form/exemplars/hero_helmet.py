"""Original hero helmet in separate parts, built one feature at a time: a full-face shell fitted as one B-spline skin,
a magnetic faceplate that rests on a lip, two pill lenses that clip in behind it on magnets, a stacked crest, raked ear
pods, a panel line round the nape, a chin grille and a hex panel texture. An original Form Studio design: it imitates
no comic, film or game character. Form Studio exemplar design (a 3D model and prop, not protective equipment).
"""

import math

from build123d import Circle, Compound, Plane, Pos, extrude, offset

from form import craft
from form.craft import MeshTexture, subd
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Assembly, Hardware, Mate, Param, Part, RecipeError

META = {
    "title": "Original hero helmet: magnetic faceplate, two lenses",
    "category": "helmet",
    "product_class": "helmet_fullface",
    "tags": ["helmet", "full-face", "full face", "hero", "original", "prop", "cosplay", "costume", "wearable", "head",
             "faceplate", "face plate", "magnetic", "magnets", "magnet", "lens", "lenses", "eyes", "separate parts",
             "parts", "multi-part", "assembly", "split", "lip", "texture", "textured", "hex", "hexagon", "panels",
             "crest", "skin", "b-spline", "nurbs", "shell", "feature", "features", "skeleton first"],
    "techniques": ["FeatureDesign (the skin fitted once in setup(), one @feature per feature, the skeleton first)",
                   "craft.skin_from_sections (the helmet_fullface section stack fitted as one B-spline grid, with "
                   "its deviation measured)", "Skin.shell (three faces: outside, inside, rim)",
                   "Skin.band (stacked crest, raked ear pods, brow ridge, eye bezels: true offsets of the skin)",
                   "Skin.layer (a panel line groove and a lens seat as offsets of the skin)",
                   "craft.split (faceplate out of the shell, resting on a lip, gap all round)",
                   "craft.magnet_pair (coaxial pocket pairs from the MAGNETS stock table, 0.6 mm floor, a boss "
                   "under the ledge)", "craft.lens (lenses as their own parts from the inner offset skin)",
                   "craft.parts (separate parts with a measured clearance)", "MeshTexture hex panels outside only"],
    "lessons": [
        "Skeleton first: the shell is the first feature and builds alone; every other feature takes the body so far "
        "and returns it changed. The skin is fitted once in setup() and read as self.ctx, so no feature refits it.",
        "Features talk only through the body: once the faceplate is split out the body is a Compound of separate "
        "solids, and each later feature finds its parts in it (by size, then by side), never in state on self.",
        "Fit the skin once, then offset it: craft.skin_from_sections turns helmet_fullface's 20 sections into one "
        "B-spline grid (its deviation from the sections is measured and reported), and every other surface (the "
        "inside, the crest, the ledge, the lens seat, the lenses) is that grid offset along its normal.",
        "Separate parts are never fused: craft.parts(shell=..., faceplate=..., lens_l=..., lens_r=...) returns them "
        "as one result and measures every pair against the clearance.",
        "A removable panel in a curved shell rests on a lip: craft.split cuts the opening, leaves a ledge at the "
        "bottom of the wall reaching under the panel, and makes the panel the outer part of the wall over the ledge.",
        "Magnets come from stock (MAGNETS: 6x2, 6x3, 8x3, 10x3 mm) with a named fit; every pocket leaves 0.6 mm "
        "behind the magnet. Each pair is built from one point and one axis, so the two pockets line up by "
        "construction; the pairs are a method of their own (magnet_pairs), so a feature and a test rebuild the same "
        "pairs from the values.",
        "Give a pocket more than its floor where it shows: the lens magnets sit in a 1 mm seat grown inside the "
        "faceplate round each eye, so about 3 mm of plate covers each pocket, not 2.",
        "Rhythm beats ornament: one thin frame, one brow ridge, one bezel per eye, a crest of two stacked bands with "
        "pointed ends, raked pods and one panel line that runs from the pods round the nape.",
        "Design an original character: pick the shapes yourself (here rounded pill lenses tilted up, a stacked "
        "crest, raked ear pods, a hex panel texture) and never copy a known hero's mask, colours or emblem.",
    ],
}

STOCKS = list(craft.MAGNETS)                       # 0: 6x2, 1: 6x3, 2: 8x3, 3: 10x3
FITS = list(craft.MAGNET_FITS)                     # 0: press, 1: glue, 2: printed
CHIN = 1.28                                        # how far the chin bar projects (helmet_fullface)
EYE = (46.0, 18.0, 2.6, 16.0, 54.0)                # pill lens: half length, half height, exponent, tilt (deg), centre y
SEAT = 1.0                                         # the lens seat grown inside the faceplate round each eye (mm)
RIM = 6.0                                          # the lens reaches this far past the eye opening (mm)


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


def _prism_x(face, length):
    """A (y, z) face extruded forward from x = 0."""
    return extrude(face, length)


def _ribbon(center, width):
    """A closed (x, z) outline of a ribbon `width` mm wide along a centre line (a panel line, side view)."""
    left, right = [], []
    for i, (x, z) in enumerate(center):
        a = center[max(0, i - 1)]
        b = center[min(len(center) - 1, i + 1)]
        dx, dz = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dz) or 1.0
        nx, nz = -dz / n * width / 2, dx / n * width / 2
        left.append((x + nx, z + nz))
        right.append((x - nx, z - nz))
    return left + right[::-1]


def _split_parts(body):
    """The parts of the body so far, by size then side: {"shell", "faceplate", "lens_l", "lens_r"} (those present)."""
    sol = sorted(body.solids(), key=lambda s: -s.volume)
    out = dict(zip(("shell", "faceplate"), sol[:2]))
    lenses = sorted(sol[2:], key=lambda s: -s.center().Y)              # lens_l on +Y, lens_r on -Y
    out.update(zip(("lens_l", "lens_r"), lenses))
    return out


class Design(FeatureDesign):
    title, summary = "Original hero helmet", ("Full-face hero helmet in four parts: a B-spline skin shell with a "
                                              "stacked crest, raked ear pods, a panel line and a chin grille, a "
                                              "magnetic faceplate on a lip with a brow ridge and eye bezels, two pill "
                                              "lenses on magnets behind it, and a hex panel texture.")
    solids = 4
    photo_color = "#262a30"
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
        Param("texture", "Hex relief", 0.9, 0.0, 1.2, 0.05, "mm", "form", "shell",
              "0 = smooth. A mesh texture: STL, GLB and renders; the STEP is the smooth skin."),
    ]

    def _magnet(self, v):
        return craft.magnet(STOCKS[int(round(v["magnet"]))], FITS[int(round(v["fit"]))])

    def constraints(self, v):
        m = self._magnet(v)
        need = m["pocket_depth"] + m["floor"]
        if v["wall"] - v["ledge"] - v["gap"] < need + 0.1:
            return [craft.RecipeError(f"The faceplate flange ({v['wall'] - v['ledge'] - v['gap']:.2f} mm) cannot "
                                      f"hold a {m['stock']} pocket and its 0.6 mm floor ({need:.2f} mm)", "magnets",
                                      "Use a thicker wall, a thinner ledge or a thinner magnet.",
                                      ["wall", "ledge", "magnet"])]
        if v["lens_t"] < need:
            return [craft.RecipeError(f"The lens ({v['lens_t']:g} mm) cannot hold a {m['stock']} pocket and its "
                                      "floor", "lenses", "Make the lens thicker or use a thinner magnet.",
                                      ["lens_t", "magnet"])]
        return []

    def form(self, v):
        """The helmet's numbers: sections, outlines and spots (no kernel)."""
        F = craft.helmet_fullface(v["head"], chin=CHIN)
        hl, H, ze = F["L"] / 2, F["H"], F["z_eye"]
        # lower edge, side view: lowest under the chin, then raked up all the way to the nape
        F["edge"] = [(hl * 1.4, -30.0), (hl * 1.4, 0.035 * H), (hl * 0.88, 0.02 * H), (hl * 0.62, 0.065 * H),
                     (hl * 0.32, 0.14 * H), (0.0, 0.18 * H), (-hl * 0.4, 0.205 * H), (-hl * 0.75, 0.235 * H),
                     (-hl * 1.4, 0.27 * H), (-hl * 1.4, -30.0)]
        zb, zt = ze - 0.16 * H, ze + 0.13 * H + 24
        # the faceplate in side view: from the brow down past the cheeks, wrapping back toward the temples
        F["plate_side"] = [(hl * 1.4, zb), (hl * 0.95, zb - 3), (hl * 0.62, zb + 3), (hl * 0.36, zb + 14),
                           (hl * 0.2, (zb + zt) / 2 - 6), (hl * 0.26, zt - 18), (hl * 0.5, zt - 3),
                           (hl * 0.9, zt + 4), (hl * 1.4, zt + 6)]
        F["plate_z"] = (zb, zt)
        a, b, n, tilt, cy = EYE
        F["eye_c"] = [(sy * cy, ze + 4) for sy in (1, -1)]
        F["eyes"] = [[(c[0] + x, c[1] + y) for x, y in craft.superellipse(a, b, n, count=56, rotate=sy * tilt)]
                     for sy, c in zip((1, -1), F["eye_c"])]
        # two lens magnets per eye, point-symmetric about its centre: over the inner corner and under the outer one
        F["lens_spots"] = []
        for sy, c in zip((1, -1), F["eye_c"]):
            r = math.radians(sy * tilt)
            edge = b * (1 - 0.72 ** n) ** (1 / n)                         # the eye's edge over the spot
            for lx, lz in ((-a * 0.72, edge + 5.5), (a * 0.72, -(edge + 5.5))):
                lx *= sy
                F["lens_spots"].append((c[0] + lx * math.cos(r) - lz * math.sin(r),
                                        c[1] + lx * math.sin(r) + lz * math.cos(r)))
        # the panel line, side view: on from the ear pods' axis, down and back round the nape
        px, pz = -hl * 0.24, ze + 6
        k = math.tan(math.radians(25))
        F["pod"] = (px, pz)
        F["panel"] = [(px - d, pz - d * k + 1.5 * ((d - 40) / 30) ** 2) for d in (36 + 134 * i / 47 for i in range(48))]
        return F

    def setup(self, v):
        """Shared by every feature (self.ctx): the form, the fitted skin and the faceplate's outline."""
        F = self.form(v)
        skin = craft.skin_from_sections(F["sections"], F["tip"], n=22, label="helmet skin")
        plate_face = craft.spline_profile(F["plate_side"], plane=Plane.XZ)

        def region(grow):                       # the faceplate grown by `grow` mm: a true 2D offset, through the width
            f = offset(plate_face, grow).faces()[0] if grow else plate_face
            return extrude(f, 400, both=True)
        return {"F": F, "skin": skin, "region": region, "m": self._magnet(v)}

    def magnet_pairs(self, v):
        """The eight magnet pairs, from the values alone: four shell-faceplate pairs across the ledge (pocket a in
        the shell, b in the faceplate), then two per lens (a in the faceplate's seat, b in the lens)."""
        c = self.ctx if getattr(self, "_form_values", None) is v else self.setup(v)
        F, skin, m = c["F"], c["skin"], c["m"]
        t, g, hl = v["wall"], v["gap"], F["L"] / 2
        contact = -t + v["ledge"]
        mid = craft.grow_outline(F["plate_side"], -v["lip"] / 2)        # the lip's middle line in side view
        zb, zt = F["plate_z"]
        pairs = []
        for z0 in (zb + v["lip"] / 2, zt - v["lip"] / 2):
            x, z = min(mid, key=lambda p: abs(p[0] - hl * 0.6) + 3 * abs(p[1] - z0))
            for sy in (1, -1):
                p, nrm = skin.ray((x, 0, z), (0, sy, 0), contact)
                pairs.append(craft.magnet_pair(p, nrm, m["stock"], m["fit"], gap=g, room_b=t - v["ledge"] - g))
        for y, z in F["lens_spots"]:
            at, nrm = skin.ray((0, y, z), (1, 0, 0), -(t + SEAT))            # the seat's inside
            pairs.append(craft.magnet_pair(at, [-q for q in nrm], m["stock"], m["fit"], gap=g, room_a=t + SEAT,
                                           room_b=v["lens_t"]))
        return pairs

    def _lens_window(self, k):
        """Lens k's outline (the eye grown by RIM, with a round tab over each of its magnets), as a prism along X."""
        F = self.ctx["F"]
        win = _prism_x(craft.spline_profile(craft.grow_outline(F["eyes"][k], RIM), plane=Plane.YZ), F["L"])
        r = self.ctx["m"]["pocket_d"] / 2 + 2.0
        for y, z in F["lens_spots"][2 * k:2 * k + 2]:
            win = craft.fuse(win, _prism_x(Plane.YZ * Pos(y, z) * Circle(r), F["L"]))
        return win

    # ---- the skeleton --------------------------------------------------------------------------------------------

    @feature("Skin shell", role="structure")
    def shell(self, v, body):
        # --- snippet: shell from one fitted skin (fitted once in setup)
        return self.ctx["skin"].shell(v["wall"])                     # outside, inside, rim: three faces
        # --- end snippet

    @feature("Lower edge", role="structure")
    def lower_edge(self, v, body):
        return craft.cut(body, _prism_y(self.ctx["F"]["edge"]))      # raked up to the nape, side view

    # ---- form on the shell ---------------------------------------------------------------------------------------

    @feature("Crest", role="finish")
    def crest(self, v, body):
        # --- snippet: a crest of two stacked bands with pointed ends, offsets of the skin
        F, skin, t = self.ctx["F"], self.ctx["skin"], v["wall"]
        hl, H = F["L"] / 2, F["H"]
        base = craft.superellipse_face(hl * 0.72, 16, 1.7, center=(-hl * 0.36, 0))      # starts behind the brow
        ridge = craft.superellipse_face(hl * 0.6, 5, 1.7, center=(-hl * 0.4, 0))
        body = craft.fuse(body, skin.band(2.0, Pos(0, 0, H * 0.42) * extrude(base, H), depth=t * 0.5))
        return craft.fuse(body, skin.band(6.0, Pos(0, 0, H * 0.42) * extrude(ridge, H), depth=t * 0.5))
        # --- end snippet

    @feature("Ear pods", role="finish")
    def ear_pods(self, v, body):
        # --- snippet: swept-back ear pods, raked 25 degrees, the cap offset rearward
        F, skin, t = self.ctx["F"], self.ctx["skin"], v["wall"]
        (px, pz), W = F["pod"], F["W"]
        pod = extrude(craft.superellipse_face(38, 20, 2.6, plane=Plane.XZ, center=(px, pz),
                                                             rotate=25), W, both=True)
        cap = extrude(craft.superellipse_face(17, 10, 2.4, plane=Plane.XZ, center=(px - 9, pz - 4), rotate=25),
                      W, both=True)
        body = craft.fuse(body, skin.band(4.0, pod, depth=t * 0.5))
        return craft.fuse(body, skin.band(6.5, cap, depth=t * 0.4))
        # --- end snippet

    @feature("Panel line", role="finish")
    def panel_line(self, v, body):
        skin = self.ctx["skin"]                 # a groove from the pods round the nape: the skin layer 0.8 mm down
        rib = extrude(craft.polygon_profile(_ribbon(self.ctx["F"]["panel"], 1.6), plane=Plane.XZ), 400, both=True)
        return craft.cut(body, skin.layer(-0.8, 1.0) & rib)

    @feature("Chin grille", role="access")
    def chin_vent(self, v, body):
        F = self.ctx["F"]
        hl, H = F["L"] / 2, F["H"]
        return craft.cut(body, craft.slot_grille((hl * 1.02, 0, 0.16 * H), (1, 0, 0), count=5, length=40,
                                                 width=3.6, pitch=7.5, depth=hl * 0.7, taper=0.35, angle=90))

    # ---- the faceplate -------------------------------------------------------------------------------------------

    @feature("Faceplate on a lip", role="interface")
    def faceplate(self, v, body):
        # --- snippet: a faceplate split out on a lip, with a thin frame and one brow ridge
        skin, region, t = self.ctx["skin"], self.ctx["region"], v["wall"]
        zb, zt = self.ctx["F"]["plate_z"]
        sp = craft.split(body, skin, t, region, gap=v["gap"], lip=v["lip"], ledge=v["ledge"])
        # the plate's own face, 0.4 mm proud and 0.6 mm in from its edge: a crisp step at the joint, and a smooth
        # face of its own that the shell's texture does not cover
        plate = craft.fuse(sp.insert, skin.band(0.4, region(-0.6), depth=1.0))
        frame = skin.band(0.8, region(-1.2) - region(-4.2), depth=1.0)          # 0.8 mm proud, 3 mm wide
        brow = (region(-1.2) - Pos(0, 0, -9) * region(-1.2)) \
            & Pos(0, 0, zt - 30) * extrude(craft.superellipse_face(400, 400, 4, plane=Plane.XY), 100)
        plate = craft.fuse(craft.fuse(plate, frame), skin.band(3.0, brow, depth=1.0))
        return Compound([sp.body, plate])
        # --- end snippet

    @feature("Faceplate magnets", role="interface")
    def magnets(self, v, body):
        # --- snippet: coaxial magnet pairs across the ledge, a boss under the ledge carries the shell's pocket
        p = _split_parts(body)
        shell, plate = p["shell"], p["faceplate"]
        pairs = self.magnet_pairs(v)[:4]
        for pr in pairs:
            q = [a - b * 0.3 for a, b in zip(pr.at, pr._u())]
            if not shell.is_inside(_vec(q)):
                raise RecipeError("A faceplate magnet is not over the ledge", "magnets",
                                  "Aim the spot at the middle of the lip.", ["lip"])
        # a raised tab over the lower magnets: the flange there is wall - ledge - gap, so it covers the pocket
        x, z = pairs[0].at[0], pairs[0].at[2]           # one prism through the width covers both sides
        tab = extrude(craft.superellipse_face(9, 6, 2.6, plane=Plane.XZ, center=(x, z), rotate=8), 400, both=True)
        plate = craft.fuse(plate, self.ctx["skin"].band(1.6, tab, depth=1.0))
        # one boolean per kind of cut, not one per magnet: the parts are many faces by now
        shell = craft.fuse(shell, _union([pr.boss("a", start=0.6 * v["ledge"], wall=1.6) for pr in pairs]))
        shell = craft.cut(shell, _union([pr.pocket_a() for pr in pairs]))
        plate = craft.cut(plate, _union([pr.pocket_b() for pr in pairs]))
        _check_floors(pairs, shell, plate, "magnets")
        return Compound([shell, plate])
        # --- end snippet

    @feature("Eye openings", role="access")
    def eyes(self, v, body):
        # --- snippet: pill eyes in a raised bezel, the lenses' seat grown inside round them
        F, skin, region, t, g = self.ctx["F"], self.ctx["skin"], self.ctx["region"], v["wall"], v["gap"]
        p = _split_parts(body)
        plate = p["faceplate"]
        core = region(-(v["lip"] + g + 0.5))                     # the seat stays clear of the ledge
        bezels = [_prism_x(craft.spline_profile(craft.grow_outline(e, 4.5), plane=Plane.YZ), F["L"]) for e in F["eyes"]]
        plate = craft.fuse(plate, skin.band(1.2, bezels, depth=1.0))                # 1.2 mm proud, both eyes
        seat = skin.layer(-(t + SEAT), -t + 0.3) & (self._lens_window(0) + self._lens_window(1)) & core
        plate = craft.fuse(plate, seat)
        cut = [_prism_x(craft.spline_profile(e, plane=Plane.YZ), F["L"]) for e in F["eyes"]]
        plate = craft.cut(plate, cut[0] + cut[1])
        return Compound([p["shell"], plate])
        # --- end snippet

    # ---- the lenses ----------------------------------------------------------------------------------------------

    @feature("Lenses", role="structure")
    def lenses(self, v, body):
        # --- snippet: lenses as their own parts from the inner offset skin, under the seat
        skin, t, g = self.ctx["skin"], v["wall"], v["gap"]
        lenses = [craft.lens(skin, self._lens_window(k), depth=t + SEAT + g, thickness=v["lens_t"]).solids()[0]
                  for k in range(2)]
        p = _split_parts(body)
        return Compound([p["shell"], p["faceplate"], *lenses])
        # --- end snippet

    @feature("Lens magnets", role="interface")
    def lens_magnets(self, v, body):
        # --- snippet: lens magnets, then the separate parts measured against the clearance
        p = _split_parts(body)
        plate, lenses = p["faceplate"], [p["lens_l"], p["lens_r"]]
        pairs = self.magnet_pairs(v)[4:]
        plate = craft.cut(plate, _union([pr.pocket_a() for pr in pairs]))
        for k in range(2):
            lenses[k] = craft.cut(lenses[k], _union([pr.pocket_b() for pr in pairs[2 * k:2 * k + 2]]))
        for pr, k in zip(pairs, (0, 0, 1, 1)):
            _check_floors([pr], plate, lenses[k], "lens_magnets")
        return craft.parts(shell=p["shell"], faceplate=plate, lens_l=lenses[0], lens_r=lenses[1], clearance=0.15)
        # --- end snippet

    # ---- what the build does not make ----------------------------------------------------------------------------

    def assembly(self, v):
        """Parts found by a point inside each (no solid counting); pure numbers, no kernel needed."""
        F = self.form(v)
        t, g, ze = v["wall"], v["gap"], F["z_eye"]
        tip = F["tip"]
        m = self._magnet(v)
        ey = EYE[4]
        lens_x = _front_x(F, ey, ze + 4) - (t + SEAT + g + v["lens_t"] / 2) * 1.08
        parts = [Part("shell", "Shell", (tip[0], 0.0, tip[2] - t / 2), note="Glue the shell's four magnets into the "
                      "bosses under the lip, all with the same pole out."),
                 Part("faceplate", "Faceplate", (_front_x(F, 0.0, ze + 4) - t / 2, 0.0, ze + 4), explode=(70, 0, 0),
                      note="Glue the faceplate's magnets in (opposite pole out), then set it on the lip."),
                 Part("lens_l", "Left lens", (lens_x, ey, ze + 4), explode=(35, 0, 0), attach="faceplate",
                      note="Glue the lens magnets in; the left lens clicks into its seat from behind."),
                 Part("lens_r", "Right lens", (lens_x, -ey, ze + 4), explode=(35, 0, 0), attach="faceplate",
                      note="The right lens clicks into its seat from behind.")]
        return Assembly(parts=parts,
                        mates=[Mate("shell", "faceplate", "contact", g), Mate("faceplate", "lens_l", "contact", g),
                               Mate("faceplate", "lens_r", "contact", g)],
                        hardware=[Hardware(f"{m['stock']} mm disc magnet", f"Ø{m['d']:g} x {m['t']:g} mm", 16,
                                           "craft.MAGNETS (nominal stock size)",
                                           f"{m['fit']} fit; pull force unknown (no datasheet value given)")])

    def mesh_texture(self, v):
        if v["texture"] <= 0:
            return []
        return [MeshTexture("hex", amplitude=v["texture"], scale=18.0, groove=0.10,
                            features=["shell", "lower_edge"], facing="out", edge_falloff=10.0)]

    def appearance(self, v):
        return [{"features": ["lenses", "lens_magnets"], "finish": "smoke", "color": "#2f6f86"},
                {"features": ["faceplate", "magnets", "eyes"], "finish": "metal", "color": "#c3c7cc"},
                {"features": ["crest", "ear_pods"], "finish": "gloss", "color": "#d0632a"},
                {"features": ["shell", "lower_edge", "panel_line", "chin_vent"], "finish": "matte",
                 "color": "#262a30"}]

    def derived(self, v):
        F = craft.helmet_fullface(v["head"], chin=CHIN)
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
               {"key": "lens_cover", "label": "Plate over a lens magnet", "value": round(v["wall"] + SEAT -
                                                                                        m["pocket_depth"], 2),
                "unit": "mm", "feature": "lens_magnets", "formula": "wall + seat - pocket depth", "interface": False},
               {"key": "pull", "label": "Magnet pull force", "value": "unknown", "unit": "",
                "feature": "magnets", "formula": "no datasheet value given", "interface": False}]
        c = getattr(self, "_form_ctx", None)
        dev = c[1]["skin"].deviation if c and c[1] else None
        if dev:
            out.append({"key": "skin_deviation", "label": "Skin fit deviation (max)", "value": dev["max_mm"],
                        "unit": "mm", "feature": "shell", "formula": "measured: section points to the fitted skin",
                        "interface": False})
        return out


def _union(solids):
    """Disjoint cutters or bosses as one operand, so a part takes one boolean for all of them."""
    out = solids[0]
    for s in solids[1:]:
        out = out + s
    return out


def _vec(q):
    from build123d import Vector
    return Vector(*q)


def _check_floors(pairs, part_a, part_b, fid):
    """Every pocket keeps 0.6 mm behind it, measured on the built parts."""
    for pr in pairs:
        for side, part in (("a", part_a), ("b", part_b)):
            fl = pr.floor(part, side)
            if fl < craft.MAGNET_FLOOR - 0.02:
                raise RecipeError(f"A {pr.spec['stock']} magnet pocket leaves {fl:.2f} mm behind it (under 0.6 mm)",
                                  fid, "Use a thinner magnet, a thicker wall or a thicker lens.",
                                  ["magnet", "wall", "lens_t"])
