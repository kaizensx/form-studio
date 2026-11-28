"""The verification suite of the strength studies: textbook cases with a known answer, solved by the same code path
a design's study takes (form/fea/core.py: meshing, picked faces, supports, loads, refinement, the stated error).

    <FEA engine's python> -m form.fea.verify [--json] [CASE ...]
    <FEA engine's python> -m form.fea.verify --bench          the timing case (a bracket), as JSON

Each case builds its solid with Netgen's OCCT, runs the study and compares named quantities with the closed-form
value. A row passes when the relative error is within the tolerance written in the case. The table in
docs/STRENGTH.md is this module's output (scripts/gen_strength_docs.py); tests/test_fea_verification.py runs it.

The reference formulas and where they are from:

* Beam deflection with shear (Timoshenko): Timoshenko and Gere, Mechanics of Materials; shear coefficient of a
  rectangle kappa = 10(1 + nu)/(12 + 11 nu) (Cowper 1966).
* Circular hole in a strip of finite width in tension: Howland (1930) as fitted by Heywood, in Pilkey, Peterson's
  Stress Concentration Factors, chart 4.1: Ktn = 2 + 0.284(1 - d/W) - 0.600(1 - d/W)^2 + 1.32(1 - d/W)^3 on the net
  section; for an infinite plate Kt = 3 (Kirsch 1898).
* Thick-walled cylinder under internal pressure: Lame (1852), plane strain.
* Bending frequencies of a uniform beam (Euler-Bernoulli): f = (beta L)^2 / (2 pi L^2) sqrt(E I / (rho A)) with
  beta L = 1.8751, 4.6941 (clamped-free) and 4.7300 (free-free); Blevins, Formulas for Natural Frequency and Mode
  Shape, table 8-1.
* Euler buckling of a clamped-free column: P = pi^2 E I / (4 L^2).
* Steady conduction through a plane wall with a convective side, and through a cylinder wall: Incropera and DeWitt,
  Fundamentals of Heat and Mass Transfer, chapter 3. Thermal stress in a long thick cylinder with steady radial heat
  flow: Timoshenko and Goodier, Theory of Elasticity, art. 151.
* Transversely isotropic (layered) material: Young's modulus along a direction at an angle to the axis of symmetry,
  1/E = cos^4/E_z + sin^4/E_p + (1/G_zp - 2 nu_zp/E_z) sin^2 cos^2 (Lekhnitskii, Theory of Elasticity of an
  Anisotropic Body, 1963; Jones, Mechanics of Composite Materials, 2nd ed., eq. 2.97); the Timoshenko beam with the
  modulus along the beam and the shear modulus of the bending plane.
* NAFEMS LE1 and LE10: The Standard NAFEMS Benchmarks, NAFEMS (1990), linear elastic tests 1 and 10; the target
  values are the published ones (92.7 MPa and -5.38 MPa for the direct stress yy at point D).
"""
from __future__ import annotations

import json
import math
import sys
import time

import numpy as np

STEEL = {"name": "steel (verification)", "E": 210000.0, "nu": 0.3, "density": 7850.0, "yield": 250.0}


def _mat(**kw):
    return [{**STEEL, **kw}]


def _face(*pts, area=None):
    r = {"samples": [list(map(float, p)) for p in pts]}
    if area:
        r["area"] = float(area)
    return r


def _probe(keep, point):
    X = keep["model"].sp.X
    return int(np.argmin(np.linalg.norm(X - np.asarray(point, float), axis=1)))


def _row(quantity, expected, got, tol, unit, source):
    err = abs(got - expected) / abs(expected)
    return {"quantity": quantity, "expected": expected, "got": got, "unit": unit, "error": err, "tolerance": tol,
            "pass": bool(err <= tol), "source": source}


# ---- cases -------------------------------------------------------------------------------------------------------

def cantilever():
    """Cantilever 100 x 10 x 10 mm, end load 100 N, nu = 0 (so a fully fixed end is the beam-theory clamp)."""
    from netgen.occ import Box, Pnt
    L, b, h, F, E = 100.0, 10.0, 10.0, 100.0, 210000.0
    shape = Box(Pnt(0, 0, 0), Pnt(L, b, h))
    spec = {"kind": "static", "materials": _mat(nu=0.0),
            "fixtures": [{"type": "fixed", "faces": [_face((0, 5, 5), area=b * h)]}],
            "loads": [{"type": "force", "faces": [_face((L, 5, 5), area=b * h)], "vector": [0, 0, -F]}]}

    def check(res, keep):
        I, A, G = b * h ** 3 / 12, b * h, E / 2
        eb = F * L ** 3 / (3 * E * I)
        tim = eb + F * L / ((10.0 / 12.0) * G * A)
        tip = -float(keep["u"][keep["model"].sp.X[:, 0] > L - 1e-6][:, 2].mean())
        k = _probe(keep, (L / 2, b / 2, h))                 # the mesh node nearest mid-span on the top fibre
        x, _, z = keep["model"].sp.X[k]
        return [_row("tip deflection", tim, tip, 0.01, "mm", "Timoshenko beam: F L^3/(3 E I) + F L/(kappa G A)"),
                _row("tip deflection (Euler-Bernoulli, no shear)", eb, tip, 0.015, "mm", "F L^3/(3 E I)"),
                _row("bending stress near mid-span, top fibre", F * (L - x) * (z - h / 2) / I, float(keep["stress"][k, 0]),
                     0.02, "MPa", "M c / I at that node"),
                _row("hand estimate: stress at the fixed end", F * L * (h / 2) / I,
                     (res["hand_estimate"].get("stress_at_fixed_end_MPa") or 0.0), 0.005, "MPa",
                     "M c / I; the estimate measures the section on the mesh"),
                _row("hand estimate: deflection at the load", eb, (res["hand_estimate"].get("deflection_at_load_mm") or 0.0),
                     0.005, "mm", "F L^3/(3 E I); the estimate measures the section on the mesh")]
    return shape, spec, check


