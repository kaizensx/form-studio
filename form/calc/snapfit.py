"""Snap joints by strain: cantilever hooks and annular (ring) snaps.

Everything here is from one guide, Bayer MaterialScience's "Snap-Fit Joints for Plastics: A Design Guide": the
deflection equations of its Table 1 (rectangular section, three taper designs), the deflection force, the mating and
separation force from the friction and the angle, the annular joint's geometric factors X_N and X_W, the permissible
short-term strains of its Table 2 and the friction coefficients of its Table 3.

The permissible strain is where a snap-fit calculation is honest or not. In order:

  1. the request's own value (`allow_strain`), specified;
  2. the guide's Table 2 value when the request names one of its resins (`guide_resin`), specified, for a moulded part;
  3. from the material's sourced datasheet, by the guide's rules: half the elongation at break (its rule for materials
     with no distinct yield point), and never more than the strain at which a linear material would reach its sourced
     strength (strength / modulus), which is Form Studio's own conservative bound and is labelled as such.

For frequent separation the guide takes 60 % of the value. A printed part is not the moulded resin the guide tested:
the sheet says so, and across the layers the datasheet's Z values are used when direction="z".
"""
from __future__ import annotations

import math

from . import CalcError, I, Sheet, choice, material_kind, material_prop, need, number

BAYER = ("Bayer MaterialScience, Snap-Fit Joints for Plastics: A Design Guide",
         "https://fab.cba.mit.edu/classes/S62.12/people/vernelle.noel/Plastic_Snap_fit_design.pdf")
# Table 1, cross-section shape A (rectangle): y = K * eps * l^2 / h
TAPER = {"constant": (0.67, "design 1: constant cross section"),
         "thickness_half": (1.09, "design 2: thickness decreasing linearly to one-half at the hook"),
         "width_quarter": (0.86, "design 3: width decreasing linearly to one-quarter at the hook")}
# Table 2: permissible short-term strain at 23 °C, single joining operation (fraction)
TABLE2 = {"pc": (0.04, "Makrolon PC"), "pc_ht": (0.04, "Apec high-heat PC"), "pc_abs": (0.025, "Bayblend PC/ABS"),
          "pc_blend": (0.035, "Makroblend polycarbonate blend"), "pc_gf10": (0.022, "Makrolon PC, 10 % glass fibre"),
          "pc_gf20": (0.020, "Makrolon PC, 20 % glass fibre")}
FREQUENT = 0.6           # "for frequent separation and rejoining, use about 60 % of these values" (Table 2 caption)
# Table 3: friction of plastics on steel (range), and the factor the guide gives for the same plastic on itself
TABLE3 = {"ptfe": (0.12, 0.22, None), "pe_rigid": (0.20, 0.25, 2.0), "pp": (0.25, 0.30, 1.5), "pom": (0.20, 0.35, 1.5),
          "pa": (0.30, 0.40, 1.5), "pbt": (0.35, 0.40, None), "ps": (0.40, 0.50, 1.2), "san": (0.45, 0.55, None),
          "pc": (0.45, 0.55, 1.2), "pmma": (0.50, 0.60, 1.2), "abs": (0.50, 0.65, 1.2), "pe_flexible": (0.55, 0.60, 1.2),
          "pvc": (0.55, 0.60, 1.0)}
FAMILY = {"ABS": "abs", "PA": "pa", "PA-CF": "pa", "NYLON-PA6": "pa", "PC": "pc", "POM": "pom", "PTFE": "ptfe",
          "PMMA": "pmma"}                       # library key -> Table 3 family (nothing for PLA, PETG, ASA, TPU, PEEK)
POISSON_PLASTICS = 0.35  # "Poisson's ratio (for plastics approx. 0.35)", the guide's torsion section


