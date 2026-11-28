"""Standard hardware for designs: screws, heat-set inserts, nuts, washers, threads, bearings, magnets, gears,
sprockets and chain, pipes and flanges.

A thin, stable FORM API over published dimensions and two libraries that ship with Form Studio:

  bd_warehouse  (fasteners, threads, bearings, sprockets, flanges, pipe data)  https://github.com/gumyr/bd_warehouse
  py_gearworks  (involute gears)                                               https://github.com/GarryBGoode/py_gearworks

and bd_materials (densities) through form.material_library.

Two kinds of call:
  pockets and holes (kind "cut"): screw_clearance, tap_hole, self_tap_pilot, heat_insert_pocket, nut_trap,
      magnet_pocket, bearing_seat, pipe_socket, thread(external=False), trapezoidal_thread(external=False),
      bottle_thread(external=False)
  the hardware itself (kind "hardware", a purchased part with .grams, .material and .bom()): screw, nut, washer,
      heat_insert, bearing, pipe, pipe_flange; printed geometry (kind "add"): thread, trapezoidal_thread,
      bottle_thread, spur_gear, gear_pair, sprocket.
  bolted_joint(size, clamp, into=...) puts them together: the clearance and counterbore through the clamped part,
  the insert pocket, nut trap or tap hole in the base, the screw of the right standard length, and the BOM rows.

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
THREAD_BORE_OVERLAP = 0.02      # mm a threaded hole's bore is moved off the thread's root when the cut fails there
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
# Brass heat-set inserts (CNC Kitchen product pages): the table lives in form.catalog, the standard-parts library.
from .catalog import INSERT_SOURCE, INSERTS  # noqa: E402
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
    kind: str                     # "cut" | "add" | "hardware" (a purchased part: place it, never fuse it)
    dims: dict = field(default_factory=dict)
    grams: float | None = None    # hardware: modelled volume x typical density (computed)
    material: str = ""            # hardware: what it is made of (form.material_library id)
    standard: str = ""            # hardware: the standard or supplier reference ("ISO 4762", "CNC Kitchen")
    size: str = ""                # hardware: the size as it is ordered ("M3 x 10")

    def __getitem__(self, key: str) -> float:
        return self.dims[key]["value"]

    def bom(self, qty: int = 1, note: str = "", after: str = "", access: tuple = (), url: str = ""):
        """This hardware as an Assembly Hardware row (BOM, assembly steps), with its mass."""
        from .recipes.assembly import Hardware
        return Hardware(self.name, self.size, int(qty), self.standard, note, after, tuple(access), url,
                        grams=self.grams, material=self.material)

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
        elif module == "sprocket":
            from bd_warehouse import sprocket as m
        elif module == "flange":
            from bd_warehouse import flange as m
        elif module == "pipe":
            from bd_warehouse import pipe as m
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
            # The head's cone is the theoretical sharp cone, dk = 2 d (ISO 10642), cut flat at the actual dk: a sink
            # sized from the actual dk would be narrower than the cone below the top and grip the head off its seat.
            D = 2 * float(s[1:]) + head_clearance
            depth = (D - d) / 2                                       # 90° included angle
            sink = Cone(d / 2, D / 2, depth, align=BOTTOM)
            sink = Pos(0, 0, -depth) * sink + Cylinder(D / 2, OVERSHOOT, align=BOTTOM)
            shape = shape + sink
            dims["countersink_d"] = _dim(D, provenance="computed",
                                         source="ISO 10642 theoretical head diameter (2 d) + head clearance")
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
def _minus_ridges(bore, ridges):
    """A threaded hole's cutter: the bore minus the nut's thread ridges. OCCT's cut of a bore by the helical ridges
    can fail silently and return the whole bore (a plain hole, no thread: seen on M8 x 1.25 and M12 x 1.75), so the
    ridges inside the bore are found first (a common) and those are cut; a cutter that still lost none raises."""
    inside = bore & ridges
    kept = float(inside.volume) if inside is not None else 0.0
    out = bore - inside if kept > 1e-6 else bore
    if kept <= 1e-6 or float(bore.volume) - float(out.volume) < 0.5 * kept:
        raise RecipeError("The threaded hole came out without thread ridges", "",
                          "Try a different length, pitch or clearance; a plain bore would not hold the screw.")
    return out


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
        cutter, r_out = _ridged_bore(th, r_out, length, f"M{major_d:g}x{pitch:g} internal thread")
        shape = Pos(0, 0, -length) * cutter + Cylinder(r_out, OVERSHOOT, align=BOTTOM)
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


# ---- the hardware itself (purchased parts: place them in an assembly, list them in the BOM) -------------------
# Tap drills for ISO coarse threads (soft = aluminium/brass/plastic, hard = steel), mm. Same values as bd_warehouse
# 0.4.0 data/tap_hole_sizes.csv.
TAP_SOURCE = "tap drill for ISO coarse threads (bd_warehouse tap_hole_sizes, Soft/Hard)"
TAP_DRILL = {"M2": (1.6, 1.75), "M2.5": (2.05, 2.2), "M3": (2.5, 2.7), "M4": (3.3, 3.5), "M5": (4.2, 4.5), "M6": (5.0, 5.4)}
# ISO 7089 plain washers (d1 inner, d2 outer, h thickness), mm, as tabulated in bd_warehouse 0.4.0.
WASHER_SOURCE = "ISO 7089 plain washer (d1, d2, h; bd_warehouse table)"
WASHERS = {"M2": (2.2, 5, 0.35), "M2.5": (2.7, 6, 0.55), "M3": (3.2, 7, 0.55), "M4": (4.3, 9, 0.9),
           "M5": (5.3, 10, 1.1), "M6": (6.4, 12, 1.8)}
# head style: (bd_warehouse class, fastener type, standard)
SCREW_TYPES = {"socket": ("SocketHeadCapScrew", "iso4762", "ISO 4762"), "pan": ("PanHeadScrew", "iso14583", "ISO 14583"),
               "countersunk": ("CounterSunkScrew", "iso10642", "ISO 10642"),
               "button": ("ButtonHeadScrew", "iso7380_1", "ISO 7380-1"), "hex": ("HexHeadScrew", "iso4017", "ISO 4017")}
# preferred lengths when bd_warehouse is missing (ISO 4762's series)
ISO_LENGTHS = (3, 4, 5, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100)
# CNC Kitchen insert -> bd_warehouse HeatSetNut size (the knurled model)
_INSERT_BD = {"M2": "M2-0.4-3", "M2.5": "M2.5-0.45-4", "M3": "M3-0.5-5.7", "M3-short": "M3-0.5-3", "M4": "M4-0.7-8.1",
              "M4-short": "M4-0.7-4", "M5": "M5-0.8-9.5", "M5-short": "M5-0.8-5.8"}
MASS_SOURCE = "computed: modelled volume x typical density (form.material_library)"


def _have(module: str) -> bool:
    try:
        _bd(module)
        return True
    except RecipeError:
        return False


def _material_id(m) -> str:
    fam = str(getattr(m, "family", "") or "").lower()
    return fam or str(getattr(m, "name", "")).lower()


def _mass(obj, material: str | None = None) -> tuple[float | None, str]:
    """Grams of a bd_warehouse part from the material it declares (children summed), or of any shape in `material`."""
    from . import material_library as ml
    if material:
        return ml.mass_g(obj.volume, material), material
    fm = getattr(obj, "material", None)
    m = getattr(fm, "material", None)
    if m is not None and getattr(m, "density", None):
        return round(float(obj.volume) * float(m.density) * 1e-6, 3), _material_id(m)
    kids = list(getattr(obj, "children", None) or [])
    if kids:
        tot, mats = 0.0, []
        for k in kids:
            g, mid = _mass(k)
            if g is None:
                return None, ""
            tot += g
            if mid and mid not in mats:
                mats.append(mid)
        return round(tot, 3), "+".join(mats)
    return None, ""


def _placed(p: HardwarePart, loc) -> HardwarePart:
    return HardwarePart(p.name, loc * p.shape, p.kind, p.dims, p.grams, p.material, p.standard, p.size)


def nominal_lengths(size: str = "M3", head: str = "socket") -> list[float]:
    """The standard lengths a screw of this size and head is sold in (mm)."""
    s = _size(size)
    if head not in SCREW_TYPES:
        raise RecipeError(f"Unknown screw head “{head}”", "", "Use " + ", ".join(SCREW_TYPES) + ".")
    if not _have("fastener"):
        return [float(x) for x in ISO_LENGTHS]
    f = _bd("fastener")
    cls, typ, _ = SCREW_TYPES[head]
    try:
        L = sorted(set(float(x) for x in getattr(f, cls)(_bd_size(s), 10, typ).nominal_lengths))
    except ValueError:
        L = sorted(float(x) for x in f.Screw.nominal_length_range[typ])
    if typ == "iso1580" and 68.0 in L:        # bd_warehouse 0.4.0 data bug (a missing comma), fixed upstream after 0.4.0
        L = sorted((set(L) - {68.0}) | {6.0, 8.0})
    return L


def screw(size: str = "M3", length: float = 10.0, head: str = "socket", threaded: bool = False) -> HardwarePart:
    """A real screw (bd_warehouse): the head's bearing face at z = 0, shank down -Z; a countersunk head's top at z = 0.

    That is where it sits on a flat face; in a counterbore move it down by the recess depth (bolted_joint does it).
    length is the ISO length (under the head; overall for countersunk). threaded=True models the helical thread
    (slower, for close-up renders); False is a plain shank at the thread's minor diameter (bd_warehouse)."""
    s = _size(size)
    if length <= 0:
        raise RecipeError("Screw length must be positive", "", "Give the ISO length in mm.")
    if head not in SCREW_TYPES:
        raise RecipeError(f"Unknown screw head “{head}”", "", "Use " + ", ".join(SCREW_TYPES) + ".")
    cls, typ, std = SCREW_TYPES[head]
    d = float(s[1:])
    if _have("fastener"):
        f = _bd("fastener")
        try:
            obj = getattr(f, cls)(_bd_size(s), length, typ, simple=not threaded)
        except ValueError as e:
            raise RecipeError(f"No {std} screw {s} x {length:g}: {e}", "", "Pick another size or head.")
        dk, k = float(obj.head_diameter), float(obj.head_height)
        grams, mat = _mass(obj)
        shape, src = obj, f"{std} (bd_warehouse)"
    else:
        if head not in HEADS:
            raise RecipeError(f"The {head} head needs bd_warehouse", "", INSTALL_HINT)
        dk, k, src = head_dims(s, head)
        if head == "countersunk":
            shape = Pos(0, 0, -k) * Cone(d / 2, dk / 2, k, align=BOTTOM) + Pos(0, 0, -k) * Cylinder(d / 2, length - k, align=TOP)
        else:
            shape = Cylinder(dk / 2, k, align=BOTTOM) + Cylinder(d / 2, length, align=TOP)
        mat = "mild_steel"
        grams, _ = _mass(shape, mat)
    lengths = nominal_lengths(s, head)
    std_len = any(abs(length - x) < 1e-6 for x in lengths)
    dims = {"d": _dim(d, source="nominal size"), "length": _dim(length, provenance="assumed", source="caller"),
            "head_d": _dim(dk, source=src), "head_h": _dim(k, source=src),
            "standard_length": _dim(1 if std_len else 0, unit="", provenance="computed",
                                    source=f"{std} length series" + ("" if std_len else ": not a stock length"))}
    if grams is not None:
        dims["grams"] = _dim(grams, unit="g", provenance="computed", source=MASS_SOURCE)
    return HardwarePart(f"{s} x {length:g} {head} screw", shape, "hardware", dims, grams, mat, std, f"{s} x {length:g}")


