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

Ops marked high_only (always the last ones in a list) work on a copy of the cage made when the first of them runs:
the bake source. The result's cage then carries it as "high" ({V, F, creases, regions}); the cage itself stays the
low-poly one the LODs are made from. A kit_place op arrives with its part's geometry ("mesh"), built by
blender_model.py from form.game.kit; the runner only places copies of it.
"""
import json
import math
import struct
import sys
import time

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

RUNNER_VERSION = 1
MAX_SCATTER = 2000
MAX_PLACE = 512
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


def high_object(ob):
    """The bake source: a copy of the cage as it stands when the first high_only op runs."""
    hi = ob.copy()
    hi.data = ob.data.copy()
    hi.name = "FormHigh"
    hi.data.name = "FormHigh"
    bpy.context.scene.collection.objects.link(hi)
    return hi


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
    if "box" in sel:                               # only faces whose centre is inside the box
        lo, hi = vec(sel["box"][0]), vec(sel["box"][1])
        out = [f for f in out if all(lo[k] - 1e-9 <= f.calc_center_median()[k] <= hi[k] + 1e-9 for k in range(3))]
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
    elif "box" in sel and len(sel) == 1:           # a point box (with region or normal it narrows a face selection)
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
    if o.get("sides") != "region":
        store_bm(ob, bm)
        return
    # sides "region": the side walls belong to the extruded part, each takes the regions of the face it rises to
    # (by default bmesh copies them from either neighbour, which is not even mirror-symmetric)
    top = {g for g in res["geom"] if isinstance(g, bmesh.types.BMFace) and g.is_valid}
    sides = {f for v in verts for f in v.link_faces if f not in top}
    layers = list(region_layers(bm).values())
    bm.faces.index_update()
    for f in sorted(sides, key=lambda x: x.index):
        src = next((g for e in f.edges for g in e.link_faces if g in top), None)
        if src is not None:
            for lay in layers:
                f[lay] = src[lay]
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
    if o.get("pin_corners") and val > 0:
        _pin_corners(bm, lay, {v for e in edges for v in e.verts})
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
    me.name = ob.name
    return name


def op_geonodes_array(ob, o):
    if "part" in o:
        return _ring_array(ob, o)
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


def _ring_array(ob, o):
    """A ring of kit-part copies at a constant pitch: the part placed at each seed point (+Z on the normal, as
    kit_place), then Geometry Nodes instances that seed set count times round the axis through center, each copy
    turned by 360 / count degrees more than the last, and realises them. The copies join the cage as closed shells."""
    count = int(o["count"])
    if count * len(o["at"]) > MAX_PLACE:
        raise OpError(f"geonodes_array: {count * len(o['at'])} copies; the limit is {MAX_PLACE}")
    k = AXES[o["axis"]]
    ctr = vec(o.get("center", [0, 0, 0]))
    mesh = o["mesh"]
    PV = [vec(p) for p in mesh["V"]]
    off = num(o.get("offset", 0.0))
    n = vec(o["normal"])
    if n.length < 1e-9:
        raise OpError("geonodes_array: the normal must not be zero")
    x, y, z = _frame(n)
    V, F, C = [], [], []
    for p in o["at"]:
        c = vec(p) - ctr
        base = len(V)
        V += [c + x * q.x + y * q.y + z * (q.z + off) for q in PV]
        F += [[base + i for i in f] for f in mesh["F"]]
        C += [(base + a, base + b, num(w, 0, 1)) for a, b, w in mesh["C"]]
    seed = bpy.data.meshes.new("FormRingSeed")
    seed.from_pydata([tuple(v) for v in V], [], F)
    seed.update()
    sb = bmesh.new()
    sb.from_mesh(seed)
    lay = crease_layer(sb)
    sb.verts.ensure_lookup_table()
    for a, b, w in C:
        e = sb.edges.get((sb.verts[a], sb.verts[b]))
        if e is not None:
            e[lay] = w
    sb.to_mesh(seed)
    sb.free()
    tmp = bpy.data.objects.new("FormRingSeed", seed)
    bpy.context.scene.collection.objects.link(tmp)
    ng, gi, go = _gn_group("FormRing")
    line = ng.nodes.new("GeometryNodeMeshLine")
    line.mode = "OFFSET"
    line.inputs["Count"].default_value = count
    line.inputs["Offset"].default_value = Vector((0.0, 0.0, 0.0))     # every point at the ring's centre
    idx = ng.nodes.new("GeometryNodeInputIndex")
    mul = ng.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = math.radians(num(o.get("angle", 360.0), 1e-3, 360.0)) / count
    cmb = ng.nodes.new("ShaderNodeCombineXYZ")
    ng.links.new(idx.outputs[0], mul.inputs[0])
    ng.links.new(mul.outputs[0], cmb.inputs["XYZ"[k]])
    inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
    real = ng.nodes.new("GeometryNodeRealizeInstances")
    ng.links.new(line.outputs["Mesh"], inst.inputs["Points"])
    ng.links.new(gi.outputs[0], inst.inputs["Instance"])
    ng.links.new(cmb.outputs[0], inst.inputs["Rotation"])
    ng.links.new(inst.outputs["Instances"], real.inputs[0])
    ng.links.new(real.outputs[0], go.inputs[0])
    mod = tmp.modifiers.new("FormRing", "NODES")
    mod.node_group = ng
    _apply_modifier(tmp, mod)
    bpy.data.node_groups.remove(ng)
    rm = tmp.data
    nv = len(rm.vertices)
    co = [0.0] * (nv * 3)
    rm.vertices.foreach_get("co", co)
    polys = [list(p.vertices) for p in rm.polygons]
    rc = {}
    a = rm.attributes.get(CREASE)
    if a is not None and a.domain == "EDGE":
        vals = [0.0] * len(rm.edges)
        a.data.foreach_get("value", vals)
        rc = {tuple(sorted(e.vertices)): float(v) for e, v in zip(rm.edges, vals) if v > 0}
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(rm)
    bm = load_bm(ob)
    ensure_region(bm, o.get("name"))
    lay = crease_layer(bm)
    vs = [bm.verts.new(Vector(co[i * 3:i * 3 + 3]) + ctr) for i in range(nv)]
    added = []
    for f in polys:
        try:
            added.append(bm.faces.new([vs[i] for i in f]))
        except ValueError as e:
            raise OpError(f"geonodes_array: ring face {f}: {e}")
    for (a2, b2), w in rc.items():
        e = bm.edges.get((vs[a2], vs[b2]))
        if e is not None:
            e[lay] = w
    if o.get("name"):
        tag_region(bm, added, o["name"])
    store_bm(ob, bm)


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


# ---- the detail vocabulary: bevel, support loops, inset, panel lines, trim, solidify, bridge, kit parts ------------

def select_edges(bm, sel):
    """Edges from an edge selection (blender_model.SELECTORS), in index order, each once."""
    bm.edges.ensure_lookup_table()
    if "pairs" in sel:
        out = [find_edge(bm, a, b) for a, b in sel["pairs"]]
    elif "path" in sel:
        p = list(sel["path"])
        if sel.get("closed"):
            p.append(p[0])
        out = [find_edge(bm, a, b) for a, b in zip(p, p[1:])]
    elif "region_boundary" in sel:
        faces = set(select_faces(bm, {"region": sel["region_boundary"]}))
        out = [e for f in faces for e in f.edges if sum(g in faces for g in e.link_faces) == 1]
    elif "box" in sel:
        lo, hi = vec(sel["box"][0]), vec(sel["box"][1])

        def inside(v):
            return all(lo[k] - 1e-9 <= v.co[k] <= hi[k] + 1e-9 for k in range(3))
        out = [e for e in bm.edges if inside(e.verts[0]) and inside(e.verts[1])]
    elif "angle_deg" in sel:
        lim = math.radians(num(sel["angle_deg"], 0, 180))
        bm.normal_update()
        out = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > lim]
    elif sel.get("creased"):
        lay = crease_layer(bm)
        out = [e for e in bm.edges if e[lay] >= 0.5]
    else:
        raise OpError("an edge selection needs pairs, path, region_boundary, angle_deg or creased")
    out = sorted({e.index: e for e in out}.values(), key=lambda e: e.index)
    if not out:
        raise OpError("the edge selection is empty")
    return out


def tag_region(bm, faces, name):
    key = REGION + name
    if bm.faces.layers.int.get(key) is None:
        raise OpError("internal: region layer missing")
    lay = bm.faces.layers.int.get(key)
    for f in faces:
        if f.is_valid:
            f[lay] = 1


def ensure_region(bm, name):
    """Make the region's layer before any face is held: a new layer re-allocates the faces."""
    if name:
        key = REGION + name
        if bm.faces.layers.int.get(key) is None:
            bm.faces.layers.int.new(key)
        bm.faces.ensure_lookup_table()


