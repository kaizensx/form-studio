"""Sourced values the print-physics tools need that the filament datasheets of form/material_data.py do not give.

A filament's entry in form/material_data.py is one manufacturer's product, and those datasheets state no thermal
expansion, no glass transition and no Poisson's ratio. The values here are for the same polymer family from another
document: a paper that measured printed specimens, or the resin maker's datasheet. Each says which, in `basis`:

    printed specimen     measured on FDM-printed specimens of that polymer (another product than the datasheet's)
    resin datasheet      the bulk moulded resin of that polymer family, not a filament and not printed

So they are sourced, and they are not the grade's own numbers: a result that uses one says so. Each record has the
value, the unit, the document, its URL, the table line it was read from (`quote`) and the day it was read. A value no
document gave is absent, and the tools then ask for it instead of assuming it.

    get("PLA", "cte")  ->  {"value": 9.6e-05, "unit": "1/K", "basis": "printed specimen", "source": ..., ...} | None
"""
from __future__ import annotations

RETRIEVED = "2026-11-28"

_FBG = {"source": "Matsika-Klossa, Chatzidai, Kousiatza and Karalekas (2024), Characterization of Thermal Expansion "
                  "Coefficient of 3D Printing Polymeric Materials Using Fiber Bragg Grating Sensors, Materials 17(18):4668, "
                  "Table 2",
        "url": "https://doi.org/10.3390/ma17184668", "basis": "printed specimen"}
_FBG_HOW = "FDM specimen, 0.2 mm layers, 100 % infill, fibre Bragg grating embedded in the mid-plane"
_CANTRELL = {"source": "Cantrell, Rohde, Damiani, Gurnani, DiSandro, Anton, Young, Jerez, Steinbach, Kroese and Ifju, "
                       "Experimental Characterization of the Mechanical Properties of 3D-Printed ABS and Polycarbonate "
                       "Parts (author manuscript; Rapid Prototyping Journal, 2017)",
             "url": "https://web.mae.ufl.edu/rapidpro/pages/3D%20Printing%20Paper%20Final%20Manuscript.pdf",
             "basis": "printed specimen"}
_EASTAR = {"source": "Eastman Chemical Company, Eastar Copolyester 6763, product data sheet",
           "url": "https://plastore.it/cgi2018/file818/1649_pet%20eastar%206763.pdf", "basis": "resin datasheet"}
_LURAN = {"source": "INEOS Styrolution, Luran S 777K (ASA), technical datasheet",
          "url": "https://plastore.it/cgi2018/file818/717_asa%20luran%20s%20777k.pdf", "basis": "resin datasheet"}
_MAKROLON = {"source": "Bayer MaterialScience, Makrolon 2805 (PC), ISO datasheet",
             "url": "https://upmold.com/wp-content/uploads/data-sheet/PC-markrolon-2805.pdf", "basis": "resin datasheet"}
_FERREIRA = {"source": "Ferreira, Amatte, Dutra and Burger (2017), Experimental characterization and micrography of 3D "
                       "printed PLA and PLA reinforced with short carbon fibers, Composites Part B: Engineering 124, "
                       "Table 4 (preprint)",
             "url": "https://www.nakka-rocketry.net/Articles/0paperPLAcf_R3_RG.pdf", "basis": "printed specimen"}