def nut(size: str = "M3", style: str = "hex") -> HardwarePart:
    """A nut standing on z = 0, axis Z: hex (ISO 4032, bd_warehouse) or thin square (DIN 562, the nut_trap table)."""
    s = _size(size)
    if style not in NUTS:
        raise RecipeError(f"Unknown nut style “{style}”", "", "Use hex or square.")
    src, table = NUTS[style]
    if style == "hex" and _have("fastener"):
        obj = _bd("fastener").HexNut(_bd_size(s), "iso4032")
        af, m = float(obj.nut_data["s"]), float(obj.nut_thickness)
        shape, (grams, mat) = obj, _mass(obj)
        src += " (bd_warehouse)"
    elif s in table:
        af, m = table[s]
        prism = extrude(RegularPolygon(af / 2, 6, major_radius=False), amount=m) if style == "hex" else Box(af, af, m, align=BOTTOM)
        shape = prism - Cylinder(float(s[1:]) / 2 * 0.85, m, align=BOTTOM)
        mat = "mild_steel"
        grams, _ = _mass(shape, mat)
    else:
        raise RecipeError(f"No {style} nut data for {s} here", "", INSTALL_HINT)
    std = "ISO 4032" if style == "hex" else "DIN 562"
    return HardwarePart(f"{s} {style} nut", shape, "hardware", {
        "across_flats": _dim(af, source=src), "thickness": _dim(m, source=src),
        "grams": _dim(grams, unit="g", provenance="computed", source=MASS_SOURCE)}, grams, mat, std, s)


