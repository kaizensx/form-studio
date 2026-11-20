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

from ._common import attempt, need, num, one
from .surfaces import loft_sections, revolve_profile, superellipse_face, sweep_spline


def section_body(sections: list[dict], tip=None, count: int = 64):
    """Loft through sections [{z, a, b, n=2.0, cx=0, cy=0, squash=0, rotate=0}, ...] in increasing z.
    tip: (x, y, z) of a closing point above the last section (a dome's crown), or None to end flat."""
    need(len(sections) >= 2, "section_body needs at least 2 sections", "Add sections.", ["sections"])
    zs = [num(s.get("z"), "z") for s in sections]
    need(all(b > a for a, b in zip(zs, zs[1:])), "section_body: sections must rise in z", "Sort the sections by z.",
         ["sections"])
    faces = [superellipse_face(s["a"], s["b"], s.get("n", 2.0), z=s["z"], center=(s.get("cx", 0.0), s.get("cy", 0.0)),
                               count=count, rotate=s.get("rotate", 0.0), squash_front=s.get("squash", 0.0))
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
    t = num(wall, "wall", lo=0.4)
    outer = section_body(sections, tip=tip, count=count)
    ins = []
    for s in sections:
        need(s["a"] - t > 1 and s["b"] - t > 1, f"section_shell: the section at z = {s['z']:g} is too small for a "
             f"{t:g} mm wall", "Use a thinner wall or larger sections.", ["wall"])
        ins.append({**s, "a": s["a"] - t, "b": s["b"] - t})
    if open_bottom:
        ins.insert(0, {**ins[0], "z": ins[0]["z"] - 1.0})
    else:
        ins[0] = {**ins[0], "z": ins[0]["z"] + t}
    if open_top and tip is None:
        ins.append({**ins[-1], "z": ins[-1]["z"] + 1.0})
    elif tip is None:
        ins[-1] = {**ins[-1], "z": ins[-1]["z"] - t}
    itip = None if tip is None else (tip[0], tip[1], tip[2] - t)
    inner = section_body(ins, tip=itip, count=count)
    hollow = attempt("section_shell", [("outer - inset inner", lambda: one(outer - inner))],
                     "Use a thinner wall; the inset sections cross the outer form.", ["wall"])
    return outer, hollow


def inflate(sections: list[dict], amount: float, tip=None):
    """The sections grown (or shrunk, amount < 0) by amount in plan, and the tip moved up by it: a near-offset of a
    section body that never fails. Use it for pads and ridges that follow a lofted surface:
        secs2, tip2 = craft.inflate(secs, 4, tip); pad = (craft.section_body(secs2, tip2) & footprint) - inside"""
    a = num(amount, "amount")
    out = [{**s, "a": s["a"] + a, "b": s["b"] + a} for s in sections]
    need(all(s["a"] > 0.5 and s["b"] > 0.5 for s in out), "inflate: a section shrank to nothing", "Use a smaller amount.",
         ["amount"])
    return out, (None if tip is None else (tip[0], tip[1], tip[2] + a))


def dome_sections(length: float, width: float, height: float, levels: int = 9, crown_back: float = 0.0,
                  squash_front: float = 0.12, n_base: float = 2.15, n_top: float = 2.0, z0: float = 0.0,
                  power: float = 2.2) -> tuple[list[dict], tuple]:
    """Sections of a smooth dome (a head form, a mouse, a shell): length along X, width along Y, height above z0.
    Each level follows a superellipse in elevation, (z/h)^p + (r/R)^p = 1, so the dome meets its crown tangent.
    crown_back moves the crown toward -X (a helmet's crown sits behind the forehead)."""
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
                    "cx": -crown_back * t ** 1.5, "squash": squash_front * (1 - t)})
    return out, (-crown_back, 0.0, z0 + H)


def helmet_shell(length: float = 270, width: float = 215, height: float = 165, wall: float = 3.0, skirt: float = 95,
                 crown_back: float = 14, squash_front: float = 0.1):
    """A closed helmet outer form (the dome continued down by `skirt` as a near-vertical wall) and its hollow shell.
    Returns (outer_solid, hollow_shell). Cut the eye port, neck and vents from the shell afterwards.
    The base of the skirt is at z = 0, the crown at skirt + height."""
    L, W, H, S = (num(x, nm, positive=True) for x, nm in ((length, "length"), (width, "width"), (height, "height"), (skirt, "skirt")))
    t = num(wall, "wall", lo=0.8)
    secs, tip = dome_sections(L, W, H, levels=9, crown_back=crown_back, squash_front=squash_front, z0=S)
    base = dict(secs[0])
    low = [{**base, "z": 0.0, "a": base["a"] * 0.93, "b": base["b"] * 0.95, "squash": squash_front * 0.9},
           {**base, "z": S * 0.55, "a": base["a"] * 0.985, "b": base["b"] * 0.99}]
    return section_shell(low + secs, t, tip=tip)


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
