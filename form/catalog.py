"""Standard parts: a parametric library of purchased hardware, generated from published tables.

Every family is generated from a table that names its source (the standard and the table, or the maker's datasheet),
and every dimension a part carries says where it came from. Nothing is interpolated or guessed: a size that is not in
the table is refused, and a value no source gives is marked "assumed" (a design choice, such as an FDM clearance) or
left out.

    from form import catalog
    catalog.search("m5 socket 12")                  # candidates with their designations
    it = catalog.resolve({"family": "iso4762", "size": "M5", "length": 12, "grade": "A2-70"})
    catalog.designation(it)                         # "ISO 4762 M5×12 A2-70"
    catalog.dims(it)                                # {name: {value, unit, provenance, source}}
    part = catalog.build(it)                        # worker only: a form.parts.HardwarePart, real CAD
    cut = catalog.mating(it, depth=6)               # worker only: the hole, counterbore or pocket for the host

The tables live here or are read from bd_warehouse's data files (CSV, read directly; build123d is not imported until a
part is built), so this module is importable by the MCP server, the CLI and the app without OCCT.

Threads are cosmetic: a screw's shank is modelled at its nominal envelope without a helix (bd_warehouse
``simple=True``), and a tapped hole is a plain bore. Every dimension list says so ("thread": cosmetic).

Frames (the same as form.parts): z = 0 is the host's surface, the mating cut goes down -Z, and the part is placed as
fitted in that cut (a screw head on its seat, an insert flush, a bearing flush in its seat, a motor's flange on the
surface with its body above).
"""
from __future__ import annotations

import csv
import functools
import importlib.util
import math
import re
from pathlib import Path

VERSION = 1                     # part of the cache keys of built parts and their mass

SPECIFIED, COMPUTED, ASSUMED = "specified", "computed", "assumed"
COSMETIC = "cosmetic: the helix is not modelled (plain shank at the nominal diameter; a tapped hole is a plain bore)"


def _err(msg: str, hint: str = ""):
    from .studio import StudioError
    return StudioError(msg, hint)


def _dim(value, source: str, provenance: str = SPECIFIED, unit: str = "mm") -> dict:
    return {"value": float(value), "unit": unit, "provenance": provenance, "source": source}


# ── bd_warehouse data files (read as CSV; no build123d import) ────────────────────────────────────────────────────
@functools.lru_cache(maxsize=1)
def _bd_data_dir() -> Path | None:
    spec = importlib.util.find_spec("bd_warehouse")
    if spec is None or not spec.submodule_search_locations:
        return None
    d = Path(list(spec.submodule_search_locations)[0]) / "data"
    return d if d.is_dir() else None


