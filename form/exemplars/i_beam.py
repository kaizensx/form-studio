"""I-beam with root fillets, a row of web lightening holes, bolt holes through the flanges at both ends and chamfered
ends, built one feature at a time. Ported from the "Polylines" seed in CADEvolve's hand-written CadQuery examples
(kulibinai/CADEvolve, Apache-2.0) and modified: rewritten for build123d and Form Studio's FeatureDesign. Form Studio
exemplar design."""
from build123d import Axis, Cylinder, Plane, Polyline, Pos, SlotOverall, extrude, make_face, mirror

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "I-beam with lightening holes and bolted ends",
    "category": "mechanical",
    "tags": ["i-beam", "i beam", "h-beam", "beam", "girder", "structural", "section", "profile", "extrusion",
             "flange", "web", "lightening holes", "bolt holes", "root fillet", "polyline", "mirror", "frame",
             "cross member", "rail"],
    "techniques": ["half section as a Polyline, mirrored about the web (mirror) and made a face, then extruded",
                   "root fillets picked as the edges that run along the beam at the web-flange corners",
                   "a row of obround lightening holes (SlotOverall) cut through the web, kept clear of the ends",
                   "bolt holes through both flanges at each end", "chamfered flange tips at the ends"],
    "lessons": [
        "Draw half a symmetric section and mirror it: the two halves cannot drift apart when a number changes, and "
        "the section has one parameter per real dimension (height, flange width, web and flange thickness).",
        "Pick fillet edges by what they are, not by their index: the root fillets are the edges parallel to the beam "
        "axis that lie inside the flange width and between the flanges, so they stay right when the size changes.",
        "Lightening holes belong in the middle of the web, away from the flanges (bending is carried there) and away "
        "from the ends (the bolts bring the load in there): keep most of a section height of solid web at each end.",
        "Check the section before building it: a web thicker than the flange width, or flanges that meet, is not "
        "an I-beam; constraints() says which number to change.",
        "Polyline + mirror + make_face is the build123d form of CadQuery's polyline().mirrorY().extrude().",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/cadquery_examples.txt", "seed": "Polylines", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}


class Design(FeatureDesign):
    title, summary = "I-beam", ("A mirrored I section extruded to length, with root fillets, web lightening holes, "
                                "bolt holes through both flanges at each end and chamfered ends.")
    params = [
        Param("length", "Length", 240, 80, 600, 5, "mm", "brief", "section"),
        Param("height", "Section height", 60, 30, 160, 1, "mm", "brief", "section"),
        Param("flange_w", "Flange width", 40, 20, 120, 1, "mm", "form", "section"),
        Param("web_t", "Web thickness", 4, 2, 12, 0.5, "mm", "form", "section"),
        Param("flange_t", "Flange thickness", 5, 2, 16, 0.5, "mm", "form", "section"),
        Param("root_r", "Root fillet", 3, 0, 10, 0.5, "mm", "form", "roots"),
        Param("holes", "Lightening holes", 3, 0, 12, 1, "", "form", "lightening"),
        Param("bolt_d", "Bolt hole", 6.6, 3.4, 13.5, 0.1, "mm", "interface", "bolts", "M6 clearance (ISO 273 medium)."),
    ]

    def constraints(self, v):
        out = []
        if v["web_t"] >= v["flange_w"] * 0.5:
            out.append(RecipeError("The web is too thick for the flanges", "section",
                                   "Keep the web under half the flange width.", ["web_t", "flange_w"]))
        if 2 * v["flange_t"] + 2 * v["root_r"] + 6 > v["height"]:
            out.append(RecipeError("The flanges and root fillets leave no web", "section",
                                   "Make the section taller, or the flanges or fillets thinner.",
                                   ["height", "flange_t", "root_r"]))
        if v["bolt_d"] + 4 > (v["flange_w"] - v["web_t"]) / 2:
            out.append(RecipeError("The bolt hole does not fit beside the web", "bolts",
                                   "Use a smaller bolt or a wider flange.", ["bolt_d", "flange_w"]))
        return out

    @feature("Section")                                     # the skeleton: half the I, mirrored, extruded along X
    def section(self, v, body):
        H, W, tw, tf = v["height"] / 2, v["flange_w"] / 2, v["web_t"] / 2, v["flange_t"]
        half = [(0, H), (W, H), (W, H - tf), (tw, H - tf), (tw, tf - H), (W, tf - H), (W, -H), (0, -H)]
        line = Polyline(*half)
        face = make_face([line, mirror(line, Plane.YZ)])
        return extrude(Plane.YZ * face, v["length"])

    @feature("Root fillets", role="finish")
    def roots(self, v, body):
        if v["root_r"] <= 0:
            return body
        lim = v["height"] / 2 - v["flange_t"] + 0.01
        edges = [e for e in body.edges().filter_by(Axis.X)
                 if abs(e.center().Y) < v["web_t"] / 2 + 0.01 and abs(e.center().Z) <= lim]
        return craft.safe_fillet(body, edges, v["root_r"])

    @feature("Lightening holes", role="structure")
    def lightening(self, v, body):
        n = int(round(v["holes"]))
        if n == 0:
            return body
        clear = v["height"] - 2 * v["flange_t"] - 2 * v["root_r"]
        h = clear * 0.6                                     # 20 % of the clear web left above and below each hole
        span = v["length"] - 1.6 * v["height"]              # 0.8 section height of solid web at each end
        pitch = span / n
        if pitch < h * 1.4:
            raise RecipeError("The lightening holes do not fit along the web", "lightening",
                              "Use fewer holes or a longer beam.", ["holes", "length"])
        w = min(pitch - h * 0.5, h * 2.2)
        for i in range(n):
            x = 0.8 * v["height"] + pitch * (i + 0.5)
            slot = Plane.XZ * Pos(x, 0) * SlotOverall(w, h)
            body = body - extrude(slot, v["web_t"] * 2, both=True)
        return body

    @feature("Bolt holes", role="interface")
    def bolts(self, v, body):
        y = (v["web_t"] / 2 + v["flange_w"] / 2) / 2         # midway between the web face and the flange tip
        for x in (v["height"] * 0.4, v["length"] - v["height"] * 0.4):
            for sy in (1, -1):
                body = body - Pos(x, sy * y, 0) * Cylinder(v["bolt_d"] / 2, v["height"] + 2)
        return body

    @feature("End chamfers", role="finish")
    def ends(self, v, body):
        edges = [e for e in body.edges().filter_by(Axis.Z)
                 if abs(abs(e.center().Y) - v["flange_w"] / 2) < 0.01 and
                 (e.center().X < 0.01 or e.center().X > v["length"] - 0.01)]
        return craft.safe_chamfer(body, edges, min(1.0, v["flange_t"] * 0.3))
