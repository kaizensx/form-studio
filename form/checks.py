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

CHECKS_VERSION = 5
STRUCTURAL_LINES = 3    # a structural feature's wall under this many nozzle widths fails the Thinnest-wall check
NA = "N/A"           # a check that cannot run for this kind of design; never counted as a pass


def build(recipe, summary: dict, analysis: dict, ctx: dict, fit: dict | None) -> list[dict]:
    out = []

    def add(id, label, status, value, detail, evidence, **kw):
        out.append({"id": id, "label": label, "status": status, "value": value, "detail": detail, "evidence": evidence, **kw})

    b = analysis["brep"]
    want = b.get("expected_solids", 1)
    ok = b["valid"] and b["solids"] == want
    mesh = bool(b.get("mesh_design") or getattr(recipe, "mesh", False))
    if mesh:                       # OpenSCAD and other mesh designs: say what cannot be known, never fake it
        add("solid", "One valid solid", NA, "mesh design",
            "Not available for mesh designs. OCCT validity checks a boundary representation. This design is a triangle mesh from OpenSCAD, so there is "
            "none to check; the closed-mesh check below runs on the exported triangles instead.", "none")
    else:
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
        # the size against the bed is "Fits the build volume" below (which knows about several plates), not this one
        fails = [f for f in m.get("failures", []) if f != "exceeds_axis_aligned_envelope"]
        add("mesh", "Export mesh is closed", "PASS" if m["status"] == "PASS_LIMITED_SCREEN" or not fails else "FAIL",
            f"{m.get('triangles', 0):,} triangles",
            "No open, non-manifold, flipped, duplicate or degenerate faces in the exported STL."
            if not fails else "Problems: " + ", ".join(fails) + ".", "computed")
        dv = abs(m["volume_mm3"] - b["volume_mm3"]) / max(b["volume_mm3"], 1e-9)
        if mesh:
            add("conversion", "STL matches the CAD solid", NA, "mesh design",
                "Not available for mesh designs. There is no CAD solid to compare the STL with: the design itself is a mesh. "
                f"Mesh volume {m['volume_mm3']/1000:.2f} cm³.", "none")
        else:
            add("conversion", "STL matches the CAD solid", "PASS" if dv <= 0.002 else ("WARN" if dv <= 0.01 else "FAIL"),
                f"{dv*100:.3f}% volume", f"CAD {b['volume_mm3']/1000:.2f} cm³, mesh {m['volume_mm3']/1000:.2f} cm³. "
                "Guards against unit or tessellation errors in conversion.", "computed")

    if ctx.get("purpose") == "model":            # a 3D model: no printer, so no print checks (form/purpose.py)
        _model_checks(add, summary, analysis, ctx, mesh)
        s = summary.get("statics")
        for c in (s or {}).get("checks", []):
            add(c["id"], c["label"], c["status"], c["value"], c["detail"], c.get("evidence", "model"), feature=c.get("feature"))
        out.extend(analysis.get("assembly") or [])
        return out

    row = next(r for r in analysis["orientation_table"] if r["id"] == ctx["orientation"])
    env, margin = ctx["envelope"], ctx["margin"]
    size = [row["footprint_mm"][0], row["footprint_mm"][1], row["height_mm"]]
    fits = size[0] <= env[0] - 2 * margin and size[1] <= env[1] - 2 * margin and size[2] <= env[2]
    allows = f"{ctx['printer']} allows {env[0]-2*margin:.0f} × {env[1]-2*margin:.0f} × {env[2]:.0f} mm with a {margin:g} mm plate margin."
    plan = ctx.get("plates")
    if plan and (plan.get("needed") or plan["too_big"]):  # several parts: each must fit; the design may take several plates
        if plan["too_big"]:
            big = plan["too_big"]
            add("envelope", "Fits the build volume", "FAIL",
                f"{big[0]['label']}: {' × '.join(f'{v:.1f}' for v in big[0]['size'])} mm",
                ("These parts are" if len(big) > 1 else "This part is") + " larger than the plate however "
                + ("they lie" if len(big) > 1 else "it lies") + " flat: " + "; ".join(
                    f"{b['label']} {' × '.join(f'{v:.1f}' for v in b['size'])} mm" for b in big)
                + f". {allows} Split the part, scale it, or choose a larger printer.", "computed")
        else:
            n = plan["count"]
            mats = sorted({pl["material"] for pl in plan["plates"] if pl["material"]})
            add("envelope", "Fits the build volume", "PASS", f"{n} plate" + ("" if n == 1 else "s"),
                f"As modelled the design is {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm"
                + (", larger than one plate" if not fits else "") + f". Its {len(ctx.get('parts') or [])} parts are laid out "
                f"one by one on {n} plate{'' if n == 1 else 's'}, {plan['spacing_mm']:g} mm apart"
                + (f", one material per plate ({', '.join(mats)})" if len(mats) > 1 else "") + f". {allows}", "computed")
    else:
        detail = allows
        if not fits:                                  # another way to lie that does fit: say which
            alt = [r for r in analysis["orientation_table"] if r["id"] != row["id"]
                   and r["footprint_mm"][0] <= env[0] - 2 * margin and r["footprint_mm"][1] <= env[1] - 2 * margin
                   and r["height_mm"] <= env[2]]
            if alt:
                detail += f" It fits lying “{alt[0]['label']}”: change the print orientation in Prove."
        add("envelope", "Fits the build volume", "PASS" if fits else "FAIL",
            f"{size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm", detail, "computed")

    thin, nz = analysis.get("thin"), ctx["nozzle"]
    if thin:
        st = "PASS" if thin["t"] >= 3 * nz else ("WARN" if thin["t"] >= 2 * nz else "FAIL")
        spot, detail = thin, ""
        ts = analysis.get("thin_structural")
        if ts and ts["t"] < STRUCTURAL_LINES * nz:
            # a wall of a structural feature (the load path: a corbel, an arm, a clip's spine) under three nozzle
            # widths is a fail, not a warning to note: the softer 2-3 line band is for decorative ridges and fins
            spot, st = ts, "FAIL"
            names = ts.get("label") or ts.get("feature", "")
            by = f" (thinned by {', '.join(ts['cut_by'])})" if ts.get("cut_by") else ""
            detail = (f"A wall of the structural feature {names}{by} is {ts['t']:.2f} mm at "
                      f"({', '.join(f'{x:.1f}' for x in ts['at'])}) mm, under the {STRUCTURAL_LINES * nz:.1f} mm "
                      f"(three lines of a {nz:g} mm nozzle) a load-bearing wall needs. Thicken it there; a finish cut "
                      "into it (flutes, grooves, a chamfer) counts against it. ")
        add("wall", "Thinnest wall", st, f"{spot['t']:.2f} mm",
            detail + f"Smallest opposing-wall distance over {analysis['thickness_samples']:,} surface samples"
            + (" of the mesh. " if mesh else ". ") +
            f"Under {2*nz:.1f} mm cannot hold two perimeters on a {nz:g} mm nozzle"
            + (" (nozzle size assumed)." if ctx.get("nozzle_assumed") else "."),
            "computed", feature=spot.get("feature"), at=spot.get("at"), to=spot.get("to"))

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
    # material notes (heat, sunlight, warping, flexible and fibre-filled filament) come from form/materials.py
    return out