@functools.lru_cache(maxsize=32)
def _bd_csv(name: str, prefix: str) -> dict:
    """{size: {column: float}} for the columns of one standard ("iso4762:dk" -> "dk"); rows without values dropped."""
    d = _bd_data_dir()
    if d is None:
        return {}
    out = {}
    with open(d / name, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vals = {}
            for k, v in row.items():
                k = (k or "").strip()
                if k.startswith(prefix + ":") and v not in (None, "", "-"):
                    try:
                        vals[k.split(":", 1)[1].strip()] = float(v)
                    except ValueError:
                        vals[k.split(":", 1)[1].strip()] = v
            if vals:
                out[row["Size"].strip()] = vals
    return out


@functools.lru_cache(maxsize=1)
def _bd_lengths() -> dict:
    d = _bd_data_dir()
    if d is None:
        return {}
    with open(d / "nominal_screw_lengths.csv", newline="", encoding="utf-8") as f:
        return {r["Screw_Type"]: [float(x) for x in r["Nominal_Sizes"].split(",")] for r in csv.DictReader(f)}


def _bd_version() -> str:
    try:
        from importlib.metadata import version
        return version("bd_warehouse")
    except Exception:                                    # noqa: BLE001
        return "?"


def _bd_src(std: str, table: str, file: str) -> str:
    return f"{std}, {table} (bd_warehouse {_bd_version()} data/{file})"


def _metric(size: str) -> str:
    """'m5' / '5' / 'M5-0.8' -> 'M5'."""
    s = str(size).strip().upper().replace(" ", "")
    s = s.split("-")[0].split("X")[0].split("×")[0]
    if not s.startswith("M"):
        s = "M" + s
    return s


def _coarse(table: dict, size: str) -> str | None:
    """The table row of a metric size at its coarse pitch ("M5" -> "M5-0.8"): the first row of that diameter."""
    m = _metric(size)
    for k in table:
        if k.split("-")[0] == m:
            return k
    return None


# ── published tables kept here (each with its source) ─────────────────────────────────────────────────────────────
# Deep-groove ball bearings, boundary dimensions d x D x B. ISO 15 sets these; read from the igus dimension table
# (which cites DIN 625-1, the national adoption of the same boundary dimensions) and cross-checked against the SKF
# values bd_warehouse ships for bores up to 10 mm (tests/test_catalog.py compares them).
BEARING_SOURCE = ("ISO 15 boundary dimensions (dimension series 10, 02 and 00), as tabulated by igus 'Ball bearing "
                  "dimension table' (DIN 625-1), https://www.igus.co.uk/ball-bearings/wiki/ball-bearing-dimension-table")
BEARINGS = {
    "604": (4, 12, 4), "605": (5, 14, 5), "606": (6, 17, 6), "607": (7, 19, 6), "608": (8, 22, 7), "609": (9, 24, 7),
    "623": (3, 10, 4), "624": (4, 13, 5), "625": (5, 16, 5), "626": (6, 19, 6), "627": (7, 22, 7), "628": (8, 24, 8),
    "629": (9, 26, 8),
    "6000": (10, 26, 8), "6001": (12, 28, 8), "6002": (15, 32, 9), "6003": (17, 35, 10), "6004": (20, 42, 12),
    "6005": (25, 47, 12),
    "6200": (10, 30, 9), "6201": (12, 32, 10), "6202": (15, 35, 11), "6203": (17, 40, 12), "6204": (20, 47, 14),
    "6205": (25, 52, 15),
}
BEARING_SEALS = {"open": "", "2Z": "-2Z", "2RS": "-2RS"}

# Linear ball bushings, THK Model LM catalogue (pages A4-42/43), https://tech.thk.com/en/products/pdfs/en_a04_042.pdf
# (d, D, L, groove spacing B [THK L1], groove width W [L2], groove diameter D1 [D0])
LM_SOURCE = "THK Linear Bushing Model LM catalogue, pp. A4-42/43, https://tech.thk.com/en/products/pdfs/en_a04_042.pdf"
LM = {"LM6UU": (6, 12, 19, 13.5, 1.1, 11.5), "LM8UU": (8, 15, 24, 17.5, 1.1, 14.3),
      "LM10UU": (10, 19, 29, 22, 1.3, 18), "LM12UU": (12, 21, 30, 23, 1.3, 20)}
SHAFT_TOL_SOURCE = ("THK 'Assembling the Linear Bushing': shaft f6/g6 (normal clearance) or h6 (small gap) for the "
                    "high-accuracy grade, https://www.thk.com/eu/en/products/other_linear_motion_guides/linear_bushing/design/0001/")

# DIN 705 form A adjusting rings (shaft collars), Elesa+Ganter GN 705 datasheet (3/2024), which "essentially
# corresponds to" DIN 705:2007: bore d (H8) -> (outer D, width b (js14), set screw)
COLLAR_SOURCE = ("Elesa+Ganter GN 705 adjusting rings datasheet (3/2024), essentially DIN 705 form A, "
                 "https://elesa-ganter.be/technicaldatasheet/GN%20705.pdf/de")
COLLARS = {5: (10, 6, "M3"), 6: (12, 8, "M4"), 8: (16, 8, "M4"), 10: (20, 10, "M5"), 12: (22, 12, "M6"),
           15: (25, 12, "M6"), 20: (32, 14, "M6")}

# ISO 8734:1997 hardened parallel (dowel) pins, tolerance m6. Table 1: chamfer c (approx.) and length range.
DOWEL_SOURCE = ("ISO 8734:1997 Table 1 (preview), "
                "https://cdn.standards.iteh.ai/samples/20002/ba95529de6a64437ac7454e14dbd2ef6/ISO-8734-1997.pdf")
DOWELS = {1: (0.2, 3, 10), 1.5: (0.3, 4, 16), 2: (0.35, 5, 20), 2.5: (0.4, 6, 24), 3: (0.5, 8, 30), 4: (0.63, 10, 40),
          5: (0.8, 12, 50), 6: (1.2, 14, 60), 8: (1.6, 20, 80), 10: (2.0, 22, 100), 12: (2.5, 26, 100),
          16: (3.0, 40, 100), 20: (3.5, 50, 100)}
DOWEL_LENGTHS = (3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 22, 24, 26, 28, 30, 32, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85,
                 90, 95, 100)

# NEMA stepper frames. Pilot, shaft, hole size: NEMA ICS 16-2001 as quoted by Aspina (inches converted);
# hole spacing and bolt circle: Hallikainen's NEMA size table (it does not cite ICS 16). Body square: "about"
# values (Aspina's text); body and shaft length vary by motor and are the caller's.
NEMA_SOURCE = ("NEMA ICS 16-2001 frame dimensions as quoted by Aspina, "
               "https://us.aspina-group.com/en/learning-zone/columns/what-is/033/")
NEMA_SPACING_SOURCE = "Hallikainen NEMA sizes table, https://pic.hallikainen.org/techref/io/stepper/nemasizes.htm"
NEMA = {  # frame: (body square, hole spacing, hole d (ICS 16 free hole), pilot d, pilot h, shaft d, screw)
    "17": (42.0, 31.0, 3.81, 22.0, 2.0, 5.0, "M3"),
    "23": (56.0, 47.14, 5.21, 38.1, 1.6, 6.35, "M5"),
}

# GT2 (2 mm pitch) timing belt profile: Pfeifer Industries 'Timing Belt Tooth Profiles and Pitches', 2MR/PGGT2 row.
GT2_SOURCE = "Pfeifer Industries 'Timing Belt Tooth Profiles and Pitches' p. 2, 2MR / PGGT2 row"
GT2_PITCH, GT2_BELT_H, GT2_TOOTH_H = 2.0, 1.52, 0.76
GT2_PLD = 0.254                 # pitch-line differential per side: NOT verified from a Gates table (assumed)
GT2_TEETH = (16, 20, 30, 36, 40, 60)

# Sintered NdFeB grades at room temperature: supermagnete 'Physical magnet data'; density from Arnold N42/N52 sheets.
MAGNET_SOURCE = "supermagnete 'Physical magnet data', https://supermagnete.de/eng/data_table.php"
MAGNET_DENSITY = (7600.0, "Arnold Magnetic Technologies N42 datasheet (density 7.6 g/cm³), "
                          "https://www.arnoldmagnetics.com/wp-content/uploads/2017/11/N42-151021.pdf")
MAGNETS = {  # grade: (Br min T, Br max T, HcJ min kA/m, BHmax min kJ/m3, BHmax max, max working °C)
    "N35": (1.17, 1.21, 955, 263, 279, 80), "N38": (1.22, 1.26, 955, 287, 303, 80),
    "N40": (1.26, 1.29, 955, 303, 318, 80), "N42": (1.29, 1.32, 955, 318, 334, 80),
    "N45": (1.32, 1.37, 955, 342, 358, 80), "N48": (1.37, 1.42, 955, 358, 382, 80),
    "N50": (1.40, 1.46, 955, 374, 406, 80), "N52": (1.42, 1.47, 955, 380, 422, 65),
}

# Brass heat-set inserts, CNC Kitchen standard and short versions, from the product pages at cnckitchen.store:
# (insert outer diameter, length, recommended hole diameter, minimum wall around the hole), mm. One copy, kernel-free,
# in form/hardware_tables.py; form.parts and form.calc read the same table.
from .hardware_tables import INSERT_SOURCE, INSERTS  # noqa: E402,F401

# OpenBuilds V-Slot and its T-nut, as bd_warehouse models them from openbuildspartstore.com product pages.
VSLOT_SOURCE = "OpenBuilds V-Slot Linear Rail product page (openbuildspartstore.com), modelled by bd_warehouse open_builds"
VSLOTS = {"2020": (20, 20), "2040": (20, 40)}
TNUT_SOURCE = "OpenBuilds Tee Nut product page (M5, 5.9 x 10 mm, mild steel), modelled by bd_warehouse open_builds"

# Property classes (ISO 898-1 steel, ISO 3506-1 stainless) and the library material whose density is used.
SCREW_GRADES = {"8.8": ("STEEL", "steel, property class 8.8 (ISO 898-1)", "density of mild steel (assumed for a carbon steel screw)"),
                "10.9": ("STEEL-4140", "alloy steel, property class 10.9 (ISO 898-1)", "density of alloy steel 4140 (assumed)"),
                "12.9": ("STEEL-4140", "alloy steel, property class 12.9 (ISO 898-1)", "density of alloy steel 4140 (assumed)"),
                "A2-70": ("STAINLESS", "stainless A2-70 (ISO 3506-1)", "density of stainless 304, the A2 group"),
                "A4-70": ("STAINLESS", "stainless A4-70 (ISO 3506-1)", "density of stainless 304 used for A4 (assumed)"),
                "A4-80": ("STAINLESS", "stainless A4-80 (ISO 3506-1)", "density of stainless 304 used for A4 (assumed)")}
NUT_GRADES = {"8": ("STEEL", "steel, property class 8 (ISO 898-2)", "density of mild steel (assumed)"),
              "10": ("STEEL-4140", "steel, property class 10 (ISO 898-2)", "density of alloy steel 4140 (assumed)"),
              "A2-70": SCREW_GRADES["A2-70"], "A4-70": SCREW_GRADES["A4-70"]}
WASHER_GRADES = {"200 HV": ("STEEL", "steel, hardness class 200 HV", "density of mild steel (assumed)"),
                 "300 HV": ("STEEL", "steel, hardness class 300 HV", "density of mild steel (assumed)"),
                 "A2": ("STAINLESS", "stainless A2", "density of stainless 304, the A2 group"),
                 "A4": ("STAINLESS", "stainless A4", "density of stainless 304 used for A4 (assumed)")}

# Withdrawn DIN standards and their successors (Würth DINO technical chapter, §3.2 successor table,
# https://prueflabor.wuerth-industrie.com/web/media/en/pictures/wuerthindustrie/technikportal/dinokapitel/Kapitel_03_DINO_techn_Teil.pdf).
# Only DIN 912 is offered as a family: its successor ISO 4762 is what is modelled, and the designation says so.
DIN_SOURCE = "Würth DINO technical chapter §3.2 (successor standards) and §3.5 (nut widths across flats)"
DIN_EQUIVALENTS = {
    "DIN 912": {"iso": "ISO 4762", "family": "iso4762", "same": True,
                "note": "Replaced by ISO 4762; modelled with ISO 4762's head dimensions."},
    "DIN 125-1 A": {"iso": "ISO 7089", "family": "iso7089", "same": True,
                    "note": "Replaced by ISO 7089 (the chamfered form by ISO 7090); modelled with ISO 7089's dimensions."},
    "DIN 934": {"iso": "ISO 4032", "family": "iso4032", "same": False,
                "note": "Not the same nut: across flats differ at M10 (17 vs 16), M12 (19 vs 18), M14 (22 vs 21) and M22 "
                        "(32 vs 34), and the heights differ. Order ISO 4032, or give the DIN 934 nut's own dimensions."},
}


# ── families ─────────────────────────────────────────────────────────────────────────────────────────────────────
class Family:
    """One kind of purchased part. Subclasses give the table (sizes), the options, the designation, the dimensions,
    the solid (build, worker only) and the mating cut (mating, worker only)."""
    id = ""
    label = ""
    category = ""
    standard = ""
    keywords: tuple = ()
    options: dict = {}            # name -> {"default", "choices"?, "min"?, "max"?, "doc"}
    mate = "clearance"            # what the fit check expects: clearance | press | seal | surface
    thread = ""

    def sizes(self) -> list[str]:
        raise NotImplementedError

    def source(self) -> str:
        raise NotImplementedError

    def size_key(self, size) -> str:
        s = str(size).strip()
        for k in self.sizes():
            if k.upper() == s.upper():
                return k
        raise _err(f"No {self.label} of size “{size}” in {self.standard}.",
                   "Sizes in the table: " + ", ".join(self.sizes()) + ".")

    def resolve(self, it: dict) -> dict:
        out = {"family": self.id, "size": self.size_key(it.get("size") or self.sizes()[0])}
        for k, o in self.options.items():
            v = it.get(k, o.get("default"))
            if v is None:
                out[k] = None
                continue
            if "choices" in o:
                ch = [str(c) for c in o["choices"]]
                if str(v) not in ch:
                    raise _err(f"{self.label}: {k} “{v}” is not one of {', '.join(ch)}.")
                v = str(v)
            elif o.get("number"):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise _err(f"{self.label}: {k} must be a number.")
                if ("min" in o and v < o["min"]) or ("max" in o and v > o["max"]):
                    raise _err(f"{self.label}: {k} must be between {o.get('min', 0):g} and {o.get('max', 1e9):g}.")
            out[k] = v
        self.check(out)
        return out

    def check(self, it: dict) -> None:
        pass

    def designation(self, it: dict) -> str:
        raise NotImplementedError

    def dims(self, it: dict) -> dict:
        raise NotImplementedError

    def material(self, it: dict) -> tuple[str | None, str, str]:
        """(library material key or None, what it is, why that density)"""
        return None, "", ""

    def catalogue_grams(self, it: dict) -> tuple[float, str] | None:
        """A mass the maker's catalogue gives (grams, source), preferred to the computed one."""
        return None

    def build(self, it: dict):
        raise NotImplementedError

    def mating(self, it: dict, depth: float):
        """The cut into the host (a form.parts HardwarePart of kind "cut"), or None when the part sits on the surface."""
        return None

    def mating_dims(self, it: dict, depth: float) -> dict:
        return {}

    def default_depth(self, it: dict) -> float:
        return 5.0

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "category": self.category, "standard": self.standard,
                "source": self.source(), "sizes": self.sizes(), "options": self.options, "mate": self.mate,
                **({"thread": self.thread} if self.thread else {})}


def _num_opt(default, lo, hi, doc, unit="mm"):
    return {"default": default, "number": True, "min": lo, "max": hi, "doc": doc, "unit": unit}


