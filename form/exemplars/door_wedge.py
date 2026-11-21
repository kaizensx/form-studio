"""Door wedge: a tapered block with a blunt nose, grip grooves across the slope, a hanging hole through the tall end
and rounded edges everywhere a hand or a foot touches it. Ported from the "wedge_basic" seed generator in CADEvolve's
evolution pipeline (kulibinai/CADEvolve, Apache-2.0) and modified: rewritten for build123d and Form Studio's
FeatureDesign and made into a product. Form Studio exemplar design."""
import math

from build123d import Axis, Cylinder, Plane, Polygon, Pos, Rot, extrude

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Door wedge with grip grooves",
    "category": "consumer",
    "tags": ["door wedge", "door stop", "doorstop", "wedge", "shim", "chock", "ramp", "taper", "grip", "grooves",
             "ridges", "hanging hole", "household", "home"],
    "techniques": ["side profile as a Polygon in XZ, extruded across the width (a wedge is a 2-D shape)",
                   "a blunt nose instead of a knife edge (thin edges print badly and chip)",
                   "grip grooves placed along the slope from its angle (positions computed, not eyeballed)",
                   "a hanging hole through the tall end, across the width",
                   "edges rounded in order: vertical corners first, then the slope's long edges"],
    "lessons": [
        "Model a prismatic product from its side view: draw the profile in the plane it lives in (XZ) and extrude "
        "it across the width. Every dimension is then in one sketch.",
        "Never end a taper in a knife edge: keep a nose of at least 2-3 mm, so it prints, survives a kick and still "
        "slides under the door.",
        "Place repeated details along a sloped face with its angle: a point at distance s along the slope is "
        "(s cos a, h0 - s sin a); compute the positions once and cut every groove the same way.",
        "A slope of about 10-15 deg holds a door best: steeper wedges spring out, flatter ones need to be very long.",
        "Round the vertical corners first and the slope's long edges after; fillets on edges that meet at a corner "
        "go in from the biggest to the smallest.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/pipeline.py (seed_primitives)", "seed": "wedge_basic", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}


class Design(FeatureDesign):
    title, summary = "Door wedge", ("A tapered door wedge with a blunt nose, grip grooves on the slope and a "
                                    "hanging hole.")
    params = [
        Param("length", "Length", 130, 60, 220, 1, "mm", "brief", "wedge"),
        Param("width", "Width", 42, 25, 80, 1, "mm", "brief", "wedge"),
        Param("height", "Tall end height", 30, 12, 50, 0.5, "mm", "brief", "wedge"),
        Param("nose", "Nose height", 3, 2, 8, 0.25, "mm", "form", "wedge", "Keep it printable: never a knife edge."),
        Param("grooves", "Grip grooves", 7, 0, 16, 1, "", "form", "grip"),
        Param("groove_r", "Groove radius", 1.6, 0.8, 3, 0.1, "mm", "form", "grip"),
        Param("hole_d", "Hanging hole", 8, 0, 14, 0.5, "mm", "access", "hole"),
        Param("r", "Edge radius", 3, 0.5, 6, 0.25, "mm", "form", "edges"),
    ]

    def setup(self, v):
        a = math.atan2(v["height"] - v["nose"], v["length"])
        return {"angle": a, "slope": math.hypot(v["length"], v["height"] - v["nose"])}

    def constraints(self, v):
        if v["hole_d"] and v["hole_d"] + 6 > v["height"]:
            return [RecipeError("The hanging hole does not fit in the tall end", "hole",
                                "Use a smaller hole or a taller wedge.", ["hole_d", "height"])]
        return []

    @feature("Wedge")                                       # the skeleton: the side profile, extruded across Y
    def wedge(self, v, body):
        prof = Polygon((0, 0), (v["length"], 0), (v["length"], v["nose"]), (0, v["height"]), align=None)
        return extrude(Plane.XZ * prof, v["width"] / 2, both=True)

    @feature("Edges", role="finish")
    def edges(self, v, body):
        crest = [e for e in body.edges().filter_by(Axis.Y) if e.center().X < 0.01 and e.center().Z > 0.01]
        body = craft.safe_fillet(body, crest, min(v["r"] * 2, v["height"] * 0.3))      # where the hand grips
        sides = [e for e in body.edges() if abs(abs(e.center().Y) - v["width"] / 2) < 0.01 and e.center().Z > 0.5]
        return craft.safe_fillet(body, sides, min(v["r"], v["nose"] * 0.45))

    @feature("Grip grooves")
    def grip(self, v, body):
        n = int(round(v["grooves"]))
        if n == 0:
            return body
        a, s_len = self.ctx["angle"], self.ctx["slope"]
        for i in range(n):
            s = s_len * (0.18 + 0.6 * i / max(n - 1, 1))       # along the slope from the tall end
            x, z = s * math.cos(a), v["height"] - s * math.sin(a)
            groove = Pos(x, 0, z) * Rot(90, 0, 0) * Cylinder(v["groove_r"], v["width"] - 2 * v["r"] - 4)
            body = body - groove
        return body

    @feature("Hanging hole", role="access")
    def hole(self, v, body):
        if v["hole_d"] <= 0:
            return body
        x, z = v["hole_d"] / 2 + 5, v["height"] * 0.45
        return body - Pos(x, 0, z) * Rot(90, 0, 0) * Cylinder(v["hole_d"] / 2, v["width"] + 2)
