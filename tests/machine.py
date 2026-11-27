"""How fast this machine is, for the tests whose limit is a time.

A time limit set on one machine is wrong on another: the hero helmet builds in 28 s on the laptop its 45 s limit
was set on, and in 50 to 120 s on a CI runner, with the same code. speed() times a fixed piece of the kind of work
those tests do (a loft, a shell, cuts, fillets, a tessellation in the CAD kernel, and a loop in Python) and returns
how many times slower this machine did it than the reference machine: 1.0 there, never less than 1.0. A test
multiplies its limit by it, so the limit says "no slower than this, for this machine", and a build that became
twice as slow fails on every machine alike.

FORM_TEST_SPEED=2.5 sets the factor by hand (0 or unset: measure).
"""
from __future__ import annotations

import os
import time

REFERENCE_S = 0.5          # seconds work() takes on the reference machine (an Apple M5 Pro; the best of three runs)
CEILING = 12.0             # a machine slower than this many times is reported as this (the limits stay finite)
_measured: list[float] = []


def work() -> None:
    """The fixed job: about half a second of kernel work and a little Python on the reference machine."""
    from build123d import Axis, Box, Circle, Cylinder, Plane, Pos, Rot, fillet, loft, offset
    sections = [Plane.XY.offset(z) * Rot(0, 0, 7 * i) * Circle(20 - i) for i, z in enumerate((0, 8, 16, 24, 32))]
    body = loft([s.face() for s in sections])
    shell = offset(body, amount=-1.5, openings=body.faces().sort_by(Axis.Z)[-1:])
    for k in range(8):
        shell = shell - Rot(0, 0, 45 * k) * Pos(18, 0, 6 + 2 * k) * Rot(0, 90, 0) * Cylinder(2.2, 12)
    block = Pos(0, 0, -3) * Box(44, 44, 6)
    block = fillet(block.edges().filter_by(Axis.Z), 3)
    part = shell + block
    part.tessellate(0.02)
    acc = 0.0
    for i in range(400_000):                        # plain Python: what the readers of meshes and slices spend
        acc += (i % 7) * 0.5
    assert part.is_valid and acc > 0


def measure(runs: int = 3) -> float:
    """Seconds for work(), the best of `runs` (the first run also loads the kernel, so it is not counted)."""
    work()
    best = float("inf")
    for _ in range(runs):
        t = time.perf_counter()
        work()
        best = min(best, time.perf_counter() - t)
    return best


def speed(fresh: bool = False) -> float:
    """How many times slower than the reference machine this one is right now (>= 1.0). Measured once per process;
    fresh=True measures again (a test that runs minutes after the first one, on a machine whose load changes)."""
    forced = float(os.environ.get("FORM_TEST_SPEED") or 0)
    if forced > 0:
        return forced
    if fresh or not _measured:
        _measured.append(measure())
    return min(CEILING, max(1.0, _measured[-1] / REFERENCE_S))


if __name__ == "__main__":
    s = measure()
    print(f"work(): {s:.3f} s; speed {min(CEILING, max(1.0, s / REFERENCE_S)) if REFERENCE_S else float('nan'):.2f}")
