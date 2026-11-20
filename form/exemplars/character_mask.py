"""Character mask with magnet eyes: a full-head cowl sculpted from a subdivision cage, with a raised web relief, two
eye lenses that click in from the inside on magnets, and a front/back split for printing that is held by magnets too.
A hybrid design: the skin is a sculpted surface (its brow, cheekbones, jaw and crown are handles you drag), the parts
that fit are exact CAD (eye openings from a constrained sketch, magnet pockets to the magnet's size plus clearance).
Form Studio exemplar design of its own (no character's likeness).
"""
import math
import os
import tempfile

from build123d import Box, Compound, Plane, Pos, extrude, mirror, offset

from form import craft
from form.craft import MeshTexture, organic, subd
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage
from form.sketch2d import Sketch

META = {
    "title": "Character mask with magnet eyes",
    "retrieval": False,          # kept in the repo, not offered by search: it reads as an egg; redo it first
    "retrieval_note": "The sculpted form is too crude to learn from (it reads as an egg with eye slits).",
    "category": "organic",
    "tags": ["mask", "cowl", "character", "cosplay", "costume", "organic", "sculpted", "subd",
             "subdivision", "nurbs", "cage", "handles", "hybrid", "magnets", "magnet", "eyes", "lenses", "split",
             "texture", "textured", "web", "relief", "sketch", "constraints", "wearable", "head"],
    "techniques": ["craft.subd.dome_cage (an analytic head form fitted as a grid cage)",
                   "craft.subd.apply_handles (brow, cheekbones, jaw, crown and back as parameters)",
                   "craft.subd.sculpted_shell (skin + inside offset + ruled rim: three exact faces)",
                   "form.sketch2d (the eye outline: two tangent arcs, width, tilt and radii as parameters)",
                   "craft.organic.magnet_boss (bosses grown from the inside, pockets to magnet + clearance)",
                   "craft.organic.split_with_magnets (front/back halves joined by four magnets)",
                   "MeshTexture heightmap, spherical round the nose (web relief on STL and renders only)"],
    "lessons": [
        "Sculpt with a cage, not with sections: a head is not a stack of ellipses. craft.subd.dome_cage fits a grid "
        "cage to a head form; handles (Handle: a centre, a radius and a direction) move its points smoothly, and each "
        "handle is a Param, so 'stronger brow' is a number in the brief and dragging the brow in the viewport finds it.",
        "A sculpted skin is one exact B-spline surface trimmed by a circle of its parameters: no corners, C2 "
        "everywhere inside. sculpted_shell offsets it inward on the same parameters and joins the two at the rim with "
        "one ruled face, so the shell is three faces and every boolean after it stays fast.",
        "Anything that has to fit is CAD, never sculpt: the eye opening is a constrained sketch (form.sketch2d), "
        "magnet pockets are the magnet's diameter plus clearance, the split is a plane. The sculpt only decides where "
        "they sit.",
        "Thin skins cannot hold magnets: grow a boss from the inside (magnet_boss) and cut the pocket into it, with "
        "at least 0.6 mm left under the magnet so it never shows through the face.",
        "Split a print-sized head where the visible seam follows a natural line (just behind the ears), and hold "
        "the halves with magnets in bosses that span the split (split_with_magnets); both pockets come from the split "
        "face, so they line up by construction.",
        "Detail that is texture (the web relief) is a mesh texture: STL, GLB and renders carry it, the STEP stays "
        "the smooth skin for tooling and further CAD.",
    ],
}

# the eye outline: a sketch in the face plane (sketch x = across the face (Y), sketch y = up (Z)), the right eye
EYE = Sketch("eye")
_o = EYE.point(0, 0, fix=True)
_ref = EYE.line(_o, EYE.point(10, 0, fix=True), construction=True)
_pin, _pout = EYE.point(16, 132), EYE.point(66, 145)
_cu, _cl = EYE.point(44, 116), EYE.point(38, 175)
_upper = EYE.arc(_cu, _pout, _pin)          # the upper lid: centre below, counter-clockwise from outer to inner corner
_lower = EYE.arc(_cl, _pin, _pout)          # the lower lid: centre above
_corner = EYE.line(_pin, _pout, construction=True)
EYE.hdist(_o, _pin, 16, "eye_inner", "Eye inner corner from centre", lo=8, hi=28)
EYE.vdist(_o, _pin, 132, "eye_z", "Eye height above the rim", lo=100, hi=165)
EYE.length(_corner, 52, "eye_w", "Eye width", lo=30, hi=64)
EYE.angle(_ref, _corner, 15, "eye_tilt", "Eye tilt", lo=-5, hi=32, step=0.5)
EYE.radius(_upper, 33, "eye_upper_r", "Upper lid radius", lo=27, hi=70)
EYE.radius(_lower, 46, "eye_lower_r", "Lower lid radius", lo=28, hi=110)

