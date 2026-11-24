"""The game bench: six original game-asset briefs (tests/design_bench/game_briefs.json) made end to end by a scripted
agent, measured, and written to docs/GAME_BENCH.md.

    python scripts/game_bench.py                       # every brief; Blender from the usual places
    python scripts/game_bench.py --only scifi_helmet   # one brief
    python scripts/game_bench.py --out DIR             # renders and the contact sheet go there (default: a temp dir)

The scripted agent does what an agent does through the MCP tools, in this process: it reads each feature's route
(form/router.py, a heuristic, said so), models the object (a subdivision cage for the smooth and repeated routes,
build123d for the kernel route; the cage builders are below and are the agent's modelling, written by hand), creates
the design with the purpose "game" (Studio.create_design), exports STEP, measures the SubD-to-CAD deviation per cage
part against the Catmull-Clark limit surface (form/craft/subd_report.py), makes the game asset (form/game:
game_asset, 1k textures, the fast bake, the brief's preset and budgets) and runs the critique.

The aesthetic rubric (form/critique.py) needs eyes: its scores come from tests/design_bench/game_scores.json, written
by whoever looked at this run's renders (it says who and when); without it a brief is "not scored". The geometry still
caps every score. Nothing is invented: every number in the report is from this run, failures included. Budgets and
thresholds are proposals the first run confirms or changes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BRIEFS = ROOT / "tests" / "design_bench" / "game_briefs.json"
SCORES = ROOT / "tests" / "design_bench" / "game_scores.json"
DOC = ROOT / "docs" / "GAME_BENCH.md"
EXPECTED_ROUTE = {"helmet": "subd_cage", "chest": "subd_cage", "sword": "subd_cage", "wall": "procedural",
                  "wheel": "subd_cage", "remote": "kernel"}


# ---- the scripted agent's modelling: cages by hand -------------------------------------------------------------------

def box(lo, hi, n=(1, 1, 1), sharp=True, profile=None):
    """A closed box cage with n quads along each axis, counter-clockwise from outside; its 12 border edges sharp
    (crease weight 1: a C0 border between exact patches). profile(x, y, z_top) -> z reshapes the top."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    nx, ny, nz = n
    pts, V = {}, []

    def pid(i, j, k):
        key = (i, j, k)
        if key not in pts:
            p = lo + (hi - lo) * np.array([i / nx, j / ny, k / nz])
            if profile is not None and k > 0:
                top = profile(p[0], p[1], hi[2])
                p[2] = lo[2] + (top - lo[2]) * k / nz
            pts[key] = len(V)
            V.append(p)
        return pts[key]
    F = []
    for i in range(nx):
        for j in range(ny):
            F.append([pid(i, j, 0), pid(i, j + 1, 0), pid(i + 1, j + 1, 0), pid(i + 1, j, 0)])
            F.append([pid(i, j, nz), pid(i + 1, j, nz), pid(i + 1, j + 1, nz), pid(i, j + 1, nz)])
    for i in range(nx):
        for k in range(nz):
            F.append([pid(i, 0, k), pid(i + 1, 0, k), pid(i + 1, 0, k + 1), pid(i, 0, k + 1)])
            F.append([pid(i, ny, k), pid(i, ny, k + 1), pid(i + 1, ny, k + 1), pid(i + 1, ny, k)])
    for j in range(ny):
        for k in range(nz):
            F.append([pid(0, j, k), pid(0, j, k + 1), pid(0, j + 1, k + 1), pid(0, j + 1, k)])
            F.append([pid(nx, j, k), pid(nx, j + 1, k), pid(nx, j + 1, k + 1), pid(nx, j, k + 1)])
    C = []
    if sharp:
        inv = {v: k for k, v in pts.items()}
        border = lambda k: sum((k[0] in (0, nx), k[1] in (0, ny), k[2] in (0, nz))) >= 2
        seen = set()
        for f in F:
            for a, b in zip(f, f[1:] + f[:1]):
                e = (min(a, b), max(a, b))
                if e not in seen and border(inv[a]) and border(inv[b]):
                    seen.add(e)
                    C.append([a, b, 1.0])
    return np.array(V), F, C


