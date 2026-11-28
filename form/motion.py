"""Motion studies: a mechanism played over time from its own joints, couplings and closed loops, checked along the way.

What a study does, frame by frame (``study``, numpy only, no kernel):
  1. Drivers set the driven joints at time t: a ramp from one value to another, keyframes, a constant speed or a sine.
     Without drivers the first joint that nothing else drives is swept over its range.
  2. Couplings (``Coupling``: gears, a rack and pinion, a lead screw, a belt, a cam) set the joints they drive.
  3. Closed loops (``Loop``: a four-bar's coupler pinned to its rocker) are solved for the joints nobody drives, by
     Newton's method on the loop-closure equations (the point common to both parts, and a pin's axis, coincide),
     least squares with a line search, started from the previous frame so the linkage stays on its branch. A frame the
     linkage cannot reach (beyond a Grashof limit, a dead point) is reported as not closing, never as a pose.
  4. Points traced on parts give their path, velocity and acceleration (central differences in time on the solved
     positions); joints give theirs too.

Then, on the real geometry (``run``, the studio process; meshes from the kernel's view, collide.py for distances):
  * clearance along the whole cycle: every pair of parts that moves relative to the other (not joined by design: a
    Mate or a Loop) at every frame, the minimum gap with the frame and time where it occurs, the first frame with
    contact or overlap, and the intervals between frames proven free (no point can travel further than the clearance
    between two frames) or sampled only;
  * holding torque under gravity on each driven joint, by virtual work on the solved positions (dV/dq with V the
    potential energy of every part's mass at its centre, from the mass properties of wave C); quasi-static, no
    friction, no inertia;
  * a film of the motion (MP4 through ffmpeg, from Form Studio's headless renderer; no GIF).

Evidence: kinematics "computed (kinematics)"; distances "computed (mesh distance, ±tol)"; torque "computed (virtual
work, quasi-static, gravity only)". Every result is stored under a key of the geometry and the study's inputs.

    from form import motion
    r = motion.run(st, p, drivers=[{"joint": "crank", "from": 0, "to": 360}], frames=73)
    motion.study(spec, drivers=[...])     # the kinematics alone, from an Assembly
"""
from __future__ import annotations

import json
import math
import time

import numpy as np

VERSION = 1
EVIDENCE_KIN = "computed (kinematics)"
EVIDENCE_CLEAR = "computed (mesh distance)"
EVIDENCE_TORQUE = "computed (virtual work, quasi-static, gravity only)"
G = 9.80665                        # m/s², standard gravity
MAX_FRAMES = 361
CLOSE_TOL = 1e-7                   # mm: a loop closes when every closure equation is within this
SINGULAR = 1e-3                    # smallest / largest singular value of the closure Jacobian under this: a dead point


class MotionError(ValueError):
    """A study that cannot be set up (unknown joint, a driver without a range, no assembly)."""


# ── values ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _dofs(j) -> int:
    from .recipes.assembly import DOF
    return DOF.get(j.kind, 1)


def _vals(j, v) -> list:
    """A joint's value as a list with one number per degree of freedom."""
    from .recipes.assembly import values_of
    n = _dofs(j)
    out = values_of(j, v)
    return (out + [0.0] * n)[:n] if n else []


def _public(j, vals):
    """A joint value for the record: a number for one degree of freedom, a list otherwise."""
    return round(float(vals[0]), 9) if len(vals) == 1 else [round(float(x), 9) for x in vals]


def _unit(j, dof: int = 0) -> str:
    from .recipes.assembly import ROTARY
    if j.kind == "cylindrical" and dof == 1:
        return "mm"
    return "deg" if j.kind in ROTARY else "mm"


def _limits(j, dof: int = 0) -> tuple:
    if j.kind == "cylindrical" and dof == 1:
        return tuple(j.range2)
    return tuple(j.range)


# ── drivers ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _driver(spec, d: dict, duration: float):
    """(joint id, dof, f(t) -> value, description) for one driver given as a dict."""
    if not isinstance(d, dict) or "joint" not in d:
        raise MotionError('A driver is {"joint": id, ...}: "from"/"to", "keys", "speed" or "sine".')
    js = {j.id: j for j in spec.joints}
    jid = str(d["joint"])
    if jid not in js:
        raise MotionError(f"Unknown joint “{jid}”. Joints: " + ", ".join(j.id for j in spec.joints if j.kind != "fixed") + ".")
    j = js[jid]
    if j.kind == "fixed":
        raise MotionError(f"Joint “{jid}” is fixed: it cannot be driven.")
    dof = int(d.get("dof", 0))
    if not 0 <= dof < _dofs(j):
        raise MotionError(f"Joint “{jid}” has {_dofs(j)} degree(s) of freedom; dof is 0" + (f" to {_dofs(j) - 1}." if _dofs(j) > 1 else "."))
    u = _unit(j, dof)
    if "keys" in d:
        keys = sorted((float(t), float(v)) for t, v in d["keys"])
        if len(keys) < 2:
            raise MotionError(f"Driver of “{jid}”: keys needs at least two [time s, value] pairs.")
        ts, vs = [k[0] for k in keys], [k[1] for k in keys]
        return jid, dof, (lambda t: float(np.interp(t, ts, vs))), f"{jid}: keyframes {keys[0][1]:g} to {keys[-1][1]:g} {u}"
    if "sine" in d:
        s = d["sine"] or {}
        amp, mid = float(s.get("amplitude", 30.0)), float(s.get("center", 0.0))
        per, ph = float(s.get("period_s", duration)), math.radians(float(s.get("phase_deg", 0.0)))
        if per <= 0:
            raise MotionError(f"Driver of “{jid}”: period_s must be positive.")
        return (jid, dof, (lambda t: mid + amp * math.sin(2 * math.pi * t / per + ph)),
                f"{jid}: {mid:g} ± {amp:g} {u}, period {per:g} s")
    if "speed" in d:
        v0, w = float(d.get("start", 0.0)), float(d["speed"])
        return jid, dof, (lambda t: v0 + w * t), f"{jid}: {w:g} {u}/s from {v0:g} {u}"
    lo, hi = _limits(j, dof)
    a, b = float(d.get("from", lo)), float(d.get("to", hi))
    return jid, dof, (lambda t: a + (b - a) * (t / duration if duration > 0 else 0.0)), f"{jid}: {a:g} to {b:g} {u}"


