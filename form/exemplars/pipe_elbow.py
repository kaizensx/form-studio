"""Flanged 90 degree pipe elbow: a bend revolved about a centre line, short straight tangents at both ends, a bore
through the whole run, a bolted flange on each end with a bolt circle, and fillets where the flanges meet the pipe.
Ported from the "quarter_torus" and "pipe_sweep" seed generators in CADEvolve's evolution pipeline
(kulibinai/CADEvolve, Apache-2.0) and modified: rewritten for build123d and Form Studio's FeatureDesign and made into
a part. Form Studio exemplar design."""
import math

from build123d import Align, Axis, Circle, Cylinder, GeomType, Plane, Pos, Rot, revolve

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Flanged 90 degree pipe elbow",
    "category": "mechanical",
    "tags": ["pipe elbow", "elbow", "bend", "90 degree", "pipe", "tube", "duct", "flange", "flanged", "bolt circle",
             "fitting", "plumbing", "torus", "revolve", "sweep", "manifold", "adapter"],
    "techniques": ["the bend as a circle revolved 90 deg about an axis one bend radius away (revolve)",
                   "straight tangents at both ends so the flanges sit square to the flow",
                   "the bore cut once along the same path (inner circle revolved, inner cylinders)",
                   "flanges placed with a Plane at each end of the path, bolt holes on a bolt circle",
                   "fillets at the flange roots, chosen as circles on the flange faces at the pipe's radius"],
    "lessons": [
        "Build a bend about its centre line: draw the pipe's section where the bend starts and revolve it about an "
        "axis one bend radius away. The bore is the same revolve with the inner radius, so the wall is exact.",
        "Give a bend a straight tangent at each end, about half a diameter long: a flange bolted straight onto the "
        "curve is not square, and the bolts cannot be reached.",
        "Keep every end on a known Plane (origin at the end, normal along the flow): flanges, bolt circles and the "
        "bore are then placed by the same Plane and cannot drift apart.",
        "A bend radius of 1 to 1.5 diameters (short / long radius elbow) is the usual choice; tighter bends raise "
        "the pressure loss and thin the outer wall when it is bent rather than modelled.",
        "Bolt holes straddle the centre lines (offset by half the pitch angle), so the elbow can be bolted to a "
        "flange that is level.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/pipeline.py (seed_primitives)", "seed": "quarter_torus, pipe_sweep",
               "licence": "Apache-2.0", "modified": "modified (ported to build123d / Form Studio)"},
}


class Design(FeatureDesign):
    title, summary = "Pipe elbow", ("A 90 deg elbow with straight tangents, a through bore and a bolted flange on "
                                    "each end.")
    params = [
        Param("bore", "Bore", 40, 10, 150, 0.5, "mm", "brief", "bore"),
        Param("wall", "Wall", 4, 1.5, 12, 0.1, "mm", "form", "bend"),
        Param("bend_r", "Bend radius (centre line)", 60, 20, 300, 1, "mm", "form", "bend", "1-1.5 x the outside diameter."),
        Param("tangent", "Straight tangent", 20, 0, 100, 1, "mm", "form", "bend"),
        Param("flange_d", "Flange diameter", 100, 30, 300, 1, "mm", "interface", "flanges"),
        Param("flange_t", "Flange thickness", 8, 3, 25, 0.5, "mm", "form", "flanges"),
        Param("bolts", "Bolts per flange", 4, 3, 12, 1, "", "interface", "bolt_holes"),
        Param("bolt_d", "Bolt hole", 9, 3.4, 22, 0.1, "mm", "interface", "bolt_holes", "M8 clearance."),
    ]

    def setup(self, v):
        ro = v["bore"] / 2 + v["wall"]
        R, T = v["bend_r"], v["tangent"]
        # the bend turns about the Y axis from (R, 0, 0) (flow +Z) to (0, 0, R) (flow -X); each end is a Plane at the
        # end of its tangent with its normal pointing out of the pipe
        ends = [Plane(origin=(R, 0, -T), z_dir=(0, 0, -1)), Plane(origin=(-T, 0, R), z_dir=(-1, 0, 0))]
        return {"ro": ro, "ends": ends, "pcd": (v["flange_d"] / 2 + ro) / 2}

    def constraints(self, v):
        ro = v["bore"] / 2 + v["wall"]
        out = []
        if v["bend_r"] < ro * 1.05:
            out.append(RecipeError("The bend radius is smaller than the pipe", "bend",
                                   "Use a bend radius of at least the pipe's outside radius.", ["bend_r", "bore"]))
        if v["flange_d"] / 2 - ro < v["bolt_d"] * 2 + 2:
            out.append(RecipeError("No room for the bolts between the pipe and the flange rim", "bolt_holes",
                                   "Make the flange larger or the bolts smaller.", ["flange_d", "bolt_d"]))
        return out

    def _run(self, v, r):
        """The pipe's run (bend and tangents) as a solid of radius r."""
        R, T = v["bend_r"], v["tangent"]
        bend = revolve(Plane.XY * Pos(R, 0) * Circle(r), Axis.Y, -90)       # +X end up to the +Z end
        if T <= 0:
            return bend
        # the tangents meet the bend's end faces exactly: an overlap of a cylinder into a torus leaves a sliver that
        # OCCT does not fuse, while two coincident circular faces fuse cleanly
        a = Pos(R, 0, -T) * Cylinder(r, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
        b = Pos(-T, 0, R) * Rot(0, 90, 0) * Cylinder(r, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return bend + a + b

    @feature("Bend")                                        # the skeleton: the solid run, outer radius
    def bend(self, v, body):
        return self._run(v, self.ctx["ro"])

    @feature("Flanges", role="interface")
    def flanges(self, v, body):
        for pl in self.ctx["ends"]:
            disc = pl * Cylinder(v["flange_d"] / 2, v["flange_t"], align=(Align.CENTER, Align.CENTER, Align.MAX))
            body = craft.safe_union(body, disc)
        return body

    @feature("Flange roots", role="finish")
    def roots(self, v, body):
        ro = self.ctx["ro"]
        edges = []
        for pl in self.ctx["ends"]:
            face_pt = pl.origin - pl.z_dir * v["flange_t"]
            edges += [e for e in body.edges().filter_by(GeomType.CIRCLE)          # the pipe's circle on the flange
                      if (e.arc_center - face_pt).length < 0.05 and abs(e.radius - ro) < 0.05]
        return craft.safe_fillet(body, edges, min(v["wall"] * 1.2, 6))

    @feature("Bore")
    def bore(self, v, body):
        cutter = self._run(v, v["bore"] / 2)
        for pl in self.ctx["ends"]:                         # through the flanges too
            cutter += pl * Cylinder(v["bore"] / 2, v["flange_t"] + 2, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        return body - cutter

    @feature("Bolt holes", role="interface")
    def bolt_holes(self, v, body):
        n = int(round(v["bolts"]))
        for pl in self.ctx["ends"]:
            for i in range(n):
                a = math.radians(360 * (i + 0.5) / n)
                hole = Pos(self.ctx["pcd"] * math.cos(a), self.ctx["pcd"] * math.sin(a), 0) * \
                    Cylinder(v["bolt_d"] / 2, 3 * v["flange_t"])
                body = body - pl * hole
        return body
