"""The changes manufacturability fixes write into a design (kernel side: called from a feature method).

A fix is a feature in the design's own source, so the person and the agent read, change, undo and optimise it like
any other. Each function picks the faces or edges it changes by a rule on the geometry the feature receives, not by
an index, so it still finds them when an earlier parameter changes:

    @feature("Draft for moulding", role="finish")
    def dfm_draft(self, v, body):
        from form.dfm import ops
        return ops.draft(body, pull=(0, 0, 1), angle=v["dfm_draft_deg"], neutral=-10.0)

    ops.draft(body, pull, angle, neutral)          every face along the pull tilted by angle (OCCT draft), about the
                                                    neutral plane normal to the pull at height `neutral`
    ops.round_corners(body, axes, radius)           every sharp internal edge along one of the axes, filleted
    ops.escape_holes(body, d, count)                count holes of diameter d from each enclosed void to the outside

A change that the kernel cannot make raises RecipeError naming the faces or edges, so the feature is left out with
the reason and the build says so. Nothing is reduced silently: a draft, a radius and a hole are made at their size
or not at all.
"""
from __future__ import annotations

import math

import numpy as np

from ..recipes.base import RecipeError
from . import geom


def _along(face, d) -> bool:
    """A face lying along the pull: a plane whose normal is normal to it, or a cylinder whose axis is it."""
    g = geom._gtype(face)
    if g == "PLANE":
        n = geom._vec(face.normal_at(face.center()))
        return abs(float(n @ d)) < 1e-6
    if g == "CYLINDER":
        cy = geom.cylinder_of(face)
        return cy is not None and abs(abs(float(cy[1] @ d)) - 1) < 1e-9
    return False


def draft(body, pull=(0.0, 0.0, 1.0), angle: float = 1.0, neutral: float | None = None):
    """Tilt every face along the pull by `angle` degrees so it releases: faces above the neutral plane lean toward
    +pull, faces below it toward −pull (the two halves of a two-plate tool). neutral: height along the pull of the
    parting plane (default: the lowest point of the body, everything in the +pull half).

    Each face turns about its far end along the way it releases (the top of a face in the +pull half), so the
    draft only adds material: no wall gets thinner, the far outline keeps its size and the part grows slightly
    toward the parting plane, by length × tan(angle).
    """
    from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from build123d import Solid
    if not (0 < float(angle) < 45):
        raise RecipeError(f"A draft of {angle}° is outside 0° to 45°.", feature="dfm_draft",
                          hint="Use the angle the moulding rule asks for (0.5° minimum, 2° recommended).")
    d = geom.unit(pull)
    faces = [f for f in body.faces() if _along(f, d)]
    if not faces:
        return body
    z = [float(geom._vec(v) @ d) for v in body.vertices()]
    h = min(z) if neutral is None else float(neutral)
    mk = BRepOffsetAPI_DraftAngle(body.wrapped)
    a = math.radians(float(angle))
    for f in faces:
        c = geom._vec(f.center())
        s = 1.0 if float(c @ d) >= h - 1e-9 else -1.0
        zs = [float(geom._vec(v) @ d) for v in f.vertices()]
        level = max(zs) if s > 0 else min(zs)
        pln = gp_Pln(gp_Pnt(*map(float, d * level)), gp_Dir(*map(float, s * d)))
        mk.Add(f.wrapped, gp_Dir(*map(float, s * d)), a, pln)
        if not mk.AddDone():
            raise RecipeError(f"The kernel cannot draft the face at {[round(float(x), 2) for x in c]}.",
                              feature="dfm_draft", hint="Draft that face by hand, or round the edges around it first.")
    mk.Build()
    if not mk.IsDone():
        raise RecipeError("The draft did not build.", feature="dfm_draft", hint="Draft the faces one by one by hand.")
    out = Solid(mk.Shape())
    if not out.is_valid:
        raise RecipeError("The drafted solid is not valid.", feature="dfm_draft", hint="Draft the faces by hand.")
    return out


def round_corners(body, axes=((0.0, 0.0, 1.0),), radius: float = 1.0):
    """Fillet every sharp internal straight edge that runs along one of `axes` (a tool direction) to `radius`, the
    corner a cutter of that radius leaves anyway."""
    dirs = [geom.unit(a) for a in axes]
    edges = [e["edge"] for e in geom.concave_line_edges(body)
             if any(abs(float(e["dir"] @ a)) > 0.9986 for a in dirs)]
    if not edges:
        return body
    try:
        out = body.fillet(float(radius), edges)
    except Exception as e:                                  # noqa: BLE001 - OCCT says why in its own words
        raise RecipeError(f"The kernel cannot round {len(edges)} internal corners to r {radius:g} mm ({e}).",
                          feature="dfm_corners", hint="A smaller radius, or a larger cavity: the corner radius cannot "
                          "exceed half the cavity's width.")
    return out


def escape_holes(body, d: float = 3.5, count: int = 2):
    """Cut `count` holes of diameter d from each enclosed void straight out of the part, along the axis with the
    least material between the void and the outside (both ways along it for two holes)."""
    from build123d import Axis, Cylinder, Pos
    vs = geom.voids(body)
    if not vs:
        return body
    bb = body.bounding_box()
    lo = np.array([bb.min.X, bb.min.Y, bb.min.Z])
    hi = np.array([bb.max.X, bb.max.Y, bb.max.Z])
    out = body
    for v in vs:
        vlo, vhi = np.asarray(v["bbox"][0]), np.asarray(v["bbox"][1])
        c = (vlo + vhi) / 2
        span = [(vlo[i] - lo[i]) + (hi[i] - vhi[i]) for i in range(3)]
        ax = int(np.argmin(span))
        sides = [1, -1][: max(1, int(count))]
        for s in sides:
            far = hi[ax] + 1.0 if s > 0 else lo[ax] - 1.0
            mid = (c[ax] + far) / 2
            L = abs(far - c[ax])
            p = c.copy()
            p[ax] = mid
            cyl = Cylinder(float(d) / 2, L)
            if ax == 0:
                cyl = cyl.rotate(Axis.Y, 90)
            elif ax == 1:
                cyl = cyl.rotate(Axis.X, 90)
            out = out - Pos(*map(float, p)) * cyl
    if geom.voids(out):
        raise RecipeError("An enclosed void is still closed after the escape holes.", feature="dfm_escape",
                          hint="Place the holes by hand.")
    return out
