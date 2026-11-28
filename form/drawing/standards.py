"""Sheet sizes, scales, line types, projection methods and general tolerances: the drawing standards as data.

Sources: ISO 5457 (sheet sizes, borders), ASME Y14.1 (ANSI A-E), ISO 5455 (scales), ISO 128-2 (line types and
widths), ISO 5456-2 (first and third angle projection), ISO 7200 (title block fields), ISO 2768-1 (general linear
and angular tolerances), ISO 2768-2 (general geometric tolerances). Values are the standards' published tables.
"""
from __future__ import annotations

# ISO 5457 trimmed sizes, landscape (mm); ASME Y14.1 inch sizes converted exactly (1 in = 25.4 mm)
SHEETS = {
    "A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0), "A0": (1189.0, 841.0),
    "ANSI A": (279.4, 215.9), "ANSI B": (431.8, 279.4), "ANSI C": (558.8, 431.8), "ANSI D": (863.6, 558.8),
    "ANSI E": (1117.6, 863.6),
}
# ISO 5457: drawing frame 20 mm from the left edge (filing margin) and 10 mm elsewhere (A4 to A0)
FRAME_ISO = {"left": 20.0, "right": 10.0, "top": 10.0, "bottom": 10.0}
FRAME_ANSI = {"left": 12.7, "right": 12.7, "top": 12.7, "bottom": 12.7}

# ISO 5455 recommended scales, as (drawing, real): enlargement, full size, reduction
SCALES = ((50, 1), (20, 1), (10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 50), (1, 100),
          (1, 200), (1, 500), (1, 1000))

# ISO 128-2 line widths (mm) in the 0.35 group: wide for visible edges, narrow for the rest
LINES = {"visible": 0.35, "hidden": 0.18, "center": 0.18, "dimension": 0.18, "hatch": 0.18, "section": 0.5,
         "frame": 0.5, "thin": 0.18, "text": 0.25}
DASH = {"hidden": (3.0, 1.5), "center": (12.0, 1.5, 1.5, 1.5), "section": (12.0, 1.5, 1.5, 1.5)}
TEXT_H = {"dimension": 3.5, "note": 2.5, "title": 7.0, "label": 5.0, "small": 2.5}       # ISO 3098 heights, mm

PROJECTIONS = ("first", "third")

TITLE_FIELDS = (  # ISO 7200 data fields: mandatory ones first
    ("owner", "Legal owner"), ("number", "Identification number"), ("title", "Title"),
    ("approved", "Approval person"), ("creator", "Creator"), ("type", "Document type"), ("revision", "Revision"),
    ("date", "Date of issue"), ("sheet", "Sheet"), ("language", "Language"), ("material", "Material"),
    ("mass", "Mass"), ("scale", "Scale"), ("projection", "Projection"), ("tolerance", "General tolerance"),
    ("release", "Release hash"),
)

# ISO 2768-1 linear tolerances, +- mm, by class; size bands (over, up to) in mm
LINEAR_BANDS = ((0.5, 3), (3, 6), (6, 30), (30, 120), (120, 400), (400, 1000), (1000, 2000), (2000, 4000))
LINEAR = {
    "f": (0.05, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, None),
    "m": (0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0),
    "c": (0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0, 4.0),
    "v": (None, 0.5, 1.0, 1.5, 2.5, 4.0, 6.0, 8.0),
}
# radii and chamfer heights
BREAK_BANDS = ((0.5, 3), (3, 6), (6, 1e9))
BREAK = {"f": (0.2, 0.5, 1.0), "m": (0.2, 0.5, 1.0), "c": (0.4, 1.0, 2.0), "v": (0.4, 1.0, 2.0)}
# angular, by the length of the shorter side (mm): +- degrees
ANGLE_BANDS = ((0, 10), (10, 50), (50, 120), (120, 400), (400, 1e9))
ANGLE = {"f": (1.0, 0.5, 1 / 3, 1 / 6, 1 / 12), "m": (1.0, 0.5, 1 / 3, 1 / 6, 1 / 12),
         "c": (1.5, 1.0, 0.5, 0.25, 1 / 6), "v": (3.0, 2.0, 1.0, 0.5, 1 / 3)}
# ISO 2768-2 straightness and flatness, by nominal length bands
GEOM_BANDS = ((0, 10), (10, 30), (30, 100), (100, 300), (300, 1000), (1000, 3000))
FLATNESS = {"H": (0.02, 0.05, 0.1, 0.2, 0.3, 0.4), "K": (0.05, 0.1, 0.2, 0.4, 0.6, 0.8),
            "L": (0.1, 0.2, 0.4, 0.8, 1.2, 1.6)}


class StandardError(ValueError):
    pass


def _band(x: float, bands) -> int:
    for i, (lo, hi) in enumerate(bands):
        if lo < x <= hi or (i == 0 and x == lo == 0):
            return i
    raise StandardError(f"{x:g} mm is outside the ISO 2768 table ({bands[0][0]} to {bands[-1][1]} mm)")


def general_linear(size: float, cls: str = "m") -> float:
    """ISO 2768-1 permissible deviation (+- mm) of a linear size without its own tolerance."""
    if cls not in LINEAR:
        raise StandardError(f"ISO 2768-1 classes are f, m, c, v (got {cls!r})")
    if size < 0.5:
        raise StandardError("ISO 2768-1 does not cover sizes below 0.5 mm: give the size its own tolerance")
    v = LINEAR[cls][_band(size, LINEAR_BANDS)]
    if v is None:
        raise StandardError(f"ISO 2768-1 class {cls} has no value for {size:g} mm")
    return v


def general_break(size: float, cls: str = "m") -> float:
    """ISO 2768-1 deviation (+- mm) of a radius or chamfer height."""
    if size < 0.5:
        raise StandardError("ISO 2768-1 does not cover radii below 0.5 mm")
    return BREAK[cls][_band(size, BREAK_BANDS)]


def general_angle(shorter_side: float, cls: str = "m") -> float:
    return ANGLE[cls][_band(max(shorter_side, 0.0), ANGLE_BANDS)]


def general_flatness(length: float, cls: str = "K") -> float:
    return FLATNESS[cls][_band(length, GEOM_BANDS)]


def tolerance_note(cls: str = "m", geom: str = "K") -> str:
    return f"ISO 2768-{cls}{geom}"


def scale_text(scale: tuple) -> str:
    return f"{scale[0]}:{scale[1]}"


def pick_scale(need: float) -> tuple:
    """The largest ISO 5455 scale not above `need` (drawing size / real size)."""
    for a, b in SCALES:
        if a / b <= need + 1e-9:
            return (a, b)
    return SCALES[-1]
