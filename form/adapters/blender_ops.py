"""Form Studio's fixed modelling runner. It runs inside Blender's own Python (blender -b ... --python blender_ops.py).

It reads one job file (JSON, written by form/adapters/blender_model.py after the op list was schema-checked there) and
executes a declarative op list on one quad cage. It never runs code it is given: every op name is looked up in OPS,
every enum value in a fixed table, and every number is checked again here. It imports nothing that talks to a network
or starts a process (tests/test_blender_model.py checks that by reading this file's syntax tree).

Protocol on stdout (one line each):
    FORM_STEP <text>              an op started
    FORM_STAGE <path.bin>         a preview of the cage after an op, at subdivision level 2 (format below)
    FORM_RESULT <json>            the end: {"ok": true, ...} or {"ok": false, "error": ..., "op": index}

A stage file is little-endian: b"FMS1", uint32 op index, uint32 vertex count n, uint32 triangle count t,
float32[n*3] positions (mm), uint32[t*3] indices.

Units are millimetres throughout; Blender's scene units are not used.
"""
import json
import math
import struct
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector

RUNNER_VERSION = 1
MAX_SCATTER = 2000
CREASE = "crease_edge"
REGION = "form_region_"
AXES = {"x": 0, "y": 1, "z": 2}
MIRROR_AXIS = {"x": "X", "y": "Y", "z": "Z"}


class OpError(Exception):
    pass


def say(tag, text):
    sys.stdout.write(f"{tag} {text}\n")
    sys.stdout.flush()


def num(x, lo=-1e6, hi=1e6):
    x = float(x)
    if not math.isfinite(x) or not lo <= x <= hi:
        raise OpError(f"number {x} out of range [{lo}, {hi}]")
    return x


def vec(v):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise OpError("expected [x, y, z]")
    return Vector([num(a) for a in v])


# ---- the cage object ---------------------------------------------------------------------------------------------

def cage_object():
    ob = bpy.data.objects.get("FormCage")
    if ob is None:
        me = bpy.data.meshes.new("FormCage")
        ob = bpy.data.objects.new("FormCage", me)
        bpy.context.scene.collection.objects.link(ob)
    return ob