def default_drivers(spec) -> list:
    """The first joint that no coupling drives, swept over its range."""
    led = {c.follower for c in spec.couplings}
    for j in spec.joints:
        if j.kind != "fixed" and j.id not in led:
            return [{"joint": j.id, "from": j.range[0], "to": j.range[1]}]
    raise MotionError("No joint can be driven: every joint is fixed or driven by a coupling.")


# ── the mechanism ─────────────────────────────────────────────────────────────────────────────────────────────────

class Mechanism:
    """An Assembly's kinematics: couplings applied, loops closed by Newton's method."""

    def __init__(self, spec):
        self.spec = spec
        self.js = {j.id: j for j in spec.joints}
        self.led = {c.follower: c for c in spec.couplings}
        pts = [np.asarray(j.origin, float) for j in spec.joints] + [np.asarray(lp.at, float) for lp in spec.loops]
        spread = max((float(np.linalg.norm(a - b)) for a in pts for b in pts), default=0.0)
        self.scale = max(spread, 1.0)                         # mm: weights a pin's axis equation like a distance

    # couplings, in the order they depend on each other
    def couple(self, pose: dict) -> dict:
        for _ in range(len(self.led) + 1):
            changed = False
            for c in self.spec.couplings:
                d = pose.get(c.driver)
                if d is None:
                    continue
                f = list(pose.get(c.follower) or _vals(self.js[c.follower], 0.0))
                v = c.value(float(d[0]))
                if abs(f[0] - v) > 1e-15:
                    f[0] = v
                    pose[c.follower] = f
                    changed = True
            if not changed:
                break
        return pose

    def motion(self, pid: str, pose: dict):
        return self.spec.motion(pid, pose)

    def residual(self, pose: dict) -> np.ndarray:
        out = []
        for lp in self.spec.loops:
            at = np.append(np.asarray(lp.at, float), 1.0)
            Ma, Mb = self.motion(lp.a, pose), self.motion(lp.b, pose)
            out.append((Ma @ at - Mb @ at)[:3])
            if lp.axis is not None:
                u = np.asarray(lp.axis, float) / np.linalg.norm(lp.axis)
                out.append(np.cross(Ma[:3, :3] @ u, Mb[:3, :3] @ u) * self.scale)
        return np.concatenate(out) if out else np.zeros(0)

    def unknowns(self, driven: set) -> list:
        """(joint id, dof) that the loops must solve: in a loop part's chain, not driven, not set by a coupling."""
        seen, out = set(), []
        for lp in self.spec.loops:
            for pid in (lp.a, lp.b):
                for j in self.spec.chain(pid):
                    if j.kind == "fixed" or j.id in self.led or j.id in seen:
                        continue
                    seen.add(j.id)
                    for k in range(_dofs(j)):
                        if (j.id, k) not in driven:
                            out.append((j.id, k))
        return out

    def _set(self, pose, unk, x):
        p = {k: list(v) for k, v in pose.items()}
        for (jid, k), val in zip(unk, x):
            p.setdefault(jid, _vals(self.js[jid], 0.0))
            p[jid][k] = float(val)
        return self.couple(p)

    def solve(self, pose: dict, unk: list, guess=None, max_iter: int = 60) -> tuple[dict, dict]:
        """Close every loop by moving the unknowns, from guess (their current values in pose by default)."""
        pose = self.couple({k: list(v) for k, v in pose.items()})
        if not self.spec.loops:
            return pose, {"closed": True, "residual_mm": 0.0, "iterations": 0, "conditioning": None}
        x = np.array([pose.get(j, _vals(self.js[j], 0.0))[k] for j, k in unk] if guess is None else guess, float)
        if not unk:
            r = self.residual(pose)
            e = float(np.max(np.abs(r))) if len(r) else 0.0
            return pose, {"closed": e < CLOSE_TOL * 10, "residual_mm": e, "iterations": 0, "conditioning": None}
        step = np.array([1e-4] * len(unk))

        def R(xv):
            return self.residual(self._set(pose, unk, xv))

        def J(xv):
            cols = []
            for i in range(len(xv)):
                h = np.zeros(len(xv))
                h[i] = step[i]
                cols.append((R(xv + h) - R(xv - h)) / (2 * step[i]))
            return np.stack(cols, axis=1)

        r = R(x)
        err = float(np.max(np.abs(r)))
        it = 0
        while err > CLOSE_TOL and it < max_iter:
            it += 1
            Jx = J(x)
            dx = np.linalg.lstsq(Jx, -r, rcond=None)[0]
            a, ok = 1.0, False
            n0 = float(r @ r)
            for _ in range(30):
                xn = x + a * dx
                rn = R(xn)
                if float(rn @ rn) < n0:
                    x, r, ok = xn, rn, True
                    break
                a *= 0.5
            if not ok:
                break
            err = float(np.max(np.abs(r)))
        out = self._set(pose, unk, x)
        cond = None
        if err <= CLOSE_TOL:
            s = np.linalg.svd(J(x), compute_uv=False)
            s = s[s > 1e-12 * max(float(s.max()), 1e-300)] if len(s) else s
            full = len(s) >= len(unk)
            cond = float(s.min() / s.max()) if full and len(s) else 0.0
        return out, {"closed": err <= CLOSE_TOL, "residual_mm": err, "iterations": it, "conditioning": cond}


def _out_of_range(mech, pose) -> list:
    out = []
    for jid, v in pose.items():
        j = mech.js[jid]
        for k, x in enumerate(v):
            if j.kind == "ball" and len(v) == 1:
                lo, hi = j.range
            else:
                lo, hi = _limits(j, k)
            if j.kind == "cylindrical" and k == 1 and lo == hi == 0:
                continue
            if x < min(lo, hi) - 1e-6 or x > max(lo, hi) + 1e-6:
                out.append({"joint": jid, "dof": k, "value": round(x, 6), "range": [lo, hi], "unit": _unit(j, k)})
    return out


def _d(values, t):
    """First and second time derivatives by central differences (one-sided at the ends), over a run of frames."""
    v = np.asarray(values, float)
    if len(v) < 3:
        z = np.full_like(v, np.nan)
        return z, z
    d1 = np.gradient(v, t, axis=0)
    d2 = np.gradient(d1, t, axis=0)
    return d1, d2


def _runs(ok: list) -> list:
    runs, cur = [], []
    for i, k in enumerate(ok):
        if k:
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _num(x, n=6):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return float(f"{float(x):.{n}g}")


