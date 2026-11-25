"""Build one recipe in the real CAD kernel the way Form Studio does, and write what happened as data and pictures.

    python scripts/ci/build_recipe.py --builtin dock --out OUT
    python scripts/ci/build_recipe.py --source recipe.py --out OUT [--variants] [--slice] [--turntable]
    python scripts/ci/build_recipe.py --archive design.formstudio --out OUT --turntable
    python scripts/ci/build_recipe.py --repo-root ../base --builtin hook --out OUT    # build with another checkout's code

Every set of parameter values (the defaults, and with --variants a smaller and a larger one) is created as a design,
run through the pipeline (solid, STEP and STL, checks, and with --slice the slice at the defaults) and rendered.

OUT/result.json (schema 1):
    {"schema": 1, "ok": bool, "verdict": "valid" | "needs-changes", "problems": [str],
     "recipe": {"title", "summary", "kind", "params": [...], "features": [...]},
     "sets": [{"name", "values", "state": "built" | "rejected" | "failed", "error", "seconds", "volume_mm3",
               "bbox_mm", "solid_mass_g", "checks": [{"id","label","status","value","evidence"}], "rollup",
               "slice": {...} | null, "image"}],
     "images": {"preview": "preview.png", "sheet": "sheet.png", "turntable": "turntable.gif"},
     "environment": {"form", "kernel", "slicer"}, "source_sha256", "seconds"}

Exit code 0 when the file was written, whatever the verdict; 2 when the inputs were unusable.
This script runs submitted code. In CI it runs inside scripts/ci/sandbox.sh: another user, no network, no tokens.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

PLA_G_PER_MM3 = 1.24e-3


def _err(e) -> dict:
    if hasattr(e, "public"):
        try:
            pub = e.public()
            return {k: pub.get(k) for k in ("message", "hint", "feature", "params") if pub.get(k)}
        except Exception:
            pass
    return {"message": f"{type(e).__name__}: {e}"[:2000]}


def _variants(recipe) -> list[tuple[str, dict]]:
    """The defaults, then the measured (brief) dimensions halfway to their minimum and to their maximum."""
    params = [p for p in recipe.params if p.max > p.min]
    brief = [p for p in params if p.group == "brief"] or [p for p in params if p.group in ("interface", "form")]
    out = [("defaults", {})]
    for name, side in (("smaller", "min"), ("larger", "max")):
        vals = {}
        for p in brief[:6]:
            bound = getattr(p, side)
            v = p.default + 0.5 * (bound - p.default)
            step = p.step or 0.1
            v = round(round(v / step) * step, 6)
            if v != p.default:
                vals[p.key] = v
        if vals:
            out.append((name, vals))
    return out


def _render(st, p, out: Path, stem: str, size=(960, 560), views=("iso",)) -> dict:
    from form import render
    v = st.view(p)
    feats = [{"id": f.id, "label": f.label} for f in st.recipe(p).features]
    title = f"{p['name']} - r{p['head']:02d}"
    files = {}
    for view in views:
        if view == "sheet":
            pngs = [render.render_png(v, feats, vw, None, size=(640, 460), title=title) for vw in ("iso", "front", "top", "right")]
            data = render.contact_sheet(pngs)
        else:
            data = render.render_png(v, feats, view, None, size=size, title=title)
        f = out / f"{stem}.png" if view == "iso" else out / f"{stem}-{view}.png"
        f.write_bytes(data)
        files[view] = f.name
    return files


def _set_result(st, pid: str, job: dict) -> dict:
    s = st.state(pid)
    p = s["project"]
    res = {"seconds": {step["node"]: step.get("seconds") for step in job.get("steps", []) if step.get("seconds") is not None},
           "steps": {step["node"]: step["state"] for step in job.get("steps", [])}}
    errors = [step.get("error") for step in job.get("steps", []) if step.get("state") == "failed" and step.get("error")]
    try:
        g = st.head_summary(p)
        lo, hi = g["bbox"]
        res["volume_mm3"] = round(g["volume_mm3"], 2)
        res["bbox_mm"] = [round(b - a, 2) for a, b in zip(lo, hi)]
        res["solid_mass_g"] = round(g["volume_mm3"] * PLA_G_PER_MM3, 2)
    except Exception as e:
        errors.append(_err(e))
    if s.get("checks"):
        res["checks"] = [{k: c.get(k) for k in ("id", "label", "status", "value", "evidence")} for c in s["checks"]["checks"]]
        res["rollup"] = s["checks"].get("rollup")
    sl = s.get("slice")
    if sl:
        presets = sl.get("presets") or {}
        res["slice"] = {"ok": True, "time_s": sl.get("time_s"), "filament_g": sl.get("filament_g"), "layers": sl.get("layers"),
                        "supports": sl.get("support_used"), "slicer": sl.get("slicer_name"), "slicer_kind": sl.get("slicer_kind"),
                        "slicer_version": sl.get("slicer_version"), "seconds": sl.get("seconds"),
                        "presets": {k: (v or {}).get("name") for k, v in presets.items()}}
    elif job.get("steps") and any(x["node"] == "slice" for x in job["steps"]):
        step = next(x for x in job["steps"] if x["node"] == "slice")
        res["slice"] = {"ok": False, "state": step["state"], "error": step.get("error") or
                        {"message": s["status"]["slice"].get("unavailable") or "not sliced"}}
    res["state"] = "failed" if errors else "built"
    if errors:
        res["error"] = errors[0]
    return res


def build(args) -> dict:
    t_all = time.perf_counter()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"schema": 1, "ok": False, "verdict": "needs-changes", "problems": [], "sets": [], "images": {}}
    from form import __version__, config, slicer
    from form.studio import Studio
    cfg = config.load()
    st = Studio(cfg)
    try:
        result["environment"] = {"form": __version__}
        try:
            result["environment"]["kernel"] = st.kernel_id()
        except Exception as e:
            result["problems"].append(f"The CAD kernel did not start: {_err(e)['message']}")
            return result
        sres = st.slicer_info()
        result["environment"]["slicer"] = {k: v for k, v in slicer.public(sres).items()
                                           if k in ("available", "kind", "name", "version", "reason")} if sres else None
        slicer_ok = bool(sres and sres.get("available"))

        source = language = None
        title = args.name or (st.recipes[args.builtin].title if args.builtin and args.builtin in st.recipes else "")
        if args.source:
            f = Path(args.source)
            source = f.read_text(encoding="utf-8")
            language = "openscad" if f.suffix.lower() == ".scad" else "python"
            result["source_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
            from form import recipe_lib
            meta = recipe_lib.read_python(source) if language == "python" else recipe_lib.read_scad(source)
            title = title or meta.get("title") or ""
            result["problems"] += meta.get("problems", [])
            if meta.get("problems"):
                return result

        # the first design: defaults (or the archive's own head revision)
        def create(values: dict, name: str):
            if args.archive:
                from form import bundle
                return bundle.import_file(st, Path(args.archive))["id"]
            if source is not None:
                return st.create_design(name, source, values=values, language=language)["id"]
            return st.create(name, args.builtin, "", values)["id"]

        t0 = time.perf_counter()
        try:
            pid = create({}, title or "Recipe")
        except Exception as e:
            result["problems"].append(f"It does not build at its default values: {_err(e)['message']}")
            result["sets"].append({"name": "defaults", "values": {}, "state": "failed", "error": _err(e)})
            return result
        load_s = round(time.perf_counter() - t0, 3)
        p = st.load(pid)
        recipe = st.recipe(p)
        result["recipe"] = {"title": recipe.title, "summary": getattr(recipe, "summary", ""), "kind": language or "python",
                            "builtin": bool(args.builtin), "id": args.builtin or None,
                            "params": [{k: getattr(q, k) for k in ("key", "label", "default", "min", "max", "unit", "group")}
                                       for q in recipe.params],
                            "features": [{"id": f.id, "label": f.label} for f in recipe.features]}
        sets = _variants(recipe) if args.variants and not args.archive else [("defaults", {})]
        for i, (name, values) in enumerate(sets):
            entry = {"name": name, "values": values}
            try:
                if i > 0:
                    t0 = time.perf_counter()
                    try:
                        pid = create(values, f"{title or 'Recipe'} ({name})")
                    except Exception as e:
                        e_ = _err(e)
                        kernel_fault = "kernel" in e_.get("message", "").lower() or "Unexpected" in e_.get("message", "")
                        entry.update({"state": "failed" if kernel_fault else "rejected", "error": e_})
                        result["sets"].append(entry)
                        continue
                    load_s = round(time.perf_counter() - t0, 3)
                nodes = None if (i == 0 and args.slice) else ["geometry", "exports", "checks"]
                job = st.run_sync(pid, nodes)
                entry.update(_set_result(st, pid, job))
                entry["seconds"]["load"] = load_s
                if entry["state"] == "built":
                    p = st.load(pid)
                    stem = "preview" if i == 0 else name
                    views = ("iso", "sheet") if i == 0 and args.sheet else ("iso",)
                    imgs = _render(st, p, out, stem, views=views)
                    entry["image"] = imgs.get("iso")
                    if i == 0:
                        result["images"]["preview"] = imgs.get("iso")
                        if "sheet" in imgs:
                            result["images"]["sheet"] = imgs["sheet"]
                        if args.turntable:
                            from form import animate
                            animate.turntable(st, p, out / "turntable.gif", frames=24, size=(480, 360))
                            result["images"]["turntable"] = "turntable.gif"
            except Exception as e:
                entry.update({"state": "failed", "error": _err(e)})
                traceback.print_exc()
            result["sets"].append(entry)

        d0 = result["sets"][0]
        if d0.get("state") != "built":
            result["problems"].append("It does not build at its default values: " + (d0.get("error") or {}).get("message", "unknown error"))
        fails = [c for c in d0.get("checks") or [] if c.get("status") == "FAIL"]
        for c in fails:
            result["problems"].append(f"Check failed at the defaults: {c['label']} ({c['value']})")
        for s in result["sets"][1:]:
            if s.get("state") == "failed":
                result["problems"].append(f"The {s['name']} parameter set crashed instead of being built or refused: "
                                          + (s.get("error") or {}).get("message", ""))
        if args.slice and slicer_ok and d0.get("state") == "built" and not (d0.get("slice") or {}).get("ok"):
            result["problems"].append("The slicer could not slice it at the default values: "
                                      + ((d0.get("slice") or {}).get("error") or {}).get("message", "no slice"))
        if args.archive:
            result["recipe"]["kind"] = "archive"
        result["ok"] = not result["problems"]
        result["verdict"] = "valid" if result["ok"] else "needs-changes"
        return result
    finally:
        result["seconds"] = round(time.perf_counter() - t_all, 2)
        (out / "result.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        try:
            st.kernel.stop()
        except Exception:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--builtin", help="a built-in recipe id")
    src.add_argument("--source", help="a recipe file (.py or .scad)")
    src.add_argument("--archive", help="a .formstudio or .formproj archive")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", help="design name shown in the pictures (default: the recipe's title)")
    ap.add_argument("--repo-root", help="import Form Studio from this checkout instead of the installed one")
    ap.add_argument("--variants", action="store_true", help="also build a smaller and a larger parameter set")
    ap.add_argument("--slice", action="store_true", help="slice the defaults when a slicer is available")
    ap.add_argument("--sheet", action="store_true", help="also render the four-view sheet of the defaults")
    ap.add_argument("--turntable", action="store_true", help="also write a turntable GIF of the defaults")
    a = ap.parse_args(argv)
    if a.repo_root:
        sys.path.insert(0, str(Path(a.repo_root).resolve()))
    os.environ.setdefault("FORM_NO_UPDATE_CHECK", "1")
    r = build(a)
    print(json.dumps({"verdict": r["verdict"], "problems": r["problems"], "seconds": r.get("seconds")}, indent=1))
    return 0 if (Path(a.out) / "result.json").exists() else 2


if __name__ == "__main__":
    sys.exit(main())
