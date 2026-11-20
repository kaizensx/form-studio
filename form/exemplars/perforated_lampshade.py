"""Pendant lampshade: a revolved bell whose wall carries a graded perforation field (large holes low, where the light
spills, fading to pin-holes near the crown), a rolled lower lip, and a top gallery with an E27 shade-ring hole
carried on three spokes with vent gaps between them. Form Studio exemplar design (a 3D model)."""
import math

from build123d import Align, Box, Compound, Cylinder, Plane, Pos, Rot, Spline, Torus, Vector

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Perforated pendant lampshade",
    "category": "textured",
    "tags": ["lamp", "lampshade", "shade", "pendant", "light", "perforated", "perforation", "holes", "graded",
             "gradient", "pattern", "textured", "e27", "revolve", "bell", "vent", "decor"],
    "techniques": ["profile spline revolved, hollowed by a revolve of the profile inset along its normal",
                   "holes placed along the spline by arc length, drilled along the surface normal",
                   "graded hole size: a fraction of the local pitch that falls with height",
                   "all holes in one Compound, one craft.cut", "rolled lip from a torus bead",
                   "gallery: E27 shade-ring hole on three spokes with vent gaps"],
    "lessons": [
        "Grade a perforation by one law, not by hand: hole diameter = local pitch x a fraction that falls from the "
        "rim to the crown. The holes keep the same number per row (they line up in meridians, like a pressed metal "
        "shade) and the web between them never drops under the minimum because it is a fraction of the pitch.",
        "Place holes along the profile by arc length, not by height: on a bell the wall turns toward horizontal near "
        "the crown, and equal heights would crowd the rows there. Drill each one along the surface normal so it reads "
        "round from outside.",
        "Cut hundreds of holes in one boolean: collect them in a Compound and subtract once (craft.cut); hundreds of "
        "single cuts are slow and each one re-splits the same faces.",
        "The interface is real: an E27 lampholder carries the shade on its threaded sleeve and shade ring, so the "
        "gallery has a 40 mm hole and is thick enough to be clamped; the gaps between its spokes let heat out above "
        "the bulb.",
        "Hollow a revolved form by revolving the profile inset along its normal (as on a vase): exact, quick, and the "
        "wall stays even through the bell's curve where a plain radial inset would thin it.",
    ],
}


