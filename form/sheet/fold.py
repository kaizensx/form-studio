"""Folding a flat pattern back, from the flat pattern's own data (numpy only, no kernel).

The flat lies in its frame's XY plane; the unfolded skin is z = 0 and the sheet's material is z ∈ [-t, 0]. A bend
is read from the flat alone: its zone's start line (a point q and the direction u along it), the direction d into
the zone, the zone's width w (the bend allowance), the bend angle θ, its direction s (+1: the flange turns toward
+z, "up"; -1: "down"), the skin's radius R_s (the inside radius r for an up bend, r + t for a down bend) and the
neutral radius R_n = r + K·t, so that w = θ·R_n.

A point of the zone at distance x into it lies on the skin's arc at angle φ = x / R_n; a point beyond the zone is
carried rigidly with the arc's end. Points beyond several bends are folded deepest bend first: a parent bend moves
its children's already folded material as one rigid piece.

    fold(points, z, path, zone, bends, amount=None)   # amount: {bend id: fraction 0..1} for a part on the brake

This is the check of form/sheet/unfold.py: every sample of the solid is laid flat by the unfold, folded back here
from the flat pattern's numbers, and must land where it came from.
"""
from __future__ import annotations

import math

import numpy as np


def _frame(b: dict):
    q = np.array([b["q"][0], b["q"][1], 0.0])
    u = np.array([b["u"][0], b["u"][1], 0.0])
    d = np.array([b["d"][0], b["d"][1], 0.0])
    return q, u, d, np.array([0.0, 0.0, 1.0])


def fold_one(P: np.ndarray, b: dict, zone: bool, frac: float = 1.0) -> np.ndarray:
    """Fold points P (n, 3) about one bend: zone=True for points inside its zone, else points beyond it."""
    if frac <= 1e-9:
        return P
    q, u, d, ez = _frame(b)
    R_s, R_n, w, s = float(b["R_s"]), float(b["R_n"]), float(b["w"]), float(b["s"])
    th = math.radians(float(b["angle"])) * frac
    if frac < 1.0:
        # part way down: the zone keeps its developed width on a wider arc (radius R_n / frac at the neutral fibre)
        R_s = R_s + (R_n / frac - R_n)
        R_n = R_n / frac
        frac = 1.0
    rel = P - q
    a = rel @ u
    x = rel @ d
    zz = rel @ ez
    if zone:
        phi = x / R_n * frac if R_n > 0 else np.zeros_like(x)
        R = R_s - s * zz
        pd = R * np.sin(phi)
        pz = s * R_s - s * R * np.cos(phi)
    else:
        ad, az = R_s * math.sin(th), s * R_s - s * R_s * math.cos(th)
        L = x - w * frac
        pd = ad + L * math.cos(th) - zz * s * math.sin(th)
        pz = az + L * s * math.sin(th) + zz * math.cos(th)
    return q + a[:, None] * u + pd[:, None] * d + pz[:, None] * ez


def fold(points, z, path: list, zone: int | None, bends: dict, amount: dict | None = None) -> np.ndarray:
    """Fold flat points (n, 2) at heights z (scalar or (n,)) that all belong to one region: `path` the bend ids from
    the base to the region (outermost first), `zone` the bend whose zone the region is (or None)."""
    P = np.asarray(points, float)
    n = len(P)
    Z = np.broadcast_to(np.asarray(z, float), (n,))
    X = np.column_stack([P[:, 0], P[:, 1], Z])
    amount = amount or {}
    for k, bid in enumerate(reversed(path)):
        b = bends[bid]
        f = float(amount.get(bid, 1.0))
        X = fold_one(X, b, zone=(k == 0 and zone == bid), frac=f)
    return X


def to_world(X: np.ndarray, frame: dict) -> np.ndarray:
    o = np.asarray(frame["origin"], float)
    M = np.array([frame["x"], frame["y"], frame["z"]], float)
    return o + np.asarray(X, float) @ M
