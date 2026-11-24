"""The kit's parts: original detail pieces made by code from a few numbers (no downloaded or copied assets).

Every part is built in its own frame, in millimetres at scale 1:
  * surface parts sit on the plane z = 0 and stand up along +Z (the surface normal when placed); their base reaches a
    little below z = 0 (EMBED) so they read as fixed into a curved surface;
  * axial parts (pommels, grip wraps) start at z = 0 and run along +Z (the axis they are placed on);
  * corner parts have the corner at the origin and the corner's diagonal along +Z.
The pivot is always the origin. kit_place scales the part, turns it about +Z and puts +Z on the surface normal.
"""
from __future__ import annotations

import math

import numpy as np

from .geom import Shell, box, circle, fillet, join, lathe, prism, ring_prism, rot, rounded_rect, sweep

EMBED = 0.3          # mm below the surface at scale 1


def _hash01(seed: int, k: int) -> float:
    """A fixed pseudo-random number in [0, 1) from (seed, k): integer arithmetic only, the same everywhere."""
    x = (seed * 0x9E3779B1 + k * 0x85EBCA77 + 0x165667B1) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x2C1B3C6D) & 0xFFFFFFFF
    x ^= x >> 12
    x = (x * 0x297A2D39) & 0xFFFFFFFF
    x ^= x >> 15
    return x / 2 ** 32


# ---- fasteners ---------------------------------------------------------------------------------------------------

def bolt_hex(p):
    R = p["across_flats"] / 2 / math.cos(math.pi / 6)
    h, c = p["height"], p["chamfer"]
    head = lathe([(R, -EMBED), (R, h - c), (R - 1.3 * c, h)], 6, phase=30, ring_crease={1: 0.8, 2: 0.9},
                 meridian_crease=0.9)
    washer = lathe([(R * 1.05, -EMBED), (R * 1.05, 0.35), (R * 0.95, 0.5)], 16, ring_crease={1: 0.7})
    return join(washer, head.moved(t=(0, 0, 0.5)))


def bolt_flange(p):
    R = p["across_flats"] / 2 / math.cos(math.pi / 6)
    h = p["height"]
    flange = lathe([(R * 1.35, -EMBED), (R * 1.35, 0.4), (R * 1.0, 1.0)], 20, ring_crease={1: 0.7})
    head = lathe([(R, 0.5), (R, h - 0.5), (R - 0.6, h)], 6, phase=30, ring_crease={1: 0.8}, meridian_crease=0.9)
    return join(flange, head)


def cap_screw(p):
    r, h = p["diameter"] / 2, p["height"]
    ri = r * p["socket"]
    return lathe([(r, -EMBED), (r, h * 0.85), (r * 0.9, h), (ri, h), (ri, h * 0.45)], 16,
                 ring_crease={1: 0.6, 2: 0.6, 3: 1.0, 4: 1.0})


def rivet_dome(p):
    r, h = p["diameter"] / 2, p["height"]
    return lathe([(r, -EMBED), (r, 0.12 * h), (0.88 * r, 0.5 * h), (0.6 * r, 0.85 * h), (0.25 * r, h)], 12,
                 ring_crease={1: 0.5})


def rivet_flat(p):
    r, h = p["diameter"] / 2, p["height"]
    return lathe([(r, -EMBED), (r, 0.35 * h), (0.75 * r, h)], 12, ring_crease={1: 0.8, 2: 0.8})


def hex_nut(p):
    R = p["across_flats"] / 2 / math.cos(math.pi / 6)
    h, rs = p["height"], p["across_flats"] * 0.3
    nut = lathe([(R, -EMBED), (R, h - 0.6), (R - 0.8, h)], 6, phase=30, ring_crease={1: 0.8, 2: 0.9},
                meridian_crease=0.9)
    stud = lathe([(rs, h - 0.5), (rs, h + p["stud"] - 0.4), (rs - 0.4, h + p["stud"])], 12, ring_crease={1: 0.7})
    return join(nut, stud)


def washer(p):
    ro, ri, t = p["outer"] / 2, p["inner"] / 2, p["thickness"]
    if ri > ro * 0.9:
        raise ValueError("washer: inner must be under 0.9 x outer")
    return ring_prism(circle(ro, 16), circle(ri, 16), -EMBED, t, crease=0.7)


