"""Structure: ribs, gussets, boss arrays and strut lattices. Shapes stand on z = 0 and are fused into a body.

    from form.craft import structure as stc
    body = body + stc.rib_grid(80, 50, height=8, pitch=12, t=1.6)           # a stiffening grid under a plate
    body = body + stc.gusset(20, 20, t=3)                                   # in the XZ corner of a bracket
    body = stc.boss_array(body, [(10, 10), (70, 10)], outer_d=7, height=6, hole_d=2.5, top_z=3)

Rules of thumb used in the defaults (heuristic): ribs 50-70 % of the wall they stiffen, height <= 3 x wall, draft for
moulding only (printing needs none); gussets at about 45 deg; bosses at least 2 x hole diameter, joined to a wall by a
rib rather than standing alone.
"""
from __future__ import annotations

import math

from build123d import Align, Box, Cylinder, Plane, Pos, Rot, Wire, extrude, make_face

from ._common import fail, need, num, one

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
MAX_STRUTS = 2000


def rib(length: float, height: float, t: float = 1.6, angle: float = 0.0, at=(0.0, 0.0), draft: float = 0.0,
        chamfer_top: bool = True):
    """One rib centred at `at`, running along X turned by angle (deg) about Z. draft (deg) tapers the sides (moulding)."""
    L, H, T = num(length, "length", positive=True), num(height, "height", positive=True), num(t, "t", positive=True)
    d = num(draft, "draft", lo=0, hi=10)
    top = max(T - 2 * H * math.tan(math.radians(d)), 0.4 * T)
    pts = [(-T / 2, 0), (T / 2, 0), (top / 2, H), (-top / 2, H)]
    face = make_face(Wire.make_polygon([Plane.YZ.from_local_coords((y, z, 0)) for y, z in pts], close=True)).faces()[0]
    r = Pos(-L / 2, 0, 0) * extrude(face, L)
    return Pos(at[0], at[1], 0) * Rot(0, 0, angle) * one(r)


def rib_grid(w: float, d: float, height: float = 6, pitch: float = 12, t: float = 1.6, angle: float = 0.0,
             border: bool = True):
    """A rectangular grid of ribs over a w x d region centred on the origin (pitch both ways); border adds the frame."""
    W, D, H = num(w, "w", positive=True), num(d, "d", positive=True), num(height, "height", positive=True)
    P, T = num(pitch, "pitch", lo=2), num(t, "t", positive=True)
    need(P > 2 * T, "rib_grid: pitch is under twice the rib thickness", "Use a larger pitch or thinner ribs.", ["pitch", "t"])
    nx, ny = max(1, int(W / P)), max(1, int(D / P))
    need(nx + ny < 400, "rib_grid: more than 400 ribs", "Use a larger pitch.", ["pitch"])
    g = None
    for i in range(1, nx):
        x = -W / 2 + i * W / nx
        r = Pos(x, 0, 0) * Box(T, D, H, align=BOTTOM)
        g = r if g is None else g + r
    for j in range(1, ny):
        y = -D / 2 + j * D / ny
        r = Pos(0, y, 0) * Box(W, T, H, align=BOTTOM)
        g = r if g is None else g + r
    if border:
        frame = Box(W, D, H, align=BOTTOM) - Box(W - 2 * T, D - 2 * T, H + 1, align=BOTTOM)
        g = frame if g is None else g + frame
    need(g is not None, "rib_grid: the region holds no rib", "Use a smaller pitch.", ["pitch"])
    return Rot(0, 0, angle) * one(g)


def gusset(leg_x: float, leg_z: float, t: float = 3.0, at=(0.0, 0.0, 0.0), toward: str = "+x", y: float = 0.0):
    """A triangular gusset for the inside corner between a floor (z = 0) and a wall (x = 0): legs along +X and +Z,
    thickness t across Y, centred on y. toward="-x" mirrors it."""
    a, b, T = num(leg_x, "leg_x", positive=True), num(leg_z, "leg_z", positive=True), num(t, "t", positive=True)
    s = -1 if toward == "-x" else 1
    if toward not in ("+x", "-x"):
        raise fail(f"gusset: toward must be +x or -x (got {toward!r})", "", ["toward"])
    pts = [(0, 0), (s * a, 0), (0, b)]
    face = make_face(Wire.make_polygon([Plane.XZ.from_local_coords((x, z, 0)) for x, z in pts], close=True)).faces()[0]
    g = Pos(0, T / 2, 0) * extrude(face, T)
    return Pos(at[0], at[1] + y, at[2]) * one(g)