def _model_checks(add, summary, analysis, ctx, mesh):
    """The checks that matter for a model that is rendered, exchanged or made another way: its size, and its thinnest
    feature against the process the person named (a rule of thumb, labelled heuristic)."""
    from . import purpose
    bb = summary.get("bbox")
    if bb and len(bb) == 2:
        dims = [hi - lo for lo, hi in zip(bb[0], bb[1])]
        add("size", "Overall size", "PASS", " × ".join(f"{d:.1f}" for d in dims) + " mm",
            "Bounding box of the solid as modelled (X × Y × Z), measured on the kernel's geometry.", "computed")
    thin = analysis.get("thin")
    pr = purpose.PROCESSES.get(ctx.get("process") or "", purpose.PROCESSES[""])
    if thin:
        t, lim = thin["t"], pr["min_feature_mm"]
        where = f"Smallest opposing-wall distance over {analysis['thickness_samples']:,} surface samples" + (" of the mesh." if mesh else ".")
        if lim:
            add("feature", "Thinnest feature", "PASS" if t >= lim else ("WARN" if t >= lim / 2 else "FAIL"), f"{t:.2f} mm",
                f"{where} {pr['label']} usually needs at least {lim:g} mm. {pr.get('why', '')}".strip(), "heuristic",
                feature=thin.get("feature"), at=thin.get("at"), to=thin.get("to"))
        else:
            add("feature", "Thinnest feature", NA, f"{t:.2f} mm",
                f"{where} No manufacturing process is stated for this model, so there is no minimum to compare it with. "
                "Name one in the design's purpose to check it.", "computed",
                feature=thin.get("feature"), at=thin.get("at"), to=thin.get("to"))


def _fit_feature(recipe):
    if recipe.fit:
        return recipe.spec(recipe.fit["clearance"]).feature
    return next((f.id for f in recipe.features if f.role == "interface"), None)


def rollup(checks: list[dict]) -> dict:
    c = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for k in checks:
        c[k["status"]] = c.get(k["status"], 0) + 1
    return c