def border_edges(faces):
    fs = set(faces)
    return sorted({e.index: e for f in fs for e in f.edges if sum(g in fs for g in e.link_faces) == 1}.values(),
                  key=lambda e: e.index)


def _bevel(bm, edges, width, segments, profile):
    return bmesh.ops.bevel(bm, geom=list(edges), offset=width, offset_type="OFFSET", segments=segments,
                           profile=profile, affect="EDGES", clamp_overlap=True, loop_slide=True)


def op_bevel(ob, o):
    bm = load_bm(ob)
    ensure_region(bm, o.get("name"))
    lay = crease_layer(bm)
    edges = select_edges(bm, o["edges"])
    res = _bevel(bm, edges, num(o["width"], 1e-6), int(o["segments"]), num(o["profile"], 0.0, 1.0))
    faces = [f for f in res["faces"] if f.is_valid]
    inner = {e for f in faces for e in f.edges}
    for e in inner:                                # the bevel's own edges start smooth
        e[lay] = 0.0
    if "crease" in o:
        for e in border_edges(faces):
            e[lay] = num(o["crease"], 0, 1)
    if o.get("name"):
        tag_region(bm, faces, o["name"])
    store_bm(ob, bm)


def op_support_loops(ob, o):
    """A two-segment bevel with a square profile: a loop either side, the middle loop on the old edge."""
    bm = load_bm(ob)
    lay = crease_layer(bm)
    edges = select_edges(bm, o["edges"])
    keep = {e.index: e[lay] for e in edges}
    segs = [(e.verts[0].co.copy(), e.verts[1].co.copy(), keep[e.index]) for e in edges]
    res = _bevel(bm, edges, num(o["distance"], 1e-6), 2, 1.0)
    faces = [f for f in res["faces"] if f.is_valid]
    for f in faces:                                # a creased edge stays creased along its middle loop
        for e in f.edges:
            e[lay] = 0.0
            mid = (e.verts[0].co + e.verts[1].co) / 2
            for a, b, w in segs:
                if w > 0 and _dist_seg(mid, a, b) < 1e-5 * max((b - a).length, 1e-6) + 1e-7:
                    e[lay] = w
    if o.get("pin_corners"):
        _pin_corners(bm, lay, {v for f in faces for v in f.verts})
    store_bm(ob, bm)