def stud_round(p):
    r, h = p["diameter"] / 2, p["height"]
    return lathe([(r, -EMBED), (r, 0.3 * h), (0.92 * r, 0.6 * h), (0.65 * r, 0.9 * h), (0.25 * r, h)], 16,
                  ring_crease={1: 0.6})


def tread_block(p):
    """A tyre tread lug: a block width (X, across the tread) by length (Y, round the tyre), its top drawn in by
    taper, its front edge bent into a chevron (the point leads along +Y)."""
    w, L, h, k = p["width"], p["length"], p["height"], p["taper"]
    c = p["chevron"] * L
    poly = [(-w / 2, -L / 2), (0.0, -L / 2 + c), (w / 2, -L / 2), (w / 2, L / 2), (0.0, L / 2 + c), (-w / 2, L / 2)]
    s = prism(poly, -EMBED, h, rim_crease=0.9, side_crease=0.6)
    V = np.asarray(s.V, float)
    top = V[:, 2] > 0
    V[top, :2] *= 1.0 - k
    return Shell(V, s.F, s.C)


def stud_pyramid(p):
    R = p["width"] / 2 * math.sqrt(2)
    h = p["height"]
    return lathe([(R, -EMBED), (R, 0.25 * h), (0.12 * R, h)], 4, phase=45, ring_crease={1: 1.0, 2: 0.8},
                 meridian_crease=1.0)


# ---- vents and grilles ----------------------------------------------------------------------------------------

def _frame(w, h, rim, depth, r=1.5):
    return ring_prism(rounded_rect(w, h, r + rim, 2), rounded_rect(w - 2 * rim, h - 2 * rim, r, 2), -EMBED, depth,
                      crease=0.8)


def vent_louver(p):
    w, h, d, n = p["width"], p["height"], p["depth"], p["slats"]
    rim = max(1.5, 0.08 * min(w, h))
    parts = [_frame(w, h, rim, d)]
    inner_h = h - 2 * rim
    pitch = inner_h / n
    for k in range(n):
        y = -inner_h / 2 + pitch * (k + 0.5)
        slat = box((w - 2 * rim + 0.4, pitch * 1.05, 0.6), crease=0.8).moved(R=rot((1, 0, 0), 35))
        parts.append(slat.moved(t=(0, y, d * 0.55)))
    return join(*parts)


def grille_bars(p):
    w, h, d, n = p["width"], p["height"], p["depth"], p["bars"]
    rim = max(1.5, 0.08 * min(w, h))
    parts = [_frame(w, h, rim, d)]
    iw = w - 2 * rim
    bw = iw / (2 * n + 1)
    for k in range(n):
        x = -iw / 2 + bw * (2 * k + 1.5)
        parts.append(box((bw, h - 2 * rim + 0.4, d * 0.7), center=(x, 0, d * 0.35 - EMBED / 2), crease=0.8))
    parts.append(box((iw + 0.4, bw, d * 0.5), center=(0, 0, d * 0.75), crease=0.8))
    return join(*parts)


def grille_round(p):
    R, d, n = p["diameter"] / 2, p["depth"], p["rings"]
    rim = max(1.2, 0.1 * R)
    parts = [ring_prism(circle(R, 32), circle(R - rim, 32), -EMBED, d, crease=0.8)]
    inner = R - rim
    t = inner / (2 * n + 1)
    for k in range(n):
        ro = inner - t * (2 * k + 1)
        parts.append(ring_prism(circle(ro, 32), circle(ro - t, 32), -EMBED, d * 0.6, crease=0.7))
    for a in (0, 90):
        brace = box((2 * inner + 0.4, t * 0.8, d * 0.4), center=(0, 0, d * 0.6), crease=0.7)
        parts.append(brace.moved(R=rot((0, 0, 1), a)))
    return join(*parts)


def fan_vent(p):
    R, d, n = p["diameter"] / 2, p["depth"], p["fins"]
    rim = max(1.2, 0.12 * R)
    parts = [ring_prism(circle(R, 32), circle(R - rim, 32), -EMBED, d, crease=0.8),
             lathe([(R * 0.25, -EMBED), (R * 0.25, d * 0.8), (R * 0.15, d)], 16, ring_crease={1: 0.7})]
    ln = R - rim - R * 0.2
    for k in range(n):
        fin = box((ln + 0.4, 0.7, d * 0.7), crease=0.8).moved(R=rot((1, 0, 0), 30))
        parts.append(fin.moved(t=(R * 0.2 + ln / 2, 0, d * 0.4)).moved(R=rot((0, 0, 1), 360 * k / n)))
    return join(*parts)


