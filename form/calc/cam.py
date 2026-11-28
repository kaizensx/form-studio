"""Plate cams from a motion law, for a translating roller follower.

The follower rises by h over the cam angle β, dwells, falls and dwells. Three laws, each with its derivatives in
closed form (u = θ / β):

    cycloidal     s = h (u − sin 2πu / 2π)              zero acceleration at both ends: the usual choice with dwells
    harmonic      s = h/2 (1 − cos πu)                  finite acceleration at the ends: a jerk spike against a dwell
    poly345       s = h (10u³ − 15u⁴ + 6u⁵)             the 3-4-5 polynomial: zero velocity and acceleration at the ends

    pressure angle        φ = atan((s′ − e) / (s + √(R_p² − e²)))             s′ = ds/dθ, e the follower's offset
    radius of curvature   ρ = ((R_p + s)² + s′²)^1.5 / ((R_p + s)² + 2 s′² − (R_p + s) s″)        pitch curve, e = 0

R_p is the prime circle radius (base circle + roller). The checks are Norton's: a pressure angle within about 30° for
a translating follower, and the smallest convex radius of curvature of the pitch curve above the roller's radius
(two to three times it is the recommendation), or the cam is undercut and the follower cannot follow the law.
"""
from __future__ import annotations

import math

from . import I, Sheet, choice, need, number

NORTON = ("Norton, Design of Machinery, 5th ed., chapter 8 (Cam Design); also Norton, Cam Design and Manufacturing Handbook, 2nd ed.", "")
LAWS = ("cycloidal", "harmonic", "poly345")


def law(kind: str, u: float) -> tuple[float, float, float]:
    """(s/h, (ds/du)/h, (d²s/du²)/h) at u in [0, 1]."""
    if kind == "cycloidal":
        return u - math.sin(2 * math.pi * u) / (2 * math.pi), 1 - math.cos(2 * math.pi * u), 2 * math.pi * math.sin(2 * math.pi * u)
    if kind == "harmonic":
        return (1 - math.cos(math.pi * u)) / 2, math.pi / 2 * math.sin(math.pi * u), math.pi ** 2 / 2 * math.cos(math.pi * u)
    return 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5, 30 * u * u - 60 * u ** 3 + 30 * u ** 4, 60 * u - 180 * u * u + 120 * u ** 3


def motion(kind: str, h: float, rise: float, dwell: float, fall: float, deg: float) -> tuple[float, float, float]:
    """(s, ds/dθ, d²s/dθ²) in mm, mm/rad, mm/rad² at cam angle deg; rise, dwell, fall in degrees."""
    deg %= 360.0
    if deg < rise:
        b = math.radians(rise)
        s, v, a = law(kind, deg / rise)
        return h * s, h * v / b, h * a / b ** 2
    if deg < rise + dwell:
        return h, 0.0, 0.0
    if deg < rise + dwell + fall:
        b = math.radians(fall)
        s, v, a = law(kind, (deg - rise - dwell) / fall)
        return h * (1 - s), -h * v / b, -h * a / b ** 2
    return 0.0, 0.0, 0.0


def spec() -> dict:
    return {"id": "cam", "title": "Plate cam from a motion law", "standard": "Norton, Design of Machinery, chapter 8",
            "doc": "A rise-dwell-fall-dwell plate cam for a translating roller follower: velocity and acceleration "
                   "peaks, pressure angle and undercut. Writes the cam plate with its bore.",
            "writes": "the cam plate (the pitch curve offset inward by the roller), with parameters",
            "inputs": [
                I("law", "Motion law", "", "cycloidal", "", LAWS),
                I("lift", "Lift h", "mm", None, ""),
                I("rise", "Rise angle", "deg", 120.0, ""),
                I("dwell", "Dwell at the top", "deg", 60.0, ""),
                I("fall", "Fall angle", "deg", 120.0, ""),
                I("base_radius", "Base circle radius", "mm", None, "the cam's smallest radius; left out: the smallest that keeps the pressure angle"),
                I("roller_radius", "Roller radius", "mm", 5.0, ""),
                I("offset", "Follower offset e", "mm", 0.0, "the pressure angle only; the curvature check and the solid are for e = 0"),
                I("speed", "Cam speed", "rpm", None, "for velocity and acceleration in mm/s and mm/s²"),
                I("max_pressure_angle", "Largest pressure angle allowed", "deg", 30.0, ""),
                I("thickness", "Plate thickness", "mm", 8.0, "geometry"),
                I("bore", "Bore", "mm", 6.0, "geometry"),
            ]}