def _pin_corners(bm, lay, verts, turn_deg=30.0):
    """Corner points of a creased loop: a point with two creased edges that turn by more than turn_deg gets every
    other edge creased too. Catmull-Clark treats a point with three or more creased edges as a corner and keeps it
    where it is; with two, it rounds the loop through it (a creased quad becomes a pill)."""
    lim = math.cos(math.radians(180.0 - turn_deg))
    for v in sorted(verts, key=lambda x: x.index):
        cr = [e for e in v.link_edges if e[lay] > 0]
        if len(cr) != 2:
            continue
        d0 = (cr[0].other_vert(v).co - v.co)
        d1 = (cr[1].other_vert(v).co - v.co)
        if d0.length < 1e-9 or d1.length < 1e-9 or d0.normalized().dot(d1.normalized()) <= lim:
            continue                                # a straight run, not a corner
        w = min(cr[0][lay], cr[1][lay])
        for e in v.link_edges:
            if e[lay] <= 0:
                e[lay] = w


def _dist_seg(p, a, b):
    ab = b - a
    t = 0.0 if ab.length_squared < 1e-18 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def offset_dir(normals):
    """The move that puts a point `1` away from every plane whose normal is given (their mean over its squared
    length; exact for two or three orthogonal planes), so a corner moves as far from each side as a flat point does.
    Held to 3x the plain normal at sharp corners."""
    n = sum(normals, Vector()) / len(normals)
    return n / max(n.length_squared, 1.0 / 9.0) if n.length > 1e-9 else Vector()