def plate_with_hole():
    """Strip 200 x 100 x 2 mm with a 20 mm hole, 100 MPa tension; one eighth by symmetry (three roller planes).
    Solved to a stress tolerance of 2 %."""
    from netgen.occ import Box, Cylinder, Pnt, Z
    W2, L2, t2, r, s = 50.0, 100.0, 1.0, 10.0, 100.0
    shape = Box(Pnt(0, 0, 0), Pnt(L2, W2, t2)) - Cylinder(Pnt(0, 0, -1), Z, r=r, h=3)
    spec = {"kind": "static", "materials": _mat(), "mesh": {"tol_stress": 0.02},
            "fixtures": [{"type": "roller", "faces": [_face((0, 30, 0.5))]},
                         {"type": "roller", "faces": [_face((50, 0, 0.5))]},
                         {"type": "roller", "faces": [_face((50, 25, 0))]}],
            "loads": [{"type": "force", "faces": [_face((L2, 25, 0.5), area=W2 * t2)], "vector": [s * W2 * t2, 0, 0]}]}

    def check(res, keep):
        x = 1 - 2 * r / (2 * W2)
        ktn = 2 + 0.284 * x - 0.600 * x ** 2 + 1.32 * x ** 3
        ktg = ktn / x
        return [_row("peak stress at the hole / applied stress (Kt, gross)", ktg, res["peak_von_mises_MPa"] / s, 0.03, "",
                     "Howland/Heywood in Peterson, chart 4.1 (d/W = 0.2); Kirsch gives 3 for an infinite plate")]
    return shape, spec, check


def thick_cylinder():
    """Thick cylinder, inner radius 20, outer 40 mm, 100 MPa inside, plane strain; a quarter by symmetry.
    Solved to a stress tolerance of 2 %."""
    from netgen.occ import Box, Cylinder, Pnt, Z
    ri, ro, Lz, p = 20.0, 40.0, 10.0, 100.0
    shape = (Cylinder(Pnt(0, 0, 0), Z, r=ro, h=Lz) - Cylinder(Pnt(0, 0, -1), Z, r=ri, h=Lz + 2)) * Box(Pnt(0, 0, 0), Pnt(50, 50, Lz))
    c = math.cos(math.pi / 4)
    spec = {"kind": "static", "materials": _mat(), "mesh": {"tol_stress": 0.02},
            "fixtures": [{"type": "roller", "faces": [_face((0, 30, 5))]}, {"type": "roller", "faces": [_face((30, 0, 5))]},
                         {"type": "roller", "faces": [_face((30 * c, 30 * c, 0))]},
                         {"type": "roller", "faces": [_face((30 * c, 30 * c, Lz))]}],
            "loads": [{"type": "pressure", "faces": [_face((ri * c, ri * c, 5))], "value": p}]}

    def check(res, keep):
        E, nu = STEEL["E"], STEEL["nu"]
        k = ri ** 2 / (ro ** 2 - ri ** 2)
        hoop, rad = p * k * (1 + ro ** 2 / ri ** 2), -p
        ax = nu * (hoop + rad)
        vm = math.sqrt(0.5 * ((hoop - rad) ** 2 + (rad - ax) ** 2 + (ax - hoop) ** 2))
        ur = (1 + nu) / E * p * k * ((1 - 2 * nu) * ri + ro ** 2 / ri)
        X = keep["model"].sp.X
        inner = np.abs(np.hypot(X[:, 0], X[:, 1]) - ri) < 1e-6        # mesh corners on the bore
        got_u = float(np.hypot(keep["u"][inner, 0], keep["u"][inner, 1]).mean())
        return [_row("peak von Mises stress (at the bore)", vm, res["peak_von_mises_MPa"], 0.02, "MPa", "Lame, plane strain"),
                _row("radial displacement of the bore", ur, got_u, 0.01, "mm", "Lame, plane strain")]
    return shape, spec, check


def self_weight():
    """Cantilever 200 x 10 x 5 mm under its own weight (1 g), nu = 0."""
    from netgen.occ import Box, Pnt
    L, b, h, E, rho = 200.0, 10.0, 5.0, 210000.0, 7850.0
    shape = Box(Pnt(0, 0, 0), Pnt(L, b, h))
    spec = {"kind": "static", "materials": _mat(nu=0.0),
            "fixtures": [{"type": "fixed", "faces": [_face((0, 5, 2.5))]}],
            "loads": [{"type": "gravity", "vector": [0, 0, -9806.65]}]}

    def check(res, keep):
        w = rho * 1e-12 * 9806.65 * b * h
        I = b * h ** 3 / 12
        tip = -float(keep["u"][keep["model"].sp.X[:, 0] > L - 1e-6][:, 2].mean())
        return [_row("tip deflection under gravity", w * L ** 4 / (8 * E * I), tip, 0.01, "mm", "w L^4/(8 E I)")]
    return shape, spec, check


