"""An ISO 286 fit over a temperature span.

The limits of the hole and the shaft are ISO 286's (form/iso286.py, the same tables form.craft.fits uses), and they
hold at 20 °C, the reference temperature of ISO 1. Away from it each part grows by its own expansion:

    d(T) = d(20 °C) · (1 + α · (T − 20))
    clearance(T) = hole(T) − shaft(T),  smallest = least hole − largest shaft,  largest = largest hole − least shaft

so a hole and a shaft of different materials change their fit with temperature: an aluminium housing loosens on a
steel shaft as it warms, a plastic bush tightens in a metal bore. The expansion coefficients are the materials'
sourced values (form/material_library.py) or the request's; one that has no source is not guessed.

Linear expansion with a constant coefficient, both parts at the same uniform temperature, free to grow. Moisture
swelling of nylon and the stress of an interference fit are not in it.
"""
from __future__ import annotations

from .. import iso286
from . import CalcError, I, Sheet, material_prop, need, number

ISO286 = (iso286.SOURCE, "")
ISO1 = ("ISO 1:2016, Geometrical product specifications: standard reference temperature (20 °C)", "")
T_REF = 20.0


def spec() -> dict:
    return {"id": "fit", "title": "Fit at temperature", "standard": "ISO 286-1/-2, ISO 1",
            "doc": "The clearance or interference range of an ISO 286 fit at 20 °C and over a temperature span, from "
                   "each material's sourced thermal expansion. Writes the bush and the pin at their mid-limit sizes.",
            "writes": "a housing ring and a pin at the middle of their tolerance zones, with parameters",
            "inputs": [
                I("fit", "Fit", "", None, 'an ISO code, e.g. "H7/g6"'),
                I("diameter", "Nominal diameter", "mm", None, ""),
                I("hole_material", "Material of the part with the hole", "", None, "library key, for its expansion"),
                I("shaft_material", "Material of the shaft", "", None, "library key"),
                I("alpha_hole", "Expansion of the hole's part", "1/K", None, "your own value, e.g. 23.6e-6"),
                I("alpha_shaft", "Expansion of the shaft", "1/K", None, ""),
                I("t_min", "Lowest temperature", "°C", None, ""),
                I("t_max", "Highest temperature", "°C", None, ""),
                I("length", "Length of the fit", "mm", None, "geometry; default 1.5 d"),
            ]}


def kind_of(cmin: float, cmax: float) -> str:
    return "clearance" if cmin >= 0 else "interference" if cmax <= 0 else "transition"


def at(limits: tuple, alpha: float, T: float) -> tuple:
    f = 1 + alpha * (T - T_REF)
    return limits[0] * f, limits[1] * f