# ---- screws ---------------------------------------------------------------------------------------------------------
class _Screw(Family):
    category = "fasteners"
    mate = "clearance"
    thread = COSMETIC
    bd_type = ""
    bd_file = ""
    bd_class = ""
    table_name = ""
    head = ""                    # socket | button | countersunk

    options = {"length": _num_opt(None, 1, 500, "Nominal length (ISO: under the head; countersunk: overall). "
                                                "Leave out to take the shortest stock length for the host."),
               "grade": {"default": "8.8", "choices": tuple(SCREW_GRADES), "doc": "Property class / material."},
               "fit": {"default": "normal", "choices": ("close", "normal", "loose"),
                       "doc": "Clearance hole series (ISO 273)."},
               "head_clearance": _num_opt(0.3, 0, 2, "Added to the head diameter for the counterbore or sink (assumed)."),
               "recess": {"default": "yes", "choices": ("yes", "no"), "doc": "Sink the head into the host."}}

    def table(self) -> dict:
        return _bd_csv(self.bd_file, self.bd_type)

    def sizes(self) -> list[str]:
        return [k.split("-")[0] for k, v in self.table().items() if k.startswith("M") and "dk" in v]

    def source(self) -> str:
        return _bd_src(self.standard, self.table_name, self.bd_file)

    def row(self, it) -> dict:
        return self.table()[_coarse(self.table(), it["size"])]

    def lengths(self, it) -> list[float]:
        r = self.row(it)
        allL = _bd_lengths().get(self.bd_type, [])
        lo, hi = r.get("short", 0), r.get("long", 1e9)
        return [x for x in allL if lo - 1e-9 <= x <= hi + 1e-9]

    def check(self, it):
        if it.get("length") is not None:
            L = self.lengths(it)
            if not any(abs(it["length"] - x) < 1e-6 for x in L):
                raise _err(f"{self.standard} {it['size']}×{it['length']:g} is not a stock length.",
                           f"Stock lengths for {it['size']}: " + ", ".join(f"{x:g}" for x in L) + " mm.")

    def choose_length(self, it, depth: float) -> float:
        """The shortest stock length that passes the host and engages one diameter beyond it (assumed rule)."""
        d = float(it["size"][1:])
        sink = 0.0
        if it.get("recess", "yes") == "yes" and self.head != "countersunk":
            sink = self.row(it)["k"] + 0.2
        need = depth - sink + d if self.head != "countersunk" else depth + d
        for L in self.lengths(it):
            if L >= need - 1e-6:
                return L
        L = self.lengths(it)
        raise _err(f"No stock {self.standard} {it['size']} screw is {need:.1f} mm or longer.",
                   "Longest stock: " + (f"{L[-1]:g} mm." if L else "none."))

    def designation(self, it):
        L = it.get("length")
        return f"{self.standard} {it['size']}×{L:g} {it['grade']}" if L else f"{self.standard} {it['size']} {it['grade']}"

    def dims(self, it):
        r, src = self.row(it), self.source()
        out = {"d": _dim(float(it["size"][1:]), "nominal size"), "head_d": _dim(r["dk"], src + ": dk"),
               "head_h": _dim(r["k"], src + ": k"), "drive": _dim(r["s"], src + ": s (hexagon socket)")}
        if it.get("length"):
            out["length"] = _dim(it["length"], f"stock length, {self.standard} length series "
                                                f"(bd_warehouse nominal_screw_lengths.csv)")
        return out

    def material(self, it):
        return SCREW_GRADES[it["grade"]]

    def clearance(self, it) -> tuple[float, str]:
        return _clearance(it["size"], it.get("fit") or "normal")

    def build(self, it):
        from . import parts
        f = parts._bd("fastener")
        cls = getattr(f, self.bd_class)
        L = it["length"]
        obj = cls(_coarse(self.table(), it["size"]), L, self.bd_type, simple=True)
        return parts.HardwarePart(self.designation(it), obj, "hardware", self.dims(it), None, "", self.standard,
                                  f"{it['size']}×{L:g}")

    def _sink(self, it):
        r = self.row(it)
        if it.get("recess", "yes") != "yes":
            return 0.0
        if self.head == "countersunk":
            return 0.0
        return r["k"] + 0.2

    def mating(self, it, depth):
        from build123d import Cone, Cylinder, Pos
        from . import parts
        d, src = self.clearance(it)
        r = self.row(it)
        hc = float(it.get("head_clearance") or 0.0)
        shape = Pos(0, 0, parts.OVERSHOOT) * Cylinder(d / 2, depth + parts.OVERSHOOT, align=parts.TOP)
        if it.get("recess", "yes") == "yes":
            if self.head == "countersunk":
                D = r["dk"] + hc
                sink = (D - d) / 2 / math.tan(math.radians(r.get("a", 90) / 2))
                if sink >= depth:
                    raise _err(f"The countersink ({sink:.1f} mm) is deeper than the host ({depth:.1f} mm).",
                               "Use a thicker host or a socket head.")
                shape = shape + Pos(0, 0, -sink) * Cone(d / 2, D / 2, sink, align=parts.BOTTOM) \
                    + Cylinder(D / 2, parts.OVERSHOOT, align=parts.BOTTOM)
            else:
                k = r["k"] + 0.2
                if k >= depth:
                    raise _err(f"The {self.head} head's counterbore ({k:.1f} mm) is as deep as the host ({depth:.1f} mm).",
                               "Use a thicker host, recess=no, or a button head.")
                D = r["dk"] + hc
                shape = shape + Pos(0, 0, parts.OVERSHOOT) * Cylinder(D / 2, k + parts.OVERSHOOT, align=parts.TOP)
        return parts.HardwarePart(f"{it['size']} clearance for {self.standard}", shape, "cut",
                                  self.mating_dims(it, depth))

    def mating_dims(self, it, depth):
        d, src = self.clearance(it)
        r = self.row(it)
        hc = float(it.get("head_clearance") or 0.0)
        out = {"hole_d": _dim(d, src + f", {it.get('fit') or 'normal'} series"),
               "depth": _dim(depth, "host thickness at the point (computed) or the caller", COMPUTED)}
        if it.get("recess", "yes") == "yes":
            out["recess_d"] = _dim(r["dk"] + hc, f"head dk + {hc:g} mm head clearance (assumed)", COMPUTED)
            if self.head == "countersunk":
                out["sink_angle"] = _dim(r.get("a", 90), self.source() + ": a", unit="deg")
            else:
                out["recess_depth"] = _dim(r["k"] + 0.2, "head height k + 0.2 mm (assumed)", COMPUTED)
        return out

    def fitted_z(self, it) -> float:
        """Where the part's own z = 0 goes in the mating frame."""
        return -self._sink(it)

    def default_depth(self, it):
        return 6.0


class ISO4762(_Screw):
    id, label, standard = "iso4762", "Socket head cap screw", "ISO 4762"
    keywords = ("socket", "cap", "shcs", "allen", "bolt", "screw", "4762")
    bd_type, bd_file, bd_class, table_name = "iso4762", "socket_head_cap_parameters.csv", "SocketHeadCapScrew", "dk, k, s, t"
    head = "socket"


class DIN912(ISO4762):
    id, label, standard = "din912", "Socket head cap screw (DIN 912)", "DIN 912"
    keywords = ("din912", "912", "socket", "cap")

    def source(self):
        return _bd_src("ISO 4762 (DIN 912's successor; " + DIN_SOURCE + ")", self.table_name, self.bd_file)

    def designation(self, it):
        return ISO4762.designation(self, it) + " (replaced by ISO 4762)"

    def build(self, it):
        p = ISO4762.build(self, it)
        p.standard = "DIN 912 / ISO 4762"
        return p


class ISO7380(_Screw):
    id, label, standard = "iso7380", "Button head screw", "ISO 7380-1"
    keywords = ("button", "dome", "bhcs", "7380")
    bd_type, bd_file, bd_class, table_name = "iso7380_1", "button_head_parameters.csv", "ButtonHeadScrew", "dk, k, s"
    head = "button"


class ISO10642(_Screw):
    id, label, standard = "iso10642", "Countersunk socket screw", "ISO 10642"
    keywords = ("countersunk", "flat", "csk", "fhcs", "10642")
    bd_type, bd_file, bd_class, table_name = "iso10642", "countersunk_head_parameters.csv", "CounterSunkScrew", "a, dk, k, s"
    head = "countersunk"

    def fitted_z(self, it):
        return 0.0


def _clearance(size: str, fit: str) -> tuple[float, str]:
    t = _bd_csv_plain("clearance_hole_sizes.csv")
    m = _metric(size)
    col = {"close": "Close", "normal": "Normal", "loose": "Loose"}[fit]
    if m in t and t[m].get(col):
        return float(t[m][col]), _bd_src("ISO 273 clearance holes", "close / medium / coarse", "clearance_hole_sizes.csv")
    raise _err(f"No ISO 273 clearance hole for {m}.")


@functools.lru_cache(maxsize=8)
def _bd_csv_plain(name: str) -> dict:
    d = _bd_data_dir()
    if d is None:
        return {}
    with open(d / name, newline="", encoding="utf-8") as f:
        return {r["Size"].strip(): {k: v for k, v in r.items() if k != "Size"} for r in csv.DictReader(f)}


# ---- nuts and washers -----------------------------------------------------------------------------------------------
class ISO4032(Family):
    id, label, standard, category = "iso4032", "Hex nut", "ISO 4032", "fasteners"
    keywords = ("nut", "hex", "4032", "934")
    mate = "clearance"
    thread = COSMETIC
    options = {"grade": {"default": "8", "choices": tuple(NUT_GRADES), "doc": "Property class / material."},
               "clearance": _num_opt(0.15, 0, 1, "Added per side to the width across flats for the trap (assumed, FDM).")}

    def table(self):
        return _bd_csv("hex_nut_parameters.csv", "iso4032")

    def sizes(self):
        return [k.split("-")[0] for k in self.table() if k.startswith("M") and "s" in self.table()[k]]

    def source(self):
        return _bd_src("ISO 4032", "m, s", "hex_nut_parameters.csv")

    def row(self, it):
        return self.table()[_coarse(self.table(), it["size"])]

    def designation(self, it):
        return f"ISO 4032 {it['size']} {it['grade']}"

    def dims(self, it):
        r = self.row(it)
        return {"across_flats": _dim(r["s"], self.source() + ": s"), "thickness": _dim(r["m"], self.source() + ": m")}

    def material(self, it):
        return NUT_GRADES[it["grade"]]

    def build(self, it):
        from . import parts
        obj = parts._bd("fastener").HexNut(_coarse(self.table(), it["size"]), "iso4032", simple=True)
        return parts.HardwarePart(self.designation(it), obj, "hardware", self.dims(it), None, "", "ISO 4032", it["size"])

    def mating(self, it, depth):
        from . import parts
        trap = parts.nut_trap(it["size"], "hex", clearance=float(it.get("clearance") or 0.15))
        if trap["depth"] > depth:
            raise _err(f"The nut trap ({trap['depth']:.1f} mm) is deeper than the host ({depth:.1f} mm).", "Use a thicker host.")
        d, _ = _clearance(it["size"], "normal")
        from build123d import Cylinder, Pos
        shape = trap.shape + Pos(0, 0, parts.OVERSHOOT) * Cylinder(d / 2, depth + 2 * parts.OVERSHOOT, align=parts.TOP)
        return parts.HardwarePart(f"{it['size']} nut trap", shape, "cut", self.mating_dims(it, depth))

    def mating_dims(self, it, depth):
        r = self.row(it)
        c = float(it.get("clearance") or 0.15)
        return {"pocket_af": _dim(r["s"] + 2 * c, f"s + 2 × {c:g} mm (assumed FDM clearance)", COMPUTED),
                "pocket_depth": _dim(r["m"] + 0.3, "m + 0.3 mm", COMPUTED),
                "hole_d": _dim(_clearance(it["size"], "normal")[0], _clearance(it["size"], "normal")[1])}

    def fitted_z(self, it):
        r = self.row(it)
        return -(r["m"] + 0.3)          # the nut on the trap's floor

    def default_depth(self, it):
        return self.row(it)["m"] + 2.0


