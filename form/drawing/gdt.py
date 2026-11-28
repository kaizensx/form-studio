"""Geometric tolerances (ISO 1101 / ASME Y14.5), datums (ISO 5459) and surface texture (ISO 21920-1 / ISO 1302).

Only what the design or the person states is drawn: a frame is a declaration, checked here for what the standard
requires (flatness takes no datum, perpendicularity needs one, a value is positive), never guessed.

    gdt.frame({"type": "position", "value": 0.1, "diameter": True, "modifier": "M", "datums": ["A", "B"]})
    gdt.validate(spec) -> list of problems (empty when the frame is well formed)

Symbols are drawn as lines and arcs in the frame's own cells (no font glyphs), so every renderer shows them alike.
"""
from __future__ import annotations

import math

from . import scene as S

# characteristic: (ISO 1101 group, datum rule: "none" | "required" | "optional", OCCT XCAF type name, ASME name)
CHARACTERISTICS = {
    "straightness": ("form", "none", "Straightness"),
    "flatness": ("form", "none", "Flatness"),
    "circularity": ("form", "none", "CircularityOrRoundness"),
    "cylindricity": ("form", "none", "Cylindricity"),
    "profile_line": ("profile", "optional", "ProfileOfLine"),
    "profile_surface": ("profile", "optional", "ProfileOfSurface"),
    "parallelism": ("orientation", "required", "Parallelism"),
    "perpendicularity": ("orientation", "required", "Perpendicularity"),
    "angularity": ("orientation", "required", "Angularity"),
    "position": ("location", "optional", "Position"),
    "concentricity": ("location", "required", "Concentricity"),
    "coaxiality": ("location", "required", "Coaxiality"),
    "symmetry": ("location", "required", "Symmetry"),
    "circular_runout": ("runout", "required", "CircularRunout"),
    "total_runout": ("runout", "required", "TotalRunout"),
}
MODIFIERS = {"M": "maximum material", "L": "least material", "E": "envelope", "F": "free state",
             "P": "projected tolerance zone", "T": "tangent plane", "U": "unequal profile"}
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"            # ISO 5459: I, O and Q are not used as datum letters


def validate(spec: dict) -> list[str]:
    """What is wrong with a frame declaration, in words. Empty when it is well formed."""
    out = []
    t = spec.get("type")
    if t not in CHARACTERISTICS:
        return [f"unknown characteristic {t!r}; use one of {', '.join(CHARACTERISTICS)}"]
    try:
        v = float(spec.get("value"))
        if not v > 0:
            out.append("the tolerance value must be positive")
    except (TypeError, ValueError):
        out.append("the tolerance value must be a number in mm")
    rule = CHARACTERISTICS[t][1]
    ds = list(spec.get("datums") or [])
    if rule == "none" and ds:
        out.append(f"{t} is a form tolerance and takes no datum (ISO 1101)")
    if rule == "required" and not ds:
        out.append(f"{t} needs at least one datum (ISO 1101)")
    if len(ds) > 3:
        out.append("a frame refers to at most three datums (primary, secondary, tertiary)")
    for d in ds:
        letter = str(d).rstrip("MLP")
        if not letter or any(c not in LETTERS for c in letter):
            out.append(f"datum {d!r} is not a datum letter (A-Z without I, O, Q)")
    if spec.get("diameter") and t not in ("position", "concentricity", "coaxiality", "perpendicularity",
                                           "parallelism", "angularity", "straightness"):
        out.append(f"a cylindrical zone (Ø) does not apply to {t}")
    if spec.get("modifier") and spec["modifier"] not in MODIFIERS:
        out.append(f"unknown modifier {spec['modifier']!r}; use one of {', '.join(MODIFIERS)}")
    return out


def text(spec: dict) -> str:
    """A frame in one line, for tables and checks: "position | Ø0.1 Ⓜ | A | B"."""
    v = f"{'Ø' if spec.get('diameter') else ''}{float(spec['value']):g}"
    if spec.get("modifier"):
        v += f" ({spec['modifier']})"
    return " | ".join([spec["type"], v, *[str(d) for d in spec.get("datums") or []]])


# ── symbols, drawn in a square cell of side s centred at c ─────────────────