class Design(Recipe):
    title, summary = "Perforated lampshade", "Pendant bell shade with a graded perforation field and an E27 gallery."
    solids = 1
    photo_color = "#efece4"
    params = [
        Param("diameter", "Rim diameter", 260, 160, 400, 5, "mm", "form", "shade"),
        Param("height", "Height", 200, 120, 320, 5, "mm", "form", "shade"),
        Param("wall", "Wall", 1.8, 1.2, 3.0, 0.1, "mm", "form", "shade"),
        Param("cols", "Holes per row", 28, 16, 40, 1, "", "form", "perforation"),
        Param("open_low", "Hole / pitch at the rim", 0.55, 0.3, 0.7, 0.01, "", "form", "perforation",
              "Largest holes, low on the shade."),
        Param("open_high", "Hole / pitch at the top", 0.2, 0.1, 0.4, 0.01, "", "form", "perforation",
              "Smallest holes, near the crown."),
        Param("holder_d", "Lampholder hole", 40, 28, 44, 0.5, "mm", "brief", "gallery",
              "E27 lampholder shade ring: 40 mm hole (common shade-carrier spec; check the holder's datasheet).",
              "specified"),
    ]
    features = [Feature("shade", "Bell shade", "structure"), Feature("lip", "Rolled lip", "finish"),
                Feature("perforation", "Graded perforation", "finish"), Feature("gallery", "E27 gallery", "interface")]

    def constraints(self, v):
        if v["open_high"] > v["open_low"]:
            return [RecipeError("The top holes are larger than the rim holes", "perforation",
                                "Keep hole / pitch at the top at or under the rim's.", ["open_high", "open_low"])]
        if v["diameter"] * 0.36 < v["holder_d"] / 2 + 12:
            return [RecipeError("The crown is too small for the lampholder", "gallery", "Widen the shade.",
                                ["diameter", "holder_d"])]
        return []

    def _profile(self, v):
        R, H = v["diameter"] / 2, v["height"]
        rt = R * 0.36                                      # crown opening
        return [(R, 0.0), (R * 0.965, H * 0.22), (R * 0.84, H * 0.52), (R * 0.6, H * 0.8), (rt, H)]

    def build(self, v):
        H, t = v["height"], v["wall"]
        pts = self._profile(v)
        prof = Spline(*[Vector(r, 0, z) for r, z in pts])
        outer = craft.revolve_profile(pts, spline=True)
        # inside: the same curve moved inward along its normal by the wall, run out past both open ends
        def inset(d):
            q = []
            for i in range(41):
                p, tg = prof.position_at(i / 40), prof.tangent_at(i / 40)
                q.append((p.X - d * tg.Z, p.Z + d * tg.X))
            return [(q[0][0], -2.0)] + q[1:-1] + [(q[-1][0], H + 2.0)]
        inner_pts = inset(t)
        body = outer - craft.revolve_profile(inner_pts, spline=True)
        stages = [Stage("shade", body)]

        # rolled lip: a bead round the inside of the rim, trimmed flush with it
        r0 = inner_pts[1][0]
        body = body + Pos(0, 0, t * 0.9) * Torus(r0 + t * 0.15, t * 0.9)
        body = body - Pos(0, 0, -10) * Cylinder(v["diameter"], 10, align=BOTTOM)
        stages.append(Stage("lip", body))

        # --- snippet: graded perforation along a revolved profile (arc length, surface normal, one cut)
        n = int(v["cols"])
        L = prof.length
        s, row, holes = 16.0 + 2 * t, 0, []
        self._open = 0.0
        while True:
            u = s / L
            p, tg = prof.position_at(u), prof.tangent_at(u)
            pitch = 2 * math.pi * p.X / n                       # around the shade at this height
            k = min(1.0, s / (0.85 * L))                        # 0 at the rim, 1 near the crown
            d = pitch * (v["open_low"] + (v["open_high"] - v["open_low"]) * k ** 0.8)
            if s + d / 2 > 0.85 * L or d < 1.2:
                break
            nr, nz = tg.Z, -tg.X                                # outward normal in the (r, z) plane
            for j in range(n):
                a = 2 * math.pi * (j + 0.5 * (row % 2) + 0.25) / n     # no hole sits on the revolve seam
                ca, sa = math.cos(a), math.sin(a)
                pl = Plane(origin=(p.X * ca, p.X * sa, p.Z), z_dir=(nr * ca, nr * sa, nz))
                holes.append(pl * Cylinder(d / 2, 6 * t))
            self._open += n * math.pi * d * d / 4
            s += max(pitch * math.sqrt(3) / 2, d + 1.6)          # staggered rows; web >= 1.6 mm along the slant
            row += 1
        body = craft.cut(body, Compound(children=holes))
        # --- end snippet
        self._holes, self._rows = len(holes), row
        stages.append(Stage("perforation", body))

        # gallery: a ring for the lampholder's shade ring, on three spokes; the gaps between them vent the heat
        rt_in = inner_pts[-2][0]
        rh, tg_ = v["holder_d"] / 2, 3.0
        # the plate is clipped by the mid-wall surface, so its rim ends inside the wall whatever the crown's slope
        mid = craft.revolve_profile(inset(t / 2), spline=True)
        plate = mid & (Pos(0, 0, H - tg_ - 0.6) * (Cylinder(rt_in + 2 * t, tg_, align=BOTTOM)
                                                  - Cylinder(rh, 20, align=BOTTOM)))
        vent = Pos(0, 0, H - 10) * (Cylinder(rt_in - 3.0, 20, align=BOTTOM) - Cylinder(rh + 6.0, 20, align=BOTTOM))
        for k in range(3):
            vent = vent - Rot(0, 0, 90 + 120 * k) * Pos(rt_in / 2, 0, H - 10) * Box(rt_in, 7.0, 20, align=BOTTOM)
        plate = plate - vent
        top = [e for e in plate.edges() if abs(e.position_at(0.5).Z - (H - 0.6)) < 0.01
               and math.hypot(e.position_at(0.5).X, e.position_at(0.5).Y) < rh + 6.5]     # the holder ring's edges
        plate = craft.safe_fillet(plate, top, 0.8)
        body = craft.fuse(body, plate)
        stages.append(Stage("gallery", body))
        return parts.checked(stages)

    def derived(self, v):
        if not hasattr(self, "_holes"):
            self.build(v)
        R, H = v["diameter"] / 2, v["height"]
        area = math.pi * (R + R * 0.36) * math.hypot(H, R * 0.64)          # frustum approximation of the skin
        return [{"key": "holes", "label": "Perforations", "value": self._holes, "unit": "", "feature": "perforation",
                 "formula": f"{int(v['cols'])} per row x {self._rows} rows", "interface": False},
                {"key": "open_area", "label": "Open area", "value": round(100 * self._open / area, 1), "unit": "%",
                 "feature": "perforation", "formula": "hole area / shade skin (frustum estimate)", "interface": False},
                {"key": "holder_hole", "label": "Lampholder hole", "value": v["holder_d"], "unit": "mm",
                 "feature": "gallery", "formula": "E27 shade ring (specified)", "interface": True}]

    def appearance(self, v):
        return [{"features": ["gallery"], "finish": "metal", "color": "#b08d57"},
                {"features": ["shade", "lip", "perforation"], "finish": "matte", "color": "#efece4"}]
