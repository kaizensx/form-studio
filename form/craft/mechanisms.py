"""Mechanisms as real geometry with their numbers: hinges, snap fits, bayonets, dovetails, detents, ratchets, cams,
four-bar linkages, gear trains and planetary sets.

Every function returns a `Mech`: named build123d solids in .shapes (e.g. hinge.shapes["leaf_a"]), the numbers it was
sized from in .dims ({name: {"value", "unit", "provenance", "source"}}, the same shape as form.parts), and .checks
(rows with status PASS/WARN/FAIL and an evidence class). mech["name"] reads one dimension; mech.derived(feature)
gives Recipe.derived() rows.

Conventions (like form.parts): parts stand on z = 0 as they print; cutters open at z = 0 and go down (-Z) with a
0.2 mm overshoot; clearances are per side and are FDM assumptions ("assumed") unless you pass a measured one.

    from form.craft import mechanisms as mech
    h = mech.pin_hinge(length=60, outer_d=8, pin_d=3.6, knuckles=5, clearance=0.35, leaf_w=18, leaf_t=2.4)
    body = h.shapes["leaf_a"] + h.shapes["leaf_b"]       # two solids, printed in place, free to turn
    hinge(..., axis=h.axis, origin=h.origin)              # the joint for assembly()

Formulas, all "computed" from the stated assumptions:
  cantilever snap strain   e = 1.5 t y / L^2               (constant rectangular section, deflection y at the tip)
  annular snap strain      e = y / d                       (hoop strain of the ring that stretches over the bead)
  planetary ratio (ring fixed)  i = 1 + Zr / Zs; assembly needs Zr = Zs + 2 Zp and (Zs + Zr) % N == 0
  four-bar                 Grashof s + l <= p + q; transmission angle from the loop at every sampled crank angle
  cam                      cycloidal / harmonic rise and fall; pressure angle of a roller follower atan(s' / (rb + s))
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from build123d import (Align, Axis, Box, Cylinder, Plane, Pos, Rot, Solid, Sphere, Spline, Vector, Wire, extrude,
                       make_face, revolve)

from ._common import attempt, fail, need, num, ok, one

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)
OVERSHOOT = 0.2


def _dim(value, unit="mm", provenance="computed", source=""):
    return {"value": value, "unit": unit, "provenance": provenance, "source": source}


def overlap(a, b) -> float:
    """Volume (mm3) shared by two solids; 0 when they do not touch."""
    try:
        r = a & b
        return float(r.volume) if r is not None else 0.0
    except Exception:
        return float("nan")


def _row(id_, label, status, value, evidence="computed", detail=""):
    return {"id": id_, "label": label, "status": status, "value": value, "evidence": evidence, "detail": detail}


@dataclass
class Mech:
    name: str
    shapes: dict
    dims: dict = field(default_factory=dict)
    checks: list = field(default_factory=list)
    axis: tuple | None = None
    origin: tuple | None = None
    info: dict = field(default_factory=dict)

    def __getitem__(self, key):
        """mech["carrier_r"] is a dimension's value; mech["sun"] (a name in .shapes) is that solid."""
        if key in self.dims:
            return self.dims[key]["value"]
        if key in self.shapes:
            return self.shapes[key]
        raise KeyError(f"{self.name} has no dimension or shape {key!r}; dims: {', '.join(self.dims)}; "
                       f"shapes: {', '.join(self.shapes)}")

    @property
    def shape(self):
        """All shapes fused (or the single one)."""
        vals = list(self.shapes.values())
        out = vals[0]
        for s in vals[1:]:
            out = out + s
        return out

    def derived(self, feature: str, prefix: str = "") -> list[dict]:
        return [{"key": prefix + k, "label": k.replace("_", " "), "value": d["value"], "unit": d["unit"], "feature": feature,
                 "formula": d["source"] or d["provenance"], "interface": False}
                for k, d in self.dims.items() if isinstance(d["value"], (int, float))]


def _polygon_face(pts, plane=Plane.XZ):
    return make_face(Wire.make_polygon([plane.from_local_coords((x, y, 0)) for x, y in pts], close=True)).faces()[0]


def _prism_xz(pts, length):
    """A prism of an (x, z) outline, extruded along +Y by length and centred on Y."""
    p = extrude(_polygon_face(pts, Plane.XZ), length)
    bb = p.bounding_box()
    return Pos(0, -(bb.min.Y + bb.max.Y) / 2, 0) * p


# ---- hinges ---------------------------------------------------------------------------------------------------

