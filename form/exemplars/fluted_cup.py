"""Fluted tumbler: a tapered revolved cup whose wall carries concave flutes that widen with the radius and end in
round scoops, a smooth drinking band under a full-round lip, a weighted base and a recessed foot ring.
Form Studio exemplar design."""
import math

from build123d import (Align, Axis, Cylinder, Line, Plane, Pos, Rot, ThreePointArc, Vector, Wire, make_face,
                       revolve)

from form import craft, parts
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

META = {
    "title": "Fluted tumbler",
    "category": "textured",
    "tags": ["cup", "tumbler", "glass", "mug", "beaker", "fluted", "flutes", "fluting", "concave", "scallop",
             "texture", "textured", "brep texture", "revolve", "tableware", "drinkware"],
    "techniques": ["revolved outer and inner profiles", "flute cutters: one revolved capsule per flute (round end, "
                   "tapered side, round end) laid along the slant", "flute radius from the chord: r = (w^2 / 4 + d^2) / 2d",
                   "craft.cut flute by flute (the cutters overlap each other)", "craft.safe_fillet full-round lip",
                   "recessed foot ring"],
    "lessons": [
        "Concave flutes are cuts, not ribs: a cutter of radius r sunk d into the wall leaves a groove of width "
        "w = 2 sqrt(2 r d - d^2). Choose the width from the pitch (pitch minus a thin arris) and the depth from the "
        "wall, then solve r = (w^2 / 4 + d^2) / 2d. The arris between flutes is what catches the light.",
        "On a tapered body the pitch grows with the radius, so each cutter is a cone whose radius grows along the "
        "slant: the flutes keep the same depth and arris from foot to lip, as on turned or moulded glass.",
        "End flutes in a round, not a cut: a cutter whose ends are half-spheres gives the scoop end of a classical "
        "flute and leaves no sharp ledge for dirt. Draw it as ONE revolved outline: a cone plus two spheres of the "
        "same radius touch tangentially, and tangent booleans are where OCCT silently drops tools. Neighbouring "
        "cutters overlap outside the wall, so cut them one by one rather than as a Compound.",
        "Leave a smooth band under the lip (the mouth touches it) and round the lip fully: half the wall each side, so "
        "it reads thin and soft; a square lip feels like a beaker.",
        "Weight goes low: a 5 mm base and a recessed foot (it stands on a ring, so it does not rock on a slightly "
        "domed first layer or a wet table).",
    ],
}