def op_inset(ob, o):
    bm = load_bm(ob)
    ensure_region(bm, o.get("name"))
    lay = crease_layer(bm)
    faces = select_faces(bm, o["faces"])
    fn = bmesh.ops.inset_individual if o.get("individual") else bmesh.ops.inset_region
    kw = dict(faces=faces, thickness=num(o["thickness"], 1e-6), depth=num(o.get("depth", 0.0)),
              use_even_offset=True, use_interpolate=True)
    if not o.get("individual"):
        kw["use_boundary"] = True
    fn(bm, **kw)
    if "crease" in o:
        for e in border_edges(faces):
            e[lay] = num(o["crease"], 0, 1)
    if o.get("name"):
        tag_region(bm, faces, o["name"])
    store_bm(ob, bm)


def op_panel_line(ob, o):
    """A V groove: support loops at half the width either side of the path, the middle loop pushed in."""
    bm = load_bm(ob)
    ensure_region(bm, o.get("name"))
    lay = crease_layer(bm)
    bm.normal_update()
    edges = select_edges(bm, o["edges"])
    segs = []
    for e in edges:
        n = Vector()
        for f in e.link_faces:
            n += f.normal
        segs.append((e.verts[0].co.copy(), e.verts[1].co.copy(), n.normalized() if n.length > 1e-12 else Vector()))
    size = max(max((b - a).length for a, b, _n in segs), 1e-6)
    res = _bevel(bm, edges, num(o["width"], 1e-6) / 2, 2, 1.0)
    faces = [f for f in res["faces"] if f.is_valid]
    verts = {v for f in faces for v in f.verts}
    mid = {}
    tol = 1e-5 * size + 1e-7
    for v in verts:
        ns = {tuple(round(x, 4) for x in s[2]): s[2] for s in segs if _dist_seg(v.co, s[0], s[1]) < tol}
        if ns:
            mid[v] = offset_dir(list(ns.values()))
    if not mid:
        raise OpError("panel_line: the groove's middle loop was not found")
    d = num(o["depth"], 1e-6)
    for v in mid:
        v.co = v.co - mid[v] * d
    w = num(o.get("crease", 1.0), 0, 1)
    for f in faces:
        for e in f.edges:
            e[lay] = 1.0 if (e.verts[0] in mid and e.verts[1] in mid) else 0.0
    for e in border_edges(faces):
        e[lay] = w
    if o.get("name"):
        tag_region(bm, faces, o["name"])
    store_bm(ob, bm)