# ---- hinges, straps, buckles, latches, handles -------------------------------------------------------------------

def _cyl_x(r, x0, x1, n=12, crease=0.7):
    c = lathe([(r, x0), (r, x1)], n, ring_crease={0: crease, 1: crease})
    return c.moved(R=rot((0, 1, 0), 90))


def hinge_barrel(p):
    L, r, leaf, k = p["length"], p["diameter"] / 2, p["leaf"], p["knuckles"]
    t = max(0.8, r * 0.35)
    parts = [box((L, leaf, t), center=(0, -leaf / 2, t / 2 - EMBED), crease=0.8),
             box((L, leaf, t), center=(0, leaf / 2, t / 2 - EMBED), crease=0.8)]
    gap = 0.4
    seg = (L - gap * (k - 1)) / k
    for i in range(k):
        x0 = -L / 2 + i * (seg + gap)
        parts.append(_cyl_x(r, x0, x0 + seg).moved(t=(0, 0, r)))
    for x in (-L / 2 - 0.6, L / 2):
        parts.append(_cyl_x(r * 0.45, x, x + 0.6, n=8).moved(t=(0, 0, r)))
    return join(*parts)


def strap(p):
    L, w, t = p["length"], p["width"], p["thickness"]
    band = prism(rounded_rect(L, w, w * 0.15, 1), -EMBED, t, rim_crease=0.7)
    parts = [band]
    n = int(p["rivets"])
    for i in range(n):
        x = 0.0 if n == 1 else -L / 2 + w * 0.6 + (L - 1.2 * w) * i / (n - 1)
        parts.append(rivet_dome({"diameter": w * 0.45, "height": w * 0.18}).moved(t=(x, 0, t)))
    return join(*parts)


def buckle(p):
    w, h, t = p["width"], p["height"], p["thickness"]
    bar = max(1.2, 0.14 * min(w, h))
    frame = ring_prism(rounded_rect(w, h, bar * 1.5, 2), rounded_rect(w - 2 * bar, h - 2 * bar, bar * 0.5, 2),
                       -EMBED, t, crease=0.6)
    prong = box((w / 2 + bar * 0.5, bar * 0.6, t * 0.7), center=(w / 4 - bar * 0.25, 0, t * 1.1), crease=0.7)
    roller = _cyl_x(t * 0.55, -h / 2 + bar * 0.2, h / 2 - bar * 0.2, n=10).moved(R=rot((0, 0, 1), 90),
                                                                                  t=(-w / 2 + bar / 2, 0, t * 0.6))
    return join(frame, prong, roller)


def latch_draw(p):
    w, L = p["width"], p["length"]
    base = prism(rounded_rect(w, L * 0.45, 1.0, 1), -EMBED, 1.2, rim_crease=0.8).moved(t=(0, -L * 0.25, 0))
    lever = box((w * 0.8, L * 0.55, 1.6), crease=0.8).moved(R=rot((1, 0, 0), -8), t=(0, L * 0.05, 2.4))
    pin = _cyl_x(1.0, -w * 0.45, w * 0.45, n=10).moved(t=(0, -L * 0.2, 1.8))
    hook = prism(rounded_rect(w * 0.6, L * 0.2, 1.0, 1), -EMBED, 1.0, rim_crease=0.8).moved(t=(0, L * 0.42, 0))
    loop = sweep(fillet([(-w * 0.25, L * 0.3, 0.4), (-w * 0.25, L * 0.4, 3.4), (w * 0.25, L * 0.4, 3.4),
                         (w * 0.25, L * 0.3, 0.4)], 1.2, 3), circle(0.6, 8))
    return join(base, lever, pin, hook, loop)


