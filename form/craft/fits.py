"""ISO 286 limits and fits: tolerance grades and fundamental deviations for the fits a designer actually uses.

    from form.craft import fits
    f = fits.iso_fit("H7/g6", 8)        # an 8 mm sliding fit
    f["hole"]      -> (8.000, 8.015) mm        f["shaft"] -> (7.986, 7.995) mm
    f["clearance"] -> (0.005, 0.029) mm        f["kind"]  -> "clearance"
    fits.bearing_fit("608", "shaft")     # k5 on a rotating shaft, with the reason

Tables (micrometres) are ISO 286-1/-2 for nominal sizes up to 500 mm: standard tolerance grades IT5-IT11, shaft
deviations e f g h js k m n p (s up to 50 mm), hole deviations E F G H JS. Values are "specified" (published
standard). They are machining tolerances: a 3D printer holds roughly +/-0.1-0.2 mm, i.e. IT12-IT14 at these sizes,
so for printed parts use Form Studio's fit model (fit clearance per side) and ream or press in a metal part where an
ISO fit is needed. iso_fit() says so in its "fdm_note".
"""
from __future__ import annotations

from ._common import fail, need, num

SOURCE = "ISO 286-1:2010 / ISO 286-2:2010 tables"
RANGES = (3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500)        # upper limits of the nominal size steps, mm

IT = {  # standard tolerance grades, um
    5: (4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27),
    6: (6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40),
    7: (10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63),
    8: (14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97),
    9: (25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155),
    10: (40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250),
    11: (60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400),
}

# shaft fundamental deviations, um: upper deviation es for e-h, lower deviation ei for k-s
SHAFT_ES = {
    "e": (-14, -20, -25, -32, -40, -50, -60, -72, -85, -100, -110, -125, -135),
    "f": (-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68),
    "g": (-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20),
    "h": (0,) * 13,
}
SHAFT_EI = {
    "k": (0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5),            # grades 4-7; other grades: 0
    "m": (2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23),
    "n": (4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40),
    "p": (6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68),
    "s": (14, 19, 23, 28, 35, 43),                            # up to 50 mm only (the table splits finer above)
}
HOLE_EI = {"E": "e", "F": "f", "G": "g", "H": "h"}            # EI = -es of the matching shaft letter

COMMON = {
    "H11/c11": "loose running (not tabulated here: use H9/e9)",
    "H9/e9": "loose running: large temperature changes, wide tolerances",
    "H8/f7": "free running: good for shafts in plain bearings at moderate speed",
    "H7/g6": "sliding: precise location, parts move freely by hand",
    "H7/h6": "locational clearance: snug, assembled by hand, no play to speak of",
    "H7/k6": "locational transition: light press or tap, accurate location",
    "H7/n6": "locational transition, tighter: press, firm location",
    "H7/p6": "locational interference: press fit, parts held without other locking",
    "H7/s6": "medium drive: shrink or heavy press, permanent",
}


def _step(d: float) -> int:
    for i, hi in enumerate(RANGES):
        if d <= hi:
            return i
    raise fail(f"ISO 286 tables here go up to 500 mm (got {d:g} mm)", "Use a nominal size up to 500 mm.", ["d"])


def _grade(g: int, i: int) -> float:
    need(g in IT, f"Tolerance grade IT{g} is not tabulated here", "Use IT5-IT11.", ["fit"])
    return IT[g][i] / 1000.0


def shaft_limits(letter: str, grade: int, d: float) -> tuple[float, float]:
    """(min, max) diameter in mm of a shaft of nominal size d, e.g. shaft_limits("g", 6, 8)."""
    d = num(d, "d", positive=True)
    i, t = _step(d), None
    t = _grade(grade, i)
    if letter == "js":
        return d - t / 2, d + t / 2
    if letter in SHAFT_ES:
        es = SHAFT_ES[letter][i] / 1000.0
        return d + es - t, d + es
    if letter in SHAFT_EI:
        row = SHAFT_EI[letter]
        need(i < len(row), f"Shaft {letter}{grade} above {RANGES[len(row) - 1]} mm is not tabulated here",
             "Use p6 or n6, or check ISO 286-2 directly.", ["fit"])
        ei = (row[i] if (letter != "k" or 4 <= grade <= 7) else 0) / 1000.0
        return d + ei, d + ei + t
    raise fail(f"Shaft deviation {letter!r} is not tabulated here", "Use e, f, g, h, js, k, m, n, p or s.", ["fit"])


