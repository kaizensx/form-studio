"""Runs INSIDE Blender (bpy), headless:  blender -b --factory-startup --python blender_scene.py -- job.json

Builds a small product-shot scene around one STL and renders one PNG. Every number comes from the job file
written by form/adapters/blender.py; this file only turns it into Blender objects. It prints one line
`FORM_RESULT {json}` at the end, with "error" set when something went wrong.

The picture is an illustration: invented light, invented material. It is not a photo of a print.
"""
import json
import math
import sys
import time
import traceback

import bmesh
import bpy
from mathutils import Euler, Vector


def step(text):
    print("FORM_STEP " + text, flush=True)


def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def principled(name, color, roughness, **kw):
    m = bpy.data.materials.new(name)
    if bpy.app.version < (5, 0, 0):        # node trees are always on from Blender 5
        m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = roughness
    names = {"metallic": "Metallic", "specular": "Specular IOR Level", "coat": "Coat Weight", "sheen": "Sheen Weight",
             "subsurface": "Subsurface Weight"}
    for k, v in kw.items():
        if k in names and names[k] in b.inputs:
            b.inputs[names[k]].default_value = v
    return m, b


def import_stl(path):
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=path, forward_axis="Y", up_axis="Z")
    else:                                                  # Blender < 4.1
        bpy.ops.import_mesh.stl(filepath=path, axis_forward="Y", axis_up="Z")
    obj = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = obj
    return obj


