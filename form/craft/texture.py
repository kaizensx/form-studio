"""Texture in two honest tiers.

1. B-rep textures (this module): real geometry in the CAD solid, so STEP, STL, checks and slices all carry it.
   knurl(), spiral_ribbed_body(), wrapped_ribs(), emboss_cells(). Capped at about MAX_INSTANCES (2000) separate
   texture elements, because every element is faces in the B-rep and booleans slow down with each one.

2. Mesh textures (form.craft.meshtex): fine displacement (noise, cells, hex, knurl, ribs, a heightmap) applied to the
   triangle mesh for STL, GLB and renders only. Declare them on the design:

       def mesh_texture(self, v):
           return [craft.MeshTexture("cells", amplitude=0.35, scale=4, features=["shell"])]

   Form Studio labels them "mesh texture; STEP carries the smooth body": the STEP stays the smooth CAD solid.

Rule of thumb: texture you can see across a room (grip ribs, a knurl, a spiral) is B-rep; texture you feel under a
fingertip (leather grain, a stone or carbon-like cell pattern, sand-blast) is a mesh texture.
"""
from __future__ import annotations

import math

from build123d import Align, Box, Cylinder, Plane, Pos, RegularPolygon, Rot, Solid, Spline, Vector, Wire, extrude, make_face

from ._common import attempt, need, num, one
from .surfaces import loft_sections

MAX_INSTANCES = 2000
BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)


def _cap(n: int, what: str, params):
    need(n <= MAX_INSTANCES, f"{what}: {n} texture elements is over the B-rep cap of {MAX_INSTANCES}",
         "Use a coarser pitch, or a mesh texture (form.craft.MeshTexture) for fine texture: STL, GLB and renders get it, "
         "the STEP keeps the smooth body.", params)


def _star(r_out: float, r_in: float, teeth: int, flat: float = 0.0):
    """Points of a V-tooth star around Z (teeth peaks at r_out, roots at r_in)."""
    pts = []
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        b = a + math.pi / teeth
        if flat:
            da = flat * math.pi / teeth / 2
            pts += [(r_out * math.cos(a - da), r_out * math.sin(a - da)), (r_out * math.cos(a + da), r_out * math.sin(a + da))]
        else:
            pts.append((r_out * math.cos(a), r_out * math.sin(a)))
        pts.append((r_in * math.cos(b), r_in * math.sin(b)))
    return pts


def _face(pts):
    return make_face(Wire.make_polygon([Vector(x, y, 0) for x, y in pts], close=True)).faces()[0]


