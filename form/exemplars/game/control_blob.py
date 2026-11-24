"""The control: a deliberately bad game asset, so the critic and the blind passes can be checked. It must fail.

A lumpy egg: one quad sphere, stretched and pushed about a little, one grey plastic with no wear, no bevel, no
detail at any scale. It is what an asset made without a design looks like, and the bench publishes its scores next
to the six real ones.
"""
from __future__ import annotations

import numpy as np

from .base import quad_sphere

TITLE = "Control: plain blob"
ORIGINALITY = "A deliberately bad control (an egg in one grey material); not a design."
MATERIALS = {"default": {"material": "plastic", "tint": "#9a9893", "grain_mm": 4, "wear": 0.0}}


def cage():
    from ... import meshsource
    b = quad_sphere(3, (140, 110, 170), (0, 0, 170))
    V = b.V.copy()
    V[:, 0] += 12 * np.sin(V[:, 2] / 60.0)                  # a slight, aimless lean
    return meshsource.cage(V, b.F)
