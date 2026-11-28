"""Write the verification table and the timings of docs/STRENGTH.md from a real run of the suite.

    python scripts/gen_strength_docs.py            # runs form.fea.verify in the FEA engine's Python, rewrites the tables
    python scripts/gen_strength_docs.py --check    # exit 1 when a case, quantity or tolerance in the docs differs

The numbers between the markers in docs/STRENGTH.md are this script's output and nothing else: never edit them by
hand. The engine's Python is form.fea.python(): $FORM_FEA_PYTHON, the installed engine, or this one.
--check compares what does not depend on the machine (cases, quantities, references, tolerances), so it can run
anywhere the engine is installed; tests/test_fea_verification.py runs the suite itself.
"""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DOC = ROOT / "docs" / "STRENGTH.md"
MARKS = {"table": ("<!-- verification:begin -->", "<!-- verification:end -->"),
         "bench": ("<!-- timings:begin -->", "<!-- timings:end -->")}


def engine(*args) -> dict:
    from form import config, fea
    py = fea.python(config.load())
    if py is None:
        sys.exit("The FEA engine is not installed (set FORM_FEA_PYTHON to its Python).")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    r = subprocess.run([str(py), "-m", "form.fea.verify", *args], env=env, capture_output=True, text=True, encoding="utf-8",
                       cwd=str(ROOT))
    if not r.stdout.strip():
        sys.exit(r.stderr[-2000:])
    return json.loads(r.stdout)


def fmt(x) -> str:
    if isinstance(x, bool):
        return "yes" if x else "no"
    return f"{x:.5g}"


def table(rep: dict) -> str:
    out = ["| Case | Quantity | Reference | Expected | Got | Error | Tolerance | Pass |", "|---|---|---|---|---|---|---|---|"]
    for c in rep["cases"]:
        for i, r in enumerate(c["rows"]):
            unit = f" {r['unit']}" if r["unit"] else ""
            err = "" if isinstance(r["expected"], bool) else f"{100 * r['error']:.2f} %"
            tol = "" if isinstance(r["expected"], bool) else f"{100 * r['tolerance']:.1f} %"
            out.append(f"| {c['title'] if i == 0 else ''} | {r['quantity']} | {r['source']} | {fmt(r['expected'])}{unit} | "
                       f"{fmt(r['got'])}{unit} | {err} | {tol} | {'PASS' if r['pass'] else 'FAIL'} |")
    out += ["", "| Case | Study | Refinements | Unknowns | Stated error | Converged | Time |", "|---|---|---|---|---|---|---|"]
    for c in rep["cases"]:
        key = {"static": "stress", "modal": "frequency", "buckling": "load_factor"}[c["kind"]]
        stated = (c.get("stated_error") or {}).get(key)
        out.append(f"| {c['title']} | {c['kind']} | {c['levels']} | {c['unknowns']:,} | "
                   f"{'' if stated is None else f'{max(100 * stated, 0.1):.1f} %'} | {'yes' if c['converged'] else 'no'} | {c['seconds']} s |")
    v = rep["versions"]
    out += ["", f"{sum(len(c['rows']) for c in rep['cases'])} quantities in {len(rep['cases'])} cases, "
            f"{'all within tolerance' if rep['pass'] else 'NOT all within tolerance'}; {rep['seconds']} s in total. "
            f"Run on {date.today().isoformat()} with Netgen {v['netgen-mesher']}, scikit-fem {v['scikit-fem']}, SciPy {v['scipy']}, "
            f"PyAMG {v['pyamg']} and NumPy {v['numpy']}."]
    return "\n".join(out)


def bench(rep: dict) -> str:
    out = ["| Study | Time | Unknowns | Tetrahedra | Refinements | Evidence | Result |", "|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        out.append(f"| {r['kind']} | {r['seconds']} s | {r['unknowns']:,} | {r['tets']:,} | {r['levels']} | {r['evidence']} | {r['result']} |")
    out += ["", f"Machine: {rep['machine']}. The time is the whole study in the engine: every mesh, every solve, the stress "
            "recovery and the field data."]
    return "\n".join(out)


def stable(text: str) -> list:
    """The cells of the table that do not depend on the machine: case, quantity, reference, tolerance."""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 8 and cells[0] != "Case" and not set(cells[1]) <= {"-"}:
            rows.append((cells[1], cells[2], cells[6]))
    return rows


def between(text: str, a: str, b: str) -> str:
    return text[text.index(a) + len(a):text.index(b)]


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    rep = engine("--json")
    new_table = table(rep)
    if "--check" in sys.argv:
        ok = stable(between(text, *MARKS["table"])) == stable(new_table) and rep["pass"]
        print("docs/STRENGTH.md matches the verification suite" if ok else
              "docs/STRENGTH.md differs from the verification suite: run scripts/gen_strength_docs.py")
        return 0 if ok else 1
    for key, body in (("table", new_table), ("bench", bench(engine("--bench")))):
        a, b = MARKS[key]
        text = text[:text.index(a) + len(a)] + "\n" + body + "\n" + text[text.index(b):]
    DOC.write_text(text, encoding="utf-8")
    print(f"wrote {DOC.relative_to(ROOT)}: {'all pass' if rep['pass'] else 'FAILURES'}")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
