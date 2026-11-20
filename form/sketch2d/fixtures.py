"""Ten fixture sketches: the profiles parts are usually made from, each fully constrained with named dimensions.
tests/test_sketch2d.py solves them, moves every dimension by +-20 % and checks the result; the agent can read them as
examples of how to constrain a profile.
"""
from __future__ import annotations

from . import Sketch


def rounded_plate() -> Sketch:
    """A mounting plate: rounded rectangle, a hole at each corner (concentric with the corner arcs) and one in the middle."""
    s = Sketch("rounded_plate")
    rr = s.rounded_rect(80, 50, 8, names=("plate_w", "plate_h", "corner_r"))
    holes = [s.circle(c, 3.2) for c in rr["centers"]]
    for h in holes[1:]:
        s.equal(holes[0], h)
    s.diameter(holes[0], 6.4, "hole_d")
    mid = s.circle(rr["center"], 10)
    s.diameter(mid, 20, "bore_d")
    return s


def slot_plate() -> Sketch:
    """An obround slot inside a rectangle."""
    s = Sketch("slot_plate")
    s.rounded_rect(90, 40, 4, names=("plate_w", "plate_h", ""))
    s.slot(40, 10, names=("slot_len", "slot_w"))
    return s


def l_bracket() -> Sketch:
    """An L profile, its inner corner filleted (tangent arc)."""
    s = Sketch("l_bracket")
    o = s.point(0, 0, fix=True)
    a, b = s.point(60, 0), s.point(60, 6)
    c, d = s.point(12, 6), s.point(6, 12)
    k = s.point(12, 12)
    e, f = s.point(6, 50), s.point(0, 50)
    base, end, ledge = s.line(o, a), s.line(a, b), s.line(b, c)
    fil = s.arc(k, d, c)              # the concave corner: centre (12, 12), counter-clockwise from d (6, 12) to c (12, 6)
    up, top, back = s.line(d, e), s.line(e, f), s.line(f, o)
    s.horizontal(base); s.vertical(end); s.horizontal(ledge); s.vertical(up); s.horizontal(top); s.vertical(back)
    s.tangent(ledge, fil); s.tangent(up, fil)
    s.length(base, 60, "leg_a")
    s.length(back, 50, "leg_b")
    s.length(end, 6, "thick_a")
    s.length(top, 6, "thick_b")
    s.radius(fil, 6, "fillet_r")
    return s


def keyhole() -> Sketch:
    """A keyhole hanger slot: a big round head and a narrow tail, tangent-free (the tail meets the head on its circle)."""
    s = Sketch("keyhole")
    c = s.point(0, 0, fix=True)
    p1, p2 = s.point(-2.5, -4.33), s.point(2.5, -4.33)
    q1, q2 = s.point(2.5, -18), s.point(-2.5, -18)
    k = s.point(0, -18)
    head = s.arc(c, p2, p1)
    right, left = s.line(p2, q1), s.line(q2, p1)
    tail = s.arc(k, q2, q1)
    s.vertical(right); s.vertical(left)
    s.tangent(right, tail); s.tangent(left, tail)
    s.equal(right, left)
    axis = s.line(c, k, construction=True)
    s.vertical(axis)
    s.symmetric(p1, p2, axis)
    s.radius(head, 5, "head_r")
    s.radius(tail, 2.5, "tail_r")
    s.distance(c, k, 18, "drop")
    return s


def t_slot() -> Sketch:
    """A T-slot cross-section: wide foot, narrow neck, symmetric about the vertical axis."""
    s = Sketch("t_slot")
    o = s.point(0, 0, fix=True)
    top = s.point(0, 20, fix=True)
    axis = s.line(o, top, construction=True)
    pts = [s.point(*p) for p in [(-10, 0), (10, 0), (10, 5), (3, 5), (3, 14), (-3, 14), (-3, 5), (-10, 5)]]
    lines = s.polyline(*pts, close=True)
    for i, ln in enumerate(lines):
        (s.horizontal if i % 2 == 0 else s.vertical)(ln)
    s.symmetric(pts[0], pts[1], axis)
    s.symmetric(pts[3], pts[6], axis)
    s.on(o, lines[0])
    s.length(lines[0], 20, "foot_w")
    s.length(lines[1], 5, "foot_h")
    s.length(lines[4], 6, "neck_w")
    s.length(lines[3], 9, "neck_h")
    return s


def stand_side() -> Sketch:
    """The side profile of a phone stand: a base, a back leaning at an angle, a lip in front."""
    s = Sketch("stand_side")
    o = s.point(0, 0, fix=True)
    pts = [o] + [s.point(*p) for p in [(90, 0), (90, 6), (30, 6), (30, 16), (24, 16), (24, 8), (12, 8), (44, 90), (36, 92)]]
    a, b, c, d, e, f, g, h, i, j = pts
    lines = s.polyline(a, b, c, d, e, f, g, h, i, j, a)
    base, front, shelf, lip_f, lip_t, lip_b, seat, back, top, rear = lines
    for ln in (base, shelf, lip_t, seat):
        s.horizontal(ln)
    for ln in (front, lip_f, lip_b):
        s.vertical(ln)
    s.parallel(back, rear)
    s.perpendicular(back, top)
    s.length(base, 90, "depth")
    s.length(front, 6, "plate_t")
    s.length(lip_f, 10, "lip_h")
    s.length(lip_t, 6, "lip_t")
    s.hdist(o, g, 24)
    s.vdist(o, g, 8)
    s.length(seat, 12)
    s.angle(base, back, 68.4, "lean", lo=50, hi=85)
    s.length(back, 86, "back_len")
    return s


