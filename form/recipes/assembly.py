"""Assembly contract: how the printed parts of a design go together, and how they move.

A design that prints several parts side by side (``Recipe.solids > 1``) can say how they are assembled by
returning an :class:`Assembly` from ``Recipe.assembly(values)``. Everything here is plain data plus the
kinematics (4x4 matrices, numpy only); the kernel worker turns it into placed solids, interference, clearance,
motion and tool-access checks, and the studio turns it into an exploded view, a BOM and numbered assembly steps.

Frames
  *print frame*      the solids exactly as ``build()`` returns them, flat on the bed.
  *assembled frame*  each part moved by ``Pos(*move) * Rot(*rotate)`` (build123d semantics: rotate the part as
                     printed about the origin, then translate), every joint at 0. Joints, hardware and markers use
                     this frame.

Parts are picked from the result by ``solid``: the result's solids numbered 0, 1, ... by the X of their
bounding-box centre, then Y, then Z (left to right on the plate, as the print layout shows them). ``solid`` may
instead be an (x, y, z) point inside the part as built: the solid that holds it (else the nearest) is used, so a
design modelled in place (a gearbox's housing, carriers and suns all centred on one axis) never counts solids.

Kinematic tree
  Every part has at most one link to a parent: ``Part(attach="arm")`` (rigidly fixed to the arm), or a joint
  ``hinge("cup", ..., parent="arm")`` (turns relative to the arm). A part with no link is fixed to the world.
  Moving a joint moves its part and everything attached to it, at any depth: arm -> cup -> cup bolt. A joint's
  axis and origin are given in the assembled frame (all joints at 0); when a parent joint moves, the child joint's
  axis moves with it. ``parent=""`` on a joint means the world, which is how every declaration before chains
  existed reads (the joint moves only its part, since nothing was attached to it).

Joint kinds
  ``hinge`` (revolute, degrees), ``slide`` (prismatic, mm), ``cylindrical`` (turns about and slides along one axis:
  a pose value is degrees, or [degrees, mm]; ``range2`` is the slide range), ``ball`` (spherical about ``origin``: a
  pose value is degrees about ``axis``, or [rx, ry, rz] degrees about the assembled X, Y and Z axes, applied as
  build123d's Rot) and ``fixed``. Every check that sweeps a joint sweeps its first degree of freedom.

Couplings and closed loops (form/motion.py solves them)
  ``Coupling(driver, follower, ratio, offset)`` ties one joint to another: gears, a rack and pinion, a lead screw or a
  belt (follower = ratio * driver + offset, each in its own unit), or a cam (``profile``: follower value against the
  driver's angle over one turn). ``Loop(a, b, at, axis)`` closes a kinematic loop: the point ``at`` (assembled frame)
  belongs to part a and to part b and stays common to both in every pose; with ``axis`` the two parts also keep that
  axis common (a pin), without it they share only the point (a ball). A four-bar linkage is a tree (ground, crank,
  coupler; ground, rocker) plus one Loop where the coupler meets the rocker.

Joined pairs
  ``Mate(a, b, kind)`` says two parts touch or interlock by design (a pin in its hole, a thread in a thread, a
  press fit). They are not booleaned against each other; their gap is checked once against the declared
  clearance instead. Every other pair is checked at rest and through every joint's motion.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

KINDS = ("hinge", "slide", "cylindrical", "ball", "fixed")
ROTARY = ("hinge", "cylindrical", "ball")      # their first degree of freedom is an angle (degrees)
KIND_ALIAS = {"slider": "slide", "revolute": "hinge", "prismatic": "slide", "rigid": "fixed", "cylinder": "cylindrical",
              "spherical": "ball"}
DOF = {"hinge": 1, "slide": 1, "cylindrical": 2, "ball": 3, "fixed": 0}
COUPLING_KINDS = ("gear", "rack", "screw", "belt", "linear", "cam")
MATE_KINDS = ("pin", "thread", "press", "snap", "slip", "contact", "ratchet")


def _vec(v, n=3) -> tuple:
    t = tuple(float(x) for x in v)
    if len(t) != n:
        raise ValueError(f"expected {n} numbers, got {len(t)}")
    return t


@dataclass(frozen=True)
class Part:
    id: str
    label: str
    solid: int                                  # index into the result's solids, ordered by bounding-box centre X, then Y,
                                                # then Z; or an (x, y, z) point inside the part as built (the solid
                                                # holding it, else the nearest), which never needs counting
    move: tuple = (0.0, 0.0, 0.0)              # assembled placement: translation (mm) ...
    rotate: tuple = (0.0, 0.0, 0.0)            # ... after this rotation (degrees about X, Y, Z, build123d Rot)
    explode: tuple = (0.0, 0.0, 0.0)           # exploded-view offset (mm, assembled frame) at factor 1, relative to its parent
    note: str = ""                              # the assembly step for this part, in the imperative ("Press the lid on.")
    material: str = ""                          # optional; the BOM otherwise uses the slicer's filament
    attach: str = ""                            # part id this one is rigidly fixed to (moves with it); "" = no rigid parent


@dataclass(frozen=True)
class Joint:
    id: str
    label: str
    part: str                                   # the part that moves (with everything attached to it)
    kind: str                                   # "hinge" (degrees) | "slide" (mm) | "fixed" (no motion)
    axis: tuple                                 # direction, assembled frame
    origin: tuple = (0.0, 0.0, 0.0)            # a point on the hinge axis (unused for a slide)
    range: tuple = (0.0, 90.0)                 # (lo, hi) limits in degrees or mm; 0 is the assembled position
    samples: int = 13                           # coarse positions checked between lo and hi, ends included
    parent: str = ""                            # the part it moves relative to; "" = the world
    step: float = 0.0                           # > 0: a ratchet or detent; only multiples of step are positions it can rest at
    range2: tuple = (0.0, 0.0)                  # cylindrical: the slide range (lo, hi) in mm along the axis


def hinge(part: str, axis, origin, range_deg, samples: int = 13, id: str = "", label: str = "", parent: str = "",
          step: float = 0.0) -> Joint:
    """A part that turns about a line. range_deg = (lo, hi) degrees, right-handed about ``axis``."""
    lo, hi = _vec(range_deg, 2)
    return Joint(id or f"{part}_hinge", label or "Hinge", part, "hinge", _vec(axis), _vec(origin), (lo, hi), int(samples),
                 parent, float(step))


def slide(part: str, axis, range_mm, samples: int = 9, id: str = "", label: str = "", parent: str = "",
          step: float = 0.0) -> Joint:
    """A part that moves along a direction. range_mm = (lo, hi) millimetres along ``axis``."""
    lo, hi = _vec(range_mm, 2)
    return Joint(id or f"{part}_slide", label or "Slide", part, "slide", _vec(axis), (0.0, 0.0, 0.0), (lo, hi), int(samples),
                 parent, float(step))


slider = slide


def cylindrical(part: str, axis, origin, range_deg, range_mm, samples: int = 13, id: str = "", label: str = "",
                parent: str = "") -> Joint:
    """A part that turns about a line and slides along it (a shaft in a plain bearing). range_deg and range_mm are
    (lo, hi) limits; a pose value is degrees, or [degrees, mm]."""
    lo, hi = _vec(range_deg, 2)
    return Joint(id or f"{part}_cylindrical", label or "Cylindrical", part, "cylindrical", _vec(axis), _vec(origin), (lo, hi),
                 int(samples), parent, 0.0, _vec(range_mm, 2))


def ball(part: str, origin, range_deg=(-30.0, 30.0), axis=(0.0, 0.0, 1.0), samples: int = 13, id: str = "",
         label: str = "", parent: str = "") -> Joint:
    """A part that turns every way about a point (a ball joint). range_deg limits each of the three rotations; a pose
    value is degrees about ``axis``, or [rx, ry, rz] degrees about the assembled X, Y and Z axes."""
    lo, hi = _vec(range_deg, 2)
    return Joint(id or f"{part}_ball", label or "Ball joint", part, "ball", _vec(axis), _vec(origin), (lo, hi), int(samples),
                 parent, 0.0)


def fixed(part: str, parent: str, id: str = "", label: str = "") -> Joint:
    """A part fixed to another one, written as a joint (the same as ``Part(attach=parent)``)."""
    return Joint(id or f"{part}_fixed", label or "Fixed", part, "fixed", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0), 2,
                 parent, 0.0)


@dataclass(frozen=True)
class Mate:
    """Two parts that touch or interlock by design: not booleaned against each other, their gap checked instead.

    kind: pin (pin or axle in a hole), thread (thread in thread), slip (sliding fit), snap, press (intended
    interference), contact (faces that rest on each other), ratchet (a = the toothed wheel, b = the pawl in its
    locking pose). With axis= and origin=, a thread is checked for engagement and a ratchet for locking against its
    clearance (form/function_checks.py). clearance: the designed gap per side in mm (negative for
    a press fit), compared with the gap measured on the model; None = not declared.
    axis, origin (thread only): the thread's axis in the assembled frame, and a point on it. A modelled thread's phase
    (how far it is turned) is arbitrary, so Form Studio turns part a about that axis through one revolution and keeps
    the best phase; without them, crossing threads are reported, not failed."""
    a: str
    b: str
    kind: str = "pin"
    clearance: float | None = None
    label: str = ""
    axis: tuple | None = None
    origin: tuple = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Coupling:
    """One joint driven by another. follower = ratio * driver + offset, each in its own unit (degrees for a hinge, mm
    for a slide): gears turn ratio = -z_driver / z_follower (external, axes declared the same way), a rack moves
    pi * d / 360 mm per degree of its pinion, a lead screw lead / 360 mm per degree. kind "cam": the follower's value
    is read from ``profile`` ((driver degrees, follower value), ...), over one turn, linearly between points and
    repeating every 360 degrees; ratio and offset are then unused."""
    driver: str                                 # joint id
    follower: str                               # joint id
    ratio: float = 1.0
    offset: float = 0.0
    kind: str = "linear"                        # gear | rack | screw | belt | linear | cam
    label: str = ""
    profile: tuple = ()

    def value(self, x: float) -> float:
        """The follower's value when the driver is at x."""
        if self.kind != "cam":
            return self.ratio * x + self.offset
        import numpy as np
        pts = sorted((float(a) % 360.0, float(b)) for a, b in self.profile)
        xs = [a for a, _ in pts] + [pts[0][0] + 360.0]
        ys = [b for _, b in pts] + [pts[0][1]]
        t = (x - xs[0]) % 360.0 + xs[0]
        return float(np.interp(t, xs, ys))


