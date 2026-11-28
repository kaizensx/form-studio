"""Helical springs from round wire: compression (EN 13906-1), extension (EN 13906-2) and torsion (EN 13906-3).

    rate                R = G d⁴ / (8 D³ n)                          compression and extension
    shear stress        τ = 8 D F / (π d³),  τ_k = k τ               k = (w + 0.5) / (w − 0.75), w = D / d (Bergsträsser)
    buckling            s_K = L0 · 0.5/(1 − G/E) · [1 − √(1 − (1 − G/E)/(0.5 + G/E) · (π D / (ν L0))²)]
    natural frequency   f_e = d / (2 π n D²) · √(G / (2 ρ))          = 3560 d / (n D²) · √(G/ρ) in the standard's units
    torsion rate        M / α = E d⁴ / (3667 D n)  per degree,  σ_q = q · 32 M / (π d³),  q = (w + 0.07) / (w − 0.75)

End types (total coils, solid length) follow Shigley's Table 10-1; the wire's tensile strength, when the request names
a wire instead of giving R_m, is Shigley's Table 10-4 estimate R_m = A / d^m. The permissible stresses are the
standards' shares of R_m (0.56 at solid length for compression, 0.45 for extension, 0.7 in bending for torsion) and
can be given instead.

Printed springs: with a filament from the materials library the same equations run on the datasheet's modulus, with
G = E / (2 (1 + ν)). The sheet then says what the equations do not know about a printed coil: it creeps under a held
load, it is weaker across its layers, and no fatigue data exists for it.
"""
from __future__ import annotations

import math

from . import CalcError, I, Sheet, choice, material_kind, material_prop, need, number

EN1 = ("EN 13906-1:2013, Cylindrical helical springs made from round wire and bar: calculation and design. Part 1: Compression springs", "")
EN2 = ("EN 13906-2:2013, Part 2: Extension springs", "")
EN3 = ("EN 13906-3:2014, Part 3: Torsion springs", "")
SHIGLEY = ("Budynas and Nisbett, Shigley's Mechanical Engineering Design, 10th ed., chapter 10 (Mechanical Springs)", "")
# Shigley Table 10-4: R_m = A / d^m, A in MPa·mm^m, valid diameter range in mm
WIRES = {"music": ("music wire (ASTM A228)", 2211.0, 0.145, 0.10, 6.5),
         "oil_tempered": ("oil-tempered wire (ASTM A229)", 1855.0, 0.187, 0.5, 12.7),
         "hard_drawn": ("hard-drawn wire (ASTM A227)", 1783.0, 0.190, 0.7, 12.7),
         "chrome_vanadium": ("chrome-vanadium wire (ASTM A232)", 2005.0, 0.168, 0.8, 11.1),
         "chrome_silicon": ("chrome-silicon wire (ASTM A401)", 1974.0, 0.108, 1.6, 9.5)}
# Shigley Table 10-1: end type -> (dead coils added to the active ones, extra wire diameters in the solid length)
ENDS = {"open": (0.0, 1.0, "plain ends"), "open_ground": (1.0, 0.0, "plain and ground ends"),
        "closed": (2.0, 1.0, "squared (closed) ends"), "closed_ground": (2.0, 0.0, "squared and ground ends")}
STEEL = {"G": 81500.0, "E": 206000.0, "rho": 7850.0}       # EN 13906-1, patented cold-drawn spring steel wire (EN 10270-1)
SEATING = {0.5: "both ends guided and held square", 0.7: "one end held square, the other pivoted",
           1.0: "both ends pivoted, or both square with one free to move sideways", 2.0: "one end held square, the other free"}
FACTOR = {"compression": (0.56, "EN 13906-1: permissible shear stress at solid length, cold-coiled, 0.56 R_m", "en1"),
          "extension": (0.45, "EN 13906-2: permissible shear stress, cold-coiled, 0.45 R_m", "en2"),
          "torsion": (0.70, "EN 13906-3: permissible bending stress, cold-coiled, 0.7 R_m", "en3")}