def pin_hinge(length: float = 60, outer_d: float = 8, pin_d: float = 3.6, knuckles: int = 5, clearance: float = 0.35,
              leaf_w: float = 18, leaf_t: float = 2.4, gap: float | None = None) -> Mech:
    """A print-in-place pin hinge along X, centred on the origin, lying flat (leaves on z = 0, axis at z = outer_d/2).
    Leaf A (y < 0) carries the even knuckles and the pin; leaf B (y > 0) the odd knuckles, bored pin_d + 2 clearance.
    The two leaves never touch: radial clearance at the pin and around each knuckle, axial gap between knuckles."""
    L = num(length, "length", lo=10)
    D = num(outer_d, "outer_d", lo=3)
    pd = num(pin_d, "pin_d", lo=1.2)
    k = num(knuckles, "knuckles", lo=3, hi=15, integer=True)
    c = num(clearance, "clearance", lo=0.1, hi=1.0)
    w = num(leaf_w, "leaf_w", lo=3)
    t = num(leaf_t, "leaf_t", lo=0.8)
    g = num(gap if gap is not None else max(c, 0.3), "gap", lo=0.1)
    need(pd + 2 * c + 1.6 <= D, f"pin_d {pd:g} + 2 x clearance leaves under 0.8 mm of knuckle wall in a {D:g} mm knuckle",
         "Use a larger outer_d or a thinner pin.", ["outer_d", "pin_d", "clearance"])
    need(t <= D / 2 + 1e-9, "leaf_t is thicker than the knuckle radius", "Use leaf_t <= outer_d / 2.", ["leaf_t"])
    seg = (L - (k - 1) * g) / k
    need(seg >= 2 * g + 1.5, f"{k} knuckles over {L:g} mm are only {seg:.1f} mm long", "Use fewer knuckles or a longer "
         "hinge.", ["knuckles", "length"])
    R = D / 2
    xs = [-L / 2 + i * (seg + g) for i in range(k)]                    # start x of each knuckle

    def cyl(r, x0, x1):
        return Pos(x0, 0, R) * Rot(0, 90, 0) * Cylinder(r, x1 - x0, align=BOTTOM)

    plate_a = Pos(0, -w / 2, 0) * Box(L, w, t, align=BOTTOM)
    plate_b = Pos(0, w / 2, 0) * Box(L, w, t, align=BOTTOM)
    a, b = plate_a, plate_b
    for i, x0 in enumerate(xs):
        if i % 2 == 0:
            a = a + cyl(R, x0, x0 + seg)
            b = b - cyl(R + c, x0 - g + 0.05, x0 + seg + g - 0.05)        # clear leaf B under A's knuckles
        else:
            b = b + cyl(R, x0, x0 + seg)
            a = a - cyl(R + c, x0 - g + 0.05, x0 + seg + g - 0.05)
    for i, x0 in enumerate(xs):
        if i % 2:
            b = b - cyl(pd / 2 + c, x0 - 0.1, x0 + seg + 0.1)
    a = a + cyl(pd / 2, xs[0], xs[-1] + seg)                            # the pin runs through every knuckle
    a, b = one(a), one(b)
    need(ok(a) and ok(b), "pin_hinge: a leaf did not build as a valid solid", "Change clearance or knuckle count slightly.",
         ["clearance", "knuckles"])
    need(overlap(a, b) < 1e-6, "pin_hinge: the leaves overlap", "Increase clearance.", ["clearance"])
    dims = {"knuckle_length": _dim(round(seg, 3)), "radial_clearance": _dim(c, provenance="assumed",
            source="FDM print-in-place clearance per side"), "axial_gap": _dim(g, provenance="assumed"),
            "knuckle_wall": _dim(round((D - pd - 2 * c) / 2, 3), source="(outer_d - pin_d - 2 c) / 2")}
    checks = [_row("hinge_clearance", "Print-in-place clearance", "PASS" if c >= 0.3 else "WARN", f"{c:g} mm",
                   "heuristic", "Below 0.3 mm per side, FDM hinges often fuse. Calibrate with a coupon.")]
    relief_a = relief_b = None                                         # clearance around each leaf's knuckles
    for i, x0 in enumerate(xs):
        cut = cyl(R + c, x0 - g + 0.05, x0 + seg + g - 0.05)
        if i % 2 == 0:
            relief_a = cut if relief_a is None else relief_a + cut
        else:
            relief_b = cut if relief_b is None else relief_b + cut
    return Mech("pin_hinge", {"leaf_a": a, "leaf_b": b}, dims, checks, axis=(1, 0, 0), origin=(0, 0, R),
                info={"swing": "leaf B turns about the axis; 0 deg = flat, open to 180 deg",
                      "knuckles": [(round(x0, 4), round(x0 + seg, 4), "a" if i % 2 == 0 else "b") for i, x0 in enumerate(xs)],
                      "relief_a": relief_a, "relief_b": relief_b,
                      "mounting": "Fuse leaf_a to one body and leaf_b to the other. Where a body reaches the hinge "
                                  "axis, cut info['relief_a'] from the body leaf_b is fused to (and relief_b from the "
                                  "other), or the knuckles fuse the two bodies. Place every shape with the same "
                                  "transform as the leaves."})


def living_hinge(width: float = 30, gap: float = 6, web_t: float = 0.5, panel_t: float = 3, panel_len: float = 25,
                 material: str = "PP") -> Mech:
    """Two panels joined by a thin web (a living hinge), lying flat: panels side by side along Y, web on the bed.
    The web is filleted into the panels so it bends along its length instead of cracking at the root."""
    W = num(width, "width", lo=4)
    G = num(gap, "gap", lo=1)
    t = num(web_t, "web_t", lo=0.2, hi=1.5)
    T = num(panel_t, "panel_t", lo=t + 0.6)
    P = num(panel_len, "panel_len", lo=3)
    pa = Pos(0, -(G / 2 + P / 2), 0) * Box(W, P, T, align=BOTTOM)
    pb = Pos(0, (G / 2 + P / 2), 0) * Box(W, P, T, align=BOTTOM)
    web = Box(W, G + 2, t, align=BOTTOM)
    s = one(pa + pb + web)
    edges = [e for e in s.edges().filter_by(Axis.X) if abs(e.center().Z - t) < 1e-3 and abs(abs(e.center().Y) - G / 2) < 1e-3]
    from .surfaces import safe_fillet
    s = safe_fillet(s, edges, min(1.0, G / 3))
    mat = material.upper()
    good = mat in ("PP", "PE", "TPU", "NYLON", "PA")
    dims = {"web_t": _dim(t, provenance="assumed"), "bend_length": _dim(G)}
    checks = [_row("living_hinge_material", "Living-hinge material", "PASS" if good else "WARN", mat, "heuristic",
                   "Polypropylene, PE, nylon and TPU flex for thousands of cycles; PLA and PETG crack after a few."),
              _row("living_hinge_web", "Web thickness", "PASS" if 0.3 <= t <= 0.8 else "WARN", f"{t:g} mm", "heuristic",
                   "0.3-0.8 mm is the usual printed web; print it flat with the lines across the bend.")]
    return Mech("living_hinge", {"hinge": s}, dims, checks, axis=(1, 0, 0), origin=(0, 0, t / 2))