class Design(Recipe):
    title, summary = "Fluted tumbler", "Tapered tumbler with concave flutes, a smooth lip band and a recessed foot."
    solids = 1
    photo_color = "#dcd6cc"
    params = [
        Param("height", "Height", 110, 70, 160, 1, "mm", "form", "body"),
        Param("foot_d", "Foot diameter", 70, 50, 90, 0.5, "mm", "form", "body"),
        Param("flare", "Flare (lip - foot diameter)", 14, 0, 30, 0.5, "mm", "form", "body"),
        Param("wall", "Wall", 3.0, 2.4, 4.0, 0.1, "mm", "form", "body"),
        Param("flutes", "Flutes", 20, 14, 36, 1, "", "form", "flutes"),
        Param("flute_depth", "Flute depth", 1.2, 0.8, 1.6, 0.05, "mm", "form", "flutes",
              "Leaves at least 0.8 mm of the wall at the flute root."),
        Param("arris", "Arris between flutes", 0.8, 0.4, 3.0, 0.1, "mm", "form", "flutes"),
        Param("lip_band", "Smooth band under the lip", 16, 12, 30, 1, "mm", "form", "lip"),
    ]
    features = [Feature("body", "Tapered cup", "structure"), Feature("flutes", "Concave flutes", "finish"),
                Feature("lip", "Rounded lip", "finish"), Feature("foot", "Recessed foot", "structure")]

    def constraints(self, v):
        if v["wall"] - v["flute_depth"] < 0.8:
            return [RecipeError("The flutes leave under 0.8 mm of wall", "flutes", "Thicken the wall or make the flutes "
                                "shallower.", ["wall", "flute_depth"])]
        if math.pi * v["foot_d"] / v["flutes"] < v["arris"] + 4:
            return [RecipeError("The flutes are too narrow at the foot", "flutes", "Use fewer flutes.", ["flutes"])]
        return []

    def build(self, v):
        H, rb, rt, t = v["height"], v["foot_d"] / 2, (v["foot_d"] + v["flare"]) / 2, v["wall"]
        al = math.atan2(rt - rb, H)
        r = lambda z: rb + (rt - rb) * z / H
        tc, bt = t / math.cos(al), 5.0
        outer = craft.revolve_profile([(0, 0), (rb, 0), (rt, H), (0, H)])
        inner = craft.revolve_profile([(0, bt), (r(bt) - tc, bt), (rt - tc, H + 1), (0, H + 1)])
        inner = craft.safe_fillet(inner, [e for e in inner.edges() if abs(e.center().Z - bt) < 0.01], 6.0)
        body = outer - inner
        stages = [Stage("body", body)]

        # --- snippet: concave round-ended flutes on a tapered wall (one revolved capsule cutter per flute)
        n, d, ar = int(v["flutes"]), v["flute_depth"], v["arris"]
        z0, z1 = 12.0, H - v["lip_band"]

        def rad(z):                                   # cutter radius that leaves the arris at this height
            w = 2 * math.pi * r(z) / n - ar
            return (w * w / 4 + d * d) / (2 * d)
        r0, r1 = rad(z0), rad(z1)
        for i in range(n):
            a = 2 * math.pi * (i + 0.5) / n             # half a pitch off the revolve seam at +X
            u = Vector(math.cos(a), math.sin(a), 0)
            A = u * (r(z0) + r0 - d) + Vector(0, 0, z0)
            B = u * (r(z1) + r1 - d) + Vector(0, 0, z1)
            Lc = (B - A).length
            # the capsule's half outline (radius, along the axis): a round end, the tapered side, a round end. One
            # revolved solid: a cone with separate end spheres would be tangent to them, and tangent booleans fail.
            k = math.sqrt(0.5)
            prof = Wire([ThreePointArc((0, 0, -r0), (r0 * k, 0, -r0 * k), (r0, 0, 0)),
                         Line((r0, 0, 0), (r1, 0, Lc)),
                         ThreePointArc((r1, 0, Lc), (r1 * k, 0, Lc + r1 * k), (0, 0, Lc + r1)),
                         Line((0, 0, Lc + r1), (0, 0, -r0))])
            capsule = revolve(make_face(prof), Axis.Z)
            # the capsule's revolve seam faces outward (+u), where it never meets the cup or the neighbouring flutes
            ax = (B - A).normalized()
            tool = Plane(origin=A, x_dir=u - ax * u.dot(ax), z_dir=ax) * capsule
            for turn in (0.0, 0.05, -0.08, 0.13):        # a cut that silently removes nothing: turn it a hair, retry
                cut = craft.cut(body, Rot(0, 0, turn) * tool)
                if body.volume - cut.volume > 1.0:
                    break
            body = cut
        # --- end snippet
        stages.append(Stage("flutes", body))

        rim = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Z - H) < 0.01]
        body = craft.safe_fillet(body, rim, t / 2 - 0.05)
        stages.append(Stage("lip", body))

        # recessed foot: it stands on a 4 mm ring
        rf = rb - 4.0
        body = body - Pos(0, 0, -0.01) * Cylinder(rf, 1.2, align=BOTTOM)
        edges = [e for e in body.edges() if e.geom_type.name == "CIRCLE" and e.center().Z < 1.3]
        body = craft.safe_fillet(body, [e for e in edges if e.radius > rb - 0.1], 1.5)
        body = craft.safe_fillet(body, [e for e in body.edges() if e.geom_type.name == "CIRCLE"
                                        and abs(e.center().Z) < 0.01 and abs(e.radius - rf) < 0.01], 0.8)
        stages.append(Stage("foot", body))
        return parts.checked(stages)

    def derived(self, v):
        H, rb, rt, t = v["height"], v["foot_d"] / 2, (v["foot_d"] + v["flare"]) / 2, v["wall"]
        a, b, h = rb - t, rt - t, H - 5.0
        d = v["flute_depth"]
        w = lambda R: 2 * math.pi * R / v["flutes"] - v["arris"]
        return [{"key": "capacity_ml", "label": "Capacity to the brim", "value": round(math.pi * h / 3 * (a * a + a * b + b * b) / 1000),
                 "unit": "ml", "feature": "body", "formula": "frustum of the inside", "interface": False},
                {"key": "flute_r_foot", "label": "Flute radius at the foot", "value": round((w(rb) ** 2 / 4 + d * d) / (2 * d), 2),
                 "unit": "mm", "feature": "flutes", "formula": "(w^2 / 4 + d^2) / 2d, w = pitch - arris", "interface": False},
                {"key": "flute_root_wall", "label": "Wall at the flute root", "value": round(t - d, 2), "unit": "mm",
                 "feature": "flutes", "formula": "wall - flute depth", "interface": False}]