def bonded_bar():
    """Two blocks bonded end to end (steel and aluminium, nu = 0), pulled with 1000 N: springs in series."""
    from netgen.occ import Box, Glue, Pnt
    A, L1, L2, F, E1, E2 = 100.0, 30.0, 50.0, 1000.0, 210000.0, 70000.0
    shape = Glue([Box(Pnt(0, 0, 0), Pnt(L1, 10, 10)), Box(Pnt(L1, 0, 0), Pnt(L1 + L2, 10, 10))])
    spec = {"kind": "static",
            "materials": [{"name": "steel", "E": E1, "nu": 0.0, "density": 7850.0, "yield": 250.0, "centre": [L1 / 2, 5, 5]},
                          {"name": "aluminium", "E": E2, "nu": 0.0, "density": 2700.0, "yield": 240.0, "centre": [L1 + L2 / 2, 5, 5]}],
            "fixtures": [{"type": "fixed", "faces": [_face((0, 5, 5))]}],
            "loads": [{"type": "force", "faces": [_face((L1 + L2, 5, 5))], "vector": [F, 0, 0]}]}

    def check(res, keep):
        end = float(keep["u"][keep["model"].sp.X[:, 0] > L1 + L2 - 1e-6][:, 0].mean())
        return [_row("elongation of two bonded solids", F * L1 / (E1 * A) + F * L2 / (E2 * A), end, 0.005, "mm",
                     "F L1/(E1 A) + F L2/(E2 A)"),
                _row("safety factor (the weaker solid governs)", 240.0 / (F / A), res["safety_factor"]["value"], 0.01, "",
                     "yield / (F / A)")]
    return shape, spec, check


def preload_block():
    """A 20 x 20 x 50 mm block clamped by a 5 kN preload between its ends (nu = 0), on three symmetry planes."""
    from netgen.occ import Box, Pnt
    a, L, N, E = 20.0, 50.0, 5000.0, 210000.0
    shape = Box(Pnt(0, 0, 0), Pnt(a, a, L))
    spec = {"kind": "static", "materials": _mat(nu=0.0),
            "fixtures": [{"type": "roller", "faces": [_face((0, 10, 25))]}, {"type": "roller", "faces": [_face((10, 0, 25))]},
                         {"type": "roller", "faces": [_face((10, 10, 0))]}],
            "loads": [{"type": "preload", "faces": [_face((10, 10, 0))], "faces_b": [_face((10, 10, L))], "force": N}]}

    def check(res, keep):
        top = -float(keep["u"][keep["model"].sp.X[:, 2] > L - 1e-6][:, 2].mean())
        return [_row("shortening under a bolt preload", N * L / (E * a * a), top, 0.005, "mm", "N L/(E A)"),
                _row("stress under a bolt preload", N / (a * a), res["peak_von_mises_MPa"], 0.01, "MPa", "N / A")]
    return shape, spec, check


def _beam_freq(bl, L, E, I, rho, A):
    return bl ** 2 / (2 * math.pi * L ** 2) * math.sqrt(E * I / (rho * 1e-12 * A))


def modal_cantilever():
    """Clamped-free steel beam 200 x 10 x 5 mm: the first bending modes."""
    from netgen.occ import Box, Pnt
    L, b, h = 200.0, 10.0, 5.0
    shape = Box(Pnt(0, 0, 0), Pnt(L, b, h))
    spec = {"kind": "modal", "materials": _mat(), "modes": 3,
            "fixtures": [{"type": "fixed", "faces": [_face((0, 5, 2.5))]}], "loads": []}

    def check(res, keep):
        E, rho, A = STEEL["E"], STEEL["density"], b * h
        f = res["frequencies_Hz"]
        return [_row("mode 1: first bending, thin direction", _beam_freq(1.8751, L, E, b * h ** 3 / 12, rho, A), f[0], 0.02, "Hz",
                     "Euler-Bernoulli, beta L = 1.8751"),
                _row("mode 2: first bending, stiff direction", _beam_freq(1.8751, L, E, h * b ** 3 / 12, rho, A), f[1], 0.02, "Hz",
                     "Euler-Bernoulli, beta L = 1.8751"),
                _row("mode 3: second bending, thin direction", _beam_freq(4.6941, L, E, b * h ** 3 / 12, rho, A), f[2], 0.02, "Hz",
                     "Euler-Bernoulli, beta L = 4.6941")]
    return shape, spec, check


def modal_free():
    """The same beam with no supports: the first elastic mode after the six rigid-body modes."""
    from netgen.occ import Box, Pnt
    L, b, h = 200.0, 10.0, 5.0
    shape = Box(Pnt(0, 0, 0), Pnt(L, b, h))
    spec = {"kind": "modal", "materials": _mat(), "modes": 2, "fixtures": [], "loads": []}

    def check(res, keep):
        E, rho, A = STEEL["E"], STEEL["density"], b * h
        f = res["frequencies_Hz"]
        return [_row("free-free mode 1: bending, thin direction", _beam_freq(4.7300, L, E, b * h ** 3 / 12, rho, A), f[0], 0.02,
                     "Hz", "Euler-Bernoulli, beta L = 4.7300"),
                _row("free-free mode 2: bending, stiff direction", _beam_freq(4.7300, L, E, h * b ** 3 / 12, rho, A), f[1], 0.02,
                     "Hz", "Euler-Bernoulli, beta L = 4.7300")]
    return shape, spec, check