def op_trim_strip(ob, o):
    """A raised band: a one-segment bevel along the path gives the strip, which is pushed out of the surface."""
    bm = load_bm(ob)
    ensure_region(bm, o.get("name"))
    lay = crease_layer(bm)
    edges = select_edges(bm, o["edges"])
    res = _bevel(bm, edges, num(o["width"], 1e-6) / 2, 1, 0.5)
    strip = [f for f in res["faces"] if f.is_valid]
    bm.normal_update()
    vn = {}
    for f in strip:
        for v in f.verts:
            vn.setdefault(v, {})[tuple(round(x, 4) for x in f.normal)] = f.normal.copy()
    ext = bmesh.ops.extrude_face_region(bm, geom=strip, use_keep_orig=False)
    new_faces = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMFace)]
    new_verts = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)]
    h = num(o["height"], 1e-6)
    # each new point is the copy of an old one; it moves along the strip's normal at the old point
    old_of, newset = {}, set(new_verts)
    for v in new_verts:
        for e in v.link_edges:
            u = e.other_vert(v)
            if u in vn and u not in newset:
                old_of[v] = u
    for v in new_verts:
        n = offset_dir(list(vn.get(old_of.get(v), {}).values()) or [Vector((0, 0, 1))])
        v.co = v.co + n * h
    left = [f for f in strip if f.is_valid]
    if left:
        bmesh.ops.delete(bm, geom=left, context="FACES_ONLY")
    top = [f for f in new_faces if f.is_valid and all(v in old_of for v in f.verts)]
    w = num(o.get("crease", 1.0), 0, 1)
    for e in border_edges(top):
        e[lay] = w
    for u in old_of.values():                      # the band's foot
        for e in u.link_edges:
            if e.other_vert(u) in old_of.values():
                e[lay] = w
    if o.get("name"):
        tag_region(bm, [f for f in new_faces if f.is_valid], o["name"])
    store_bm(ob, bm)


def op_solidify(ob, o):
    mod = ob.modifiers.new("FormSolidify", "SOLIDIFY")
    mod.thickness = num(o["thickness"])
    mod.offset = num(o.get("offset", -1.0), -1, 1)
    mod.use_rim = True
    mod.use_even_offset = True
    mod.use_quality_normals = True
    mod.edge_crease_rim = num(o.get("rim_crease", 0.0), 0, 1)
    _apply_modifier(ob, mod)
    bm = load_bm(ob)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    store_bm(ob, bm)


def op_bridge(ob, o):
    bm = load_bm(ob)
    ensure_region(bm, o.get("name"))
    fa, fb = select_faces(bm, o["faces_a"]), select_faces(bm, o["faces_b"])
    if set(fa) & set(fb):
        raise OpError("bridge: faces_a and faces_b overlap")
    la, lb = border_edges(fa), border_edges(fb)
    for name, loop in (("faces_a", la), ("faces_b", lb)):
        vs = {v for e in loop for v in e.verts}
        if not loop or len(vs) != len(loop):
            raise OpError(f"bridge: {name} must be one disc of faces with a single border loop")
    # the discs go with their inner edges and points; their borders stay (other faces use them)
    bmesh.ops.delete(bm, geom=list(fa) + list(fb), context="FACES")
    loops = [e for e in la + lb if e.is_valid]
    res = bmesh.ops.bridge_loops(bm, edges=loops, use_pairs=False, use_cyclic=False, use_merge=False,
                                 merge_factor=0.5, twist_offset=int(o.get("twist", 0)))
    faces = list(res["faces"])
    if not faces:
        raise OpError("bridge: Blender could not join the two borders")
    loopset = set(loops)
    ring = [e for e in res["edges"] if e not in loopset]
    if o.get("name"):                              # tagged first: subdivision copies face data to the pieces
        tag_region(bm, faces, o["name"])
    cuts = int(o.get("cuts", 0))
    if cuts and ring:
        bmesh.ops.subdivide_edges(bm, edges=[e for e in ring if e.is_valid], cuts=cuts, use_grid_fill=False,
                                  use_only_quads=True)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    store_bm(ob, bm)


def _frame(n):
    """A tangent frame for a surface normal: x level (in the world X-Y plane) where it can be."""
    n = n.normalized()
    x = Vector((0, 0, 1)).cross(n)
    if x.length < 1e-6:
        x = Vector((1, 0, 0)) if n.z > 0 else Vector((-1, 0, 0))
    x.normalize()
    return x, n.cross(x), n


