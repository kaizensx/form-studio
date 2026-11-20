"""What a design is for, and whether the person prints at all.

Two answers shape the whole app:

  [general].capabilities              what the person set Form Studio up for (form/capabilities.py). Printing is the
                                      capability "print": off unless they turn it on in the launcher or in Settings ›
                                      Set up for. Form Studio is for making things first; printing is one optional way
                                      to make them. Older files with only [general].printing still read as they did.
  project["purpose"]                  "print" (made to be 3D printed) or "model" (just a 3D model: for rendering,
                                      CAD exchange, CNC, laser cutting, moulding, visualisation, ...). A new design
                                      is a model unless whoever creates it says it is for printing (the person on
                                      Home, or the agent when the request says so); a design saved before purposes
                                      existed is "print".
  project["process"]                  for a model: how it will be made, if the person said ("" = not stated). It sets
                                      the smallest feature worth flagging (form/checks.py).

A model is never sliced and never checked against a printer: overhangs, bridges, plate contact, the build volume,
nozzle-based wall rules, the printer-accuracy fit model and the slice are not applicable, and say so.
"""
from __future__ import annotations

PURPOSES = {
    "print": {"label": "For 3D printing", "short": "3D print",
              "text": "Checked against your printer and sliced when a slicer is installed."},
    "model": {"label": "Just a 3D model", "short": "3D model",
              "text": "For rendering, CAD exchange, CNC, laser cutting, moulding or visualisation. Not sliced, and no "
                      "printer is needed."},
}

# how a model will be made; min_feature_mm is the thinnest wall or feature that process usually holds (a rule of
# thumb, stated as such in the check)
PROCESSES = {
    "": {"label": "Not stated", "min_feature_mm": None},
    "render": {"label": "Rendering or visualisation", "min_feature_mm": None},
    "cad": {"label": "CAD exchange (STEP for another program)", "min_feature_mm": None},
    "cnc": {"label": "CNC machining", "min_feature_mm": 0.8,
            "why": "Thin walls chatter and deflect under the cutter; about 0.8 mm in metal, more in plastics."},
    "laser": {"label": "Laser or waterjet cutting", "min_feature_mm": 1.0,
              "why": "Slots and bridges narrower than about the sheet thickness, or 1 mm, burn through or warp."},
    "injection": {"label": "Injection moulding", "min_feature_mm": 0.8,
                  "why": "Walls under about 0.8 mm do not fill reliably; most parts use 1.5 to 3 mm."},
    "casting": {"label": "Casting", "min_feature_mm": 2.0,
                "why": "Metal does not flow into sections much thinner than about 2 mm in sand or investment casting."},
    "sheet_metal": {"label": "Sheet metal", "min_feature_mm": 0.5,
                    "why": "Sheet thinner than about 0.5 mm is foil; holes and flanges need about the sheet thickness."},
    "other": {"label": "Other", "min_feature_mm": None},
}

# the checks that only make sense for a part that will be printed (form/checks.py ids), with what they would say
PRINT_ONLY = [
    ("envelope", "Fits the build volume"), ("wall", "Thinnest wall for the nozzle"), ("overhang", "Unsupported overhangs"),
    ("bridge", "Bridged ceilings"), ("adhesion", "Plate contact"), ("fit", "Fit with the printer's accuracy"),
    ("slice", "Slice: print time, filament and toolpaths"),
]


def normalise(v) -> str | None:
    s = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
    if s in ("print", "printing", "3d_print", "3d_printing", "for_3d_printing", "printed"):
        return "print"
    if s in ("model", "3d_model", "just_a_3d_model", "not_for_printing", "no_print"):
        return "model"
    return None


def normalise_process(v) -> str | None:
    s = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias = {"machining": "cnc", "milling": "cnc", "cnc_machining": "cnc", "laser_cutting": "laser", "waterjet": "laser",
             "moulding": "injection", "molding": "injection", "injection_moulding": "injection",
             "injection_molding": "injection", "visualisation": "render", "visualization": "render", "rendering": "render",
             "sheet": "sheet_metal", "none": "", "not_stated": ""}
    s = alias.get(s, s)
    return s if s in PROCESSES else None


def printing(cfg: dict) -> bool:
    """Does the person print? The capability "print" (form/capabilities.py); off when it was never chosen."""
    from . import capabilities
    return capabilities.has(cfg, "print")


def decided(cfg: dict) -> bool:
    """Has the person chosen what to set Form Studio up for? Only a value in the file counts."""
    from . import capabilities
    return capabilities.decided(cfg)


def default(cfg: dict) -> str:
    """What a new design is for, when nobody says: a 3D model, for everyone. Form Studio is for making things first;
    someone who prints marks a design for printing when they say so (Home's "Make it for: my printer", the request
    itself, or one click in Make). Someone who prints and wants every new design made for the printer says so once:
    [general].new_designs = "print" (Settings › Printing), honoured only while printing is on."""
    g = cfg.get("general") if isinstance(cfg, dict) else None
    want = str((g or {}).get("new_designs") or "").strip().lower() if isinstance(g, dict) else ""
    return "print" if want == "print" and printing(cfg) else "model"


def of(p: dict | None) -> str:
    """A design's purpose. Saved before purposes existed: a print, which is what every design then was."""
    if not isinstance(p, dict):
        return "print"
    return normalise(p.get("purpose")) or "print"


def is_model(p: dict | None) -> bool:
    return of(p) == "model"


def process(p: dict | None) -> str:
    return (normalise_process(p.get("process")) or "") if isinstance(p, dict) else ""


def describe(p: dict | None) -> dict:
    """{"purpose", "label", "process", "process_label", "min_feature_mm", "not_applicable"} for the UI and agents."""
    pur = of(p)
    pr = process(p) if pur == "model" else ""
    out = {"purpose": pur, "label": PURPOSES[pur]["label"], "text": PURPOSES[pur]["text"]}
    if pur == "model":
        out.update(process=pr, process_label=PROCESSES[pr]["label"], min_feature_mm=PROCESSES[pr]["min_feature_mm"],
                   not_applicable=[label for _, label in PRINT_ONLY])
    return out


def catalogue(cfg: dict) -> dict:
    """Everything a picker needs: purposes, processes, the global answer and the default for a new design."""
    return {"purposes": [{"id": k, **v} for k, v in PURPOSES.items()],
            "processes": [{"id": k, "label": v["label"], "min_feature_mm": v["min_feature_mm"], "why": v.get("why", "")}
                          for k, v in PROCESSES.items()],
            "printing": printing(cfg), "decided": decided(cfg), "default": default(cfg),
            "capabilities": capabilities_of(cfg)}


def capabilities_of(cfg: dict) -> list[str]:
    from . import capabilities
    return capabilities.of(cfg)