def boss_array(body, points, outer_d: float = 7, height: float = 6, hole_d: float = 2.5, top_z: float = 0.0,
               hole_depth: float | None = None, base_fillet: float = 0.6):
    """Fuse cylindrical bosses at the (x, y) points rising from top_z, then bore each from its top. Returns the body."""
    D, H, h = num(outer_d, "outer_d", positive=True), num(height, "height", positive=True), num(hole_d, "hole_d", lo=0)
    need(h <= D - 1.6, "boss_array: hole leaves under 0.8 mm of boss wall", "Use a larger outer_d.", ["outer_d", "hole_d"])
    pts = [(float(p[0]), float(p[1])) for p in points]
    need(0 < len(pts) <= 200, "boss_array: give 1-200 points", "", ["points"])
    out = body
    for x, y in pts:
        out = out + Pos(x, y, top_z) * Cylinder(D / 2, H, align=BOTTOM)
    out = one(out)
    if base_fillet:
        from .surfaces import safe_fillet
        edges = [e for e in out.edges() if e.geom_type.name == "CIRCLE" and abs(e.center().Z - top_z) < 1e-3
                 and any(math.hypot(e.center().X - x, e.center().Y - y) < 1e-3 for x, y in pts)
                 and abs(e.radius - D / 2) < 1e-3]
        out = safe_fillet(out, edges, base_fillet)
    if h:
        dep = H + top_z if hole_depth is None else num(hole_depth, "hole_depth", positive=True)
        for x, y in pts:
            out = out - Pos(x, y, top_z + H - dep) * Cylinder(h / 2, dep + 0.2, align=BOTTOM)
    return one(out)


def lattice(w: float, d: float, h: float, cell: float = 8, strut: float = 1.2, kind: str = "bcc"):
    """A strut lattice filling a w x d x h box standing on z = 0: "cubic" (edges of each cell) or "bcc" (cubic plus
    the four body diagonals). Struts are square-section bars; capped at 2000 struts (B-rep booleans get slow)."""
    W, D, H = num(w, "w", positive=True), num(d, "d", positive=True), num(h, "h", positive=True)
    c, s = num(cell, "cell", lo=2), num(strut, "strut", lo=0.4)
    need(s < c / 2, "lattice: struts are thicker than half a cell", "Use thinner struts or bigger cells.", ["strut", "cell"])
    nx, ny, nz = max(1, round(W / c)), max(1, round(D / c)), max(1, round(H / c))
    cx, cy, cz = W / nx, D / ny, H / nz
    count = (nx * (ny + 1) * (nz + 1) + ny * (nx + 1) * (nz + 1) + nz * (nx + 1) * (ny + 1)
             + (4 * nx * ny * nz if kind == "bcc" else 0))
    need(kind in ("cubic", "bcc"), f"lattice: unknown kind {kind!r}", "Use cubic or bcc.", ["kind"])
    need(count <= MAX_STRUTS, f"lattice: {count} struts is over the {MAX_STRUTS} cap", "Use bigger cells, or a mesh texture "
         "for the look of a lattice.", ["cell"])
    bars = []
    x0, y0 = -W / 2, -D / 2
    for k in range(nz + 1):
        for j in range(ny + 1):
            bars.append(Pos(0, y0 + j * cy, k * cz) * Box(W + s, s, s))
        for i in range(nx + 1):
            bars.append(Pos(x0 + i * cx, 0, k * cz) * Box(s, D + s, s))
    for i in range(nx + 1):
        for j in range(ny + 1):
            bars.append(Pos(x0 + i * cx, y0 + j * cy, H / 2) * Box(s, s, H + s))
    if kind == "bcc":
        L = math.sqrt(cx * cx + cy * cy + cz * cz)
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    ctr = (x0 + (i + 0.5) * cx, y0 + (j + 0.5) * cy, (k + 0.5) * cz)
                    for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                        v = (sx * cx, sy * cy, cz)
                        yaw = math.degrees(math.atan2(v[1], v[0]))
                        pitch = math.degrees(math.acos(v[2] / L))
                        bars.append(Pos(*ctr) * Rot(0, 0, yaw) * Rot(0, pitch, 0) * Box(s, s, L))
    body = bars[0].fuse(*bars[1:]) if len(bars) > 1 else bars[0]
    clip = Box(W + s, D + s, H + s / 2, align=BOTTOM)
    return one(body & clip)
