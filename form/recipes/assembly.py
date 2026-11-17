"""Assembly contract: how the printed parts of a design go together.

A design that prints several parts side by side (``Recipe.solids > 1``) can say how they are assembled by
returning an :class:`Assembly` from ``Recipe.assembly(values)``. Everything here is plain data; the kernel
worker turns it into placed solids, interference, clearance, motion and tool-access checks, and the studio
turns it into an exploded view, a BOM and numbered assembly steps.

Frames
  *print frame*      the solids exactly as ``build()`` returns them, flat on the bed.
  *assembled frame*  each part moved by ``Pos(*move) * Rot(*rotate)`` (build123d semantics: rotate the part as
                     printed about the origin, then translate). Joints, hardware and markers use this frame.

Parts are picked from the result by ``solid``: the result's solids numbered 0, 1, ... by the X of their
bounding-box centre, then Y (left to right on the plate, as the print layout shows them).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


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
    explode: tuple = (0.0, 0.0, 0.0)           # exploded-view offset (mm, assembled frame) at factor 1; the separation direction
    note: str = ""                              # the assembly step for this part, in the imperative ("Press the lid on.")
    material: str = ""                          # optional; the BOM otherwise uses the slicer's filament


@dataclass(frozen=True)
class Joint:
    id: str
    label: str
    part: str                                   # the part that moves; every other part stays where it is assembled
    kind: str                                   # "hinge" (degrees) | "slide" (mm)
    axis: tuple                                 # direction, assembled frame
    origin: tuple = (0.0, 0.0, 0.0)            # a point on the hinge axis (unused for a slide)
    range: tuple = (0.0, 90.0)                 # (lo, hi) in degrees or mm; 0 is the assembled position
    samples: int = 13                           # positions checked between lo and hi, ends included


def hinge(part: str, axis, origin, range_deg, samples: int = 13, id: str = "", label: str = "") -> Joint:
    """A part that turns about a line. range_deg = (lo, hi) degrees, right-handed about ``axis``."""
    lo, hi = _vec(range_deg, 2)
    return Joint(id or f"{part}_hinge", label or "Hinge", part, "hinge", _vec(axis), _vec(origin), (lo, hi), int(samples))


def slide(part: str, axis, range_mm, samples: int = 9, id: str = "", label: str = "") -> Joint:
    """A part that moves along a direction. range_mm = (lo, hi) millimetres along ``axis``."""
    lo, hi = _vec(range_mm, 2)
    return Joint(id or f"{part}_slide", label or "Slide", part, "slide", _vec(axis), (0.0, 0.0, 0.0), (lo, hi), int(samples))


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


@dataclass
class Assembly:
    parts: list
    joints: list = field(default_factory=list)
    hardware: list = field(default_factory=list)
    clearance_warn: float = 0.1                 # a gap between parts under this (and over 0) is reported for review, mm
    derived: bool = False                       # made by FORM from separate solids (no assembly() declared): view only

    def validate(self, n_solids: int) -> list[str]:
        """Problems that make the assembly meaningless. Empty when it can be checked."""
        out, ids = [], [p.id for p in self.parts]
        if not self.parts:
            out.append("An assembly needs at least one part.")
        if len(set(ids)) != len(ids):
            out.append("Part ids must be unique.")
        used = [p.solid for p in self.parts]
        for p in self.parts:
            if not 0 <= p.solid < n_solids:
                out.append(f"Part {p.id} names solid {p.solid}; the design has {n_solids} (0–{n_solids - 1}).")
        if len(set(used)) != len(used):
            out.append("Two parts name the same solid.")
        for j in self.joints:
            if j.part not in ids:
                out.append(f"Joint {j.id} moves unknown part “{j.part}”.")
            if j.kind not in ("hinge", "slide"):
                out.append(f"Joint {j.id}: kind must be hinge or slide.")
            if sum(a * a for a in j.axis) < 1e-12:
                out.append(f"Joint {j.id}: axis is zero.")
            if j.samples < 2:
                out.append(f"Joint {j.id}: sample at least 2 positions.")
        for h in self.hardware:
            if h.after and h.after not in ids:
                out.append(f"Hardware {h.name} is fitted after unknown part “{h.after}”.")
        return out

    def public(self) -> dict:
        return {"parts": [asdict(p) for p in self.parts], "joints": [asdict(j) for j in self.joints],
                "hardware": [{**asdict(h), "access": [asdict(a) for a in h.access]} for h in self.hardware],
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