def _symbol(t: str, c, s: float, layer="gdt") -> list:
    x, y = c
    h = s * 0.32
    out = []
    if t == "straightness":
        out.append(S.line((x - h, y), (x + h, y), layer))
    elif t == "flatness":
        k = h * 0.35
        out.append(S.polyline([(x - h + k, y + k), (x + h + k, y + k), (x + h - k, y - k), (x - h - k, y - k)],
                              layer, closed=True))
    elif t == "circularity":
        out.append(S.circle((x, y), h * 0.9, layer))
    elif t == "cylindricity":
        out.append(S.circle((x, y), h * 0.7, layer))
        out += [S.line((x - h * 0.5, y - h), (x + h * 0.1, y + h), layer),
                S.line((x - h * 0.1, y - h), (x + h * 0.5, y + h), layer)]
    elif t == "profile_line":
        out.append(S.arc((x, y - h * 0.4), h, 0, 180, layer))
    elif t == "profile_surface":
        out.append(S.arc((x, y - h * 0.4), h, 0, 180, layer))
        out.append(S.line((x - h, y - h * 0.4), (x + h, y - h * 0.4), layer))
    elif t == "parallelism":
        out += [S.line((x - h * 0.6, y - h), (x - h * 0.1, y + h), layer),
                S.line((x + h * 0.1, y - h), (x + h * 0.6, y + h), layer)]
    elif t == "perpendicularity":
        out += [S.line((x - h, y - h * 0.8), (x + h, y - h * 0.8), layer), S.line((x, y - h * 0.8), (x, y + h), layer)]
    elif t == "angularity":
        out += [S.line((x - h, y - h * 0.8), (x + h, y - h * 0.8), layer),
                S.line((x - h, y - h * 0.8), (x + h * 0.7, y + h), layer)]
    elif t == "position":
        out += [S.circle((x, y), h * 0.62, layer), S.line((x - h, y), (x + h, y), layer),
                S.line((x, y - h), (x, y + h), layer)]
    elif t in ("concentricity", "coaxiality"):
        out += [S.circle((x, y), h * 0.45, layer), S.circle((x, y), h * 0.9, layer)]
    elif t == "symmetry":
        out += [S.line((x - h, y), (x + h, y), layer), S.line((x - h * 0.6, y + h * 0.5), (x + h * 0.6, y + h * 0.5), layer),
                S.line((x - h * 0.6, y - h * 0.5), (x + h * 0.6, y - h * 0.5), layer)]
    elif t == "circular_runout":
        out += [S.line((x - h * 0.5, y - h), (x + h * 0.5, y + h), layer)] + _arrowhead((x + h * 0.5, y + h), (x - h * 0.5, y - h), h, layer)
    elif t == "total_runout":
        out += [S.line((x - h * 0.7, y - h), (x + h * 0.2, y + h), layer), S.line((x - h * 0.2, y - h), (x + h * 0.7, y + h), layer),
                S.line((x - h * 0.9, y - h), (x + h * 0.3, y - h), layer)]
        out += _arrowhead((x + h * 0.2, y + h), (x - h * 0.7, y - h), h, layer)
        out += _arrowhead((x + h * 0.7, y + h), (x - h * 0.2, y - h), h, layer)
    return out


def _arrowhead(tip, frm, h, layer):
    return [S.arrow(tip, frm, size=h * 0.6, layer=layer)]


def _modifier(m: str, c, h: float, layer="gdt") -> list:
    """A circled letter (Ⓜ, Ⓛ, ...) drawn as a circle and its letter."""
    return [S.circle(c, h * 0.72, layer), S.text((c[0], c[1]), m, h * 0.9, "middle", "middle", layer=layer)]


def frame(spec: dict, at, h: float = 3.5, gid: str = "", meta=None) -> dict:
    """A feature control frame with its lower left corner at `at`: symbol cell, tolerance cell, datum cells."""
    problems = validate(spec)
    if problems:
        raise ValueError("; ".join(problems))
    s = h * 2.0                                         # cell height: twice the text height (ISO 1101)
    x, y = at
    kids = []
    cells = [s]
    tol = f"{'Ø' if spec.get('diameter') else ''}{float(spec['value']):g}"
    tw = S.text_width(tol, h) + h * 1.2 + (h * 1.8 if spec.get("modifier") else 0.0)
    cells.append(max(s, tw))
    ds = [str(d) for d in spec.get("datums") or []]
    cells += [max(s, S.text_width(d, h) + h * 1.2) for d in ds]
    width = sum(cells)
    kids.append(S.polyline([(x, y), (x + width, y), (x + width, y + s), (x, y + s)], "gdt", closed=True))
    cx = x
    for w in cells[:-1]:
        cx += w
        kids.append(S.line((cx, y), (cx, y + s), "gdt"))
    kids += _symbol(spec["type"], (x + s / 2, y + s / 2), s)
    tx = x + cells[0] + h * 0.6
    kids.append(S.text((tx, y + s / 2), tol, h, "start", "middle", layer="gdt"))
    if spec.get("modifier"):
        kids += _modifier(spec["modifier"], (tx + S.text_width(tol, h) + h * 1.0, y + s / 2), h)
    cx = x + cells[0] + cells[1]
    for d, w in zip(ds, cells[2:]):
        kids.append(S.text((cx + w / 2, y + s / 2), d, h, "middle", "middle", layer="gdt"))
        cx += w
    return S.group("gdt", kids, gid, {**(meta or {}), "spec": spec, "text": text(spec)})