def spec() -> dict:
    return {"id": "spring", "title": "Helical spring", "standard": "EN 13906-1 (compression), -2 (extension), -3 (torsion)",
            "doc": "A compression, extension or torsion spring from round wire: rate, stress with the curvature "
                   "correction, solid length, buckling and natural frequency. Writes the coil as a swept solid.",
            "writes": "the coil swept along its centre line (closed and ground ends, or tangent legs; an extension spring as its body), with parameters",
            "inputs": [
                I("kind", "Kind of spring", "", "compression", "", ("compression", "extension", "torsion")),
                I("wire_d", "Wire diameter d", "mm", None, ""),
                I("mean_d", "Mean coil diameter D", "mm", None, ""),
                I("active", "Active coils n", "", None, "left out: from the rate"),
                I("rate", "Rate wanted", "N/mm (torsion: N·mm/deg)", None, "sizes the active coils when they are left out"),
                I("free_length", "Free length L0", "mm", None, "compression; left out: the shortest that gives the travel"),
                I("ends", "Ends", "", "closed_ground", "compression", tuple(ENDS)),
                I("force", "Largest working force", "N", None, "compression and extension"),
                I("deflection", "Largest working deflection", "mm (torsion: deg)", None, ""),
                I("torque", "Largest working torque", "N·mm", None, "torsion"),
                I("initial_tension", "Initial tension F0", "N", 0.0, "extension: the force at which the coils start to open"),
                I("hook_radius", "Mean radius of the hook's bend", "mm", None, "extension; default D / 2"),
                I("leg1", "First leg length", "mm", 20.0, "torsion geometry"),
                I("leg2", "Second leg length", "mm", 20.0, "torsion geometry"),
                I("seating", "Seating coefficient ν", "", 0.5, "compression buckling: 0.5 both ends guided and square, "
                  "0.7, 1 both pivoted, 2 one end free"),
                I("wire", "Spring wire", "", None, "tensile strength from Shigley's Table 10-4", tuple(WIRES)),
                I("Rm", "Tensile strength of the wire R_m", "MPa", None, "your wire's value (EN 10270 table or certificate)"),
                I("stress_factor", "Permissible stress as a share of R_m", "", None, "default: the standard's"),
                I("G", "Shear modulus", "MPa", None, "default: spring steel, or from the material"),
                I("E", "Young's modulus", "MPa", None, ""),
                I("density", "Density", "kg/m³", None, ""),
                I("material", "Printed material", "", None, "a filament of the materials library: printed-spring mode"),
                I("poisson", "Poisson's ratio", "", None, "printed mode; default the assumed 0.35"),
            ]}


def bergstrasser(w: float) -> float:
    return (w + 0.5) / (w - 0.75)


def wahl(w: float) -> float:
    return (4 * w - 1) / (4 * w - 4) + 0.615 / w


def buckling_deflection(L0: float, D: float, G: float, E: float, nu: float):
    """The deflection at which a compression spring buckles (EN 13906-1), or None when it never does."""
    r = 1 - (1 - G / E) / (0.5 + G / E) * (math.pi * D / (nu * L0)) ** 2
    if r < 0:
        return None
    return L0 * 0.5 / (1 - G / E) * (1 - math.sqrt(r))


def natural_frequency(d: float, D: float, n: float, G: float, rho: float) -> float:
    """First natural frequency in Hz of a spring held at both ends; mm, MPa, kg/m³."""
    return (d / (2 * math.pi * n * D * D)) * math.sqrt(G * 1e6 / (2 * rho)) * 1e3


