"""Facade over the configured slicer adapter ([slicer].kind, default "bambu").

A slice is a simulation by the slicer. It is not a print.
"""
from __future__ import annotations

import importlib

from .adapters import SLICERS
from .adapters.bambu import SlicerBlocked, SlicerFailed, flatten, parse_gcode_header, parse_layers  # noqa: F401

_loaded: dict = {}


def adapter(kind: str):
    if kind not in SLICERS:
        raise SlicerBlocked(f"Unknown slicer kind “{kind}”. Known: {', '.join(SLICERS)}.")
    if kind not in _loaded:
        _loaded[kind] = importlib.import_module(SLICERS[kind])
    return _loaded[kind]


def resolve(cfg: dict) -> dict:
    kind = cfg["slicer"].get("kind", "bambu")
    try:
        out = adapter(kind).resolve(cfg)
    except SlicerBlocked as e:
        out = {"available": False, "reason": str(e), "presets": {}, "app": ""}
    out["kind"] = kind
    return out


def _for(resolved: dict):
    return adapter(resolved.get("kind", "bambu"))


def version(app: str, kind: str = "bambu") -> str:
    return adapter(kind).version(app)


def public(resolved: dict) -> dict:
    out = _for(resolved).public(resolved)
    out["kind"] = resolved.get("kind", "bambu")
    return out


def slice_stl(resolved: dict, stl, out_dir, timeout: float = 600) -> dict:
    return _for(resolved).slice_stl(resolved, stl, out_dir, timeout)
