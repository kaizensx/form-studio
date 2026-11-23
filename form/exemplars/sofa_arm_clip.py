"""Sofa-arm caddy clip: one continuous band that wraps a sofa's arm and drops into a cradle on the outside for a
power strip, a remote or a phone. The band is drawn as one centreline (straight runs joined by tangent arcs) and
thickened, so every bend is a true radius; its side edges are rounded, the inner leg flares to slide on, and soft
ribs grip the fabric. Form Studio exemplar design (premium everyday object, original; sizes are typical, measure
the arm and the device)."""
import math

from build123d import Axis, Edge, Kind, Plane, Pos, Side, Vector, Wire, extrude, make_face

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Sofa-arm caddy clip (one band, cradle, grip ribs)",
    "category": "consumer",
    "tags": ["clip", "sofa clip", "sofa arm", "armrest", "caddy", "holder", "power strip holder", "outlet holder",
             "remote holder", "saddle", "u clip", "band", "premium", "beautiful", "grip ribs", "two material"],
    "techniques": ["the whole part as ONE centreline (lines joined by tangent arcs) thickened with Wire.offset_2d: "
                   "every bend is a true radius, constant wall",
                   "profile drawn in XZ, extruded along the arm (Y) in one go",
                   "tier 2 radius on both side outlines (the loops in y = +-L/2) with safe_fillet; tier 1 is in the "
                   "path's bend radii; tier 3 on the ribs",
                   "a lead-in flare on the inner leg (the last run turned out by a few degrees)",
                   "grip ribs on a rhythm on the faces that touch the fabric, in a second material"],
    "lessons": [
        "Draw a clip as one band, not as boxes: a centreline with tangent-arc bends, thickened, gives a constant wall "
        "and real radii in every bend. Boxes give square corners that crack and look improvised.",
        "Put the big radius where the band wraps the arm (sofa arms are rounded: R 8-12 inside), smaller radii in "
        "the cradle, and round the band's side edges (R 1.5-2): three tiers.",
        "Flare the free end of a clip outward by 8-12 deg: it slides on and does not dig into the fabric.",
        "The holder is part of the same gesture: the outer leg runs on into the cradle. A cradle bolted on as a "
        "separate box reads as an add-on.",
        "Grip comes from a few soft ribs on the faces that touch the fabric, spaced on a rhythm, in a second material; "
        "a plain hard band slides.",
        "If a fillet fails, make it smaller or fillet the loops one at a time (safe_fillet does both); never ship the "
        "band with sharp side edges.",
    ],
}


def _filleted(P, radii):
    """A path through the points P with a tangent arc of radii[i] at each inner corner (a bent strip)."""
    edges, start = [], P[0]
    for i in range(1, len(P) - 1):
        a, b, c = P[i - 1], P[i], P[i + 1]
        d1, d2 = (b - a).normalized(), (c - b).normalized()
        ang = math.acos(max(-1.0, min(1.0, d1.dot(d2))))
        if ang < 1e-3:
            continue
        cut = radii[i - 1] * math.tan(ang / 2)
        p1, p2 = b - d1 * cut, b + d2 * cut
        if (p1 - start).length > 1e-6:
            edges.append(Edge.make_line(start, p1))
        edges.append(Edge.make_tangent_arc(p1, d1, p2))
        start = p2
    edges.append(Edge.make_line(start, P[-1]))
    return Wire(edges)


class Design(FeatureDesign):
    title, summary = "Sofa-arm caddy clip", "One band that wraps a sofa arm and drops into a cradle, with grip ribs."
    params = [
        Param("arm_w", "Sofa arm width", 60, 30, 160, 0.5, "mm", "brief", "band", "Measure across the arm's top."),
        Param("inner_drop", "Inner leg length", 34, 15, 80, 1, "mm", "form", "band"),
        Param("cradle_w", "Cradle width", 52, 20, 90, 0.5, "mm", "brief", "band",
              "The device's thickness across the cradle plus about 1 mm."),
        Param("cradle_d", "Cradle depth", 42, 20, 80, 0.5, "mm", "brief", "band", "How deep the device sits."),
        Param("length", "Clip length (along the arm)", 64, 30, 140, 1, "mm", "form", "band"),
        Param("t", "Band thickness", 4.5, 3, 7, 0.25, "mm", "form", "band", "PETG flexes; 4-5 mm for a firm grip."),
        Param("wrap_r", "Wrap radius", 10, 3, 20, 0.5, "mm", "form", "band", "Tier 1: the bends over the arm."),
    ]

    def setup(self, v):
        t, W = v["t"], v["arm_w"]
        xi, xo = -t / 2, W + t / 2                         # centreline of the inner and outer legs
        zc = t / 2                                         # centreline of the crown (arm top at z = 0)
        zb = -(v["cradle_d"] + 8)                          # cradle floor centreline
        xc = xo + v["cradle_w"] + t                        # cradle outer wall centreline
        flare = math.radians(10)
        tip = Vector(xi - 10 * math.sin(flare), 0, -v["inner_drop"] - 10 * math.cos(flare))
        # --- snippet: the whole clip as one centreline: flared inner leg, crown, outer leg, cradle
        P = [tip, Vector(xi, 0, -v["inner_drop"]), Vector(xi, 0, zc), Vector(xo, 0, zc), Vector(xo, 0, zb),
             Vector(xc, 0, zb), Vector(xc, 0, zb + v["cradle_d"] * 0.72)]
        r = v["wrap_r"]
        path = _filleted(P, [14.0, r, r, 6.0, 6.0])
        # --- end snippet
        return {"path": path, "xi": xi, "xo": xo, "xc": xc, "zb": zb}

    def constraints(self, v):
        if v["wrap_r"] > v["arm_w"] / 2 - 2:
            return [RecipeError("The wrap radius is wider than half the arm", "band", "Use a smaller wrap radius.",
                                ["wrap_r", "arm_w"])]
        return []

    @feature("Band")                                       # skeleton: the thickened centreline, extruded along Y
    def band(self, v, body):
        # --- snippet: thicken a centreline into a band profile and extrude it
        outline = self.ctx["path"].offset_2d(v["t"] / 2, kind=Kind.ARC, side=Side.BOTH, closed=True)
        prof = make_face(outline)
        return extrude(prof, v["length"] / 2, both=True)
        # --- end snippet

    @feature("Edges", role="finish")
    def edges(self, v, body):
        L = v["length"] / 2
        for y in (L, -L):                                  # one side outline at a time (tier 2)
            loop = [e for e in body.edges() if abs(e.center().Y - y) < 1e-3]
            body = craft.safe_fillet(body, loop, 1.6)
        return body

    @feature("Grip ribs", role="interface")
    def ribs(self, v, body):
        c, t, L = self.ctx, v["t"], v["length"]
        # --- snippet: soft ribs on a rhythm on the faces that touch the fabric
        out = body
        for x_face, sgn in ((c["xi"] + t / 2, 1), (c["xo"] - t / 2, -1)):      # inner faces of both legs
            for k in range(3):
                z = -6 - k * 8.0
                rib = Pos(x_face, 0, z) * extrude(craft.superellipse_face(1.1, 1.6, 2.0, plane=Plane.XZ), L / 2 - 4, both=True)
                out = craft.safe_union(out, rib)
        # --- end snippet
        return out

    def appearance(self, v):
        return [{"features": ["band", "edges"], "finish": "petg", "color": "#5b6f7a", "label": "slate PETG"},
                {"features": ["ribs"], "finish": "rubber", "color": "#d97a4a", "label": "soft grip ribs"}]
