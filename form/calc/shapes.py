"""The solids the calculators write. Kernel side: runs in the worker, called by the designs form/calc/design.py makes.

Every function takes the design's values (v) and returns a build123d solid. The numbers are the calculator's; nothing
here decides a dimension that carries load. Where a shape is drawn more simply than the real part (the hooks of an
extension spring, the legs of a torsion spring), the design's summary says so.
"""
from __future__ import annotations

import math

from build123d import Align, Axis, Box, Circle, Cylinder, Plane, Pos, Rot, Spline, Vector, Wire, extrude, make_face

from .. import craft
from ..craft._common import note, one
from ..recipes.base import RecipeError

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
STEPS = 24                                    # path points per coil turn
TAPERS = ("constant", "thickness_half", "width_quarter")


def _fail(msg: str, feature: str, hint: str, params: list) -> RecipeError:
    return RecipeError(msg, feature, hint, params)


def _prism_xz(pts, width):
    """An (x, z) outline extruded along Y, centred on Y."""
    face = make_face(Wire.make_polygon([Plane.XZ.from_local_coords((x, z, 0)) for x, z in pts], close=True)).faces()[0]
    p = extrude(face, width)
    bb = p.bounding_box()
    return Pos(0, -(bb.min.Y + bb.max.Y) / 2, 0) * p


# ---- snap joints ------------------------------------------------------------------------------------------------
def snap_pad(v, thick: float = 2.0):
    """The pad the hook stands on: top at z = 0."""
    t, y, w = v["thickness"], v["undercut"], v["width"]
    lx = max(3 * t, t + y + 4.0)
    return Pos(t / 2, 0, -thick) * Box(lx + 4, w + 6, thick, align=BOTTOM)


def snap_hook(v):
    """The cantilever: root on z = 0, thickness along X from 0 (the back) to t, the lip pointing +X at height l.
    taper 1: the thickness falls to one-half at the hook (the back leans in); taper 2: the width falls to one-quarter."""
    L, t, w, y = v["length"], v["thickness"], v["width"], v["undercut"]
    la, ra = v["lead_angle"], v["return_angle"]
    taper = TAPERS[int(round(v.get("taper", 0)))]
    lead_h = y / math.tan(math.radians(la))
    ret_h = 0.0 if ra >= 89.999 else y / math.tan(math.radians(ra))
    flat = max(0.4, 0.2 * t)
    back = t / 2 if taper == "thickness_half" else 0.0          # the back face's x at the hook end
    top = L + ret_h + flat + lead_h
    pts = [(0, 0), (t, 0), (t, L), (t + y, L + ret_h), (t + y, L + ret_h + flat), (t, top), (back, top), (back, L)]
    hook = _prism_xz(pts, w)
    if taper == "width_quarter":
        keep = [(-w / 2, 0), (w / 2, 0), (w / 8, L), (w / 8, top + 1), (-w / 8, top + 1), (-w / 8, L)]
        face = make_face(Wire.make_polygon([Plane.YZ.from_local_coords((yy, zz, 0)) for yy, zz in keep], close=True)).faces()[0]
        hook = craft.safe_intersect(hook, Pos(-1, 0, 0) * extrude(face, t + y + 2))
    return hook


def annular_shaft(v):
    """The beaded tube (male): outer diameter d, the bead standing undercut / 2 proud near the top."""
    m = craft.annular_snap(d=v["diameter"], undercut=v["undercut"] / 2, height=v["height"], wall=v["wall"],
                           lead_angle=v["lead_angle"], clearance=0.0)
    return m["male"]


def annular_hub(v, gap: float = 6.0):
    """The hub (female): a ring bored to d with the groove the bead snaps into, set beside the shaft."""
    d, t, H = v["diameter"], v["wall"], v["height"]
    y = v["undercut"] / 2
    m = craft.annular_snap(d=d, undercut=y, height=H, wall=v["wall"], lead_angle=v["lead_angle"], clearance=0.0)
    od = d + 2 * y + 2 * t
    ring = Cylinder(od / 2, H, align=BOTTOM) - Cylinder(d / 2, H + 1, align=BOTTOM)
    ring = ring - m["groove_cutter"]
    return Pos(d / 2 + od / 2 + y + gap, 0, 0) * one(ring)