def belt_cam() -> Sketch:
    """Two circles' outline joined by tangent lines (a link or a cam): arc-line tangency on both sides."""
    s = Sketch("belt_cam")
    c1 = s.point(0, 0, fix=True)
    c2 = s.point(50, 0)
    a1, b1 = s.point(0, -12), s.point(50, -6)
    b2, a2 = s.point(50, 6), s.point(0, 12)
    big = s.arc(c1, a2, a1)
    small = s.arc(c2, b1, b2)
    low, high = s.line(a1, b1), s.line(b2, a2)
    for ln in (low, high):
        s.tangent(ln, big)
        s.tangent(ln, small)
    axis = s.line(c1, c2, construction=True)
    s.horizontal(axis)
    s.distance(c1, c2, 50, "centres")
    s.radius(big, 12, "r_big")
    s.radius(small, 6, "r_small")
    hole = s.circle(c1, 4)
    s.diameter(hole, 8, "bore")
    return s


def hexagon() -> Sketch:
    """A regular hexagon by equal sides and 120 degree corners, sized across flats, with a round hole."""
    s = Sketch("hexagon")
    import math
    c = s.point(0, 0, fix=True)
    R = 10 / math.cos(math.pi / 6)
    pts = [s.point(R * math.cos(math.pi / 3 * k + math.pi / 6), R * math.sin(math.pi / 3 * k + math.pi / 6)) for k in range(6)]
    lines = s.polyline(*pts, close=True)
    for ln in lines[1:]:
        s.equal(lines[0], ln)
    for k in range(5):
        s.angle(lines[k], lines[k + 1], 60)
    s.vertical(lines[5])
    s.midpoint(c, s.line(pts[0], pts[3], construction=True))
    s.distance(c, lines[5], 10, "half_flats", lo=5, hi=20)
    hole = s.circle(c, 4)
    s.diameter(hole, 8, "hole_d")
    return s


def u_channel() -> Sketch:
    """A U channel with rounded outer corners."""
    s = Sketch("u_channel")
    o = s.point(0, 0, fix=True)
    k1, k2 = s.point(5, 5), s.point(35, 5)
    p = [s.point(*q) for q in [(5, 0), (35, 0), (40, 5), (40, 30), (36, 30), (36, 4), (4, 4), (4, 30), (0, 30), (0, 5)]]
    a1 = s.arc(k2, p[1], p[2])
    a2 = s.arc(k1, p[9], p[0])
    bot = s.line(p[0], p[1])
    rest = [s.line(p[2], p[3]), s.line(p[3], p[4]), s.line(p[4], p[5]), s.line(p[5], p[6]), s.line(p[6], p[7]),
            s.line(p[7], p[8]), s.line(p[8], p[9])]
    s.horizontal(bot)
    for ln, f in zip(rest, ("v", "h", "v", "h", "v", "h", "v")):
        (s.vertical if f == "v" else s.horizontal)(ln)
    s.tangent(bot, a1); s.tangent(rest[0], a1); s.tangent(bot, a2); s.tangent(rest[6], a2)
    s.equal(a1, a2)
    s.on(o, rest[6])
    s.vdist(o, p[0], 0)
    s.radius(a1, 5, "corner_r")
    s.hdist(p[9], p[2], 40, "width")
    s.vdist(p[0], p[3], 30, "height")
    s.hdist(p[4], p[3], 4, "wall")
    s.hdist(p[8], p[7], 4)
    s.vdist(p[0], p[6], 4, "floor")
    return s


def gasket() -> Sketch:
    """A flange gasket: rounded outer rectangle, rounded window, twelve bolt holes round it. 32 entities and over 60
    constraints: the size the solver is timed on."""
    s = Sketch("gasket")
    outer = s.rounded_rect(120, 80, 12, names=("outer_w", "outer_h", "outer_r"))
    s.rounded_rect(84, 44, 6, names=("window_w", "window_h", "window_r"), fix_center=False)
    s.coincident(s.points[-1], outer["center"])
    c = outer["center"]
    yax = s.line(c, s.point(0, 20), construction=True)
    xax = s.line(c, s.point(20, 0), construction=True)
    s.vertical(yax); s.horizontal(xax)
    tm, tl, tr = s.point(0, 31), s.point(-24, 31), s.point(24, 31)
    bm, bl, br = s.point(0, -31), s.point(-24, -31), s.point(24, -31)
    lm, rm = s.point(-52, 0), s.point(52, 0)
    s.on(tm, yax); s.vdist(c, tm, 31, "bolt_row")
    s.vdist(tm, tl, 0); s.vdist(tm, tr, 0)
    s.symmetric(tl, tr, yax); s.hdist(tl, tr, 48, "bolt_pitch")
    for top, bot in ((tm, bm), (tl, bl), (tr, br)):
        s.symmetric(top, bot, xax)
    s.on(lm, xax); s.on(rm, xax); s.symmetric(lm, rm, yax); s.hdist(lm, rm, 104, "side_pitch")
    holes = [s.circle(p, 3) for p in outer["centers"] + [tm, tl, tr, bm, bl, br, lm, rm]]
    for h in holes[1:]:
        s.equal(holes[0], h)
    s.diameter(holes[0], 6, "bolt_d")
    return s


ALL = {f.__name__: f for f in (rounded_plate, slot_plate, l_bracket, keyhole, t_slot, stand_side, belt_cam, hexagon,
                               u_channel, gasket)}