def sphere(n, scale, at=(0, 0, 0)):
    from form.craft import subd
    V, F = subd.quad_sphere(n, 1.0)
    return V * np.asarray(scale, float) + np.asarray(at, float), [list(map(int, f)) for f in F], []


def rot(V, axis, deg, about=(0, 0, 0)):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    R = {"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
         "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]
    o = np.asarray(about, float)
    return (np.asarray(V, float) - o) @ np.array(R).T + o


def assemble(parts):
    """[(V, F, creases, region)] -> one CageData (each part keeps its own points; regions name faces)."""
    from form import meshsource
    V, F, C, R, off = [], [], [], {}, 0
    for v, f, c, reg in parts:
        if reg:
            R.setdefault(reg, []).extend(range(len(F), len(F) + len(f)))
        V.append(np.asarray(v, float))
        F += [[int(i) + off for i in q] for q in f]
        C += [[int(a) + off, int(b) + off, float(s)] for a, b, s in c]
        off += len(v)
    return meshsource.cage(np.concatenate(V), F, C, R)


def helmet():
    V, F, _ = sphere(4, (115, 100, 120), (0, 0, 120))
    V[:, 2] = np.where(V[:, 2] < 60, 60 + (V[:, 2] - 60) * 0.35, V[:, 2])        # a flat-ish neck opening line
    cen = np.array([np.mean(V[f], axis=0) for f in F])
    visor = [i for i, c in enumerate(cen) if c[0] > 55 and 95 < c[2] < 175 and abs(c[1]) < 80]
    shell = [i for i in range(len(F)) if i not in set(visor)]
    parts = [(V, [F[i] for i in shell] + [F[i] for i in visor], [], None)]
    pods = [(*sphere(2, (30, 22, 38), (-5, s * 98, 125))[:3], "pod") for s in (-1, 1)]
    crest = (*box((-95, -9, 200), (70, 9, 248), (4, 1, 1),
                  profile=lambda x, y, z: z - 0.0016 * (x + 10) ** 2), "crest")
    cage = assemble(parts + pods + [crest])
    regions = dict(cage.regions)
    regions["visor"] = list(range(len(shell), len(shell) + len(visor)))
    from form import meshsource
    return meshsource.cage(cage.V, cage.F, cage.creases, regions)


def chest():
    W, D, H, LID = 600.0, 380.0, 300.0, 110.0
    arch = lambda r: (lambda x, y, z: z + LID * 0.85 * math.sqrt(max(1 - (y / r) ** 2, 0)))
    parts = [(*box((-W / 2, -D / 2, 0), (W / 2, D / 2, H), (6, 4, 3)), None),
             (*box((-W / 2 - 6, -D / 2 - 6, H + 4), (W / 2 + 6, D / 2 + 6, H + 30), (6, 6, 2), profile=arch(D / 2 + 6)), None)]
    for x in (-205.0, 205.0):
        parts.append((*box((x - 22, -D / 2 - 8, -6), (x + 22, D / 2 + 8, H + 2), (2, 4, 3)), "iron"))
        parts.append((*box((x - 24, -D / 2 - 12, H + 2), (x + 24, D / 2 + 12, H + 36), (2, 6, 1), profile=arch(D / 2 + 14)), "iron"))
    parts.append((*box((-W / 2 - 8, -D / 2 - 8, -8), (W / 2 + 8, D / 2 + 8, 26), (6, 4, 1)), "iron"))
    parts.append((*box((-46, -D / 2 - 26, 210), (46, -D / 2 + 4, 330), (2, 1, 3)), "gold"))
    return assemble(parts)


def sword():
    V, F, C = box((-30, -4, 80), (30, 4, 860), (2, 1, 8))
    t = (V[:, 2] - 80) / 780.0
    V[:, 0] *= 1 - 0.55 * t ** 1.5 - np.where(t > 0.97, 0.4, 0.0)
    V[:, 1] *= 1 - 0.5 * t
    parts = [(V, F, C, "blade")]
    parts.append((*box((-120, -16, 56), (120, 16, 84), (4, 1, 1), profile=lambda x, y, z: z + 0.0009 * x * x), "guard"))
    parts.append((*box((-17, -17, -110), (17, 17, 60), (2, 2, 5), sharp=False), "grip"))
    parts.append((*sphere(2, (32, 32, 32), (0, 0, -130)), None))
    return assemble(parts)


def wall():
    parts = [(*box((-1000, -125, 120), (1000, 125, 2400), (4, 1, 4)), None),
             (*box((-1010, -150, 0), (1010, 150, 140), (4, 1, 1)), None)]
    bw, bh, gap = 380.0, 150.0, 20.0
    for r in range(6):
        z0 = 300 + r * (bh + gap)
        shift = 0.0 if r % 2 == 0 else (bw + gap) / 2
        for c in range(5):
            x0 = -980 + shift + c * (bw + gap)
            x1 = min(x0 + bw, 980)
            if x1 - x0 < 120:
                continue
            parts.append((*box((x0, -150, z0), (x1, -115, z0 + bh), (2, 1, 1)), "brick"))
    return assemble(parts)


def wheel():
    from form.craft import subd_report
    tv, tf = subd_report.torus_cage(24, 10, 300.0, 95.0)
    tyre = (rot(tv, "x", 90), [list(map(int, f)) for f in tf], [], "tyre")
    rim = (*sphere(3, (225, 40, 225)), "rim")
    parts = [tyre, rim]
    for k in range(5):
        v, f, c = box((-22, -26, 50), (22, 26, 215), (1, 1, 2))
        parts.append((rot(v, "y", 72 * k), f, c, "rim"))
    parts.append((*sphere(2, (60, 62, 60)), None))
    return assemble(parts)


REMOTE = '''"""A generic TV remote control: a rounded body, button holes on the top, a battery cover split line underneath."""
from build123d import Align, Axis, Box, Cylinder, Pos, fillet

from form.recipes.base import Feature, Param, Recipe, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Remote control"
    summary = "A rounded remote body with button holes and a battery cover."
    solids = 1
    params = [Param("length", "Length", 180, 120, 240, 1, "mm", "form", "body"),
              Param("width", "Width", 48, 36, 70, 1, "mm", "form", "body"),
              Param("thickness", "Thickness", 20, 12, 30, 0.5, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure"), Feature("buttons", "Button holes", "detail"),
                Feature("battery_cover", "Battery cover", "detail")]

    def build(self, v):
        L, W, T = v["length"], v["width"], v["thickness"]
        body = Box(L, W, T, align=A)
        body = fillet(body.edges().filter_by(Axis.Z), min(W, L) * 0.22)
        body = fillet(body.edges().group_by(Axis.Z)[-1], T * 0.22)
        body = fillet(body.edges().group_by(Axis.Z)[0], T * 0.12)
        out = [Stage("body", body)]
        holes = Pos(L * 0.36, 0, T - 2.5) * Cylinder(5.5, 4, align=A)
        for i in range(4):
            for j in (-1, 0, 1):
                holes += Pos(L * 0.16 - i * 15, j * 13, T - 1.6) * Cylinder(3.6, 4, align=A)
        body = body - holes
        out.append(Stage("buttons", body))
        cut = Pos(-L * 0.22, 0, -0.01) * Box(L * 0.42, W * 0.72, 1.0, align=A)
        inner = Pos(-L * 0.22, 0, -0.02) * Box(L * 0.42 - 1.2, W * 0.72 - 1.2, 1.2, align=A)
        latch = Pos(-L * 0.01, 0, -0.02) * Box(4, 10, 1.6, align=A)
        body = body - (cut - inner) - latch
        out.append(Stage("battery_cover", body))
        return out

    def appearance(self, v):
        return [{"features": ["buttons"], "finish": "rubber", "color": "#5a5f66", "label": "buttons"}]
'''

GENERATORS = {"helmet": helmet, "chest": chest, "sword": sword, "wall": wall, "wheel": wheel}

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
sc.render.resolution_x = sc.render.resolution_y = 560
world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.8, 0.8, 0.78, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sun.data.energy = 3.0
sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(35)); sc.collection.objects.link(sun)
names = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
sc.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in names else "BLENDER_EEVEE_NEXT"
lods = sorted([o for o in meshes if "_LOD" in o.name], key=lambda o: o.name)
lod0 = lods[0]
pts = [lod0.matrix_world @ Vector(c) for c in lod0.bound_box]
c = sum(pts, Vector()) / 8
r = max((p - c).length for p in pts)
cam.data.lens = 50
d = r * 3.0
cam.location = c + Vector((d * 0.75, -d * 0.95, d * 0.55))
cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
wire = bpy.data.materials.new("wire"); wire.use_nodes = True
wire.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.05, 0.05, 0.06, 1)
clay = bpy.data.materials.new("clay"); clay.use_nodes = True
clay.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.75, 0.74, 0.7, 1)
for o in meshes:
    o.hide_render = True
