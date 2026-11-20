"""Action-camera helmet mount: a curved adhesive base whose underside follows a 150 mm sphere (a helmet's crown), a
lofted riser, and the standard three-finger interface (3 mm fingers, 15 mm wide, 3.2 mm gaps, M5 bolt) with a
captive-nut boss on the outer finger. Form Studio exemplar design."""
import math

from build123d import Align, Cylinder, Plane, Pos, Rot, Sphere, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Action camera helmet mount",
    "category": "mechanical",
    "tags": ["action camera", "camera mount", "three prong", "3-prong", "fingers", "helmet mount", "curved base",
             "adhesive mount", "m5", "nut trap", "thumb screw", "sphere", "interface", "mechanical", "bracket"],
    "techniques": ["curved plate = (Sphere(R + t) - Sphere(R)) & plan prism: an exact spherical shell piece",
                   "adhesive-pad recess as a thin spherical shell cut inside an inset plan",
                   "riser lofted between two superellipse sections (craft.loft_sections), sunk into the plate",
                   "fingers from one YZ profile (rectangle + tip circle) extruded along X, spaced by thickness + gap",
                   "parts.clearance_d('M5') bore and parts.nut_trap('M5') in a boss on the outer finger",
                   "craft.safe_fillet on finger roots and the plate's top edge"],
    "lessons": [
        "The interface is the standard, so copy it exactly and name it: three fingers 3.0 mm thick and 15 mm wide, "
        "3.2 mm gaps that take the camera's two fingers with ~0.1 mm per side, the bolt hole on the fingers' tip-"
        "circle centre, a 5.3-5.5 mm clearance for the M5 thumb screw (ISO 273), and the nut captive in the outer "
        "finger so one hand can tighten it.",
        "A base that follows a surface is cut from that surface: a helmet crown is close to a 150 mm sphere, so the "
        "plate is the space between spheres of radius R and R + t inside the plan outline. Its underside then "
        "touches along the whole pad instead of rocking on two corners.",
        "The adhesive pad (VHB, about 1 mm) sits in a 0.5 mm recess with a rim around it: the rim protects the pad's "
        "edge from peeling, and the recess is again a spherical shell, so the pad stays the same thickness.",
        "Sink every part you fuse 0.5-1 mm into the one below (riser into the plate, fingers into the riser): "
        "surfaces that only touch leave a zero-thickness seam the boolean cannot close.",
        "The fingers carry bending at their roots when the camera is knocked: round the roots (r ~1 mm) and make the "
        "riser wider than the finger stack so the load spreads into the plate.",
        "Check that the riser's top really contains the finger stack (a superellipse's corners are inside its "
        "bounding box): fingers that overhang its edge by a fraction of a millimetre make the root fillets fail, and "
        "a fillet that half-succeeds can leave a solid that reports valid yet silently ignores every later cut. "
        "After a risky step, confirm a probe cut changes the volume.",
    ],
}


