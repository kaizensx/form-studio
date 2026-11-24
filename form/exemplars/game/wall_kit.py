"""Modular wall kit piece: 2 m x 2.4 m on a 0.5 m grid, its whole face in staggered bricks that tile into the next
piece, a plinth and a coping trim, and some damage.

How it is made: one slab exactly on the grid (x -1000..1000, z 0..2400, 250 thick; pivot at the bottom centre),
its front built as brick cells, one polygon per brick, laid in stretcher bond with half bricks at both ends, so two
pieces side by side continue the bond. The plinth and the coping are the slab's own front and back strips extruded
(no block buried in another, so no hidden faces waste texels); creased edges get one bevel, the extrusions another.
Bake-only (high_only): every brick cell inset with its joint and raised 12 mm, so the bricks live in the normal map,
ambient occlusion and cavity dirt while the LODs stay a light slab. Damage: three bricks sunk to a 3 mm relief.
Known weakness: the creased brick faces still bake as rounded "pills" (their corners are crease vertices, not
corners), and the back is plain.
"""
from __future__ import annotations

import numpy as np

from .base import Block, box, start

TITLE = "Modular wall kit piece"
ORIGINALITY = ("An original modular wall built from generic masonry (stretcher-bond brick, plinth, coping). Sizes "
               "follow a 0.5 m kit grid chosen here; it copies no game's kit.")
MATERIALS = {"default": {"material": "stone", "tint": "#9a958c", "grain_mm": 40, "wear": 0.4},
             "brick": {"material": "stone", "tint": "#8c4f38", "grain_mm": 30, "wear": 0.65},
             "trim": {"material": "stone", "tint": "#6f6c66", "grain_mm": 70, "wear": 0.6}}

W, H, T = 2000.0, 2400.0, 250.0
PLINTH, COPING = 150.0, 120.0
ROWS, JOINT, BRICK_L = 10, 12.0, 400.0
FACE = -T / 2


def rows() -> list[float]:
    rh = (H - PLINTH - COPING) / ROWS
    return [PLINTH + r * rh for r in range(ROWS + 1)]


def joints(r: int) -> list[float]:
    """The vertical joints of row r (stretcher bond: odd rows start and end with half a brick)."""
    if r % 2 == 0:
        return [-W / 2 + k * BRICK_L for k in range(6)]
    return [-W / 2] + [-W / 2 + BRICK_L / 2 + k * BRICK_L for k in range(5)] + [W / 2]


SUNK = {(3, 2), (6, 4), (8, 1)}                  # (row, brick): sunk to a 3 mm relief (damage)


def _merge(faces):
    """One polygon from adjacent polygons (their shared edges dropped), orientation kept."""
    es = [(f[k], f[(k + 1) % len(f)]) for f in faces for k in range(len(f))]
    s = set(es)
    left = [e for e in es if (e[1], e[0]) not in s]
    nxt = dict(left)
    start = left[0][0]
    loop, v = [start], nxt[start]
    while v != start:
        loop.append(v)
        v = nxt[v]
    return loop


def slab() -> Block:
    """The core slab, its front made of brick cells (one polygon per brick: two grid quads, or one at the ends)."""
    xs = [-W / 2 + 200.0 * k for k in range(11)]
    zr = rows()
    zs = [0.0] + zr + [H]
    b = box(xs, [FACE, T / 2], zs, crease=1.0)
    cen = [b.V[f].mean(0) for f in b.F]
    front = {}
    for i, c in enumerate(cen):
        if abs(c[1] - FACE) < 1e-6:
            front[(int(np.searchsorted(xs, c[0])) - 1, int(np.searchsorted(zs, c[2])) - 1)] = i
    keep = [i for i in range(len(b.F)) if i not in front.values()]
    F = [b.F[i] for i in keep]
    reg: dict = {k: [] for k in ("cells", "brick", "sunk", "trim", "plinth_f", "plinth_b", "coping_f", "coping_b")}
    for i, c in zip(range(len(F)), [cen[k] for k in keep]):
        if abs(c[1] - T / 2) < 1e-6 and c[2] < PLINTH:
            reg["plinth_b"].append(i)
        if abs(c[1] - T / 2) < 1e-6 and c[2] > H - COPING:
            reg["coping_b"].append(i)
    for (ix, iz), fi in front.items():
        if iz == 0 or iz == ROWS + 1:
            reg["plinth_f" if iz == 0 else "coping_f"].append(len(F))
            F.append(b.F[fi])
    for r in range(ROWS):
        js = joints(r)
        for k in range(len(js) - 1):
            cols = [ix for ix in range(10) if js[k] - 1e-6 <= xs[ix] and xs[ix + 1] <= js[k + 1] + 1e-6]
            for name in (("brick", "sunk") if (r, k) in SUNK else ("cells",)):
                reg[name].append(len(F))
            F.append(_merge([b.F[front[(ix, r + 1)]] for ix in cols]))
    reg["trim"] = reg["plinth_f"] + reg["plinth_b"] + reg["coping_f"] + reg["coping_b"]
    out = Block(b.V, F, b.creases)
    for k, v in reg.items():
        out.region(k, v)
    return out


def ops() -> list[dict]:
    o = start([slab()])
    o += [
        {"op": "extrude_region", "faces": {"region": "plinth_f"}, "offset": 34.0},
        {"op": "extrude_region", "faces": {"region": "plinth_b"}, "offset": 20.0},
        {"op": "extrude_region", "faces": {"region": "coping_f"}, "offset": 40.0},
        {"op": "extrude_region", "faces": {"region": "coping_b"}, "offset": 40.0},
        {"op": "bevel", "edges": {"creased": True}, "width": 6.0, "segments": 2, "profile": 0.5, "crease": 1.0},
        {"op": "bevel", "edges": {"angle_deg": 70}, "width": 4.0, "segments": 2, "profile": 0.5, "crease": 1.0},
        # bake-only: every brick a raised block with its joint round it
        {"op": "inset", "faces": {"region": "cells"}, "thickness": 6.0, "depth": 12.0, "individual": True,
         "crease": 1.0, "name": "brick", "high_only": True},
        {"op": "inset", "faces": {"region": "sunk"}, "thickness": 6.0, "depth": 3.0, "individual": True,
         "crease": 1.0, "name": "brick", "high_only": True},
        # each brick face's own border sharp too, so subdivision keeps them blocks (not pebbles)
        {"op": "crease", "region_boundary": "brick", "value": 1.0, "high_only": True},
    ]
    return o