def study(spec, drivers: list | None = None, duration_s: float = 2.0, frames: int = 49, hold: dict | None = None,
          traces: list | None = None) -> dict:
    """The kinematics of a motion: every joint's value, velocity and acceleration per frame, loops closed, points traced.

    drivers: [{"joint", "from", "to"} | {"joint", "keys": [[t, v], ...]} | {"joint", "speed", "start"} |
    {"joint", "sine": {"amplitude", "center", "period_s", "phase_deg"}}], each with an optional "dof" (a cylindrical or
    ball joint). hold: {joint id: value} for joints nobody drives and no loop moves (else 0). traces: [{"part", "at":
    [x, y, z], "label"}] points in the assembled frame (every joint at 0) carried by a part."""
    from .recipes.assembly import Assembly
    if not isinstance(spec, Assembly):
        raise MotionError("study() needs an Assembly.")
    probs = spec.validate(10 ** 6)
    probs = [x for x in probs if "names solid" not in x and "same solid" not in x]
    if probs:
        raise MotionError(" ".join(probs))
    duration = float(duration_s)
    if not duration > 0:
        raise MotionError("duration_s must be positive.")
    n = int(frames)
    if not 2 <= n <= MAX_FRAMES:
        raise MotionError(f"frames is 2 to {MAX_FRAMES}.")
    mech = Mechanism(spec)
    drv = [_driver(spec, d, duration) for d in (drivers or default_drivers(spec))]
    driven = {(jid, k) for jid, k, _, _ in drv}
    if len(driven) != len(drv):
        raise MotionError("Two drivers drive the same joint.")
    for jid, _, _, _ in drv:
        if jid in mech.led:
            raise MotionError(f"Joint “{jid}” is driven by a coupling ({mech.led[jid].label or mech.led[jid].kind}); drive "
                              f"“{mech.led[jid].driver}” instead.")
    unk = mech.unknowns(driven)
    base = {j.id: _vals(j, (hold or {}).get(j.id, 0.0)) for j in spec.joints if j.kind != "fixed"}
    for k in (hold or {}):
        if k not in base:
            raise MotionError(f"hold names unknown or fixed joint “{k}”.")
    # does the design close at rest? (A Loop's point is common to both parts at 0 by definition, but a coupling's
    # offset can move a joint of the loop away from 0.)
    r0 = mech.residual(mech.couple({j: [0.0] * len(v) for j, v in base.items()}))
    gap0 = float(np.max(np.abs(r0))) if len(r0) else 0.0
    if gap0 > 0.01:
        raise MotionError(f"The loops do not close at rest: with every joint at 0 and the couplings applied, the pinned "
                          f"points are {gap0:.3f} mm apart. Check the couplings' offsets on joints inside a loop.")
    ts = np.linspace(0.0, duration, n)
    rows, prev = [], None
    for i, t in enumerate(ts):
        pose = {k: list(v) for k, v in base.items()}
        for jid, k, f, _ in drv:
            pose[jid][k] = f(float(t))
        guess = None
        if prev is not None:
            guess = [prev[j][k] for j, k in unk]
        sol, info = mech.solve(pose, unk, guess)
        if not info["closed"] and prev is not None:       # continuation in smaller steps from the last closed frame
            sol, info = _substep(mech, prev, pose, unk, drv)
        rows.append({"t": float(t), "pose": sol, **info})
        if info["closed"]:
            prev = sol
    # branch jumps: a solved joint that leaps between neighbouring closed frames
    for a, b in zip(rows, rows[1:]):
        if a["closed"] and b["closed"] and unk:
            jump = max(abs(b["pose"][j][k] - a["pose"][j][k]) for j, k in unk)
            step = max((abs(b["pose"][j][k] - a["pose"][j][k]) for j, k in driven), default=0.0)
            if jump > max(30.0, 10 * step):
                b["branch_jump"] = True
    out_frames = []
    for r in rows:
        f = {"t": round(r["t"], 9), "closed": r["closed"], "residual_mm": _num(r["residual_mm"], 3),
             "pose": {j: _public(mech.js[j], v) for j, v in r["pose"].items()}}
        if r.get("conditioning") is not None:
            f["conditioning"] = _num(r["conditioning"], 4)
            f["singular"] = r["conditioning"] < SINGULAR
        oor = _out_of_range(mech, r["pose"]) if r["closed"] else []
        if oor:
            f["out_of_range"] = oor
        if r.get("branch_jump"):
            f["branch_jump"] = True
        out_frames.append(f)
    ok = [r["closed"] for r in rows]
    runs = _runs(ok)
    # joints: value, velocity, acceleration per frame (None where a frame does not close)
    joints = []
    for j in spec.joints:
        if j.kind == "fixed":
            continue
        for k in range(_dofs(j)):
            vals = [r["pose"][j.id][k] if r["closed"] else None for r in rows]
            vel, acc = [None] * n, [None] * n
            for run in runs:
                d1, d2 = _d([vals[i] for i in run], ts[run])
                for q, i in enumerate(run):
                    vel[i], acc[i] = _num(d1[q]), _num(d2[q])
            role = ("driven" if (j.id, k) in driven else "coupled" if j.id in mech.led and k == 0
                    else "solved (loop)" if (j.id, k) in unk else "held")
            u = _unit(j, k)
            joints.append({"joint": j.id, "label": j.label, "kind": j.kind, "dof": k, "role": role, "unit": u,
                           "range": list(_limits(j, k)), "value": [_num(x, 9) for x in vals], "velocity": vel,
                           "acceleration": acc, "units": {"value": u, "velocity": f"{u}/s", "acceleration": f"{u}/s²"}})
    # traces
    tr_out = []
    for k, tr in enumerate(traces or []):
        pid = tr.get("part")
        if pid not in {p.id for p in spec.parts}:
            raise MotionError(f"Trace {k + 1}: unknown part “{pid}”.")
        at = np.append(np.asarray(tr.get("at", (0, 0, 0)), float), 1.0)
        P = [(mech.motion(pid, r["pose"]) @ at)[:3] if r["closed"] else None for r in rows]
        vel, acc = [None] * n, [None] * n
        for run in runs:
            d1, d2 = _d(np.array([P[i] for i in run]), ts[run])
            for q, i in enumerate(run):
                vel[i], acc[i] = d1[q], d2[q]
        sp = [float(np.linalg.norm(v)) if v is not None and np.all(np.isfinite(v)) else None for v in vel]
        ac = [float(np.linalg.norm(a)) if a is not None and np.all(np.isfinite(a)) else None for a in acc]
        smax = max(((s, i) for i, s in enumerate(sp) if s is not None), default=(None, None))
        amax = max(((s, i) for i, s in enumerate(ac) if s is not None), default=(None, None))
        pts = [x for x in P if x is not None]
        tr_out.append({"part": pid, "label": tr.get("label") or f"Point on {pid}", "at": [float(x) for x in at[:3]],
                       "positions_mm": [[_num(c, 9) for c in x] if x is not None else None for x in P],
                       "velocity_mm_s": [[_num(c) for c in v] if v is not None and np.all(np.isfinite(v)) else None for v in vel],
                       "acceleration_mm_s2": [[_num(c) for c in a] if a is not None and np.all(np.isfinite(a)) else None for a in acc],
                       "speed_mm_s": [_num(s) for s in sp], "accel_mm_s2": [_num(a) for a in ac],
                       "max_speed_mm_s": _num(smax[0]), "max_speed_t": _num(ts[smax[1]]) if smax[1] is not None else None,
                       "max_accel_mm_s2": _num(amax[0]), "max_accel_t": _num(ts[amax[1]]) if amax[1] is not None else None,
                       "path_length_mm": _num(sum(float(np.linalg.norm(b - a)) for a, b in zip(pts, pts[1:]))),
                       "bbox_mm": [[_num(x) for x in np.min(pts, 0)], [_num(x) for x in np.max(pts, 0)]] if pts else None})
    bad = [f["t"] for f in out_frames if not f["closed"]]
    sing = [f["t"] for f in out_frames if f.get("singular")]
    oor = [f["t"] for f in out_frames if f.get("out_of_range")]
    notes = []
    if spec.loops:
        notes.append(f"{len(spec.loops)} closed loop{'s' if len(spec.loops) != 1 else ''} solved per frame by Newton's method "
                     f"on the loop-closure equations (to {CLOSE_TOL:g} mm), continued from the previous frame.")
    if bad:
        notes.append(f"{len(bad)} of {n} frames do not close: the linkage cannot reach those driver values (from t = "
                     f"{bad[0]:g} s). Those frames have no pose.")
    if sing:
        notes.append(f"{len(sing)} frames are near a dead point (the closure Jacobian is nearly singular): small driver "
                     "motion gives large or undefined motion there.")
    if oor:
        notes.append(f"{len(oor)} frames move a joint outside its declared range.")
    notes.append("Velocities and accelerations are central differences in time on the solved positions (one-sided at the "
                 f"ends of each run of frames), at {n} frames over {duration:g} s.")
    return {"version": VERSION, "evidence": EVIDENCE_KIN, "duration_s": duration, "frames": out_frames,
            "times": [round(float(t), 9) for t in ts], "drivers": [x[3] for x in drv],
            "solved": [{"joint": j, "dof": k} for j, k in unk],
            "couplings": [{"driver": c.driver, "follower": c.follower, "kind": c.kind, "ratio": c.ratio, "offset": c.offset,
                           "label": c.label} for c in spec.couplings],
            "loops": [{"a": lp.a, "b": lp.b, "at": list(lp.at), "pin": lp.axis is not None, "label": lp.label} for lp in spec.loops],
            "joints": joints, "traces": tr_out, "closed_frames": int(sum(ok)), "open_frames": bad,
            "singular_frames": sing, "out_of_range_frames": oor, "notes": notes}


