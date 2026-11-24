"""Form Studio's fixed game-asset runner. It runs inside Blender's own Python (blender -b ... --python blender_game.py).

It reads one job file (JSON, written by form/game/pipeline.py after the job was schema-checked there) and the
arrays next to it (input.npz, collision.npz: numpy files read with allow_pickle=False), then makes a game asset:

    1. the base mesh: a subdivision cage (points, polygons, creases, named regions, a material per face) or a mesh
       (a CAD tessellation, a material per face)
    2. UVs: angle-based unwrap with seams on region borders and sharp creases, or Smart UV Project; then packed
    3. the high-poly: the cage at subdivision level N (or the mesh as it is)
    4. LOD0..LOD3: cage levels, or Decimate (edge collapse) / QuadriFlow to the triangle budgets
    5. a Principled BSDF per material (colour, roughness, metallic, a fixed procedural pattern: wood, noise, brushed)
    6. Cycles bakes from the high-poly onto LOD0: base colour, tangent-space normal, roughness, metallic, AO;
       ORM packed (R AO, G roughness, B metallic) with numpy
    7. LOD arrays written back (lod<i>.npz: positions mm, corner normals, UVs, triangles); FBX and USD exported with
       Blender's own exporters when asked, and read back in to measure their size

It never runs code it is given: every value is a number, a name from a fixed table or a path inside the job's own
folder. It imports nothing that talks to a network or starts a process (tests/test_game.py reads this file's syntax
tree to check that).

Protocol on stdout: FORM_STEP <text> per step, then FORM_RESULT <json> ({"ok": true, ...} or {"ok": false, "error"}).
Units: the scene works in millimetres (1 Blender unit = 1 mm) until export, which scales to the preset's units.
"""
import json
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np

RUNNER_VERSION = 1
CREASE = "crease_edge"
PATTERNS = ("none", "wood", "noise", "brushed")
FORMATS = ("fbx", "usd")


class JobError(Exception):
    pass


def say(tag, text):
    sys.stdout.write(f"{tag} {text}\n")
    sys.stdout.flush()


def inside(work, path):
    p = os.path.realpath(os.path.join(work, os.path.basename(str(path))))
    if os.path.dirname(p) != os.path.realpath(work):
        raise JobError("a path leaves the job folder")
    return p


def num(x, lo, hi):
    x = float(x)
    if not math.isfinite(x) or not lo <= x <= hi:
        raise JobError(f"number {x} out of range [{lo}, {hi}]")
    return x


# ---- scene helpers ---------------------------------------------------------------------------------------------

def clear_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 0.001          # 1 unit = 1 mm while modelling and baking


def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


def activate(ob, others=()):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in others:
        o.select_set(True)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def copy_object(ob, name):
    c = ob.copy()
    c.data = ob.data.copy()
    c.name = c.data.name = name
    c.modifiers.clear()
    return link(c)


