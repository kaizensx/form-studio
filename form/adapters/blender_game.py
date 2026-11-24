"""Form Studio's fixed game-asset runner. It runs inside Blender's own Python (blender -b ... --python blender_game.py).

It reads one job file (JSON, written by form/game/pipeline.py after the job was schema-checked there) and the
arrays next to it (input.npz, collision.npz: numpy files read with allow_pickle=False), then makes a game asset:

    1. the base mesh: a subdivision cage (points, polygons, creases, named regions, a material per face) or a mesh
       (a CAD tessellation, a material per face)
    2. UVs: angle-based unwrap with seams on region borders and sharp creases, or Smart UV Project; then packed
    3. the high-poly: the cage at subdivision level N, or the cage's high-only mesh (detail only the bake source
       has) subdivided, or the mesh as it is
    4. LOD0..LOD3: cage levels, or Decimate (edge collapse) / QuadriFlow to the triangle budgets; every UV island
       brought to one texel density measured on the subdivided surface
    5. a Principled BSDF per material from the library (form/game/materials.py): wood, bare/brushed/painted metal,
       leather, plastic, rubber, stone, fabric, emissive, each a height pattern bumped into the normal; edge wear,
       cavity dirt and roughness breakup driven by masks read from the high poly (curvature, AO, thickness)
    6. Cycles bakes from the high-poly onto LOD0 through a cage per part (extrusion from the sampled low-to-high
       distance): base colour, tangent-space normal, roughness, metallic, AO, the masks, emission;
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
import threading
import time

import bmesh
import bpy
import numpy as np

RUNNER_VERSION = 4
CREASE = "crease_edge"
BOARD = "form_board"          # a face attribute: one value 0..1 per board (wood plank, stone block), see boards()
KINDS = ("wood", "bare_metal", "brushed_metal", "painted_metal", "leather", "plastic", "rubber", "stone", "fabric",
         "emissive")
EXTRA_MAPS = ("emissive", "curvature", "thickness")      # written whenever they are baked (with the base colour)
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


def uv_seam_vertices(ob):
    """Vertices on a UV seam (their corners carry more than one UV)."""
    me = ob.data
    if me.uv_layers.active is None:
        return []
    nl = len(me.loops)
    vi = np.empty(nl, dtype=np.int64)
    me.loops.foreach_get("vertex_index", vi)
    uv = np.empty(nl * 2)
    me.uv_layers.active.data.foreach_get("uv", uv)
    key = np.unique(np.c_[vi, np.round(uv.reshape(-1, 2) * 1e6)], axis=0)
    v, n = np.unique(key[:, 0].astype(np.int64), return_counts=True)
    return v[n > 1].tolist()


def decimate_to(src, name, budget, keep_seams=False):
    """A copy of src decimated (edge collapse, UVs kept) to at most budget triangles, as close under it as a few
    corrections of the ratio get. keep_seams: UV seam vertices collapse last (a collapse across a seam moves an
    island's border in 3D but not in UV, and a small island then has another texel density than the rest).
    Returns (object, iterations)."""
    have = tris(src)
    if have <= budget:
        return copy_object(src, name), 0
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__))); import blender_lod  # noqa: E401,E702 WP8 hook
    return blender_lod.decimate_to(src, name, budget, globals())  # WP8 hook: silhouette-preserving LODs (blender_lod.py)
    target = budget * 0.995
    ratio = target / have
    best = None
    seams = uv_seam_vertices(src) if keep_seams else []
    for it in range(1, 7):
        ob = copy_object(src, name + "_try")
        m = ob.modifiers.new("FormDecimate", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = max(min(ratio, 1.0), 1e-5)
        m.use_collapse_triangulate = True
        if seams:
            g = ob.vertex_groups.new(name="FormSeams")
            g.add(seams, 1.0, "REPLACE")
            m.vertex_group = g.name
            m.invert_vertex_group = True           # weight 1 collapses first, so the seams are inverted
            m.vertex_group_factor = 1.0
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
    bm.normal_update()
    boards(bm, lay, reg)
    me = bpy.data.meshes.new("FormBase")
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    return link(bpy.data.objects.new("FormBase", me))


def boards(bm, crease_layer, reg, max_faces=400_000, turn_deg=35.0):
    """A face attribute (BOARD) that tells one board from the next: faces joined by edges that are smooth (no full
    crease, no region border, a turn under turn_deg) share a board, and every board takes its own value 0..1 (the
    golden-ratio sequence, so neighbours differ). Planks split by creased grooves, or box sides that meet at creased
    corners, get one value per plank face; the wood and stone materials offset their grain and vary their tint by
    it. The subdivision carries face attributes to the faces it makes."""
    n = len(bm.faces)
    if n == 0 or n > max_faces:
        return 0
    cos_t = math.cos(math.radians(turn_deg))
    lab = [-1] * n
    k = 0
    for f0 in bm.faces:
        if lab[f0.index] >= 0:
            continue
        lab[f0.index] = k
        stack = [f0]
        while stack:
            f = stack.pop()
            for e in f.edges:
                if e[crease_layer] >= 0.999 or (e.seam and len(reg)):
                    continue
                for g in e.link_faces:
                    if lab[g.index] < 0 and f.normal.dot(g.normal) >= cos_t:
                        lab[g.index] = k
                        stack.append(g)
        k += 1
    lay = bm.faces.layers.float.get(BOARD) or bm.faces.layers.float.new(BOARD)
    for f in bm.faces:
        f[lay] = (lab[f.index] * 0.6180339887 + 0.137) % 1.0
    return k


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


def uv_island_stats(ob):
    """Per UV island of a mesh: (island per polygon, texel density sqrt(UV area / surface area), UV centroid,
    surface area). Polygons are in one island when they share an edge whose two corners have the same UVs."""
    me = ob.data
    nl, npoly = len(me.loops), len(me.polygons)
    vi = np.empty(nl, dtype=np.int64)
    me.loops.foreach_get("vertex_index", vi)
    uv = np.empty(nl * 2)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    ls = np.empty(npoly, dtype=np.int64)
    lt = np.empty(npoly, dtype=np.int64)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    poly_of = np.repeat(np.arange(npoly), lt)
    nxt = np.arange(nl) + 1
    last = ls + lt - 1
    nxt[last] = ls
    _, wid = np.unique(np.c_[vi, np.round(uv * 1e6)], axis=0, return_inverse=True)
    wid = wid.reshape(-1)
    E = np.sort(np.c_[wid, wid[nxt]], axis=1)
    o = np.lexsort((E[:, 1], E[:, 0]))
    same = np.all(E[o][1:] == E[o][:-1], axis=1)
    parent = np.arange(npoly)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in zip(poly_of[o][:-1][same].tolist(), poly_of[o][1:][same].tolist()):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    lab = np.unique([find(i) for i in range(npoly)], return_inverse=True)[1].reshape(-1)
    n = int(lab.max()) + 1 if npoly else 0
    me.calc_loop_triangles()
    tl = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("loops", tl)
    tl = tl.reshape(-1, 3)
    co = coords(ob)
    P, U = co[vi[tl]], uv[tl]
    a3 = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
    e1, e2 = U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]
    a2 = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    tlab = lab[poly_of[tl[:, 0]]]
    S3, S2 = np.bincount(tlab, a3, n), np.bincount(tlab, a2, n)
    cu = np.stack([np.bincount(tlab, a2 * U[:, :, k].mean(1), n) for k in (0, 1)], 1) / np.maximum(S2, 1e-30)[:, None]
    dens = np.sqrt(S2 / np.maximum(S3, 1e-30))
    return lab, dens, cu, S3


def even_texel(base, margin, level=2, rounds=3):
    """Every UV island at the median island's texel density, measured on the surface the LODs really have (the
    cage subdivided `level` times, so a coarse cage's flat faces do not undercount a curved part's area), then the
    islands repacked. Average Islands Scale alone works on the cage's own faces, which put the wheel hub and tyre
    at half the density of the flat parts. Returns {"rounds", "worst_before", "worst_after"}."""
    out = {"rounds": 0}
    for r in range(rounds + 1):
        tmp = subdivide(copy_object(base, "FormTexel"), level)
        _, dt, ct, at = uv_island_stats(tmp)
        bpy.data.objects.remove(tmp)
        keep = at > 0
        if not keep.any():
            return out
        med = float(np.median(dt[keep]))
        worst = float(np.max(np.abs(dt[keep] / med - 1)))
        out["worst_before" if r == 0 else "worst_after"] = round(worst, 4)
        if worst <= 0.05 or r == rounds:
            break
        lab, _db, cb, _ab = uv_island_stats(base)
        match = np.argmin(np.linalg.norm(cb[:, None, :] - ct[None, :, :], axis=2), axis=1)
        f = np.clip(med / np.maximum(dt[match], 1e-12), 0.25, 4.0)
        me = base.data
        nl = len(me.loops)
        uv = np.empty(nl * 2)
        me.uv_layers.active.data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        lt = np.empty(len(me.polygons), dtype=np.int64)
        me.polygons.foreach_get("loop_total", lt)
        li = np.repeat(lab, lt)
        uv = cb[li] + (uv - cb[li]) * f[li][:, None]
        me.uv_layers.active.data.foreach_set("uv", uv.reshape(-1))

        def pack():
            try:
                bpy.ops.uv.pack_islands(rotate=True, margin_method="FRACTION", margin=margin)
            except TypeError:
                bpy.ops.uv.pack_islands(rotate=True, margin=margin)
        in_edit(base, pack)
        out["rounds"] = r + 1
    out.setdefault("worst_after", out.get("worst_before"))
    return out


# ---- materials ------------------------------------------------------------------------------------------------------

def principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


# The material library (form/game/materials.py) as Cycles node graphs, built here from a fixed table of kinds. Every
# material has a height pattern (bumped into the shading normal, so the NORMAL bake carries it) and masks read from
# the high poly while it is baked: edge (a Bevel normal against the shading normal: curvature), cavity (ambient
# occlusion over a short distance) and thickness (ambient occlusion inside the surface). Edge wear, cavity dirt and
# roughness breakup are driven from them, and the masks are baked as maps too (curvature, thickness).

CONTRAST = {"wood": 0.55, "stone": 0.4, "leather": 0.3, "fabric": 0.3, "rubber": 0.15, "bare_metal": 0.15,
            "brushed_metal": 0.12, "painted_metal": 0.12, "plastic": 0.08, "emissive": 0.0}
BOARD_TINT = {"wood": 0.22, "stone": 0.08}          # tint spread between boards (planks, blocks), +- share

# Edge wear: the raw score (a wide convex-edge mask x breakup noise, 0..1.25) wears through above a threshold that
# falls as the material's wear rises. Calibrated on the six game bench assets (scripts/game_bench.py) by baking the
# raw score and measuring the worn share at each threshold: raw over 0.63 - 0.35 x wear (the ramp's middle) leaves
# about 2-9 % of their surface worn at wear 0.3-0.75, measured on the baked mask (wear_measure()). The first runner's
# threshold, 1 - 0.75 x wear, left about 1 % worn on the same assets.
WEAR_RAMP = 0.12
WEAR_REACH = 3.0              # the wear's rounding radius, in edge-mask radii


def wear_threshold(wear):
    return 0.57 - 0.35 * wear


def node(nt, kind, **props):
    n = nt.nodes.new(kind)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def sock(n, ident):
    return next(s for s in list(n.inputs) + list(n.outputs) if s.identifier == ident)


def feed(nt, dst, src):
    """Connect src (a socket) into dst, or set a constant."""
    if hasattr(src, "is_output"):
        nt.links.new(src, dst)
    else:
        dst.default_value = src


def mth(nt, op, a, b=0.0, clamp=False):
    n = node(nt, "ShaderNodeMath", operation=op, use_clamp=clamp)
    feed(nt, n.inputs[0], a)
    feed(nt, n.inputs[1], b)
    return n.outputs[0]


def mix_col(nt, fac, a, b):
    n = node(nt, "ShaderNodeMix", data_type="RGBA", clamp_factor=True)
    feed(nt, sock(n, "Factor_Float"), fac)
    feed(nt, sock(n, "A_Color"), a)
    feed(nt, sock(n, "B_Color"), b)
    return sock(n, "Result_Color")


def mix_val(nt, fac, a, b):
    n = node(nt, "ShaderNodeMix", data_type="FLOAT", clamp_factor=True)
    feed(nt, sock(n, "Factor_Float"), fac)
    feed(nt, sock(n, "A_Float"), a)
    feed(nt, sock(n, "B_Float"), b)
    return sock(n, "Result_Float")


def ramp(nt, x, lo, hi):
    """A smooth 0..1 step of x from lo to hi, clamped."""
    n = node(nt, "ShaderNodeMapRange", interpolation_type="SMOOTHSTEP", clamp=True)
    feed(nt, n.inputs["Value"], x)
    n.inputs["From Min"].default_value = lo
    n.inputs["From Max"].default_value = hi
    return n.outputs["Result"]


def scaled(nt, v, sx, sy, sz):
    n = node(nt, "ShaderNodeMapping")
    feed(nt, n.inputs["Vector"], v)
    n.inputs["Scale"].default_value = (sx, sy, sz)
    return n.outputs["Vector"]


def noise(nt, v, scale, detail=6.0, rough=0.55):
    n = node(nt, "ShaderNodeTexNoise")
    feed(nt, n.inputs["Vector"], v)
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    return n.outputs["Fac"]


def vadd(nt, a, b):
    n = node(nt, "ShaderNodeVectorMath", operation="ADD")
    feed(nt, n.inputs[0], a)
    feed(nt, n.inputs[1], b)
    return n.outputs["Vector"]


def vscale(nt, a, s):
    n = node(nt, "ShaderNodeVectorMath", operation="SCALE")
    feed(nt, n.inputs[0], a)
    feed(nt, sock(n, "Scale"), s)
    return n.outputs["Vector"]


def wood(nt, vec, board):
    """Wood: (height, albedo variation, end grain 0..1). The growth rings are cylinders around the grain axis (X),
    so long faces show flat-sawn streaks and end faces (normal along X) show ring arcs; the rings are warped by a
    noise field so they wander and pinch, and every board (BOARD) shifts the log centre and the warp, so no two
    planks show the same figure. Ring pitch is about grain_mm / 4.6."""
    off = node(nt, "ShaderNodeCombineXYZ")              # a per-board shift: a different cut of the log
    feed(nt, off.inputs["X"], mth(nt, "MULTIPLY", board, 173.0))
    feed(nt, off.inputs["Y"], mth(nt, "MULTIPLY", board, 7.31))
    feed(nt, off.inputs["Z"], mth(nt, "MULTIPLY", board, -5.17))
    p = vadd(nt, vec, off.outputs["Vector"])
    wn = node(nt, "ShaderNodeTexNoise")                 # the warp: slow along the grain, faster across it
    feed(nt, wn.inputs["Vector"], scaled(nt, p, 0.08, 0.55, 0.55))
    wn.inputs["Scale"].default_value = 1.0
    wn.inputs["Detail"].default_value = 3.0
    wn.inputs["Roughness"].default_value = 0.5
    warp = vscale(nt, vadd(nt, wn.outputs["Color"], (-0.5, -0.5, -0.5)), 0.9)
    q = scaled(nt, vadd(nt, p, warp), 0.0, 1.0, 1.0)    # x dropped: cylindrical rings around X
    w = node(nt, "ShaderNodeTexWave", wave_type="RINGS")
    feed(nt, w.inputs["Vector"], q)
    w.inputs["Scale"].default_value = 1.45
    w.inputs["Distortion"].default_value = 2.5
    w.inputs["Detail"].default_value = 2.0
    w.inputs["Detail Scale"].default_value = 1.5
    ring = ramp(nt, sock(w, "Fac"), 0.15, 0.95)        # late wood: thin dark bands, not a sine
    fine = noise(nt, scaled(nt, p, 0.25, 14.0, 14.0), 1.0, 4.0)     # pores along the grain
    h = mth(nt, "ADD", mth(nt, "MULTIPLY", ring, 0.7), mth(nt, "MULTIPLY", fine, 0.3))
    var = mth(nt, "ADD", mth(nt, "MULTIPLY", ring, 0.8), mth(nt, "MULTIPLY", fine, 0.2))
    tc = node(nt, "ShaderNodeTexCoord")
    sep = node(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Normal"], sep.inputs["Vector"])
    end = ramp(nt, mth(nt, "ABSOLUTE", sep.outputs["X"]), 0.6, 0.85)
    return h, var, end


def pattern(nt, kind, vec, board=0.0):
    """(height 0..1, albedo variation 0..1) for a kind, from object coordinates in units of its grain."""
    if kind == "wood":
        h, var, _end = wood(nt, vec, board)
        return h, var
    if kind == "brushed_metal":
        n = noise(nt, scaled(nt, vec, 0.03, 6.0, 6.0), 4.0, 8.0, 0.6)             # fine lines along X
        return n, n
    if kind == "leather":
        v = node(nt, "ShaderNodeTexVoronoi", feature="F1")
        feed(nt, v.inputs["Vector"], vec)
        v.inputs["Scale"].default_value = 1.0
        dome = mth(nt, "SUBTRACT", 1.0, mth(nt, "MULTIPLY", v.outputs["Distance"], 1.4), clamp=True)
        n = noise(nt, vec, 0.4, 4.0)
        return mth(nt, "ADD", mth(nt, "MULTIPLY", dome, 0.8), mth(nt, "MULTIPLY", n, 0.2)), n
    if kind == "stone":
        v = node(nt, "ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE")
        feed(nt, v.inputs["Vector"], vec)
        v.inputs["Scale"].default_value = 1.0
        crack = ramp(nt, v.outputs["Distance"], 0.0, 0.08)
        n = noise(nt, vec, 3.0, 8.0, 0.6)
        return mth(nt, "MULTIPLY", crack, mth(nt, "ADD", mth(nt, "MULTIPLY", n, 0.5), 0.5)), n
    if kind == "fabric":
        a = node(nt, "ShaderNodeTexWave", wave_type="BANDS", bands_direction="X")
        b = node(nt, "ShaderNodeTexWave", wave_type="BANDS", bands_direction="Y")
        for w in (a, b):
            feed(nt, w.inputs["Vector"], vec)
            w.inputs["Scale"].default_value = 1.0
        return mth(nt, "MULTIPLY", sock(a, "Fac"), sock(b, "Fac")), noise(nt, vec, 0.3, 3.0)
    if kind == "painted_metal":
        return noise(nt, vec, 2.0, 4.0, 0.5), noise(nt, vec, 0.25, 3.0)          # orange peel
    if kind in ("bare_metal", "rubber"):
        n = noise(nt, vec, 3.0 if kind == "bare_metal" else 2.0, 10.0, 0.65)
        return n, n
    return noise(nt, vec, 2.0, 5.0, 0.5), noise(nt, vec, 0.2, 3.0)               # plastic, emissive


def make_material(spec, masks):
    kind = spec["kind"]
    if kind not in KINDS:
        raise JobError(f"unknown material kind {kind!r}")
    mat = bpy.data.materials.new(spec["name"])
    mat.use_nodes = True
    nt = mat.node_tree
    bs = principled(mat)
    col = [num(c, 0, 1) for c in spec["color"]] + [1.0]
    edge_col = [num(c, 0, 1) for c in spec["edge_color"]] + [1.0]
    dirt_col = [num(c, 0, 1) for c in spec["dirt_color"]] + [1.0]
    rough, metal = num(spec["roughness"], 0, 1), num(spec["metallic"], 0, 1)
    wear = num(spec["wear"], 0, 1)
    grain = num(spec["grain_mm"], 0.05, 1e5)
    height = num(spec["height_mm"], 0, 100)
    emis = num(spec["emission"], 0, 50)
    e_mm, c_mm, t_mm = (num(masks[k], 1e-4, 1e5) for k in ("edge_mm", "cavity_mm", "thick_mm"))
    tc = node(nt, "ShaderNodeTexCoord")
    vec = scaled(nt, tc.outputs["Object"], 1.0 / grain, 1.0 / grain, 1.0 / grain)
    board = node(nt, "ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name=BOARD).outputs["Fac"]
    end = None
    if kind == "wood":
        h, var, end = wood(nt, vec, board)
    else:
        h, var = pattern(nt, kind, vec)
    # masks, read from the high poly as it is shaded
    geo = node(nt, "ShaderNodeNewGeometry")
    bev = node(nt, "ShaderNodeBevel", samples=8)
    bev.inputs["Radius"].default_value = e_mm
    dot = node(nt, "ShaderNodeVectorMath", operation="DOT_PRODUCT")
    nt.links.new(bev.outputs["Normal"], dot.inputs[0])
    nt.links.new(geo.outputs["Normal"], dot.inputs[1])
    tilt = mth(nt, "SQRT", mth(nt, "MULTIPLY", mth(nt, "SUBTRACT", 1.0, sock(dot, "Value")), 2.0, clamp=False))
    edge = ramp(nt, tilt, 0.04, 0.35)              # the angle (radians) the rounded-edge normal turns away
    ao = node(nt, "ShaderNodeAmbientOcclusion", samples=8, only_local=True)
    ao.inputs["Distance"].default_value = c_mm
    cavity = ramp(nt, mth(nt, "SUBTRACT", 1.0, ao.outputs["AO"]), 0.08, 0.6)
    th = node(nt, "ShaderNodeAmbientOcclusion", samples=8, inside=True, only_local=True)
    th.inputs["Distance"].default_value = t_mm
    thick = th.outputs["AO"]
    convex = mth(nt, "MULTIPLY", edge, mth(nt, "SUBTRACT", 1.0, cavity, clamp=True))   # a creased valley is no edge
    breakup = noise(nt, scaled(nt, tc.outputs["Object"], *(1.0 / (e_mm * 12.0),) * 3), 1.0, 8.0, 0.65)
    # wear reads a wider rounding than the edge mask (a worn band is wider than the highlight), only on convex
    # ground: raw = convex_wide x (breakup + a base); nothing wears off the edges. The rounding shrinks where the
    # part is thin (thickness AO low): a blade thinner than the radius would read as all edge.
    bw = node(nt, "ShaderNodeBevel", samples=8)
    feed(nt, bw.inputs["Radius"], mth(nt, "MULTIPLY", mth(nt, "ADD", mth(nt, "MULTIPLY", thick, WEAR_REACH - 0.6),
                                                          0.6), e_mm))
    dw = node(nt, "ShaderNodeVectorMath", operation="DOT_PRODUCT")
    nt.links.new(bw.outputs["Normal"], dw.inputs[0])
    nt.links.new(geo.outputs["Normal"], dw.inputs[1])
    tw = mth(nt, "SQRT", mth(nt, "MULTIPLY", mth(nt, "SUBTRACT", 1.0, sock(dw, "Value")), 2.0, clamp=False))
    convex_w = mth(nt, "MULTIPLY", ramp(nt, tw, 0.03, 0.3), mth(nt, "SUBTRACT", 1.0, cavity, clamp=True))
    raw = mth(nt, "MULTIPLY", convex_w, mth(nt, "ADD", mth(nt, "MULTIPLY", breakup, 1.1), 0.15))
    lo_w = wear_threshold(wear)
    worn = ramp(nt, raw, lo_w, lo_w + WEAR_RAMP) if wear > 0 else 0.0
    dirt = mth(nt, "MULTIPLY", mth(nt, "MULTIPLY", cavity, mth(nt, "ADD", mth(nt, "MULTIPLY", breakup, 0.8), 0.4)),
               0.25 + 0.6 * wear, clamp=True)
    mk = node(nt, "ShaderNodeCombineColor")
    mk.name = "FormMasks"                          # R convex edge, G worn (what the bake measures), B thickness
    feed(nt, mk.inputs["Red"], convex)
    feed(nt, mk.inputs["Green"], worn)
    feed(nt, mk.inputs["Blue"], thick)
    # albedo: the tint varied by the pattern and per board, dirt in cavities, the edge colour where worn
    c = CONTRAST[kind]
    dark = [x * (1 - c) for x in col[:3]] + [1.0]
    light = [min(x * (1 + c * 0.6), 1.0) for x in col[:3]] + [1.0]
    albedo = mix_col(nt, var, dark, light)
    bv = BOARD_TINT.get(kind, 0.0)
    if bv > 0:                                     # each board a little lighter or darker, warmer or cooler
        lo = [x * (1 - bv) for x in (1.04, 1.0, 0.92)] + [1.0]
        hi = [x * (1 + bv) for x in (0.97, 1.0, 1.05)] + [1.0]
        f = mix_col(nt, board, lo, hi)
        mul = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_result=True)
        sock(mul, "Factor_Float").default_value = 1.0
        nt.links.new(albedo, sock(mul, "A_Color"))
        nt.links.new(f, sock(mul, "B_Color"))
        albedo = sock(mul, "Result_Color")
    if end is not None:                            # end grain drinks finish: darker and rougher
        albedo = mix_col(nt, mth(nt, "MULTIPLY", end, 0.45), albedo, [x * 0.45 for x in col[:3]] + [1.0])
        rough = mth(nt, "ADD", rough, mth(nt, "MULTIPLY", end, 0.12))
    albedo = mix_col(nt, dirt, albedo, dirt_col)
    albedo = mix_col(nt, worn, albedo, edge_col)
    nt.links.new(albedo, bs.inputs["Base Color"])
    r = mth(nt, "ADD", rough, mth(nt, "MULTIPLY", mth(nt, "SUBTRACT", breakup, 0.5), 0.22))
    r = mth(nt, "ADD", r, mth(nt, "MULTIPLY", mth(nt, "SUBTRACT", var, 0.5), 0.1))
    r = mth(nt, "ADD", r, mth(nt, "MULTIPLY", dirt, 0.2), clamp=True)
    nt.links.new(mix_val(nt, worn, r, num(spec["edge_roughness"], 0, 1)), bs.inputs["Roughness"])
    m = mth(nt, "MULTIPLY", metal, mth(nt, "SUBTRACT", 1.0, mth(nt, "MULTIPLY", dirt, 0.6)))
    nt.links.new(mix_val(nt, worn, m, num(spec["edge_metallic"], 0, 1)), bs.inputs["Metallic"])
    # height: the pattern, minus a chip where paint wears through
    hh = h if kind != "painted_metal" else mth(nt, "SUBTRACT", h, mth(nt, "MULTIPLY", worn, 1.5))
    bump = node(nt, "ShaderNodeBump")
    bump.inputs["Distance"].default_value = height
    bump.inputs["Strength"].default_value = 1.0
    feed(nt, bump.inputs["Height"], hh)
    nt.links.new(bev.outputs["Normal"], bump.inputs["Normal"])    # edges baked round, as a bevel would shade them
    nt.links.new(bump.outputs["Normal"], bs.inputs["Normal"])
    em = node(nt, "ShaderNodeRGB")
    em.name = "FormEmission"
    em.outputs[0].default_value = col if emis > 0 else (0.0, 0.0, 0.0, 1.0)
    nt.links.new(em.outputs[0], bs.inputs["Emission Color"])
    bs.inputs["Emission Strength"].default_value = emis
    mat["form_emissive"] = bool(emis > 0)
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
    if "emissive" in imgs:
        nt.links.new(tex(imgs["emissive"]).outputs["Color"], bs.inputs["Emission Color"])
        bs.inputs["Emission Strength"].default_value = 1.0
    return mat


# ---- baking ---------------------------------------------------------------------------------------------------------

def islands(ob):
    """Connected parts of a mesh (by shared vertices): (label per vertex, number of parts)."""
    n = len(ob.data.vertices)
    e = np.empty(len(ob.data.edges) * 2, dtype=np.int64)
    ob.data.edges.foreach_get("vertices", e)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in e.reshape(-1, 2).tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(i) for i in range(n)], dtype=np.int64)
    _, lab = np.unique(roots, return_inverse=True)
    return lab.reshape(-1), int(lab.max()) + 1 if n else 0


def coords(ob):
    co = np.empty(len(ob.data.vertices) * 3)
    ob.data.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def explode(high, low, spacing):
    """Move each part of the low poly, and the high-poly part it was made from, apart by `spacing` (the exploded
    bake): a bake ray from one part can then never land on another part. Parts that touch or nest (a lid resting on
    a box, a band round a body) otherwise trade surfaces, and a face takes a neighbour's colour or an inverted normal
    (the tangent normal points into the surface). Parts are matched by bounding box (centre and size). Returns
    (restore function, number of parts moved)."""
    lo_lab, nl = islands(low)
    hi_lab, nh = islands(high)
    if nl < 2:
        return (lambda: None), 0, lo_lab
    lo_co, hi_co = coords(low), coords(high)

    def boxes(co, lab, n):
        lo = np.full((n, 3), np.inf)
        hi = np.full((n, 3), -np.inf)
        np.minimum.at(lo, lab, co)
        np.maximum.at(hi, lab, co)
        return np.concatenate([(lo + hi) / 2, hi - lo], axis=1)
    bl, bh = boxes(lo_co, lo_lab, nl), boxes(hi_co, hi_lab, nh)
    cost = np.linalg.norm(bl[:, None, :] - bh[None, :, :], axis=2)
    pairs, used_l, used_h = [], set(), set()
    for k in np.argsort(cost, axis=None):
        i, j = divmod(int(k), nh)
        if i in used_l or j in used_h:
            continue
        used_l.add(i)
        used_h.add(j)
        pairs.append((i, j))
    # high-poly parts left over (detail that exists only on the high poly: a bolt, a strap) go with the low part whose
    # box is nearest their centre (the smaller box on a tie: a bolt on a band, not the body under it)
    owner = {j: i for i, j in pairs}
    for j in range(nh):
        if j in owner:
            continue
        c = bh[j, :3]
        gap = np.linalg.norm(np.maximum(np.abs(c[None, :] - bl[:, :3]) - bl[:, 3:] / 2, 0.0), axis=1)
        vol = np.prod(np.maximum(bl[:, 3:], 1e-9), axis=1)
        owner[j] = int(np.lexsort((vol, np.round(gap, 6)))[0])
    order = {i: k for k, i in enumerate(sorted({i for i, _ in pairs} | set(owner.values())))}
    lo_new, hi_new = lo_co.copy(), hi_co.copy()
    for i, k in order.items():
        lo_new[lo_lab == i] += np.array([spacing * (k + 1), 0.0, 0.0])
    for j, i in owner.items():
        hi_new[hi_lab == j] += np.array([spacing * (order[i] + 1), 0.0, 0.0])
    low.data.vertices.foreach_set("co", lo_new.reshape(-1))
    high.data.vertices.foreach_set("co", hi_new.reshape(-1))
    low.data.update()
    high.data.update()

    def restore():
        low.data.vertices.foreach_set("co", lo_co.reshape(-1))
        high.data.vertices.foreach_set("co", hi_co.reshape(-1))
        low.data.update()
        high.data.update()
    return restore, len(order), lo_lab


def ray_plan(high, low, lab, n):
    """The bake ray per exploded part, from the low-to-high distance (A5: a fixed share of the diagonal either
    stops short of the high poly, so a ray starts inside it and lands on its far side from behind, or reaches another
    surface). From each LOD0 point and face centre, the distance to the high poly along the normal (out or in, the
    nearer hit; the nearest point when neither hits) is sampled; the part's cage extrusion is its 99th percentile
    x 1.2 (at least 0.2% of the part's size) and its ray 2x that. Returns (extrusion per part, rows for the report)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    hc = coords(high)
    bvh = BVHTree.FromPolygons([tuple(v) for v in hc.tolist()], [tuple(p.vertices) for p in high.data.polygons])
    me = low.data
    lc = coords(low)
    ln = np.empty(len(lc) * 3)
    me.vertices.foreach_get("normal", ln)
    ln = ln.reshape(-1, 3)
    pc = np.empty(len(me.polygons) * 3)
    pn = np.empty(len(me.polygons) * 3)
    me.polygons.foreach_get("center", pc)
    me.polygons.foreach_get("normal", pn)
    pc, pn = pc.reshape(-1, 3), pn.reshape(-1, 3)
    pv = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_start", pv)
    lv = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", lv)
    plab = lab[lv[pv]]
    ext = np.zeros(n)
    rows = []
    for k in range(n):
        pts = np.concatenate([lc[lab == k], pc[plab == k]])
        nrm = np.concatenate([ln[lab == k], pn[plab == k]])
        if not len(pts):
            continue
        size = float(np.linalg.norm(pts.max(0) - pts.min(0)))
        lim = max(size * 0.25, 1e-3)
        if len(pts) > 6000:
            pick = np.linspace(0, len(pts) - 1, 6000).astype(int)
            pts, nrm = pts[pick], nrm[pick]
        d = np.empty(len(pts))
        for i, (p, q) in enumerate(zip(pts.tolist(), nrm.tolist())):
            p, q = Vector(p), Vector(q)
            best = None
            for dirn in (q, -q):
                hit = bvh.ray_cast(p, dirn, lim)
                if hit[0] is not None:
                    best = hit[3] if best is None else min(best, hit[3])
            if best is None:
                f = bvh.find_nearest(p, lim)
                best = f[3] if f[0] is not None else lim
            d[i] = best
        p99 = float(np.percentile(d, 99))
        ext[k] = max(p99 * 1.2, size * 0.002, 1e-3)
        rows.append({"part": k, "samples": int(len(d)), "p99_mm": round(p99, 4), "max_mm": round(float(d.max()), 4),
                     "extrusion_mm": round(float(ext[k]), 4), "ray_mm": round(float(ext[k] * 2), 4)})
    return ext, rows


def detail_reach(high, low, lab, ext, rows):
    """High-only detail (a bolt, a strap, a raised panel) is a small share of the surface, so the 99th percentile of
    the low-to-high distance misses it and the bake ray would start inside it. With a high-only mesh, each part's
    extrusion also covers the farthest high-poly point outside its LOD0 surface (x 1.05)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    me = low.data
    bvh = BVHTree.FromPolygons([tuple(v) for v in coords(low).tolist()], [tuple(p.vertices) for p in me.polygons])
    pv = np.empty(len(me.polygons), dtype=np.int64)
    me.polygons.foreach_get("loop_start", pv)
    lv = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", lv)
    plab = lab[lv[pv]]
    hc = coords(high)
    if len(hc) > 40000:
        hc = hc[np.linspace(0, len(hc) - 1, 40000).astype(int)]
    out = np.zeros(len(ext))
    for p in hc.tolist():
        loc, nrm, idx, dist = bvh.find_nearest(Vector(p))
        if loc is None or (Vector(p) - loc).dot(nrm) <= 0:
            continue
        k = int(plab[idx])
        out[k] = max(out[k], dist)
    ext = np.maximum(ext, out * 1.05)
    for r in rows:
        r["detail_mm"] = round(float(out[r["part"]]), 4)
        r["extrusion_mm"] = round(float(ext[r["part"]]), 4)
        r["ray_mm"] = round(float(ext[r["part"]] * 2), 4)
    return ext


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
    target = bpy.data.materials.new("FormBakeTarget")
    target.use_nodes = True
    tnode = target.node_tree.nodes.new("ShaderNodeTexImage")
    target.node_tree.nodes.active = tnode
    low.data.materials.clear()
    low.data.materials.append(target)
    for p in low.data.polygons:
        p.material_index = 0
    times, imgs, arrays = {}, {}, {}
    # the cage: LOD0 pushed out along its normals by its part's extrusion (measured exploded, see ray_plan)
    undo, _parts, lab = explode(high, low, diag * 3.0)          # exploded only to measure, then put back
    nparts = int(lab.max()) + 1 if len(lab) else 0
    ext, rays = ray_plan(high, low, lab, nparts)
    if job.get("high_input"):
        ext = detail_reach(high, low, lab, ext, rays)
    undo()
    ray = float(ext.max() * 2) if len(ext) else diag * 0.03
    vn = np.empty(len(low.data.vertices) * 3)
    low.data.vertices.foreach_get("normal", vn)
    push = vn.reshape(-1, 3) * ext[lab][:, None]
    cage = copy_object(low, "FormBakeCage")

    def place_cage():
        cage.data.vertices.foreach_set("co", (coords(low) + push).reshape(-1))
        cage.data.update()
    hidden = []                                    # the LODs lie on the surface: they must not shade it (AO)
    for o in bpy.context.scene.objects:
        if o is not high:
            hidden.append((o, o.visible_camera, o.visible_diffuse, o.visible_glossy, o.visible_transmission,
                           o.visible_volume_scatter, o.visible_shadow))
            o.visible_camera = o.visible_diffuse = o.visible_glossy = False
            o.visible_transmission = o.visible_volume_scatter = o.visible_shadow = False
    activate(low, others=[high])

    def bake(key, btype, color_space, samples, **kw):
        img = bpy.data.images.new(f"{job['asset']}_{key}", px, px, alpha=False)
        img.colorspace_settings.name = color_space
        tnode.image = img
        sc.cycles.samples = int(samples)
        t0 = time.perf_counter()
        bpy.ops.object.bake(type=btype, use_selected_to_active=True, use_cage=True, cage_object=cage.name,
                            max_ray_distance=ray, margin=int(b["margin_px"]), target="IMAGE_TEXTURES", **kw)
        times[key] = round(time.perf_counter() - t0, 3)
        a = np.empty(px * px * 4, dtype=np.float32)
        img.pixels.foreach_get(a)
        arrays[key] = a.reshape(px, px, 4)
        imgs[key] = img
        say("FORM_STEP", f"baked {key} in {times[key]} s")

    def emit_bake(key, color_space, source):
        """Bake a value as it is shaded on the high poly (a Principled input, a mask, the emission colour) by routing
        it to emission: the DIFFUSE colour pass would give black for metals (their diffuse is zero), and metallic and
        the masks have no bake type. Every material's own emission link is put back afterwards."""
        saved = []
        for m in high.data.materials:
            bs = principled(m)
            ec, es = bs.inputs["Emission Color"], bs.inputs["Emission Strength"]
            old = ec.links[0].from_socket if ec.is_linked else None
            saved.append((m, ec, old, tuple(ec.default_value), es, es.default_value))
            for ln in list(ec.links):
                m.node_tree.links.remove(ln)
            src = source(m)
            if hasattr(src, "is_output"):
                m.node_tree.links.new(src, ec)
            else:
                ec.default_value = src
            es.default_value = 1.0
        try:
            bake(key, "EMIT", color_space, b["samples"])
        finally:
            for m, ec, old, c, es, v in saved:
                for ln in list(ec.links):
                    m.node_tree.links.remove(ln)
                if old is not None:
                    m.node_tree.links.new(old, ec)
                ec.default_value = c
                es.default_value = v

    def input_of(name):
        def get(m):
            s = principled(m).inputs[name]
            if s.is_linked:
                return s.links[0].from_socket
            v = s.default_value
            return tuple(v) if hasattr(v, "__len__") else (float(v), float(v), float(v), 1.0)
        return get

    def named(node_name):
        def get(m):
            nd = m.node_tree.nodes.get(node_name)
            return nd.outputs[0] if nd is not None else (0.0, 0.0, 0.0, 1.0)
        return get
    maps = set(b["maps"])
    # AO is baked with the parts in place (a lid does shade the box under it); every surface map is baked exploded,
    # so each part only ever sees its own high poly (see explode())
    place_cage()
    if "orm" in maps or "ao" in maps:
        bake("ao", "AO", "Non-Color", b["ao_samples"])
    restore, moved = explode(high, low, diag * 3.0)[:2]
    place_cage()
    emissive = any(bool(m.get("form_emissive")) for m in high.data.materials)
    try:
        if "base_color" in maps:
            emit_bake("base_color", "sRGB", input_of("Base Color"))
            emit_bake("masks", "Non-Color", named("FormMasks"))
            if emissive:
                emit_bake("emissive", "sRGB", named("FormEmission"))
        if "normal" in maps:
            bake("normal", "NORMAL", "Non-Color", b["samples"], normal_space="TANGENT")
        if "orm" in maps:
            emit_bake("roughness", "Non-Color", input_of("Roughness"))
            emit_bake("metallic", "Non-Color", input_of("Metallic"))
    finally:
        restore()
    wear = wear_measure(low, arrays["masks"]) if "masks" in arrays else None
    hidden = [h for h in hidden if h[0] is not cage]
    bpy.data.objects.remove(cage)

    def gray(key, channel, src):
        a = np.ones((px, px, 4), dtype=np.float32)
        a[..., 0] = a[..., 1] = a[..., 2] = arrays[src][..., channel]
        img = bpy.data.images.new(f"{job['asset']}_{key}", px, px, alpha=False)
        img.colorspace_settings.name = "Non-Color"
        img.pixels.foreach_set(a.reshape(-1))
        imgs[key] = img
    if "masks" in arrays:
        gray("curvature", 0, "masks")
        gray("thickness", 2, "masks")
    if "orm" in maps:
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
    for key in ("base_color", "normal", "orm", "ao", "emissive", "curvature", "thickness"):
        if key in imgs and (key in maps or key in EXTRA_MAPS):
            path = inside(work, f"{key}.png")
            imgs[key].filepath_raw = path
            imgs[key].file_format = "PNG"
            imgs[key].save()
            files[key] = os.path.basename(path)
    return {"seconds": times, "total_seconds": round(sum(times.values()), 3), "files": files,
            "px": px, "samples": b["samples"], "ao_samples": b["ao_samples"], "device": sc.cycles.device,
            "cage_extrusion": round(float(ext.max()) if len(ext) else 0.0, 4), "max_ray_distance": round(ray, 4),
            "rays": rays, "exploded_parts": moved, "parts": nparts, "wear": wear,
            "ray_note": "a cage per exploded part (extrusion p99 x 1.2 of its low-to-high distance); one bake call "
                        "takes one ray length, the largest part's (2 x its extrusion)"}, imgs


def wear_measure(low, masks, n=200_000):
    """How much of LOD0's surface the baked wear mask (masks G) covers, by area: surface samples (a fixed seed)
    looked up in the mask through LOD0's UVs. worn_share is the share worn (mask over 0.5), convex_share the share
    on a convex edge (R over 0.5), worn_on_convex the share of the convex edges that is worn and convex_of_worn the
    share of the worn surface that lies on a convex edge. Measured, not judged."""
    a = lod_arrays(low)
    P, UV, T = a["P"], a["UV"], a["T"]
    if not len(T):
        return None
    A = 0.5 * np.linalg.norm(np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]]), axis=1)
    if A.sum() <= 0:
        return None
    rng = np.random.default_rng(5)
    k = rng.choice(len(T), size=n, p=A / A.sum())
    u, v = rng.random(n), rng.random(n)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    uv = UV[T[k, 0]] * (1 - u - v)[:, None] + UV[T[k, 1]] * u[:, None] + UV[T[k, 2]] * v[:, None]
    px = masks.shape[0]
    x = np.clip((uv[:, 0] * px).astype(int), 0, px - 1)
    y = np.clip((uv[:, 1] * px).astype(int), 0, px - 1)       # Blender's pixel rows run bottom-up, like v
    s = masks[y, x]
    convex, worn = s[:, 0] > 0.5, s[:, 1] > 0.5
    out = {"worn_share": round(float(worn.mean()), 4), "convex_share": round(float(convex.mean()), 4),
           "worn_on_convex": round(float((worn & convex).sum() / max(int(convex.sum()), 1)), 4),
           "convex_of_worn": round(float((worn & convex).sum() / max(int(worn.sum()), 1)), 4),
           "samples": n, "threshold": 0.5}
    return out


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
    mats = [make_material(m, job["masks"]) for m in job["materials"]]
    margin = num(job["uv"]["margin_px"], 0, 64) / int(job["texture_px"])
    lods, report = [], []
    texel = None
    high_src = "the cage subdivided"
    if job["source"] == "cage":
        say("FORM_STEP", "cage")
        base = base_from_cage(z, mats)
        say("FORM_STEP", f"UVs ({job['uv']['method']})")
        unwrap(base, job["uv"]["method"], margin, at_limit=True)
        texel = even_texel(base, margin)
        timing["uv"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        if job.get("high_input"):                  # detail that exists only on the high poly (high_only cage ops)
            zh = np.load(inside(work, job["high_input"]), allow_pickle=False)
            hb = base_from_cage(zh, mats)
            hb.name = hb.data.name = "FormHighCage"
            high = subdivide(hb, int(job["high_input_level"]))
            high_src = "the high-only cage subdivided"
        else:
            high = subdivide(copy_object(base, "FormHigh"), int(job["high_level"]))
        high.name = high.data.name = "FormHigh"
        timing["high"] = round(time.perf_counter() - t, 3)
        for spec in job["lods"]:
            t = time.perf_counter()
            name = spec["name"]
            ob = subdivide(copy_object(base, name + "_src"), int(spec["level"]))
            it = 0
            if spec["decimate"]:
                triangulate(ob)
                dec, it = decimate_to(ob, name, int(spec["budget"]), keep_seams=spec["lod"] == 0)
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
            "high_triangles": tris(high), "high_source": high_src, "bake": bake, "timing": timing,
            "exports": exports, "collision_objects": [o.name for o in cols], "texel": texel}


def watch_parent():
    """Blender runs in its own process group, so it would outlive a Form Studio that was killed mid-bake. A thread
    (Cycles bakes leave Python threads running) ends this process when its parent is gone (it is re-parented)."""
    parent = os.getppid()

    def loop():
        while True:
            time.sleep(1.0)
            if os.getppid() != parent:
                os._exit(5)
    threading.Thread(target=loop, name="form-parent-watch", daemon=True).start()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    watch_parent()
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