def washer(size: str = "M3") -> HardwarePart:
    """An ISO 7089 plain washer standing on z = 0."""
    s = _size(size)
    if _have("fastener"):
        obj = _bd("fastener").PlainWasher(s, "iso7089")
        d1, d2, h = (float(obj.washer_data[k]) for k in ("d1", "d2", "h"))
        shape, (grams, mat) = obj, _mass(obj)
    elif s in WASHERS:
        d1, d2, h = WASHERS[s]
        shape = Cylinder(d2 / 2, h, align=BOTTOM) - Cylinder(d1 / 2, h, align=BOTTOM)
        mat = "mild_steel"
        grams, _ = _mass(shape, mat)
    else:
        raise RecipeError(f"No washer data for {s} here", "", INSTALL_HINT)
    return HardwarePart(f"{s} washer", shape, "hardware", {
        "inner_d": _dim(d1, source=WASHER_SOURCE), "outer_d": _dim(d2, source=WASHER_SOURCE),
        "thickness": _dim(h, source=WASHER_SOURCE),
        "grams": _dim(grams, unit="g", provenance="computed", source=MASS_SOURCE)}, grams, mat, "ISO 7089", s)


def _insert_key(size: str) -> str:
    key = str(size).strip().upper().replace("SHORT", "short")
    return _size(key.split("-")[0]) + ("-short" if key.endswith("short") else "")


def heat_insert(size: str = "M3") -> HardwarePart:
    """A brass heat-set insert (CNC Kitchen sizes) as fitted: top flush with z = 0, going down -Z. Its pocket is
    heat_insert_pocket(size): the hole is smaller than the insert on purpose; the insert melts its way in."""
    key = _insert_key(size)
    if key not in INSERTS:
        raise RecipeError(f"No heat-set insert data for {size}", "", "Known: " + ", ".join(INSERTS) + ".")
    od, L, hole, wall = INSERTS[key]
    if _have("fastener"):
        shape = Pos(0, 0, -L) * _bd("fastener").HeatSetNut(_INSERT_BD[key], "CNCKitchen")
    else:
        bore = float(key.split("-")[0][1:])
        shape = Pos(0, 0, -L) * (Cylinder(od / 2, L, align=BOTTOM) - Cylinder(bore / 2, L, align=BOTTOM))
    grams, mat = _mass(shape, "brass")          # CNC Kitchen inserts are brass (bd_warehouse labels its model steel)
    return HardwarePart(f"{key} heat-set insert", shape, "hardware", {
        "insert_od": _dim(od, source=INSERT_SOURCE), "insert_length": _dim(L, source=INSERT_SOURCE),
        "hole_d": _dim(hole, source=INSERT_SOURCE),
        "interference": _dim(round(od - hole, 3), provenance="computed", source="insert OD - recommended hole: plastic it displaces"),
        "grams": _dim(grams, unit="g", provenance="computed", source=MASS_SOURCE)}, grams, mat, "CNC Kitchen",
        f"{key.split('-')[0]} x {L:g}")