def gears(driver: str, follower: str, teeth_driver: int, teeth_follower: int, internal: bool = False, label: str = "") -> Coupling:
    """A gear pair: the follower turns z_driver / z_follower as far, the other way round for external gears."""
    r = float(teeth_driver) / float(teeth_follower)
    return Coupling(driver, follower, r if internal else -r, 0.0, "gear", label or f"Gears {teeth_driver}:{teeth_follower}")


def rack(pinion: str, rack_joint: str, pitch_diameter: float, label: str = "") -> Coupling:
    """A rack driven by its pinion: pi * d mm per turn."""
    return Coupling(pinion, rack_joint, math.pi * float(pitch_diameter) / 360.0, 0.0, "rack", label or "Rack and pinion")


def lead_screw(screw: str, nut: str, lead: float, label: str = "") -> Coupling:
    """A nut on a turning screw: `lead` mm per turn (negative for a left-hand thread)."""
    return Coupling(screw, nut, float(lead) / 360.0, 0.0, "screw", label or f"Lead screw {lead:g} mm")


def cam(driver: str, follower: str, profile, label: str = "") -> Coupling:
    """A cam: the follower's value against the cam's angle, ((degrees, value), ...) over one turn."""
    return Coupling(driver, follower, 1.0, 0.0, "cam", label or "Cam", tuple((float(a), float(b)) for a, b in profile))