# ---- snap fits ------------------------------------------------------------------------------------------------

def cantilever_snap(length: float = 12, thickness: float = 1.6, width: float = 6, undercut: float = 0.8,
                    lead_angle: float = 30, return_angle: float = 90, allow_strain: float = 0.02) -> Mech:
    """A cantilever snap hook standing on z = 0: the beam rises along +Z (thickness along X from 0 to t, width centred on
    Y), the hook lip at the top points +X by `undercut`. lead_angle is the ramp that pushes it in (from the beam
    axis), return_angle the retaining face (90 = permanent, 45 = releasable). Strain e = 1.5 t y / L^2 (computed)."""
    L = num(length, "length", lo=3)
    t = num(thickness, "thickness", lo=0.6)
    w = num(width, "width", lo=1)
    y = num(undercut, "undercut", lo=0.1)
    la = num(lead_angle, "lead_angle", lo=10, hi=60)
    ra = num(return_angle, "return_angle", lo=30, hi=90)
    allow = num(allow_strain, "allow_strain", lo=0.001, hi=0.2)
    lead_h = y / math.tan(math.radians(la))
    ret_h = 0.0 if ra >= 89.999 else y / math.tan(math.radians(ra))
    lip_h = max(1.0, 0.6 * t)
    z0 = L                                                    # the hook's retaining face starts at the beam's length
    pts = [(0, 0), (t, 0), (t, z0), (t + y, z0 + ret_h), (t + y, z0 + ret_h + lip_h * 0.3),
           (t, z0 + ret_h + lip_h * 0.3 + lead_h), (0, z0 + ret_h + lip_h * 0.3 + lead_h)]
    hook = _prism_xz(pts, w)
    e = 1.5 * t * y / L ** 2
    dims = {"strain": _dim(round(e, 5), "", source="1.5 t y / L^2 (constant section)"), "beam_length": _dim(L),
            "undercut": _dim(y), "total_height": _dim(round(pts[-1][1], 3))}
    st = "PASS" if e <= allow else "FAIL"
    checks = [_row("snap_strain", "Snap hook strain", st, f"{e * 100:.2f} % (allowed {allow * 100:.1f} %)",
                   "computed" if allow_strain != 0.02 else "heuristic",
                   "Allowed strain is a material value; 2 % is a rule of thumb for printed PLA/PETG along the layers. "
                   "Print the beam with its length in the XY plane.")]
    return Mech("cantilever_snap", {"hook": one(hook)}, dims, checks)


def annular_snap(d: float = 20, undercut: float = 0.4, height: float = 8, wall: float = 1.6, lead_angle: float = 30,
                 clearance: float = 0.1, allow_strain: float = 0.03) -> Mech:
    """A ring bead (male, on a tube of outer diameter d) and the matching groove cutter (female). Both are rings
    around Z: the bead sits at z = height - bead height on the tube, the groove cutter at the same height in a bore of
    d + 2 clearance. Strain of the ring that stretches over the bead: y / d (computed)."""
    D = num(d, "d", lo=4)
    y = num(undercut, "undercut", lo=0.1)
    H = num(height, "height", lo=2)
    t = num(wall, "wall", lo=0.8)
    la = num(lead_angle, "lead_angle", lo=15, hi=60)
    c = num(clearance, "clearance", lo=0, hi=0.6)
    r = D / 2
    ramp = y / math.tan(math.radians(la))
    zb = H - ramp - y - 0.4
    need(zb > 0.5, "annular_snap: the bead does not fit on the tube height", "Increase height or reduce undercut.",
         ["height", "undercut"])
    prof = [(r - 0.01, zb), (r + y, zb + y), (r + y, zb + y + 0.4), (r - 0.01, zb + y + 0.4 + ramp)]
    bead = one(revolve(_polygon_face(prof), Axis.Z))
    tube = Cylinder(r, H, align=BOTTOM) - Cylinder(r - t, H + 1, align=BOTTOM)
    male = one(tube + bead)
    gprof = [(r + c - 0.2, zb - c), (r + c + y, zb + y - c), (r + c + y, zb + y + 0.4 + c), (r + c - 0.2, zb + y + 0.4 + ramp + c)]
    groove = one(revolve(_polygon_face(gprof), Axis.Z))
    e = y / D
    dims = {"strain": _dim(round(e, 5), "", source="undercut / d (hoop strain)"), "bead_z": _dim(round(zb, 3)),
            "bore_d": _dim(D + 2 * c, source="d + 2 clearance")}
    checks = [_row("annular_strain", "Annular snap strain", "PASS" if e <= allow_strain else "FAIL", f"{e * 100:.2f} %",
                   "heuristic", "The female ring must stretch by the undercut; keep it thin-walled and flexible.")]
    return Mech("annular_snap", {"male": male, "groove_cutter": groove}, dims, checks)


# ---- bayonet, dovetail, detent ----------------------------------------------------------------------------------