def tap_hole(size: str = "M3", depth: float = 8.0, material: str = "soft") -> HardwarePart:
    """A tap-drill hole for cutting an ISO coarse thread with a tap (metal, wood, dense plastic stock), below z = 0.

    material: "soft" (aluminium, brass, plastics) or "hard" (steel). For a printed part use self_tap_pilot or a
    heat-set insert instead: a tapped thread in printed plastic strips."""
    s = _size(size)
    if material not in ("soft", "hard"):
        raise RecipeError(f"Unknown tap material “{material}”", "", "Use soft (aluminium, brass, plastic) or hard (steel).")
    if s in TAP_DRILL:
        d, src = TAP_DRILL[s][0 if material == "soft" else 1], TAP_SOURCE
    else:
        f = _bd("fastener")
        d = float(f.SocketHeadCapScrew(_bd_size(s), 10).tap_hole_diameters[material.capitalize()])
        src = TAP_SOURCE + " (via bd_warehouse)"
    P = PITCH.get(s) or float(_bd_size(s).split("-")[1])
    D1 = float(s[1:]) - 1.0825 * P
    shape = Pos(0, 0, OVERSHOOT) * Cylinder(d / 2, depth + OVERSHOOT, align=TOP)
    return HardwarePart(f"{s} tap hole ({material})", shape, "cut", {
        "hole_d": _dim(d, source=src), "pitch": _dim(P, source="ISO 261 coarse"),
        "basic_minor_d": _dim(round(D1, 3), provenance="computed", source="ISO 68-1: d - 1.0825 P"),
        "depth": _dim(depth, provenance="assumed", source="caller")})


def bearing(designation: str = "608") -> HardwarePart:
    """A deep-groove ball bearing (bd_warehouse model: rings, balls, cage) standing on z = 0, axis Z. It fits
    bearing_seat(designation) with the seat's opening at the bearing's top face."""
    key = str(designation).strip()
    if _have("bearing"):
        try:
            obj = _bd("bearing").SingleRowDeepGrooveBallBearing(_BEARING_BD.get(key, key))
        except Exception as e:
            raise RecipeError(f"Unknown bearing “{designation}” ({e})", "", "Known here: " + ", ".join(BEARINGS) +
                              "; or a bd_warehouse size such as M8-22-7.")
        bd = obj.bearing_dict
        d, D, B = float(bd["d"]), float(bd["D"]), float(bd["B"])
        shape, (grams, mat), src = obj, _mass(obj), BEARING_SOURCE + " (bd_warehouse)"
    elif key in BEARINGS:
        d, D, B = BEARINGS[key][:3]
        shape = Cylinder(D / 2, B, align=BOTTOM) - Cylinder(d / 2, B, align=BOTTOM)
        mat, src = "alloy_steel", BEARING_SOURCE
        grams = round(_mass(shape, mat)[0] * 0.6, 2)    # a solid ring overstates it; about 60 % of it is steel
    else:
        raise RecipeError(f"Unknown bearing “{designation}”", "", INSTALL_HINT)
    return HardwarePart(f"{key} bearing", shape, "hardware", {
        "bore": _dim(d, source=src), "outer_d": _dim(D, source=src), "width": _dim(B, source=src),
        "grams": _dim(grams, unit="g", provenance="computed", source=MASS_SOURCE)}, grams, mat, "ISO 15",
        f"{d:g} x {D:g} x {B:g}")


# ---- screw length and whole bolted joints ------------------------------------------------------------------
def screw_length(size: str, shortest: float, longest: float = 1e9, head: str = "socket") -> float:
    """The shortest stock length in [shortest, longest]; RecipeError when none fits."""
    for L in nominal_lengths(size, head):
        if shortest - 1e-6 <= L <= longest + 1e-6:
            return L
    raise RecipeError(f"No stock {_size(size)} {head} screw is between {shortest:.1f} and {longest:.1f} mm long", "",
                      "Change the thickness of the parts so a stock length fits; stock lengths: " +
                      ", ".join(f"{x:g}" for x in nominal_lengths(size, head)[:14]) + " mm.")


@dataclass
class BoltedJoint:
    """One screw joint. Frame: z = 0 is the top face of the clamped part, which spans -clamp..0; the base (the part
    the screw holds in) starts at z = -clamp and goes down. Cut both parts at the same position::

        lid = lid - Pos(x, y, z_top) * j.top.shape
        box = box - Pos(x, y, z_top) * j.bottom.shape
    """
    top: HardwarePart             # clearance hole + counterbore / countersink through the clamped part
    bottom: HardwarePart          # insert pocket, nut trap, tap hole or pilot in the base
    screw: HardwarePart           # placed as fitted
    parts: list                   # every purchased part, placed as fitted (screw, and the insert or nut)
    length: float                 # the stock screw length chosen
    base_min: float               # the thinnest base that holds it (mm, from z = -clamp down)
    dims: dict

    def hardware(self, qty: int = 1, after: str = "", note: str = "") -> list:
        """Assembly Hardware rows (BOM) for qty of these joints."""
        return [p.bom(qty, note or ("Screw through the clamped part." if p is self.screw else "Fit before the screw."),
                      after) for p in self.parts]


