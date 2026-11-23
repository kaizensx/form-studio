"""Wall hook for coats: a slender soft-cornered backplate with two countersunk screw holes, and one arm that leaves
the plate level, sweeps forward and up, tapers from a flared root to a narrow neck and ends in a ball. Form Studio
exemplar design."""

from build123d import Axis, Edge, Plane, Pos, Rot, Sphere, Vector, extrude

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

META = {
    "title": "Swept coat hook with ball end",
    "category": "consumer",
    "tags": ["hook", "wall hook", "coat hook", "hat hook", "hanger", "towel hook", "wall mount", "backplate",
             "countersunk", "screw", "taper", "loft", "sweep", "ball end", "consumer", "home"],
    "techniques": ["craft.loft_sections through sections normal to a tangent-constrained spline (Edge.make_spline)",
                   "taper law: flared root -> slim neck -> ball (radius as a function of the path fraction)",
                   "ball end fused with an overlap, its neck rounded with craft.safe_fillet",
                   "parts.screw_clearance countersunk holes turned to the plate's face (Rot about Y)",
                   "root blend selected as the loop that lies in the plate's front face"],
    "lessons": [
        "Elegance is in the taper: the arm is thickest where the bending moment is (the root, flared into the plate) "
        "and thins steadily toward the tip, then the ball swells again. A constant-section bar reads as pipe.",
        "Sections slightly taller than wide (about 1.2 : 1) are stiffer in the direction the coat pulls and look "
        "slimmer from the front.",
        "Leave the plate level and rise only after the first third: a hook that climbs straight from the wall lets "
        "the coat's loop slide off; one that rises at the tip holds it, and the ball stops it at the end and keeps "
        "a point away from faces and fabric.",
        "Screw holes go where the driver can reach them straight on: one above the arm, clear of the ball's path, "
        "one below the root. 4 mm wood screws with countersunk heads (M4 clearance, ISO 273; 90 deg sink) sit flush.",
        "Give the path end tangents (Edge.make_spline(..., tangents=...)): the root then leaves the plate square to "
        "the wall and the tip points where you chose, instead of wherever the spline happens to end.",
        "Fuse a ball with a real overlap (its centre inside the last section) and round the concave neck: a sphere "
        "that only touches the arm's end face makes a knife-edge OCCT cannot fillet. Turn the sphere so its poles "
        "(where its surface is singular) are off the arm's axis, or the boolean fails for some sizes.",
    ],
}


