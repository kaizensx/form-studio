"""Standard hardware for designs: screws, heat-set inserts, nuts, threads, bearings, magnets, gears.

A thin, stable FORM API over published dimensions and two optional libraries:

  bd_warehouse  (fasteners, threads, bearings)  https://github.com/gumyr/bd_warehouse
  py_gearworks  (involute gears)                https://github.com/GarryBGoode/py_gearworks

Install them with ``pip install "form-studio[parts]"``. The common sizes (M2-M6 screws and nuts, CNC Kitchen
heat-set inserts, 6xx/608 bearings) are tabulated here, so screw, insert, nut, bearing and magnet pockets work
without the extra. Other sizes, threads and gears need the libraries; when one is missing, the call raises a
RecipeError that says what to install.

Every function returns a ``HardwarePart``:
  .shape   a build123d solid
  .kind    "cut"  (subtract it: ``body - Pos(x, y, z_top) * part.shape``) or "add" (fuse it)
  .dims    {name: {"value", "unit", "provenance", "source"}} - what the shape was built from
  part["name"] is the value of one dimension.

Conventions: cutters have their axis on Z with the opening at z = 0, going down into the material (-Z), and
overshoot 0.2 mm above z = 0 so the cut never leaves a skin. Gears and threaded rods stand on z = 0, axis on Z.
Clearances for FDM printing are FORM assumptions (provenance "assumed"); catalogue dimensions are "specified".
"""
from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field
from typing import Any

from build123d import Align, Box, Cone, Cylinder, Plane, Pos, RegularPolygon, Rot, extrude

from .recipes.base import RecipeError

INSTALL_HINT = 'Install the parts extra: pip install "form-studio[parts]" (adds bd_warehouse and py_gearworks).'
OVERSHOOT = 0.2
BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
TOP = (Align.CENTER, Align.CENTER, Align.MAX)

