"""Living hinges: a thin web that folds.

Two ways to size one, and the sheet says which it used:

  elastic   The web bends as a strip onto an arc: fold angle θ over a flexing length L gives the radius R = L / θ and
            the outer-fibre strain ε = t / (2 R) = t · θ / (2 L) (pure bending, plane sections). The strain is kept
            under the material's permissible strain (form/calc/snapfit.py: the same sourced rules), so the hinge
            springs back. This is the mode for printed parts and for any material that is not polypropylene or
            polyethylene; it gives long, thin flexures.

  moulded   A moulded polypropylene or polyethylene hinge is not an elastic design: at 0.3 mm thick, folded flat over
            1.5 mm, the outer fibre sees tens of per cent strain. It lasts because the resin orients across the hinge
            on the first flexes. Its dimensions are moulders' practice, taken here from cited guides, and the strain
            is reported so nobody mistakes it for an elastic hinge.

The moment to hold the fold (elastic mode) is M = E · I · θ / L with I = w · t³ / 12.
"""
from __future__ import annotations

import math

from . import I, Sheet, choice, material_kind, need, number
from .snapfit import modulus, permissible_strain

PROTOLABS = ("Protolabs, Designing Living Hinges that Fold Flat",
             "https://www.protolabs.com/resources/design-tips/designing-living-hinges-that-fold-flat/")
PTA = ("Plastics Technology Alliance, Injection Molding Living Hinge Design: Dimensions, Materials, and Process Rules",
       "https://plasticstechnologyalliance.com/injection-molding-living-hinge/")
RJC = ("RJC Mold, Living Hinge Design Guide for Injection Molding", "https://rjcmold.com/guides/living-hinge-design-guide/")
BEAM = ("Euler-Bernoulli pure bending: strain = distance from the neutral axis / radius of curvature "
        "(any mechanics of materials text, e.g. Gere and Goodno, Mechanics of Materials, ch. 5)", "")
# moulded PP / PE, 180° flat-fold profile (mm): web thickness range and baseline, land length, bottom relief radius
MOULDED = {"web": (0.20, 0.38), "web_baseline": (0.25, 0.30), "land": 1.5, "relief_r": (0.65, 0.90, 0.75)}
HINGE_RESINS = ("pp", "pe")


def spec() -> dict:
    return {"id": "hinge", "title": "Living hinge", "standard": "pure bending of a strip; moulders' dimensions for PP and PE",
            "doc": "A living hinge sized by strain (elastic: any material, printed parts) or from cited moulding "
                   "practice (polypropylene, polyethylene). Writes two panels joined by the web.",
            "writes": "two panels joined by a filleted web, with parameters",
            "inputs": [
                I("mode", "How it is sized", "", "elastic", "", ("elastic", "moulded")),
                I("resin", "Moulded resin", "", "pp", "moulded mode", HINGE_RESINS),
                I("material", "Material", "", None, "elastic mode: a key of the materials library"),
                I("direction", "Bending direction of a printed part", "", "xy", "", ("xy", "z")),
                I("allow_strain", "Permissible strain", "fraction", None, "elastic mode; your own value"),
                I("guide_resin", "Resin of Bayer's Table 2", "", None, ""),
                I("use", "How often it folds", "", "frequent", "frequent: 60 % of the permissible strain", ("single", "frequent")),
                I("utilisation", "Share of the permissible strain used", "fraction", 1.0, ""),
                I("E", "Modulus", "MPa", None, "for the holding moment"),
                I("angle", "Fold angle θ", "deg", 180.0, ""),
                I("thickness", "Web thickness t", "mm", None, "left out (elastic): sized from the length; (moulded): 0.3"),
                I("length", "Flexing length L (the web's land)", "mm", None, "left out (elastic): sized from the thickness"),
                I("width", "Hinge width w", "mm", 30.0, ""),
                I("panel_thickness", "Panel thickness", "mm", 3.0, "geometry"),
                I("panel_length", "Panel length", "mm", 25.0, "geometry"),
            ]}


