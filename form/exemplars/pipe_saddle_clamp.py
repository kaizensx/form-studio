"""Pipe saddle clamp: a strap that wraps a pipe and holds it against a wall, with two ears for countersunk screws, a
stiffening bead along the crown and rounded corners. Ported from the "half_cylinder" seed generator in CADEvolve's
evolution pipeline (kulibinai/CADEvolve, Apache-2.0) and modified: rewritten for build123d and Form Studio's
FeatureDesign and made into a product. Form Studio exemplar design."""
from build123d import Align, Axis, Box, Cone, Cylinder, Plane, Pos, Rot, extrude, make_face, Polyline, ThreePointArc

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Pipe saddle clamp",
    "category": "mechanical",
    "tags": ["pipe clamp", "pipe clip", "saddle clamp", "saddle clip", "strap", "conduit", "tube",
             "hose", "pipe", "wall mount", "bracket", "ears", "countersunk", "screw", "mount", "half cylinder",
             "clip"],
    "techniques": ["the strap as one U profile (legs + half ring) in XZ, extruded along the pipe",
                   "the pipe's centre one radius off the wall, so the strap's legs are straight",
                   "a gap under the crown (pinch) so tightening the screws clamps the pipe",
                   "ears as a separate box unioned to the legs, then the inside corner filleted",
                   "countersunk screw holes from a Cylinder and a Cone", "a stiffening bead on the crown"],
    "lessons": [
        "Clamp, do not just cover: make the strap's inside a little smaller than the pipe in height (pinch), so the "
        "screws pull it down onto the pipe; a strap that only touches rattles.",
        "Draw the strap as one closed profile (outer U, inner U) and extrude it: the wall thickness is then exact "
        "everywhere and a boolean of two cylinders is not needed.",
        "Fillet where the ear meets the leg: that inside corner is where a strap cracks when the screw is tightened.",
        "Countersink to the screw: a 90 deg cone whose top diameter is about twice the shank for a wood screw.",
        "A bead along the crown stiffens a thin strap more than making all of it thicker.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/pipeline.py (seed_primitives)", "seed": "half_cylinder", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}


class Design(FeatureDesign):
    title, summary = "Pipe saddle clamp", ("A strap that holds a pipe against a wall, with two countersunk screw "
                                           "ears and a stiffening bead.")
    params = [
        Param("pipe_d", "Pipe diameter", 22, 6, 110, 0.5, "mm", "brief", "strap", "Measure it: 15, 22, 28 mm copper."),
        Param("t", "Strap thickness", 3, 1.6, 6, 0.1, "mm", "form", "strap"),
        Param("width", "Strap width", 16, 8, 40, 0.5, "mm", "form", "strap"),
        Param("pinch", "Pinch", 0.4, 0, 1.5, 0.1, "mm", "interface", "strap",
              "How much smaller the strap is than the pipe, so the screws clamp it."),
        Param("ear", "Ear length", 14, 9, 30, 0.5, "mm", "form", "ears"),
        Param("screw_d", "Screw", 4.5, 3, 6, 0.1, "mm", "interface", "screws", "Shank clearance."),
        Param("bead", "Crown bead", 1.2, 0, 3, 0.1, "mm", "form", "bead"),
    ]

    def setup(self, v):
        r_in = v["pipe_d"] / 2 - v["pinch"] / 2
        return {"r_in": r_in, "r_out": r_in + v["t"], "zc": v["pipe_d"] / 2 - v["pinch"]}

    def constraints(self, v):
        if v["ear"] < v["screw_d"] * 2 + 3:
            return [RecipeError("The ears are too short for the screw heads", "ears",
                                "Lengthen the ears or use a smaller screw.", ["ear", "screw_d"])]
        return []

    @feature("Strap")                                       # the skeleton: a U strap; the wall is z = 0
    def strap(self, v, body):
        ri, ro, zc = self.ctx["r_in"], self.ctx["r_out"], self.ctx["zc"]
        wire = [Polyline((ri, 0), (ro, 0), (ro, zc)), ThreePointArc((ro, zc), (0, zc + ro), (-ro, zc)),
                Polyline((-ro, zc), (-ro, 0), (-ri, 0), (-ri, zc)), ThreePointArc((-ri, zc), (0, zc + ri), (ri, zc)),
                Polyline((ri, zc), (ri, 0))]                 # outer U, then back along the inner U
        return extrude(Plane.XZ * make_face(wire), v["width"] / 2, both=True)

    @feature("Ears")
    def ears(self, v, body):
        ro = self.ctx["r_out"]
        for sx in (1, -1):
            ear = Pos(sx * (ro + v["ear"] / 2 - 0.5), 0, 0) * Box(v["ear"] + 1, v["width"], v["t"],
                                                                  align=(Align.CENTER, Align.CENTER, Align.MIN))
            body = craft.safe_union(body, ear)
        roots = [e for e in body.edges().filter_by(Axis.Y)
                 if abs(abs(e.center().X) - ro) < 0.01 and abs(e.center().Z - v["t"]) < 0.01]
        return craft.safe_fillet(body, roots, v["t"] * 0.8)

    @feature("Crown bead")
    def bead(self, v, body):
        if v["bead"] <= 0:
            return body
        ring = Rot(90, 0, 0) * (Cylinder(self.ctx["r_out"] + v["bead"], v["bead"] * 2.5)
                                - Cylinder(self.ctx["r_out"] - 0.2, v["bead"] * 3))
        ring = Pos(0, 0, self.ctx["zc"]) * ring
        keep = Pos(0, 0, self.ctx["zc"]) * Box(4 * self.ctx["r_out"], 4 * v["bead"], 2 * self.ctx["r_out"],
                                                align=(Align.CENTER, Align.CENTER, Align.MIN))
        return craft.safe_union(body, ring & keep)

    @feature("Screw holes", role="interface")
    def screws(self, v, body):
        d, x = v["screw_d"], self.ctx["r_out"] + v["ear"] / 2
        for sx in (1, -1):
            at = Pos(sx * x, 0, 0)
            body = body - at * Cylinder(d / 2, v["t"] * 3)
            body = body - at * Pos(0, 0, v["t"] - d / 2) * Cone(d / 2, d + 0.02, d / 2 + 0.02,
                                                                align=(Align.CENTER, Align.CENTER, Align.MIN))
        return body

    @feature("Corners", role="finish")
    def corners(self, v, body):
        tips = [e for e in body.edges().filter_by(Axis.Z)
                if abs(abs(e.center().X) - (self.ctx["r_out"] + v["ear"])) < 0.6]
        return craft.safe_fillet(body, tips, min(v["width"] * 0.3, v["ear"] * 0.3))
