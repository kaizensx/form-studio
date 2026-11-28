"""ISO 286 limits and fits, computed from the standard's formulas.

    from form.drawing import iso286
    iso286.limits("H7", 25)        # {"es"/"ES": +21, "ei"/"EI": 0 µm, "min": 25.000, "max": 25.021, ...}
    iso286.fit("H7/g6", 25)        # hole, shaft, clearance range, kind
    iso286.it(7, 25)               # 21 µm, with how it was obtained

How each number is made (ISO 286-1:2010, Annex A):

- The nominal size step's geometric mean D = sqrt(D1 * D2) (the first step uses 1 and 3).
- The standard tolerance factor i = 0.45 * cbrt(D) + 0.001 * D (µm); ITn = k_n * i with k = 7, 10, 16, 25, 40, 64,
  100, 160, 250, 400, 640, 1000, 1600, 2500 for IT5 .. IT18, rounded by the Annex rounding table.
- Fundamental deviations by the Annex formulas: d = -16 D^0.44, e = -11 D^0.41, f = -5.5 D^0.41, g = -2.5 D^0.34,
  h = 0; k = +0.6 cbrt(D) (IT4 to IT7, else 0), m = IT7 - IT6, n = +5 D^0.34, p = IT7 + 0 to 5, r = sqrt(p * s),
  s = IT8 + 1 to 4 (up to 50 mm) or IT7 + 0.4 D, t = IT7 + 0.63 D, u = IT7 + D.
- Holes: EI = -es for D to H; ES = -ei for K to U, plus delta = ITn - IT(n-1) for K, M, N up to IT8 and P to U up to
  IT7 (the delta rule); JS and js are +-IT/2.

ISO 286-1 says its tables govern, and in a few cells the table is not the bare formula rounded (the 1 to 3 mm step
is tabulated outright, and some cells keep the older ISA rounding). Those cells are listed below in PUBLISHED with
their table value, and every value says how it was obtained ("formula" or "table"). tests/test_drawing_iso286.py
checks every cell against the published ISO 286-2 values: formula where the list is silent, table where it speaks.
Sizes: 1 to 500 mm (r, s, t, u: up to 180 mm, the range the tests verify against the published table).
"""
from __future__ import annotations

import math
import re

SOURCE = "ISO 286-1:2010 Annex A formulas; ISO 286-2:2010 tables"

MAIN = (0, 3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500)      # step bounds (mm); the first step is 0-3
# intermediate steps used by the r..u deviations above 50 mm (and t, u from 18 mm)
INTER = (0, 3, 6, 10, 14, 18, 24, 30, 40, 50, 65, 80, 100, 120, 140, 160, 180)

K = {5: 7, 6: 10, 7: 16, 8: 25, 9: 40, 10: 64, 11: 100, 12: 160, 13: 250, 14: 400, 15: 640, 16: 1000, 17: 1600,
     18: 2500}

# Annex A rounding: (upper bound of the computed value in µm, rounding step in µm)
ROUND_IT = ((60, 1), (100, 1), (200, 5), (500, 10), (1000, 20), (2000, 50), (5000, 100), (10000, 200),
            (20000, 500), (50000, 1000))
ROUND_DEV = ((45, 1), (60, 2), (100, 5), (200, 5), (300, 10), (560, 10), (600, 20), (800, 20), (1000, 50))

# Cells where the published table is not the formula rounded. Key (what, grade or letter, step's upper bound in mm).
PUBLISHED: dict[tuple, int] = {
    # the 0-3 mm step is tabulated outright
    **{("IT", g, 3): v for g, v in {5: 4, 6: 6, 7: 10, 8: 14, 9: 25, 10: 40, 11: 60, 12: 100, 13: 140, 14: 250,
                                     15: 400, 16: 600, 17: 1000, 18: 1400}.items()},
    ("dev", "d", 3): -20, ("dev", "e", 3): -14, ("dev", "f", 3): -6, ("dev", "g", 3): -2, ("dev", "k", 3): 0,
    ("dev", "m", 3): 2, ("dev", "n", 3): 4, ("dev", "p", 3): 6, ("dev", "r", 3): 10, ("dev", "s", 3): 14,
    ("dev", "u", 3): 18,
    # IT cells that keep the older rounding
    ("IT", 6, 6): 8, ("IT", 9, 6): 30, ("IT", 10, 6): 48, ("IT", 11, 6): 75, ("IT", 7, 10): 15, ("IT", 10, 10): 58,
    ("IT", 7, 18): 18, ("IT", 10, 18): 70, ("IT", 11, 50): 160, ("IT", 11, 80): 190, ("IT", 6, 400): 36,
    ("IT", 11, 400): 360, ("IT", 6, 500): 40, ("IT", 7, 500): 63, ("IT", 11, 500): 400,
    # deviation cells
    ("dev", "d", 10): -40, ("dev", "e", 120): -72, ("dev", "e", 400): -125, ("dev", "f", 400): -62,
    ("dev", "f", 500): -68, ("dev", "n", 120): 23,
    # p and s up to 50 mm: the formula gives a range (IT7 + 0 to 5, IT8 + 1 to 4); the table picks the value
    **{("dev", "p", hi): v for hi, v in ((6, 12), (10, 15), (18, 18), (30, 22), (50, 26), (80, 32),
                                         (120, 37), (180, 43), (250, 50), (315, 56), (400, 62), (500, 68))},
    **{("dev", "s", hi): v for hi, v in ((6, 19), (10, 23), (14, 28), (18, 28), (24, 35), (30, 35), (40, 43),
                                         (50, 43))},
    ("dev", "r", 14): 23, ("dev", "r", 18): 23, ("dev", "r", 160): 65,
    ("dev", "t", 30): 41, ("dev", "t", 40): 48, ("dev", "t", 50): 54, ("dev", "u", 24): 41,
}

