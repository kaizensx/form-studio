"""Organic bodies from stacked sections: domes and helmet shells, grips and handles.

The method is the one industrial designers use in surfacing tools: describe the body by a few horizontal (or
along-axis) sections, each a superellipse with its own half-widths, squareness and offset, and loft a smooth B-spline
skin through them. Every section is a design decision you can name ("the crown sits 12 mm behind centre", "the
grip is 30 % squarer at the palm"), so the shape stays editable.

    from form.craft import organic as org
    dome = org.section_body([dict(z=0, a=60, b=48, n=2.2), dict(z=40, a=55, b=44, n=2.3), dict(z=80, a=30, b=25)],
                            tip=(0, 0, 92))
    grip = org.grip(length=110, d_max=34, d_min=26, flat=0.82, finger_grooves=3)
"""
from __future__ import annotations

import math

from build123d import Vertex, scale

from ._common import attempt, need, note, num, one, pts2
from .surfaces import loft_sections, revolve_profile, superellipse_face, sweep_spline


def section_body(sections: list[dict], tip=None, count: int = 64):
    """Loft through sections [{z, a, b, n=2.0, cx=0, cy=0, squash=0, rotate=0, seam=0}, ...] in increasing z.
    tip: (x, y, z) of a closing point above the last section (a dome's crown), or None to end flat.
    seam: the angle (degrees) where each section starts; the loft's seam line runs there (180 hides it at the back).
    Give every section the same seam, or the loft twists."""
    need(len(sections) >= 2, "section_body needs at least 2 sections", "Add sections.", ["sections"])
    zs = [num(s.get("z"), "z") for s in sections]
    need(all(b > a for a, b in zip(zs, zs[1:])), "section_body: sections must rise in z", "Sort the sections by z.",
         ["sections"])
    faces = [superellipse_face(s["a"], s["b"], s.get("n", 2.0), z=s["z"], center=(s.get("cx", 0.0), s.get("cy", 0.0)),
                               count=count, rotate=s.get("rotate", 0.0), squash_front=s.get("squash", 0.0), seam=s.get("seam", 0.0))
             for s in sections]
    if tip is not None:
        faces.append(Vertex(*map(float, tip)))
    return loft_sections(faces)


def section_shell(sections: list[dict], wall: float, tip=None, open_bottom: bool = True, count: int = 64,
                  open_top: bool = False):
    """A hollow body from sections: the outer loft minus an inner loft whose sections are inset by `wall` (half-widths
    reduced, the tip lowered by wall). Robust where an offset of a lofted dome fails (a crown point is a singular
    point for offsets). The wall is `wall` measured in plan and at the crown; on steep slopes it is close to it.
    open_bottom leaves the lowest section open; open_top (no tip) the highest (a lamp shade, a sleeve).
    Returns (outer, hollow)."""
    outer = section_body(sections, tip=tip, count=count)
    inner = inset_body(sections, wall, tip=tip, open_bottom=open_bottom, count=count, open_top=open_top)
    hollow = attempt("section_shell", [("outer - inset inner", lambda: one(outer - inner))],
                     "Use a thinner wall; the inset sections cross the outer form.", ["wall"])
    return outer, hollow


def inset_body(sections: list[dict], wall: float, tip=None, open_bottom: bool = True, count: int = 64,
               open_top: bool = False):
    """The inner body section_shell subtracts: the sections inset by `wall` along the surface normal (and past the
    open ends). Use it when a feature must change the outside before hollowing, so the wall follows it:
        outer = craft.section_body(secs, tip); inner = craft.inset_body(secs, 2, tip)
        outer = craft.safe_fillet(outer - scoop, scoop_edges, 3)      # shape and round the OUTSIDE first
        shell = outer - (inner - grown_scoop)                         # the inside follows, the wall stays even"""
    t = num(wall, "wall", lo=0.4)
    for s in sections:
        need(s["a"] - t > 1 and s["b"] - t > 1, f"section_shell: the section at z = {s['z']:g} is too small for a "
             f"{t:g} mm wall", "Use a thinner wall or larger sections.", ["wall"])
    # along the surface normal, so the wall is t thick on a flat crown too, not only on the steep sides
    ins = _normal_offset(sections, -t, tip)
    if open_bottom:
        ins.insert(0, {**ins[0], "z": ins[0]["z"] - 1.0})
    else:
        ins[0] = {**ins[0], "z": ins[0]["z"] + t}
    if open_top and tip is None:
        ins.append({**ins[-1], "z": ins[-1]["z"] + 1.0})
    elif tip is None:
        ins[-1] = {**ins[-1], "z": ins[-1]["z"] - t}
    itip = None if tip is None else (tip[0], tip[1], tip[2] - t)
    return section_body(ins, tip=itip, count=count)


def _normal_offset(sections: list[dict], d: float, tip=None) -> list[dict]:
    """Each section moved along the body's surface normal in its (r, z) plane by d (> 0 outward): half-widths change
    by d / N and the height by -d * slope / N, where slope = d(half-width)/dz from the neighbours and N = sqrt(1 +
    slope^2). Near a crown, where the skin is almost flat, a plan-only offset would barely move the surface; this one
    moves it by d everywhere. The lowest section moves in plan only (an open edge stays where it is cut); sections
    that would cross their neighbour are dropped."""
    zs = [x["z"] for x in sections]
    rs = [(x["a"] + x["b"]) / 2 for x in sections]
    if tip is not None:
        zs.append(tip[2])
        rs.append(0.0)
    out = []
    for i, x in enumerate(sections):
        j0, j1 = max(0, i - 1), min(len(zs) - 1, i + 1)
        dz = zs[j1] - zs[j0]
        slope = (rs[j1] - rs[j0]) / dz if (i and dz > 1e-9) else 0.0
        N = math.sqrt(1 + slope * slope)
        y = {**x, "a": x["a"] + d / N, "b": x["b"] + d / N, "z": x["z"] - d * slope / N}
        if out and y["z"] <= out[-1]["z"] + 0.05:
            continue
        out.append(y)
    return out


def inflate(sections: list[dict], amount: float, tip=None, normal: bool = False):
    """The sections grown (or shrunk, amount < 0) by amount, and the tip moved up by it: a near-offset of a section
    body that never fails. Use it for pads and ridges that follow a lofted surface:
        secs2, tip2 = craft.inflate(secs, 4, tip); pad = (craft.section_body(secs2, tip2) & footprint) - inside
    In plan by default: every section keeps its height, so bodies grown by different amounts share their section
    heights and booleans between them stay simple. normal=True offsets along the surface normal instead (the true
    distance on a flat crown; inset_body hollows that way)."""
    a = num(amount, "amount")
    out = _normal_offset(sections, a, tip) if normal else [{**s, "a": s["a"] + a, "b": s["b"] + a} for s in sections]
    need(len(out) >= 2 and all(s["a"] > 0.5 and s["b"] > 0.5 for s in out), "inflate: a section shrank to nothing",
         "Use a smaller amount.", ["amount"])
    return out, (None if tip is None else (tip[0], tip[1], tip[2] + a))


