"""Flat pocket flask after the classic OpenCascade bottle: a lens-shaped section of two arcs extruded to height, every
edge rounded, hollowed to an even wall, a neck tube that opens it, and a rolled bead round the
mouth. Ported from "The Classic OCC Bottle" seed in CADEvolve's hand-written CadQuery examples (kulibinai/CADEvolve,
Apache-2.0) and modified: rewritten for build123d and Form Studio's FeatureDesign, hollowed before the neck so the
offset never meets the neck. Form Studio exemplar design."""
from build123d import Align, Axis, Cylinder, Kind, Line, Pos, ThreePointArc, Torus, extrude, make_face, offset

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Flat flask (the OCC bottle, hollowed)",
    "category": "consumer",
    "tags": ["flask", "bottle", "hip flask", "pocket flask", "occ bottle", "opencascade bottle", "container",
             "vessel", "neck", "mouth", "bead", "shell", "hollow", "wall", "arc", "lens section", "fillet"],
    "techniques": ["the section as two ThreePointArcs joined by short flats, made a face and extruded",
                   "every edge of the body rounded before anything is added (big radius, whole body)",
                   "hollowed closed: the body minus its own arc offset inward by the wall (offset, Kind.ARC)",
                   "the neck added afterwards as a tube reaching through the wall, its bore opening the void",
                   "a rolled bead (Torus) round the mouth, added after hollowing so it stays solid"],
    "lessons": [
        "Fillet before you hollow: an arc offset follows the rounds and gives an even wall; hollowing a sharp box and "
        "rounding it afterwards leaves thin corners or fails.",
        "Hollow the simple body, then add the neck: offsetting the body with the neck already on fails where the "
        "neck meets the rounded top (OCCT cannot offset that junction). A tube added afterwards, sunk through the "
        "wall, with a bore that reaches the void, gives the same part every time.",
        "Keep the fillet radius under half the thinnest dimension of the body (here the flask's depth), or OCCT "
        "cannot roll the ball round the edge; constraints() says which number to change.",
        "Add solid details (the bead) after the shell: anything added before is hollowed too.",
        "The classic OCC bottle is a good drill for a section made of arcs: draw one half, then mirror or repeat it, "
        "so both sides stay equal when the sizes change.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/cadquery_examples.txt", "seed": "The Classic OCC Bottle", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}


class Design(FeatureDesign):
    title, summary = "Flat flask", ("A lens-section flask with rounded edges, a neck and a rolled bead, shelled to "
                                    "an even wall.")
    params = [
        Param("width", "Width", 80, 40, 160, 1, "mm", "brief", "body"),
        Param("flat", "Depth at the sides", 18, 8, 50, 0.5, "mm", "form", "body"),
        Param("bulge", "Extra depth at the middle", 10, 0, 30, 0.5, "mm", "form", "body"),
        Param("height", "Body height", 110, 40, 250, 1, "mm", "brief", "body"),
        Param("r", "Edge radius", 6, 1, 15, 0.5, "mm", "form", "rounds"),
        Param("neck_d", "Neck diameter", 22, 10, 40, 0.5, "mm", "interface", "neck"),
        Param("neck_h", "Neck height", 16, 5, 40, 0.5, "mm", "form", "neck"),
        Param("wall", "Wall", 1.6, 0.8, 4, 0.1, "mm", "form", "hollow"),
    ]

    def constraints(self, v):
        out = []
        if v["r"] >= v["flat"] / 2:
            out.append(RecipeError("The edge radius is too large for the flask's depth", "rounds",
                                   "Keep the radius under half the depth at the sides.", ["r", "flat"]))
        if v["neck_d"] > v["flat"] + v["bulge"] - 2 * v["wall"] - 2:
            out.append(RecipeError("The neck is deeper than the flask", "neck", "Use a narrower neck or a deeper "
                                   "flask.", ["neck_d", "flat", "bulge"]))
        return out

    @feature("Body")                                        # the skeleton: the lens section extruded up Z
    def body(self, v, body):
        return self._lens(v, 0.0)

    def _lens(self, v, inset):
        """The lens section extruded to height, everything moved in by `inset` (the inside of the wall when > 0)."""
        a, w, t = v["width"] / 2 - inset, v["flat"] / 2 - inset, v["bulge"] / 2
        edges = [Line((-a, -w), (-a, w)), ThreePointArc((-a, w), (0, w + t), (a, w)), Line((a, w), (a, -w)),
                 ThreePointArc((a, -w), (0, -w - t), (-a, -w))]
        return Pos(0, 0, inset) * extrude(make_face(edges), v["height"] - 2 * inset)

    @feature("Rounds", role="finish")
    def rounds(self, v, body):
        return craft.safe_fillet(body, body.edges(), v["r"])

    @feature("Hollow")
    def hollow(self, v, body):
        # hollow the rounded body closed: the inside is the body offset inward by the wall (an arc offset follows the
        # rounds, so the wall is even); the neck opens it afterwards
        inside = offset(body, amount=-v["wall"], kind=Kind.ARC)
        return body - inside

    @feature("Neck", role="interface")
    def neck(self, v, body):
        up = (Align.CENTER, Align.CENTER, Align.MIN)
        tube = Pos(0, 0, v["height"] - v["wall"] - 0.2) * Cylinder(v["neck_d"] / 2, v["neck_h"] + v["wall"] + 0.2, align=up)
        body = craft.safe_union(body, tube)
        bore = Pos(0, 0, v["height"] - 2 * v["wall"] - 1) * Cylinder(v["neck_d"] / 2 - v["wall"],
                                                                     v["neck_h"] + 2 * v["wall"] + 2, align=up)
        return body - bore

    @feature("Mouth bead", role="finish")
    def bead(self, v, body):
        z = v["height"] + v["neck_h"] - 2.5
        ring = Pos(0, 0, z) * Torus(v["neck_d"] / 2, 1.2)
        body = craft.safe_union(body, ring)
        lip = [e for e in body.edges().filter_by(Axis.Z, reverse=True)
               if abs(e.center().Z - (v["height"] + v["neck_h"])) < 0.01]
        return craft.safe_fillet(body, lip, v["wall"] * 0.4)