def apply_modifiers(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    mats = list(ob.data.materials)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    if len(me.materials) != len(mats):
        me.materials.clear()
        for m in mats:
            me.materials.append(m)
    bpy.data.meshes.remove(old)
    return ob


def subdivide(ob, level):
    if level <= 0:
        return ob
    m = ob.modifiers.new("FormSubD", "SUBSURF")
    m.levels = m.render_levels = int(level)
    m.subdivision_type = "CATMULL_CLARK"
    m.use_limit_surface = True
    m.use_creases = True
    m.boundary_smooth = "ALL"
    m.uv_smooth = "PRESERVE_BOUNDARIES"           # the cage's UVs carry to every level, so all LODs share one layout
    return apply_modifiers(ob)


def triangulate(ob):
    m = ob.modifiers.new("FormTri", "TRIANGULATE")
    m.quad_method = "BEAUTY"
    m.ngon_method = "BEAUTY"
    return apply_modifiers(ob)


def decimate_to(src, name, budget):
    """A copy of src decimated (edge collapse, UVs kept) to at most budget triangles, as close under it as a few
    corrections of the ratio get. Returns (object, iterations)."""
    have = tris(src)
    if have <= budget:
        return copy_object(src, name), 0
    target = budget * 0.995
    ratio = target / have
    best = None
    for it in range(1, 7):
        ob = copy_object(src, name + "_try")
        m = ob.modifiers.new("FormDecimate", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = max(min(ratio, 1.0), 1e-5)
        m.use_collapse_triangulate = True
        apply_modifiers(ob)
        got = tris(ob)
        if got <= budget and (best is None or got > tris(best)):
            if best is not None:
                bpy.data.objects.remove(best)
            best = ob
        else:
            bpy.data.objects.remove(ob)
        if best is not None and tris(best) >= budget * 0.98:
            break
        ratio *= target / max(got, 1)
    if best is None:
        raise JobError(f"decimation could not reach {budget} triangles")
    best.name = best.data.name = name
    return best, it


def in_edit(ob, fn):
    activate(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        fn()
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


def smooth_shading(ob, angle_deg):
    me = ob.data
    try:
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(angle_deg))
    except AttributeError:                         # older Blender: polygon flags
        for p in me.polygons:
            p.use_smooth = True


# ---- building the base ------------------------------------------------------------------------------------------

def base_from_cage(z, mats):
    V = z["V"]
    sizes = z["F_len"].astype(int)
    flat = z["F_flat"].astype(int)
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    bm = bmesh.new()
    verts = [bm.verts.new((float(a), float(b), float(c))) for a, b, c in V]
    bm.verts.ensure_lookup_table()
    fmat = z["face_mat"].astype(int)
    for i, (s, n) in enumerate(zip(starts, sizes)):
        f = bm.faces.new([verts[k] for k in flat[s:s + n]])
        f.material_index = int(fmat[i]) if len(fmat) else 0
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    lay = bm.edges.layers.float.get(CREASE) or bm.edges.layers.float.new(CREASE)
    ce, cs = z["crease_e"].astype(int).reshape(-1, 2), z["crease_s"].astype(float)
    for (a, b), s in zip(ce, cs):
        e = bm.edges.get((verts[a], verts[b]))
        if e is not None:
            e[lay] = float(min(max(s, 0.0), 1.0))
    reg = z["face_region"].astype(int)
    if len(reg):                                   # seams: borders between regions, and fully sharp creases
        for e in bm.edges:
            fs = e.link_faces
            if len(fs) == 2 and reg[fs[0].index] != reg[fs[1].index]:
                e.seam = True
            elif e[lay] >= 0.999:
                e.seam = True
    me = bpy.data.meshes.new("FormBase")
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    return link(bpy.data.objects.new("FormBase", me))


def base_from_mesh(z, mats):
    V, T = z["V"], z["T"].astype(int)
    me = bpy.data.meshes.new("FormHigh")
    me.from_pydata([tuple(map(float, p)) for p in V], [], [tuple(map(int, t)) for t in T])
    fm = z["face_mat"].astype(int)
    if len(fm) == len(me.polygons):
        me.polygons.foreach_set("material_index", fm.tolist())
    for m in mats:
        me.materials.append(m)
    me.validate()
    me.update()
    return link(bpy.data.objects.new("FormHigh", me))


# ---- UVs ------------------------------------------------------------------------------------------------------------

def limit_positions(ob):
    """Each cage point moved to where the subdivision surface passes it (its limit position; the subsurf result keeps
    the cage's points first, in order). Unwrapping there measures the areas the surface really has, not the cage's."""
    n = len(ob.data.vertices)
    tmp = copy_object(ob, "FormLimit")
    subdivide(tmp, 1)
    co = np.empty(len(tmp.data.vertices) * 3)
    tmp.data.vertices.foreach_get("co", co)
    bpy.data.objects.remove(tmp)
    return co[:n * 3]


def unwrap(ob, method, margin, at_limit=False):
    saved = None
    if at_limit:
        saved = np.empty(len(ob.data.vertices) * 3)
        ob.data.vertices.foreach_get("co", saved)
        ob.data.vertices.foreach_set("co", limit_positions(ob))
        ob.data.update()

    def smart():
        bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=margin, area_weight=0.0,
                                 correct_aspect=True, scale_to_bounds=False)

    def regions():
        bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=margin)

    in_edit(ob, regions if method == "regions" else smart)

    def pack():
        bpy.ops.uv.average_islands_scale()        # one texel density across islands
        try:
            bpy.ops.uv.pack_islands(rotate=True, margin_method="FRACTION", margin=margin)
        except TypeError:
            bpy.ops.uv.pack_islands(rotate=True, margin=margin)
    in_edit(ob, pack)
    if saved is not None:
        ob.data.vertices.foreach_set("co", saved)
        ob.data.update()


# ---- materials ------------------------------------------------------------------------------------------------------

def principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def make_material(spec):
    mat = bpy.data.materials.new(spec["name"])
    mat.use_nodes = True
    nt = mat.node_tree
    bs = principled(mat)
    col = [num(c, 0, 1) for c in spec["color"]] + [1.0]
    rough, metal = num(spec["roughness"], 0, 1), num(spec["metallic"], 0, 1)
    bs.inputs["Base Color"].default_value = col
    bs.inputs["Roughness"].default_value = rough
    bs.inputs["Metallic"].default_value = metal
    pat = spec.get("pattern", "none")
    if pat not in PATTERNS:
        raise JobError(f"unknown pattern {pat!r}")
    if pat == "none":
        return mat
    scale = 1.0 / num(spec.get("pattern_mm", 20.0), 0.01, 1e5)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    dark = [c * 0.55 for c in col[:3]] + [1.0]
    light = [min(c * 1.15, 1.0) for c in col[:3]] + [1.0]
    ramp.color_ramp.elements[0].color = dark
    ramp.color_ramp.elements[1].color = light
    if pat == "wood":
        tex = nt.nodes.new("ShaderNodeTexWave")
        tex.wave_type = "RINGS"
        tex.inputs["Scale"].default_value = 1.2
        tex.inputs["Distortion"].default_value = 6.0
        tex.inputs["Detail"].default_value = 3.0
        mp.inputs["Scale"].default_value = (scale * 0.15, scale, scale)    # grain runs along X
        nt.links.new(mp.outputs["Vector"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
    else:
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = 4.0
        tex.inputs["Detail"].default_value = 6.0
        if pat == "brushed":
            mp.inputs["Scale"].default_value = (scale * 0.05, scale * 4, scale * 4)
            ramp.color_ramp.elements[0].color = [c * 0.85 for c in col[:3]] + [1.0]
        nt.links.new(mp.outputs["Vector"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bs.inputs["Base Color"])
    rr = nt.nodes.new("ShaderNodeMapRange")                                 # roughness varies a little with it
    rr.inputs["To Min"].default_value = max(rough - 0.12, 0.0)
    rr.inputs["To Max"].default_value = min(rough + 0.12, 1.0)
    nt.links.new(tex.outputs["Fac"], rr.inputs["Value"])
    nt.links.new(rr.outputs["Result"], bs.inputs["Roughness"])
    return mat


def final_material(name, imgs):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bs = principled(mat)

    def tex(img):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        return n
    if "base_color" in imgs:
        nt.links.new(tex(imgs["base_color"]).outputs["Color"], bs.inputs["Base Color"])
    if "orm" in imgs:
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(tex(imgs["orm"]).outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bs.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bs.inputs["Metallic"])
    if "normal" in imgs:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(tex(imgs["normal"]).outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bs.inputs["Normal"])
    return mat


# ---- baking ---------------------------------------------------------------------------------------------------------

def bake_all(high, low, job, work):
    b = job["bake"]
    px = int(job["texture_px"])
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "GPU" if b.get("device") == "GPU" else "CPU"
    sc.render.bake.margin = int(b["margin_px"])
    try:
        sc.render.bake.margin_type = "EXTEND"
    except (AttributeError, TypeError):
        pass
    diag = float(np.linalg.norm(np.array(low.dimensions)))
    extrusion, ray = diag * 0.01, diag * 0.03
    target = bpy.data.materials.new("FormBakeTarget")
    target.use_nodes = True
    node = target.node_tree.nodes.new("ShaderNodeTexImage")
    target.node_tree.nodes.active = node
    low.data.materials.clear()
    low.data.materials.append(target)
    for p in low.data.polygons:
        p.material_index = 0
    activate(low, others=[high])
    times, imgs, arrays = {}, {}, {}

    def bake(key, btype, color_space, samples, **kw):
        img = bpy.data.images.new(f"{job['asset']}_{key}", px, px, alpha=False)
        img.colorspace_settings.name = color_space
        node.image = img
        sc.cycles.samples = int(samples)
        t0 = time.perf_counter()
        bpy.ops.object.bake(type=btype, use_selected_to_active=True, cage_extrusion=extrusion,
                            max_ray_distance=ray, margin=int(b["margin_px"]), target="IMAGE_TEXTURES", **kw)
        times[key] = round(time.perf_counter() - t0, 3)
        a = np.empty(px * px * 4, dtype=np.float32)
        img.pixels.foreach_get(a)
        arrays[key] = a.reshape(px, px, 4)
        imgs[key] = img
        say("FORM_STEP", f"baked {key} in {times[key]} s")

    def through_emission(key, socket, color_space):
        """Bake a Principled input as it is shaded (linked pattern or plain value) by routing it to emission: the
        DIFFUSE colour pass would give black for metals (their diffuse is zero), and metallic has no bake type."""
        saved, added = [], []
        for m in high.data.materials:
            bs = principled(m)
            ec, es = bs.inputs["Emission Color"], bs.inputs["Emission Strength"]
            saved.append((ec, tuple(ec.default_value), es, es.default_value))
            src = bs.inputs[socket]
            if src.is_linked:
                added.append((m, m.node_tree.links.new(src.links[0].from_socket, ec)))
            else:
                v = src.default_value
                ec.default_value = tuple(v) if hasattr(v, "__len__") else (float(v), float(v), float(v), 1.0)
            es.default_value = 1.0
        try:
            bake(key, "EMIT", color_space, b["samples"])
        finally:
            for m, ln in added:
                m.node_tree.links.remove(ln)
            for ec, c, es, v in saved:
                ec.default_value = c
                es.default_value = v

    hidden = []                                    # the LODs lie on the surface: they must not shade it (AO)
    for o in bpy.context.scene.objects:
        if o is not high:
            hidden.append((o, o.visible_camera, o.visible_diffuse, o.visible_glossy, o.visible_transmission,
                           o.visible_volume_scatter, o.visible_shadow))
            o.visible_camera = o.visible_diffuse = o.visible_glossy = False
            o.visible_transmission = o.visible_volume_scatter = o.visible_shadow = False
    maps = set(b["maps"])
    if "base_color" in maps:
        through_emission("base_color", "Base Color", "sRGB")
    if "normal" in maps:
        bake("normal", "NORMAL", "Non-Color", b["samples"], normal_space="TANGENT")
    if "orm" in maps or "ao" in maps:
        bake("ao", "AO", "Non-Color", b["ao_samples"])
    if "orm" in maps:
        through_emission("roughness", "Roughness", "Non-Color")
        through_emission("metallic", "Metallic", "Non-Color")
        orm = np.ones((px, px, 4), dtype=np.float32)
        orm[..., 0] = arrays["ao"][..., 0]
        orm[..., 1] = arrays["roughness"][..., 0]
        orm[..., 2] = arrays["metallic"][..., 0]
        img = bpy.data.images.new(f"{job['asset']}_orm", px, px, alpha=False)
        img.colorspace_settings.name = "Non-Color"
        img.pixels.foreach_set(orm.reshape(-1))
        imgs["orm"] = img
    for o, *vis in hidden:
        (o.visible_camera, o.visible_diffuse, o.visible_glossy, o.visible_transmission, o.visible_volume_scatter,
         o.visible_shadow) = vis
    files = {}
    for key in ("base_color", "normal", "orm", "ao"):
        if key in imgs and key in maps:
            path = inside(work, f"{key}.png")
            imgs[key].filepath_raw = path
            imgs[key].file_format = "PNG"
            imgs[key].save()
            files[key] = os.path.basename(path)
    return {"seconds": times, "total_seconds": round(sum(times.values()), 3), "files": files,
            "px": px, "samples": b["samples"], "ao_samples": b["ao_samples"], "device": sc.cycles.device,
            "cage_extrusion": round(extrusion, 4), "max_ray_distance": round(ray, 4)}, imgs


# ---- reading LODs back -------------------------------------------------------------------------------------------

def lod_arrays(ob):
    me = ob.data
    me.calc_loop_triangles()
    nl = len(me.loops)
    vi = np.empty(nl, dtype=np.int64)
    me.loops.foreach_get("vertex_index", vi)
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    nrm = np.empty(nl * 3, dtype=np.float64)
    try:
        me.corner_normals.foreach_get("vector", nrm)
    except AttributeError:
        me.calc_normals_split()
        me.loops.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3)
    uv = np.zeros((nl, 2), dtype=np.float64)
    if me.uv_layers.active is not None:
        u = np.empty(nl * 2, dtype=np.float64)
        me.uv_layers.active.data.foreach_get("uv", u)
        uv = u.reshape(-1, 2)
    lt = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("loops", lt)
    key = np.concatenate([vi[:, None].astype(np.float64), np.round(nrm, 5), np.round(uv, 6)], axis=1)
    uk, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    corner = first
    return {"P": co[vi[corner]], "N": nrm[corner], "UV": uv[corner], "T": inv.reshape(-1)[lt].reshape(-1, 3)}


# ---- export ---------------------------------------------------------------------------------------------------------

def bbox_of(objs):
    pts = []
    for o in objs:
        if o.type == "MESH":
            M = np.array(o.matrix_world)
            co = np.empty(len(o.data.vertices) * 3)
            o.data.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)
            pts.append(co @ M[:3, :3].T + M[:3, 3])
    if not pts:
        return None
    P = np.concatenate(pts)
    return (P.max(0) - P.min(0)).tolist()


def export(spec, objs, work):
    fmt = spec["format"]
    if fmt not in FORMATS:
        raise JobError(f"unknown format {fmt!r}")
    path = inside(work, spec["file"])
    unit = spec["unit"]
    scale = num(spec["scale"], 1e-6, 1e3)            # units per mm
    sc = bpy.context.scene
    copies, originals = [], {}
    for o in objs:                                 # the originals step aside, so the copies keep the exact names
        want = spec["names"].get(o.name, o.name)
        originals[o] = o.name
        o.name = o.name + "__src"
        c = o.copy()
        c.data = o.data
        c.name = want
        c.scale = (scale, scale, scale)
        link(c)
        copies.append(c)
    exported = sorted(c.name for c in copies)
    sc.unit_settings.scale_length = 0.01 if unit == "cm" else 1.0
    for o in sc.objects:
        o.select_set(o in copies)
    bpy.context.view_layer.objects.active = copies[0]
    t0 = time.perf_counter()
    if fmt == "fbx":
        up = spec["up"]
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"MESH"}, apply_unit_scale=True,
                                 apply_scale_options="FBX_SCALE_UNITS", axis_up=up, axis_forward="-Z" if up == "Y" else "Y",
                                 mesh_smooth_type="OFF", use_tspace=True, path_mode="COPY", embed_textures=True,
                                 add_leaf_bones=False, bake_anim=False)
    else:
        bpy.ops.wm.usd_export(filepath=path, selected_objects_only=True, export_materials=True)
    secs = round(time.perf_counter() - t0, 3)
    for c in copies:
        bpy.data.objects.remove(c)
    for o, name in originals.items():
        o.name = name
    # read it back into the scene, in metres, and measure it
    sc.unit_settings.scale_length = 1.0
    before = set(bpy.data.objects)
    if fmt == "fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        bpy.ops.wm.usd_import(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    lod0 = [o for o in meshes if o.name.split(".")[0] == spec["lod0"]]
    size = bbox_of(lod0 or meshes)
    names = sorted(o.name for o in meshes)
    for o in new:
        bpy.data.objects.remove(o)
    sc.unit_settings.scale_length = 0.001
    return {"format": fmt, "file": os.path.basename(path), "bytes": os.path.getsize(path), "seconds": secs,
            "objects": exported,
            "reimport": {"objects": names, "lod0_size_m": size}}


