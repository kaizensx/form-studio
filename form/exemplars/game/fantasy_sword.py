"""Fantasy sword: a tapered blade with a real fuller recess and ground edges, a swept crossguard, a leather-wrapped
grip and a pear-shaped pommel.

How it is made: the blade is one block whose cross-section is a flat middle ground down to a thin edge (the grind
line a soft crease), tapered to the point; its fuller faces are named at the start and inset as a recess on both
sides. The guard is a block swept up at the ends; the grip a rounded prism; the pommel a rounded prism profiled
like a pear.
Edges: a fine bevel on the creased edges, a wider one on every remaining hard edge. Bake-only (high_only): the
leather wrap round the grip.
"""
from __future__ import annotations

import numpy as np

from .base import box, quad_sphere, span, start

TITLE = "Fantasy sword"
ORIGINALITY = ("An original arming-sword shape from generic sword anatomy (fuller, ground edges, a swept guard, a "
               "wrapped grip, a faceted pommel). It reproduces no named weapon from a game, film or book.")
MATERIALS = {"default": {"material": "bare_metal", "tint": "#a27c38", "grain_mm": 10, "wear": 0.55},
             "blade": {"material": "brushed_metal", "tint": "#c4c9cf", "grain_mm": 22, "wear": 0.35},
             "fuller": {"material": "brushed_metal", "tint": "#8f969d", "grain_mm": 14, "wear": 0.3},
             "grip": {"material": "leather", "tint": "#3f2517", "grain_mm": 3, "wear": 0.5},
             "pommel": {"material": "bare_metal", "tint": "#a27c38", "grain_mm": 10, "wear": 0.6}}

W, T, Z0, Z1 = 31.0, 4.6, 80.0, 880.0


def _blade():
    b = box(np.array([-1, -0.55, -0.22, 0.22, 0.55, 1]) * W, [-T, T], span(Z0, Z1, 12), crease=1.0)
    b.region("blade")
    b.region("fuller", b.faces_where(lambda c: abs(c[0]) < 0.22 * W and 110 < c[2] < 620 and abs(c[1]) > T - 0.1))

    def shape(V):
        t = (V[:, 2] - Z0) / (Z1 - Z0)
        edge = np.abs(V[:, 0]) > 0.99 * W
        V[edge, 1] *= 0.16                                     # the cutting edge: a thin flat between the grinds
        tip = np.clip((t - 0.82) / 0.18, 0, 1)
        V[:, 0] *= (1 - 0.28 * t) * (1 - 0.94 * tip ** 1.3)
        V[:, 1] *= (1 - 0.35 * t) * (1 - 0.6 * tip)
        return V
    b.map(shape)
    return b


def _round_prism(r, zs, region):
    p = box(span(-1, 1, 2), span(-1, 1, 2), zs, crease=0)

    def disc(V):
        x, y = V[:, 0].copy(), V[:, 1].copy()
        V[:, 0] = x * np.sqrt(1 - y * y / 2) * r
        V[:, 1] = y * np.sqrt(1 - x * x / 2) * r
        return V
    return p.map(disc).region(region)


def _profile(V, radius_at_z):
    for i in range(len(V)):
        r = radius_at_z[min(radius_at_z, key=lambda z: abs(z - V[i, 2]))]
        V[i, :2] *= r
    return V


def ops() -> list[dict]:
    blade = _blade()
    guard = box(span(-130, 130, 8), [-14, 14], [48, 82], crease=0).region("guard")

    def sweep(V):
        x = V[:, 0]
        V[:, 2] += 0.0016 * x * x                                 # the arms sweep up towards the blade
        V[:, 1] *= 1 - 0.45 * (np.abs(x) / 130) ** 2              # and thin out to the tips
        return V
    guard.map(sweep)
    block = box([-27, 27], [-18, 18], [42, 100], crease=0).region("guard")
    grip = _round_prism(15.5, span(-112, 46, 4), "grip")
    pommel = _round_prism(1.0, [-168, -158, -140, -124, -114, -106], "pommel")
    prof = {-168: 12.0, -158: 22.0, -140: 27.0, -124: 24.0, -114: 15.0, -106: 13.0}
    pommel.map(lambda V: _profile(V, prof))
    # the guard's terminals: a flattened knob on each swept arm (the arms end in a shape, not a cut), and the peen
    # block under the pommel; they carry the brass to the ends of the silhouette
    tips = [quad_sphere(2, (15.0, 9.0, 13.0), (sx * 136.0, 0.0, 92.0)).region("pommel") for sx in (-1, 1)]
    peen = quad_sphere(2, (9.0, 9.0, 7.0), (0.0, 0.0, -170.0)).region("pommel")
    # the block steps down into the blade (a langet): it is narrower at the top than where it meets the arms
    block.map(lambda V: V * np.c_[1 - 0.3 * np.clip((V[:, 2] - 82) / 18, 0, 1), np.ones(len(V)), np.ones(len(V))])
    o = start([blade, guard, block, grip, pommel, peen] + tips)
    o += [
        {"op": "inset", "faces": {"region": "fuller"}, "thickness": 1.4, "depth": -1.6, "crease": 1.0},
        {"op": "bevel", "edges": {"creased": True}, "width": 0.45, "segments": 1, "profile": 0.5, "crease": 1.0},
        {"op": "bevel", "edges": {"angle_deg": 70}, "width": 2.2, "segments": 2, "profile": 0.5, "crease": 1.0},
        # bake-only: the leather wrap
        {"op": "kit_place", "part": "grip_wrap", "params": {"radius": 15.0, "length": 150.0, "turns": 9, "band": 13.0},
         "at": [[0.0, 0.0, -108.0]], "normal": [0, 0, 1], "name": "grip", "high_only": True},
    ]
    return o
