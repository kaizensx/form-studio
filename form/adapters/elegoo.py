"""Slicer adapter for ElegooSlicer (ELEGOO-3D/ElegooSlicer), an OrcaSlicer fork with OrcaSlicer's CLI and presets.

Everything is in orca_forks.py (and _bbl.py / orca.py). Settings, all optional, in studio.toml:
    [slicer.elegoo]
    app = "/Applications/ElegooSlicer.app/Contents/MacOS/ElegooSlicer"
    config_dir = "~/Library/Application Support/ElegooSlicer"
    machine = "auto"      # "auto" follows the selection in ElegooSlicer
    process = "auto"
    filament = "auto"
"""
from .common import SlicerBlocked, SlicerFailed  # noqa: F401
from .orca_forks import ELEGOO, export

export(ELEGOO, globals())