def handle_pull(p):
    L, h, r = p["length"], p["height"], p["bar"] / 2
    path = fillet([(-L / 2, 0, 0.6), (-L / 2, 0, h), (L / 2, 0, h), (L / 2, 0, 0.6)], min(h, L) * 0.3, 4)
    bar = sweep(path, circle(r, 10), cap_crease=0.5)
    pads = [lathe([(r * 1.9, -EMBED), (r * 1.9, 0.6), (r * 1.4, 1.2)], 16, ring_crease={1: 0.7}).moved(t=(x, 0, 0))
            for x in (-L / 2, L / 2)]
    return join(bar, *pads)


def eye_ring(p):
    R, r = p["diameter"] / 2, p["wire"] / 2
    ring = lathe(circle(r, 10, c=(R, 0)), 20, closed=True).moved(R=rot((1, 0, 0), 90), t=(0, 0, R + r + 2.0))
    boss = lathe([(r * 2.4, -EMBED), (r * 2.4, 1.0), (r * 1.4, 2.5), (r * 1.2, 2.9)], 12, ring_crease={1: 0.7})
    return join(boss, ring)


def chain_link(p):
    L, w, r = p["length"], p["width"], p["wire"] / 2
    path = [(x, y, 0.0) for x, y in rounded_rect(L, w, w / 2 - 1e-3, 4)]
    return sweep(path, circle(r, 8), closed=True).moved(t=(0, 0, r - EMBED))


def cable_clamp(p):
    R, w, t = p["cable"] / 2, p["width"], p["thickness"]
    rc = R + t / 2                     # the band's centre line round a cable lying on the surface
    foot = max(4.0, w * 0.8)
    arc = [(rc * math.cos(math.radians(a)), 0.0, R + rc * math.sin(math.radians(a))) for a in range(15, 166, 15)]
    path = [(rc + foot, 0.0, t / 2), (rc, 0.0, t / 2), (rc, 0.0, R)] + arc + \
        [(-rc, 0.0, R), (-rc, 0.0, t / 2), (-rc - foot, 0.0, t / 2)]
    band = sweep(fillet(path, min(1.0, R * 0.5), 2), [(-w / 2, -t / 2), (w / 2, -t / 2), (w / 2, t / 2),
                                                       (-w / 2, t / 2)],
                 up=(0, 1, 0), cap_crease=0.7, crease={0: 0.6, 1: 0.6, 2: 0.6, 3: 0.6})
    screw = rivet_flat({"diameter": w * 0.6, "height": 0.9}).moved(t=(rc + foot * 0.55, 0, t))
    return join(band, screw)


# ---- grips, pommels, blades ---------------------------------------------------------------------------------------

def grip_wrap(p):
    r, L, n, b = p["radius"], p["length"], int(p["turns"]), p["band"]
    th = max(0.6, b * 0.22)
    pitch = L / n
    tilt = math.degrees(math.atan2(pitch, 2 * math.pi * r)) * 2.0
    parts = []
    for k in range(n):
        band = lathe([(r - th, -b / 2), (r + th, -b / 2), (r + th * 1.2, 0), (r + th, b / 2), (r - th, b / 2)], 24,
                     closed=True, ring_crease={})
        parts.append(band.moved(R=rot((1, 0, 0), tilt), t=(0, 0, pitch * (k + 0.5))))
    return join(*parts)


def pommel_disc(p):
    r, t = p["diameter"] / 2, p["thickness"]
    return lathe([(r * 0.35, -EMBED), (r * 0.6, 0.0), (r, t * 0.25), (r, t * 0.75), (r * 0.6, t), (r * 0.3, t * 1.12),
                  (r * 0.2, t * 1.2)], 24, ring_crease={2: 0.6, 3: 0.6, 4: 0.5})


def pommel_scent(p):
    r, L = p["diameter"] / 2, p["length"]
    return lathe([(r * 0.3, -EMBED), (r * 0.45, L * 0.08), (r * 0.9, L * 0.35), (r, L * 0.55), (r * 0.75, L * 0.8),
                  (r * 0.35, L * 0.94), (r * 0.15, L)], 16, ring_crease={})


def pommel_faceted(p):
    r, L = p["diameter"] / 2, p["length"]
    return lathe([(r * 0.4, -EMBED), (r * 0.45, L * 0.05), (r, L * 0.35), (r, L * 0.6), (r * 0.4, L * 0.95),
                  (r * 0.32, L)], 8, phase=22.5, ring_crease={1: 0.8, 2: 1.0, 3: 1.0, 4: 0.8}, meridian_crease=1.0)