def bolted_joint(size: str = "M3", clamp: float = 5.0, into: str = "insert", head: str = "socket",
                 base: float | None = None, fit: str = "normal", material: str = "soft") -> BoltedJoint:
    """A screw clamping a part `clamp` mm thick onto a base, with a stock screw length chosen so the thread engages
    enough and never bottoms out.

    into: "insert" (brass heat-set insert in a printed base), "nut" (hex nut trapped from the base's underside; give
    `base`, the base thickness), "tap" (tapped hole in metal or wood stock; material "soft" or "hard") or "self_tap"
    (screw cut straight into printed plastic). Engagement rules are rules of thumb (provenance "assumed"): insert
    >= 0.6 x insert length; tap >= 1.5 d soft / 1.0 d hard; self-tap >= 2 d; the screw passes a nut by one to three
    pitches."""
    s = _size(size)
    d = float(s[1:])
    P = PITCH.get(s) or float(_bd_size(s).split("-")[1])
    if clamp <= 0:
        raise RecipeError("The clamped part must have a thickness", "", "Give clamp in mm.")
    if into not in ("insert", "nut", "tap", "self_tap"):
        raise RecipeError(f"Unknown joint “{into}”", "", "Use insert, nut, tap or self_tap.")
    top = screw_clearance(s, clamp, head=head if head in HEADS else "socket", fit=fit, recess=head in HEADS)
    sink = top["recess_depth"] if head in ("socket", "pan") else 0.0
    above = clamp if head == "countersunk" else clamp - sink        # screw length inside the clamped part
    rows = {}
    if into == "insert":
        ins = heat_insert_pocket(s)
        L = screw_length(s, above + 0.6 * ins["insert_length"], above + ins["depth"] - 0.3, head)
        bottom = _placed(ins, Pos(0, 0, -clamp))
        extra = [_placed(heat_insert(s), Pos(0, 0, -clamp))]
        base_min = ins["depth"] + 1.0
        rows["engagement"] = _dim(round(min(L - above, ins["insert_length"]), 3), provenance="computed",
                                  source="thread inside the insert")
    elif into in ("tap", "self_tap"):
        need = ((1.5 if material == "soft" else 1.0) if into == "tap" else 2.0) * d
        L = screw_length(s, above + need, head=head)
        depth = L - above + (3 * P if into == "tap" else 1.0)
        hole = tap_hole(s, depth, material) if into == "tap" else self_tap_pilot(s, depth)
        bottom = _placed(hole, Pos(0, 0, -clamp))
        extra, base_min = [], depth + 1.0
        rows["engagement"] = _dim(round(L - above, 3), provenance="computed", source="thread below the clamped part")
        rows["engagement_min"] = _dim(need, provenance="assumed",
                                      source="rule of thumb: 1.5 d into aluminium, 1 d into steel, 2 d into printed plastic")
    else:
        trap, n = nut_trap(s, "hex"), nut(s, "hex")
        m, h = n["thickness"], trap["depth"]
        if base is None:
            base = round(max(h + 1.6, 3.0), 2)
        L = screw_length(s, above + base - h + m + P, above + base + 3 * P, head)
        hole_d = clearance_d(s, fit)[0]
        shape = Pos(0, 0, -clamp + OVERSHOOT) * Cylinder(hole_d / 2, base + 2 * OVERSHOOT, align=TOP) \
            + Pos(0, 0, -clamp - base) * Rot(180, 0, 0) * trap.shape
        bottom = HardwarePart(f"{s} nut trap with clearance hole", shape, "cut",
                              {**trap.dims, "base": _dim(base, provenance="assumed", source="caller")})
        extra = [_placed(n, Pos(0, 0, -clamp - base + h - m))]       # nut pulled up against the pocket's ceiling
        base_min = h + 1.0
        rows["protrusion"] = _dim(round(L - above - (base - h + m), 3), provenance="computed",
                                  source="thread past the nut's far face")
    if base is not None and base < base_min:
        raise RecipeError(f"The base is {base:.1f} mm thick; this {s} joint needs {base_min:.1f} mm", "",
                          "Thicken the base or boss, or use a shorter insert.")
    placed = _placed(screw(s, L, head), Pos(0, 0, -sink))
    rows.update({"length": _dim(L, source=f"{SCREW_TYPES[head][2]} stock length"),
                 "clamp": _dim(clamp, provenance="assumed", source="caller"),
                 "thread_below": _dim(round(L - above, 3), provenance="computed", source="length - screw inside the clamped part"),
                 "base_min": _dim(round(base_min, 2), provenance="computed", source="deepest cut in the base + 1 mm floor")})
    return BoltedJoint(top, bottom, placed, [placed] + extra, L, round(base_min, 2), rows)


# ---- lead screws and bottle threads -------------------------------------------------------------------------
def _ridged_bore(th, r_out: float, length: float, label: str):
    """(the cutter of a threaded hole: a bore minus the nut's thread ridges, the bore radius used).

    The cut is measured, not assumed. Where the bore and the thread's own root cylinder coincide, OCCT can return
    the bore untouched: a plain cylinder, and the hole cut with it has no thread at all. When the ridges are not
    gone from the cutter, the bore is moved by THREAD_BORE_OVERLAP off that surface (outward where the thread
    reaches past it, inward otherwise, so the ridges stay joined to the wall) and cut again; a cutter that is still
    plain is an error, never a part."""
    def cut(r):
        bore = Cylinder(r, length, align=BOTTOM)
        c = bore - th
        return c, bore.volume - c.volume >= 0.2 * th.volume
    cutter, ok = cut(r_out)
    if ok:
        return cutter, r_out
    bb = th.bounding_box()
    reach = max(bb.max.X, bb.max.Y, -bb.min.X, -bb.min.Y)
    r = r_out + (THREAD_BORE_OVERLAP if reach >= r_out + 2 * THREAD_BORE_OVERLAP else -THREAD_BORE_OVERLAP)
    cutter, ok = cut(r)
    if not ok:
        raise RecipeError(f"The {label} did not cut (the cutter is a plain bore)", "",
                          "Try a coarser pitch, a different length or clearance; do not use the result as a threaded hole.")
    return cutter, r


