"""Decorative cuts that respect the wall behind them: flutes, grooves, a fluted skin, a parting line by hand.

    from form import craft
    cuts = [lambda d, x=x, y=y: Pos(x + nx * (r - d), y + ny * (r - d), -1) * Cylinder(r, L + 2, align=C)
            for x, y, nx, ny in spots]
    body = craft.finish_cut(body, cuts, depth=0.5)

Each cut is a function of its depth that returns the tool. finish_cut makes it at `depth`, measures the wall left
under it (form/wallguard.py cut_walls, the Thinnest-wall check's ray) and, where that wall is under the print minimum
(min_wall, default the build's floor: max(2 x line width, three nozzle widths) for a print), makes it again only as
deep as the wall allows; a cut that would be shallower than min_depth is left out. What it clamped or left out is
noted (craft.notes()), so the build log says it. A finish written this way never trips the feature guard.
"""
from __future__ import annotations

from typing import Callable, Iterable

from ._common import need, note, num

MARGIN = 0.03        # mm a clamped cut leaves above the floor, so the feature guard's own measurement agrees


def finish_cut(body, cuts: Iterable[Callable], depth: float, min_wall: float | None = None,
               min_depth: float = 0.15, label: str = "finish_cut"):
    """Cut each tool `cut(d)` into body at depth d <= depth, keeping the wall under it >= min_wall."""
    from .. import wallguard
    d0 = num(depth, "depth", positive=True)
    floor = wallguard.current_floor() if min_wall is None else num(min_wall, "min_wall")
    fns = list(cuts)
    need(all(callable(c) for c in fns), f"{label}: every cut is a function of its depth that returns the tool",
         "Pass lambdas: lambda d: Pos(...) * Cylinder(r, h) placed so it reaches d into the surface.", ["cuts"])
    out = body
    full = clamped = skipped = 0
    shallowest = d0
    for cut in fns:
        d = d0
        done = False
        for _ in range(3):                       # the asked depth, then what the measured wall leaves room for
            try:
                cand = out - cut(d)
            except Exception:
                break
            if cand is None or not getattr(cand, "is_valid", True) or len(cand.solids()) != len(out.solids()):
                break
            w = wallguard.cut_walls(out, cand, n=60) if floor > 0 else None
            if w is None or w["t"] >= floor + (MARGIN if d < d0 - 1e-9 else 0.0) - 1e-3:
                out, done = cand, True
                break
            d = d - (floor - w["t"]) - MARGIN     # the wall is short by floor - t: take that (and a margin) off
            if d < min_depth:
                break
        if done:
            if d < d0 - 1e-9:
                clamped += 1
                shallowest = min(shallowest, d)
            else:
                full += 1
        else:
            skipped += 1
    if clamped or skipped:
        note(f"{label}: {full} of {len(fns)} cuts at {d0:g} mm"
             + (f", {clamped} made shallower (down to {shallowest:.2f} mm)" if clamped else "")
             + (f", {skipped} left out" if skipped else "")
             + f" to keep a {floor:g} mm wall under them")
    return out


__all__ = ["finish_cut"]