def spec() -> dict:
    return {"id": "snapfit", "title": "Snap joint by strain", "standard": "Bayer, Snap-Fit Joints for Plastics",
            "doc": "A cantilever hook or an annular snap sized from the material's permissible strain: thickness or "
                   "undercut, deflection force, mating and separation force. Writes the hook (or the ring and groove).",
            "writes": "cantilever: a snap hook on a base, with parameters; annular: the beaded tube and its grooved hub",
            "inputs": [
                I("kind", "Kind of joint", "", "cantilever", "", ("cantilever", "annular")),
                I("material", "Material", "", None, "A key of the materials library (form materials), for the modulus, "
                  "the elongation and the strength, each with its datasheet."),
                I("direction", "Bending direction of a printed part", "", "xy", "xy: the hook bends along the layers "
                  "(lies flat on the bed); z: across them (stands up).", ("xy", "z")),
                I("allow_strain", "Permissible strain", "fraction", None, "Your own value, e.g. 0.02; overrides the rest."),
                I("guide_resin", "Resin of the guide's Table 2", "", None, "A moulded resin of the guide's table.",
                  tuple(TABLE2)),
                I("use", "How often it is joined", "", "single", "frequent: 60 % of the permissible strain.",
                  ("single", "frequent")),
                I("utilisation", "Share of the permissible strain used", "fraction", 1.0, "The guide's first example "
                  "uses 0.5."),
                I("E", "Modulus used for the forces", "MPa", None, "The secant modulus at the strain, if you have the "
                  "curve; else the datasheet's tensile modulus is used and the forces are an upper estimate."),
                I("mu", "Friction coefficient", "", None, "Hook on its mating part; else the guide's Table 3 where it "
                  "has the material."),
                I("lead_angle", "Lead (inclination) angle", "deg", 30.0, ""),
                I("return_angle", "Return angle", "deg", 90.0, "90: cannot be pulled apart; 30 to 45: separable."),
                # cantilever
                I("length", "Arm length l", "mm", None, "cantilever"),
                I("width", "Arm width b at the root", "mm", None, "cantilever"),
                I("thickness", "Arm thickness h at the root", "mm", None, "cantilever; left out: sized from the undercut"),
                I("undercut", "Undercut y", "mm", None, "cantilever: the deflection; left out: the largest the "
                  "strain allows. annular: the diametral undercut (the bead stands y/2 proud all round)."),
                I("taper", "Arm design", "", "constant", "", tuple(TAPER)),
                # annular
                I("diameter", "Diameter at the joint d", "mm", None, "annular"),
                I("wall", "Wall thickness of the elastic part", "mm", None, "annular"),
                I("elastic", "Which part gives", "", "hub", "hub: the outer tube stretches over a rigid shaft; shaft: "
                  "a hollow shaft is squeezed by a rigid hub; both: equal stiffness, each takes half.", ("hub", "shaft", "both")),
                I("position", "Where the bead sits", "", "near", "near the open end of the tube, or remote from it "
                  "(the guide: forces about three times as high).", ("near", "remote")),
                I("poisson", "Poisson's ratio", "", None, "annular; else the library's, else the guide's 0.35."),
                I("height", "Height of the ring parts", "mm", None, "annular geometry; default 0.5 d, at least 6"),
            ]}


def _eqs(s: Sheet) -> str:
    b = s.source("bayer", *BAYER)
    s.eq("deflection", "y = K · ε · l² / h   (K = 0.67 constant section, 1.09 thickness to one-half, 0.86 width to one-quarter)", b,
         "Table 1, shape A (rectangle)")
    s.eq("force", "P = (b · h² / 6) · E_s · ε / l", b, "Table 1, deflection force, shape A; E_s is the secant modulus")
    s.eq("mating", "W = P · (μ + tan α) / (1 − μ · tan α)", b, "mating force; the separation force uses the return angle α′")
    return b