DATA = {
    "PLA": {
        "cte": {**_FBG, "value": 96e-6, "unit": "1/K", "spread": 5e-6, "max": 99e-6,
                "condition": f"{_FBG_HOW}; raster along the specimen, 25 to 50 C (across it: 99 +/- 5, 25 to 30 C)",
                "quote": "PLA | 0° | 25–50 | 96 ± 5 | 100 [18] | 62 ± 2 | 57 [33]"},
        "tg": {**_FBG, "value": 62.0, "unit": "°C", "spread": 2.0,
               "condition": f"{_FBG_HOW}; the knee of the grating's wavelength against temperature, raster along the specimen",
               "quote": "PLA | 0° | 25–50 | 96 ± 5 | 100 [18] | 62 ± 2 | 57 [33]"},
        "poisson": {**_FERREIRA, "value": 0.331, "unit": "", "spread": 0.011,
                    "condition": "ASTM D638, rectilinear 100 % infill, lines along the load (nu12); across them nu21 = 0.325",
                    "quote": "Poisson Coefficient | ν12 | 0.349 | 0.331 | 0.011 | 0.408 | 0.400 | 0.012 | D638"},
        "shear_modulus": {**_FERREIRA, "value": 1092.0, "unit": "MPa", "spread": 36.0,
                          "source": _FERREIRA["source"].replace("Table 4", "Table 3"),
                          "condition": "ASTM D3518, +/-45 deg rectilinear 100 % infill: shear in the plane of the layers, "
                                       "not between them",
                          "quote": "In-plane Shear Modulus (MPa) | ± 45° (G12) | 1140 | 1092 | 36 | 1270 | 1268 | 5 | D3518"},
    },
    "ABS": {
        "cte": {**_FBG, "value": 86e-6, "unit": "1/K", "spread": 3e-6, "max": 89e-6,
                "condition": f"{_FBG_HOW}; raster along the specimen, 25 to 50 C (across it: 89 +/- 3)",
                "quote": "ABS | 0° | 25–50 | 86 ± 3 | 90 [18], 102 [23] | 92 ± 2 | 107 [33]"},
        "tg": {**_FBG, "value": 92.0, "unit": "°C", "spread": 2.0,
               "condition": f"{_FBG_HOW}; the knee of the grating's wavelength against temperature",
               "quote": "ABS | 0° | 25–50 | 86 ± 3 | 90 [18], 102 [23] | 92 ± 2 | 107 [33]"},
        "poisson": {**_CANTRELL, "value": 0.36, "unit": "", "spread": 0.03, "min": 0.36, "max": 0.38,
                    "condition": "ASTM D638 with digital image correlation; six build orientations and rasters, 0.36 to 0.38",
                    "quote": "Poisson’s Ratio | 0.36 ± 0.03 | 0.37 ± 0.04 | 0.38 ± 0.03 | 0.36 ± 0.02 | 0.36 ± 0.03 | 0.36 ± 0.03"},
    },
    "PA": {
        "cte": {**_FBG, "value": 118e-6, "unit": "1/K", "spread": 5e-6, "max": 119e-6,
                "condition": f"{_FBG_HOW}; Taulman Bridge nylon, raster along the specimen, 25 to 40 C (across it: 119 +/- 5)",
                "quote": "PA | 0° | 25–40 | 118 ± 5 | 126 [18] | 52 ± 2 | 50–55 [32]"},
        "tg": {**_FBG, "value": 52.0, "unit": "°C", "spread": 2.0,
               "condition": f"{_FBG_HOW}; Taulman Bridge nylon; the knee of the grating's wavelength against temperature",
               "quote": "PA | 0° | 25–40 | 118 ± 5 | 126 [18] | 52 ± 2 | 50–55 [32]"},
    },
    "PETG": {
        "cte": {**_EASTAR, "value": 51e-6, "unit": "1/K", "condition": "ASTM D 696, -30 to 40 C; moulded PETG copolyester",
                "quote": "Coefficient of Linear Thermal Expansion | D 696 | 5.1 × 10-5 /°C (mm/mm·°C)"},
        "tg": {**_EASTAR, "value": 80.0, "unit": "°C", "condition": "DSC; PETG copolyester resin",
               "quote": "Glass Transition Temperature (Tg) | DSC | 80°C (176°F)"},
    },
    "ASA": {
        "cte": {**_LURAN, "value": 95e-6, "unit": "1/K", "min": 80e-6, "max": 110e-6,
                "condition": "ISO 11359; the datasheet gives a range, 80 to 110: the value here is its middle",
                "quote": "Coefficient of Linear Thermal Expansion | ISO 11359 | 10-6/°C | 80 - 110"},
    },
    "PC": {
        "cte": {**_MAKROLON, "value": 65e-6, "unit": "1/K", "condition": "ISO 11359-1,-2, 23 to 55 C, in units of 1e-4/K, the same along and across the flow",
                "quote": "Coefficient of linear thermal expansion, parallel | 23 to 55 °C | ISO 11359-1,-2 | 0.65"},
        "tg": {**_MAKROLON, "value": 145.0, "unit": "°C", "condition": "ISO 11357-1,-2, 10 C/min; moulded resin",
               "quote": "Glass transition temperature | 10 °C/min | °C | ISO 11357-1,-2 | 145"},
        "poisson": {**_CANTRELL, "value": 0.34, "unit": "", "min": 0.29, "max": 0.39,
                    "condition": "ASTM D638 with digital image correlation; eight build orientations and rasters gave 0.29 "
                                 "to 0.39: the value here is the middle of that range",
                    "quote": "Poisson’s Ratio | 0.39 ± 0.03 | 0.36 ± 0.02 | 0.33 ± 0.02 | 0.29 ± 0.02"},
    },
}
NOT_THE_GRADE = ("From another document than the filament's own datasheet (which does not state it): the same polymer "
                 "family, another product.")


def get(key, name: str) -> dict | None:
    """One value for a stored material key ("PLA", "PETG", ...), or None when no document gives it."""
    from .. import materials
    k = materials._key(key) if key else None
    rec = (DATA.get(k) or {}).get(name)
    if rec is None:
        return None
    return {"name": name, **rec, "retrieved": RETRIEVED, "evidence": f"specified ({rec['basis']}, not this filament's own datasheet)",
            "note": NOT_THE_GRADE}


def table() -> list:
    """Every record, for docs and listings."""
    return [{"material": m, **get(m, n)} for m, props in DATA.items() for n in props]
