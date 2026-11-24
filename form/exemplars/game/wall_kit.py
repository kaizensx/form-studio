"""Modular wall kit piece: 2 m x 2.4 m on a 0.5 m grid, its whole face in staggered bricks that tile into the next
piece, a plinth and a coping trim, and some damage.

How it is made: one slab exactly on the grid (x -1000..1000, z 0..2400, 250 thick; pivot at the bottom centre),
its front built as brick cells, one polygon per brick, laid in stretcher bond with half bricks at both ends, so two
pieces side by side continue the bond (the end joints are half joints: two pieces meet in one full joint). The plinth
and the coping are the slab's own front and back strips extruded (no block buried in another, so no hidden faces waste
texels); creased edges get one bevel, the extrusions another.
Bake-only (high_only): every brick cell inset with its joint and raised 12 mm, its border creased with the corner
points pinned (form/refine/ops_cage.crisp: a third creased edge makes each one a subdivision corner), so each brick is
a block with true corners, not a creased quad that subdivides into a pill; the flat brick faces need no support loops.
The bricks live in the normal map, ambient occlusion and cavity dirt while the LODs stay a light slab. Damage: three
bricks sunk to a 3 mm relief and four brick corners knocked back. Trim: the coping cut into stones at a constant
400 mm pitch. The back is ashlar: courses two brick rows high, 600 mm blocks, head joints staggered.
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
RELIEF = 12.0                                    # how far a brick stands out of its joint, mm (bake source)
FACE = -T / 2
# the brick cells only: bevel faces next to a cell inherit its region, so the region alone also holds slivers of the
# edge bevels; the cells' centres lie within 2.5 mm of the front plane (the end cells lean into the edge bevels), the
# slivers' lie at the very ends or along the plinth and the coping
FRONT = [[-W / 2 + 10, FACE - 2.5, PLINTH + 5], [W / 2 - 10, FACE + 2.5, H - COPING - 5]]


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


CHIPPED = ((1, 1, 0, 1), (4, 3, 1, 1), (7, 2, 0, 0), (9, 4, 1, 0))    # (row, brick, right?, top?): a knocked corner


def _corner(r: int, k: int, right: int, top: int) -> list[float]:
    """The brick top's corner point after the 6 mm joint inset and the raise."""
    js, zr = joints(r), rows()
    x = js[k + 1] - 6.0 if right else js[k] + 6.0
    z = zr[r + 1] - 6.0 if top else zr[r] + 6.0
    return [x, FACE - RELIEF, z]


def back_lines() -> list[dict]:
    """The back as ashlar: a bed joint every two brick rows, 600 mm blocks, the head joints of every other course moved
    a third of a block."""
    from ...refine.ops_cage import panel_line
    zr = rows()
    yb = T / 2
    ops = []
    for c in range(1, 5):
        z = zr[2 * c]
        ops.append(panel_line({"box": [[-W / 2 - 1, yb - 0.5, z - 0.5], [W / 2 + 1, yb + 0.5, z + 0.5]]}, 8.0, 5.0,
                              high_only=True))
    for c in range(5):
        z0, z1 = zr[2 * c], zr[2 * c + 2]
        for x in [-W / 2 + 600.0 * k - (200.0 if c % 2 else 0.0) for k in range(1, 4)]:
            ops.append(panel_line({"box": [[x - 0.5, yb - 0.5, z0 + 0.5], [x + 0.5, yb + 0.5, z1 - 0.5]]}, 8.0,
                                  5.0, high_only=True))
    return ops


def trim_joints() -> list[dict]:
    """The coping as stones: a joint across it at a constant 400 mm pitch (the end stones half as long, so the joints
    continue into the next piece). The plinth stays one run: its joints would cost the bake source more faces than a
    design source may hold."""
    from ...refine.ops_cage import panel_line
    return [panel_line({"box": [[x - 0.5, -T, H - COPING - 0.5], [x + 0.5, T, H + 60]]}, 6.0, 4.0, high_only=True)
            for x in (-600.0, -200.0, 200.0, 600.0)]


def ops() -> list[dict]:
    from ...refine.ops_cage import crisp
    o = start([slab()])
    o += [
        {"op": "extrude_region", "faces": {"region": "plinth_f"}, "offset": 34.0},
        {"op": "extrude_region", "faces": {"region": "plinth_b"}, "offset": 20.0},
        {"op": "extrude_region", "faces": {"region": "coping_f"}, "offset": 40.0},
        {"op": "extrude_region", "faces": {"region": "coping_b"}, "offset": 40.0},
        {"op": "bevel", "edges": {"creased": True}, "width": 6.0, "segments": 2, "profile": 0.5, "crease": 1.0},
        {"op": "bevel", "edges": {"angle_deg": 70}, "width": 4.0, "segments": 2, "profile": 0.5, "crease": 1.0},
    ]
    # bake-only: the stone joints first (on the plain slab), then every brick a raised block with its joint round it
    o += back_lines() + trim_joints()
    o += [
        {"op": "inset", "faces": {"region": "cells", "box": FRONT}, "thickness": 6.0, "depth": RELIEF,
         "individual": True, "name": "bricktop", "high_only": True},
        {"op": "inset", "faces": {"region": "sunk", "box": FRONT}, "thickness": 6.0, "depth": 3.0,
         "individual": True, "name": "bricktop", "high_only": True},
        # the brick material's region (a region of its own for the creases: "brick" also holds bevel slivers)
        {"op": "name_region", "name": "brick", "faces": {"region": "bricktop"}, "high_only": True},
    ]
    for r, k, right, top in CHIPPED:                         # damage: a corner knocked back into the brick
        x, y, z = _corner(r, k, right, top)
        o.append({"op": "move", "verts": {"box": [[x - 1, y - 1, z - 1], [x + 1, y + 1, z + 1]]},
                  "by": [-14.0 if right else 14.0, 9.0, -11.0 if top else 11.0], "high_only": True})
    # each brick's border creased with its corners pinned: true corners, not pills
    o += crisp("bricktop", high_only=True)
    return o