# ---- main -------------------------------------------------------------------------------------------------------

def run(job):
    work = os.path.dirname(os.path.realpath(sys.argv[sys.argv.index("--") + 1]))
    clear_scene()
    timing = {}
    t = time.perf_counter()
    z = np.load(inside(work, job["input"]), allow_pickle=False)
    mats = [make_material(m) for m in job["materials"]]
    margin = num(job["uv"]["margin_px"], 0, 64) / int(job["texture_px"])
    lods, report = [], []
    if job["source"] == "cage":
        say("FORM_STEP", "cage")
        base = base_from_cage(z, mats)
        say("FORM_STEP", f"UVs ({job['uv']['method']})")
        unwrap(base, job["uv"]["method"], margin, at_limit=True)
        timing["uv"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        high = subdivide(copy_object(base, "FormHigh"), int(job["high_level"]))
        timing["high"] = round(time.perf_counter() - t, 3)
        for spec in job["lods"]:
            t = time.perf_counter()
            name = spec["name"]
            ob = subdivide(copy_object(base, name + "_src"), int(spec["level"]))
            it = 0
            if spec["decimate"]:
                triangulate(ob)
                dec, it = decimate_to(ob, name, int(spec["budget"]))
                bpy.data.objects.remove(ob)
                ob = dec
            else:
                ob.name = ob.data.name = name
            smooth_shading(ob, job["smooth_angle_deg"])
            lods.append(ob)
            report.append({"lod": spec["lod"], "triangles": tris(ob), "budget": spec["budget"], "level": spec["level"],
                           "decimated": bool(spec["decimate"]), "iterations": it, "source": spec["source"],
                           "seconds": round(time.perf_counter() - t, 3)})
        bpy.data.objects.remove(base)
    else:
        say("FORM_STEP", "mesh")
        high = base_from_mesh(z, mats)
        smooth_shading(high, job["smooth_angle_deg"])
        src = high
        retopo = job.get("retopo", "decimate")
        note = ""
        if retopo == "quadriflow":
            q = copy_object(high, "FormQuad")
            activate(q)
            try:
                r = bpy.ops.object.quadriflow_remesh(target_faces=max(int(job["lods"][0]["budget"] // 2), 6), seed=0,
                                                     use_mesh_symmetry=False, use_preserve_sharp=True,
                                                     use_preserve_boundary=True, smooth_normals=False, mode="FACES")
                ok = "FINISHED" in r and len(q.data.polygons) > 0
            except RuntimeError:
                ok = False
            if ok:
                src = q
            else:
                bpy.data.objects.remove(q)
                note = "QuadriFlow failed on this mesh; decimated instead"
        prev = src
        for k, spec in enumerate(job["lods"]):
            t = time.perf_counter()
            if k == 0:
                tri = copy_object(prev, "FormTri")
                triangulate(tri)
                ob, it = decimate_to(tri, spec["name"], int(spec["budget"]))
                bpy.data.objects.remove(tri)
                say("FORM_STEP", "UVs (smart)")
                unwrap(ob, "smart", margin)
            else:
                ob, it = decimate_to(prev, spec["name"], int(spec["budget"]))
            smooth_shading(ob, job["smooth_angle_deg"])
            lods.append(ob)
            if src is not high:
                how = "QuadriFlow remesh" + (", then decimated to the budget" if it or k else "") + \
                      " (automatic retopology)"
            elif it:
                how = "decimated to the budget (automatic retopology)"
            else:
                how = "the mesh as it is (under budget)"
            report.append({"lod": spec["lod"], "triangles": tris(ob), "budget": spec["budget"], "level": None,
                           "decimated": bool(it), "iterations": it, "source": how + (f"; {note}" if note else ""),
                           "seconds": round(time.perf_counter() - t, 3)})
            prev = ob
        timing["lods"] = round(sum(r["seconds"] for r in report), 3)
    say("FORM_STEP", "bake")
    t = time.perf_counter()
    lod0_mats = list(lods[0].data.materials)
    bake = None
    imgs = {}
    if job["bake"]["maps"]:
        bake, imgs = bake_all(high, lods[0], job, work)
    timing["bake"] = round(time.perf_counter() - t, 3)
    final = final_material("M_" + job["asset"], imgs) if imgs else None
    for ob in lods:
        ob.data.materials.clear()
        if final is not None:
            ob.data.materials.append(final)
        elif lod0_mats:
            ob.data.materials.append(lod0_mats[0])
        for p in ob.data.polygons:
            p.material_index = 0
    for ob, r in zip(lods, report):
        a = lod_arrays(ob)
        np.savez(inside(work, f"lod{r['lod']}.npz"), **a)
        r["corners"] = int(len(a["P"]))
    cols = []
    if job.get("collision"):
        c = np.load(inside(work, job["collision"]), allow_pickle=False)
        for i in range(int(c["n"])):
            me = bpy.data.meshes.new(job["collision_names"][i])
            me.from_pydata([tuple(map(float, p)) for p in c[f"V{i}"]], [], [tuple(map(int, f)) for f in c[f"T{i}"]])
            me.update()
            cols.append(link(bpy.data.objects.new(job["collision_names"][i], me)))
    exports = []
    high.hide_render = True
    for spec in job.get("exports", []):
        say("FORM_STEP", f"export {spec['format']}")
        exports.append(export(spec, lods + cols, work))
    return {"ok": True, "runner": RUNNER_VERSION, "blender": bpy.app.version_string, "lods": report,
            "high_triangles": tris(high), "bake": bake, "timing": timing, "exports": exports,
            "collision_objects": [o.name for o in cols]}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    try:
        job = json.loads(open(argv[0], encoding="utf-8").read())
        if job.get("runner") != RUNNER_VERSION:
            raise JobError("runner version mismatch")
        out = run(job)
        with open(inside(os.path.dirname(os.path.realpath(argv[0])), "result.json"), "w", encoding="utf-8") as f:
            json.dump(out, f)
        say("FORM_RESULT", json.dumps({"ok": True}))
    except Exception as e:                         # the caller keeps the project as it was
        say("FORM_RESULT", json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        sys.exit(3)


if __name__ == "__main__":
    main()