class ISO7089(Family):
    id, label, standard, category = "iso7089", "Plain washer", "ISO 7089", "fasteners"
    keywords = ("washer", "7089", "125")
    mate = "surface"
    options = {"grade": {"default": "200 HV", "choices": tuple(WASHER_GRADES), "doc": "Hardness class / material."}}

    def table(self):
        return _bd_csv("plain_washer_parameters.csv", "iso7089")

    def sizes(self):
        return [k for k in self.table() if "d2" in self.table()[k]]

    def source(self):
        return _bd_src("ISO 7089", "d1, d2, h", "plain_washer_parameters.csv")

    def designation(self, it):
        return f"ISO 7089 - {it['size'][1:]} - {it['grade']}"

    def dims(self, it):
        r = self.table()[it["size"]]
        return {"inner_d": _dim(r["d1"], self.source() + ": d1"), "outer_d": _dim(r["d2"], self.source() + ": d2"),
                "thickness": _dim(r["h"], self.source() + ": h")}

    def material(self, it):
        return WASHER_GRADES[it["grade"]]

    def build(self, it):
        from build123d import Cylinder
        from . import parts
        r = self.table()[it["size"]]
        shape = Cylinder(r["d2"] / 2, r["h"], align=parts.BOTTOM) - Cylinder(r["d1"] / 2, r["h"], align=parts.BOTTOM)
        return parts.HardwarePart(self.designation(it), shape, "hardware", self.dims(it), None, "", "ISO 7089", it["size"])


# ---- inserts, magnets, O-rings --------------------------------------------------------------------------------------
class HeatInsert(Family):
    id, label, standard, category = "heat_insert", "Heat-set insert (brass)", "CNC Kitchen", "inserts"
    keywords = ("insert", "heat", "heatset", "threaded insert", "brass")
    mate = "press"
    thread = COSMETIC
    options = {}

    def sizes(self):
        return list(INSERTS)

    def source(self):
        return INSERT_SOURCE

    def designation(self, it):
        od, L, hole, wall = INSERTS[it["size"]]
        return f"Heat-set insert {it['size'].split('-')[0]}×{L:g} (CNC Kitchen{', short' if 'short' in it['size'] else ''}), brass"

    def dims(self, it):
        od, L, hole, wall = INSERTS[it["size"]]
        return {"outer_d": _dim(od, INSERT_SOURCE), "length": _dim(L, INSERT_SOURCE),
                "hole_d": _dim(hole, INSERT_SOURCE + " (recommended hole)"), "min_wall": _dim(wall, INSERT_SOURCE)}

    def material(self, it):
        return "BRASS", "brass", "CNC Kitchen inserts are brass"

    def build(self, it):
        from build123d import Cylinder, Pos
        from . import parts
        od, L, hole, wall = INSERTS[it["size"]]
        bore = float(it["size"].split("-")[0][1:])
        shape = Pos(0, 0, -L) * (Cylinder(od / 2, L, align=parts.BOTTOM) - Cylinder(bore / 2, L, align=parts.BOTTOM))
        dims = {**self.dims(it), "model": _dim(0, "outer diameter and length as the datasheet gives them; knurls and "
                                                  "thread cosmetic (not modelled)", ASSUMED, "")}
        return parts.HardwarePart(self.designation(it), shape, "hardware", dims, None, "brass", "CNC Kitchen",
                                  f"{it['size'].split('-')[0]}×{L:g}")

    def mating(self, it, depth):
        from . import parts
        pk = parts.heat_insert_pocket(it["size"])
        if pk["depth"] > depth:
            raise _err(f"The insert pocket ({pk['depth']:.1f} mm) is deeper than the host ({depth:.1f} mm).",
                       "Use a thicker boss, or the short insert.")
        return pk

    def mating_dims(self, it, depth):
        od, L, hole, wall = INSERTS[it["size"]]
        return {"hole_d": _dim(hole, INSERT_SOURCE + " (recommended hole)"),
                "depth": _dim(L + 1.0, "insert length + 1 mm for displaced plastic (assumed)", COMPUTED),
                "boss_min_d": _dim(hole + 2 * wall, "hole + 2 × minimum wall", COMPUTED)}

    def default_depth(self, it):
        return INSERTS[it["size"]][1] + 2.0


class Magnet(Family):
    id, label, standard, category = "magnet", "Disc magnet (NdFeB)", "NdFeB sintered", "magnets"
    keywords = ("magnet", "neodymium", "ndfeb", "disc", "cylinder")
    mate = "clearance"
    options = {"d": _num_opt(6.0, 1, 100, "Diameter (as sold; measure yours)."),
               "h": _num_opt(3.0, 0.5, 50, "Thickness (as sold; measure yours)."),
               "grade": {"default": "N42", "choices": tuple(MAGNETS), "doc": "Grade (remanence class)."},
               "clearance": _num_opt(0.1, 0, 1, "Added per side to the pocket (assumed, FDM).")}

    def sizes(self):
        return ["disc"]

    def source(self):
        return MAGNET_SOURCE

    def resolve(self, it):
        it = dict(it, size=it.get("size") or "disc")
        return Family.resolve(self, it)

    def designation(self, it):
        return f"NdFeB disc magnet Ø{it['d']:g}×{it['h']:g} {it['grade']}, axially magnetised"

    def dims(self, it):
        g = MAGNETS[it["grade"]]
        return {"d": _dim(it["d"], "caller (the magnet as sold)", ASSUMED), "h": _dim(it["h"], "caller", ASSUMED),
                "Br_min": _dim(g[0], MAGNET_SOURCE, unit="T"), "Br_max": _dim(g[1], MAGNET_SOURCE, unit="T"),
                "HcJ_min": _dim(g[2], MAGNET_SOURCE, unit="kA/m"),
                "BHmax_min": _dim(g[3], MAGNET_SOURCE, unit="kJ/m³"), "BHmax_max": _dim(g[4], MAGNET_SOURCE, unit="kJ/m³"),
                "max_temp": _dim(g[5], MAGNET_SOURCE + " (plain grade)", unit="°C")}

    def material(self, it):
        return None, "sintered NdFeB " + it["grade"], MAGNET_DENSITY[1]

    def build(self, it):
        from build123d import Cylinder, Pos
        from . import parts
        shape = Pos(0, 0, -it["h"]) * Cylinder(it["d"] / 2, it["h"], align=parts.BOTTOM)
        return parts.HardwarePart(self.designation(it), shape, "hardware", self.dims(it), None, "ndfeb", "NdFeB",
                                  f"Ø{it['d']:g}×{it['h']:g}")

    def mating(self, it, depth):
        from . import parts
        pk = parts.magnet_pocket(it["d"], it["h"], clearance=float(it.get("clearance") or 0.1))
        if pk["depth"] > depth:
            raise _err(f"The magnet pocket ({pk['depth']:.1f} mm) is deeper than the host ({depth:.1f} mm).", "Use a thicker host.")
        return pk

    def mating_dims(self, it, depth):
        c = float(it.get("clearance") or 0.1)
        return {"pocket_d": _dim(it["d"] + 2 * c, f"d + 2 × {c:g} mm (assumed)", COMPUTED),
                "pocket_depth": _dim(it["h"] + 0.2, "h + 0.2 mm", COMPUTED)}

    def default_depth(self, it):
        return it["h"] + 1.2


