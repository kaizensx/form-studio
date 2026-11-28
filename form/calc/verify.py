"""The calculators against published worked examples, and the solids they write against their own numbers.

    examples()   every worked example: the reference value as printed in its source, the computed value, the accepted
                 error and whether it holds. No kernel needed.
    geometry()   each kind of solid built (in this process: needs the CAD kernel) and measured against the sheet that
                 sized it: lengths from the bounding box, a gear's tooth thickness against the exact involute.

`form calc verify` prints both as JSON; tests/test_calculators.py asserts them; docs/CALCULATORS.md is this table.
A reference is only what its source prints. Where the source rounds an intermediate (the guide reads X = 0.0017 off a
chart, a table lists 18.8 where the formula gives 18.6), the accepted error is set to cover the rounding and the row
says so.
"""
from __future__ import annotations

import math

from . import run
from . import fastener, gear, spring

INCH, LBF, PSI = 25.4, 4.4482216, 6.894757e-3
BAYER = "Bayer, Snap-Fit Joints for Plastics"
SHIGLEY = "Shigley's Mechanical Engineering Design, 10th ed."
KHK = "KHK Gear Technical Reference"
VDI_TABLE = "Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8)"
NORTON = "Norton, Design of Machinery, ch. 8"
VDI_URL = "https://www.pfeiffervacuum.com/global/de/knowledge/vacuum-technology/mechanical-components-in-vacuum/connections"


def _v(r: dict) -> dict:
    return {x["key"]: x["value"] for x in r["values"]}


def _row(calc, case, quantity, ref, got, tol, source, unit="", note=""):
    err = abs(got - ref) / abs(ref) if ref else abs(got - ref)
    return {"calculator": calc, "case": case, "quantity": quantity, "reference": ref, "computed": float(f"{got:.6g}"), "unit": unit,
            "error": float(f"{err:.3g}"), "accepted": tol, "pass": err <= tol, "source": source, "note": note}