def dome_sections(length: float, width: float, height: float, levels: int = 9, crown_back: float = 0.0,
                  squash_front: float = 0.12, n_base: float = 2.15, n_top: float = 2.0, z0: float = 0.0,
                  power: float = 2.2, seam: float = 0.0) -> tuple[list[dict], tuple]:
    """Sections of a smooth dome (a head form, a mouse, a shell): length along X, width along Y, height above z0.
    Each level follows a superellipse in elevation, (z/h)^p + (r/R)^p = 1, so the dome meets its crown tangent.
    crown_back moves the crown toward -X (a helmet's crown sits behind the forehead). seam: where the loft's seam
    line runs (0 = down the nose, +X; 180 = the back). Keep it away from where you cut or add features: a boolean
    across a seam is where OCCT fails first (a spoiler fused across a seam at 180 comes back empty)."""
    L, W, H = num(length, "length", positive=True), num(width, "width", positive=True), num(height, "height", positive=True)
    n = num(levels, "levels", lo=3, hi=30, integer=True)
    p = num(power, "power", lo=1.5, hi=6)
    out = []
    for i in range(n):
        u = i / n                                                    # 0 at the base, < 1 at the last section
        z = z0 + H * (1 - (1 - u) ** 1.6) * 0.985                   # denser sections near the crown
        k = (1 - ((z - z0) / H) ** p) ** (1 / p)
        t = (z - z0) / H
        out.append({"z": z, "a": max(L / 2 * k, 0.5), "b": max(W / 2 * k, 0.5), "n": n_base + (n_top - n_base) * t,
                    "cx": -crown_back * t ** 1.5, "squash": squash_front * (1 - t), "seam": seam})
    return out, (-crown_back, 0.0, z0 + H)


def helmet_shell(length: float = 270, width: float = 215, height: float = 165, wall: float = 3.0, skirt: float = 95,
                 crown_back: float = 14, squash_front: float = 0.1):
    """A closed helmet outer form (the dome continued down by `skirt` as a near-vertical wall) and its hollow shell.
    Returns (outer_solid, hollow_shell). Cut the eye port, neck and vents from the shell afterwards.
    The base of the skirt is at z = 0, the crown at skirt + height."""
    t = num(wall, "wall", lo=0.8)
    secs, tip = helmet_sections(length, width, height, skirt, crown_back, squash_front)
    return section_shell(secs, t, tip=tip)


def helmet_sections(length: float = 270, width: float = 215, height: float = 165, skirt: float = 95,
                    crown_back: float = 14, squash_front: float = 0.1) -> tuple[list[dict], tuple]:
    """The sections and crown tip helmet_shell lofts, for everything that must follow the same surface:
        secs, tip = craft.helmet_sections(270, 215, 165, 95)
        visor_out, tip2 = craft.inflate(secs, 4, tip)       # a visor band 4 mm proud of the shell
        visor = (craft.section_body(visor_out, tip2) - craft.section_body(*craft.inflate(secs, 1.2, tip))) & window"""
    L, W, H, S = (num(x, nm, positive=True) for x, nm in ((length, "length"), (width, "width"), (height, "height"), (skirt, "skirt")))
    secs, tip = dome_sections(L, W, H, levels=9, crown_back=crown_back, squash_front=squash_front, z0=S)
    base = dict(secs[0])
    low = [{**base, "z": 0.0, "a": base["a"] * 0.93, "b": base["b"] * 0.95, "squash": squash_front * 0.9},
           {**base, "z": S * 0.55, "a": base["a"] * 0.985, "b": base["b"] * 0.99}]
    return low + secs, tip


def grip(length: float = 110, d_max: float = 34, d_min: float = 26, flat: float = 0.85, finger_grooves: int = 0,
         groove_depth: float = 1.2, end_r: float = 4.0):
    """A handle grip along Z from z = 0: a B-spline profile that swells to d_max at 40 % of its length, eases to d_min
    at the ends, with optional finger grooves; flat < 1 squashes the section along Y into an oval that resists turning
    in the hand. Ends are rounded by end_r."""
    L, D1, D0 = num(length, "length", lo=20), num(d_max, "d_max", lo=8), num(d_min, "d_min", lo=6)
    need(D1 >= D0, "grip: d_max must be at least d_min", "Swap them.", ["d_max", "d_min"])
    fl = num(flat, "flat", lo=0.5, hi=1.0)
    g = num(finger_grooves, "finger_grooves", lo=0, hi=5, integer=True)
    gd = num(groove_depth, "groove_depth", lo=0, hi=4)
    er = num(end_r, "end_r", lo=0, hi=D0 / 2 - 0.5)
    N = 40
    K = math.log(0.5) / math.log(0.4)
    pts = []
    for i in range(N + 1):
        z = L * i / N
        u = z / L
        bulge = math.sin(math.pi * u ** K)                       # 0 at both ends, 1 at 40 % of the length
        r = D0 / 2 + (D1 - D0) / 2 * bulge
        if g:
            zone = (u - 0.12) / 0.6
            if 0 <= zone <= 1:
                r -= gd * max(0.0, math.sin(math.pi * zone * g)) ** 2
        pts.append((r, z))
    if er:
        pts[0] = (pts[0][0] - er * 0.6, 0.0)
        pts[-1] = (pts[-1][0] - er * 0.6, L)
    body = revolve_profile(pts, spline=True)
    if fl < 0.999:
        body = attempt("grip flatten", [("scale", lambda: one(scale(body, (1.0, fl, 1.0))))],
                       "Use flat closer to 1.", ["flat"])
    if er:
        from .surfaces import safe_fillet
        edges = [e for e in body.edges() if abs(e.center().Z) < 1e-3 or abs(e.center().Z - L) < 1e-3]
        body = safe_fillet(body, edges, er)
    return body


def handle(span: float = 100, rise: float = 32, section_w: float = 22, section_h: float = 16, n: float = 2.6,
           foot: float = 6):
    """A D-shaped pull handle: a superellipse section swept along a smooth arch from (-span/2, 0, 0) over to
    (span/2, 0, 0), peaking at z = rise, with the feet sunk `foot` mm below z = 0 to fuse into the part."""
    S, R = num(span, "span", lo=20), num(rise, "rise", lo=section_h / 2 + 2)
    w, h = num(section_w, "section_w", lo=4), num(section_h, "section_h", lo=4)
    f = num(foot, "foot", lo=0)
    path = [(-S / 2, 0, -f), (-S / 2, 0, R * 0.55), (-S * 0.3, 0, R * 0.98), (0, 0, R), (S * 0.3, 0, R * 0.98),
            (S / 2, 0, R * 0.55), (S / 2, 0, -f)]
    prof = superellipse_face(h / 2, w / 2, n)
    return sweep_spline(prof, path)


# ---- guide curves and silhouette-driven sections ------------------------------------------------------------------
#
# A product's form is decided in three views long before it is surfaced: the side silhouette (where the front and the
# back are at each height), the front silhouette (how wide it is at each height) and the plan shape of each section.
# profile_sections() turns those guide curves into the stacked sections section_body lofts, so the silhouette you
# drew is the silhouette you get. The whole body is then one B-spline face: curvature-continuous (C2) inside, so the
# only ways it can go wrong are wiggles and folds, which loft_report() measures.

