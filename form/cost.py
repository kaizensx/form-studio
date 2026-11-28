"""What a print would cost: filament, electricity, machine time. Every figure says how it is known.

- grams and hours come from the slicer's estimate of the current slice: `simulated`;
- prices, printer power and an hourly rate are numbers a person gives (or the price the slicer's own
  filament preset carries): `specified`. FORM never makes one up: until a price is known the cost is
  None and the reason says what to set.

Prices are kept per filament type in <data dir>/cost.json, next to the projects, so they follow you
across designs. No currency is assumed; amounts are in whatever currency the prices were typed in.
"""
from __future__ import annotations

import json
import math
import statistics
import threading
from pathlib import Path

PREF_KEYS = ("kwh_price", "watts", "machine_rate_per_h")
_lock = threading.Lock()
_materials_cache: dict = {}


# ---- preferences --------------------------------------------------------------------------------
def prefs_path(cfg: dict) -> Path:
    return Path(cfg["data"]["dir"]) / "cost.json"


def load_prefs(cfg: dict) -> dict:
    out = {"prices": {}, "kwh_price": None, "watts": None, "machine_rate_per_h": None, "currency": ""}
    try:
        got = json.loads(prefs_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if isinstance(got, dict):
        out["prices"] = {str(k): float(v) for k, v in (got.get("prices") or {}).items() if _num(v) is not None}
        for k in PREF_KEYS:
            out[k] = _num(got.get(k))
        out["currency"] = str(got.get("currency") or "")[:8]
    return out


def _num(v) -> float | None:
    """A non-negative number, or None for anything else (empty, text, negative, NaN)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f >= 0 else None


def save_prefs(cfg: dict, body: dict) -> dict:
    """Merge a change into cost.json. A value of None (or "") forgets that number.

    body: {"price_per_kg": x, "filament_type": "PLA"} | {"prices": {"PETG": x}} | kwh_price | watts |
    machine_rate_per_h | currency."""
    with _lock:
        cur = load_prefs(cfg)
        prices = dict(cur["prices"])
        changes = dict(body.get("prices") or {})
        if "price_per_kg" in body:
            changes[str(body.get("filament_type") or "")] = body["price_per_kg"]
        for k, v in changes.items():
            k = str(k).strip()
            if not k:
                raise ValueError("A price per kg needs the filament type it is for (for example PLA).")
            if v in (None, ""):
                prices.pop(k, None)
            elif _num(v) is None:
                raise ValueError(f"The price per kg for {k} must be a number, zero or more.")
            else:
                prices[k] = _num(v)
        cur["prices"] = prices
        for k in PREF_KEYS:
            if k in body:
                if body[k] in (None, ""):
                    cur[k] = None
                elif _num(body[k]) is None:
                    raise ValueError(f"{k} must be a number, zero or more.")
                else:
                    cur[k] = _num(body[k])
        if "currency" in body:
            cur["currency"] = str(body["currency"] or "").strip()[:8]
        path = prefs_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:                                       # keep what other parts of Form Studio keep here (form/costing: shops)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            raw = {}
        path.write_text(json.dumps({**raw, **cur}, indent=1, ensure_ascii=False), encoding="utf-8")
        return cur


# ---- the sums -----------------------------------------------------------------------------------
def filament_cost(grams: float, price_per_kg: float) -> float:
    return grams / 1000.0 * price_per_kg


def electricity_cost(watts: float, seconds: float, kwh_price: float) -> float:
    return watts / 1000.0 * seconds / 3600.0 * kwh_price


def machine_cost(seconds: float, rate_per_h: float) -> float:
    return seconds / 3600.0 * rate_per_h


def filament_volume_cm3(length_mm: float, diameter_mm: float) -> float:
    return math.pi * (diameter_mm / 2.0) ** 2 * length_mm / 1000.0


def _first(text, default=None):
    """First number in a slicer value such as "1.24", "1.24,1.24" or '"20"'."""
    import re
    m = re.search(r"-?\d+(?:\.\d+)?", str(text if text is not None else ""))
    return float(m.group(0)) if m else default


def estimate(slice_meta: dict, settings: dict | None = None, prefs: dict | None = None, copies: int = 1,
             overrides: dict | None = None) -> dict:
    """Cost of the sliced plate, and of `copies` of it on one plate.

    slice_meta: the slice's meta (time_s, filament_g, filament_mm); settings: toolpath.gcode_settings();
    overrides: price_per_kg / kwh_price / watts / machine_rate_per_h for this call only (CLI flags, MCP)."""
    settings, prefs, overrides = settings or {}, prefs or {"prices": {}}, overrides or {}
    copies = max(1, int(copies))
    grams, seconds = slice_meta.get("filament_g"), slice_meta.get("time_s")
    ftype = str(settings.get("filament_type") or "").split(";")[0].split(",")[0].strip().strip('"') or None
    hours = seconds / 3600.0 if seconds is not None else None

    preset_price = _first(settings.get("filament_cost"))
    if overrides.get("price_per_kg") is not None:
        price, source = float(overrides["price_per_kg"]), "given for this estimate"
    elif ftype and ftype in prefs.get("prices", {}):
        price, source = prefs["prices"][ftype], f"your price for {ftype}"
    elif preset_price and preset_price > 0:
        price, source = preset_price, "the slicer's filament preset (filament_cost)"
    else:
        price, source = None, None

    def pick(key):
        return float(overrides[key]) if overrides.get(key) is not None else prefs.get(key)
    watts, kwh_price, rate = pick("watts"), pick("kwh_price"), pick("machine_rate_per_h")

    fil = {"grams": grams, "filament_type": ftype, "price_per_kg": price, "price_source": source,
           "preset_price_per_kg": preset_price if preset_price and preset_price > 0 else None,
           "cost": None, "evidence": ["simulated", "specified"], "needs": None}
    if grams is None:
        fil["needs"] = "The slicer did not report a filament weight."
    elif price is None:
        fil["needs"] = "Set a price per kg" + (f" for {ftype}" if ftype else "") + "."
    else:
        fil["cost"] = round(filament_cost(grams, price), 4)

    el = {"watts": watts, "kwh_price": kwh_price, "hours": None if hours is None else round(hours, 3),
          "kwh": None, "cost": None, "evidence": ["simulated", "specified"], "needs": None}
    missing = [n for n, v in (("the printer's average power in watts", watts), ("a price per kWh", kwh_price)) if v is None]
    if hours is None:
        el["needs"] = "The slicer did not report a print time."
    elif missing:
        el["needs"] = "Set " + " and ".join(missing) + "."
    else:
        el["kwh"] = round(watts / 1000.0 * hours, 4)
        el["cost"] = round(electricity_cost(watts, seconds, kwh_price), 4)

    mach = {"hours": None if hours is None else round(hours, 3), "rate_per_h": rate, "cost": None,
            "evidence": ["simulated", "specified"], "needs": None}
    if hours is not None and rate is not None:
        mach["cost"] = round(machine_cost(seconds, rate), 4)
    elif rate is None:
        mach["needs"] = "Optional: set an hourly rate for the machine."

    known = [x["cost"] for x in (fil, el, mach) if x["cost"] is not None]
    not_counted = [n for n, x in (("filament", fil), ("electricity", el), ("machine time", mach)) if x["cost"] is None]
    total = round(sum(known), 4) if known else None
    part = {"filament_g": grams, "time_s": seconds, "cost": total, "counts": [n for n in ("filament", "electricity", "machine time") if n not in not_counted],
            "not_counted": not_counted}
    out = {
        "currency": prefs.get("currency", ""), "filament": fil, "electricity": el, "machine": mach,
        "per_plate_as_sliced": part,
        "copies": copies,
        "per_plate_of_copies": None,
        "evidence": "simulated × specified",
        "note": "Grams and hours are the slicer's simulation of this slice; prices and power are numbers you gave "
                "(or the price in the slicer's filament preset). Failed prints, supports you remove, wear and your time "
                "are not included. Not a quote.",
    }
    if copies > 1:
        out["per_plate_of_copies"] = {
            "copies": copies,
            "filament_g": None if grams is None else round(grams * copies, 2),
            "time_s": None if seconds is None else round(seconds * copies, 1),
            "cost": None if total is None else round(total * copies, 4),
            "evidence": "estimated",
            "note": f"{copies} × one part. A plate of copies shares start-up and travel, so the real slice differs a little: "
                    "slice the full plate to confirm.",
        }
    return out


# ---- other materials ----------------------------------------------------------------------------
def installed_filaments(slicer_info: dict) -> dict:
    """Filament presets the slicer has installed for the selected printer, grouped by material type.

    Reads Bambu Studio / OrcaSlicer preset folders (JSON). {"materials": [...], "reason": ""} ; reason says why
    the list is empty."""
    kind, cdir = slicer_info.get("kind"), slicer_info.get("config_dir")
    machine = (slicer_info.get("presets", {}).get("machine") or {}).get("name")
    if kind not in ("bambu", "orca"):
        return {"materials": [], "reason": "Form Studio reads installed filament presets from Bambu Studio and OrcaSlicer only."}
    if not cdir or not Path(cdir).is_dir():
        return {"materials": [], "reason": "The slicer's preset folder was not found."}
    if not machine:
        return {"materials": [], "reason": "No printer preset is selected in the slicer."}
    key = (str(cdir), machine)
    with _lock:
        if key in _materials_cache:
            return _materials_cache[key]
    from .adapters import _bbl
    raw: dict = {}
    for d in reversed(_bbl.search_dirs(Path(cdir), "filament")):          # user folders last, so they win
        for f in sorted(d.rglob("*.json")):
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(j, dict) and j.get("name"):
                raw[j["name"]] = j

    def flat(name, depth=0):
        j = raw.get(name)
        if j is None or depth > 12:
            return {}
        base = flat(j["inherits"], depth + 1) if j.get("inherits") else {}
        return {**base, **j}

    def one(v):
        return v[0] if isinstance(v, list) and v else v

    groups: dict = {}
    for name, j in raw.items():
        if machine not in (j.get("compatible_printers") or []) or str(j.get("instantiation", "true")) != "true":
            continue
        f = flat(name)
        ftype, dens = str(one(f.get("filament_type")) or "").strip(), _first(one(f.get("filament_density")))
        if not ftype or not dens or dens <= 0 or str(one(f.get("filament_is_support")) or "0") == "1":
            continue
        cost = _first(one(f.get("filament_cost")))
        groups.setdefault(ftype, []).append({"name": name, "density": dens, "cost": cost if cost and cost > 0 else None,
                                             "generic": name.startswith("Generic ")})
    mats = []
    for ftype, items in groups.items():
        rep = next((i for i in items if i["generic"]), None) or sorted(items, key=lambda i: i["name"])[0]
        dens = [i["density"] for i in items]
        mats.append({"type": ftype, "density_g_cm3": round(statistics.median(dens), 3),
                     "density_range": [min(dens), max(dens)], "presets": len(items), "example": rep["name"],
                     "preset_price_per_kg": rep["cost"]})
    order = ["PLA", "PETG", "ABS", "ASA", "TPU", "PC", "PA"]
    mats.sort(key=lambda m: (order.index(m["type"]) if m["type"] in order else len(order), m["type"]))
    out = {"materials": mats, "reason": "" if mats else f"No installed filament preset lists “{machine}” as compatible.",
           "printer": machine}
    with _lock:
        _materials_cache[key] = out
    return out


def compare_materials(volume_cm3: float | None, materials: list, prefs: dict, current_type: str | None = None,
                      current_grams: float | None = None, current_density: float | None = None) -> list:
    """The same sliced volume in other materials: grams from density, cost from the price per kg (yours, else the preset's)."""
    rows = []
    for m in materials:
        grams = None if volume_cm3 is None else round(volume_cm3 * m["density_g_cm3"], 2)
        if m["type"] in prefs.get("prices", {}):
            price, source = prefs["prices"][m["type"]], "your price"
        elif m.get("preset_price_per_kg"):
            price, source = m["preset_price_per_kg"], "slicer preset"
        else:
            price, source = None, None
        row = {"type": m["type"], "density_g_cm3": m["density_g_cm3"], "presets": m["presets"], "example": m["example"],
               "grams": grams, "price_per_kg": price, "price_source": source,
               "cost": None if grams is None or price is None else round(filament_cost(grams, price), 4),
               "current": m["type"] == current_type, "evidence": "estimated"}
        if row["current"] and current_grams is not None:              # the slicer's own figure for the material it sliced
            row["grams"], row["evidence"] = current_grams, "simulated"
            if current_density:
                row["density_g_cm3"] = current_density
            row["cost"] = None if price is None else round(filament_cost(current_grams, price), 4)
        rows.append(row)
    return rows


MATERIALS_NOTE = ("Estimated from volume: the sliced filament volume × each material's density from the slicer's installed "
                  "presets. Other materials need other temperatures, speeds and sometimes supports; re-slice to confirm.")


# ---- a project ----------------------------------------------------------------------------------
def project(st, p: dict, copies: int = 1, overrides: dict | None = None, with_materials: bool = True) -> dict:
    """Cost of the project's current slice (raises StudioError if there is none)."""
    from . import toolpath
    from .studio import StudioError
    key = st.keys(p)["slice"]
    meta = st.read(p, "slice", key)
    if not meta:
        raise StudioError("There is no current slice to cost.", "Run the pipeline first (form run <project>).", status=409)
    settings = toolpath.gcode_settings(st.apath(p, "slice", key) / meta["gcode"])
    prefs = load_prefs(st.cfg)
    out = estimate(meta, settings, prefs, copies, overrides)
    out |= {"project": p["id"], "rev": meta.get("rev", p["head"]), "slicer": meta.get("slicer_name") or "the slicer",
            "prefs": prefs, "prefs_file": str(prefs_path(st.cfg))}
    if meta.get("plates"):                            # several plates (form/plates.py): each costed with its own filament
        rows = []
        for pl in meta["plates"]:
            e = estimate(pl, toolpath.gcode_settings(st.apath(p, "slice", key) / pl["gcode"]), prefs, 1, overrides)
            rows.append({"n": pl["n"], "material": pl.get("material") or e["filament"]["filament_type"],
                         "filament_g": pl.get("filament_g"), "time_s": pl.get("time_s"),
                         "cost": e["per_plate_as_sliced"]["cost"], "not_counted": e["per_plate_as_sliced"]["not_counted"]})
        out["plates"] = rows
        costs = [r["cost"] for r in rows]
        out["per_plate_as_sliced"]["cost"] = None if any(c is None for c in costs) else round(sum(costs), 4)
        out["per_plate_as_sliced"]["plates"] = len(rows)
    if with_materials:
        dia = _first(settings.get("filament_diameter"), 1.75)
        vol = filament_volume_cm3(meta["filament_mm"], dia) if meta.get("filament_mm") else None
        inst = installed_filaments(st.slicer_info())
        out["materials"] = {
            "volume_cm3": None if vol is None else round(vol, 2),
            "volume_source": f"slicer's filament length × {dia:g} mm filament",
            "rows": compare_materials(vol, inst["materials"], prefs, out["filament"]["filament_type"], meta.get("filament_g"),
                                      _first(settings.get("filament_density"))),
            "reason": inst["reason"], "evidence": "estimated", "note": MATERIALS_NOTE,
        }
    return out