def _material(s: Sheet, inputs: dict, kind: str) -> dict:
    """G, E, ρ and R_m with where each is from; "printed": True for a filament."""
    material = inputs.get("material") or None
    out = {"printed": False, "Rm": None}
    G, E, rho = (number(inputs, k, None, 1, 1e7) for k in ("G", "E", "density"))
    if material:
        mk = material_kind(material)
        out["printed"] = mk["kind"] == "filament"
        E = material_prop(s, material, "E", "E", "Young's modulus", override=E, scale=1000.0, unit="MPa")
        need(E is not None, f"No sourced modulus for {material}.", "Give E (MPa).", ["E"])
        if G is None:
            nu = material_prop(s, material, "poisson", "poisson", "Poisson's ratio", override=number(inputs, "poisson", None, 0, 0.5))
            if nu is None:
                nu = s.assumed("poisson", "Poisson's ratio", 0.35, "", "no sourced value for this material; 0.35 is "
                               "the usual figure for unfilled thermoplastics (Bayer's snap-fit guide uses it)")
            s.eq("shear_modulus", "G = E / (2 (1 + ν))", "", "isotropic elasticity")
            G = s.computed("G", "Shear modulus", E / (2 * (1 + nu)), "MPa", "shear_modulus")
        else:
            s.given("G", "Shear modulus", G, "MPa")
        rho = material_prop(s, material, "density", "density", "Density", override=rho, unit="kg/m³")
        Rm = number(inputs, "Rm", None, 1, 5000)
        if Rm is not None:
            out["Rm"] = s.given("Rm", "Tensile strength R_m", Rm, "MPa")
        else:
            out["Rm"] = material_prop(s, material, "uts", "Rm", "Tensile strength", unit="MPa")
        if out["printed"]:
            s.caveat("Printed spring: the equations are for an isotropic, elastic wire. A printed coil creeps and "
                     "relaxes under a held load, is weaker between its layers than the datasheet's X-Y values, and "
                     "has no fatigue data. Treat the rate as a first estimate and the spring as good for a few "
                     "cycles; measure a printed one before relying on it.")
    else:
        en = s.source("en1", *EN1)
        note = "patented cold-drawn spring steel wire to EN 10270-1"
        G = s.given("G", "Shear modulus", G, "MPa") if G is not None else s.add("G", "Shear modulus", STEEL["G"], "MPa", "specified", source=en, note=note)
        E = s.given("E", "Young's modulus", E, "MPa") if E is not None else s.add("E", "Young's modulus", STEEL["E"], "MPa", "specified", source=en, note=note)
        rho = s.given("density", "Density", rho, "kg/m³") if rho is not None else s.add("density", "Density", STEEL["rho"], "kg/m³", "specified", source=en, note="steel, 7.85 kg/dm³")
        Rm = number(inputs, "Rm", None, 1, 5000)
        if Rm is not None:
            out["Rm"] = s.given("Rm", "Tensile strength of the wire R_m", Rm, "MPa")
        elif inputs.get("wire"):
            wk = choice(inputs, "wire", tuple(WIRES), "music")
            name, A, m, lo, hi = WIRES[wk]
            sh = s.source("shigley", *SHIGLEY)
            s.eq("wire_strength", "R_m = A / d^m", sh, "Table 10-4, an estimate of the minimum tensile strength of spring wire")
            d = number(inputs, "wire_d", None)
            if d is not None:
                out["Rm"] = s.computed("Rm", f"Tensile strength of {name}", A / d ** m, "MPa", "wire_strength",
                                       f"A = {A:g} MPa·mm^m, m = {m:g}" + ("" if lo <= d <= hi else f"; outside the table's {lo:g} to {hi:g} mm"))
    out.update(G=G, E=E, rho=rho)
    return out


