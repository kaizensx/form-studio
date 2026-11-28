"""Involute gears: spur and helical pairs with profile shift, internal gears and racks.

Geometry is the involute's own (ISO 21771; the worked tables of the KHK Gear Technical Reference are the check):

    transverse section       α_t = atan(tan α_n / cos β),  m_t = m_n / cos β,  d = z · m_t,  d_b = d · cos α_t
    working pressure angle   inv α_wt = inv α_t + 2 tan α_n · (x1 + x2) / (z1 + z2),      inv α = tan α − α
    centre distance          a_w = a · cos α_t / cos α_wt,   a = m_t (z1 + z2) / 2
    tooth depth              h_a1 = (1 + y − x2) m_n,  h = (2.25 + y − (x1 + x2)) m_n,  y = (a_w − a) / m_n
    contact ratio            ε_α = [√(r_a1² − r_b1²) + √(r_a2² − r_b2²) − a_w sin α_wt] / (π m_t cos α_t)
    overlap ratio            ε_β = b · sin β / (π m_n)
    undercut                 x_min = 1 − z sin² α_t / (2 cos β)
    backlash                 j_bn = 2 m_n Δx sin α_n  from a centre distance set wider than the tight mesh, plus thinning

Tooth strength is the Lewis bending equation, σ = K_v · F_t / (b · m_n · Y), with the Lewis form factor of Shigley's
Table 14-2 (20° full-depth teeth) and Barth's velocity factor. That is what is computed, and what is left out is said:
no ISO 6336 or AGMA factors (stress concentration, load sharing, application, size, life), no contact (pitting)
stress, and the form factor is the unshifted 20° value even when the teeth are shifted or helical (then with the
virtual tooth count z / cos³ β).

The solid is written with py_gearworks' involute generator; form/calc/design.py measures the built tooth against the
exact involute thickness at several radii and reports the largest difference.
"""
from __future__ import annotations

import math

from . import I, Sheet, choice, material_kind, material_prop, need, number

ISO21771 = ("ISO 21771:2007, Gears: cylindrical involute gears and gear pairs, concepts and geometry", "")
KHK = ("KHK Gear Technical Reference, Calculation of gear dimensions",
       "https://khkgears.net/new/gear_knowledge/gear_technical_reference/calculation_gear_dimensions.html")
SHIGLEY = ("Budynas and Nisbett, Shigley's Mechanical Engineering Design, 10th ed., chapters 13 and 14", "")
# Shigley Table 14-2: Lewis form factor Y, 20° pressure angle, full-depth teeth, load at the tip
LEWIS = ((12, 0.245), (13, 0.261), (14, 0.277), (15, 0.290), (16, 0.296), (17, 0.303), (18, 0.309), (19, 0.314),
         (20, 0.322), (21, 0.328), (22, 0.331), (24, 0.337), (26, 0.346), (28, 0.353), (30, 0.359), (34, 0.371),
         (38, 0.384), (43, 0.397), (50, 0.409), (60, 0.422), (75, 0.435), (100, 0.447), (150, 0.460), (300, 0.472),
         (400, 0.480))
LEWIS_RACK = 0.485


def spec() -> dict:
    return {"id": "gear", "title": "Involute gears", "standard": "ISO 21771 geometry; Lewis bending (no ISO 6336 factors)",
            "doc": "A spur or helical pair with profile shift, an internal pair or a rack and pinion: centre distance, "
                   "contact ratio, undercut, backlash and Lewis bending stress. Writes the gears in mesh.",
            "writes": "the gears as involute solids in mesh at the working centre distance, with parameters",
            "inputs": [
                I("kind", "Pair", "", "external", "", ("external", "internal", "rack")),
                I("module", "Normal module m_n", "mm", None, ""),
                I("z1", "Pinion teeth", "", None, ""),
                I("z2", "Gear teeth", "", None, "external and internal; a rack has none"),
                I("pressure_angle", "Normal pressure angle α_n", "deg", 20.0, ""),
                I("helix", "Helix angle β", "deg", 0.0, "0: spur"),
                I("x1", "Pinion profile shift", "", 0.0, "coefficient"),
                I("x2", "Gear profile shift", "", 0.0, "coefficient; external pairs only"),
                I("centre_distance", "Working centre distance", "mm", None, "left out: the tight mesh of the shifts given"),
                I("backlash", "Tooth thinning for backlash", "mm", 0.0, "normal backlash taken off the teeth, half from each gear"),
                I("face", "Face width b", "mm", None, "default 8 m"),
                I("torque", "Torque on the pinion", "N·mm", None, "for the bending stress"),
                I("speed", "Pinion speed", "rpm", None, "for the velocity factor"),
                I("material", "Gear material", "", None, "library key: the strength the stress is compared with"),
                I("direction", "Load direction of a printed tooth", "", "xy", "", ("xy", "z")),
                I("bore1", "Pinion bore", "mm", 0.0, "geometry"),
                I("bore2", "Gear bore", "mm", 0.0, "geometry"),
                I("rack_teeth", "Teeth on the rack", "", 10, "geometry"),
                I("rim", "Rim thickness of the internal gear", "mm", None, "geometry; default 3 m"),
            ]}


