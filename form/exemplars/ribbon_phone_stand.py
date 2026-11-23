"""Ribbon phone stand: one continuous band, rounded in section, that curls up into the lip, runs back along the desk
and rises forward to cradle the phone's back. The band's section is a superellipse, so every edge is rounded by
construction; rubber pads on the lip and the rest are the band's own ends in another material. Form Studio exemplar
design (premium everyday object, original)."""
import math

from build123d import Edge, Plane, PositionMode, Vector, Wire

from form import craft
from form.featureprog import FeatureDesign, feature
from form.recipes.base import Param, RecipeError

META = {
    "title": "Ribbon phone stand (one swept band)",
    "category": "consumer",
    "tags": ["phone stand", "phone holder", "tablet stand", "desk stand", "dock", "ribbon", "band", "sweep",
             "premium", "beautiful", "minimal", "rubber pads", "two material", "everyday"],
    "techniques": ["one gesture: a single band lofted along a bent-strip path (straight runs joined by tangent arcs)",
                   "sections placed with x_dir along the band's width: a planar path's tangent never leaves XZ, so the "
                   "band cannot twist (a plain sweep's frame rolls through the path's inflections)",
                   "section as a superellipse (n = 6): the band's edges are rounded by the section, no fillet to fail",
                   "the path split into three parameter spans, each lofted on its own: the end spans are their own "
                   "features, so appearance() gives them rubber",
                   "lean angle and lip height as Params; the rest point computed from the phone's lean"],
    "lessons": [
        "One gesture carries the whole object: a band that never stops (lip, floor, rise) reads as designed; three "
        "boxes joined at corners read as a bracket. Draw the path first, then the section.",
        "Put the rounding in the section, not in fillets: a swept superellipse band has soft edges everywhere and "
        "nothing left for the kernel to fail on. This is how to keep edges round when fillets keep crashing.",
        "Draw a bent band's path as straight runs joined by tangent arcs with chosen radii (how sheet metal or a "
        "bent strip is made): it goes exactly where you put it. A free spline through the same points overshoots "
        "and loops at tight turns.",
        "Bends tighter than about three band thicknesses look pinched and self-intersect in the sweep: keep the "
        "radius of every curl above 3x the thickness.",
        "A lofted band is a poor target for later booleans (a slot through it can fail): put openings in the "
        "section or the path, or leave the band whole and let the pads carry the detail.",
        "Materials mark function: rubber where the phone touches (lip, rest), the band itself in one calm colour.",
        "A wide band swept along a path with inflections twists (the sweep frame rolls). Loft it through sections "
        "placed on the path with a fixed x_dir instead; split it into spans that share their end section, so the "
        "fuse is clean and each span is its own feature.",
    ],
}


def _filleted(P, radii):
    """A path through the points P with a tangent arc of radii[i] at each inner corner (a bent strip)."""
    edges, start = [], P[0]
    for i in range(1, len(P) - 1):
        a, b, c = P[i - 1], P[i], P[i + 1]
        d1, d2 = (b - a).normalized(), (c - b).normalized()
        ang = math.acos(max(-1.0, min(1.0, d1.dot(d2))))
        cut = radii[i - 1] * math.tan(ang / 2)
        p1, p2 = b - d1 * cut, b + d2 * cut
        edges.append(Edge.make_line(start, p1))
        edges.append(Edge.make_tangent_arc(p1, d1, p2))
        start = p2
    edges.append(Edge.make_line(start, P[-1]))
    return Wire(edges)