SHAFT_UPPER = ("d", "e", "f", "g", "h")           # these letters give es (upper deviation, <= 0)
SHAFT_LOWER = ("k", "m", "n", "p", "r", "s", "t", "u")
LETTERS = SHAFT_UPPER + ("js",) + SHAFT_LOWER
INTER_LETTERS = ("r", "s", "t", "u")
STARTS = {"t": 24}                                 # t is defined from 24 mm


class FitError(ValueError):
    """A size, grade or class the tables here do not cover, with what to do instead."""


def _rnd(x: float, table) -> int:
    s = abs(x)
    for hi, step in table:
        if s <= hi:
            v = step * math.floor(s / step + 0.5)
            return int(math.copysign(v, x)) if v else 0
    raise FitError(f"{x:g} µm is beyond the rounding table")


def _step(d: float, bounds=MAIN) -> tuple[float, float]:
    if not (0 < d <= bounds[-1]):
        raise FitError(f"ISO 286 here covers nominal sizes above 0 up to {bounds[-1]} mm (got {d:g} mm)")
    for lo, hi in zip(bounds, bounds[1:]):
        if d <= hi:
            return lo, hi
    raise FitError(f"no step for {d:g} mm")


def _gm(lo: float, hi: float) -> float:
    return math.sqrt((lo or 1) * hi)


def it_formula(grade: int, d: float) -> float:
    """The unrounded IT value in µm from the formula, for the size step that holds d."""
    if grade not in K:
        raise FitError(f"IT{grade} is not computed here (IT5 to IT18 are)")
    D = _gm(*_step(d))
    return K[grade] * (0.45 * D ** (1 / 3) + 0.001 * D)


def it(grade: int, d: float) -> dict:
    """Standard tolerance ITgrade for nominal size d: {"um", "formula_um", "how": "formula" | "table", "step"}."""
    lo, hi = _step(d)
    raw = it_formula(grade, d)
    pub = PUBLISHED.get(("IT", grade, hi))
    return {"um": pub if pub is not None else _rnd(raw, ROUND_IT), "formula_um": round(raw, 3),
            "how": "table" if pub is not None else "formula", "step": (lo, hi)}


def _it(grade: int, d: float) -> int:
    return it(grade, d)["um"]


def _dev_formula(letter: str, d: float, grade: int) -> float:
    lo, hi = _step(d, INTER if letter in INTER_LETTERS else MAIN)
    D = _gm(lo, hi)
    if letter == "d":
        return -16 * D ** 0.44
    if letter == "e":
        return -11 * D ** 0.41
    if letter == "f":
        return -5.5 * D ** 0.41
    if letter == "g":
        return -2.5 * D ** 0.34
    if letter == "h":
        return 0.0
    if letter == "k":
        return 0.6 * D ** (1 / 3) if 4 <= grade <= 7 else 0.0
    if letter == "m":
        return _it(7, d) - _it(6, d)
    if letter == "n":
        return 5 * D ** 0.34
    if letter == "p":
        return _it(7, d) + 0.0                                    # IT7 + 0 to 5: the table picks within the range
    if letter == "s":
        return _it(8, d) + 1 if d <= 50 else _it(7, d) + 0.4 * D
    if letter == "r":
        return math.sqrt(_dev_um("p", d, grade) * _dev_um("s", d, grade))
    if letter == "t":
        return _it(7, d) + 0.63 * D
    if letter == "u":
        return _it(7, d) + D
    raise FitError(f"shaft deviation {letter!r} is not computed here (use one of {', '.join(LETTERS)})")


def _dev_um(letter: str, d: float, grade: int) -> int:
    if letter in INTER_LETTERS and d > 180:
        raise FitError(f"{letter} deviations are verified here up to 180 mm (got {d:g} mm)")
    if d <= STARTS.get(letter, 0):
        raise FitError(f"ISO 286 defines {letter} from {STARTS[letter]} mm")
    lo, hi = _step(d, INTER if letter in INTER_LETTERS else MAIN)
    if letter == "k" and not (4 <= grade <= 7):
        return 0
    pub = PUBLISHED.get(("dev", letter, hi))
    if pub is not None:
        return pub
    return _rnd(_dev_formula(letter, d, grade), ROUND_DEV)


