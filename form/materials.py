"""Materials: which filament a design (or each of its parts) is printed in, the slicer preset that matches it, and
what the material means for the checks.

Where the material is stated, nearest first:

    project["parts"][<part id>]["material"]   one printed part (part ids: the design's assembly parts, or
                                               "part1", "part2", ... for separate solids without an assembly)
    project["material"]                        the whole design
    Part(material=...) in the recipe's assembly()  what the design itself suggests
    otherwise                                  the filament selected for the printer (nothing is changed)

"color" sits beside "material" in the same places (a "#rrggbb" string) and is carried into the plate plan and the
release; Form Studio does not pick a filament by colour.

A stated material changes the slice only through the filament preset: among the filaments the printer's slicer
offers for that printer (form/printers.py options), the one whose name names that material, preferring the slicer's
generic preset. If the selected filament already is that material it stays. If the printer has none, the slice keeps
the selected filament and a check says so. Material notes in the checks are heuristics: typical values for the
material family, not a datasheet for a brand.
"""
from __future__ import annotations

import re
import time

# key -> properties of the material family. softens_c: about where a printed part starts to creep under load
# (glass transition / heat deflection of typical filaments); uv: how it stands up outdoors.
MATERIALS: dict[str, dict] = {
    "PLA": {"label": "PLA", "softens_c": 55, "uv": "poor", "flexible": False, "enclosure": False, "warp": "low"},
    "PLA-CF": {"label": "PLA-CF", "softens_c": 60, "uv": "poor", "flexible": False, "enclosure": False, "warp": "low",
               "abrasive": True},
    "PETG": {"label": "PETG", "softens_c": 75, "uv": "fair", "flexible": False, "enclosure": False, "warp": "low"},
    "PETG-CF": {"label": "PETG-CF", "softens_c": 78, "uv": "fair", "flexible": False, "enclosure": False, "warp": "low",
                "abrasive": True},
    "PCTG": {"label": "PCTG", "softens_c": 75, "uv": "fair", "flexible": False, "enclosure": False, "warp": "low"},
    "ABS": {"label": "ABS", "softens_c": 95, "uv": "poor", "flexible": False, "enclosure": True, "warp": "high"},
    "ASA": {"label": "ASA", "softens_c": 95, "uv": "good", "flexible": False, "enclosure": True, "warp": "high"},
    "PC": {"label": "PC", "softens_c": 115, "uv": "fair", "flexible": False, "enclosure": True, "warp": "high"},
    "PA": {"label": "Nylon (PA)", "softens_c": 80, "uv": "fair", "flexible": False, "enclosure": True, "warp": "high",
           "hygroscopic": True},
    "PA-CF": {"label": "PA-CF", "softens_c": 150, "uv": "fair", "flexible": False, "enclosure": True, "warp": "medium",
              "abrasive": True, "hygroscopic": True},
    "TPU": {"label": "TPU", "softens_c": 80, "uv": "fair", "flexible": True, "enclosure": False, "warp": "low"},
}
ALIASES = {"PLA+": "PLA", "PLA PLUS": "PLA", "PET-G": "PETG", "NYLON": "PA", "PA6": "PA", "PA12": "PA", "TPE": "TPU",
           "TPU95A": "TPU", "TPU 95A": "TPU", "TPU 90A": "TPU", "PLA CF": "PLA-CF", "PETG CF": "PETG-CF", "PA CF": "PA-CF",
           "PA6-CF": "PA-CF", "PAHT-CF": "PA-CF"}
# name tokens that count as the material in a filament preset's name ("Generic PETG @BBL A1M", "Bambu TPU 95A @BBL A1M")
TOKENS = {"PLA": {"PLA", "PLA+"}, "PLA-CF": {"PLA-CF"}, "PETG": {"PETG", "PET-G"}, "PETG-CF": {"PETG-CF"},
          "PCTG": {"PCTG"}, "ABS": {"ABS"}, "ASA": {"ASA"}, "PC": {"PC"}, "PA": {"PA", "PA6", "PA12", "NYLON"},
          "PA-CF": {"PA-CF", "PA6-CF", "PAHT-CF"}, "TPU": {"TPU", "TPE"}}
SKIP = re.compile(r"support|copy|calibrat|test|for ams|\bhf\b", re.I)     # never picked on our own
FIBRE = re.compile(r"\b(cf|gf)\b", re.I)
OUTDOOR = re.compile(r"\b(outdoors?|outside|garden|balcony|sun(light|ny)?|uv|car|dashboard|windscreen|windshield|"
                     r"weather|rain|patio|mailbox|letterbox)\b", re.I)