def _thread_part(th, length: float, external: bool, label: str, dims: dict, comp: float) -> HardwarePart:
    """comp: bd_warehouse's radial manufacturing compensation, which moves the thread but not its radius attributes."""
    r_in, r_out = min(th.apex_radius, th.root_radius), max(th.apex_radius, th.root_radius)
    r_in, r_out = (r_in - comp, r_out - comp) if external else (r_in + comp, r_out + comp)
    if external:
        shape, kind = Cylinder(r_in + 0.002, length, align=BOTTOM) + th, "add"
    else:
        # one cut, no fuse: a bore that overshoots z = 0, minus the nut's thread ridges (a fused overshoot disc
        # leaves an invalid solid at some lengths)
        cutter, _r = _ridged_bore(th, r_out, length + OVERSHOOT, label)
        shape = Pos(0, 0, -length) * cutter
        kind = "cut"
    if not shape.is_valid or len(shape.solids()) != 1:
        raise RecipeError(f"The {label} did not build as one valid solid", "", "Try a different length or clearance.")
    dims["modelled_minor_d"] = _dim(round(2 * r_in, 3), provenance="computed", source="as modelled")
    dims["modelled_major_d"] = _dim(round(2 * r_out, 3), provenance="computed", source="as modelled")
    return HardwarePart(label, shape, kind, dims)


def trapezoidal_thread(diameter: float = 8.0, pitch: float = 2.0, length: float = 20.0, starts: int = 1,
                       external: bool = True, clearance: float = 0.3, acme: bool = False) -> HardwarePart:
    """A lead-screw thread: ISO 2904 trapezoidal (30°) or ACME (29°), bd_warehouse TrapezoidalThread.

    starts > 1 gives a multi-start screw (lead = pitch x starts; the common 3D-printer "T8 x 8" lead screw is
    diameter 8, pitch 2, 4 starts). external=True: a threaded rod standing on z = 0 (kind "add"); False: the cutter
    for a nut, opening at z = 0 going down (kind "cut"). clearance is diametral, per part (assumed, FDM): each thread
    moves away from the other by clearance / 2."""
    th_mod = _bd("thread")
    if pitch < 1 or diameter < 3 * pitch or length < pitch * starts:
        raise RecipeError(f"Tr{diameter:g}x{pitch:g} with {starts} starts, {length:g} mm long, is not printable", "",
                          "Use pitch >= 1 mm, diameter >= 3 x pitch and a length of at least one lead.")
    ang = 29.0 if acme else 30.0
    th = th_mod.TrapezoidalThread(diameter=diameter, pitch=pitch, thread_angle=ang, length=length, external=external,
                                  starts=int(starts), end_finishes=("chamfer", "chamfer"),
                                  manufacturing_compensation=clearance / 2)
    std = "ACME (29°)" if acme else "ISO 2904 trapezoidal (30°)"
    lead = pitch * starts
    dims = {"diameter": _dim(diameter, provenance="assumed", source="caller"),
            "pitch": _dim(pitch, provenance="assumed", source="caller"),
            "starts": _dim(starts, unit="", provenance="assumed", source="caller"),
            "lead": _dim(lead, provenance="computed", source="pitch x starts: travel per turn"),
            "pitch_d": _dim(diameter - pitch / 2, provenance="computed", source=std + ": d - P/2"),
            "clearance": _dim(clearance, provenance="assumed", source="diametral, per part (FDM)"),
            "length": _dim(length, provenance="assumed", source="caller")}
    name = f"Tr{diameter:g}x{lead:g}" + (f" (P{pitch:g}, {starts} starts)" if starts > 1 else "")
    return _thread_part(th, length, external, f"{name} {'external' if external else 'internal'} thread", dims,
                        clearance / 2)


def bottle_thread(finish: str = "PCO1881", external: bool = False, clearance: float = 0.3) -> HardwarePart:
    """A plastic-bottle thread (bd_warehouse PlasticBottleThread): "PCO1881" (the 28 mm soft-drink neck) or an ASTM
    D2911 finish such as "M38SP400". external=False: the cutter for a cap that screws onto a real bottle, opening at
    z = 0 going down (cap's open end up, as it prints); True: a neck standing on z = 0 that a real cap fits.
    clearance: diametral (assumed, FDM)."""
    th_mod = _bd("thread")
    f = str(finish).strip().upper().replace(" ", "").replace("-", "")
    bt, size = ("pco1881", "28") if f in ("PCO1881", "PCO", "28") else ("astm_d2911", f)
    try:
        th = th_mod.PlasticBottleThread(size, external=external, bottle_type=bt, manufacturing_compensation=clearance / 2)
    except ValueError as e:
        raise RecipeError(f"Unknown bottle finish “{finish}” ({e})", "", "Use PCO1881 or an ASTM D2911 finish like M38SP400.")
    L = float(th.length)
    std = "PCO 1881" if bt == "pco1881" else f"ASTM D2911 {size}"
    src = f"{std} (bd_warehouse PlasticBottleThread)"
    dims = {"thread_length": _dim(round(L, 3), source=src), "major_d": _dim(float(th.major_diameter), source=src),
            "minor_d": _dim(float(th.minor_diameter), source=src),
            "clearance": _dim(clearance, provenance="assumed", source="diametral (FDM)")}
    return _thread_part(th, L, external, f"{std} {'neck' if external else 'cap'} thread", dims, clearance / 2)