def curve(knots, name: str = "curve", end_slope: float | None = None):
    """A smooth function through (t, value) knots: a C2 cubic spline (scipy CubicSpline), held flat outside the knots.
    A single number is a constant. end_slope fixes the slope at the last knot (0 makes a guide meet a dome above it
    with a common tangent)."""
    if isinstance(knots, (int, float)):
        c = float(knots)
        return lambda t: c
    pts = sorted(pts2(knots, name, 2))
    ts = [p[0] for p in pts]
    need(all(b > a for a, b in zip(ts, ts[1:])), f"{name}: knots need distinct positions", "Remove repeated knots.", [name])
    if len(pts) == 2 and end_slope is None:
        (t0, v0), (t1, v1) = pts
        return lambda t: v0 + (v1 - v0) * (min(max(float(t), t0), t1) - t0) / (t1 - t0)
    from scipy.interpolate import CubicSpline
    if end_slope is None:
        bc = "not-a-knot" if len(pts) >= 4 else "natural"
    else:
        bc = ("not-a-knot", (1, float(end_slope))) if len(pts) >= 4 else ((2, 0.0), (1, float(end_slope)))
    cs = CubicSpline(ts, [p[1] for p in pts], bc_type=bc)
    lo, hi = ts[0], ts[-1]
    return lambda t: float(cs(min(max(float(t), lo), hi)))


def profile_sections(front, back, half_width, z_eq: float | None = None, crown=None, levels: int = 12,
                     dome_levels: int = 9, n=2.2, squash=0.0, cy=0.0, power: float = 2.0, seam: float = 180.0,
                     z0: float | None = None) -> tuple[list[dict], tuple | None]:
    """Sections from silhouette guide curves, ready for section_body / checked_body / inset_body / inflate.

    front, back: the side silhouette, x of the front and of the back at each height, as (z, x) knots from the bottom
    up to the widest line z_eq (the last knot when z_eq is None). half_width: the front silhouette, (z, y) knots.
    The guides are clamped flat at z_eq, so they meet the dome above with a common tangent.
    crown: (x, z_top) closes the body with a dome above z_eq: every section follows the superellipse law
    (t^p + k^p = 1, p = power) toward the crown point (a head, a helmet, a mouse's hump). None: it ends flat at z_eq.
    n (soft-squareness), squash (egg-shaped front), cy (sideways shift: an asymmetric product) are numbers or (z, v)
    knots over the whole height. seam: where each section starts (180 = the back, away from front features).
    Returns (sections, tip)."""
    zf = sorted(pts2(front, "front", 2))
    za = z0 if z0 is not None else zf[0][0]
    ze = z_eq if z_eq is not None else zf[-1][0]
    flat = 0.0 if crown is not None else None
    F, B, Wd = curve(front, "front", flat), curve(back, "back", flat), curve(half_width, "half_width", flat)
    need(ze > za, "profile_sections: z_eq must be above the lowest knot", "Give knots from the bottom up.", ["z_eq"])
    nl = num(levels, "levels", lo=2, hi=60, integer=True)
    Nn, Sq, Cy = curve(n, "n"), curve(squash, "squash"), curve(cy, "cy")
    p = num(power, "power", lo=1.5, hi=6)
    out = []

    def sec(z, f, b, w):
        need(f - b > 1.0 and w > 0.5, f"profile_sections: the section at z = {z:.1f} has no size (front {f:.1f}, back "
             f"{b:.1f}, half width {w:.1f})", "Keep front > back and the half width positive at every height.",
             ["front", "back", "half_width"])
        return {"z": z, "a": (f - b) / 2, "b": w, "n": Nn(z), "cx": (f + b) / 2, "cy": Cy(z),
                "squash": min(max(Sq(z), 0.0), 0.6), "seam": seam}

    for i in range(nl):
        z = za + (ze - za) * i / (nl - 1)
        out.append(sec(z, F(z), B(z), Wd(z)))
    if crown is None:
        return out, None
    cxr, ztop = float(crown[0]), float(crown[1])
    need(ztop > ze + 1, "profile_sections: the crown must be above z_eq", "Raise the crown or lower z_eq.", ["crown"])
    D = num(dome_levels, "dome_levels", lo=2, hi=40, integer=True)
    f0, b0, w0 = F(ze), B(ze), Wd(ze)
    for i in range(1, D + 1):
        u = i / (D + 1)
        tt = (1 - (1 - u) ** 1.6) * 0.985                     # denser toward the crown
        z = ze + (ztop - ze) * tt
        k = (1 - tt ** p) ** (1 / p)
        out.append({**sec(z, cxr + (f0 - cxr) * k, cxr + (b0 - cxr) * k, max(w0 * k, 0.6)), "dome": True})
    return out, (cxr, Cy(ztop), ztop)


def check_sections(sections: list[dict], max_slope: float = 4.0) -> list[str]:
    """Warnings for a section stack before lofting: sections out of order, seams that differ (the loft twists), and
    steps between neighbours steeper than max_slope (horizontal change per unit of height: the skin there is nearly
    flat and an interpolating loft overshoots into a fold). Each warning is also left as a craft note."""
    out = []
    for s0, s1 in zip(sections, sections[1:]):
        dz = s1["z"] - s0["z"]
        if dz <= 0:
            out.append(f"sections out of order at z = {s1['z']:.1f}")
            continue
        if abs(s1.get("seam", 0.0) - s0.get("seam", 0.0)) > 1e-6:
            out.append(f"seam changes between z = {s0['z']:.1f} and {s1['z']:.1f}: the loft will twist")
        if abs(s1.get("rotate", 0.0) - s0.get("rotate", 0.0)) > 25:
            out.append(f"sections turn {abs(s1.get('rotate', 0) - s0.get('rotate', 0)):.0f} deg between z = "
                       f"{s0['z']:.1f} and {s1['z']:.1f}: the loft will twist")
        if s1 is sections[-1] or s1.get("dome"):             # a dome law flattens toward its crown by design
            continue
        for k0, k1, nm in (("a", "cx", "length"), ("b", "cy", "width")):
            step = max(abs((s1[k0] + s1.get(k1, 0)) - (s0[k0] + s0.get(k1, 0))),
                       abs((s1.get(k1, 0) - s1[k0]) - (s0.get(k1, 0) - s0[k0])))
            if step / dz > max_slope:
                out.append(f"{nm} steps {step:.1f} mm over {dz:.1f} mm of height at z = {s0['z']:.1f}-{s1['z']:.1f}: "
                           "add sections there or ease the guide, or the loft may fold")
    for w in out:
        note("check_sections: " + w)
    return out