class ORing(Family):
    id, label, standard, category = "oring", "O-ring", "ISO 3601-1", "seals"
    keywords = ("oring", "o-ring", "seal", "3601", "as568")
    mate = "seal"
    options = {"material": {"default": "NBR 70", "choices": ("NBR 70", "FKM 75", "EPDM 70", "VMQ 70"),
                            "doc": "Compound (no density source here: mass is not given)."}}

    def table(self):
        return _bd_csv("o-ring_parameters.csv", "iso3601")

    def sizes(self):
        return list(self.table())

    def source(self):
        return _bd_src("ISO 3601-1 class A", "id, w", "o-ring_parameters.csv")

    def gland(self, w: float) -> dict:
        d = _bd_data_dir()
        if d is not None:
            with open(d / "o-ring_static_gland_parameters.csv", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if abs(float(row["w"]) - w) < 1e-6:
                        return row
        raise _err(f"No gland data for a {w:g} mm section.")

    def designation(self, it):
        r = self.table()[it["size"]]
        return f"O-ring ISO 3601-1 A {it['size']} ({r['id']:g}×{r['w']:g}) {it['material']}"

    def dims(self, it):
        r = self.table()[it["size"]]
        return {"inner_d": _dim(r["id"], self.source() + ": id"), "section": _dim(r["w"], self.source() + ": w"),
                "inner_d_tol": _dim(r["id_tol"], self.source() + ": ± id"), "section_tol": _dim(r["w_tol"], self.source() + ": ± w")}

    def build(self, it):
        from build123d import Circle, Plane, Pos, revolve
        from . import parts
        r = self.table()[it["size"]]
        g = self.gland(r["w"])
        depth = (float(g["d_a_min"]) + float(g["d_a_max"])) / 2
        R = r["id"] / 2 + r["w"] / 2
        sec = Plane.XZ * Pos(R, -depth + r["w"] / 2) * Circle(r["w"] / 2)
        shape = revolve(sec)
        return parts.HardwarePart(self.designation(it), shape, "hardware", self.dims(it), None, "", "ISO 3601-1", it["size"])

    def mating(self, it, depth):
        from build123d import Cylinder, Pos
        from . import parts
        r = self.table()[it["size"]]
        md = self.mating_dims(it, depth)
        gd, gw = md["groove_depth"]["value"], md["groove_width"]["value"]
        if gd >= depth:
            raise _err(f"The gland ({gd:.2f} mm) is as deep as the host ({depth:.1f} mm).", "Use a thicker host.")
        ri = r["id"] / 2
        shape = Pos(0, 0, parts.OVERSHOOT) * (Cylinder(ri + gw, gd + parts.OVERSHOOT, align=parts.TOP)
                                              - Cylinder(ri, gd + parts.OVERSHOOT, align=parts.TOP))
        return parts.HardwarePart(f"{it['size']} face gland", shape, "cut", md)

    def mating_dims(self, it, depth):
        r = self.table()[it["size"]]
        g = self.gland(r["w"])
        src = (f"static axial gland for a {r['w']:g} mm section: Apple Rubber Seal Design Guide values as tabulated "
               f"by bd_warehouse (data/o-ring_static_gland_parameters.csv; not verified against ISO 3601-2)")
        gd = (float(g["d_a_min"]) + float(g["d_a_max"])) / 2
        return {"groove_depth": _dim(round(gd, 3), src + ", mid of d_a", COMPUTED),
                "groove_width": _dim(float(g["g_w_0"]), src + ", g_w_0"),
                "groove_inner_d": _dim(r["id"], "O-ring inner diameter (internal pressure face seal, assumed)", COMPUTED),
                "squeeze_pct": _dim(round(100 * (r["w"] - gd) / r["w"], 1), "(w − groove depth) / w", COMPUTED, "%")}

    def default_depth(self, it):
        return self.table()[it["size"]]["w"] + 2.0


# ---- bearings, bushings, shafts, collars, dowels ----------------------------------------------------------------------
class Bearing(Family):
    id, label, standard, category = "bearing", "Deep-groove ball bearing", "ISO 15", "motion"
    keywords = ("bearing", "ball", "608", "skateboard", "deep groove", "62", "60")
    mate = "clearance"
    options = {"seal": {"default": "2Z", "choices": tuple(BEARING_SEALS), "doc": "Open, two shields (2Z) or two seals (2RS)."},
               "fit": _num_opt(0.05, -0.2, 0.5, "Added to the outside diameter for the seat (assumed; calibrate)."),
               "lip": {"default": "yes", "choices": ("yes", "no"), "doc": "A through hole below the seat leaving a shoulder."}}

    def sizes(self):
        return list(BEARINGS)

    def source(self):
        return BEARING_SOURCE

    def designation(self, it):
        d, D, B = BEARINGS[it["size"]]
        return f"Deep-groove ball bearing {it['size']}{BEARING_SEALS[it['seal']]} ({d:g}×{D:g}×{B:g})"

    def dims(self, it):
        d, D, B = BEARINGS[it["size"]]
        return {"bore": _dim(d, BEARING_SOURCE + ": d"), "outer_d": _dim(D, BEARING_SOURCE + ": D"),
                "width": _dim(B, BEARING_SOURCE + ": B")}

    def _skf(self, it):
        t = _bd_csv("single_row_deep_groove_ball_bearing_parameters.csv", "SKT")
        d, D, B = BEARINGS[it["size"]]
        for v in t.values():
            name = str(v.get("Designation", "")).replace("*", "").strip().split(".")[0]
            if name == it["size"] and (v.get("d"), v.get("D"), v.get("B")) == (d, D, B):
                return v
        return None

    def catalogue_grams(self, it):
        v = self._skf(it)
        if v and v.get("mass"):
            return float(v["mass"]) * 1000.0, ("SKF catalogue mass as tabulated by bd_warehouse "
                                                "(data/single_row_deep_groove_ball_bearing_parameters.csv)")
        return None

    def material(self, it):
        return "STEEL-4140", "bearing steel", "density of alloy steel 4140 (assumed for bearing steel)"

    def build(self, it):
        from build123d import Cylinder, Pos
        from . import parts
        d, D, B = BEARINGS[it["size"]]
        t = (D - d) / 2
        ri, ro = d / 2 + 0.3 * t, D / 2 - 0.3 * t         # rings each 30 % of the section (balls and cage not modelled)
        inner = Cylinder(ri, B, align=parts.BOTTOM) - Cylinder(d / 2, B, align=parts.BOTTOM)
        outer = Cylinder(D / 2, B, align=parts.BOTTOM) - Cylinder(ro, B, align=parts.BOTTOM)
        shape = inner + outer
        if it["seal"] != "open":
            sh = 0.3
            for z in (0.15, B - 0.15 - sh):
                shape = shape + Pos(0, 0, z) * (Cylinder(ro + 0.01, sh, align=parts.BOTTOM) - Cylinder(ri - 0.01, sh, align=parts.BOTTOM))
        shape = Pos(0, 0, -B) * shape
        dims = {**self.dims(it), "model": _dim(0.3, "rings each 30 % of the radial section; balls and cage not "
                                                    "modelled (the envelope d, D, B is exact)", ASSUMED, "")}
        return parts.HardwarePart(self.designation(it), shape, "hardware", dims, None, "", "ISO 15",
                                  f"{d:g}×{D:g}×{B:g}")

    def mating(self, it, depth):
        from build123d import Cylinder, Pos
        from . import parts
        d, D, B = BEARINGS[it["size"]]
        if B > depth + 1e-9:
            raise _err(f"The {it['size']} seat ({B:g} mm) is deeper than the host ({depth:.1f} mm).", "Use a thicker host.")
        md = self.mating_dims(it, depth)
        seat = md["seat_d"]["value"]
        shape = Pos(0, 0, parts.OVERSHOOT) * Cylinder(seat / 2, B + parts.OVERSHOOT, align=parts.TOP)
        if it.get("lip", "yes") == "yes" and depth - B > 0.2:
            shape = shape + Pos(0, 0, -B + 0.01) * Cylinder(md["lip_hole_d"]["value"] / 2, depth - B + parts.OVERSHOOT, align=parts.TOP)
        return parts.HardwarePart(f"{it['size']} bearing seat", shape, "cut", md)

    def mating_dims(self, it, depth):
        d, D, B = BEARINGS[it["size"]]
        f = float(it.get("fit") if it.get("fit") is not None else 0.05)
        t = (D - d) / 2
        return {"seat_d": _dim(D + f, f"D + {f:g} mm (assumed fit)", COMPUTED),
                "seat_depth": _dim(B, BEARING_SOURCE + ": B"),
                "lip_hole_d": _dim(round(D - 2 * 0.3 * t - 0.4, 3), "outer ring's inner edge − 0.4 mm: the shoulder holds the "
                                                                    "outer ring, the inner ring turns free (computed)", COMPUTED)}

    def default_depth(self, it):
        return BEARINGS[it["size"]][2] + 2.0


class LinearBushing(Family):
    id, label, standard, category = "lm_uu", "Linear ball bushing", "THK LM", "motion"
    keywords = ("lm8uu", "lmuu", "linear bearing", "bushing", "lm6uu", "lm10uu", "lm12uu", "linear")
    mate = "clearance"
    options = {"fit": _num_opt(0.05, -0.2, 0.5, "Added to D for the housing bore (assumed; THK specifies H7 or J7 in metal).")}

    def sizes(self):
        return list(LM)

    def source(self):
        return LM_SOURCE

    def designation(self, it):
        d, D, L, *_ = LM[it["size"]]
        return f"Linear ball bushing {it['size']} ({d:g}×{D:g}×{L:g})"

    def dims(self, it):
        d, D, L, B, W, D1 = LM[it["size"]]
        return {"bore": _dim(d, LM_SOURCE + ": dr"), "outer_d": _dim(D, LM_SOURCE + ": D"), "length": _dim(L, LM_SOURCE + ": L"),
                "groove_spacing": _dim(B, LM_SOURCE + ": L1"), "groove_width": _dim(W, LM_SOURCE + ": L2"),
                "groove_d": _dim(D1, LM_SOURCE + ": D0")}

    def build(self, it):
        from build123d import Cylinder, Pos
        from . import parts
        d, D, L, B, W, D1 = LM[it["size"]]
        shape = Cylinder(D / 2, L, align=parts.BOTTOM) - Cylinder(d / 2 + 0.6, L, align=parts.BOTTOM)
        ring = Cylinder(D / 2 + 0.1, W, align=parts.BOTTOM) - Cylinder(D1 / 2, W, align=parts.BOTTOM)
        for z in ((L - B) / 2, (L + B) / 2 - W):
            shape = shape - Pos(0, 0, z) * ring
        shape = Pos(0, 0, -L) * shape
        dims = {**self.dims(it), "model": _dim(0.6, "outer sleeve with its retaining-ring grooves; ball circuits not "
                                                    "modelled (bore shown 0.6 mm open)", ASSUMED)}
        return parts.HardwarePart(self.designation(it), shape, "hardware", dims, None, "", "THK LM", it["size"])

    def mating(self, it, depth):
        from build123d import Cylinder, Pos
        from . import parts
        d, D, L, *_ = LM[it["size"]]
        if L > depth + 1e-9:
            raise _err(f"The {it['size']} housing bore ({L:g} mm) is deeper than the host ({depth:.1f} mm).", "Use a thicker host.")
        md = self.mating_dims(it, depth)
        shape = Pos(0, 0, parts.OVERSHOOT) * Cylinder(md["bore_d"]["value"] / 2, L + parts.OVERSHOOT, align=parts.TOP)
        if depth - L > 0.2:
            shape = shape + Pos(0, 0, -L + 0.01) * Cylinder(d / 2 + 1.0, depth - L + parts.OVERSHOOT, align=parts.TOP)
        return parts.HardwarePart(f"{it['size']} housing bore", shape, "cut", md)

    def mating_dims(self, it, depth):
        d, D, L, *_ = LM[it["size"]]
        f = float(it.get("fit") if it.get("fit") is not None else 0.05)
        return {"bore_d": _dim(D + f, f"D + {f:g} mm (assumed)", COMPUTED), "bore_depth": _dim(L, LM_SOURCE + ": L"),
                "shaft_hole_d": _dim(d + 2.0, "shaft + 2 mm clearance below the bushing (assumed)", COMPUTED)}

    def default_depth(self, it):
        return LM[it["size"]][2] + 2.0


class LinearRod(Family):
    id, label, standard, category = "linear_rod", "Linear shaft (ground)", "THK LM shaft", "motion"
    keywords = ("rod", "shaft", "linear rod", "smooth rod", "ground shaft")
    mate = "press"
    options = {"length": _num_opt(300.0, 10, 3000, "Cut length (caller)."),
               "tolerance": {"default": "h6", "choices": ("f6", "g6", "h6"), "doc": "Shaft tolerance class (THK)."},
               "inserted": _num_opt(10.0, 1, 200, "How deep the shaft sits in the host (caller)."),
               "fit": _num_opt(-0.05, -0.5, 0.5, "Added to the shaft diameter for the host's hole (assumed; negative = press).")}

    def sizes(self):
        return [str(LM[k][0]) for k in LM]

    def source(self):
        return SHAFT_TOL_SOURCE

    def designation(self, it):
        return f"Linear shaft Ø{it['size']} {it['tolerance']} × {it['length']:g}, hardened and ground"

    def dims(self, it):
        return {"d": _dim(float(it["size"]), "nominal; the diameter the LM bushings of the same bore run on (" + LM_SOURCE + ")"),
                "length": _dim(it["length"], "caller", ASSUMED),
                "tolerance": _dim(0, f"{it['tolerance']}: " + SHAFT_TOL_SOURCE, SPECIFIED, "")}

    def material(self, it):
        return "STEEL-4140", "hardened bearing steel", "density of alloy steel 4140 (assumed)"

    def build(self, it):
        from build123d import Cylinder, Pos
        from . import parts
        d = float(it["size"])
        shape = Pos(0, 0, -it["inserted"]) * Cylinder(d / 2, it["length"], align=parts.BOTTOM)
        return parts.HardwarePart(self.designation(it), shape, "hardware", self.dims(it), None, "", "linear shaft",
                                  f"Ø{d:g}×{it['length']:g}")

    def mating(self, it, depth):
        from build123d import Cylinder, Pos
        from . import parts
        dd = it["inserted"]
        if dd > depth + 1e-9:
            raise _err(f"The shaft is set {dd:g} mm deep in a host {depth:.1f} mm thick.", "Lower 'inserted'.")
        D = float(it["size"]) + float(it.get("fit") or 0.0)
        return parts.HardwarePart(f"Ø{it['size']} shaft hole", Pos(0, 0, parts.OVERSHOOT) * Cylinder(D / 2, dd + parts.OVERSHOOT, align=parts.TOP),
                                  "cut", self.mating_dims(it, depth))

    def mating_dims(self, it, depth):
        f = float(it.get("fit") or 0.0)
        return {"hole_d": _dim(float(it["size"]) + f, f"d {f:+g} mm (assumed)", COMPUTED),
                "hole_depth": _dim(it["inserted"], "caller", ASSUMED)}

    def default_depth(self, it):
        return it["inserted"] + 2.0


class ShaftCollar(Family):
    id, label, standard, category = "shaft_collar", "Shaft collar (set screw)", "DIN 705 A", "motion"
    keywords = ("collar", "shaft collar", "stellring", "705", "lock collar")
    mate = "surface"
    options = {"grade": {"default": "steel", "choices": ("steel", "stainless"), "doc": "Material."}}

    def sizes(self):
        return [f"{d:g}" for d in COLLARS]

    def source(self):
        return COLLAR_SOURCE

    def row(self, it):
        return COLLARS[float(it["size"]) if "." in it["size"] else int(it["size"])]

    def designation(self, it):
        return f"Adjusting ring DIN 705 A {it['size']} ({'stainless' if it['grade'] == 'stainless' else 'steel'})"

    def dims(self, it):
        D, b, s = self.row(it)
        return {"bore": _dim(float(it["size"]), COLLAR_SOURCE + ": d (H8)"), "outer_d": _dim(D, COLLAR_SOURCE + ": d1"),
                "width": _dim(b, COLLAR_SOURCE + ": b (js14)"),
                "set_screw": _dim(float(s[1:]), COLLAR_SOURCE + f": set screw {s}")}

    def material(self, it):
        return ("STAINLESS", "stainless", "density of stainless 304") if it["grade"] == "stainless" else \
            ("STEEL", "steel", "density of mild steel (assumed)")

    def build(self, it):
        from build123d import Cylinder, Pos, Rot
        from . import parts
        D, b, s = self.row(it)
        d = float(it["size"])
        sd = float(s[1:])
        ring = Cylinder(D / 2, b, align=parts.BOTTOM) - Cylinder(d / 2, b, align=parts.BOTTOM)
        hole = Pos(0, 0, b / 2) * Rot(0, 90, 0) * Cylinder(sd * 0.42, D, align=parts.BOTTOM)   # tapped hole, cosmetic
        shape = ring - hole
        return parts.HardwarePart(self.designation(it), shape, "hardware",
                                  {**self.dims(it), "thread": _dim(0, COSMETIC, SPECIFIED, "")}, None, "", "DIN 705",
                                  f"d {d:g}")


class Dowel(Family):
    id, label, standard, category = "dowel", "Dowel pin (hardened)", "ISO 8734", "motion"
    keywords = ("dowel", "pin", "parallel pin", "8734")
    mate = "press"
    options = {"length": _num_opt(None, 3, 100, "Nominal length from the ISO 8734 series."),
               "inserted": _num_opt(None, 1, 100, "How deep it sits in the host; default half the length (assumed)."),
               "fit": _num_opt(-0.02, -0.3, 0.5, "Added to d for the host's hole (assumed; negative = press).")}

    def sizes(self):
        return [f"{d:g}" for d in DOWELS]

    def source(self):
        return DOWEL_SOURCE

    def row(self, it):
        return DOWELS[float(it["size"])]

    def resolve(self, it):
        out = Family.resolve(self, it)
        c, lo, hi = self.row(out)
        if out.get("length") is None:
            out["length"] = float(next(L for L in DOWEL_LENGTHS if L >= lo))
        if out.get("inserted") is None:
            out["inserted"] = round(out["length"] / 2, 2)
        if out["inserted"] >= out["length"]:
            raise _err("The pin cannot sit deeper than it is long.")
        return out

    def check(self, it):
        if it.get("length") is None:
            return
        c, lo, hi = self.row(it)
        if it["length"] not in DOWEL_LENGTHS or not lo <= it["length"] <= hi:
            ok = [L for L in DOWEL_LENGTHS if lo <= L <= hi]
            raise _err(f"ISO 8734 has no {it['size']} × {it['length']:g} pin.",
                       f"Lengths for d {it['size']}: " + ", ".join(f"{x:g}" for x in ok) + " mm.")

    def designation(self, it):
        return f"Parallel pin ISO 8734 - {it['size']} × {it['length']:g} - A - St"

    def dims(self, it):
        c, lo, hi = self.row(it)
        return {"d": _dim(float(it["size"]), DOWEL_SOURCE + ": d (m6)"), "length": _dim(it["length"], DOWEL_SOURCE + ": l"),
                "chamfer": _dim(c, DOWEL_SOURCE + ": c ≈")}

    def material(self, it):
        return "STEEL-4140", "hardened steel", "density of alloy steel 4140 (assumed)"

    def build(self, it):
        from build123d import Cylinder, Pos, chamfer
        from . import parts
        c, *_ = self.row(it)
        d, L = float(it["size"]), it["length"]
        cyl = Cylinder(d / 2, L, align=parts.BOTTOM)
        cyl = chamfer(cyl.edges(), min(c, d / 2 - 0.01))
        shape = Pos(0, 0, -it["inserted"]) * cyl
        return parts.HardwarePart(self.designation(it), shape, "hardware", self.dims(it), None, "", "ISO 8734",
                                  f"{d:g}×{L:g}")

    def mating(self, it, depth):
        from build123d import Cylinder, Pos
        from . import parts
        dd = it["inserted"]
        if dd > depth + 1e-9:
            raise _err(f"The pin is set {dd:g} mm deep in a host {depth:.1f} mm thick.", "Lower 'inserted'.")
        D = float(it["size"]) + float(it.get("fit") or 0.0)
        return parts.HardwarePart(f"Ø{it['size']} dowel hole", Pos(0, 0, parts.OVERSHOOT) * Cylinder(D / 2, dd + parts.OVERSHOOT, align=parts.TOP),
                                  "cut", self.mating_dims(it, depth))

    def mating_dims(self, it, depth):
        f = float(it.get("fit") or 0.0)
        return {"hole_d": _dim(float(it["size"]) + f, f"d {f:+g} mm (assumed)", COMPUTED),
                "hole_depth": _dim(it["inserted"], "caller or half the length (assumed)", ASSUMED)}

    def default_depth(self, it):
        return (it.get("inserted") or 5) + 2.0


# ---- motion: belts, pulleys, motors -----------------------------------------------------------------------------------
class GT2Pulley(Family):
    id, label, standard, category = "gt2_pulley", "GT2 pulley", "GT2 2 mm pitch", "motion"
    keywords = ("gt2", "pulley", "timing pulley", "2gt")
    mate = "surface"
    options = {"bore": {"default": "5", "choices": ("5", "6.35", "8"), "doc": "Bore (caller; as sold)."},
               "belt_width": {"default": "6", "choices": ("6", "9"), "doc": "Belt width it takes (caller; as sold)."}}

    def sizes(self):
        return [str(z) for z in GT2_TEETH]

    def source(self):
        return GT2_SOURCE

    def pd(self, it) -> float:
        return int(it["size"]) * GT2_PITCH / math.pi

    def designation(self, it):
        return f"GT2 pulley {it['size']}T, bore {it['bore']} mm, for {it['belt_width']} mm belt"

    def dims(self, it):
        pd = self.pd(it)
        return {"teeth": _dim(int(it["size"]), "caller", ASSUMED, ""), "pitch": _dim(GT2_PITCH, GT2_SOURCE),
                "pitch_d": _dim(round(pd, 3), "z × pitch / π", COMPUTED),
                "outer_d": _dim(round(pd - 2 * GT2_PLD, 3), f"pitch d − 2 × {GT2_PLD} mm pitch-line differential "
                                                            "(assumed: not verified from a Gates table)", ASSUMED),
                "bore": _dim(float(it["bore"]), "caller (as sold)", ASSUMED),
                "belt_width": _dim(float(it["belt_width"]), "caller", ASSUMED),
                "teeth_model": _dim(0, "teeth cosmetic: the toothed band is modelled as a cylinder at the outer diameter", ASSUMED, "")}

    def build(self, it):
        from build123d import Cylinder, Pos
        from . import parts
        pd = self.pd(it)
        od = pd - 2 * GT2_PLD
        w = float(it["belt_width"]) + 1.0
        fl = od + 2 * 1.5                                  # flanges and hub: maker-specific, assumed
        hub_d, hub_h = max(od, float(it["bore"]) + 6), 7.0
        shape = Cylinder(hub_d / 2, hub_h, align=parts.BOTTOM)
        z = hub_h
        shape = shape + Pos(0, 0, z) * Cylinder(fl / 2, 1.0, align=parts.BOTTOM)
        shape = shape + Pos(0, 0, z + 1.0) * Cylinder(od / 2, w, align=parts.BOTTOM)
        shape = shape + Pos(0, 0, z + 1.0 + w) * Cylinder(fl / 2, 1.0, align=parts.BOTTOM)
        shape = shape - Cylinder(float(it["bore"]) / 2, z + w + 2.0, align=parts.BOTTOM)
        dims = {**self.dims(it), "hub": _dim(hub_h, "hub and flanges vary by maker: modelled 7 mm hub, 1 mm flanges (assumed)", ASSUMED)}
        return parts.HardwarePart(self.designation(it), shape, "hardware", dims, None, "", "GT2", f"{it['size']}T")

    def material(self, it):
        return "AL-6061", "aluminium", "density of aluminium 6061 (assumed); the solid is a simplified model (estimate)"


class GT2Belt(Family):
    id, label, standard, category = "gt2_belt", "GT2 belt (closed loop)", "GT2 2 mm pitch", "motion"
    keywords = ("gt2", "belt", "timing belt", "2gt", "loop")
    mate = "surface"
    options = {"teeth": _num_opt(100, 20, 2000, "Teeth in the loop (length = teeth × 2 mm)."),
               "width": {"default": "6", "choices": ("6", "9"), "doc": "Width (caller; as sold)."}}

    def sizes(self):
        return ["loop"]

    def source(self):
        return GT2_SOURCE

    def resolve(self, it):
        out = Family.resolve(self, dict(it, size=it.get("size") or "loop"))
        out["teeth"] = int(round(out["teeth"]))
        return out

    def designation(self, it):
        return f"GT2 belt, closed loop {it['teeth'] * GT2_PITCH:g} mm ({it['teeth']} teeth), {it['width']} mm wide"

    def dims(self, it):
        return {"pitch": _dim(GT2_PITCH, GT2_SOURCE), "height": _dim(GT2_BELT_H, GT2_SOURCE + ": belt height"),
                "tooth_h": _dim(GT2_TOOTH_H, GT2_SOURCE + ": tooth depth"),
                "length": _dim(it["teeth"] * GT2_PITCH, "teeth × pitch", COMPUTED),
                "width": _dim(float(it["width"]), "caller", ASSUMED)}

    def build(self, it):
        from build123d import Cylinder
        from . import parts
        L = it["teeth"] * GT2_PITCH
        r = L / (2 * math.pi)                              # shown as a circle of the same pitch length (cosmetic teeth)
        w = float(it["width"])
        shape = Cylinder(r + GT2_BELT_H - GT2_TOOTH_H, w, align=parts.BOTTOM) - Cylinder(r - GT2_TOOTH_H, w, align=parts.BOTTOM)
        dims = {**self.dims(it), "model": _dim(0, "shown as a round loop of the same pitch length; teeth cosmetic", ASSUMED, "")}
        return parts.HardwarePart(self.designation(it), shape, "hardware", dims, None, "", "GT2", f"{L:g} mm")


def belt_teeth(teeth_a: int, teeth_b: int, centre: float) -> dict:
    """The closed GT2 loop for two pulleys at a centre distance: L = 2C + π(D1+D2)/2 + (D2−D1)²/(4C) on the pitch
    diameters, rounded up to whole teeth (computed)."""
    d1, d2 = sorted((teeth_a * GT2_PITCH / math.pi, teeth_b * GT2_PITCH / math.pi))
    L = 2 * centre + math.pi * (d1 + d2) / 2 + (d2 - d1) ** 2 / (4 * centre)
    n = math.ceil(L / GT2_PITCH - 1e-9)
    return {"length_mm": round(L, 3), "teeth": n, "loop_mm": n * GT2_PITCH, "evidence": COMPUTED,
            "formula": "L = 2C + π(D1+D2)/2 + (D2−D1)²/(4C), pitch diameters z·2/π"}


class Nema(Family):
    id, label, category = "nema", "Stepper motor (NEMA frame)", "motion"
    standard = "NEMA ICS 16"
    keywords = ("nema", "stepper", "motor", "nema17", "nema23", "17", "23")
    mate = "clearance"
    options = {"body_length": _num_opt(40.0, 20, 150, "Body length (varies by motor: caller)."),
               "shaft_length": _num_opt(24.0, 5, 60, "Shaft length past the pilot (varies by motor: caller)."),
               "pilot_clearance": _num_opt(0.2, 0, 2, "Added to the pilot diameter for its pocket (assumed)."),
               "fit": {"default": "normal", "choices": ("close", "normal", "loose"), "doc": "Screw clearance series (ISO 273)."}}

    def sizes(self):
        return list(NEMA)

    def source(self):
        return NEMA_SOURCE

    def designation(self, it):
        return f"Stepper motor NEMA {it['size']} ({NEMA[it['size']][0]:g} mm frame), body {it['body_length']:g} mm"

    def dims(self, it):
        sq, sp, hd, pd, ph, sd, scr = NEMA[it["size"]]
        return {"frame": _dim(sq, "about " + f"{sq:g} mm (Aspina text); body square varies slightly by maker", ASSUMED),
                "hole_spacing": _dim(sp, NEMA_SPACING_SOURCE), "hole_d": _dim(hd, NEMA_SOURCE + ": mounting hole"),
                "pilot_d": _dim(pd, NEMA_SOURCE), "pilot_h": _dim(ph, NEMA_SOURCE + " (within its range)"),
                "shaft_d": _dim(sd, NEMA_SOURCE),
                "body_length": _dim(it["body_length"], "caller", ASSUMED), "shaft_length": _dim(it["shaft_length"], "caller", ASSUMED)}

    def build(self, it):
        from build123d import Box, Cylinder, Pos
        from . import parts
        sq, sp, hd, pd, ph, sd, scr = NEMA[it["size"]]
        body = Box(sq, sq, it["body_length"], align=parts.BOTTOM)
        for x in (-sp / 2, sp / 2):
            for y in (-sp / 2, sp / 2):
                body = body - Pos(x, y, 0) * Cylinder(hd / 2, 4.5, align=parts.BOTTOM)
        pilot = Cylinder(pd / 2, ph, align=parts.TOP)
        shaft = Pos(0, 0, -ph) * Cylinder(sd / 2, it["shaft_length"], align=parts.TOP)
        shape = body + pilot + shaft
        return parts.HardwarePart(self.designation(it), shape, "hardware", self.dims(it), None, "", "NEMA ICS 16",
                                  f"NEMA {it['size']}")

    def mating(self, it, depth):
        from build123d import Cylinder, Pos
        from . import parts
        sq, sp, hd, pd, ph, sd, scr = NEMA[it["size"]]
        md = self.mating_dims(it, depth)
        if ph + 0.2 >= depth:
            raise _err(f"The pilot pocket ({ph + 0.2:.1f} mm) is as deep as the plate ({depth:.1f} mm).", "Use a thicker plate.")
        P = md["pilot_pocket_d"]["value"]
        shape = Pos(0, 0, parts.OVERSHOOT) * Cylinder(P / 2, ph + 0.2 + parts.OVERSHOOT, align=parts.TOP)
        shape = shape + Pos(0, 0, parts.OVERSHOOT) * Cylinder(md["shaft_hole_d"]["value"] / 2, depth + 2 * parts.OVERSHOOT, align=parts.TOP)
        hcl = md["screw_hole_d"]["value"]
        for x in (-sp / 2, sp / 2):
            for y in (-sp / 2, sp / 2):
                shape = shape + Pos(x, y, parts.OVERSHOOT) * Cylinder(hcl / 2, depth + 2 * parts.OVERSHOOT, align=parts.TOP)
        return parts.HardwarePart(f"NEMA {it['size']} mount", shape, "cut", md)

    def mating_dims(self, it, depth):
        sq, sp, hd, pd, ph, sd, scr = NEMA[it["size"]]
        c = float(it.get("pilot_clearance") or 0.2)
        d, src = _clearance(scr, it.get("fit") or "normal")
        return {"pilot_pocket_d": _dim(pd + c, f"pilot + {c:g} mm (assumed)", COMPUTED),
                "pilot_pocket_depth": _dim(ph + 0.2, "pilot height + 0.2 mm", COMPUTED),
                "shaft_hole_d": _dim(sd + 2.0, "shaft + 2 mm (assumed)", COMPUTED),
                "screw_hole_d": _dim(d, src + f" for {scr} (the screws most {it['size']} frames take; check the motor)"),
                "hole_spacing": _dim(sp, NEMA_SPACING_SOURCE)}

    def fitted_z(self, it):
        return 0.0

    def default_depth(self, it):
        return 5.0


# ---- frame: extrusion and T-nuts ------------------------------------------------------------------------------------
class Extrusion(Family):
    id, label, standard, category = "extrusion", "Aluminium extrusion (V-Slot)", "OpenBuilds V-Slot", "frame"
    keywords = ("2020", "2040", "extrusion", "profile", "vslot", "v-slot", "aluminium", "aluminum")
    mate = "surface"
    options = {"length": _num_opt(500.0, 10, 3000, "Cut length (caller).")}

    def sizes(self):
        return list(VSLOTS)

    def source(self):
        return VSLOT_SOURCE

    def designation(self, it):
        return f"V-Slot {it['size']} × {it['length']:g} mm (OpenBuilds), aluminium"

    def dims(self, it):
        a, b = VSLOTS[it["size"]]
        return {"width": _dim(a, VSLOT_SOURCE), "height": _dim(b, VSLOT_SOURCE), "length": _dim(it["length"], "caller", ASSUMED),
                "centre_bore": _dim(5, VSLOT_SOURCE + ": M5 tap-ready centre bore", SPECIFIED, "M")}

    def material(self, it):
        return "AL-6061", "aluminium", "density of aluminium 6061 (assumed; the alloy is not on the product page)"

    def build(self, it):
        from . import parts
        ob = _open_builds()
        size = {"2020": "20x20", "2040": "20x40"}[it["size"]]
        obj = ob.VSlotLinearRail(size, it["length"])
        return parts.HardwarePart(self.designation(it), obj, "hardware", self.dims(it), None, "", "OpenBuilds V-Slot",
                                  f"{it['size']}×{it['length']:g}")


class TNut(Family):
    id, label, standard, category = "tnut", "T-nut for V-Slot (M5)", "OpenBuilds Tee Nut", "frame"
    keywords = ("tnut", "t-nut", "tee nut", "slot nut", "2020")
    mate = "clearance"
    thread = COSMETIC
    options = {"fit": {"default": "normal", "choices": ("close", "normal", "loose"), "doc": "M5 clearance series (ISO 273)."}}

    def sizes(self):
        return ["M5"]

    def source(self):
        return TNUT_SOURCE

    def designation(self, it):
        return "Tee nut M5 for V-Slot (OpenBuilds), mild steel"

    def dims(self, it):
        return {"thread": _dim(5, TNUT_SOURCE, SPECIFIED, "M"), "width": _dim(5.9, TNUT_SOURCE), "length": _dim(10, TNUT_SOURCE)}

    def material(self, it):
        return "STEEL", "mild steel", "density of mild steel"

    def build(self, it):
        from build123d import Pos
        from . import parts
        obj = _open_builds().TNut()
        bb = obj.bounding_box()
        shape = Pos(0, 0, -bb.max.Z) * obj                 # the nut's top face at the host's far side is moved by place
        return parts.HardwarePart(self.designation(it), shape, "hardware", self.dims(it), None, "", "OpenBuilds", "M5")

    def mating(self, it, depth):
        from build123d import Cylinder, Pos
        from . import parts
        d, src = _clearance("M5", it.get("fit") or "normal")
        return parts.HardwarePart("M5 clearance", Pos(0, 0, parts.OVERSHOOT) * Cylinder(d / 2, depth + 2 * parts.OVERSHOOT, align=parts.TOP),
                                  "cut", self.mating_dims(it, depth))

    def mating_dims(self, it, depth):
        d, src = _clearance("M5", it.get("fit") or "normal")
        return {"hole_d": _dim(d, src), "depth": _dim(depth, "host thickness", COMPUTED)}

    def fitted_z(self, it):
        return None                    # below the host: place() puts it at -depth


def _open_builds():
    try:
        from bd_warehouse import open_builds
    except ImportError as e:
        raise _err(f"bd_warehouse's OpenBuilds parts are not available ({e}).", 'pip install "form-studio[parts]"')
    return open_builds


FAMILIES: dict[str, Family] = {f.id: f for f in (
    ISO4762(), DIN912(), ISO7380(), ISO10642(), ISO4032(), ISO7089(), HeatInsert(), Bearing(), Dowel(), ShaftCollar(),
    LinearRod(), LinearBushing(), GT2Pulley(), GT2Belt(), Nema(), Extrusion(), TNut(), Magnet(), ORing())}


# ── the API ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def family(fid: str) -> Family:
    f = FAMILIES.get(str(fid or "").strip().lower())
    if f is None:
        raise _err(f"Unknown part family “{fid}”.", "Families: " + ", ".join(FAMILIES) + ".")
    return f


def families() -> list[dict]:
    return [f.public() for f in FAMILIES.values()]


def resolve(it: dict) -> dict:
    """A checked, complete spec {family, size, options...} (defaults filled; sizes and lengths from the tables)."""
    if not isinstance(it, dict):
        raise _err("A part is {family, size, ...}.")
    return family(it.get("family")).resolve(it)


def designation(it: dict) -> str:
    it = resolve(it)
    return family(it["family"]).designation(it)


def dims(it: dict) -> dict:
    it = resolve(it)
    return family(it["family"]).dims(it)


def describe(it: dict, depth: float | None = None) -> dict:
    """Everything known about one part without building it: designation, dimensions with sources, the mating cut's
    dimensions, material, thread and the tables it came from."""
    it = resolve(it)
    f = family(it["family"])
    mk, what, why = f.material(it)
    dep = depth if depth is not None else f.default_depth(it)
    out = {"spec": it, "designation": f.designation(it), "family": f.id, "label": f.label, "standard": f.standard,
           "source": f.source(), "dims": f.dims(it), "mate": f.mate, "mating": f.mating_dims(it, dep),
           "material": {"key": mk, "label": what, "density_note": why}}
    if f.thread:
        out["thread"] = f.thread
    cg = f.catalogue_grams(it)
    if cg:
        out["catalogue_grams"] = {"value": round(cg[0], 3), "source": cg[1], "evidence": SPECIFIED}
    return out


_SIZE = re.compile(r"\bm(\d+(?:\.\d+)?)(?:\s*[x×]\s*(\d+(?:\.\d+)?))?\b", re.I)


def search(query: str, limit: int = 24) -> list[dict]:
    """Candidates for a query ("m5 socket 12", "608", "lm8uu", "nema 17", "2020 500", "iso 4762 m3x10"), each with a
    spec, its designation and the source table. Nothing is sent anywhere: the tables are local."""
    q = str(query or "").strip().lower()
    toks = [t for t in re.split(r"[\s,;/]+", q) if t]
    m = _SIZE.search(q)
    want_size = ("M" + m.group(1)) if m else None
    want_len = float(m.group(2)) if m and m.group(2) else None
    nums = [t for t in toks if re.fullmatch(r"\d+(?:\.\d+)?", t)]
    out = []
    for f in FAMILIES.values():
        words = set(re.split(r"[\s,;/()\-]+", " ".join((f.id, f.label, f.standard, *f.keywords)).lower()))
        score = sum(2 for t in toks if len(t) > 1 and (t in words or (len(t) >= 3 and any(w.startswith(t) for w in words))))
        score += 1 if f.keywords and f.keywords[0] in toks else 0       # the word the family is known by
        sizes = f.sizes()
        hits = []
        if want_size and want_size in sizes:
            hits = [want_size]
            score += 2
        for t in nums + [t.upper() for t in toks]:
            for s in sizes:
                if s.lower() == str(t).lower() and s not in hits:
                    hits.append(s)
                    score += 3
        if f.id == "din912" and "din" not in q and "912" not in q:
            score -= 1
        if score <= 0 or not toks:
            continue
        if want_len is None and "length" in f.options and isinstance(f, _Screw):
            for t in nums:
                if hits and any(abs(float(t) - L) < 1e-9 for L in f.lengths({"size": hits[0]})):
                    want_len = float(t)
        for s in (hits or sizes[:3]):
            it = {"family": f.id, "size": s}
            if want_len and "length" in f.options:
                it["length"] = want_len
            elif "length" in f.options and f.options["length"].get("default") is None and isinstance(f, _Screw):
                L = f.lengths({"size": s})
                it["length"] = L[min(len(L) - 1, 3)] if L else None
            try:
                r = resolve(it)
                out.append({"score": score + (1 if hits else 0), "spec": r, "designation": f.designation(r),
                            "family": f.id, "label": f.label, "standard": f.standard, "source": f.source()})
            except Exception as e:                       # noqa: BLE001 - a length not in stock: say so as a candidate
                out.append({"score": score - 1, "spec": it, "designation": "", "family": f.id, "label": f.label,
                            "standard": f.standard, "source": f.source(), "error": getattr(e, "msg", str(e)),
                            "hint": getattr(e, "hint", "")})
    out.sort(key=lambda x: (-x["score"], x["family"]))
    return out[:limit]


def din(designation: str) -> dict:
    """What a withdrawn DIN designation is ordered as today, and whether the dimensions are the same."""
    k = re.sub(r"\s+", " ", str(designation).strip().upper())
    for d, v in DIN_EQUIVALENTS.items():
        if k.startswith(d.upper()):
            return {"din": d, **v, "source": DIN_SOURCE}
    raise _err(f"No successor recorded for “{designation}”.", "Known: " + ", ".join(DIN_EQUIVALENTS) + ".")


# ── worker side: real CAD ────────────────────────────────────────────────────────────────────────────────────────────
def build(it: dict):
    """The part as real CAD (build123d), in the fitted frame (z = 0 at the host surface). Worker only."""
    it = resolve(it)
    f = family(it["family"])
    if isinstance(f, _Screw) and not it.get("length"):
        raise _err("A screw needs a length to be built.", "Give length, or place it so the host's thickness picks one.")
    p = f.build(it)
    z = f.fitted_z(it) if hasattr(f, "fitted_z") else 0.0
    if z:
        from build123d import Pos
        p.shape = Pos(0, 0, z) * p.shape
    return p


def mating(it: dict, depth: float):
    """The cut into the host for this part (kind "cut"), or None. Worker only."""
    it = resolve(it)
    return family(it["family"]).mating(it, float(depth))


def mass(it: dict, volume_mm3: float | None) -> dict:
    """Mass of one item with its evidence: the maker's catalogue value when there is one, else the modelled volume
    (computed on the B-rep) times the density of its material from the library, else unsourced."""
    it = resolve(it)
    f = family(it["family"])
    cg = f.catalogue_grams(it)
    if cg:
        return {"grams": round(cg[0], 3), "evidence": SPECIFIED, "source": cg[1]}
    mk, what, why = f.material(it)
    if it["family"] == "magnet" and volume_mm3:
        return {"grams": round(volume_mm3 * MAGNET_DENSITY[0] * 1e-6, 3), "evidence": COMPUTED,
                "source": f"modelled volume (B-rep) × {MAGNET_DENSITY[0]:g} kg/m³, {MAGNET_DENSITY[1]}"}
    if mk and volume_mm3:
        from . import material_library as ml
        d = ml.density(mk)
        est = isinstance(f, (Bearing, GT2Pulley))
        return {"grams": round(volume_mm3 * d["value"] * 1e-6, 3), "evidence": "estimate" if est else COMPUTED,
                "source": f"modelled volume (B-rep) × {d['value']:g} kg/m³ ({d['source']}); {why}"
                          + ("; simplified model" if est else ""), "material": mk}
    return {"grams": None, "evidence": "unsourced",
            "source": "No source here gives this part's mass, so none is stated."}


def op_catalog_part(spec: dict, step_path: str | None = None) -> dict:
    """Kernel op: build one part, measure it on the B-rep, optionally write a STEP."""
    from .massprops import unit_props
    p = build(spec)
    props = unit_props(p.shape)
    bb = p.shape.bounding_box()
    out = {"designation": p.name, "volume_mm3": round(props["volume_mm3"], 4),
           "bbox": [[round(bb.min.X, 4), round(bb.min.Y, 4), round(bb.min.Z, 4)], [round(bb.max.X, 4), round(bb.max.Y, 4), round(bb.max.Z, 4)]],
           "solids": len(p.shape.solids()), "valid": bool(p.shape.is_valid)}
    if step_path:
        from build123d import export_step
        export_step(p.shape, step_path)
        out["step"] = step_path
    return out


KERNEL_OPS = {"catalog_part": op_catalog_part}


def part_info(st, spec: dict, step_path: str | None = None) -> dict:
    """describe() plus the measured solid and the mass with its evidence. Built once per spec (cached in the studio's
    folder by the spec and the catalogue version); step_path also writes a STEP."""
    import hashlib
    import json
    from . import fsutil
    it = resolve(spec)
    key = hashlib.sha256(json.dumps([VERSION, _bd_version(), it], sort_keys=True).encode()).hexdigest()[:24]
    path = Path(st.root) / ".catalog" / f"{key}.json"
    measured = None
    if path.is_file() and not step_path:
        try:
            measured = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            measured = None
    if measured is None:
        measured = st._k("catalog_part", timeout=120, spec=it, step_path=step_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({k: v for k, v in measured.items() if k != "step"}), encoding="utf-8")
        fsutil.replace(tmp, path)
    out = describe(it)
    out["measured"] = {**measured, "evidence": COMPUTED}
    out["mass"] = mass(it, measured.get("volume_mm3"))
    return out
