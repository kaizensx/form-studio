"""Cutting tools for 3-axis milling: the shape that cuts, the shape that must not touch, and a small library.

A tool is a solid of revolution about its axis, with its tip at height 0:

    flat      a cylinder of diameter d
    ball      a hemisphere of radius d/2 under a cylinder
    bull      a flat end with a corner radius corner_r (a torus under a cylinder)
    drill     a cone with the point angle (118° unless stated) under a cylinder
    chamfer   a cone with the included angle (90° unless stated) from a flat tip of diameter tip_d up to d

Above the flutes (flute_l from the tip) nothing cuts: the shank (shank_d, at least d here) runs up to `length`, the
stick-out below the holder, and the holder (holder_d, holder_l) sits above that. `profile(r)` is the height of the
cutting surface above the tip at radius r; `envelope(r)` is the lowest height of the whole body, holder included;
`inside(r, h)` is how deep a point is inside the body (the distance to its surface, exact for the outline's
segments; arcs are drawn with 48 chords, 0.0005 × radius off at most).

The library is data. A tool the person described is `specified`; one taken from DEFAULTS is `assumed`: its flute
length, flute count and holder are a guess about a tool nobody named, and a program that uses it cannot be released.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, replace

import numpy as np

KINDS = ("flat", "ball", "bull", "drill", "chamfer")
ARC_CHORDS = 48


@dataclass(frozen=True)
class Tool:
    id: str
    kind: str
    d: float                       # cutting diameter, mm
    flutes: int = 2
    flute_l: float = 0.0           # length that cuts, from the tip
    length: float = 0.0            # stick-out below the holder
    corner_r: float = 0.0          # bull
    angle: float = 0.0             # drill: point angle (118); chamfer: included angle (90)
    tip_d: float = 0.0             # chamfer: flat at the tip
    shank_d: float = 0.0
    holder_d: float = 0.0
    holder_l: float = 0.0
    number: int = 0                # T word
    material: str = "carbide"
    provenance: str = "specified"  # specified (the person described it) | assumed (a library default)

    # ---- derived ---------------------------------------------------------------------------------------------
    @property
    def r(self) -> float:
        return self.d / 2

    @property
    def half_angle(self) -> float:
        a = self.angle or (118.0 if self.kind == "drill" else 90.0)
        return math.radians(a / 2)

    @property
    def cone_h(self) -> float:
        """Height of the conical part (drill point, chamfer cone)."""
        if self.kind == "drill":
            return self.r / math.tan(self.half_angle)
        if self.kind == "chamfer":
            return (self.r - self.tip_d / 2) / math.tan(self.half_angle)
        return 0.0

    @property
    def shank_r(self) -> float:
        return max(self.shank_d / 2, self.r)

    @property
    def holder_r(self) -> float:
        return max(self.holder_d / 2, self.shank_r) if self.holder_l > 0 else self.shank_r

    @property
    def top(self) -> float:
        return self.length + max(self.holder_l, 0.0)

    def profile(self, r):
        """Height of the cutting surface above the tip at radius r (inf beyond the cutting radius)."""
        r = np.asarray(r, float)
        R = self.r
        if self.kind == "flat":
            h = np.zeros_like(r)
        elif self.kind == "ball":
            h = R - np.sqrt(np.maximum(R * R - np.minimum(r, R) ** 2, 0.0))
        elif self.kind == "bull":
            rc = self.corner_r
            x = np.clip(r - (R - rc), 0.0, rc)
            h = rc - np.sqrt(np.maximum(rc * rc - x * x, 0.0))
        elif self.kind == "drill":
            h = r / math.tan(self.half_angle)
        else:
            h = np.maximum(r - self.tip_d / 2, 0.0) / math.tan(self.half_angle)
        return np.where(r <= R + 1e-12, h, np.inf)

    def contact_r(self, slope):
        """The radius at which the tool touches a plane of the given slope (rise over run): where the profile's
        own slope equals it."""
        m = np.asarray(slope, float)
        R = self.r
        if self.kind == "flat":
            return np.full_like(m, R)
        if self.kind == "ball":
            return R * m / np.sqrt(1 + m * m)
        if self.kind == "bull":
            return (R - self.corner_r) + self.corner_r * m / np.sqrt(1 + m * m)
        ms = 1.0 / math.tan(self.half_angle)                    # the cone's own slope
        inner = 0.0 if self.kind == "drill" else self.tip_d / 2
        return np.where(m > ms, R, inner)                       # a plane flatter than the cone meets its point

    def noncut(self, r):
        """Lowest height of what does not cut at radius r: the body above the flutes, then the holder."""
        r = np.asarray(r, float)
        return np.where(r <= self.shank_r + 1e-12, self.flute_l,
                        np.where(r <= self.holder_r + 1e-12, self.length, np.inf))

    def envelope(self, r):
        """Lowest height of the whole body (cutter, shank and holder) at radius r."""
        return np.minimum(self.profile(r), self.noncut(r))

    def outline(self) -> np.ndarray:
        """The body's outline in the (r, h) half-plane, from the tip outward and up: (n, 2)."""
        R, pts = self.r, [(0.0, 0.0)]
        if self.kind == "ball":
            for k in range(1, ARC_CHORDS + 1):
                a = math.pi / 2 * k / ARC_CHORDS
                pts.append((R * math.sin(a), R - R * math.cos(a)))
        elif self.kind == "bull":
            rc = self.corner_r
            pts.append((R - rc, 0.0))
            for k in range(1, ARC_CHORDS + 1):
                a = math.pi / 2 * k / ARC_CHORDS
                pts.append((R - rc + rc * math.sin(a), rc - rc * math.cos(a)))
        elif self.kind == "drill":
            pts.append((R, self.cone_h))
        elif self.kind == "chamfer":
            pts += [(self.tip_d / 2, 0.0), (R, self.cone_h)]
        else:
            pts.append((R, 0.0))
        fl = max(self.flute_l, pts[-1][1])
        pts.append((R, fl))
        if self.shank_r > R + 1e-9:
            pts.append((self.shank_r, fl))
        ln = max(self.length, fl)
        pts.append((self.shank_r, ln))
        if self.holder_r > self.shank_r + 1e-9:
            pts += [(self.holder_r, ln), (self.holder_r, self.top)]
        out = [pts[0]]
        for p in pts[1:]:
            if abs(p[0] - out[-1][0]) > 1e-12 or abs(p[1] - out[-1][1]) > 1e-12:
                out.append(p)
        return np.array(out, float)

    def inside(self, r, h):
        """How deep the points (r, h) are inside the body: the distance to its surface (0 outside)."""
        r, h = np.asarray(r, float), np.asarray(h, float)
        inn = (h > self.envelope(r)) & (h < max(self.top, self.flute_l))
        out = np.zeros(r.shape)
        if not inn.any():
            return out
        O = self.outline()
        a, b = O[:-1], O[1:]
        ab = b - a
        L2 = np.maximum((ab * ab).sum(axis=1), 1e-30)
        pr, ph = r[inn][:, None], h[inn][:, None]
        t = np.clip(((pr - a[:, 0]) * ab[:, 0] + (ph - a[:, 1]) * ab[:, 1]) / L2, 0.0, 1.0)
        d = np.hypot(pr - (a[:, 0] + t * ab[:, 0]), ph - (a[:, 1] + t * ab[:, 1]))
        out[inn] = d.min(axis=1)
        return out

    def part(self, h) -> str:
        """Which part of the body is at height h above the tip."""
        return "cutter" if h <= self.flute_l + 1e-9 else "shank" if h <= self.length + 1e-9 else "holder"

    def public(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if v not in (0, 0.0, "")}
        d["label"] = self.label
        return d

    @property
    def label(self) -> str:
        what = {"flat": "flat end mill", "ball": "ball end mill", "bull": f"bull nose r{self.corner_r:g}",
                "drill": "drill", "chamfer": f"chamfer mill {self.angle or 90:g}°"}[self.kind]
        return f"Ø{self.d:g} mm {what}, {self.flutes} flutes"


