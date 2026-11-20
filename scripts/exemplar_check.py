"""Build exemplar designs (or any design file) the way the kernel does, check them, and draw a four-view sheet.

    .venv/bin/python scripts/exemplar_check.py helmet knurled_knob          # exemplars by name
    .venv/bin/python scripts/exemplar_check.py path/to/design.py --png out/  # a design file; sheets into out/
    .venv/bin/python scripts/exemplar_check.py --all --json report.json      # every exemplar

For each design: valid B-rep, solids against the declared count, faces, build seconds, the critique metrics that
matter for quality (smallest fillet, sharp-edge fraction, free-form share, folds, thin walls), the product-class
silhouette score when the design names one, and the craft fallbacks the build took. A design that fails prints the
structured diagnosis (form/build_diag.py). Exit code 1 when any design fails to build or is invalid.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_file(path: Path):
    spec = importlib.util.spec_from_file_location(f"check_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    inst = mod.Design()
    inst.id = f"check:{path.stem}"
    return inst, getattr(mod, "META", {})


def check(target: str, png_dir: Path | None = None, product_class: str | None = None) -> dict:
    from form import critique, exemplars, kernel
    from form.recipes import RecipeError
    if target.endswith(".py"):
        recipe, meta = _load_file(Path(target))
        name = Path(target).stem
    else:
        recipe = exemplars.load(target)
        meta = next((e for e in exemplars.catalogue() if e["name"] == target), {})
        name = target
    cls = product_class or meta.get("product_class")
    key = f"check-{name}"
    old = kernel.resolve
    kernel.resolve = lambda rid: recipe
    kernel._cache.clear()
    out = {"name": name, "ok": False}
    t0 = time.perf_counter()
    try:
        model = kernel._build(key, recipe.defaults(), 0.05)
        kernel._cache[(key, 0.05)] = model
        out["build_s"] = round(time.perf_counter() - t0, 2)
        shape = model["shape"]
        out.update(valid=bool(shape.is_valid), solids=len(shape.solids()), declared=getattr(recipe, "solids", 1),
                   faces=len(shape.faces()), bbox=[round(b - a, 1) for a, b in zip(*model["bbox"])],
                   volume_cm3=round(model["volume"] / 1000, 2), craft_notes=model["craft_notes"],
                   features=sorted(model["by_feature"]))
        m = critique.op_critique_metrics(key, key, recipe.defaults(), 0.05, product_class=cls)
        out["metrics"] = {k: m.get(k) for k in ("smallest_fillet_mm", "sharp_edge_fraction", "surface_mix", "folds",
                                                "walls", "symmetry")}
        cl = (m.get("form") or {}).get("class")
        if cl:
            out["class_score"] = round(cl["score"], 3)
        out["ok"] = out["valid"] and out["solids"] == out["declared"]
        if png_dir is not None:
            from form import render as rendering
            view = kernel.op_view(key, key, recipe.defaults(), tol=0.05)
            feats = [{"id": f.id, "label": f.label} for f in recipe.features]
            pngs = [rendering.render_png(view, feats, v, None, size=(560, 420), title=f"{name} ({v})")
                    for v in ("iso", "iso_back", "front", "top")]
            png_dir.mkdir(parents=True, exist_ok=True)
            f = png_dir / f"{name}.png"
            f.write_bytes(rendering.contact_sheet(pngs, cols=2))
            out["png"] = str(f)
    except RecipeError as e:
        out["build_s"] = round(time.perf_counter() - t0, 2)
        out["error"] = e.public()
    except Exception as e:                                       # report and carry on with the next design
        out["build_s"] = round(time.perf_counter() - t0, 2)
        out["error"] = {"message": f"{type(e).__name__}: {e}"}
    finally:
        kernel.resolve = old
        kernel._cache.clear()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--png", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--product-class")
    a = ap.parse_args(argv)
    from form import exemplars
    targets = [e["name"] for e in exemplars.catalogue()] if a.all else a.targets
    res, bad = [], 0
    for t in targets:
        r = check(t, a.png, a.product_class)
        res.append(r)
        if not r["ok"]:
            bad += 1
        line = (f"{r['name']:28s} {'ok ' if r['ok'] else 'BAD'} {r.get('build_s', 0):6.2f} s  "
                + (f"solids {r['solids']}/{r['declared']} faces {r['faces']} bbox {r['bbox']}"
                   + (f" class {r['class_score']}" if 'class_score' in r else "")
                   if "error" not in r else json.dumps(r["error"], default=str)[:900]))
        print(line, flush=True)
        if r.get("craft_notes"):
            print("    craft notes: " + "; ".join(r["craft_notes"])[:600])
        if r.get("metrics"):
            mm = r["metrics"]
            print(f"    fillet {mm.get('smallest_fillet_mm')} sharp {mm.get('sharp_edge_fraction')} "
                  f"folds {(mm.get('folds') or {}).get('folds')} walls {json.dumps(mm.get('walls'), default=str)[:160]}")
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
