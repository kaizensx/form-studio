"""Slicer adapter for SuperSlicer: a PrusaSlicer fork with the same INI presets, CLI and G-code comments.

Everything is in prusa.py; only the program name, folder and version string differ.
Not run against a real SuperSlicer on the machine this was written on. Settings: [slicer.superslicer] (see prusa.py).
"""
from .common import SlicerBlocked, SlicerFailed  # noqa: F401
from .prusa import SUPERSLICER, Adapter, parse_layers_prusa

_A = Adapter(SUPERSLICER)
LABEL = SUPERSLICER.label
find_app, config_dir, install_hint, resolve = _A.find_app, _A.config_dir, _A.install_hint, _A.resolve
version, public, slice_stl = _A.version, _A.public, _A.slice_stl
parse_layers = parse_layers_prusa