def bayonet(d: float = 30, height: float = 12, lugs: int = 3, lug_w: float = 6, lug_h: float = 3, lug_depth: float = 1.6,
            twist: float = 30, clearance: float = 0.3, wall: float = 2.4) -> Mech:
    """A bayonet: the male is a tube of outer diameter d with radial lugs near its top; the female cutter is the bore
    (d + 2 c) with axial entry slots and circumferential locking slots `twist` degrees long.
    The two share one frame: the cutter's floor is z = 0 and its open end is the top (entry slots run down from it);
    the male stands inside it, from z = clearance to z = height, already engaged at the entry angle. Place both with
    the SAME transform, cut the cutter from the socket body, then turn the male by about twist - 2 degrees about Z to
    show it locked. Attach the male's top end (z = height) to the other part:
        head = head - Pos(0, 0, z) * bay["female_cutter"]
        male = Pos(0, 0, z) * Rot(0, 0, twist - 2) * bay["male"]       # its top at z + height"""
    D = num(d, "d", lo=8)
    H = num(height, "height", lo=4)
    n = num(lugs, "lugs", lo=2, hi=8, integer=True)
    lw, lh, ld = num(lug_w, "lug_w", lo=1.5), num(lug_h, "lug_h", lo=1), num(lug_depth, "lug_depth", lo=0.6)
    tw = num(twist, "twist", lo=5, hi=90)
    c = num(clearance, "clearance", lo=0.1, hi=1)
    wall = num(wall, "wall", lo=0.8)
    r = D / 2
    ang_w = math.degrees(lw / r)
    need(n * (ang_w + tw) < 330, "bayonet: lugs and their twist do not fit around the circumference",
         "Use fewer or narrower lugs, or less twist.", ["lugs", "lug_w", "twist"])
    zl = H - lh - 1.0                                        # lug bottom
    # the male starts `c` above the cutter's floor, so the pair placed with one transform never touches
    tube = Pos(0, 0, c) * (Cylinder(r, H - c, align=BOTTOM) - Cylinder(r - wall, H + 1, align=BOTTOM))
    male = tube
    for i in range(n):
        lug = Rot(0, 0, i * 360 / n) * Pos(r + ld / 2 - 0.2, 0, zl) * Box(ld + 0.4, lw, lh, align=BOTTOM)
        male = male + lug
    male = one(male)
    cutter = Cylinder(r + c, H + OVERSHOOT, align=BOTTOM)
    R2 = math.hypot(r + ld, lw / 2) + c                      # the lug's square corners reach past r + ld
    for i in range(n):
        a0 = i * 360 / n
        entry = Rot(0, 0, a0) * Pos((r + R2) / 2, 0, zl - c) * Box(R2 - r + 0.4, lw + 2 * c, H - zl + c + OVERSHOOT, align=BOTTOM)
        sector = _polygon_face([(r - 0.1, zl - c), (R2, zl - c), (R2, zl + lh + c), (r - 0.1, zl + lh + c)])
        lock = Rot(0, 0, a0 - math.degrees((lw / 2 + c) / r)) * revolve(sector, Axis.Z, tw + math.degrees((lw + 2 * c) / r))
        cutter = cutter + entry + lock
    cutter = one(cutter)
    dims = {"lug_angle_deg": _dim(round(ang_w, 2), "deg"), "twist_deg": _dim(tw, "deg"), "lock_z": _dim(round(zl, 3)),
            "radial_clearance": _dim(c, provenance="assumed")}
    return Mech("bayonet", {"male": male, "female_cutter": cutter}, dims, [], axis=(0, 0, 1), origin=(0, 0, 0))


def dovetail(length: float = 40, width: float = 12, height: float = 5, angle: float = 60, clearance: float = 0.2) -> Mech:
    """A dovetail rail along Y standing on z = 0 (narrow at the root, `width` across the top) and the matching slot
    cutter (the profile grown by clearance per side, opening at z = 0 going down, overshooting above). angle: flank
    to base, degrees (60 is the usual dovetail; 90 would be a plain key)."""
    L = num(length, "length", lo=4)
    W = num(width, "width", lo=3)
    H = num(height, "height", lo=1)
    a = num(angle, "angle", lo=45, hi=85)
    c = num(clearance, "clearance", lo=0, hi=1)
    inset = H / math.tan(math.radians(a))
    need(W - 2 * inset >= 1.0, "dovetail: the root is narrower than 1 mm", "Make it wider or lower, or steepen angle.",
         ["width", "height", "angle"])
    male = _prism_xz([(-(W / 2 - inset), 0), (W / 2 - inset, 0), (W / 2, H), (-W / 2, H)], L)
    ci = c / math.sin(math.radians(a))
    cut = _prism_xz([(-(W / 2 - inset) - ci, OVERSHOOT), ((W / 2 - inset) + ci, OVERSHOOT), (W / 2 + ci, -H - c),
                     (-W / 2 - ci, -H - c)], L + 2 * OVERSHOOT)
    dims = {"root_w": _dim(round(W - 2 * inset, 3)), "top_w": _dim(W), "clearance": _dim(c, provenance="assumed")}
    checks = [_row("dovetail_clearance", "Dovetail clearance", "PASS" if c >= 0.15 else "WARN", f"{c:g} mm", "heuristic",
                   "Slide fits on FDM need about 0.15-0.25 mm per side; print a coupon to tune it.")]
    return Mech("dovetail", {"male": one(male), "slot_cutter": one(cut)}, dims, checks)