def _substep(mech, prev, pose, unk, drv, depth: int = 6):
    """Walk the drivers from the last closed frame to this one in halving steps, so Newton stays on the branch."""
    def walk(a, b, lvl):
        sol, info = mech.solve(b, unk, [a[j][k] for j, k in unk])
        if info["closed"] or lvl == 0:
            return sol, info
        mid = {k: list(v) for k, v in b.items()}
        for jid, k, _, _ in drv:
            mid[jid][k] = (a[jid][k] + b[jid][k]) / 2
        m, mi = walk(a, mid, lvl - 1)
        if not mi["closed"]:
            return m, mi
        return walk(m, b, lvl - 1)
    return walk(prev, pose, depth)


# ── four-bar reference (the analytic case the solver is verified against) ────────────────────────────────────────

def grashof(a: float, b: float, c: float, d: float) -> dict:
    """Grashof's condition for a four-bar with crank a, coupler b, rocker c and ground d: s + l <= p + q means at least
    one link turns fully. The class follows the shortest link: ground (double crank), crank (crank-rocker), coupler
    (double rocker), rocker (rocker-crank); otherwise a triple rocker (non-Grashof)."""
    links = {"crank": a, "coupler": b, "rocker": c, "ground": d}
    s, l = min(links.values()), max(links.values())
    pq = sum(links.values()) - s - l
    short = min(links, key=links.get)
    if s + l > pq + 1e-12:
        kind = "non-Grashof (triple rocker)"
    elif abs(s + l - pq) <= 1e-12:
        kind = "change point (s + l = p + q)"
    else:
        kind = {"ground": "double crank", "crank": "crank-rocker", "coupler": "double rocker",
                "rocker": "rocker-crank"}[short]
    return {"grashof": s + l <= pq + 1e-12, "class": kind, "s_plus_l": s + l, "p_plus_q": pq, "shortest": short}


def fourbar_rocker(a: float, b: float, c: float, d: float, theta2_deg: float, open_branch: bool = True) -> float | None:
    """The rocker angle theta4 (degrees, from the ground line) of a planar four-bar at crank angle theta2, in closed
    form (Freudenstein; Norton, Design of Machinery, eq. 4.10). None where the loop cannot close."""
    t2 = math.radians(theta2_deg)
    K1, K2, K3 = d / a, d / c, (a * a - b * b + c * c + d * d) / (2 * a * c)
    A = math.cos(t2) - K1 - K2 * math.cos(t2) + K3
    B = -2 * math.sin(t2)
    C = K1 - (K2 + 1) * math.cos(t2) + K3
    disc = B * B - 4 * A * C
    if disc < 0:
        return None
    root = math.sqrt(disc)
    return math.degrees(2 * math.atan2(-B - root if open_branch else -B + root, 2 * A))


# ── on the real design (studio process; the kernel only makes the view) ─────────────────────────────────────────

def _spec(view: dict):
    from .recipes.assembly import Assembly
    a = view.get("assembly") or {}
    if not a.get("parts"):
        raise MotionError("This design is one part: there is nothing to move. A motion study needs an assembly() with joints.")
    if a.get("error"):
        raise MotionError(f"The assembly cannot be used: {a['error']}")
    if a.get("derived"):
        raise MotionError("This design builds several bodies but does not declare how they go together or move "
                          "(assembly() with joints).")
    spec = Assembly.from_public(a)
    if not any(j.kind != "fixed" for j in spec.joints):
        raise MotionError("The assembly declares no joint that moves.")
    return spec