def _allow(s: Sheet, inputs: dict, kind: str, mat: dict):
    """The permissible stress, or None (said) when no tensile strength is known."""
    if mat["Rm"] is None:
        s.missing("stress_allow", "Permissible stress", "No tensile strength: name the wire (wire=music) or give Rm "
                  "(MPa). The stresses are reported without a verdict.")
        return None
    f = number(inputs, "stress_factor", None, 0.05, 1.0)
    if mat["printed"] and f is None:
        s.eq("allow_printed", "τ_perm = R_m / √3   (bending: σ_perm = R_m)", "", "Form Studio's bound for a printed coil, "
             "not a spring-wire rule: the von Mises shear equivalent of the datasheet's tensile strength")
        v = mat["Rm"] if kind == "torsion" else mat["Rm"] / math.sqrt(3)
        return s.computed("stress_allow", "Permissible stress (printed)", v, "MPa", "allow_printed")
    if f is not None:
        s.given("stress_factor", "Permissible stress as a share of R_m", f, "")
    else:
        f, text, sid = FACTOR[kind]
        src = s.source(sid, *{"en1": EN1, "en2": EN2, "en3": EN3}[sid])
        s.add("stress_factor", "Permissible stress as a share of R_m", f, "", "specified", source=src, note=text)
    s.eq("allow", "stress_perm = factor · R_m", "", "")
    return s.computed("stress_allow", "Permissible stress", f * mat["Rm"], "MPa", "allow")


def run(inputs: dict) -> dict:
    kind = choice(inputs, "kind", ("compression", "extension", "torsion"), "compression")
    return {"compression": _compression, "extension": _extension, "torsion": _torsion}[kind](inputs)


def _common(s: Sheet, inputs: dict):
    d = number(inputs, "wire_d", None, 0.05, 80)
    D = number(inputs, "mean_d", None, 0.5, 2000)
    need(d is not None and D is not None, "A spring needs its wire diameter and mean coil diameter.",
         "wire_d=1.6 mean_d=14 (mm).", ["wire_d", "mean_d"])
    s.given("wire_d", "Wire diameter d", d, "mm")
    s.given("mean_d", "Mean coil diameter D", D, "mm")
    s.eq("index", "w = D / d", "", "spring index")
    w = s.computed("index", "Spring index w", D / d, "", "index")
    need(w > 1.5, "The coil is smaller than the wire allows (index under 1.5).", "Use a larger coil or a thinner wire.", ["mean_d", "wire_d"])
    s.check("index", "Spring index", "PASS" if 4 <= w <= 20 else "WARN", f"w = {w:.2f}",
            "The standard's equations are stated for 4 ≤ w ≤ 20 (cold coiled). " + ("Inside it." if 4 <= w <= 20 else
            "Outside it: under 4 the wire cracks on coiling and the correction factor is uncertain; over 20 the coil is limp and tangles."),
            "index", evidence="specified")
    return d, D, w


def _coils(s: Sheet, inputs: dict, rate_of_one: float, unit: str, eq: str) -> float:
    n = number(inputs, "active", None, 0.5, 500)
    R_target = number(inputs, "rate", None, 1e-6, 1e7)
    if n is None:
        need(R_target is not None, "Give the active coils, or the rate to size them from.", "active=6, or rate=2.5.", ["active", "rate"])
        s.given("rate_target", "Rate wanted", R_target, unit)
        n = s.computed("active", "Active coils n for that rate", rate_of_one / R_target, "", eq)
    else:
        s.given("active", "Active coils n", n, "")
    return n


