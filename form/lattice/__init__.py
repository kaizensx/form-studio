"""Lattices and TPMS infill inside a region of a design, with what the cell is worth.

    form/lattice/cells.py   the unit cells: TPMS level sets (gyroid, Schwarz P, Schwarz D / diamond, Neovius) and
                            strut lattices (BCC, FCC, octet, Kelvin); density, wall, pore and area from the cell
                            alone; marching tetrahedra. numpy only
    form/lattice/geom.py    the geometry in the kernel: struts as exact B-rep cylinders and node spheres, a TPMS as
                            a faceted B-rep while it is small and a mesh body when it is not; the skin always exact
    form/lattice/homog.py   one periodic cell by finite elements (a frame for struts, voxels for a TPMS)
    form/lattice/tools.py   MCP: lattice_fill, lattice_properties        form/lattice/cli.py   `form lattice ...`
    form/lattice/bench.py   the Bench entry "Lattice infill"

A lattice is one feature of the design, kept as data in a block at the end of its source (as text on faces and
standard features are): the build replaces the inside of the region with the lattice and leaves a skin of the given
thickness. Changing it is a new revision; removing it gives the body back.

Numbers and what they are:
  * relative density: "computed" on the unit cell (a smoothed count; the first-order strut formula beside it), and
    "measured on the built solid" once it is built;
  * stiffness and strength: "computed (scaling law)", Gibson and Ashby's E* / Es = C rho^n with the class of the cell
    (bending: C = 1, n = 2; stretch: C = 1/3, n = 1; the octet truss along a cell axis: C = 1/9), and, when asked,
    one cell by finite elements beside it with the difference;
  * printability: the thinnest strut or wall against the process's sourced limit (form/dfm/rules), against the
    nozzle for FDM, and for resin and powder processes the closed voids the skin leaves and the pore against the
    escape hole the table asks for.
"""
from __future__ import annotations

import ast
import json
import math
import re

from . import cells as C

VERSION = 1
EVIDENCE_CELL = "computed (unit cell)"
EVIDENCE_LAW = "computed (scaling law)"
EVIDENCE_BUILT = "measured on the built solid"
START = "# ---- Form Studio: lattice infill (edit with lattice_fill or `form lattice`) ----"
END = "# ---- end of lattice infill ----"

# Gibson-Ashby scaling: E* / Es = C rho^n, sigma* / sigma_ys = Cs rho^m
LAWS = {
    "bending": {"C": 1.0, "n": 2.0, "Cs": 0.3, "m": 1.5,
                "source": "Gibson and Ashby, Cellular Solids, 2nd ed. (1997), eqs 5.6a and 5.27a (open cells that bend)"},
    "stretch": {"C": 1.0 / 3.0, "n": 1.0, "Cs": 1.0 / 3.0, "m": 1.0,
                "source": "Ashby, Phil. Trans. R. Soc. A 364 (2006) 15-30, sect. 3 (stretch-dominated lattices, the "
                          "ideal upper estimate)"},
    "octet": {"C": 1.0 / 9.0, "n": 1.0, "Cs": 1.0 / 3.0, "m": 1.0,
              "source": "Deshpande, Fleck and Ashby, J. Mech. Phys. Solids 49 (2001) 1747-1769: E = rho Es / 9 along "
                        "a cell axis of the octet truss"},
}
# The class of each cell. Struts: the exponent of the periodic frame model (form/lattice/homog.py; the test suite
# recomputes it: 1.00 for fcc and octet, 2.0 for bcc and kelvin). TPMS: Form Studio's voxel model gives E close to
# the stretch law for sheets and to the bending law for networks (docs/LATTICES.md), as Al-Ketan, Rowshan and Abu
# Al-Rub, Additive Manufacturing 19 (2018) 167-183 report from tests.
CLASS = {"bcc": "bending", "kelvin": "bending", "fcc": "stretch", "octet": "octet",
         ("sheet",): "stretch", ("network",): "bending"}
CLASS_BASIS = {"bcc": "frame FE exponent 2.0", "kelvin": "frame FE exponent 2.0", "fcc": "frame FE exponent 1.0",
               "octet": "frame FE exponent 1.0; Deshpande, Fleck and Ashby 2001",
               "sheet": "sheet TPMS: near the stretch law in Form Studio's voxel FE and in Al-Ketan et al. 2018 (tests)",
               "network": "network TPMS: near the bending law in Form Studio's voxel FE and in Al-Ketan et al. 2018"}
