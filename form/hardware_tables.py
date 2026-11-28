"""Published fastener dimensions, with no CAD kernel behind them: ISO 273 clearance holes, ISO 261 coarse pitches, screw
heads, nuts and heat-set inserts. form/parts.py (geometry) and form/calc/fasteners.py (sizing from loads) read the same
tables here.
"""
from __future__ import annotations

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