def detent(ball_d: float = 3.0, depth: float = 0.8, clearance: float = 0.1) -> Mech:
    """A spherical detent: the bump (a cap `depth` high on z = 0) and the dimple cutter (opening at z = 0, going
    down). Use the bump on one part and dimples at each rest position on the other."""
    r = num(ball_d, "ball_d", lo=1) / 2
    h = num(depth, "depth", lo=0.2)
    need(h < r, "detent: depth must be less than the ball radius", "Use a shallower detent.", ["depth"])
    c = num(clearance, "clearance", lo=0, hi=0.5)
    bump = (Pos(0, 0, h - r) * Sphere(r)) & Box(4 * r, 4 * r, h + 0.01, align=BOTTOM)
    rc = r + c
    dim = (Pos(0, 0, rc - (h + c)) * Sphere(rc)) & Pos(0, 0, OVERSHOOT) * Box(4 * rc, 4 * rc, h + c + OVERSHOOT,
                                                                              align=(Align.CENTER, Align.CENTER, Align.MAX))
    return Mech("detent", {"bump": one(bump), "dimple_cutter": one(dim)},
                {"cap_d": _dim(round(2 * math.sqrt(r * r - (r - h) ** 2), 3), source="2 sqrt(r^2 - (r - h)^2)")})


# ---- ratchet and cam -------------------------------------------------------------------------------------------

def ratchet(teeth: int = 16, od: float = 40, tooth_h: float = 3, thickness: float = 6, bore: float = 8,
            pawl_len: float = 22) -> Mech:
    """A ratchet wheel (sawtooth: radial locking face, sloped back) centred on the origin, and a pawl lying beside it
    (pivot hole at its left end, tip shaped to the tooth). The wheel turns counter-clockwise freely."""
    n = num(teeth, "teeth", lo=6, hi=120, integer=True)
    R = num(od, "od", lo=10) / 2
    th = num(tooth_h, "tooth_h", lo=0.8)
    T = num(thickness, "thickness", lo=1.5)
    b = num(bore, "bore", lo=0)
    need(R - th - b / 2 >= 2, "ratchet: under 2 mm of wheel between bore and tooth roots", "Smaller bore or teeth.",
         ["bore", "tooth_h"])
    pts = []
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        pts += [((R - th) * math.cos(a0), (R - th) * math.sin(a0)), (R * math.cos(a1 - 1e-3), R * math.sin(a1 - 1e-3))]
    face = make_face(Wire.make_polygon([Vector(x, y, 0) for x, y in pts], close=True)).faces()[0]
    wheel = extrude(face, T)
    if b:
        wheel = wheel - Cylinder(b / 2, T + 1, align=BOTTOM)
    PL = num(pawl_len, "pawl_len", lo=8)
    pw = max(4.0, th * 1.6)
    pawl_pts = [(0, -pw / 2), (PL - th, -pw / 2), (PL, -pw / 2 + th * 0.2), (PL, pw / 2 - th), (PL - th * 1.2, pw / 2), (0, pw / 2)]
    pf = make_face(Wire.make_polygon([Vector(x, y, 0) for x, y in pawl_pts], close=True)).faces()[0]
    pawl = Pos(R + 8, -R - pw, 0) * (extrude(pf, T) + Cylinder(pw / 2, T, align=BOTTOM) - Cylinder(1.7, T + 1, align=BOTTOM))
    dims = {"tooth_pitch": _dim(round(2 * math.pi * R / n, 3), source="pi od / teeth"), "index_deg": _dim(round(360 / n, 3), "deg")}
    return Mech("ratchet", {"wheel": one(wheel), "pawl": one(pawl)}, dims)


def _motion(kind, u):
    if kind == "cycloidal":
        return u - math.sin(2 * math.pi * u) / (2 * math.pi), 1 - math.cos(2 * math.pi * u)
    if kind == "harmonic":
        return (1 - math.cos(math.pi * u)) / 2, math.pi / 2 * math.sin(math.pi * u)
    raise fail(f"Unknown cam motion {kind!r}", "Use cycloidal or harmonic.", ["kind"])


