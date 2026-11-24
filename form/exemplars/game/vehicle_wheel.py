"""Vehicle wheel for an off-road game vehicle: a fat tyre with a baked lug tread, a rim ring with five open spokes,
a hub with a cap and lug nuts.

How it is made: the tyre and the rim are one lathed ring round the axle (Y), the rim barrel and lips inside the tyre's
beads (one shell, so no face is buried), named by region; the hub is another ring; profile corners are creased and
bevelled; five tapered spoke blocks run from the hub to the rim with open space between them, so the
wheel reads as spoked from the side. Bake-only (high_only): two staggered rows of tread lugs round the tyre and
five lug nuts on the hub, from the kit.
"""
from __future__ import annotations

import math

import numpy as np

from .base import box, lathe, quad_sphere, rotate, start

TITLE = "Vehicle wheel"
ORIGINALITY = ("An original off-road wheel (lug tread, five-spoke rim, hub with lug nuts) from generic wheel anatomy. "
               "No maker's rim design, tread pattern, logo or lettering.")
MATERIALS = {"default": {"material": "bare_metal", "tint": "#8d9196", "grain_mm": 12, "wear": 0.5},
             "tyre": {"material": "rubber", "tint": "#242424", "grain_mm": 6, "wear": 0.4},
             "rim": {"material": "painted_metal", "tint": "#b4b9be", "grain_mm": 20, "wear": 0.6},
             "hub": {"material": "bare_metal", "tint": "#6e7277", "grain_mm": 10, "wear": 0.5}}

R_TYRE = 335.0


def _ring_creases(b, prof_pts):
    """Crease the lathe rings at the given profile points."""
    keys = {(round(r, 3), round(h, 3)) for r, h in prof_pts}

    def on(p):
        return (round(math.hypot(p[0], p[2]), 3), round(p[1], 3)) in keys
    return b.crease(lambda p, q: on(p) and on(q) and abs(p[1] - q[1]) < 1e-6 and
                    abs(math.hypot(p[0], p[2]) - math.hypot(q[0], q[2])) < 1e-6)


def ops() -> list[dict]:
    # tyre and rim are one lathed ring (nothing buried): the rim barrel inside, the rim lips, the tyre round them
    prof = [(206, -100), (206, 100), (236, 100), (238, 108), (246, 116), (298, 123), (322, 113), (333, 85),
            (R_TYRE, 0), (333, -85), (322, -113), (298, -123), (246, -116), (238, -108), (236, -100)]
    wheel = lathe(prof, 32, "y")
    on_tyre = {(246, 116), (298, 123), (322, 113), (333, 85), (R_TYRE, 0), (333, -85), (322, -113), (298, -123),
               (246, -116)}
    ring = lambda p: (round(math.hypot(p[0], p[2])), round(p[1]))      # noqa: E731
    wheel.region("tyre", wheel.faces_where(lambda c: False))
    wheel.regions["tyre"] = [i for i, f in enumerate(wheel.F)
                             if sum(ring(wheel.V[v]) in on_tyre for v in f) >= 2 and
                             all(ring(wheel.V[v]) in on_tyre | {(238, 108), (238, -108)} for v in f)]
    wheel.region("rim", [i for i in range(len(wheel.F)) if i not in set(wheel.regions["tyre"])])
    _ring_creases(wheel, [(206, -100), (206, 100), (236, 100), (236, -100), (238, 108), (238, -108)])
    hub_prof = [(34, -64), (92, -64), (104, -30), (104, 40), (34, 40)]
    hub = lathe(hub_prof, 20, "y").region("hub")
    _ring_creases(hub, hub_prof)
    cap = quad_sphere(2, (44, 16, 44), (0, -64, 0)).region("hub")
    blocks = [wheel, hub, cap]
    for k in range(5):
        s = box(np.array([-1, 1]), [-62, -22], [88, 218], crease=1.0)

        def taper(V):
            t = (V[:, 2] - 88) / 130
            V[:, 0] *= 30 - 12 * t                               # wide at the hub, slimmer at the rim
            V[:, 1] += 14 * t                                     # dished: the rim end sits further in
            return V
        s.map(taper)
        s.V = rotate(s.V, "y", 72 * k + 36)
        blocks.append(s.region("rim"))
    o = start(blocks)
    o += [{"op": "bevel", "edges": {"creased": True}, "width": 4.0, "segments": 2, "profile": 0.5, "crease": 1.0}]
    # bake-only detail ----------------------------------------------------------------------------------------------
    lugs = []
    for k in range(24):
        a = 2 * math.pi * (k + 0.5 * (k % 2)) / 24
        for y in ((-58.0,) if k % 2 else (58.0,)):
            lugs.append([R_TYRE * math.cos(a), y, R_TYRE * math.sin(a)])
        lugs.append([R_TYRE * math.cos(a + 0.1), 0.0 if k % 2 else 0.0, R_TYRE * math.sin(a + 0.1)])
    o.append({"op": "kit_place", "part": "stud_pyramid", "params": {"width": 34.0, "height": 13.0}, "at": lugs,
              "snap": True, "scale": [1.0, 1.9, 1.0], "name": "tyre", "high_only": True})
    nuts = [[62 * math.cos(2 * math.pi * k / 5), -64.0, 62 * math.sin(2 * math.pi * k / 5)] for k in range(5)]
    o.append({"op": "kit_place", "part": "hex_nut", "params": {"across_flats": 17.0, "height": 9.0, "stud": 4.0},
              "at": nuts, "normal": [0, -1, 0], "name": "hub", "high_only": True})
    return o