# ---- sprockets and roller chain -----------------------------------------------------------------------------
# Roller chain (ISO 606 / ANSI B29.1): pitch p, roller diameter d1, inner width b1, mm.
CHAIN_SOURCE = "ISO 606 / ANSI B29.1 roller chain (p, d1, b1)"
CHAINS = {"04C": (6.35, 3.30, 3.18), "06C": (9.525, 5.08, 4.68), "08A": (12.7, 7.92, 7.85),
          "06B": (9.525, 6.35, 5.72), "08B": (12.7, 8.51, 7.75), "10B": (15.875, 10.16, 9.65)}
CHAIN_ALIASES = {"ANSI25": "04C", "25": "04C", "ANSI35": "06C", "35": "06C", "ANSI40": "08A", "40": "08A"}


def chain_spec(chain: str = "08B") -> tuple[float, float, float, str]:
    """(pitch, roller diameter, inner width, ISO name) of a roller chain."""
    k = str(chain).strip().upper().replace(" ", "").replace("#", "")
    k = CHAIN_ALIASES.get(k, k)
    if k not in CHAINS:
        raise RecipeError(f"Unknown chain “{chain}”", "", "Use " + ", ".join(CHAINS) + " or ANSI 25 / 35 / 40.")
    return (*CHAINS[k], k)


def sprocket_pitch_d(teeth: int, pitch: float) -> float:
    """Pitch diameter of a roller-chain sprocket: p / sin(180° / z)."""
    return pitch / math.sin(math.pi / teeth)


def sprocket(teeth: int = 18, chain: str = "08B", bore: float = 8.0, thickness: float | None = None,
             clearance: float = 0.1) -> HardwarePart:
    """A roller-chain sprocket (bd_warehouse Sprocket) standing on z = 0, centred on the origin, kind "add".

    thickness defaults to the ISO 606 tooth width for simple chain, 0.93 x b1 (0.95 x b1 above 12.7 mm pitch).
    clearance widens the roller seats (assumed, FDM)."""
    p, d1, b1, key = chain_spec(chain)
    if int(teeth) != teeth or teeth < 9:
        raise RecipeError(f"A sprocket needs a whole number of teeth, at least 9 (got {teeth})", "", "Use 12 or more teeth.")
    t = thickness or round((0.93 if p <= 12.7 else 0.95) * b1, 2)
    pd = sprocket_pitch_d(int(teeth), p)
    root_d = pd - d1
    if bore and bore > root_d - 6:
        raise RecipeError("The bore leaves under 3 mm of sprocket below the tooth roots", "", "Use a smaller bore or more teeth.")
    sp = _bd("sprocket").Sprocket(num_teeth=int(teeth), chain_pitch=p, roller_diameter=d1, clearance=clearance,
                                  thickness=t, bore_diameter=bore or 0.0, align=BOTTOM)
    shape = sp.solids()[0] if len(sp.solids()) == 1 else sp
    return HardwarePart(f"{key} z{int(teeth)} sprocket", shape, "add", {
        "teeth": _dim(teeth, unit="", provenance="assumed", source="caller"), "pitch": _dim(p, source=CHAIN_SOURCE),
        "roller_d": _dim(d1, source=CHAIN_SOURCE),
        "pitch_d": _dim(round(pd, 3), provenance="computed", source="p / sin(180° / z)"),
        "root_d": _dim(round(root_d, 3), provenance="computed", source="pitch d - roller d"),
        "tip_d": _dim(round(2 * float(sp.outer_radius), 3), provenance="computed", source="bd_warehouse tooth form"),
        "thickness": _dim(t, provenance="computed" if thickness is None else "assumed",
                          source="ISO 606 tooth width 0.93 b1" if thickness is None else "caller"),
        "bore": _dim(bore, provenance="assumed", source="caller")}, standard="ISO 606")


def chain_links(pitch: float, teeth_a: int, teeth_b: int, centre: float) -> float:
    """Chain length in links (not rounded) for two sprockets at this centre distance (the standard approximation)."""
    z1, z2 = sorted((teeth_a, teeth_b))
    return 2 * centre / pitch + (z1 + z2) / 2 + pitch * ((z2 - z1) / (2 * math.pi)) ** 2 / centre


def chain_centre(pitch: float, teeth_a: int, teeth_b: int, links: int) -> float:
    """Centre distance at which a chain of `links` links is just taut (the inverse of chain_links)."""
    z1, z2 = sorted((teeth_a, teeth_b))
    a = links - (z1 + z2) / 2
    disc = a * a - 8 * ((z2 - z1) / (2 * math.pi)) ** 2
    if disc < 0 or a <= 0:
        raise RecipeError(f"{links} links cannot wrap these sprockets", "", "Use more links.")
    return pitch / 4 * (a + math.sqrt(disc))


def chain_drive(chain: str = "08B", teeth_a: int = 12, teeth_b: int = 24, centre: float = 150.0) -> dict:
    """Two sprockets and a chain: the even link count at or just above the wanted centre distance, and the exact
    centre distance for that chain (put the axles there, or slot one for tension)."""
    p, _, _, key = chain_spec(chain)
    n = math.ceil(chain_links(p, teeth_a, teeth_b, centre) - 1e-9)
    n += n % 2                                    # an even number of links needs no offset link
    C = chain_centre(p, teeth_a, teeth_b, n)
    return {"chain": key, "pitch": p, "links": n, "centre_distance": round(C, 3), "wanted_centre": centre,
            "ratio": teeth_b / teeth_a, "chain_length": round(n * p, 2),
            "source": "L = 2C/p + (z1+z2)/2 + p((z2-z1)/2π)²/C, rounded up to an even number of links"}