def polyhedron(V, F):
    """A B-rep solid from a closed, consistently wound triangle mesh (planar faces, sewn). V: (x, y, z) points,
    F: index triples. Used for faceted textures whose exact shape is triangles (a diamond knurl)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from build123d import Shape
    sew = BRepBuilderAPI_Sewing(1e-6)
    P = [gp_Pnt(float(x), float(y), float(z)) for x, y, z in V]
    for f in F:                                        # triangles, or planar polygons (caps)
        poly = BRepBuilderAPI_MakePolygon()
        for i in f:
            poly.Add(P[i])
        poly.Close()
        sew.Add(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face())
    sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    need(ex.More(), "polyhedron: the triangles do not close into a shell", "Check that the mesh is closed.", ["mesh"])
    solid = Shape.cast(BRepBuilderAPI_MakeSolid(TopoDS.Shell(ex.Current())).Solid())
    if solid.volume < 0:
        solid = Shape.cast(solid.wrapped.Reversed())
    return solid


def _knurl_mesh(R, d, H, cols, rows, chamfer, radius_of):
    """Vertices on rows z_k, columns at angle 2 pi j / cols; each grid cell split along the diagonal that keeps the
    pyramids (or ridges) intact; star-shaped caps at both ends."""
    V = []
    for k in range(rows + 1):
        z = H * k / rows
        lim = R - d + d * min(1.0, z / chamfer, (H - z) / chamfer) if chamfer > 0 else R
        for j in range(cols):
            r = min(radius_of(j, k), lim)
            a = 2 * math.pi * j / cols
            V.append((r * math.cos(a), r * math.sin(a), z))
    idx = lambda j, k: k * cols + (j % cols)
    F = []
    for k in range(rows):
        for j in range(cols):
            a, b, c, e = idx(j, k), idx(j + 1, k), idx(j + 1, k + 1), idx(j, k + 1)
            if (j + k) % 2:                                    # split (j, k)-(j+1, k+1)
                F += [(a, b, c), (a, c, e)]
            else:                                              # split (j+1, k)-(j, k+1)
                F += [(a, b, e), (b, c, e)]
    F.append(tuple(idx(j, 0) for j in range(cols - 1, -1, -1)))          # flat star-shaped caps, one face each
    F.append(tuple(idx(j, rows) for j in range(cols)))
    return V, F


def knurl(diameter: float, height: float, pitch: float = 1.6, depth: float = 0.5, kind: str = "diamond",
          helix_angle: float = 30.0, chamfer: float = 0.6):
    """A knurled cylinder standing on z = 0 (outer diameter = diameter at the tooth tips). kind: "diamond" (pyramids
    between two opposite helical grooves, the classic knurl) or "straight" (axial V-grooves). helix_angle: degrees
    of the diamond's grooves from the axis. chamfer eases the teeth to the root
    diameter at both ends so they do not end in burrs.
    Exact faceted B-rep: a star prism (straight), or planar triangles sewn into a solid (diamond)."""
    D, H = num(diameter, "diameter", lo=4), num(height, "height", lo=1)
    p, d = num(pitch, "pitch", lo=0.6), num(depth, "depth", lo=0.1)
    need(kind in ("straight", "diamond"), f"knurl: unknown kind {kind!r}", "Use diamond or straight.", ["kind"])
    ha = num(helix_angle, "helix_angle", lo=10, hi=60)
    need(d < D / 4, "knurl: depth is over a quarter of the diameter", "Use a shallower knurl.", ["depth"])
    c = num(chamfer, "chamfer", lo=0, hi=H / 3)
    R = D / 2
    teeth = max(6, int(round(math.pi * D / p)))
    if kind == "straight":
        _cap(teeth, "knurl", ["pitch"])
        body = one(extrude(_face(_star(R, R - d, teeth, flat=0.12)), H))
        if c:
            clip = Pos(0, 0, c) * Cylinder(R + 1, H - 2 * c, align=BOTTOM)
            lo = Solid.make_cone(R - d, R + 0.01, c + 0.01)
            hi = Pos(0, 0, H - c - 0.01) * Solid.make_cone(R + 0.01, R - d, c + 0.01)
            body = attempt("knurl chamfer", [("chamfer", lambda: one(body & (clip + lo + hi)))], "Use chamfer=0.", ["chamfer"])
        return body
    ps = 2 * math.pi * R / teeth                              # pitch around the circumference
    pz = ps / math.tan(math.radians(ha))                      # pitch along the axis
    rows = max(2, int(round(H / (pz / 2))))
    cols = 2 * teeth
    _cap(teeth * rows // 2, "knurl", ["pitch", "height"])
    V, F = _knurl_mesh(R, d, H, cols, rows, c, lambda j, k: R if (j + k) % 2 else R - d)
    return attempt("knurl", [("faceted solid", lambda: polyhedron(V, F))], "Use a coarser pitch.", ["pitch"])


def spiral_ribbed_body(profile, ribs: int = 24, rib_depth: float = 2.0, twist: float = 90.0, levels: int = 14,
                       sharpness: float = 1.5, points: int = 0):
    """A body of revolution whose surface carries `ribs` spiral ribs, as ONE smooth B-spline skin (a ribbed vase, a
    lamp, a fluted knob). profile: (r, z) pairs, rising in z, r = the radius at the rib roots. The ribs turn `twist`
    degrees from bottom to top. sharpness 1 = sinusoidal flutes, 2-4 = rounded ribs with wider valleys.
    The result is a closed solid; shell it (craft.shell) for a vase."""
    pr = [(float(r), float(z)) for r, z in profile]
    need(len(pr) >= 2 and all(b[1] > a[1] for a, b in zip(pr, pr[1:])), "spiral_ribbed_body: profile must rise in z",
         "Give (r, z) pairs with increasing z.", ["profile"])
    n = num(ribs, "ribs", lo=3, hi=MAX_INSTANCES, integer=True)
    dp = num(rib_depth, "rib_depth", lo=0)
    tw = num(twist, "twist", lo=-720, hi=720)
    L = num(levels, "levels", lo=3, hi=60, integer=True)
    sh = num(sharpness, "sharpness", lo=0.5, hi=8)
    N = num(points or min(1440, max(96, 16 * n)), "points", lo=48, hi=1440, integer=True)
    need(N >= 8 * n, "spiral_ribbed_body: too few points per rib", "Raise points to at least 8 x ribs.", ["points"])
    z0, z1 = pr[0][1], pr[-1][1]
    zs = [z0 + (z1 - z0) * i / (L - 1) for i in range(L)]
    rs = Spline(*[Vector(r, 0, z) for r, z in pr]) if len(pr) > 2 else None

    def r_at(z):
        if rs is None:
            u = (z - z0) / (z1 - z0)
            return pr[0][0] + (pr[1][0] - pr[0][0]) * u
        # the profile spline is parameterised by length; find the point at height z by bisection
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            if rs.position_at(mid).Z < z:
                lo = mid
            else:
                hi = mid
        return rs.position_at((lo + hi) / 2).X

    secs = []
    for z in zs:
        R = r_at(z)
        need(R > dp + 0.5, f"spiral_ribbed_body: radius {R:.1f} at z = {z:.1f} is too small for {dp:g} mm ribs",
             "Increase the radius or reduce rib_depth.", ["profile", "rib_depth"])
        ph = math.radians(tw) * (z - z0) / (z1 - z0)
        pts = []
        for i in range(N):                       # the section turns with the twist, so loft lines follow the ribs
            a = 2 * math.pi * i / N
            c = 0.5 + 0.5 * math.cos(n * a)
            r = R + dp * c ** sh
            pts.append(Vector(r * math.cos(a + ph), r * math.sin(a + ph), z))
        secs.append(make_face(Wire([Spline(*pts, periodic=True)])).faces()[0])
    return loft_sections(secs)


def wrapped_ribs(radius: float, height: float, count: int = 12, rib_w: float = 2.0, rib_h: float = 1.0,
                 twist: float = 0.0, z0: float = 0.0):
    """count ribs standing on a cylinder of `radius` (fuse them onto it), each rib_w wide and rib_h proud, running
    from z0 for `height`, optionally twisted (degrees over the height)."""
    R, H = num(radius, "radius", lo=2), num(height, "height", lo=0.5)
    n = num(count, "count", lo=1, integer=True)
    _cap(n, "wrapped_ribs", ["count"])
    w, h = num(rib_w, "rib_w", lo=0.3), num(rib_h, "rib_h", lo=0.1)
    tw = num(twist, "twist", lo=-720, hi=720)
    sec = _face([(R - 0.3, -w / 2), (R + h, -w / 2 * 0.7), (R + h, w / 2 * 0.7), (R - 0.3, w / 2)])
    ribs = []
    for i in range(n):
        f = Rot(0, 0, 360 * i / n) * sec
        r = Solid.extrude_linear_with_rotation(f, (0, 0, 0), (0, 0, H), tw) if tw else extrude(f, H)
        ribs.append(Pos(0, 0, z0) * r)
    out = ribs[0].fuse(*ribs[1:]) if len(ribs) > 1 else ribs[0]
    return one(out.clean() if hasattr(out, "clean") else out)


def emboss_cells(w: float, d: float, cell: float = 6.0, height: float = 0.6, kind: str = "hex", gap: float = 0.8,
                 margin: float = 0.0, plane: Plane = Plane.XY):
    """Raised cells covering a w x d region centred on the plane's origin, standing `height` proud of it: kind "hex"
    (hexagon tiles), "diamond" (rotated squares), "dots" (round studs) or "pyramids" (four-sided, a grip pattern).
    gap is the groove between cells. Fuse the result onto a flat face (or place it with plane=...)."""
    W, D = num(w, "w", positive=True), num(d, "d", positive=True)
    c, h, g = num(cell, "cell", lo=1), num(height, "height", lo=0.1), num(gap, "gap", lo=0.2)
    need(kind in ("hex", "diamond", "dots", "pyramids"), f"emboss_cells: unknown kind {kind!r}",
         "Use hex, diamond, dots or pyramids.", ["kind"])
    need(g < c, "emboss_cells: gap is wider than a cell", "Use a smaller gap.", ["gap"])
    m = num(margin, "margin", lo=0)
    pts = []
    if kind == "hex":
        px, py = c, c * math.sqrt(3) / 2
        rows = int((D - 2 * m) / py) + 1
        cols = int((W - 2 * m) / px) + 1
        for j in range(rows):
            for i in range(cols):
                x = -W / 2 + m + c / 2 + i * px + (px / 2 if j % 2 else 0)
                y = -D / 2 + m + c / 2 + j * py
                if x + c / 2 <= W / 2 - m + 1e-9 and y + c / 2 <= D / 2 - m + 1e-9:
                    pts.append((x, y))
    else:
        pitch = c
        cols, rows = int((W - 2 * m) / pitch), int((D - 2 * m) / pitch)
        for j in range(rows):
            for i in range(cols):
                pts.append((-W / 2 + m + pitch / 2 + i * pitch, -D / 2 + m + pitch / 2 + j * pitch))
    need(bool(pts), "emboss_cells: no cell fits the region", "Use a smaller cell.", ["cell"])
    _cap(len(pts), "emboss_cells", ["cell"])
    s = c - g
    if kind == "hex":
        unit = extrude(RegularPolygon(s / 2, 6, major_radius=False), h)
    elif kind == "diamond":
        unit = Rot(0, 0, 45) * Box(s / math.sqrt(2), s / math.sqrt(2), h, align=BOTTOM)
    elif kind == "dots":
        unit = Cylinder(s / 2, h, align=BOTTOM)
    else:
        unit = Solid.make_loft([Wire.make_polygon([Vector(-s / 2, -s / 2, 0), Vector(s / 2, -s / 2, 0),
                                                   Vector(s / 2, s / 2, 0), Vector(-s / 2, s / 2, 0)], close=True),
                                Wire.make_polygon([Vector(-s / 10, -s / 10, h), Vector(s / 10, -s / 10, h),
                                                   Vector(s / 10, s / 10, h), Vector(-s / 10, s / 10, h)], close=True)])
    cells = [Pos(x, y, 0) * unit for x, y in pts]
    out = cells[0].fuse(*cells[1:]) if len(cells) > 1 else cells[0]
    return plane * one(out)