HOT = re.compile(r"\b(hot|heat|dishwasher|boiling|kettle|oven|engine|radiator|coffee machine|3d printer enclosure|"
                 r"hot ?end|near the nozzle)\b", re.I)


def normalise(name) -> str | None:
    """"petg" -> "PETG", "PLA+" -> "PLA", "Nylon" -> "PA"; None for anything not in MATERIALS."""
    if not isinstance(name, str) or not name.strip():
        return None
    s = re.sub(r"\s+", " ", name.strip().upper())
    s = ALIASES.get(s, s)
    return s if s in MATERIALS else None


def info(key: str) -> dict:
    return dict(MATERIALS[key], key=key)


def of_project(p: dict, parts: list | None = None) -> dict:
    """{"design": key | None, "color": hex | "", "parts": {id: {"material", "color", "source"}}} for a project.

    parts: the design's printed parts ([{"id", "material"?}], e.g. from the kernel's plate_parts or assembly view);
    each gets its material from project["parts"], then project["material"], then the recipe's own suggestion."""
    own = p.get("parts") if isinstance(p.get("parts"), dict) else {}
    design = normalise(p.get("material"))
    out = {"design": design, "color": str(p.get("color") or ""), "parts": {}, "unknown": []}
    if p.get("material") and not design:
        out["unknown"].append(str(p["material"]))
    for part in parts or []:
        pid = part["id"]
        mine = own.get(pid) if isinstance(own.get(pid), dict) else {}
        m = normalise(mine.get("material"))
        if mine.get("material") and not m:
            out["unknown"].append(str(mine["material"]))
        src = "part"
        if not m and design:
            m, src = design, "design"
        if not m and normalise(part.get("material")):
            m, src = normalise(part.get("material")), "recipe"
        out["parts"][pid] = {"material": m, "color": str(mine.get("color") or out["color"] or ""),
                             "source": src if m else ""}
    return out


def stated(p: dict) -> str | None:
    """The material stated for the whole design (project["material"]). Parts with their own material are sliced
    plate by plate (form/plates.py), never by promoting one part's material to the design."""
    return normalise(p.get("material")) if isinstance(p, dict) else None


def _tokens(name: str) -> set:
    return {t.upper() for t in re.split(r"[\s@()_/,]+", name or "") if t}


def names_material(name: str, key: str) -> bool:
    return bool(_tokens(name) & TOKENS.get(key, {key}))


def material_of_preset(name: str, filament_type: str = "") -> str | None:
    """The material a filament preset is: its filament_type when the slicer states one, else its name."""
    t = normalise(filament_type)
    if t:
        return t
    for key in sorted(TOKENS, key=lambda k: -len(k)):            # PLA-CF before PLA
        if names_material(name, key):
            return key
    return None


def rank(name: str, source: str, key: str) -> tuple | None:
    """How good a preset name is for this material (lower is better), or None if it is not that material."""
    if not names_material(name, key):
        return None
    if SKIP.search(name) or (FIBRE.search(name) and "CF" not in key):
        return None
    words = [w for w in _tokens(name) if not w.startswith("BBL") and w not in TOKENS.get(key, set())]
    generic = name.lower().startswith("generic ")
    return (source == "user", not generic, "BASIC" not in _tokens(name) and not generic, len(words), name.lower())


_cache: dict = {}


def pick_filament(cfg: dict, kind: str, machine: str, key: str) -> str | None:
    """The filament preset for `key` among those the slicer offers this printer, or None. Cached for a minute."""
    ck = (kind, machine, key)
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    from . import printers
    try:
        opts = printers.options(cfg, kind, machine)
    except Exception:                                            # no such printer, slicer gone: nothing to pick
        return None
    best = None
    for f in opts.get("filaments", []):
        r = rank(f["name"], f.get("source", "system"), key)
        if r is not None and (best is None or r < best[0]):
            best = (r, f["name"])
    name = best[1] if best else None
    _cache[ck] = (time.time(), name)
    return name