# ---- pipes and flanges ------------------------------------------------------------------------------------
PIPE_SOURCE = "ASME B36.10M / B36.19M, ASTM B88, ASTM D1785 pipe sizes (bd_warehouse pipe table)"
_PIPE_MATERIAL = {"steel": "mild_steel", "iron": "mild_steel", "stainless": "stainless", "copper": "copper",
                  "pvc": "pvc", "abs": "abs"}


def pipe_size(nps: str = "3/4", identifier: str = "40", material: str = "pvc") -> tuple[float, float]:
    """(outside diameter, wall thickness) in mm of a standard pipe: nps "1/8"..."42", schedule or type ("40", "80",
    "STD", "XS", "40S", copper "K"/"L"/"M"), material steel, iron, stainless, copper, pvc or abs."""
    data = _bd("pipe")._read_pipe_data()
    head = f"{nps}{material}"
    k = head + str(identifier)
    if k not in data:
        have = sorted(key[len(head):] for key in data if key.startswith(head))
        raise RecipeError(f"No {material} pipe NPS {nps} schedule {identifier}", "",
                          ("Schedules for it: " + ", ".join(have)) if have else "Check the nominal size and material.")
    od, t = data[k]
    return round(od * 25.4, 3), round(t * 25.4, 3)


def pipe(nps: str = "3/4", length: float = 100.0, identifier: str = "40", material: str = "pvc") -> HardwarePart:
    """A straight standard pipe standing on z = 0, axis Z (sizes from bd_warehouse's pipe table)."""
    od, t = pipe_size(nps, identifier, material)
    shape = Cylinder(od / 2, length, align=BOTTOM) - Cylinder(od / 2 - t, length, align=BOTTOM)
    mat = _PIPE_MATERIAL.get(material, material)
    grams, _ = _mass(shape, mat)
    return HardwarePart(f'NPS {nps}" {material} pipe, schedule {identifier}', shape, "hardware", {
        "od": _dim(od, source=PIPE_SOURCE), "wall": _dim(t, source=PIPE_SOURCE),
        "id": _dim(round(od - 2 * t, 3), provenance="computed", source="od - 2 x wall"),
        "length": _dim(length, provenance="assumed", source="caller"),
        "grams": _dim(grams, unit="g", provenance="computed", source=MASS_SOURCE)}, grams, mat, "ASME B36.10M",
        f'NPS {nps}" sch {identifier} x {length:g} mm')


def pipe_socket(nps: str = "3/4", depth: float = 20.0, identifier: str = "40", material: str = "pvc",
                clearance: float = 0.3, stop: bool = True) -> HardwarePart:
    """A socket a real pipe slides into, below z = 0: the pipe's OD + clearance (diametral, assumed for FDM; glue or
    a clamp holds it), with a stop at the bottom for the pipe end, bored through at the pipe's bore."""
    od, t = pipe_size(nps, identifier, material)
    D = od + clearance
    shape = Pos(0, 0, OVERSHOOT) * Cylinder(D / 2, depth + OVERSHOOT, align=TOP)
    if stop:
        shape = shape + Pos(0, 0, -depth + 0.01) * Cylinder(od / 2 - t, 3.0, align=TOP)
    return HardwarePart(f'NPS {nps}" pipe socket', shape, "cut", {
        "pipe_od": _dim(od, source=PIPE_SOURCE),
        "socket_d": _dim(round(D, 3), provenance="computed", source=f"pipe OD + {clearance:g} mm (assumed)"),
        "depth": _dim(depth, provenance="assumed", source="caller"),
        "bore_d": _dim(round(od - 2 * t, 3), provenance="computed", source="pipe bore, so the flow is not stepped")})


def pipe_flange(nps: str = "1", flange_class: int = 150, kind: str = "slip_on", face: str = "Raised") -> HardwarePart:
    """An ASME B16.5 pipe flange (bd_warehouse) standing on z = 0, axis Z: kind slip_on, weld_neck or blind."""
    fl = _bd("flange")
    cls = {"slip_on": "SlipOnFlange", "weld_neck": "WeldNeckFlange", "blind": "BlindFlange"}.get(kind)
    if cls is None:
        raise RecipeError(f"Unknown flange kind “{kind}”", "", "Use slip_on, weld_neck or blind.")
    try:
        obj = getattr(fl, cls)(nps=str(nps), flange_class=int(flange_class), face_type=face)
    except (KeyError, ValueError) as e:
        raise RecipeError(f"No class {flange_class} {kind} flange for NPS {nps} here ({e})", "",
                          "bd_warehouse 0.4.0 has class 150 flanges from NPS 1 up: 1, 1 1/2, 2, 3, 4 ...")
    src = f"ASME B16.5 class {flange_class} (bd_warehouse)"
    dims = {"od": _dim(float(obj.od), source=src), "thickness": _dim(float(obj.thickness), source=src)}
    if getattr(obj, "id", None):
        dims["bore"] = _dim(float(obj.id), source=src)
    grams, mat = _mass(obj, "mild_steel")
    dims["grams"] = _dim(grams, unit="g", provenance="computed", source=MASS_SOURCE + "; carbon steel (A105) assumed")
    return HardwarePart(f'NPS {nps}" class {flange_class} {kind.replace("_", "-")} flange', obj, "hardware", dims,
                        grams, mat, f"ASME B16.5 class {flange_class}", f'NPS {nps}"')


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
    for mod in ("bd_warehouse", "py_gearworks", "bd_materials"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "installed")
        except ImportError:
            out[mod] = None
    return out
