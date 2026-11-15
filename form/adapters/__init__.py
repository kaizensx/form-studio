"""Adapters to the software FORM drives. Each one is a plain module.

A slicer adapter provides:

    resolve(cfg) -> dict            which presets a slice would use now; must set
                                    "available", "reason", "app", "presets"
                                    ({kind: {"name", "sha", "data"}}), "nozzle_mm"
    version(app) -> str
    public(resolved) -> dict        the same, without preset bodies
    slice_stl(resolved, stl, out_dir, timeout) -> dict
                                    time_s, filament_g, layers, gcode, threemf, ...
    parse_layers(gcode_path) -> list
    SlicerBlocked, SlicerFailed     exceptions: cannot run here / ran and refused

Register a new adapter in SLICERS and select it with [slicer].kind in studio.toml.
"""
SLICERS = {"bambu": "form.adapters.bambu"}