def euler_column():
    """Clamped-free steel column 10 x 10 x 200 mm under 1000 N: the buckling load factor."""
    from netgen.occ import Box, Pnt
    a, L, P = 10.0, 200.0, 1000.0
    shape = Box(Pnt(0, 0, 0), Pnt(a, a, L))
    spec = {"kind": "buckling", "materials": _mat(), "modes": 2,
            "fixtures": [{"type": "fixed", "faces": [_face((5, 5, 0))]}],
            "loads": [{"type": "force", "faces": [_face((5, 5, L))], "vector": [0, 0, -P]}]}

    def check(res, keep):
        pcr = math.pi ** 2 * STEEL["E"] * (a ** 4 / 12) / (4 * L ** 2)
        return [_row("buckling load factor", pcr / P, res["load_factor"], 0.02, "", "Euler: pi^2 E I/(4 L^2) / P")]
    return shape, spec, check


def _nafems_ellipse(thickness: float, split: bool = False):
    """The quarter of NAFEMS' elliptic plate: inner ellipse 2 x 1 m, outer 3.25 x 2.75 m (semi-axes), in millimetres.
    split: as two solids glued at mid-height, so the outer face has an edge on the mid-plane."""
    from netgen.occ import Axes, Glue, WorkPlane, X, Z

    def face(z):
        ax = Axes((0, 0, z), n=Z, h=X)
        return (WorkPlane(ax).Ellipse(3250, 2750).Face() - WorkPlane(ax).Ellipse(2000, 1000).Face()) * \
            WorkPlane(ax).Rectangle(4000, 4000).Face()
    if not split:
        return face(0).Extrude(thickness * Z)
    return Glue([face(-thickness / 2).Extrude(thickness / 2 * Z), face(0).Extrude(thickness / 2 * Z)])


_OUT = (3250 * math.cos(0.7), 2750 * math.sin(0.7))          # a point on the outer ellipse
_IN = (2000 * math.cos(0.7), 1000 * math.sin(0.7))


def nafems_le1():
    """NAFEMS LE1, elliptic membrane: 0.1 m thick, 10 MPa outward on the outer edge, symmetry on both straight
    edges, E = 210 GPa, nu = 0.3. Solved as a solid, half the thickness by symmetry."""
    shape = _nafems_ellipse(50.0)
    spec = {"kind": "static", "materials": _mat(), "mesh": {"tol_stress": 0.01, "h0": 400.0},
            "fixtures": [{"type": "roller", "faces": [_face((0, 1800, 25))]}, {"type": "roller", "faces": [_face((2600, 0, 25))]},
                         {"type": "roller", "faces": [_face((1532, 1381, 0))]}],
            "loads": [{"type": "pressure", "faces": [_face((*_OUT, 25))], "value": -10.0}]}

    def check(res, keep):
        k = _probe(keep, (2000, 0, 0))
        return [_row("stress yy at D (2, 0)", 92.7, float(keep["stress"][k, 1]), 0.02, "MPa",
                     "NAFEMS, The Standard NAFEMS Benchmarks (1990), test LE1: 92.7 MPa (plane stress)")]
    return shape, spec, check


def nafems_le10():
    """NAFEMS LE10, thick plate: 0.6 m thick, 1 MPa on the upper face, symmetry on both straight faces, the outer
    face held in x and y and, on its mid-plane edge, in z. E = 210 GPa, nu = 0.3. The support along that edge is
    a singular line: the study names it and leaves the stress within 300 mm of it out; point D is far from it."""
    shape = _nafems_ellipse(600.0, split=True)
    up, low = _face((*_OUT, 150)), _face((*_OUT, -150))
    spec = {"kind": "static", "materials": _mat(), "mesh": {"tol_stress": 0.02, "h0": 200.0, "singular_radius": 300.0},
            "fixtures": [{"type": "roller", "faces": [_face((0, 1800, 150)), _face((0, 1800, -150))]},
                         {"type": "roller", "faces": [_face((2600, 0, 150)), _face((2600, 0, -150))]},
                         {"type": "hold", "faces": [up, low], "directions": [[1, 0, 0], [0, 1, 0]]},
                         {"type": "hold", "faces": [up], "faces_b": [low], "directions": [[0, 0, 1]]}],
            "loads": [{"type": "pressure", "faces": [_face((1532, 1381, 300))], "value": 1.0}]}

    def check(res, keep):
        k = _probe(keep, (2000, 0, 300))
        return [_row("stress yy at D (2, 0, top)", -5.38, float(keep["stress"][k, 1]), 0.03, "MPa",
                     "NAFEMS, The Standard NAFEMS Benchmarks (1990), test LE10: -5.38 MPa")]
    return shape, spec, check


def thermal_slab():
    """A wall 20 mm thick, k = 15 W/(m K): 100 C on one side, convection h = 500 W/(m2 K) to 20 C on the other."""
    from netgen.occ import Box, Pnt
    L, a, k, h, T1, Ta = 20.0, 40.0, 15.0, 500.0, 100.0, 20.0
    shape = Box(Pnt(0, 0, 0), Pnt(L, a, a))
    spec = {"kind": "thermal", "materials": [{"name": "stainless (verification)", "k": k}],
            "thermal": {"conditions": [{"type": "temperature", "faces": [_face((0, 20, 20))], "value": T1},
                                       {"type": "convection", "faces": [_face((L, 20, 20))], "h": h, "ambient": Ta}]}}

    def check(res, keep):
        q = (T1 - Ta) / (L * 1e-3 / k + 1 / h)                  # W/m2
        X = keep["model"].sp.X
        return [_row("heat through the wall", q * (a * 1e-3) ** 2, res["heat_through_W"], 0.005, "W",
                     "q = (T1 - Ta) / (L / k + 1 / h), times the area"),
                _row("temperature of the convective face", Ta + q / h, float(keep["T"][X[:, 0] > L - 1e-6].mean()), 0.005, "C",
                     "Ta + q / h")]
    return shape, spec, check


