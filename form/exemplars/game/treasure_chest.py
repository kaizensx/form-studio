"""Stylised treasure chest: a plank body with a barrel lid, iron straps with dome rivets, a hasp and worn edges.

How it is made: wood blocks (body, arched lid) and iron plates on their surface (straps front and back, bands over the
lid and down its front and back, a foot frame, a lock plate) as numpy boxes, so no face is buried in the wood; their
outer edges bevelled in the cage (the big blocks wide, the iron narrow, chosen by the angle left after the first bevel);
the lock plate's face inset as a recess. Bake-only (high_only): the plank seams as V grooves, dome rivets on every strap
and band, and a draw latch from the kit on the lock plate.

Creases in the low cage are 1 (sharp) or none: a semi-sharp crease costs the CAD limit surface a subdivision level per
unit of sharpness, so kit parts (which carry 0.5..0.9 creases) go in the bake source only.
"""
from __future__ import annotations

import math

from .base import box, span, start

TITLE = "Stylised treasure chest"
ORIGINALITY = ("An original chest built from generic woodworking and hardware vocabulary (boarded body, barrel lid, "
               "riveted strap iron, a draw latch). It copies no game, film or brand prop; the proportions, plank "
               "count and hardware layout were chosen here.")
MATERIALS = {"default": {"material": "wood", "tint": "#8a5a32", "grain_mm": 28, "wear": 0.75},
             "iron": {"material": "bare_metal", "tint": "#3e3c3a", "grain_mm": 18, "wear": 0.7},
             "gold": {"material": "bare_metal", "tint": "#c9982f", "grain_mm": 10, "wear": 0.5}}

W, D, H, LID = 600.0, 380.0, 300.0, 120.0
PLANKS_Z = [0.0, 62.0, 122.0, 182.0, 242.0, 300.0]
STRAP_X = (-205.0, 205.0)


def _arch(r):
    return lambda y: LID * 0.9 * math.cos(math.pi / 2 * min(abs(y) / r, 1.0) * 0.86)     # never vertical: UVs stay even


def ops() -> list[dict]:
    body = box(span(-W / 2, W / 2, 6), span(-D / 2, D / 2, 4), PLANKS_Z)
    lid = box(span(-W / 2 - 6, W / 2 + 6, 6), span(-D / 2 - 6, D / 2 + 6, 8), [H - 2, H + 30])
    ar = _arch(D / 2 + 6)
    lid.map(lambda V: _lift(V, H - 2, ar))
    blocks = [body, lid]
    yb = D / 2 + 8
    for x in STRAP_X:                           # iron is plate on the surface, not slabs through the wood
        for sy in (-1, 1):
            blocks.append(box([x - 22, x + 22], sorted([sy * (D / 2 + 7), sy * (D / 2 - 3)]), [26, H - 3],
                              crease=0).region("iron"))
            blocks.append(box([x - 24, x + 24], sorted([sy * (D / 2 + 10), sy * (D / 2 + 3)]), [H - 2, H + 62],
                              crease=0).region("iron"))
        band = box([x - 24, x + 24], span(-yb, yb, 7), [H + 26, H + 38], crease=0).region("iron")
        band.map(lambda V: _lift(V, H + 20, ar))
        blocks.append(band)
    for sy in (-1, 1):
        blocks.append(box([-W / 2 - 7, W / 2 + 7], sorted([sy * (D / 2 + 7), sy * (D / 2 - 3)]), [-8, 30],
                          crease=0).region("iron"))
    for sx in (-1, 1):
        blocks.append(box(sorted([sx * (W / 2 + 7), sx * (W / 2 - 3)]), [-D / 2 - 2, D / 2 + 2], [-8, 30],
                          crease=0).region("iron"))
    plate = box([-50, 50], [-D / 2 - 16, -D / 2 + 4], [196, 286], crease=0).region("gold")
    plate.region("lockface", plate.faces_where(lambda c: c[1] < -D / 2 - 15))
    blocks.append(plate)
    o = start(blocks)
    yf = -D / 2 - 16
    o += [
        # the large blocks' border edges were creased: a wide bevel, its borders crisp
        {"op": "bevel", "edges": {"creased": True}, "width": 7.0, "segments": 2, "profile": 0.5, "crease": 1.0},
        # every edge still sharper than 70 deg is a small block's: a narrow bevel
        {"op": "bevel", "edges": {"angle_deg": 70}, "width": 2.5, "segments": 2, "profile": 0.5, "crease": 1.0},
        {"op": "inset", "faces": {"region": "lockface"}, "thickness": 9.0, "depth": -3.0, "crease": 1.0},
    ]
    # bake-only detail ----------------------------------------------------------------------------------------------
    o.append({"op": "kit_place", "part": "latch_draw", "params": {"width": 46.0, "length": 120.0},
              "at": [[0.0, yf + 3.0, 262.0]], "normal": [0, -1, 0], "name": "iron", "high_only": True})
    for z in PLANKS_Z[1:-1]:
        o.append({"op": "panel_line", "edges": {"box": [[-W, -D, z - 0.4], [W, D, z + 0.4]]}, "width": 7.0,
                  "depth": 4.0, "crease": 1.0, "high_only": True})
    for y in (-D / 2 - 6 + (D + 12) * k / 4 for k in (1, 2, 3)):
        o.append({"op": "panel_line", "edges": {"box": [[-W, y - 0.4, H + 31], [W, y + 0.4, H + 200]]},
                  "width": 7.0, "depth": 4.0, "crease": 1.0, "high_only": True})
    rivets = []
    for x in STRAP_X:
        for z in (60.0, 150.0, 240.0):
            rivets += [[x, -D / 2 - 7, z, 0, -1, 0], [x, D / 2 + 7, z, 0, 1, 0]]
    for p, n in _groups(rivets):
        o.append({"op": "kit_place", "part": "rivet_dome", "params": {"diameter": 13.0, "height": 5.0},
                  "at": p, "normal": n, "name": "iron", "high_only": True})
    o.append({"op": "kit_place", "part": "rivet_dome", "params": {"diameter": 12.0, "height": 4.5},
              "at": [[x, y, H + 200] for x in STRAP_X for y in (-120.0, 0.0, 120.0)],
              "snap": True, "name": "iron", "high_only": True})
    return o


def _lift(V, base, arch):
    """Raise a box's top points into a barrel arch over Y."""
    top = V[:, 2] > base + 1.0
    V[top, 2] += [arch(y) for y in V[top, 1]]
    return V


def _groups(rows):
    """[(points, normal)] from rows [x, y, z, nx, ny, nz] grouped by normal."""
    g: dict = {}
    for x, y, z, *n in rows:
        g.setdefault(tuple(n), []).append([x, y, z])
    return [(p, list(n)) for n, p in g.items()]
