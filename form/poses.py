"""Where an assembly's parts are drawn on the ground, assembled and pulled apart (the app's Viewport.qml does the same).

    anchor_of(parts)                      the part that stays put: fixed to the world, largest footprint, lowest
    explode_offsets(parts, factor)        {part id: [dx, dy, dz]}: each part's offset in the exploded view

`parts` are the view payload's assembly parts (form/assembly.py view): "id", "parent", "bbox" (assembled, the
displayed frame), "explode_total".

The assembled set rests on the ground: its lowest point at z = 0. Pulling it apart never moves the anchor: every
other part moves by its own exploded offset less the anchor's, so the anchor's offset is zero, and an offset that
would take a part below the ground has its vertical part turned upward (reflected). So the exploded set rests on
z >= 0 with the anchor exactly where it was. Joints swing about the same rest: the part fixed to the world never
moves when another one turns.
"""
from __future__ import annotations

EPS_Z = 1.0          # mm: parts whose lowest points are this close count as equally low


def _area(b) -> float:
    return max(0.0, b[1][0] - b[0][0]) * max(0.0, b[1][1] - b[0][1])


def anchor_of(parts: list) -> str:
    """The anchor: among the parts fixed to the world (no parent), the one with the largest footprint in the
    assembled pose; of footprints within 5 % of the largest, the lowest. "" for no parts."""
    if not parts:
        return ""
    roots = [x for x in parts if not x.get("parent")] or list(parts)
    big = max(_area(x["bbox"]) for x in roots)
    near = [x for x in roots if _area(x["bbox"]) >= 0.95 * big - 1e-9]
    return min(near, key=lambda x: (round(x["bbox"][0][2] / EPS_Z), -_area(x["bbox"]), parts.index(x)))["id"]


def rest_lift(parts: list) -> float:
    """How far the assembled set is lifted to rest on the ground (its lowest point to z = 0)."""
    return -min(x["bbox"][0][2] for x in parts) if parts else 0.0


def explode_offsets(parts: list, factor: float = 1.0, anchor: str | None = None) -> dict:
    """{part id: [dx, dy, dz]}: the exploded offset of each part relative to the anchor (whose offset is zero), with
    a downward offset that would take the part below the ground reflected upward. In the displayed (assembled)
    frame, before the rest lift is applied."""
    if not parts:
        return {}
    anchor = anchor or anchor_of(parts)
    by = {x["id"]: x for x in parts}
    a = [float(v) for v in (by[anchor].get("explode_total") or by[anchor].get("explode") or (0, 0, 0))] if anchor in by \
        else [0.0, 0.0, 0.0]
    lift = rest_lift(parts)
    out = {}
    for x in parts:
        e = [float(v) for v in (x.get("explode_total") or x.get("explode") or (0, 0, 0))]
        d = [(e[i] - a[i]) * factor for i in range(3)] if x["id"] != anchor else [0.0, 0.0, 0.0]
        if x["bbox"][0][2] + lift + d[2] < -1e-9:          # it would go below the ground: turn it upward
            d[2] = -d[2]
        out[x["id"]] = d
    return out