def hole_limits(letter: str, grade: int, d: float) -> tuple[float, float]:
    """(min, max) diameter in mm of a hole of nominal size d, e.g. hole_limits("H", 7, 8)."""
    d = num(d, "d", positive=True)
    i = _step(d)
    t = _grade(grade, i)
    if letter == "JS":
        return d - t / 2, d + t / 2
    need(letter in HOLE_EI, f"Hole deviation {letter!r} is not tabulated here", "Use E, F, G, H or JS (H is the "
         "hole-basis standard).", ["fit"])
    ei = -SHAFT_ES[HOLE_EI[letter]][i] / 1000.0
    return d + ei, d + ei + t


def _parse(code: str):
    import re
    m = re.fullmatch(r"\s*([A-Z]{1,2})(\d{1,2})\s*/\s*([a-z]{1,2})(\d{1,2})\s*", code or "")
    need(m is not None, f"Not an ISO fit code: {code!r}", 'Write it like "H7/g6".', ["fit"])
    return m.group(1), int(m.group(2)), m.group(3), int(m.group(4))


def iso_fit(code: str, d: float) -> dict:
    """Limits of a hole/shaft pair, e.g. iso_fit("H7/p6", 10): hole and shaft (min, max) in mm, clearance (min, max)
    (negative = interference) and kind clearance | transition | interference."""
    hl, hg, sl, sg = _parse(code)
    h, s = hole_limits(hl, hg, d), shaft_limits(sl, sg, d)
    cmin, cmax = h[0] - s[1], h[1] - s[0]
    kind = "clearance" if cmin >= 0 else "interference" if cmax <= 0 else "transition"
    r = lambda x: round(x, 4)
    return {"code": code.replace(" ", ""), "nominal": d, "hole": (r(h[0]), r(h[1])), "shaft": (r(s[0]), r(s[1])),
            "clearance": (r(cmin), r(cmax)), "kind": kind, "use": COMMON.get(code.replace(" ", ""), ""),
            "provenance": "specified", "source": SOURCE,
            "fdm_note": "ISO 286 is a machining tolerance (microns). FDM holds about +/-0.15 mm: print the hole "
                        "undersize and ream it, or use the fit model's clearance per side for printed-to-printed fits."}


def bearing_fit(designation: str, where: str = "shaft", rotating: str = "inner") -> dict:
    """The usual ISO tolerance for a ball-bearing seat (rolling-bearing makers' general recommendation, normal loads):
    the ring that turns relative to the load is fitted tight, the other loose. where = "shaft" | "housing";
    rotating = "inner" | "outer". Returns the seat's tolerance class and its limits for the bearing's bore or OD."""
    from .. import parts
    need(where in ("shaft", "housing"), f"where must be shaft or housing (got {where!r})", "", ["where"])
    need(rotating in ("inner", "outer"), f"rotating must be inner or outer (got {rotating!r})", "", ["rotating"])
    b = parts.BEARINGS.get(str(designation))
    need(b is not None, f"Unknown bearing {designation!r}", "Known: " + ", ".join(parts.BEARINGS), ["designation"])
    bore, od = b[0], b[1]
    if where == "shaft":
        (letter, grade), why = ((("k", 5), "rotating inner ring: transition fit so the ring cannot creep") if rotating == "inner"
                                else (("g", 6), "stationary inner ring: sliding fit, the ring may creep"))
        lim = shaft_limits(letter, grade, bore)
        nominal = bore
    else:
        (letter, grade), why = ((("H", 7), "stationary outer ring: the ring can float axially") if rotating == "inner"
                                else (("H", 7), "rotating outer ring: N7 is usual; H7 shown (N is not tabulated here), "
                                      "add a retaining feature"))
        lim = hole_limits(letter, grade, od)
        nominal = od
    return {"designation": str(designation), "where": where, "tolerance": f"{letter}{grade}", "nominal": nominal,
            "limits": (round(lim[0], 4), round(lim[1], 4)), "why": why, "provenance": "heuristic",
            "source": "rolling-bearing makers' general fit recommendations (normal loads); limits from " + SOURCE}