def part_meshes(view: dict) -> dict:
    """{part id: (P, T)} in the print frame, from the view's per-feature meshes."""
    from . import render
    acc = {}
    for m in view["mesh"]:
        pid = m.get("part")
        if not pid:
            continue
        P = render._arr(m["positions"], np.float32, 3).astype(np.float64)
        T = render._arr(m["indices"], np.uint32, 3).astype(np.int64)
        g = acc.setdefault(pid, {"P": [], "T": [], "n": 0})
        g["P"].append(P)
        g["T"].append(T + g["n"])
        g["n"] += len(P)
    return {k: (np.concatenate(g["P"]), np.concatenate(g["T"])) for k, g in acc.items()}


def _world(spec, mech, pid, pose):
    """4x4 print frame -> world at a solved pose."""
    from .recipes.assembly import placement_matrix
    p = next(x for x in spec.parts if x.id == pid)
    return mech.motion(pid, pose) @ placement_matrix(p)


def _pose_of(frame, mech) -> dict:
    return {j: _vals(mech.js[j], v) for j, v in frame["pose"].items()}


def clearance(spec, kin: dict, meshes: dict, tol: float, budget_s: float = 60.0) -> dict:
    """Clearance along the cycle: every pair moving relative to the other (not joined by a Mate or a Loop) at every
    closed frame, by collide.query on the meshes; the interval between two frames is proven free when the clearance at
    both ends exceeds how far any point moves relative to the other part between them."""
    from . import collide
    mech = Mechanism(spec)
    t0 = time.perf_counter()
    deadline = t0 + float(budget_s)
    B = {pid: collide.Body(P, T, tol) for pid, (P, T) in meshes.items()}
    ids = [p.id for p in spec.parts if p.id in B]
    lab = {p.id: p.label for p in spec.parts}
    frames = [f for f in kin["frames"] if f["closed"]]
    poses = [_pose_of(f, mech) for f in frames]
    W = [{pid: _world(spec, mech, pid, ps) for pid in ids} for ps in poses]
    pairs, joined = [], []
    for i in range(len(ids)):
        for k in range(i + 1, len(ids)):
            x, y = ids[i], ids[k]
            if spec.mate(x, y) is not None or spec.pinned(x, y) is not None:
                joined.append(f"{lab[x]} / {lab[y]}")
                continue
            rel0 = np.linalg.inv(W[0][y]) @ W[0][x] if W else None
            if W and any(np.max(np.abs(np.linalg.inv(w[y]) @ w[x] - rel0)) > 1e-9 for w in W):
                pairs.append((x, y))
    tol2 = 2 * tol
    warn = spec.clearance_warn
    cutoff = max(2.0, 4 * warn)
    per, partial = [], False
    for fi, (f, w) in enumerate(zip(frames, W)):
        if time.perf_counter() > deadline:
            partial = True
            break
        row = {"t": f["t"], "state": "clear", "clearance_mm": None, "at_least_mm": None, "pair": None, "pairs": {}}
        best = math.inf
        try:
            for x, y in pairs:
                r = collide.query(B[x], B[y], np.linalg.inv(w[y]) @ w[x], cutoff, deadline)
                st = r.state(tol2)
                row["pairs"][f"{x}|{y}"] = (0.0 if st in ("overlap", "contact") else r.d, r.exact, st,
                                           r.depth if st == "overlap" else 0.0)
                if st == "overlap":
                    if row["state"] != "overlap" or r.depth > row.get("depth_mm", 0):
                        row.update(state="overlap", depth_mm=_num(r.depth if math.isfinite(r.depth) else -1, 4),
                                   pair=[x, y], clearance_mm=0.0)
                        if r.box:
                            row["box"] = [(w[y][:3, :3] @ np.asarray(q) + w[y][:3, 3]).tolist() for q in r.box]
                    best = 0.0
                elif st == "contact" and row["state"] != "overlap":
                    row.update(state="contact", pair=[x, y], clearance_mm=0.0)
                    best = 0.0
                elif row["state"] in ("clear", "close") and r.d < best:
                    best = r.d
                    row["pair"] = [x, y]
                    if r.exact:
                        row.update(clearance_mm=_num(r.d, 5), at_least_mm=None)
                        if r.pa:
                            row["at"] = (w[y][:3, :3] @ np.asarray(r.pa) + w[y][:3, 3]).tolist()
                            row["to"] = (w[y][:3, :3] @ np.asarray(r.pb) + w[y][:3, 3]).tolist()
                        row["state"] = "close" if r.d < warn + tol2 else "clear"
                    else:
                        row.update(clearance_mm=None, at_least_mm=_num(r.d, 4))
        except collide.OutOfTime:
            partial = True
            break
        per.append(row)
    # intervals between neighbouring frames: proven free, or sampled only
    proven, sampled = [], []
    for a in range(len(per) - 1):
        ra, rb = per[a], per[a + 1]
        if ra["state"] in ("overlap", "contact") or rb["state"] in ("overlap", "contact"):
            continue
        ok = True
        for x, y in pairs:
            da, ea, _, _ = ra["pairs"][f"{x}|{y}"]
            db, eb, _, _ = rb["pairs"][f"{x}|{y}"]
            rel_a = np.linalg.inv(W[a][y]) @ W[a][x]
            rel_b = np.linalg.inv(W[a + 1][y]) @ W[a + 1][x]
            Va = B[x].V @ rel_a[:3, :3].T + rel_a[:3, 3]
            Vb = B[x].V @ rel_b[:3, :3].T + rel_b[:3, 3]
            travel = float(np.max(np.linalg.norm(Vb - Va, axis=1))) if len(Va) else 0.0
            # a chord bound: a point's path between frames bends, so allow it a quarter more than the straight line
            if (max(0.0, da - tol2) + max(0.0, db - tol2)) <= 1.25 * travel:
                ok = False
                break
        (proven if ok else sampled).append([ra["t"], rb["t"]])
    contact = [r for r in per if r["state"] in ("overlap", "contact")]
    overlap = [r for r in per if r["state"] == "overlap"]
    gaps = [r for r in per if r["state"] in ("clear", "close") and r["clearance_mm"] is not None]
    mn = min(gaps, key=lambda r: r["clearance_mm"], default=None)
    for r in per:
        r["pairs"] = {k: {"gap_mm": _num(v[0], 5) if v[1] or v[2] in ("overlap", "contact") else None,
                          "at_least_mm": None if (v[1] or v[2] in ("overlap", "contact")) else _num(v[0], 4),
                          "state": v[2], **({"depth_mm": _num(v[3], 4)} if v[2] == "overlap" else {})}
                      for k, v in r["pairs"].items()}
    lbl = lambda pr: f"{lab[pr[0]]} / {lab[pr[1]]}" if pr else ""
    if overlap:
        worst = max(overlap, key=lambda r: r.get("depth_mm") or 0)
        status, value = "FAIL", f"overlap at t = {overlap[0]['t']:g} s"
        detail = (f"{lbl(overlap[0]['pair'])} overlap from t = {overlap[0]['t']:g} s; deepest at t = {worst['t']:g} s "
                  f"(at least {worst.get('depth_mm') or 0:.2f} mm, {lbl(worst['pair'])}).")
    elif contact:
        status, value = "WARN", f"contact at t = {contact[0]['t']:g} s"
        detail = f"{lbl(contact[0]['pair'])} touch at t = {contact[0]['t']:g} s (within the mesh tolerance ±{tol2:.2f} mm)."
    elif mn is not None:
        status = "WARN" if mn["clearance_mm"] < warn else "PASS"
        value = f"{mn['clearance_mm']:.3f} mm at t = {mn['t']:g} s"
        detail = f"Smallest gap {mn['clearance_mm']:.3f} mm between {lbl(mn['pair'])} at t = {mn['t']:g} s."
    elif pairs:
        lb = min((r["at_least_mm"] for r in per if r["at_least_mm"] is not None), default=None)
        status, value = "PASS", f"> {lb:g} mm" if lb is not None else "clear"
        detail = f"No pair comes within {cutoff:g} mm at any frame."
    else:
        status, value, detail = "PASS", "nothing moves relative to anything", "No pair of parts moves relative to the other."
    if pairs and not partial:
        detail += (f" {len(per)} frames, {len(pairs)} pair{'s' if len(pairs) != 1 else ''} moving relative to each other; "
                   f"between frames {len(proven)} interval{'s' if len(proven) != 1 else ''} proven free (the clearance exceeds "
                   f"how far any point travels), {len(sampled)} sampled only.")
    if joined:
        detail += " Not compared (joined by design): " + ", ".join(joined) + "."
    if partial:
        detail += f" PARTIAL: the time budget ({budget_s:g} s) ran out after {len(per)} of {len(frames)} frames."
    return {"status": status, "value": value, "detail": detail, "evidence": EVIDENCE_CLEAR,
            "tolerance_mm": tol2, "warn_mm": warn, "pairs": [[x, y] for x, y in pairs], "joined": joined,
            "min": ({"clearance_mm": mn["clearance_mm"], "t": mn["t"], "frame": frames.index(next(f for f in frames if f["t"] == mn["t"])),
                     "pair": mn["pair"], "at": mn.get("at"), "to": mn.get("to")} if mn else None),
            "first_contact_t": contact[0]["t"] if contact else None,
            "overlap_frames": [r["t"] for r in overlap], "proven": proven, "sampled": sampled, "per_frame": per,
            "partial": partial, "seconds": round(time.perf_counter() - t0, 2)}


