"""Engineering materials for parts that are not printed: metals, woods and engineering plastics.

Densities, typical property ranges and a look for each material, from bd_materials (gumyr's materials catalogue for
build123d, Apache-2.0; colours and metalness for metals from physicallybased.info, CC0). Used for the mass of standard
hardware (form.parts: screws, nuts, washers, bearings, sprockets, pipes), the BOM, and for designs whose purpose is a
model made in metal or wood (CNC, casting)::

    from form import material_library as ml
    ml.get("aluminum")          # {"id", "name", "category", "density_kg_m3", "color", "finish", "properties", "source"}
    ml.mass_g(12_000, "brass")  # grams of 12 cm3 of brass
    ml.zone("brass", ["insert"])  # an appearance() zone: {"features", "finish": "metal", "color": "#..."}

Filament for printing is a different list (form/materials.py: PLA, PETG, ...), with the print properties the checks
use. Values here are typical figures, not a datasheet for a specific grade: `properties` keeps bd_materials' ranges
(min, max) so nothing pretends to be one number. Without bd_materials the common materials still work from a small
fallback table with the same densities (marked in "source").
"""
from __future__ import annotations

import functools
import math

SOURCE = "bd_materials (typical values)"
FALLBACK_SOURCE = "Form Studio fallback table (typical values; bd_materials 0.2 densities where it has the material)"

# id: (name, category, density kg/m3, display colour, finish). The colours are what a render shows by default; a
# design may give its own. Densities are the bd_materials 0.2 values for the same grades.
FALLBACK = {
    "mild_steel": ("Mild steel", "metal", 7800, "#e2dfdc", "metal"),
    "alloy_steel": ("Alloy steel (4140)", "metal", 7850, "#e2dfdc", "metal"),
    "stainless": ("Stainless steel (304)", "metal", 7930, "#edeae5", "metal"),
    "aluminum": ("Aluminium (6061-T6)", "metal", 2700, "#f9f9f9", "metal"),
    "brass": ("Brass (C360)", "metal", 8500, "#f8f2d9", "metal"),
    "bronze": ("Phosphor bronze (C51000)", "metal", 8800, "#ecdac3", "metal"),
    "copper": ("Copper (C110)", "metal", 8900, "#fae9e1", "metal"),
    "titanium": ("Titanium (grade 5)", "metal", 4430, "#dbd5cf", "metal"),
    "pom": ("Acetal (POM)", "plastic", 1410, "#f1efe9", "matte"),
    "nylon": ("Nylon (PA12)", "plastic", 1010, "#efeadc", "matte"),
    "ptfe": ("PTFE", "plastic", 2170, "#f4f4f2", "matte"),
    "pvc": ("PVC (rigid)", "plastic", 1400, "#e4e6e8", "matte"),
    "rubber": ("Rubber", "plastic", 1200, "#202224", "rubber"),
    "oak": ("Oak", "wood", 755, "#b98b5b", "matte"),
    "walnut": ("Walnut", "wood", 640, "#6b4a33", "matte"),
    "mdf": ("MDF", "wood", 750, "#b59a77", "matte"),
}
ALIASES = {"steel": "mild_steel", "aluminium": "aluminum", "alu": "aluminum", "stainless_steel": "stainless",
           "ss304": "stainless", "acetal": "pom", "delrin": "pom", "pa": "nylon", "teflon": "ptfe"}
# default display colours by category when the catalogue gives no tint (plastics are white in bd_materials: the
# colour is the part's choice) or the look is a texture (woods)
_CATEGORY_COLOR = {"plastic": "#e9e5dc", "resin": "#d9d4c8", "wood": "#b98b5b", "glass": "#d4e4ec", "paper": "#c9b38f",
                   "textile": "#6b6f75", "metal": "#d8d8d8"}


def _key(name: str) -> str:
    k = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return ALIASES.get(k, k)


def _hex(rgb_linear) -> str:
    """physicallybased.info colours are linear RGB; the display hex is sRGB."""
    def enc(c):
        c = min(max(float(c), 0.0), 1.0)
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return "#" + "".join(f"{round(enc(c) * 255):02x}" for c in rgb_linear[:3])


def available() -> bool:
    try:
        import bd_materials  # noqa: F401
        return True
    except Exception:                       # noqa: BLE001 - missing, or broken on import: the built-in table serves
        return False


def _finish(category: str, family: str) -> str:
    fam = (family or "").lower()
    if category == "metal":
        return "metal"
    if "rubber" in fam or "tpu" in fam or "flexible" in fam:
        return "rubber"
    if "cfrp" in fam or "carbon" in fam:
        return "carbon"
    if category == "glass" or fam in ("pmma",):
        return "smoke"
    return "matte"


