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
bounding-box centre, then Y (left to right on the plate, as the print layout shows them).

Kinematic tree
  Every part has at most one link to a parent: ``Part(attach="arm")`` (rigidly fixed to the arm), or a joint
  ``hinge("cup", ..., parent="arm")`` (turns relative to the arm). A part with no link is fixed to the world.
  Moving a joint moves its part and everything attached to it, at any depth: arm -> cup -> cup bolt. A joint's
  axis and origin are given in the assembled frame (all joints at 0); when a parent joint moves, the child joint's
  axis moves with it. ``parent=""`` on a joint means the world, which is how every declaration before chains
  existed reads (the joint moves only its part, since nothing was attached to it).

Joined pairs
  ``Mate(a, b, kind)`` says two parts touch or interlock by design (a pin in its hole, a thread in a thread, a
  press fit). They are not booleaned against each other; their gap is checked once against the declared
  clearance instead. Every other pair is checked at rest and through every joint's motion.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

KINDS = ("hinge", "slide", "fixed")
KIND_ALIAS = {"slider": "slide", "revolute": "hinge", "prismatic": "slide", "rigid": "fixed"}
MATE_KINDS = ("pin", "thread", "press", "snap", "slip", "contact")


def _vec(v, n=3) -> tuple:
    t = tuple(float(x) for x in v)
    if len(t) != n:
        raise ValueError(f"expected {n} numbers, got {len(t)}")
    return t


@dataclass(frozen=True)
class Part:
    id: str
    label: str
    solid: int                                  # index into the result's solids, ordered by bounding-box centre X, then Y
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


def fixed(part: str, parent: str, id: str = "", label: str = "") -> Joint:
    """A part fixed to another one, written as a joint (the same as ``Part(attach=parent)``)."""
    return Joint(id or f"{part}_fixed", label or "Fixed", part, "fixed", (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 0.0), 2,
                 parent, 0.0)


@dataclass(frozen=True)
class Mate:
    """Two parts that touch or interlock by design: not booleaned against each other, their gap checked instead.

    kind: pin (pin or axle in a hole), thread (thread in thread), slip (sliding fit), snap, press (intended
    interference), contact (faces that rest on each other). clearance: the designed gap per side in mm (negative for
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


def joint_matrix(j: Joint, value: float):
    """4x4 motion of a joint at `value` (degrees or mm), acting in the assembled frame."""
    import numpy as np
    M = np.eye(4)
    if j.kind == "fixed" or not value:
        return M
    n = math.sqrt(sum(a * a for a in j.axis)) or 1.0
    u = np.array(j.axis, float) / n
    if j.kind == "hinge":
        t = math.radians(value)
        K = np.array([[0, -u[2], u[1]], [u[2], 0, -u[0]], [-u[1], u[0], 0]])
        R = np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * (K @ K)
        o = np.array(j.origin, float)
        M[:3, :3] = R
        M[:3, 3] = o - R @ o
    else:
        M[:3, 3] = u * value
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
        used = [p.solid for p in self.parts]
        for p in self.parts:
            if not 0 <= p.solid < n_solids:
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
                out.append(f"Joint {j.id}: kind must be hinge, slide or fixed (got “{j.kind}”).")
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
                "clearance_warn": self.clearance_warn, "derived": self.derived}


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
