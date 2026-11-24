"""The game asset pipeline: a design's cage or CAD tessellation in, a checked engine-ready asset out.

    build(source, out_dir, preset="gltf", budgets=None, texture_px=1024, ...)  ->  report dict

source is a cage (meshsource.CageData: V, F, creases, named regions) or a mesh ((V, T) millimetres, Z up: the CAD
solid's tessellation), each with a material per face. Steps, and where each runs:

    here      check every option; pivot; plan the LODs from cage levels (lod.plan_lods); pick the UV method (region
              seams when every region is a disc, else Smart UV Project); collision hulls (lod.convex_parts, or CoACD)
    Blender   form/adapters/blender_game.py, the fixed runner: UVs, high-poly, LODs, Principled materials, Cycles
              bakes (base colour, normal, ORM, AO), FBX/USD export
    here      the GLB (form/meshio.glb_scene, metres, +Y up), a collision GLB, and validate.validate on the GLB

Blender is run as the modelling bridge runs it (form/adapters/blender_model.py): -b --factory-startup -noaudio -Y,
--offline-mode on 4.2+, a scrubbed environment, a new temporary folder, a watchdog that kills the process group. The
runner gets a JSON job and numpy arrays, never code. Everything is built in a temporary folder and moved to out_dir
only when it all worked, so a failed or killed run leaves out_dir as it was. Not enforced: OS-level network
isolation (Blender's --offline-mode is its own switch, not a sandbox).

Textures are baked from the design's own materials and fixed procedural patterns. Nothing is downloaded.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from .. import meshio, meshsource
from . import lod as lodmod
from . import presets as pz
from . import validate as vmod

RUNNER = Path(__file__).resolve().parent.parent / "adapters" / "blender_game.py"
RUNNER_VERSION = 2
TIMEOUT_S = 1800.0
PATTERNS = ("none", "wood", "noise", "brushed")
UV_METHODS = ("auto", "regions", "smart")
RETOPO = ("decimate", "quadriflow")
COLLISION = ("hull", "coacd", "none")
DEFAULT_MATERIAL = {"finish": "matte", "color": "#b8b2a7", "pattern": "none"}


class GameError(ValueError):
    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint


# ---- materials ---------------------------------------------------------------------------------------------------

def srgb_to_linear(hexcol: str) -> list[float]:
    c = np.array([int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5)])
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).round(6).tolist()


def material_spec(name: str, m: dict) -> dict:
    """A material for the runner from {finish, color, pattern, pattern_mm} (finishes: the Blender adapter's FINISHES).
    Raises GameError naming what is wrong."""
    from ..adapters.blender import FINISHES
    from ..appearance import HEX
    if not isinstance(m, dict):
        raise GameError(f"material {name} must be an object {{finish, color, pattern}}.")
    extra = set(m) - {"finish", "color", "pattern", "pattern_mm", "label", "features"}
    if extra:
        raise GameError(f"material {name} does not take {', '.join(sorted(extra))}.")
    fin = str(m.get("finish") or "matte")
    if fin not in FINISHES:
        raise GameError(f"material {name}: unknown finish {fin!r}.", "Finishes: " + ", ".join(FINISHES))
    col = str(m.get("color") or DEFAULT_MATERIAL["color"])
    if not HEX.fullmatch(col):
        raise GameError(f"material {name}: colour {col!r} is not #rrggbb.")
    pat = str(m.get("pattern") or "none")
    if pat not in PATTERNS:
        raise GameError(f"material {name}: pattern must be one of {', '.join(PATTERNS)}.")
    pmm = m.get("pattern_mm", 20.0)
    if isinstance(pmm, bool) or not isinstance(pmm, (int, float)) or not 0.01 <= float(pmm) <= 1e5:
        raise GameError(f"material {name}: pattern_mm must be a size in mm (0.01..100000).")
    f = FINISHES[fin]
    return {"name": pz.safe_name(name), "finish": fin, "hex": col.lower(), "color": srgb_to_linear(col),
            "roughness": float(f["roughness"]), "metallic": float(f["metallic"]), "pattern": pat,
            "pattern_mm": float(pmm)}


def region_materials(cage: meshsource.CageData, materials: dict | None) -> tuple[list[dict], list[int]]:
    """Materials and a material index per cage face from {region name or "default": material}."""
    materials = dict(materials or {})
    default = materials.pop("default", DEFAULT_MATERIAL)
    unknown = [k for k in materials if k not in cage.regions]
    if unknown:
        raise GameError(f"materials name regions the cage does not have: {', '.join(unknown)}.",
                        "Regions: " + (", ".join(cage.regions) or "none") + ". Use \"default\" for the rest.")
    specs = [material_spec("default", default)]
    face = [0] * len(cage.F)
    for name, m in materials.items():
        specs.append(material_spec(name, m))
        for fi in cage.regions[name]:
            face[fi] = len(specs) - 1
    return specs, face


# ---- UV method -------------------------------------------------------------------------------------------------------

def is_disc(F: list, faces: list[int]) -> bool:
    """A face set that is a topological disc (Euler characteristic 1, one boundary loop): it flattens without cuts."""
    if not faces:
        return True
    E: dict = {}
    Vs = set()
    for fi in faces:
        f = F[fi]
        Vs.update(f)
        for k in range(len(f)):
            a, b = f[k], f[(k + 1) % len(f)]
            e = (min(a, b), max(a, b))
            E[e] = E.get(e, 0) + 1
    if len(Vs) - len(E) + len(faces) != 1:
        return False
    bnd = [e for e, c in E.items() if c == 1]
    if not bnd:
        return False
    adj: dict = {}
    for a, b in bnd:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    if any(len(v) != 2 for v in adj.values()):
        return False
    start = bnd[0][0]
    seen, prev, cur = {start}, None, start
    while True:                                    # one boundary loop through every boundary point
        nxt = [x for x in adj[cur] if x != prev]
        prev, cur = cur, nxt[0]
        if cur == start:
            break
        seen.add(cur)
    return len(seen) == len(adj)


def uv_method(cage: meshsource.CageData, want: str = "auto") -> tuple[str, str]:
    """("regions" | "smart", why). Regions are used when every region (and the faces no region names) is a disc."""
    if want not in UV_METHODS:
        raise GameError(f"uv must be one of {', '.join(UV_METHODS)}.")
    if want == "smart":
        return "smart", "asked for Smart UV Project"
    if not cage.regions:
        if want == "regions":
            raise GameError("uv=regions needs named regions on the cage.", "Name regions with model_mesh name_region.")
        return "smart", "the cage has no named regions"
    groups: dict = {}
    for name, fs in cage.regions.items():
        for fi in fs:
            groups.setdefault(fi, name)
    rest = [i for i in range(len(cage.F)) if i not in groups]
    sets = [[i for i, n in groups.items() if n == name] for name in cage.regions] + ([rest] if rest else [])
    bad = [i for i, s in enumerate(sets) if not is_disc(cage.F, s)]
    if not bad:
        return "regions", "every region is a disc: seams on the region borders"
    if want == "regions":
        return "regions", "asked for region seams, though not every region is a disc (expect overlaps)"
    return "smart", "a region is not a disc (it needs more seams), so Smart UV Project"


# ---- reading a design --------------------------------------------------------------------------------------------

def cages_in_source(text: str) -> list[meshsource.CageData]:
    """The literal meshsource.cage(...) calls in a design's source, read with ast.literal_eval (never executed)."""
    out = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
        if name != "cage" or not (isinstance(fn, ast.Name) or (isinstance(fn.value, ast.Name) and fn.value.id == "meshsource")):
            continue
        try:
            args = [ast.literal_eval(a) for a in node.args]
            kw = {k.arg: ast.literal_eval(k.value) for k in node.keywords if k.arg}
            fields = dict(zip(("V", "F", "creases", "regions"), args), **kw)
            out.append(meshsource.cage(fields["V"], fields["F"], fields.get("creases"), fields.get("regions")))
        except (ValueError, KeyError, TypeError, SyntaxError):
            continue
    return out


def merge_cages(cages: list[meshsource.CageData]) -> meshsource.CageData:
    if len(cages) == 1:
        return cages[0]
    V, F, C, R, off, foff = [], [], [], {}, 0, 0
    for c in cages:
        V.append(c.V)
        F += [[i + off for i in f] for f in c.F]
        C += [[a + off, b + off, s] for a, b, s in c.creases]
        for k, fs in c.regions.items():
            R.setdefault(k, []).extend(i + foff for i in fs)
        off += len(c.V)
        foff += len(c.F)
    return meshsource.cage(np.concatenate(V), F, C, R)


def split_cage(cage: meshsource.CageData) -> list[meshsource.CageData]:
    """A cage's connected parts (faces that share points), each a cage of its own with its creases and regions."""
    F = [list(f) for f in cage.F]
    parent = list(range(len(cage.V)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for f in F:
        for a in f[1:]:
            ra, rb = find(f[0]), find(a)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups: dict = {}
    for i, f in enumerate(F):
        groups.setdefault(find(f[0]), []).append(i)
    if len(groups) <= 1:
        return [cage]
    face_region = {}
    for name, fs in cage.regions.items():
        for i in fs:
            face_region.setdefault(int(i), []).append(name)
    out = []
    for root in sorted(groups):
        fids = groups[root]
        used = sorted({v for i in fids for v in F[i]})
        remap = {v: k for k, v in enumerate(used)}
        regions: dict = {}
        for k, i in enumerate(fids):
            for name in face_region.get(i, []):
                regions.setdefault(name, []).append(k)
        creases = [[remap[a], remap[b], w] for a, b, w in cage.creases if a in remap and b in remap]
        out.append(meshsource.cage(np.asarray(cage.V)[used], [[remap[v] for v in F[i]] for i in fids], creases,
                                   regions))
    return out


def cage_design_source(cage: meshsource.CageData, title: str = "Cage design") -> str:
    """A design source (one Recipe) whose solid is the cage's limit surface as exact CAD (form/craft/subd.py), one
    cage literal per connected part, fused. The cage stays data in the source, so game_asset reads it back
    (cages_in_source) and builds LODs from its levels, while STEP comes from the same cage."""
    parts = split_cage(cage)
    lits = "".join(c.literal(f"CAGE_{i}") for i, c in enumerate(parts))
    names = ", ".join(f"CAGE_{i}" for i in range(len(parts)))
    t = json.dumps(str(title or "Cage design"))
    return f'''"""{str(title or "Cage design").replace('"', "'")}: a subdivision cage as exact CAD. Form Studio."""
from form import meshsource
from form.recipes.base import Feature, Param, Recipe, Stage

{lits}
CAGES = [{names}]


class Design(Recipe):
    title = {t}
    summary = "A subdivision cage; its limit surface is the solid (exact B-spline patches, ACC at extraordinary points)."
    solids = 1
    params = [Param("merge_faces", "Merge B-spline faces", 1, 0, 1, 1, "", "form", "body",
                    "1: regular patch blocks become multi-span B-spline faces (a lighter STEP); 0: one face per patch. "
                    "The surface is the same either way.")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        body = None
        for c in CAGES:
            s = c.to_subd().solid(merge=bool(round(v["merge_faces"])))
            body = s if body is None else body + s
        return [Stage("body", body)]
'''


# ---- running Blender -------------------------------------------------------------------------------------------------

def _run_blender(app: str, ver: str, job_path: Path, work: Path, timeout: float, progress=None) -> dict:
    from ..adapters.blender import BlenderFailed, tail
    from ..adapters.blender_model import offline_flag, scrubbed_env
    cmd = [app, "-b", "--factory-startup", "-noaudio", "-Y", *offline_flag(ver), "--python-exit-code", "3",
           "--python", str(RUNNER), "--", str(job_path)]
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=str(work), env=scrubbed_env(work), text=True, encoding="utf-8", errors="replace",
                                start_new_session=(os.name != "nt"))
    except OSError as e:
        raise BlenderFailed(f"Could not start Blender: {e}", "Check [blender].app.")
    killed = {"v": False}

    def watchdog():
        if proc.poll() is None:
            killed["v"] = True
            try:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except OSError:
                proc.kill()
    timer = threading.Timer(timeout, watchdog)
    timer.daemon = True
    timer.start()
    log, report = [], None
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            log.append(line)
            if len(log) > 4000:
                del log[:2000]
            if line.startswith("FORM_STEP ") and progress:
                progress(line[10:])
            elif line.startswith("FORM_RESULT "):
                try:
                    report = json.loads(line[12:])
                except ValueError:
                    report = None
        proc.wait()
    finally:
        timer.cancel()
        proc.stdout.close()
    text = "\n".join(log)
    if killed["v"]:
        raise BlenderFailed(f"Blender did not finish the game asset within {timeout:.0f} s and was stopped.",
                            "Use a smaller texture size, the fast bake preset or lower budgets. Nothing was saved.",
                            tail(text))
    if not report or not report.get("ok") or proc.returncode != 0:
        err = (report or {}).get("error") or f"Blender stopped without a result (exit {proc.returncode})."
        raise BlenderFailed(f"The game asset build failed: {err}", "Nothing was saved.", tail(text))
    res = json.loads((work / "result.json").read_text(encoding="utf-8"))
    res["wall_seconds"] = round(time.time() - t0, 3)
    return res


# ---- the build ---------------------------------------------------------------------------------------------------

def check_options(preset="gltf", budgets=None, texture_px=1024, bake="fast", pivot="bottom_center", uv="auto",
                  retopo="decimate", collision="hull", formats=None, maps=None) -> dict:
    """Every option checked; GameError names the first wrong one. Nothing has run yet."""
    try:
        pre = pz.preset(preset)
        b = pz.budgets(budgets)
        px = pz.texture_px(texture_px)
        pz.pivot_offset(np.zeros((1, 3)), pivot)
    except ValueError as e:
        raise GameError(str(e))
    if bake not in pz.BAKE:
        raise GameError(f"bake must be one of {', '.join(pz.BAKE)}.")
    if uv not in UV_METHODS:
        raise GameError(f"uv must be one of {', '.join(UV_METHODS)}.")
    if retopo not in RETOPO:
        raise GameError(f"retopo must be one of {', '.join(RETOPO)}.")
    if collision not in COLLISION:
        raise GameError(f"collision must be one of {', '.join(COLLISION)}.")
    fm = list(pre["formats"]) + [f for f in (formats or []) if f not in pre["formats"]]
    bad = [f for f in fm if f not in ("glb",) + pz.EXTRA_FORMATS]
    if bad:
        raise GameError(f"Unknown format {bad[0]!r}. Formats: glb, " + ", ".join(pz.EXTRA_FORMATS) + ".")
    mp = list(pz.MAPS if maps is None else maps)
    if any(m not in pz.MAPS for m in mp):
        raise GameError(f"maps must be from {', '.join(pz.MAPS)}.")
    return {"preset": pre, "budgets": b, "texture_px": px, "bake": bake, "pivot": pivot, "uv": uv,
            "retopo": retopo, "collision": collision, "formats": fm, "maps": mp}


def options_key(opts: dict, extra=None) -> str:
    from ..studio import H
    o = {k: (v["id"] if k == "preset" else v) for k, v in opts.items()}
    return H("game_asset", RUNNER_VERSION, o, extra)


def build(source: dict, out_dir, asset: str = "asset", preset="gltf", budgets=None, texture_px=1024, bake="fast",
          pivot="bottom_center", uv="auto", retopo="decimate", collision="hull", formats=None, maps=None,
          cfg: dict | None = None, timeout: float = TIMEOUT_S, app: str | None = None, progress=None) -> dict:
    """Build a game asset into out_dir and return its report (also written as out_dir/report.json).

    source: {"cage": CageData, "materials": {region|"default": {finish, color, pattern}}} or
            {"mesh": (V, T), "face_material": [index per triangle], "materials": [material, ...]}.
    Raises GameError (bad options, before Blender starts), BlenderMissing or BlenderFailed."""
    from ..adapters.blender import BlenderMissing, resolve, version
    opts = check_options(preset, budgets, texture_px, bake, pivot, uv, retopo, collision, formats, maps)
    pre, B, px = opts["preset"], opts["budgets"], opts["texture_px"]
    asset = pz.safe_name(asset)
    notes = []
    # -- the input, pivoted ----------------------------------------------------------------------------------------
    if "cage" in source:
        cage = source["cage"]
        if not isinstance(cage, meshsource.CageData):
            cage = meshsource.CageData.from_dict(cage)
        if cage.open_edges():
            raise GameError(f"The cage has {cage.open_edges()} open edges; the game pipeline needs a closed cage.")
        mats, face_mat = region_materials(cage, source.get("materials"))
        off = pz.pivot_offset(cage.V, pivot)
        V = cage.V + off
        method, why = uv_method(cage, uv)
        plan = lodmod.plan_lods(cage.F, B)
        hl = lodmod.high_level(cage.F, plan[0]["expected_tris"])
        try:                                     # hull input: two Catmull-Clark steps approach the limit surface
            from ..craft import subd
            Vh, Fh = subd.catmull_clark(V, cage.F)
            Vh, Fh = subd.catmull_clark(Vh, [list(f) for f in Fh])
            hull_P = np.asarray(Vh)
            hull_T = np.array([[f[0], f[1], f[2]] for f in Fh] + [[f[0], f[2], f[3]] for f in Fh])
        except Exception:                        # noqa: BLE001 - the cage points bound the surface
            hull_P = V
            hull_T = np.array([[f[0], f[k], f[k + 1]] for f in cage.F for k in range(1, len(f) - 1)])
        arrays = {"V": V, "F_flat": np.array([i for f in cage.F for i in f], np.int64),
                  "F_len": np.array([len(f) for f in cage.F], np.int64),
                  "crease_e": np.array([[a, b] for a, b, _ in cage.creases], np.int64).reshape(-1, 2),
                  "crease_s": np.array([s for *_, s in cage.creases], np.float64),
                  "face_region": _face_region(cage), "face_mat": np.array(face_mat, np.int64)}
        lods_job = [{"lod": p["lod"], "name": pz.lod_name(asset, p["lod"]), "budget": p["budget"],
                     "level": p["level"], "decimate": p["decimate"], "source": p["source"]} for p in plan]
        src_info = {"kind": "cage", "points": len(cage.V), "faces": len(cage.F), "regions": sorted(cage.regions),
                    "creases": len(cage.creases), "high_level": hl, "hash": cage.hash()}
    elif "mesh" in source:
        Vm, Tm = (np.asarray(a) for a in source["mesh"])
        Vm = Vm.astype(np.float64).reshape(-1, 3)
        Tm = Tm.astype(np.int64).reshape(-1, 3)
        mats_in = source.get("materials") or [DEFAULT_MATERIAL]
        mats = [material_spec(m.get("label") or f"zone{i}", m) for i, m in enumerate(mats_in)]
        fm = np.asarray(source.get("face_material", np.zeros(len(Tm))), np.int64)
        if len(fm) != len(Tm) or (len(fm) and (fm.min() < 0 or fm.max() >= len(mats))):
            raise GameError("face_material must give a material index for every triangle.")
        Vm, Tm, fm, welded = weld_mesh(Vm, Tm, fm)
        if welded:
            notes.append(f"Welded {welded} coincident points (a CAD tessellation splits points at face borders).")
        off = pz.pivot_offset(Vm, pivot)
        V = Vm + off
        method, why = "smart", "a mesh (CAD tessellation) has no regions: Smart UV Project on LOD0"
        hull_P, hull_T = V, Tm
        arrays = {"V": V, "T": Tm, "face_mat": fm}
        lods_job = [{"lod": i, "name": pz.lod_name(asset, i), "budget": b} for i, b in enumerate(B)]
        hl = None
        src_info = {"kind": "mesh", "points": len(Vm), "triangles": len(Tm)}
    else:
        raise GameError("source must hold a cage or a mesh.")
    # -- collision ---------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    hulls = []
    if opts["collision"] == "hull":
        hulls = lodmod.convex_parts(hull_P, hull_T)
    elif opts["collision"] == "coacd":
        try:
            hulls = lodmod.coacd_parts(hull_P, hull_T, cfg)
        except RuntimeError as e:
            notes.append(f"{e} Used a convex hull per part instead.")
            hulls = lodmod.convex_parts(hull_P, hull_T)
    coll_secs = round(time.perf_counter() - t0, 3)
    coll_names = [pz.collision_name(pre, asset, i) for i in range(len(hulls))]
    # -- Blender -----------------------------------------------------------------------------------------------------
    if app is None:
        r = resolve(cfg)
        if not r["available"]:
            raise BlenderMissing(r["reason"])
        app, ver = r["app"], r["version"]
    else:
        ver = version(app)
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="form-game-", dir=str(out_dir.parent)))
    try:
        run_dir = work / "run"
        (run_dir / "blender-user").mkdir(parents=True)
        np.savez(run_dir / "input.npz", **arrays)
        if hulls:
            np.savez(run_dir / "collision.npz", n=len(hulls), **{f"V{i}": h["V"] for i, h in enumerate(hulls)},
                     **{f"T{i}": h["T"] for i, h in enumerate(hulls)})
        exports = []
        for f in opts["formats"]:
            if f == "glb":
                continue
            ex_pre = pre if f == "fbx" else pz.preset("gltf")
            exports.append({"format": f, "file": f"{asset}.{f}", "unit": ex_pre["unit"], "up": ex_pre["up"],
                            "scale": ex_pre["scale"], "names": {}, "lod0": pz.lod_name(asset, 0)})
        bk = pz.BAKE[opts["bake"]]
        job = {"runner": RUNNER_VERSION, "asset": asset, "source": "cage" if "cage" in source else "mesh",
               "input": "input.npz", "materials": [{k: m[k] for k in ("name", "color", "roughness", "metallic",
                                                                       "pattern", "pattern_mm")} for m in mats],
               "lods": lods_job, "high_level": hl, "retopo": opts["retopo"],
               "uv": {"method": method, "margin_px": 4}, "texture_px": px, "smooth_angle_deg": 40.0,
               "bake": {"samples": bk["samples"], "ao_samples": bk["ao_samples"], "margin_px": bk["margin_px"],
                        "device": bk["device"], "maps": opts["maps"]},
               "collision": "collision.npz" if hulls else None, "collision_names": coll_names, "exports": exports}
        jp = run_dir / "job.json"
        jp.write_text(json.dumps(job), encoding="utf-8")
        res = _run_blender(app, ver, jp, run_dir, timeout, progress)
        # -- the GLB, here -------------------------------------------------------------------------------------------
        stage = work / "out"
        (stage / "textures").mkdir(parents=True)
        (stage / "lods").mkdir()
        gl = pz.preset("gltf")
        images, names = [], {}
        for key in ("base_color", "orm", "normal", "ao"):
            f = (res.get("bake") or {}).get("files", {}).get(key)
            if f:
                shutil.copy2(run_dir / f, stage / "textures" / f"{asset}_{key}.png")
                if key != "ao":
                    names[key] = len(images)
                    images.append((run_dir / f).read_bytes())
        mat = {"name": f"M_{asset}", "base_color": [1, 1, 1, 1], "metallic": 1.0 if "orm" in names else 0.0,
               "roughness": 1.0 if "orm" in names else 0.6, "base_color_tex": names.get("base_color"),
               "orm_tex": names.get("orm"), "normal_tex": names.get("normal")}
        if not images:
            m0 = mats[0]
            mat.update(base_color=m0["color"] + [1.0], metallic=m0["metallic"], roughness=m0["roughness"])
        nodes, lod_mm = [], {}
        for r in res["lods"]:
            z = np.load(run_dir / f"lod{r['lod']}.npz", allow_pickle=False)
            shutil.copy2(run_dir / f"lod{r['lod']}.npz", stage / "lods" / f"lod{r['lod']}.npz")
            lod_mm[r["lod"]] = z["P"]
            uvs = np.c_[z["UV"][:, 0], 1.0 - z["UV"][:, 1]]          # glTF: v runs down
            nodes.append({"name": pz.lod_name(asset, r["lod"]), "P": pz.to_engine(z["P"], gl),
                          "N": pz.to_engine(z["N"], {"scale": 1.0, "up": "Y"}), "UV": uvs, "idx": z["T"],
                          "material": 0, "extras": {"lod": r["lod"], "budget": r["budget"]}})
        cnodes = [{"name": n, "P": pz.to_engine(h["V"], gl), "idx": h["T"],
                   "extras": {"form": "collision", "shape": h["method"]}} for n, h in zip(coll_names, hulls)]
        main = nodes + (cnodes if pre["id"] == "godot" else [])
        extras = {"form": {"asset": asset, "preset": pre["id"], "units": "m", "up": "+Y", "from": "millimetres x 0.001"}}
        (stage / f"{asset}.glb").write_bytes(meshio.glb_scene(main, [mat], images, extras=extras))
        if cnodes:
            (stage / f"{asset}_collision.glb").write_bytes(meshio.glb_scene(cnodes, extras=extras))
        for e in res.get("exports", []):
            shutil.copy2(run_dir / e["file"], stage / e["file"])
        # -- checks --------------------------------------------------------------------------------------------------
        size_mm = (lod_mm[0].max(0) - lod_mm[0].min(0)).tolist()
        val = vmod.validate((stage / f"{asset}.glb").read_bytes(), B, px, expect_size_mm=size_mm)
        exp_checks = []
        for e in res.get("exports", []):
            got = (e.get("reimport") or {}).get("lod0_size_m")
            if got:
                want = np.asarray(size_mm) * 0.001
                gs = np.sort(np.asarray(got))
                err = float(np.max(np.abs(gs - np.sort(want)) / np.maximum(np.sort(want), 1e-12)))
                e["size_error"] = round(err, 6)
                exp_checks.append({"id": f"export_{e['format']}", "label": f"{e['format'].upper()} reads back at the "
                                   "design's size", "status": "PASS" if err <= vmod.SCALE_TOL else "FAIL",
                                   "value": f"{err * 100:.3f}% size error", "evidence": "computed",
                                   "detail": "Re-imported into Blender and measured in metres (axes compared as "
                                             "sorted extents)."})
        val["checks"] += exp_checks
        val["checks"] += _normal_checks(stage, asset)
        val["ok"] = all(c["status"] == "PASS" for c in val["checks"])
        report = {"asset": asset, "preset": {k: pre[k] for k in ("id", "label", "unit", "up")},
                  "budgets": B, "texture_px": px, "bake_preset": opts["bake"], "pivot": pivot,
                  "pivot_offset_mm": [round(float(x), 6) for x in off], "size_mm": [round(x, 4) for x in size_mm],
                  "source": src_info, "uv": {"method": method, "why": why}, "materials":
                  [{k: m[k] for k in ("name", "finish", "hex", "pattern")} for m in mats],
                  "lods": res["lods"], "high_triangles": res["high_triangles"], "bake": res.get("bake"),
                  "collision": {"method": opts["collision"], "parts": len(hulls), "names": coll_names,
                                "seconds": coll_secs, "hull_points": [int(len(h["V"])) for h in hulls]},
                  "exports": res.get("exports", []), "timing": {**res.get("timing", {}),
                                                                "blender_wall": res.get("wall_seconds")},
                  "blender": res.get("blender") or ver, "validation": val, "notes": notes,
                  "files": sorted(str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file()),
                  "retopology_note": "Decimated or QuadriFlow LODs are automatic retopology, not hand topology."}
        (stage / "report.json").write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
        if out_dir.exists():
            old = out_dir.with_name(out_dir.name + f".old-{os.getpid()}")
            out_dir.rename(old)
            stage.rename(out_dir)
            shutil.rmtree(old, ignore_errors=True)
        else:
            stage.rename(out_dir)
        report["dir"] = str(out_dir)
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def weld_mesh(V: np.ndarray, T: np.ndarray, fm: np.ndarray, tol_mm: float = 1e-4):
    """Points within tol_mm merged and triangles that collapse dropped: a CAD tessellation is one patch per face, and
    decimating unwelded patches opens cracks. Returns (V, T, face material, points merged)."""
    key = np.round(V / tol_mm).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    T2 = inv.reshape(-1)[T]
    keep = (T2[:, 0] != T2[:, 1]) & (T2[:, 1] != T2[:, 2]) & (T2[:, 0] != T2[:, 2])
    return V[first], T2[keep], fm[keep], int(len(V) - len(first))


