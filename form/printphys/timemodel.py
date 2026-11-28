"""A fast print-time and filament model of one orientation, from facet integrals (no slicing).

    s = settings(preset_process, preset_filament)      # layer height, walls, infill, speeds: from the slicer's
                                                       # preset where it has them, else assumed, each labelled
    t = estimate(geometry_row, volume_mm3, s)          # {"time_s", "filament_g", "support_g", "parts": {...}}

What the extruder draws, as lengths of line (w wide, h high):

    walls      n_walls x (side area / h)            the perimeter of every layer, summed: the area of the surface
                                                    seen from the side, over the layer height
    skins      (top area x n_top + bottom area x n_bottom) / w     solid layers under every upward face and over
                                                    every downward one
    infill     the rest of the volume x density / (w h)
    support    support volume x support density / (w h), and its interface layers under the overhangs

Time is each length over its speed, plus a fixed time per layer (the layer change and the travel to it). This ignores
acceleration, cooling slow-downs, travel inside a layer, the prime tower and everything a slicer plans, so on its own
it ranks orientations and little more. **Calibration:** when a real slice of one orientation is at hand, the model's
time and grams are multiplied by (slicer / model) of that slice; the factors are stated, and the error on other
orientations is measured by slicing them (form/printphys/orient.py verify), never assumed.
"""
from __future__ import annotations

ASSUMED = "assumed"
PRESET = "slicer preset"
DEFAULTS = {"layer_height": 0.2, "line_width": 0.42, "walls": 2, "top_layers": 5, "bottom_layers": 3, "infill": 0.15,
            "wall_speed": 150.0, "skin_speed": 150.0, "infill_speed": 200.0, "support_speed": 150.0,
            "support_spacing": 2.5, "support_interface_layers": 2, "support_interface_spacing": 0.5,
            "layer_overhead_s": 1.5, "critical_deg": 45.0, "density_g_cm3": 1.24, "nozzle": 0.4}
UNITS = {"layer_height": "mm", "line_width": "mm", "walls": "", "top_layers": "", "bottom_layers": "", "infill": "",
         "wall_speed": "mm/s", "skin_speed": "mm/s", "infill_speed": "mm/s", "support_speed": "mm/s",
         "support_spacing": "mm", "support_interface_layers": "", "support_interface_spacing": "mm",
         "layer_overhead_s": "s", "critical_deg": "deg from vertical", "density_g_cm3": "g/cm3", "nozzle": "mm"}
# our name: the preset keys that hold it (Bambu Studio / OrcaSlicer family first, then PrusaSlicer family)
KEYS = {"layer_height": ("layer_height",), "line_width": ("line_width", "extrusion_width"),
        "walls": ("wall_loops", "perimeters"), "top_layers": ("top_shell_layers", "top_solid_layers"),
        "bottom_layers": ("bottom_shell_layers", "bottom_solid_layers"),
        "infill": ("sparse_infill_density", "fill_density"),
        "wall_speed": ("inner_wall_speed", "perimeter_speed"),
        "skin_speed": ("internal_solid_infill_speed", "solid_infill_speed"),
        "infill_speed": ("sparse_infill_speed", "infill_speed"),
        "support_speed": ("support_speed", "support_material_speed"),
        "support_spacing": ("support_base_pattern_spacing", "support_material_spacing"),
        "support_interface_layers": ("support_interface_top_layers", "support_material_interface_layers"),
        "support_interface_spacing": ("support_interface_spacing", "support_material_interface_spacing")}
FILAMENT_KEYS = {"density_g_cm3": ("filament_density",)}
THRESHOLD_KEYS = ("support_threshold_angle", "support_material_threshold")    # from horizontal, in the slicers


def _num(v):
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None:
        return None
    s = str(v).strip()
    pct = s.endswith("%")
    try:
        x = float(s.rstrip("%"))
    except ValueError:
        return None
    return x / 100.0 if pct else x


def settings(process: dict | None = None, filament: dict | None = None, given: dict | None = None) -> dict:
    """{"values": {name: number}, "how_known": {name: "slicer preset" | "assumed" | "given"}, "units": {...}}."""
    vals, how = dict(DEFAULTS), {k: ASSUMED for k in DEFAULTS}
    for name, keys in KEYS.items():
        for k in keys:
            x = _num((process or {}).get(k))
            if x is not None and x > 0:
                if name == "infill" and x > 1:
                    x /= 100.0
                vals[name], how[name] = x, PRESET
                break
    for name, keys in FILAMENT_KEYS.items():
        for k in keys:
            x = _num((filament or {}).get(k))
            if x is not None and x > 0:
                vals[name], how[name] = x, PRESET
                break
    for k in THRESHOLD_KEYS:
        x = _num((process or {}).get(k))
        if x is not None and 0 < x < 90:                 # the slicers count from horizontal: 30 supports below 30
            vals["critical_deg"], how["critical_deg"] = 90.0 - x, PRESET
            break
    for k, v in (given or {}).items():
        if k in vals and v is not None:
            vals[k], how[k] = float(v), "given"
    return {"values": vals, "how_known": how, "units": UNITS}


def estimate(g: dict, volume_mm3: float, s: dict, calibration: dict | None = None) -> dict:
    """Time and filament of one orientation. g: a row of form.printphys.geom.evaluate (side, top and bottom areas,
    height, support volume and shadow). calibration: {"time": factor, "mass": factor} from a real slice."""
    v = s["values"] if "values" in s else s
    h, w = v["layer_height"], v["line_width"]
    layers = max(1.0, g["height_mm"] / h)
    walls = v["walls"] * g["lateral_mm2"] / h
    skins = (g["top_mm2"] * v["top_layers"] + g["bottom_mm2"] * v["bottom_layers"]) / w
    shell_mm3 = min((walls + skins) * w * h, volume_mm3)
    infill = max(volume_mm3 - shell_mm3, 0.0) * v["infill"] / (w * h)
    sup_density = min(1.0, w / max(v["support_spacing"], w))
    int_density = min(1.0, w / (w + max(v["support_interface_spacing"], 0.0)))
    support = g["support_mm3"] * sup_density / (w * h)
    interface = g.get("support_shadow_mm2", 0.0) * v["support_interface_layers"] * int_density / w
    parts = {"walls_s": walls / v["wall_speed"], "skins_s": skins / v["skin_speed"], "infill_s": infill / v["infill_speed"],
             "support_s": (support + interface) / v["support_speed"], "layers_s": layers * v["layer_overhead_s"]}
    rho = v["density_g_cm3"] * 1e-3                                   # g/mm3
    model_g = (walls + skins + infill) * w * h * rho
    support_g = (support + interface) * w * h * rho
    time_s = sum(parts.values())
    kt = (calibration or {}).get("time") or 1.0
    km = (calibration or {}).get("mass") or 1.0
    return {"time_s": time_s * kt, "filament_g": (model_g + support_g) * km, "support_g": support_g * km,
            "model_g": model_g * km, "layers": int(round(layers)),
            "parts": {k: x * kt for k, x in parts.items()}, "uncalibrated": {"time_s": time_s, "filament_g": model_g + support_g,
                                                                             "support_g": support_g}}