for o in (lods[0], lods[-1]):
    o.hide_render = False
    sc.render.filepath = f"{out}/{o.name}_tex.png"
    bpy.ops.render.render(write_still=True)
    w = o.copy(); w.data = o.data.copy(); sc.collection.objects.link(w)
    w.data.materials.clear(); w.data.materials.append(wire)
    m = w.modifiers.new("wf", "WIREFRAME"); m.thickness = r * 0.002; m.use_replace = True
    k = o.copy(); k.data = o.data.copy(); sc.collection.objects.link(k)
    k.data.materials.clear(); k.data.materials.append(clay)
    o.hide_render = True
    sc.render.filepath = f"{out}/{o.name}_wire.png"
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(w); bpy.data.objects.remove(k)
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
    return {"features": rows, "main": main, "expected": EXPECTED_ROUTE[brief["generator"]],
            "agrees": main == EXPECTED_ROUTE[brief["generator"]]}


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


def render(glb: Path, out: Path, blender: str) -> list:
    script = out / "_render.py"
    script.write_text(RENDER, encoding="utf-8")
    r = subprocess.run([blender, "-b", "--factory-startup", "-noaudio", "--python", str(script), "--", str(glb), str(out)],
                       capture_output=True, text=True, timeout=900)
    return sorted(str(p) for p in out.glob("*.png")) if "RENDERED" in r.stdout else []