def fuller_channel(p):
    """Two low rails with a shallow channel between them, tapered at both ends: on a blade it reads as a fuller
    bounded by its shoulders. A true recess is panel_line or inset with a negative depth."""
    L, w, h = p["length"], p["width"], p["height"]
    prof = [(-w / 2, -EMBED), (w / 2, -EMBED), (w / 2, h), (w * 0.32, h), (w * 0.22, h * 0.2), (-w * 0.22, h * 0.2),
            (-w * 0.32, h), (-w / 2, h)]
    n = 9
    path = [(-L / 2 + L * i / (n - 1), 0.0, 0.0) for i in range(n)]
    sc = [0.35 + 0.65 * math.sin(math.pi * min(1.0, 4 * i / (n - 1), 4 * (n - 1 - i) / (n - 1)) / 2) for i in range(n)]
    # the profile is in (N, B): N is +Z for a path along +X with Z up, B = T x N = -Y
    prof_nb = [(v, -u) for u, v in prof]
    return sweep(path, prof_nb, scales=sc, up=(0, 0, 1), cap_crease=0.6,
                 crease={2: 0.7, 3: 1.0, 4: 1.0, 5: 1.0, 6: 1.0, 7: 0.7})


def spine_ridge(p):
    L, w, h = p["length"], p["width"], p["height"]
    prof = [(-w / 2, -EMBED), (w / 2, -EMBED), (0.0, h)]
    n = 7
    path = [(-L / 2 + L * i / (n - 1), 0.0, 0.0) for i in range(n)]
    sc = [0.3 + 0.7 * math.sin(math.pi * i / (n - 1)) ** 0.5 for i in range(n)]
    prof_nb = [(v, -u) for u, v in prof]
    return sweep(path, prof_nb, scales=sc, up=(0, 0, 1), cap_crease=0.8, crease={2: 1.0})


# ---- mounts, corners, plates, greebles ---------------------------------------------------------------------------

def lug_tab(p):
    w, h, t, hole = p["width"], p["height"], p["thickness"], p["hole"] / 2
    if hole > w * 0.4 or h < w * 0.6:
        raise ValueError("lug_tab: hole must be under 0.8 x width and height at least 0.6 x width")
    n = 16
    outer = []
    for k in range(n):            # a tab: straight sides, a round top; matched point for point with the hole
        a = math.radians(-90 + 360 * k / n)
        if math.sin(a) >= 0:
            outer.append((w / 2 * math.cos(a), h - w / 2 + w / 2 * math.sin(a)))
        else:
            outer.append((w / 2 * (1 if math.cos(a) >= 0 else -1) * min(1.0, abs(math.cos(a)) * 3), -EMBED))
    inner = [(hole * math.cos(a), h - w / 2 + hole * math.sin(a))
             for a in (math.radians(-90 + 360 * k / n) for k in range(n))]
    tab = ring_prism(outer, inner, -t / 2, t / 2, crease=0.7).moved(R=rot((1, 0, 0), 90))
    foot = prism(rounded_rect(w * 1.4, t * 2.2, 0.8, 1), -EMBED, 1.0, rim_crease=0.7)
    return join(foot, tab)


def corner_cap(p):
    s, t = p["size"], p["thickness"]
    # the protected box fills the negative octant; the cap's three plates wrap its corner
    plates = [box((s, s, t), center=(-s / 2 + t, -s / 2 + t, t / 2 - EMBED), crease=0.8),
              box((s, t, s), center=(-s / 2 + t, t / 2 - EMBED, -s / 2 + t), crease=0.8),
              box((t, s, s), center=(t / 2 - EMBED, -s / 2 + t, -s / 2 + t), crease=0.8)]
    studs = [rivet_dome({"diameter": s * 0.25, "height": s * 0.08}).moved(R=R, t=c) for R, c in (
        (np.eye(3), (-s * 0.45, -s * 0.45, t)), (rot((1, 0, 0), -90), (-s * 0.45, t, -s * 0.45)),
        (rot((0, 1, 0), 90), (t, -s * 0.45, -s * 0.45)))]
    R = _diag_to_z()
    return join(*plates, *studs).moved(R=R)


