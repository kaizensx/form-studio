"""Patterns and textures a design can place on a face: vents, perforations, knurls, grip ribs.

    from form import patterns
    vent = patterns.hex_vents(w=60, d=36, cell=5, web=1.2, depth=lid_t + 0.2)
    lid = lid - Pos(0, 0, lid_t) * vent.shape          # cutter: opening at z = 0, going down
    lid = vent.apply(lid, on=(0, 0, lid_t), normal=(0, 0, 1))     # the same, placed on a face

Every function returns a `Pattern`:
  .shape     a build123d cutter or solid, built on first use
  .kind      "cut" (subtract it) or "add" (fuse it)
  .computed  {"count", "open_area_ratio", "min_web_mm", "region_mm", ...}: arithmetic on the layout, no kernel needed
  .derived(feature, prefix)   the computed values as Recipe.derived() rows
  .check(nozzle)              one check row: is the thinnest printed web at least two perimeters wide?

Conventions match form.parts: a cutter is centred on X and Y, its opening is at z = 0, it goes down into the
material (-Z) and overshoots 0.2 mm above z = 0. For a through-cut give depth = wall thickness + 0.2.

open_area_ratio is the open area divided by the area of the pattern's region (w x d). For "add" patterns (ribs)
it is the covered fraction instead. min_web_mm is the thinnest strip of plastic the pattern leaves (or, for
ribs, the rib itself). A perimeter is taken to be one nozzle width wide.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

OVERSHOOT = 0.2
SQRT3 = math.sqrt(3.0)


@dataclass
class Pattern:
    name: str
    kind: str                                   # "cut" | "add"
    computed: dict
    centres: list = field(default_factory=list)      # (x, y) of every cell, mm
    _make: Callable[[], Any] | None = None
    _shape: Any = None

    @property
    def shape(self):
        if self._shape is None:
            if not self.centres and self.name != "knurl":
                from .recipes.base import RecipeError
                raise RecipeError(f"The {self.name} pattern has no cells: the region is too small for one",
                                  "", "Enlarge the patterned area, or use a smaller cell.")
            self._shape = self._make()
        return self._shape

    def __getitem__(self, key: str):
        return self.computed[key]

    def on(self, at, normal=None, up=None):
        """The shape placed on a face: at is a planar Face, a Plane, a Location, or a point with normal=."""
        from . import marks
        return marks._plane(None, at, normal, up) * self.shape

    def apply(self, body, on, normal=None, up=None):
        tool = self.on(on, normal, up)
        return body - tool if self.kind == "cut" else body + tool

    def derived(self, feature: str, prefix: str = "") -> list[dict]:
        c = self.computed
        rows = [{"key": prefix + "open_area", "label": f"{self.name.capitalize()}: " + ("open area" if self.kind == "cut" else "covered area"),
                 "value": round(c["open_area_ratio"] * 100, 2), "unit": "%", "feature": feature,
                 "formula": f"computed: {c['count']} cells over {c['region_mm'][0]:.1f} × {c['region_mm'][1]:.1f} mm"}]
        if c.get("min_web_mm") is not None:
            rows.append({"key": prefix + "min_web", "label": f"{self.name.capitalize()}: thinnest web", "value": round(c["min_web_mm"], 3),
                         "unit": "mm", "feature": feature, "formula": "computed: smallest strip of plastic between openings"})
        return rows

    def check(self, nozzle: float | None = None, id: str | None = None, feature: str | None = None) -> dict:
        """Webs against two perimeters (one perimeter = one nozzle width). nozzle: worker context, then 0.4 mm."""
        from . import marks
        ctx = marks.context()
        assumed = nozzle is None and "nozzle" not in ctx
        nz = float(nozzle if nozzle is not None else ctx.get("nozzle", 0.4))
        web = self.computed.get("min_web_mm")
        if web is None:
            st, value = "PASS", "one opening"
        else:
            st, value = ("PASS" if web >= 2 * nz - 1e-9 else ("WARN" if web >= nz - 1e-9 else "FAIL")), f"{web:.2f} mm web"
        return {"id": id or f"pattern_{self.name}", "label": f"{self.name.capitalize()} pattern webs", "status": st, "value": value,
                "detail": f"{self.computed['count']} cells, {self.computed['open_area_ratio'] * 100:.0f}% "
                          + ("open" if self.kind == "cut" else "covered") + ". "
                          + (f"The thinnest web is {web:.2f} mm; two perimeters on a {nz:g} mm nozzle"
                             + (" (assumed)" if assumed else "") + f" need {2 * nz:g} mm. Thinner webs print as a single line "
                             "or not at all." if web is not None else "There is no web between openings to check."),
                "evidence": "computed", "feature": feature}


def _need(cond: bool, msg: str, hint: str = ""):
    if not cond:
        from .recipes.base import RecipeError
        raise RecipeError(msg, "", hint)


def _copies(unit, centres):
    from build123d import Compound, Pos
    return Compound(children=[Pos(x, y, 0) * unit for x, y in centres])


def _lattice(w: float, d: float, px: float, py: float, half_x: float, half_y: float, stagger: bool) -> list:
    """As many rows and columns as fit inside w x d (cell half extents half_x, half_y), centred on the origin.
    Staggered: every other row is shifted half a pitch and holds one cell more or less, whichever fits."""
    if w < 2 * half_x - 1e-9 or d < 2 * half_y - 1e-9:
        return []
    ny = int(math.floor((d - 2 * half_y) / py + 1e-9)) + 1
    nx = int(math.floor((w - 2 * half_x) / px + 1e-9)) + 1
    out = []
    for j in range(ny):
        n = nx
        if stagger and j % 2:
            n = nx + 1 if nx * px + 2 * half_x <= w + 1e-9 else nx - 1
        y = (j - (ny - 1) / 2) * py
        out += [((i - (n - 1) / 2) * px, y) for i in range(n)]
    return out


def hex_vents(w: float, d: float, cell: float = 5.0, web: float = 1.2, depth: float = 2.2) -> Pattern:
    """Honeycomb of hexagonal holes filling a w x d region. cell: across flats, mm. web: plastic between
    neighbouring flats, mm (the same in all three directions)."""
    _need(cell > 0 and web > 0 and depth > 0, "Hex vents need a positive cell, web and depth")
    px, py = cell + web, (cell + web) * SQRT3 / 2
    corner = cell / SQRT3                                  # circumradius
    centres = _lattice(w, d, px, py, cell / 2, corner, True)
    area = SQRT3 / 2 * cell * cell

    def make():
        from build123d import RegularPolygon, extrude, Pos
        unit = Pos(0, 0, -depth) * extrude(RegularPolygon(corner, 6, rotation=30), amount=depth + OVERSHOOT)
        return _copies(unit, centres)
    n = len(centres)
    return Pattern("hex", "cut", {"count": n, "open_area_mm2": n * area, "open_area_ratio": n * area / (w * d),
                                  "min_web_mm": web if n > 1 else None, "region_mm": [w, d], "cell_mm": cell,
                                  "pitch_mm": [px, py]}, centres, make)


def perforation_grid(w: float, d: float, hole_d: float = 3.0, web: float = 1.5, depth: float = 2.2,
                     stagger: bool = False) -> Pattern:
    """Round holes on a square grid (or staggered rows) filling a w x d region. web: plastic between holes, mm."""
    _need(hole_d > 0 and web > 0 and depth > 0, "A perforation grid needs a positive hole, web and depth")
    p = hole_d + web
    centres = _lattice(w, d, p, p * SQRT3 / 2 if stagger else p, hole_d / 2, hole_d / 2, stagger)
    area = math.pi * hole_d * hole_d / 4

    def make():
        from build123d import Align, Cylinder, Pos
        unit = Pos(0, 0, -depth) * Cylinder(hole_d / 2, depth + OVERSHOOT, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return _copies(unit, centres)
    n = len(centres)
    return Pattern("grid", "cut", {"count": n, "open_area_mm2": n * area, "open_area_ratio": n * area / (w * d),
                                   "min_web_mm": web if n > 1 else None, "region_mm": [w, d], "hole_d_mm": hole_d,
                                   "pitch_mm": [p, p * SQRT3 / 2 if stagger else p]}, centres, make)


def slot_array(slot_w: float, slot_l: float, count: int | None = None, web: float | None = None, depth: float = 2.2,
               w: float | None = None) -> Pattern:
    """Parallel round-ended slots, long axis on Y, spaced along X. Give count, or w (a width to fill).
    web: plastic between slots (default 1.2 x slot width). The region is the array's own bounding rectangle
    when count is given, w x slot_l when w is given."""
    _need(slot_w > 0 and slot_l >= slot_w and depth > 0, "Slots need a width, a length at least as long, and a depth")
    web = 1.2 * slot_w if web is None else web
    _need(web > 0, "The web between slots must be above 0 mm")
    pitch = slot_w + web
    if count is None:
        _need(w is not None, "Give the slot array a count or a width to fill")
        count = int(math.floor((w + web) / pitch + 1e-9))
    n = max(0, int(count))
    region_w = w if w is not None else max(slot_w, n * slot_w + (n - 1) * web)
    centres = [((i - (n - 1) / 2) * pitch, 0.0) for i in range(n)]
    area = (slot_l - slot_w) * slot_w + math.pi * slot_w * slot_w / 4

    def make():
        from build123d import Plane, Pos, SlotOverall, extrude
        unit = Pos(0, 0, -depth) * extrude(Plane.XY * SlotOverall(slot_l, slot_w, rotation=90), amount=depth + OVERSHOOT)
        return _copies(unit, centres)
    return Pattern("slot", "cut", {"count": n, "open_area_mm2": n * area, "open_area_ratio": n * area / (region_w * slot_l) if n else 0.0,
                                   "min_web_mm": web if n > 1 else None, "region_mm": [region_w, slot_l], "pitch_mm": [pitch, 0.0]},
                   centres, make)


def grip_ribs(w: float, d: float, rib_w: float = 1.2, pitch: float = 3.0, height: float = 0.8) -> Pattern:
    """Raised straight ribs for grip: long axis on Y (length d), spaced along X across w. kind "add": the ribs
    stand on z = 0 and reach 0.05 mm below it so they fuse. min_web_mm is the rib width (the thin printed thing)."""
    _need(rib_w > 0 and pitch > rib_w and height > 0, "Ribs need a width, a larger pitch, and a height")
    n = int(math.floor((w - rib_w) / pitch + 1e-9)) + 1 if w >= rib_w else 0
    centres = [((i - (n - 1) / 2) * pitch, 0.0) for i in range(n)]

    def make():
        from build123d import Align, Box, Pos
        unit = Pos(0, 0, -0.05) * Box(rib_w, d, height + 0.05, align=(Align.CENTER, Align.CENTER, Align.MIN))
        return _copies(unit, centres)
    return Pattern("rib", "add", {"count": n, "open_area_mm2": n * rib_w * d, "open_area_ratio": n * rib_w * d / (w * d) if n else 0.0,
                                  "min_web_mm": rib_w if n else None, "region_mm": [w, d], "pitch_mm": [pitch, 0.0],
                                  "gap_mm": pitch - rib_w}, centres, make)


def knurl(diameter: float, height: float, pitch: float = 2.0, depth: float = 0.6) -> Pattern:
    """Straight knurl for a cylinder on the Z axis standing on z = 0: V grooves along the axis, evenly spaced.
    Subtract it from a cylinder of this diameter. pitch: groove spacing on the surface, mm (rounded so a whole
    number fits). Each groove is as wide as it is deep times two (a 90 degree V); the ridge between grooves is
    min_web_mm. open_area_ratio is the grooved fraction of the surface."""
    _need(diameter > 0 and height > 0 and pitch > 0 and depth > 0, "A knurl needs a diameter, height, pitch and depth")
    R = diameter / 2
    n = max(3, int(round(math.pi * diameter / pitch)))
    real_pitch = math.pi * diameter / n
    groove = 2 * depth
    _need(groove < real_pitch, "Knurl grooves overlap", "Use a larger pitch or a shallower depth.")
    _need(depth < R, "Knurl depth is larger than the radius")

    def make():
        from build123d import Compound, Plane, Polygon, Pos, Rot, extrude
        tri = Polygon((R - depth, 0), (R + OVERSHOOT, -(depth + OVERSHOOT)), (R + OVERSHOOT, depth + OVERSHOOT), align=None)
        unit = Pos(0, 0, -OVERSHOOT) * extrude(Plane.XY * tri, amount=height + 2 * OVERSHOOT)
        return Compound(children=[Rot(0, 0, 360.0 * i / n) * unit for i in range(n)])
    return Pattern("knurl", "cut", {"count": n, "open_area_mm2": n * groove * height, "open_area_ratio": groove / real_pitch,
                                    "min_web_mm": real_pitch - groove, "region_mm": [math.pi * diameter, height],
                                    "pitch_mm": [real_pitch, 0.0], "depth_mm": depth},
                   [(R * math.cos(2 * math.pi * i / n), R * math.sin(2 * math.pi * i / n)) for i in range(n)], make)


VENT_STYLES = {0: "slots", 1: "hex", 2: "grid"}