def _compression(inputs: dict) -> dict:
    s = Sheet("spring", "Compression spring", "EN 13906-1", inputs)
    en = s.source("en1", *EN1)
    sh = s.source("shigley", *SHIGLEY)
    s.eq("rate", "R = G · d⁴ / (8 · D³ · n)", en)
    s.eq("shear", "τ = 8 · D · F / (π · d³)", en, "uncorrected; the standard uses it for static loading")
    s.eq("correction", "τ_k = k · τ,  k = (w + 0.5) / (w − 0.75)", en, "Bergsträsser's curvature correction, for fatigue "
         "loading; Wahl's k = (4w − 1)/(4w − 4) + 0.615/w is within 1 % of it for w ≥ 3")
    s.eq("ends", "n_t = n + dead coils,  L_c = (n_t + extra) · d", sh, "Table 10-1: plain 0 and 1; plain and ground 1 and 0; squared 2 and 1; squared and ground 2 and 0")
    s.eq("clearance", "S_a = n · (0.0015 · D² / d + 0.1 · d)", en, "least sum of the gaps between active coils at the shortest working length, cold-coiled")
    s.eq("buckling", "s_K = L0 · 0.5/(1 − G/E) · [1 − √(1 − (1 − G/E)/(0.5 + G/E) · (π·D/(ν·L0))²)]", en,
         "ν is the seating coefficient; no real root: the spring cannot buckle. The same relation as Shigley's eq. 10-10")
    s.eq("frequency", "f_e = d / (2π · n · D²) · √(G / (2ρ))", en, "first natural frequency, both ends held: half of "
         "√(R / active mass); in the standard's units 3560 · d/(n·D²) · √(G/ρ)")
    s.eq("mass", "m = ρ · (π d²/4) · π D · n_t", "", "wire volume along the mean coil; pitch neglected")
    d, D, w = _common(s, inputs)
    mat = _material(s, inputs, "compression")
    G, E, rho = mat["G"], mat["E"], mat["rho"]
    n = _coils(s, inputs, G * d ** 4 / (8 * D ** 3), "N/mm", "rate")
    R = s.computed("rate", "Rate R", G * d ** 4 / (8 * D ** 3 * n), "N/mm", "rate")
    ends = choice(inputs, "ends", tuple(ENDS), "closed_ground")
    dead, extra, ends_text = ENDS[ends]
    if "ends" in inputs:
        s.given("ends", "Ends", ends_text, "")
    else:
        s.assumed("ends", "Ends", ends_text, "", "squared and ground unless the request says otherwise: it stands square")
    nt = s.computed("total", "Total coils n_t", n + dead, "", "ends")
    Lc = s.computed("solid_length", "Solid length L_c", (nt + extra) * d, "mm", "ends")
    Sa = s.computed("clearance", "Least clearance between active coils, summed", n * (0.0015 * D * D / d + 0.1 * d), "mm", "clearance")
    F = number(inputs, "force", None, 0, 1e7)
    sd = number(inputs, "deflection", None, 0, 1e5)
    if F is not None:
        s.given("force", "Largest working force", F, "N")
        s.eq("hooke", "s = F / R", "", "")
        sm = s.computed("deflection", "Deflection at that force", F / R, "mm", "hooke")
    elif sd is not None:
        sm = s.given("deflection", "Largest working deflection", sd, "mm")
        s.eq("hooke", "F = R · s", "", "")
        F = s.computed("force", "Force at that deflection", R * sd, "N", "hooke")
    else:
        sm = None
    L0 = number(inputs, "free_length", None, 0.5, 1e5)
    if L0 is None:
        need(sm is not None, "Give the free length, or a working force or deflection to size it from.",
             "free_length=40, or force=30.", ["free_length", "force", "deflection"])
        s.eq("free", "L0 = L_c + S_a + s_max", en, "the shortest free length that keeps the clearance at the working deflection")
        L0 = s.computed("free_length", "Free length L0", Lc + Sa + sm, "mm", "free")
    else:
        s.given("free_length", "Free length L0", L0, "mm")
    need(L0 > Lc, f"The free length ({L0:g} mm) is not above the solid length ({Lc:.2f} mm): no travel.",
         "Lengthen the spring, or use fewer coils or thinner wire.", ["free_length"])
    s.eq("pitch", "p = (L0 − L_c) / n + d", "", "gap per active coil plus the wire")
    s.computed("pitch", "Pitch of the active coils", (L0 - Lc) / n + d, "mm", "pitch")
    sc = s.computed("travel_solid", "Travel to solid", L0 - Lc, "mm", "ends")
    Fc = s.computed("force_solid", "Force at solid length", R * sc, "N", "rate")
    tau_c = s.computed("stress_solid", "Shear stress at solid length (uncorrected)", 8 * D * Fc / (math.pi * d ** 3), "MPa", "shear")
    k = s.computed("k", "Stress correction factor k", bergstrasser(w), "", "correction")
    allow = _allow(s, inputs, "compression", mat)
    if sm is not None:
        tau = s.computed("stress", "Shear stress at the working force (uncorrected)", 8 * D * F / (math.pi * d ** 3), "MPa", "shear")
        s.computed("stress_corrected", "Corrected shear stress at the working force", k * tau, "MPa", "correction")
        ok = sm <= sc - Sa + 1e-9
        s.check("travel", "Working length against the coil clearance", "PASS" if ok else ("FAIL" if sm > sc else "WARN"),
                f"{L0 - sm:.2f} mm, least {Lc + Sa:.2f} mm", "Shortest working length against solid length plus the "
                "least clearance. " + ("" if ok else "Too close to solid: lengthen the spring or lower the load."), "clearance")
        if allow is not None:
            st = "PASS" if tau <= allow else "FAIL"
            s.check("stress", "Stress at the working force", st, f"{tau:.0f} MPa of {allow:.0f} MPa",
                    "Static load. For a load that cycles, the corrected stress and the wire's fatigue diagram decide; "
                    "that is not computed here.", "shear")
    if allow is not None:
        st = "PASS" if tau_c <= allow else "WARN"
        s.check("solid", "Pressed solid", st, f"{tau_c:.0f} MPa of {allow:.0f} MPa",
                "Within the permissible stress at solid length: it can be pressed solid without taking a set."
                if st == "PASS" else "Pressed solid it takes a set (shortens for good). Keep it off solid, or lower the pitch.", "shear")
    nu = number(inputs, "seating", 0.5, 0.25, 4)
    (s.given if "seating" in inputs else lambda *a: s.assumed(*a, "both ends guided and held square, the usual seat"))("seating", "Seating coefficient ν", nu, "")
    sK = buckling_deflection(L0, D, G, E, nu)
    if sK is None:
        s.check("buckling", "Buckling", "PASS", "cannot buckle", f"L0 / D = {L0 / D:.2f}: short enough that no deflection buckles it.", "buckling")
    else:
        s.computed("buckling_deflection", "Deflection at which it buckles", sK, "mm", "buckling")
        ref = sm if sm is not None else sc
        st = "PASS" if ref < sK else "FAIL"
        s.check("buckling", "Buckling", st, f"buckles at {sK:.2f} mm, " + (f"works to {ref:.2f} mm" if sm is not None else f"solid at {ref:.2f} mm"),
                "Guide it on a rod or in a bore, shorten it or widen the coil." if st == "FAIL" else "The working deflection stays under it.", "buckling")
    if rho:
        fe = s.computed("frequency", "First natural frequency", natural_frequency(d, D, n, G, rho), "Hz", "frequency")
        s.computed("mass", "Mass", rho * 1e-9 * (math.pi * d * d / 4) * math.pi * D * nt * 1000, "g", "mass")
        s.note(f"Keep the working frequency well under {fe:.0f} Hz (a usual margin is a factor of 13 or more for cyclic drives): near it the coils surge.")
    else:
        s.missing("frequency", "Natural frequency and mass", "No sourced density: give density (kg/m³).")
    s.geometry("spring_compression", {"wire_d": d, "mean_d": D, "active": n, "free_l": L0,
                                      "closed": 1.0 if dead >= 2 else 0.0, "ground": 1.0 if ends.endswith("ground") else 0.0},
               "Compression spring", {"material": inputs.get("material") or "spring steel", "ends": ends})
    return s.done(f"Rate {R:.3g} N/mm, {n:.2f} active coils, free {L0:.1f} mm, solid {Lc:.1f} mm"
                  + (f"; {F:.3g} N at {sm:.1f} mm" if sm is not None else ""))