def cam(base_r: float = 15, lift: float = 6, rise: float = 150, dwell_top: float = 30, fall: float = 150,
        kind: str = "cycloidal", thickness: float = 6, bore: float = 6, follower_r: float = 0, samples: int = 180) -> Mech:
    """A plate cam centred on the origin: rise over `rise` degrees, dwell, fall, dwell at the base circle. With a
    roller follower (follower_r > 0) the plate is the pitch curve offset inward by the roller radius."""
    rb = num(base_r, "base_r", lo=3)
    h = num(lift, "lift", lo=0.2)
    r1, d1, f1 = num(rise, "rise", lo=10, hi=340), num(dwell_top, "dwell_top", lo=0, hi=300), num(fall, "fall", lo=10, hi=340)
    need(r1 + d1 + f1 <= 360, "cam: rise + dwell + fall exceed 360 degrees", "Shorten one of them.", ["rise", "dwell_top", "fall"])
    T, b, fr = num(thickness, "thickness", lo=1), num(bore, "bore", lo=0), num(follower_r, "follower_r", lo=0)
    N = num(samples, "samples", lo=36, hi=720, integer=True)

    def s_of(deg):
        deg %= 360
        if deg < r1:
            s, ds = _motion(kind, deg / r1)
            return h * s, h * ds / math.radians(r1)
        if deg < r1 + d1:
            return h, 0.0
        if deg < r1 + d1 + f1:
            s, ds = _motion(kind, (deg - r1 - d1) / f1)
            return h * (1 - s), -h * ds / math.radians(f1)
        return 0.0, 0.0

    pts, pa_max = [], 0.0
    for i in range(N):
        a = 360 * i / N
        s, ds = s_of(a)
        r = rb + s
        if fr:
            pa_max = max(pa_max, abs(math.degrees(math.atan2(ds, r))))
        pts.append(Vector(r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), 0))
    face = make_face(Wire([Spline(*pts, periodic=True)])).faces()[0]
    plate = extrude(face, T)
    if fr:
        from build123d import offset

        def by_offset():
            return one(extrude(offset(face, -fr), T))

        def by_normals():
            # the roller's inner envelope point by point: each pitch point moved inward along the curve's normal
            # (some OCCT builds fail a negative 2D offset of a periodic spline)
            q = []
            for i in range(N):
                p0, p1 = pts[i - 1], pts[(i + 1) % N]
                tx, ty = p1.X - p0.X, p1.Y - p0.Y
                L = math.hypot(tx, ty) or 1.0
                nx, ny = ty / L, -tx / L                       # outward normal of a counter-clockwise curve
                q.append(Vector(pts[i].X - fr * nx, pts[i].Y - fr * ny, 0))
            return one(extrude(make_face(Wire([Spline(*q, periodic=True)])).faces()[0], T))

        # the normals first: OCCT's negative 2D offset of a periodic spline can crash the process outright (seen on
        # x86-64 macOS), which no fallback can catch; the kernel offset stays as the second try
        plate = attempt("cam", [("offset along the normals", by_normals), ("2D offset of the pitch curve", by_offset)],
                        "Use a smaller follower radius than the cam's smallest radius of curvature.", ["follower_r"])
    if b:
        plate = plate - Cylinder(b / 2, T + 1, align=BOTTOM)
    dims = {"base_r": _dim(rb), "lift": _dim(h), "max_r": _dim(rb + h)}
    checks = []
    if fr:
        dims["pressure_angle_max"] = _dim(round(pa_max, 2), "deg", source="atan(s' / (rb + s)), roller pitch curve")
        checks.append(_row("cam_pressure", "Cam pressure angle", "PASS" if pa_max <= 30 else "WARN", f"{pa_max:.1f} deg",
                           "computed", "Above about 30 deg a translating follower jams; enlarge base_r or lengthen rise."))
    m = Mech("cam", {"cam": one(plate)}, dims, checks, axis=(0, 0, 1), origin=(0, 0, 0))
    m.info["lift_at"] = lambda deg: s_of(deg)[0]
    return m


# ---- four-bar linkage -------------------------------------------------------------------------------------------

def link(length: float, width: float = 8, thickness: float = 4, hole_d: float = 3.2) -> Solid:
    """A stadium-shaped link bar along X from (0, 0) to (length, 0), holes at both centres, standing on z = 0."""
    L, w, t, hd = num(length, "length", lo=4), num(width, "width", lo=3), num(thickness, "thickness", lo=1), num(hole_d, "hole_d", lo=0)
    need(hd <= w - 1.6, "link: hole leaves under 0.8 mm of wall", "Use a wider link or a smaller hole.", ["hole_d", "width"])
    bar = Pos(L / 2, 0, 0) * Box(L, w, t, align=BOTTOM) + Cylinder(w / 2, t, align=BOTTOM) + Pos(L, 0, 0) * Cylinder(w / 2, t, align=BOTTOM)
    if hd:
        bar = bar - Cylinder(hd / 2, t + 1, align=BOTTOM) - Pos(L, 0, 0) * Cylinder(hd / 2, t + 1, align=BOTTOM)
    return one(bar)


def link_between(p, q, width: float = 8, thickness: float = 4, hole_d: float = 3.2, z: float = 0.0) -> Solid:
    """A link bar from point p = (x, y) to q = (x, y), holes on both, standing on z: a four-bar's crank, coupler or
    rocker placed where four_bar_pose() puts it (pins along Z)."""
    (x0, y0), (x1, y1) = (float(p[0]), float(p[1])), (float(q[0]), float(q[1]))
    L = math.hypot(x1 - x0, y1 - y0)
    need(L >= 4, f"link_between: the points are {L:.2f} mm apart", "Links need at least 4 mm between their holes.", ["p", "q"])
    return one(Pos(x0, y0, z) * Rot(0, 0, math.degrees(math.atan2(y1 - y0, x1 - x0))) * link(L, width, thickness, hole_d))


def four_bar_pose(ground: float, crank: float, coupler: float, rocker: float, crank_deg: float, branch: int = 1) -> dict:
    """Where a four-bar sits at one crank angle: A = (0, 0) and D = (ground, 0) are the ground pivots, B the crank
    end, C the rocker end (branch +1 or -1 picks the assembly mode). Returns {"A", "B", "C", "D", "coupler_deg",
    "rocker_deg", "transmission_deg"}; build the links with link_between(A, B), (B, C), (D, C)."""
    g, a, b, c = (num(x, n, positive=True) for x, n in ((ground, "ground"), (crank, "crank"), (coupler, "coupler"), (rocker, "rocker")))
    th = math.radians(num(crank_deg, "crank_deg"))
    B = (a * math.cos(th), a * math.sin(th))
    dx, dy = g - B[0], -B[1]
    dist = math.hypot(dx, dy)
    need(abs(b - c) - 1e-9 <= dist <= b + c + 1e-9 and dist > 1e-9, f"four_bar_pose: the loop does not close at "
         f"{crank_deg:g} deg", "Choose a crank angle inside the linkage's range (four_bar() lists it).", ["crank_deg"])
    ex, ey = dx / dist, dy / dist
    x = (b * b - c * c + dist * dist) / (2 * dist)
    yy = math.sqrt(max(b * b - x * x, 0)) * (1 if branch >= 0 else -1)
    C = (B[0] + ex * x - ey * yy, B[1] + ey * x + ex * yy)
    mu = math.degrees(math.acos(max(-1, min(1, (b * b + c * c - dist * dist) / (2 * b * c)))))
    return {"A": (0.0, 0.0), "B": B, "C": C, "D": (g, 0.0),
            "coupler_deg": math.degrees(math.atan2(C[1] - B[1], C[0] - B[0])),
            "rocker_deg": math.degrees(math.atan2(C[1], C[0] - g)), "transmission_deg": round(min(mu, 180 - mu), 2)}


