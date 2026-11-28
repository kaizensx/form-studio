"""The test plan and the results report: what to measure on the made part, and what was measured.

The test plan is written from what the design claims, nothing else:

    requirement   each assertion of the brief's contract (form/contract.py): the size, the bores, the bolt circle
    fit           every fit the design declares: an ISO 286 hole made by hand (form/handfeat.py), an ISO 286 pair
                  written in the code (fits.iso_fit), the fit model of a design with a mating part (form/fit.py),
                  and each Mate of an assembly with its designed clearance
    dimension     every critical dimension: a parameter of the brief or of an interface (group brief or interface,
                  or a feature whose role is interface), one that is measured or specified, and the overall size
    load          each load of a strength study (p["strength"], wave D) at the load the study defines, with the
                  study's converged largest displacement and its stated error as the prediction
    inspection    a visual check against the four-view sheet

Each test says what to measure, with which instrument (chosen so its resolution is a tenth of the tolerance band or
finer), the limits and where they come from, how many readings, and when it passes. A critical dimension takes its
limits from the drawing (form/drawing) where it states them: an ISO 286 fit on the size, else the drawing's ISO 2768-1
class; a dimension neither the design nor the drawing tolerances gets ISO 2768-1 class m, and says so. A claim with no
physical test (a face count) is listed as not tested, with why. The plan is keyed by the revision's geometry, values,
provenance, contract, drawing spec and strength studies with their current results.

Results are recorded with record_physical_result(kind="test", test=<id>, values=[...] or result="pass"|"fail",
instrument=...), always with provenance "measured": only numbers a person read off the part. The record keeps the
limits it was judged against, so it stands on its own.

The results report is one document for the head revision: the design and its hashes, every check and study with its
evidence class and what is stated about its error, the physical results against the plan, the open items and a
verdict. The verdict is PASS only when every required test has a measured result that passes and nothing is open
(no unproven requirement, no stale or failed study, no check that is not current). Anything unchecked makes it
NOT A PASS, and a measured failure makes it FAIL. The physical section holds only numbers a person measured.

Outputs (PDF in Geist, form/pdfdoc.py; Markdown; the checklist as CSV) are written under
<project>/artifacts/reports/<key>/ and are Bench documents ("testplan", "report").

    form testplan <project> [--out DIR]                    the plan, its PDF, Markdown and checklist
    form testplan record <project> <test> 8.01 8.02 ...    one result; --result pass|fail, --instrument, --by
    form testplan record <project> --csv filled.csv        every filled row of the checklist
    form report <project> [--out DIR]                      the results report
"""
from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import math
import re
import time
from pathlib import Path

VERSION = 1
GROUPS = ("requirement", "fit", "dimension", "load", "inspection")
GROUP_LABEL = {"requirement": "Requirements of the brief", "fit": "Fits", "dimension": "Critical dimensions",
               "load": "Loads", "inspection": "Inspection"}
COUNT_WORD = {"requirement": ("requirement", "requirements"), "fit": ("fit", "fits"),
              "dimension": ("critical dimension", "critical dimensions"), "load": ("load", "loads"),
              "inspection": ("inspection", "inspections")}
VERDICTS = ("PASS", "NOT A PASS", "FAIL")
RESULT_WORDS = {"pass": "pass", "good": "pass", "fail": "fail", "too_tight": "fail", "too_loose": "fail"}
PLAN_FILES = ("TEST_PLAN.pdf", "TEST_PLAN.md", "TEST_CHECKLIST.csv", "test_plan.json")
REPORT_FILES = ("RESULTS_REPORT.pdf", "RESULTS_REPORT.md", "results.json")

# ISO 2768-1 general tolerances, class m (medium), linear dimensions: (over, up to, ± mm)
ISO2768_M = ((0.5, 3, 0.1), (3, 6, 0.1), (6, 30, 0.2), (30, 120, 0.3), (120, 400, 0.5), (400, 1000, 0.8),
             (1000, 2000, 1.2), (2000, 4000, 2.0))
GENERAL = "ISO 2768-1 class m (general tolerance: the design states none for this dimension)"
ANGLE_TOL = 1.0              # ISO 2768-1 m, angles whose shorter leg is up to 10 mm; longer legs are tighter
TEN_TO_ONE = "the instrument resolves a tenth of the tolerance band or finer (the 10:1 rule)"

# instruments: (name, resolution, largest size it measures, how)
CALIPERS = ("Digital calipers", 0.01, 150.0)
CALIPERS_L = ("Digital calipers, 300 mm", 0.01, 300.0)
MICROMETER = ("Outside micrometer", 0.001, 100.0)
BORE_GAUGE = ("Bore gauge or a set of pin gauges", 0.001, 100.0)
RULE_STEEL = ("Steel rule", 0.5, 1000.0)
TAPE = ("Tape measure", 1.0, 5000.0)
PROTRACTOR = ("Digital protractor", 0.1, 360.0)


def _err(msg: str, hint: str = "", status: int = 400):
    from .studio import StudioError
    return StudioError(msg, hint, status=status)


def H(*a) -> str:
    from .studio import H as _h
    return _h(*a)


def fmt(x, unit: str = "") -> str:
    if x is None:
        return ""
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)
    s = f"{x:.3f}".rstrip("0").rstrip(".") if isinstance(x, (int, float)) else str(x)
    return f"{s} {unit}".strip() if unit else s


def general_tol(d: float) -> float:
    d = abs(float(d))
    for lo, hi, t in ISO2768_M:
        if lo < d <= hi:
            return t
    return ISO2768_M[0][2] if d <= 0.5 else ISO2768_M[-1][2]


def instrument(nominal: float, lo: float | None, hi: float | None, inside: bool = False, unit: str = "mm") -> dict:
    """The instrument a reading needs: the coarsest whose resolution is a tenth of the band or finer."""
    if unit in ("deg", "°"):
        name, res = PROTRACTOR[0], PROTRACTOR[1]
        band = (hi - lo) if lo is not None and hi is not None else None
        ok = band is None or res <= band / 10 + 1e-12
        return {"name": name, "resolution": res, "unit": "°", "meets_10_to_1": ok,
                "method": "Against the two faces that form the angle; two readings, one at each end of the edge."}
    band = (hi - lo) if lo is not None and hi is not None else None
    size = abs(nominal)
    if inside:
        options = [CALIPERS, BORE_GAUGE] if size <= 150 else [CALIPERS_L, RULE_STEEL]
    else:
        options = [CALIPERS, MICROMETER] if size <= 150 else [CALIPERS_L] if size <= 300 else [RULE_STEEL, TAPE]
    if size > 300 and band is not None:
        options = sorted(options, key=lambda o: -o[1])
    pick = None
    for o in options:
        if o[2] >= size and (band is None or o[1] <= band / 10 + 1e-12):
            pick = o
            break
    ok = pick is not None
    if pick is None:                              # nothing in the list meets 10:1: the finest that reaches the size
        reach = [o for o in options if o[2] >= size] or options
        pick = min(reach, key=lambda o: o[1])
    how = ("Inside jaws or the gauge across the widest point; turn 90° and repeat" if inside
           else "Square to the faces, outside jaws; at different places along the feature")
    return {"name": pick[0], "resolution": pick[1], "unit": "mm", "meets_10_to_1": ok, "method": how}


def _decimals(lo, hi) -> int | None:
    """Decimals that show the band: three for a band under 0.1 mm (ISO 286), else as written."""
    if lo is None or hi is None or isinstance(lo, int) and isinstance(hi, int):
        return None
    return 3 if 0 < (hi - lo) < 0.1 else None


def _test(tid, group, title, claim, source, *, nominal=None, lo=None, hi=None, unit="mm", samples=3, inside=False,
          input="number", instrument_=None, method="", criterion="", required=True, feature="", model=None,
          tol_text="") -> dict:
    t = {"id": tid, "group": group, "title": title, "claim": claim, "source": source, "feature": feature,
         "nominal": nominal, "lo": lo, "hi": hi, "unit": unit, "input": input, "samples": int(samples),
         "required": bool(required), "model": model or {}}
    if input == "number":
        ins = instrument_ or instrument(nominal or 0.0, lo, hi, inside, unit)
        t["instrument"] = ins["name"]
        t["resolution"] = ins.get("resolution")
        t["method"] = method or (ins.get("method", "") + f"; {samples} readings, each recorded.")
        if not ins.get("meets_10_to_1", True):
            t["instrument_note"] = ("The band is tighter than a tenth of this instrument's resolution: use a finer "
                                    "instrument or a coordinate measuring machine.")
        nd = _decimals(lo, hi)
        f = (lambda x: f"{x:.{nd}f}") if nd is not None else fmt
        if lo is not None and hi is not None:
            t["limits"] = (f"{f(lo)} {unit}" if lo == hi else f"{f(lo)} to {f(hi)} {unit}").strip()
        elif lo is not None:
            t["limits"] = f"at least {f(lo)} {unit}".strip()
        elif hi is not None:
            t["limits"] = f"at most {f(hi)} {unit}".strip()
        else:
            t["limits"] = "recorded, no limit"
        t["tolerance"] = tol_text
        if criterion:
            t["criterion"] = criterion
        elif lo is not None and hi is not None:
            t["criterion"] = f"Exactly {t['limits']}." if lo == hi else f"Every reading from {f(lo)} to {f(hi)} {unit}.".replace("  ", " ")
        elif lo is not None or hi is not None:
            t["criterion"] = f"Every reading {t['limits']}."
        else:
            t["criterion"] = "Recorded beside the prediction; no pass or fail."
    else:
        t["instrument"] = (instrument_ or {}).get("name", "By eye and by hand")
        t["method"] = method
        t["limits"] = "pass or fail"
        t["tolerance"] = tol_text
        t["criterion"] = criterion
    return t