def thermal_cylinder():
    """A pipe wall, inner radius 20, outer 40 mm, k = 50 W/(m K): 200 C inside, 50 C outside; a quarter, 10 mm long."""
    from netgen.occ import Box, Cylinder, Pnt, Z
    ri, ro, Lz, k, Ti, To = 20.0, 40.0, 10.0, 50.0, 200.0, 50.0
    shape = (Cylinder(Pnt(0, 0, 0), Z, r=ro, h=Lz) - Cylinder(Pnt(0, 0, -1), Z, r=ri, h=Lz + 2)) * Box(Pnt(0, 0, 0), Pnt(50, 50, Lz))
    c = math.cos(math.pi / 4)
    spec = {"kind": "thermal", "materials": [{"name": "steel (verification)", "k": k}],
            "thermal": {"conditions": [{"type": "temperature", "faces": [_face((ri * c, ri * c, 5))], "value": Ti},
                                       {"type": "temperature", "faces": [_face((ro * c, ro * c, 5))], "value": To}]}}

    def check(res, keep):
        Q = 2 * math.pi * k * (Lz * 1e-3) * (Ti - To) / math.log(ro / ri) / 4          # the quarter
        X = keep["model"].sp.X
        r = np.hypot(X[:, 0], X[:, 1])
        mid = np.abs(r - 30.0) < 0.75
        exact = Ti - (Ti - To) * np.log(r[mid] / ri) / math.log(ro / ri)
        worst = float(np.abs(keep["T"][mid] - exact).max())
        return [_row("heat through the wall (a quarter)", Q, res["heat_through_W"], 0.005, "W", "2 pi k L (Ti - To) / ln(ro / ri)"),
                _row("temperature at mid-wall (span minus the worst node error)", Ti - To, Ti - To - worst, 0.005, "K",
                     "T(r) = Ti - (Ti - To) ln(r / ri) / ln(ro / ri)")]
    return shape, spec, check


def thermal_stress_bar():
    """A steel bar held between two walls (rollers on both ends and two sides), heated by 80 K: it cannot grow along
    its length. alpha = 12e-6 1/K."""
    from netgen.occ import Box, Pnt
    L, a, dT, al = 100.0, 10.0, 80.0, 12e-6
    shape = Box(Pnt(0, 0, 0), Pnt(L, a, a))
    spec = {"kind": "static", "materials": _mat(k=50.0, cte=al, **{"yield": 400.0}),
            "fixtures": [{"type": "roller", "faces": [_face((0, 5, 5))]}, {"type": "roller", "faces": [_face((L, 5, 5))]},
                         {"type": "roller", "faces": [_face((50, 0, 5))]}, {"type": "roller", "faces": [_face((50, 5, 0))]}],
            "loads": [],
            "thermal": {"reference": 20.0, "conditions": [{"type": "temperature", "faces": [_face((0, 5, 5))], "value": 20.0 + dT}]}}

    def check(res, keep):
        E, nu = STEEL["E"], STEEL["nu"]
        top = float(keep["u"][keep["model"].sp.X[:, 1] > a - 1e-6][:, 1].mean())
        return [_row("stress in a bar that cannot expand", E * al * dT, res["peak_von_mises_MPa"], 0.005, "MPa", "E alpha dT"),
                _row("sideways growth of the free faces", (1 + nu) * al * dT * a, top, 0.005, "mm", "(1 + nu) alpha dT a")]
    return shape, spec, check


def thermal_stress_cylinder():
    """The thick cylinder (20 / 40 mm) with 200 C inside and 50 C outside, plane strain: the hoop stress at the bore
    and at the outside from the radial temperature gradient. alpha = 12e-6 1/K."""
    from netgen.occ import Box, Cylinder, Pnt, Z
    ri, ro, Lz, Ti, To, al = 20.0, 40.0, 10.0, 200.0, 50.0, 12e-6
    shape = (Cylinder(Pnt(0, 0, 0), Z, r=ro, h=Lz) - Cylinder(Pnt(0, 0, -1), Z, r=ri, h=Lz + 2)) * Box(Pnt(0, 0, 0), Pnt(50, 50, Lz))
    c = math.cos(math.pi / 4)
    spec = {"kind": "static", "materials": _mat(k=50.0, cte=al, **{"yield": 800.0}), "mesh": {"tol_stress": 0.02},
            "fixtures": [{"type": "roller", "faces": [_face((0, 30, 5))]}, {"type": "roller", "faces": [_face((30, 0, 5))]},
                         {"type": "roller", "faces": [_face((30 * c, 30 * c, 0))]},
                         {"type": "roller", "faces": [_face((30 * c, 30 * c, Lz))]}],
            "loads": [],
            "thermal": {"reference": 50.0, "conditions": [{"type": "temperature", "faces": [_face((ri * c, ri * c, 5))], "value": Ti},
                                                          {"type": "temperature", "faces": [_face((ro * c, ro * c, 5))], "value": To}]}}

    def check(res, keep):
        E, nu = STEEL["E"], STEEL["nu"]
        ln = math.log(ro / ri)
        C = E * al * (Ti - To) / (2 * (1 - nu) * ln)
        hoop_i = C * (1 - 2 * ro ** 2 / (ro ** 2 - ri ** 2) * ln)
        hoop_o = C * (1 - 2 * ri ** 2 / (ro ** 2 - ri ** 2) * ln)
        X = keep["model"].sp.X
        r = np.hypot(X[:, 0], X[:, 1])
        s = keep["stress"]

        def hoop(mask):                                         # on the plane y = 0 the hoop stress is syy
            sel = mask & (np.abs(X[:, 1]) < 1e-6) & (X[:, 2] > 2) & (X[:, 2] < 8)
            return float(s[sel, 1].mean())
        return [_row("hoop stress at the bore (hot side, compression)", hoop_i, hoop(np.abs(r - ri) < 1e-6), 0.02, "MPa",
                     "Timoshenko and Goodier, Theory of Elasticity, art. 151: long cylinder, steady radial heat flow"),
                _row("hoop stress at the outside (cold side, tension)", hoop_o, hoop(np.abs(r - ro) < 1e-6), 0.02, "MPa",
                     "the same solution at r = ro")]
    return shape, spec, check