TRAPPING = ("sla", "sls", "mjf", "lpbf")
MEDIUM = {"sla": "resin", "sls": "powder", "mjf": "powder", "lpbf": "powder"}


LatticeError = C.LatticeError


def _serr(e):
    from ..studio import StudioError
    return StudioError(str(e), getattr(e, "hint", "") or "")


def _num(v, what: str, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise LatticeError(f"{what} must be a number.", params=[what]) from None
    if not math.isfinite(x) or not lo <= x <= hi:
        raise LatticeError(f"{what} must be between {lo:g} and {hi:g}.", params=[what])
    return x


# ── the specification ────────────────────────────────────────────────────────────────────────────────────────────

def normalise(kind: str, cell: float, form: str = "sheet", wall: float | None = None, strut_d: float | None = None,
              density: float | None = None, skin: float = 0.0, node: float = 1.25, region: dict | None = None,
              grading: dict | None = None, output: str = "auto", resolution: int = 14) -> dict:
    """A lattice specification, checked and completed (the level of a TPMS, the strut of a density). Plain data."""
    try:
        k = C.kind_of(kind)
    except ValueError as e:
        raise LatticeError(str(e), params=["kind"]) from None
    a = _num(cell, "cell", 0.5, 500.0)
    spec: dict = {"kind": k, "cell": round(a, 4), "skin": round(_num(skin or 0.0, "skin", 0.0, 100.0), 4)}
    if output not in ("auto", "brep", "mesh"):
        raise LatticeError("output is auto, brep or mesh.", params=["output"])
    spec["output"] = output
    g = _grading(grading)
    if g:
        spec["grading"] = g
    given = [n for n, v in (("wall", wall), ("strut_d", strut_d), ("density", density)) if v is not None]
    if g:
        if given:
            raise LatticeError("A graded lattice takes its density from grading.density: leave out " + ", ".join(given) + ".",
                               params=given)
        density = 0.5 * (g["density"][0] + g["density"][1])               # the nominal value the numbers are quoted at
    elif len(given) != 1:
        raise LatticeError("Give one of: density (0.02 to 0.8), " + ("wall (mm)" if C.is_tpms(k) else "strut_d (mm)") + ".",
                           "density is the relative density of the lattice; the wall or strut follows from it.",
                           ["density", "wall", "strut_d"])
    if C.is_tpms(k):
        f = str(form or "sheet").lower()
        if f not in C.FORMS:
            raise LatticeError("form is sheet (a wall about the surface) or network (one channel system filled).",
                               params=["form"])
        if strut_d is not None:
            raise LatticeError("A TPMS has a wall, not struts: give wall or density.", params=["strut_d"])
        spec["form"] = f
        spec["resolution"] = int(_num(resolution, "resolution", 6, 64))
        if wall is not None:
            if f != "sheet":
                raise LatticeError("A network TPMS is sized by density, not wall.", params=["wall"])
            w = _num(wall, "wall", 0.01, a / 2)
            level = C.tpms_level_for_wall(k, w, a)
            if level >= 0.95 * C.F_MAX[k]:
                raise LatticeError(f"A {w:g} mm wall closes a {a:g} mm {C.LABEL[k]} cell.", "Use a thinner wall or a "
                                   "larger cell.", ["wall", "cell"])
        else:
            lo = 0.02 if f == "sheet" else 0.05
            level = float(C.tpms_level(k, f, _num(density, "density", lo, 0.8)))
        spec["level"] = round(level, 6)
    else:
        if wall is not None:
            raise LatticeError("A strut lattice has struts, not a wall: give strut_d or density.", params=["wall"])
        spec["node"] = round(_num(node, "node", 1.05, 2.0), 3)
        from . import geom
        import numpy as np
        if strut_d is not None:
            d = _num(strut_d, "strut_d", 0.02, a)
        else:
            d = 2.0 * float(geom._radius_for_density(k, np.array([_num(density, "density", 0.005, 0.6)]), a, spec["node"])[0])
        thick = d if not g else 2.0 * float(geom._radius_for_density(k, np.array([max(g["density"])]), a, spec["node"])[0])
        short = C.strut_min_length(k) * a
        if thick * spec["node"] > 0.8 * short:
            # two node spheres on one short strut would all but touch: surfaces that graze each other are where a
            # B-rep kernel fails, and a lattice that dense is nearly solid anyway
            raise LatticeError(f"A {thick:.2f} mm strut is too thick for a {a:g} mm {C.LABEL[k]} cell: its node spheres "
                               f"({thick * spec['node']:.2f} mm) nearly fill the shortest strut ({short:.2f} mm).",
                               "Use a thinner strut, a lower density or a larger cell (node sphere at most 0.8 of the "
                               "shortest strut).", ["strut_d", "density", "cell"])
        spec["strut_d"] = round(d, 5)
    if region:
        try:
            lo, hi = [float(x) for x in region["min"]], [float(x) for x in region["max"]]
            assert len(lo) == 3 and len(hi) == 3
        except (KeyError, TypeError, ValueError, AssertionError):
            raise LatticeError('region is {"min": [x, y, z], "max": [x, y, z]} in design millimetres.',
                               params=["region"]) from None
        spec["region"] = {"min": lo, "max": hi}
    return spec


def _grading(g) -> dict | None:
    if not g or (g.get("mode") or "uniform") == "uniform":
        return None
    mode = g.get("mode")
    if mode not in ("distance", "stress"):
        raise LatticeError(f"Unknown grading “{mode}”.", "uniform, distance or stress.", ["grading"])
    try:
        d0, d1 = (float(x) for x in g["density"])
    except (KeyError, TypeError, ValueError):
        raise LatticeError("grading.density is [density at the reference (or at no stress), density far from it (or at "
                           "the peak stress)].", params=["grading"]) from None
    for d in (d0, d1):
        if not 0.02 <= d <= 0.8:
            raise LatticeError("grading.density values are relative densities between 0.02 and 0.8.", params=["grading"])
    out = {"mode": mode, "density": [d0, d1]}
    if mode == "distance":
        out["from"] = g.get("from", "boundary")
        out["over"] = _num(g.get("over"), "grading.over", 0.1, 10000.0)
    else:
        grid = g.get("grid")
        if not isinstance(grid, dict) or not {"origin", "step", "shape", "values"} <= set(grid):
            raise LatticeError("grading.grid is missing: a stress grading takes the field of a strength study.",
                               "Pass study= (lattice_fill reads the study's von Mises field), or a grid "
                               "{origin, step, shape, values} with values from 0 to 1.", ["grading"])
        n = int(grid["shape"][0]) * int(grid["shape"][1]) * int(grid["shape"][2])
        if n != len(grid["values"]) or n > 4096:
            raise LatticeError("grading.grid.values must have shape[0] * shape[1] * shape[2] numbers (at most 4096).",
                               params=["grading"])
        out["grid"] = {"origin": [float(x) for x in grid["origin"]], "step": [float(x) for x in grid["step"]],
                       "shape": [int(x) for x in grid["shape"]], "values": [round(float(x), 4) for x in grid["values"]]}
        out["exponent"] = _num(g.get("exponent", 1.0), "grading.exponent", 0.1, 4.0)
        for k in ("study", "peak_MPa", "field_evidence"):
            if g.get(k) is not None:
                out[k] = g[k]
    return out


def stress_grid(st, p: dict, study: str, n: int = 8) -> dict:
    """A strength study's von Mises field (form/fea, the surface of its finest mesh) as a grid over the part's
    bounding box, n points along the longest side, each value the mean of the 8 nearest surface vertices weighted by
    inverse distance, divided by the peak: 0 to 1. The study must be current for the head revision."""
    import base64
    import numpy as np
    from ..fea import study as fs
    f = fs.field(st, p, study)
    if "von_mises" not in (f.get("fields") or {}):
        raise LatticeError("That study has no von Mises field (a static or thermal-stress study has one).",
                           params=["study"])
    P = np.frombuffer(base64.b64decode(f["positions"]), "<f4").reshape(-1, 3).astype(float)
    vm = np.frombuffer(base64.b64decode(f["fields"]["von_mises"]["data"]), "<f4").astype(float)
    return grid_from_points(P, vm, n, study=study, evidence=f.get("evidence"))


def grid_from_points(P, values, n: int = 8, study: str = "", evidence: str | None = None) -> dict:
    import numpy as np
    P, v = np.asarray(P, float), np.asarray(values, float)
    lo, hi = P.min(axis=0), P.max(axis=0)
    size = np.maximum(hi - lo, 1e-9)
    shape = np.maximum(2, np.round(size / size.max() * (n - 1)).astype(int) + 1)
    step = size / (shape - 1)
    G = np.stack(np.meshgrid(*[lo[k] + step[k] * np.arange(shape[k]) for k in range(3)], indexing="ij"), axis=-1).reshape(-1, 3)
    out = np.zeros(len(G))
    k = min(8, len(P))
    for i in range(0, len(G), 512):
        d = np.linalg.norm(G[i:i + 512, None, :] - P[None, :, :], axis=2)
        idx = np.argpartition(d, k - 1, axis=1)[:, :k]
        dd = np.take_along_axis(d, idx, axis=1)
        w = 1.0 / np.maximum(dd, 1e-6)
        out[i:i + 512] = (w * v[idx]).sum(axis=1) / w.sum(axis=1)
    peak = float(v.max())
    grid = {"origin": lo.tolist(), "step": step.tolist(), "shape": shape.tolist(),
            "values": (out / peak if peak > 0 else out).tolist()}
    return {"grid": grid, "peak_MPa": peak, "study": study, "field_evidence": evidence}


# ── what the cell is worth ───────────────────────────────────────────────────────────────────────────────────────

def cell_class(spec: dict) -> tuple:
    if C.is_tpms(spec["kind"]):
        f = spec.get("form", "sheet")
        return CLASS[(f,)], CLASS_BASIS[f]
    return CLASS[spec["kind"]], CLASS_BASIS[spec["kind"]]


def gibson_ashby(density: float, cls: str) -> dict:
    """E* / Es and sigma* / sigma_ys from the scaling law of a class (bending, stretch, octet)."""
    law = LAWS[cls]
    return {"E_rel": law["C"] * density ** law["n"], "strength_rel": law["Cs"] * density ** law["m"],
            "C": law["C"], "n": law["n"], "Cs": law["Cs"], "m": law["m"], "class": cls, "source": law["source"]}


def _density(spec: dict) -> dict:
    k, a = spec["kind"], float(spec["cell"])
    if C.is_tpms(k):
        rho = C.tpms_density(k, spec["form"], float(spec["level"]))
        out = {"value": rho, "evidence": EVIDENCE_CELL, "method": "smoothed count on 72³ points of one cell"}
        if spec["form"] == "sheet":
            area = C.PUBLISHED_AREA.get(k)
            w = C.tpms_wall(k, float(spec["level"]), a)
            if area:
                out["thin_wall_estimate"] = {"value": area * w["mean_mm"] / a, "formula": "A t / a, A the minimal "
                                             f"surface's area per cell ({area})", "source": C.AREA_SOURCE}
        return out
    from . import geom
    r = float(spec["strut_d"]) / 2.0
    thin = r / a * 96 < 1.25
    return {"value": geom.strut_density(k, r, a, float(spec["node"])), "evidence": EVIDENCE_CELL,
            "method": "thin-strut limit pi r² L / a³ (the strut is too thin to count on a grid)" if thin else
                      "smoothed count on the union of struts and node spheres (48³ points, 96³ for thin struts)",
            "first_order": {"value": C.strut_density_first_order(k, r, a), "formula": "pi r² L / a³, L = "
                            f"{C.STRUT_LENGTH[k] :.4f} a (node overlap and node spheres not counted)"}}


def _features(spec: dict) -> dict:
    """The thinnest thing to print and the open space, from the cell."""
    k, a = spec["kind"], float(spec["cell"])
    g = spec.get("grading")
    if C.is_tpms(k):
        f = spec["form"]
        levels = [float(spec["level"])] if not g else [float(C.tpms_level(k, f, d)) for d in g["density"]]
        if f == "sheet":
            walls = [C.tpms_wall(k, lv, a) for lv in levels]
            thin = min(w["min_mm"] for w in walls)
            out = {"what": "wall", "min_mm": thin, "mean_mm": [w["mean_mm"] for w in walls] if g else walls[0]["mean_mm"],
                   "method": "2 c / |grad f| on the surface (first order)"}
        else:
            lv = min(levels)
            X, Y, Z = C._phase_grid(48)
            solid = C.tpms_solid(k, f, X, Y, Z, lv) < 0
            thin = 2.0 * float(C._edt(solid).max()) * a / 48 if solid.any() else 0.0
            out = {"what": "thickest section of the network (its thinnest is not measured on the cell)", "min_mm": None,
                   "largest_section_mm": thin, "method": "largest sphere inside the solid, on a 48³ grid"}
        out["pore_mm"] = min(C.tpms_pore(k, f, lv, a) for lv in levels)
        out["channels"] = 2 if f == "sheet" else 1
        return out
    if g:
        from . import geom
        import numpy as np
        rs = geom._radius_for_density(k, np.array(g["density"], float), a, float(spec["node"]))
        d_lo, d_hi = 2 * float(rs.min()), 2 * float(rs.max())
    else:
        d_lo = d_hi = float(spec["strut_d"])
    return {"what": "strut", "min_mm": d_lo, "max_mm": d_hi, "pore_mm": C.strut_pore(k, d_hi / 2.0 * float(spec["node"]), a),
            "channels": 1, "method": "strut diameter; pore = largest sphere between struts of the node radius"}


def material_numbers(material) -> dict | None:
    """E (MPa) and yield (MPa) of the solid with their sources, from the materials library or as given."""
    if not material:
        return None
    from ..fea import material as fm
    m = fm.resolve(material, need=("E",))
    src = m.get("sources") or {}
    e = src.get("E") or {}
    y = src.get("yield") or {}
    out = {"key": m.get("key") or m.get("name"), "name": m.get("name"),
           "E_MPa": float(e["value"]) * (1000.0 if e.get("unit") == "GPa" else 1.0) if e.get("value") is not None else None,
           "E_source": e.get("source"), "E_evidence": e.get("evidence")}
    if y.get("value") is not None:
        out.update(yield_MPa=float(y["value"]), yield_source=y.get("source"), yield_evidence=y.get("evidence"))
    nu = src.get("nu") or {}
    if nu.get("value") is not None:
        out["poisson"] = float(nu["value"])
    return out


def printability(spec: dict, feats: dict, process: str | None = None, nozzle: float | None = None,
                 built: dict | None = None) -> dict:
    """Rows against a process: thinnest strut or wall, and for resin and powder what stays trapped."""
    if not process:
        return {"process": None, "rows": [], "note": "No process given: the thinnest feature is "
                + (f"{feats['min_mm']:.3f} mm" if feats.get("min_mm") is not None else "not measured on the cell")
                + ". Give process= (fdm, sla, sls, mjf, lpbf) to check it against that process's limits."}
    from ..dfm import ALIASES, rules as R
    proc = ALIASES.get(str(process).lower(), str(process).lower())
    if proc not in R.PRINTING:
        raise LatticeError(f"“{process}” is not a printing process.", "fdm, sla, sls, mjf or lpbf.", ["process"])
    tb = R.table(proc)
    rows = []
    wall = next((r for r in tb["rules"] if r.get("measure") == "wall_min_mm"), None)
    thin = feats.get("min_mm")
    if wall is not None and wall.get("fail") is not None:
        src = tb["sources"].get(wall.get("source"), {})
        if thin is None:
            rows.append({"id": "lattice.thin", "title": f"Thinnest {feats['what']}", "status": "UNKNOWN",
                         "detail": "a network TPMS's thinnest section is not measured on the cell", "limit_mm": wall["fail"]})
        else:
            rows.append({"id": "lattice.thin", "title": f"Thinnest {feats['what']}", "value_mm": round(thin, 4),
                         "limit_mm": wall["fail"], "status": "PASS" if thin >= wall["fail"] else "FAIL",
                         "evidence": "computed (unit cell) against a sourced limit",
                         "source": R.source_text(src) if src else wall.get("source"), "quote": wall.get("quote"),
                         "note": ("the table's limit is for a wall; it has none for a strut" if feats["what"] == "strut" else "")})
    if proc == "fdm" and thin is not None:
        if nozzle:
            rows.append({"id": "lattice.nozzle", "title": f"Thinnest {feats['what']} against the nozzle",
                         "value_mm": round(thin, 4), "limit_mm": float(nozzle),
                         "status": "PASS" if thin >= float(nozzle) else "FAIL", "evidence": "computed",
                         "note": "a feature narrower than one extrusion cannot be printed"})
        else:
            rows.append({"id": "lattice.nozzle", "title": f"Thinnest {feats['what']} against the nozzle", "status": "UNKNOWN",
                         "detail": "no nozzle given (nozzle=, or a printer chosen in Form Studio)"})
    if proc in TRAPPING:
        med = MEDIUM[proc]
        trap = next((r for r in tb["rules"] if r.get("measure") == "trapped_voids"), {})
        hole = trap.get("hole_d")
        skin = float(spec.get("skin") or 0.0)
        if built is not None and built.get("trapped_voids") is not None:
            n = int(built["trapped_voids"])
            rows.append({"id": "lattice.trapped", "title": f"No closed space that holds {med}", "value": n, "limit": 0,
                         "status": "PASS" if n == 0 else "FAIL", "evidence": "computed (closed voids of the built solid)",
                         "detail": "" if n == 0 else f"{n} closed void(s): the skin seals the lattice's open space, so "
                                                     f"the {med} cannot leave. Cut escape holes through the skin"
                                                     + (f" (at least {hole:g} mm, {trap.get('hole_quote') or ''})" if hole else "") + "."})
        else:
            rows.append({"id": "lattice.trapped", "title": f"No closed space that holds {med}",
                         "status": "WARN" if skin > 0 else "PASS", "evidence": "computed (from the specification; the "
                                                                              "built solid is counted once it is built)",
                         "detail": (f"a closed skin seals the lattice's open space: {med} stays inside unless escape "
                                    f"holes are cut" if skin > 0 else "no skin: the lattice is open to the outside")})
        if hole and feats.get("pore_mm") is not None:
            rows.append({"id": "lattice.pore", "title": f"Pores large enough for the {med} to leave",
                         "value_mm": round(feats["pore_mm"], 3), "limit_mm": hole,
                         "status": "PASS" if feats["pore_mm"] >= hole else "WARN",
                         "evidence": "computed (largest sphere in the open space) against the table's escape hole",
                         "quote": trap.get("hole_quote")})
        if feats.get("channels") == 2:
            rows.append({"id": "lattice.channels", "title": "Two separate channel systems", "status": "INFO",
                         "detail": f"a sheet TPMS divides the space into two channel systems that never meet: each "
                                   f"needs its own way out for the {med}"})
    order = {"FAIL": 0, "WARN": 1, "UNKNOWN": 2, "PASS": 3, "INFO": 4}
    worst = min((r["status"] for r in rows), key=lambda s: order[s], default="PASS")
    return {"process": proc, "label": tb["process"].get("label"), "machine": tb["process"].get("machine_note"),
            "verdict": worst if worst != "INFO" else "PASS", "rows": rows}


def properties(spec: dict, material=None, process: str | None = None, nozzle: float | None = None,
               verify: bool = False, built: dict | None = None) -> dict:
    """Relative density, stiffness and strength by the scaling law, printability; with verify=True one cell by
    finite elements beside the estimate."""
    dens = _density(spec)
    feats = _features(spec)
    cls, basis = cell_class(spec)
    rho = dens["value"]
    g = spec.get("grading")
    ga = gibson_ashby(rho, cls)
    mat = material_numbers(material)
    stiff = {"E_rel": ga["E_rel"], "law": f"E* / Es = {ga['C']:.4g} rho^{ga['n']:g}", "class": cls, "class_basis": basis,
             "evidence": EVIDENCE_LAW, "source": ga["source"],
             "direction": "along a cell axis" if cls == "octet" else "order of magnitude; the law has no direction"}
    strength = {"rel": ga["strength_rel"], "law": f"sigma* / sigma_ys = {ga['Cs']:.4g} rho^{ga['m']:g}",
                "evidence": EVIDENCE_LAW, "source": ga["source"]}
    if mat and mat.get("E_MPa"):
        stiff.update(E_MPa=ga["E_rel"] * mat["E_MPa"], Es_MPa=mat["E_MPa"], Es_source=mat["E_source"])
    if mat and mat.get("yield_MPa"):
        strength.update(MPa=ga["strength_rel"] * mat["yield_MPa"], yield_MPa=mat["yield_MPa"], yield_source=mat["yield_source"])
    out = {"spec": spec, "label": C.LABEL[spec["kind"]] + (f", {spec['form']}" if C.is_tpms(spec["kind"]) else ""),
           "relative_density": dens, "features": feats, "stiffness": stiff, "strength": strength, "material": mat,
           "printability": printability(spec, feats, process, nozzle, built)}
    if g:
        lo, hi = (gibson_ashby(d, cls) for d in g["density"])
        out["graded"] = {"mode": g["mode"], "density": g["density"], "E_rel": [lo["E_rel"], hi["E_rel"]],
                         "note": "the numbers above are at the middle of the range; the built solid's mean density is "
                                 "measured"}
    if built:
        out["built"] = {k: built.get(k) for k in ("output", "representation", "relative_density_measured", "cells", "struts",
                                                  "triangles", "faces", "lattice_facets", "deviation", "trapped_voids",
                                                  "volume_mm3", "volume_before_mm3", "core_volume_mm3", "seconds",
                                                  "grid_mm", "grid_note", "strut_d_mm", "fragments_removed", "level", "level_meshed", "level_note") if built.get(k) is not None}
        out["built"]["evidence"] = EVIDENCE_BUILT
    if verify:
        from . import homog
        nu = (mat or {}).get("poisson") or 0.3
        v = homog.verify(spec, ga["E_rel"], nu)
        v["poisson"] = nu
        v["poisson_from"] = "the material" if (mat or {}).get("poisson") else "assumed 0.3"
        out["verification"] = v
    out["headline"] = _headline(out)
    return out


def _headline(r: dict) -> str:
    s = (f"{r['label']}, {r['spec']['cell']:g} mm cell: relative density {r['relative_density']['value']:.3f} (computed); "
         f"E about {r['stiffness']['E_rel']:.3g} of the solid's (scaling law)")
    if r["stiffness"].get("E_MPa") is not None:
        s += f", {r['stiffness']['E_MPa']:.4g} MPa"
    v = r.get("verification") or {}
    if v.get("available"):
        s += f"; one cell by FE: {v['E_rel_fe']:.3g} (the law is {v['difference'] * 100:+.0f} % against it)"
    b = r.get("built")
    if b:
        s += f"; built as {b['output'] if b['output'] != 'brep' else 'B-rep'}, measured density {b['relative_density_measured']:.3f}"
    pr = r["printability"]
    if pr.get("process"):
        s += f"; {pr['process'].upper()}: {pr['verdict']}"
    return s + "."


# ── the block in the design's source ─────────────────────────────────────────────────────────────────────────────

TEMPLATE = '''
{start}
from form.lattice import geom as _form_lattice_geom
from form.recipes.base import Feature as _FormLatticeFeature, Stage as _FormLatticeStage
_FORM_LATTICE = {spec}


def _form_lattice(cls):
    build = cls.build

    def body(self, v):
        return list(build(self, v))[-1].shape

    def with_lattice(self, v):
        stages = list(build(self, v))
        stages.append(_FormLatticeStage("lattice", _form_lattice_geom.fill(stages[-1].shape, _FORM_LATTICE)))
        return stages
    cls.build = with_lattice
    cls._form_lattice = _FORM_LATTICE
    cls._form_lattice_base = body
    cls.features = [f for f in cls.features if f.id != "lattice"] + [_FormLatticeFeature("lattice", {label!r}, "structure")]
    if _FORM_LATTICE.get("output") == "mesh":
        cls.mesh = True                       # facets: no STEP, no B-rep checks
    return cls


{cls} = _form_lattice({cls})
{end}
'''


def split(source: str) -> tuple[str, dict | None]:
    """(the source without the lattice block, the specification it holds or None)."""
    i = source.find(START)
    if i < 0:
        return source, None
    j = source.find(END, i)
    block = source[i:j if j >= 0 else len(source)]
    m = re.search(r"^_FORM_LATTICE = (.*)$", block, re.M)
    spec = ast.literal_eval(m.group(1)) if m else None
    rest = source[:i].rstrip() + "\n" + (source[j + len(END):].lstrip("\n") if j >= 0 else "")
    return rest.rstrip() + "\n", spec


def join(source: str, spec: dict | None) -> str:
    from ..engrave import design_class
    base, _old = split(source)
    if not spec:
        return base
    label = "Lattice infill: " + C.LABEL[spec["kind"]]
    return base.rstrip() + "\n" + TEMPLATE.format(start=START, end=END, cls=design_class(base), spec=repr(spec), label=label)


def current(st, p: dict) -> dict | None:
    """The lattice the head revision carries, or None."""
    try:
        from ..engrave import _python_source
        return split(_python_source(st, p))[1]
    except Exception:                                   # noqa: BLE001 - a recipe or OpenSCAD design carries none
        return None


def _dir(st, p: dict):
    return st.dir(p["id"]) / "artifacts" / "lattice"


def _key(st, p: dict, extra) -> str:
    from ..studio import H
    return H("lattice", VERSION, st.keys(p)["geometry"], extra)


def _kernel(st, p: dict, op: str, **kw) -> dict:
    r = st.rev(p)
    out = st._k(op, timeout=900, key=st.keys(p)["geometry"], recipe_id=st.rid(p), values=r["values"], p=p, **kw)
    if out.get("error"):
        raise LatticeError(out["error"], out.get("hint", ""), out.get("params"))
    return out


def _nozzle(st, p: dict, process: str | None, nozzle: float | None):
    if nozzle is not None or (process or "").lower() != "fdm":
        return nozzle
    try:
        s = st.slicer_info(p=p)
        return float(s["nozzle_mm"]) if s.get("available") and s.get("nozzle_mm") else None
    except Exception:                                   # noqa: BLE001 - no printer chosen: the row says so
        return None


def read(st, p: dict, material=None, process: str | None = None, nozzle: float | None = None,
         verify: bool = False) -> dict:
    """The lattice of the head revision with its numbers: the specification, the build's report (from the kernel),
    density, stiffness, printability. Stored under a key of the geometry and what was asked."""
    spec = current(st, p)
    if not spec:
        return {"state": "never", "project": p["id"],
                "why": "This design carries no lattice.", "next": f"lattice_fill(project='{p['id']}', kind='gyroid', cell=8, density=0.2, skin=1.2)"}
    material = material or p.get("material")
    k = _key(st, p, [material if isinstance(material, (str, dict)) else None, process, nozzle, bool(verify)])
    f = _dir(st, p) / f"{k}.json"
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass
    built = _kernel(st, p, "lattice_report")["report"]
    try:
        out = properties(spec, material, process, _nozzle(st, p, process, nozzle), verify, built)
    except Exception as e:                              # noqa: BLE001 - a material the library has no E for
        from ..studio import StudioError
        if not isinstance(e, StudioError):
            raise
        out = properties(spec, None, process, _nozzle(st, p, process, nozzle), verify, built)
        out["material_note"] = str(e)
    out.update(state="current", project=p["id"], rev=p["head"], key=k)
    f.parent.mkdir(parents=True, exist_ok=True)
    from .. import fsutil
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    fsutil.replace(tmp, f)
    (_dir(st, p) / "last.json").write_text(json.dumps({"rev": p["head"], "key": k, "headline": out["headline"],
                                                         "geometry": st.keys(p)["geometry"]}), encoding="utf-8")
    return out


def apply(st, p: dict, spec: dict, expect_head: int | None = None, origin: str = "agent", material=None,
          process: str | None = None, nozzle: float | None = None, verify: bool = False) -> dict:
    """Put the lattice in the design: the output (B-rep or mesh) is decided in the kernel on the body, written into
    the specification, and the design is rebuilt as a new revision. Returns read() of the new head."""
    from ..engrave import _python_source
    src = _python_source(st, p)
    from ..studio import StudioError
    asked = spec.get("output") or "auto"
    plan = _kernel(st, p, "lattice_plan", spec=spec)
    spec = {**spec, "output": plan["output"]}
    note = f"Lattice infill: {C.LABEL[spec['kind']]}, {spec['cell']:g} mm cell" + (f", {spec['skin']:g} mm skin" if spec.get("skin") else "")
    try:
        p = st.update_design(p, join(src, spec), note=note, origin=origin, expect_head=expect_head)
    except StudioError as e:
        # OCCT sometimes makes an invalid solid of a faceted surface that touches itself (a Neovius sheet does):
        # when the output was Form Studio's choice, the mesh route is taken instead, and the plan says so
        if not (asked == "auto" and spec["output"] == "brep" and "invalid solid" in str(e)):
            raise
        spec = {**spec, "output": "mesh"}
        plan = {**plan, "output": "mesh", "why": "the B-rep was tried and OCCT made an invalid solid of it, so the "
                                                  "lattice is a mesh body (" + plan["why"] + ")"}
        p = st.update_design(st.load(p["id"]), join(src, spec), note=note, origin=origin, expect_head=expect_head)
    out = read(st, p, material, process, nozzle, verify)
    out["plan"] = plan
    out["head"] = p["head"]
    return out


def remove(st, p: dict, expect_head: int | None = None, origin: str = "agent") -> dict:
    from ..engrave import _python_source
    src = _python_source(st, p)
    base, spec = split(src)
    if not spec:
        raise LatticeError("This design carries no lattice.")
    p = st.update_design(p, base, note="Removed the lattice infill", origin=origin, expect_head=expect_head)
    return {"head": p["head"], "removed": spec}


__all__ = ["LatticeError", "LAWS", "CLASS", "normalise", "stress_grid", "grid_from_points", "gibson_ashby",
           "cell_class", "properties", "printability", "material_numbers", "split", "join", "current", "read", "apply",
           "remove", "EVIDENCE_CELL", "EVIDENCE_LAW", "EVIDENCE_BUILT"]