def torque(spec, kin: dict, masses: dict, gravity=(0.0, 0.0, -1.0), drivers: list | None = None) -> dict:
    """Holding torque (force for a slide) on each driven joint under gravity, by virtual work: tau = dV/dq with
    V = -sum(m g . c) over the parts' centres, at q +- h re-solved through the loops and couplings."""
    mech = Mechanism(spec)
    g = np.asarray(gravity, float)
    g = g / (np.linalg.norm(g) or 1.0) * G
    com0 = {pid: (m["mass_kg"], np.append(np.asarray(m["com_mm"], float), 1.0)) for pid, m in masses.items()}

    def V(pose):
        return sum(-mk * float(g @ (mech.motion(pid, pose) @ c)[:3]) for pid, (mk, c) in com0.items())   # N·mm

    drv = [_driver(spec, d, kin["duration_s"]) for d in (drivers or default_drivers(spec))]
    driven = {(jid, k) for jid, k, _, _ in drv}
    unk = mech.unknowns(driven)
    out = []
    for jid, k, _, _ in drv:
        j = mech.js[jid]
        rot = _unit(j, k) == "deg"
        h = 0.05 if rot else 0.01
        vals = []
        for f in kin["frames"]:
            if not f["closed"]:
                vals.append(None)
                continue
            base = _pose_of(f, mech)
            e = []
            for s in (+1, -1):
                ps = {a: list(b) for a, b in base.items()}
                ps[jid][k] += s * h
                sol, info = mech.solve(ps, unk, [base[a][b] for a, b in unk])
                e.append(V(sol) if info["closed"] else None)
            if None in e:
                vals.append(None)
                continue
            dq = 2 * h * (math.pi / 180 if rot else 1.0)
            tau = (e[0] - e[1]) / dq                                # N·mm per rad, or N
            vals.append(tau / 1000.0 if rot else tau)               # N·m, or N
        fin = [(abs(v), i) for i, v in enumerate(vals) if v is not None]
        mx = max(fin, default=(None, None))
        out.append({"joint": jid, "dof": k, "unit": "N·m" if rot else "N", "values": [_num(v) for v in vals],
                    "max_abs": _num(mx[0]), "max_t": kin["frames"][mx[1]]["t"] if mx[1] is not None else None})
    return {"evidence": EVIDENCE_TORQUE, "gravity": [float(x) for x in np.asarray(gravity, float)], "joints": out,
            "note": "What the driven joint must hold against gravity at each frame (quasi-static: no friction, no "
                    "inertia, no springs), from every part's mass at its centre (wave C mass properties)."}


def _masses(st, p, rev, assume):
    from . import massprops
    r = massprops.compute(st, p, frame="assembled", rev=rev, assume=assume)
    out, missing = {}, list(r.get("missing_material") or [])
    for x in r["parts"]:
        if x.get("mass_g") is not None and x["id"]:
            out[x["id"]] = {"mass_kg": x["mass_g"] / 1000.0, "com_mm": x["com_mm"]}
    return out, missing, r


