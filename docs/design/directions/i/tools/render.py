import bpy, sys, json, math, mathutils
argv = sys.argv[sys.argv.index("--") + 1:]
geo, outdir, only = argv[0], argv[1], set(argv[2:])
D = 52.0
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"; sc.cycles.samples = 160; sc.cycles.use_denoising = True
    try:
        pr = bpy.context.preferences.addons["cycles"].preferences; pr.compute_device_type = "METAL"; pr.get_devices()
        for d in pr.devices: d.use = True
        sc.cycles.device = "GPU"
    except Exception as e: print("cpu", e)
    sc.render.film_transparent = True; sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Medium High Contrast"
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.92, 1, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.16
    return sc
def clay(name="clay", col=(0.80, 0.765, 0.70), rough=0.58, metal=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*col, 1); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
    return m
def vcol(name, emit=0.0, rough=0.6):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    a = nt.nodes.new("ShaderNodeAttribute"); a.attribute_name = "Col"
    nt.links.new(a.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
    if emit:
        nt.links.new(a.outputs["Color"], b.inputs["Emission Color"])
        mth = nt.nodes.new("ShaderNodeMath"); mth.operation = "POWER"; mth.inputs[1].default_value = 1.6
        nt.links.new(a.outputs["Alpha"], mth.inputs[0])
        m2 = nt.nodes.new("ShaderNodeMath"); m2.operation = "MULTIPLY"; m2.inputs[1].default_value = emit
        nt.links.new(mth.outputs[0], m2.inputs[0]); nt.links.new(m2.outputs[0], b.inputs["Emission Strength"])
    return m
def load(path, mat, rot=None, loc=(0, 0, 0), smooth=True):
    if path.endswith(".stl"): bpy.ops.wm.stl_import(filepath=path)
    else: bpy.ops.wm.ply_import(filepath=path)
    o = bpy.context.selected_objects[0]; o.data.materials.clear(); o.data.materials.append(mat)
    if smooth:
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.shade_auto_smooth(angle=math.radians(30))
    if rot: o.rotation_euler = rot
    o.location = loc
    return o
def floor(size=2000):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0)); p = bpy.context.object; p.is_shadow_catcher = True
    p.data.materials.append(clay("floor", (0.5, 0.5, 0.5), 0.9)); return p
def lights(scale=1.0, key=1.0):
    def area(loc, size, power, col, tgt=(0, 26, 25)):
        bpy.ops.object.light_add(type="AREA", location=loc); l = bpy.context.object
        l.data.size = size; l.data.energy = power * 0.092; l.data.color = col
        l.rotation_euler = (mathutils.Vector(tgt) - mathutils.Vector(loc)).to_track_quat("-Z", "Y").to_euler(); return l
    s = scale
    area((-130 * s, -150 * s, 230 * s), 190 * s, 5.2e6 * s * s * key, (1.0, 0.925, 0.84))      # warm key, high left front
    area((240 * s, -60 * s, 90 * s), 220 * s, 1.5e6 * s * s, (0.86, 0.93, 1.0))                # cool fill from the right
    area((40 * s, 260 * s, 160 * s), 160 * s, 1.9e6 * s * s, (0.75, 0.92, 1.0))                # rim from behind
def camera(sc, target, ortho, res, az=-55, el=28):
    a, e = math.radians(az), math.radians(el)
    d = mathutils.Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
    T = mathutils.Vector(target)
    bpy.ops.object.camera_add(location=T + d * 600); c = bpy.context.object
    c.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler(); c.data.type = "ORTHO"; c.data.ortho_scale = ortho
    c.data.clip_start = 1; c.data.clip_end = 3000; sc.camera = c; sc.render.resolution_x, sc.render.resolution_y = res
    bpy.context.view_layer.update()
    R = c.matrix_world.to_3x3(); right = R @ mathutils.Vector((1, 0, 0)); up = R @ mathutils.Vector((0, 1, 0))
    k = res[0] / ortho
    return {"T": list(T), "right": list(right), "up": list(up), "pxmm": k / 2, "w": res[0] / 2, "h": res[1] / 2}
def go(sc, name):
    sc.render.filepath = f"{outdir}/{name}.png"; bpy.ops.render.render(write_still=True); print("wrote", name)
proj = {}
RES = (1760, 1760); T0 = (0, 26, 27); ORTHO = 116
def part_scene(name, mesh, mat_fn, key=1.0):
    if only and name not in only: return
    sc = reset(); floor(); lights(key=key); load(f"{geo}/{mesh}", mat_fn(), smooth=mesh.endswith(".stl"))
    proj["part"] = camera(sc, T0, ORTHO, RES); go(sc, name)
for i in (1, 2, 3, 5, 8):
    part_scene(f"mount-s{i}", f"s{i}.stl", clay)
part_scene("mount-heat", "heat.ply", lambda: vcol("heat", emit=2.2), key=0.55)
# milling frame: x, z -> y', D - y -> z'   (rotate -90 deg about X, then lift by D)
MILL = (math.radians(-90), 0, math.radians(180))
if not only or "cam-stock" in only:
    sc = reset(); floor(); lights(key=1.0)
    load(f"{geo}/stock.ply", vcol("stock", rough=0.42), smooth=False)
    alu = clay("tool", (0.82, 0.83, 0.85), 0.25, 1.0)
    cam = json.load(open(f"{geo}/cam.json")); tx, ty, tz = 6.0, cam["yprog"], cam["level"]
    bpy.ops.mesh.primitive_cylinder_add(radius=3.0, depth=22, vertices=64, location=(tx, ty, tz + 11)); bpy.context.object.data.materials.append(alu)
    bpy.ops.mesh.primitive_cylinder_add(radius=3.0, depth=30, vertices=64, location=(tx, ty, tz + 37)); bpy.context.object.data.materials.append(clay("shank", (0.55, 0.56, 0.58), 0.3, 1.0))
    bpy.ops.mesh.primitive_cone_add(radius1=5, radius2=9, depth=10, vertices=64, location=(tx, ty, tz + 57)); bpy.context.object.data.materials.append(clay("holder", (0.12, 0.12, 0.13), 0.35, 1.0))
    proj["cam"] = camera(sc, (0, 31, 30), 150, RES); proj["cam"]["tool"] = [tx, ty, tz]; go(sc, "cam-stock")
def plate(name, spots):
    if only and name not in only: return
    sc = reset(); floor(); lights(scale=2.4, key=1.0)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1.5)); p = bpy.context.object; p.scale = (184, 184, 3)
    bpy.ops.object.transform_apply(scale=True); bv = p.modifiers.new("b", "BEVEL"); bv.width = 3; bv.segments = 6
    p.data.materials.append(clay("plate", (0.045, 0.047, 0.05), 0.42, 0.0))
    m = clay()
    for (px, py) in spots:
        load(f"{geo}/s8.stl", m, rot=MILL, loc=(px, py + 31, 3 + D))
    proj["plate"] = camera(sc, (0, 0, 16), 300, (1760, 1320)); go(sc, name)
xs = (-60, 0, 60); ys = (-36, 36)
plate("plate-1", [(x, y) for y in ys for x in xs])
plate("plate-2", [(-60, 36), (0, 36)])
json.dump(proj, open(f"{outdir}/proj.json", "w"), indent=1)