def datum_feature(letter: str, foot, direction, h: float = 3.5, gid: str = "", meta=None, lead: float | None = None) -> dict:
    """A datum feature symbol: a filled triangle on the feature at `foot`, a leader along `direction`, a boxed
    letter (ISO 5459)."""
    if letter not in LETTERS:
        raise ValueError(f"datum {letter!r} is not a datum letter (A-Z without I, O, Q)")
    dx, dy = direction
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    t = h * 0.9
    base = (foot[0] + ux * t, foot[1] + uy * t)
    tri = S.polygon([(foot[0] - uy * t * 0.6, foot[1] + ux * t * 0.6), (foot[0] + uy * t * 0.6, foot[1] - ux * t * 0.6),
                     base], "gdt")
    L = h * 1.6 if lead is None else lead
    end = (base[0] + ux * L, base[1] + uy * L)
    s = h * 2.0
    cx, cy = end[0] + ux * s / 2, end[1] + uy * s / 2
    box = S.polyline([(cx - s / 2, cy - s / 2), (cx + s / 2, cy - s / 2), (cx + s / 2, cy + s / 2), (cx - s / 2, cy + s / 2)],
                     "gdt", closed=True)
    return S.group("datum", [tri, S.line(base, end, "gdt"), box, S.text((cx, cy), letter, h, "middle", "middle", layer="gdt")],
                   gid, {**(meta or {}), "letter": letter})


# ── surface texture (ISO 21920-1, formerly ISO 1302) ───────────────────────

PROCESS = {"any": "any process permitted", "removal": "material removal required", "no_removal": "material removal prohibited"}
LAY = {"=": "parallel", "⊥": "perpendicular", "X": "crossed", "M": "multidirectional", "C": "circular", "R": "radial",
       "P": "particulate"}
RA_SERIES = (0.012, 0.025, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.3, 12.5, 25.0, 50.0)   # ISO 1302 preferred Ra, µm


def surface_problems(spec: dict) -> list[str]:
    out = []
    if spec.get("process", "removal") not in PROCESS:
        out.append(f"process must be one of {', '.join(PROCESS)}")
    try:
        if not float(spec.get("ra")) > 0:
            out.append("Ra must be positive (µm)")
    except (TypeError, ValueError):
        out.append("Ra must be a number in µm")
    if spec.get("lay") and spec["lay"] not in LAY:
        out.append(f"lay must be one of {', '.join(LAY)}")
    return out


def surface_symbol(spec: dict, foot, h: float = 3.5, gid: str = "", meta=None) -> dict:
    """The surface texture symbol standing on `foot`: the 60 degree check mark, a bar for required material removal
    or a circle where removal is prohibited, the requirement above the long leg ("Ra 1.6")."""
    p = surface_problems(spec)
    if p:
        raise ValueError("; ".join(p))
    x, y = foot
    a = h * 1.4                                        # short leg height (ISO 21920-1: 1.4 h)
    left = (x - a / math.tan(math.radians(60)), y + a)
    long_top = (x + 2 * a / math.tan(math.radians(60)), y + 2 * a)
    kids = [S.line(left, (x, y), "dimension"), S.line((x, y), long_top, "dimension")]
    proc = spec.get("process", "removal")
    if proc == "removal":
        kids.append(S.line(left, (left[0] + (long_top[0] - x) * 0.5 + (x - left[0]), y + a), "dimension"))
    elif proc == "no_removal":
        kids.append(S.circle((x + a * 0.08, y + a * 0.42), a * 0.36, "dimension"))
    bar_end = (long_top[0] + S.text_width(f"Ra {float(spec['ra']):g}", h) + h * 0.5, long_top[1])
    kids.append(S.line(long_top, bar_end, "dimension"))
    kids.append(S.text((long_top[0] + h * 0.3, long_top[1] - h * 1.35), f"Ra {float(spec['ra']):g}", h, "start",
                       layer="dimension"))
    if spec.get("lay"):
        kids.append(S.text((x + a * 0.9, y + a * 0.1), spec["lay"], h * 0.8, "start", layer="dimension"))
    return S.group("surface", kids, gid, {**(meta or {}), "spec": spec})
