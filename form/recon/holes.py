"""Standard hole sizes, for naming a hole measured on a mesh. Plain data.

A measured diameter is snapped to the nearest standard size within the snap distance and the record says what it
was measured as, what it was snapped to and why: "computed from mesh" is the provenance, never "measured".
"""
from __future__ import annotations

# ISO 273 clearance holes (fine / normal / coarse) and common ISO tap-drill sizes, mm
CLEARANCE = {
    "M1.6": (1.7, 1.8, 2.0), "M2": (2.2, 2.4, 2.6), "M2.5": (2.7, 2.9, 3.1), "M3": (3.2, 3.4, 3.6),
    "M4": (4.3, 4.5, 4.8), "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0), "M8": (8.4, 9.0, 10.0),
    "M10": (10.5, 11.0, 12.0), "M12": (13.0, 13.5, 14.5), "M16": (17.0, 17.5, 18.5), "M20": (21.0, 22.0, 24.0),
    "M24": (25.0, 26.0, 28.0),
}
TAP = {"M2": 1.6, "M2.5": 2.05, "M3": 2.5, "M4": 3.3, "M5": 4.2, "M6": 5.0, "M8": 6.8, "M10": 8.5, "M12": 10.2,
       "M16": 14.0, "M20": 17.5, "M24": 21.0}


def standard_sizes() -> list[tuple[float, str]]:
    out = []
    for m, (f, n, c) in CLEARANCE.items():
        out += [(f, f"{m} clearance, fine (ISO 273)"), (n, f"{m} clearance, normal (ISO 273)"), (c, f"{m} clearance, coarse (ISO 273)")]
    out += [(d, f"{m} tap drill") for m, d in TAP.items()]
    return out


def snap(d: float, within: float) -> dict:
    """The standard size nearest to d within `within` mm, else a whole or half millimetre drill, else d itself."""
    rec = {"measured_mm": round(d, 4), "provenance": "computed from mesh"}
    best = min(standard_sizes(), key=lambda t: abs(t[0] - d))
    half = round(d * 2) / 2
    tenth = round(d * 10) / 10
    if abs(half - d) <= within and (abs(half - d) <= abs(best[0] - d) or abs(best[0] - d) > within):
        rec.update({"diameter_mm": half, "standard": f"Ø{half:g} mm drill"})
        # a size that is both a drill and a named hole keeps the name
        if abs(best[0] - half) < 1e-9:
            rec["standard"] = best[1]
    elif abs(best[0] - d) <= within:
        rec.update({"diameter_mm": best[0], "standard": best[1]})
    elif abs(tenth - d) <= within:
        rec.update({"diameter_mm": tenth, "standard": f"Ø{tenth:g} mm (0.1 mm drill series)"})
    else:
        rec.update({"diameter_mm": round(d, 3), "standard": None})
    rec["snapped_by_mm"] = round(rec["diameter_mm"] - d, 4)
    return rec