class Design(Recipe):
    title, summary = "Coat hook", "Backplate with two countersunk screws and a tapering swept arm ending in a ball."
    params = [
        Param("plate_h", "Plate height", 92, 80, 130, 1, "mm", "form", "plate"),
        Param("plate_w", "Plate width", 26, 20, 36, 0.5, "mm", "form", "plate"),
        Param("plate_t", "Plate thickness", 7, 5, 10, 0.5, "mm", "form", "plate"),
        Param("reach", "Reach from the wall", 62, 40, 90, 1, "mm", "form", "arm"),
        Param("rise", "Rise at the tip", 30, 15, 38, 0.5, "mm", "form", "arm"),
        Param("root_r", "Arm radius at the root", 8, 6, 10, 0.25, "mm", "form", "arm", "Half the arm's width."),
        Param("ball_d", "Ball diameter", 17, 13, 24, 0.5, "mm", "form", "ball"),
    ]
    features = [Feature("plate", "Backplate", "structure"), Feature("holes", "Countersunk screw holes", "interface"),
                Feature("arm", "Tapered arm", "structure"), Feature("root", "Root blend", "finish"),
                Feature("ball", "Ball end", "finish")]

    def constraints(self, v):
        if v["ball_d"] / 2 < v["root_r"] * 0.55 + 2:
            return [RecipeError("The ball is smaller than the arm's tip", "ball", "Use a larger ball.", ["ball_d", "root_r"])]
        if 2 * v["root_r"] + 6 > v["plate_w"] + 4:
            return [RecipeError("The arm is wider than the plate", "arm", "Widen the plate or thin the arm.",
                                ["root_r", "plate_w"])]
        if self._z_root(v) + v["rise"] + v["ball_d"] / 2 + 6 > v["plate_h"] - 8:
            return [RecipeError("The ball rises in front of the upper screw", "arm",
                                "Lower the rise or make the plate taller.", ["rise", "plate_h", "ball_d"])]
        return []

    def _z_root(self, v):
        return v["plate_h"] * 0.33

    def _path(self, v):
        t, L, H = v["plate_t"], v["reach"], v["rise"]
        z0 = self._z_root(v)
        pts = [(t - 2.0, z0), (t + L * 0.35, z0 + H * 0.06), (t + L * 0.75, z0 + H * 0.38), (t + L, z0 + H)]
        return Edge.make_spline([Vector(x, 0, z) for x, z in pts],
                                tangents=[Vector(1, 0, 0), Vector(0.45, 0, 1).normalized()])

    def _radius(self, v, s):
        """Arm radius along the path fraction s: a flare in the first 10 %, then an eased taper to 52 % at the tip."""
        r0 = v["root_r"]
        flare = max(0.0, 1 - s / 0.1) ** 2 * 3.0
        return r0 * (1 - 0.48 * (1 - (1 - s) ** 1.4)) + flare

    def build(self, v):
        t, Hp, W = v["plate_t"], v["plate_h"], v["plate_w"]
        # plate: a tall soft-square slab in the wall plane (YZ), its back on the wall at x = 0
        face = craft.superellipse_face(W / 2, Hp / 2, 3.2, plane=Plane.YZ, center=(0, Hp / 2), count=72)
        plate = extrude(face, t)
        plate = craft.safe_fillet(plate, plate.edges().group_by(Axis.X)[-1], min(2.5, t * 0.4))   # front edge
        plate = craft.safe_fillet(plate, plate.edges().group_by(Axis.X)[0], 0.6)                  # wall edge
        stages = [Stage("plate", plate)]
        # holes: 4 mm wood screws, countersinks on the front face (the cutter's -Z turned to -X)
        cs = parts.screw_clearance("M4", t, head="countersunk")
        body = plate
        for z in (11.0, Hp - 11.0):
            body = craft.cut(body, Pos(t, 0, z) * Rot(0, 90, 0) * cs.shape)
        stages.append(Stage("holes", body))
        # --- snippet: a tapering arm lofted along a spline with end tangents
        path = self._path(v)
        secs = []
        for i in range(14):
            s = (i / 13) ** 1.2
            r = self._radius(v, s)
            pl = Plane(origin=path.position_at(s), x_dir=(0, 1, 0), z_dir=path.tangent_at(s))
            secs.append(craft.superellipse_face(r, r * 1.2, 2.0, plane=pl, count=48))
        arm = craft.loft_sections(secs)
        body = craft.fuse(body, arm)
        # --- end snippet
        stages.append(Stage("arm", body))
        # root: round the loop where the arm leaves the plate's front face
        def in_front(e):
            bb = e.bounding_box()
            return abs(bb.min.X - t) < 0.05 and abs(bb.max.X - t) < 0.05 and bb.size.Z < 4 * v["root_r"] + 10
        root = [e for e in body.edges() if in_front(e) and e.geom_type.name == "BSPLINE"]
        body = craft.safe_fillet(body, root, 3.0)
        stages.append(Stage("root", body))
        # --- snippet: a ball end with a real overlap and a rounded neck
        rb = v["ball_d"] / 2
        end, d = path.position_at(1.0), path.tangent_at(1.0)
        ball = Pos(*(end + d * (rb * 0.55))) * Rot(90, 0, 0) * Sphere(rb)      # poles off the arm axis
        body = craft.fuse(body, ball)
        neck = [e for e in body.edges() if (e.center() - end).length < rb + 2 and e.geom_type.name != "LINE"
                and (e.center() - (end + d * (rb * 0.55))).length < rb + 0.5]
        body = craft.safe_fillet(body, neck, 2.5)
        # --- end snippet
        stages.append(Stage("ball", body))
        return parts.checked(stages)

    def appearance(self, v):
        return [{"features": ["plate", "holes", "arm", "root", "ball"], "finish": "metal", "color": "#b8925a"}]

    def derived(self, v):
        return [{"key": "tip_r", "label": "Arm radius at the tip", "value": round(self._radius(v, 1.0), 2), "unit": "mm",
                 "feature": "arm", "formula": "root radius x 0.52", "interface": False},
                {"key": "screw", "label": "Screw clearance", "value": parts.clearance_d("M4")[0], "unit": "mm",
                 "feature": "holes", "formula": "4 mm wood screw, M4 normal clearance (ISO 273), 90 deg countersink",
                 "interface": True}]
