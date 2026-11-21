"""Compression spring with closed and ground ends: a round wire swept along a helix whose pitch eases from touching
coils at each end to the working pitch in the middle, then ground flat at both ends so it stands square. Ported from
the "helix_wire" seed generator in CADEvolve's evolution pipeline (kulibinai/CADEvolve, Apache-2.0) and modified:
rewritten for build123d and Form Studio's FeatureDesign, with variable pitch, closed ends and grinding. Form Studio
exemplar design."""
import math

from build123d import Align, Box, Circle, Pos, Spline

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Compression spring, closed and ground ends",
    "category": "mechanical",
    "tags": ["spring", "compression spring", "coil spring", "helix", "helical", "coil", "wire", "sweep", "pitch",
             "variable pitch", "closed ends", "ground ends", "suspension", "return spring", "mechanism"],
    "techniques": ["the centre line computed as points: angle -> (r cos, r sin, z) with the pitch integrated turn by "
                   "turn, so the pitch can vary smoothly", "a Spline through the points as the sweep path",
                   "a Circle placed on the path's start plane (craft.plane_on_path) and swept (craft.safe_sweep)",
                   "closed ends: one turn at the wire's own pitch, blended into the working pitch with a smoothstep",
                   "ground ends: the swept coil intersected with a box between the two end planes"],
    "lessons": [
        "A real compression spring is not a constant-pitch helix: its end turns are closed (pitch = wire diameter) "
        "and ground flat so it stands square and pushes evenly. Compute the centre line yourself and vary the pitch "
        "along it; Edge.make_helix only does a constant pitch.",
        "Blend pitch changes smoothly (a smoothstep over half a turn): a sudden change puts a kink in the path and "
        "the sweep twists or fails at it.",
        "Place the profile on the path's start plane before sweeping (craft.plane_on_path(path, 0)); a profile left "
        "on XY sweeps into a flattened or self-intersecting tube.",
        "Grinding is an intersection: keep what lies between the two end planes. Grind about half a wire diameter off "
        "each end so the flats are wide enough to stand on.",
        "Check the solid length (all coils touching) against the travel you need: total turns x wire diameter is the "
        "shortest the spring can ever get.",
    ],
    "origin": {"repo": "kulibinai/CADEvolve", "sha": "e30e6358648df661247815c67414cd42079f8b41",
               "path": "evolution/pipeline.py (seed_primitives)", "seed": "helix_wire", "licence": "Apache-2.0",
               "modified": "modified (ported to build123d / Form Studio)"},
}

STEPS = 24                          # path points per turn


def _smooth(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class Design(FeatureDesign):
    title, summary = "Compression spring", ("A round-wire compression spring with closed, ground ends and a smoothly "
                                            "varying pitch.")
    params = [
        Param("mean_d", "Mean coil diameter", 16, 4, 80, 0.5, "mm", "brief", "coil"),
        Param("wire_d", "Wire diameter", 1.8, 0.5, 8, 0.1, "mm", "brief", "coil"),
        Param("free_l", "Free length", 40, 8, 200, 0.5, "mm", "brief", "coil"),
        Param("active", "Active turns", 6, 2, 20, 0.5, "", "form", "coil"),
        Param("end_turns", "Closed turns at each end", 1, 0.5, 2, 0.25, "", "form", "coil"),
    ]

    def setup(self, v):
        d, e, n = v["wire_d"], v["end_turns"], v["active"]
        total = n + 2 * e
        grind = d / 2                                         # ground off each end
        # the centre line runs from z = 0 to z = free_l + 2 * grind; the active pitch takes what the closed ends leave
        rise = v["free_l"] + 2 * grind
        p_act = (rise - 2 * e * d) / n
        pts, z, r = [], 0.0, v["mean_d"] / 2
        k = int(math.ceil(total * STEPS))
        dt = total / k
        for i in range(k + 1):
            t = i * dt
            blend = min(_smooth((t - e + 0.25) / 0.5), _smooth((total - e + 0.25 - t) / 0.5))
            pitch = d + (p_act - d) * blend
            if i:
                z += pitch * dt
            a = 2 * math.pi * t
            pts.append((r * math.cos(a), r * math.sin(a), z))
        scale = rise / z                                      # the blends are symmetric; land exactly on the rise
        return {"pts": [(x, y, zz * scale) for x, y, zz in pts], "grind": grind, "p_act": p_act,
                "solid_l": (total + 1) * d}

    def constraints(self, v):
        out = []
        if v["mean_d"] < 3 * v["wire_d"]:
            out.append(RecipeError("The coil is too tight for the wire (spring index under 3)", "coil",
                                   "Use a larger coil or a thinner wire.", ["mean_d", "wire_d"]))
        s = self.setup(v)
        if s["p_act"] < v["wire_d"] * 1.2:
            out.append(RecipeError("The active coils touch: no travel left", "coil",
                                   "Make the spring longer or use fewer turns.", ["free_l", "active"]))
        return out

    def derived(self, v):
        s = self.setup(v)
        return [{"key": "pitch", "label": "Active pitch", "value": round(s["p_act"], 2), "unit": "mm", "feature": "coil",
                 "formula": "(free length + wire - 2 x end turns x wire) / active turns"},
                {"key": "solid_length", "label": "Solid length (all coils touching)", "value": round(s["solid_l"], 1),
                 "unit": "mm", "feature": "coil", "formula": "(active + 2 x end turns + 1) x wire, approximate"}]

    @feature("Coil")                                        # the skeleton: the wire swept along the centre line
    def coil(self, v, body):
        path = Spline(*self.ctx["pts"])
        profile = craft.plane_on_path(path, 0.0) * Circle(v["wire_d"] / 2)
        return craft.safe_sweep(profile, path, frenet=True)

    @feature("Ground ends", role="interface")
    def ends(self, v, body):
        g = self.ctx["grind"]
        keep = Pos(0, 0, g) * Box(v["mean_d"] * 2, v["mean_d"] * 2, v["free_l"], align=(Align.CENTER, Align.CENTER,
                                                                                         Align.MIN))
        return Pos(0, 0, -g) * craft.safe_intersect(body, keep)