def examples() -> list:
    rows = []
    # ---- snap joints: the guide's two worked examples --------------------------------------------------------
    v = _v(run("snapfit", dict(allow_strain=0.04, utilisation=0.5, taper="thickness_half", length=19, width=9.5,
                               undercut=2.4, E=1815, mu=0.6, lead_angle=30)))
    c = "Calculation example I: PC hook, l 19, b 9.5, y 2.4 mm, half of 4 % strain, thickness tapering to one-half"
    rows += [_row("snapfit", c, "thickness h", 3.28, v["thickness"], 0.002, BAYER, "mm"),
             _row("snapfit", c, "deflection force P", 32.5, v["deflection_force"], 0.002, BAYER, "N", "E_s = 1815 MPa from the guide's Fig. 16"),
             _row("snapfit", c, "mating force W", 58.5, v["mating_force"], 0.003, BAYER, "N", "the guide reads the friction term as 1.8 off its chart; it is 1.801")]
    v = _v(run("snapfit", dict(kind="annular", guide_resin="pc", diameter=200, wall=2.5, undercut=2, elastic="both", E=2200,
                               mu=0.6, lead_angle=30, poisson=0.35)))
    c = "Annular example: PC lamp cover, d 200, t 2.5, undercut 2 × 1 mm, both parts equally stiff"
    rows += [_row("snapfit", c, "hoop strain", 0.005, v["strain"], 1e-6, BAYER, ""),
             _row("snapfit", c, "geometric factor X_N", 0.0017, v["X"], 0.01, BAYER, "", "read off the guide's Fig. 27; its formula gives 0.001686"),
             _row("snapfit", c, "transverse force P", 748.0, v["deflection_force"], 0.01, BAYER, "N", "the guide multiplies by the rounded 0.0017"),
             _row("snapfit", c, "mating force W", 1346.0, v["mating_force"], 0.01, BAYER, "N", "same rounding")]
    # ---- springs: Shigley example 10-1, in SI ------------------------------------------------------------------
    d, D = 0.037 * INCH, 0.4005 * INCH
    v = _v(run("spring", dict(wire_d=d, mean_d=D, active=10.5, ends="closed", wire="music", stress_factor=0.45,
                              G=11.85e6 * PSI, E=28.5e6 * PSI, free_length=2.06 * INCH)))
    c = "Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends"
    Fy = math.pi * d ** 3 * (0.45 * v["Rm"]) / (8 * v["k"] * D)
    rows += [_row("spring", c, "tensile strength S_ut", 324.0, v["Rm"] / PSI / 1000, 0.003, SHIGLEY, "kpsi", "Table 10-4, A / d^m"),
             _row("spring", c, "correction factor K_B", 1.124, v["k"], 0.001, SHIGLEY, ""),
             _row("spring", c, "rate k", 4.13, v["rate"] / LBF * INCH, 0.005, SHIGLEY, "lbf/in", "the book rounds intermediates; exact arithmetic gives 4.116"),
             _row("spring", c, "solid length L_s", 0.5, v["solid_length"] / INCH, 0.002, SHIGLEY, "in"),
             _row("spring", c, "load at torsional yield", 6.46, Fy / LBF, 0.005, SHIGLEY, "lbf", "from the sheet's k and R_m"),
             _row("spring", c, "deflection at that load", 1.56, Fy / v["rate"] / INCH, 0.005, SHIGLEY, "in")]
    # absolute stability: Shigley eq. 10-13, L0 < 2.63 D / α for steel (E 30, G 11.5 Mpsi); the EN relation must agree
    Lcrit = 2.63 * D / 0.5
    stable = spring.buckling_deflection(Lcrit * 0.995, D, 11.5, 30.0, 0.5) is None
    unstable = spring.buckling_deflection(Lcrit * 1.005, D, 11.5, 30.0, 0.5) is not None
    rows.append(_row("spring", c, "longest free length that cannot buckle", 2.11, Lcrit / INCH if stable and unstable else 0.0, 0.003,
                     SHIGLEY, "in", "EN 13906-1's buckling relation changes from no root to a root at 2.63 D / α"))
    f = spring.natural_frequency(2.0, 20.0, 8.0, 81500.0, 7850.0)
    rows.append(_row("spring", "d 2, D 20, n 8, steel", "natural frequency, the standard's 3560 d/(n D²) √(G/ρ)",
                     3560 * 2 / (8 * 400) * math.sqrt(81500 / 7.85), f, 0.001, "EN 13906-1", "Hz",
                     "the SI form used here against the standard's unit form (3560 is 10³·√500/2π = 3558.8, rounded)"))
    # ---- fasteners: published VDI 2230 reference values ------------------------------------------------------
    table = {"M6": ((10.4, 9.0), (10.2, 10.1), (9.9, 11.3)), "M8": ((19.1, 21.6), (18.8, 24.6), (18.1, 27.3)),
             "M10": ((30.3, 43.0), (29.6, 48.0), (28.8, 54.0)), "M12": ((44.1, 73.0), (43.0, 84.0), (41.9, 93.0))}
    for size, cols in table.items():
        for mu, (F_ref, M_ref) in zip((0.10, 0.12, 0.14), cols):
            F = fastener.preload_permissible(size, 640.0, mu)
            M = fastener.torque(size, F, mu, mu, "hex")
            odd = size == "M8" and mu == 0.12
            rows.append(_row("fastener", f"{size} class 8.8, μ = {mu:g}", "permissible preload F_M", F_ref, F / 1000, 0.012 if odd else 0.006, VDI_TABLE, "kN",
                             "the table prints 18.8 between 19.1 and 18.1; the guideline's formula gives 18.6" if odd else ""))
            rows.append(_row("fastener", f"{size} class 8.8, μ = {mu:g}", "tightening torque M_A", M_ref, M / 1000, 0.012, VDI_TABLE, "N·m",
                             "hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10"))
    # ---- gears: KHK tables and Shigley ---------------------------------------------------------------------------
    v = _v(run("gear", dict(module=3, z1=12, z2=24, x1=0.6, x2=0.36)))
    c = "Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36"
    for q, ref, key, tol in (("working pressure angle", 26.0886, "alpha_wt", 1e-5), ("centre distance", 56.4999, "centre_distance", 1e-5),
                             ("centre distance modification y", 0.8333, "y", 1e-4), ("pinion tip diameter", 44.84, "da1", 1e-4),
                             ("gear tip diameter", 79.40, "da2", 1e-4), ("pinion root diameter", 32.10, "df1", 1e-4),
                             ("gear root diameter", 66.66, "df2", 1e-4), ("tooth depth", 6.37, "depth", 1e-4)):
        rows.append(_row("gear", c, q, ref, v[key], tol, KHK, "deg" if "angle" in q else "" if q.endswith("y") else "mm"))
    v = _v(run("gear", dict(module=3, z1=12, z2=60, x1=0.09809, helix=30)))
    c = "Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809"
    for q, ref, key, tol in (("transverse pressure angle", 22.79588, "alpha_t", 1e-6), ("working pressure angle", 23.1126, "alpha_wt", 1e-5),
                             ("centre distance", 125.000, "centre_distance", 1e-5), ("pinion reference diameter", 41.569, "d1", 1e-5),
                             ("gear reference diameter", 207.846, "d2", 1e-5), ("pinion base diameter", 38.322, "db1", 1e-5),
                             ("gear base diameter", 191.611, "db2", 1e-5), ("pinion tip diameter", 48.153, "da1", 1e-4),
                             ("gear tip diameter", 213.842, "da2", 1e-4)):
        rows.append(_row("gear", c, q, ref, v[key], tol, KHK, "deg" if "angle" in q else "mm"))
    v = _v(run("gear", dict(module=INCH / 2, z1=16, z2=40, centre_distance=14.25 * INCH)))
    c = "Example 13-1: P 2 teeth/in, 16/40 teeth, 20°, mounted 1/4 in too far apart"
    rows += [_row("gear", c, "pinion base radius", 3.76, v["db1"] / 2 / INCH, 0.002, SHIGLEY, "in"),
             _row("gear", c, "gear base radius", 9.40, v["db2"] / 2 / INCH, 0.002, SHIGLEY, "in"),
             _row("gear", c, "pressure angle as mounted", 22.59, v["alpha_wt"], 0.001, SHIGLEY, "deg", "the book rounds the base radius first; exact arithmetic gives 22.60")]
    v = _v(run("gear", dict(module=INCH / 8, z1=16, z2=32, face=1.5 * INCH, torque=365 * LBF * INCH, speed=1200)))
    c = "Example 14-1: P 8, 16 teeth, face 1.5 in, 1200 rev/min, W_t 365 lbf"
    rows += [_row("gear", c, "velocity factor K_v", 1.52, v["Kv"], 0.003, SHIGLEY, ""),
             _row("gear", c, "Lewis form factor Y", 0.296, v["Y"], 1e-9, SHIGLEY, ""),
             _row("gear", c, "bending stress", 10.0, v["bending_stress"] / PSI / 1000, 0.003, SHIGLEY, "kpsi", "the book's allowable stress, which its W_t = 365 lbf was sized to")]
    rows.append(_row("gear", "involute function", "inverse of inv α at α = 26.0886°", 26.0886,
                     math.degrees(gear.inv_inverse(gear.inv(math.radians(26.0886)))), 1e-9, "ISO 21771", "deg"))
    # ---- cams: the laws' peak coefficients --------------------------------------------------------------------
    for law, cv, ca in (("cycloidal", 2.0, 6.283), ("harmonic", 1.571, 4.935), ("poly345", 1.875, 5.777)):
        v = _v(run("cam", dict(law=law, lift=10, rise=90, dwell=90, fall=90, base_radius=40)))
        b = math.pi / 2
        rows += [_row("cam", f"{law} rise", "peak velocity factor C_v (v = C_v h/β)", cv, v["velocity_peak"] * b / 10, 0.001, NORTON, ""),
                 _row("cam", f"{law} rise", "peak acceleration factor C_a (a = C_a h/β²)", ca, v["acceleration_peak"] * b * b / 10, 0.001, NORTON, "",
                      "the handbook prints 5.777 for the 3-4-5 polynomial; the exact maximum is 5.7735" if law == "poly345" else "")]
    # ---- fits --------------------------------------------------------------------------------------------------
    v = _v(run("fit", dict(fit="H7/g6", diameter=25, alpha_hole=23.6e-6, alpha_shaft=11.7e-6, t_min=20, t_max=120)))
    c = "H7/g6 at Ø25: hole 0/+21 µm, shaft −7/−20 µm"
    rows += [_row("fit", c, "smallest clearance at 20 °C", 0.007, v["clearance_min_20"], 1e-9, "ISO 286-2 tables", "mm"),
             _row("fit", c, "largest clearance at 20 °C", 0.041, v["clearance_max_20"], 1e-9, "ISO 286-2 tables", "mm"),
             _row("fit", c + "; aluminium on steel, +100 K", "growth of the clearance, d (α_h − α_s) ΔT = 25 × 11.9e-6 × 100", 0.02975,
                  v["clearance_min_hot"] - v["clearance_min_20"], 0.002, "hand calculation", "mm", "the limits scale too, hence the 0.1 % difference")]
    return rows