def choice_for(cfg: dict, base: dict, resolved: dict | None, key: str) -> tuple[dict, dict]:
    """(choice, note) that slices `key` on the printer of `base` ({kind, machine, process, filament}).

    note: {"material", "filament", "matched": bool, "changed": bool, "text"} for the person."""
    from . import slicer as slicer_mod
    label = MATERIALS[key]["label"]
    cur = base.get("filament") or ""
    cur_type = ""
    if resolved and resolved.get("available"):
        cur_type = (resolved.get("summary") or {}).get("filament_type") or ""
        cur = cur or resolved["presets"]["filament"]["name"]
    if cur and material_of_preset(cur, cur_type) == key:
        return base, {"material": key, "filament": cur, "matched": True, "changed": False,
                      "text": f"{cur} is {label}."}
    pick = pick_filament(cfg, base["kind"], base["machine"], key)
    if not pick:
        return base, {"material": key, "filament": cur, "matched": False, "changed": False,
                      "text": f"{slicer_mod.label(base['kind'])} offers no {label} filament for {base['machine']}; "
                              f"the slice uses {cur or 'the selected filament'}."}
    return dict(base, filament=pick), {"material": key, "filament": pick, "matched": True, "changed": True,
                                       "text": f"{pick}: the {label} preset for {base['machine']}"
                                               + (f" (instead of {cur})." if cur else ".")}


def base_choice(choice: dict | None, resolved: dict) -> dict | None:
    """The printer choice to change the filament of: the design's or default choice, else the slicer's selection."""
    if choice:
        return dict(choice)
    if not resolved.get("available"):
        return None
    pr = resolved["presets"]
    return {"kind": resolved.get("kind", "bambu"), "machine": pr["machine"]["name"], "process": pr["process"]["name"],
            "filament": pr["filament"]["name"]}


# ---- checks ---------------------------------------------------------------------------------------------------

def checks(by_part: dict, row: dict | None, brief: str = "", footprint=None, per_part: bool = False) -> list[dict]:
    """Heuristic notes for the materials in use. by_part: {label: material key}; row: the orientation-table row in use
    (steep_mm2, ceiling_mm2); footprint: [w, d] mm of the largest part on the plate."""
    used: dict = {}
    for label, key in by_part.items():
        if key:
            used.setdefault(key, []).append(label)
    out = []
    brief = brief or ""
    for key, labels in used.items():
        m = MATERIALS[key]
        who = "" if not per_part else (" (" + ", ".join(labels[:4]) + ("…" if len(labels) > 4 else "") + ")")
        notes, status = [], "PASS"
        if OUTDOOR.search(brief) and m["uv"] == "poor":
            status = "WARN"
            notes.append(f"The brief mentions use outdoors or in a car. {m['label']} softens from about {m['softens_c']} °C "
                         f"and {'yellows and turns brittle in sunlight' if key != 'ABS' else 'chalks and turns brittle in sunlight'}; "
                         "a car interior in sun exceeds 70 °C. ASA (or PETG) holds up better.")
        if HOT.search(brief) and m["softens_c"] < 90:
            status = "WARN"
            notes.append(f"The brief mentions heat. {m['label']} starts to creep under load from about {m['softens_c']} °C.")
        if m["flexible"] and row:
            steep, ceil = row.get("steep_mm2", 0), row.get("ceiling_mm2", 0)
            if steep >= 1 or ceil >= 1:
                status = "WARN"
                notes.append(f"Flexible {m['label']} sags more than rigid filament: {steep:.0f} mm² of overhang and {ceil:.0f} mm² of "
                             "flat ceiling here. Keep overhangs under about 35°, bridges short, and print slowly.")
            else:
                notes.append(f"Flexible {m['label']}: print slowly; there are no overhangs or bridges in this orientation.")
        if m["enclosure"]:
            big = footprint and max(footprint) >= 150
            if big:
                status = "WARN"
            notes.append(f"{m['label']} warps on a large footprint without an enclosure"
                         + (f": the largest part covers {footprint[0]:.0f} × {footprint[1]:.0f} mm." if big else
                            "; print it enclosed, with a brim on sharp corners."))
        if m.get("abrasive"):
            notes.append("Carbon or glass fibre wears a brass nozzle; use a hardened one.")
        if m.get("hygroscopic"):
            notes.append("Dry the spool before printing; nylon takes up water from the air within hours.")
        if not notes:
            notes.append(f"{m['label']}: softens from about {m['softens_c']} °C; "
                         + {"poor": "not for long sun exposure.", "fair": "fair outdoors.", "good": "good outdoors."}[m["uv"]])
        out.append({"id": f"material_{key.lower().replace('-', '_')}", "label": f"Material: {m['label']}{who}",
                    "status": status, "value": m["label"], "detail": " ".join(notes), "evidence": "heuristic"})
    return out