def _diag_to_z():
    from .geom import align
    return align((1, 1, 1), (0, 0, 1))


def panel_plate(p):
    w, h, t = p["width"], p["height"], p["thickness"]
    plate = prism(rounded_rect(w, h, min(w, h) * 0.12, 2), -EMBED, t, rim_crease=0.6)
    top = prism(rounded_rect(w - 2 * t, h - 2 * t, min(w, h) * 0.1, 2), t - 0.1, t + 0.35 * t, rim_crease=0.7)
    m = min(w, h) * 0.12 + 1.0
    screws = [rivet_flat({"diameter": min(w, h) * 0.12, "height": 0.6}).moved(t=(x, y, t * 1.35))
              for x in (-w / 2 + m, w / 2 - m) for y in (-h / 2 + m, h / 2 - m)]
    return join(plate, top, *screws)


def knob_ridged(p):
    r, h, n = p["diameter"] / 2, p["height"], int(p["ridges"])
    prof = [(r, -EMBED), (r, h * 0.85), (r * 0.88, h), (r * 0.3, h)]
    body = lathe(prof, n * 2, ring_crease={1: 0.6}, meridian_crease=0.5)
    # every other column of points pulled in: the ridges
    V = body.V.copy()
    for i in range(len(V)):
        rr = math.hypot(V[i, 0], V[i, 1])
        if rr > r * 0.5:
            a = math.atan2(V[i, 1], V[i, 0])
            k = round(a / (math.pi / n))
            if k % 2:
                V[i, :2] *= 0.84
    return Shell(V, body.F, body.C)


def greeble_block(p):
    s, seed = p["size"], int(p["seed"])
    parts = [box((s, s * 0.7, s * 0.18), center=(0, 0, s * 0.09 - EMBED), crease=0.8)]
    for k in range(4):
        w = s * (0.2 + 0.3 * _hash01(seed, 4 * k))
        d = s * (0.15 + 0.25 * _hash01(seed, 4 * k + 1))
        h = s * (0.08 + 0.22 * _hash01(seed, 4 * k + 2))
        x = (s - w) * (_hash01(seed, 4 * k + 3) - 0.5)
        y = (s * 0.7 - d) * (_hash01(seed, 4 * k + 7) - 0.5)
        parts.append(box((w, d, h), center=(x, y, s * 0.18 + h / 2 - 0.1), crease=0.8))
    return join(*parts)


def greeble_pipe(p):
    L, r, seed = p["length"], p["radius"], int(p["seed"])
    rise = r * 2.5
    jog = (0.25 + 0.4 * _hash01(seed, 1)) * L * 0.4
    path = fillet([(-L / 2, 0, 0.0), (-L / 2, 0, rise), (-L / 6, 0, rise), (-L / 6, jog, rise),
                   (L / 2 - r * 2, jog, rise),
                   (L / 2 - r * 2, jog, 0.0)], r * 1.8, 4)
    pipe = sweep(path, circle(r, 10), cap_crease=0.6)
    clamps = [box((r * 1.2, r * 3.2, r * 0.8), center=(x, y, r * 0.4 - EMBED), crease=0.8) for x, y in
              ((-L / 2, 0), (L / 2 - r * 2, jog))]
    collar = lathe([(r * 1.3, 0), (r * 1.3, r * 1.2)], 12, ring_crease={0: 0.7, 1: 0.7}).moved(
        R=rot((0, 1, 0), 90), t=(-L / 12, 0, rise))
    return join(pipe, *clamps, collar)


# ---- the registry -------------------------------------------------------------------------------------------------
# name: (builder, kind, {param: (default, lo, hi, integer)}, description)