def load_bm(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return bm


def store_bm(ob, bm):
    bm.normal_update()
    bm.to_mesh(ob.data)
    ob.data.update()
    bm.free()


def canonical(ob):
    """Put points and faces in an order that depends only on the geometry: some bmesh operators order their output
    by memory address, so without this a replay could number the same cage differently. Points sort by position
    (rounded to 1e-6 mm), faces by their point indices, each read from its lowest index (orientation kept)."""
    bm = load_bm(ob)
    vk = sorted(bm.verts, key=lambda v: (round(v.co.x, 6), round(v.co.y, 6), round(v.co.z, 6), v.index))
    vrank = {v.index: r for r, v in enumerate(vk)}            # sort() takes a number, so sort by rank
    bm.verts.sort(key=lambda v: vrank[v.index])
    bm.verts.index_update()

    def fkey(f):
        ix = [v.index for v in f.verts]
        k = ix.index(min(ix))
        return tuple(ix[k:] + ix[:k])
    fk = sorted(bm.faces, key=lambda f: (fkey(f), f.index))
    frank = {f.index: r for r, f in enumerate(fk)}
    bm.faces.sort(key=lambda f: frank[f.index])
    bm.faces.index_update()
    store_bm(ob, bm)


def crease_layer(bm):
    return bm.edges.layers.float.get(CREASE) or bm.edges.layers.float.new(CREASE)


def region_layers(bm):
    return {k[len(REGION):]: l for k, l in bm.faces.layers.int.items() if k.startswith(REGION)}


def select_faces(bm, sel):
    bm.faces.ensure_lookup_table()
    if sel.get("all"):
        return list(bm.faces)
    if "region" in sel:
        lay = region_layers(bm).get(sel["region"])
        if lay is None:
            raise OpError(f"no region named {sel['region']}")
        out = [f for f in bm.faces if f[lay]]
    elif "indices" in sel:
        n = len(bm.faces)
        bad = [i for i in sel["indices"] if not 0 <= i < n]
        if bad:
            raise OpError(f"face index {bad[0]} out of range (the cage has {n} faces)")
        out = [bm.faces[i] for i in sel["indices"]]
    elif "normal" in sel:
        d = vec(sel["normal"]).normalized()
        c = math.cos(math.radians(num(sel.get("within_deg", 1.0), 0, 180)))
        bm.normal_update()
        out = [f for f in bm.faces if f.normal.dot(d) >= c - 1e-9]
    else:
        raise OpError("a face selection needs all, region, indices or normal")
    if not out:
        raise OpError("the face selection is empty")
    return out


def select_verts(bm, sel):
    bm.verts.ensure_lookup_table()
    if "indices" in sel:
        n = len(bm.verts)
        bad = [i for i in sel["indices"] if not 0 <= i < n]
        if bad:
            raise OpError(f"vertex index {bad[0]} out of range (the cage has {n} points)")
        out = [bm.verts[i] for i in sel["indices"]]
    elif "box" in sel:
        lo, hi = vec(sel["box"][0]), vec(sel["box"][1])
        out = [v for v in bm.verts if all(lo[k] - 1e-9 <= v.co[k] <= hi[k] + 1e-9 for k in range(3))]
    else:
        seen, out = set(), []
        for f in select_faces(bm, sel):
            for v in f.verts:
                if v.index not in seen:
                    seen.add(v.index)
                    out.append(v)
    if not out:
        raise OpError("the point selection is empty")
    return out


def find_edge(bm, a, b):
    n = len(bm.verts)
    if not (0 <= a < n and 0 <= b < n):
        raise OpError(f"edge [{a}, {b}] names a point that does not exist (the cage has {n} points)")
    e = bm.edges.get((bm.verts[a], bm.verts[b]))
    if e is None:
        raise OpError(f"points {a} and {b} are not joined by an edge")
    return e


# ---- ops -------------------------------------------------------------------------------------------------------

def op_cage_new(ob, o):
    bm = bmesh.new()
    if "quads" in o:
        V, F = o["quads"]["V"], o["quads"]["F"]
        vs = [bm.verts.new(vec(p)) for p in V]
        bm.verts.ensure_lookup_table()
        for f in F:
            try:
                bm.faces.new([vs[i] for i in f])
            except ValueError as e:
                raise OpError(f"face {f}: {e}")
    else:
        prim = o["primitive"]
        if prim in ("cube", "quad_sphere"):
            bmesh.ops.create_cube(bm, size=1.0)
            if prim == "quad_sphere":
                cuts = int(o.get("segments", 4)) - 1
                if cuts > 0:
                    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
                r = num(o.get("radius", 10.0), 1e-6)
                for v in bm.verts:
                    v.co = v.co.normalized() * r
            else:
                s = vec(o.get("size", [10, 10, 10]))
                bmesh.ops.scale(bm, vec=s, verts=bm.verts[:])
        elif prim == "plane":
            n = int(o.get("segments", 1))
            bmesh.ops.create_grid(bm, x_segments=n, y_segments=n, size=0.5)
            s = vec(o.get("size", [10, 10, 1]))
            bmesh.ops.scale(bm, vec=Vector((s[0], s[1], 1.0)), verts=bm.verts[:])
        elif prim == "cylinder":
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=int(o.get("segments", 8)),
                                  radius1=num(o.get("radius", 5.0), 1e-6), radius2=num(o.get("radius", 5.0), 1e-6),
                                  depth=num(o.get("height", 10.0), 1e-6))
        else:
            raise OpError(f"unknown primitive {prim}")
    c = o.get("center")
    if c:
        bmesh.ops.translate(bm, vec=vec(c), verts=bm.verts[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    crease_layer(bm)
    store_bm(ob, bm)


def op_extrude_region(ob, o):
    bm = load_bm(ob)
    faces = select_faces(bm, o["faces"])
    bm.normal_update()
    n = Vector()
    for f in faces:
        n += f.normal * f.calc_area()
    d = vec(o["vector"]) if "vector" in o else (n.normalized() * num(o["offset"]))
    res = bmesh.ops.extrude_face_region(bm, geom=faces, use_keep_orig=False)
    verts = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=d, verts=verts)
    left = [f for f in faces if f.is_valid]        # the region's old faces are inside the solid now
    if left:
        bmesh.ops.delete(bm, geom=left, context="FACES_ONLY")
    store_bm(ob, bm)


def edge_ring(e0):
    """The edges across a strip of quads, starting at e0 and walking both ways."""
    ring, seen = [e0], {e0.index}
    for start in list(e0.link_faces)[:2]:
        e, f = e0, start
        while f is not None and len(f.verts) == 4:
            loops = list(f.loops)
            i = next(k for k, l in enumerate(loops) if l.edge == e)
            opp = loops[(i + 2) % 4].edge
            if opp.index in seen:
                break
            seen.add(opp.index)
            ring.append(opp)
            nxt = [g for g in opp.link_faces if g != f]
            e, f = opp, (nxt[0] if len(nxt) == 1 else None)
    return ring


def op_loop_cut(ob, o):
    bm = load_bm(ob)
    e = find_edge(bm, *o["edge"])
    ring = edge_ring(e)
    bmesh.ops.subdivide_edges(bm, edges=ring, cuts=int(o.get("cuts", 1)), use_grid_fill=False,
                              use_only_quads=True)
    store_bm(ob, bm)


def op_move(ob, o):
    bm = load_bm(ob)
    vs = select_verts(bm, o["verts"])
    if "by" in o:
        bmesh.ops.translate(bm, vec=vec(o["by"]), verts=vs)
    if "scale" in o:
        c = Vector()
        for v in vs:
            c += v.co
        c /= len(vs)
        s = vec(o["scale"])
        for v in vs:
            v.co = c + Vector([(v.co[k] - c[k]) * s[k] for k in range(3)])
    store_bm(ob, bm)


def op_crease(ob, o):
    bm = load_bm(ob)
    lay = crease_layer(bm)
    val = num(o.get("value", 1.0), 0.0, 1.0)
    if "edges" in o:
        edges = [find_edge(bm, a, b) for a, b in o["edges"]]
    else:
        faces = set(select_faces(bm, {"region": o["region_boundary"]}))
        edges = [e for f in faces for e in f.edges if sum(g in faces for g in e.link_faces) == 1]
        if not edges:
            raise OpError(f"region {o['region_boundary']} has no boundary")
    for e in edges:
        e[lay] = val
    store_bm(ob, bm)


def op_name_region(ob, o):
    bm = load_bm(ob)
    key = REGION + o["name"]
    lay = bm.faces.layers.int.get(key) or bm.faces.layers.int.new(key)     # a new layer first: it re-allocates faces
    bm.faces.ensure_lookup_table()
    faces = select_faces(bm, o["faces"])
    for f in faces:
        f[lay] = 1
    store_bm(ob, bm)


def op_mirror(ob, o):
    bm = load_bm(ob)
    k = AXES[o["axis"]]
    thr = num(o.get("merge", 1e-4), 0.0, 10.0)
    if o.get("clip", True):
        no = Vector((0, 0, 0))
        no[k] = 1.0
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, dist=thr, plane_co=Vector(), plane_no=no, clear_inner=True)
        for v in bm.verts:                         # points on the plane sit exactly on it, so the halves weld
            if abs(v.co[k]) <= max(thr, 1e-9):
                v.co[k] = 0.0
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    bmesh.ops.mirror(bm, geom=geom, matrix=Matrix.Identity(4), merge_dist=thr, axis=MIRROR_AXIS[o["axis"]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    store_bm(ob, bm)


def _gn_group(name):
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi = ng.nodes.new("NodeGroupInput")
    go = ng.nodes.new("NodeGroupOutput")
    return ng, gi, go


def _apply_modifier(ob, mod):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    ob.modifiers.remove(mod)
    old = ob.data
    ob.data = me
    bpy.data.meshes.remove(old)
    name = me.name
    me.name = "FormCage"
    return name


def op_geonodes_array(ob, o):
    ng, gi, go = _gn_group("FormArray")
    line = ng.nodes.new("GeometryNodeMeshLine")
    line.mode = "OFFSET"
    line.inputs["Count"].default_value = int(o["count"])
    line.inputs["Offset"].default_value = vec(o["offset"])
    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    real = ng.nodes.new("GeometryNodeRealizeInstances")
    ng.links.new(line.outputs["Mesh"], inst.inputs["Points"])
    ng.links.new(gi.outputs[0], inst.inputs["Instance"])
    ng.links.new(inst.outputs["Instances"], real.inputs[0])
    ng.links.new(real.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("FormArray", "NODES")
    mod.node_group = ng
    _apply_modifier(ob, mod)
    bpy.data.node_groups.remove(ng)


def op_geonodes_scatter(ob, o):
    me = ob.data
    area = sum(p.area for p in me.polygons) or 1.0
    ng, gi, go = _gn_group("FormScatter")
    sel = ng.nodes.new("GeometryNodeDistributePointsOnFaces")
    sel.distribute_method = "RANDOM"
    sel.inputs["Density"].default_value = int(o["count"]) / area
    sel.inputs["Seed"].default_value = int(o.get("seed", 0))
    cube = ng.nodes.new("GeometryNodeMeshCube")
    cube.inputs["Size"].default_value = Vector([num(o.get("item_size", 1.0), 1e-6)] * 3)
    rnd = ng.nodes.new("FunctionNodeRandomValue")
    rnd.data_type = "FLOAT"
    lo, hi = o.get("scale", [1.0, 1.0])
    rnd.inputs["Min"].default_value = num(lo, 1e-3, 1e3)
    rnd.inputs["Max"].default_value = num(hi, 1e-3, 1e3)
    rnd.inputs["Seed"].default_value = int(o.get("seed", 0))
    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    real = ng.nodes.new("GeometryNodeRealizeInstances")
    join = ng.nodes.new("GeometryNodeJoinGeometry")
    ng.links.new(gi.outputs[0], sel.inputs["Mesh"])
    ng.links.new(sel.outputs["Points"], inst.inputs["Points"])
    ng.links.new(cube.outputs["Mesh"], inst.inputs["Instance"])
    ng.links.new(rnd.outputs["Value"], inst.inputs["Scale"])
    ng.links.new(inst.outputs["Instances"], real.inputs[0])
    ng.links.new(gi.outputs[0], join.inputs[0])
    ng.links.new(real.outputs[0], join.inputs[0])
    ng.links.new(join.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("FormScatter", "NODES")
    mod.node_group = ng
    _apply_modifier(ob, mod)
    bpy.data.node_groups.remove(ng)


def _falloff(d, r):
    if d >= r:
        return 0.0
    t = 1.0 - d / r
    return t * t * (3 - 2 * t)


def op_sculpt_ops(ob, o):
    """Form's own deterministic brushes, applied to the cage points (not Blender's interactive sculpt mode)."""
    bm = load_bm(ob)
    for s in o["strokes"]:
        bm.normal_update()
        c, r, k = vec(s["center"]), num(s["radius"], 1e-6), num(s.get("strength", 0.5), -1.0, 1.0)
        brush = s["brush"]
        hit = [(v, _falloff((v.co - c).length, r)) for v in bm.verts]
        hit = [(v, w) for v, w in hit if w > 0]
        if not hit:
            continue
        if brush in ("draw", "inflate"):
            for v, w in hit:
                v.co = v.co + v.normal * (k * w * r * (0.25 if brush == "draw" else 0.1))
        elif brush == "grab":
            d = vec(s["direction"])
            for v, w in hit:
                v.co = v.co + d * (w * abs(k))
        elif brush == "pinch":
            for v, w in hit:
                v.co = v.co + (c - v.co) * (k * w * 0.5)
        elif brush == "smooth":
            for _ in range(int(s.get("iterations", 1))):
                new = {}
                for v, w in hit:
                    nb = [e.other_vert(v).co for e in v.link_edges]
                    if nb:
                        avg = sum(nb, Vector()) / len(nb)
                        new[v.index] = v.co.lerp(avg, abs(k) * w)
                for v, _w in hit:
                    if v.index in new:
                        v.co = new[v.index]
        elif brush == "flatten":
            pc = sum((v.co for v, _ in hit), Vector()) / len(hit)
            pn = sum((v.normal * w for v, w in hit), Vector())
            pn = pn.normalized() if pn.length > 1e-12 else Vector((0, 0, 1))
            for v, w in hit:
                v.co = v.co - pn * ((v.co - pc).dot(pn) * abs(k) * w)
        else:
            raise OpError(f"unknown brush {brush}")
    store_bm(ob, bm)


def op_remesh(ob, o):
    if o["mode"] == "voxel":
        mod = ob.modifiers.new("FormRemesh", "REMESH")
        mod.mode = "VOXEL"
        mod.voxel_size = num(o["voxel_size"], 1e-4)
        mod.use_smooth_shade = False
        _apply_modifier(ob, mod)
    else:                                          # QuadriFlow: Blender's automatic quad retopology
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        r = bpy.ops.object.quadriflow_remesh(target_faces=int(o["target_faces"]), seed=int(o.get("seed", 0)),
                                             use_mesh_symmetry=False, use_preserve_sharp=False,
                                             use_preserve_boundary=False, smooth_normals=False, mode="FACES")
        if "FINISHED" not in r:
            raise OpError(f"QuadriFlow did not finish ({r})")


OPS = {"cage_new": op_cage_new, "extrude_region": op_extrude_region, "loop_cut": op_loop_cut, "move": op_move,
       "crease": op_crease, "name_region": op_name_region, "mirror": op_mirror, "geonodes_array": op_geonodes_array,
       "geonodes_scatter": op_geonodes_scatter, "sculpt_ops": op_sculpt_ops, "remesh": op_remesh}


# ---- reading the cage back -----------------------------------------------------------------------------------------

def cage_data(ob):
    me = ob.data
    n = len(me.vertices)
    co = [0.0] * (n * 3)
    me.vertices.foreach_get("co", co)
    V = [co[i:i + 3] for i in range(0, len(co), 3)]
    F = [list(p.vertices) for p in me.polygons]
    creases = []
    a = me.attributes.get(CREASE)
    if a is not None and a.domain == "EDGE":
        vals = [0.0] * len(me.edges)
        a.data.foreach_get("value", vals)
        creases = [[int(e.vertices[0]), int(e.vertices[1]), round(float(v), 6)] for e, v in zip(me.edges, vals) if v > 0]
    regions = {}
    for at in me.attributes:
        if at.name.startswith(REGION) and at.domain == "FACE":
            vals = [0] * len(me.polygons)
            at.data.foreach_get("value", vals)
            regions[at.name[len(REGION):]] = [i for i, x in enumerate(vals) if x]
    return {"V": V, "F": F, "creases": creases, "regions": regions}


def subdivided(ob, levels, limit=True, creases=True):
    """(positions flat list, triangle indices flat list, n verts, polygons) of the cage at a subdivision level."""
    tmp = ob.copy()
    tmp.data = ob.data.copy()
    bpy.context.scene.collection.objects.link(tmp)
    mod = tmp.modifiers.new("FormSubD", "SUBSURF")
    mod.levels = levels
    mod.render_levels = levels
    mod.subdivision_type = "CATMULL_CLARK"
    mod.use_limit_surface = limit
    mod.use_creases = creases
    mod.boundary_smooth = "ALL"
    mod.uv_smooth = "NONE"
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg), depsgraph=dg)
    me.calc_loop_triangles()
    n = len(me.vertices)
    co = [0.0] * (n * 3)
    me.vertices.foreach_get("co", co)
    tri = [0] * (len(me.loop_triangles) * 3)
    me.loop_triangles.foreach_get("vertices", tri)
    old = tmp.data
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(old)
    bpy.data.meshes.remove(me)
    return co, tri, n


def write_stage(ob, path, index, levels):
    co, tri, n = subdivided(ob, levels)
    t = len(tri) // 3
    with open(path, "wb") as f:
        f.write(b"FMS1" + struct.pack("<III", index, n, t))
        f.write(struct.pack(f"<{len(co)}f", *co))
        f.write(struct.pack(f"<{len(tri)}I", *tri))
    say("FORM_STAGE", path)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    job = json.loads(open(argv[0], encoding="utf-8").read())
    for ob in list(bpy.data.objects):              # an empty scene: the factory cube, camera and light go
        bpy.data.objects.remove(ob)
    ob = cage_object()
    times, stage_dir, levels = [], job.get("stage_dir"), int(job.get("preview_levels", 2))
    i = -1
    try:
        for i, o in enumerate(job["ops"]):
            fn = OPS.get(o.get("op"))
            if fn is None:
                raise OpError(f"unknown op {o.get('op')!r}")
            say("FORM_STEP", f"{i + 1}/{len(job['ops'])} {o['op']}")
            t0 = time.perf_counter()
            fn(ob, o)
            canonical(ob)
            dt = time.perf_counter() - t0
            if not len(ob.data.polygons):
                raise OpError("the cage has no faces left")
            ts = time.perf_counter()
            if stage_dir:
                write_stage(ob, f"{stage_dir}/stage_{i:03d}.bin", i, levels)
            times.append({"op": o["op"], "seconds": round(dt, 4), "stage_seconds": round(time.perf_counter() - ts, 4)})
        out = {"ok": True, "runner": RUNNER_VERSION, "blender": bpy.app.version_string, "ops": times,
               "cage": cage_data(ob)}
        chk = job.get("export_subdiv")
        if chk:                                    # verification: the cage subdivided by Blender (no limit projection)
            co, _tri, n = subdivided(ob, int(chk["levels"]), limit=False, creases=False)
            out["subdiv"] = {"levels": int(chk["levels"]), "V": [co[k:k + 3] for k in range(0, len(co), 3)]}
        with open(job["out"], "w", encoding="utf-8") as f:
            json.dump(out, f)
        say("FORM_RESULT", json.dumps({"ok": True, "ops": times}))
    except Exception as e:                         # report which op failed; the caller keeps the project as it was
        say("FORM_RESULT", json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}", "op": i, "ops": times}))
        sys.exit(3)


if __name__ == "__main__":
    main()
