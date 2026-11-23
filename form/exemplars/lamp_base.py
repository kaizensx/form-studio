"""Table lamp base: a low stone-like dome on a black plinth ring with two turned grooves, crowned by a brass collar
that takes the lamp's stem. The dome sits inside the ring's edge and the collar in a recess, so each part is read
by its shadow line. Form Studio exemplar design (premium everyday object, original)."""
from build123d import Align, Axis, Cylinder, Pos, Torus

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

UP = (Align.CENTER, Align.CENTER, Align.MIN)        # a cylinder standing on its base

META = {
    "title": "Lamp base: dome, plinth ring and brass collar",
    "category": "consumer",
    "tags": ["lamp", "lamp base", "table lamp", "light", "base", "stand", "revolve", "dome", "collar", "brass",
             "premium", "beautiful", "shadow gap", "turned grooves", "three material", "everyday"],
    "techniques": ["a revolved spline profile (craft.revolve_profile(..., spline=True)) for a tense dome",
                   "stacked parts of one axis, each stepped in from the one below: the steps are the shadow lines",
                   "turned grooves on a rhythm as torus cuts (exact, no fillet needed)",
                   "a collar set into a recess: the gap around it is a deliberate shadow ring",
                   "appearance(): stone dome, gloss black ring, brass collar, rubber foot"],
    "lessons": [
        "Archetype: the stacked turned object (plinth, body, crown). Each tier is a different material and steps "
        "in from the one below by 1.5-2 mm; the step's shadow does what a seam line would on a moulded part.",
        "A dome reads tense when its profile is a spline that leaves the plinth almost vertical and lands on the "
        "crown almost flat; a circular arc dome reads as half a ball.",
        "Rhythm: two or three grooves at equal pitch on the plinth, nothing anywhere else. Detail is concentrated "
        "where the hand turns the lamp, the rest stays plain.",
        "Proportion: plinth : dome : collar heights about 1 : 2.5 : 1.2, diameters falling by about 1/4 each tier.",
        "Set a small metal part into a recess rather than on a flat face: the ring of shadow around it makes it look "
        "fitted, not glued.",
        "Torus cuts make exact turned grooves on a cylinder; no fillet, nothing to fail.",
    ],
}


class Design(FeatureDesign):
    title, summary = "Lamp base", "A stone dome on a black ringed plinth with a brass collar for the stem."
    params = [
        Param("dia", "Plinth diameter", 112, 80, 180, 1, "mm", "form", "plinth"),
        Param("plinth_h", "Plinth height", 11, 6, 18, 0.5, "mm", "form", "plinth"),
        Param("dome_h", "Dome height", 21, 14, 45, 0.5, "mm", "form", "dome"),
        Param("collar_d", "Collar diameter", 24, 16, 40, 0.5, "mm", "form", "collar"),
        Param("collar_h", "Collar height", 12, 6, 24, 0.5, "mm", "form", "collar"),
        Param("stem_d", "Stem hole", 10.2, 6, 16, 0.1, "mm", "interface", "collar",
              "A 10 mm lamp tube (M10x1 threaded tube is common) with 0.2 mm clearance."),
    ]

    def setup(self, v):
        R = v["dia"] / 2
        z1 = 2.5 + v["plinth_h"]
        return {"R": R, "z0": 2.5, "z1": z1, "rd": R - 2.0, "z2": z1 + v["dome_h"]}

    def constraints(self, v):
        if v["collar_d"] > v["dia"] * 0.45:
            return [RecipeError("The collar is too wide for the dome", "collar", "Use a smaller collar.",
                                ["collar_d", "dia"])]
        if v["stem_d"] > v["collar_d"] - 6:
            return [RecipeError("The stem hole leaves the collar too thin", "collar", "A wider collar or a thinner stem.",
                                ["stem_d", "collar_d"])]
        return []

    @feature("Plinth ring")                                # skeleton: the ring every other tier sits on
    def plinth(self, v, body):
        c = self.ctx
        ring = Pos(0, 0, c["z0"]) * Cylinder(c["R"], v["plinth_h"], align=UP)
        return craft.safe_fillet(ring, ring.edges(), 1.2)                          # tier 3 on both rims

    @feature("Grooves", role="finish")
    def grooves(self, v, body):
        c = self.ctx
        # --- snippet: turned grooves on a rhythm as exact torus cuts
        for k in (1, 2):
            z = c["z0"] + v["plinth_h"] * k / 3
            body = craft.safe_cut(body, Pos(0, 0, z) * Torus(c["R"] + 0.15, 0.55))
        # --- end snippet
        return body

    @feature("Dome")
    def dome(self, v, body):
        c = self.ctx
        rd, z1, z2, rc = c["rd"], c["z1"], c["z2"], v["collar_d"] / 2 + 1.5
        # --- snippet: a tense dome: leaves the plinth near vertical, lands on the crown near flat
        prof = [(rd, z1 - 0.5), (rd - 0.4, z1 + 0.18 * (z2 - z1)), (rd - 0.10 * rd, z1 + 0.5 * (z2 - z1)),
                (rd * 0.62, z1 + 0.84 * (z2 - z1)), (rc + 0.3 * (rd - rc) * 0.5, z2 - 0.6), (rc, z2)]
        dome = craft.revolve_profile(prof, spline=True)
        # --- end snippet
        return craft.safe_union(body, dome)

    @feature("Collar", role="interface")
    def collar(self, v, body):
        c = self.ctx
        rc, z2 = v["collar_d"] / 2, c["z2"]
        recess = Pos(0, 0, z2 - 1.6) * Cylinder(rc + 1.5, 4, align=UP)
        body = craft.safe_cut(body, recess)                                       # the shadow ring round the collar
        col = Pos(0, 0, z2 - 1.6) * Cylinder(rc, v["collar_h"] + 1.6, align=UP)
        col = craft.safe_fillet(col, col.edges().group_by(Axis.Z)[-1], 1.0)
        body = craft.safe_union(body, col)
        bore = Pos(0, 0, -5) * Cylinder(v["stem_d"] / 2, z2 + v["collar_h"] + 20, align=UP)
        return craft.safe_cut(body, bore)

    @feature("Foot", role="structure")
    def foot(self, v, body):
        c = self.ctx
        f = Cylinder(c["R"] - 7, c["z0"] + 0.4, align=UP)
        f = craft.safe_fillet(f, f.edges().group_by(Axis.Z)[0], 0.6)
        return craft.safe_union(body, f)

    def appearance(self, v):
        return [{"features": ["dome"], "finish": "matte", "color": "#e4ddd0", "label": "stone dome"},
                {"features": ["plinth", "grooves"], "finish": "gloss", "color": "#1f2124", "label": "black ring"},
                {"features": ["collar"], "finish": "metal", "color": "#b8925a", "label": "brass collar"},
                {"features": ["foot"], "finish": "rubber", "color": "#2b2c2e", "label": "rubber foot"}]
