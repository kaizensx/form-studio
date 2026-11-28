"""“Use in Form Studio”: one switch per optional engine or app, separate from whether it is installed.

Installing something puts it on this computer; this switch says whether Form Studio calls it. Every place that would
run an optional engine asks `on(id, cfg)` first, so one that is switched off is never started, whatever is installed.

    id (the installer's registry id)   key in studio.toml       default
    recon.learned   CAD-Recode         [recon] learned          on    (used whenever it is installed, as before)
    recon.cadfit    CADFit             [recon] cadfit           off   (Settings turns it on when it installs it)
    game.coacd      CoACD              [use] coacd              on
    robot.mujoco    MuJoCo             [use] mujoco             on
    exemplars.cadevolve  CADEvolve     [use] corpus             on
    blender, freecad, openscad, kicad  [use] <id>               on
    slicer.<kind>                      [use] <kind>             on

An environment variable wins for one run: FORM_USE_<ID> (dots as underscores, e.g. FORM_USE_RECON_LEARNED=0), and the
older FORM_RECON_CADFIT for CADFit. Nothing here imports an engine; it only reads the configuration.
"""
from __future__ import annotations

import os

_SLICERS = ("bambu", "orca", "prusa", "superslicer", "qidi", "elegoo", "snapmaker")   # form/adapters AUTO_ORDER

# id -> key, default, what the switch changes (one concrete line, shown next to it), what it is called when off
SWITCHES: dict[str, dict] = {
    "recon.learned": {
        "key": "recon.learned", "default": True, "name": "CAD-Recode",
        "effect": "On: making a mesh editable also asks CAD-Recode for a sketch-and-extrude program (up to 30% of the "
                  "time), kept only when it matches the mesh better. Off: Form Studio's own route only."},
    "recon.cadfit": {
        "key": "recon.cadfit", "default": False, "name": "CADFit", "env": ("FORM_RECON_CADFIT",),
        "effect": "On: making a mesh editable also runs CADFit's search (20 to 120 s more per mesh), kept only when "
                  "it verifies and is better. Off: it is never started."},
    "game.coacd": {
        "key": "use.coacd", "default": True, "name": "CoACD",
        "effect": "On: a game asset may ask for collision=\"coacd\" (several convex pieces). Off: every game asset "
                  "gets one convex hull per part."},
    "robot.mujoco": {
        "key": "use.mujoco", "default": True, "name": "MuJoCo",
        "effect": "On: robot files are loaded by yourdfpy and MuJoCo (and the MJCF stepped for a second) when it is "
                  "installed. Off: they are validated structurally only, and say so."},
    "exemplars.cadevolve": {
        "key": "use.corpus", "default": True, "name": "the CADEvolve corpus",
        "effect": "On: the agent's example search adds reference CadQuery programs from this corpus after Form "
                  "Studio's own examples. Off: only Form Studio's examples."},
    "blender": {
        "key": "use.blender", "default": True, "name": "Blender",
        "effect": "On: photo renders, game-asset bakes and organic modelling steps run Blender in the background. "
                  "Off: those say Blender is switched off; everything else works."},
    "freecad": {
        "key": "use.freecad", "default": True, "name": "FreeCAD",
        "effect": "On: every STEP export is read back in FreeCAD as an extra check, and “Open in FreeCAD” is offered. "
                  "Off: neither happens."},
    "openscad": {
        "key": "use.openscad", "default": True, "name": "OpenSCAD",
        "effect": "On: designs written in OpenSCAD build here. Off: they are refused with a message; designs in "
                  "Python are not affected."},
    "kicad": {
        "key": "use.kicad", "default": True, "name": "KiCad",
        "effect": "On: board checks run KiCad's own DRC and ERC, and board fab files (Gerbers, drill, pick-and-place, "
                  "BOM, STEP) are made with it. Off: boards are still read and enclosures checked; KiCad is never started."},
    "freerouting": {
        "key": "use.freerouting", "default": False, "name": "Freerouting",
        "effect": "On: board_route may hand a board to your Freerouting (a separate GPL-3.0 program) when asked with "
                  "engine=\"freerouting\". Off: it is never started; Form Studio's own router is used."},
    **{f"slicer.{k}": {
        "key": f"use.{k}", "default": True, "name": "this slicer",
        "effect": "On: Form Studio may slice with it and lists its printers. Off: it is skipped, also when the "
                  "slicer is set to Automatic."} for k in _SLICERS},
}

_TRUE, _FALSE = ("1", "true", "yes", "on"), ("0", "false", "no", "off")


def env_names(eid: str) -> tuple[str, ...]:
    return ("FORM_USE_" + eid.upper().replace(".", "_"), *SWITCHES.get(eid, {}).get("env", ()))


def env_override(eid: str) -> tuple[str, bool] | None:
    """(variable, value) when an environment variable decides this switch for this run."""
    for n in env_names(eid):
        v = (os.environ.get(n) or "").strip().lower()
        if v in _TRUE:
            return n, True
        if v in _FALSE:
            return n, False
    return None


def on(eid: str, cfg: dict | None = None) -> bool:
    """Does Form Studio use this engine or app when it is installed? Unknown ids are on (nothing to switch).
    cfg None: the configuration is read from the file, so a child process sees what Settings last saved."""
    sw = SWITCHES.get(eid)
    if sw is None:
        return True
    ov = env_override(eid)
    if ov is not None:
        return ov[1]
    if cfg is None:
        try:
            from . import config
            cfg = config.load()
        except Exception:                               # noqa: BLE001 - an unreadable file: the defaults
            cfg = {}
    sec, name = sw["key"].split(".", 1)
    v = (cfg.get(sec) or {}).get(name)
    return bool(sw["default"] if v is None else v)


def off_reason(eid: str) -> str:
    """What a caller says when it would have used an engine that is switched off."""
    sw = SWITCHES.get(eid) or {}
    name = sw.get("name", eid)
    name = name[0].upper() + name[1:]
    return f"{name} is switched off in Settings › Engines & software (“Use in Form Studio”)."


def describe(eid: str, cfg: dict | None = None) -> dict | None:
    """What Settings shows for the switch: its key, whether it is on, its default, what it changes, and the
    environment variable that decides it for this run, if one does. None for something that has no switch."""
    sw = SWITCHES.get(eid)
    if sw is None:
        return None
    ov = env_override(eid)
    return {"key": sw["key"], "on": on(eid, cfg), "default": bool(sw["default"]), "effect": sw["effect"],
            "locked_by": ov[0] if ov else ""}


def defaults() -> dict:
    """{section: {name: default}} for form/config.py."""
    out: dict = {}
    for sw in SWITCHES.values():
        sec, name = sw["key"].split(".", 1)
        out.setdefault(sec, {})[name] = bool(sw["default"])
    return out