def run(inputs: dict) -> dict:
    mode = choice(inputs, "mode", ("elastic", "moulded"), "elastic")
    s = Sheet("hinge", "Living hinge", spec()["standard"], inputs)
    beam = s.source("beam", *BEAM)
    s.eq("radius", "R = L / θ   (θ in radians)", beam, "the web bends to a circular arc over its flexing length")
    s.eq("strain", "ε = t / (2 R) = t · θ / (2 L)", beam, "outer fibre, neutral axis at mid-thickness")
    s.eq("moment", "M = E · (w · t³ / 12) · θ / L", beam, "moment that holds the fold, linear elastic")
    theta_deg = number(inputs, "angle", 180.0, 5, 360)
    (s.given if "angle" in inputs else lambda *a: s.assumed(*a, "folds flat, unless the request says otherwise"))("angle", "Fold angle θ", theta_deg, "deg")
    theta = math.radians(theta_deg)
    w = number(inputs, "width", 30.0, 2, 2000)
    (s.given if "width" in inputs else lambda *a: s.assumed(*a, "30 mm, unless the request says otherwise"))("width", "Hinge width w", w, "mm")
    t = number(inputs, "thickness", None, 0.05, 5)
    L = number(inputs, "length", None, 0.3, 500)
    material = inputs.get("material") or None
    direction = choice(inputs, "direction", ("xy", "z"), "xy")
    if mode == "moulded":
        resin = choice(inputs, "resin", HINGE_RESINS, "pp")
        pl = s.source("protolabs", *PROTOLABS, "“The most popular resins for parts with living hinges are polypropylene and polyethylene”; recess the hinge so the panels fold flat")
        pta = s.source("pta", *PTA, "“the ideal living hinge web thickness is 0.20–0.38 mm (0.008–0.015 in), with 0.25–0.30 mm … the industry baseline for 180° flat-folding hinges”; bottom relief radius 0.75 mm (0.65–0.90 mm); citing Protolabs")
        rjc = s.source("rjc", *RJC, "“the thin hinge land is often approximately 1.5 mm long, while the bend radius is commonly around 0.75 mm”; PP hinge thickness 0.2–0.5 mm")
        if t is None:
            t = s.add("thickness", "Web thickness t", 0.30, "mm", "specified", source=pta, note="top of the 0.25–0.30 mm baseline for a 180° fold")
        else:
            s.given("thickness", "Web thickness t", t, "mm")
        if L is None:
            L = s.add("length", "Land length L", MOULDED["land"], "mm", "specified", source=rjc)
        else:
            s.given("length", "Land length L", L, "mm")
        s.add("relief_radius", "Bottom relief radius", MOULDED["relief_r"][2], "mm", "specified", source=pta, note="0.65–0.90 mm")
        lo, hi = MOULDED["web"]
        s.check("web", "Web thickness against moulding practice", "PASS" if lo <= t <= hi else "WARN", f"{t:g} mm",
                f"Cited range for {resin.upper()}: {lo:g} to {hi:g} mm. Thicker folds stiffly and whitens; thinner will not fill.",
                evidence="specified")
        R = s.computed("radius", "Bend radius of the web's mid-plane", L / theta, "mm", "radius")
        eps = s.computed("strain", "Outer-fibre strain, as if elastic", t / (2 * R), "", "strain")
        s.check("regime", "Design regime", "INFO", f"{100 * eps:.0f} % nominal strain",
                "Far above any elastic limit, as every moulded PP or PE hinge is. It survives by orientation of the "
                "resin across the hinge (flex it right after moulding; gate so the melt crosses the hinge). No fatigue "
                "life is computed.", "strain")
        s.caveat("Moulded mode: dimensions from cited moulding guides, valid for injection-moulded "
                 f"{'polypropylene' if resin == 'pp' else 'polyethylene'} only. A printed or machined web of these "
                 "dimensions in another material cracks; use elastic mode for those.")
        s.note(f"Source for the resin choice: {PROTOLABS[0]}.")
        _ = pl
        head = f"Moulded {resin.upper()} hinge: web {t:g} mm over a {L:g} mm land, relief radius {MOULDED['relief_r'][2]:g} mm"
    else:
        eps_allow = permissible_strain(s, {"use": "frequent", **inputs}, material, direction)
        need(t is not None or L is not None, "Give the web thickness (the length is then sized) or the length.",
             "thickness=0.5, or length=20.", ["thickness", "length"])
        if L is None:
            s.given("thickness", "Web thickness t", t, "mm")
            L = s.computed("length", "Shortest flexing length L the strain allows", t * theta / (2 * eps_allow), "mm", "strain")
        elif t is None:
            s.given("length", "Flexing length L", L, "mm")
            t = s.computed("thickness", "Thickest web t the strain allows", 2 * eps_allow * L / theta, "mm", "strain")
        else:
            s.given("thickness", "Web thickness t", t, "mm")
            s.given("length", "Flexing length L", L, "mm")
        R = s.computed("radius", "Bend radius of the web's mid-plane", L / theta, "mm", "radius")
        eps = s.computed("strain", "Outer-fibre strain when folded", t / (2 * R), "", "strain")
        st = "FAIL" if eps > eps_allow * 1.0005 else "PASS"
        s.check("strain", "Strain when folded", st, f"{100 * eps:.2f} % of {100 * eps_allow:.2f} % allowed",
                "Lengthen the web or thin it." if st == "FAIL" else "The web stays within the permissible strain.", "strain")
        E = modulus(s, inputs, material, direction)
        if E:
            s.computed("moment", "Moment to hold the fold", E * (w * t ** 3 / 12) * theta / L, "N·mm", "moment")
        else:
            s.missing("moment", "Moment to hold the fold", "No sourced modulus: give E (MPa).")
        if material_kind(material)["kind"] == "filament":
            s.caveat("A printed web: lay the lines across the bend, print it flat, and expect creep and whitening well "
                     "before the datasheet's elongation. Good for tens of folds in PETG or nylon, not for a product.")
        if t < 0.4 and material_kind(material)["kind"] == "filament":
            s.check("printable", "Web against a 0.4 mm nozzle", "WARN", f"{t:.2f} mm", "Thinner than one extrusion "
                    "line of a 0.4 mm nozzle (assumed): print it as two layers of 0.2 mm, or lengthen the web.",
                    evidence="assumed")
        head = f"Strain {100 * eps:.2f} % of {100 * eps_allow:.2f} % allowed; web {t:.2f} mm over {L:.1f} mm"
    pt = number(inputs, "panel_thickness", 3.0, 0.8, 50)
    plen = number(inputs, "panel_length", 25.0, 3, 500)
    need(pt >= t + 0.6, "The panels must be at least 0.6 mm thicker than the web.", "Raise panel_thickness.", ["panel_thickness"])
    s.geometry("living_hinge", {"width": w, "gap": L, "web_t": t, "panel_t": pt, "panel_len": plen, "angle": theta_deg},
               "Living hinge", {"material": material or "", "mode": mode})
    return s.done(head)