def loft_report(shape, grid: int = 28, fold_deg: float = 135.0) -> dict:
    """Is a lofted (free-form) skin clean? Samples every B-spline/Bezier face on a grid x grid net of (u, v) and
    reports where neighbouring normals turn by more than fold_deg (the skin folds back over itself, the normal almost
    reversing; ribs and crisp crests turn less). Degenerate samples (a pole, |Su x Sv| near 0) are skipped. Computed from the
    surface's own derivatives: exact where it samples, heuristic between samples.
    Returns {faces_checked, folds, worst_deg, where: [(x, y, z), ...]}."""
    import numpy as np
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_BezierSurface, GeomAbs_BSplineSurface
    from OCP.gp import gp_Pnt, gp_Vec
    faces, folds, worst, where = 0, 0, 0.0, []
    for f in shape.faces():
        s = BRepAdaptor_Surface(f.wrapped)
        if s.GetType() not in (GeomAbs_BSplineSurface, GeomAbs_BezierSurface):
            continue
        faces += 1
        u0, u1, v0, v1 = s.FirstUParameter(), s.LastUParameter(), s.FirstVParameter(), s.LastVParameter()
        N = np.zeros((grid, grid, 3))
        P = np.zeros((grid, grid, 3))
        M = np.zeros((grid, grid))
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        for i in range(grid):
            u = u0 + (u1 - u0) * (i + 0.5) / grid
            for j in range(grid):
                v = v0 + (v1 - v0) * (j + 0.5) / grid
                s.D1(u, v, p, du, dv)
                n = np.array([du.Y() * dv.Z() - du.Z() * dv.Y(), du.Z() * dv.X() - du.X() * dv.Z(),
                              du.X() * dv.Y() - du.Y() * dv.X()])
                M[i, j] = np.linalg.norm(n)
                N[i, j] = n / (M[i, j] or 1.0)
                P[i, j] = (p.X(), p.Y(), p.Z())
        live = M > 1e-4 * (np.median(M) or 1.0)
        for axis in (0, 1):
            A, B_ = (N[1:, :], N[:-1, :]) if axis == 0 else (N[:, 1:], N[:, :-1])
            la = (live[1:, :] & live[:-1, :]) if axis == 0 else (live[:, 1:] & live[:, :-1])
            ang = np.degrees(np.arccos(np.clip((A * B_).sum(-1), -1, 1)))
            ang[~la] = 0.0
            bad = ang > fold_deg
            folds += int(bad.sum())
            if ang.size:
                worst = max(worst, float(ang.max()))
            Q = P[1:, :] if axis == 0 else P[:, 1:]
            for ii, jj in list(zip(*np.nonzero(bad)))[:4]:
                where.append(tuple(round(float(x), 1) for x in Q[ii, jj]))
    return {"faces_checked": faces, "folds": folds, "worst_deg": round(worst, 1), "where": where[:8]}


def checked_body(sections: list[dict], tip=None, count: int = 72, label: str = "body"):
    """section_body with the checks a lofted form needs: the section stack (check_sections) before, the skin
    (loft_report) after. A fold is left as a craft note naming where it is, so critique and get_project show it."""
    check_sections(sections)
    body = section_body(sections, tip=tip, count=count)
    r = loft_report(body)
    if r["folds"]:
        note(f"loft_report: the {label} skin folds ({r['folds']} sample pairs turn more than 135 deg, worst "
             f"{r['worst_deg']:g} deg, near {r['where'][:2]}); ease the guide curves or add sections there")
    return body


# ---- cutters and surface-following details ----------------------------------------------------------------------

def two_view_cutter(side, front, x_range=(-1000.0, 1000.0), y_half: float = 1000.0, smooth=(True, True)):
    """A cutter whose side view is the closed outline `side` [(x, z), ...] and whose front view is `front`
    [(y, z), ...]: the side outline extruded along Y intersected with the front outline extruded along X over x_range.
    An eye port, a visor window or a wrapped vent is defined like this: in two views, as a designer draws it.
    smooth (side, front): True draws the outline as a closed B-spline through the points (it bulges past the points
    between them: a spline through a rectangle's four corners is a fat oval), False as straight segments."""
    from build123d import Plane, Pos, extrude
    from .surfaces import polygon_profile, spline_profile
    s = (spline_profile if smooth[0] else polygon_profile)(side, plane=Plane.XZ)
    fr = (spline_profile if smooth[1] else polygon_profile)(front, plane=Plane.YZ)
    a = extrude(s, y_half, both=True)
    x0, x1 = float(x_range[0]), float(x_range[1])
    b = Pos(x0, 0, 0) * extrude(fr, x1 - x0)
    return attempt("two_view_cutter", [("intersect", lambda: one(a & b))],
                   "The two outlines do not overlap in height; draw them over the same z range.", ["side", "front"])


_LAYERS: dict = {}                                         # surface_band layers by sections, amount and depth


def grow_outline(points, amount: float):
    """A closed outline [(x, y), ...] moved outward by about `amount` mm at every point (along the outline's own
    normal, estimated from its neighbours); negative shrinks. For a rim or a gasket round an opening:
        rim = two_view_cutter(grow_outline(side, 6), grow_outline(front, 6)) - two_view_cutter(side, front)"""
    p = pts2(points, "points", 3)
    a = num(amount, "amount")
    n = len(p)
    area = sum(p[i][0] * p[(i + 1) % n][1] - p[(i + 1) % n][0] * p[i][1] for i in range(n)) / 2
    sgn = 1.0 if area > 0 else -1.0                        # counter-clockwise: the outward normal is (dy, -dx)
    out = []
    for i in range(n):
        (x0, y0), (x1, y1) = p[i - 1], p[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) or 1.0
        out.append((p[i][0] + sgn * a * dy / ln, p[i][1] - sgn * a * dx / ln))
    return out


def surface_band(sections: list[dict], tip, amount: float, region, depth: float = 1.0, count: int = 48):
    """A pad, rim, trim strip or panel that follows a section body: the layer between the body shrunk by `depth` and
    the body grown by `amount` (inflate), clipped to region (a solid: a prism, a two_view_cutter). Union it with the
    shell: its root lies inside the wall (keep depth under the wall thickness), so no face of the band coincides with
    a face of the shell and the boolean is robust. The band's sides are the region's walls, so its border is a crisp
    character line."""
    a, d = num(amount, "amount", positive=True), num(depth, "depth", lo=0.2)
    grown, root = offset_body(sections, tip, a, count), offset_body(sections, tip, -d, count)
    # clip first, then take the root away: two booleans on a small piece instead of one on the whole skin
    piece = attempt("surface_band", [("clip", lambda: one(grown & region))],
                    "The region does not reach the surface; move or enlarge it.", ["region"])
    return attempt("surface_band", [("minus root", lambda: one(piece - root))],
                   "Use a smaller depth, or a region that reaches the surface.", ["depth", "region"])


