"""Form Studio's LOD decimation, run inside Blender by the game-asset runner (form/adapters/blender_game.py calls
decimate_to from its own decimate_to, passing its helpers). Like the runner it only reads numbers it is given: no
network, no processes, no files.

A plain edge collapse spends its budget evenly, so a round tyre turns polygonal and a thin rim or a crisp border
melts first. Here, in order:

    1. planar: Decimate (planar, 0.5 degrees) dissolves flat areas into larger faces first, delimited by seams, sharp
       edges, materials and UV islands, then triangulates. Flats lose nothing and free triangles for curves.
    2. a vertex group FormKeep, weight per point: 1 on borders (open edges), UV seams, sharp or creased edges, material
       boundaries and edges with a dihedral angle of 30 degrees or more; 0.6 on the silhouette from 8 fixed views (an
       edge whose two faces turn one towards the view and one away); else by curvature (the sharpest dihedral at the
       point, 0 at flat up to 0.5 at 30 degrees), so round parts keep their radial segments
    3. Decimate (collapse) three ways: even, and with FormKeep holding its points at factors 1 and 4 (inverted: the
       modifier collapses where its group is), each with the ratio corrected until the triangles are at most the budget
       and as close under it as a few tries get. Each is measured against the source (the larger one-sided distance,
       every point and face centre to the other's surface, Blender's BVH tree); the most held one within 1.25 x the
       closest one's distance is kept. Holding features wins on mild reductions (LOD1, LOD2); on severe ones holding
       everything at once makes the unheld small parts collapse instead, and the even collapse is kept

Returns (object, iterations), as the runner's own decimate_to.
"""
import math

import bmesh
import bpy
import numpy as np

KEEP = "FormKeep"
FLAT_DEG = 0.5
FEATURE_DEG = 30.0
SILHOUETTE_W = 0.6
CURVE_W = 0.5
HOLD_SLACK = 1.25                # a held collapse is kept when its deviation is at most 1.25 x the closest one's
FACTORS = (0.0, 1.0, 4.0)        # Decimate's vertex group factor per try: 0 an even collapse, then FormKeep holding