def scan(kind: str, h: float, rise: float, dwell: float, fall: float, Rp: float, e: float = 0.0, n: int = 7200) -> dict:
    out = {"v": 0.0, "a": 0.0, "phi": 0.0, "phi_at": 0.0, "rho_convex": math.inf, "rho_concave": math.inf}
    root = math.sqrt(max(Rp * Rp - e * e, 1e-12))
    for i in range(n):
        th = 360.0 * i / n
        s, v, a = motion(kind, h, rise, dwell, fall, th)
        out["v"], out["a"] = max(out["v"], abs(v)), max(out["a"], abs(a))
        phi = abs(math.degrees(math.atan2(v - e, s + root)))
        if phi > out["phi"]:
            out["phi"], out["phi_at"] = phi, th
        r = Rp + s
        den = r * r + 2 * v * v - r * a
        if abs(den) > 1e-12:
            rho = (r * r + v * v) ** 1.5 / den
            if rho > 0:
                out["rho_convex"] = min(out["rho_convex"], rho)
            else:
                out["rho_concave"] = min(out["rho_concave"], -rho)
    return out


def run(inputs: dict) -> dict:
    s = Sheet("cam", "Plate cam", "Norton, Design of Machinery, chapter 8 (Cam Design)", inputs)
    nor = s.source("norton", *NORTON)
    kind = choice(inputs, "law", LAWS, "cycloidal")
    s.eq("law", {"cycloidal": "s = h (u − sin 2πu / 2π)", "harmonic": "s = h/2 (1 − cos πu)",
                 "poly345": "s = h (10u³ − 15u⁴ + 6u⁵)"}[kind] + ",  u = θ / β", nor)
    s.eq("peaks", "v_max = C_v · h / β,  a_max = C_a · h / β²   (β in radians; per unit cam speed)", nor,
         "C_v, C_a: cycloidal 2 and 2π; harmonic π/2 and π²/2; 3-4-5 polynomial 1.875 and 5.7735")
    s.eq("pressure", "φ = atan((s′ − e) / (s + √(R_p² − e²))),  R_p = R_b + R_f", nor, "translating roller follower")
    s.eq("curvature", "ρ = ((R_p + s)² + s′²)^1.5 / ((R_p + s)² + 2 s′² − (R_p + s) s″)", nor, "pitch curve, radial follower")
    s.eq("time", "v = s′ · ω,  a = s″ · ω²,  ω = 2π n / 60", nor)
    h = number(inputs, "lift", None, 0.05, 1000)
    need(h is not None, "A cam needs its lift.", "lift=8 (mm).", ["lift"])
    s.given("lift", "Lift h", h, "mm")
    rise, dwell, fall = number(inputs, "rise", 120.0, 5, 350), number(inputs, "dwell", 60.0, 0, 340), number(inputs, "fall", 120.0, 5, 350)
    need(rise + dwell + fall <= 360 + 1e-9, "Rise, dwell and fall exceed one turn.", "Shorten one of them.", ["rise", "dwell", "fall"])
    for k, lab, v in (("rise", "Rise angle β", rise), ("dwell", "Dwell at the top", dwell), ("fall", "Fall angle", fall)):
        (s.given if k in inputs else lambda *a: s.assumed(*a, "a default the request can replace"))(k, lab, v, "deg")
    Rf = number(inputs, "roller_radius", 5.0, 0, 500)
    (s.given if "roller_radius" in inputs else lambda *a: s.assumed(*a, "5 mm, unless the request gives the roller"))("roller_radius", "Roller radius R_f", Rf, "mm")
    e = number(inputs, "offset", 0.0, -500, 500)
    if e:
        s.given("offset", "Follower offset e", e, "mm")
    lim = number(inputs, "max_pressure_angle", 30.0, 5, 60)
    (s.given if "max_pressure_angle" in inputs else lambda *a: s.add(*a, "specified", source=nor, note="about 30° for a translating follower"))("max_pressure_angle", "Largest pressure angle allowed", lim, "deg")
    Rb = number(inputs, "base_radius", None, 1, 5000)
    if Rb is None:
        lo, hi = max(abs(e) + 0.5, 1.0), 5000.0
        need(scan(kind, h, rise, dwell, fall, hi + Rf, e, 720)["phi"] <= lim, "No base circle up to 5 m keeps that pressure angle.",
             "Lengthen the rise and fall, or allow a larger pressure angle.", ["rise", "fall"])
        for _ in range(50):
            mid = (lo + hi) / 2
            if scan(kind, h, rise, dwell, fall, mid + Rf, e, 720)["phi"] <= lim:
                hi = mid
            else:
                lo = mid
        Rb = s.computed("base_radius", "Smallest base circle radius that keeps the pressure angle", math.ceil(hi * 2) / 2, "mm", "pressure",
                        "by bisection on the pressure angle, rounded up to 0.5 mm")
    else:
        s.given("base_radius", "Base circle radius R_b", Rb, "mm")
    s.eq("prime", "R_p = R_b + R_f", nor)
    Rp = s.computed("prime_radius", "Prime circle radius R_p", Rb + Rf, "mm", "prime")
    need(Rp > abs(e), "The follower's offset is outside the prime circle.", "", ["offset"])
    r = scan(kind, h, rise, dwell, fall, Rp, e)
    s.computed("velocity_peak", "Largest ds/dθ", r["v"], "mm/rad", "peaks")
    s.computed("acceleration_peak", "Largest d²s/dθ²", r["a"], "mm/rad²", "peaks")
    rpm = number(inputs, "speed", None, 0, 1e6)
    if rpm is not None:
        w = 2 * math.pi * rpm / 60
        s.given("speed", "Cam speed", rpm, "rpm")
        s.computed("velocity", "Largest follower velocity", r["v"] * w, "mm/s", "time")
        s.computed("acceleration", "Largest follower acceleration", r["a"] * w * w, "mm/s²", "time")
    phi = s.computed("pressure_angle", "Largest pressure angle", r["phi"], "deg", "pressure", f"at {r['phi_at']:.0f}° of cam angle")
    s.check("pressure", "Pressure angle", "PASS" if phi <= lim + 1e-6 else "FAIL", f"{phi:.1f}° of {lim:g}° allowed",
            "Above the limit the side load jams a translating follower in its guide: enlarge the base circle or lengthen the rise.", "pressure")
    rc = r["rho_convex"]
    s.computed("curvature_min", "Smallest convex radius of curvature of the pitch curve", rc, "mm", "curvature")
    if Rf > 0:
        st = "FAIL" if rc <= Rf else ("WARN" if rc < 2 * Rf else "PASS")
        s.check("undercut", "Undercut", st, f"ρ_min = {rc:.2f} mm, roller {Rf:g} mm",
                "ρ_min must exceed the roller radius or the cam is undercut and the follower leaves the law; two to "
                "three times the roller radius is the recommendation.", "curvature")
    if e:
        s.caveat("The curvature check and the solid are for a radial follower (offset 0); the offset enters the pressure angle only.")
    if kind == "harmonic" and (dwell > 0 or rise + dwell + fall < 360):
        s.check("jerk", "Motion law against the dwells", "WARN", "acceleration jumps", "Simple harmonic motion starts and "
                "ends with full acceleration: next to a dwell the jerk is unbounded. Fine for slow cams; use cycloidal or 3-4-5 at speed.", "law")
    T = number(inputs, "thickness", 8.0, 0.5, 500)
    bore = number(inputs, "bore", 6.0, 0, 2 * Rb - 2)
    s.geometry("cam", {"lift": h, "rise": rise, "dwell": dwell, "fall": fall, "base_r": Rb, "roller_r": Rf, "thickness": T,
                       "bore": bore, "law": LAWS.index(kind)}, f"Cam, {h:g} mm lift", {"law": kind})
    return s.done(f"{kind} cam: lift {h:g} mm, base R {Rb:g} mm, pressure angle {phi:.1f}°, ρ_min {rc:.1f} mm")