def permissible_strain(s: Sheet, inputs: dict, material: str | None, direction: str = "xy") -> float:
    """The permissible strain on the sheet (key "strain_allow"), by the order in the module docstring."""
    b = s.source("bayer", *BAYER)
    use = choice(inputs, "use", ("single", "frequent"), "single")
    given = number(inputs, "allow_strain", None, 1e-4, 0.5)
    resin = inputs.get("guide_resin")
    if given is not None:
        base = s.given("strain_base", "Permissible strain (your value)", given, "")
    elif resin:
        resin = choice(inputs, "guide_resin", tuple(TABLE2), "pc")
        base = s.add("strain_base", f"Permissible short-term strain, {TABLE2[resin][1]}", TABLE2[resin][0], "",
                     "specified", source=b, note="Table 2: moulded resin, 23 °C, single joining operation")
        if material_kind(material)["kind"] == "filament":
            s.caveat("The guide's strain is for the moulded resin. A printed part reaches less, and much less across "
                     "its layers; give allow_strain from a test of your own print to be sure.")
    else:
        need(material, "Give a material, a guide resin or allow_strain: the permissible strain has to come from somewhere.",
             "material=PETG (the sourced library), guide_resin=pc (the guide's table) or allow_strain=0.02.",
             ["material", "allow_strain"])
        s.eq("strain_half_break", "ε_pm = 0.5 · ε_break", b,
             "the guide's rule for a material with no distinct yield point (its Fig. 13); applied to the datasheet's "
             "elongation at break")
        s.eq("strain_linear", "ε_lin = σ / E", "",
             "Form Studio's own conservative bound, not from a guide: the strain at which a linear material reaches "
             "its sourced strength")
        eb = material_prop(s, material, "elongation", "elongation_break", "Elongation at break", direction=direction, unit="%")
        E = material_prop(s, material, "E", "E_datasheet", "Tensile modulus", direction=direction, scale=1000.0, unit="MPa")
        sy = material_prop(s, material, "yield", "strength_ref", "Yield strength", unit="MPa")
        if sy is None:
            sy = material_prop(s, material, "uts", "strength_ref", "Tensile strength", direction=direction, unit="MPa")
        cands = []
        if eb is not None:
            cands.append((s.computed("strain_half_break", "Half the elongation at break", 0.5 * eb / 100.0, "", "strain_half_break"), "half the elongation at break"))
        if E and sy:
            cands.append((s.computed("strain_linear", "Strength over modulus", sy / E, "", "strain_linear"), "strength / modulus"))
        if not cands:
            raise CalcError(f"The library has no sourced elongation or strength for {material}: no permissible strain.",
                            "Give allow_strain (a fraction, e.g. 0.02) from the resin's datasheet or a test.", ["allow_strain"])
        base, why = min(cands)
        base = s.computed("strain_base", f"Permissible strain ({why} governs)", base, "",
                          "strain_half_break" if why.startswith("half") else "strain_linear",
                          "the smaller of the two bounds" if len(cands) > 1 else "")
        if material_kind(material)["kind"] == "filament":
            s.caveat("Datasheet values of printed specimens at 100 % infill; your walls, infill, layer height and "
                     "temperature change them" + (", and this hook bends across its layers (Z values used)." if direction == "z"
                                                   else ". Print the hook lying flat so it bends along its layers."))
    s.eq("strain_use", "ε = utilisation · (0.6 if joined often) · ε_pm", b, "Table 2 caption: about 60 % for frequent separation")
    util = number(inputs, "utilisation", 1.0, 0.05, 1.0)
    s.given("utilisation", "Share of the permissible strain used", util, "") if "utilisation" in inputs else \
        s.assumed("utilisation", "Share of the permissible strain used", util, "", "all of it, unless the request says less")
    f = FREQUENT if use == "frequent" else 1.0
    return s.computed("strain_allow", "Strain the joint may reach" + (" (joined often: 60 %)" if use == "frequent" else ""),
                      base * f * util, "", "strain_use")


def modulus(s: Sheet, inputs: dict, material: str | None, direction: str = "xy"):
    """The modulus the forces use: the request's (a secant modulus), else the datasheet's tensile modulus, said to
    overestimate the force. None when neither exists."""
    E = number(inputs, "E", None, 1.0, 1e6)
    if E is not None:
        return s.given("E", "Modulus (your value)", E, "MPa")
    E = s.get("E_datasheet") or material_prop(s, material, "E", "E_datasheet", "Tensile modulus", direction=direction,
                                               scale=1000.0, unit="MPa")
    if E is None:
        return None
    s.note("Forces use the datasheet's tensile modulus, not the secant modulus at the strain: plastics soften as they "
           "strain, so the real forces are lower (an upper estimate). Give E = your secant modulus for a closer figure.")
    return E


