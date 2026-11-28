"""The material numbers a strength study uses, each with where it comes from.

    resolve("AL-6061")                                   # from the materials library, every value with its document
    resolve({"key": "PLA", "poisson": 0.35})             # the library's values, one given by the caller (assumed)
    resolve({"name": "my steel", "E_GPa": 200, "poisson": 0.29, "yield_MPa": 355, "density_kg_m3": 7850,
             "source": "EN 10025-2 S355JR, mill certificate"})

The library is form/material_library.py's sourced properties (`prop(key, name)` and `density(key)`: E in GPa,
Poisson's ratio, yield and ultimate strength in MPa, each with its source, URL and the line it was read from). Nothing
here holds a material value of its own, and nothing is defaulted: a mechanical study needs E and Poisson's ratio, a
heat study the thermal conductivity k (W/(m K)), a thermal-stress study all three and the expansion coefficient
(1/K); each stops with the name of the missing one when no source gives it. Without a yield strength the study still runs and gives stress
and displacement, but no safety factor.

A printed filament is taken as a solid isotropic part with its in-plane stiffness (E X-Y). Its strength is the weakest
sourced direction, the ultimate strength across the layers (Z) when the datasheet has it; the datasheet's Z / X-Y
ratio is named in the result as the knock-down applied. Layers, infill and walls are not simulated.
"""
from __future__ import annotations

SPECIFIED = "specified (given with the study)"
ASSUMED = "assumed (given with the study, no source named)"
_GIVEN = {"E_GPa": ("E", 1000.0), "E_MPa": ("E", 1.0), "poisson": ("nu", 1.0), "nu": ("nu", 1.0),
          "yield_MPa": ("yield", 1.0), "density_kg_m3": ("density", 1.0), "k_W_mK": ("k", 1.0), "cte_per_K": ("cte", 1.0)}
_WORDS = {"E": "Young's modulus (E)", "poisson": "Poisson's ratio", "k": "the thermal conductivity (k)",
          "cte": "the thermal expansion coefficient"}
_KEY_OF = {"E": "E_GPa", "poisson": "poisson", "k": "k_W_mK", "cte": "cte_per_K"}
MECHANICAL = ("E", "poisson")


def _err(msg: str, hint: str = ""):
    from ..studio import StudioError
    return StudioError(msg, hint)


def library_ready() -> bool:
    """Whether the materials library has sourced mechanical properties (its prop() and density())."""
    from .. import material_library as ml
    return callable(getattr(ml, "prop", None)) and callable(getattr(ml, "density", None))


def _from_library(key: str) -> dict:
    from .. import material_library as ml
    if not library_ready():
        raise _err("This build's materials library has no sourced mechanical properties, so a material cannot be "
                   "looked up by name.",
                   "Give the values with the study: material={\"name\": ..., \"E_GPa\": ..., \"poisson\": ..., "
                   "\"yield_MPa\": ..., \"density_kg_m3\": ..., \"source\": \"where they are from\"}.")
    try:
        rec = ml.record(key) if callable(getattr(ml, "record", None)) else {}
    except KeyError as e:
        raise _err(str(e).strip("'\""), "set_appearance lists the materials a design can be given.") from None
    out = {"key": rec.get("id", key), "name": rec.get("label") or str(key), "kind": rec.get("kind"), "sources": {},
           "notes": [], "missing": []}
    filament = rec.get("kind") == "filament"

    def take(dst, name, scale=1.0, direction=""):
        try:
            p = ml.prop(key, name, direction) if direction else ml.prop(key, name)
        except KeyError as e:
            raise _err(str(e).strip("'\"")) from None
        if not p or p.get("status") == "unsourced" or p.get("value") is None:
            return False
        out[dst] = float(p["value"]) * scale
        out["sources"][dst] = {k: p.get(k) for k in ("name", "value", "unit", "source", "url", "condition", "retrieved",
                                                     "evidence", "spread") if p.get(k) is not None}
        return True
    if not take("E", "E", 1000.0):                       # GPa in the library
        out["missing"].append("E")
    if not take("nu", "poisson"):
        out["missing"].append("poisson")
    for dst in ("k", "cte"):                             # W/(m K) and 1/K in the library
        if not take(dst, dst):
            out["missing"].append(dst)
    try:
        d = ml.density(key)
        if d and d.get("value"):
            out["density"] = float(d["value"])
            out["sources"]["density"] = {k: d.get(k) for k in ("value", "source", "url", "retrieved", "evidence") if d.get(k) is not None}
            out["sources"]["density"]["unit"] = "kg/m3"
    except KeyError:
        pass
    if take("yield", "yield"):
        out["strength_basis"] = "yield strength"
    elif filament and take("yield", "uts", 1.0, "z"):
        out["strength_basis"] = "ultimate tensile strength across the layers (Z), the weakest sourced direction"
        kd = (ml.knockdown_z(key) if callable(getattr(ml, "knockdown_z", None)) else {}).get("uts")
        if kd:
            out["knockdown"] = {"what": "Z / X-Y ultimate strength of the datasheet's printed specimens", **kd}
        out["notes"].append("No yield strength is sourced for this filament: the safety factor is against its ultimate "
                            "strength across the layers, so it is a factor against breaking, not against yielding.")
    elif take("yield", "uts"):
        out["strength_basis"] = "ultimate tensile strength (no yield strength is sourced)"
        out["notes"].append("No yield strength is sourced: the safety factor is against the ultimate strength, so it "
                            "is a factor against breaking, not against yielding.")
    else:
        out["missing"].append("yield")
    if filament:
        out["notes"].append("Printed part: solved as a solid isotropic part with the in-plane (X-Y) modulus of the "
                            "datasheet's 100 % infill specimens. Layers, infill, walls and print settings are not "
                            "simulated.")
    if rec.get("category") == "wood":
        out["notes"].append("Wood is anisotropic; an isotropic study with along-the-grain values overstates it across "
                            "the grain.")
    return out