L, W, H = 214.0, 178.0, 262.0               # length (front-back), width, height of the cowl, from a size J head


def _rim(th):
    return 18.0 * (1 - math.cos(th)) / 2      # the neck line: lowest under the chin, 18 mm higher at the nape


HANDLES = [
    subd.Handle("brow", "Brow ridge", (L * 0.47, 0, H * 0.60), 70, (1, 0, 0.15), 7, -8, 14, 0.5,
                doc="Pushes the brow forward (+) or back."),
    subd.Handle("cheeks", "Cheekbones", (L * 0.36, 0, H * 0.42), 85, "normal", 3, -8, 10, 0.5,
                doc="Raises (+) or hollows the cheekbones."),
    subd.Handle("jaw", "Jaw and neck width", (L * 0.05, 0, -H * 0.05), 175, (0.45, 1, 0), -24, -35, 10, 1, "%", kind="scale",
                doc="Narrows (-) or widens the jaw and neck, in percent: a head narrows below the cheekbones."),
    subd.Handle("chin", "Chin", (L * 0.44, 0, H * 0.08), 60, (1, 0, -0.3), 7, -10, 14, 0.5,
                doc="Brings the chin forward (+)."),
    subd.Handle("crown", "Crown height", (0, 0, H), 120, (0, 0, 1), 0, -15, 20, 0.5,
                doc="Raises the crown (+)."),
    subd.Handle("back", "Back of head", (-L * 0.48, 0, H * 0.55), 90, (-1, 0, 0), 5, -10, 15, 0.5,
                doc="Fuller (+) or flatter back of the head."),
]