def inv(a: float) -> float:
    return math.tan(a) - a


def inv_inverse(v: float) -> float:
    """The angle (radians) whose involute function is v, by Newton's method."""
    a = (3 * v) ** (1 / 3) if v > 0 else 0.0
    for _ in range(60):
        f = math.tan(a) - a - v
        a -= f / (math.tan(a) ** 2 or 1e-12)
        if abs(f) < 1e-15:
            break
    return a


def lewis_y(z: float) -> float:
    """Lewis form factor by teeth, interpolated in 1/z between the table's rows (the table is close to linear in 1/z)."""
    if z >= LEWIS[-1][0]:
        z0, y0 = LEWIS[-1]
        return y0 + (LEWIS_RACK - y0) * (1 - z0 / z)
    if z <= LEWIS[0][0]:
        return LEWIS[0][1]
    for (za, ya), (zb, yb) in zip(LEWIS, LEWIS[1:]):
        if za <= z <= zb:
            t = (1 / za - 1 / z) / (1 / za - 1 / zb)
            return ya + (yb - ya) * t
    return LEWIS[-1][1]


def tooth_thickness(r: float, z: int, m_t: float, alpha_t: float, x: float, alpha_n: float, thin: float = 0.0) -> float:
    """Transverse arc tooth thickness (mm) at radius r of an involute tooth: the exact relation the built solid is
    measured against. thin: the transverse arc thinning at the reference circle."""
    rp = z * m_t / 2
    rb = rp * math.cos(alpha_t)
    s_p = m_t * (math.pi / 2 + 2 * x * math.tan(alpha_n)) - thin      # s_t = s_n / cos β, s_n = m_n (π/2 + 2 x tan α_n)
    a_r = math.acos(min(1.0, rb / r))
    return 2 * r * (s_p / (2 * rp) + inv(alpha_t) - inv(a_r))