def run(inputs: dict) -> dict:
    s = Sheet("fit", "Fit at temperature", "ISO 286-1/-2 limits at ISO 1's 20 °C, linear thermal expansion", inputs)
    src = s.source("iso286", *ISO286)
    iso1 = s.source("iso1", *ISO1)
    s.eq("limits", "hole = d + [EI, EI + IT],  shaft = d + [es − IT, es]  (or [ei, ei + IT])", src, "fundamental deviation and tolerance grade from the tables")
    s.eq("clearance", "C_min = hole_min − shaft_max,  C_max = hole_max − shaft_min", src, "negative = interference")
    s.eq("expansion", "d(T) = d(20 °C) · (1 + α · (T − 20))", iso1, "limits are defined at 20 °C; linear expansion with a constant α")
    code = inputs.get("fit")
    d = number(inputs, "diameter", None, 0.5, 500)
    need(code and d is not None, "Give the fit and the nominal diameter.", 'fit="H7/g6" diameter=25.', ["fit", "diameter"])
    try:
        hl, hg, sl, sg = iso286.parse(str(code))
        hole, shaft = iso286.hole_limits(hl, hg, d), iso286.shaft_limits(sl, sg, d)
    except iso286.Iso286Error as e:
        raise CalcError(str(e), e.hint, e.params) from None
    code = f"{hl}{hg}/{sl}{sg}"
    s.given("fit", "Fit", code, "")
    s.given("diameter", "Nominal diameter", d, "mm")
    for key, lab, lim in (("hole", f"Hole {hl}{hg}", hole), ("shaft", f"Shaft {sl}{sg}", shaft)):
        s.add(key + "_min", lab + ", least", round(lim[0], 4), "mm", "specified", source=src)
        s.add(key + "_max", lab + ", largest", round(lim[1], 4), "mm", "specified", source=src)
    c0 = (hole[0] - shaft[1], hole[1] - shaft[0])
    s.computed("clearance_min_20", "Smallest clearance at 20 °C", round(c0[0], 4), "mm", "clearance")
    s.computed("clearance_max_20", "Largest clearance at 20 °C", round(c0[1], 4), "mm", "clearance")
    k0 = kind_of(*c0)
    s.check("fit_20", "Fit at 20 °C", "INFO", k0, f"{c0[0] * 1000:+.0f} to {c0[1] * 1000:+.0f} µm (negative = interference).", "clearance")
    tmin, tmax = number(inputs, "t_min", None, -273, 2000), number(inputs, "t_max", None, -273, 2000)
    head = f"{code} Ø{d:g}: {c0[0] * 1000:+.0f} to {c0[1] * 1000:+.0f} µm at 20 °C ({k0})"
    if tmin is None and tmax is None:
        s.note("No temperature span given: the fit at 20 °C only. Give t_min and t_max for the range in service.")
    else:
        tmin = T_REF if tmin is None else tmin
        tmax = T_REF if tmax is None else tmax
        need(tmin <= tmax, "t_min is above t_max.", "", ["t_min", "t_max"])
        s.given("t_min", "Lowest temperature", tmin, "°C")
        s.given("t_max", "Highest temperature", tmax, "°C")
        ah = material_prop(s, inputs.get("hole_material") or None, "cte", "alpha_hole", "Thermal expansion, hole's part",
                           override=number(inputs, "alpha_hole", None, 0, 1e-3), unit="1/K")
        ash = material_prop(s, inputs.get("shaft_material") or None, "cte", "alpha_shaft", "Thermal expansion, shaft",
                            override=number(inputs, "alpha_shaft", None, 0, 1e-3), unit="1/K")
        lacking = [n for n, v, m in (("hole", ah, inputs.get("hole_material")), ("shaft", ash, inputs.get("shaft_material"))) if v is None]
        if lacking:
            for n in lacking:
                mat = inputs.get(n + "_material")
                s.missing("alpha_" + n, f"Thermal expansion of the {n}",
                          (f"The library has no sourced expansion coefficient for {mat}. " if mat else "No material given. ")
                          + f"Give alpha_{n} (1/K) from the material's datasheet; it is not assumed.")
            s.missing("clearance_span", "Clearance over the temperature span", "Needs both expansion coefficients.")
            s.check("fit_span", "Fit over the temperature span", "WARN", "not computed",
                    "An expansion coefficient has no source (see not_computed). The fit at 20 °C stands.", "expansion", evidence="specified")
            head += "; span not computed (an expansion coefficient is unsourced)"
        else:
            worst = []
            for T, tag in ((tmin, "cold"), (tmax, "hot")):
                h, sh = at(hole, ah, T), at(shaft, ash, T)
                c = (h[0] - sh[1], h[1] - sh[0])
                s.computed(f"clearance_min_{tag}", f"Smallest clearance at {T:g} °C", round(c[0], 4), "mm", "expansion")
                s.computed(f"clearance_max_{tag}", f"Largest clearance at {T:g} °C", round(c[1], 4), "mm", "expansion")
                worst += [c[0], c[1]]
            lo, hi = min(worst + list(c0)), max(worst + list(c0))
            s.computed("clearance_min_span", "Smallest clearance over the span", round(lo, 4), "mm", "expansion",
                       "the extremes are at the ends of the span (expansion is linear), 20 °C included")
            s.computed("clearance_max_span", "Largest clearance over the span", round(hi, 4), "mm", "expansion")
            s.eq("drift", "ΔC = d · (α_hole − α_shaft) · (T − 20)", iso1, "how far the whole fit moves with temperature")
            s.computed("drift_per_K", "Change of clearance per kelvin", d * (ah - ash) * 1000, "µm/K", "drift")
            ks = kind_of(lo, hi)
            changed = {kind_of(worst[0], worst[1]), kind_of(worst[2], worst[3]), k0}
            st = "PASS" if len(changed) == 1 else "WARN"
            s.check("fit_span", "Fit over the temperature span", st, f"{lo * 1000:+.0f} to {hi * 1000:+.0f} µm",
                    f"Stays a {k0} fit from {tmin:g} to {tmax:g} °C." if st == "PASS" else
                    f"Changes character over the span ({', '.join(sorted(changed))}): a {k0} fit at 20 °C is not one at the extremes.", "expansion")
            head = f"{code} Ø{d:g}: {c0[0] * 1000:+.0f} to {c0[1] * 1000:+.0f} µm at 20 °C, {lo * 1000:+.0f} to {hi * 1000:+.0f} µm from {tmin:g} to {tmax:g} °C ({ks})"
    s.caveat("ISO 286 limits are machining tolerances in micrometres. A printed hole or shaft holds about ±0.1 to "
             "0.2 mm: print undersize and ream, or use Form Studio's fit model for printed-to-printed fits.")
    L = number(inputs, "length", None, 1, 2000) or round(1.5 * d, 1)
    s.geometry("fit_pair", {"hole_d": (hole[0] + hole[1]) / 2, "shaft_d": (shaft[0] + shaft[1]) / 2, "length": L,
                            "wall": max(3.0, round(0.3 * d, 1))}, f"{code} fit, Ø{d:g}", {"fit": code})
    return s.done(head)