def run(st, p: dict, drivers: list | None = None, duration_s: float = 2.0, frames: int = 49, hold: dict | None = None,
        traces: list | None = None, clearance_check: bool = True, torque_check: bool = True, video: bool = False,
        budget_s: float = 60.0, assume: str | None = None, gravity=(0.0, 0.0, -1.0), rev: int | None = None,
        fps: int = 24, size=(960, 720)) -> dict:
    """A motion study of a revision (head by default): kinematics, clearance along the cycle, holding torque and,
    with video=True, an MP4. Stored under artifacts/motion/ by the geometry key and the inputs."""
    from . import fsutil
    from .studio import H, StudioError
    r = st.rev(p, rev)
    gk = st.keys(p, r["n"])["geometry"]
    inputs = {"drivers": drivers, "duration_s": duration_s, "frames": frames, "hold": hold, "traces": traces,
              "clearance": bool(clearance_check), "torque": bool(torque_check), "budget_s": budget_s, "assume": assume,
              "gravity": list(gravity)}
    mats = sorted(((k, (v or {}).get("material")) for k, v in (p.get("parts") or {}).items() if isinstance(v, dict)), key=str)
    key = H("motion", VERSION, gk, inputs, p.get("material"), mats)
    d = st.dir(p["id"]) / "artifacts" / "motion"
    f = d / f"study-{key}.json"
    res = None
    if f.is_file():
        try:
            res = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            res = None
    if res is None:
        view = st.view(p, r["n"])
        try:
            spec = _spec(view)
            if not traces:
                traces = default_traces(spec, view)
            kin = study(spec, drivers, duration_s, frames, hold, traces)
        except MotionError as e:
            raise StudioError(str(e), "Joints: " + ", ".join(j["id"] for j in (view.get("assembly") or {}).get("joints", [])
                                                             if j.get("kind") != "fixed") + ".")
        res = {"project": p["id"], "rev": r["n"], "key": key, "geometry_key": gk, "inputs": inputs, **kin}
        if clearance_check:
            res["clearance"] = clearance(spec, kin, part_meshes(view), float(view.get("tol") or 0.05), budget_s)
        if torque_check:
            masses, missing, mres = _masses(st, p, r["n"], assume)
            if missing:
                res["torque"] = {"evidence": EVIDENCE_TORQUE, "joints": [], "missing_material": missing,
                                 "note": "No holding torque: these parts have no material, so no mass (never a default). "
                                         "Choose one with set_appearance, or pass assume= for a labelled what-if."}
            else:
                res["torque"] = torque(spec, kin, masses, gravity, drivers)
                res["torque"]["materials"] = {k: v.get("label") or k for k, v in (mres.get("materials") or {}).items()}
        res["summary"] = summary(res)
        d.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(res), encoding="utf-8")
        fsutil.replace(tmp, f)
    if video:
        res["video"] = film(st, p, res, fps=fps, size=size)
    res["text"] = text(res)
    return res


def default_traces(spec, view: dict) -> list:
    """Each loop's pinned point (on part a), else the centre of every part a joint moves (assembled, at rest)."""
    out = [{"part": lp.a, "at": list(lp.at), "label": lp.label or f"{lp.a} / {lp.b} pin"} for lp in spec.loops]
    if out:
        return out
    bb = {x["id"]: x.get("bbox") for x in (view.get("assembly") or {}).get("parts", [])}
    moving = []
    for j in spec.joints:
        if j.kind != "fixed":
            moving += [m for m in spec.moved_by(j.id) if m not in moving]
    for pid in moving[:4]:
        b = bb.get(pid)
        if b:
            out.append({"part": pid, "at": [(b[0][i] + b[1][i]) / 2 for i in range(3)], "label": f"Centre of {pid}"})
    return out


def summary(res: dict) -> dict:
    s = {"frames": len(res["frames"]), "closed_frames": res["closed_frames"], "duration_s": res["duration_s"]}
    c = res.get("clearance")
    if c:
        s.update(clearance_status=c["status"], clearance=c["value"], min_gap_mm=(c["min"] or {}).get("clearance_mm"),
                 min_gap_t=(c["min"] or {}).get("t"), first_contact_t=c["first_contact_t"])
    t = res.get("torque")
    if t and t.get("joints"):
        s["max_torque"] = [{"joint": x["joint"], "max_abs": x["max_abs"], "unit": x["unit"], "t": x["max_t"]} for x in t["joints"]]
    return s


def headline(res: dict) -> str:
    c = res.get("clearance") or {}
    n, ok = len(res["frames"]), res["closed_frames"]
    head = f"{ok}/{n} frames close" if res.get("loops") else f"{n} frames"
    if c:
        head += f" · clearance {c['value']}"
    t = res.get("torque") or {}
    if t.get("joints"):
        x = t["joints"][0]
        if x["max_abs"] is not None:
            head += f" · holding {x['max_abs']:.3g} {x['unit']} max ({x['joint']})"
    return head


def text(res: dict) -> str:
    out = [f"Motion study of r{res['rev']:02d}: {len(res['frames'])} frames over {res['duration_s']:g} s, driven by "
           + "; ".join(res["drivers"]) + f" ({res['evidence']})."]
    out += res.get("notes", [])
    c = res.get("clearance")
    if c:
        out.append(f"Clearance along the motion: {c['status']}, {c['value']}. {c['detail']} ({c['evidence']}, "
                   f"±{c['tolerance_mm']:.2f} mm).")
    for tr in res.get("traces", []):
        if tr["max_speed_mm_s"] is not None:
            out.append(f"{tr['label']}: path {tr['path_length_mm']:g} mm, top speed {tr['max_speed_mm_s']:g} mm/s at "
                       f"t = {tr['max_speed_t']:g} s, top acceleration {tr['max_accel_mm_s2']:g} mm/s² at t = {tr['max_accel_t']:g} s.")
    t = res.get("torque")
    if t:
        if t.get("joints"):
            for x in t["joints"]:
                if x["max_abs"] is not None:
                    out.append(f"Holding {x['joint']} against gravity: up to {x['max_abs']:.4g} {x['unit']} at t = {x['max_t']:g} s "
                               f"({t['evidence']}).")
        else:
            out.append(t["note"])
    v = res.get("video")
    if v:
        out.append(f"Film: {v['file']} ({v['frames']} frames, {v['fps']} fps)." if v.get("file") else f"No film: {v.get('error')}")
    return " ".join(out)


# ── the film (MP4 through the turntable pipeline's ffmpeg) ───────────────────────────────────────────────────────