# ---- published dimensions ----------------------------------------------------------------------------------
# ISO 273 clearance holes (close / normal ["medium"] / loose), mm.
ISO_273 = "ISO 273 clearance holes for bolts and screws"
CLEARANCE = {
    "M2": (2.2, 2.4, 2.6), "M2.5": (2.7, 2.9, 3.1), "M3": (3.2, 3.4, 3.6), "M4": (4.3, 4.5, 4.8),
    "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0),
}
PITCH = {"M2": 0.4, "M2.5": 0.45, "M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0}
# Screw heads (diameter, height), mm. Same values as bd_warehouse 0.4.0's tables.
HEADS = {
    "socket": ("ISO 4762 socket head cap screw (dk, k)", {
        "M2": (3.98, 2.0), "M2.5": (4.68, 2.5), "M3": (5.68, 3.0), "M4": (7.22, 4.0), "M5": (8.72, 5.0), "M6": (10.22, 6.0)}),
    "pan": ("ISO 14583 pan head screw (dk, k)", {
        "M2": (4.0, 1.6), "M2.5": (5.0, 2.1), "M3": (5.6, 2.4), "M4": (8.0, 3.1), "M5": (9.5, 3.7), "M6": (12.0, 4.6)}),
    "countersunk": ("ISO 10642 countersunk socket screw (dk actual, k), 90 degrees", {
        "M3": (5.64, 1.7), "M4": (7.51, 2.3), "M5": (9.41, 2.8), "M6": (11.3, 3.3)}),
}
# Nuts: (width across flats s, thickness m), mm.
NUTS = {
    "hex": ("ISO 4032 hex nut (s, m)", {
        "M2": (4.0, 1.6), "M2.5": (5.0, 2.0), "M3": (5.5, 2.4), "M4": (7.0, 3.2), "M5": (8.0, 4.7), "M6": (10.0, 5.2)}),
    "square": ("DIN 562 thin square nut (s, m)", {
        "M2": (4.0, 1.2), "M2.5": (5.0, 1.6), "M3": (5.5, 1.8), "M4": (7.0, 2.2), "M5": (8.0, 2.7), "M6": (10.0, 3.2)}),
}
# Brass heat-set inserts, CNC Kitchen standard and short versions, from the product pages at cnckitchen.store
# (e.g. /products/heat-set-insert-m3-x-5-7-100-pieces): (insert outer diameter, length, recommended hole
# diameter, minimum wall around the hole), mm. The hole diameter is the published one; it is not an FDM guess.
INSERT_SOURCE = "CNC Kitchen heat-set insert datasheet (cnckitchen.store), recommended hole"
INSERTS = {
    "M2": (3.6, 3.0, 3.2, 1.3), "M2.5": (4.6, 4.0, 4.0, 1.6), "M3": (4.6, 5.7, 4.0, 1.6), "M3-short": (4.6, 3.0, 4.0, 1.6),
    "M4": (6.3, 8.1, 5.7, 2.1), "M4-short": (6.3, 4.0, 5.7, 2.1), "M5": (7.1, 9.5, 6.5, 2.6), "M5-short": (7.1, 5.8, 6.5, 2.6),
}
# Deep-groove ball bearings, ISO 15: bore d, outside D, width B, inner-ring shoulder d1, max housing shoulder Da.
BEARING_SOURCE = "ISO 15 deep-groove ball bearing (SKF catalogue values, as tabulated in bd_warehouse)"
BEARINGS = {
    "623": (3, 10, 4, 5.2, 8.8), "625": (5, 16, 5, 8.4, 13.6), "626": (6, 19, 6, 11.1, 16.6),
    "608": (8, 22, 7, 12.1, 20.0), "6000": (10, 26, 8, 14.8, 24.0),
}
_BEARING_BD = {"623": "M3-10-4", "625": "M5-16-5", "626": "M6-19-6", "608": "M8-22-7", "6000": "M10-26-8"}


def _dim(value, unit="mm", provenance="specified", source=""):
    return {"value": float(value), "unit": unit, "provenance": provenance, "source": source}


@dataclass
class HardwarePart:
    """A build123d shape plus the dimensions it was built from, each with its provenance and source."""
    name: str
    shape: Any
    kind: str                     # "cut" | "add"
    dims: dict = field(default_factory=dict)

    def __getitem__(self, key: str) -> float:
        return self.dims[key]["value"]

    def derived(self, feature: str, prefix: str = "", interface: tuple = ()) -> list[dict]:
        """The dimensions as Recipe.derived() rows, so checks and the fit model can show them."""
        return [{"key": prefix + k, "label": f"{self.name}: {k.replace('_', ' ')}", "value": d["value"], "unit": d["unit"],
                 "feature": feature, "formula": f"{d['provenance']}: {d['source']}", "interface": k in interface}
                for k, d in self.dims.items()]


def _size(size: str) -> str:
    s = str(size).strip().upper().split("-")[0].split("X")[0]
    if not s.startswith("M"):
        s = "M" + s
    try:
        float(s[1:])
    except ValueError:
        raise RecipeError(f"Unknown screw size “{size}”", "", "Use a metric size such as M2, M2.5, M3, M4, M5 or M6.")
    return s.rstrip("0").rstrip(".") if "." in s else s


def size_name(d: float) -> str:
    """3 -> "M3", 2.5 -> "M2.5" (recipes keep sizes as numbers)."""
    return "M" + (f"{d:g}")


def _bd(module: str):
    try:
        if module == "fastener":
            from bd_warehouse import fastener as m
        elif module == "thread":
            from bd_warehouse import thread as m
        elif module == "bearing":
            from bd_warehouse import bearing as m
        else:
            import py_gearworks as m
    except ImportError as e:
        lib = "py_gearworks" if module == "gear" else "bd_warehouse"
        raise RecipeError(f"{lib} is not installed, so this part cannot be built here ({e}).", "", INSTALL_HINT)
    return m


def _bd_size(s: str) -> str:
    """M3 -> M3-0.5, the coarse-pitch name bd_warehouse uses."""
    f = _bd("fastener")
    for name in f.HexNut.sizes("iso4032"):
        if name.split("-")[0] == s:
            return name
    raise RecipeError(f"No coarse-pitch metric size {s} in bd_warehouse.", "", "Use a standard size such as M3 or M8.")


def clearance_d(size: str, fit: str = "normal") -> tuple[float, str]:
    s = _size(size)
    col = {"close": 0, "normal": 1, "loose": 2}.get(fit)
    if col is None:
        raise RecipeError(f"Unknown fit “{fit}”", "", "Use close, normal or loose.")
    if s in CLEARANCE:
        return CLEARANCE[s][col], ISO_273
    f = _bd("fastener")
    d = f.SocketHeadCapScrew(_bd_size(s), 10).clearance_hole_diameters[fit.capitalize()]
    return float(d), ISO_273 + " (via bd_warehouse)"


def head_dims(size: str, head: str) -> tuple[float, float, str]:
    s = _size(size)
    if head not in HEADS:
        raise RecipeError(f"Unknown screw head “{head}”", "", "Use socket, pan or countersunk.")
    src, table = HEADS[head]
    if s in table:
        return table[s][0], table[s][1], src
    f = _bd("fastener")
    cls = {"socket": f.SocketHeadCapScrew, "pan": f.PanHeadScrew, "countersunk": f.CounterSunkScrew}[head]
    try:
        sc = cls(_bd_size(s), 10)
    except ValueError as e:
        raise RecipeError(f"No {head} head data for {s}: {e}", "", "Pick another head style or size.")
    return float(sc.head_diameter), float(sc.head_height), src + " (via bd_warehouse)"


# ---- pockets and holes -------------------------------------------------------------------------------------
def screw_clearance(size: str = "M3", length: float = 10.0, head: str = "socket", fit: str = "normal",
                    head_clearance: float = 0.3, recess: bool = True) -> HardwarePart:
    """A clearance hole for a screw, `length` deep below z = 0, with a counterbore (socket, pan) or a 90° countersink.

    recess=False gives the plain hole (the head sits on the surface). head_clearance is added to the head
    diameter (assumed, for FDM)."""
    if length <= 0:
        raise RecipeError("Screw hole length must be positive", "", "Give the material thickness the screw passes.")
    s = _size(size)
    d, src = clearance_d(s, fit)
    dk, k, hsrc = head_dims(s, head)
    hole = Pos(0, 0, OVERSHOOT) * Cylinder(d / 2, length + OVERSHOOT, align=TOP)
    dims = {"hole_d": _dim(d, source=f"{src}, {fit} fit"), "head_d": _dim(dk, source=hsrc), "head_h": _dim(k, source=hsrc),
            "head_clearance": _dim(head_clearance, provenance="assumed", source="Form Studio default for FDM"),
            "length": _dim(length, provenance="assumed", source="caller")}
    shape = hole
    if recess:
        D = dk + head_clearance
        if head == "countersunk":
            depth = (D - d) / 2                                       # 90° included angle
            sink = Cone(d / 2, D / 2, depth, align=BOTTOM)
            sink = Pos(0, 0, -depth) * sink + Cylinder(D / 2, OVERSHOOT, align=BOTTOM)
            shape = shape + sink
            dims["countersink_d"] = _dim(D, provenance="computed", source="head diameter + head clearance")
        else:
            depth = k + 0.2
            shape = shape + Pos(0, 0, OVERSHOOT) * Cylinder(D / 2, depth + OVERSHOOT, align=TOP)
            dims["counterbore_d"] = _dim(D, provenance="computed", source="head diameter + head clearance")
        dims["recess_depth"] = _dim(depth, provenance="computed", source="head height + 0.2" if head != "countersunk" else "90° sink")
        if depth >= length:
            raise RecipeError(f"The {head} head recess ({depth:.1f} mm) is deeper than the hole ({length:.1f} mm)", "",
                              "Make the material thicker or use a pan head without a recess.")
    return HardwarePart(f"{s} {head} screw clearance", shape, "cut", dims)


def self_tap_pilot(size: str = "M3", depth: float = 8.0) -> HardwarePart:
    """A pilot hole for a machine screw cut straight into printed plastic (no insert)."""
    s = _size(size)
    nominal = float(s[1:])
    d = round(nominal * 0.85, 2)
    shape = Pos(0, 0, OVERSHOOT) * Cylinder(d / 2, depth + OVERSHOOT, align=TOP)
    return HardwarePart(f"{s} self-tap pilot", shape, "cut", {
        "hole_d": _dim(d, provenance="assumed", source="0.85 x nominal, a common rule of thumb for screws into PLA/PETG"),
        "depth": _dim(depth, provenance="assumed", source="caller")})


def heat_insert_pocket(size: str = "M3", extra_depth: float = 1.0, lead_in: float = 0.4) -> HardwarePart:
    """The hole for a brass heat-set insert (CNC Kitchen dimensions), with room below for displaced plastic.

    size: "M3" (standard, 5.7 mm long) or "M3-short"; same for M4/M5. min_wall is the published minimum
    material around the hole: make the boss at least hole_d + 2 x min_wall."""
    key = str(size).strip().upper().replace("SHORT", "short")
    key = _size(key.split("-")[0]) + ("-short" if key.endswith("short") else "")
    if key not in INSERTS:
        raise RecipeError(f"No heat-set insert data for {size}", "", "Known: " + ", ".join(INSERTS) + ".")
    od, L, hole, wall = INSERTS[key]
    depth = L + extra_depth
    shape = Pos(0, 0, OVERSHOOT) * Cylinder(hole / 2, depth + OVERSHOOT, align=TOP)
    if lead_in > 0:
        shape = shape + Pos(0, 0, -lead_in) * Cone(hole / 2, hole / 2 + lead_in, lead_in, align=BOTTOM) \
            + Cylinder(hole / 2 + lead_in, OVERSHOOT, align=BOTTOM)
    return HardwarePart(f"{key} heat-set insert pocket", shape, "cut", {
        "hole_d": _dim(hole, source=INSERT_SOURCE), "insert_od": _dim(od, source=INSERT_SOURCE),
        "insert_length": _dim(L, source=INSERT_SOURCE), "min_wall": _dim(wall, source=INSERT_SOURCE),
        "depth": _dim(depth, provenance="assumed", source=f"insert length + {extra_depth:g} mm for displaced plastic"),
        "boss_min_d": _dim(hole + 2 * wall, provenance="computed", source="hole + 2 x minimum wall")})


def nut_trap(size: str = "M3", style: str = "hex", clearance: float = 0.15, depth: float | None = None,
             slot: float = 0.0) -> HardwarePart:
    """A pocket that holds a nut from turning: hex (ISO 4032) or square (DIN 562), below z = 0.

    clearance is added per side to the width across flats (assumed, FDM). slot > 0 extends the pocket that far
    along +X so the nut can slide in from the side (a captive nut slot)."""
    s = _size(size)
    if style not in NUTS:
        raise RecipeError(f"Unknown nut style “{style}”", "", "Use hex or square.")
    src, table = NUTS[style]
    if s in table:
        af, m = table[s]
    else:
        f = _bd("fastener")
        nut = (f.HexNut if style == "hex" else f.SquareNut)(_bd_size(s))
        af, m = float(nut.nut_data["s"]), float(nut.nut_thickness)
        src += " (via bd_warehouse)"
    w = af + 2 * clearance
    h = (m + 0.3) if depth is None else depth
    if style == "hex":
        prism = extrude(RegularPolygon(w / 2, 6, major_radius=False), amount=h + OVERSHOOT)
    else:
        prism = Box(w, w, h + OVERSHOOT, align=BOTTOM)
    shape = Pos(0, 0, -h) * prism
    if slot > 0:
        shape = shape + Pos(slot / 2, 0, -h) * Box(slot, w, h + OVERSHOOT, align=BOTTOM)
    return HardwarePart(f"{s} {style} nut trap", shape, "cut", {
        "across_flats": _dim(af, source=src), "nut_thickness": _dim(m, source=src),
        "pocket_af": _dim(w, provenance="computed", source=f"across flats + 2 x {clearance:g} mm (assumed FDM clearance)"),
        "depth": _dim(h, provenance="computed", source="nut thickness + 0.3 mm" if depth is None else "caller"),
        "pocket_corner_d": _dim(w / math.cos(math.pi / 6) if style == "hex" else w * math.sqrt(2), provenance="computed",
                                source="pocket across corners")})


def magnet_pocket(d: float, h: float, clearance: float = 0.1, extra_depth: float = 0.2) -> HardwarePart:
    """A round pocket for a disc magnet of diameter d and thickness h (measure your magnets)."""
    if d <= 0 or h <= 0:
        raise RecipeError("Magnet diameter and thickness must be positive", "", "Measure the magnet with calipers.")
    D, depth = d + 2 * clearance, h + extra_depth
    shape = Pos(0, 0, OVERSHOOT) * Cylinder(D / 2, depth + OVERSHOOT, align=TOP)
    return HardwarePart(f"{d:g} x {h:g} mm magnet pocket", shape, "cut", {
        "magnet_d": _dim(d, provenance="assumed", source="caller; measure the magnet"),
        "magnet_h": _dim(h, provenance="assumed", source="caller; measure the magnet"),
        "pocket_d": _dim(D, provenance="computed", source=f"magnet + 2 x {clearance:g} mm"),
        "depth": _dim(depth, provenance="computed", source=f"thickness + {extra_depth:g} mm")})


def bearing_seat(designation: str = "608", fit: float = 0.05, through: float = 3.0, lip: bool = True) -> HardwarePart:
    """A pocket for a deep-groove ball bearing's outer ring, depth = bearing width, opening at z = 0.

    fit: added to the outside diameter (mm, assumed). 0-0.1 is a light press in most FDM printers; calibrate.
    through > 0 continues below the seat with a smaller hole, leaving a lip that the outer ring sits on but the
    inner ring clears (shoulder between d1 and Da, ISO 15 abutment dimensions)."""
    key = str(designation).strip()
    if key in BEARINGS:
        d, D, B, d1, Da = BEARINGS[key]
        src = BEARING_SOURCE
    else:
        be = _bd("bearing")
        try:
            b = be.SingleRowDeepGrooveBallBearing(key)
        except Exception as e:
            raise RecipeError(f"Unknown bearing “{designation}” ({e})", "", "Known here: " + ", ".join(BEARINGS) +
                              "; or a bd_warehouse size such as M8-22-7.")
        bd = b.bearing_dict
        d, D, B, d1, Da = bd["d"], bd["D"], bd["B"], bd["d1"], bd["Da"]
        src = BEARING_SOURCE + " (via bd_warehouse)"
    seat = D + fit
    shape = Pos(0, 0, OVERSHOOT) * Cylinder(seat / 2, B + OVERSHOOT, align=TOP)
    lip_d = (d1 + Da) / 2 if lip else seat
    if through > 0:
        shape = shape + Pos(0, 0, -B + 0.01) * Cylinder(lip_d / 2, through + 0.01, align=TOP)
    return HardwarePart(f"{key} bearing seat", shape, "cut", {
        "bore": _dim(d, source=src), "outer_d": _dim(D, source=src), "width": _dim(B, source=src),
        "seat_d": _dim(seat, provenance="computed", source=f"outer diameter + {fit:g} mm (assumed press fit)"),
        "lip_hole_d": _dim(lip_d, provenance="computed", source="midway between inner-ring shoulder d1 and housing shoulder Da")})


# ---- threads -----------------------------------------------------------------------------------------------
def thread(major_d: float, pitch: float, length: float, external: bool = True, clearance: float = 0.3,
           chamfer: bool = True) -> HardwarePart:
    """A printable ISO metric thread (bd_warehouse IsoThread). Use pitch >= 1 mm for FDM.

    external=True: a threaded rod standing on z = 0 (kind "add"), major diameter reduced by `clearance`.
    external=False: a cutter for a threaded hole, opening at z = 0 going down (kind "cut"), major diameter
    increased by `clearance`. One external and one internal part with the default 0.3 mm each mate with
    0.6 mm of diametral play: a free fit on most FDM printers (assumed)."""
    th_mod = _bd("thread")
    if pitch < 0.5 or major_d < 4 * pitch or length < 2 * pitch:
        raise RecipeError(f"Thread M{major_d:g}x{pitch:g}, {length:g} mm long is not printable", "",
                          "Use pitch >= 1 mm, a diameter >= 4 x pitch and a length >= 2 x pitch.")
    ends = ("chamfer", "chamfer") if chamfer else ("square", "square")
    if external:
        D = major_d - clearance
        th = th_mod.IsoThread(major_diameter=D, pitch=pitch, length=length, external=True, end_finishes=ends)
        core = Cylinder(th.min_radius + 0.002, length, align=BOTTOM)
        shape = core + th
        kind = "add"
    else:
        D = major_d + clearance
        th = th_mod.IsoThread(major_diameter=D, pitch=pitch, length=length, external=False, end_finishes=("fade", "fade"))
        r_out = D / 2
        bore = Cylinder(r_out, length, align=BOTTOM)
        shape = Pos(0, 0, -length) * (bore - th) + Cylinder(r_out, OVERSHOOT, align=BOTTOM)
        kind = "cut"
    if not shape.is_valid:
        raise RecipeError("The thread did not build as a valid solid", "", "Try a coarser pitch or a different length.")
    return HardwarePart(f"M{major_d:g}x{pitch:g} {'external' if external else 'internal'} thread", shape, kind, {
        "major_d": _dim(major_d, provenance="specified", source="ISO 261/ISO 68-1 basic profile (bd_warehouse IsoThread)"),
        "pitch": _dim(pitch, provenance="specified", source="ISO 261"),
        "modelled_major_d": _dim(D, provenance="computed", source=f"major {'−' if external else '+'} {clearance:g} mm FDM clearance (assumed)"),
        "length": _dim(length, provenance="assumed", source="caller")})


# ---- gears -------------------------------------------------------------------------------------------------
def centre_distance(module: float, teeth_a: int, teeth_b: int) -> float:
    """Standard centre distance of two external spur gears without profile shift: m (z1 + z2) / 2."""
    return module * (teeth_a + teeth_b) / 2


def contact_ratio(module: float, teeth_a: int, teeth_b: int, pressure_angle: float = 20.0) -> float:
    """Transverse contact ratio of a standard (unshifted, full-depth) external spur pair."""
    a = math.radians(pressure_angle)
    ra1, ra2 = module * (teeth_a / 2 + 1), module * (teeth_b / 2 + 1)
    rb1, rb2 = module * teeth_a / 2 * math.cos(a), module * teeth_b / 2 * math.cos(a)
    C = centre_distance(module, teeth_a, teeth_b)
    return (math.sqrt(ra1 ** 2 - rb1 ** 2) + math.sqrt(ra2 ** 2 - rb2 ** 2) - C * math.sin(a)) / (math.pi * module * math.cos(a))


@functools.lru_cache(maxsize=64)
def contact_ratio_modelled(module: float, teeth_a: int, teeth_b: int, backlash: float = 0.0,
                           pressure_angle: float = 20.0) -> tuple[float, str]:
    """Contact ratio of the teeth FORM actually builds (tip rounding, undercut, thinning), from py_gearworks.

    Falls back to the standard formula, and says so, when the library is missing."""
    try:
        g = _bd("gear")
    except RecipeError:
        return contact_ratio(module, teeth_a, teeth_b, pressure_angle), "standard full-depth formula (py_gearworks not installed)"
    ga = _spur(module, teeth_a, 1.0, backlash / 2, pressure_angle)
    gb = _spur(module, teeth_b, 1.0, backlash / 2, pressure_angle)
    gb.mesh_to(ga)
    return float(g.get_contact_ratio(ga, gb)), "py_gearworks, on the modelled tooth profiles"


def _gear_dims(module, teeth, thickness, pressure_angle, backlash_each):
    m, z = module, teeth
    src = "involute spur gear, standard full-depth proportions (computed)"
    return {"module": _dim(m, unit="mm", provenance="assumed", source="caller"),
            "teeth": _dim(z, unit="", provenance="assumed", source="caller"),
            "pitch_d": _dim(m * z, provenance="computed", source="m x z; " + src),
            "tip_d": _dim(m * (z + 2), provenance="computed", source="m (z + 2)"),
            "root_d": _dim(m * (z - 2.4), provenance="computed", source="m (z - 2.4), dedendum 1.2 m"),
            "base_d": _dim(m * z * math.cos(math.radians(pressure_angle)), provenance="computed", source="pitch d x cos(pressure angle)"),
            "thickness": _dim(thickness, provenance="assumed", source="caller"),
            "tooth_thinning": _dim(backlash_each, provenance="assumed",
                                   source="backlash share of this gear, along the line of action")}


def _spur(module, teeth, thickness, backlash_each, pressure_angle):
    g = _bd("gear")
    if int(teeth) != teeth or teeth < 6:
        raise RecipeError(f"A spur gear needs a whole number of teeth, at least 6 (got {teeth:g})", "", "Use 10 or more teeth.")
    return g.SpurGear(number_of_teeth=int(teeth), module=module, height=thickness, backlash=backlash_each / module,
                      pressure_angle=math.radians(pressure_angle), root_fillet=0.25, tip_fillet=0.1)


def _finish_gear(gear_obj, bore: float, thickness: float):
    part = gear_obj.build_part()
    shape = part.solids()[0] if len(part.solids()) == 1 else part
    if bore > 0:
        c = gear_obj.center
        shape = shape - Pos(float(c[0]), float(c[1]), -0.1) * Cylinder(bore / 2, thickness + 0.2, align=BOTTOM)
    return shape


def spur_gear(module: float = 1.5, teeth: int = 20, thickness: float = 6.0, bore: float = 5.0,
              backlash: float = 0.1, pressure_angle: float = 20.0) -> HardwarePart:
    """An involute spur gear (py_gearworks) standing on z = 0, centred on the origin.

    backlash: the share of mesh backlash this gear takes, in mm along the line of action; the teeth are thinned
    by that much so two gears at the standard centre distance run with the sum of their shares."""
    if module < 0.5:
        raise RecipeError(f"Module {module:g} is too fine to print", "", "Use module >= 0.8 for FDM; 1.5 or more prints cleanly.")
    if bore and bore >= module * (teeth - 2.4) - 2:
        raise RecipeError("The bore leaves under 1 mm of gear below the tooth roots", "", "Use a smaller bore or more teeth.")
    g = _spur(module, teeth, thickness, backlash, pressure_angle)
    shape = _finish_gear(g, bore, thickness)
    dims = _gear_dims(module, teeth, thickness, pressure_angle, backlash)
    dims["bore"] = _dim(bore, provenance="assumed", source="caller")
    return HardwarePart(f"m{module:g} z{int(teeth)} spur gear", shape, "add", dims)


@dataclass
class GearPair:
    a: HardwarePart               # at the origin
    b: HardwarePart               # at (centre_distance, 0), rotated to mesh
    centre_distance: float
    backlash: float
    contact_ratio: float
    dims: dict


def gear_pair(module: float = 1.5, teeth_a: int = 15, teeth_b: int = 30, thickness: float = 6.0,
              bore_a: float = 5.0, bore_b: float = 5.0, backlash: float = 0.2, pressure_angle: float = 20.0) -> GearPair:
    """Two meshing spur gears: a at the origin, b at +X by the standard centre distance, rotated into mesh.

    backlash: total mesh backlash in mm (along the line of action), split equally between the two gears by
    thinning their teeth; the centre distance stays m (z1 + z2) / 2 so axle holes go at a standard spacing.
    Move b's shape (e.g. Pos(dx, 0, 0) * pair.b.shape) to lay the gears out apart for printing."""
    for bore, z, nm in ((bore_a, teeth_a, "a"), (bore_b, teeth_b, "b")):
        if bore and bore >= module * (z - 2.4) - 2:
            raise RecipeError(f"Gear {nm}: the bore leaves under 1 mm below the tooth roots", "", "Use a smaller bore or more teeth.")
    ga = _spur(module, teeth_a, thickness, backlash / 2, pressure_angle)
    gb = _spur(module, teeth_b, thickness, backlash / 2, pressure_angle)
    gb.mesh_to(ga)                                         # places b at +X, rotated so its teeth sit in a's gaps
    C = centre_distance(module, teeth_a, teeth_b)
    if abs(float(gb.center[0]) - C) > 1e-3:
        raise RecipeError(f"Gear library placed the pair {gb.center[0]:.3f} mm apart; expected {C:.3f}", "",
                          "Report this: py_gearworks meshing does not match the standard centre distance.")
    sa = _finish_gear(ga, bore_a, thickness)
    sb = _finish_gear(gb, bore_b, thickness)
    da = _gear_dims(module, teeth_a, thickness, pressure_angle, backlash / 2)
    db = _gear_dims(module, teeth_b, thickness, pressure_angle, backlash / 2)
    da["bore"], db["bore"] = _dim(bore_a, provenance="assumed", source="caller"), _dim(bore_b, provenance="assumed", source="caller")
    eps, eps_src = contact_ratio_modelled(module, int(teeth_a), int(teeth_b), backlash, pressure_angle)
    dims = {"centre_distance": _dim(C, provenance="computed", source="m (z1 + z2) / 2"),
            "ratio": _dim(teeth_b / teeth_a, unit="", provenance="computed", source="z2 / z1"),
            "backlash": _dim(backlash, provenance="assumed", source="total, along the line of action"),
            "contact_ratio": _dim(eps, unit="", provenance="computed", source=eps_src)}
    return GearPair(HardwarePart(f"m{module:g} z{int(teeth_a)} spur gear", sa, "add", da),
                    HardwarePart(f"m{module:g} z{int(teeth_b)} spur gear", sb, "add", db), C, backlash, eps, dims)


def checked(stages: list) -> list:
    """Raise a RecipeError naming the first stage whose boolean result is not a valid solid.

    A failed boolean can leave a valid fragment in a later stage; checking every stage catches it."""
    for st in stages:
        if not st.shape.is_valid or st.shape.volume <= 0:
            raise RecipeError(f"The {st.feature} step did not produce a valid solid", st.feature,
                              "Change the parameters of this feature slightly; coincident or tangent faces usually cause it.")
    return stages


def available() -> dict:
    """Which optional libraries are importable here (for setup and diagnostics)."""
    out = {}
    for mod in ("bd_warehouse", "py_gearworks"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "installed")
        except ImportError:
            out[mod] = None
    return out