def run_brief(st, b: dict, cfg: dict, out: Path, scores: dict, blender: str | None) -> dict:
    from form import critique, game
    from form.game import pipeline
    row = {"id": b["id"], "title": b["title"], "preset": b["preset"], "budgets": b["budgets"]}
    t0 = time.time()
    row["route"] = routes(b)
    gen = b["generator"]
    cage = None
    if gen == "remote":
        src = REMOTE
    else:
        cage = GENERATORS[gen]()
        row["cage"] = {"points": int(len(cage.V)), "quads": int(len(cage.F)), "creases": len(cage.creases),
                       "regions": sorted(cage.regions)}
        src = pipeline.cage_design_source(cage, b["title"])
    try:
        t = time.time()
        p = st.create_design(b["title"], src, b["brief"], purpose="game")
        j = st.run_sync(p["id"], ["geometry", "exports"])
        row["build"] = {"ok": j["state"] == "done", "seconds": round(time.time() - t, 2)}
        p = st.load(p["id"])
    except Exception as e:                                   # noqa: BLE001 - a failed build is a result
        row["build"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300], "seconds": round(time.time() - t, 2)}
        row["seconds"] = round(time.time() - t0, 1)
        return row
    row["pid"] = p["id"]
    keys = st.keys(p)
    ex = st.read(p, "exports", keys["exports"]) or {}
    stp = ex.get("files", {}).get("step")
    try:
        row["step"] = step_check(st.apath(p, "exports", keys["exports"]) / stp["name"]) if stp else {"valid": False,
                                                                                                     "error": "no STEP"}
    except Exception as e:                                   # noqa: BLE001
        row["step"] = {"valid": False, "error": str(e)[:200]}
    row["deviation"] = deviation(cage) if cage is not None else None
    try:
        t = time.time()
        res = game.game_asset(st, p["id"], preset=b["preset"], budgets=b["budgets"], texture_px=cfg["texture_px"],
                              bake=cfg["bake"], materials=b["materials"])
        row["game"] = {"ok": True, "seconds": round(time.time() - t, 1), "validation": res["validation"],
                       "lods": [{k: r[k] for k in ("lod", "triangles", "budget", "source")} for r in res["lods"]],
                       "bake_seconds": (res.get("bake") or {}).get("total_seconds"), "uv": res["uv"],
                       "collision": res["collision"], "dir": res["dir"], "notes": res.get("notes", [])}
        rep = json.loads((Path(res["dir"]) / "report.json").read_text(encoding="utf-8"))
        row["game"]["checks"] = [{k: c.get(k) for k in ("id", "lod", "status", "value")} for c in rep["validation"]["checks"]]
        if blender:
            d = out / b["id"]
            d.mkdir(parents=True, exist_ok=True)
            row["renders"] = render(Path(res["dir"]) / f"{rep['asset']}.glb", d, blender)
            nm = Path(res["dir"]) / "textures" / f"{rep['asset']}_normal.png"
            if nm.is_file():
                shutil.copy2(nm, d / "normal.png")
                row["renders"].append(str(d / "normal.png"))
    except Exception as e:                                   # noqa: BLE001
        row["game"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}
    try:
        sc = (scores.get("scores") or {}).get(b["id"])
        c = critique.run(st, p["id"], aesthetic=sc)
        a = c["aesthetic"]
        row["aesthetic"] = {"mean": a["mean"], "passed": a["passed"], "scored": sc is not None,
                            "items": {i["id"]: {"score": i["score"], "cap": i["cap"], "final": i["final"], "why": i["why"]}
                                      for i in a["items"]}}
    except Exception as e:                                   # noqa: BLE001
        row["aesthetic"] = {"error": str(e)[:200]}
    row["seconds"] = round(time.time() - t0, 1)
    return row


