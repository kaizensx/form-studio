"""Sci-fi helmet prop: a shaped shell with a recessed visor, raised cheek plates with vents, a crest and panel lines.

How it is made: one quad-sphere shell squared towards a rounded box and pushed into a helmet (a flatter crown, a longer
back, a jaw that comes forward, a flat neck line), its visor and cheek faces named at the start; inset makes the visor a
recess and the cheek plates raised panels; the crest is its own bevelled block riding the shell's curve. Bake-only
(high_only): panel lines round the back and down the middle, louvre vents and cap screws on the cheek plates, a round
grille at the back.
"""
from __future__ import annotations

import numpy as np

from .base import box, quad_sphere, span, start

TITLE = "Sci-fi helmet prop"
ORIGINALITY = ("An original helmet built from generic hard-surface vocabulary (a recessed visor, cheek plates, a "
               "crest, vents, panel lines). It is no franchise's helmet: no character's visor shape, crest or "
               "markings were referenced; the proportions and layout were chosen here.")
MATERIALS = {"default": {"material": "painted_metal", "tint": "#d8d3c6", "grain_mm": 20, "wear": 0.55},
             "visor": {"material": "plastic", "tint": "#141c24", "roughness": 0.12, "wear": 0.15},
             "cheek": {"material": "painted_metal", "tint": "#b8492a", "grain_mm": 16, "wear": 0.65},
             "crest": {"material": "painted_metal", "tint": "#34383d", "grain_mm": 16, "wear": 0.6}}

RX, RY, RZ, CZ = 118.0, 148.0, 140.0, 150.0


def _cube(p):
    """A unit-sphere point's position on the cube it was projected from (the quad sphere's grid lines are straight
    there)."""
    p = np.asarray(p, float)
    return p / np.max(np.abs(p), axis=-1, keepdims=True)


def _shape(U):
    """Unit-sphere points to the helmet: squared towards a rounded box (no egg), the crown flattened, the neck line
    flat, the jaw brought forward and the back flared over the neck."""
    C = _cube(U)
    P = 0.76 * U + 0.24 * C * 0.86
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    low = np.clip(-z, 0, 1)
    front = np.clip(-y, 0, 1)
    back = np.clip(y, 0, 1)
    X = x * RX * (1 + 0.08 * back * low) * (1 - 0.12 * front * low)
    Y = y * RY - 26 * front * low ** 1.3 + 16 * back * low ** 1.5
    Z = CZ + z * RZ * np.where(z > 0, 0.9, 1.0)
    Z = np.where(Z < 42, 42 + (Z - 42) * 0.15, Z)
    return np.c_[X, Y, Z]


def shell_z(y):
    """The shell's top along the middle (x = 0) at y, from the shape itself."""
    t = np.linspace(-1.2, 1.2, 721)
    U = np.c_[np.zeros_like(t), np.sin(t), np.cos(t)]
    S = _shape(U)
    return np.interp(y, S[:, 1], S[:, 2])


def ops() -> list[dict]:
    s = quad_sphere(6)
    U = s.V.copy()
    cc = lambda c: _cube(c)                                    # noqa: E731 - face centres in cube coordinates
    s.region("visor", s.faces_where(lambda c: (cc(c)[1] < -0.99 and abs(cc(c)[0]) < 0.67 and -0.4 < cc(c)[2] < 0.3)
                                    or (abs(cc(c)[0]) > 0.99 and cc(c)[1] < -0.67 and -0.4 < cc(c)[2] < 0.3)))
    s.region("cheek", s.faces_where(lambda c: abs(cc(c)[0]) > 0.99 and -0.6 < cc(c)[1] < 0.34
                                    and -0.7 < cc(c)[2] < -0.05))
    s.map(lambda V: _shape(U))
    crest = box([-11, 11], span(-80, 150, 10), [0, 1], crease=1.0).region("crest")

    def ride(V):
        for i, (x, y, z) in enumerate(V):
            base = float(shell_z(y))
            rise = 30 * min(1.0, (y + 80) / 60) * (1 - 0.55 * max(0.0, (y - 40) / 110))
            V[i, 2] = base - 14 if z < 0.5 else base + rise
            V[i, 0] = x * (0.55 if z > 0.5 else 1.0)
        return V
    crest.map(ride)
    o = start([s, crest])
    o += [
        {"op": "inset", "faces": {"region": "visor"}, "thickness": 7.0, "depth": -12.0, "crease": 1.0},
        {"op": "inset", "faces": {"region": "visor"}, "thickness": 2.5, "depth": 1.5, "crease": 1.0},
        {"op": "inset", "faces": {"region": "cheek"}, "thickness": 5.0, "depth": 7.0, "crease": 1.0},
        {"op": "bevel", "edges": {"creased": True}, "width": 2.5, "segments": 2, "profile": 0.5, "crease": 1.0},
    ]
    # bake-only detail ----------------------------------------------------------------------------------------------
    o += [
        {"op": "panel_line", "edges": {"box": [[-200, -10, CZ - 0.5], [200, 300, CZ + 0.5]]}, "width": 4.0,
         "depth": 2.5, "crease": 1.0, "high_only": True},
        {"op": "panel_line", "edges": {"box": [[-0.5, 40, 0], [0.5, 300, 250]]}, "width": 4.0, "depth": 2.5,
         "crease": 1.0, "high_only": True},
    ]
    cz = CZ - RZ * 0.33
    for sx in (-1, 1):
        cx = sx * RX * 0.93
        o.append({"op": "kit_place", "part": "vent_louver", "params": {"width": 46.0, "height": 30.0, "depth": 3.0,
                                                                       "slats": 4},
                  "at": [[cx, -22.0, cz]], "snap": True, "name": "crest", "high_only": True})
        o.append({"op": "kit_place", "part": "cap_screw", "params": {"diameter": 6.0, "height": 2.5},
                  "at": [[cx, y, z] for y, z in ((-48.0, cz + 26), (10.0, cz + 26), (-48.0, cz - 26),
                                                 (10.0, cz - 26))],
                  "snap": True, "name": "crest", "high_only": True})
    o.append({"op": "kit_place", "part": "grille_round", "params": {"diameter": 50.0, "depth": 3.0},
              "at": [[0.0, RY + 20, CZ - 60]], "snap": True, "name": "crest", "high_only": True})
    return o