@dataclass(frozen=True)
class Loop:
    """A closed kinematic loop: the point ``at`` (assembled frame, every joint at 0) is on part a and on part b and stays
    common to both. axis: a pin's direction there (the parts also keep it common); None: they share only the point."""
    a: str
    b: str
    at: tuple
    axis: tuple | None = None
    label: str = ""


@dataclass(frozen=True)
class Access:
    """A straight tool path to a fastener: a cylinder ``length`` long that ends at ``at`` and points along ``axis``."""
    at: tuple                                   # where the tool meets the fastener (screw head), assembled frame
    axis: tuple                                 # direction the fastener is driven (the tool comes from the opposite side)
    tool_d: float = 6.0                         # tool shaft diameter, mm (a #1 Phillips / 2.5 mm hex driver is about 5–6)
    length: float = 80.0                        # straight length needed in front of the head, mm


@dataclass(frozen=True)
class Hardware:
    name: str                                   # "M3 x 10 countersunk screw"
    size: str = ""                              # "M3 x 10", "Ø1.75 x 58 mm"
    qty: int = 1
    source: str = ""                            # standard or supplier reference ("ISO 10642", "filament offcut")
    note: str = ""                              # how it is fitted (used as an assembly step)
    after: str = ""                             # part id it is fitted after; "" = after every part
    access: tuple = ()                          # Access items checked against the parts in place at that step
    url: str = ""
    grams: float | None = None                  # mass of one item, when known (form.parts hardware: computed)
    material: str = ""                          # what it is made of ("mild_steel", "brass")