def offset_body(sections: list[dict], tip, amount: float, count: int = 48):
    """section_body of the sections inflated by amount (negative shrinks), cached for the build: surface_band and
    visor-like skins ask for the same few offsets many times."""
    key = (repr([(round(s["z"], 4), round(s["a"], 4), round(s["b"], 4), s.get("n"), s.get("cx"), s.get("cy"),
                  s.get("squash"), s.get("seam"), s.get("rotate")) for s in sections]), tip, round(amount, 4), count)
    body = _LAYERS.get(key)
    if body is None:
        s2, t2 = inflate(sections, amount, tip)
        body = section_body(s2, tip=t2, count=count)
        if len(_LAYERS) > 24:
            _LAYERS.clear()
        _LAYERS[key] = body
    return body


def slot_grille(center, normal, count: int = 5, length: float = 30.0, width: float = 4.0, pitch: float = 8.0,
                depth: float = 40.0, angle: float = 0.0, taper: float = 0.0):
    """A B-rep vent grille cutter: `count` rounded slots side by side, centred at center, cut along normal (they
    pierce whatever surface they cross, curved or flat). angle turns the slots about the normal; taper (0-0.6)
    shortens the outer slots so the grille's outline is a lens, not a rectangle. Subtract it from a shell or a pad."""
    from build123d import Plane, Pos, SlotOverall, Vector, extrude
    n = num(count, "count", lo=1, hi=40, integer=True)
    Lg, w, pt = num(length, "length", positive=True), num(width, "width", positive=True), num(pitch, "pitch", positive=True)
    need(n == 1 or pt > w, "slot_grille: the pitch must exceed the slot width", "Widen the pitch.", ["pitch", "width"])
    tp = num(taper, "taper", lo=0, hi=0.6)
    nv = Vector(*map(float, normal)).normalized()
    ref = Vector(0, 0, 1) if abs(nv.Z) < 0.9 else Vector(1, 0, 0)
    xd = ref.cross(nv).normalized()
    yd = nv.cross(xd)
    a = math.radians(angle)
    pl = Plane(origin=Vector(*map(float, center)) - nv * (depth / 2), x_dir=xd * math.cos(a) + yd * math.sin(a), z_dir=nv)
    out = None
    for i in range(n):
        off = (i - (n - 1) / 2) * pt
        frac = abs(off) / ((n - 1) / 2 * pt) if n > 1 else 0.0
        s = pl * Pos(0, off, 0) * extrude(SlotOverall(max(w + 0.5, Lg * (1 - tp * frac ** 2)), w), depth)
        out = s if out is None else out + s
    return out


# ---- named proportions ------------------------------------------------------------------------------------------
#
# Real products are sized from people. These tables are what the families below are driven by. They are typical
# values for design, not a certification: a helmet built from them is a form study, not an approved helmet.

#: EN 960 / ECE 22.05 headform sizes: head circumference in mm.
HEADFORMS = {"A": 500, "E": 540, "J": 570, "M": 600, "O": 620}
#: ANSUR II (US Army anthropometric survey, 2012), mean male head: circumference 573, length (glabella to
#: opisthocranion) 199, breadth 155, vertex to menton (chin) 232, vertex to eye about 118, vertex to tragion (ear) 131.
ANSUR_HEAD = {"circumference": 573.0, "length": 199.0, "breadth": 155.0, "menton": 232.0, "eye": 118.0, "tragion": 131.0}
#: Full-face helmet build-up from the head outward (typical, per side): comfort liner 8-12, EPS 30-40, shell 3-5 mm.
#: The chin bar stands 25-35 mm clear of the chin.
HELMET_LAYERS = {"comfort": 10.0, "eps": 34.0, "shell": 3.5, "chin_clear": 30.0}
#: ANSUR II mean male hand: length 194, breadth 90 mm. Palm-grip mice run about 0.62-0.68 x hand length long and
#: 0.62-0.72 x hand breadth wide (manufacturers' size charts; a rule of thumb, not a standard).
ANSUR_HAND = {"length": 194.0, "breadth": 90.0}
#: PCO 1881 (28 mm) neck finish of a PET drinks bottle: thread outside diameter 27.4, bore 21.7, support ring 33 mm.
PCO1881 = {"thread_d": 27.4, "bore_d": 21.7, "ring_d": 33.0, "finish_h": 17.0}


def head_form(size="J", cephalic: float | None = None) -> dict:
    """Head dimensions for an EN 960 / ECE 22.05 headform size letter (A, E, J, M, O) or a circumference in mm,
    scaled from the ANSUR II mean male head. cephalic: breadth / length (0.78 the ANSUR mean; 0.83-0.85 a round
    head). The circumference is kept when the ratio changes."""
    C = float(HEADFORMS[size]) if isinstance(size, str) and size in HEADFORMS else num(size, "size", lo=480, hi=660)
    k = C / ANSUR_HEAD["circumference"]
    ci = ANSUR_HEAD["breadth"] / ANSUR_HEAD["length"] if cephalic is None else num(cephalic, "cephalic", lo=0.7, hi=0.92)
    ci0 = ANSUR_HEAD["breadth"] / ANSUR_HEAD["length"]

    def per(a, b):                                         # Ramanujan's ellipse perimeter
        h = ((a - b) / (a + b)) ** 2
        return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))
    L0 = ANSUR_HEAD["length"] * k
    s = per(L0 / 2, L0 * ci0 / 2) / per(L0 / 2, L0 * ci / 2)
    return {"circumference": C, "length": round(L0 * s, 1), "breadth": round(L0 * ci * s, 1),
            "menton": round(ANSUR_HEAD["menton"] * k, 1), "eye": round(ANSUR_HEAD["eye"] * k, 1),
            "tragion": round(ANSUR_HEAD["tragion"] * k, 1),
            "source": "EN 960 / ECE 22.05 headform circumference; ANSUR II (2012) mean male head proportions"}