# ---- geometry: each solid built and measured -----------------------------------------------------------------------
def _g(kind, what, expected, measured, tol, unit="mm"):
    err = abs(measured - expected)
    return {"geometry": kind, "measured_on_the_solid": what, "expected": float(f"{expected:.6g}"), "measured": float(f"{measured:.6g}"),
            "unit": unit, "difference": float(f"{err:.3g}"), "accepted": tol, "pass": err <= tol}


def tooth_thickness_measured(solid, r: float, z: int, face: float, dr: float) -> float:
    """Mean transverse arc tooth thickness at radius r, by cutting the gear with a thin tube: volume / (z · 2 dr · b)."""
    from build123d import Align, Cylinder
    al = (Align.CENTER, Align.CENTER, Align.MIN)
    tube = Cylinder(r + dr, face, align=al) - Cylinder(r - dr, face, align=al)
    return (solid & tube).volume / (z * 2 * dr * face)


def geometry() -> list:
    from . import shapes
    rows = []

    def box(s):
        b = s.bounding_box()
        return b.min, b.max

    # snap hook
    r = run("snapfit", dict(material="PETG", length=15, width=6, undercut=1.0))
    g, v = r["geometry"]["values"], _v(r)
    s = shapes.snap_hook(g)
    lo, hi = box(s)
    rows += [_g("snap hook", "root thickness plus undercut (extent in X)", v["thickness"] + v["undercut"], hi.X - lo.X, 1e-4),
             _g("snap hook", "width (extent in Y)", v["width"], hi.Y - lo.Y, 1e-4),
             _g("snap hook", "valid solid", 1, int(s.is_valid and len(s.solids()) == 1), 0, "")]
    # compression spring
    r = run("spring", dict(wire_d=1.6, mean_d=14, active=6, force=40, wire="music"))
    g, v = r["geometry"]["values"], _v(r)
    s = shapes.spring_compression(g)
    lo, hi = box(s)
    wire_len = math.pi * v["mean_d"] * v["total"]
    zs = [p.Z for p in s.vertices()]             # the ground flats' own vertices: a swept surface's bounding box is loose
    rows += [_g("compression spring", "free length (between the ground faces)", v["free_length"], max(zs) - min(zs), 0.02),
             _g("compression spring", "outside diameter D + d", v["mean_d"] + v["wire_d"], hi.X - lo.X, 0.02),
             _g("compression spring", "wire volume against π d²/4 · π D n_t (less what is ground off)", 1.0,
                s.volume / (math.pi * v["wire_d"] ** 2 / 4 * wire_len), 0.08, "ratio"),
             _g("compression spring", "valid solid", 1, int(s.is_valid and len(s.solids()) == 1), 0, "")]
    # gears: the built tooth against the exact involute
    for label, inp in (("spur gear, x = 0.3", dict(module=2, z1=14, z2=30, x1=0.3)),
                       ("spur gear, unshifted", dict(module=2, z1=24, z2=36)),
                       ("helical gear, β = 20°", dict(module=2, z1=15, z2=31, helix=20, face=10))):
        r = run("gear", inp)
        g, v = r["geometry"]["values"], _v(r)
        s = shapes.gear_pinion(g)
        lo, hi = box(s)
        z, m = int(g["z1"]), g["module"]
        an, beta = math.radians(g["pressure_angle"]), math.radians(g["helix"])
        at = math.atan(math.tan(an) / math.cos(beta))
        mt = m / math.cos(beta)
        rb, ra = v["db1"] / 2, v["da1"] / 2
        worst = 0.0
        for f in (0.3, 0.5, 0.7, 0.9):
            rr = rb + (ra - rb) * f
            if rr <= rb * 1.01:
                continue
            exact = gear.tooth_thickness(rr, z, mt, at, g["x1"], an)
            worst = max(worst, abs(tooth_thickness_measured(s, rr, z, g["face"], 0.01 * m) - exact))
        rows += [_g(label, "tip diameter d_a1 (bounding box)", v["da1"], hi.X - lo.X, 2e-3),
                 _g(label, "tooth thickness against the exact involute at four radii, largest difference", 0.0, worst, 2e-3)]
    r = run("gear", dict(module=2, z1=14, z2=30, x1=0.3))
    a, b, _e = shapes.gear_objects(r["geometry"]["values"])
    rows.append(_g("spur pair, x = 0.3", "centre distance at which the library meshes the two gears", _v(r)["centre_distance"],
                   float(math.hypot(float(b.center[0]) - float(a.center[0]), float(b.center[1]) - float(a.center[1]))), 2e-3))
    # in mesh with backlash, the two solids of a pair share no volume
    def shared(p, q):
        c = p & q
        return float(c.volume) if c is not None else 0.0

    g = run("gear", dict(module=2, z1=14, z2=30, x1=0.3, backlash=0.1))["geometry"]["values"]
    rows.append(_g("spur pair, x = 0.3, backlash 0.1", "volume the meshed pinion and gear share", 0.0, shared(shapes.gear_pinion(g), shapes.gear_wheel(g)), 1e-3, "mm³"))
    g = run("gear", dict(module=2, z1=15, z2=31, helix=20, face=10, backlash=0.1))["geometry"]["values"]
    rows.append(_g("helical pair, β = 20°, backlash 0.1", "volume the meshed pinion and gear share", 0.0, shared(shapes.gear_pinion(g), shapes.gear_wheel(g)), 1e-3, "mm³"))
    g = run("gear", dict(kind="internal", module=2, z1=16, z2=48, backlash=0.1))["geometry"]["values"]
    rows.append(_g("internal pair, backlash 0.1", "volume the pinion and the internal gear share", 0.0, shared(shapes.rack_pinion(g), shapes.gear_ring(g)), 1e-3, "mm³"))
    # rack
    r = run("gear", dict(kind="rack", module=2, z1=18, backlash=0.1))
    g = r["geometry"]["values"]
    s = shapes.gear_rack(g)
    lo, hi = box(s)
    rows += [_g("rack", "length = teeth × π m", 10 * math.pi * 2, hi.Y - lo.Y, 1e-4),
             _g("rack and pinion, backlash 0.1", "volume the pinion and the rack share", 0.0, shared(shapes.rack_pinion(g), s), 1e-3, "mm³")]
    # cam
    r = run("cam", dict(lift=8, rise=120, dwell=60, fall=120, roller_radius=4, base_radius=20))
    s = shapes.cam(r["geometry"]["values"])
    pts = [(vx.X, vx.Y) for vx in s.vertices()]
    lo, hi = box(s)
    rows += [_g("cam", "largest radius = base circle + lift (extent toward the dwell)", 28.0, max(-lo.X, hi.X, -lo.Y, hi.Y), 0.02),
             _g("cam", "valid solid", 1, int(s.is_valid and len(s.solids()) == 1 and bool(pts)), 0, "")]
    # fit
    r = run("fit", dict(fit="H7/g6", diameter=25))
    g = r["geometry"]["values"]
    s = shapes.fit_shaft(g)
    lo, hi = box(s)
    rows.append(_g("fit pair", "pin diameter = middle of g6 at Ø25", 24.9865, hi.Y - lo.Y, 1e-4))
    # insert boss
    r = run("fastener", dict(kind="boss", size="M3"))
    g = r["geometry"]["values"]
    boss, pocket = shapes.insert_boss(g, "M3")
    lo, hi = box(boss)
    plo, phi_ = box(pocket)
    rows += [_g("insert boss", "boss diameter = hole + 2 × least wall (CNC Kitchen M3: 4.0 + 2 × 1.6)", 7.2, hi.X - lo.X, 1e-4),
             _g("insert boss", "pocket depth below the boss top = insert length + 1", 6.7, g["height"] - plo.Z, 1e-3)]
    return rows


def summary(rows: list) -> dict:
    return {"rows": len(rows), "passed": sum(1 for r in rows if r["pass"]), "failed": [r for r in rows if not r["pass"]]}