def resolve(material, need: tuple = MECHANICAL) -> dict:
    """{"name", "key", "E" (MPa), "nu", "density" (kg/m3) | None, "yield" (MPa) | None, "k" (W/(m K)) | None, "cte"
    (1/K) | None, "strength_basis", "sources": {value name: {value, unit, source, url, evidence}}, "notes": [...],
    "knockdown": {...}?}. need: the values this study cannot run without ("E", "poisson", "k", "cte"). Raises
    StudioError naming what is missing."""
    if material is None or material == "":
        raise _err("A strength study needs a material.",
                   "Give material=\"AL-6061\" (a key of the materials library) or the values with their source.")
    given = {}
    if isinstance(material, dict):
        given = {k: v for k, v in material.items() if v is not None}
        key = given.get("key") or given.get("material")
    else:
        key = str(material)
    out = _from_library(key) if key else {"key": None, "name": str(given.get("name") or "custom material"),
                                          "kind": "custom", "sources": {}, "notes": [],
                                          "missing": ["E", "poisson", "yield", "k", "cte"]}
    src = str(given.get("source") or "").strip()
    for k, (dst, scale) in _GIVEN.items():
        if k not in given:
            continue
        try:
            v = float(given[k]) * scale
        except (TypeError, ValueError):
            raise _err(f"{k} is a number.") from None
        out[dst] = v
        out["sources"][dst] = {"value": float(given[k]), "unit": {"E_GPa": "GPa", "E_MPa": "MPa", "yield_MPa": "MPa",
                                                                   "density_kg_m3": "kg/m3", "k_W_mK": "W/(m K)",
                                                                   "cte_per_K": "1/K"}.get(k, ""),
                               "source": src or None, "evidence": SPECIFIED if src else ASSUMED}
        if dst == "yield":
            out["strength_basis"] = "yield strength"
        miss = {"E": "E", "nu": "poisson", "yield": "yield", "k": "k", "cte": "cte"}.get(dst)
        if miss in out["missing"]:
            out["missing"].remove(miss)
    if given.get("name"):
        out["name"] = str(given["name"])
    lack = [m for m in out["missing"] if m in need]
    if lack:
        what = " and ".join(_WORDS[m] for m in lack)
        raise _err(f"No source gives {what} for {out['name']}, and this study cannot run without it. Nothing is assumed.",
                   "Give it with the study, with where it is from: material={\"key\": \"" + str(out.get("key") or "...") +
                   "\", " + ", ".join(f"\"{_KEY_OF[m]}\": ..." for m in lack) + ", \"source\": \"...\"}.")
    if "E" in need and not out.get("E", 0) > 0:
        raise _err("Young's modulus must be positive.")
    for dst in ("k", "cte"):
        if out.get(dst) is not None and not out[dst] > 0:
            raise _err(f"{_WORDS[dst].capitalize()} must be positive.")
    if "poisson" in need and not -1.0 < out.get("nu", 0) < 0.5:
        raise _err(f"Poisson's ratio {out.get('nu')} is outside (-1, 0.5): the study's formulation needs a compressible "
                   "material.", "Rubber-like materials (0.5) need a different formulation and are not supported.")
    for dst in ("density", "yield", "k", "cte", "E", "nu"):
        out.setdefault(dst, None)
    if out["yield"] is None and "E" in need:
        out["notes"].append("No yield strength is sourced or given: the study reports stress and displacement, and no "
                            "safety factor.")
    out.pop("missing", None)
    return out


def engine_material(m: dict) -> dict:
    """What the solver needs of a resolved material."""
    return {"name": m["name"], "E": m["E"], "nu": m["nu"], "density": m.get("density"), "yield": m.get("yield"),
            "k": m.get("k"), "cte": m.get("cte")}