def helmet_fullface(size="J", layers: dict | None = None, cephalic: float | None = None, crown_back: float = 0.05,
                    chin: float = 1.0, tail: float = 1.0) -> dict:
    """The form of a full-face (motorcycle) helmet from a head size: guide curves, sections and the outlines its
    openings are cut from. The helmet faces +X; the chin bar's lowest point is near z = 0.

    Proportions follow the head: shell length = head length + 2 x (comfort + EPS + shell), width likewise, the crown
    that far above the vertex, the eye line where the head's eyes are. chin (0.6-1.4) scales how far the chin bar
    projects; tail (0.6-1.4) how far the back tucks in to the nape.
    Keys: L, W, H (outside), z_eye, z_eq, sections, tip, edge (lower edge, side view [(x, z)]), port_side and
    port_front (the eye port in two views, for two_view_cutter), visor_side, pivot (x, z), head, layers, guides."""
    hd = head_form(size, cephalic)
    ly = {**HELMET_LAYERS, **(layers or {})}
    off = ly["comfort"] + ly["eps"] + ly["shell"]
    L, W = hd["length"] + 2 * off, hd["breadth"] + 2 * off
    ch, tl = num(chin, "chin", lo=0.6, hi=1.4), num(tail, "tail", lo=0.6, hi=1.4)
    z_menton = ly["shell"] + 12.0                         # the chin bar's underside sits just below the chin
    z_vertex = z_menton + hd["menton"]
    H = z_vertex + off * 0.8                           # the crown sits lower over the head than the sides stand off
    z_eye = z_vertex - hd["eye"]
    hl = L / 2
    zeq = z_eye + 0.30 * (H - z_eye)                      # the widest line: above the eyes, at the temples
    # side silhouette: the chin bar's nose projects ahead of the face; the face behind the visor is nearly upright
    # the visor face leans back from the chin bar's nose to the brow
    front = [(0.0, hl * (0.78 + 0.08 * ch)), (0.12 * H, hl * (0.96 + 0.07 * ch)), (0.21 * H, hl * (0.99 + 0.08 * ch)),
             (z_eye - 0.10 * H, hl * 0.985), (z_eye, hl * 0.965), (zeq, hl * 0.95)]
    back = [(0.0, -hl * (0.80 - 0.04 * (tl - 1) * 2)), (0.12 * H, -hl * (0.84 - 0.03 * (tl - 1) * 2)),
            (0.26 * H, -hl * 0.93), (z_eye - 0.04 * H, -hl * 0.99), (zeq, -hl)]
    half = [(0.0, W / 2 * 0.80), (0.14 * H, W / 2 * 0.84), (0.30 * H, W / 2 * 0.92), (z_eye, W / 2 * 0.985),
            (zeq, W / 2)]
    # plan: the chin bar is a narrow prow (egg-shaped front), easing to the head's oval at the temples
    squash = [(0.0, 0.34), (0.22 * H, 0.32), (z_eye - 0.05 * H, 0.16), (zeq, 0.10), (H, 0.06)]
    secs, tip = profile_sections(front, back, half, z_eq=zeq, crown=(-crown_back * L, H), levels=11, dome_levels=9,
                                 n=[(0.0, 2.25), (zeq, 2.15), (H, 2.05)], squash=squash, power=2.15, seam=180.0)
    # lower edge, side view: lowest under the chin, a scoop up under the jaw, then a gentle rise to the nape (a real
    # helmet's bottom line tilts up toward the back)
    edge = [(hl * 1.4, -30.0), (hl * 1.4, 0.035 * H), (hl * 0.88, 0.02 * H), (hl * 0.62, 0.06 * H),
            (hl * 0.32, 0.135 * H), (hl * 0.02, 0.165 * H), (-hl * 0.35, 0.165 * H), (-hl * 0.72, 0.155 * H),
            (-hl * 1.4, 0.15 * H), (-hl * 1.4, -30.0)]
    # eye port: wraps from the front back to about a third of the way to the pivot; the top edge is the brow line
    pb, pt = z_eye - 0.11 * H, z_eye + 0.13 * H
    xb = hl * 0.30
    port_side = [(hl * 1.3, pb - 6), (hl * 0.80, pb - 2), (hl * 0.50, pb + 4), (xb + 6, pb + 10), (xb, (pb + pt) / 2),
                 (xb + 8, pt - 6), (hl * 0.55, pt + 2), (hl * 0.85, pt + 4), (hl * 1.3, pt + 6)]
    # the front outline reaches past the shell's sides (the side outline decides how far the port wraps); it gives the
    # brow line, highest at the centre, and the bottom edge's dip over the nose
    pw = W / 2 * 1.2
    port_front = [(0.0, pb - 5.0), (pw * 0.25, pb), (pw * 0.6, pb + 3), (pw, pb + 4), (pw, pt - 4), (pw * 0.6, pt),
                  (pw * 0.25, pt + 4), (0.0, pt + 5), (-pw * 0.25, pt + 4), (-pw * 0.6, pt), (-pw, pt - 4), (-pw, pb + 4),
                  (-pw * 0.6, pb + 3), (-pw * 0.25, pb)]
    pivot = (hl * 0.12, z_eye + 0.035 * H)
    # visor: the port grown by an overlap, an arm sweeping back to the pivot, a top edge that runs up into the brow
    vb, vt = pb - 12, pt + 14
    visor_side = [(hl * 1.3, vb - 8), (hl * 0.75, vb - 2), (hl * 0.42, vb + 6), (pivot[0] + 10, pivot[1] - 22),
                  (pivot[0] - 14, pivot[1] - 8), (pivot[0] - 14, pivot[1] + 12), (pivot[0] + 14, pivot[1] + 24),
                  (hl * 0.45, vt + 2), (hl * 0.8, vt + 6), (hl * 1.3, vt + 8)]
    return {"L": round(L, 1), "W": round(W, 1), "H": round(H, 1), "z_eye": round(z_eye, 1), "z_eq": round(zeq, 1),
            "sections": secs, "tip": tip, "edge": edge, "port_side": port_side, "port_front": port_front,
            "port_z": (pb, pt), "visor_side": visor_side, "pivot": pivot, "head": hd, "layers": ly, "offset": off,
            "guides": {"front": front, "back": back, "half_width": half}}


def helmet_open(size="J", kind: str = "cycling", layers: dict | None = None, cephalic: float | None = None) -> dict:
    """A half-shell (kind="cycling": EPS 20-30 mm, a tail that drops over the occiput, brow above the eyebrows) or an
    open-face helmet (kind="open": covers the ears, no chin bar). Same keys as helmet_fullface where they apply."""
    need(kind in ("cycling", "open"), f"helmet_open: unknown kind {kind!r}", "Use cycling or open.", ["kind"])
    hd = head_form(size, cephalic)
    base = {"comfort": 6.0, "eps": 24.0, "shell": 1.2} if kind == "cycling" else dict(HELMET_LAYERS)
    ly = {**base, **(layers or {})}
    off = ly["comfort"] + ly["eps"] + ly["shell"]
    L, W = hd["length"] + 2 * off + (22 if kind == "cycling" else 0), hd["breadth"] + 2 * off
    hl = L / 2
    H = hd["tragion"] + (0 if kind == "cycling" else 40) + off
    zeq = H * 0.42
    front = [(0.0, hl * 0.90), (zeq * 0.5, hl * 0.97), (zeq, hl * 0.96)]
    back = [(0.0, -hl * 0.92), (zeq * 0.5, -hl * 0.99), (zeq, -hl)]
    half = [(0.0, W / 2 * 0.93), (zeq * 0.5, W / 2 * 0.985), (zeq, W / 2)]
    secs, tip = profile_sections(front, back, half, z_eq=zeq, crown=(-0.04 * L, H), levels=6, dome_levels=9,
                                 n=2.2, squash=[(0, 0.18), (H, 0.05)], power=2.3 if kind == "cycling" else 2.15)
    if kind == "cycling":
        edge = [(hl * 1.3, -20), (hl * 1.3, H * 0.34), (hl * 0.6, H * 0.30), (0, H * 0.18), (-hl * 0.6, H * 0.06),
                (-hl * 1.3, 0.0), (-hl * 1.3, -20)]
    else:
        edge = [(hl * 1.3, -20), (hl * 1.3, H * 0.36), (hl * 0.55, H * 0.30), (hl * 0.3, H * 0.05),
                (-hl * 0.6, H * 0.02), (-hl * 1.3, H * 0.06), (-hl * 1.3, -20)]
    return {"L": round(L, 1), "W": round(W, 1), "H": round(H, 1), "z_eq": round(zeq, 1), "sections": secs, "tip": tip,
            "edge": edge, "head": hd, "layers": ly, "offset": off}


