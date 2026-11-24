"""The game bench: six original game-asset briefs (tests/design_bench/game_briefs.json) and one deliberately bad
control, made end to end, measured, rendered for review and written to docs/GAME_BENCH.md.

    python scripts/game_bench.py                       # every brief and the control; Blender from the usual places
    python scripts/game_bench.py --only treasure_chest # one brief (no report is written)
    python scripts/game_bench.py --out DIR             # renders, review sheets and the contact sheet go there
    python scripts/game_bench.py --refine on --scores tests/design_bench/game_scores_refine.json --json on.json
    python scripts/game_bench.py --compare on.json off.json          # docs/GAME_BENCH.md with both runs

Each brief names a game exemplar (form/exemplars/game/): a cage made by model_mesh ops (blocks, bevel, inset,
panel_line, kit_place; bake-only detail high_only) or a kernel design. The bench creates the design with the purpose
"game" (Studio.create_design), exports STEP, measures the SubD-to-CAD deviation per cage part, makes the game asset
(form/game: the brief's preset and budgets, the exemplar's materials) and measures it for the game critic
(form/critique.game_evidence: bevel coverage, materials, value contrast, detail scales, silhouette, wear).

Review: for every asset it renders LOD0 lit from four views and a 64 px silhouette into a review sheet with no name
on it (review/<letter>.png, letters shuffled with a fixed seed, the control among them). Scores come from
tests/design_bench/game_scores.json: three blind passes over those sheets, written by whoever scored them (the file
says who); each item takes the median of the passes, capped by the asset's game evidence. Without that file a brief
is "not scored". Nothing is invented: every number in the report is from this run, failures included.

--refine on: after the design is created, the refinement engine (form/refine/engine.py) refines it as it would in
the app (cage and material operators for a cage, material operators for a kernel design; candidates judged on the
cage geometry and materials, one bake at the end checked by the validator and the budgets), and the game asset is
made from the refined head: the game pipeline replays REFINE_OPS on the low cage and keeps the bake source.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BRIEFS = ROOT / "tests" / "design_bench" / "game_briefs.json"
SCORES = ROOT / "tests" / "design_bench" / "game_scores.json"
DOC = ROOT / "docs" / "GAME_BENCH.md"
REVIEW_SEED = 20261124

RENDER = r'''
import math, sys
import bpy
from mathutils import Vector
glb, out = sys.argv[sys.argv.index("--") + 1:][:2]
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
sc = bpy.context.scene
sc.render.resolution_x = sc.render.resolution_y = 600
names = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
sc.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in names else "BLENDER_EEVEE_NEXT"
world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.62, 0.63, 0.65, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55
def sun(name, energy, rx, rz, col=(1, 1, 1)):
    s = bpy.data.objects.new(name, bpy.data.lights.new(name, "SUN")); s.data.energy = energy; s.data.color = col
    s.data.angle = math.radians(8)
    s.rotation_euler = (math.radians(rx), 0, math.radians(rz)); sc.collection.objects.link(s)
sun("key", 3.2, 48, 32, (1.0, 0.96, 0.9))
sun("fill", 0.9, 65, -120, (0.85, 0.9, 1.0))
sun("rim", 1.6, 115, 160)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "PERSP"; cam.data.lens = 70
lods = sorted([o for o in meshes if "_LOD" in o.name], key=lambda o: o.name)
lod0 = lods[0]
pts = [lod0.matrix_world @ Vector(c) for c in lod0.bound_box]
c = sum(pts, Vector()) / 8
r = max((p - c).length for p in pts)
VIEWS = {"three_quarter": (35, 20), "front": (0, 8), "side": (90, 8), "back": (215, 25)}
def look(az, el, dist):
    a, e = math.radians(az), math.radians(el)
    cam.location = c + Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))) * dist
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
dist = r / math.tan(math.atan(18 / 70)) * 1.12
for o in meshes:
    o.hide_render = True
lod0.hide_render = False
for name, (az, el) in VIEWS.items():
    look(az, el, dist)
    sc.render.filepath = f"{out}/lod0_{name}.png"
    bpy.ops.render.render(write_still=True)
look(35, 20, dist)
lod0.hide_render = True
last = lods[-1]
last.hide_render = False
sc.render.filepath = f"{out}/lod{len(lods) - 1}_three_quarter.png"
bpy.ops.render.render(write_still=True)
last.hide_render = True
wire = bpy.data.materials.new("wire"); wire.use_nodes = True
wire.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.05, 0.05, 0.06, 1)
clay = bpy.data.materials.new("clay"); clay.use_nodes = True
clay.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.75, 0.74, 0.7, 1)
w = lod0.copy(); w.data = lod0.data.copy(); sc.collection.objects.link(w)
w.data.materials.clear(); w.data.materials.append(wire)
m = w.modifiers.new("wf", "WIREFRAME"); m.thickness = r * 0.0018; m.use_replace = True
k = lod0.copy(); k.data = lod0.data.copy(); sc.collection.objects.link(k)
k.data.materials.clear(); k.data.materials.append(clay)
w.hide_render = k.hide_render = False
sc.render.filepath = f"{out}/lod0_wire.png"
bpy.ops.render.render(write_still=True)
print("RENDERED")
'''


# ---- measuring -------------------------------------------------------------------------------------------------------

def routes(brief: dict) -> dict:
    from form import router
    rows = [{"feature": f["id"], **{k: v for k, v in router.feature_route({**f, "label": f["label"]}).items()
                                     if k in ("route", "because", "confident", "evidence")}} for f in brief["features"]]
    counts: dict = {}
    for r in rows:
        counts[r["route"]] = counts.get(r["route"], 0) + 1
    main = max(counts, key=lambda k: (counts[k], k != "kernel"))
    return {"features": rows, "main": main, "expected": brief["route"], "agrees": main == brief["route"]}


def deviation(cage) -> dict:
    """Per connected cage part: max and RMS distance between the CAD patches and the limit surface."""
    from form.craft import subd_report
    from form.game import pipeline
    out = []
    for part in pipeline.split_cage(cage):
        d = subd_report.deviation(part.to_subd())
        out.append({k: d[k] for k in ("max_mm", "rms_mm", "max_per_100mm", "size_mm", "exact", "irregular_points",
                                      "level")})
    worst = max(out, key=lambda d: d["max_per_100mm"])
    return {"parts": len(out), "max_mm": max(d["max_mm"] for d in out), "rms_mm": max(d["rms_mm"] for d in out),
            "max_per_100mm": worst["max_per_100mm"], "exact_parts": sum(d["exact"] for d in out),
            "irregular_points": sum(d["irregular_points"] for d in out)}


def step_check(path: Path) -> dict:
    from build123d import import_step
    back = import_step(str(path))
    sols = back.solids()
    return {"valid": bool(back.is_valid) and len(sols) >= 1, "solids": len(sols),
            "volume_mm3": float(sum(s.volume for s in sols)), "bytes": path.stat().st_size,
            "faces": len(back.faces())}


def render(glb: Path, out: Path, blender: str) -> dict:
    script = out / "_render.py"
    script.write_text(RENDER, encoding="utf-8")
    r = subprocess.run([blender, "-b", "--factory-startup", "-noaudio", "--python", str(script), "--", str(glb), str(out)],
                       capture_output=True, text=True, timeout=900)
    if "RENDERED" not in r.stdout:
        return {}
    return {p.stem: str(p) for p in out.glob("*.png")}


def silhouette_png(asset_dir: Path, path: Path, px: int = 64) -> None:
    """LOD0's outline from three quarters, at 64 px: the read at a glance."""
    import numpy as np
    from PIL import Image

    from form import critique
    z = np.load(asset_dir / "lods" / "lod0.npz")
    m = critique.silhouettes(z["P"], z["T"], px, {"three_quarter": critique.GAME_VIEWS["three_quarter"]})
    Image.fromarray(np.where(m["three_quarter"], 20, 235).astype("uint8")).save(path)