def twill_image(n=256):
    """A 2x2 twill tile (8 x 8 tows), drawn with numpy: each tow a rounded band with fibre streaks along it, the two
    directions at different brightness so the weave reads under a clear coat. Values 0..1 in the red channel
    (brightness), the green channel holds which way the tow runs (1 = along u)."""
    import numpy as np
    cells = 8
    s = n // cells
    u = (np.arange(n) % s) / s
    U, V = np.meshgrid(u, u)
    cu = np.arange(n)[None, :] // s
    cv = np.arange(n)[:, None] // s
    along_u = ((cu + cv) // 2 % 2 == 0)
    across = np.where(along_u, V, U)                       # position across the tow
    prof = np.sqrt(np.clip(np.sin(np.pi * across), 0, 1))
    rng = np.random.default_rng(7)
    fib = rng.random((n, n))
    streak = np.where(along_u, np.repeat(fib[:, :1], n, 1), np.repeat(fib[:1, :], n, 0))
    b = np.where(along_u, 0.72, 0.38) * (0.55 + 0.45 * prof) * (0.88 + 0.12 * streak)
    img = bpy.data.images.new("Twill", n, n, alpha=False, float_buffer=True)
    px = np.zeros((n, n, 4), np.float32)
    px[..., 0] = b
    px[..., 1] = along_u.astype(np.float32)
    px[..., 2] = prof
    px[..., 3] = 1
    img.pixels.foreach_set(px.ravel())
    img.pack()
    return img


def material(name, finish, color, layer_mm=None):
    """A Principled material for a finish (see FINISHES in blender.py); carbon and smoke get their own node set-ups."""
    f = finish
    kind = f.get("id", "matte")
    m, b = principled(name, color, f["roughness"], metallic=f["metallic"], specular=f["specular"], coat=f["coat"],
                      sheen=f["sheen"], subsurface=f["subsurface"])
    nt = m.node_tree
    if "Coat Roughness" in b.inputs and f.get("coat_roughness") is not None:
        b.inputs["Coat Roughness"].default_value = f["coat_roughness"]
    if kind == "smoke":                                    # tinted polycarbonate: transmissive, glossy, dark
        for k, v in (("Transmission Weight", 1.0), ("IOR", 1.58), ("Alpha", 1.0)):
            if k in b.inputs:
                b.inputs[k].default_value = v
        try:
            m.blend_method = "HASHED"
        except (AttributeError, TypeError):
            pass
    if kind == "carbon":                                   # a box-projected twill: tow brightness and sheen, clear coat
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        tile = float(f.get("tile_mm", 24.0))               # 8 tows per tile: 3 mm tows
        mp.inputs["Scale"].default_value = (1 / tile, 1 / tile, 1 / tile)
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = twill_image()
        tex.projection = "BOX"
        tex.projection_blend = 0.25
        tex.interpolation = "Cubic"
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], tex.inputs["Vector"])
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(tex.outputs["Color"], sep.inputs[0])
        base = nt.nodes.new("ShaderNodeMix")
        base.data_type = "RGBA"
        base.inputs["A"].default_value = (*[c * 0.12 for c in color], 1)
        base.inputs["B"].default_value = (*[min(1.0, c * 0.75 + 0.004) for c in color], 1)
        nt.links.new(sep.outputs[0], base.inputs["Factor"])
        nt.links.new(base.outputs["Result"], b.inputs["Base Color"])
        rough = nt.nodes.new("ShaderNodeMapRange")
        rough.inputs["To Min"].default_value = 0.55
        rough.inputs["To Max"].default_value = 0.22
        nt.links.new(sep.outputs[0], rough.inputs["Value"])
        nt.links.new(rough.outputs["Result"], b.inputs["Roughness"])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.12
        bump.inputs["Distance"].default_value = 0.0002
        nt.links.new(sep.outputs[2], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    if layer_mm and kind in ("matte", "petg", "silk"):
        # printed layer lines: a faint ridge every layer height, along the print's Z
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = 2 * math.pi / layer_mm
        sine = nt.nodes.new("ShaderNodeMath")
        sine.operation = "SINE"
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.16
        bump.inputs["Distance"].default_value = 0.00004
        nt.links.new(tc.outputs["Object"], sep.inputs[0])
        nt.links.new(sep.outputs["Z"], mul.inputs[0])
        nt.links.new(mul.outputs[0], sine.inputs[0])
        nt.links.new(sine.outputs[0], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def parts(job):
    """Every part of the job (one STL, or one per material zone), each with its own material. Returns the objects."""
    specs = job.get("parts") or [{"stl": job["stl"], "finish": job["finish"], "color": job["color"]}]
    objs = []
    for i, sp in enumerate(specs):
        obj = import_stl(sp["stl"])
        me = obj.data
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
        bmesh.ops.translate(bm, verts=bm.verts, vec=Vector(job["offset_mm"]))
        bm.to_mesh(me)
        bm.free()
        obj.location = (0, 0, 0)
        obj.rotation_euler = (0, 0, 0)
        obj.scale = (0.001, 0.001, 0.001)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(32))
        except Exception:
            bpy.ops.object.shade_flat()
        me.materials.append(material(f"Zone{i}", sp["finish"], sp["color"], job.get("layer_mm")))
        objs.append(obj)
    return objs


def sweep(name, width, depth, height, radius, rot_z, color, roughness, back=0.0, specular=0.3):
    """A seamless backdrop: floor toward the camera, a curved cove `back` behind the part, a wall. Built facing -Y, then turned."""
    prof = [(-depth, 0.0)]
    for i in range(0, 25):
        a = math.pi / 2 * i / 24
        prof.append((back + radius * math.sin(a), radius * (1 - math.cos(a))))
    prof.append((back + radius, height))
    bm = bmesh.new()
    rows = [[bm.verts.new((x, y, z)) for (y, z) in prof] for x in (-width / 2, width / 2)]
    for i in range(len(prof) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    obj.rotation_euler = Euler((0, 0, rot_z))
    m, _ = principled(name, color, roughness, specular=specular)
    me.materials.append(m)
    return obj


def wood(name, size, grain=0.011):
    """A desk top. grain: metres between growth rings (about 18 mm)."""
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    m, b = principled(name, (0.3, 0.17, 0.08), 0.45, specular=0.35)
    nt = m.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    links = nt.links

    def op(kind, a=None, b=None, c=None):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = kind
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                links.new(v, n.inputs[i])
        return n.outputs[0]

    # growth rings seen edge-on: streaks along X whose phase wanders slowly (noise stretched along the grain)
    stretch = nt.nodes.new("ShaderNodeMapping")
    stretch.inputs["Scale"].default_value = (0.08, 1.0, 1.0)
    links.new(tc.outputs["Object"], stretch.inputs["Vector"])
    wander = nt.nodes.new("ShaderNodeTexNoise")
    wander.inputs["Scale"].default_value = 0.25 / grain
    wander.inputs["Detail"].default_value = 3.0
    links.new(stretch.outputs["Vector"], wander.inputs["Vector"])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["Object"], sep.inputs[0])
    phase = op("MULTIPLY_ADD", wander.outputs["Fac"], 30.0, op("MULTIPLY", sep.outputs["Y"], 2 * math.pi / grain))
    ring = op("POWER", op("MULTIPLY_ADD", op("SINE", phase), 0.5, 0.5), 2.5)
    fib = nt.nodes.new("ShaderNodeTexNoise")          # fine fibres, also stretched along the grain
    fib.inputs["Scale"].default_value = 6.0 / grain
    fib.inputs["Detail"].default_value = 5.0
    links.new(stretch.outputs["Vector"], fib.inputs["Vector"])
    v = op("MULTIPLY_ADD", fib.outputs["Fac"], 0.5, op("MULTIPLY", ring, 0.75))
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.33, 0.18, 0.085, 1)
    ramp.color_ramp.elements[1].color = (0.15, 0.07, 0.03, 1)
    links.new(v, ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    obj.data.materials.append(m)
    return obj


def light(name, loc, target, size, energy, color=(1, 1, 1), shape="RECTANGLE"):
    d = bpy.data.lights.new(name, "AREA")
    d.shape, d.size, d.energy, d.color = shape, size, energy, color
    if shape == "RECTANGLE":
        d.size_y = size * 0.7
    obj = bpy.data.objects.new(name, d)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    look_at(obj, target)
    return obj


def around(target, az_deg, el_deg, dist):
    az, el = math.radians(az_deg), math.radians(el_deg)
    return Vector(target) + Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * dist


def world(color, strength):
    w = bpy.data.worlds.new("World")
    if bpy.app.version < (5, 0, 0):
        w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (*color, 1)
    bg.inputs["Strength"].default_value = strength
    bpy.context.scene.world = w


def stage(job):
    """Backdrop and lights for the preset. Sizes follow the part; intensities follow the light's distance squared."""
    s = max(job["size_m"], 0.02)
    tgt = job["camera"]["target"]
    az = job["view"]["az"]
    D = job["camera"]["distance_m"]
    rot = math.radians(az)
    p = job["preset"]
    if p == "studio":
        sweep("Backdrop", 8 * D, 5 * D, 4 * D, 0.7 * D, rot, (0.5, 0.5, 0.49), 0.85, back=0.5 * D)
        r = 1.1 * D
        light("Key", around(tgt, az - 48, 52, r), tgt, 0.6 * D, 17 * r * r)
        light("Fill", around(tgt, az + 62, 22, r), tgt, 1.0 * D, 2.5 * r * r)
        light("Top", around(tgt, az + 180, 75, 0.9 * r), tgt, 0.5 * D, 7 * r * r)
        world((0.8, 0.8, 0.8), 0.08)
    elif p == "desk":
        wood("Desk", 60 * s)
        wall = sweep("Wall", 60 * s, 0.01 * s, 30 * s, 0.01 * s, rot, (0.55, 0.47, 0.38), 0.95)
        wall.location = around((0, 0, 0), az + 180, 0, 7 * s)
        r = 1.2 * D
        light("Window", around(tgt, az - 70, 38, r), tgt, 1.6 * D, 36 * r * r, color=(1.0, 0.93, 0.84))
        light("Bounce", around(tgt, az + 60, 15, r), tgt, 1.4 * D, 5 * r * r, color=(0.9, 0.95, 1.0))
        world((0.65, 0.6, 0.55), 0.25)
    else:  # dark
        sweep("Backdrop", 8 * D, 5 * D, 4 * D, 0.7 * D, rot, (0.014, 0.017, 0.019), 0.9, back=0.5 * D, specular=0.12)
        r = 1.1 * D
        light("Key", around(tgt, az - 40, 48, r), tgt, 0.6 * D, 12 * r * r, color=(0.95, 0.98, 1.0))
        light("Rim", around(tgt, az + 155, 30, 0.8 * D), tgt, 0.4 * D, 30 * (0.8 * D) ** 2, color=(0.8, 0.95, 0.9))
        light("Fill", around(tgt, az + 70, 10, r), tgt, 1.0 * D, 2.5 * r * r)
        world((0.02, 0.025, 0.028), 0.15)


def camera(job):
    c = job["camera"]
    d = bpy.data.cameras.new("Camera")
    d.lens, d.sensor_width, d.sensor_fit = c["lens_mm"], c["sensor_mm"], "HORIZONTAL"
    d.clip_start, d.clip_end = c["distance_m"] / 100, c["distance_m"] * 100
    if job["preset"] == "desk":
        d.dof.use_dof = True
        d.dof.focus_distance = c["distance_m"]
        d.dof.aperture_fstop = 5.6
    obj = bpy.data.objects.new("Camera", d)
    bpy.context.collection.objects.link(obj)
    obj.location = c["location"]
    look_at(obj, c["target"])
    bpy.context.scene.camera = obj


def gpu(scene):
    """Use a GPU for Cycles when there is one; otherwise the CPU. Returns what was used."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return "CPU"
    for kind in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
        except (TypeError, ValueError):
            continue
        devs = [d for d in prefs.devices if d.type == kind]
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            scene.cycles.device = "GPU"
            return f"{devs[0].name} via {kind.title()}"
    scene.cycles.device = "CPU"
    return "CPU"


def settings(job):
    sc = bpy.context.scene
    r = sc.render
    r.resolution_x, r.resolution_y = job["resolution"]
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.filepath = job["out"]
    r.film_transparent = False
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    device = "GPU"
    if job["engine"] == "eevee":
        for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
            try:
                r.engine = eng
                break
            except TypeError:
                continue
        try:
            sc.eevee.taa_render_samples = job["samples"]
            sc.eevee.use_shadows = True
            sc.eevee.use_raytracing = True
        except AttributeError:
            pass
    else:
        r.engine = "CYCLES"
        device = gpu(sc)
        sc.cycles.samples = job["samples"]
        sc.cycles.use_adaptive_sampling = True
        sc.cycles.adaptive_threshold = 0.02
        sc.cycles.use_denoising = True
        try:
            sc.cycles.denoiser = "OPENIMAGEDENOISE"
        except TypeError:
            pass
        sc.cycles.max_bounces = 8
    return r.engine, device


def main():
    job = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    t0 = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    step("Importing the STL")
    objs = parts(job)
    step("Building the scene")
    stage(job)
    camera(job)
    engine, device = settings(job)
    step(f"Rendering with {engine.replace('BLENDER_', '').title()} on {device}")
    # progress: Blender 5 no longer prints per-sample lines in background mode, so report its render stats
    bpy.app.handlers.render_stats.append(lambda stats: print("FORM_STATS " + str(stats), flush=True))
    bpy.ops.render.render(write_still=True)
    return {"ok": True, "engine": engine, "device": device, "samples": job["samples"], "blender": bpy.app.version_string,
            "triangles": sum(len(o.data.polygons) for o in objs), "parts": len(objs),
            "render_s": round(time.time() - t0, 2)}


if __name__ == "__main__":
    try:
        out = main()
    except Exception as e:
        print("FORM_RESULT " + json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}), flush=True)
        traceback.print_exc()
        sys.exit(3)
    print("FORM_RESULT " + json.dumps(out), flush=True)