def mouse_form(length: float | None = None, width: float | None = None, height: float | None = None,
               hand: str = "right", hump: float = 0.40, tilt: float = 0.12, flare: float = 4.0, nose: float = 0.34,
               hand_length: float | None = None) -> dict:
    """The form of a palm-grip mouse (nose toward +X, base at z = 0). Without length/width/height they follow the
    hand (ANSUR_HAND, or hand_length): length 0.65 x hand length, width 0.70 x hand breadth, height 0.33 x length.
    hump: where the palm hump peaks, as a fraction of the length from the back (0.35-0.45 for a palm grip).
    tilt: how far the top leans toward the thumb so the hand rolls toward the little finger (0 symmetric, 0.15 an
    ergonomic right-hand shape). flare: mm the thumb-side skirt flares out at the base. nose: the height of the front
    and the widest line, as a fraction of the height. hand="right" puts the thumb on +Y; "left" mirrors it;
    "both" is symmetric. Keys: L, W, H, z_eq, sections, tip, guides, thumb_y (+1 or -1), crown_x."""
    hl_ = ANSUR_HAND["length"] if hand_length is None else num(hand_length, "hand_length", lo=140, hi=230)
    hb = ANSUR_HAND["breadth"] * hl_ / ANSUR_HAND["length"]
    L = 0.65 * hl_ if length is None else num(length, "length", lo=80, hi=150)
    W = 0.70 * hb if width is None else num(width, "width", lo=45, hi=90)
    H = 0.33 * L if height is None else num(height, "height", lo=25, hi=55)
    need(hand in ("right", "left", "both"), f"mouse_form: unknown hand {hand!r}", "Use right, left or both.", ["hand"])
    sgn = -1.0 if hand == "left" else 1.0
    tl, fl = (0.0, 0.0) if hand == "both" else (num(tilt, "tilt", lo=0, hi=0.3), num(flare, "flare", lo=0, hi=10))
    hp, nz = num(hump, "hump", lo=0.25, hi=0.6), num(nose, "nose", lo=0.2, hi=0.75)
    hl = L / 2
    zeq = H * nz
    # an almost upright skirt (a mouse glides on its base; an undercut reads as a pebble), the dome law above it
    front = [(0.0, hl * 0.975), (zeq * 0.5, hl * 0.995), (zeq, hl)]
    back = [(0.0, -hl * 0.97), (zeq * 0.5, -hl * 0.993), (zeq, -hl)]
    half = [(0.0, W / 2 * 0.965 + fl * 0.5), (zeq * 0.5, W / 2 * 0.993), (zeq, W / 2)]
    cy = [(0.0, sgn * fl * 0.5), (zeq * 0.6, 0.0), (H, sgn * tl * W * 0.35)]
    crown_x = -hl + hp * L
    secs, tip = profile_sections(front, back, half, z_eq=zeq, crown=(crown_x, H), levels=5, dome_levels=10,
                                 n=[(0.0, 3.0), (zeq, 2.8), (H, 2.2)], squash=[(0.0, 0.04), (H, 0.02)], cy=cy,
                                 power=2.0, seam=180.0)
    return {"L": round(L, 1), "W": round(W, 1), "H": round(H, 1), "z_eq": round(zeq, 1), "sections": secs, "tip": tip,
            "thumb_y": sgn, "crown_x": crown_x, "guides": {"front": front, "back": back, "half_width": half, "cy": cy},
            "source": "ANSUR II mean male hand; palm-grip size rule of thumb 0.65 x hand length"}


def bottle_profile(volume_ml: float = 500, diameter: float | None = None, shoulder: float = 0.22,
                   neck_d: float = PCO1881["thread_d"], waist: float = 0.04, base_r: float = 6.0) -> dict:
    """A drinks bottle's revolve profile [(r, z)] (points for revolve_profile(spline=True)) for a capacity: the body
    diameter (default about 0.38 x the body height), a shoulder over `shoulder` of the height running into a PCO 1881
    neck, an optional grip waist (fraction of the radius) and a rounded heel. The height is solved from the volume
    (a cylinder estimate plus 10 % for the shoulder). Keys: profile, height, diameter, neck."""
    V = num(volume_ml, "volume_ml", lo=50, hi=3000) * 1000.0
    D = num(diameter, "diameter", lo=30, hi=160) if diameter is not None else (4 * V * 0.38 / math.pi) ** (1 / 3)
    R = D / 2
    Hb = V / (math.pi * R * R) * 1.1
    sh = num(shoulder, "shoulder", lo=0.08, hi=0.5)
    rn = num(neck_d, "neck_d", lo=10, hi=D - 4) / 2
    w = num(waist, "waist", lo=0, hi=0.15)
    br = num(base_r, "base_r", lo=1, hi=R * 0.4)
    zs = Hb * (1 - sh)
    H = Hb + PCO1881["finish_h"]
    pts = [(R - br, 0.0), (R - br * 0.25, br * 0.35), (R, br * 1.2), (R, zs * 0.3), (R * (1 - w), zs * 0.5),
           (R, zs * 0.72), (R, zs), (R * 0.82, zs + (Hb - zs) * 0.45), (rn * 1.25, Hb - 4), (rn, Hb + 2), (rn, H)]
    return {"profile": pts, "height": round(H, 1), "diameter": round(D, 1), "neck": PCO1881,
            "source": "PCO 1881 neck finish; height from the stated volume"}


def grip_sections(length: float | None = None, hand_breadth: float | None = None, flat: float = 0.85,
                  swell_at: float = 0.4, taper: float = 0.82) -> tuple[list[dict], None]:
    """Sections of a power-grip handle along Z (z = 0 at the guard end): the diameter follows the hand (power-grip
    studies put the best diameter at 31-38 mm; 0.40 x hand breadth here), swells at swell_at of the length (the palm),
    eases to `taper` of it at both ends, and is flatter across Y (flat) so it does not turn in the hand.
    Loft with section_body(secs) and round the ends. The length defaults to hand breadth + 20 mm."""
    hb = ANSUR_HAND["breadth"] if hand_breadth is None else num(hand_breadth, "hand_breadth", lo=60, hi=120)
    Lg = hb + 20 if length is None else num(length, "length", lo=40, hi=300)
    D = 0.40 * hb
    tp, s0, f = num(taper, "taper", lo=0.5, hi=1.0), num(swell_at, "swell_at", lo=0.2, hi=0.8), num(flat, "flat", lo=0.5, hi=1.0)
    out = []
    for i in range(9):
        u = i / 8
        bump = math.sin(math.pi / 2 * (u / s0 if u <= s0 else 1 + (u - s0) / (1 - s0)))
        r = D / 2 * (tp + (1 - tp) * max(0.0, bump))
        out.append({"z": Lg * u, "a": r, "b": r * f, "n": 2.15, "seam": 180.0})
    return out, None