@functools.lru_cache(maxsize=256)
def get(name: str) -> dict:
    """One material by name (bd_materials names and aliases: "aluminum", "alu_g7075_t6", "brass", "oak", "pom"...).

    Raises KeyError naming close matches when the name is unknown."""
    k = _key(name)
    try:
        hit = _from_bd_materials(k)
    except Exception:                       # noqa: BLE001 - a broken install never fails a lookup the table can answer
        hit = None
    if hit is not None:
        return hit
    if k in FALLBACK:
        nm, cat, rho, col, fin = FALLBACK[k]
        return {"id": k, "name": nm, "category": cat, "family": k, "density_kg_m3": float(rho), "color": col,
                "finish": fin, "properties": {}, "source": FALLBACK_SOURCE, "look": "fallback colour"}
    near = [n for n in names() if k[:3] and n.startswith(k[:3])][:6]
    raise KeyError(f"Unknown material “{name}”" + (f"; did you mean {', '.join(near)}?" if near else "") +
                   " (form.material_library.names() lists them).")


def _from_bd_materials(k: str) -> dict | None:
    """One material from bd_materials, or None when it is not installed or does not know the name."""
    try:
        from bd_materials import resolve
    except ImportError:
        return None
    try:
        fm = resolve(k)
    except (ValueError, TypeError, KeyError, LookupError):
        return None
    if fm is None:
        return None
    m = fm.material
    color, finish = _CATEGORY_COLOR.get(m.category, "#d8d8d8"), _finish(m.category, m.family)
    look = "category default colour"
    try:
        p = fm.pbr                      # values only; texture maps are never loaded
        has_maps = any(v for v in vars(p.maps).values()) if p.maps else False
        if m.category == "metal" and p.values.color and not has_maps:
            color, look = _hex(p.values.color), f"{p.source} ({p.license})"
    except Exception:                   # the look is decoration: a missing PBR module never fails a lookup
        pass
    if look == "category default colour" and k in FALLBACK:
        color, look = FALLBACK[k][3], "Form Studio display colour"
    props = {}
    for f, v in vars(m).items():
        if hasattr(v, "min") and hasattr(v, "max") and not (math.isnan(v.min) or math.isnan(v.max)):
            props[f] = [float(v.min), float(v.max)]
    return {"id": k, "name": m.name, "category": m.category, "family": m.family,
            "density_kg_m3": float(m.density), "color": color, "finish": finish, "properties": props,
            "source": SOURCE, "look": look}


def names() -> list[str]:
    try:
        from bd_materials import material_names
        return sorted(set(material_names()) | set(FALLBACK) | set(ALIASES))
    except Exception:                       # noqa: BLE001 - missing or broken: the built-in table's names
        return sorted(set(FALLBACK) | set(ALIASES))


def density_g_mm3(name: str) -> float:
    return get(name)["density_kg_m3"] * 1e-6          # 1 kg/m3 = 1e-6 g/mm3


def mass_g(volume_mm3: float, name: str) -> float:
    """Mass of a solid of this volume (mm3) in this material, in grams (computed: volume x typical density)."""
    return round(float(volume_mm3) * density_g_mm3(name), 3)


def zone(name: str, features: list, color: str | None = None, label: str | None = None) -> dict:
    """An appearance() zone for these features in this material: its finish and display colour."""
    m = get(name)
    return {"features": list(features), "finish": m["finish"], "color": color or m["color"], "label": label or m["name"]}


def catalogue() -> list[dict]:
    """The common engineering materials, for listings (the full catalogue is names())."""
    out = []
    for k in FALLBACK:
        try:
            m = get(k)
        except KeyError:
            continue
        out.append({x: m[x] for x in ("id", "name", "category", "density_kg_m3", "color", "finish", "source")})
    return out


# ── Sourced engineering properties (form/material_data.py) ──────────────────────────────────────────────────────
# The one source the mass properties (form/massprops.py), the strength studies and the manufacturability rules read.
# Keys are the stored material keys of form/materials.py: the filaments (PLA, PETG, ...) and the engineering materials
# (AL-6061, STAINLESS, OAK, POM, ...). Every value names its document, URL, the line it was read from and the date.

EVIDENCE_SPECIFIED = "specified (datasheet)"
EVIDENCE_TYPICAL = "typical (bd_materials catalogue, no per-value citation)"
EVIDENCE_MODELLED = "modelled"
UNSOURCED = "unsourced"
PROPERTY_UNITS = {"density": "kg/m3", "E": "GPa", "E_xy": "GPa", "E_z": "GPa", "poisson": "", "yield": "MPa",
                  "uts": "MPa", "uts_xy": "MPa", "uts_z": "MPa", "elongation": "%", "elongation_xy": "%",
                  "elongation_z": "%", "flex_mod_xy": "GPa", "flex_mod_z": "GPa", "flex_str_xy": "MPa",
                  "flex_str_z": "MPa", "cte": "1/K", "k": "W/(m·K)", "hdt_045": "°C", "hdt_18": "°C", "vicat": "°C",
                  "sg_12": "", "moe": "GPa", "mor": "MPa"}