def _extension(inputs: dict) -> dict:
    s = Sheet("spring", "Extension spring", "EN 13906-2", inputs)
    en = s.source("en2", *EN2)
    sh = s.source("shigley", *SHIGLEY)
    s.eq("rate", "R = G · d⁴ / (8 · D³ · n)", en)
    s.eq("force", "F = F0 + R · s", en, "F0 is the initial tension wound into the coils")
    s.eq("shear", "τ = 8 · D · F / (π · d³),  τ_k = k · τ,  k = (w + 0.5) / (w − 0.75)", en)
    s.eq("hook", "σ_A = F · [K_A · 16 D / (π d³) + 4 / (π d²)],  K_A = (4 C1² − C1 − 1) / (4 C1 (C1 − 1)),  C1 = 2 r1 / d", sh,
         "eq. 10-34: bending and tension at the inside of the hook's bend")
    s.eq("body", "L_K = (n + 1) · d", "", "close-wound coils touching: geometry")
    d, D, w = _common(s, inputs)
    mat = _material(s, inputs, "extension")
    G = mat["G"]
    n = _coils(s, inputs, G * d ** 4 / (8 * D ** 3), "N/mm", "rate")
    R = s.computed("rate", "Rate R", G * d ** 4 / (8 * D ** 3 * n), "N/mm", "rate")
    F0 = number(inputs, "initial_tension", 0.0, 0, 1e6)
    (s.given if "initial_tension" in inputs else lambda *a: s.assumed(*a, "none, unless the request gives the wound-in tension"))("initial_tension", "Initial tension F0", F0, "N")
    LK = s.computed("body_length", "Body length L_K", (n + 1) * d, "mm", "body")
    F = number(inputs, "force", None, 0, 1e7)
    sd = number(inputs, "deflection", None, 0, 1e5)
    if F is not None:
        need(F >= F0, "The working force is below the initial tension: the coils do not open.", "", ["force"])
        s.given("force", "Largest working force", F, "N")
        sd = s.computed("deflection", "Extension at that force", (F - F0) / R, "mm", "force")
    elif sd is not None:
        s.given("deflection", "Largest working extension", sd, "mm")
        F = s.computed("force", "Force at that extension", F0 + R * sd, "N", "force")
    allow = _allow(s, inputs, "extension", mat)
    k = s.computed("k", "Stress correction factor k", bergstrasser(w), "", "shear")
    r1 = number(inputs, "hook_radius", None, 0.3, 1000) or D / 2
    (s.given if inputs.get("hook_radius") else lambda *a: s.assumed(*a, "a full loop of the coil's own radius"))("hook_radius", "Mean radius of the hook's bend r1", r1, "mm")
    if F is not None:
        tau = s.computed("stress", "Shear stress in the body (uncorrected)", 8 * D * F / (math.pi * d ** 3), "MPa", "shear")
        s.computed("stress_corrected", "Corrected shear stress in the body", k * tau, "MPa", "shear")
        C1 = 2 * r1 / d
        need(C1 > 1.05, "The hook's bend is tighter than the wire allows.", "Raise hook_radius.", ["hook_radius"])
        KA = (4 * C1 * C1 - C1 - 1) / (4 * C1 * (C1 - 1))
        sA = s.computed("hook_stress", "Bending stress at the hook", F * (KA * 16 * D / (math.pi * d ** 3) + 4 / (math.pi * d * d)), "MPa", "hook")
        if allow is not None:
            st = "PASS" if tau <= allow else "FAIL"
            s.check("stress", "Body stress at the working force", st, f"{tau:.0f} MPa of {allow:.0f} MPa", "Static load.", "shear")
        if mat["Rm"]:
            st = "PASS" if sA <= mat["Rm"] * 0.75 else ("WARN" if sA <= mat["Rm"] else "FAIL")
            s.check("hook", "Hook", st, f"{sA:.0f} MPa, R_m {mat['Rm']:.0f} MPa",
                    "Hooks break before bodies. Compared with 75 % of the tensile strength, a margin Form Studio "
                    "chose (assumed), not a standard's limit.", "hook", evidence="assumed")
    else:
        s.missing("stress", "Stresses", "Give the working force or extension.")
    s.caveat("The hooks' own deflection is not in the rate; a real spring is a little softer than computed.")
    s.geometry("spring_extension", {"wire_d": d, "mean_d": D, "coils": n}, "Extension spring",
               {"material": inputs.get("material") or "spring steel"})
    return s.done(f"Rate {R:.3g} N/mm, {n:.2f} coils, body {LK:.1f} mm" + (f"; {F:.3g} N at {sd:.1f} mm" if F is not None else ""))


