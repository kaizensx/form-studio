"""The motion of a program, and how long it takes.

A program is a list of events, the same whether an operation wrote it or a posted G-code file was read back:

    ("op", n, name)                      the moves that follow belong to operation n
    ("tool", number)                     tool change
    ("spindle", rpm)  ("stop",)          spindle on (clockwise) and off
    ("coolant", "flood" | "mist" | "off")
    ("rapid", x, y, z)                   G0
    ("feed", x, y, z, f)                 G1 at f mm/min
    ("arc", x, y, z, cx, cy, cw, f)      G2 (cw) or G3 in XY about the centre (cx, cy); z may change (a helix)
    ("drill", x, y, z, r, q, f)          a drilling cycle: bottom z, retract plane r, peck q (0: none)
    ("dwell", seconds)
    ("home",)                            retract in machine coordinates (G28 or G53); taken as a rapid to the
                                         program's highest Z
    ("end",)

`flatten` turns events into straight segments: arcs become chords within ARC_TOL of the arc, and a drilling cycle
becomes the moves a controller makes (`drill_moves`). The simulation and the clock both run on these segments.

Cycle time. Each segment is run with a trapezoidal speed profile under one acceleration limit for every axis, and
the speed carried through a corner is the junction-deviation limit of Grbl's planner
(v² = a·δ·sin(θ/2) / (1 − sin(θ/2)), θ the angle between the moves; Sonny Jeon, "Improving Grbl's cornering
algorithm", 2011), with a backward and a forward pass so that every segment can still stop in the distance left.
The limits (rapid rate, acceleration, junction deviation, feed ceiling) are the machine's and are stated with the
result; with `exact_stop` every move starts and ends at rest. Spindle run-up, tool changes and the controller's own
look-ahead are not timed. The result is a simulation of the motion, not a measurement on a machine.
"""
from __future__ import annotations

import math

import numpy as np

ARC_TOL = 0.002          # mm: the largest distance between an arc and the chords that stand for it
PECK_CLEAR = 0.5         # mm above the last depth a peck cycle comes back down to at the rapid rate
RAPID, FEED = 0, 1

# What the clock assumes about a machine nobody described. Stated with every result; `assumed` until given.
MACHINE_DEFAULTS = {"rapid": 3000.0, "accel": 500.0, "junction_deviation": 0.01, "max_feed": 3000.0,
                    "max_rpm": 24000.0, "exact_stop": False}


def machine(given: dict | None = None) -> dict:
    """The machine's limits: what was given, and the defaults for the rest (each named as assumed)."""
    g = {k: v for k, v in (given or {}).items() if v not in (None, "")}
    m = {**MACHINE_DEFAULTS, **{k: (bool(v) if k == "exact_stop" else float(v)) for k, v in g.items() if k in MACHINE_DEFAULTS}}
    m["assumed"] = sorted(k for k in MACHINE_DEFAULTS if k not in g and k != "exact_stop")
    for k in ("name", "travel"):
        if k in g:
            m[k] = g[k]
    return m