def sharp_corner():
    """An L-bracket with a sharp inside corner: the study must name the corner and leave its stress out."""
    from netgen.occ import Box, Pnt
    shape = Box(Pnt(0, 0, 0), Pnt(60, 20, 10)) + Box(Pnt(0, 0, 0), Pnt(10, 20, 60))
    spec = {"kind": "static", "materials": _mat(),
            "fixtures": [{"type": "fixed", "faces": [_face((5, 10, 60))]}],
            "loads": [{"type": "force", "faces": [_face((60, 10, 5))], "vector": [0, 0, -200.0]}]}

    def check(res, keep):
        s = [x for x in res["singularities"] if x["kind"] == "corner"]
        grow = s[0]["stress_there_MPa_by_refinement"] if s else [0, 0]
        named = bool(s) and grow[-1] > grow[0] * 1.15 and res["peak_von_mises_MPa"] < grow[-1]
        return [{"quantity": "the sharp inside corner is named and its stress left out", "expected": True, "got": named,
                 "unit": "", "error": 0.0 if named else 1.0, "tolerance": 0.0, "pass": named,
                 "source": "Williams (1952): the stress at a re-entrant corner is unbounded",
                 "detail": {"stress_at_the_corner_by_refinement": grow, "peak_reported": res["peak_von_mises_MPa"]}}]
    return shape, spec, check


LAYERED = {"E_p": 2600.0, "E_z": 2000.0, "nu_p": 0.33, "nu_zp": 0.25, "G_zp": 900.0, "S_xy": 35.0, "S_z": 25.0,
           "S_shear": None}


def _layered(axis, **kw):
    ly = {**LAYERED, **kw, "axis": list(map(float, axis))}
    return [{"name": "layered polymer (verification)", "E": ly["E_p"], "nu": ly["nu_p"], "density": 1240.0,
             "yield": ly["S_xy"], "layers": ly}]


def layered_tension():
    """A bar 60 x 10 x 10 mm of a layered (transversely isotropic) material pulled along its length with 1 MPa, the
    build direction at 30 degrees to the bar in the x-z plane. Held so the stress is uniform: the end face may not
    move along the bar, one of its edges not up or down, another not sideways."""
    from netgen.occ import Box, Pnt
    from . import solve
    L, b, h, s, th = 60.0, 10.0, 10.0, 1.0, 30.0
    ax = (math.cos(math.radians(th)), 0.0, math.sin(math.radians(th)))
    shape = Box(Pnt(0, 0, 0), Pnt(L, b, h))
    end, bottom, side = _face((0, 5, 5), area=b * h), _face((30, 5, 0), area=L * b), _face((30, 0, 5), area=L * h)
    spec = {"kind": "static", "materials": _layered(ax),
            "fixtures": [{"type": "hold", "faces": [end], "directions": [[1, 0, 0]]},
                         {"type": "hold", "faces": [end], "faces_b": [bottom], "directions": [[0, 0, 1]]},
                         {"type": "hold", "faces": [end], "faces_b": [side], "directions": [[0, 1, 0]]}],
            "loads": [{"type": "force", "faces": [_face((L, 5, 5), area=b * h)], "vector": [s * b * h, 0, 0]}]}

    def check(res, keep):
        E = solve.young_along(LAYERED["E_p"], LAYERED["E_z"], LAYERED["nu_zp"], LAYERED["G_zp"], th)
        X = keep["model"].sp.X
        ux = float(keep["u"][X[:, 0] > L - 1e-6][:, 0].mean())
        c2 = math.cos(math.radians(th)) ** 2
        return [_row("elongation of the bar", s * L / E, ux, 1e-3, "mm", "sigma L / E(30 deg), Lekhnitskii / Jones eq. 2.97"),
                _row("stress along the bar, everywhere", s, float(keep["stress"][:, 0].mean()), 1e-3, "MPa", "F / A"),
                _row("largest tension across the layers", s * c2, res["layers"]["across_layers"]["peak_tension_MPa"], 1e-3,
                     "MPa", "sigma cos^2(30 deg): the normal stress on a plane at 30 deg"),
                _row("largest shear between the layers", s * math.sin(math.radians(th)) * math.cos(math.radians(th)),
                     res["layers"]["interlayer_shear"]["peak_MPa"], 1e-3, "MPa", "sigma sin cos"),
                _row("safety factor across the layers", LAYERED["S_z"] / (s * c2),
                     res["layers"]["across_layers"]["safety_factor"]["value"], 1e-3, "", "Z strength / tension across")]
    return shape, spec, check