def run(inputs: dict) -> dict:
    kind = choice(inputs, "kind", ("external", "internal", "rack"), "external")
    s = Sheet("gear", {"external": "Involute gear pair", "internal": "Internal gear pair", "rack": "Rack and pinion"}[kind],
              "ISO 21771 (geometry); Lewis bending, simplified", inputs)
    iso = s.source("iso21771", *ISO21771)
    khk = s.source("khk", *KHK)
    sh = s.source("shigley", *SHIGLEY)
    s.eq("transverse", "α_t = atan(tan α_n / cos β),  m_t = m_n / cos β,  d = z · m_t,  d_b = d · cos α_t", iso)
    s.eq("involute", "inv α = tan α − α", iso)
    m = number(inputs, "module", None, 0.05, 100)
    z1 = number(inputs, "z1", None, 5, 2000, whole=True)
    need(m is not None and z1 is not None, "A gear needs its module and the pinion's tooth count.", "module=1.5 z1=17 z2=40.", ["module", "z1"])
    z2 = number(inputs, "z2", None, 5, 5000, whole=True)
    need(kind == "rack" or z2 is not None, "Give the gear's tooth count z2.", "", ["z2"])
    s.given("module", "Normal module m_n", m, "mm")
    s.given("z1", "Pinion teeth z1", z1, "")
    if z2 is not None and kind != "rack":
        s.given("z2", "Gear teeth z2", z2, "")
    an_deg = number(inputs, "pressure_angle", 20.0, 10, 35)
    (s.given if "pressure_angle" in inputs else lambda *a: s.add(*a, "specified", source=iso, note="the standard basic rack's 20°"))("pressure_angle", "Normal pressure angle α_n", an_deg, "deg")
    beta_deg = number(inputs, "helix", 0.0, 0, 45)
    if beta_deg:
        s.given("helix", "Helix angle β", beta_deg, "deg")
    x1 = number(inputs, "x1", 0.0, -1, 1.5)
    x2 = number(inputs, "x2", 0.0, -1, 1.5)
    need(kind == "external" or (x2 == 0), "Profile shift on an internal gear or a rack is not supported here.",
         "Leave x2 out; shift the pinion only.", ["x2"])
    need(kind != "internal" or x1 == 0, "Profile shift in an internal pair is not supported here.", "Leave x1 out.", ["x1"])
    if x1 or "x1" in inputs:
        s.given("x1", "Pinion profile shift x1", x1, "")
    if x2 or "x2" in inputs:
        s.given("x2", "Gear profile shift x2", x2, "")
    an, beta = math.radians(an_deg), math.radians(beta_deg)
    at = math.atan(math.tan(an) / math.cos(beta))
    mt = m / math.cos(beta)
    s.computed("alpha_t", "Transverse pressure angle α_t", math.degrees(at), "deg", "transverse")
    d1 = s.computed("d1", "Pinion reference diameter d1", z1 * mt, "mm", "transverse")
    db1 = s.computed("db1", "Pinion base diameter d_b1", d1 * math.cos(at), "mm", "transverse")
    b = number(inputs, "face", None, 0.5, 2000)
    if b is None:
        b = s.assumed("face", "Face width b", 8 * m, "mm", "8 modules, a usual proportion, unless the request gives it")
    else:
        s.given("face", "Face width b", b, "mm")
    thin = number(inputs, "backlash", 0.0, 0, 5)
    s.eq("undercut", "x_min = 1 − z · sin² α_t / (2 cos β)", khk, "below it the cutter undercuts the root (basic rack addendum 1 m)")
    aw_in = number(inputs, "centre_distance", None, 0.1, 1e5)
    geom = {"module": m, "z1": z1, "pressure_angle": an_deg, "helix": beta_deg, "x1": x1, "face": b, "backlash": thin,
            "bore1": number(inputs, "bore1", 0.0, 0, 1e4)}
    jbn_cd = 0.0

    def undercut(tag, z, x):
        xmin = s.computed(f"x_min{tag}", f"Least profile shift without undercut, {'pinion' if tag == '1' else 'gear'}", 1 - z * math.sin(at) ** 2 / (2 * math.cos(beta)), "", "undercut")
        s.check(f"undercut{tag}", f"Undercut, {'pinion' if tag == '1' else 'gear'}", "PASS" if x >= xmin - 1e-9 else "WARN", f"x = {x:g}, least {xmin:.3f}",
                "No undercut." if x >= xmin - 1e-9 else "The root is undercut: weaker teeth and a shorter involute. Shift the profile by at least the value shown, or use more teeth.", "undercut")

    undercut("1", z1, x1)
    if kind == "external":
        s.eq("working_angle", "inv α_wt = inv α_t + 2 tan α_n · (x1 + x2) / (z1 + z2)", khk, "tight mesh (no backlash)")
        s.eq("centre", "a = m_t (z1 + z2)/2,  a_w = a · cos α_t / cos α_wt,  y = (a_w − a)/m_n", khk)
        s.eq("depth", "h_a1 = (1 + y − x2) m_n,  h_a2 = (1 + y − x1) m_n,  h = (2.25 + y − (x1 + x2)) m_n,  d_a = d + 2 h_a,  d_f = d_a − 2 h", khk,
             "tips shortened so the standard 0.25 m_n clearance is kept")
        s.eq("contact", "ε_α = [√(r_a1² − r_b1²) + √(r_a2² − r_b2²) − a_w sin α_wt] / (π m_t cos α_t)", iso)
        s.eq("backlash", "j_bn = 2 m_n · Δx · sin α_n,   Δx = (z1 + z2)(inv α_wt − inv α_t)/(2 tan α_n) − (x1 + x2)", khk,
             "normal backlash from a centre distance wider than the tight mesh")
        d2 = s.computed("d2", "Gear reference diameter d2", z2 * mt, "mm", "transverse")
        db2 = s.computed("db2", "Gear base diameter d_b2", d2 * math.cos(at), "mm", "transverse")
        a_ref = mt * (z1 + z2) / 2
        awt_tight = inv_inverse(inv(at) + 2 * math.tan(an) * (x1 + x2) / (z1 + z2))
        a_tight = a_ref * math.cos(at) / math.cos(awt_tight)
        if aw_in is None:
            awt, aw = awt_tight, a_tight
            s.computed("alpha_wt", "Working transverse pressure angle α_wt", math.degrees(awt), "deg", "working_angle")
            s.computed("centre_distance", "Working centre distance a_w", aw, "mm", "centre")
        else:
            need(aw_in >= a_tight - 1e-6, f"That centre distance ({aw_in:g} mm) is tighter than the gears mesh at ({a_tight:.4f} mm): they jam.",
                 "Widen it, or lower the profile shifts.", ["centre_distance"])
            aw = s.given("centre_distance", "Working centre distance a_w", aw_in, "mm")
            awt = math.acos(a_ref * math.cos(at) / aw)
            s.eq("working_angle_cd", "α_wt = acos(a · cos α_t / a_w)", khk, "from the centre distance as mounted")
            s.computed("alpha_wt", "Working transverse pressure angle α_wt", math.degrees(awt), "deg", "working_angle_cd")
            dx = (z1 + z2) * (inv(awt) - inv(at)) / (2 * math.tan(an)) - (x1 + x2)
            jbn_cd = s.computed("backlash_centre", "Normal backlash from the centre distance", 2 * m * dx * math.sin(an), "mm", "backlash")
        y = s.computed("y", "Centre distance modification y", (a_tight - a_ref) / m, "", "centre",
                       "of the tight mesh; the tooth depth follows it")
        ha1, ha2 = (1 + y - x2) * m, (1 + y - x1) * m
        h = (2.25 + y - (x1 + x2)) * m
        da1 = s.computed("da1", "Pinion tip diameter d_a1", d1 + 2 * ha1, "mm", "depth")
        da2 = s.computed("da2", "Gear tip diameter d_a2", d2 + 2 * ha2, "mm", "depth")
        s.computed("df1", "Pinion root diameter d_f1", da1 - 2 * h, "mm", "depth")
        s.computed("df2", "Gear root diameter d_f2", da2 - 2 * h, "mm", "depth")
        s.computed("depth", "Tooth depth h", h, "mm", "depth")
        need(da1 / 2 > db1 / 2 and da2 / 2 > db2 / 2, "The teeth have no involute left at these shifts.", "Lower the shifts.", ["x1", "x2"])
        ea = (math.sqrt((da1 / 2) ** 2 - (db1 / 2) ** 2) + math.sqrt((da2 / 2) ** 2 - (db2 / 2) ** 2) - aw * math.sin(awt)) / (math.pi * mt * math.cos(at))
        undercut("2", z2, x2)
        dw1 = 2 * aw * z1 / (z1 + z2)
        s.eq("ratio", "i = z2 / z1,  d_w1 = 2 a_w z1 / (z1 + z2)", iso)
        s.computed("ratio", "Ratio i", z2 / z1, "", "ratio")
        geom.update(z2=z2, x2=x2, centre=aw, ha1=ha1 / m, ha2=ha2 / m, depth=h / m, bore2=number(inputs, "bore2", 0.0, 0, 1e4))
        gkind, name = "gear_pair", f"m{m:g} gear pair {z1}:{z2}"
        zs = [(z1, x1, da1, "1"), (z2, x2, da2, "2")]
    elif kind == "internal":
        s.eq("centre", "a = m_t (z2 − z1) / 2", khk, "internal pair, no profile shift")
        s.eq("depth", "d_a1 = d1 + 2 m_n,  d_a2 = d2 − 2 m_n (the ring's tips point inward),  d_f2 = d2 + 2.5 m_n", khk)
        s.eq("contact", "ε_α = [√(r_a1² − r_b1²) − √(r_a2² − r_b2²) + a sin α_t] / (π m_t cos α_t)", iso)
        need(z2 > z1 + 2, "The ring needs more teeth than the pinion.", "", ["z2"])
        d2 = s.computed("d2", "Ring reference diameter d2", z2 * mt, "mm", "transverse")
        db2 = s.computed("db2", "Ring base diameter d_b2", d2 * math.cos(at), "mm", "transverse")
        aw = s.computed("centre_distance", "Centre distance a", mt * (z2 - z1) / 2, "mm", "centre")
        awt = at
        da1 = s.computed("da1", "Pinion tip diameter d_a1", d1 + 2 * m, "mm", "depth")
        da2 = s.computed("da2", "Ring tip (inner) diameter d_a2", d2 - 2 * m, "mm", "depth")
        need(da2 > db2, f"With {z2} teeth the ring's tips fall inside its base circle: no involute there.",
             "Use more teeth on the ring (above about 34 at 20°).", ["z2"])
        ea = (math.sqrt((da1 / 2) ** 2 - (db1 / 2) ** 2) - math.sqrt((da2 / 2) ** 2 - (db2 / 2) ** 2) + aw * math.sin(at)) / (math.pi * mt * math.cos(at))
        s.check("interference", "Tip interference", "PASS" if z2 - z1 >= 10 else "WARN", f"z2 − z1 = {z2 - z1}",
                "A rule of thumb for 20° full-depth teeth (assumed, not computed): with fewer than about 10 teeth of "
                "difference the pinion's tips foul the ring's on the way in. The interference itself is not computed.",
                evidence="assumed")
        dw1 = d1
        s.eq("ratio", "i = z2 / z1", iso)
        s.computed("ratio", "Ratio i", z2 / z1, "", "ratio")
        rim = number(inputs, "rim", None, 0.5, 1000) or 3 * m
        geom.update(z2=z2, centre=aw, rim=rim)
        gkind, name = "gear_internal", f"m{m:g} internal pair {z1}:{z2}"
        zs = [(z1, x1, da1, "1")]
    else:
        s.eq("centre", "a = d1 / 2 + x1 · m_n", khk, "pinion axis to the rack's pitch line")
        s.eq("depth", "d_a1 = d1 + 2 m_n (1 + x1)", khk)
        s.eq("contact", "ε_α = [√(r_a1² − r_b1²) − r_b1 tan α_t + (1 − x1) m_n / sin α_t] / (π m_t cos α_t)", iso)
        s.eq("travel", "travel per turn = π · d1,  rack pitch = π · m_t", iso)
        aw = s.computed("centre_distance", "Pinion axis to the rack's pitch line", d1 / 2 + x1 * m, "mm", "centre")
        awt = at
        da1 = s.computed("da1", "Pinion tip diameter d_a1", d1 + 2 * m * (1 + x1), "mm", "depth")
        ea = (math.sqrt((da1 / 2) ** 2 - (db1 / 2) ** 2) - db1 / 2 * math.tan(at) + (1 - x1) * m / math.sin(at)) / (math.pi * mt * math.cos(at))
        s.computed("travel", "Rack travel per pinion turn", math.pi * d1, "mm", "travel")
        s.computed("rack_pitch", "Rack pitch", math.pi * mt, "mm", "travel")
        dw1 = d1
        geom.update(centre=aw, rack_teeth=number(inputs, "rack_teeth", 10, 2, 400, whole=True))
        gkind, name = "gear_rack", f"m{m:g} rack and pinion, {z1} teeth"
        zs = [(z1, x1, da1, "1")]
    ea = s.computed("contact_ratio", "Transverse contact ratio ε_α", ea, "", "contact")
    total = ea
    if beta_deg:
        s.eq("overlap", "ε_β = b · sin β / (π m_n)", iso)
        eb = s.computed("overlap_ratio", "Overlap ratio ε_β", b * math.sin(beta) / (math.pi * m), "", "overlap")
        total = s.computed("total_contact_ratio", "Total contact ratio ε_γ", ea + eb, "", "overlap")
    s.check("contact", "Contact ratio", "PASS" if ea >= 1.2 else ("WARN" if total >= 1.0 else "FAIL"), f"ε_α = {ea:.3f}" + (f", total {total:.3f}" if beta_deg else ""),
            "At least 1.2 in the transverse plane is the usual floor for smooth running; under 1.0 in total the teeth lose contact between pairs.", "contact")
    s.eq("tip", "s_a = d_a · [(π/2 + 2 x tan α_n)/z + inv α_t − inv α_a],  α_a = acos(d_b / d_a)", iso, "transverse tooth thickness at the tip")
    for z, x, da, tag in zs:
        aa = math.acos(z * mt * math.cos(at) / da)
        sa = s.computed(f"tip_thickness{tag}", f"Tip thickness, {'pinion' if tag == '1' else 'gear'}", da * ((math.pi / 2 + 2 * x * math.tan(an)) / z + inv(at) - inv(aa)), "mm", "tip")
        s.check(f"tip{tag}", f"Tooth tip, {'pinion' if tag == '1' else 'gear'}", "PASS" if sa >= 0.25 * m else ("WARN" if sa > 0 else "FAIL"), f"{sa:.2f} mm",
                "At least 0.25 m_n keeps the tip from being a knife edge (0.4 m_n for hardened teeth)." if sa > 0 else "The flanks cross below the tip: pointed teeth. Lower the shift.", "tip")
    s.eq("backlash_total", "j_bn,total = j_bn(centre distance) + tooth thinning", khk)
    if thin:
        s.given("backlash_thinning", "Tooth thinning for backlash (normal, both gears together)", thin, "mm")
    s.computed("backlash_total", "Normal backlash in the mesh", jbn_cd + thin, "mm", "backlash_total")
    if jbn_cd + thin <= 0:
        s.check("backlash", "Backlash", "WARN", "0 mm", "A tight mesh: it binds with any error in the centre distance, "
                "heat or (printed) elephant's foot. Give backlash (0.05 to 0.1 m_n is common; printed gears more).", "backlash_total")
    # ---- bending, Lewis ----
    T = number(inputs, "torque", None, 0, 1e9)
    if T is not None:
        s.eq("tangential", "F_t = 2 T / d_w1", iso)
        s.eq("lewis", "σ_F = K_v · F_t / (b · m_n · Y)", sh, "eq. 14-8 in metric form. Simplified: no ISO 6336 / AGMA "
             "factors, load taken by one tooth at its tip, no stress concentration at the root fillet")
        s.eq("barth", "K_v = (6.1 + V) / 6.1,  V = π d_w1 n / 60000  (m/s)", sh, "eq. 14-6b: Barth's velocity factor for cut or milled teeth")
        s.given("torque", "Torque on the pinion", T, "N·mm")
        Ft = s.computed("tangential_force", "Tangential force F_t", 2 * T / dw1, "N", "tangential")
        rpm = number(inputs, "speed", None, 0, 1e6)
        Kv = 1.0
        if rpm is not None:
            s.given("speed", "Pinion speed", rpm, "rpm")
            V = math.pi * dw1 * rpm / 60000.0
            s.computed("pitch_velocity", "Pitch-line velocity V", V, "m/s", "barth")
            Kv = s.computed("Kv", "Velocity factor K_v", (6.1 + V) / 6.1, "", "barth")
        zv = z1 / math.cos(beta) ** 3
        Y = s.add("Y", "Lewis form factor Y" + (f" (virtual teeth {zv:.1f})" if beta_deg else ""), lewis_y(zv), "", "specified", source=sh,
                  note="Table 14-2, 20° full depth, unshifted; interpolated in 1/z")
        if abs(an_deg - 20) > 1e-6 or x1:
            s.caveat("The Lewis form factor is the table's value for unshifted 20° full-depth teeth; this pinion is "
                     "shifted or has another pressure angle, so the bending stress is approximate (a positive shift "
                     "makes the real tooth stronger than computed).")
        sig = s.computed("bending_stress", "Bending stress at the pinion root σ_F", Kv * Ft / (b * m * Y), "MPa", "lewis")
        material = inputs.get("material") or None
        direction = choice(inputs, "direction", ("xy", "z"), "xy")
        ref = material_prop(s, material, "yield", "strength", "Yield strength", unit="MPa") if material else None
        if ref is None and material:
            ref = material_prop(s, material, "uts", "strength", "Tensile strength", direction=direction, unit="MPa")
        if ref:
            s.eq("bending_sf", "S = strength / σ_F", "", "static strength; fatigue of the root is not assessed")
            SF = s.computed("bending_safety", "Safety against the sourced strength", ref / sig, "", "bending_sf")
            s.check("bending", "Tooth bending", "PASS" if SF >= 2 else ("WARN" if SF >= 1 else "FAIL"), f"{sig:.1f} MPa, S = {SF:.2f}",
                    "Lewis, static. Under 2 is marked because nothing here covers fatigue, shock or the root's stress concentration.", "lewis")
            if material_kind(material)["kind"] == "filament":
                s.caveat("Printed gear: the datasheet's strength is of a solid printed specimen; teeth printed flat "
                         "are loaded along their layers, and they creep and wear. Treat the safety figure as a ranking, not a rating.")
        else:
            s.missing("bending_safety", "Verdict on tooth bending", "No sourced strength: give material (a library key).")
        s.caveat("Bending only, by Lewis: no surface (pitting) stress, no ISO 6336 or AGMA factors, no fatigue life.")
    s.geometry(gkind, geom, name, {"material": inputs.get("material") or ""})
    return s.done(f"a = {aw:.3f} mm, α_w = {math.degrees(awt):.2f}°, contact ratio {ea:.2f}"
                  + (f", bending {s['bending_stress']:.1f} MPa" if T is not None else ""))