def arc_points(p0, p1, c, cw: bool, tol: float = ARC_TOL) -> np.ndarray:
    """Points along an XY arc from p0 to p1 about centre c (z linear along it), p0 left out. A full circle when
    the ends coincide in XY."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    r0 = math.hypot(p0[0] - c[0], p0[1] - c[1])
    r1 = math.hypot(p1[0] - c[0], p1[1] - c[1])
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    sweep = a1 - a0
    if cw:
        while sweep >= -1e-9:
            sweep -= 2 * math.pi
    else:
        while sweep <= 1e-9:
            sweep += 2 * math.pi
    r = max(r0, r1, 1e-9)
    step = 2 * math.acos(max(-1.0, min(1.0, 1 - tol / r))) if r > tol else math.pi / 2
    n = max(2, int(math.ceil(abs(sweep) / max(step, 1e-6))))
    t = np.arange(1, n + 1) / n
    ang = a0 + sweep * t
    rad = r0 + (r1 - r0) * t
    out = np.stack([c[0] + rad * np.cos(ang), c[1] + rad * np.sin(ang), p0[2] + (p1[2] - p0[2]) * t], axis=1)
    out[-1] = p1
    return out


def drill_moves(x, y, z0, z, r, q, f) -> list:
    """What a drilling cycle does from Z z0 (G98, return to the initial level): position, rapid to r, feed to the
    bottom in pecks of q with a full retract to r between them, rapid out."""
    out = [("rapid", x, y, z0), ("rapid", x, y, r)]
    if q and q > 0:
        d = r
        while True:
            nd = max(z, d - q)
            out.append(("feed", x, y, nd, f))
            if nd <= z + 1e-9:
                break
            out.append(("rapid", x, y, r))
            out.append(("rapid", x, y, min(r, nd + PECK_CLEAR)))
            d = nd
    else:
        out.append(("feed", x, y, z, f))
    out.append(("rapid", x, y, max(z0, r)))
    return out


def primitives(events) -> list:
    """The events with every drilling cycle written out as rapids and feeds (what a post without canned cycles
    emits, and what a controller does with one)."""
    out, z = [], None
    for e in events:
        k = e[0]
        if k == "drill":
            _, x, y, zb, r, q, f = e
            mv = drill_moves(x, y, z if z is not None else r, zb, r, q, f)
            out += mv
            z = mv[-1][3]
            continue
        if k in ("rapid", "feed", "arc"):
            z = e[3]
        out.append(e)
    return out


def flatten(events) -> dict:
    """Straight segments from events. {"a", "b": (n, 3) ends, "kind": 0 rapid | 1 feed, "feed": mm/min (0 for a
    rapid), "tool": the T number, "op": the operation index, "event": the index of the event the segment came
    from, "dwell": seconds in all, "tools": tool numbers in order, "top": the highest Z}.

    The tool is taken to start at the first commanded position (a program opens by going to a safe height and then
    over the work; where the machine was before that is not known and not simulated)."""
    A, B, K, F, T, O, E = [], [], [], [], [], [], []
    pos = [None, None, None]
    tool, op, dwell, tools = 0, -1, 0.0, []
    ev = primitives(events)
    zs = [e[3] for e in ev if e[0] in ("rapid", "feed", "arc")]
    top = max(zs) if zs else 0.0

    def seg(p1, kind, f, i):
        nonlocal pos
        if None not in pos:
            a = np.array(pos, float)
            if float(np.abs(p1 - a).max()) > 1e-9:
                A.append(a)
                B.append(np.array(p1, float))
                K.append(kind)
                F.append(f)
                T.append(tool)
                O.append(op)
                E.append(i)
        pos = [float(p1[0]), float(p1[1]), float(p1[2])]

    for i, e in enumerate(ev):
        k = e[0]
        if k == "op":
            op = int(e[1])
        elif k == "tool":
            tool = int(e[1])
            tools.append(tool)
        elif k == "dwell":
            dwell += float(e[1])
        elif k in ("rapid", "feed"):
            tgt = [e[1], e[2], e[3]]
            if None in pos:                            # the first commanded position is where the tool starts
                pos = [float(v) for v in tgt]
                continue
            seg(np.array(tgt, float), RAPID if k == "rapid" else FEED, 0.0 if k == "rapid" else float(e[4]), i)
        elif k == "arc":
            _, x, y, z, cx, cy, cw, f = e
            if None in pos:
                pos = [x, y, z]
                continue
            for p in arc_points(pos, (x, y, z), (cx, cy), bool(cw)):
                seg(p, FEED, float(f), i)
        elif k == "home":
            if None not in pos:
                seg(np.array([pos[0], pos[1], top]), RAPID, 0.0, i)
    n = len(A)
    return {"a": np.array(A, float).reshape(n, 3), "b": np.array(B, float).reshape(n, 3),
            "kind": np.array(K, np.int8), "feed": np.array(F, float), "tool": np.array(T, np.int32),
            "op": np.array(O, np.int32), "event": np.array(E, np.int64), "dwell": dwell, "tools": tools, "top": top}


def cycle_time(segs: dict, mach: dict) -> dict:
    """Time to run the segments under the machine's limits. {"seconds", "feed_s", "rapid_s", "dwell_s",
    "feed_mm", "rapid_mm", "per_op": {op: seconds}, "t": cumulative seconds at the end of each segment, "limits"}."""
    a, b = segs["a"], segs["b"]
    n = len(a)
    limits = {"rapid_mm_min": mach["rapid"], "accel_mm_s2": mach["accel"], "junction_deviation_mm": mach["junction_deviation"],
              "max_feed_mm_min": mach["max_feed"], "exact_stop": bool(mach.get("exact_stop")),
              "assumed": list(mach.get("assumed", [])),
              "model": "trapezoidal speed profile per move, one acceleration for all axes, corner speed by junction "
                       "deviation; spindle run-up, tool changes and dwell inside the controller are not timed"}
    if n == 0:
        return {"seconds": float(segs.get("dwell", 0.0)), "feed_s": 0.0, "rapid_s": 0.0, "dwell_s": float(segs.get("dwell", 0.0)),
                "feed_mm": 0.0, "rapid_mm": 0.0, "per_op": {}, "t": np.zeros(0), "limits": limits}
    d = b - a
    L = np.linalg.norm(d, axis=1)
    u = d / np.maximum(L, 1e-12)[:, None]
    acc = float(mach["accel"])
    vn = np.where(segs["kind"] == RAPID, mach["rapid"], np.minimum(segs["feed"], mach["max_feed"])) / 60.0
    vn = np.maximum(vn, 1e-6)
    # the speed a corner can be taken at
    vj = np.zeros(n + 1)
    if not mach.get("exact_stop") and n > 1:
        cos = -(u[:-1] * u[1:]).sum(axis=1)
        s = np.sqrt(np.clip(0.5 * (1 - cos), 0.0, 1.0))                       # sin(θ/2)
        jd = float(mach["junction_deviation"])
        with np.errstate(divide="ignore", invalid="ignore"):
            v = np.sqrt(acc * jd * s / np.maximum(1 - s, 1e-12))
        v = np.where(cos > 0.999999, 0.0, np.where(cos < -0.999999, np.inf, v))
        vj[1:-1] = np.minimum(v, np.minimum(vn[:-1], vn[1:]))
    ve = vj.copy()                                     # ve[i]: speed entering segment i; ve[n]: leaving the last
    for i in range(n - 1, -1, -1):                     # every segment can brake to what follows
        ve[i] = min(ve[i], math.sqrt(ve[i + 1] ** 2 + 2 * acc * L[i]))
    ve[0] = 0.0
    for i in range(n):                                 # and can only gain what its length allows
        ve[i + 1] = min(ve[i + 1], math.sqrt(ve[i] ** 2 + 2 * acc * L[i]))
    v0, v1 = ve[:-1], ve[1:]
    vp = np.minimum(vn, np.sqrt(np.maximum((2 * acc * L + v0 ** 2 + v1 ** 2) / 2, 0.0)))
    vp = np.maximum(vp, np.maximum(v0, v1))
    cruise = np.maximum(L - (2 * vp ** 2 - v0 ** 2 - v1 ** 2) / (2 * acc), 0.0)
    t = (vp - v0) / acc + (vp - v1) / acc + cruise / np.maximum(vp, 1e-9)
    feed = segs["kind"] == FEED
    per = {}
    for o in np.unique(segs["op"]):
        per[int(o)] = round(float(t[segs["op"] == o].sum()), 6)
    dw = float(segs.get("dwell", 0.0))
    return {"seconds": round(float(t.sum()) + dw, 6), "feed_s": round(float(t[feed].sum()), 6),
            "rapid_s": round(float(t[~feed].sum()), 6), "dwell_s": dw, "feed_mm": round(float(L[feed].sum()), 3),
            "rapid_mm": round(float(L[~feed].sum()), 3), "per_op": per, "t": np.cumsum(t), "limits": limits}