def layered_cantilever():
    """Cantilever 100 x 10 x 10 mm of a layered material, end load 10 N, Poisson's ratios 0 (so the fixed end is the
    beam-theory clamp). Printed standing (layers stacked along the beam), and solved again lying flat and on its
    side: the modulus along the beam and the shear modulus of the bending plane change with the build direction."""
    from netgen.occ import Box, Pnt
    L, b, h, F = 100.0, 10.0, 10.0, 10.0
    Ep, Ez, G = LAYERED["E_p"], LAYERED["E_z"], LAYERED["G_zp"]
    shape = Box(Pnt(0, 0, 0), Pnt(L, b, h))
    spec = {"kind": "static", "materials": _layered((1, 0, 0), nu_p=0.0, nu_zp=0.0),
            "layers": {"id": "standing", "sweep": [{"id": "flat", "axis": [0, 0, 1]}, {"id": "on its side", "axis": [0, 1, 0]}]},
            "fixtures": [{"type": "fixed", "faces": [_face((0, 5, 5), area=b * h)]}],
            "loads": [{"type": "force", "faces": [_face((L, 5, 5), area=b * h)], "vector": [0, 0, -F]}]}

    def check(res, keep):
        I, A, kappa = b * h ** 3 / 12, b * h, 5.0 / 6.0

        def tim(E, Gs):
            return F * L ** 3 / (3 * E * I) + F * L / (kappa * Gs * A)
        tip = -float(keep["u"][keep["model"].sp.X[:, 0] > L - 1e-6][:, 2].mean())
        k = _probe(keep, (L / 2, b / 2, h))
        x, _, z = keep["model"].sp.X[k]
        rows = {r["id"]: r for r in res["layers"]["by_orientation"]}
        src = "Timoshenko beam: F L^3/(3 E I) + F L/(kappa G A), E along the beam, G of the bending plane"
        return [_row("tip deflection, printed standing (E across the layers along the beam)", tim(Ez, G), tip, 0.01, "mm", src),
                _row("largest displacement, printed flat (in-plane E along the beam)", tim(Ep, G),
                     rows["flat"]["max_displacement_mm"], 0.015, "mm", src),
                _row("largest displacement, printed on its side (bending in the layer plane)", tim(Ep, Ep / 2),
                     rows["on its side"]["max_displacement_mm"], 0.015, "mm", src + "; in the layers G = E_p / (2 (1 + nu_p))"),
                _row("deflection standing / flat", tim(Ez, G) / tim(Ep, G),
                     rows["standing"]["max_displacement_mm"] / rows["flat"]["max_displacement_mm"], 0.01, "", "ratio of the two"),
                _row("bending stress near mid-span, top fibre (tension across the layers, standing)",
                     F * (L - x) * (z - h / 2) / I, float(keep["stress"][k, 0]), 0.02, "MPa",
                     "M c / I at that node: statically determinate, the same for any material")]
    return shape, spec, check


CASES = {"cantilever": cantilever, "plate_with_hole": plate_with_hole, "thick_cylinder": thick_cylinder,
         "self_weight": self_weight, "bonded_bar": bonded_bar, "preload_block": preload_block,
         "nafems_le1": nafems_le1, "nafems_le10": nafems_le10,
         "modal_cantilever": modal_cantilever, "modal_free": modal_free, "euler_column": euler_column,
         "thermal_slab": thermal_slab, "thermal_cylinder": thermal_cylinder, "thermal_stress_bar": thermal_stress_bar,
         "thermal_stress_cylinder": thermal_stress_cylinder, "sharp_corner": sharp_corner,
         "layered_tension": layered_tension, "layered_cantilever": layered_cantilever}
TITLES = {"cantilever": "Cantilever beam, end load", "plate_with_hole": "Plate with a hole in tension",
          "thick_cylinder": "Thick cylinder under internal pressure", "self_weight": "Cantilever under its own weight",
          "bonded_bar": "Two bonded solids in series", "preload_block": "Block under a bolt preload",
          "nafems_le1": "NAFEMS LE1: elliptic membrane", "nafems_le10": "NAFEMS LE10: thick plate under pressure",
          "modal_cantilever": "Natural frequencies of a cantilever", "modal_free": "Natural frequencies of a free beam",
          "euler_column": "Euler buckling of a column", "sharp_corner": "Sharp inside corner (singularity)",
          "thermal_slab": "Heat through a wall with convection", "thermal_cylinder": "Heat through a pipe wall",
          "thermal_stress_bar": "Thermal stress in a bar that cannot expand",
          "thermal_stress_cylinder": "Thermal stress in a thick cylinder",
          "layered_tension": "Layered material pulled at 30 degrees to its build direction",
          "layered_cantilever": "Cantilever of a layered material, three build directions"}


