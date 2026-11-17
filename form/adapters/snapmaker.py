"""Slicer adapter for Snapmaker Orca (Snapmaker/OrcaSlicer), an OrcaSlicer fork with OrcaSlicer's CLI and presets.

Everything is in orca_forks.py (and _bbl.py / orca.py). Settings, all optional, in studio.toml:
    [slicer.snapmaker]
    app = "/Applications/Snapmaker Orca.app/Contents/MacOS/Snapmaker_Orca"
    config_dir = "~/Library/Application Support/Snapmaker_Orca"
    machine = "auto"      # "auto" follows the selection in Snapmaker Orca
    process = "auto"
    filament = "auto"
"""
from .common import SlicerBlocked, SlicerFailed  # noqa: F401
from .orca_forks import SNAPMAKER, export

export(SNAPMAKER, globals())