def film(st, p: dict, res: dict, fps: int = 24, size=(960, 720)) -> dict:
    """The motion rendered from the kernel's mesh, one picture per frame (closed frames only), written as H.264 MP4 by
    ffmpeg. Refused with the reason when ffmpeg is not installed: never a GIF instead."""
    from . import animate, render
    from .studio import H, StudioError
    from .recipes.assembly import Assembly
    exe = animate.ffmpeg()
    if not exe:
        return {"error": "MP4 needs ffmpeg, which is not installed (brew install ffmpeg). The study itself is complete."}
    d = st.dir(p["id"]) / "artifacts" / "motion"
    stem = f"r{res['rev']:02d}-motion-{H(res['key'], fps, list(size))[:12]}"
    out = d / f"{stem}.mp4"
    meta = d / f"{stem}.json"
    if meta.is_file() and out.is_file():
        return json.loads(meta.read_text(encoding="utf-8")) | {"cached": True}
    view = st.view(p, res["rev"])
    spec = Assembly.from_public(view["assembly"])
    mech = Mechanism(spec)
    from .recipes.assembly import placement_matrix
    place = {x.id: placement_matrix(x) for x in spec.parts}
    meshes = [(m, render._arr(m["positions"], np.float32, 3).astype(np.float64)) for m in view["mesh"]]
    frames = [f for f in res["frames"] if f["closed"]]
    if not frames:
        raise StudioError("No frame of this motion closes, so there is nothing to film.")
    worlds = []
    for f in frames:
        ps = _pose_of(f, mech)
        worlds.append({pid: mech.motion(pid, ps) @ place[pid] for pid in place})
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for w in worlds[:: max(1, len(worlds) // 12)] + [worlds[-1]]:
        for m, P in meshes:
            M = w.get(m.get("part"))
            if M is None:
                continue
            Q = P @ M[:3, :3].T + M[:3, 3]
            lo, hi = np.minimum(lo, Q.min(0)), np.maximum(hi, Q.max(0))
    feats = [{"id": f.id, "label": f.label} for f in st.recipe(p).features]
    tr = res.get("traces") or []
    clr = {r["t"]: r for r in ((res.get("clearance") or {}).get("per_frame") or [])}
    imgs = []
    import base64
    for i, (f, w) in enumerate(zip(frames, worlds)):
        mesh = []
        for m, P in meshes:
            M = w.get(m.get("part"))
            Q = P if M is None else P @ M[:3, :3].T + M[:3, 3]
            mesh.append({**m, "positions": base64.b64encode(np.ascontiguousarray(Q.astype(np.float32)).tobytes()).decode()})
        lines = []
        for t in tr:                                         # the path so far, in signal orange
            pts = [x for x in t["positions_mm"][: res["frames"].index(f) + 1] if x is not None]
            if len(pts) > 1:
                seg = np.array([[*a, *b] for a, b in zip(pts, pts[1:])], float)
                lines.append((seg, (226, 77, 38)))
        c = clr.get(f["t"])
        cap = f"t = {f['t']:.2f} s   " + "   ".join(f"{j} {v if isinstance(v, (int, float)) else v[0]:.1f}"
                                                   for j, v in list(f["pose"].items())[:3])
        if c and c.get("clearance_mm") is not None:
            cap += f"   gap {c['clearance_mm']:.2f} mm"
        elif c and c["state"] in ("contact", "overlap"):
            cap += f"   {c['state']}"
        imgs.append(render.render_png({"mesh": mesh}, feats, camera=(-55, 26), frame_box=(lo, hi), size=size,
                                      overlay=False, title=f"{p['name']}  r{res['rev']:02d}  motion", caption=cap,
                                      lines=lines, as_image=True))
    info = animate.write_mp4(imgs, out, fps, exe)
    still = d / f"{stem}-still.png"
    imgs[len(imgs) // 3].convert("RGB").save(still)
    info |= {"kind": "motion", "rev": res["rev"], "still": str(still), "seconds": round(len(imgs) / fps, 2),
             "renderer": "Form Studio's headless renderer, from the kernel's mesh"}
    meta.write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info | {"cached": False}


# ── the Bench (form/studies.py, Wave A) ───────────────────────────────────────────────────────────────────────────

def register_studies(register):
    """Bench entries of wave I and Y: Motion (Check), Robot files and Assembly steps (Document)."""
    from .studies import Study

    def motion_key(ctx):
        from . import massprops
        from .studio import H
        return H("motion", VERSION, massprops.study_key(ctx.st, ctx.p))   # geometry and every part's material

    def robot_key(ctx):
        from . import massprops
        from .studio import H
        return H("robot", massprops.study_key(ctx.st, ctx.p))           # the inertia per link comes from the masses

    def motion_run(ctx):
        r = run(ctx.st, ctx.p)
        return {"headline": headline(r), "evidence": r["evidence"], "data": {k: r.get(k) for k in ("summary", "key", "notes")}}

    def robot_run(ctx):
        from . import robot
        r = robot.write(ctx.st, ctx.p)
        return {"headline": robot.headline(r), "evidence": r["evidence"], "files": list(r["files"].values()),
                "data": {"checks": r["checks"], "validation": r["validation"]}}

    def seq_run(ctx):
        from . import sequence
        r = sequence.plan(ctx.st, ctx.p)
        return {"headline": sequence.headline(r), "evidence": r["evidence"], "data": {"steps": r["steps"], "limits": r["limits"]}}

    register(Study("motion", "study", "Motion", "The mechanism played over time: loops closed, points traced, clearance "
                   "along the whole cycle with the smallest gap and when, holding torque under gravity.",
                   EVIDENCE_KIN, run=motion_run, key=motion_key, needs=("joints",), inputs=("geometry", "materials"),
                   app="motion", tool="motion_study", order=13))
    register(Study("robot", "document", "Robot files", "URDF, SRDF and MJCF from the parts, joints and mates, with "
                   "inertia from the B-rep and meshes per link, checked and parsed back.", "computed (B-rep)",
                   run=robot_run, key=robot_key, needs=("joints",), inputs=("geometry", "materials"), app="robot", tool="robot_files",
                   heavy=True, order=27))
    register(Study("sequence", "document", "Assembly steps", "An order the parts can go together in, each with the "
                   "straight direction it goes in, from contact normals and a collision sweep.",
                   "computed (geometric feasibility)", run=seq_run, needs=("assembly",), inputs=("geometry",),
                   app="instructions", tool="assembly_sequence", order=19))


BENCH = {"id": "motion", "group": "studies", "label": "Motion", "stage": "review", "needs": ["joints"],
         "evidence": EVIDENCE_KIN, "mcp": "motion_study", "cli": "form motion <project>"}
