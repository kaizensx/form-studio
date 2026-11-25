"""Make game assets from the game exemplars the way scripts/game_bench.py does, then photograph the GLB.

    .venv/bin/python scripts/media/showcase/game_shots.py make treasure_chest vehicle_wheel
    .venv/bin/python scripts/media/showcase/game_shots.py shoot treasure_chest 35 18 hero 1600 1200 128
    .venv/bin/python scripts/media/showcase/game_shots.py shoot treasure_chest 14 16 ladder 2400 800 96

make builds the asset (model, levels of detail, UVs, bakes, the GLB) from a brief of tests/design_bench/game_briefs.json
with 2048 px textures and prints its report; shoot renders the GLB in Cycles with three area lights on a dark floor:
"hero" is LOD0, "ladder" is every level of detail side by side with its triangle mesh drawn over it. The triangle
counts it prints are the GLB's own.
"""
import json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
S = Path(os.environ.get("SHOWCASE_WORK") or ROOT / ".dev" / "showcase")      # scratch: projects, zones, renders
S.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["FORM_DATA"] = str(S / "game-data")
os.environ["FORM_CONFIG"] = "/nonexistent"

SCENE = r'''
import math, sys, json
import bpy
from mathutils import Vector
glb, out, az, el, mode, W, H, samples = sys.argv[sys.argv.index("--") + 1:][:8]
az, el, W, H, samples = float(az), float(el), int(W), int(H), int(samples)
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
lods = sorted([o for o in meshes if "_LOD" in o.name], key=lambda o: o.name)
for o in meshes:
    o.hide_render = True
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = samples
sc.cycles.use_denoising = True
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"; prefs.get_devices()
    for d in prefs.devices: d.use = True
    sc.cycles.device = "GPU"
except Exception as e:
    print("cpu", e)
sc.render.resolution_x, sc.render.resolution_y = W, H
sc.view_settings.view_transform = "Filmic" if "Filmic" in [i.identifier for i in type(sc.view_settings).bl_rna.properties["view_transform"].enum_items] else "AgX"
world = bpy.data.worlds.new("w"); sc.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.012, 0.016, 0.018, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
def bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi
shown = [lods[0]]
tris = {}
for o in lods:
    me = o.data; me.calc_loop_triangles(); tris[o.name] = len(me.loop_triangles)
if mode == "ladder":
    lo, hi = bounds([lods[0]])
    step = (hi.x - lo.x) * 1.22
    shown = []
    for k, o in enumerate(lods):
        o.location.x += k * step
        shown.append(o)
        w = o.copy(); w.data = o.data.copy(); sc.collection.objects.link(w)
        mod = w.modifiers.new("wire", "WIREFRAME"); mod.thickness = (hi - lo).length * 0.0011; mod.use_replace = True
        m = bpy.data.materials.new("wire"); m.use_nodes = True
        nt = m.node_tree; nt.nodes.clear()
        e = nt.nodes.new("ShaderNodeEmission"); e.inputs["Color"].default_value = (0.49, 0.82, 0.69, 1); e.inputs["Strength"].default_value = 1.6
        o_ = nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(e.outputs[0], o_.inputs[0])
        w.data.materials.clear(); w.data.materials.append(m)
        w.hide_render = False
for o in shown:
    o.hide_render = False
bpy.context.view_layer.update()
lo, hi = bounds(shown)
c = (lo + hi) / 2
size = (hi - lo).length
# floor: a dark seamless plane under the asset
bpy.ops.mesh.primitive_plane_add(size=size * 40, location=(c.x, c.y, lo.z))
floor = bpy.context.active_object
fm = bpy.data.materials.new("floor"); fm.use_nodes = True
b = fm.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (0.02, 0.026, 0.03, 1); b.inputs["Roughness"].default_value = 0.75
floor.data.materials.append(fm)
def area(name, energy, loc, sz, col=(1, 1, 1)):
    l = bpy.data.lights.new(name, "AREA"); l.energy = energy; l.size = sz; l.color = col
    o = bpy.data.objects.new(name, l); o.location = loc; sc.collection.objects.link(o)
    o.rotation_euler = (c - o.location).to_track_quat("-Z", "Y").to_euler()
r = size / 2
a, e = math.radians(az), math.radians(el)
view = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
right = Vector((math.cos(a), math.sin(a), 0))
P = r * r * (38 if mode == "ladder" else 130)
area("key", 5.5 * P, c + (view * 1.2 + right * 1.6 + Vector((0, 0, 1.9))) * r, r * 2.2, (1.0, 0.95, 0.88))
area("fill", 1.1 * P, c + (view * 1.6 - right * 2.2 + Vector((0, 0, 0.6))) * r, r * 3.0, (0.8, 0.9, 1.0))
area("rim", (1.5 if mode == "ladder" else 5.0) * P, c + (-view * 2.0 - right * 0.8 + Vector((0, 0, 1.6))) * r, r * 1.6, (0.72, 0.95, 0.88))
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.lens = 85; cam.data.sensor_width = 36
# fit: project the bounding box corners and back the camera off until they fit
corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
up = right.cross(-view).normalized() * -1
up = Vector((0, 0, 1)) - view * view.z; up.normalize()
hw = max(abs((p - c).dot(right)) for p in corners); hh = max(abs((p - c).dot(up)) for p in corners)
fov_h = math.atan(18 / 85); fov_v = math.atan(18 * H / W / 85)
dist = max(hw / math.tan(fov_h), hh / math.tan(fov_v)) * (1.05 if mode == "ladder" else 1.16) + r
cam.location = c + view * dist
cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.clip_end = dist * 10
sc.render.filepath = out
sc.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)
print("RENDERED " + json.dumps(tris))
'''


