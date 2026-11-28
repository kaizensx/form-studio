"""ISO 286 limits: standard tolerance grades and fundamental deviations, with no CAD kernel behind them.

The tables (micrometres) are ISO 286-1/-2 for nominal sizes up to 500 mm: grades IT5-IT11, shaft deviations e f g h js
k m n p (s up to 50 mm), hole deviations E F G H JS. form/craft/fits.py (designs) and form/calc/fits.py (the fit at
temperature calculator) both read them here, so there is one copy. Errors are Iso286Error(message, hint, params);
form.craft.fits turns them into a RecipeError.
"""
from __future__ import annotations


class Iso286Error(ValueError):
    def __init__(self, message: str, hint: str = "", params: list | None = None):
        super().__init__(message)
        self.hint = hint
        self.params = list(params or [])


def fail(message: str, hint: str = "", params=None) -> Iso286Error:
    return Iso286Error(message, hint, params)


def need(cond: bool, message: str, hint: str = "", params=None) -> None:
    if not cond:
        raise fail(message, hint, params)


def num(x, name: str, positive: bool = False) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise fail(f"{name} must be a number (got {x!r})", "", [name]) from None
    if v != v or v in (float("inf"), float("-inf")) or (positive and v <= 0):
        raise fail(f"{name} must be a positive number (got {x!r})", "", [name])
    return v


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


def parse(code: str):
    """("H", 7, "g", 6) from "H7/g6"."""
    import re
    m = re.fullmatch(r"\s*([A-Z]{1,2})(\d{1,2})\s*/\s*([a-z]{1,2})(\d{1,2})\s*", code or "")
    need(m is not None, f"Not an ISO fit code: {code!r}", 'Write it like "H7/g6".', ["fit"])
    return m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