class Design(Recipe):
    title, summary = "Character mask with magnet eyes", (
        "Full-head cowl sculpted from a subdivision cage (brow, cheekbones, jaw, chin, crown and back are handles), "
        "a web relief, eye lenses that fit from the inside on magnets, and a front/back split held by magnets.")
    solids = 4
    photo_color = "#2f4f5f"
    params = [
        Param("wall", "Shell wall", 2.4, 1.6, 4.0, 0.1, "mm", "form", "shell"),
        *[h.param("shell") for h in HANDLES],
        *EYE.params(feature="eyes"),
        Param("magnet_d", "Magnet diameter", 6.0, 3.0, 12.0, 0.5, "mm", "interface", "magnets",
              "Disc magnets, for example 6 x 2 mm N52."),
        Param("magnet_t", "Magnet thickness", 2.0, 1.0, 5.0, 0.5, "mm", "interface", "magnets"),
        Param("magnet_clear", "Magnet pocket clearance", 0.15, 0.05, 0.4, 0.05, "mm", "interface", "magnets",
              "Radial and depth clearance; press-fit at 0.05, glue-in at 0.2+."),
        Param("split_x", "Split plane (from centre)", -28.0, -70.0, 10.0, 1.0, "mm", "form", "split",
              "Where the front and the back meet; just behind the ears hides the seam."),
        Param("lens_t", "Lens frame thickness", 3.0, 2.0, 5.0, 0.1, "mm", "form", "lenses",
              "At least the magnet thickness + 0.8 mm: the lens carries a magnet pocket too."),
        Param("relief", "Relief height", 0.45, 0.0, 1.2, 0.05, "mm", "form", "shell",
              "0 = smooth. A mesh texture: STL, GLB and renders; the STEP is the smooth skin."),
        Param("pattern", "Relief pattern", 0, 0, 1, 1, "", "form", "shell",
              "0 = hexagon panels, 1 = web lines radiating from the nose (craft.organic.web_heightmap)."),
    ]
    features = [Feature("shell", "Sculpted cowl (surface body)", "structure"),
                Feature("eyes", "Eye openings", "access"),
                Feature("magnets", "Lens magnet bosses", "interface"),
                Feature("split", "Front/back split with magnets", "interface"),
                Feature("lenses", "Eye lenses", "interface")]

    def constraints(self, v):
        if v["lens_t"] < v["magnet_t"] + v["magnet_clear"] + 0.6:
            return [RecipeError("The lens frame is too thin for its magnet pocket", "lenses",
                                "Make the lens frame thicker or use thinner magnets.", ["lens_t", "magnet_t"])]
        return []

    def cage(self, v):
        C = subd.dome_cage(L, W, H, n=14, rim=_rim, tuck=0.42, squash=2.3)
        return subd.apply_handles(C, HANDLES, v)

    def eye_cutter(self, v):
        face = EYE.face(v, plane=Plane.YZ)            # in the YZ plane, extruded forward through the face
        right = extrude(face, L)
        return right + mirror(right, Plane.XZ)

    def build(self, v):
        C = self.cage(v)
        shell = subd.sculpted_shell(C, v["wall"])
        stages = [Stage("shell", shell)]

        # eye openings: the sketch, pushed through the front half only
        body = craft.cut(shell, self.eye_cutter(v))
        stages.append(Stage("eyes", body))

        # two magnet bosses per eye, inside, above the outer corner and below the inner corner
        sol = EYE.solve(v)
        (yi, zi), (yo, zo) = sol.p(_pin), sol.p(_pout)
        spots = [(yo + 4, zo + 14), (yi + 2, zi - 14)]
        tops = []
        for sy in (1, -1):
            for (y, z) in spots:
                at, n = organic.surface_point(body, (0, sy * y, z), (1, 0, 0))     # the inside surface, from within
                # square to the skin (its normal there points into the hollow), so a boss never shows outside
                body, top = organic.magnet_boss(body, at, n, v["magnet_d"], v["magnet_t"],
                                                clearance=v["magnet_clear"])
                tops.append((top, n))
        stages.append(Stage("magnets", body))

        # split front/back, four magnets across the split, two each side at temple and jaw height
        x = v["split_x"]
        ys = []
        for z in (H * 0.62, H * 0.28):
            at, _ = organic.surface_point(body, (x, 0, z), (0, 1, 0))
            ys.append((at[1] - v["magnet_d"] / 2 - 2.0 + 1.2, z))       # the inside wall, the boss sunk 1.2 mm into it
        spots_split = [(sy * y, z) for (y, z) in ys for sy in (1, -1)]
        front, back = organic.split_with_magnets(body, x, spots_split, v["magnet_d"], v["magnet_t"],
                                                 v["magnet_clear"])
        stages.append(Stage("split", Compound([front, back])))

        # eye lenses: a frame that follows the inside, sits on the bosses, covers the opening with 6 mm to spare
        boss_h = v["magnet_t"] + 1.0                  # magnet_boss: magnet + 0.6 mm floor + 0.4 mm
        gap = v["wall"] + boss_h
        lens_skin = subd.trimmed_shell_solid(subd.offset_grid(C, -gap), subd.offset_grid(C, -gap - v["lens_t"]),
                                             subd.DISK_R)
        region = extrude(Plane.YZ.location * offset(EYE.face(v), 7), L)
        region = region + mirror(region, Plane.XZ)
        lenses = lens_skin & region & (Pos(x + L / 2 + 1, 0, 0) * Box(L, W * 2, H * 3))
        for top, n in tops:
            lenses = craft.cut(lenses, organic.magnet_pocket(top, n, v["magnet_d"], v["magnet_t"],
                                                             v["magnet_clear"]))
        out = Compound([front, back, *lenses.solids()])
        stages.append(Stage("lenses", out))
        return stages

    def mesh_texture(self, v):
        if v["relief"] <= 0:
            return []
        feats = ["shell", "eyes", "split"]
        if v["pattern"] < 0.5:
            return [MeshTexture("hex", amplitude=v["relief"], scale=11.0, groove=0.12, features=feats, facing="out",
                                edge_falloff=2.0)]
        path = os.path.join(tempfile.gettempdir(), "form-web-relief-24x14.png")
        organic.web_heightmap(path, spokes=24, rings=14)
        return [MeshTexture("heightmap", amplitude=v["relief"], image=path, projection="spherical",
                            axis=(1.0, 0.0, 0.0), center=(0.0, 0.0, H * 0.55), features=feats,
                            facing="out", edge_falloff=2.0, max_edge=0.8)]

    def appearance(self, v):
        return [{"features": ["lenses"], "finish": "smoke", "color": "#d9dde2"},
                {"features": ["magnets"], "finish": "matte", "color": "#2b2d31"},
                {"features": ["shell", "eyes", "split"], "finish": "gloss", "color": "#2f4f5f"}]

    def derived(self, v):
        sol = EYE.solve(v)
        (xi, zi), (xo, zo) = sol.p(_pin), sol.p(_pout)
        return [{"key": "eye_span", "label": "Eye span (outer corners)", "value": round(2 * xo, 2), "unit": "mm",
                 "feature": "eyes", "formula": "2 x outer corner from centre (sketch)", "interface": False},
                {"key": "pocket_d", "label": "Magnet pocket diameter", "value": v["magnet_d"] + 2 * v["magnet_clear"],
                 "unit": "mm", "feature": "magnets", "formula": "magnet_d + 2 x clearance", "interface": True}]
