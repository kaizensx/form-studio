"""Tests of print features: 3D printing is an opt-in capability (form/capabilities.py), so a configuration that
exercises the slicer, print checks and the fit model turns it on explicitly."""

PRINTING = ["core", "parts", "mesh", "print"]


def with_printing(cfg: dict) -> dict:
    cfg.setdefault("general", {})["capabilities"] = list(PRINTING)
    return cfg