def _torsion(inputs: dict) -> dict:
    s = Sheet("spring", "Torsion spring", "EN 13906-3", inputs)
    en = s.source("en3", *EN3)
    s.eq("rate", "R_M = M / α = E · d⁴ / (3667 · D · n)   (N·mm per degree; 3667 = 64 · 180 / π)", en)
    s.eq("bending", "σ = 32 · M / (π · d³),  σ_q = q · σ,  q = (w + 0.07) / (w − 0.75)", en, "q corrects for the wire's curvature")
    s.eq("wound", "D_α = D · n / (n + α / 360)", en, "the coil tightens as it is wound up")
    s.eq("body", "L_K = (n + 1) · d", "", "close-wound coils touching: geometry")
    d, D, w = _common(s, inputs)
    mat = _material(s, inputs, "torsion")
    E = mat["E"]
    n = _coils(s, inputs, E * d ** 4 / (3667 * D), "N·mm/deg", "rate")
    R = s.computed("rate", "Rate R_M", E * d ** 4 / (3667 * D * n), "N·mm/deg", "rate")
    s.computed("body_length", "Body length L_K", (n + 1) * d, "mm", "body")
    M = number(inputs, "torque", None, 0, 1e9)
    a = number(inputs, "deflection", None, 0, 36000)
    if M is not None:
        s.given("torque", "Largest working torque", M, "N·mm")
        a = s.computed("deflection", "Angle at that torque", M / R, "deg", "rate")
    elif a is not None:
        s.given("deflection", "Largest working angle", a, "deg")
        M = s.computed("torque", "Torque at that angle", R * a, "N·mm", "rate")
    allow = _allow(s, inputs, "torsion", mat)
    q = s.computed("q", "Stress correction factor q", (w + 0.07) / (w - 0.75), "", "bending")
    if M is not None:
        sig = s.computed("stress", "Bending stress (uncorrected)", 32 * M / (math.pi * d ** 3), "MPa", "bending")
        s.computed("stress_corrected", "Corrected bending stress", q * sig, "MPa", "bending")
        Da = s.computed("wound_d", "Mean coil diameter when wound", D * n / (n + a / 360), "mm", "wound")
        s.note(f"A mandrel inside the coil must be smaller than {Da - d:.2f} mm (the wound coil's inner diameter), with clearance.")
        if allow is not None:
            st = "PASS" if sig <= allow else "FAIL"
            s.check("stress", "Stress at the working torque", st, f"{sig:.0f} MPa of {allow:.0f} MPa",
                    "Static load, wound in the direction that closes the coil.", "bending")
    else:
        s.missing("stress", "Stresses", "Give the working torque or angle.")
    l1, l2 = number(inputs, "leg1", 20.0, 0, 1000), number(inputs, "leg2", 20.0, 0, 1000)
    s.caveat("The legs are taken as rigid: their bending adds to the angle, so a real spring is a little softer.")
    s.geometry("spring_torsion", {"wire_d": d, "mean_d": D, "coils": n, "leg1": l1, "leg2": l2}, "Torsion spring",
               {"material": inputs.get("material") or "spring steel"})
    return s.done(f"Rate {R:.3g} N·mm/deg, {n:.2f} coils" + (f"; {M:.3g} N·mm at {a:.1f}°" if M is not None else ""))


__all__ = ["run", "spec", "bergstrasser", "wahl", "buckling_deflection", "natural_frequency", "CalcError"]