def op_kit_place(ob, o):
    """Copies of a kit part (its geometry built by blender_model from form.game.kit), each its own closed shell."""

    bm = load_bm(ob)
    ensure_region(bm, o.get("name"))
    bm.normal_update()
    frames = []
    if "faces" in o:
        faces = sorted(select_faces(bm, o["faces"]), key=lambda f: f.index)
        if o.get("mode", "each") == "each":
            frames = [(f.calc_center_median(), f.normal.copy()) for f in faces]
        else:
            a = sum(f.calc_area() for f in faces) or 1.0
            c = sum((f.calc_center_median() * f.calc_area() for f in faces), Vector()) / a
            n = sum((f.normal * f.calc_area() for f in faces), Vector())
            frames = [(c, n if n.length > 1e-12 else Vector((0, 0, 1)))]
    elif o.get("snap"):
        tree = BVHTree.FromBMesh(bm)
        for p in o["at"]:
            loc, _nrm, idx, _d = tree.find_nearest(vec(p))
            if loc is None:
                raise OpError("kit_place: no surface to snap to")
            frames.append((loc, bm.faces[idx].normal.copy()))
    else:
        frames = [(vec(p), vec(o["normal"])) for p in o["at"]]
    if len(frames) > MAX_PLACE:
        raise OpError(f"kit_place: {len(frames)} copies; the limit is {MAX_PLACE}")
    mesh = o["mesh"]
    PV = [vec(p) for p in mesh["V"]]
    lay = crease_layer(bm)
    rkey = REGION + o["name"] if o.get("name") else None
    off = num(o.get("offset", 0.0))
    added = []
    for c, n in frames:
        x, y, z = _frame(n)
        vs = [bm.verts.new(c + x * p.x + y * p.y + z * (p.z + off)) for p in PV]
        for f in mesh["F"]:
            try:
                added.append(bm.faces.new([vs[i] for i in f]))
            except ValueError as e:
                raise OpError(f"kit_place: part face {f}: {e}")
        for a, b, w in mesh["C"]:
            e = bm.edges.get((vs[a], vs[b]))
            if e is not None:
                e[lay] = num(w, 0, 1)
    if rkey:
        tag_region(bm, added, o["name"])
    store_bm(ob, bm)


OPS = {"cage_new": op_cage_new, "extrude_region": op_extrude_region, "loop_cut": op_loop_cut, "move": op_move,
       "crease": op_crease, "name_region": op_name_region, "mirror": op_mirror, "geonodes_array": op_geonodes_array,
       "geonodes_scatter": op_geonodes_scatter, "sculpt_ops": op_sculpt_ops, "remesh": op_remesh,
       "bevel": op_bevel, "support_loops": op_support_loops, "inset": op_inset, "panel_line": op_panel_line,
       "trim_strip": op_trim_strip, "solidify": op_solidify, "bridge": op_bridge, "kit_place": op_kit_place}


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
    high = None
    times, stage_dir, levels = [], job.get("stage_dir"), int(job.get("preview_levels", 2))
    i = -1
    try:
        for i, o in enumerate(job["ops"]):
            fn = OPS.get(o.get("op"))
            if fn is None:
                raise OpError(f"unknown op {o.get('op')!r}")
            say("FORM_STEP", f"{i + 1}/{len(job['ops'])} {o['op']}")
            t0 = time.perf_counter()
            if o.get("high_only"):                 # detail for the bake source: a copy of the finished cage takes it
                if high is None:
                    high = high_object(ob)
                target = high
            else:
                target = ob
            fn(target, o)
            canonical(target)
            dt = time.perf_counter() - t0
            if not len(target.data.polygons):
                raise OpError("the cage has no faces left")
            ts = time.perf_counter()
            if stage_dir:
                write_stage(target, f"{stage_dir}/stage_{i:03d}.bin", i, levels)
            times.append({"op": o["op"], "seconds": round(dt, 4), "stage_seconds": round(time.perf_counter() - ts, 4),
                          **({"high_only": True} if o.get("high_only") else {})})
        out = {"ok": True, "runner": RUNNER_VERSION, "blender": bpy.app.version_string, "ops": times,
               "cage": cage_data(ob)}
        if high is not None:
            out["cage"]["high"] = cage_data(high)
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