def _views():
    out = []
    for az, el in ((0, 0), (45, 0), (90, 0), (135, 0), (30, 40), (150, 40), (270, 40), (0, 90)):
        a, e = math.radians(az), math.radians(el)
        out.append((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
    return np.array(out)


def keep_weights(ob):
    """FormKeep's weight per point (see the module's docstring) and how many points each rule held."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    crease = bm.edges.layers.float.get("crease_edge")
    nv = len(bm.verts)
    w = np.zeros(nv)
    fn = np.array([f.normal[:] for f in bm.faces]) if bm.faces else np.zeros((0, 3))
    fmat = np.array([f.material_index for f in bm.faces], dtype=np.int64)
    views = _views()
    feat_deg = math.radians(FEATURE_DEG)
    counts = {"feature": 0, "silhouette": 0, "curved": 0}
    for e in bm.edges:
        fs = e.link_faces
        a, b = e.verts[0].index, e.verts[1].index
        if len(fs) != 2:
            w[a] = w[b] = 1.0
            continue
        n0, n1 = fn[fs[0].index], fn[fs[1].index]
        ang = math.acos(max(-1.0, min(1.0, float(n0 @ n1))))
        hard = (e.seam or not e.smooth or ang >= feat_deg or fmat[fs[0].index] != fmat[fs[1].index]
                or (crease is not None and e[crease] >= 0.5))
        if hard:
            w[a] = w[b] = 1.0
            continue
        s0, s1 = views @ n0, views @ n1
        if np.any(s0 * s1 < 0):
            w[a] = max(w[a], SILHOUETTE_W)
            w[b] = max(w[b], SILHOUETTE_W)
        c = CURVE_W * min(ang / feat_deg, 1.0)
        w[a] = max(w[a], c)
        w[b] = max(w[b], c)
    bm.free()
    counts["feature"] = int((w >= 1.0).sum())
    counts["silhouette"] = int(((w >= SILHOUETTE_W) & (w < 1.0)).sum())
    counts["curved"] = int(((w > 0) & (w < SILHOUETTE_W)).sum())
    g = ob.vertex_groups.get(KEEP) or ob.vertex_groups.new(name=KEEP)
    for k in np.unique(np.round(w, 3)):
        idx = np.nonzero(np.round(w, 3) == k)[0].tolist()
        if idx and k > 0:
            g.add(idx, float(k), "REPLACE")
    return w, counts


def planar(ob, rt):
    """Flat areas dissolved (delimited by seams, sharp edges, materials and UVs), then triangulated."""
    m = ob.modifiers.new("FormPlanar", "DECIMATE")
    m.decimate_type = "DISSOLVE"
    m.angle_limit = math.radians(FLAT_DEG)
    m.use_dissolve_boundaries = False
    try:
        m.delimit = {"SEAM", "SHARP", "MATERIAL", "UV"}
    except (TypeError, AttributeError):
        pass
    rt["apply_modifiers"](ob)
    t = ob.modifiers.new("FormTri", "TRIANGULATE")
    t.quad_method = "BEAUTY"
    t.ngon_method = "BEAUTY"
    rt["apply_modifiers"](ob)
    return ob


def collapse(base, name, budget, rt, factor):
    """base collapsed to at most `budget` triangles, FormKeep holding points with `factor` (0: an even collapse), the
    ratio corrected until the count is as close under the budget as a few tries get. (object or None, tries)"""
    tris, copy_object = rt["tris"], rt["copy_object"]
    have = tris(base)
    target = budget * 0.995
    ratio = target / have
    best, it = None, 0
    for it in range(1, 8):
        ob = copy_object(base, name + "_try")
        m = ob.modifiers.new("FormDecimate", "DECIMATE")
        m.decimate_type = "COLLAPSE"
        m.ratio = max(min(ratio, 1.0), 1e-5)
        m.use_collapse_triangulate = True
        if factor > 0:
            m.vertex_group = KEEP
            m.vertex_group_factor = factor
            m.invert_vertex_group = True       # Decimate collapses where the group is; inverted, FormKeep holds
        rt["apply_modifiers"](ob)
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
    return best, it


def _points(ob, centres=False):
    me = ob.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    if centres:
        c = np.empty(len(me.polygons) * 3)
        me.polygons.foreach_get("center", c)
        co = np.concatenate([co, c.reshape(-1, 3)])
    return co


def _tree(ob):
    from mathutils.bvhtree import BVHTree
    return BVHTree.FromPolygons([tuple(v.co) for v in ob.data.vertices], [tuple(p.vertices) for p in ob.data.polygons])


def deviation(a, b):
    """The larger of the two one-sided distances between a's and b's surfaces: every point (and face centre) of each
    to the other's nearest surface point (Blender's BVH tree)."""
    worst = 0.0
    for src, dst in ((a, b), (b, a)):
        tree = _tree(dst)
        for p in _points(src, centres=True):
            hit = tree.find_nearest(tuple(p))
            if hit[3] is not None and hit[3] > worst:
                worst = hit[3]
    return worst


def decimate_to(src, name, budget, rt):
    """src decimated to at most `budget` triangles: planar first, then collapses with FormKeep holding at each of
    FACTORS; the one closest to src (deviation) is kept."""
    copy_object = rt["copy_object"]
    base = copy_object(src, name + "_lodsrc")
    planar(base, rt)
    if rt["tris"](base) <= budget:
        base.name = base.data.name = name
        return base, 1
    keep_weights(base)
    tried, tries = [], 0
    for factor in FACTORS:
        ob, it = collapse(base, name, budget, rt, factor)
        tries += it
        if ob is not None:
            tried.append((factor, deviation(src, ob), ob))
    bpy.data.objects.remove(base)
    if not tried:
        raise rt["JobError"](f"decimation could not reach {budget} triangles")
    least = min(d for _f, d, _o in tried)
    # the most held collapse whose surface is about as close as the closest one (features cost little distance)
    factor, dev, best = max((t for t in tried if t[1] <= least * HOLD_SLACK + 1e-9), key=lambda t: t[0])
    for _f, _d, o in tried:
        if o is not best:
            bpy.data.objects.remove(o)
    rt["say"]("FORM_LOD", f"{name}: hold factor {factor:g}, deviation {dev:.4g} mm (closest {least:.4g} mm)")
    for g in list(best.vertex_groups):
        best.vertex_groups.remove(g)
    best.name = best.data.name = name
    return best, tries
