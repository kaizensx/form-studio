"""Design bench: about 20 briefs with automated scoring.

    .venv/bin/python tests/design_bench/bench.py                      # build and check every exemplar-backed brief
    .venv/bin/python tests/design_bench/bench.py --solutions DIR      # also score an agent's DIR/<brief id>.py files
    .venv/bin/python tests/design_bench/bench.py --only knob,vase --json out.json

Score per brief (points out of the maximum that applies, scaled to 100):
  staging    10  the staged workflow triggers exactly when the brief is complex (form.staged.assess, heuristic)
  builds     20  the design builds in the kernel: a valid B-rep with the number of solids it declares
  features   15  the brief's feature groups are present as features with faces in the solid
  craft      10  rounded where it matters: a fillet exists if asked, sharp-edge fraction below 0.6
  form       10  the brief's expectations: free-form surface share, solids, symmetry, mesh texture declared
  integrity  10  no folds in lofted skins (loft_report), no break-through or paper-thin walls in shells (ray thickness;
                 for a product class or expect.shell), no
                 invalid intermediate stage
  silhouette 25  only for a brief with a product "class" (form.product_classes): the side, front and top silhouettes
                 against the class outline, proportions against the class range, the class signature (an eye port,
                 a neck opening, a palm hump ...). A design whose class score is under 0.8 does not read as its class
                 and is capped at 60 whatever else it earns.
A folded lofted skin or a wall that breaks through is a defect: the total is capped at 65.
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
MAX = {"staging": 10, "builds": 20, "features": 15, "craft": 10, "form": 10, "integrity": 10, "silhouette": 25}
CLASS_BAR, CAP = 0.8, 60
DEFECT_CAP = 65                  # a folded skin or a wall that breaks through is a defect, not a style choice


def product_class(b: dict) -> str | None:
    from form import product_classes
    return b.get("class") or product_classes.detect(b["brief"])


def briefs() -> list[dict]:
    return json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))["briefs"]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"bench_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    inst = mod.Design()
    inst.id = f"bench:{path.stem}"
    return inst


def check(recipe, key: str, cls: str | None = None) -> dict:
    """Build a recipe instance the way the kernel does and compute the critique metrics (with the product class's
    silhouette assessment when cls is given)."""
    from form import critique, kernel
    old = kernel.resolve
    kernel.resolve = lambda rid: recipe
    kernel._cache.clear()
    t0 = time.time()
    try:
        model = kernel._build(key, recipe.defaults(), 0.05)
        kernel._cache[(key, 0.05)] = model
        m = critique.op_critique_metrics(key, key, recipe.defaults(), 0.05, product_class=cls)
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


def _total(out: dict, cls: str | None) -> int:
    """Points scaled to 100 over the categories that apply (silhouette only with a product class)."""
    keys = [k for k in MAX if k in out["points"]]
    mx = sum(MAX[k] for k in keys)
    return round(100 * sum(out["points"][k] for k in keys) / mx) if mx else 0


def score(b: dict, m: dict | None) -> dict:
    from form import staged
    out = {"id": b["id"], "points": {}, "notes": []}
    cls = product_class(b)
    a = staged.assess(b["brief"])
    out["points"]["staging"] = MAX["staging"] if a["complex"] == b["complex"] else 0
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
        out["points"].update(builds=0, features=0, craft=0, form=0, integrity=0)
        if cls:
            out["points"]["silhouette"] = 0
        out["notes"].append(m["error"][:200])
        out["status"] = "failed to build"
        out["total"] = _total(out, cls)
        return out
    out["points"]["builds"] = MAX["builds"] if m["valid"] else 6
    present = {k: (k + " " + m["feature_labels"].get(k, "")).lower() for k in m["features"]}
    groups = b.get("features", [])
    hit = [g for g in groups if any(any(w in txt for w in g) for txt in present.values())]
    out["points"]["features"] = round(MAX["features"] * len(hit) / max(1, len(groups)))
    miss = [g[0] for g in groups if g not in hit]
    if miss:
        out["notes"].append("features missing: " + ", ".join(miss))
    e = b.get("expect", {})
    craft = MAX["craft"]
    if e.get("fillet") and m.get("smallest_fillet_mm") is None:
        craft -= 5
        out["notes"].append("no fillet")
    if (m.get("sharp_edge_fraction") or 0) > 0.6:
        craft -= 5
        out["notes"].append(f"sharp-edge fraction {m['sharp_edge_fraction']}")
    out["points"]["craft"] = craft
    form, checks = MAX["form"], 0
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
        form = round(MAX["form"] * (checks - len(fails)) / checks)
    out["points"]["form"] = form
    out["notes"] += fails
    # integrity: folds, walls, broken intermediate stages
    integ = MAX["integrity"]
    fo, wl = m.get("folds") or {}, m.get("walls") or {}
    defects = []
    if fo.get("folds"):
        defects.append("folded skin")
        integ -= 4
        out["notes"].append(f"lofted skin folds ({fo['folds']} sample pairs, worst {fo['worst_deg']} deg)")
    # thin walls are a defect of shells (a product class, or a brief that says so); gear teeth and ribs are thin on
    # purpose and are only reported
    shell = bool(cls) or e.get("shell", False)
    if not shell and wl.get("samples") and wl["thin_fraction"] > 0.01:
        out["notes"].append(f"thin features (reported, not scored): {wl['thin_fraction'] * 100:.1f} % under 35 % of "
                            f"the median wall")
    if shell and wl.get("samples") and (wl["p2_mm"] < 0.35 * wl["median_mm"] or wl["thin_fraction"] > 0.01):
        defects.append("thin or broken-through walls")
        integ -= 4
        out["notes"].append(f"thin or broken-through walls (2 % {wl['p2_mm']} mm vs median {wl['median_mm']} mm, "
                            f"{wl['thin_fraction'] * 100:.1f} % thin)")
    if any("not a valid solid" in n or "loft_report" in n for n in m.get("craft_notes", [])):
        integ -= 2
        out["notes"].append("an intermediate stage was invalid or a loft folded (craft notes)")
    out["points"]["integrity"] = max(0, integ)
    cl = (m.get("form") or {}).get("class")
    if cls:
        if not cl:
            out["points"]["silhouette"] = 0
            out["notes"].append(f"silhouette: no assessment ({(m.get('form') or {}).get('error', 'none')})")
        else:
            out["points"]["silhouette"] = round(MAX["silhouette"] * cl["score"])
            bad = [s["id"] for s in cl["signature"] if not s["ok"]]
            out["notes"].append(f"{cls}: class score {cl['score']:.2f} (outline {cl['parts']['outline']:.2f}, dev "
                                f"{cl['profile_dev'] * 100:.1f} %; proportions {cl['parts']['ratios']:.2f}; signature "
                                f"{cl['parts']['signature']:.2f}" + (f", missing {', '.join(bad)}" if bad else "") + ")")
    out["total"] = _total(out, cls)
    if cls and cl and cl["score"] < CLASS_BAR and out["total"] > CAP:
        out["notes"].append(f"capped at {CAP}: does not read as a {cl['label']} (class score {cl['score']:.2f} < "
                            f"{CLASS_BAR})")
        out["total"] = CAP
    if defects and out["total"] > DEFECT_CAP:
        out["notes"].append(f"capped at {DEFECT_CAP}: {', '.join(defects)}")
        out["total"] = DEFECT_CAP
    out["status"] = "pass" if out["total"] >= PASS else "below the bar"
    out["metrics"] = {k: m.get(k) for k in ("smallest_fillet_mm", "sharp_edge_fraction", "symmetry", "surface_mix",
                                           "solids", "build_s", "folds", "walls")}
    if cl:
        out["metrics"]["class"] = {k: cl[k] for k in ("score", "parts", "profile_dev", "ratios", "signature")}
    return out


def run(solutions: Path | None = None, only: set | None = None, exemplars_too: bool = True) -> list[dict]:
    from form import exemplars
    res = []
    for b in briefs():
        if only and b["id"] not in only:
            continue
        m = None
        if solutions and (solutions / f"{b['id']}.py").is_file():
            m = check(_load(solutions / f"{b['id']}.py"), f"bench-{b['id']}", product_class(b))
            src = "solution"
        elif exemplars_too and b.get("exemplar"):
            m = check(exemplars.load(b["exemplar"]), f"exemplar-{b['exemplar']}", product_class(b))
            src = f"exemplar {b['exemplar']}"
        elif exemplars_too and b.get("solution"):
            m = check(_load(HERE / "solutions" / f"{b['solution']}.py"), f"solution-{b['solution']}", product_class(b))
            src = f"solution {b['solution']}"
        else:
            src = "-"
        r = score(b, m)
        r["source"] = src
        res.append(r)
    return res


def table(res: list[dict]) -> str:
    cols = list(MAX)
    rows = ["| brief | source | " + " | ".join(cols) + " | total | status |", "|---|---|" + "---|" * len(cols) + "---|---|"]
    for r in res:
        p = r["points"]
        rows.append(f"| {r['id']} | {r['source']} | " + " | ".join(str(p.get(k, "")) for k in cols)
                    + f" | {r['total']} | {r['status']} |")
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