# ---- what the design claims ----------------------------------------------------------------------------------------
def _contract_tests(st, p, rev) -> tuple[list, list]:
    from . import contract
    c = contract.of(p)
    if not c:
        return [], []
    sheet = contract.prove(st, p, compute=False)
    by_id = {r.get("id"): r for r in (sheet or {}).get("rows") or []}
    out, skipped = [], []

    def model(a):
        r = by_id.get(a.get("id"))
        if not r:
            return {"status": "not measured on the model yet", "evidence": ""}
        return {"status": r["status"], "value": r.get("measured_text") or r.get("measured"), "evidence": r.get("evidence", "")}

    for a in c.get("assertions") or []:
        aid, kind, tol = a.get("id", ""), a["kind"], float(a.get("tol") or contract.DEFAULT_TOL)
        src = f"brief requirement {aid}: “{a.get('text', '')}”" + (" (tolerance assumed)" if "assumed" in
                                                                   str((a.get("provenance") or {}).get("tolerance", "")) else "")
        base = f"req.{aid}"
        feat = a.get("feature") or a.get("of") or ""
        if kind == "bbox":
            order = sorted(a["size"], reverse=True) if a.get("any_order") else a["size"]
            names = ("largest", "middle", "smallest") if a.get("any_order") else ("X", "Y", "Z")
            for ax, nm, v in zip("xyz", names, order):
                out.append(_test(f"{base}.{ax}", "requirement", f"Overall size, {nm}" if a.get("any_order") else f"Overall size {nm}",
                                 a.get("text", ""), src, nominal=v, lo=v - tol, hi=v + tol, tol_text=f"±{fmt(tol)} mm",
                                 feature=feat, model=model(a)))
        elif kind == "extent":
            v = a["mm"]
            out.append(_test(base, "requirement", f"Extent{(' along ' + a['axis'].upper()) if a.get('axis') else ''}",
                             a.get("text", ""), src, nominal=v, lo=v - tol, hi=v + tol, tol_text=f"±{fmt(tol)} mm",
                             feature=feat, model=model(a)))
        elif kind in ("cylinder", "holes"):
            d = a.get("d")
            inside = kind == "holes" or a.get("of") in ("bore", "any")
            if a.get("count"):
                n = int(a["count"])
                out.append(_test(base + ".n", "requirement", f"Count of Ø{fmt(d)} {('holes' if inside else 'bosses')}", a.get("text", ""),
                                 src, nominal=n, lo=n, hi=n, unit="", samples=1, tol_text="exact",
                                 instrument_={"name": "Count", "resolution": 1, "meets_10_to_1": True},
                                 method="Count them on the part.", feature=feat, model=model(a)))
            out.append(_test(base, "requirement", f"Ø{fmt(d)} {'bore' if inside else 'boss'}", a.get("text", ""), src,
                             nominal=d, lo=d - tol, hi=d + tol, inside=inside, tol_text=f"±{fmt(tol)} mm", feature=feat,
                             model=model(a)))
        elif kind == "bolt_circle":
            n, hd, cd = int(a["count"]), a["hole_d"], a["circle_d"]
            out.append(_test(base + ".n", "requirement", f"Holes on the Ø{fmt(cd)} circle", a.get("text", ""), src,
                             nominal=n, lo=n, hi=n, unit="", samples=1, tol_text="exact",
                             instrument_={"name": "Count", "resolution": 1, "meets_10_to_1": True},
                             method="Count them on the part.", feature=feat, model=model(a)))
            out.append(_test(base + ".d", "requirement", f"Ø{fmt(hd)} holes of the bolt circle", a.get("text", ""), src,
                             nominal=hd, lo=hd - tol, hi=hd + tol, inside=True, tol_text=f"±{fmt(tol)} mm",
                             method="Inside jaws or pin gauges; one reading in each hole.", samples=min(n, 6),
                             feature=feat, model=model(a)))
            out.append(_test(base + ".pcd", "requirement", f"Bolt circle Ø{fmt(cd)}", a.get("text", ""), src,
                             nominal=cd, lo=cd - tol, hi=cd + tol, tol_text=f"±{fmt(tol)} mm",
                             method="Across two opposite holes: outside edge to outside edge minus one hole Ø (or "
                                    "centre to centre with pins); one reading per pair of holes.",
                             samples=max(1, n // 2), feature=feat, model=model(a)))
        elif kind == "pattern":
            n, pitch, hd = int(a["count"]), a["pitch"], a["hole_d"]
            out.append(_test(base + ".n", "requirement", f"Holes in the pattern", a.get("text", ""), src,
                             nominal=n, lo=n, hi=n, unit="", samples=1, tol_text="exact",
                             instrument_={"name": "Count", "resolution": 1, "meets_10_to_1": True},
                             method="Count them on the part.", feature=feat, model=model(a)))
            out.append(_test(base + ".pitch", "requirement", f"Pitch {fmt(pitch)} mm", a.get("text", ""), src,
                             nominal=pitch, lo=pitch - tol, hi=pitch + tol, tol_text=f"±{fmt(tol)} mm",
                             method="Centre to centre of neighbouring holes (edge to edge plus one Ø); one reading per gap.",
                             samples=max(1, n - 1), feature=feat, model=model(a)))
            out.append(_test(base + ".d", "requirement", f"Ø{fmt(hd)} holes of the pattern", a.get("text", ""), src,
                             nominal=hd, lo=hd - tol, hi=hd + tol, inside=True, tol_text=f"±{fmt(tol)} mm",
                             samples=min(n, 6), feature=feat, model=model(a)))
        elif kind == "min_wall":
            t = a["t"]
            out.append(_test(base, "requirement", f"Thinnest wall at least {fmt(t)} mm", a.get("text", ""), src,
                             nominal=t, lo=t - tol, hi=None, tol_text=f"-{fmt(tol)} mm",
                             method="Calipers or a wall-thickness gauge at the thinnest place the four-view sheet shows; "
                                    "three places.", feature=feat, model=model(a)))
        elif kind == "thread":
            mj, pitch = a["major"], a.get("pitch")
            name = f"M{fmt(mj)}" + (f" × {fmt(pitch)}" if pitch else "")
            out.append(_test(base, "requirement", f"Thread {name}", a.get("text", ""), src, input="result", samples=1,
                             instrument_={"name": f"{name} thread gauge (go / no-go) and a pitch gauge"},
                             method="The go gauge (or a known good bolt) runs the full length by hand; the no-go gauge "
                                    "does not enter more than two turns; the pitch gauge sits without light.",
                             criterion="Go enters the full length, no-go does not, pitch gauge matches.",
                             feature=feat, model=model(a)))
        elif kind == "volume":
            op = a.get("op", "max")
            v = a["mm3"]
            out.append(_test(base, "requirement", f"Volume {('at most' if op == 'max' else 'at least' if op == 'min' else '')} {fmt(v)} mm³".replace("  ", " "),
                             a.get("text", ""), src, nominal=v, lo=v if op == "min" else (v - tol if op == "eq" else None),
                             hi=v if op == "max" else (v + tol if op == "eq" else None), unit="mm³", samples=1,
                             instrument_={"name": "Scale (0.01 g) and the material's density, or water displacement",
                                          "resolution": None, "meets_10_to_1": True},
                             method="Weigh the part and divide by the material's density, or measure the water it "
                                    "displaces; say which.", feature=feat, model=model(a)))
        elif kind == "part_count":
            n = int(a["count"])
            out.append(_test(base, "requirement", f"{n} parts", a.get("text", ""), src, nominal=n, lo=n, hi=n, unit="",
                             samples=1, tol_text="exact", instrument_={"name": "Count", "resolution": 1, "meets_10_to_1": True},
                             method="Count the separate parts.", feature=feat, model=model(a)))
        else:                                       # face_count and anything only the model has
            skipped.append({"what": a.get("text", kind), "why": "a property of the CAD model with no physical "
                            "measurement; it is proved on the model (the proof sheet), not on the part", "source": src})
    return out, skipped


_ISO_DOC = re.compile(r"ISO 286.*?:\s*([A-Z]{1,2}\d{1,2})\s+on\s+Ø\s*([\d.]+)")


def _source_text(st, p) -> str:
    from .recipes import is_source, source_path
    rid = st.rid(p)
    try:
        if is_source(rid):
            return source_path(st.sources, rid).read_text(encoding="utf-8")
    except OSError:
        pass
    return ""


def iso_fits_in_source(text: str) -> list:
    """Every fits.iso_fit("H7/g6", 8) with literal arguments in a design's code: [(code, nominal, line)]."""
    out = []
    try:
        tree = ast.parse(text or "")
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if name != "iso_fit" or len(n.args) < 2:
                continue
            a, b = n.args[0], n.args[1]
            if isinstance(a, ast.Constant) and isinstance(a.value, str) and isinstance(b, ast.Constant) \
                    and isinstance(b.value, (int, float)):
                out.append((a.value.replace(" ", ""), float(b.value), n.lineno))
    return out


MATE_RULE = {
    "pin": "The pin turns and slides by hand over its whole engagement, without binding.",
    "slip": "The parts slide by hand over the whole travel, without binding.",
    "press": "Assembly needs force (a press or a mallet) and the parts then hold without other locking.",
    "snap": "The snap engages with a click and holds; it releases as designed without cracking.",
    "thread": "The threads run together by hand over the full length.",
    "contact": "The faces seat fully: the parts do not rock on each other.",
    "ratchet": "The pawl locks the wheel in the locking direction and lets it turn the other way.",
}


def _fit_tests(st, p, rev, recipe, used_keys: set) -> list:
    from .craft import fits
    out = []
    # ISO 286 holes made by picking (their diameter parameter says the code and the nominal)
    for sp in recipe.params:
        m = _ISO_DOC.search(sp.doc or "")
        if not m:
            continue
        code, nominal = m.group(1), float(m.group(2))
        lm = re.fullmatch(r"([A-Z]{1,2})(\d{1,2})", code)
        try:
            lo, hi = fits.hole_limits(lm.group(1), int(lm.group(2)), nominal)
        except Exception as e:                       # noqa: BLE001 - a code the tables do not hold: said, not guessed
            out.append(_test(f"fit.{sp.key}", "fit", f"{sp.label}: {code} on Ø{fmt(nominal)}", sp.doc, f"parameter {sp.key}",
                             input="result", criterion=f"Not tested: {e}", required=False, feature=sp.feature))
            continue
        used_keys.add(sp.key)
        band_um = round((hi - lo) * 1000)
        out.append(_test(f"fit.{sp.key}", "fit", f"Ø{fmt(nominal)} {code} hole", f"{sp.label} is an ISO 286 {code} hole on Ø{fmt(nominal)}",
                         f"{fits.SOURCE}: {code} on Ø{fmt(nominal)} (specified)", nominal=nominal, lo=round(lo, 4),
                         hi=round(hi, 4), inside=True, tol_text=f"{code}: {band_um} µm band", feature=sp.feature,
                         instrument_={"name": f"Plug gauge Ø{fmt(nominal)} {code} (go / no-go), or a bore gauge",
                                      "resolution": 0.001, "meets_10_to_1": True,
                                      "method": "Bore gauge across the bore at the top, middle and bottom, turned 90° at each; "
                                                "or the go end enters and the no-go end does not (then record the limit it proves)"},
                         model={"status": "modelled at mid-tolerance", "value": fmt(rev["values"].get(sp.key), "mm"),
                                "evidence": "specified"}))
    # ISO 286 pairs written in the code
    for code, nominal, line in iso_fits_in_source(_source_text(st, p)):
        try:
            f = fits.iso_fit(code, nominal)
        except Exception:                            # noqa: BLE001
            continue
        tid = f"fit.iso.{code.replace('/', '-')}.{fmt(nominal)}"
        if any(t["id"] == tid + ".hole" for t in out):
            continue
        src = f"{fits.SOURCE}: {code} on Ø{fmt(nominal)}, design code line {line} (specified)"
        clr = f"clearance {fmt(f['clearance'][0])} to {fmt(f['clearance'][1])} mm ({f['kind']})"
        out.append(_test(tid + ".hole", "fit", f"Ø{fmt(nominal)} {code}: hole", f"{code} {f['kind']} fit, {clr}", src,
                         nominal=nominal, lo=f["hole"][0], hi=f["hole"][1], inside=True,
                         tol_text=f"{code.split('/')[0]}: {round((f['hole'][1] - f['hole'][0]) * 1000)} µm band",
                         instrument_={"name": f"Plug gauge Ø{fmt(nominal)} {code.split('/')[0]} (go / no-go), or a bore gauge",
                                      "resolution": 0.001, "meets_10_to_1": True,
                                      "method": "Bore gauge at the top, middle and bottom, turned 90° at each"}))
        out.append(_test(tid + ".shaft", "fit", f"Ø{fmt(nominal)} {code}: shaft", f"{code} {f['kind']} fit, {clr}", src,
                         nominal=nominal, lo=f["shaft"][0], hi=f["shaft"][1],
                         tol_text=f"{code.split('/')[1]}: {round((f['shaft'][1] - f['shaft'][0]) * 1000)} µm band",
                         instrument_={"name": "Outside micrometer (0.001 mm) or a ring gauge", "resolution": 0.001,
                                      "meets_10_to_1": True, "method": "Micrometer at both ends and the middle, turned 90° at each"}))
    # the fit model of a design with a mating part
    try:
        fa = st.fit(p)
    except Exception:                                # noqa: BLE001
        fa = None
    if fa:
        lo, hi = fa["window"]
        used_keys.update({fa.get("cavity_key") or "", fa.get("mating_key") or ""})
        out.append(_test("fit.model", "fit", f"Fit: {fa['label']}", f"the gap lands in the {fmt(lo)} to {fmt(hi)} mm window",
                         "the design's fit window (form/fit.py); the gap is the cavity minus the mating part",
                         nominal=round((lo + hi) / 2, 4), lo=lo, hi=hi, inside=True, samples=3,
                         tol_text=f"window {fmt(lo)} to {fmt(hi)} mm",
                         method=f"Measure the cavity ({fa.get('cavity_key')}) with inside jaws and the mating part "
                                f"({fa.get('mating_label') or fa.get('mating_key')}) with outside jaws at the same place; "
                                "record cavity minus part, three places. Or record how it fits (good, too tight, too loose).",
                         model={"status": f"{round(fa['yield'] * 100)} % of prints within the window", "evidence": "modelled",
                                "value": f"expected gap {fmt(round(fa['expected_gap'], 3))} mm"}))
    # declared mates of an assembly
    try:
        spec = recipe.assembly(rev["values"]) if st._declares_assembly(recipe) else None
    except Exception:                                # noqa: BLE001
        spec = None
    for i, m in enumerate(getattr(spec, "mates", None) or []):
        lab = m.label or f"{m.a} in {m.b}"
        rule = MATE_RULE.get(m.kind, "The parts go together as designed.")
        if m.clearance is not None:
            rule += f" Designed clearance {fmt(m.clearance)} mm per side" + (" (an interference)" if m.clearance < 0 else "") + "."
        out.append(_test(f"fit.mate.{i + 1}", "fit", f"{m.kind.capitalize()} fit: {lab}", f"{m.a} and {m.b} join as a {m.kind} fit",
                         "the assembly's Mate declaration", input="result", samples=1,
                         instrument_={"name": "By hand" + (", feeler gauges for the gap" if (m.clearance or 0) > 0 else "")},
                         method="Assemble the two parts as the assembly notes say.", criterion=rule))
    return out


def critical_params(recipe, rev) -> list:
    """The parameters that are critical dimensions: of the brief or an interface, on an interface feature, or
    measured or specified (a number the design takes from the world). Lengths and angles only."""
    roles = {f.id: getattr(f, "role", "") for f in getattr(recipe, "features", None) or []}
    out = []
    for sp in recipe.params:
        if sp.unit not in ("mm", "deg", "°"):
            continue
        src = (rev["provenance"].get(sp.key) or {}).get("source", "assumed")
        if sp.group in ("brief", "interface") or roles.get(sp.feature) == "interface" or src in ("measured", "specified"):
            out.append(sp)
    return out


def drawing_spec(st, p, rev) -> dict:
    """What the drawing declares (form/drawing: the design's drawing() and what the person set), or {}."""
    try:
        from . import drawing as D
        return D.merged_spec(st, p, rev["n"])
    except Exception:                                # noqa: BLE001 - no drawing declared: the general rule applies
        return {}


def drawing_tolerance(sp, value: float, unit: str, spec: dict) -> dict | None:
    """A critical dimension's limits from the drawing: an ISO 286 fit stated on the size (at={"param": key}, or a
    cylinder of its feature), else the drawing's stated ISO 2768-1 class. None when the drawing states neither."""
    from .stack import _fit_for
    fit = _fit_for(sp.key, sp, value, spec) if unit == "mm" else None
    if fit:
        from . import iso286
        cls, scale = fit
        try:
            lim = iso286.limits(cls, value / scale)
        except iso286.FitError:
            lim = None
        if lim:
            lo, hi = lim["lower_um"] / 1000 * scale, lim["upper_um"] / 1000 * scale
            return {"lo": value + lo, "hi": value + hi, "text": f"{lim['class']}: {fmt(round(value + lo, 4))} to "
                    f"{fmt(round(value + hi, 4))} mm, ISO 286 stated on the drawing"
                    + (" (half: the parameter is a radius)" if scale != 1 else ""),
                    "source": "the drawing (" + lim["source"] + ")"}
    cls = spec.get("general")
    if cls and unit in ("mm", "°"):
        from .drawing import standards as STD
        try:
            tol = STD.general_angle(0.0, cls) if unit == "°" else STD.general_linear(abs(value), cls)
        except STD.StandardError:
            return None
        return {"lo": value - tol, "hi": value + tol, "text": f"±{fmt(tol)}{'°' if unit == '°' else ' mm'}, ISO 2768-1 {cls} "
                "stated on the drawing", "source": "the drawing's general tolerance"}
    return None


def _dimension_tests(st, p, rev, recipe, used_keys: set, has_bbox: bool) -> list:
    out = []
    spec = drawing_spec(st, p, rev)
    for sp in critical_params(recipe, rev):
        if sp.key in used_keys:
            continue
        v = float(rev["values"][sp.key])
        prov = rev["provenance"].get(sp.key) or {}
        world = sp.group == "brief"
        lab = sp.label.lower()
        inside = any(k in lab for k in ("inner", "inside", "opening", "hole", "slot", "gap", "bore", "pocket", "channel", "cavity"))
        if sp.unit in ("deg", "°"):
            t = ANGLE_TOL
            tt = f"±{fmt(t)}°, ISO 2768-1 m (shorter leg up to 10 mm)"
            unit = "°"
        else:
            t = general_tol(v)
            tt = f"±{fmt(t)} mm, ISO 2768-1 m"
            unit = "mm"
        lo, hi = round(v - t, 4), round(v + t, 4)
        dt = drawing_tolerance(sp, v, unit, spec)
        if dt:
            lo, hi, tt = round(dt["lo"], 4), round(dt["hi"], 4), dt["text"]
        claim = (f"{sp.label} is {fmt(v, unit)}" + (f": {sp.doc}" if sp.doc else ""))
        src = f"parameter {sp.key} ({sp.group}, {prov.get('source', 'assumed')})" + (f"; limits: {dt['source']}" if dt else "")
        if world:
            claim += (". This is a dimension of the object the part meets; measure that object and the part's "
                      "matching feature.")
        out.append(_test(f"dim.{sp.key}", "dimension", sp.label + (" (the part's matching feature)" if world else ""), claim, src,
                         nominal=v, lo=lo, hi=hi, unit=unit, inside=inside, tol_text=tt,
                         feature=sp.feature, model={"status": "as modelled", "value": fmt(v, unit), "evidence": "computed (B-rep)"}))
    if not has_bbox:
        try:
            bb = st.view(p).get("bbox")
        except Exception:                            # noqa: BLE001 - the plan still lists everything else
            bb = None
        if bb:
            size = [round(bb[1][i] - bb[0][i], 3) for i in range(3)]
            cls = spec.get("general")
            for ax, v in zip("XYZ", size):
                t = general_tol(v)
                tt = f"±{fmt(t)} mm, ISO 2768-1 m"
                if cls:
                    from .drawing import standards as STD
                    try:
                        t = STD.general_linear(v, cls)
                        tt = f"±{fmt(t)} mm, ISO 2768-1 {cls} stated on the drawing"
                    except STD.StandardError:
                        pass
                out.append(_test(f"dim.size.{ax.lower()}", "dimension", f"Overall size {ax}", f"the part is {fmt(v)} mm along {ax}",
                                 "the solid's bounding box (computed)", nominal=v, lo=round(v - t, 4), hi=round(v + t, 4),
                                 tol_text=tt, samples=2,
                                 model={"status": "as modelled", "value": fmt(v, "mm"), "evidence": "computed (B-rep)"}))
    return out


def _strength_defs(p) -> list:
    return [d for d in (p.get("strength") or {}).values() if isinstance(d, dict)]


def _strength_result(st, p, sid):
    try:
        from .fea import study as fea_study          # wave D, when it is installed
    except ImportError:
        return None
    try:
        return fea_study.result(st, p, sid, stale_ok=False).get("result")
    except Exception:                                # noqa: BLE001
        return None


def _load_tests(st, p) -> list:
    out = []
    for d in _strength_defs(p):
        if d.get("kind", "static") not in ("static", "thermal_stress"):
            continue
        res = _strength_result(st, p, d.get("id")) or {}
        disp = res.get("max_displacement_mm") if res.get("converged", True) else None
        derr = (res.get("discretisation_error") or {}).get("displacement")
        for i, ld in enumerate(d.get("loads") or []):
            t = ld.get("type")
            if t == "force":
                vec = ld.get("vector") or [0, 0, 0]
                mag = math.sqrt(sum(float(x) ** 2 for x in vec))
                what = f"{fmt(round(mag, 2))} N in direction ({', '.join(fmt(round(x / (mag or 1), 3)) for x in vec)})"
            elif t == "pressure":
                what = f"{fmt(ld.get('value'))} MPa on the picked faces"
            elif t == "preload":
                what = f"bolt preload {fmt(ld.get('force'))} N"
            else:
                continue                             # gravity: the part's own weight, not a test to set up
            pred = (f"Predicted largest displacement {fmt(round(disp, 4))} mm"
                    + (f" ± {100 * derr:.1f} %" if isinstance(derr, (int, float)) else "")
                    + f" (strength study {d.get('name') or d.get('id')}: {res.get('evidence', 'simulated (FEA)')})"
                    if disp is not None else
                    "No converged strength result for this revision: the deflection is recorded without a prediction")
            out.append(_test(f"load.{d.get('id')}.{i + 1}", "load", f"Load: {d.get('name') or d.get('label') or d.get('id')} #{i + 1}",
                             f"the part carries {what} held as the study holds it", f"strength study {d.get('id')} (defined loads)",
                             input="result", samples=1,
                             instrument_={"name": "Force gauge or calibrated weights; a dial indicator (0.01 mm) at the load point"},
                             method=(f"Hold the part at the faces the study fixes and apply {what} at the faces it loads; "
                                     "hold 60 s, release. Record the deflection under load and any permanent set. "
                                     + pred + "."),
                             criterion="No crack, no yielding, no permanent set after release. The design load only: no "
                                       "safety margin is tested and none is claimed.",
                             model={"status": res.get("headline") or "not solved for this revision",
                                    "evidence": res.get("evidence") or "simulated",
                                    **({"predicted_displacement_mm": round(disp, 6)} if disp is not None else {}),
                                    **({"displacement_error": derr} if disp is not None and derr is not None else {})}))
    return out


def plan_key(st, p) -> str:
    from . import contract
    rev = st.rev(p)
    return H("testplan", VERSION, st.keys(p)["geometry"], rev["values"], rev["provenance"], contract.fingerprint(contract.of(p)),
             _strength_defs(p), p.get("purpose"), p.get("fit"), drawing_spec(st, p, rev), _strength_keys(st, p))


def _strength_keys(st, p) -> list:
    """The current result of each strength study (the plan quotes its predicted deflection)."""
    try:
        from .fea import study as fea_study
    except ImportError:
        return []
    out = []
    for d in _strength_defs(p):
        try:
            s = fea_study.state(st, p, d.get("id"))
            out.append((d.get("id"), s.get("key") if s.get("state") == "current" else None))
        except Exception:                            # noqa: BLE001
            out.append((d.get("id"), None))
    return out


def plan(st, p) -> dict:
    """The test plan of the head revision (structured)."""
    rev, recipe = st.rev(p), st.recipe(p)
    req, skipped = _contract_tests(st, p, rev)
    used: set = set()
    fit = _fit_tests(st, p, rev, recipe, used)
    has_bbox = any(t["id"].endswith((".x", ".y", ".z")) and t["id"].startswith("req.") for t in req)
    dims = _dimension_tests(st, p, rev, recipe, used, has_bbox)
    loads = _load_tests(st, p)
    insp = [_test("inspect.visual", "inspection", "Visual inspection", "the part is whole and matches the design",
                  "the four-view sheet of this revision", input="result", samples=1,
                  instrument_={"name": "Eyes, good light, the four-view sheet"},
                  method="Compare the part with the four views: every feature present, no cracks, no warping, no "
                         "layer separation, no missing or extra material.",
                  criterion="Every feature present; no crack, warp or separation.")]
    tests = req + fit + dims + loads + insp
    seen, uniq = set(), []
    for t in tests:
        if t["id"] not in seen:
            seen.add(t["id"])
            uniq.append(t)
    keys = st.keys(p)
    return {"version": VERSION, "project": p["id"], "name": p["name"], "rev": rev["n"], "key": plan_key(st, p),
            "geometry": keys["geometry"], "purpose": p.get("purpose"), "tests": uniq, "not_tested": skipped,
            "counts": {g: sum(1 for t in uniq if t["group"] == g) for g in GROUPS},
            "required": sum(1 for t in uniq if t["required"]),
            "general_tolerance": GENERAL, "rule": TEN_TO_ONE,
            "note": "Written from what the design claims: its brief, fits, critical dimensions and strength studies. "
                    "Model values beside each test are computed or modelled, never physical results."}


# ---- results ---------------------------------------------------------------------------------------------------------
def judge(test: dict, rec: dict) -> str:
    """pass or fail of one recorded result against the limits it was recorded under."""
    lim = rec.get("limits") or {"lo": test.get("lo"), "hi": test.get("hi")}
    if rec.get("result"):
        return RESULT_WORDS.get(rec["result"], "fail")
    vals = rec.get("values") or []
    if not vals:
        return "fail"
    lo, hi = lim.get("lo"), lim.get("hi")
    ok = all((lo is None or v >= lo - 1e-9) and (hi is None or v <= hi + 1e-9) for v in vals)
    return "pass" if ok else "fail"


def clean_result(t: dict, body: dict) -> dict:
    """Check one result against its test before it is recorded. Returns the evidence fields."""
    out = {"test": t["id"], "title": t["title"], "unit": t.get("unit", ""), "source": "measured",
           "limits": {"lo": t.get("lo"), "hi": t.get("hi")}, "instrument": str(body.get("instrument") or "")[:200],
           "by": str(body.get("by") or "")[:120]}
    if body.get("values") not in (None, []) and body.get("result"):
        raise _err("Give the readings or a pass/fail result, not both.")
    if body.get("result"):
        r = str(body["result"]).strip().lower().replace(" ", "_")
        if r not in RESULT_WORDS:
            raise _err(f"Unknown result “{body['result']}”.", "pass or fail (a fit: good, too_tight or too_loose).")
        out["result"] = r
    else:
        if t["input"] != "number":
            raise _err(f"{t['title']} is a pass or fail test.", "Record result=\"pass\" or \"fail\" with what was seen in note.")
        vals = body.get("values")
        if not isinstance(vals, (list, tuple)) or not vals:
            raise _err("Give the readings: values=[...] in " + (t.get("unit") or "the test's unit") + ".",
                       f"The plan asks for {t['samples']} reading(s) with {t['instrument']}.")
        try:
            out["values"] = [float(v) for v in vals]
        except (TypeError, ValueError):
            raise _err("Every reading is a number.") from None
        if any(not math.isfinite(v) for v in out["values"]):
            raise _err("Every reading is a finite number.")
        if len(out["values"]) > 200:
            raise _err("At most 200 readings in one result.")
    if not out["instrument"]:
        out["instrument"] = t.get("instrument", "")
    out["verdict"] = judge(t, out)
    return out


def record(st, pid: str, test: str, values=None, result=None, instrument: str = "", by: str = "", note: str = "") -> dict:
    """Record what a person measured against one test of the head revision's plan (provenance "measured")."""
    p = st.load(pid)
    pl = plan(st, p)
    t = next((x for x in pl["tests"] if x["id"] == test), None)
    if t is None:
        raise _err(f"No test “{test}” in the plan of r{p['head']:02d}.",
                   "test_plan (or `form testplan <project>`) lists the test ids.", status=404)
    fields = clean_result(t, {"values": values, "result": result, "instrument": instrument, "by": by})
    fields["plan"] = pl["key"]
    fields["geometry"] = pl["geometry"]
    return st.add_evidence(p, {"kind": "test", "note": note, "test_record": fields})


def record_csv(st, pid: str, text: str) -> dict:
    """Every filled row of a TEST_CHECKLIST.csv: readings in reading_1..n, or result pass/fail."""
    rows = list(csv.DictReader(io.StringIO(text)))
    made, skipped = [], []
    for r in rows:
        tid = (r.get("test_id") or "").strip()
        vals = [r[k] for k in sorted((k for k in r if k and k.startswith("reading_")), key=lambda k: int(k.split("_")[1]))
                if (r.get(k) or "").strip()]
        res = (r.get("result") or "").strip()
        if not tid or (not vals and not res):
            skipped.append(tid or "(no id)")
            continue
        made.append(record(st, pid, tid, values=[v.strip().replace(",", ".") for v in vals] if vals else None,
                           result=None if vals else res, instrument=(r.get("instrument_used") or "").strip(),
                           by=(r.get("by") or "").strip(), note=(r.get("note") or "").strip()))
    return {"recorded": made, "skipped_blank": skipped}


def _results_for(p, pl) -> dict:
    """The newest recorded result per test for this revision (or one with the same geometry)."""
    out = {}
    for e in p.get("evidence") or []:
        if e.get("kind") == "test":
            tr = e.get("test_record") or {}
            if e.get("rev") == p["head"] or tr.get("geometry") == pl["geometry"]:
                out[tr.get("test")] = {**tr, "id": e["id"], "ts": e["ts"], "rev": e["rev"], "note": e.get("note", "")}
        elif e.get("kind") == "fit" and e.get("rev") == p["head"]:
            out.setdefault("fit.model", {"test": "fit.model", "result": e.get("result"), "id": e["id"], "ts": e["ts"],
                                         "rev": e["rev"], "note": e.get("note", ""), "source": "measured",
                                         "instrument": "by hand (recorded as a fit result)",
                                         "verdict": RESULT_WORDS.get(e.get("result"), "fail")})
    return out


def _hashes(st, p) -> dict:
    keys, status = st.keys(p), st.status(p)
    out = {"revision": p["head"], "geometry_key": keys["geometry"], "kernel": st.kernel_id()}
    src = _source_text(st, p)
    if src:
        out["design_code_sha256"] = hashlib.sha256(src.encode("utf-8")).hexdigest()
    else:
        out["recipe_sha256"] = st.recipe_sha(st.rid(p))
    if status["exports"]["state"] == "current":
        ex = st.read(p, "exports", keys["exports"]) or {}
        f = (ex.get("files") or {}).get("step")
        if f:
            path = st.apath(p, "exports", keys["exports"]) / f["name"]
            if path.is_file():
                out["step_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    from . import __version__
    out["app"] = __version__
    return out


def report_key(st, p) -> str:
    """What the report is made of: the revision's keys and states, the contract, every result, the strength studies,
    and the newest run of every Bench study (its log changes on every run)."""
    from . import contract
    keys, status = st.keys(p), st.status(p)
    logs = []
    base = st.dir(p["id"]) / "artifacts" / "studies"
    if base.is_dir():
        for f in sorted(base.glob("*/log.json")):
            try:
                logs.append((f.parent.name, f.stat().st_mtime_ns))
            except OSError:
                pass
    sdir = st.dir(p["id"]) / "artifacts" / "strength"
    if sdir.is_dir():
        for f in sorted(sdir.glob("*/log.json")):
            try:
                logs.append(("strength/" + f.parent.name, f.stat().st_mtime_ns))
            except OSError:
                pass
    ev = [(e.get("id"), e.get("rev")) for e in p.get("evidence") or []]
    crit = len((p.get("design") or {}).get("critiques") or [])
    return H("report", VERSION, plan_key(st, p), keys, {n: status[n]["state"] for n in status}, ev, logs, crit,
             contract.fingerprint(contract.of(p)))


def _study_rows(st, p) -> list:
    from . import studies
    rows = []
    for e in studies.listing(st, p, "study")["entries"]:
        if e["state"] == "n/a" or e["id"] in ("checks", "proof"):
            continue
        rows.append({"id": e["id"], "label": e["label"], "state": e["state"], "rev": e.get("rev"),
                     "evidence": e.get("evidence") or "", "headline": e.get("headline") or "",
                     "error": e.get("detail") or "", "why": e.get("why") or ((e.get("error") or {}).get("message") or "")})
    return rows


def results(st, p) -> dict:
    """The results report of the head revision (structured)."""
    from . import contract
    pl = plan(st, p)
    keys, status = st.keys(p), st.status(p)
    got = _results_for(p, pl)
    tests = []
    for t in pl["tests"]:
        r = got.get(t["id"])
        row = {"id": t["id"], "group": t["group"], "title": t["title"], "limits": t["limits"], "criterion": t["criterion"],
               "unit": t.get("unit", ""), "required": t["required"], "instrument_planned": t["instrument"],
               "samples": t["samples"], "status": "not measured"}
        if r:
            row.update({"status": r.get("verdict") or judge(t, r), "values": r.get("values"), "result": r.get("result"),
                        "instrument": r.get("instrument", ""), "by": r.get("by", ""), "ts": r["ts"], "rev": r["rev"],
                        "note": r.get("note", ""), "evidence": "measured"})
            if r.get("values"):
                vs = sorted(r["values"])
                row["median"] = vs[len(vs) // 2] if len(vs) % 2 else (vs[len(vs) // 2 - 1] + vs[len(vs) // 2]) / 2
                row["range"] = [vs[0], vs[-1]]
        tests.append(row)
    checks_state = status["checks"]["state"]
    ch = st.read(p, "checks", keys["checks"]) if checks_state == "current" else None
    checks = [{"id": c["id"], "label": c["label"], "status": c["status"], "value": c.get("value"),
               "evidence": c.get("evidence") or "", "method": c.get("detail") or ""} for c in (ch or {}).get("checks", [])]
    sheet = contract.prove(st, p, compute=False) if contract.of(p) or contract._features(st, p) else None
    proof = contract.table(sheet) if sheet else []
    study_rows = _study_rows(st, p)
    # open items: everything not checked
    open_items, fails = [], []
    for t in tests:
        if t["status"] == "not measured" and t["required"]:
            open_items.append({"kind": "test", "what": f"{t['title']}: not measured", "id": t["id"]})
        elif t["status"] == "fail":
            fails.append({"kind": "test", "what": f"{t['title']}: measured outside {t['limits']}" if t.get("values")
                          else f"{t['title']}: recorded as {t.get('result')}", "id": t["id"]})
    if checks_state != "current":
        open_items.append({"kind": "checks", "what": f"The checks are {checks_state} for r{p['head']:02d}: run them (run_pipeline)."})
    for c in checks:
        if c["status"] == "FAIL":
            fails.append({"kind": "check", "what": f"Check failed: {c['label']} ({c['value']})", "id": c["id"]})
        elif c["status"] in ("WARN", "REVIEW"):
            open_items.append({"kind": "check", "what": f"Check to review: {c['label']} ({c['value']})", "id": c["id"]})
    if contract.of(p) and not sheet:
        open_items.append({"kind": "proof", "what": "The brief's requirements have not been measured on this revision's model."})
    for r in proof:
        if r["status"] == "FAIL":
            fails.append({"kind": "proof", "what": f"Requirement not met on the model: {r['requirement']} ({r.get('measured')})"})
        elif r["status"] == "UNPROVEN":
            open_items.append({"kind": "proof", "what": f"Requirement not proved on the model: {r['requirement']}"})
    defined_strength = bool(_strength_defs(p))
    for s in study_rows:
        if s["state"] in ("stale", "failed", "running") or (s["id"] == "strength" and defined_strength and s["state"] != "current"):
            open_items.append({"kind": "study", "what": f"{s['label']} is {s['state']}" + (f" (computed for r{s['rev']:02d})" if s.get("rev") and s["state"] == "stale" else "")
                               + (f": {s['why']}" if s.get("why") else ""), "id": s["id"]})
    rev = st.rev(p)
    for sp in critical_params(st.recipe(p), rev):
        if sp.group == "brief" and (rev["provenance"].get(sp.key) or {}).get("source", "assumed") == "assumed":
            open_items.append({"kind": "provenance", "what": f"{sp.label} ({fmt(rev['values'][sp.key], sp.unit)}) is assumed: "
                               "the object it comes from has not been measured", "id": sp.key})
    measured = sum(1 for t in tests if t["status"] in ("pass", "fail"))
    req_n = sum(1 for t in tests if t["required"])
    if fails:
        verdict, tone = "FAIL", "fail"
        line = f"{len(fails)} failure{'s' if len(fails) != 1 else ''}" + (f" and {len(open_items)} open item{'s' if len(open_items) != 1 else ''}" if open_items else "") + "."
    elif open_items or not measured:
        verdict, tone = "NOT A PASS", "warn"
        line = (f"{len(open_items)} open item{'s' if len(open_items) != 1 else ''}: nothing unchecked is a pass."
                if open_items else "No physical result is recorded.")
    else:
        verdict, tone = "PASS", "pass"
        line = f"All {req_n} required tests measured and within their limits; nothing is open."
    out = {"version": VERSION, "project": p["id"], "name": p["name"], "rev": p["head"], "key": report_key(st, p),
           "made": time.time(), "hashes": _hashes(st, p), "purpose": p.get("purpose"),
           "verdict": verdict, "tone": tone, "verdict_line": line,
           "counts": {"tests": len(tests), "required": req_n, "measured": measured,
                      "passed": sum(1 for t in tests if t["status"] == "pass"),
                      "failed": sum(1 for t in tests if t["status"] == "fail"),
                      "not_measured": sum(1 for t in tests if t["status"] == "not measured"),
                      "open": len(open_items), "failures": len(fails)},
           "tests": tests, "checks": checks, "checks_state": checks_state, "proof": proof, "studies": study_rows,
           "not_tested": pl["not_tested"], "open": open_items, "failures": fails, "plan_key": pl["key"],
           "rule": "PASS only when every required test has a measured result within its limits and nothing is open. "
                   "Model results are labelled by their evidence class; the physical results hold only numbers a "
                   "person measured."}
    return out


# ---- writing ---------------------------------------------------------------------------------------------------------
def _dir(st, p, key: str) -> Path:
    return st.dir(p["id"]) / "artifacts" / "reports" / key


def _stamp(p, rev, what: str, key: str) -> str:
    return f"{p['name']} · r{rev:02d} · {what} · {key[:12]}"


def plan_markdown(pl: dict) -> str:
    L = [f"# Test plan: {pl['name']}", "", f"Revision r{pl['rev']:02d} · plan {pl['key'][:12]} · geometry {pl['geometry']}", "",
         pl["note"], "",
         f"Instruments are chosen so that {pl['rule']}. Dimensions the design gives no tolerance use {pl['general_tolerance']}.", ""]
    for g in GROUPS:
        ts = [t for t in pl["tests"] if t["group"] == g]
        if not ts:
            continue
        L += [f"## {GROUP_LABEL[g]} ({len(ts)})", "", "| Test | Limits | Instrument | Readings | Passes when | Source |",
              "|---|---|---|---|---|---|"]
        for t in ts:
            cell = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
            L.append(f"| `{t['id']}` {cell(t['title'])}{'' if t['required'] else ' (optional)'} | {cell(t['limits'])}"
                     f"{(' (' + cell(t['tolerance']) + ')') if t.get('tolerance') else ''} | {cell(t['instrument'])} | "
                     f"{t['samples']} | {cell(t['criterion'])} | {cell(t['source'])} |")
        L.append("")
    if pl["not_tested"]:
        L += ["## Not tested on the part", ""] + [f"- {x['what']}: {x['why']}." for x in pl["not_tested"]] + [""]
    L += ["## Recording results", "",
          "Fill in TEST_CHECKLIST.csv (readings in reading_1, reading_2, ...; or result pass/fail) and import it with "
          "`form testplan record <project> --csv TEST_CHECKLIST.csv`, or record each test with "
          "`record_physical_result(kind=\"test\", test=..., values=[...], instrument=...)`. Record only what you read "
          "off the part.", ""]
    return "\n".join(L)


def checklist_csv(pl: dict) -> str:
    n = max([t["samples"] for t in pl["tests"] if t["input"] == "number"] + [1])
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["test_id", "title", "lower", "upper", "unit", "readings_wanted", "instrument_planned"]
               + [f"reading_{i + 1}" for i in range(n)] + ["result", "instrument_used", "by", "date", "note"])
    for t in pl["tests"]:
        w.writerow([t["id"], t["title"], "" if t.get("lo") is None else fmt(t["lo"]), "" if t.get("hi") is None else fmt(t["hi"]),
                    t.get("unit", ""), t["samples"] if t["input"] == "number" else 0, t["instrument"]] + [""] * n + ["", "", "", "", ""])
    return out.getvalue()


def plan_pdf(pl: dict, p: dict) -> bytes:
    from .pdfdoc import Col, Doc, Style
    doc = Doc(f"Test plan: {pl['name']}", stamp=_stamp(p, pl["rev"], "test plan", pl["key"]),
              subject="What to measure on the made part, with which instrument, and when it passes.")
    doc.overline("Form Studio · test plan")
    doc.title(pl["name"], "What to measure on the made part, with which instrument, and when it passes.")
    doc.kv([("Design", f"{p['id']} · revision r{pl['rev']:02d}"),
            ("Geometry", pl["geometry"], True), ("Plan", pl["key"], True),
            ("Tests", f"{len(pl['tests'])} ({pl['required']} required)" + "".join(
                f" · {pl['counts'][g]} {COUNT_WORD[g][pl['counts'][g] != 1]}" for g in GROUPS if pl["counts"][g])),
            ("Instruments", f"Chosen so that {pl['rule']}."), ("Untoleranced", pl["general_tolerance"] + ".")])
    doc.space(4)
    doc.para(pl["note"])
    for g in GROUPS:
        ts = [t for t in pl["tests"] if t["group"] == g]
        if not ts:
            continue
        doc.h2(GROUP_LABEL[g], f"{len(ts)} test{'s' if len(ts) != 1 else ''}")
        rows = []
        for t in ts:
            rows.append([{"text": t["title"] + ("" if t["required"] else " (optional)"), "semi": True, "sub": t["source"]},
                         {"text": t["limits"], "mono": True, "sub": t.get("tolerance") or ""},
                         {"text": t["instrument"], "sub": t.get("instrument_note") or ""},
                         {"text": str(t["samples"]) if t["input"] == "number" else "1", "mono": True},
                         t["criterion"]])
        doc.table([Col("Test", 0.27), Col("Limits", 0.2, mono=True), Col("Instrument", 0.2), Col("n", 0.05, align="right", mono=True),
                   Col("Passes when", 0.28)], rows, size=7.8)
    if pl["not_tested"]:
        doc.h2("Not tested on the part")
        for x in pl["not_tested"]:
            doc.para(f"{x['what']}: {x['why']}.")
    # the checklist: one block per test, with a blank per reading
    doc.new_page()
    doc.overline("Form Studio · checklist")
    doc.title("Checklist", "Write down what you read off the part. A reading left empty is not measured, and "
                          "nothing unmeasured is a pass. Readings are judged against the limits when they are recorded.")
    doc.kv([("Part", f"{pl['name']} · r{pl['rev']:02d}"), ("Plan", pl["key"], True)])
    doc.space(6)
    lab = Style("semi", 9, "ink")
    for t in pl["tests"]:
        n = t["samples"] if t["input"] == "number" else 0
        per = 6
        rows_n = max(1, math.ceil(n / per)) if n else 0
        need = 34 + rows_n * 26 + 22
        doc.ensure(need)
        doc.line(doc.left, doc.y, doc.right, doc.y, (0xdd, 0xda, 0xd4), 0.4)
        doc.y -= 13
        doc.text(doc.left, doc.y, t["title"] + ("" if t["required"] else " (optional)"), lab)
        idw = doc.measure(t["id"], Style("mono", 6.8, "ink3"))
        doc.text(doc.right - idw, doc.y, t["id"], Style("mono", 6.8, "ink3"))
        doc.y -= 11
        doc.text(doc.left, doc.y, f"{t['limits']} · {t['instrument']}", Style("mono", 7.2, "ink2"))
        doc.y -= 6
        if n:
            fw = (doc.width - (per - 1) * 6) / per
            for i in range(n):
                r, c = divmod(i, per)
                doc.field(doc.left + c * (fw + 6), doc.y - 22 - r * 26, fw, f"reading {i + 1}" + (f" ({t['unit']})" if t["unit"] else ""))
            doc.y -= rows_n * 26 + 4
        else:
            doc.y -= 4
        x = doc.left
        doc.y -= 12
        if not n:
            x += doc.box(x, doc.y, "pass") + 14
            x += doc.box(x, doc.y, "fail") + 22
        doc.text(x, doc.y + 1.5, "instrument used ____________________   by ____________   date ____________",
                 Style("regular", 8, "ink3"))
        doc.y -= 10
    doc.space(10)
    doc.para("Record results with form testplan record <project> --csv TEST_CHECKLIST.csv, or the agent's "
             "record_physical_result. Form Studio keeps each with provenance “measured”, the instrument and the limits "
             "it was judged against.", Style("regular", 8, "ink3"))
    return doc.pdf()


def report_markdown(r: dict) -> str:
    h = r["hashes"]
    L = [f"# Results report: {r['name']}", "",
         f"**{r['verdict']}** · {r['verdict_line']}", "",
         f"Revision r{r['rev']:02d} · report {r['key'][:12]} · test plan {r['plan_key'][:12]}", "",
         "| Hash | Value |", "|---|---|"] + [f"| {k} | `{v}` |" for k, v in h.items()] + ["",
         r["rule"], "", f"## Physical results ({r['counts']['measured']} of {r['counts']['tests']} measured)", "",
         "| Test | Limits | Measured | Instrument | Result |", "|---|---|---|---|---|"]
    for t in r["tests"]:
        if t.get("values"):
            m = f"median {fmt(t['median'])} {t['unit']} (n={len(t['values'])}, {fmt(t['range'][0])} to {fmt(t['range'][1])})"
        elif t.get("result"):
            m = t["result"].replace("_", " ")
        else:
            m = ""
        L.append(f"| `{t['id']}` {t['title']}{'' if t['required'] else ' (optional)'} | {t['limits']} | {m} | "
                 f"{t.get('instrument') or ''} | {t['status']} |")
    L += ["", f"## Requirements on the model ({len(r['proof'])})", ""]
    if r["proof"]:
        L += ["| Requirement | Measured on the model | Tolerance | Evidence | Status |", "|---|---|---|---|---|"]
        L += [f"| {x['requirement']} | {x.get('measured') or ''} | {x['tolerance']} | {x['evidence']} | {x['status']} |" for x in r["proof"]]
    else:
        L.append("No requirement sheet for this revision.")
    L += ["", f"## Checks ({r['checks_state']})", ""]
    if r["checks"]:
        L += ["| Check | Value | Evidence | How | Status |", "|---|---|---|---|---|"]
        L += [f"| {c['label']} | {c.get('value') or ''} | {c['evidence']} | {c['method']} | {c['status']} |" for c in r["checks"]]
    else:
        L.append(f"The checks are {r['checks_state']} for this revision.")
    L += ["", "## Studies", "", "| Study | State | Headline | Evidence | Stated error and notes |", "|---|---|---|---|---|"]
    for s in r["studies"]:
        L.append(f"| {s['label']} | {s['state']}{(' r%02d' % s['rev']) if s.get('rev') else ''} | {s['headline']} | "
                 f"{s['evidence']} | {s['error'] or 'not stated'} |")
    L += ["", f"## Open items ({len(r['open'])})", ""] + ([f"- {x['what']}" for x in r["open"]] or ["None."])
    if r["failures"]:
        L += ["", f"## Failures ({len(r['failures'])})", ""] + [f"- {x['what']}" for x in r["failures"]]
    if r["not_tested"]:
        L += ["", "## Not tested on the part", ""] + [f"- {x['what']}: {x['why']}." for x in r["not_tested"]]
    L.append("")
    return "\n".join(L)


def _iso_png(st, p) -> bytes | None:
    try:
        from . import render as rendering
        recipe = st.recipe(p)
        feats = [{"id": x.id, "label": x.label} for x in recipe.features]
        return rendering.render_png(st.view(p), feats, "iso", None, size=(900, 480), overlay=False, ss=2)
    except Exception:                                # noqa: BLE001 - the report stands without its picture
        return None


def report_pdf(r: dict, p: dict, picture: bytes | None) -> bytes:
    from .pdfdoc import Col, Doc
    doc = Doc(f"Results report: {r['name']}", stamp=_stamp(p, r["rev"], "results report", r["key"]),
              subject="What was measured on the made part against the test plan, and what remains open.")
    doc.overline("Form Studio · results report")
    doc.title(r["name"], "What was measured on the made part, what the model says, and what is still open.")
    doc.verdict(r["verdict"], r["tone"], r["verdict_line"], r["rule"])
    h = r["hashes"]
    doc.kv([("Design", f"{p['id']} · revision r{r['rev']:02d} · Form Studio {h.get('app', '')}"),
            ("Geometry key", h["geometry_key"], True)]
           + ([("Design code", "SHA-256 " + h["design_code_sha256"], True)] if h.get("design_code_sha256") else
              [("Recipe", "SHA-256 " + h.get("recipe_sha256", ""), True)])
           + ([("STEP", "SHA-256 " + h["step_sha256"], True)] if h.get("step_sha256") else
              [("STEP", "no current export for this revision")])
           + [("Kernel", h["kernel"], True), ("Report", r["key"] + " · plan " + r["plan_key"], True),
              ("Made", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(r["made"])))])
    if picture:
        doc.space(4)
        doc.image(picture, doc.width * 0.62, caption=f"r{r['rev']:02d}, iso view from the kernel's solid")
    c = r["counts"]
    doc.h2("Physical results", f"{c['measured']} of {c['tests']} measured · {c['passed']} pass · {c['failed']} fail")
    rows = []
    for t in r["tests"]:
        if t.get("values"):
            m = {"text": f"{fmt(t['median'])} {t['unit']}".strip(), "mono": True,
                 "sub": f"median of {len(t['values'])} · {fmt(t['range'][0])} to {fmt(t['range'][1])}"}
        elif t.get("result"):
            m = {"text": t["result"].replace("_", " ")}
        else:
            m = {"text": "", "sub": ""}
        tone = {"pass": "pass", "fail": "fail"}.get(t["status"], "warn" if t["required"] else "ink3")
        word = {"not measured": "open" if t["required"] else "optional"}.get(t["status"], t["status"])
        who = ", ".join(x for x in (t.get("instrument") or "", t.get("by") or "",
                                    time.strftime("%Y-%m-%d", time.gmtime(t["ts"])) if t.get("ts") else "") if x)
        rows.append([{"text": t["title"], "semi": True, "sub": t["id"]}, {"text": t["limits"], "mono": True}, m,
                     {"text": who, "sub": ("measured" if t.get("evidence") else "")}, {"pill": word, "tone": tone}])
    doc.table([Col("Test", 0.28), Col("Limits", 0.19, mono=True), Col("Measured", 0.17, mono=True), Col("Instrument, by, date", 0.24),
               Col("Result", 0.12, align="right")], rows, size=7.8)
    doc.h2("Requirements on the model", f"{len(r['proof'])} rows")
    if r["proof"]:
        st_tone = {"PASS": "pass", "FAIL": "fail", "UNPROVEN": "warn"}
        doc.table([Col("Requirement", 0.36), Col("On the model", 0.2, mono=True), Col("Tolerance", 0.12, mono=True),
                   Col("Evidence", 0.2), Col("Status", 0.12, align="right")],
                  [[x["requirement"], {"text": str(x.get("measured") or ""), "mono": True}, x["tolerance"], x["evidence"],
                    {"pill": x["status"].lower(), "tone": st_tone.get(x["status"], "ink2")}] for x in r["proof"]], size=7.8)
    else:
        doc.para("No requirement sheet for this revision (the design has no brief with requirements, or they were not "
                 "measured on the model yet).")
    doc.h2("Checks", r["checks_state"])
    if r["checks"]:
        ct = {"PASS": "pass", "FAIL": "fail", "WARN": "warn", "REVIEW": "warn"}
        doc.table([Col("Check", 0.24), Col("Value", 0.2, mono=True), Col("Evidence", 0.13), Col("How it is known", 0.31),
                   Col("Status", 0.12, align="right")],
                  [[c["label"], {"text": str(c.get("value") or ""), "mono": True}, c["evidence"], {"text": c["method"], "tone": "ink2"},
                    {"pill": c["status"].lower(), "tone": ct.get(c["status"], "ink3")}] for c in r["checks"]], size=7.8)
    else:
        doc.para(f"The checks are {r['checks_state']} for this revision: nothing from them is reported.")
    doc.h2("Studies", f"{len(r['studies'])} that apply")
    stt = {"current": "pass", "stale": "warn", "failed": "fail", "running": "accent", "never": "ink3", "unavailable": "ink3"}
    doc.table([Col("Study", 0.2), Col("Headline", 0.26), Col("Evidence", 0.16), Col("Stated error and notes", 0.26),
               Col("State", 0.12, align="right")],
              [[s["label"], s["headline"] or ("" if s["state"] != "never" else "not run"), s["evidence"],
                {"text": s["error"] or "not stated", "tone": "ink2" if s["error"] else "ink3"},
                {"pill": s["state"] + (f" r{s['rev']:02d}" if s.get("rev") and s["state"] == "stale" else ""),
                 "tone": stt.get(s["state"], "ink3")}] for s in r["studies"]], size=7.8)
    doc.h2("Open items", str(len(r["open"])))
    if r["open"]:
        for x in r["open"]:
            doc.para("·  " + x["what"])
    else:
        doc.para("None.")
    if r["failures"]:
        doc.h2("Failures", str(len(r["failures"])))
        for x in r["failures"]:
            doc.para("·  " + x["what"])
    if r["not_tested"]:
        doc.h2("Not tested on the part")
        for x in r["not_tested"]:
            doc.para(f"{x['what']}: {x['why']}.")
    return doc.pdf()


def _write(folder: Path, files: dict) -> dict:
    from . import fsutil
    folder.parent.mkdir(parents=True, exist_ok=True)
    tmp = folder.with_name(folder.name + ".tmp")
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    index = {}
    for name, data in files.items():
        b = data.encode("utf-8") if isinstance(data, str) else data
        (tmp / name).write_bytes(b)
        index[name] = hashlib.sha256(b).hexdigest()
    (tmp / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    fsutil.replace_dir(tmp, folder)
    return index


def write_plan(st, p, out: Path | None = None) -> dict:
    """Write the plan's PDF, Markdown, checklist and JSON for the head revision (reused while its key holds)."""
    pl = plan(st, p)
    folder = _dir(st, p, "plan-" + pl["key"])
    if not (folder / "index.json").is_file():
        _write(folder, {"TEST_PLAN.pdf": plan_pdf(pl, p), "TEST_PLAN.md": plan_markdown(pl),
                        "TEST_CHECKLIST.csv": checklist_csv(pl), "test_plan.json": json.dumps(pl, indent=1, default=str)})
    files = {n: str(folder / n) for n in PLAN_FILES}
    if out:
        files = _copy_out(folder, Path(out), PLAN_FILES)
    return {"plan": pl, "files": files, "dir": str(folder)}


def write_report(st, p, out: Path | None = None) -> dict:
    """Write the results report's PDF, Markdown and JSON for the head revision (reused while its key holds)."""
    key = report_key(st, p)
    folder = _dir(st, p, "report-" + key)
    if (folder / "results.json").is_file():
        r = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    else:
        r = results(st, p)
        _write(folder, {"RESULTS_REPORT.pdf": report_pdf(r, p, _iso_png(st, p)), "RESULTS_REPORT.md": report_markdown(r),
                        "results.json": json.dumps(r, indent=1, default=str)})
    files = {n: str(folder / n) for n in REPORT_FILES}
    if out:
        files = _copy_out(folder, Path(out), REPORT_FILES)
    return {"report": r, "files": files, "dir": str(folder)}


def _copy_out(folder: Path, out: Path, names) -> dict:
    import shutil
    out = out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    got = {}
    for n in names:
        shutil.copy2(folder / n, out / n)
        got[n] = str(out / n)
    return got


def cached(st, p, which: str) -> dict | None:
    key = plan_key(st, p) if which == "plan" else report_key(st, p)
    folder = _dir(st, p, f"{which}-{key}")
    idx = folder / "index.json"
    return {"dir": str(folder), "key": key} if idx.is_file() else None


# ---- the Bench (form/studies.py PROVIDERS) ---------------------------------------------------------------------------
def _plan_head(pl: dict) -> str:
    return f"{len(pl['tests'])} tests · {pl['required']} required"


def register_studies(register) -> None:
    from .studies import Study

    def plan_run(ctx):
        w = write_plan(ctx.st, ctx.p)
        return {"headline": _plan_head(w["plan"]), "evidence": "a plan: no result", "files": [w["files"]["TEST_PLAN.pdf"]],
                "data": {"counts": w["plan"]["counts"], "files": w["files"]}}

    def plan_probe(ctx):
        c = cached(ctx.st, ctx.p, "plan")
        if not c:
            return None
        pl = json.loads((Path(c["dir"]) / "test_plan.json").read_text(encoding="utf-8"))
        return {"headline": _plan_head(pl), "evidence": "a plan: no result", "files": [str(Path(c["dir"]) / "TEST_PLAN.pdf")]}

    def rep_head(r):
        c = r["counts"]
        return f"{r['verdict'].lower()} · {c['measured']} of {c['tests']} measured · {c['open']} open"

    def rep_run(ctx):
        w = write_report(ctx.st, ctx.p)
        return {"headline": rep_head(w["report"]), "evidence": "measured and computed, each labelled",
                "files": [w["files"]["RESULTS_REPORT.pdf"]], "data": {"verdict": w["report"]["verdict"], "files": w["files"]}}

    def rep_probe(ctx):
        c = cached(ctx.st, ctx.p, "report")
        if not c:
            return None
        r = json.loads((Path(c["dir"]) / "results.json").read_text(encoding="utf-8"))
        return {"headline": rep_head(r), "evidence": "measured and computed, each labelled",
                "files": [str(Path(c["dir"]) / "RESULTS_REPORT.pdf")]}

    register(Study("testplan", "document", "Test plan", "What to measure on the made part: each requirement, fit, "
                   "critical dimension and load, with its instrument, limits, readings and when it passes; a checklist "
                   "to fill in.", "a plan: no result", run=plan_run, probe=plan_probe,
                   key=lambda ctx: plan_key(ctx.st, ctx.p), inputs=("geometry", "values", "provenance", "contract", "strength studies"),
                   tool="test_plan", order=30))
    register(Study("report", "document", "Results report", "The design and its hashes, every check and study with its "
                   "evidence, the measured results against the test plan, what is open, and a verdict that is never a "
                   "pass with anything unchecked.", "measured and computed, each labelled", run=rep_run, probe=rep_probe,
                   key=lambda ctx: report_key(ctx.st, ctx.p), inputs=("every key of the revision", "physical results", "studies"),
                   tool="results_report", order=32))


# ---- command line ----------------------------------------------------------------------------------------------------
def _studio():
    from . import config
    from .studio import Studio
    return Studio(config.load())


def main_testplan(argv=None) -> int:
    import argparse
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    from .studio import StudioError
    if argv[:1] == ["record"]:
        ap = argparse.ArgumentParser(prog="form testplan record", description="Record what you measured against one "
                                     "test of the plan (provenance measured). Prints JSON.")
        ap.add_argument("project")
        ap.add_argument("test", nargs="?")
        ap.add_argument("values", nargs="*", type=float)
        ap.add_argument("--result", choices=sorted(RESULT_WORDS))
        ap.add_argument("--instrument", default="")
        ap.add_argument("--by", default="")
        ap.add_argument("--note", default="")
        ap.add_argument("--csv", help="a filled TEST_CHECKLIST.csv")
        a = ap.parse_args(argv[1:])
    else:
        ap = argparse.ArgumentParser(prog="form testplan", description="The test plan of a design: what to measure on "
                                     "the made part. Writes PDF, Markdown and a checklist; prints JSON.")
        ap.add_argument("project")
        ap.add_argument("--out", help="copy the files into this folder")
        a = ap.parse_args(argv)
    st = _studio()
    try:
        if argv[:1] == ["record"]:
            if a.csv:
                out = record_csv(st, a.project, Path(a.csv).expanduser().read_text(encoding="utf-8"))
            elif a.test:
                out = record(st, a.project, a.test, values=a.values or None, result=a.result, instrument=a.instrument,
                             by=a.by, note=a.note)
            else:
                raise _err("Name the test, or give --csv.", "form testplan <project> lists the test ids.")
        else:
            w = write_plan(st, st.load(a.project), Path(a.out) if a.out else None)
            out = {"files": w["files"], **w["plan"]}
        print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
        return 0
    except StudioError as e:
        print(json.dumps({"error": e.public()}, indent=1, ensure_ascii=False))
        return 2
    finally:
        try:
            st.kernel.shutdown()
        except Exception:                            # noqa: BLE001
            pass


def main_report(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="form report", description="The results report of a design: measured results "
                                 "against the test plan, every check and study with its evidence, open items and a "
                                 "verdict. Writes PDF and Markdown; prints JSON.")
    ap.add_argument("project")
    ap.add_argument("--out", help="copy the files into this folder")
    a = ap.parse_args(argv)
    from .studio import StudioError
    st = _studio()
    try:
        w = write_report(st, st.load(a.project), Path(a.out) if a.out else None)
        print(json.dumps({"files": w["files"], **w["report"]}, indent=1, ensure_ascii=False, default=str))
        return 0 if w["report"]["verdict"] == "PASS" else 1
    except StudioError as e:
        print(json.dumps({"error": e.public()}, indent=1, ensure_ascii=False))
        return 2
    finally:
        try:
            st.kernel.shutdown()
        except Exception:                            # noqa: BLE001
            pass


# ---- MCP -------------------------------------------------------------------------------------------------------------
def register_mcp(mcp, get_studio, run) -> None:
    from mcp.types import ToolAnnotations
    rw = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    async def test_plan(project: str, out_dir: str | None = None) -> dict:
        """The physical test plan of a design's head revision, from what it claims: one test per brief requirement,
        per fit (ISO 286 holes and pairs, the fit window, assembly mates), per critical dimension (brief and
        interface parameters, measured or specified values, the overall size) and per strength-study load. Each test:
        id, what to measure, instrument (10:1 rule), limits and their source (the drawing's ISO 286 fit or ISO 2768
        class where it states one, else ISO 2768-1 m), readings, and when it passes; a load test quotes the strength
        study's converged displacement. Writes TEST_PLAN.pdf, TEST_PLAN.md and TEST_CHECKLIST.csv (copied to out_dir if given).
        Results go in with record_physical_result(kind="test", test=<id>, values=[...] or result="pass"|"fail",
        instrument=...), only for what the person measured."""
        st = get_studio()

        def go():
            w = write_plan(st, st.load(project), Path(out_dir) if out_dir else None)
            pl = w["plan"]
            return {"files": w["files"], "rev": pl["rev"], "key": pl["key"], "counts": pl["counts"], "required": pl["required"],
                    "tests": [{k: t.get(k) for k in ("id", "group", "title", "limits", "tolerance", "instrument", "samples",
                                                     "input", "criterion", "source", "required")} for t in pl["tests"]],
                    "not_tested": pl["not_tested"], "rule": pl["rule"], "general_tolerance": pl["general_tolerance"]}
        return await run(go)

    async def results_report(project: str, out_dir: str | None = None) -> dict:
        """The results report of a design's head revision: the design with its revision and hashes, every check and
        study with its evidence class and stated error, the physical results recorded against the test plan, open
        items and a verdict. PASS only when every required test is measured within limits and nothing is open;
        anything unchecked is NOT A PASS; a measured failure is FAIL. Writes RESULTS_REPORT.pdf and .md (copied to
        out_dir if given). Report the verdict as it is."""
        st = get_studio()

        def go():
            w = write_report(st, st.load(project), Path(out_dir) if out_dir else None)
            r = w["report"]
            return {"files": w["files"], "verdict": r["verdict"], "verdict_line": r["verdict_line"], "counts": r["counts"],
                    "open": r["open"], "failures": r["failures"], "hashes": r["hashes"], "rev": r["rev"],
                    "tests": [{k: t.get(k) for k in ("id", "title", "status", "limits", "median", "values", "result", "instrument")}
                              for t in r["tests"]]}
        return await run(go)

    for fn in (test_plan, results_report):
        mcp.tool(name=fn.__name__, annotations=rw)(fn)
