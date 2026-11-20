"""Design bench: about 20 briefs with automated scoring.

    .venv/bin/python tests/design_bench/bench.py                      # build and check every exemplar-backed brief
    .venv/bin/python tests/design_bench/bench.py --solutions DIR      # also score an agent's DIR/<brief id>.py files
    .venv/bin/python tests/design_bench/bench.py --only knob,vase --json out.json

Score per brief (100):
  staging  15  the staged workflow triggers exactly when the brief is complex (form.staged.assess, heuristic)
  builds   30  the design builds in the kernel: a valid B-rep with the number of solids it declares
  features 25  the brief's feature groups are present as features with faces in the solid
  craft    15  rounded where it matters: a fillet exists if asked, sharp-edge fraction below 0.6
  form     15  the brief's expectations: free-form surface share, solids, symmetry, mesh texture declared
A brief without a solution scores staging only and is reported as "no solution". A brief may name a reference
"solution" (tests/design_bench/solutions/NAME.py): a design written through the MCP tools in a design evaluation,
built and scored like an exemplar. A design that needs an optional extra that is not installed (py_gearworks for
gears) is reported as skipped, not failed. Metrics come from form.critique
(evidence class heuristic). Builds run in this process (build123d / OCCT), like the kernel worker.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS = 70


def briefs() -> list[dict]:
    return json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))["briefs"]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"bench_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    inst = mod.Design()
    inst.id = f"bench:{path.stem}"
    return inst


def check(recipe, key: str) -> dict:
    """Build a recipe instance the way the kernel does and compute the critique metrics."""
    from form import critique, kernel
    old = kernel.resolve
    kernel.resolve = lambda rid: recipe
    kernel._cache.clear()
    t0 = time.time()
    try:
        model = kernel._build(key, recipe.defaults(), 0.05)
        kernel._cache[(key, 0.05)] = model
        m = critique.op_critique_metrics(key, key, recipe.defaults(), 0.05)
        m["build_s"] = round(time.time() - t0, 2)
        m["valid"] = bool(model["shape"].is_valid)
        m["feature_labels"] = {f.id: f.label for f in recipe.features}
        from form.craft import meshtex
        m["mesh_texture"] = bool(meshtex.declared(recipe, model["values"]))
        return m
    except Exception as e:                                       # a failed build is a score of 0 for builds
        if "is not installed" in str(e):                         # an optional extra (py_gearworks): not a failure
            return {"skipped": str(e).split("\n")[0][:160], "build_s": round(time.time() - t0, 2)}
        return {"error": f"{type(e).__name__}: {e}", "build_s": round(time.time() - t0, 2)}
    finally:
        kernel.resolve = old
        kernel._cache.clear()


def score(b: dict, m: dict | None) -> dict:
    from form import staged
    out = {"id": b["id"], "points": {}, "notes": []}
    a = staged.assess(b["brief"])
    out["points"]["staging"] = 15 if a["complex"] == b["complex"] else 0
    if a["complex"] != b["complex"]:
        out["notes"].append(f"staging: assess() said complex={a['complex']}")
    if m is None:
        out["status"] = "no solution"
        out["total"] = out["points"]["staging"]
        return out
    if m.get("skipped"):
        out["notes"].append(m["skipped"])
        out["status"] = "skipped (optional extra missing)"
        out["total"] = out["points"]["staging"]
        return out
    if m.get("error"):
        out["points"].update(builds=0, features=0, craft=0, form=0)
        out["notes"].append(m["error"][:200])
        out["status"] = "failed to build"
        out["total"] = sum(out["points"].values())
        return out
    out["points"]["builds"] = 30 if m["valid"] else 10
    present = {k: (k + " " + m["feature_labels"].get(k, "")).lower() for k in m["features"]}
    groups = b.get("features", [])
    hit = [g for g in groups if any(any(w in txt for w in g) for txt in present.values())]
    out["points"]["features"] = round(25 * len(hit) / max(1, len(groups)))
    miss = [g[0] for g in groups if g not in hit]
    if miss:
        out["notes"].append("features missing: " + ", ".join(miss))
    e = b.get("expect", {})
    craft = 15
    if e.get("fillet") and m.get("smallest_fillet_mm") is None:
        craft -= 8
        out["notes"].append("no fillet")
    if (m.get("sharp_edge_fraction") or 0) > 0.6:
        craft -= 7
        out["notes"].append(f"sharp-edge fraction {m['sharp_edge_fraction']}")
    out["points"]["craft"] = craft
    form, checks = 15, 0
    fails = []
    mix = m.get("surface_mix") or {}
    if "freeform_min" in e:
        checks += 1
        ff = mix.get("free", 0) + mix.get("torus", 0) + mix.get("sphere", 0)
        if ff < e["freeform_min"]:
            fails.append(f"free-form share {ff:.2f} < {e['freeform_min']}")
    if "solids_min" in e:
        checks += 1
        if m["solids"] < e["solids_min"]:
            fails.append(f"{m['solids']} solids < {e['solids_min']}")
    for ax, lo in e.get("symmetry_min", {}).items():
        checks += 1
        if m["symmetry"].get(ax, 0) < lo:
            fails.append(f"{ax} {m['symmetry'].get(ax)} < {lo}")
    if "mesh_texture" in e and e["mesh_texture"]:
        checks += 1
        if not m["mesh_texture"]:
            fails.append("no mesh texture declared")
    if checks:
        form = round(15 * (checks - len(fails)) / checks)
    out["points"]["form"] = form
    out["notes"] += fails
    out["total"] = sum(out["points"].values())
    out["status"] = "pass" if out["total"] >= PASS else "below the bar"
    out["metrics"] = {k: m.get(k) for k in ("smallest_fillet_mm", "sharp_edge_fraction", "symmetry", "surface_mix",
                                           "solids", "build_s")}
    return out


def run(solutions: Path | None = None, only: set | None = None, exemplars_too: bool = True) -> list[dict]:
    from form import exemplars
    res = []
    for b in briefs():
        if only and b["id"] not in only:
            continue
        m = None
        if solutions and (solutions / f"{b['id']}.py").is_file():
            m = check(_load(solutions / f"{b['id']}.py"), f"bench-{b['id']}")
            src = "solution"
        elif exemplars_too and b.get("exemplar"):
            m = check(exemplars.load(b["exemplar"]), f"exemplar-{b['exemplar']}")
            src = f"exemplar {b['exemplar']}"
        elif exemplars_too and b.get("solution"):
            m = check(_load(HERE / "solutions" / f"{b['solution']}.py"), f"solution-{b['solution']}")
            src = f"solution {b['solution']}"
        else:
            src = "-"
        r = score(b, m)
        r["source"] = src
        res.append(r)
    return res


def table(res: list[dict]) -> str:
    rows = ["| brief | source | staging | builds | features | craft | form | total | status |",
            "|---|---|---|---|---|---|---|---|---|"]
    for r in res:
        p = r["points"]
        rows.append(f"| {r['id']} | {r['source']} | {p.get('staging', '')} | {p.get('builds', '')} | {p.get('features', '')} | "
                    f"{p.get('craft', '')} | {p.get('form', '')} | {r['total']} | {r['status']} |")
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--solutions", type=Path)
    ap.add_argument("--only")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    res = run(a.solutions, set(a.only.split(",")) if a.only else None)
    print(table(res))
    for r in res:
        if r["notes"]:
            print(f"  {r['id']}: " + "; ".join(r["notes"]))
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