def deviation(letter: str, d: float, grade: int = 7) -> dict:
    """The fundamental deviation of a shaft letter (µm): es for d..h, ei for k..u, with how it was obtained."""
    if letter not in LETTERS or letter == "js":
        raise FitError(f"shaft deviation {letter!r} is not computed here (use one of {', '.join(LETTERS)})")
    lo, hi = _step(d, INTER if letter in INTER_LETTERS else MAIN)
    um = _dev_um(letter, d, grade)
    how = "table" if ("dev", letter, hi) in PUBLISHED else "formula"
    try:
        raw = round(_dev_formula(letter, d, grade), 3)
    except FitError:
        raw = None
    return {"um": um, "formula_um": raw, "how": how, "which": "es" if letter in SHAFT_UPPER else "ei"}


_CLASS = re.compile(r"\s*([A-Za-z]{1,2})\s*(\d{1,2})\s*")


def parse(cls: str) -> tuple[str, int]:
    m = _CLASS.fullmatch(cls or "")
    if not m:
        raise FitError(f"not an ISO 286 tolerance class: {cls!r} (write it like H7 or g6)")
    return m.group(1), int(m.group(2))


def limits(cls: str, d: float) -> dict:
    """Limits of one tolerance class at nominal size d. Holes are upper case (H7), shafts lower case (g6).

    Returns upper and lower deviations in µm, the limit sizes in mm, the IT value, and "how" for each number."""
    letter, grade = parse(cls)
    d = float(d)
    t = it(grade, d)
    T = t["um"]
    hole = letter.isupper()
    low = letter.lower()
    hows = [t["how"]]
    if low == "js":
        up, lo_ = T / 2, -T / 2
    elif not hole:
        dv = deviation(low, d, grade)
        hows.append(dv["how"])
        if dv["which"] == "es":
            up, lo_ = dv["um"], dv["um"] - T
        else:
            up, lo_ = dv["um"] + T, dv["um"]
    else:
        if low in SHAFT_UPPER:                       # D..H: EI = -es
            dv = deviation(low, d, grade)
            hows.append(dv["how"])
            lo_ = -dv["um"]
            up = lo_ + T
        elif low in SHAFT_LOWER:                     # K..U: ES = -ei (+ delta)
            dv = deviation(low, d, grade)
            hows.append(dv["how"])
            delta = 0
            if (low in ("k", "m", "n") and grade <= 8) or (low not in ("k", "m", "n") and grade <= 7):
                if d > 3:
                    delta = T - _it(grade - 1, d)
            if low == "k" and grade > 8:
                es = 0
            elif low == "n" and grade > 8 and d > 3:
                es = 0
            else:
                ei_shaft = dv["um"] if not (low == "k" and not 4 <= grade <= 7) else _k_any(d)
                es = -ei_shaft + delta
            up, lo_ = es, es - T
        else:
            raise FitError(f"hole deviation {letter!r} is not computed here")
    up_mm, lo_mm = up / 1000.0, lo_ / 1000.0
    return {"class": f"{letter}{grade}", "nominal": d, "upper_um": _clean(up), "lower_um": _clean(lo_),
            "min": round(d + lo_mm, 4), "max": round(d + up_mm, 4), "it_um": T, "kind": "hole" if hole else "shaft",
            "how": "table" if "table" in hows else "formula", "source": SOURCE}


def _k_any(d: float) -> int:
    """ei of k at grades 4-7 (the K hole's ES uses it at every grade up to 8)."""
    return _dev_um("k", d, 6)


def _clean(x: float):
    return int(x) if float(x).is_integer() else round(x, 1)


def fit(code: str, d: float) -> dict:
    """A hole/shaft fit like "H7/g6" at nominal size d: both limits, clearance range (mm, negative = interference)
    and kind (clearance, transition, interference)."""
    m = re.fullmatch(r"\s*([A-Z]{1,2}\d{1,2})\s*/\s*([a-z]{1,2}\d{1,2})\s*", code or "")
    if not m:
        raise FitError(f"not an ISO fit: {code!r} (write it like H7/g6)")
    h, s = limits(m.group(1), d), limits(m.group(2), d)
    cmin, cmax = round(h["min"] - s["max"], 4), round(h["max"] - s["min"], 4)
    kind = "clearance" if cmin >= 0 else "interference" if cmax <= 0 else "transition"
    return {"code": f"{m.group(1)}/{m.group(2)}", "nominal": float(d), "hole": h, "shaft": s,
            "clearance": (cmin, cmax), "kind": kind, "source": SOURCE}


def callout(cls: str, d: float, diameter: bool = True) -> str:
    """How the size is written on a drawing: "Ø25 H7 (+0.021/0)"."""
    lim = limits(cls, d)
    sym = "Ø" if diameter else ""
    return f"{sym}{d:g} {lim['class']} ({_signed(lim['upper_um'])}/{_signed(lim['lower_um'])})"


def _signed(um) -> str:
    if um == 0:
        return "0"
    return f"{um / 1000:+.3f}".rstrip("0").rstrip(".") if abs(um) % 1 else f"{um / 1000:+.3f}"
