"""Floating wall hook: a low domed rose that stands off the wall on a hidden disc, so it floats on its own shadow,
and one tapering arm that leaves the rose level and rises to a flattened pad in a warm second material. The fixing
is a keyhole on the back: no screw head shows. Form Studio exemplar design (premium everyday object, original)."""
import math

from build123d import Align, Axis, Box, Cylinder, Edge, Plane, Pos, Rot, Vector

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

UP = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Floating wall hook: domed rose, tapered arm, pad tip",
    "category": "consumer",
    "tags": ["wall hook", "coat hook", "hook", "hanger", "towel hook", "rose", "keyhole", "hidden fixing", "taper",
             "premium", "beautiful", "shadow gap", "floating", "two material", "everyday"],
    "techniques": ["a rose revolved from a spline profile (built on Z, turned to face +X before it is fused)",
                   "a stand-off disc smaller than the rose: the rose floats on its shadow line",
                   "an arm lofted through sections on a spline path (x_dir fixed along Y: no twist), tapering by a law",
                   "the last span of the same loft flattened into a pad: one gesture, a second material",
                   "a keyhole on the back for a hidden screw (the front shows no fixing)"],
    "lessons": [
        "Hide the fixing. A premium hook shows no screw head: a keyhole on the back takes a screw already in the wall.",
        "Float it: a stand-off disc 3-4 mm smaller than the rose and 1.5-2 mm deep lifts the whole object off the "
        "wall on a ring of shadow.",
        "The arm's taper carries the gesture: thickest at the root where the moment is, thinning toward the tip, then "
        "opening into a pad that spreads the load on a collar. Sections taller than wide look slimmer from the front.",
        "Make the end of a loft its own feature and material: the pad is the arm's last span with flatter sections, "
        "so there is no joint to blend.",
        "Build a revolved part on Z and turn it with Rot before fusing: the feature then owns its faces in place.",
        "Radius tiers: the rose's dome (R big, from the profile), the root blend R2-2.5, the pad's edge from its "
        "section; never a sharp edge where cloth runs.",
    ],
}