F, I = False, True
PARTS = {
    "bolt_hex": (bolt_hex, "surface", {"across_flats": (8.0, 2, 60, F), "height": (3.2, 0.8, 30, F),
                                       "chamfer": (0.6, 0.1, 3, F)},
                 "Hex bolt head on a round washer face; chamfered top, sharp flats."),
    "bolt_flange": (bolt_flange, "surface", {"across_flats": (8.0, 2, 60, F), "height": (4.0, 1, 30, F)},
                    "Hex head on a wide flange washer (a flange bolt)."),
    "cap_screw": (cap_screw, "surface", {"diameter": (7.0, 2, 60, F), "height": (4.0, 1, 30, F),
                                         "socket": (0.45, 0.2, 0.7, F)},
                  "Round cap screw head with a recessed socket (socket radius as a share of the head)."),
    "rivet_dome": (rivet_dome, "surface", {"diameter": (6.0, 1, 40, F), "height": (2.2, 0.4, 20, F)},
                   "Round-head rivet: a low dome with a soft rim."),
    "rivet_flat": (rivet_flat, "surface", {"diameter": (6.0, 1, 40, F), "height": (0.8, 0.2, 10, F)},
                   "Flat (countersunk-look) rivet: a disc with a chamfered edge."),
    "hex_nut": (hex_nut, "surface", {"across_flats": (10.0, 3, 60, F), "height": (5.0, 1, 40, F),
                                     "stud": (2.5, 0.5, 30, F)},
                "Hex nut on a protruding threaded stud end."),
    "washer": (washer, "surface", {"outer": (12.0, 3, 80, F), "inner": (6.0, 1, 70, F), "thickness": (1.2, 0.3, 10, F)},
               "Flat washer: a ring with softened rims."),
    "stud_round": (stud_round, "surface", {"diameter": (8.0, 1, 40, F), "height": (3.0, 0.5, 20, F)},
                   "Domed decorative stud (leather and armour)."),
    "tread_block": (tread_block, "surface", {"width": (40.0, 4, 400, F), "length": (24.0, 3, 400, F),
                                             "height": (10.0, 1, 100, F), "taper": (0.12, 0.0, 0.4, F),
                                             "chevron": (0.25, 0.0, 0.6, F)},
                    "Tyre tread lug: a tapered block, width across the tread (X), length round the tyre (Y), its "
                    "leading edge bent into a chevron."),
    "stud_pyramid": (stud_pyramid, "surface", {"width": (8.0, 1, 40, F), "height": (3.5, 0.5, 20, F)},
                     "Square pyramid stud with sharp facets."),
    "vent_louver": (vent_louver, "surface", {"width": (40.0, 8, 400, F), "height": (24.0, 6, 400, F),
                                             "depth": (3.0, 0.5, 40, F), "slats": (5, 1, 24, I)},
                    "Louvred vent: a rounded frame with angled slats."),
    "grille_bars": (grille_bars, "surface", {"width": (40.0, 8, 400, F), "height": (24.0, 6, 400, F),
                                             "depth": (3.0, 0.5, 40, F), "bars": (6, 1, 32, I)},
                    "Bar grille: a frame, upright bars and one cross bar."),
    "grille_round": (grille_round, "surface", {"diameter": (40.0, 8, 400, F), "depth": (2.5, 0.5, 40, F),
                                               "rings": (4, 1, 12, I)},
                     "Round speaker-style grille: a rim, concentric rings and a cross brace."),
    "fan_vent": (fan_vent, "surface", {"diameter": (30.0, 8, 400, F), "depth": (3.0, 0.5, 40, F),
                                       "fins": (8, 3, 24, I)},
                 "Round vent with angled radial fins round a hub."),
    "hinge_barrel": (hinge_barrel, "surface", {"length": (40.0, 6, 400, F), "diameter": (6.0, 1.5, 40, F),
                                               "leaf": (12.0, 2, 100, F), "knuckles": (5, 2, 15, I)},
                     "Butt hinge: two leaves, alternating knuckles along X and pin caps."),
    "strap": (strap, "surface", {"length": (60.0, 6, 1000, F), "width": (12.0, 2, 200, F),
                                 "thickness": (1.2, 0.3, 10, F), "rivets": (2, 0, 12, I)},
              "Flat strap band along X with dome rivets spaced along it."),
    "buckle": (buckle, "surface", {"width": (20.0, 6, 200, F), "height": (16.0, 6, 200, F),
                                   "thickness": (1.5, 0.4, 10, F)},
               "Rectangular buckle: rounded frame, prong and roller."),
    "latch_draw": (latch_draw, "surface", {"width": (14.0, 6, 200, F), "length": (30.0, 10, 300, F)},
                   "Draw latch: base plate, lever, pivot pin, wire loop and keeper plate (along Y)."),
    "handle_pull": (handle_pull, "surface", {"length": (40.0, 8, 600, F), "height": (12.0, 3, 200, F),
                                             "bar": (4.0, 1, 40, F)},
                    "Pull handle: a round bar bent into a U, on two mounting pads (along X)."),
    "eye_ring": (eye_ring, "surface", {"diameter": (10.0, 3, 200, F), "wire": (2.0, 0.5, 30, F)},
                 "Ring bolt: an upright ring on a round boss."),
    "chain_link": (chain_link, "surface", {"length": (14.0, 4, 200, F), "width": (8.0, 3, 120, F),
                                           "wire": (2.0, 0.5, 30, F)},
                   "One oval chain link lying on the surface."),
    "cable_clamp": (cable_clamp, "surface", {"cable": (6.0, 1, 100, F), "width": (6.0, 2, 60, F),
                                             "thickness": (1.0, 0.3, 8, F)},
                    "P-clip: a strap arching over a cable (along Y), with a flat screw on its foot."),
    "grip_wrap": (grip_wrap, "axial", {"radius": (12.0, 2, 200, F), "length": (60.0, 6, 1000, F),
                                       "turns": (10, 2, 60, I), "band": (5.0, 1, 50, F)},
                  "Wrapped grip: tilted leather bands round an axis, from z = 0 along +Z (place on the grip axis)."),
    "pommel_disc": (pommel_disc, "axial", {"diameter": (30.0, 6, 300, F), "thickness": (12.0, 2, 200, F)},
                    "Wheel pommel: a bevelled disc with a raised centre, along +Z from the grip end."),
    "pommel_scent": (pommel_scent, "axial", {"diameter": (24.0, 5, 300, F), "length": (32.0, 5, 300, F)},
                     "Teardrop (scent-stopper) pommel along +Z."),
    "pommel_faceted": (pommel_faceted, "axial", {"diameter": (26.0, 5, 300, F), "length": (28.0, 5, 300, F)},
                       "Eight-sided faceted pommel along +Z."),
    "fuller_channel": (fuller_channel, "surface", {"length": (120.0, 10, 2000, F), "width": (8.0, 2, 100, F),
                                                   "height": (1.4, 0.2, 10, F)},
                       "Fuller shoulders: two low tapered rails with a shallow channel, along X. For a true "
                       "recess use panel_line or inset with a negative depth."),
    "spine_ridge": (spine_ridge, "surface", {"length": (100.0, 10, 2000, F), "width": (6.0, 1, 100, F),
                                             "height": (1.5, 0.2, 20, F)},
                    "A sharp tapered ridge along X (blade spine, armour crest)."),
    "lug_tab": (lug_tab, "surface", {"width": (12.0, 3, 200, F), "height": (14.0, 3, 200, F),
                                     "thickness": (4.0, 1, 50, F), "hole": (5.0, 1, 150, F)},
                "Mounting lug: an upright round-topped tab with a through hole, on a foot (tab in the X-Z plane)."),
    "corner_cap": (corner_cap, "corner", {"size": (14.0, 4, 200, F), "thickness": (1.5, 0.4, 10, F)},
                   "Box corner protector: three plates with a rivet each; the corner diagonal is +Z (place at a box "
                   "corner with normal along the corner diagonal)."),
    "panel_plate": (panel_plate, "surface", {"width": (30.0, 6, 600, F), "height": (20.0, 6, 600, F),
                                             "thickness": (1.2, 0.3, 10, F)},
                    "Access panel: a rounded plate with a raised centre and four flat screws."),
    "knob_ridged": (knob_ridged, "surface", {"diameter": (14.0, 3, 200, F), "height": (8.0, 1, 100, F),
                                             "ridges": (12, 4, 48, I)},
                    "Ridged control knob."),
    "greeble_block": (greeble_block, "surface", {"size": (20.0, 3, 400, F), "seed": (1, 0, 99999, I)},
                      "Stepped greeble: a base slab and four blocks, laid out from a seed."),
    "greeble_pipe": (greeble_pipe, "surface", {"length": (40.0, 10, 1000, F), "radius": (1.6, 0.3, 40, F),
                                               "seed": (1, 0, 99999, I)},
                     "Pipe run greeble: a bent pipe with clamps and a collar, laid out from a seed."),
}