def contact_sheet(rows: list, path: Path) -> None:
    from PIL import Image, ImageDraw
    tiles = []
    for r in rows:
        files = r.get("renders") or []
        pick = [f for f in files if f.endswith("LOD0_tex.png")] + [f for f in files if f.endswith("LOD3_tex.png")] + \
               [f for f in files if f.endswith("LOD0_wire.png")] + [f for f in files if f.endswith("normal.png")]
        tiles.append((r, pick))
    W, H, pad, head = 300, 300, 10, 26
    sheet = Image.new("RGB", (pad + 4 * (W + pad), pad + len(tiles) * (H + head + pad)), (244, 243, 239))
    dr = ImageDraw.Draw(sheet)
    for i, (r, pick) in enumerate(tiles):
        y = pad + i * (H + head + pad)
        g = r.get("game") or {}
        lods = g.get("lods") or []
        dr.text((pad, y + 6), f"{r['title']} · {r['preset']} · LOD tris {[l['triangles'] for l in lods]} · "
                f"validation {'PASS' if (g.get('validation') or {}).get('ok') else 'FAIL'}", fill=(30, 30, 30))
        for k, f in enumerate(pick[:4]):
            im = Image.open(f).convert("RGB")
            im.thumbnail((W, H))
            sheet.paste(im, (pad + k * (W + pad), y + head))
    sheet.save(path)


def fmt(v, d=2):
    return "—" if v is None else f"{v:.{d}f}" if isinstance(v, float) else str(v)