def make(names):
    from form import config, game
    from form.exemplars import game as gex
    from form.studio import Studio
    briefs = {b["id"]: b for b in json.loads((ROOT / "tests/design_bench/game_briefs.json").read_text())["briefs"]}
    cfg = config.load()
    st = Studio(cfg)
    idx_f = S / "game.json"
    idx = json.loads(idx_f.read_text()) if idx_f.exists() else {}
    try:
        for n in names:
            b = briefs[n]
            t = time.time()
            ex = gex.make(b["exemplar"], st.cfg)
            p = st.create_design(b["title"], ex["source"], b["brief"], purpose="game")
            j = st.run_sync(p["id"], ["geometry", "exports"])
            res = game.game_asset(st, p["id"], preset=b["preset"], budgets=b["budgets"], texture_px=2048, bake="fast",
                                  materials=ex["materials"])
            gdir = Path(res["dir"])
            rep = json.loads((gdir / "report.json").read_text())
            idx[n] = {"glb": str(gdir / f"{rep['asset']}.glb"), "validation": res["validation"],
                      "lods": [{k: r[k] for k in ("lod", "triangles", "budget")} for r in res["lods"]],
                      "uv": res["uv"], "size_mm": rep["size_mm"], "seconds": round(time.time() - t, 1),
                      "textures": sorted(f.name for f in (gdir / "textures").glob("*"))}
            idx_f.write_text(json.dumps(idx, indent=1, default=str))
            print("MADE", n, json.dumps(idx[n], default=str)[:900], flush=True)
    finally:
        st.kernel.stop()


def shoot(name, az, el, mode="hero", W="1600", H="1200", samples="96"):
    from form import config
    from form.adapters import blender as bl
    app = bl.resolve(config.load())["app"]
    idx = json.loads((S / "game.json").read_text())
    script = S / "_game_scene.py"
    script.write_text(SCENE)
    out = S / "out" / f"game-{name}-{mode}.png"
    r = subprocess.run([app, "-b", "--factory-startup", "-noaudio", "--python", str(script), "--", idx[name]["glb"],
                        str(out), az, el, mode, W, H, samples], capture_output=True, text=True, timeout=1500)
    print([l for l in r.stdout.splitlines() if "RENDERED" in l] or (r.stdout[-1500:] + r.stderr[-1500:]))


if __name__ == "__main__":
    if sys.argv[1] == "make":
        make(sys.argv[2:])
    else:
        shoot(*sys.argv[2:])