def review_sheet(renders: dict, sil: Path, path: Path) -> None:
    """Four lit views of LOD0 and the 64 px silhouette, with no name: what a blind pass looks at."""
    from PIL import Image, ImageDraw
    T, pad = 420, 8
    sheet = Image.new("RGB", (pad + 2 * (T + pad) + 140, pad + 2 * (T + pad)), (236, 235, 231))
    for k, v in enumerate(("three_quarter", "front", "side", "back")):
        im = Image.open(renders[f"lod0_{v}"]).convert("RGB")
        im.thumbnail((T, T))
        sheet.paste(im, (pad + (k % 2) * (T + pad), pad + (k // 2) * (T + pad)))
    s = Image.open(sil).convert("RGB")
    sheet.paste(s.resize((128, 128), Image.NEAREST), (pad + 2 * (T + pad), pad + 20))
    sheet.paste(s, (pad + 2 * (T + pad), pad + 160))
    ImageDraw.Draw(sheet).text((pad + 2 * (T + pad), pad + 4), "64 px outline", fill=(40, 40, 40))
    sheet.save(path)


def refine_brief(st, pid: str, b: dict, row: dict) -> None:
    from form.refine import engine
    from form.refine.ledger import Ledger
    t = time.time()
    try:
        r = engine.refine(st, pid, ledger=Ledger.memory(),
                          game={"budgets": b["budgets"], "preset": b["preset"]})
        row["refine"] = {"seconds": round(time.time() - t, 1), "skipped": r.get("skipped"),
                         "stopped": r.get("stopped"), "base": (r.get("base") or {}).get("total"),
                         "final": (r.get("final") or {}).get("total"), "head": r.get("head"),
                         "final_check": r.get("final_check"), "measure": r.get("measure"),
                         "applied": [{"operator": a["operator"], "label": a["label"], "kind": a.get("kind"),
                                      "reason": a.get("reason"), "deltas": a.get("deltas")} for a in r.get("applied", [])],
                         "rejected": [{"operator": x["operator"], "why": (x.get("why") or [""])[0][:200]}
                                      for x in r.get("rejected", [])][:12],
                         "commit_error": r.get("commit_error")}
    except Exception as e:                                   # noqa: BLE001 - a failure is a result
        row["refine"] = {"error": f"{type(e).__name__}: {e}"[:400], "seconds": round(time.time() - t, 1)}


def run_brief(st, b: dict, cfg: dict, out: Path, scores: dict, blender: str | None, refine: bool = False) -> dict:
    from form import critique, game
    from form.exemplars import game as gex
    row = {"id": b["id"], "title": b["title"], "preset": b["preset"], "budgets": b["budgets"],
           "control": bool(b.get("control"))}
    t0 = time.time()
    row["route"] = routes(b) if b.get("features") else None
    try:
        ex = gex.make(b["exemplar"], st.cfg)
    except Exception as e:                                   # noqa: BLE001 - a failed model is a result
        row["model"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}
        row["seconds"] = round(time.time() - t0, 1)
        return row
    cage = ex["cage"]
    row["model"] = {"ok": True, "seconds": ex["seconds"], "ops": len(ex["ops"] or []),
                    "high_only_ops": sum(1 for o in ex["ops"] or [] if o.get("high_only"))}
    row["originality"] = ex["originality"]
    if cage is not None:
        row["cage"] = {"points": int(len(cage.V)), "faces": int(len(cage.F)), "creases": len(cage.creases),
                       "regions": sorted(cage.regions),
                       "high_faces": int(len(cage.high.F)) if cage.high is not None else 0}
    try:
        t = time.time()
        p = st.create_design(b["title"], ex["source"], b["brief"], purpose="game")
        j = st.run_sync(p["id"], ["geometry", "exports"])
        row["build"] = {"ok": j["state"] == "done", "seconds": round(time.time() - t, 2)}
        if j["state"] != "done":
            row["build"]["error"] = str(j.get("error") or j)[:300]
        p = st.load(p["id"])
        if refine and row["build"]["ok"]:
            refine_brief(st, p["id"], b, row)
            j = st.run_sync(p["id"], ["geometry", "exports"])
            p = st.load(p["id"])
    except Exception as e:                                   # noqa: BLE001
        row["build"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300], "seconds": round(time.time() - t, 2)}
        row["seconds"] = round(time.time() - t0, 1)
        return row
    row["pid"] = p["id"]
    keys = st.keys(p)
    exr = st.read(p, "exports", keys["exports"]) or {}
    stp = exr.get("files", {}).get("step")
    try:
        row["step"] = step_check(st.apath(p, "exports", keys["exports"]) / stp["name"]) if stp else {
            "valid": False, "error": "no STEP"}
    except Exception as e:                                   # noqa: BLE001
        row["step"] = {"valid": False, "error": str(e)[:200]}
    try:
        row["deviation"] = deviation(cage) if cage is not None else None
    except Exception as e:                                   # noqa: BLE001
        row["deviation"] = {"error": str(e)[:200]}
    gdir = None
    try:
        t = time.time()
        res = game.game_asset(st, p["id"], preset=b["preset"], budgets=b["budgets"], texture_px=cfg["texture_px"],
                              bake=cfg["bake"], materials=ex["materials"])
        gdir = Path(res["dir"])
        rep = json.loads((gdir / "report.json").read_text(encoding="utf-8"))
        row["game"] = {"ok": True, "seconds": round(time.time() - t, 1), "validation": res["validation"],
                       "lods": [{k: r[k] for k in ("lod", "triangles", "budget", "source")} for r in res["lods"]],
                       "bake_seconds": (res.get("bake") or {}).get("total_seconds"), "uv": res["uv"],
                       "collision": res["collision"], "dir": res["dir"], "notes": res.get("notes", []),
                       "size_mm": rep["size_mm"], "high_source": rep.get("high_source"),
                       "checks": [{k: c.get(k) for k in ("id", "lod", "status", "value")}
                                  for c in rep["validation"]["checks"]]}
    except Exception as e:                                   # noqa: BLE001
        row["game"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}
    if gdir is not None:
        try:
            row["evidence"] = critique.game_evidence(gdir)
        except Exception as e:                               # noqa: BLE001
            row["evidence"] = {"error": f"{type(e).__name__}: {e}"[:300]}
        if blender:
            d = out / b["id"]
            d.mkdir(parents=True, exist_ok=True)
            row["renders"] = render(gdir / f"{rep['asset']}.glb", d, blender)
            nm = gdir / "textures" / f"{rep['asset']}_normal.png"
            if nm.is_file():
                shutil.copy2(nm, d / "normal.png")
                row["renders"]["normal"] = str(d / "normal.png")
            silhouette_png(gdir, d / "silhouette64.png")
            row["renders"]["silhouette64"] = str(d / "silhouette64.png")
    try:
        sc = (scores.get("passes") or {}).get(b["id"])
        c = critique.run(st, p["id"], aesthetic={"passes": sc} if sc else None, game_dir=str(gdir) if gdir else None)
        a = c["aesthetic"]
        row["aesthetic"] = {"mean": a["mean"], "passed": a["passed"], "scored": bool(sc), "passes": len(sc or []),
                            "items": {i["id"]: {"score": i["score"], "cap": i["cap"], "final": i["final"],
                                                "why": i["why"], "passes": i.get("passes")} for i in a["items"]}}
    except Exception as e:                                   # noqa: BLE001
        row["aesthetic"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    row["seconds"] = round(time.time() - t0, 1)
    return row


def review_letters(ids: list[str]) -> dict:
    """{brief id: letter}: a fixed shuffle, so a blind pass cannot tell the briefs (or the control) by order."""
    ids = sorted(ids)
    random.Random(REVIEW_SEED).shuffle(ids)
    return {i: chr(ord("A") + k) for k, i in enumerate(ids)}


def write_reviews(rows: list, out: Path) -> dict:
    letters = review_letters([r["id"] for r in rows if (r.get("renders") or {}).get("lod0_back")])
    rd = out / "review"
    rd.mkdir(parents=True, exist_ok=True)
    for r in rows:
        if r["id"] in letters:
            review_sheet(r["renders"], Path(r["renders"]["silhouette64"]), rd / f"{letters[r['id']]}.png")
    (out / "review_key.json").write_text(json.dumps(letters, indent=1), encoding="utf-8")
    return letters


def contact_sheet(rows: list, path: Path) -> None:
    from PIL import Image, ImageDraw
    cols = ("lod0_three_quarter", "lod0_front", "lod0_back", "lod3_three_quarter", "lod0_wire", "normal", "silhouette64")
    W, pad, head = 250, 8, 40
    sheet = Image.new("RGB", (pad + len(cols) * (W + pad), pad + len(rows) * (W + head + pad)), (244, 243, 239))
    dr = ImageDraw.Draw(sheet)
    for i, r in enumerate(rows):
        y = pad + i * (W + head + pad)
        g = r.get("game") or {}
        a = r.get("aesthetic") or {}
        ev = r.get("evidence") or {}
        val = (g.get("validation") or {})
        fails = sorted({c["id"] for c in val.get("failed", [])})
        line1 = (f"{r['title']}{'  (CONTROL)' if r.get('control') else ''}  ·  {r['preset']}  ·  LOD tris "
                 f"{[l['triangles'] for l in g.get('lods') or []]}  ·  checks "
                 f"{'PASS' if val.get('ok') else 'FAIL ' + ', '.join(fails) if g.get('ok') else 'not built'}")
        line2 = (f"rubric {a.get('mean') if a.get('mean') is not None else 'not scored'}"
                 f" {'(passes gate)' if a.get('passed') else '(below gate)' if a.get('mean') is not None else ''}  ·  "
                 + (f"bevel {ev['edges']['coverage']:.0%}  materials {ev['materials']['count']}  contrast "
                    f"{ev['value_contrast']}  scales {ev['scales']['count']}/3  silhouette "
                    f"{ev['silhouette']['complexity']:.3f}  wear {'yes' if ev['wear']['present'] else 'no'}"
                    if ev.get("edges") else "no game evidence"))
        dr.text((pad, y + 4), line1, fill=(30, 30, 30))
        dr.text((pad, y + 20), line2, fill=(30, 30, 30) if a.get("passed") or r.get("control") else (150, 30, 20))
        for k, c in enumerate(cols):
            f = (r.get("renders") or {}).get(c)
            if not f:
                continue
            im = Image.open(f).convert("RGB")
            im = im.resize((W, W), Image.NEAREST) if c == "silhouette64" else im
            im.thumbnail((W, W))
            sheet.paste(im, (pad + k * (W + pad), y + head))
    sheet.save(path)


def fmt(v, d=2):
    return "—" if v is None else f"{v:.{d}f}" if isinstance(v, float) else str(v)


def _ok(r):
    g = r.get("game") or {}
    return bool(r.get("build", {}).get("ok") and g.get("ok") and (g.get("validation") or {}).get("ok")
                and (r.get("step") or {}).get("valid"))


def write_doc(rows: list, cfg: dict, meta: dict, scores: dict) -> None:
    real = [r for r in rows if not r.get("control")]
    ctrl = [r for r in rows if r.get("control")]
    scored = [r for r in real if (r.get("aesthetic") or {}).get("mean") is not None]
    ge4 = [r for r in scored if r["aesthetic"]["mean"] >= 4.0]
    lt3 = [r for r in scored if r["aesthetic"]["mean"] < 3.0]
    L = ["# Game bench", "",
         f"Six original game-asset briefs ({BRIEFS.relative_to(ROOT)}) and one deliberately bad control, made end to "
         f"end (`python scripts/game_bench.py`) from the game exemplars in form/exemplars/game/, run {meta['date']} "
         f"on {meta['machine']} with Blender {meta['blender']}. Textures {cfg['texture_px']} px, the {cfg['bake']} "
         "bake. Every number below is from that run; failures are published as they came out. Budgets and "
         "thresholds are proposed values, not engine rules.", "",
         "## Result", ""]
    L.append(f"- Rubric (median of three blind passes, capped by the game evidence): "
             + (f"{len(ge4)} of {len(real)} at 4.0 or more; {len(lt3)} under 3.0; " if scored else "not scored; ")
             + f"technical checks pass on {sum(_ok(r) for r in real)} of {len(real)}.")
    for r in ctrl:
        a = r.get("aesthetic") or {}
        L.append(f"- Control ({r['title']}): rubric {fmt(a.get('mean'))}, "
                 f"{'passes the gate (the critic is miscalibrated)' if a.get('passed') else 'fails the gate, as it must'}.")
    who = scores.get("scored_by")
    L += [f"- Scored by: {who} ({scores.get('date', 'undated')}). {scores.get('method', '')}" if who else
          "- Scored by: nobody yet (no scores file).", ""]
    L += ["How it is measured:", "",
          "- **Model**: the exemplar's model_mesh op list run in Blender's fixed runner (blocks, bevel, inset, "
          "panel_line, trim_strip, kit_place); ops tagged high_only build the bake source only. The remote is a kernel "
          "design (build123d).",
          "- **Build**: the design created with the purpose \"game\" and built by the kernel; STEP exported and read "
          "back with OCCT.",
          "- **SubD to CAD**: per connected cage part, the CAD patches against the Catmull-Clark limit surface "
          "(form/craft/subd_report.py); the worst part's max deviation per 100 mm of its size.",
          "- **Game asset**: form/game (Blender bakes; the GLB is written and checked here): every validation check, "
          "LOD triangles against budgets (2% over passes).",
          "- **Game evidence** (form/critique.game_evidence, computed; thresholds proposed): *bevel* coverage (share "
          "of LOD0's feature-edge length that is not a raw hard edge: bevelled in the mesh, or baked: the normal map "
          "leans >= 12 deg just inside it); *materials* (distinct kind and tint); *contrast* (base colour luminance "
          "p95 - p5 over LOD0); *scales* (primary: LOD3 shows more than one mass; secondary: LOD0 holds forms LOD3 "
          "drops; tertiary: the normal map carries surface detail); *silhouette* complexity (1 - mean solidity of "
          "LOD0's outline in four views); *wear* (a worn material and a lit curvature mask).",
          "- **Rubric**: form/critique.py's eight items, 0-5. Three blind passes, each over the anonymous review "
          "sheets (four lit views of LOD0 and a 64 px outline, the seven assets shuffled, the control among them); "
          "each item is the median of the passes, capped by the game evidence. Gate: mean >= 4.0 and none under 3 "
          "(proposed).", "",
          "| Brief | Route (expected) | Build | SubD→CAD max / 100 mm | Validation | LOD0..LOD3 tris / budget | "
          "Bevel | Mat. | Contrast | Scales | Silh. | Wear | Rubric |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ro = r.get("route") or {}
        b = r.get("build", {})
        dv = r.get("deviation")
        g = r.get("game") or {}
        val = g.get("validation") or {}
        lods = g.get("lods") or []
        a = r.get("aesthetic") or {}
        ev = r.get("evidence") or {}
        e_ok = bool(ev.get("edges"))
        L.append("| " + " | ".join([
            r["title"] + (" (control)" if r.get("control") else ""),
            (f"{ro.get('main')} ({ro.get('expected')}){'' if ro.get('agrees') else ' ✗'}" if ro else "—"),
            ("ok" if b.get("ok") else "FAILED") + f" {fmt(b.get('seconds'), 1)} s",
            ("n/a (kernel)" if dv is None else f"{dv['max_per_100mm']:.3g} mm ({dv['exact_parts']}/{dv['parts']} exact)"
             if "max_per_100mm" in dv else "error"),
            ("PASS" if val.get("ok") else ("FAIL: " + ", ".join(sorted({c['id'] for c in val.get('failed', [])}))
                                           if g.get("ok") else "not built")),
            " · ".join(f"{l['triangles']}/{l['budget']}" for l in lods) or "—",
            f"{ev['edges']['coverage']:.0%}" if e_ok else "—",
            str(ev["materials"]["count"]) if e_ok else "—",
            fmt(ev.get("value_contrast")) if e_ok else "—",
            f"{ev['scales']['count']}/3" if e_ok else "—",
            f"{ev['silhouette']['complexity']:.3f}" if e_ok else "—",
            ("yes" if ev["wear"]["present"] else "no") if e_ok else "—",
            (f"{a['mean']:.2f} {'pass' if a.get('passed') else 'FAIL'}" if a.get("mean") is not None
             else "not scored" if "error" not in a else "error")]) + " |")
    L += ["", "## Per brief", ""]
    for r in rows:
        L.append(f"### {r['title']}" + (" (control)" if r.get("control") else ""))
        L.append("")
        if r.get("originality"):
            L.append(f"- Originality: {r['originality']}")
        ro = r.get("route") or {}
        if ro:
            L.append("- Routes: " + "; ".join(f"{f['feature']} → {f['route']}" for f in ro.get("features", [])))
        m = r.get("model") or {}
        if not m.get("ok"):
            L.append(f"- **Model failed**: {m.get('error')}")
        elif m.get("ops"):
            L.append(f"- Model: {m['ops']} model_mesh ops ({m['high_only_ops']} high_only) in {m['seconds']} s.")
        if r.get("cage"):
            c = r["cage"]
            L.append(f"- Cage: {c['points']} points, {c['faces']} faces, {c['creases']} creased edges, regions "
                     f"{', '.join(c['regions']) or 'none'}; bake source {c['high_faces'] or 'none (the cage itself)'}"
                     + (" faces." if c["high_faces"] else "."))
        b = r.get("build", {})
        if b and not b.get("ok"):
            L.append(f"- **Build failed**: {b.get('error', 'the kernel build did not finish')}")
        dv = r.get("deviation")
        if dv and "max_mm" in dv:
            L.append(f"- SubD→CAD: {dv['parts']} part(s), worst max {dv['max_mm']:.3g} mm, RMS {dv['rms_mm']:.3g} mm, "
                     f"{dv['max_per_100mm']:.3g} mm per 100 mm; {dv['irregular_points']} irregular point(s).")
        st = r.get("step") or {}
        if st:
            L.append(f"- STEP: {'valid' if st.get('valid') else 'invalid'}" + (
                f", {st.get('solids')} solid(s), {st.get('faces')} faces, {st.get('bytes', 0) / 1024:.0f} kB"
                if st.get("solids") is not None else f" ({st.get('error', '')})"))
        g = r.get("game") or {}
        if g.get("ok"):
            fails = [c for c in g.get("checks", []) if c["status"] != "PASS"]
            L.append(f"- Game asset ({r['preset']}): {g['seconds']} s, bake {fmt(g.get('bake_seconds'), 1)} s, size "
                     f"{' x '.join(f'{x:.0f}' for x in g['size_mm'])} mm, UVs {g['uv']['method']}, "
                     f"{g['collision']['parts']} collision hull(s).")
            L.append("- Checks: " + ("all PASS" if not fails else "; ".join(
                f"{c['id']}{'' if c.get('lod') is None else ' LOD' + str(c['lod'])} {c['status']} ({c['value']})"
                for c in fails)))
            for lv in g.get("lods", []):
                L.append(f"  - LOD{lv['lod']}: {lv['triangles']} / {lv['budget']} triangles, {lv['source']}")
        elif g:
            L.append(f"- **Game asset failed**: {g.get('error')}")
        ev = r.get("evidence") or {}
        if ev.get("edges"):
            e, s = ev["edges"], ev["scales"]
            L.append(f"- Game evidence: bevel coverage {e['coverage']:.0%} ({e['hard_edges_mm'] - e['hard_baked_mm']:.0f} "
                     f"mm raw hard edge of {e['feature_edges_mm']:.0f} mm feature edge, {e['hard_baked_mm']:.0f} mm "
                     f"baked); materials {ev['materials']['count']} ({', '.join(ev['materials']['list'])}); value "
                     f"contrast {ev['value_contrast']}; scales primary {'yes' if s['primary'] else 'no'} "
                     f"({s['lod3_parts']} LOD3 part(s), min solidity {s['lod3_min_solidity']}), secondary "
                     f"{'yes' if s['secondary'] else 'no'} ({s['lod0_far_from_lod3']:.1%} of LOD0 off LOD3), tertiary "
                     f"{'yes' if s['tertiary'] else 'no'} (normal blue std {s['normal_blue_std']}, rg std "
                     f"{s['normal_rg_std']}); silhouette complexity {ev['silhouette']['complexity']} "
                     f"({', '.join(f'{k} {v}' for k, v in ev['silhouette']['solidity'].items())}); wear "
                     f"{'yes' if ev['wear']['present'] else 'no'} (max {ev['wear']['max_wear']}, edge mask "
                     f"{ev['wear']['edge_mask_share']:.1%}).")
        elif ev:
            L.append(f"- Game evidence failed: {ev.get('error')}")
        a = r.get("aesthetic") or {}
        if a.get("items"):
            L.append("- Rubric: " + ", ".join(
                f"{k} {fmt(v['final'], 1) if v['final'] is not None else '—'}"
                + (f" (passes {'/'.join(fmt(x, 0) for x in v['passes'])})" if v.get("passes") else "")
                + (f" [cap {v['cap']}: {v['why']}]" if v.get("cap") is not None else "")
                for k, v in a["items"].items()) + (f"; mean {a['mean']:.2f}" if a.get("mean") is not None else
                                                   "; not scored"))
        for k, note in enumerate((scores.get("notes") or {}).get(r["id"]) or []):
            L.append(f"- Blind pass {k + 1} said: {note}")
        L.append(f"- Wall time {r.get('seconds')} s.")
        L.append("")
    fails = [r["title"] for r in real if not _ok(r)]
    below = [r["title"] for r in real if (r.get("aesthetic") or {}).get("mean") is not None
             and not r["aesthetic"].get("passed")]
    L += ["## What failed", "",
          ("Technical: nothing failed." if not fails else "Technical: " + ", ".join(fails) + "."),
          ("Rubric: every brief passes the gate." if scored and not below else
           "Rubric: below the gate: " + ", ".join(below) + "." if below else "Rubric: not scored."),
          "See each brief above for the measured reason.", ""]
    DOC.write_text("\n".join(L), encoding="utf-8")


def _rubric(r):
    a = r.get("aesthetic") or {}
    return a.get("mean"), a.get("passed")


def write_compare(on: dict, off: dict) -> None:
    """docs/GAME_BENCH.md for two runs: refinement off (the baseline) and on, with the gates of the refinement plan.
    The per-brief detail of the on run follows (write_doc), so the page keeps everything it said before."""
    import io
    rows_on, rows_off = on["rows"], {r["id"]: r for r in off["rows"]}
    real = [r for r in rows_on if not r.get("control")]
    ctrl = [r for r in rows_on if r.get("control")]
    scored = [r for r in real if _rubric(r)[0] is not None]
    ge4 = [r for r in scored if _rubric(r)[0] >= 4.0]
    m_on, m_off = on["meta"], off["meta"]
    so = m_on.get("scores_meta") or {}
    gate_rubric = len(ge4) >= 5 and len(scored) == len(real)
    gate_ctrl = all(not _rubric(r)[1] for r in ctrl)
    tech_on = sum(_ok(r) for r in real)
    L = ["# Game bench", "",
         f"Six original game-asset briefs ({BRIEFS.relative_to(ROOT)}) and one deliberately bad control, made end to "
         f"end from the game exemplars in form/exemplars/game/, twice: with design refinement off (the exemplar as "
         f"written) and on (form/refine: cage and material operators, one bake checked at the end, the asset made "
         f"from the refined head). Run {m_on['date']} on {m_on['machine']} with Blender {m_on['blender']}. Every number "
         "below is from those runs; failures are published as they came out. Budgets and thresholds are proposed "
         "values, not engine rules.", "",
         "## Result", "",
         f"- Rubric with refinement on (median of three new blind passes, capped by the game evidence): {len(ge4)} of "
         f"{len(real)} at 4.0 or more (gate: at least 5 of 6): **{'pass' if gate_rubric else 'FAIL'}**.",
         f"- Control: {'fails the gate, as it must' if gate_ctrl else 'PASSES the gate (the critic is miscalibrated)'}"
         f": **{'pass' if gate_ctrl else 'FAIL'}**.",
         f"- Technical checks pass on {tech_on} of {len(real)} with refinement on, "
         f"{sum(_ok(r) for r in off['rows'] if not r.get('control'))} of {len(real)} off.",
         f"- Scored by: {so.get('scored_by') or 'nobody'} ({so.get('date', 'undated')}). {so.get('method') or ''} "
         "The rubric is a model's judgement of rendered sheets, not a person's and not a measurement.",
         f"- The off column's rubric is the earlier scores file ({Path(m_off.get('scores') or SCORES).name}), "
         "scored on the sheets of the run it came with.", "",
         "| Brief | Validation off / on | LOD0 tris off / on | Bevel off / on | Contrast off / on | Wear off / on | "
         "Rubric off | Rubric on | Refinement (kept) |",
         "|---|---|---|---|---|---|---|---|---|"]

    def ev(r, f):
        e = r.get("evidence") or {}
        try:
            return f(e)
        except Exception:                                   # noqa: BLE001
            return "—"
    for r in rows_on:
        o = rows_off.get(r["id"]) or {}
        g_on, g_off = (r.get("game") or {}), (o.get("game") or {})
        val = lambda g: ("PASS" if (g.get("validation") or {}).get("ok") else "FAIL") if g.get("ok") else "not built"
        tri = lambda g: str(((g.get("lods") or [{}])[0]).get("triangles", "—"))
        rf = r.get("refine") or {}
        kept = ", ".join(a["label"] for a in rf.get("applied") or []) or (rf.get("error") or rf.get("skipped")
                                                                         or rf.get("stopped") or "none")
        if rf.get("commit_error"):
            kept = f"{kept}, not kept: {(rf['commit_error'] or {}).get('message', rf['commit_error'])}"
        mo, po = _rubric(o)
        mn, pn = _rubric(r)
        L.append("| " + " | ".join([
            r["title"] + (" (control)" if r.get("control") else ""), f"{val(g_off)} / {val(g_on)}",
            f"{tri(g_off)} / {tri(g_on)}",
            f"{ev(o, lambda e: format(e['edges']['coverage'], '.0%'))} / {ev(r, lambda e: format(e['edges']['coverage'], '.0%'))}",
            f"{ev(o, lambda e: e['value_contrast'])} / {ev(r, lambda e: e['value_contrast'])}",
            f"{ev(o, lambda e: format(e['wear'].get('worn_share', e['wear'].get('edge_mask_share', 0)), '.1%'))} / "
            f"{ev(r, lambda e: format(e['wear'].get('worn_share', e['wear'].get('edge_mask_share', 0)), '.1%'))}",
            "—" if mo is None else f"{mo:.2f} {'pass' if po else 'FAIL'}",
            "—" if mn is None else f"{mn:.2f} {'pass' if pn else 'FAIL'}",
            f"{rf.get('seconds', '—')} s: {kept}"]) + " |")
    L += ["", "## Refinement per brief", ""]
    for r in rows_on:
        rf = r.get("refine") or {}
        L.append(f"- **{r['title']}**: " + (f"failed: {rf['error']}" if rf.get("error") else
                 f"deficit {rf.get('base')} → {rf.get('final')}, {rf.get('seconds')} s, stopped: {rf.get('stopped')}"
                 + (f", final check: {rf['final_check']}" if rf.get("final_check") else "")
                 + (f", NOT COMMITTED: {(rf['commit_error'] or {}).get('message')}" if rf.get("commit_error") else "")
                 + "; kept: " + ("; ".join(f"{a['label']} ({a.get('reason') or ''})" for a in rf.get("applied") or [])
                                 or "nothing")
                 + ("; rejected: " + "; ".join(f"{x['operator']} ({x['why']})" for x in rf.get("rejected") or [])
                    if rf.get("rejected") else "")))
    L += [""]
    buf = io.StringIO()
    tmp = DOC.with_name(".game_bench_on.md")
    old = DOC.read_text(encoding="utf-8") if DOC.is_file() else None
    sc = json.loads(Path(m_on["scores"]).read_text(encoding="utf-8")) if m_on.get("scores") and Path(m_on["scores"]).is_file() else {}
    write_doc(rows_on, {"texture_px": on.get("cfg", {}).get("texture_px", 1024), "bake": on.get("cfg", {}).get("bake", "fast")},
              m_on, sc)
    detail = DOC.read_text(encoding="utf-8")
    cut = detail.find("How it is measured:")
    L.append("## Refinement on: every number" + "\n\n" + (detail[cut:] if cut >= 0 else detail))
    DOC.write_text("\n".join(L), encoding="utf-8")
    del buf, tmp, old


def rescore(path: Path, scores_file: Path) -> int:
    """Blind passes scored after a run (they look at the run's review sheets): the rubric of every asset again, from
    the same projects and game assets, with the new scores file. The rest of the run is unchanged."""
    run = json.loads(path.read_text(encoding="utf-8"))
    os.environ["FORM_DATA"] = run["meta"]["form_data"]
    os.environ["FORM_CONFIG"] = str(Path(run["meta"]["form_data"]) / "studio.toml")
    os.environ["FORM_REFINE"] = "off"
    from form import config, critique
    from form.studio import Studio
    scores = json.loads(scores_file.read_text(encoding="utf-8"))
    st = Studio(config.load())
    try:
        for r in run["rows"]:
            sc = (scores.get("passes") or {}).get(r["id"])
            if not r.get("pid"):
                continue
            gdir = (r.get("game") or {}).get("dir")
            c = critique.run(st, r["pid"], aesthetic={"passes": sc} if sc else None, game_dir=gdir)
            a = c["aesthetic"]
            r["aesthetic"] = {"mean": a["mean"], "passed": a["passed"], "scored": bool(sc), "passes": len(sc or []),
                              "items": {i["id"]: {"score": i["score"], "cap": i["cap"], "final": i["final"],
                                                  "why": i["why"], "passes": i.get("passes")} for i in a["items"]}}
            print(f"{r['id']:16s} rubric {a['mean']} {'pass' if a['passed'] else 'FAIL'}", flush=True)
    finally:
        st.kernel.stop()
    run["meta"].update(scores=str(scores_file), scores_meta={k: scores.get(k) for k in ("scored_by", "method", "date",
                                                                                     "about")})
    path.write_text(json.dumps(run, indent=1, default=float), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="comma-separated brief ids")
    ap.add_argument("--out", help="folder for renders, review sheets and the contact sheet")
    ap.add_argument("--json", help="also write the raw results here")
    ap.add_argument("--no-doc", action="store_true", help="do not write docs/GAME_BENCH.md")
    ap.add_argument("--refine", choices=("on", "off"), default="off", help="refine each design before its asset")
    ap.add_argument("--scores", help="the blind-pass scores file (default tests/design_bench/game_scores.json)")
    ap.add_argument("--compare", nargs=2, metavar=("ON_JSON", "OFF_JSON"),
                    help="write docs/GAME_BENCH.md from a --refine on and a --refine off run (with --json)")
    ap.add_argument("--rescore", help="a run's JSON: apply --scores to its assets again (the run's data folder is kept)")
    a = ap.parse_args()
    if a.rescore:
        return rescore(Path(a.rescore), Path(a.scores) if a.scores else SCORES)
    if a.compare:
        on, off = (json.loads(Path(x).read_text(encoding="utf-8")) for x in a.compare)
        write_compare(on, off)
        print(f"report: {DOC}")
        return 0
    data = Path(tempfile.mkdtemp(prefix="form-game-bench-"))
    os.environ["FORM_DATA"] = str(data)
    os.environ["FORM_CONFIG"] = str(data / "studio.toml")
    from form import config
    from form.adapters.blender import resolve
    from form.studio import Studio
    spec = json.loads(BRIEFS.read_text(encoding="utf-8"))
    sf = Path(a.scores) if a.scores else SCORES
    scores = json.loads(sf.read_text(encoding="utf-8")) if sf.is_file() else {}
    os.environ["FORM_REFINE"] = "on" if a.refine == "on" else "off"
    cfg = {"texture_px": spec["texture_px"], "bake": spec["bake"]}
    st = Studio(config.load())
    bl = resolve(st.cfg)
    if not bl.get("available"):
        print("Blender is not installed: the game bench needs it (it models and bakes the assets).", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else data / "renders"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for b in spec["briefs"]:
            if a.only and b["id"] not in a.only.split(","):
                continue
            print(f"… {b['id']}", flush=True)
            r = run_brief(st, b, cfg, out, scores, bl["app"], refine=a.refine == "on")
            g = r.get("game") or {}
            ev = r.get("evidence") or {}
            print(f"  model {r.get('model', {}).get('ok')} · build {r.get('build', {}).get('ok')} · game {g.get('ok')} "
                  f"· validation {(g.get('validation') or {}).get('ok')} · bevel "
                  f"{(ev.get('edges') or {}).get('coverage')} · rubric {(r.get('aesthetic') or {}).get('mean')} · "
                  f"{r.get('seconds')} s", flush=True)
            rows.append(r)
    finally:
        st.kernel.stop()
    import platform
    meta = {"date": time.strftime("%Y-%m-%d"), "machine": f"{platform.system()} {platform.machine()}",
            "blender": bl.get("version"), "refine": a.refine, "scores": str(sf), "form_data": str(data), "scores_meta":
            {k: scores.get(k) for k in ("scored_by", "method", "date", "about")}, "out": str(out)}
    contact_sheet(rows, out / "contact_sheet.png")
    write_reviews(rows, out)
    if not a.only and not a.no_doc and a.refine == "off":
        write_doc(rows, cfg, meta, scores)
    if a.json:
        Path(a.json).write_text(json.dumps({"meta": meta, "cfg": cfg, "rows": rows}, indent=1, default=float),
                                encoding="utf-8")
    print(f"contact sheet: {out / 'contact_sheet.png'}\nreview sheets: {out / 'review'}"
          + ("" if a.only or a.no_doc else f"\nreport: {DOC}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
