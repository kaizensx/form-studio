"""The contract of a design: what the brief asks for, as assertions the kernel can check.

"Done" is not "correct": a build that returns a valid solid says nothing about whether the four holes are there.
A contract turns the brief into typed assertions, each with a tolerance and where it came from; every assertion is
an obligation of one feature; the kernel measures each on the built solid (form/proving.py); and the result is the
proof sheet: one row per requirement with what was measured, the tolerance, the evidence class and a status.

    c = contract.compile_brief(brief)            # {"assertions": [...], "audit": {...}}, kernel-free
    contract.assign(c["assertions"], features)   # each assertion gets the feature that must discharge it
    sheet = contract.prove(st, p)                # measured by the kernel, kept under the solid's key
    contract.claim_gate(st, p)                   # what an end-of-run summary may and may not claim (WP7)

Assertion kinds (a dict with "kind"; the constructors below make them and can be used in a design's source as
@feature(..., expects=[contract.bolt_circle(4, 5.2, 60)])):

    bbox          size [x, y, z] mm (any_order: the three sizes in any orientation)
    extent        one overall size mm: along axis x | y | z, or along any one of them ("overall length 40 mm")
    volume        mm3, op min | max | eq
    part_count    count of separate solids
    face_count    count of faces of a kind (plane, cylinder, cone, sphere, torus, bspline, any), op eq | min | max
    hole_count    count of round holes of diameter d
    cylinder      a cylindrical face of diameter d; of: any | boss | bore; axis x | y | z (optional); count
                  (optional): exactly that many separate cylinders of that diameter; length (optional): each
                  that long along its axis, which tells a through bore from a blind one
    bolt_circle   count holes of diameter hole_d with their axes on a circle of diameter circle_d
    pattern       count holes of diameter hole_d in a row, pitch mm apart
    min_wall      thinnest wall >= t
    thread        a thread of major diameter `major` (pitch optional) is present

Tolerance: every assertion carries tol (mm; DEFAULT_TOL when the brief gives none, and then its provenance says
"default tolerance (assumed)"). Provenance: where the number came from: the brief's words (quoted), a named
dimension with its source (measured, specified, assumed), or the design's source (expects=).

Evidence classes on the proof sheet are Form Studio's own (docs/ARCHITECTURE.md): "computed" (read off the B-rep:
sizes, counts, radii, axes), "heuristic" (a rule on computed values: thread presence is read from helical faces at
that diameter) and "none" for a row nothing could measure. A row's status is PASS, FAIL or UNPROVEN; UNPROVEN is
never counted as a pass.

Plain data: no kernel, no SDK. prove() asks the kernel worker through Studio.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time

VERSION = 1
DEFAULT_TOL = 0.1                 # mm, when the brief states none (Form Studio's default for a remodel as well)
KINDS = ("bbox", "extent", "volume", "part_count", "face_count", "hole_count", "cylinder", "bolt_circle", "pattern",
         "min_wall", "thread")
FACE_KINDS = ("plane", "cylinder", "cone", "sphere", "torus", "bspline", "any")
OPS = ("eq", "min", "max")
STATUSES = ("PASS", "FAIL", "UNPROVEN")
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "twelve": 12}


class ContractError(ValueError):
    pass


# ---- constructors ------------------------------------------------------------------------------------------------

def _pos(x, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x:
        raise ContractError(f"{what} must be a number")
    return float(x)


def _a(kind: str, text: str, tol, **f) -> dict:
    out = {"kind": kind, "text": text, **f}
    if tol is not None:
        out["tol"] = _pos(tol, "tol")
    return out


def bbox(x: float, y: float, z: float, tol: float | None = None, any_order: bool = False) -> dict:
    s = [_pos(x, "x"), _pos(y, "y"), _pos(z, "z")]
    return _a("bbox", f"size {s[0]:g} x {s[1]:g} x {s[2]:g} mm" + (" (any orientation)" if any_order else ""), tol,
              size=s, any_order=bool(any_order))


def extent(mm: float, axis: str = "", tol: float | None = None) -> dict:
    return _a("extent", f"overall size {mm:g} mm" + (f" along {axis}" if axis else " (along one axis)"), tol,
              mm=_pos(mm, "mm"), **({"axis": axis} if axis else {}))


def volume(mm3: float, op: str = "max", tol: float | None = None) -> dict:
    return _a("volume", f"volume {'at most' if op == 'max' else 'at least' if op == 'min' else '='} {mm3:g} mm³", tol,
              mm3=_pos(mm3, "mm3"), op=op)


def part_count(count: int) -> dict:
    return _a("part_count", f"{int(count)} separate part(s)", None, count=int(count))


def face_count(count: int, of: str = "any", op: str = "eq") -> dict:
    return _a("face_count", f"{'at least ' if op == 'min' else 'at most ' if op == 'max' else ''}{int(count)} "
              f"{'' if of == 'any' else of + ' '}face(s)", None, count=int(count), of=of, op=op)


def holes(count: int, d: float, tol: float | None = None, axis: str = "") -> dict:
    return _a("hole_count", f"{int(count)} hole(s) Ø{d:g} mm" + (f" along {axis}" if axis else ""), tol,
              count=int(count), d=_pos(d, "d"), **({"axis": axis} if axis else {}))


def cylinder(d: float, of: str = "any", tol: float | None = None, axis: str = "", count: int | None = None,
             length: float | None = None, length_tol: float | None = None) -> dict:
    return _a("cylinder", (f"{int(count)} x " if count is not None else "") + f"Ø{d:g} mm {'cylinder' if of == 'any' else of}"
              + (f", {length:g} mm long" if length is not None else "") + (f" along {axis}" if axis else ""), tol,
              d=_pos(d, "d"), of=of, **({"axis": axis} if axis else {}),
              **({"count": int(count)} if count is not None else {}),
              **({"length": _pos(length, "length")} if length is not None else {}),
              **({"length_tol": _pos(length_tol, "length_tol")} if length_tol is not None else {}))


def bolt_circle(count: int, hole_d: float, circle_d: float, tol: float | None = None) -> dict:
    return _a("bolt_circle", f"{int(count)} x Ø{hole_d:g} mm on a Ø{circle_d:g} mm bolt circle", tol,
              count=int(count), hole_d=_pos(hole_d, "hole_d"), circle_d=_pos(circle_d, "circle_d"))


def pattern(count: int, pitch: float, hole_d: float, tol: float | None = None) -> dict:
    return _a("pattern", f"{int(count)} x Ø{hole_d:g} mm in a row, {pitch:g} mm apart", tol,
              count=int(count), pitch=_pos(pitch, "pitch"), hole_d=_pos(hole_d, "hole_d"))


def wall(t: float, tol: float | None = None) -> dict:
    return _a("min_wall", f"walls at least {t:g} mm", tol, t=_pos(t, "t"))


def thread(major: float, pitch: float | None = None, tol: float | None = None) -> dict:
    return _a("thread", f"M{major:g}" + (f"x{pitch:g}" if pitch else "") + " thread", tol, major=_pos(major, "major"),
              **({"pitch": _pos(pitch, "pitch")} if pitch else {}))


min_wall = wall
hole_count = holes
_REQUIRED = {"bbox": ("size",), "extent": ("mm",), "volume": ("mm3",), "part_count": ("count",), "face_count": ("count",),
             "hole_count": ("count", "d"), "cylinder": ("d",), "bolt_circle": ("count", "hole_d", "circle_d"),
             "pattern": ("count", "pitch", "hole_d"), "min_wall": ("t",), "thread": ("major",)}


def normalise(a: dict, provenance: dict | None = None) -> dict:
    """One assertion, checked and completed (text, tol with where it came from). Raises ContractError."""
    if not isinstance(a, dict) or a.get("kind") not in KINDS:
        raise ContractError(f"an assertion needs a kind: one of {', '.join(KINDS)}")
    k = a["kind"]
    miss = [f for f in _REQUIRED[k] if a.get(f) is None]
    if miss:
        raise ContractError(f"{k} needs {', '.join(miss)}")
    try:
        made = {"bbox": lambda: bbox(*a["size"], any_order=a.get("any_order", False)),
                "extent": lambda: extent(a["mm"], a.get("axis", "")),
                "volume": lambda: volume(a["mm3"], a.get("op", "max")),
                "part_count": lambda: part_count(a["count"]),
                "face_count": lambda: face_count(a["count"], a.get("of", "any"), a.get("op", "eq")),
                "hole_count": lambda: holes(a["count"], a["d"], axis=a.get("axis", "")),
                "cylinder": lambda: cylinder(a["d"], a.get("of", "any"), axis=a.get("axis", ""), count=a.get("count"),
                                             length=a.get("length"), length_tol=a.get("length_tol")),
                "bolt_circle": lambda: bolt_circle(a["count"], a["hole_d"], a["circle_d"]),
                "pattern": lambda: pattern(a["count"], a["pitch"], a["hole_d"]),
                "min_wall": lambda: wall(a["t"]),
                "thread": lambda: thread(a["major"], a.get("pitch"))}[k]()
    except (TypeError, ValueError) as e:
        raise ContractError(f"{k}: {e}")
    if made.get("op") and made["op"] not in OPS:
        raise ContractError(f"{k}: op is one of {', '.join(OPS)}")
    if k == "face_count" and made["of"] not in FACE_KINDS:
        raise ContractError(f"face_count: of is one of {', '.join(FACE_KINDS)}")
    if k == "cylinder" and made["of"] not in ("any", "boss", "bore"):
        raise ContractError("cylinder: of is any, boss or bore")
    if made.get("axis") and made["axis"] not in ("x", "y", "z"):
        raise ContractError(f"{k}: axis is x, y or z")
    out = {**made, **{f: a[f] for f in ("id", "feature", "text", "outer") if a.get(f)}}
    prov = dict(a.get("provenance") or provenance or {"source": "stated", "basis": "assumed"})
    if k not in ("part_count", "face_count"):
        if a.get("tol") is not None:
            out["tol"] = _pos(a["tol"], "tol")
        else:
            out["tol"] = DEFAULT_TOL
            prov["tolerance"] = "default tolerance (assumed)"
    out["provenance"] = prov
    return out


# ---- reading a brief ---------------------------------------------------------------------------------------------

_N = r"(\d+(?:[.,]\d+)?)"
_DIA = r"(?:Ø|ø|⌀|dia(?:meter)?\.?\s*)"
_CNT = r"(\d+|" + "|".join(_WORDS) + r")"


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _n(s: str) -> int:
    return _WORDS.get(s.lower(), None) or int(s)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("×", "x").replace("–", "-").replace("≥", ">=")).strip()


def parse_text(text: str) -> tuple[list, list]:
    """(assertions read from a sentence, things it mentions without enough numbers to check). Each assertion's
    provenance quotes the words it was read from. Patterns, not understanding: what they do not match is not a
    requirement here, and the agent adds it as a typed assertion."""
    t = _clean(text)
    found: list = []
    missing: list = []
    spans: list = []

    def take(m, a: dict):
        spans.append((m.start(), m.end()))
        a["provenance"] = {"source": "brief", "quote": t[m.start():m.end()].strip(), "basis": "stated"}
        found.append(a)

    def free(m) -> bool:
        return not any(a < m.end() and m.start() < b for a, b in spans)
    # 4 x Ø5.2 on a 60 mm bolt circle | 4 holes Ø5.2 on PCD 60
    # "from Ø20 mm to Ø24 mm": the first number is what it was, not a requirement
    for m in re.finditer(r"\bfrom\s+(?:" + _DIA + r")?\s*" + _N + r"\s*(?:mm)?\s+(?=to\b)", t, re.I):
        spans.append((m.start(), m.end()))
    bc = re.compile(_CNT + r"\s*(?:x\s*)?(?:equally[- ]spaced\s*)?(?:(?:bolt|fastener|mounting|clearance|through)[- ])?(?:holes?\s*)?(?:of\s*)?"
                    + _DIA + r"\s*" + _N + r"\s*(?:mm)?\s*(?:(?:bolt|fastener|mounting|clearance|through)[- ])?(?:holes?)?\s*,?\s*"
                    r"(?:equally[- ]spaced\s*)?(?:on|at|around)\s*(?:a\s*|the\s*same\s*|the\s*)?(?:(?:" + _DIA + r")?\s*" + _N + r"\s*(?:mm)?\s*"
                    r"(?:diameter\s*)?(?:bolt[- ]circle|pcd|pitch[- ]circle(?: diameter)?|bcd)|(?:pcd|bcd|bolt[- ]circle)\s*"
                    r"(?:of\s*)?(?:" + _DIA + r")?\s*" + _N + r")", re.I)
    for m in bc.finditer(t):
        take(m, bolt_circle(_n(m.group(1)), _f(m.group(2)), _f(m.group(3) or m.group(4))))
    for m in re.finditer(r"bolt[- ]circle|\bpcd\b|\bbcd\b|pitch[- ]circle", t, re.I):
        if free(m) and not any(a["kind"] == "bolt_circle" for a in found):
            missing.append({"what": "bolt circle", "quote": t[max(0, m.start() - 40):m.end() + 20].strip(),
                            "need": "hole count, hole diameter and circle diameter (for example 4 x Ø5.2 on a 60 mm "
                                    "bolt circle)"})
            spans.append((m.start(), m.end()))
    # 80 mm x 80 mm, 8 mm thick
    for m in re.finditer(_N + r"\s*(?:mm)?\s*x\s*" + _N + r"\s*mm\s*,?\s*(?:and\s*)?" + _N + r"\s*mm\s*thick", t, re.I):
        if free(m):
            take(m, bbox(_f(m.group(1)), _f(m.group(2)), _f(m.group(3)), any_order=True))
    # 80 x 60 x 20 mm
    for m in re.finditer(_N + r"\s*(?:mm)?\s*x\s*" + _N + r"\s*(?:mm)?\s*x\s*" + _N + r"\s*mm", t, re.I):
        if free(m):
            take(m, bbox(_f(m.group(1)), _f(m.group(2)), _f(m.group(3)), any_order=True))
    # 3 holes Ø4 in a row 20 mm apart
    for m in re.finditer(_CNT + r"\s*(?:x\s*)?(?:holes?\s*)?" + _DIA + r"\s*" + _N + r"\s*(?:mm)?\s*(?:holes?)?\s*"
                         r"(?:in a (?:row|line)|spaced|pitch(?:ed)?)\s*(?:,?\s*(?:at|of)?\s*)?" + _N + r"\s*mm(?:\s*apart)?",
                         t, re.I):
        if free(m):
            take(m, pattern(_n(m.group(1)), _f(m.group(3)), _f(m.group(2))))
    # 4 x Ø5.2 | 4 holes Ø5.2 | four 5.2 mm holes | four Ø9 mm fastener holes
    for m in re.finditer(_CNT + r"\s*x\s*" + _DIA + r"\s*" + _N + r"(?:\s*mm)?(?:\s*holes?)?|" + _CNT + r"\s*holes?\s*(?:of\s*)?"
                         + _DIA + r"\s*" + _N + r"(?:\s*mm)?|" + _CNT + r"\s+" + _N + r"\s*mm\s*(?:diameter\s*)?holes?|"
                         + _CNT + r"\s+" + _DIA + r"\s*" + _N + r"\s*(?:mm)?\s*(?:[a-z]+\s+)?holes?", t, re.I):
        if free(m):
            g = [x for x in m.groups() if x]
            if _n(g[0]) == 1:                              # "one Ø8 hole here ... and one there": not a count of them all
                take(m, cylinder(_f(g[1]), "bore"))
            else:
                take(m, holes(_n(g[0]), _f(g[1])))
    # M6 thread | threaded M6x1 | M6 tapped
    for m in re.finditer(r"\bM(\d+(?:\.\d+)?)(?:\s*x\s*" + _N + r")?\s*(?:internal |external )?(?:thread(?:ed|s)?|tapped|tap\b)"
                         r"|(?:thread(?:ed)?|tapped)\s*(?:hole|bore|boss|insert)?s?\s*(?:for |of |: )?M(\d+(?:\.\d+)?)"
                         r"(?:\s*x\s*" + _N + r")?", t, re.I):
        if free(m):
            major = m.group(1) or m.group(3)
            pitch = m.group(2) or m.group(4)
            take(m, thread(_f(major), _f(pitch) if pitch else None))
    for m in re.finditer(r"\bthread(?:ed|s)?\b|\btapped\b", t, re.I):
        if free(m):
            missing.append({"what": "thread", "quote": t[max(0, m.start() - 30):m.end() + 30].strip(),
                            "need": "its size (for example M6, or M6x1)"})
            spans.append((m.start(), m.end()))
    # 2.4 mm wall | wall thickness 2.4 mm | walls at least 2 mm
    for m in re.finditer(_N + r"\s*mm\s*(?:min(?:imum)?\.?\s*)?(?:thick\s*)?walls?(?:\s*thickness)?|walls?\s*thickness\s*"
                         r"(?:of|:|=|>=|is|are|at least|min(?:imum)?\.?(?: of)?)?\s*" + _N + r"\s*mm|walls?\s*"
                         r"(?:of|:|=|>=|at least|min(?:imum)?\.?(?: of)?)\s*" + _N + r"\s*mm(?!\s*(?:wide|long|high|tall|deep))",
                         t, re.I):
        if free(m):
            take(m, wall(_f(m.group(1) or m.group(2) or m.group(3))))
    for m in re.finditer(r"\bwall(?:s| thickness)?\b", t, re.I):
        if free(m) and re.search(r"thick|thin|min|wall thickness", t[max(0, m.start() - 20):m.end() + 20], re.I):
            missing.append({"what": "wall thickness", "quote": t[max(0, m.start() - 30):m.end() + 30].strip(),
                            "need": "a number in mm"})
    # two-part | 3 separate parts
    for m in re.finditer(_CNT + r"[- ](?:separate\s+)?(?:part|piece)s?\b", t, re.I):
        if free(m):
            take(m, part_count(_n(m.group(1))))
    # outside diameter 30 mm | bore diameter 20 mm | a flange of diameter 60 mm | inside (hole) diameter 21 mm
    for m in re.finditer(r"(?:(outside|outer|external|bore|inside|inner|internal|hole|hub|flange|disc|disk|shaft|pin)\s*"
                         r"(?:\((hole|bore)\)\s*)?)?(?:of\s+)?diameter\s*(?:of\s*|is\s*|:\s*|=\s*)?" + _N + r"\s*mm", t, re.I):
        if free(m):
            word = (m.group(2) or m.group(1) or "").lower()
            if not word:
                b = re.search(r"(flange|disc|disk|hub|bore|hole|shaft|pin|boss|section|seat)s?\s*(?:of|is|has|with)?\s*$",
                              t[max(0, m.start() - 24):m.start()], re.I)
                word = b.group(1).lower() if b else ""
            of = "bore" if word in ("bore", "inside", "inner", "internal", "hole") else \
                "boss" if word in ("outside", "outer", "external", "hub", "flange", "disc", "disk", "shaft", "pin", "boss",
                                   "section", "seat") else "any"
            a = cylinder(_f(m.group(3)), of)
            if word in ("outside", "outer", "external", "flange", "disc", "disk"):
                a["outer"] = True
            take(m, a)
    # overall length 40 mm | total height of 36 mm (a part's own thickness is not an overall size: it is not read)
    for m in re.finditer(r"(?:overall|total)\s+(?:length|height|width|depth|size)\s*(?:of\s*|is\s*|:\s*|=\s*)?" + _N + r"\s*mm|"
                         r"(?:overall|total)\s+(?:length|height|width|depth)[^.;,]{0,24}?\bis\s+" + _N + r"\s*mm", t, re.I):
        if free(m):
            take(m, extent(_f(next(g for g in m.groups() if g))))
    # Ø68 flange | Ø30 bore | 30 mm diameter boss
    for m in re.finditer(_DIA + r"\s*" + _N + r"\s*(?:mm)?\s*(flange|disc|disk|plate|outer|rim|bore|boss|shaft|hub|post|pin|"
                         r"spigot|recess|pocket|counterbore)?|" + _N + r"\s*mm\s*(?:outer |outside |inner |inside )?diameter\s*"
                         r"(flange|disc|disk|plate|bore|boss|shaft|hub|post|pin|spigot|recess|pocket)?", t, re.I):
        if free(m):
            d = _f(m.group(1) or m.group(3))
            word = (m.group(2) or m.group(4) or "").lower()
            if not word:                                   # "flange Ø68": the word may come first
                b = re.search(r"(flange|disc|disk|plate|outer|rim|bore|boss|shaft|hub|post|pin|spigot|recess|pocket)"
                              r"\s*(?:of\s*|is\s*|:\s*)?$", t[max(0, m.start() - 16):m.start()], re.I)
                word = b.group(1).lower() if b else ""
            of = "bore" if word in ("bore", "recess", "pocket", "counterbore") else \
                "boss" if word in ("boss", "shaft", "hub", "post", "pin", "spigot", "flange", "disc", "disk", "plate",
                                   "outer", "rim") else "any"
            a = cylinder(d, of)
            if word in ("flange", "disc", "disk", "plate", "outer", "rim"):
                a["outer"] = True
            take(m, a)
    found.sort(key=lambda a: t.find(a["provenance"]["quote"]))
    return found, missing


def compile_brief(brief: dict, assertions: list | None = None) -> dict:
    """{"assertions", "audit", "version"} for a brief (form/staged.py): typed assertions the agent passed, those
    read from the brief's goal, requirements and constraints, and those named dimensions imply. Explicit ones win
    over read ones that say the same thing."""
    out: list = []
    problems: list = []
    missing: list = []
    for i, a in enumerate(assertions or []):
        try:
            out.append(normalise(a, {"source": "agent", "basis": "stated"}))
        except ContractError as e:
            problems.append({"what": f"assertion {i + 1}", "why": str(e)})
    texts = [("goal", brief.get("goal") or "")] + [("requirement", r) for r in brief.get("requirements") or []] \
        + [("constraint", c) for c in brief.get("constraints") or []]
    for where, tx in texts:
        got, miss = parse_text(str(tx))
        for a in got:
            a = normalise(a)
            a["provenance"]["where"] = where
            if not any(_same_subject(a, b) and _same_value(a, b) for b in out):
                out.append(a)
        missing += miss
    dims = brief.get("dimensions") or {}
    for name, d in dims.items():
        low = name.lower().replace("_", " ")
        val = d.get("value") if isinstance(d, dict) else d
        if not isinstance(val, (int, float)) or isinstance(val, bool) or (isinstance(d, dict) and d.get("unit", "mm") != "mm"):
            continue
        if re.search(r"\bwall\b", low) and not re.search(r"height|width|length|count", low):
            a = normalise(wall(val), {"source": f"dimension {name}", "basis": d.get("source", "assumed")})
            if not any(_same_subject(a, b) and _same_value(a, b) for b in out):
                out.append(a)
    size = _size_from_dims(dims)
    if size and not any(a["kind"] == "bbox" for a in out):
        out.append(normalise(bbox(*size[0]), {"source": "dimensions " + ", ".join(size[1]), "basis": size[2]}))
    for i, a in enumerate(out, 1):
        a["id"] = a.get("id") or f"c{i}"
    for u in brief.get("unknowns") or []:
        missing.append({"what": "unknown", "quote": str(u)[:200], "need": "an answer from the person, or a stated "
                                                                         "assumption"})
    au = audit(out)
    au["missing"] = missing + au["missing"]
    au["invalid"] = problems
    au["ok"] = not (au["conflicting"] or au["impossible"] or problems)
    return {"version": VERSION, "assertions": out, "audit": au}


def _size_from_dims(dims: dict):
    pick = {}
    for name, d in (dims or {}).items():
        low = name.lower()
        val = d.get("value") if isinstance(d, dict) else d
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        for ax, words in (("x", ("length", "overall_length")), ("y", ("width", "overall_width")),
                          ("z", ("height", "overall_height"))):
            if low in words:
                pick[ax] = (float(val), name, d.get("source", "assumed") if isinstance(d, dict) else "assumed")
    if len(pick) != 3:
        return None
    basis = {v[2] for v in pick.values()}
    return [pick[a][0] for a in "xyz"], [pick[a][1] for a in "xyz"], (basis.pop() if len(basis) == 1 else "mixed")


def _subject(a: dict) -> tuple:
    k = a["kind"]
    if k == "hole_count":
        return k, round(a["d"], 3)
    if k == "bolt_circle":
        return k, round(a["hole_d"], 3), round(a["circle_d"], 3)
    if k == "cylinder":
        return k, round(a["d"], 3), a.get("of", "any")
    if k == "thread":
        return k, round(a["major"], 3)
    if k == "face_count":
        return k, a.get("of", "any")
    if k == "pattern":
        return k, round(a["hole_d"], 3)
    if k == "extent":
        return k, round(a["mm"], 3), a.get("axis", "")
    return (k,)


def _value(a: dict):
    return {k: a[k] for k in ("size", "mm", "mm3", "count", "d", "hole_d", "circle_d", "pitch", "t", "major", "op", "of",
                              "any_order", "length") if k in a}


def _same_subject(a: dict, b: dict) -> bool:
    return a["kind"] == b["kind"] and (a["kind"] in ("bbox", "volume", "part_count", "min_wall") or _subject(a) == _subject(b))


def _same_value(a: dict, b: dict) -> bool:
    va, vb = _value(a), _value(b)
    if a["kind"] == "bbox":
        return sorted(va["size"]) == sorted(vb["size"])
    return va == vb


# ---- the audit: missing, conflicting, impossible -----------------------------------------------------------------

def audit(assertions: list) -> dict:
    """What is wrong with the numbers themselves, before any code: {"missing", "conflicting", "impossible", "ok"}.
    Arithmetic on the stated values only: nothing is measured."""
    conflicting, impossible, missing = [], [], []
    A = list(assertions)

    def ref(a):
        return a.get("id") or a["text"]
    for i, a in enumerate(A):
        for b in A[i + 1:]:
            if a["kind"] in ("bbox", "part_count", "min_wall") and b["kind"] == a["kind"] and not _same_value(a, b):
                conflicting.append({"between": [ref(a), ref(b)], "why": f"two different values for the same thing: "
                                    f"“{a['text']}” and “{b['text']}”"})
            if a["kind"] == "volume" and b["kind"] == "volume" and {a["op"], b["op"]} == {"min", "max"}:
                lo, hi = (a, b) if a["op"] == "min" else (b, a)
                if lo["mm3"] > hi["mm3"]:
                    impossible.append({"between": [ref(a), ref(b)], "why": f"volume at least {lo['mm3']:g} and at most "
                                       f"{hi['mm3']:g} mm³"})
    walls = [a for a in A if a["kind"] == "min_wall"]
    w = max((a["t"] for a in walls), default=None)
    boxes = [a for a in A if a["kind"] == "bbox"]
    outers = [a for a in A if a["kind"] == "cylinder" and a.get("outer")]
    for a in A:
        nums = [v for k, v in _value(a).items() if isinstance(v, (int, float)) and not isinstance(v, bool)] \
            + list(a.get("size") or [])
        if any(v <= 0 for v in nums) and a["kind"] != "face_count":
            impossible.append({"between": [ref(a)], "why": f"“{a['text']}” has a value that is zero or negative"})
            continue
        if a["kind"] == "bolt_circle":
            n, hd, cd = a["count"], a["hole_d"], a["circle_d"]
            if hd >= cd:
                impossible.append({"between": [ref(a)], "why": f"Ø{hd:g} holes do not fit on a Ø{cd:g} circle"})
            elif n >= 2:
                chord = cd * math.sin(math.pi / n)
                if hd >= chord:
                    impossible.append({"between": [ref(a)], "why": f"{n} holes of Ø{hd:g} on a Ø{cd:g} circle overlap: "
                                       f"their centres are {chord:.2f} mm apart"})
                elif w is not None and chord - hd < w - 1e-9:
                    conflicting.append({"between": [ref(a), ref(walls[0])], "why":
                                        f"between two neighbouring holes there is {chord - hd:.2f} mm of material "
                                        f"(centres {chord:.2f} mm apart on the Ø{cd:g} circle, holes Ø{hd:g}); the brief "
                                        f"asks for walls of at least {w:g} mm"})
            for o in outers:
                edge = (o["d"] - cd - hd) / 2.0
                if edge <= 0:
                    impossible.append({"between": [ref(a), ref(o)], "why": f"the holes break out of the Ø{o['d']:g} "
                                       f"edge: a Ø{cd:g} circle of Ø{hd:g} holes needs more than Ø{cd + hd:g}"})
                elif w is not None and edge < w - 1e-9:
                    conflicting.append({"between": [ref(a), ref(o), ref(walls[0])], "why":
                                        f"between a hole and the Ø{o['d']:g} edge there is {edge:.2f} mm "
                                        f"(({o['d']:g} - {cd:g} - {hd:g}) / 2); the brief asks for walls of at least "
                                        f"{w:g} mm, which needs an outside diameter of at least {cd + hd + 2 * w:g} mm"})
            for bx in boxes:
                big = sorted(bx["size"])[-1]
                if cd + hd > big:
                    impossible.append({"between": [ref(a), ref(bx)], "why": f"a Ø{cd:g} circle of Ø{hd:g} holes is "
                                       f"{cd + hd:g} mm across; the largest size is {big:g} mm"})
        if a["kind"] in ("hole_count", "pattern", "cylinder") and boxes:
            d = a.get("d") or a.get("hole_d")
            big = sorted(boxes[0]["size"])[-1]
            if d > big:
                impossible.append({"between": [ref(a), ref(boxes[0])], "why": f"Ø{d:g} is larger than the largest size, "
                                   f"{big:g} mm"})
        if a["kind"] == "pattern" and a["hole_d"] >= a["pitch"]:
            impossible.append({"between": [ref(a)], "why": f"Ø{a['hole_d']:g} holes {a['pitch']:g} mm apart overlap"})
        if a["kind"] == "min_wall" and boxes and 2 * a["t"] > sorted(boxes[0]["size"])[0]:
            impossible.append({"between": [ref(a), ref(boxes[0])], "why": f"two {a['t']:g} mm walls are thicker than the "
                               f"smallest size, {sorted(boxes[0]['size'])[0]:g} mm"})
        if a["kind"] == "volume" and a.get("op") == "eq" and (a.get("provenance") or {}).get("tolerance"):
            missing.append({"what": "tolerance", "quote": a["text"], "need": "how close the volume must be (tol, mm³), "
                            "or op min / max"})
        if a["kind"] == "thread" and a.get("pitch") and a["pitch"] * 4 > a["major"]:
            impossible.append({"between": [ref(a)], "why": f"a pitch of {a['pitch']:g} mm on M{a['major']:g} leaves no "
                               f"core"})
    return {"missing": missing, "conflicting": conflicting, "impossible": impossible,
            "ok": not (conflicting or impossible), "evidence": "arithmetic on the stated values; nothing measured"}


def audit_text(au: dict) -> str:
    """The audit as one message for the person (ask_user), or "" when there is nothing to settle."""
    rows = [f"Conflict: {x['why']}." for x in au.get("conflicting", [])] \
        + [f"Impossible: {x['why']}." for x in au.get("impossible", [])] \
        + [f"Missing: {x['what']} ({x['quote']}): {x['need']}." for x in au.get("missing", [])] \
        + [f"Not usable: {x['what']}: {x['why']}." for x in au.get("invalid", [])]
    return "\n".join(rows)


# ---- obligations: which feature must discharge an assertion ------------------------------------------------------

_WORDS_FOR = {
    "hole_count": ("hole", "bore", "drill", "mount", "screw", "bolt", "fixing", "vent", "slot"),
    "bolt_circle": ("bolt", "hole", "mount", "flange", "screw", "fixing", "pcd"),
    "pattern": ("hole", "pattern", "mount", "row", "vent", "screw"),
    "thread": ("thread", "bolt", "nut", "screw", "tap"),
    "min_wall": ("shell", "wall", "hollow", "cavity", "pocket", "body"),
    "cylinder": ("boss", "bore", "shaft", "hub", "post", "pin", "flange", "disc", "spigot", "body", "base"),
}


def assign(assertions: list, features: list) -> list:
    """Each assertion with "feature": the feature that must discharge it. An assertion that names a feature the
    design has keeps it; one written in a feature's expects= belongs to that feature; otherwise the first feature
    whose id or label has a word for that kind of requirement; otherwise the last feature (the finished design).
    features: [{"id", "label", "role"?, "expects"?}] in build order. Returns new dicts with "assigned": how."""
    ids = [f["id"] for f in features]
    out = []
    for a in assertions:
        b = dict(a)
        how = ""
        if b.get("feature") in ids:
            how = "named"
        else:
            b.pop("feature", None)
            for f in features:
                if any(_same_subject(a, e) and _same_value(a, e) for e in f.get("expects") or [] if isinstance(e, dict)
                       and e.get("kind") in KINDS):
                    b["feature"], how = f["id"], "expects"
                    break
        if not how and a["kind"] in _WORDS_FOR:
            want = _WORDS_FOR[a["kind"]]
            if a["kind"] == "cylinder":                    # a bore is owed by the feature that cuts, a boss by one that adds
                want = ("bore", "hole", "pocket", "recess", "counterbore") if a.get("of") == "bore" else \
                    ("boss", "shaft", "hub", "post", "pin", "spigot", "flange", "disc", "disk", "plate", "body", "base") \
                    if a.get("of") == "boss" else want
            for f in features:
                words = set(re.findall(r"[a-z]+", (f["id"] + " " + f.get("label", "")).lower().replace("_", " ")))
                words |= {w[:-1] for w in words if w.endswith("s")}
                if words & set(want):
                    b["feature"], how = f["id"], "matched by name"
                    break
        if not how and ids:
            b["feature"], how = ids[-1], "the finished design"
        b["assigned"] = how
        out.append(b)
    return out


# ---- a project's contract and its proof sheet --------------------------------------------------------------------

def of(p: dict) -> dict | None:
    """The contract a project carries (from its brief), or None."""
    d = (p or {}).get("design") or {}
    c = d.get("contract") or (d.get("brief") or {}).get("contract")
    return c if c and c.get("assertions") else None


def fingerprint(c: dict | None) -> str:
    if not c:
        return ""
    rows = [{k: v for k, v in a.items() if k not in ("provenance", "text", "assigned")} for a in c.get("assertions") or []]
    return hashlib.sha1(json.dumps([VERSION, rows], sort_keys=True, default=str).encode()).hexdigest()[:16]


def _features(st, p: dict) -> list:
    recipe = st.recipe(p)
    meta = getattr(type(recipe), "_form_meta", {}) or {}
    out = []
    for f in getattr(recipe, "features", None) or []:
        out.append({"id": f.id, "label": getattr(f, "label", "") or "", "role": getattr(f, "role", ""),
                    "expects": (meta.get(f.id) or {}).get("expects") or []})
    return out


def _sheet_path(st, p: dict, c: dict | None):
    from .studio import H
    key = H("proof", VERSION, st.keys(p)["geometry"], fingerprint(c))
    return st.dir(p["id"]) / "artifacts" / "proof" / f"{key}.json"


def prove(st, p: dict, compute: bool = True, timeout: float = 120) -> dict | None:
    """The proof sheet of the head revision: every contract assertion and every expects= postcondition, measured.

    Kept under a key made of the solid's key and the contract, so it is current exactly while both are (a sheet for
    another solid or another contract is simply not found). compute=False only reads it. None: the design has
    neither a contract nor expects=. A design that does not build has a sheet whose rows are UNPROVEN, with why."""
    c = of(p)
    feats = _features(st, p)
    has_expects = any(f["expects"] for f in feats)
    if not c and not has_expects:
        return None
    path = _sheet_path(st, p, c)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if not compute:
        return None
    asserts = assign((c or {}).get("assertions") or [], feats)
    rev = st.rev(p)
    from .studio import StudioError
    rows, err = [], ""
    from .studio import H
    gk = st.keys(p)["geometry"]
    # the model is still in a kernel worker under the key it was built with: the pipeline's when it has run for this
    # solid, else the key of the build that made the revision (asking under another key would build it again)
    key = gk if st.read(p, "geometry", gk) else "pv-" + H(st.rid(p), rev["values"])
    try:
        r = st._k("prove", key=key, recipe_id=st.rid(p), values=rev["values"], assertions=asserts,
                  p=p, rev=rev["n"], timeout=timeout)
        rows = r["rows"]
    except StudioError as e:
        err = str(e)[:300]
        rows = [{"id": a.get("id", ""), "requirement": a["text"], "kind": a["kind"], "wanted": _wanted(a),
                 "tolerance": a.get("tol"), "measured": None, "evidence": "none", "status": "UNPROVEN",
                 "feature": a.get("feature", ""), "why": "the design did not build: " + err,
                 "provenance": a.get("provenance") or {}, "source": "contract"} for a in asserts]
    sheet = _sheet(p, rows, c, err)
    if not err:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(sheet, indent=1, default=str), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
    return sheet


def _wanted(a: dict) -> str:
    return a["text"]


def _sheet(p: dict, rows: list, c: dict | None, err: str = "") -> dict:
    n = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    part = (next((r for r in p["revisions"] if r["n"] == p["head"]), {}) or {}).get("partial")
    return {"version": VERSION, "rev": p["head"], "ts": time.time(), "rows": rows, "counts": n,
            "green": bool(rows) and n["FAIL"] == 0 and n["UNPROVEN"] == 0 and not part,
            "partial": bool(part), **({"error": err} if err else {}),
            "audit": (c or {}).get("audit") or {},
            "note": "PASS and FAIL are measured on the kernel's solid of this revision; UNPROVEN was not measured "
                    "and is never a pass. Nothing here is a physical result."}


def table(sheet: dict | None) -> list:
    """The proof sheet as the rows get_project and a commit return: requirement, measured, tolerance, evidence class,
    status (and the feature it is an obligation of; for a FAIL, what was wanted)."""
    if not sheet:
        return []
    out = []
    for r in sheet["rows"]:
        row = {"id": r.get("id", ""), "requirement": r["requirement"], "measured": r.get("measured_text") or r.get("measured"),
               "tolerance": (f"±{r['tolerance']:g} mm" if isinstance(r.get("tolerance"), (int, float)) else "exact"),
               "evidence": r["evidence"], "status": r["status"], "feature": r.get("feature", "")}
        if r["status"] != "PASS" and r.get("why"):
            row["why"] = r["why"]
        for k in ("where", "repair", "at"):
            if r.get(k) and r["status"] != "PASS":
                row[k] = r[k]
        out.append(row)
    return out


def summary(sheet: dict | None) -> str:
    if not sheet:
        return ""
    n = sheet["counts"]
    return (f"{n['PASS']} of {len(sheet['rows'])} requirements proved" + (f", {n['FAIL']} failed" if n["FAIL"] else "")
            + (f", {n['UNPROVEN']} not proved" if n["UNPROVEN"] else "") + f" (r{sheet['rev']:02d})")


def gate_reason(st, p: dict) -> str | None:
    """Why the contract blocks a release (read only: a sheet that was never made is said to be missing)."""
    c = of(p)
    if not c:
        return None
    sheet = prove(st, p, compute=False)
    if sheet is None:
        return (f"The requirements of the brief have not been measured on r{p['head']:02d} yet (they are measured "
                "with the checks).")
    bad = [r for r in sheet["rows"] if r["status"] == "FAIL"]
    if bad:
        return (f"{len(bad)} requirement(s) of the brief fail on r{p['head']:02d}: "
                + "; ".join(f"{r['requirement']} (measured {r.get('measured_text') or r.get('measured')})" for r in bad[:3])
                + ("; ..." if len(bad) > 3 else "") + ".")
    return None


def claim_gate(st, p: dict, compute: bool = True) -> dict:
    """What a summary at the end of a run may claim about the head revision. For the chat's claim gate (WP7).

        {"rev", "has_contract", "green", "may_claim": [requirement texts that are PASS],
         "must_not_claim": [{"requirement", "status", "measured", "why"}] (FAIL and UNPROVEN),
         "unsettled": the audit's open items (conflicting, impossible, missing), "summary": one line,
         "evidence": {"computed": n, "heuristic": n, "none": n}, "physical": False}

    A design without a contract has has_contract False and empty lists: nothing was promised in checkable form, so
    nothing is proved either, and a summary must not say "meets the requirements". physical is always False here:
    a proof sheet is about the kernel's solid, never about a print."""
    sheet = prove(st, p, compute=compute)
    c = of(p)
    if sheet is None:
        return {"rev": p["head"], "has_contract": bool(c), "green": False, "may_claim": [], "must_not_claim": [],
                "unsettled": [], "summary": "No checkable contract: nothing is proved about the brief."
                if not c else "The contract has not been measured for this revision.",
                "evidence": {}, "physical": False, "stale": bool(c)}
    rows = sheet["rows"]
    ev: dict = {}
    for r in rows:
        ev[r["evidence"]] = ev.get(r["evidence"], 0) + 1
    au = sheet.get("audit") or {}
    unsettled = [x["why"] for x in au.get("conflicting", [])] + [x["why"] for x in au.get("impossible", [])] \
        + [f"{x['what']}: {x['need']}" for x in au.get("missing", [])]
    return {"rev": sheet["rev"], "has_contract": bool(c), "green": sheet["green"],
            "may_claim": [r["requirement"] for r in rows if r["status"] == "PASS"],
            "must_not_claim": [{"requirement": r["requirement"], "status": r["status"],
                                "measured": r.get("measured_text") or r.get("measured"), "why": r.get("why", ""),
                                "feature": r.get("feature", "")} for r in rows if r["status"] != "PASS"],
            "unsettled": unsettled, "summary": summary(sheet), "evidence": ev, "physical": False,
            "partial": sheet.get("partial", False)}
