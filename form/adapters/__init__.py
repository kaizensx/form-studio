"""Adapters to the software FORM drives. Each one is a plain module.

A slicer adapter provides:

    LABEL                           the program's name, for people ("OrcaSlicer")
    find_app(cfg) -> str | None     the program, if it is installed (cheap; used by auto-detection)
    install_hint() -> dict          {url, cmds, note, size}: how to get it
    resolve(cfg) -> dict            which presets a slice would use now; must set
                                    "available", "reason", "app", "presets"
                                    ({kind: {"name", "sha", "data"}}), "nozzle_mm"
    version(app) -> str
    public(resolved) -> dict        the same, without preset bodies
    slice_stl(resolved, stl, out_dir, timeout) -> dict
                                    time_s, filament_g, layers, gcode, threemf, ...
    parse_layers(gcode_path) -> list
    SlicerBlocked, SlicerFailed     exceptions: cannot run here / ran and refused (form.adapters.common)

Register a new adapter in SLICERS and select it with [slicer].kind in studio.toml.
[slicer].kind = "auto" picks the first installed one in AUTO_ORDER.
"""
SLICERS = {
    "bambu": "form.adapters.bambu",
    "orca": "form.adapters.orca",
    "prusa": "form.adapters.prusa",
    "superslicer": "form.adapters.superslicer",
    "qidi": "form.adapters.qidi",
    "elegoo": "form.adapters.elegoo",
    "snapmaker": "form.adapters.snapmaker",
}
AUTO_ORDER = ["bambu", "orca", "prusa", "superslicer", "qidi", "elegoo", "snapmaker"]
