"""Export the design the home page's hero draws: the sensor case, built and checked by Form Studio's own engine.

    FORM_DATA=.dev/web/case FORM_CONFIG=/nonexistent PYTHONPATH=. .venv/bin/python site/tools/export_case.py

The design is the `enclosure` building block at its defaults, named "Sensor case" and made for printing: the same
design the app's own pictures show. The script creates it in the scratch data folder (when it is not there yet), runs
the pipeline and writes what the engine returned. Nothing the hero shows is typed by hand.

Writes into site/assets/data/:
    case.glb    the head revision, one mesh per feature (the faces that feature made); the page draws each mesh's
                own outline and creases as its edges
    case.json   features in build order, size, faces, volume, kernel, checks with the engine's own wording, the fit
                model, the next actions, and the slice summary when a slicer Form Studio can drive is installed

A design that was not sliced gets no slice in the output, and the page then draws none.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_site_data import GLB, OUT, feature_meshes, weld  # noqa: E402

from form import config  # noqa: E402
from form.studio import Studio  # noqa: E402

NAME = "Sensor case"
RECIPE = "enclosure"


def dur(s: float) -> str:
    m = round(s / 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Studio(config.load())
    try:
        found = [x["id"] for x in s.list() if x.get("name") == NAME]
        pid = found[0] if found else s.create(NAME, RECIPE, purpose="print")["id"]
        s.run_sync(pid)
        p = s.load(pid)
        rev = s.rev(p)
        v = s.view(p)
        recipe = s.recipe(p)
        state = s.state(pid)
        order = [f.id for f in recipe.features]
        feats = {f.id: {"label": f.label, "role": f.role, "doc": f.doc} for f in recipe.features}
        lo = np.asarray(v["bbox"][0]); hi = np.asarray(v["bbox"][1]); span = np.maximum(hi - lo, 1e-6)

        g = GLB()
        by_feature: dict = {}
        part_of: dict = {}
        for (fid, part), (P, T) in feature_meshes(v).items():
            Ps, Ts, n = by_feature.setdefault(fid, ([], [], [0]))
            Ps.append(P); Ts.append(T + n[0]); n[0] += len(P)
            part_of[fid] = part
        built = sorted(by_feature, key=lambda k: order.index(k) if k in order else 99)
        for fid in built:
            P, T = weld(np.concatenate(by_feature[fid][0]), np.concatenate(by_feature[fid][1]))
            g.add(fid, P, T, lo, span, {"feature": fid, "part": part_of[fid], **feats.get(fid, {})})
        nb = g.write(OUT / "case.glb", {"project": pid, "rev": rev["n"]})

        prov = rev["provenance"]
        known = [q for q in recipe.params if q.group == "brief"]
        checks = (state.get("checks") or {}).get("checks") or []
        roll = (state.get("checks") or {}).get("rollup") or {}
        fit = state.get("fit") or {}
        sl = state.get("slice") or None
        asm = v.get("assembly") or {}
        out = {
            "id": pid, "name": p.get("name"), "rev": rev["n"], "recipe": RECIPE, "purpose": "print",
            "features": [{"id": i, **feats[i], "built": i in by_feature, "part": part_of.get(i)} for i in order],
            "bbox": v["bbox"], "size": [round(float(x), 1) for x in span], "volume_cm3": round(v["volume_mm3"] / 1000, 1),
            "faces": v["faces"], "triangles": v.get("triangles"), "build_ms": round(v["timing"]["build_s"] * 1000),
            "kernel": v["kernel"], "parts": [{"id": x["id"], "label": x["label"]} for x in asm.get("parts", [])],
            "known": {"measured": sum(1 for q in known if (prov.get(q.key) or {}).get("source") == "measured"), "of": len(known)},
            "checks": [{k: c.get(k) for k in ("id", "label", "status", "value", "detail", "evidence", "feature")} for c in checks],
            "rollup": roll,
            "fit": {"label": fit.get("label"), "yield": fit.get("yield"), "model": fit.get("model")} if fit else None,
            "actions": [{k: a.get(k) for k in ("id", "title", "why", "cost")} for a in state.get("actions") or []],
            "exports": sorted((state.get("exports") or {}).get("files", {}).keys()) if isinstance((state.get("exports") or {}).get("files"), dict) else None,
            "gate": {k: state["gate"].get(k) for k in ("ready", "warnings_to_acknowledge", "evidence")} if state.get("gate") else None,
        }
        if sl:
            pr = state["printer"]
            out["slice"] = {"time_s": sl.get("time_s"), "time": dur(sl["time_s"]) if sl.get("time_s") else None,
                            "filament_g": sl.get("filament_g"), "layers": sl.get("layers"),
                            "slicer": (pr.get("slicer") or {}).get("label"), "slicer_version": (pr.get("slicer") or {}).get("version"),
                            "printer": (state["calibration"]["profile"] or "").split(" · ")[0]}
        (OUT / "case.json").write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        print("case.glb", nb, "bytes;", len(built), "of", len(order), "features with faces;", out["faces"], "faces;",
              out["volume_cm3"], "cm3;", roll, "; slice", (out.get("slice") or {}).get("time"))
    finally:
        getattr(s, "close", lambda: None)()
    return 0


if __name__ == "__main__":
    sys.exit(main())