def friction(s: Sheet, inputs: dict, material: str | None):
    mu = number(inputs, "mu", None, 0.0, 2.0)
    if mu is not None:
        return s.given("mu", "Friction coefficient (your value)", mu, "")
    fam = FAMILY.get(material_kind(material).get("id", "")) if material else None
    if not fam:
        return None
    lo, hi, same = TABLE3[fam]
    mid = (lo + hi) / 2 * (same or 1.0)
    return s.add("mu", f"Friction coefficient, {fam.upper()} on itself", mid, "", "specified", source=s.source("bayer", *BAYER),
                 note=f"Table 3: {lo:g} to {hi:g} on steel (mid-range taken)" + (f", × {same:g} for the same plastic" if same else ""))


def ramp(mu: float, angle_deg: float):
    """(μ + tan α) / (1 − μ tan α), or None when the face locks (μ tan α >= 1 or α >= 90)."""
    if angle_deg >= 89.999:
        return None
    t = math.tan(math.radians(angle_deg))
    return None if mu * t >= 1 else (mu + t) / (1 - mu * t)


def _forces(s: Sheet, inputs: dict, P: float | None, mu) -> str:
    la = number(inputs, "lead_angle", 30.0, 5, 80)
    ra = number(inputs, "return_angle", 90.0, 5, 90)
    (s.given if "lead_angle" in inputs else lambda *a: s.assumed(*a, "30°, the guide's usual lead angle"))("lead_angle", "Lead angle α", la, "deg")
    (s.given if "return_angle" in inputs else lambda *a: s.assumed(*a, "90°: a joint that is not pulled apart"))("return_angle", "Return angle α′", ra, "deg")
    if P is None:
        s.missing("deflection_force", "Deflection force", "No sourced modulus for this material: give E (MPa).")
        return ""
    if mu is None:
        s.missing("mating_force", "Mating and separation force",
                  "The guide's friction table has no entry for this material: give mu (hook on its mating part).")
        return f"deflection force {P:.3g} N"
    k = ramp(mu, la)
    need(k is not None, f"With μ = {mu:g} a lead angle of {la:g}° locks: the hook cannot be pushed in.",
         "Use a shallower lead angle.", ["lead_angle"])
    W = s.computed("mating_force", "Mating force W", P * k, "N", "mating")
    kr = ramp(mu, ra)
    if kr is None:
        s.check("separation", "Separation", "INFO", "locks", f"With μ = {mu:g} a return angle of {ra:g}° does not "
                "slide: the joint holds until the hook breaks or is released by hand.", "mating")
        return f"mating force {W:.3g} N, locks"
    S = s.computed("separation_force", "Separation force", P * kr, "N", "mating", "the mating equation with the return angle")
    return f"mating {W:.3g} N, separation {S:.3g} N"


def run(inputs: dict) -> dict:
    kind = choice(inputs, "kind", ("cantilever", "annular"), "cantilever")
    material = inputs.get("material") or None
    direction = choice(inputs, "direction", ("xy", "z"), "xy")
    return (_annular if kind == "annular" else _cantilever)(inputs, material, direction)