# the in-plane value a direction-free name means for a printed part (E -> E_xy); the Z value is across the layers
_PRINTED = {"E": "E_xy", "uts": "uts_xy", "elongation": "elongation_xy"}


def _data() -> dict:
    from .material_data import DATA
    return DATA


def _store_key(key) -> str:
    from . import materials
    k = materials._key(key)
    if k is None:
        raise KeyError(f"Unknown material “{key}”. {materials.known()}")
    return k


def properties(key) -> dict:
    """Every sourced property of a stored material key: {prop: {value, unit, [min, max, spread], condition, source,
    url, quote, retrieved, evidence}}. Empty when nothing is sourced for it."""
    from .material_data import RETRIEVED
    m = _data().get(_store_key(key))
    if not m:
        return {}
    return {k: {**v, "retrieved": RETRIEVED, "evidence": EVIDENCE_SPECIFIED} for k, v in m["properties"].items()}


def prop(key, name: str, direction: str = "") -> dict:
    """One property: the sourced record, or {"status": "unsourced"} (never a default). For a printed filament,
    direction "xy" (in the layers, the default) or "z" (across them) picks E/uts/elongation; "E" means E_xy."""
    props = properties(key)
    n = name
    if name in _PRINTED and name not in props:
        n = (name + "_z") if direction == "z" else _PRINTED[name]
    if n in props:
        return {"name": n, **props[n]}
    return {"name": n, "status": UNSOURCED, "unit": PROPERTY_UNITS.get(n, ""),
            "note": f"No source in Form Studio's library gives {n} for {key}; it is left out rather than assumed."}


def knockdown_z(key) -> dict:
    """For a printed filament: the ratio of each Z (across the layers) value to its X-Y value, from the same
    datasheet. Labelled modelled: these are the datasheet's specimens, not this part."""
    props, out = properties(key), {}
    for base in ("E", "uts", "elongation", "flex_mod", "flex_str"):
        a, b = props.get(base + "_xy"), props.get(base + "_z")
        if a and b and a.get("value") and b.get("value") is not None:
            out[base] = {"ratio": round(b["value"] / a["value"], 3), "xy": a["value"], "z": b["value"], "unit": a["unit"],
                         "evidence": EVIDENCE_MODELLED, "source": a["source"],
                         "note": "Z / X-Y of the datasheet's printed specimens (100 % infill); a part's infill, walls "
                                 "and print settings change it."}
    return out


def density(key) -> dict:
    """Density of a stored material key, kg/m3, with where it comes from: the sourced datasheet value, else (an
    engineering material) bd_materials' typical value, said so. Raises KeyError for an unknown material."""
    from . import materials
    k = _store_key(key)
    p = properties(k).get("density")
    if p and p.get("value"):
        return {"value": float(p["value"]), "source": p["source"], "url": p["url"], "retrieved": p["retrieved"],
                "evidence": EVIDENCE_SPECIFIED, "condition": p.get("condition", "")}
    if k in materials.ENGINEERING_SPEC:
        m = get(materials.ENGINEERING_SPEC[k][0])
        return {"value": float(m["density_kg_m3"]), "source": m["source"], "url": None, "retrieved": None,
                "evidence": EVIDENCE_TYPICAL if m["source"] == SOURCE else "typical (Form Studio fallback table)"}
    info = materials.info(k)
    return {"value": float(info["density_g_cm3"]) * 1000.0, "source": "Form Studio filament table", "url": None,
            "retrieved": None, "evidence": UNSOURCED}


def record(key) -> dict:
    """The full library entry of a stored material key: label, kind, grade, density (with its source), every sourced
    property, a filament's Z knock-down, and which of the properties the studies read are unsourced."""
    from . import materials
    k = _store_key(key)
    info = materials.info(k) or {}
    m = _data().get(k) or {}
    props = properties(k)
    wanted = ["density", "E", "poisson", "yield", "uts", "cte"]
    if info.get("kind") == "filament":
        wanted = ["density", "E_xy", "E_z", "poisson", "uts_xy", "uts_z", "hdt_045"]
    elif info.get("category") == "wood":
        wanted = ["sg_12", "moe", "mor"]
    out = {"id": k, "label": info.get("label", k), "kind": info.get("kind"), "category": info.get("category", "plastic"),
           "grade": m.get("grade", ""), "density": density(k), "properties": props,
           "unsourced": [w for w in wanted if w not in props]}
    if info.get("kind") == "filament":
        out["knockdown_z"] = knockdown_z(k)
        out["note"] = ("Printed-specimen values from one manufacturer's datasheet; a part's infill, walls, layer "
                       "height and print temperature change them. Not simulated per part.")
    elif info.get("category") == "wood":
        out["note"] = "Wood is anisotropic: MOE and MOR are along the grain in bending, at 12 % moisture."
    return out


def library() -> list:
    """Every material a design can be given, as record() entries (filaments first)."""
    from . import materials
    return [record(k) for k in list(materials.MATERIALS) + list(materials.engineering())]