def _err(msg, hint=""):
    from ..studio import StudioError
    return StudioError(msg, hint)


def make(spec, number: int = 0, provenance: str = "specified") -> Tool:
    """A tool from what the person gave: a dict (kind, d, flutes, flute_l, length, corner_r, angle, tip_d, shank_d,
    holder_d, holder_l, material, id, number) or a short name ("6mm-flat", "3mm-ball", "6mm-bull-r1", "5mm-drill",
    "6mm-chamfer-90"). What a dict leaves out is filled from the short name's proportions and the tool is then
    `assumed`: nobody said how long its flutes are."""
    if isinstance(spec, Tool):
        return spec
    assumed = False
    if isinstance(spec, str):
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*mm[-_ ]?(flat|ball|bull|drill|chamfer)(?:[-_ ]r?(\d+(?:\.\d+)?))?\s*", spec.lower())
        if not m:
            raise _err(f"Unknown tool “{spec}”.", "Name it like 6mm-flat, 3mm-ball, 6mm-bull-r1, 5mm-drill or "
                       "6mm-chamfer-90, or give {kind, d, flutes, flute_l, length, holder_d, holder_l}.")
        spec = {"kind": m.group(2), "d": float(m.group(1))}
        if m.group(3):
            spec["corner_r" if spec["kind"] == "bull" else "angle"] = float(m.group(3))
        assumed = True
    s = dict(spec)
    kind = str(s.get("kind", "")).lower()
    if kind not in KINDS:
        raise _err(f"Unknown tool kind “{s.get('kind')}”.", "Kinds: " + ", ".join(KINDS) + ".")
    try:
        d = float(s["d"])
    except (KeyError, TypeError, ValueError):
        raise _err("A tool needs its diameter d in mm.")
    if not d > 0:
        raise _err("A tool's diameter is above 0.")
    for k in ("flute_l", "length"):
        if not s.get(k):
            assumed = True
    flute_l = float(s.get("flute_l") or 3 * d)
    length = max(float(s.get("length") or flute_l + 2 * d), flute_l)
    corner_r = float(s.get("corner_r") or (d / 6 if kind == "bull" else 0))
    if kind == "bull" and not 0 < corner_r < d / 2:
        raise _err("A bull nose's corner radius is between 0 and its radius.")
    t = Tool(id=str(s.get("id") or f"{d:g}mm-{kind}" + (f"-r{corner_r:g}" if kind == "bull" else "")), kind=kind, d=d,
             flutes=int(s.get("flutes") or 2), flute_l=flute_l, length=length, corner_r=corner_r,
             angle=float(s.get("angle") or (118 if kind == "drill" else 90 if kind == "chamfer" else 0)),
             tip_d=float(s.get("tip_d") or 0), shank_d=float(s.get("shank_d") or d),
             holder_d=float(s.get("holder_d") or 0), holder_l=float(s.get("holder_l") or (25.0 if s.get("holder_d") else 0)),
             number=int(s.get("number") or number), material=str(s.get("material") or "carbide"),
             provenance="assumed" if (assumed or s.get("provenance") == "assumed" or provenance == "assumed") else "specified")
    if t.kind in ("drill", "chamfer"):
        t = replace(t, flute_l=max(t.flute_l, t.cone_h), length=max(t.length, t.cone_h))
    return t