class Design(FeatureDesign):
    title, summary = "Ribbon phone stand", "One bent band: a lip, a floor and a forward-leaning rest, with rubber ends."
    params = [
        Param("width", "Band width", 68, 40, 110, 1, "mm", "form", "band"),
        Param("thick", "Band thickness", 5, 3.5, 8, 0.25, "mm", "form", "band"),
        Param("lean", "Phone lean from vertical", 22, 12, 35, 1, "deg", "brief", "band",
              "15-25 deg reads a screen comfortably at a desk."),
        Param("lip_h", "Lip height", 13, 8, 22, 0.5, "mm", "brief", "lip"),
        Param("rest_h", "Rest height", 72, 45, 110, 1, "mm", "brief", "rest",
              "Where the band meets the phone's back; about half a phone's height."),
        Param("slot", "Phone thickness allowance", 13, 8, 20, 0.5, "mm", "interface", "lip",
              "Gap between the lip and the rest line at the floor: phone plus case."),
    ]

    def setup(self, v):
        t, L = v["thick"], math.radians(v["lean"])
        x_lip = 0.0
        x_phone = x_lip - v["slot"]                     # phone back at the floor
        # rest point: on the phone's back line, leaning back by `lean`, offset by half the band
        xr = x_phone - v["rest_h"] * math.tan(L) - t / 2 * math.cos(L)
        zr = v["rest_h"] - t / 2 * math.sin(L)
        # --- snippet: the band's path as straight runs joined by tangent arcs (a bent strip): exact, never overshoots
        xb = xr - 46.0                                   # the riser's top, behind the phone
        zb = zr - (xr - xb) * math.tan(L)                # so the top arm reaches the phone square to its back
        pts = [(x_lip + t / 2, v["lip_h"]), (x_lip + t / 2, t / 2), (xb + 8, t / 2), (xb, zb), (xr, zr)]
        path = _filleted([Vector(x, 0, z) for x, z in pts], [min(v["lip_h"] - t, 4.0), 18.0, 16.0])
        # --- end snippet
        return {"path": path}

    def constraints(self, v):
        if v["lip_h"] < v["thick"] * 1.8:
            return [RecipeError("The lip is too low to hold a phone", "lip", "Raise the lip.", ["lip_h", "thick"])]
        return []

    def _band(self, v, t0, t1):
        # --- snippet: a rounded band along a planar path, lofted through sections that keep their width along Y
        path, out = self.ctx["path"], []
        L = path.length
        n = max(4, int(round((t1 - t0) * L / 3.0)))      # a section every 3 mm of path, placed by length
        for i in range(n + 1):
            d = (t0 + (t1 - t0) * i / n) * L
            pl = Plane(origin=path.position_at(d, position_mode=PositionMode.LENGTH), x_dir=(0, 1, 0),
                       z_dir=path.tangent_at(d, position_mode=PositionMode.LENGTH))
            out.append(craft.superellipse_face(v["width"] / 2, v["thick"] / 2, 6.0, plane=pl, count=64))
        return craft.loft_sections(out)
        # --- end snippet

    @feature("Band")                                     # skeleton: the middle span (floor and rise)
    def band(self, v, body):
        return self._band(v, 0.1, 0.86)

    @feature("Lip pad", role="interface")
    def lip(self, v, body):
        body = craft.safe_union(body, self._band(v, 0.0, 0.1))
        return self._round_end(v, body, 0.0)

    @feature("Rest pad", role="interface")
    def rest(self, v, body):
        body = craft.safe_union(body, self._band(v, 0.86, 1.0))
        return self._round_end(v, body, 1.0)

    def _round_end(self, v, body, u):
        """Soften the band's cut end (tier 3): the loop of edges centred on the path's end."""
        path = self.ctx["path"]
        end = path.position_at(u * path.length, position_mode=PositionMode.LENGTH)
        loop = [e for e in body.edges() if (e.center() - end).length < v["width"] / 2 + 1
                and abs((e.center() - end).dot(path.tangent_at(u * path.length, position_mode=PositionMode.LENGTH))) < 0.3]
        return craft.safe_fillet(body, loop, v["thick"] * 0.3)

    def appearance(self, v):
        return [{"features": ["band"], "finish": "matte", "color": "#c9cdd1", "label": "anodised grey"},
                {"features": ["lip", "rest"], "finish": "rubber", "color": "#24272b", "label": "rubber pads"}]
