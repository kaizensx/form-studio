"""Tests of print features: 3D printing is an opt-in capability (form/capabilities.py), so a configuration that
exercises the slicer, print checks and the fit model turns it on explicitly."""

PRINTING = ["core", "parts", "mesh", "print"]


def with_printing(cfg: dict) -> dict:
    cfg.setdefault("general", {})["capabilities"] = list(PRINTING)
    cfg["general"]["new_designs"] = "print"     # and, as before creation came first, new designs are made for the printer
    return cfg