def _cantilever(inputs: dict, material, direction) -> dict:
    s = Sheet("snapfit", "Cantilever snap hook", "Bayer, Snap-Fit Joints for Plastics (Table 1, shape A)", inputs)
    _eqs(s)
    taper = choice(inputs, "taper", tuple(TAPER), "constant")
    K = s.add("K", "Deflection factor K", TAPER[taper][0], "", "specified", source="bayer", note="Table 1, " + TAPER[taper][1])
    l = number(inputs, "length", None, 1, 500)
    b = number(inputs, "width", None, 0.5, 500)
    h = number(inputs, "thickness", None, 0.2, 100)
    y = number(inputs, "undercut", None, 0.05, 100)
    need(l is not None and b is not None, "A cantilever needs its length and width.", "length=15 width=6 (mm).", ["length", "width"])
    s.given("length", "Arm length l", l, "mm")
    s.given("width", "Arm width b", b, "mm")
    eps_allow = permissible_strain(s, inputs, material, direction)
    if h is None and y is None:
        raise CalcError("Give the undercut (the thickness is then sized) or the thickness (the undercut is then sized).",
                        "undercut=1.0, or thickness=1.6.", ["undercut", "thickness"])
    if h is None:
        s.given("undercut", "Undercut y", y, "mm")
        h = s.computed("thickness", "Root thickness h at the strain allowed", K * eps_allow * l * l / y, "mm", "deflection",
                       "the thickest arm that reaches the undercut within the strain")
        eps = eps_allow
    elif y is None:
        s.given("thickness", "Root thickness h", h, "mm")
        y = s.computed("undercut", "Largest undercut y the strain allows", K * eps_allow * l * l / h, "mm", "deflection")
        eps = eps_allow
    else:
        s.given("thickness", "Root thickness h", h, "mm")
        s.given("undercut", "Undercut y", y, "mm")
        eps = y * h / (K * l * l)
    eps = s.computed("strain", "Strain at the root when it snaps", eps, "", "deflection")
    st = "FAIL" if eps > eps_allow * 1.0005 else "PASS"
    s.check("strain", "Strain when it snaps", st, f"{100 * eps:.2f} % of {100 * eps_allow:.2f} % allowed",
            "Over the limit: lengthen the arm, thin it, reduce the undercut or taper the thickness to one-half."
            if st == "FAIL" else "Within the permissible strain.", "deflection")
    if l / h < 5:
        s.check("slender", "Beam theory", "WARN", f"l / h = {l / h:.1f}", "Under about 5 the arm is too stubby for the "
                "bending equations: shear and the root's give matter, and the real strain is lower than computed.", "deflection")
    E = modulus(s, inputs, material, direction)
    P = s.computed("deflection_force", "Deflection force P", b * h * h / 6 * E * eps / l, "N", "force") if E else None
    tail = _forces(s, inputs, P, friction(s, inputs, material))
    s.geometry("snap_cantilever", {"length": l, "thickness": h, "width": b, "undercut": y,
                                   "lead_angle": s["lead_angle"], "return_angle": s["return_angle"],
                                   "taper": list(TAPER).index(taper)},
               "Snap hook", {"material": material or "", "direction": direction},
               place={"feature": "snap_hook", "options": {"length": l, "thickness": h, "width": b, "lip": y}})
    return s.done(f"Strain {100 * eps:.2f} % of {100 * eps_allow:.2f} % allowed; h = {h:.2f} mm, y = {y:.2f} mm"
                  + (", " + tail if tail else ""))


def geometric_factor(ratio: float, nu: float, elastic: str) -> float:
    """X_N (hub elastic, ratio = d0/d) or X_W (hollow shaft elastic, ratio = d/di) of the guide's annular joint."""
    a = math.sqrt((ratio - 1) / (ratio + 1))
    c = (ratio ** 2 + 1) / (ratio ** 2 - 1)
    return 0.62 * a / (c + nu) if elastic == "hub" else 0.62 * a / (c - nu)