class Design(FeatureDesign):
    title, summary = "Floating wall hook", "A domed rose on a hidden stand-off, a tapered arm and a pad tip; keyhole fixing."
    params = [
        Param("rose_d", "Rose diameter", 48, 34, 70, 0.5, "mm", "form", "rose"),
        Param("rose_h", "Rose height", 7.5, 6, 14, 0.25, "mm", "form", "rose"),
        Param("reach", "Reach", 58, 40, 90, 1, "mm", "form", "arm"),
        Param("rise", "Rise at the tip", 22, 10, 40, 0.5, "mm", "form", "arm"),
        Param("root_w", "Arm width at the root", 13, 9, 18, 0.25, "mm", "form", "arm"),
        Param("screw_head", "Screw head diameter", 8.5, 6, 11, 0.25, "mm", "interface", "keyhole",
              "The keyhole's wide end; its slot takes the shank (about 4.5 mm for a 4 mm wood screw)."),
    ]

    def setup(self, v):
        x0 = 1.8 + v["rose_h"] - 1.0                      # the arm starts 1 mm inside the rose's crown
        L, H = v["reach"], v["rise"]
        pts = [(x0, 0.0), (x0 + L * 0.40, -1.0), (x0 + L * 0.78, H * 0.30), (x0 + L, H)]
        path = Edge.make_spline([Vector(x, 0, z) for x, z in pts],
                                tangents=[Vector(1, 0, 0), Vector(0.55, 0, 1).normalized()])
        return {"path": path, "sd": 1.8}

    def constraints(self, v):
        if v["root_w"] > v["rose_d"] * 0.4:
            return [RecipeError("The arm is too wide for the rose", "arm", "A narrower arm or a larger rose.",
                                ["root_w", "rose_d"])]
        return []

    @feature("Rose")                                       # skeleton: the domed rose, standing off the wall
    def rose(self, v, body):
        R, h, sd = v["rose_d"] / 2, v["rose_h"], self.ctx["sd"]
        # --- snippet: a revolved rose built on Z and turned to face +X
        prof = [(R, 0.0), (R + 0.1, h * 0.28), (R * 0.84, h * 0.80), (R * 0.45, h * 0.99), (0.01, h)]
        dome = craft.revolve_profile(prof, spline=True)
        dome = craft.safe_fillet(dome, dome.edges().group_by(Axis.Z)[0], 0.8)
        return Pos(sd, 0, 0) * Rot(0, 90, 0) * dome
        # --- end snippet

    @feature("Stand-off", role="structure")
    def standoff(self, v, body):
        disc = Rot(0, 90, 0) * Cylinder(v["rose_d"] / 2 - 3.5, self.ctx["sd"] + 0.4, align=UP)
        return craft.safe_union(body, disc)

    def _arm(self, v, t0, t1, pad=False):
        path, out = self.ctx["path"], []
        n = max(4, int(round((t1 - t0) * 30)))
        w0 = v["root_w"] / 2
        for i in range(n + 1):
            s = t0 + (t1 - t0) * i / n
            pl = Plane(origin=path.position_at(s), x_dir=(0, 1, 0), z_dir=path.tangent_at(s))
            a = w0 * (1 - 0.45 * s ** 0.9)                 # the taper law: 55 % of the root at the tip
            b = a * 1.25
            if pad:                                        # the pad swells a little and turns flatter, gently
                k = (s - t0) / (t1 - t0)
                a, b = a * (1 + 0.18 * k * k), b * (1 - 0.12 * k * k)
            out.append(craft.superellipse_face(a, b, 2.4, plane=pl, count=48))
        if pad:
            # --- snippet: a rounded end made by the loft itself: sections past the end shrink on a quarter ellipse
            end, d = path.position_at(1.0), path.tangent_at(1.0)
            cap = min(a, b) * 0.9
            for phi in (30, 55, 72, 84):
                r = math.radians(phi)
                pl = Plane(origin=end + d * (cap * math.sin(r)), x_dir=(0, 1, 0), z_dir=d)
                out.append(craft.superellipse_face(a * math.cos(r), b * math.cos(r), 2.4, plane=pl, count=48))
            # --- end snippet
        return craft.loft_sections(out)

    @feature("Arm")
    def arm(self, v, body):
        body = craft.safe_union(body, self._arm(v, 0.0, 0.8))
        root = [e for e in body.edges() if abs(e.center().X - (self.ctx["sd"] + v["rose_h"] * 0.9)) < v["rose_h"] * 0.4
                and abs(e.center().Y) < v["root_w"] and e.geom_type.name != "LINE"
                and (e.center() - Vector(e.center().X, 0, 0)).length < v["root_w"]]
        return craft.safe_fillet(body, root, 2.2)

    @feature("Pad", role="interface")
    def pad(self, v, body):
        return craft.safe_union(body, self._arm(v, 0.8, 1.0, pad=True))

    @feature("Keyhole", role="interface")
    def keyhole(self, v, body):
        hd = v["screw_head"]
        z = v["rose_d"] * 0.18
        head = Pos(-1, 0, z) * Rot(0, 90, 0) * Cylinder(hd / 2, 4.5, align=UP)
        slot = Pos(1.2, 0, z - hd * 0.6) * Box(4.4, 4.6, hd * 1.2)
        return craft.safe_cut(body, head + slot)

    def appearance(self, v):
        return [{"features": ["rose", "arm"], "finish": "matte", "color": "#1f2022", "label": "black powder coat"},
                {"features": ["pad"], "finish": "matte", "color": "#b98a58", "label": "oiled oak tone"},
                {"features": ["standoff", "keyhole"], "finish": "rubber", "color": "#3b3d40", "label": "stand-off"}]