def bracket():
    """An aluminium L-bracket 80 x 40 x 60 mm, 6 mm thick, with a 6 mm fillet and three 6 mm holes: fixed at the two
    base holes, 300 N and -200 N on the hole of the upright. No reference value: this is the timing case."""
    from netgen.occ import Box, Cylinder, Pnt, X, Z
    t = 6.0
    s = Box(Pnt(0, 0, 0), Pnt(80, 40, t)) + Box(Pnt(0, 0, 0), Pnt(t, 40, 60))
    s = s.MakeFillet([e for e in s.edges if abs(e.center.x - t) < 1e-6 and abs(e.center.z - t) < 1e-6], 6.0)
    s = s - Cylinder(Pnt(30, 20, -1), Z, r=3, h=t + 2) - Cylinder(Pnt(62, 20, -1), Z, r=3, h=t + 2) \
        - Cylinder(Pnt(-1, 20, 42), X, r=3, h=t + 2)
    spec = {"materials": [{"name": "aluminium 6061-T6 (timing case)", "E": 68900.0, "nu": 0.33, "density": 2700.0, "yield": 276.0}],
            "fixtures": [{"type": "fixed", "faces": [_face((33, 20, 3)), _face((65, 20, 3))]}],
            "loads": [{"type": "force", "faces": [_face((3, 20, 45))], "vector": [300.0, 0, -200.0]}], "modes": 4}
    return s, spec


def run_bench() -> dict:
    """The bracket solved as a static, a modal and a buckling study: wall time, unknowns and what converged."""
    import platform

    from . import core
    from . import mesh as mesh_mod
    rows = []
    for kind in ("static", "modal", "buckling"):
        shape, spec = bracket()
        t0 = time.perf_counter()
        res, _ = core.run(mesh_mod.from_shape(shape), {**spec, "kind": kind})
        rows.append({"kind": kind, "seconds": round(time.perf_counter() - t0, 1), "converged": res["converged"],
                     "evidence": res["evidence"], "unknowns": res["mesh"]["unknowns"], "tets": res["mesh"]["tets"],
                     "levels": len(res["convergence"]["levels"]),
                     "result": (f"peak von Mises {res['peak_von_mises_MPa']:.1f} MPa, safety factor {res['safety_factor']['value']:.2f}"
                                if kind == "static" and res.get("safety_factor") else
                                "first frequencies " + ", ".join(f"{x:.0f}" for x in res["frequencies_Hz"][:3]) + " Hz" if kind == "modal"
                                else f"load factor {res['load_factor']:.1f}" if kind == "buckling" else "not converged")})
    return {"case": (bracket.__doc__ or "").strip(), "rows": rows, "machine": f"{platform.machine()}, {platform.system()} "
            f"{platform.release()}, {__import__('os').cpu_count()} cores", "versions": versions()}


def run_case(cid: str, mesh: dict | None = None) -> dict:
    from . import core
    from . import mesh as mesh_mod
    shape, spec, check = CASES[cid]()
    if mesh:
        spec["mesh"] = {**(spec.get("mesh") or {}), **mesh}
    keep: dict = {}
    t0 = time.perf_counter()
    res, _field = core.run(mesh_mod.from_shape(shape), spec, keep=keep)
    rows = check(res, keep)
    return {"case": cid, "title": TITLES[cid], "doc": (CASES[cid].__doc__ or "").strip(), "kind": spec["kind"],
            "converged": res["converged"], "evidence": res["evidence"], "stated_error": res.get("discretisation_error"),
            "unknowns": res["mesh"]["unknowns"], "levels": len(res["convergence"]["levels"]),
            "seconds": round(time.perf_counter() - t0, 2), "rows": rows, "pass": all(r["pass"] for r in rows) and res["converged"],
            "stopped_because": res["stopped_because"], "not_converged_because": res.get("not_converged_because")}


def run_all(ids=None) -> dict:
    out = [run_case(c) for c in (ids or CASES)]
    return {"cases": out, "pass": all(c["pass"] for c in out), "seconds": round(sum(c["seconds"] for c in out), 2),
            "versions": versions()}


def versions() -> dict:
    import netgen
    import pyamg
    import scipy
    import skfem
    v = {"scikit-fem": skfem.__version__, "scipy": scipy.__version__, "numpy": np.__version__, "pyamg": pyamg.__version__}
    try:
        from importlib.metadata import version
        v["netgen-mesher"] = version("netgen-mesher")
    except Exception:                           # noqa: BLE001
        v["netgen-mesher"] = getattr(netgen, "__version__", "?")
    return v


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    if "--bench" in argv:
        print(json.dumps(run_bench(), indent=1, default=float))
        return 0
    ids = [a for a in argv if not a.startswith("--")]
    for c in ids:
        if c not in CASES:
            sys.exit(f"unknown case {c}; cases: {', '.join(CASES)}")
    rep = run_all(ids or None)
    if as_json:
        print(json.dumps(rep, indent=1, default=float))
    else:
        for c in rep["cases"]:
            print(f"{c['title']}  [{c['evidence']}; {c['unknowns']:,} unknowns, {c['levels']} levels, {c['seconds']} s]")
            for r in c["rows"]:
                if isinstance(r["expected"], bool):
                    print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['quantity']}")
                else:
                    print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['quantity']}: expected {r['expected']:.6g} {r['unit']}, got "
                          f"{r['got']:.6g}, error {100 * r['error']:.2f} % (tolerance {100 * r['tolerance']:.1f} %)")
            if not c["converged"]:
                print(f"  NOT CONVERGED: {c['not_converged_because']}")
        print("ALL PASS" if rep["pass"] else "FAILURES", f"in {rep['seconds']} s")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