def four_bar(ground: float, crank: float, coupler: float, rocker: float, samples: int = 72, width: float = 8,
             thickness: float = 4, hole_d: float = 3.2) -> Mech:
    """A four-bar linkage: ground pivots A = (0, 0) and D = (ground, 0), crank AB, coupler BC, rocker DC.
    Returns its Grashof class, the sampled loop (B and C for each crank angle that closes), the rocker's swing and
    the minimum transmission angle, and the three moving links as printable bars laid out side by side."""
    g, a, b, c = (num(x, n, positive=True) for x, n in ((ground, "ground"), (crank, "crank"), (coupler, "coupler"), (rocker, "rocker")))
    L = sorted([g, a, b, c])
    grashof = L[0] + L[3] <= L[1] + L[2] + 1e-9
    shortest = min((g, "ground"), (a, "crank"), (b, "coupler"), (c, "rocker"))[1]
    kind = ("crank-rocker" if shortest == "crank" else "double-crank" if shortest == "ground" else
            "double-rocker" if shortest == "coupler" else "rocker-crank") if grashof else "non-Grashof triple-rocker"
    loop, mu_min, phis = [], 180.0, []
    for i in range(num(samples, "samples", lo=8, hi=720, integer=True)):
        th = 2 * math.pi * i / samples
        B = (a * math.cos(th), a * math.sin(th))
        dx, dy = g - B[0], -B[1]
        dist = math.hypot(dx, dy)
        if dist > b + c or dist < abs(b - c) or dist < 1e-9:
            continue
        ex, ey = dx / dist, dy / dist
        x = (b * b - c * c + dist * dist) / (2 * dist)
        yy = math.sqrt(max(b * b - x * x, 0))
        C = (B[0] + ex * x - ey * yy, B[1] + ey * x + ex * yy)
        mu = math.degrees(math.acos(max(-1, min(1, (b * b + c * c - dist * dist) / (2 * b * c)))))
        mu_min = min(mu_min, mu, 180 - mu)
        phis.append(math.degrees(math.atan2(C[1], C[0] - g)))
        loop.append({"crank_deg": round(math.degrees(th), 3), "B": B, "C": C, "transmission_deg": round(mu, 2)})
    need(bool(loop), "four_bar: the links never close a loop", "Check the lengths: coupler + rocker must reach across.",
         ["ground", "crank", "coupler", "rocker"])
    swing = (max(phis) - min(phis)) if phis else 0.0
    shapes = {"crank": link(a, width, thickness, hole_d),
              "coupler": Pos(0, width + 5, 0) * link(b, width, thickness, hole_d),
              "rocker": Pos(0, 2 * (width + 5), 0) * link(c, width, thickness, hole_d)}
    dims = {"grashof": _dim(grashof, "", source="s + l <= p + q"), "rocker_swing_deg": _dim(round(swing, 2), "deg"),
            "min_transmission_deg": _dim(round(mu_min, 2), "deg")}
    checks = [_row("four_bar_transmission", "Minimum transmission angle", "PASS" if mu_min >= 40 else "WARN",
                   f"{mu_min:.0f} deg", "computed", "Below about 40 deg the linkage binds and loses force.")]
    return Mech("four_bar", shapes, dims, checks, info={"kind": kind, "loop": loop, "full_rotation": len(loop) == samples})


# ---- gears ------------------------------------------------------------------------------------------------------

def _gw():
    from .. import parts
    return parts, parts._bd("gear")


def gear_train(module: float = 1.5, teeth: tuple = (14, 28, 14), thickness: float = 6, bores=5.0, backlash: float = 0.15,
               pressure_angle: float = 20.0) -> Mech:
    """A simple gear train: gear i+1 meshes with gear i at +X (py_gearworks profiles via form.parts). Idlers change
    direction, not ratio: ratio = z_last / z_first. Shapes are named g0, g1, ... standing on z = 0, in mesh."""
    m = num(module, "module", lo=0.5)
    zs = [num(z, "teeth", lo=6, hi=300, integer=True) for z in teeth]
    need(len(zs) >= 2, "gear_train needs at least two gears", "Pass teeth=(z1, z2, ...).", ["teeth"])
    T = num(thickness, "thickness", lo=1)
    bl = [bores] * len(zs) if isinstance(bores, (int, float)) else list(bores)
    need(len(bl) == len(zs), "gear_train: one bore per gear", "Pass bores as a number or a list as long as teeth.", ["bores"])
    parts, g = _gw()
    import numpy as np
    objs = []
    for i, z in enumerate(zs):
        o = parts._spur(m, z, T, backlash / 2, pressure_angle)
        if objs:
            o.mesh_to(objs[-1], target_dir=np.array([1.0, 0.0, 0.0]))
        objs.append(o)
    shapes = {f"g{i}": one(parts._finish_gear(o, float(bl[i]), T)) for i, o in enumerate(objs)}
    centres = [float(o.center[0]) for o in objs]
    dims = {"ratio": _dim(round(zs[-1] / zs[0], 5), "", source="z_last / z_first"),
            "centres_x": _dim(centres, "mm", source="m (z_i + z_i+1) / 2 between neighbours")}
    for i in range(len(zs) - 1):
        dims[f"centre_distance_{i}{i + 1}"] = _dim(parts.centre_distance(m, zs[i], zs[i + 1]), source="m (z1 + z2) / 2")
    return Mech("gear_train", shapes, dims, [], axis=(0, 0, 1), origin=(0, 0, 0), info={"centres": centres, "teeth": zs})


