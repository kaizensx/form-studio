"""Two-part enclosure with screw posts: a rounded box modelled closed, four corner posts with pilot holes, the lid
split off along a plane, a locating lip under the lid notched round the posts, counterbored screw holes through the
lid, and the lid laid out beside the base, lip up, as a separate part. Ported from the "A Parametric Enclosure" seed
in CADEvolve's hand-written CadQuery examples (kulibinai/CADEvolve, Apache-2.0) and modified: rewritten for build123d
and Form Studio's FeatureDesign, the parts kept separate with craft.parts. Form Studio exemplar design."""
from build123d import Align, Box, Cylinder, Pos, RectangleRounded, Rot, extrude

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Two-part enclosure with screw posts and a lid lip",
    "category": "assembly",
    "tags": ["enclosure", "box", "project box", "electronics box", "case", "housing", "lid", "lip", "screw posts",
             "bosses", "standoffs", "counterbore", "self-tapping", "m3", "split", "two parts", "separate parts",
             "assembly", "rounded box"],
    "techniques": ["model the box closed (outside, cavity, posts, holes) and split the lid off last, so the lid and "
                   "the base always match", "vertical edges rounded in the sketch (RectangleRounded), top and bottom "
                   "edges filleted after", "the cavity's corners = outside radius - wall, so the wall is even",
                   "posts from the floor to the split plane; pilot holes for M3 self-tapping screws",
                   "a lip under the lid, a gap inside the walls, notched round each post",
                   "the lid flipped and laid beside the base; craft.parts keeps the two parts separate and measures "
                   "the gap"],
    "lessons": [
        "Model a box closed and split it last: the lid's outline, the screw holes and the posts are then cut in one "
        "body and line up by construction, whatever the sizes.",
        "An even wall needs matching corner radii: the cavity's corner radius is the outside radius minus the wall. "
        "A sharp inside corner under a rounded outside leaves the wall thin at the corner.",
        "A lid that only sits on the rim slides; a lip that drops inside the walls with a 0.2 mm gap locates it. "
        "Notch the lip round the posts rather than moving the posts.",
        "Self-tapping M3 screws in printed posts: 2.5 mm pilot, 3.4 mm clearance in the lid, post outside at least "
        "2.5 x the screw (8 mm). Stop the pilot 2 mm above the floor so nothing shows underneath.",
        "Parts of an assembly are never fused: lay them out apart and return craft.parts(base=..., lid=...), which "
        "checks they do not touch and records the gap.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/cadquery_examples.txt", "seed": "A Parametric Enclosure", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}

UP = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(FeatureDesign):
    title, summary = "Screw-post enclosure", ("A rounded two-part box: base with four screw posts, lid with a "
                                              "locating lip and counterbored screws.")
    solids = 2
    params = [
        Param("width", "Width", 80, 40, 250, 1, "mm", "brief", "box"),
        Param("length", "Length", 120, 40, 300, 1, "mm", "brief", "box"),
        Param("height", "Height", 40, 15, 150, 1, "mm", "brief", "box"),
        Param("wall", "Wall", 2.5, 1.6, 5, 0.1, "mm", "form", "cavity"),
        Param("side_r", "Corner radius", 8, 3, 25, 0.5, "mm", "form", "box"),
        Param("edge_r", "Top and bottom edge radius", 2, 0.5, 5, 0.25, "mm", "form", "box"),
        Param("inset", "Post inset", 9, 6, 30, 0.5, "mm", "interface", "posts", "Post centre from the outside edges."),
        Param("post_d", "Post diameter", 8, 6, 14, 0.5, "mm", "form", "posts"),
        Param("lip", "Lip height", 2.5, 0, 6, 0.5, "mm", "interface", "split"),
        Param("gap", "Lip gap", 0.2, 0.1, 0.5, 0.05, "mm", "interface", "split"),
    ]

    def setup(self, v):
        x, y = v["width"] / 2 - v["inset"], v["length"] / 2 - v["inset"]
        return {"posts": [(x, y), (-x, y), (-x, -y), (x, -y)], "split": v["height"] - v["wall"]}

    def constraints(self, v):
        out = []
        if v["side_r"] <= v["wall"] + 1:
            out.append(RecipeError("The corner radius is smaller than the wall", "box",
                                   "Use a corner radius at least 1 mm over the wall.", ["side_r", "wall"]))
        if v["inset"] - v["post_d"] / 2 < v["wall"] - 0.5:
            out.append(RecipeError("The posts run into the wall", "posts", "Increase the inset.", ["inset", "post_d"]))
        if v["edge_r"] >= v["wall"] * 1.5:
            out.append(RecipeError("The edge radius cuts through the wall", "box", "Use a smaller edge radius.",
                                   ["edge_r", "wall"]))
        return out

    @feature("Box")                                         # the skeleton: the closed outside
    def box(self, v, body):
        out = extrude(RectangleRounded(v["width"], v["length"], v["side_r"]), v["height"])
        flat = [e for e in out.edges() if abs(e.center().Z) < 0.01 or abs(e.center().Z - v["height"]) < 0.01]
        return craft.safe_fillet(out, flat, v["edge_r"])

    @feature("Cavity")
    def cavity(self, v, body):
        t = v["wall"]
        inside = extrude(RectangleRounded(v["width"] - 2 * t, v["length"] - 2 * t, v["side_r"] - t), v["height"] - 2 * t)
        return body - Pos(0, 0, t) * inside

    @feature("Screw posts", role="interface")
    def posts(self, v, body):
        t, top = v["wall"], self.ctx["split"]
        for x, y in self.ctx["posts"]:
            body = craft.safe_union(body, Pos(x, y, t - 0.01) * Cylinder(v["post_d"] / 2, top - t + 0.01, align=UP))
        return body

    @feature("Screw holes", role="interface")
    def holes(self, v, body):
        t, top = v["wall"], self.ctx["split"]
        for x, y in self.ctx["posts"]:
            body = body - Pos(x, y, t + 2) * Cylinder(1.25, v["height"], align=UP)            # M3 self-tapping pilot
            body = body - Pos(x, y, top) * Cylinder(1.7, t + 1, align=UP)                     # clearance in the lid
            body = body - Pos(x, y, v["height"] - 1.2) * Cylinder(3.2, 2, align=UP)          # head counterbore
        return body

    @feature("Lid split and lip", role="interface")
    def split(self, v, body):
        t, top = v["wall"], self.ctx["split"]
        big = max(v["width"], v["length"]) * 2
        lid = body & Pos(0, 0, top) * Box(big, big, v["height"], align=UP)
        base = body - Pos(0, 0, top) * Box(big, big, v["height"], align=UP)
        if v["lip"] > 0:
            g = v["gap"]
            w, l, r = v["width"] - 2 * t - 2 * g, v["length"] - 2 * t - 2 * g, v["side_r"] - t - g
            ring = extrude(RectangleRounded(w, l, r), v["lip"]) - \
                extrude(RectangleRounded(w - 2.4, l - 2.4, max(r - 1.2, 0.5)), v["lip"])
            for x, y in self.ctx["posts"]:                  # notch the lip round each post
                ring = ring - Pos(x, y, -1) * Cylinder(v["post_d"] / 2 + g + 0.3, v["lip"] + 2, align=UP)
            lid = craft.safe_union(lid, Pos(0, 0, top - v["lip"] + 0.01) * ring)
        # lay the lid beside the base, outside face down, lip up
        lid = Pos(v["width"] + 12, 0, v["height"]) * Rot(180, 0, 0) * lid
        return craft.parts(base=base, lid=lid, clearance=1.0)