def _face_region(cage: meshsource.CageData) -> np.ndarray:
    r = np.full(len(cage.F), -1, np.int64)
    for k, name in enumerate(sorted(cage.regions)):
        r[cage.regions[name]] = k
    return r if cage.regions else np.zeros(0, np.int64)


def _normal_checks(stage: Path, asset: str) -> list[dict]:
    """The baked normal map against LOD0's UVs (validate.normal_map_check), when both are there."""
    png, lod0 = stage / "textures" / f"{asset}_normal.png", stage / "lods" / "lod0.npz"
    if not (png.is_file() and lod0.is_file()):
        return []
    z = np.load(lod0, allow_pickle=False)
    return [vmod.normal_map_check(png.read_bytes(), z["UV"], z["T"])]


def revalidate(out_dir) -> dict:
    """validate.validate on a built asset's GLB again, with the budgets and texture size it was built with, and the
    baked normal map against LOD0's UVs."""
    out_dir = Path(out_dir)
    rep = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    v = vmod.validate((out_dir / f"{rep['asset']}.glb").read_bytes(), rep["budgets"], rep["texture_px"],
                      expect_size_mm=rep["size_mm"])
    v["checks"] += _normal_checks(out_dir, rep["asset"])
    v["ok"] = all(c["status"] == "PASS" for c in v["checks"])
    return v

