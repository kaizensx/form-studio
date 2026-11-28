"""The Bench entry "Lattice infill" (the Bench is form/studies.py), among the Check studies.

Current when the head revision carries a lattice and its numbers are stored for the head's geometry (form/lattice
keeps them under a key of the geometry and what was asked); stale when the design changed since they were read; never
when the design carries no lattice, with the tool that puts one in. Running it reads the lattice again for the head:
the build's report from the kernel, density, the scaling-law stiffness, printability.
"""
from __future__ import annotations

import json

ID = "lattice"
LABEL = "Lattice infill"


def summary(st, p: dict) -> dict:
    from . import _dir, current
    spec = current(st, p)
    if not spec:
        return {"state": "never", "headline": "",
                "why": "No lattice in this design: lattice_fill (or `form lattice fill`) puts one in a region, with a skin."}
    try:
        last = json.loads((_dir(st, p) / "last.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "never", "headline": "", "why": "The lattice has not been read for this design yet."}
    if last.get("geometry") == st.keys(p)["geometry"]:
        return {"state": "current", "headline": last.get("headline", ""), "rev": last.get("rev"),
                "evidence": "computed (unit cell; scaling law); measured on the built solid"}
    return {"state": "stale", "headline": last.get("headline", ""), "rev": last.get("rev"),
            "why": f"read for r{last.get('rev')}; the design has changed since"}


def run(st, pid: str) -> dict:
    from . import read
    r = read(st, st.load(pid))
    return {"headline": r.get("headline", ""), "evidence": "computed (unit cell; scaling law); measured on the built solid",
            "detail": (r.get("built") or {}).get("representation", ""), "data": {k: r.get(k) for k in
                                                                                 ("spec", "relative_density", "stiffness",
                                                                                  "features", "printability", "built")}}


def register_studies(register) -> None:
    from ..studies import Study
    register(Study(
        id=ID, group="study", label=LABEL,
        doc="A strut lattice or a TPMS inside a region of the design, with a skin: what was built (B-rep or mesh, and "
            "why), relative density measured on the solid, stiffness by Gibson-Ashby scaling, the thinnest strut or "
            "wall against the process, and trapped powder or resin.",
        evidence="computed (unit cell; scaling law); measured on the built solid",
        run=lambda ctx: run(ctx.st, ctx.p["id"]),
        state_fn=lambda ctx: summary(ctx.st, ctx.p),
        inputs=("geometry", "the lattice's specification", "material (stiffness)", "process (printability)"),
        by="engine", app="lattice", tool="lattice_fill", order=20, extra={"chapter": "check", "cli": "form lattice"}))