# ---- living hinge -----------------------------------------------------------------------------------------------
def living_hinge(v):
    """Two panels joined by the web, lying flat: the web on z = 0 spanning the gap along Y, filleted into the panels."""
    W, G, t, T, P = v["width"], v["gap"], v["web_t"], v["panel_t"], v["panel_len"]
    if T < t + 0.3:
        raise _fail("The panels are not thicker than the web", "hinge", "Raise the panel thickness.", ["panel_t", "web_t"])
    pa = Pos(0, -(G / 2 + P / 2), 0) * Box(W, P, T, align=BOTTOM)
    pb = Pos(0, (G / 2 + P / 2), 0) * Box(W, P, T, align=BOTTOM)
    web = Box(W, G + 1.0, t, align=BOTTOM)
    s = one(pa + pb + web)
    r = min(0.75, G / 3, (T - t) * 0.9)
    edges = [e for e in s.edges().filter_by(Axis.X) if abs(e.center().Z - t) < 1e-3 and abs(abs(e.center().Y) - G / 2) < 1e-3]
    if r > 0.05 and edges:
        s = craft.safe_fillet(s, edges, r)
    return s


# ---- springs ----------------------------------------------------------------------------------------------------
def _smooth(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _sweep(points, d):
    path = Spline(*points)
    profile = craft.plane_on_path(path, 0.0) * Circle(d / 2)
    return craft.safe_sweep(profile, path, frenet=True)


def compression_points(v) -> tuple[list, float]:
    """(centre-line points, grind depth). Closed ends: one turn at the wire's own pitch at each end, eased into the
    working pitch; the centre line is scaled so the finished spring is exactly the free length."""
    d, D, n, L0 = v["wire_d"], v["mean_d"], v["active"], v["free_l"]
    e = 1.0 if v.get("closed", 1) >= 0.5 else 0.0
    ground = v.get("ground", 1) >= 0.5
    grind = d / 2 if ground else 0.0
    total = n + 2 * e
    rise = L0 - d + 2 * grind                      # centre line: the wire's own radius at each end, plus what is ground off
    p_act = (rise - 2 * e * d) / n
    if p_act < d * 1.02:
        raise _fail("The active coils touch: no travel left", "coil", "Make the spring longer, or use fewer coils or thinner wire.",
                    ["free_l", "active", "wire_d"])
    pts, z, r = [], 0.0, D / 2
    k = int(math.ceil(total * STEPS))
    dt = total / k
    for i in range(k + 1):
        t = i * dt
        blend = min(_smooth((t - e + 0.25) / 0.5), _smooth((total - e + 0.25 - t) / 0.5)) if e else 1.0
        pitch = d + (p_act - d) * blend
        if i:
            z += pitch * dt
        a = 2 * math.pi * t
        pts.append((r * math.cos(a), r * math.sin(a), z))
    scale = rise / z
    return [(x, y, zz * scale + d / 2 - grind) for x, y, zz in pts], grind


def spring_compression(v):
    pts, grind = compression_points(v)
    coil = _sweep(pts, v["wire_d"])
    if grind:
        keep = Box(v["mean_d"] * 2 + 4 * v["wire_d"], v["mean_d"] * 2 + 4 * v["wire_d"], v["free_l"], align=BOTTOM)
        coil = craft.safe_intersect(coil, keep)
    return coil


def _helix_close(d, D, n, z0=0.0, a0=0.0):
    k = int(math.ceil(n * 12))
    return [(D / 2 * math.cos(a0 + 2 * math.pi * n * i / k), D / 2 * math.sin(a0 + 2 * math.pi * n * i / k), z0 + d * 1.02 * n * i / k)
            for i in range(k + 1)]


def spring_extension(v):
    """The close-wound body of an extension spring. The hooks are not drawn: their form (half loop, full loop, side
    loop, swivel) is the maker's, and the sheet's hook stress is for the bend radius given, not for a drawn shape."""
    return _sweep(_helix_close(v["wire_d"], v["mean_d"], v["coils"]), v["wire_d"])


def spring_torsion(v):
    """Close-wound body with two straight legs leaving along the coil's tangent."""
    d, D, n = v["wire_d"], v["mean_d"], v["coils"]
    body = _helix_close(d, D, n)
    path = Spline(*body)
    # the coil is swept; each leg is a straight cylinder along the swept centre line's own tangent at its end, started
    # a little inside the coil so the two fuse (a straight stretch has no curvature for a swept frame to follow)
    coil = _sweep(body, d)
    legs = []
    for u, sign, length in ((0.0, -1, v["leg1"]), (1.0, 1, v["leg2"])):
        if length > 0.5:
            p, t = path.position_at(u), path.tangent_at(u) * sign
            legs.append(Plane(origin=p - t * (0.3 * d), z_dir=t) * Cylinder(d / 2, length + 0.3 * d, align=BOTTOM))
    if not legs:
        return coil
    out = coil.fuse(*legs)
    if not (out.is_valid and len(out.solids()) == 1):
        note("spring: the legs could not be fused to the coil; the body is shown without them")
        return coil
    return one(out)


# ---- fasteners --------------------------------------------------------------------------------------------------
def _size(v) -> str:
    return f"M{v['d']:g}"


def _plate(v, thick: float):
    n, pitch = int(round(v["bolts"])), v["pitch"]
    edge = max(1.5 * v["d"], 6.0)
    return Box((n - 1) * pitch + 2 * edge, 2 * edge + v["d"], thick, align=BOTTOM), [((i - (n - 1) / 2) * pitch, 0.0) for i in range(n)]


def joint_bottom(v):
    """The plate the screws go into: tap-drill holes when tapped, clearance holes for a nut otherwise."""
    from .. import parts
    plate, at = _plate(v, v["bottom_t"])
    size = _size(v)
    for x, y in at:
        if v["tapped"] >= 0.5:
            cut = parts.tap_hole(size, depth=min(v["engagement"] + v["d"] * 0.5, v["bottom_t"] - 0.6)).shape
        else:
            cut = parts.screw_clearance(size, length=v["bottom_t"] + 0.5, recess=False).shape
        plate = plate - Pos(x, y, v["bottom_t"]) * cut
    return one(plate)


def joint_top(v, head: str = "socket", gap: float = 6.0):
    """The clamped plate: ISO 273 clearance holes, counterbored for socket heads when the plate is thick enough."""
    from .. import parts
    plate, at = _plate(v, v["top_t"])
    size = _size(v)
    dk, k, _src = parts.head_dims(size, "socket") if size in parts.HEADS["socket"][1] else (0, 1e9, "")
    recess = head == "socket" and v["top_t"] >= k + 0.2 + 1.5
    for x, y in at:
        if size in parts.CLEARANCE:
            cut = parts.screw_clearance(size, length=v["top_t"] + 0.5, head="socket", recess=recess).shape
        else:
            from .fastener import HOLE
            cut = Pos(0, 0, 0.2) * Cylinder(HOLE[size] / 2, v["top_t"] + 0.9, align=(Align.CENTER, Align.CENTER, Align.MAX))
        plate = plate - Pos(x, y, v["top_t"]) * cut
    w = 2 * max(1.5 * v["d"], 6.0) + v["d"]
    return Pos(0, w + gap, 0) * one(plate)


def insert_base(v):
    return Pos(0, 0, -2.0) * Box(v["boss_d"] + 10, v["boss_d"] + 10, 2.0, align=BOTTOM)


def insert_boss(v, key: str):
    """The boss with the insert maker's pocket: outer diameter = hole + 2 × least wall."""
    from .. import parts
    boss = Pos(0, 0, -0.05) * Cylinder(v["boss_d"] / 2, v["height"] + 0.05, align=BOTTOM)
    pocket = parts.heat_insert_pocket(key)
    return boss, Pos(0, 0, v["height"]) * pocket.shape


# ---- gears ------------------------------------------------------------------------------------------------------
def _gw():
    from .. import parts
    return parts._bd("gear")


def _gear_obj(v, which: str, addendum: float = 1.0, dedendum: float = 1.25):
    g = _gw()
    z = int(round(v["z" + which]))
    x = v.get("x" + which, 0.0)
    helix = v.get("helix", 0.0)

    def make(fillet):
        kw = dict(number_of_teeth=z, module=v["module"], height=v["face"], profile_shift=x,
                  addendum_coefficient=round(addendum, 6), dedendum_coefficient=round(dedendum, 6), tip_truncation=0.0,
                  pressure_angle=math.radians(v["pressure_angle"]), backlash=v.get("backlash", 0.0) / 2 / v["module"],
                  root_fillet=fillet, enable_undercut=True)
        if helix > 1e-9:
            return g.HelicalGear(helix_angle=math.radians(helix) * (1 if which == "1" else -1), **kw)
        return g.SpurGear(**kw)

    # the root fillet is the largest of these the tooth space takes: the flanks (the involute) do not change with it
    for fillet in (0.25, 0.15, 0.08, 0.0):
        obj = make(fillet)
        try:
            part = obj.build_part()
            ok = part.is_valid and len(part.solids()) == 1
        except Exception:                                   # noqa: BLE001 - try the next fillet
            continue
        if ok:
            if fillet < 0.25:
                note(f"gear: root fillet {fillet:g} m_n on the {z}-tooth gear (0.25 m_n did not fit the tooth space)")
            return obj
    raise _fail(f"The {z}-tooth gear could not be built as a valid solid", "gear", "Change the tooth count, the profile shift or the module.",
                ["z" + which, "x" + which, "module"])


def _solid(obj, bore: float, face: float):
    part = obj.build_part()
    shape = part.solids()[0] if len(part.solids()) == 1 else part
    if bore > 0:
        c = obj.center
        shape = shape - Pos(float(c[0]), float(c[1]), -0.1) * Cylinder(bore / 2, face + 0.2, align=BOTTOM)
    return one(shape)


def gear_objects(v):
    """The two gear objects of an external pair in mesh: the pinion on the origin, the gear at the centre distance on +X."""
    import numpy as np
    a = _gear_obj(v, "1", v["ha1"] - v["x1"], v["depth"] - v["ha1"] + v["x1"])
    b = _gear_obj(v, "2", v["ha2"] - v["x2"], v["depth"] - v["ha2"] + v["x2"])
    b.mesh_to(a, target_dir=np.array([1.0, 0.0, 0.0]))
    tight = float(np.linalg.norm(np.array(b.center, dtype=float)))
    extra = v["centre"] - tight
    if extra < -2e-3:
        raise _fail(f"The centre distance ({v['centre']:.3f} mm) is tighter than the gears mesh at ({tight:.3f} mm)", "gear",
                    "Widen the centre distance or lower the profile shifts.", ["centre"])
    return a, b, max(extra, 0.0)


def gear_pinion(v):
    a, _b, _e = gear_objects(v) if "z2" in v and "ha1" in v else (_gear_obj(v, "1", 1.0, 1.25), None, 0.0)
    return _solid(a, v["bore1"], v["face"])


def gear_wheel(v):
    _a, b, extra = gear_objects(v)
    return Pos(extra, 0, 0) * _solid(b, v["bore2"], v["face"])


def gear_ring(v):
    """The internal gear: teeth pointing inward, its centre at the centre distance from the pinion (on -X so they mesh at +X)."""
    import numpy as np
    g = _gw()
    z2, m = int(round(v["z2"])), v["module"]
    ring = g.SpurRingGear(number_of_teeth=z2, module=m, height=v["face"], pressure_angle=math.radians(v["pressure_angle"]),
                          addendum_coefficient=1.25, dedendum_coefficient=1.0, outside_ring_coefficient=1.25 + v["rim"] / m,
                          backlash=v.get("backlash", 0.0) / 2 / m, root_fillet=0.2)
    pin = _gear_obj(v, "1", 1.0, 1.25)
    try:
        ring.mesh_to(pin, target_dir=np.array([1.0, 0.0, 0.0]))
    except Exception as e:                                  # noqa: BLE001 - placed by the computed centre distance instead
        note(f"gear: the ring was placed by the centre distance, not meshed by the library ({type(e).__name__})")
        ring.center = np.array([-v["centre"], 0.0, 0.0])
    part = ring.build_part()
    return one(part.solids()[0] if len(part.solids()) == 1 else part)


def gear_rack(v):
    """The rack: straight flanks at the pressure angle (the involute of an infinite gear, exact), its pitch line at the
    centre distance from the pinion's axis, running along Y."""
    m, n = v["module"], int(round(v["rack_teeth"]))
    a = math.radians(v["pressure_angle"])
    p = math.pi * m
    ha, hf, body = m, 1.25 * m, 3 * m
    thin = v.get("backlash", 0.0) / 2 / math.cos(a)
    pts = [(-(hf + body), -n * p / 2), (-(hf + body), n * p / 2)]
    for i in reversed(range(n)):
        yc = (i - (n - 1) / 2) * p
        half_p = p / 4 - thin / 2                  # half tooth thickness on the pitch line
        pts += [(-hf, yc + half_p + hf * math.tan(a)), (ha, yc + half_p - ha * math.tan(a)),
                (ha, yc - half_p + ha * math.tan(a)), (-hf, yc - half_p - hf * math.tan(a))]
    face = make_face(Wire.make_polygon([Vector(x, y, 0) for x, y in pts], close=True)).faces()[0]
    rack = extrude(face, v["face"])
    # teeth point -X toward the pinion: mirror by turning half a turn, pitch line at x = centre; shifted half a pitch so
    # a rack tooth space meets the pinion tooth on the X axis
    return Pos(v["centre"], p / 2 if n % 2 else 0.0, 0) * Rot(0, 0, 180) * one(rack)


def rack_pinion(v):
    return _solid(_gear_obj(v, "1", 1.0, 1.25), v["bore1"], v["face"])


# ---- cam --------------------------------------------------------------------------------------------------------
def cam(v, samples: int = 360):
    """The plate: the pitch curve of the motion law moved inward along its normal by the roller radius."""
    from .cam import LAWS, motion
    kind = LAWS[int(round(v["law"]))]
    Rp, Rf = v["base_r"] + v["roller_r"], v["roller_r"]
    pts = []
    for i in range(samples):
        th = 360.0 * i / samples
        s, ds, _a = motion(kind, v["lift"], v["rise"], v["dwell"], v["fall"], th)
        r, a = Rp + s, math.radians(th)
        # tangent of the pitch curve r(θ) e_r: r′ e_r + r e_θ; the inward normal is that turned +90°
        tx = ds * math.cos(a) - r * math.sin(a)
        ty = ds * math.sin(a) + r * math.cos(a)
        ln = math.hypot(tx, ty)
        pts.append(Vector(r * math.cos(a) - Rf * ty / ln, r * math.sin(a) + Rf * tx / ln, 0))
    face = make_face(Wire([Spline(*pts, periodic=True)])).faces()[0]
    plate = extrude(face, v["thickness"])
    if v["bore"] > 0:
        plate = plate - Pos(0, 0, -0.1) * Cylinder(v["bore"] / 2, v["thickness"] + 0.2, align=BOTTOM)
    return one(plate)


# ---- fit --------------------------------------------------------------------------------------------------------
def fit_housing(v):
    return one(Cylinder(v["hole_d"] / 2 + v["wall"], v["length"], align=BOTTOM) - Pos(0, 0, -0.1) * Cylinder(v["hole_d"] / 2, v["length"] + 0.2, align=BOTTOM))


def fit_shaft(v, gap: float = 6.0):
    return Pos(v["hole_d"] + 2 * v["wall"] + gap, 0, 0) * Cylinder(v["shaft_d"] / 2, v["length"] * 1.4, align=BOTTOM)