def planetary(module: float = 1.5, sun: int = 12, planet: int = 18, planets: int = 3, thickness: float = 8,
              ring_rim: float = 4, backlash: float = 0.1, sun_bore: float = 5, planet_bore: float = 3.2,
              ring_od: float | None = None, ring_height: float | None = None) -> Mech:
    """A planetary gear set standing on z = 0: sun at the origin, `planets` planets on the carrier circle, internal
    ring around them, all in mesh. Ring teeth = sun + 2 planet. Ratio with the ring fixed, sun in, carrier out:
    1 + Zr / Zs. Checks: equal spacing ((Zs + Zr) % N == 0) and neighbouring planets clear of each other.
    ring_height (default: thickness) makes the ring taller than the gears, standing on z = 0 like them: a housing
    that carries several stages, or a lip above the gears. Stages stacked in one ring share its tooth phase."""
    m = num(module, "module", lo=0.5)
    zs, zp, N = num(sun, "sun", lo=6, integer=True), num(planet, "planet", lo=6, integer=True), num(planets, "planets", lo=2, hi=8, integer=True)
    T, rim = num(thickness, "thickness", lo=1), num(ring_rim, "ring_rim", lo=1.2)
    RH = T if ring_height is None else num(ring_height, "ring_height", lo=T)
    zr = zs + 2 * zp
    need((zs + zr) % N == 0, f"planetary: {N} planets cannot be spaced evenly with sun {zs} and ring {zr} "
         f"((Zs + Zr) % N = {(zs + zr) % N})", "Change the sun or planet tooth count so (sun + ring) divides by the "
         "number of planets.", ["sun", "planet", "planets"])
    a = m * (zs + zp) / 2
    tip_p = m * (zp + 2)
    gap = 2 * a * math.sin(math.pi / N) - tip_p
    need(gap > 0.5 * m, f"planetary: neighbouring planets collide (tip gap {gap:.2f} mm)", "Use fewer planets or a larger "
         "sun.", ["planets", "sun", "planet"])
    parts, g = _gw()
    import numpy as np
    ps = g.PlanetaryGearset(zs, zr, zp, N)
    dirs = ps.get_planet_directions_distributed()
    s_obj = parts._spur(m, zs, T, backlash / 2, 20.0)
    p_objs = []
    for d in dirs:
        o = parts._spur(m, zp, T, backlash / 2, 20.0)
        o.mesh_to(s_obj, target_dir=np.array(d, dtype=float))
        p_objs.append(o)
    rd = (m * (zr + 2 * 1.2) + 2 * rim) if ring_od is None else num(ring_od, "ring_od", positive=True)
    ring_coef = max(1.5, (rd / 2 - m * zr / 2) / m)

    def ring_lib():
        r = g.SpurRingGear(zr, height=RH, module=m, backlash=backlash / 2 / m, outside_ring_coefficient=ring_coef)
        r.mesh_to(p_objs[0], target_dir=np.array(dirs[0], dtype=float))
        return one(r.build_part())

    def ring_cut():
        cutter = parts._spur(m, zr, RH + 1, -backlash, 20.0)
        return one(Cylinder(rd / 2, RH, align=BOTTOM) - Pos(0, 0, -0.5) * one(cutter.build_part()))

    ring = attempt("planetary ring", [("internal involute ring", ring_lib), ("ring cut by an external gear", ring_cut)],
                   "Change the tooth counts slightly.", ["sun", "planet"])
    shapes = {"sun": one(parts._finish_gear(s_obj, sun_bore, T)), "ring": ring}
    for i, o in enumerate(p_objs):
        shapes[f"planet{i}"] = one(parts._finish_gear(o, planet_bore, T))
    rows = [overlap(shapes["ring"], shapes[f"planet{i}"]) + overlap(shapes["sun"], shapes[f"planet{i}"]) for i in range(N)]
    centres = [(float(o.center[0]), float(o.center[1])) for o in p_objs]
    dims = {"ring_teeth": _dim(zr, "", source="Zs + 2 Zp"), "carrier_r": _dim(round(a, 4), source="m (Zs + Zp) / 2"),
            "ratio_ring_fixed": _dim(round(1 + zr / zs, 5), "", source="1 + Zr / Zs (sun in, carrier out)"),
            "planet_tip_gap": _dim(round(gap, 3), source="2 a sin(pi / N) - tip d"), "ring_od": _dim(round(rd, 3))}
    checks = [_row("planet_overlap", "Gears overlap in mesh", "PASS" if rows and max(rows) < 1e-3 else "WARN",
                   f"{max(rows) if rows else float('nan'):.4f} mm3", "computed",
                   "Volume of intersection between each planet and the sun/ring, from the solids.")]
    return Mech("planetary", shapes, dims, checks, axis=(0, 0, 1), origin=(0, 0, 0), info={"planet_centres": centres})