# Starting tools for a plan nobody gave tools to. Their proportions are a guess (flutes 3 × d, stick-out 5 × d, an
# ER-style holder of Ø28 mm): every one is `assumed`.
DEFAULTS = [
    {"kind": "flat", "d": 6.0, "flutes": 3, "flute_l": 18.0, "length": 30.0, "holder_d": 28.0, "holder_l": 30.0},
    {"kind": "ball", "d": 6.0, "flutes": 2, "flute_l": 12.0, "length": 30.0, "holder_d": 28.0, "holder_l": 30.0},
]


def library(tools=None) -> list[Tool]:
    """The tools of a plan, numbered from T1 in the order given."""
    if not tools:
        return [replace(make(s, i + 1), provenance="assumed") for i, s in enumerate(DEFAULTS)]
    out = []
    for i, s in enumerate(tools):
        t = make(s, i + 1)
        out.append(t if t.number else replace(t, number=i + 1))
    ids = [t.id for t in out]
    if len(set(ids)) != len(ids):
        raise _err("Two tools have the same id.", "Give each tool its own id.")
    return out


def pick(tools: list[Tool], kind: str, largest: bool = True, max_d: float | None = None) -> Tool | None:
    c = [t for t in tools if t.kind == kind and (max_d is None or t.d <= max_d + 1e-9)]
    if not c:
        return None
    return max(c, key=lambda t: t.d) if largest else min(c, key=lambda t: t.d)