# ---- kinematics (numpy only) -----------------------------------------------------------------------------
def _rot_xyz(rx, ry, rz):
    """build123d Rot(rx, ry, rz) as a matrix acting on column vectors: Rx @ Ry @ Rz."""
    import numpy as np
    a, b, c = (math.radians(x) for x in (rx, ry, rz))
    X = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    Y = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Z = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return X @ Y @ Z


def placement_matrix(p: Part):
    """4x4: print frame -> assembled frame, Pos(*move) * Rot(*rotate)."""
    import numpy as np
    M = np.eye(4)
    M[:3, :3] = _rot_xyz(*p.rotate)
    M[:3, 3] = p.move
    return M


def _axis_rot(u, deg):
    import numpy as np
    t = math.radians(deg)
    K = np.array([[0, -u[2], u[1]], [u[2], 0, -u[0]], [-u[1], u[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)


def values_of(j: Joint, value) -> list:
    """A pose value as one number per degree of freedom (missing ones are 0). A ball joint given one number keeps it
    as one: a turn about its declared axis."""
    n = DOF.get(j.kind, 1)
    if value is None:
        vals = []
    elif isinstance(value, (list, tuple)) or hasattr(value, "__len__"):
        vals = [float(x) for x in value]
    else:
        vals = [float(value)]
    if j.kind == "ball" and len(vals) == 1:
        return vals
    return (vals + [0.0] * n)[:max(n, 1)]


def joint_matrix(j: Joint, value):
    """4x4 motion of a joint at `value` (degrees or mm; a list for a cylindrical or ball joint), assembled frame."""
    import numpy as np
    M = np.eye(4)
    if j.kind == "fixed":
        return M
    v = values_of(j, value)
    if not any(v):
        return M
    n = math.sqrt(sum(a * a for a in j.axis)) or 1.0
    u = np.array(j.axis, float) / n
    o = np.array(j.origin, float)
    if j.kind == "slide":
        M[:3, 3] = u * v[0]
        return M
    R = _rot_xyz(*v) if j.kind == "ball" and len(v) == 3 else _axis_rot(u, v[0])
    M[:3, :3] = R
    M[:3, 3] = o - R @ o
    if j.kind == "cylindrical" and len(v) > 1:
        M[:3, 3] += u * v[1]
    return M


@dataclass
class Assembly:
    parts: list
    joints: list = field(default_factory=list)
    hardware: list = field(default_factory=list)
    clearance_warn: float = 0.1                 # a gap between parts under this (and over 0) is reported for review, mm
    derived: bool = False                       # made by FORM from separate solids (no assembly() declared): view only
    mates: list = field(default_factory=list)   # Mate items: pairs joined by design
    budget_s: float | None = None               # time for the assembly checks; None = the studio's [assembly].budget_s
    couplings: list = field(default_factory=list)  # Coupling items: joints driven by other joints (gears, racks, cams)
    loops: list = field(default_factory=list)   # Loop items: closed kinematic loops (form/motion.py solves them)

    def __post_init__(self):
        js = []
        for j in self.joints:                     # accept the usual synonyms (slider, revolute, ...)
            k = KIND_ALIAS.get(j.kind, j.kind)
            js.append(j if k == j.kind else Joint(**{**asdict(j), "kind": k}))
        self.joints = js

    # ---- the tree ----------------------------------------------------------------------------------------
    def link(self, pid: str):
        """(parent part id, joint or None) for a part; ("", None) for a part fixed to the world."""
        for j in self.joints:
            if j.part == pid:
                return j.parent, j
        p = next((x for x in self.parts if x.id == pid), None)
        return (p.attach if p else ""), None

    def chain(self, pid: str) -> list:
        """Joints from the root down to this part (the ones that move it), outermost first."""
        out, seen, cur = [], set(), pid
        while cur and cur not in seen:
            seen.add(cur)
            parent, j = self.link(cur)
            if j is not None:
                out.append(j)
            cur = parent
        return out[::-1]

    def ancestors(self, pid: str) -> list:
        """Part ids from the root down to this part's parent."""
        out, seen, cur = [], {pid}, self.link(pid)[0]
        while cur and cur not in seen:
            out.append(cur)
            seen.add(cur)
            cur = self.link(cur)[0]
        return out[::-1]

    def moved_by(self, joint_id: str) -> list:
        """Ids of the parts a joint moves: its part and every part below it in the tree."""
        return [p.id for p in self.parts if any(j.id == joint_id for j in self.chain(p.id))]

    def rigid_group(self, pid: str) -> str:
        """The part at the top of this part's rigid attachments (parts in one group never move relative to each other)."""
        cur, seen = pid, set()
        while cur not in seen:
            seen.add(cur)
            parent, j = self.link(cur)
            if not parent or (j is not None and j.kind != "fixed"):
                return cur
            cur = parent
        return cur

    def motion(self, pid: str, pose: dict | None = None):
        """4x4 assembled-frame motion of a part for joint values {joint id: value} (missing joints at 0)."""
        import numpy as np
        M = np.eye(4)
        for j in self.chain(pid):
            M = M @ joint_matrix(j, (pose or {}).get(j.id, 0.0))
        return M

    def world(self, pid: str, pose: dict | None = None):
        """4x4: print frame -> where the part is at this pose."""
        p = next(x for x in self.parts if x.id == pid)
        return self.motion(pid, pose) @ placement_matrix(p)

    def explode_total(self, pid: str) -> tuple:
        """Exploded-view offset of a part: its own plus every ancestor's (a child separates with its parent)."""
        by = {p.id: p for p in self.parts}
        tot = [0.0, 0.0, 0.0]
        for q in self.ancestors(pid) + [pid]:
            if q in by:
                tot = [a + b for a, b in zip(tot, by[q].explode)]
        return tuple(tot)

    def mate(self, a: str, b: str):
        return next((m for m in self.mates if {m.a, m.b} == {a, b}), None)

    def pinned(self, a: str, b: str):
        """The Loop that pins these two parts together, or None (such a pair touches by design, like a Mate)."""
        return next((lp for lp in self.loops if {lp.a, lp.b} == {a, b}), None)

    def detents(self, j: Joint) -> list:
        """The positions a ratchet joint can rest at (multiples of step within the range)."""
        lo, hi = j.range
        k0, k1 = math.ceil(lo / j.step - 1e-9), math.floor(hi / j.step + 1e-9)
        return [round(k * j.step, 9) for k in range(k0, k1 + 1)]

    # ---- validation --------------------------------------------------------------------------------------
    def validate(self, n_solids: int) -> list[str]:
        """Problems that make the assembly meaningless. Empty when it can be checked."""
        out, ids = [], [p.id for p in self.parts]
        idset = set(ids)
        if not self.parts:
            out.append("An assembly needs at least one part.")
        if len(set(ids)) != len(ids):
            out.append("Part ids must be unique.")
        used = [tuple(p.solid) if isinstance(p.solid, (tuple, list)) else p.solid for p in self.parts]
        for p in self.parts:
            if isinstance(p.solid, (tuple, list)):         # a point in the part: resolved against the built solids
                if len(p.solid) != 3:
                    out.append(f"Part {p.id}: solid as a point needs (x, y, z), got {p.solid}.")
            elif not 0 <= p.solid < n_solids:
                out.append(f"Part {p.id} names solid {p.solid}; the design has {n_solids} (0–{n_solids - 1}).")
            if p.attach:
                if p.attach == p.id:
                    out.append(f"Part {p.id} is attached to itself.")
                elif p.attach not in idset:
                    out.append(f"Part {p.id} is attached to unknown part “{p.attach}”.")
        if len(set(used)) != len(used):
            out.append("Two parts name the same solid.")
        jids = [j.id for j in self.joints]
        if len(set(jids)) != len(jids):
            out.append("Joint ids must be unique.")
        moved = {}
        for j in self.joints:
            if j.part not in idset:
                out.append(f"Joint {j.id} moves unknown part “{j.part}”.")
            if j.parent and j.parent not in idset:
                out.append(f"Joint {j.id}: parent “{j.parent}” is not a part. Name the part it is mounted on, or \"\" for the world.")
            if j.parent and j.parent == j.part:
                out.append(f"Joint {j.id} moves {j.part} relative to itself; parent must be another part.")
            if j.kind not in KINDS:
                out.append(f"Joint {j.id}: kind must be hinge, slide, cylindrical, ball or fixed (got “{j.kind}”).")
            if j.kind == "cylindrical" and not j.range2[0] <= j.range2[1]:
                out.append(f"Joint {j.id}: range2 (the slide range) must be (lo, hi) with lo <= hi.")
            if j.kind != "fixed" and sum(a * a for a in j.axis) < 1e-12:
                out.append(f"Joint {j.id}: axis is zero.")
            if j.kind != "fixed" and j.samples < 2:
                out.append(f"Joint {j.id}: sample at least 2 positions.")
            if j.kind != "fixed" and not j.range[0] < j.range[1]:
                out.append(f"Joint {j.id}: range must be (lo, hi) with lo < hi, got {tuple(j.range)}.")
            if j.step < 0 or (j.step > 0 and j.step > j.range[1] - j.range[0]):
                out.append(f"Joint {j.id}: step must be 0 (smooth) or a detent spacing inside the range.")
            if j.part in moved:
                out.append(f"Part {j.part} is moved by two joints ({moved[j.part]}, {j.id}); give it one, and mount "
                           "the second on an intermediate part.")
            moved[j.part] = j.id
            p = next((x for x in self.parts if x.id == j.part), None)
            if p is not None and p.attach:
                out.append(f"Part {p.id} is both attached to {p.attach} and moved by joint {j.id}; use one "
                           f"(the joint's parent says what it moves relative to).")
        if not out:                               # loops only make sense to look for in an otherwise sound tree
            for p in self.parts:
                cur, path = p.id, [p.id]
                while True:
                    cur = self.link(cur)[0]
                    if not cur:
                        break
                    if cur in path:
                        loop = path[path.index(cur):] + [cur]
                        out.append("Parts " + " → ".join(loop) + " form a loop; every chain must end at a part "
                                   "fixed to the world (no attach and no joint).")
                        break
                    path.append(cur)
                if out:
                    break
        for m in self.mates:
            for x in (m.a, m.b):
                if x not in idset:
                    out.append(f"Mate {m.a}/{m.b} names unknown part “{x}”.")
            if m.a == m.b:
                out.append(f"Mate {m.a}/{m.b} joins a part to itself.")
            if m.kind not in MATE_KINDS:
                out.append(f"Mate {m.a}/{m.b}: kind must be one of {', '.join(MATE_KINDS)} (got “{m.kind}”).")
            if m.axis is not None and (len(m.axis) != 3 or sum(a * a for a in m.axis) < 1e-12):
                out.append(f"Mate {m.a}/{m.b}: axis must be three numbers, not zero.")
            if len(tuple(m.origin)) != 3:
                out.append(f"Mate {m.a}/{m.b}: origin must be three numbers.")
        jd = {j.id: j for j in self.joints}
        led = {}
        for c in self.couplings:
            for x in (c.driver, c.follower):
                if x not in jd:
                    out.append(f"Coupling {c.driver}/{c.follower} names unknown joint “{x}”.")
                elif jd[x].kind == "fixed":
                    out.append(f"Coupling {c.driver}/{c.follower}: joint {x} is fixed and cannot move.")
            if c.driver == c.follower:
                out.append(f"Coupling {c.driver}/{c.follower} drives a joint by itself.")
            if c.kind not in COUPLING_KINDS:
                out.append(f"Coupling {c.driver}/{c.follower}: kind must be one of {', '.join(COUPLING_KINDS)} (got “{c.kind}”).")
            if c.kind == "cam" and len(c.profile) < 2:
                out.append(f"Coupling {c.driver}/{c.follower}: a cam needs a profile of at least two (degrees, value) points.")
            if c.follower in led:
                out.append(f"Joint {c.follower} is driven by two couplings ({led[c.follower]}, {c.driver}); give it one.")
            led[c.follower] = c.driver
        for start in led:                         # a follower that drives its own driver, at any depth
            cur, seen = start, set()
            while cur in led and cur not in seen:
                seen.add(cur)
                cur = led[cur]
            if cur in seen:
                out.append("Couplings " + " → ".join(sorted(seen)) + " drive each other in a circle.")
                break
        for lp in self.loops:
            for x in (lp.a, lp.b):
                if x not in idset:
                    out.append(f"Loop {lp.a}/{lp.b} names unknown part “{x}”.")
            if lp.a == lp.b:
                out.append(f"Loop {lp.a}/{lp.b} closes a part on itself.")
            if len(tuple(lp.at)) != 3:
                out.append(f"Loop {lp.a}/{lp.b}: at must be three numbers.")
            if lp.axis is not None and (len(lp.axis) != 3 or sum(a * a for a in lp.axis) < 1e-12):
                out.append(f"Loop {lp.a}/{lp.b}: axis must be three numbers, not zero.")
        for h in self.hardware:
            if h.after and h.after not in idset:
                out.append(f"Hardware {h.name} is fitted after unknown part “{h.after}”.")
        if self.budget_s is not None and not 1 <= self.budget_s <= 600:
            out.append("budget_s must be between 1 and 600 seconds.")
        return out

    def public(self) -> dict:
        joints = []
        for j in self.joints:
            d = asdict(j)
            d["moves"] = self.moved_by(j.id)
            if j.step:
                d["detents"] = self.detents(j)
            joints.append(d)
        return {"parts": [asdict(p) for p in self.parts], "joints": joints,
                "hardware": [{**asdict(h), "access": [asdict(a) for a in h.access]} for h in self.hardware],
                "mates": [asdict(m) for m in self.mates],
                "couplings": [asdict(c) for c in self.couplings], "loops": [asdict(lp) for lp in self.loops],
                "clearance_warn": self.clearance_warn, "derived": self.derived}

    @classmethod
    def from_public(cls, d: dict) -> "Assembly":
        """The declaration rebuilt from public() (or from the assembly view, which carries the same keys and more)."""
        from dataclasses import fields

        def make(T, row):
            names = {f.name for f in fields(T)}
            kw = {}
            for k, v in row.items():
                if k not in names:
                    continue
                if isinstance(v, list):
                    v = tuple(tuple(x) if isinstance(x, list) else x for x in v)
                kw[k] = v
            return T(**kw)

        hw = [make(Hardware, {**h, "access": tuple(make(Access, a) for a in h.get("access") or [])})
              for h in d.get("hardware") or []]
        rows = []
        for x in d.get("parts") or []:            # the assembly view gives the placement as a matrix, not move/rotate
            if "move" not in x and isinstance(x.get("placement"), dict) and x["placement"].get("m"):
                x = {**x, **_move_rotate(x["placement"]["m"])}
            rows.append(x)
        return cls(parts=[make(Part, x) for x in rows], joints=[make(Joint, x) for x in d.get("joints") or []],
                   hardware=hw, mates=[make(Mate, x) for x in d.get("mates") or []],
                   couplings=[make(Coupling, x) for x in d.get("couplings") or []],
                   loops=[make(Loop, x) for x in d.get("loops") or []],
                   clearance_warn=float(d.get("clearance_warn", 0.1)), derived=bool(d.get("derived")))


def _move_rotate(m) -> dict:
    """move and rotate (build123d Rot: Rx @ Ry @ Rz, degrees) of a 3x4 placement matrix, so placement_matrix() gives
    it back."""
    R = [[float(m[r][c]) for c in range(3)] for r in range(3)]
    b = math.asin(max(-1.0, min(1.0, R[0][2])))
    if abs(R[0][2]) < 1 - 1e-12:
        a = math.atan2(-R[1][2], R[2][2])
        c = math.atan2(-R[0][1], R[0][0])
    else:                                     # gimbal lock: put the whole turn about X
        a, c = math.atan2(R[2][1], R[1][1]), 0.0
    return {"move": tuple(float(m[r][3]) for r in range(3)), "rotate": tuple(math.degrees(x) for x in (a, b, c))}


def from_solids(boxes: list) -> Assembly:
    """A view-only assembly for a design that builds several separate solids and declares no assembly().

    Each solid is one part, left where the design built it (so "assembled" is the design as modelled), and pulled
    away from the centre of the whole for the exploded view: along the line from that centre to the part's own
    centre (never downward, through the plate), by about a third of the largest dimension (straight up for a part at the centre, stacked by height).
    `boxes` are the solids' bounding boxes, [[x0, y0, z0], [x1, y1, z1]], in the order assembly.get numbers them.
    No checks come from it: the design never said how its parts meet."""
    lo = [min(b[0][i] for b in boxes) for i in range(3)]
    hi = [max(b[1][i] for b in boxes) for i in range(3)]
    mid = [(lo[i] + hi[i]) / 2 for i in range(3)]
    reach = max(hi[i] - lo[i] for i in range(3)) * 0.35 + 6.0
    order_z = sorted(range(len(boxes)), key=lambda k: (boxes[k][0][2] + boxes[k][1][2]) / 2)
    parts = []
    for k, b in enumerate(boxes):
        c = [(b[0][i] + b[1][i]) / 2 for i in range(3)]
        d = [c[0] - mid[0], c[1] - mid[1], max(0.0, c[2] - mid[2])]     # never down through the build plate
        n = sum(x * x for x in d) ** 0.5
        if n < 1e-6:
            e = (0.0, 0.0, reach * (1 + order_z.index(k)) / len(boxes))
        else:
            e = tuple(x / n * reach for x in d)
        parts.append(Part(f"part{k + 1}", f"Part {k + 1}", k, explode=tuple(round(x, 3) for x in e)))
    return Assembly(parts=parts, derived=True)
