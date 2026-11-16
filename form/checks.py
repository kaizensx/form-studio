"""Turn raw analysis into a check list. Each check states how it was obtained.

evidence:
  computed  — measured on the solid or mesh by the kernel
  heuristic — a rule of thumb applied to computed quantities
  model     — a statistical or rigid-body model with stated assumptions
  simulated — reported by the slicer
  physical  — recorded by the user from a real print

Assembly checks (form/assembly.py) carry frame="assembled": their at/to markers are in the assembled frame,
and a motion check's pose names the joint position where it was found.
"""
from __future__ import annotations

CHECKS_VERSION = 4


def build(recipe, summary: dict, analysis: dict, ctx: dict, fit: dict | None) -> list[dict]:
    out = []

    def add(id, label, status, value, detail, evidence, **kw):
        out.append({"id": id, "label": label, "status": status, "value": value, "detail": detail, "evidence": evidence, **kw})

    b = analysis["brep"]
    want = b.get("expected_solids", 1)
    ok = b["valid"] and b["solids"] == want
    add("solid", "One valid solid" if want == 1 else f"{want} valid parts", "PASS" if ok else "FAIL",
        f"{b['solids']} solid" + ("" if b["solids"] == 1 else "s"),
        "OCCT validity check on the boundary representation.", "computed")

    worst = max((abs(a["modelled"] - a["intended"]) for a in analysis["interface_audit"]), default=None)
    if worst is not None:
        txt = " · ".join(f"{a['label']} {a['modelled']:.3f}" for a in analysis["interface_audit"])
        add("interfaces", "Interfaces as modelled", "PASS" if worst <= 1e-3 else "FAIL", f"Δ {worst:.4f} mm",
            f"Measured on the built solid, not read from parameters: {txt} mm.", "computed", feature=_fit_feature(recipe))

    m = analysis.get("mesh")
    if m:
        fails = m.get("failures", [])
        add("mesh", "Export mesh is closed", "PASS" if m["status"] == "PASS_LIMITED_SCREEN" else "FAIL",
            f"{m.get('triangles', 0):,} triangles",
            "No open, non-manifold, flipped, duplicate or degenerate faces in the exported STL."
            if not fails else "Problems: " + ", ".join(fails) + ".", "computed")
        dv = abs(m["volume_mm3"] - b["volume_mm3"]) / max(b["volume_mm3"], 1e-9)
        add("conversion", "STL matches the CAD solid", "PASS" if dv <= 0.002 else ("WARN" if dv <= 0.01 else "FAIL"),
            f"{dv*100:.3f}% volume", f"CAD {b['volume_mm3']/1000:.2f} cm³, mesh {m['volume_mm3']/1000:.2f} cm³. "
            "Guards against unit or tessellation errors in conversion.", "computed")

    row = next(r for r in analysis["orientation_table"] if r["id"] == ctx["orientation"])
    env, margin = ctx["envelope"], ctx["margin"]
    size = [row["footprint_mm"][0], row["footprint_mm"][1], row["height_mm"]]
    fits = size[0] <= env[0] - 2 * margin and size[1] <= env[1] - 2 * margin and size[2] <= env[2]
    add("envelope", "Fits the build volume", "PASS" if fits else "FAIL",
        f"{size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm",
        f"{ctx['printer']} allows {env[0]-2*margin:.0f} × {env[1]-2*margin:.0f} × {env[2]:.0f} mm with a {margin:g} mm plate margin.", "computed")

    thin, nz = analysis.get("thin"), ctx["nozzle"]
    if thin:
        st = "PASS" if thin["t"] >= 3 * nz else ("WARN" if thin["t"] >= 2 * nz else "FAIL")
        add("wall", "Thinnest wall", st, f"{thin['t']:.2f} mm",
            f"Smallest opposing-wall distance over {analysis['thickness_samples']:,} surface samples. "
            f"Under {2*nz:.1f} mm cannot hold two perimeters on a {nz:g} mm nozzle"
            + (" (nozzle size assumed)." if ctx.get("nozzle_assumed") else "."),
            "computed", feature=thin.get("feature"), at=thin.get("at"), to=thin.get("to"))

    steep = row["steep_mm2"]
    add("overhang", "Unsupported overhangs", "PASS" if steep < 1 else "WARN", f"{steep:.0f} mm²",
        "Surface steeper than 45° from vertical, excluding flat ceilings and the plate face. "
        + ("None in this orientation." if steep < 1 else "Reorient, or confirm supports in the sliced preview."), "computed")

    span = next((d["value"] for d in summary["derived"] if d["key"] == "bridge_span"), None)
    if row["ceiling_mm2"] >= 1:
        if span is not None:
            add("bridge", "Bridged ceilings", "PASS" if span <= 10 else "WARN", f"{span:.1f} mm span",
                f"{row['ceiling_mm2']:.0f} mm² of flat ceiling prints as a bridge. Spans to about 10 mm usually bridge cleanly in PLA; "
                "inspect the bridge layers in the slice.", "heuristic", feature="cable")
        else:
            add("bridge", "Flat ceilings", "WARN", f"{row['ceiling_mm2']:.0f} mm²",
                "Flat downward faces above the plate print as bridges or need support. Inspect them in the slice.", "heuristic")

    slender = row["height_mm"] / max(min(row["footprint_mm"]), 1e-6)
    good = row["contact_mm2"] >= 150 and slender <= 3
    add("adhesion", "Plate contact", "PASS" if good else "WARN", f"{row['contact_mm2']:.0f} mm²",
        f"Flat area on the plate; height is {slender:.1f}× the narrowest footprint side. "
        + ("Stable first layer expected." if good else "Small or tall footprints may need a brim."), "heuristic")

    s = summary.get("statics")
    for c in (s or {}).get("checks", []):          # recipe-specific models (strength, loads, ...)
        add(c["id"], c["label"], c["status"], c["value"], c["detail"], c.get("evidence", "model"), feature=c.get("feature"))
    if s and "tip_force_n" in s:
        f = s["tip_force_n"]
        add("stability", "Tip-over resistance", "PASS" if f >= 1.0 else ("WARN" if f >= 0.5 else "FAIL"), f"{f:.2f} N",
            f"Push at the top of the device ({s['push_height_mm']:.0f} mm up) needed to tip the dock backwards. "
            f"Centre of mass sits {s['margin_back_mm']:.0f} mm ahead of the rear edge. {s['model']} "
            + ("Dock mass is an assumed infill fraction until sliced. " if s["dock_mass_assumed"] else "")
            + "The 1 N threshold (a firm tap) is an assumption.", "model", feature="body")

    if fit:
        y = fit["yield"]
        p = fit["sources"]["printer"]
        add("fit", "Fit within tolerance window", "PASS" if y >= 0.95 else ("WARN" if y >= 0.5 else "FAIL"), f"{y*100:.0f}% modelled",
            f"Expected total gap {fit['expected_gap']:.2f} mm (±{2*fit['sd']:.2f} at 2σ) against a window of "
            f"{fit['window'][0]:.2f}–{fit['window'][1]:.2f} mm. {fit.get('mating_label', 'Device width')} is {fit['sources']['mating']['source']}; "
            f"printer accuracy is {p['source']}" + (f" from {p['n']} measurements" if p["n"] else "") + ".",
            "model", feature=_fit_feature(recipe))
    out.extend(analysis.get("assembly") or [])     # interference, clearance, motion, tool access (form/assembly.py)
    return out


def _fit_feature(recipe):
    if recipe.fit:
        return recipe.spec(recipe.fit["clearance"]).feature
    return next((f.id for f in recipe.features if f.role == "interface"), None)


def rollup(checks: list[dict]) -> dict:
    c = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for k in checks:
        c[k["status"]] = c.get(k["status"], 0) + 1
    return c