def write_doc(rows: list, cfg: dict, meta: dict, scores: dict) -> None:
    L = ["# Game bench", "",
         f"Six original game-asset briefs ({BRIEFS.relative_to(ROOT)}) made end to end by a scripted agent "
         f"(`python scripts/game_bench.py`), run {meta['date']} on {meta['machine']} with Blender {meta['blender']}. "
         f"Textures {cfg['texture_px']} px, the {cfg['bake']} bake. Every number below is from that run; failures "
         "are published as they came out. Budgets and thresholds are proposed values, not engine rules.", "",
         "How it is measured:", "",
         "- **Route**: form/router.py reads each feature's words (a heuristic, and labelled one); the main route is the "
         "most common one, compared with the route the brief was written for.",
         "- **Build**: the design created with the purpose \"game\" and built by the kernel, with STEP exported.",
         "- **SubD to CAD**: per connected cage part, the CAD patches against the Catmull-Clark limit surface "
         "(form/craft/subd_report.py); the worst part's max deviation per 100 mm of its size. Exact only where every "
         "patch is a regular B-spline patch; ACC elsewhere.",
         "- **STEP**: the exported STEP read back with OCCT: valid, solids.",
         "- **Game asset**: form/game (Blender bakes, the GLB is written and checked here): every validation check, "
         "LOD triangles against budgets (2% over passes), bake seconds.",
         "- **Aesthetic**: form/critique.py's rubric (heuristic). Scores come from " +
         (f"{SCORES.relative_to(ROOT)} ({scores.get('scored_by', 'unknown')}, {scores.get('date', 'undated')})"
          if scores.get("scores") else "nobody yet: no scores file") +
         ", capped by what the geometry supports. Gate: mean ≥ 4.0 and none under 3 (proposed).", "",
         "| Brief | Route (expected) | Build | SubD→CAD max / 100 mm | STEP | Validation | LOD0..LOD3 tris / budget | Bake s | Aesthetic |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ro = r.get("route", {})
        b = r.get("build", {})
        dv = r.get("deviation")
        st = r.get("step") or {}
        g = r.get("game") or {}
        val = g.get("validation") or {}
        lods = g.get("lods") or []
        a = r.get("aesthetic") or {}
        L.append("| " + " | ".join([
            r["title"],
            f"{ro.get('main')} ({ro.get('expected')}){'' if ro.get('agrees') else ' ✗'}",
            ("ok" if b.get("ok") else "FAILED") + f" {fmt(b.get('seconds'), 1)} s",
            ("n/a (kernel)" if dv is None else f"{dv['max_per_100mm']:.3g} mm ({dv['exact_parts']}/{dv['parts']} parts exact)"),
            ("valid" if st.get("valid") else "INVALID") + (f", {st.get('solids')} solid(s)" if st.get("solids") is not None else ""),
            ("PASS" if val.get("ok") else ("FAIL: " + ", ".join(sorted({c['id'] for c in val.get('failed', [])})) if g.get("ok") else "not built")),
            " · ".join(f"{l['triangles']}/{l['budget']}" for l in lods) or "—",
            fmt(g.get("bake_seconds"), 1),
            (f"{a['mean']:.2f} {'pass' if a.get('passed') else 'below gate'}" if a.get("mean") is not None
             else "not scored" if "error" not in a else "error")]) + " |")
    L += ["", "## Per brief", ""]
    for r in rows:
        L.append(f"### {r['title']}")
        L.append("")
        ro = r.get("route", {})
        L.append("- Routes: " + "; ".join(f"{f['feature']} → {f['route']}" + (f" ({', '.join(f['because'][:3])})" if f.get("because") else "")
                                          + ("" if f.get("confident", True) else ", not confident") for f in ro.get("features", [])))
        if r.get("cage"):
            c = r["cage"]
            L.append(f"- Cage: {c['points']} points, {c['quads']} quads, {c['creases']} sharp crease edges, regions {', '.join(c['regions']) or 'none'}.")
        b = r.get("build", {})
        if not b.get("ok"):
            L.append(f"- **Build failed**: {b.get('error', 'the kernel build did not finish')}")
        dv = r.get("deviation")
        if dv:
            L.append(f"- SubD→CAD: {dv['parts']} part(s), worst max {dv['max_mm']:.3g} mm, RMS {dv['rms_mm']:.3g} mm, "
                     f"{dv['max_per_100mm']:.3g} mm per 100 mm; {dv['irregular_points']} irregular point(s).")
        st = r.get("step") or {}
        if st:
            L.append(f"- STEP: {'valid' if st.get('valid') else 'invalid'}" + (f", {st.get('solids')} solid(s), {st.get('faces')} faces, "
                     f"{st.get('bytes', 0) / 1024:.0f} kB" if st.get("solids") is not None else f" ({st.get('error', '')})"))
        g = r.get("game") or {}
        if g.get("ok"):
            fails = [c for c in g.get("checks", []) if c["status"] != "PASS"]
            L.append(f"- Game asset ({r['preset']}): built in {g['seconds']} s, bake {fmt(g.get('bake_seconds'), 1)} s, UVs {g['uv']['method']}, "
                     f"collision {g['collision']['parts']} hull(s) ({', '.join(g['collision']['names'][:2])}{', …' if g['collision']['parts'] > 2 else ''}).")
            L.append("- Checks: " + ("all PASS" if not fails else "; ".join(f"{c['id']}{'' if c.get('lod') is None else ' LOD' + str(c['lod'])} {c['status']} ({c['value']})" for c in fails)))
            for l in g.get("lods", []):
                L.append(f"  - LOD{l['lod']}: {l['triangles']} / {l['budget']} triangles, {l['source']}")
        elif g:
            L.append(f"- **Game asset failed**: {g.get('error')}")
        a = r.get("aesthetic") or {}
        if a.get("items"):
            L.append("- Aesthetic rubric (heuristic): " + ", ".join(
                f"{k} {fmt(v['final'], 1) if v['final'] is not None else '—'}" + (f" (cap {v['cap']}: {v['why']})" if v.get("cap") is not None else "")
                for k, v in a["items"].items()) + (f"; mean {a['mean']:.2f}" if a.get("mean") is not None else "; not scored"))
        note = (scores.get("notes") or {}).get(r["id"])
        if note:
            L.append(f"- Looked at ({scores.get('scored_by', 'reviewer')}): {note}")
        L.append(f"- Wall time {r.get('seconds')} s.")
        L.append("")
    fails = [r["title"] for r in rows if not (r.get("build", {}).get("ok") and (r.get("game") or {}).get("ok")
                                              and ((r.get("game") or {}).get("validation") or {}).get("ok"))]
    L += ["## What failed", "", ("Nothing failed in this run." if not fails else
          "Published as they came out: " + ", ".join(fails) + ". See each brief above for the measured reason."), ""]
    DOC.write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="comma-separated brief ids")
    ap.add_argument("--out", help="folder for renders and the contact sheet")
    ap.add_argument("--json", help="also write the raw results here")
    a = ap.parse_args()
    data = Path(tempfile.mkdtemp(prefix="form-game-bench-"))
    os.environ["FORM_DATA"] = str(data)
    os.environ.pop("FORM_CONFIG", None)
    os.environ["FORM_CONFIG"] = str(data / "studio.toml")
    from form import config
    from form.adapters.blender import resolve
    from form.studio import Studio
    spec = json.loads(BRIEFS.read_text(encoding="utf-8"))
    scores = json.loads(SCORES.read_text(encoding="utf-8")) if SCORES.is_file() else {}
    cfg = {"texture_px": spec["texture_px"], "bake": spec["bake"]}
    st = Studio(config.load())
    bl = resolve(st.cfg)
    if not bl.get("available"):
        print("Blender is not installed: the game bench needs it (it bakes the assets).", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else data / "renders"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for b in spec["briefs"]:
            if a.only and b["id"] not in a.only.split(","):
                continue
            print(f"… {b['id']}", flush=True)
            r = run_brief(st, b, cfg, out, scores, bl["app"])
            g = r.get("game") or {}
            print(f"  build {r.get('build', {}).get('ok')} · game {g.get('ok')} · validation "
                  f"{(g.get('validation') or {}).get('ok')} · {r.get('seconds')} s", flush=True)
            rows.append(r)
    finally:
        st.kernel.stop()
    import platform
    meta = {"date": time.strftime("%Y-%m-%d"), "machine": f"{platform.system()} {platform.machine()}",
            "blender": bl.get("version")}
    contact_sheet(rows, out / "contact_sheet.png")
    if not a.only:
        write_doc(rows, cfg, meta, scores)
    if a.json:
        Path(a.json).write_text(json.dumps({"meta": meta, "rows": rows}, indent=1, default=float), encoding="utf-8")
    print(f"contact sheet: {out / 'contact_sheet.png'}" + ("" if a.only else f"\nreport: {DOC}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