class Design(Recipe):
    title, summary = "Helmet camera mount", ("Curved adhesive base for a 150 mm helmet crown with the standard "
                                             "three-finger mount, M5 bolt and captive nut.")
    params = [
        Param("helmet_r", "Helmet radius", 150, 110, 250, 1, "mm", "brief", "base",
              "A helmet crown is about a 150 mm sphere; measure yours with a ruler across it if it matters."),
        Param("base_l", "Base length", 42, 38, 56, 0.5, "mm", "form", "base"),
        Param("base_w", "Base width", 36, 34, 48, 0.5, "mm", "form", "base"),
        Param("base_t", "Base thickness", 3.5, 2.5, 5, 0.1, "mm", "form", "base"),
        Param("finger_t", "Finger thickness", 3.0, 2.8, 3.2, 0.05, "mm", "interface", "fingers",
              "Standard three-prong action-camera mount (de facto standard).", "specified"),
        Param("gap", "Gap between fingers", 3.2, 3.05, 3.4, 0.05, "mm", "interface", "fingers",
              "Takes the camera's 3.0 mm fingers with 0.1 mm per side.", "specified"),
        Param("hole_h", "Bolt hole above the riser", 9.0, 7.5, 14, 0.25, "mm", "form", "fingers"),
    ]
    features = [Feature("base", "Curved base", "structure"), Feature("pad", "Adhesive pad recess", "interface"),
                Feature("riser", "Riser", "structure"), Feature("fingers", "Three fingers", "interface"),
                Feature("bolt", "M5 bolt hole", "interface"), Feature("nut", "Captive nut pocket", "interface")]

    W_F = 15.0                     # finger width (standard)

    def constraints(self, v):
        stack = 3 * v["finger_t"] + 2 * v["gap"]
        if v["base_w"] < self.W_F + 10 or v["base_l"] < stack + 16:
            return [RecipeError("The base is smaller than the riser under the fingers", "base", "Enlarge the base.",
                                ["base_l", "base_w"])]
        return []

    def _z_top(self, v, x=0.0, y=0.0):
        """Height of the base's top surface at (x, y): the helmet sphere (centre at z = -R, crown at z = 0) + t."""
        R = v["helmet_r"] + v["base_t"]
        return math.sqrt(R * R - x * x - y * y) - v["helmet_r"]

    def build(self, v):
        Rh, t, L, W = v["helmet_r"], v["base_t"], v["base_l"], v["base_w"]
        c = Pos(0, 0, -Rh)
        # --- snippet: a plate that follows a sphere (the space between two spheres inside the plan outline)
        plan = Pos(0, 0, -20) * extrude(craft.superellipse_face(L / 2, W / 2, 3.2, count=72), 40)
        shell = c * Sphere(Rh + t) - c * Sphere(Rh)
        base = shell & plan
        base = craft.safe_fillet(base, [e for e in base.edges() if e.center().Z > 0.5 * t - 0.5
                                        and e.geom_type.name != "CIRCLE"], 1.2)
        # --- end snippet
        stages = [Stage("base", base)]
        # pad recess: 0.5 mm deep, 2.5 mm rim, the same spherical law
        inset = Pos(0, 0, -20) * extrude(craft.superellipse_face(L / 2 - 2.5, W / 2 - 2.5, 3.2, count=72), 40)
        recess = (c * Sphere(Rh + 0.5) - c * Sphere(Rh - 1)) & inset
        body = craft.cut(base, recess)
        stages.append(Stage("pad", body))
        # riser: a loft from a soft footprint sunk into the plate up to a top that contains the finger stack with
        # 3 mm all round (room for the root fillets)
        ft, g = v["finger_t"], v["gap"]
        stack = 3 * ft + 2 * g
        z0 = self._z_top(v) - 1.0
        z1 = self._z_top(v) + 4.0
        riser = craft.loft_sections([craft.superellipse_face(stack / 2 + 7.5, self.W_F / 2 + 7, 2.6, z=z0 - 1.5),
                                     craft.superellipse_face(stack / 2 + 5.5, self.W_F / 2 + 5, 3.0, z=z0 + 1.0),
                                     craft.superellipse_face(stack / 2 + 3.0, self.W_F / 2 + 3.0, 4.0, z=z1)])
        body = craft.fuse(body, riser)
        stages.append(Stage("riser", body))
        # --- snippet: three fingers from one profile, spaced by thickness + gap
        zc = z1 + v["hole_h"]                                  # bolt axis height
        r_tip = self.W_F / 2
        prof = craft.polygon_profile([(-r_tip, z1 - 0.8), (r_tip, z1 - 0.8), (r_tip, zc), (-r_tip, zc)], plane=Plane.YZ)
        finger = extrude(prof, ft) + Pos(0, 0, zc) * Rot(0, 90, 0) * Cylinder(r_tip, ft, align=BOTTOM)
        xs = [-stack / 2 + i * (ft + g) for i in range(3)]
        fingers = [Pos(x, 0, 0) * finger for x in xs]
        # the outer (+X) finger carries a round boss for the captive nut; fuse it to its finger first (two simple
        # solids), then the finger to the body
        x_out = stack / 2
        boss = Pos(x_out - 0.5, 0, zc) * Rot(0, 90, 0) * Cylinder(6.4, 4.6, align=BOTTOM)
        boss = craft.safe_fillet(boss, [e for e in boss.edges() if e.center().X > x_out + 3], 1.0)
        fingers[-1] = craft.fuse(fingers[-1], boss)
        for f in fingers:
            body = craft.fuse(body, f)
        roots = [e for e in body.edges() if abs(e.bounding_box().min.Z - z1) < 0.05 and abs(e.bounding_box().max.Z - z1) < 0.05
                 and e.geom_type.name == "LINE" and abs(e.tangent_at(0.5).Y) > 0.99]
        body = craft.safe_fillet(body, roots, 1.0)
        # --- end snippet
        stages.append(Stage("fingers", body))
        # bolt: M5 clearance straight through all three fingers on the tip-circle centre
        d_bolt = parts.clearance_d("M5", "normal")[0]
        bolt = Pos(-stack / 2 - 10, 0, zc) * Rot(0, 90, 0) * Cylinder(d_bolt / 2, stack + 30, align=BOTTOM)
        body = craft.cut(body, bolt)
        stages.append(Stage("bolt", body))
        # nut: a hex pocket (ISO 4032 M5, 8 mm across flats + 0.15 per side) in the boss, opening outward
        nt = parts.nut_trap("M5", "hex", clearance=0.15, depth=4.9)
        body = craft.cut(body, Pos(x_out + 4.1, 0, zc) * Rot(0, 90, 0) * Rot(0, 0, 30) * nt.shape)
        stages.append(Stage("nut", body))
        return parts.checked(stages)

    def appearance(self, v):
        return [{"features": ["base", "pad", "riser", "fingers", "bolt", "nut"], "finish": "matte", "color": "#232527"}]

    def derived(self, v):
        stack = 3 * v["finger_t"] + 2 * v["gap"]
        return [{"key": "stack", "label": "Finger stack width", "value": round(stack, 2), "unit": "mm",
                 "feature": "fingers", "formula": "3 x finger + 2 x gap", "interface": True},
                {"key": "bolt_d", "label": "Bolt hole", "value": parts.clearance_d("M5")[0], "unit": "mm",
                 "feature": "bolt", "formula": "M5 normal clearance (ISO 273)", "interface": True},
                {"key": "pad_sag", "label": "Base curvature over its length", "value":
                 round(v["helmet_r"] - math.sqrt(v["helmet_r"] ** 2 - (v["base_l"] / 2) ** 2), 2), "unit": "mm",
                 "feature": "base", "formula": "sphere sagitta R - sqrt(R^2 - (L/2)^2)", "interface": True}]
