"""Form Studio's own verification suites, as rows: each one compares a computed value with a published one.

    python form/bench/suites.py <suite>        prints {"suite", "available", "rows", ...} as JSON

This file is run BY PATH in its own process, with the source tree to measure first on PYTHONPATH
(form/bench/__init__.py does that). It imports only `form` modules from that tree, so the same runner measures
any checkout, and a suite whose code is not in the tree reports `available: false` with the reason instead of a row.
Every computed value comes from the code under test. Expected values come from the published source each suite
names: the suite modules' own references (strength, calculators), the transcribed ISO 286-2 table (iso286; four
named fits listed below when wave F is absent), the rule tables themselves (dfm) and the input mesh (recon).

Suites:
  strength      form.fea.verify (wave D): textbook and NAFEMS cases solved by the strength study's own code path.
                Needs the FEA engine's Python ($FORM_FEA_PYTHON, or this Python when it has Netgen and scikit-fem).
  calculators   form.calc.verify (wave X): worked examples from their published sources, and the solids measured.
  iso286        ISO 286 limits (wave F): form.drawing.iso286 computed from the standard's formulas, checked against
                the ISO 286-2 table values transcribed in form/craft/fits.py; without wave F, the tabulated module's
                own named fits.
  dfm           form.dfm.rules (wave E): every numeric limit of every process table probed on both sides of its
                threshold through rules.evaluate, the function that judges a real part.
  recon         scripts/recon_bench.py: mesh to editable CAD on the synthetic part classes, deviation against
                tolerance (about 15 minutes).
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _root() -> Path:
    spec = importlib.util.find_spec("form")
    if spec is None or not spec.origin:
        raise SystemExit("no `form` package on PYTHONPATH")
    return Path(spec.origin).resolve().parents[1]


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def _row(group, item, expected, got, unit, tolerance, passed, source="", note="", error=None, relative=False) -> dict:
    """relative: tolerance and error are fractions of the expected value (else absolute, in the row's unit)."""
    return {"group": group, "item": item, "expected": expected, "got": got, "unit": unit, "tolerance": tolerance,
            "error": error, "relative": relative, "pass": bool(passed), "source": source, "note": note}


def _absent(suite: str, why: str) -> dict:
    return {"suite": suite, "available": False, "reason": why, "rows": []}


# ---- strength (wave D) ------------------------------------------------------------------------------------------

def strength() -> dict:
    if not _has("form.fea.verify"):
        return _absent("strength", "form.fea is not in this source tree (it lands with wave D, branch wave-d-strength)")
    py = os.environ.get("FORM_FEA_PYTHON") or ""
    if not py:
        if all(_has(m) for m in ("netgen", "skfem", "pyamg", "scipy")):
            py = sys.executable
        else:
            return _absent("strength", "no FEA engine Python: set FORM_FEA_PYTHON to a Python with the FEA engine's "
                                       "pinned libraries (Netgen, scikit-fem, SciPy, PyAMG)")
    env = {**os.environ, "PYTHONPATH": str(_root())}
    r = subprocess.run([py, "-m", "form.fea.verify", "--json"], capture_output=True, text=True, env=env, cwd=str(_root()),
                       timeout=3600)
    try:
        rep = json.loads(r.stdout)
    except ValueError:
        return {**_absent("strength", "the suite did not print JSON"), "available": True, "stderr": r.stderr[-2000:],
                "rows": [_row("strength", "suite run", "JSON report", "none", "", "", False, note=r.stderr[-300:])]}
    rows = []
    for c in rep["cases"]:
        for x in c["rows"]:
            rows.append(_row(c["title"], x["quantity"], x["expected"], x["got"], x.get("unit", ""), x.get("tolerance"),
                             x["pass"], x.get("source", ""), error=x.get("error"), relative=True))
        if not c.get("converged", True):
            rows.append(_row(c["title"], "converged", True, False, "", "", False,
                             note=str(c.get("not_converged_because") or "")))
    return {"suite": "strength", "available": True, "rows": rows, "versions": rep.get("versions", {}),
            "cases": len(rep["cases"])}


# ---- calculators (wave X) ---------------------------------------------------------------------------------------

def calculators() -> dict:
    if not _has("form.calc.verify"):
        return _absent("calculators", "form.calc is not in this source tree (it lands with wave X, branch "
                                      "wave-x-calculators)")
    from form.calc import verify
    rows = []
    for x in verify.examples():
        rows.append(_row(f"{x['calculator']}: {x['case']}", x["quantity"], x["reference"], x["computed"], x.get("unit", ""),
                         x["accepted"], x["pass"], x.get("source", ""), x.get("note", ""), error=x.get("error"), relative=True))
    note = ""
    try:
        geo = verify.geometry()
    except Exception as e:                                            # noqa: BLE001 - the kernel may be missing
        geo, note = [], f"solids not measured: {type(e).__name__}: {e}"
    for x in geo:
        rows.append(_row(f"solid: {x['geometry']}", x["measured_on_the_solid"], x["expected"], x["measured"],
                         x.get("unit", "mm"), x["accepted"], x["pass"], "the calculator's own sheet",
                         error=x.get("difference")))
    if note:
        rows.append(_row("solid", "solids built and measured", "built", "not built", "", "", False, note=note))
    return {"suite": "calculators", "available": True, "rows": rows}


# ---- ISO 286 (wave F) -------------------------------------------------------------------------------------------

def iso286() -> dict:
    if not _has("form.craft.fits"):
        return _absent("iso286", "form.craft.fits is not in this source tree")
    from form.craft import fits as table
    src = "ISO 286-2:2010 table value, as transcribed in form/craft/fits.py"
    mids = [hi - 0.5 if i else 2 for i, hi in enumerate(table.RANGES)]       # one size inside each step
    lows = (0,) + tuple(table.RANGES[:-1])
    step = [f"over {lo} to {hi} mm" for lo, hi in zip(lows, table.RANGES)]
    rows = []
    if _has("form.drawing.iso286"):
        from form.drawing import iso286 as calc
        for g in sorted(table.IT):
            for k, d in enumerate(mids):
                got = calc.it(g, d)
                rows.append(_row(f"IT{g}", step[k], table.IT[g][k], got["um"], "µm", 0, got["um"] == table.IT[g][k],
                                 src, f"computed by {got['how']}"))
        for L in "efgh":
            for k, d in enumerate(mids):
                got = calc.deviation(L, d)
                rows.append(_row(f"shaft {L}: upper deviation es", step[k], table.SHAFT_ES[L][k], got["um"], "µm", 0,
                                 got["um"] == table.SHAFT_ES[L][k], src))
        for L in "kmnps":
            for k, d in enumerate(mids[:len(table.SHAFT_EI[L])]):
                got = calc.deviation(L, d, 6)
                rows.append(_row(f"shaft {L}6: lower deviation ei", step[k], table.SHAFT_EI[L][k], got["um"], "µm", 0,
                                 got["um"] == table.SHAFT_EI[L][k], src))
        for code in ("H7/g6", "H7/h6", "H7/k6", "H7/p6", "H8/f7", "H9/e9"):
            for d in (8, 25, 100):
                want, got = table.iso_fit(code, d), calc.fit(code, d)
                rows.append(_row(f"fit {code}", f"Ø{d} kind and clearance", f"{want['kind']} {want['clearance']}",
                                 f"{got['kind']} {tuple(got['clearance'])}", "mm", 0,
                                 want["kind"] == got["kind"] and all(abs(a - b) < 5e-4 for a, b in
                                                                     zip(want["clearance"], got["clearance"])),
                                 "form/craft/fits.py (the tabulated values)"))
        return {"suite": "iso286", "available": True, "rows": rows, "mode": "formulas against the table"}
    # without wave F: the tabulated module's named examples (the values its docstring and tests state)
    named = [("H7/g6", 8, (8.0, 8.015), (7.986, 7.995)), ("H7/h6", 25, (25.0, 25.021), (24.987, 25.0)),
             ("H7/p6", 25, (25.0, 25.021), (25.022, 25.035)), ("H7/k6", 25, (25.0, 25.021), (25.002, 25.015))]
    for code, d, hole, shaft in named:
        f = table.iso_fit(code, d)
        rows.append(_row(f"fit {code}", f"Ø{d} hole limits", hole, tuple(f["hole"]), "mm", 0, tuple(f["hole"]) == hole, src))
        rows.append(_row(f"fit {code}", f"Ø{d} shaft limits", shaft, tuple(f["shaft"]), "mm", 0, tuple(f["shaft"]) == shaft, src))
    return {"suite": "iso286", "available": True, "rows": rows, "mode": "named fits (form.drawing.iso286 not in this tree)"}


# ---- DFM thresholds (wave E) ------------------------------------------------------------------------------------

def _probe_points(op: str, fail, warn):
    """[(value, expected status, what)] on both sides of each limit, for op >= or <=."""
    out = []
    eps = lambda x: 1e-6 * max(1.0, abs(x))                           # noqa: E731
    sgn = -1 if op == ">=" else 1                                        # the side of the limit that is worse
    if fail is not None:
        at = "warn" if warn is not None and ((op == ">=" and fail < warn) or (op == "<=" and fail > warn)) else "pass"
        out += [(fail, at, "at the fail limit"), (fail + sgn * eps(fail), "fail", "just past the fail limit")]
    if warn is not None:
        out += [(warn, "pass", "at the warn limit"), (warn + sgn * eps(warn), "warn", "just past the warn limit")]
    return out


def dfm() -> dict:
    if not _has("form.dfm.rules"):
        return _absent("dfm", "form.dfm is not in this source tree (it lands with wave E, branch wave-e-dfm)")
    from form.dfm import rules
    rows = []
    for proc in rules.processes():
        t = rules.table(proc)
        for r in t["rules"]:
            if r.get("op") not in (">=", "<="):
                continue
            keys = [None]
            for lim in (r.get("fail"), r.get("warn")):
                if isinstance(lim, dict):
                    keys = sorted({k for k in lim})
            for key in keys:
                opts: dict = {}
                if r.get("when"):
                    opts[r["when"]] = True
                if key is not None and key != "default":
                    opts[r.get("by", "")] = key
                if r.get("fail") == "tool_r" or r.get("warn") == "tool_r":
                    opts["tool_d"] = 6.0
                f, w, why = rules.limits(r, opts)
                label = f"{proc} {r['id']}" + (f" ({r.get('by')} = {key})" if key is not None else "")
                if why:
                    rows.append(_row(label, "limit resolved", "a limit", why, r.get("unit", ""), "", False,
                                     r.get("source", "")))
                    continue
                for v, want, what in _probe_points(r["op"], f, w):
                    meas = {"measures": {r["measure"]: {"state": "measured", "items": [{"value": v}]}}}
                    res = rules.evaluate(proc, meas, opts)
                    got = next(x["status"] for x in res["rows"] if x["id"] == r["id"])
                    rows.append(_row(label, f"{r['op']} {what} ({v:.6g} {r.get('unit', '')})".strip(), want, got,
                                     "", "", got == want, rules.evidence_of(r, t["sources"])))
    return {"suite": "dfm", "available": True, "rows": rows, "processes": rules.processes()}


# ---- mesh to CAD (recon bench) ----------------------------------------------------------------------------------

def recon() -> dict:
    script = _root() / "scripts" / "recon_bench.py"
    if not script.is_file():
        return _absent("recon", "scripts/recon_bench.py is not in this source tree")
    with tempfile.TemporaryDirectory(prefix="form-bench-recon-") as tmp:
        out = Path(tmp) / "recon.json"
        args = [sys.executable, str(script), "--out", str(Path(tmp) / "recon.md"), "--json", str(out)]
        if os.environ.get("FORM_BENCH_RECON_CLASSES"):
            args += ["--classes", *os.environ["FORM_BENCH_RECON_CLASSES"].split(",")]
        r = subprocess.run(args, capture_output=True, text=True, cwd=str(_root()), timeout=4 * 3600,
                           env={**os.environ, "PYTHONPATH": str(_root())})
        if not out.is_file():
            return {"suite": "recon", "available": True, "rows": [
                _row("recon", "bench run", "a report", "none", "", "", False, note=(r.stderr or r.stdout)[-300:])]}
        rep = json.loads(out.read_text(encoding="utf-8"))
    rows = []
    for x in rep.get("rows", []):
        res = x.get("without") or {}
        part = f"{x.get('class', '')}: {x.get('part', '')}"
        if res.get("error"):
            rows.append(_row(part, "Hausdorff deviation", f"<= {x['tol']}", "error", "mm", x["tol"], False,
                             note=str(res["error"])[:200]))
            continue
        rows.append(_row(part, "Hausdorff deviation", f"<= {x['tol']}", res.get("hausdorff_mm"), "mm", x["tol"],
                         bool(res.get("within")), "the input mesh",
                         note=f"B-rep {res.get('brep_pct')} %, editable {res.get('editable_pct')} %, "
                              f"gates {res.get('gates')}, {res.get('seconds')} s"))
    return {"suite": "recon", "available": True, "rows": rows}


SUITES = {"strength": strength, "calculators": calculators, "iso286": iso286, "dfm": dfm, "recon": recon}


def main(argv: list[str]) -> int:
    name = argv[0] if argv else ""
    if name not in SUITES:
        print(json.dumps({"error": f"unknown suite {name!r}; suites: {', '.join(SUITES)}"}))
        return 2
    t0 = time.perf_counter()
    try:
        rep = SUITES[name]()
    except Exception as e:                                            # noqa: BLE001 - a crash is a published failure
        import traceback
        rep = {"suite": name, "available": True, "crashed": True,
               "rows": [_row(name, "suite run", "completes", f"{type(e).__name__}: {e}", "", "", False,
                             note=traceback.format_exc()[-400:])]}
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    rep["python"] = platform.python_version()
    print(json.dumps(rep, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