def _annular(inputs: dict, material, direction) -> dict:
    s = Sheet("snapfit", "Annular snap joint", "Bayer, Snap-Fit Joints for Plastics (annular snap joints)", inputs)
    bay = _eqs(s)
    s.eq("hoop", "ε = y / d", bay, "the undercut over the joint diameter; with both parts equally stiff each takes half")
    s.eq("transverse", "P = y · d · E_s · X", bay, "transverse force, joint near the end of the tube")
    s.eq("x_hub", "X_N = 0.62 · √((d0/d − 1)/(d0/d + 1)) / ([(d0/d)² + 1]/[(d0/d)² − 1] + ν)", bay, "elastic hub on a rigid shaft")
    s.eq("x_shaft", "X_W = 0.62 · √((d/di − 1)/(d/di + 1)) / ([(d/di)² + 1]/[(d/di)² − 1] − ν)", bay, "elastic hollow shaft in a rigid hub")
    s.eq("remote", "P_remote ≈ 3 · P_near   when the bead is more than 1.8 · √(d · t) from the end", bay,
         "theory gives 4; the guide's tests rarely exceed 3")
    d = number(inputs, "diameter", None, 2, 2000)
    t = number(inputs, "wall", None, 0.3, 200)
    need(d is not None and t is not None, "An annular joint needs its diameter and the wall of the part that gives.",
         "diameter=40 wall=2 (mm).", ["diameter", "wall"])
    s.given("diameter", "Diameter at the joint d", d, "mm")
    s.given("wall", "Wall thickness t", t, "mm")
    elastic = choice(inputs, "elastic", ("hub", "shaft", "both"), "hub")
    share = 0.5 if elastic == "both" else 1.0
    eps_allow = permissible_strain(s, inputs, material, direction)
    y = number(inputs, "undercut", None, 0.02, 100)
    if y is None:
        y = s.computed("undercut", "Largest undercut y the strain allows", eps_allow * d / share, "mm", "hoop")
    else:
        s.given("undercut", "Undercut y (on the diameter)", y, "mm")
    eps = s.computed("strain", "Hoop strain when it snaps", share * y / d, "", "hoop",
                     "each part takes half the undercut" if share < 1 else "one part rigid: the other takes it all")
    st = "FAIL" if eps > eps_allow * 1.0005 else "PASS"
    s.check("strain", "Strain when it snaps", st, f"{100 * eps:.2f} % of {100 * eps_allow:.2f} % allowed",
            "Reduce the undercut or make the joint larger." if st == "FAIL" else "Within the permissible strain.", "hoop")
    nu = material_prop(s, material, "poisson", "poisson", "Poisson's ratio", override=number(inputs, "poisson", None, 0, 0.5))
    if nu is None:
        nu = s.assumed("poisson", "Poisson's ratio", POISSON_PLASTICS, "", "no sourced value; the guide's own figure "
                       "for plastics (“approx. 0.35”)", source=bay)
    part = "shaft" if elastic == "shaft" else "hub"
    if part == "hub":
        ratio = s.computed("ratio", "d0 / d of the hub", (d + 2 * t) / d, "", "x_hub")
    else:
        need(d - 2 * t > 0.2 * d, "The hollow shaft's wall leaves almost no bore.", "Use a thinner wall.", ["wall"])
        ratio = s.computed("ratio", "d / di of the hollow shaft", d / (d - 2 * t), "", "x_shaft")
    X = s.computed("X", "Geometric factor X", geometric_factor(ratio, nu, part), "", "x_hub" if part == "hub" else "x_shaft")
    E = modulus(s, inputs, material, direction)
    P = None
    if E:
        P = y * share * d * E * X
        if choice(inputs, "position", ("near", "remote"), "near") == "remote":
            P = s.computed("deflection_force", "Transverse force P (bead remote from the end)", 3 * P, "N", "remote")
        else:
            P = s.computed("deflection_force", "Transverse force P", P, "N", "transverse")
        s.computed("remote_distance", "Distance from the end beyond which the joint counts as remote",
                   1.8 * math.sqrt(d * t), "mm", "remote")
    tail = _forces(s, inputs, P, friction(s, inputs, material))
    s.caveat("The mating force is for the whole ring pressed on square, by machine. By hand the bead goes in at an "
             "angle and the force is much lower (the guide says so of its own example).")
    H = number(inputs, "height", None, 3, 500) or max(6.0, round(0.5 * d, 1))
    s.geometry("snap_annular", {"diameter": d, "undercut": y, "wall": t, "height": H, "lead_angle": s["lead_angle"]},
               "Annular snap", {"material": material or ""})
    return s.done(f"Hoop strain {100 * eps:.2f} % of {100 * eps_allow:.2f} % allowed; undercut {y:.2f} mm on Ø{d:g}"
                  + (", " + tail if tail else ""))