# ── sculpted bodies with engineered features (hybrid): cages, magnets, split lines ───────────────────────────────
# The skin comes from a subdivision cage (form.craft.subd: dome_cage, apply_handles, sculpted_shell) or from a
# sculpted mesh made into a surface body (form.meshbody.organic_solid). What a person fits, fastens or prints flat
# is exact CAD on top of it: magnet pockets on bosses that grow from the inside, a split plane for printing, openings
# from a constrained sketch (form.sketch2d).

def surface_point(shape, origin, direction):
    """Where a ray from origin along direction first meets the shape: (point (x, y, z), outward unit normal)."""
    import numpy as np
    from build123d import Face, Vector
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    inter = BRepIntCurveSurface_Inter()
    inter.Init(shape.wrapped, gp_Lin(gp_Pnt(*map(float, origin)), gp_Dir(*map(float, direction))), 1e-7)
    best = None
    while inter.More():
        if inter.W() > 1e-6 and (best is None or inter.W() < best[0]):
            p = inter.Pnt()
            best = (inter.W(), (p.X(), p.Y(), p.Z()), inter.Face())
        inter.Next()
    need(best is not None, "surface_point: the ray misses the body", "Aim the ray at the body.", ["origin", "direction"])
    _, p, f = best
    nv = Face(f).normal_at(Vector(*p))
    n = np.array([nv.X, nv.Y, nv.Z])
    return tuple(p), tuple(n / (np.linalg.norm(n) or 1))


def _cyl(at, axis, d: float, h: float, back: float = 0.0):
    """A cylinder of diameter d from at - back along axis to at + h along axis."""
    import numpy as np
    from build123d import Cylinder, Plane, Pos
    ax = np.asarray(axis, float)
    ax = ax / (np.linalg.norm(ax) or 1)
    base = np.asarray(at, float) - back * ax
    pl = Plane(origin=tuple(base), z_dir=tuple(ax))
    return pl.location * Pos(0, 0, (h + back) / 2) * Cylinder(d / 2, h + back)


def magnet_boss(body, at, axis, magnet_d: float, magnet_t: float, wall: float = 1.6, clearance: float = 0.15,
                floor: float = 0.6):
    """A round boss grown from the inside of a thin skin at `at` (a point on the inside surface) along `axis` (into
    the hollow), tall enough for a magnet pocket with `floor` mm left under it, and the pocket cut in it from the top:
    (body with the boss fused, the pocket cut). Returns (body, top centre of the pocket)."""
    from .surfaces import cut, fuse
    d = num(magnet_d, "magnet_d", lo=1, hi=40)
    t = num(magnet_t, "magnet_t", lo=0.5, hi=20)
    h = t + floor + 0.4
    boss = _cyl(at, axis, d + 2 * wall, h, back=1.5)
    body = fuse(body, boss)
    import numpy as np
    top = np.asarray(at, float) + h * np.asarray(axis, float) / (np.linalg.norm(axis) or 1)
    body = cut(body, magnet_pocket(top, [-x for x in axis], d, t, clearance))
    return body, tuple(top)


def magnet_pocket(at, axis, magnet_d: float, magnet_t: float, clearance: float = 0.15):
    """The tool for a magnet pocket: diameter magnet_d + 2 x clearance, depth magnet_t + clearance, from the face
    point `at` going along `axis` (into the material)."""
    return _cyl(at, axis, magnet_d + 2 * clearance, magnet_t + clearance, back=2.0)


def split_with_magnets(body, x: float, spots, magnet_d: float, magnet_t: float, clearance: float = 0.15,
                       boss_wall: float = 2.0):
    """Split a hollow body at the plane X = x into a front (x > plane) and a back, joined by magnets: at each spot
    ((y, z) on the plane, inside the wall) a boss grows across the split from the inside surface, and both halves get
    a pocket from the split face. Returns (front, back)."""
    import numpy as np
    from build123d import Box, Pos
    from .surfaces import cut, fuse
    d = num(magnet_d, "magnet_d", lo=1, hi=40)
    t = num(magnet_t, "magnet_t", lo=0.5, hi=20)
    bb = body.bounding_box()
    big = 4 * max(bb.size.X, bb.size.Y, bb.size.Z)
    for (y, z) in spots:
        # a boss on the plane, reaching from the wall a little inward, as long as two pockets plus floors
        c = np.array([x, y, z], float)
        r = d / 2 + boss_wall
        boss = _cyl(c, (1, 0, 0), 2 * r, (t + 1.2) * 2, back=0)
        boss = Pos(-(t + 1.2), 0, 0) * boss
        body = fuse(body, boss)
    front = body & (Pos(x + big / 2, 0, 0) * Box(big, big, big))
    back = body & (Pos(x - big / 2, 0, 0) * Box(big, big, big))
    for (y, z) in spots:
        front = cut(front, magnet_pocket((x, y, z), (1, 0, 0), d, t, clearance))
        back = cut(back, magnet_pocket((x, y, z), (-1, 0, 0), d, t, clearance))
    return one(front), one(back)


def web_heightmap(path, spokes: int = 24, rings: int = 14, line: float = 0.010, sag: float = 0.35,
                  size=(2048, 1024)) -> str:
    """A grayscale heightmap of a web relief (radial spokes from a pole, rings sagging between them) for
    MeshTexture("heightmap", projection="spherical", axis=<the pole>): u is the angle round the pole, v the angle
    from it. Raised lines on a flat ground; written to path (PNG) once, returned."""
    import os
    import numpy as np
    from PIL import Image
    if os.path.isfile(path):
        return str(path)
    W, H = size
    u = (np.arange(W) + 0.5) / W
    v = (np.arange(H) + 0.5) / H
    U, Vv = np.meshgrid(u, v)
    k = U * spokes
    du = np.abs(k - np.round(k)) / spokes                       # distance (in u) to the nearest spoke
    frac = k - np.floor(k)
    ring_v = Vv * rings + sag * np.sin(np.pi * frac)               # rings droop between spokes, like a web
    dv = np.abs(ring_v - np.round(ring_v)) / rings
    near = np.minimum(du * 2 * np.pi * np.sin(np.clip(Vv * np.pi, 0.05, np.pi)), dv * np.pi)
    hmap = np.clip(1 - near / line, 0, 1) ** 0.6
    hmap[Vv < 0.012] = 1.0                                       # the hub
    Image.fromarray((hmap * 255).astype(np.uint8)).save(path)
    return str(path)


def split_spots(body, x: float, heights, magnet_d: float, boss_wall: float = 2.0, sink: float = 1.2):
    """Where magnets across a split at X = x can sit on a hollow body: at each height z, on both sides (+Y and -Y),
    just inside the wall (a boss of magnet_d + 2 x boss_wall sunk `sink` mm into it). From the body's middle the ray
    meets the inside surface first. Returns [(y, z), ...] for split_with_magnets."""
    out = []
    for z in heights:
        for sy in (1, -1):
            at, _ = surface_point(body, (x, 0, z), (0, sy, 0))
            out.append((at[1] - sy * (magnet_d / 2 + boss_wall - sink), z))
    return out
