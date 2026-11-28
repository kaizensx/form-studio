"""Post-processors: a program's events written as G-code for one controller, and read back.

Dialects (`DIALECTS`), each with what it accepts:

    grbl       Grbl 1.1. No tool changer (M6 is an error there) and no canned cycles: a tool change is M5 and a
               program pause (M0) with the tool named in a comment; drilling is written out as G0/G1.
    linuxcnc   LinuxCNC (RS274/NGC). T.. M6 and G43 H.., path blending G64 P0.01, canned G81/G83 with G98,
               a machine-coordinate retract G53 G0 Z0, M2.
    fanuc      A generic Fanuc mill. % and an O number, T.. M6, G43 H.. on the first Z move, canned G81/G83 with
               G98, G91 G28 Z0 to retract, M30, %.
    haas       Haas mills. As Fanuc with O and a five-digit number, G53 G0 Z0 to retract.
    marlin     Marlin with a spindle (a router or a converted printer). Semicolon comments; G0 moves carry the
               rapid rate as F because Marlin runs G0 at the last feedrate; no canned cycles, no M6, no G54
               unless a work offset other than G54 is asked for (CNC_COORDINATE_SYSTEMS), no M2/M30.

Every program says its units (G21 or G20), absolute distances (G90), the XY plane (G17, where the controller
knows it), feed per minute (G94, likewise) and its work offset (G54 to G59). Words are modal: a motion word, an
axis or a feed is written when it changes. Coordinates are written with three decimals in millimetres and four in
inches, and the arc centre (I, J) is taken from the rounded start point, so the arc a controller reads closes
within its own tolerance.

`parse` reads a posted file back into the same events (form/cam/motion.py), converting inches, expanding nothing:
a canned cycle comes back as a ("drill", ...) event, which `motion.primitives` writes out the way the controller
runs it. `parse` also lists what the dialect does not accept. The stock simulation runs on what `parse` returns,
so the file itself is what is checked.
"""
from __future__ import annotations

import math
import re

LABEL = "simulated, not proven on a machine"

_COMMON_G = {0, 1, 2, 3, 4, 20, 21, 90}
DIALECTS = {
    "grbl": {"label": "Grbl 1.1", "ext": ".nc", "comment": "paren", "canned": False, "m6": False, "tlo": False,
             "g": _COMMON_G | {17, 28, 40, 49, 53, 54, 55, 56, 57, 58, 59, 80, 91, 94},
             "m": {0, 2, 3, 5, 7, 8, 9, 30}, "dwell": "P_s", "end": ["M2"], "home": "G53 G0 Z0",
             "safety": "G17 G40 G49 G80 G94"},
    "linuxcnc": {"label": "LinuxCNC", "ext": ".ngc", "comment": "paren", "canned": True, "m6": True, "tlo": True,
                 "g": _COMMON_G | {17, 28, 40, 43, 49, 53, 54, 55, 56, 57, 58, 59, 61, 64, 80, 81, 83, 91, 94, 98, 99},
                 "m": {0, 1, 2, 3, 5, 6, 7, 8, 9, 30}, "dwell": "P_s", "end": ["M2"], "home": "G53 G0 Z0",
                 "safety": "G17 G40 G49 G80 G94", "blend": "G64 P0.01"},
    "fanuc": {"label": "Fanuc (generic mill)", "ext": ".nc", "comment": "paren", "canned": True, "m6": True, "tlo": True,
              "g": _COMMON_G | {17, 28, 40, 43, 49, 53, 54, 55, 56, 57, 58, 59, 80, 81, 83, 91, 94, 98, 99},
              "m": {0, 1, 3, 5, 6, 7, 8, 9, 30}, "dwell": "P_ms", "end": ["M30"], "home": "G91 G28 Z0", "percent": True,
              "onum": "O1000", "upper": True, "safety": "G17 G40 G49 G80 G94", "tlo_on_move": True},
    "haas": {"label": "Haas mill", "ext": ".nc", "comment": "paren", "canned": True, "m6": True, "tlo": True,
             "g": _COMMON_G | {17, 28, 40, 43, 49, 53, 54, 55, 56, 57, 58, 59, 80, 81, 83, 91, 94, 98, 99},
             "m": {0, 1, 3, 5, 6, 7, 8, 9, 30}, "dwell": "P_ms", "end": ["M30"], "home": "G53 G0 Z0", "percent": True,
             "onum": "O00001", "upper": True, "safety": "G17 G40 G49 G80 G94", "tlo_on_move": True},
    "marlin": {"label": "Marlin (CNC)", "ext": ".gcode", "comment": "semi", "canned": False, "m6": False, "tlo": False,
               "g": _COMMON_G | {54, 55, 56, 57, 58, 59, 91}, "m": {0, 3, 5, 400}, "dwell": "S_s", "end": [], "home": None,
               "safety": "", "g0_feed": True},
}
ALIASES = {"grbl1.1": "grbl", "grbl_1.1": "grbl", "emc": "linuxcnc", "emc2": "linuxcnc", "fanuc_generic": "fanuc",
           "fanuc-generic": "fanuc", "generic": "fanuc", "marlin_cnc": "marlin", "marlin-cnc": "marlin", "mach3": "fanuc"}
ARC_CLOSE_TOL = 0.005        # mm: start and end radius of an arc may differ by this (Grbl's own limit)


def _err(msg, hint=""):
    from ..studio import StudioError
    return StudioError(msg, hint)


def dialect_id(name) -> str:
    s = str(name or "").strip().lower().replace(" ", "_")
    s = ALIASES.get(s, s)
    if s not in DIALECTS:
        raise _err(f"Unknown post-processor “{name}”.", "Posts: " + ", ".join(DIALECTS) + ".")
    return s


def _ascii(s: str, upper: bool = False) -> str:
    s = str(s).replace("Ø", "D").replace("×", "x").replace("°", " deg").replace("“", '"').replace("”", '"').replace("—", "-")
    s = s.replace("(", "[").replace(")", "]").replace(";", ",").replace("%", " pct")
    s = "".join(c if 32 <= ord(c) < 127 else "?" for c in s)
    return s.upper() if upper else s


class _Writer:
    def __init__(self, dialect: str, units: str, mach: dict):
        self.d = DIALECTS[dialect]
        self.id = dialect
        self.inch = units == "inch"
        self.k = 1 / 25.4 if self.inch else 1.0
        self.nd = 4 if self.inch else 3
        self.lines: list[str] = []
        self.pos = [None, None, None]
        self.g = None                # the modal motion word
        self.f = None
        self.rapid_f = float(mach.get("rapid", 3000.0))

    def num(self, v: float) -> str:
        s = f"{round(v * self.k, self.nd):.{self.nd}f}"
        return "0." + "0" * self.nd if float(s) == 0 else s

    def rnd(self, v: float) -> float:
        """The value a controller reads back, in mm."""
        return round(v * self.k, self.nd) / self.k

    def fnum(self, f: float) -> str:
        return f"{round(f * self.k, 2 if self.inch else 1):.{2 if self.inch else 1}f}"

    def comment(self, text: str) -> None:
        t = _ascii(text, self.d.get("upper", False))
        self.lines.append(f"({t})" if self.d["comment"] == "paren" else f"; {t}")

    def raw(self, line: str) -> None:
        self.lines.append(line)

    def _axes(self, x, y, z) -> str:
        out = []
        for i, (ax, v) in enumerate(zip("XYZ", (x, y, z))):
            r = self.rnd(v)
            if self.pos[i] is None or abs(r - self.pos[i]) > 1e-9:
                out.append(f"{ax}{self.num(v)}")
                self.pos[i] = r
        return " ".join(out)

    def move(self, kind: str, x, y, z, f=None, extra: str = "") -> None:
        first = None in self.pos
        if first and kind == "rapid":                # to the safe height first, then over the work
            self.pos[2] = self.rnd(z)
            self.lines.append(self._g("G0") + f"Z{self.num(z)}" + (f" {extra}" if extra else "") + self._g0f())
            extra = ""
        ax = self._axes(x, y, z)
        if not ax and not extra:
            return
        word = "G0" if kind == "rapid" else "G1"
        line = self._g(word) + ax + (f" {extra}" if extra else "")
        if kind == "feed":
            line += self._feed(f)
        else:
            line += self._g0f()
        self.lines.append(line.strip())

    def _g(self, word: str) -> str:
        if self.g == word:
            return ""
        self.g = word
        return word + " "

    def _feed(self, f) -> str:
        if f is None or (self.f is not None and abs(self.f - f) < 1e-9):
            return ""
        self.f = f
        return f" F{self.fnum(f)}"

    def _g0f(self) -> str:
        if not self.d.get("g0_feed"):
            return ""
        return self._feed(self.rapid_f)

    def arc(self, x, y, z, cx, cy, cw, f) -> None:
        sx, sy = self.pos[0], self.pos[1]
        word = "G2" if cw else "G3"
        self.g = word
        zw = "" if abs(self.rnd(z) - self.pos[2]) < 1e-9 else f" Z{self.num(z)}"
        line = f"{word} X{self.num(x)} Y{self.num(y)}{zw} I{self.num(cx - sx)} J{self.num(cy - sy)}" + self._feed(f)
        self.pos = [self.rnd(x), self.rnd(y), self.rnd(z)]
        self.lines.append(line)


def post(events, dialect: str = "grbl", name: str = "program", units: str = "mm", wcs: str = "G54",
         tools: dict | None = None, mach: dict | None = None, header: list | None = None, line_numbers: bool = False,
         label: str = LABEL) -> str:
    """G-code for the events in a dialect. tools: {number: text} for the comments. header: extra comment lines
    (stock, zero, the simulation's key). The label is written at the top of every program."""
    did = dialect_id(dialect)
    d = DIALECTS[did]
    if units not in ("mm", "inch"):
        raise _err("units is mm or inch.")
    wcs = str(wcs or "G54").upper()
    if wcs not in ("G54", "G55", "G56", "G57", "G58", "G59"):
        raise _err("The work offset is G54 to G59.")
    w = _Writer(did, units, mach or {})
    tools = tools or {}
    if d.get("percent"):
        w.raw("%")
    if d.get("onum"):
        w.raw(f"{d['onum']} ({_ascii(name, True)[:40]})")
    w.comment(f"{name} - {d['label']}")
    w.comment(label)
    if did == "marlin" and wcs == "G54":
        w.comment(f"units {units}, work zero as set on the machine: no work offset word is sent")
    else:
        w.comment(f"units {units}, work offset {wcs}, Z0 and XY0 as stated below")
    for h in header or []:
        w.comment(h)
    for n, t in sorted(tools.items()):
        w.comment(f"T{n}: {t}")
    w.raw("G20" if w.inch else "G21")
    w.raw("G90")
    if d["safety"]:
        w.raw(d["safety"])
    if d.get("blend"):
        w.raw(d["blend"])
    if did != "marlin" or wcs != "G54":
        w.raw(wcs)
    first_tool, spindle_on, pending_tlo = True, False, None
    from . import motion
    ev = list(events) if d["canned"] else motion.primitives(events)
    in_cycle = False
    for e in ev:
        k = e[0]
        if in_cycle and k != "drill":
            w.raw("G80")
            w.g = None
            in_cycle = False
        if k == "op":
            w.comment(f"OP {int(e[1])}: {e[2]}")
        elif k == "tool":
            n = int(e[1])
            if d["m6"]:
                w.raw(f"T{n} M6")
                if d["tlo"]:
                    if d.get("tlo_on_move"):
                        pending_tlo = n
                    else:
                        w.raw(f"G43 H{n}")
            else:
                if spindle_on:
                    w.raw("M5")
                    spindle_on = False
                w.comment(f"change to T{n}: {tools.get(n, '')}")
                if did == "grbl":
                    w.raw(f"T{n}")                  # Grbl records the T word; it has no M6
                if not first_tool:
                    w.raw("M0")                     # the program waits here for the person to change the tool
            first_tool = False
            w.pos = [None, None, None]            # after a tool change the program positions again
            w.g = None
        elif k == "spindle":
            w.raw(f"M3 S{int(round(e[1]))}")
            spindle_on = True
        elif k == "stop":
            w.raw("M5")
            spindle_on = False
        elif k == "coolant":
            if did != "marlin":
                w.raw({"flood": "M8", "mist": "M7", "off": "M9"}[e[1]])
        elif k == "rapid":
            extra = ""
            if pending_tlo is not None:
                extra, pending_tlo = f"G43 H{pending_tlo}", None
            w.move("rapid", e[1], e[2], e[3], extra=extra)
        elif k == "feed":
            w.move("feed", e[1], e[2], e[3], e[4])
        elif k == "arc":
            w.arc(*e[1:])
        elif k == "drill":
            _, x, y, z, r, q, f = e
            cyc = "G83" if q and q > 0 else "G81"
            line = f"G98 {cyc} X{w.num(x)} Y{w.num(y)} Z{w.num(z)} R{w.num(r)}"
            if q and q > 0:
                line += f" Q{w.num(q)}"
            w.f = f
            line += f" F{w.fnum(f)}"
            w.raw(line)
            w.pos = [w.rnd(x), w.rnd(y), w.pos[2] if w.pos[2] is not None else w.rnd(r)]
            w.g = None
            in_cycle = True
        elif k == "dwell":
            s = float(e[1])
            w.raw({"P_s": f"G4 P{s:.3f}", "P_ms": f"G4 P{int(round(s * 1000))}", "S_s": f"G4 S{s:.3f}"}[d["dwell"]])
        elif k == "home":
            if d["home"]:
                w.raw(d["home"])
                if "G91" in d["home"]:
                    w.raw("G90")
                w.g = None
                w.pos[2] = None
        elif k == "end":
            if spindle_on:
                w.raw("M5")
                spindle_on = False
            for line in d["end"]:
                w.raw(line)
    if in_cycle:
        w.raw("G80")
    if d.get("percent"):
        w.raw("%")
    lines = w.lines
    if line_numbers and d["comment"] == "paren":
        out, n = [], 10
        for ln in lines:
            if ln == "%" or ln.startswith("O") or ln.startswith("("):
                out.append(ln)
            else:
                out.append(f"N{n} {ln}")
                n += 10
        lines = out
    return "\n".join(lines) + "\n"


# ---- reading it back -------------------------------------------------------------------------------------------

_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_OP = re.compile(r"OP\s+(\d+)\s*:\s*(.*)", re.I)
_CHANGE = re.compile(r"change to T(\d+)", re.I)


def parse(text: str, dialect: str = "grbl") -> dict:
    """Read a G-code file as a controller of the dialect would. {"events", "units", "wcs", "problems": [text],
    "lines", "codes": {"G": [...], "M": [...]}, "tools": [numbers], "spindle": [rpm values], "feeds": [values]}.
    A problem is something the dialect does not accept, or something this reader does not simulate (another
    plane, cutter compensation, an R-format arc)."""
    did = dialect_id(dialect)
    d = DIALECTS[did]
    events: list = []
    problems: list[str] = []
    gs, ms = set(), set()
    k = 1.0
    units, wcs = None, None
    pos = [None, None, None]
    started = False
    absolute = True
    motion_g = None
    feed = None
    cyc = None            # the modal canned cycle: {"g", "z", "r", "q"}
    tools, spindle, feeds = [], [], []
    pend_t = None
    nlines = 0

    def note(msg, ln):
        if len(problems) < 50:
            problems.append(f"line {ln}: {msg}")

    def emit(kind, tgt, f=None, arc=None):
        nonlocal started
        if None in tgt:
            return
        if not started:
            started = True
            events.append(("rapid", *tgt))
            return
        if kind == "rapid":
            events.append(("rapid", *tgt))
        elif kind == "feed":
            events.append(("feed", *tgt, f))
        else:
            events.append(("arc", *tgt, arc[0], arc[1], arc[2], f))

    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line == "%":
            continue
        nlines += 1
        comments = re.findall(r"\(([^)]*)\)", line)
        line = re.sub(r"\([^)]*\)", " ", line)
        if ";" in line:
            line, _, c = line.partition(";")
            comments.append(c)
        for c in comments:
            m = _OP.match(c.strip())
            if m:
                events.append(("op", int(m.group(1)), m.group(2).strip()))
            m = _CHANGE.match(c.strip())
            if m and not d["m6"]:                     # no tool changer: the tool is the one the comment names
                tools.append(int(m.group(1)))
                events.append(("tool", int(m.group(1))))
        if d["comment"] == "semi" and re.search(r"\(", raw.split(";")[0]):
            note("a comment in parentheses (this controller reads only ; comments)", ln)
        words = [(a.upper(), float(b)) for a, b in _WORD.findall(line)]
        if not words:
            continue
        if words[0][0] == "O":
            words = words[1:]
        w = {}
        gl, ml = [], []
        for a, v in words:
            if a == "G":
                gl.append(v)
            elif a == "M":
                ml.append(int(v))
            elif a == "N":
                continue
            else:
                w[a] = v
        for g in gl:
            gi = int(g) if abs(g - int(g)) < 1e-9 else g
            gs.add(gi)
            if gi not in d["g"]:
                note(f"G{g:g} is not accepted by {d['label']}", ln)
        for m in ml:
            ms.add(m)
            if m not in d["m"]:
                note(f"M{m} is not accepted by {d['label']}", ln)
        home = False
        dwell = False
        for g in gl:
            gi = int(g)
            if g in (20, 21):
                k = 25.4 if g == 20 else 1.0
                units = "inch" if g == 20 else "mm"
            elif g in (90, 91):
                absolute = g == 90
            elif 54 <= g <= 59 and g == gi:
                wcs = f"G{gi}"
            elif g in (0, 1, 2, 3):
                motion_g, cyc = gi, None
            elif g in (81, 83):
                motion_g = gi
                cyc = {"g": gi, "z": None, "r": None, "q": 0.0}
            elif g == 80:
                cyc = None
                if motion_g in (81, 83):
                    motion_g = None
            elif g in (28, 53):
                home = True
            elif g == 4:
                dwell = True
            elif g in (18, 19):
                note("only the XY plane (G17) is simulated", ln)
            elif g in (41, 42):
                note("cutter compensation is not simulated", ln)
        if "F" in w:
            feed = w["F"] * k
            feeds.append(feed)
        if "S" in w and not dwell:
            spindle.append(w["S"])
        if "T" in w:
            pend_t = int(w["T"])
        for m in ml:
            if m == 6:
                if pend_t is None:
                    note("M6 with no tool selected", ln)
                else:
                    tools.append(pend_t)
                    events.append(("tool", pend_t))
            elif m in (3, 4):
                events.append(("spindle", w.get("S", spindle[-1] if spindle else 0.0)))
            elif m == 5:
                events.append(("stop",))
            elif m in (7, 8, 9):
                events.append(("coolant", {7: "mist", 8: "flood", 9: "off"}[m]))
            elif m in (2, 30):
                events.append(("end",))
        if dwell:
            if "S" in w and d["dwell"] == "S_s":
                sec = w["S"]
            elif "P" in w:
                sec = w["P"] / 1000.0 if d["dwell"] in ("P_ms", "S_s") else w["P"]
            else:
                sec = 0.0
            events.append(("dwell", sec))
            continue
        if home:
            events.append(("home",))
            continue
        if not any(a in w for a in "XYZIJR") and not (cyc and gl):
            continue
        if "R" in w and motion_g in (2, 3):
            note("an arc given by R is not read; arcs are posted with I and J", ln)
            continue
        tgt = list(pos)
        for i, ax in enumerate("XYZ"):
            if ax in w and not (cyc and ax == "Z"):
                v = w[ax] * k
                tgt[i] = v if absolute or pos[i] is None else pos[i] + v
        if cyc is not None:
            if "Z" in w:
                cyc["z"] = w["Z"] * k
            if "R" in w:
                cyc["r"] = w["R"] * k
            if "Q" in w:
                cyc["q"] = abs(w["Q"]) * k
            if None in (cyc["z"], cyc["r"], tgt[0], tgt[1]) or feed is None:
                note("a drilling cycle needs X, Y, Z, R and F", ln)
                continue
            if 99 in [int(g) for g in gl]:
                note("G99 (retract to R) is read as G98 (retract to the initial level)", ln)
            if not started or pos[2] is None:
                note("a drilling cycle before the tool has been positioned in Z", ln)
                continue
            events.append(("drill", tgt[0], tgt[1], cyc["z"], cyc["r"], cyc["q"] if cyc["g"] == 83 else 0.0, feed))
            pos[0], pos[1] = tgt[0], tgt[1]
            continue
        if motion_g is None:
            note("axis words with no motion mode", ln)
            continue
        if motion_g == 0:
            emit("rapid", tgt)
        elif motion_g == 1:
            if feed is None:
                note("G1 with no feed", ln)
                feed = 1.0
            emit("feed", tgt, feed)
        else:
            if None in pos:
                note("an arc before the tool has been positioned", ln)
            else:
                cx, cy = pos[0] + w.get("I", 0.0) * k, pos[1] + w.get("J", 0.0) * k
                r0 = math.hypot(pos[0] - cx, pos[1] - cy)
                r1 = math.hypot(tgt[0] - cx, tgt[1] - cy)
                if abs(r0 - r1) > ARC_CLOSE_TOL:
                    note(f"arc ends {abs(r0 - r1):.4f} mm off its radius", ln)
                if feed is None:
                    note("an arc with no feed", ln)
                    feed = 1.0
                emit("arc", tgt, feed, (cx, cy, motion_g == 2))
        pos = tgt
    if units is None:
        problems.append("the program never states its units (G20 or G21)")
    return {"events": events, "units": units or "mm", "wcs": wcs or "G54", "problems": problems, "lines": nlines,
            "codes": {"G": sorted(gs, key=float), "M": sorted(ms)}, "tools": tools, "spindle": spindle, "feeds": feeds,
            "dialect": did}


def rounded(events, units: str = "mm") -> list:
    """The events as a controller reads them back: every coordinate at the precision the post writes."""
    k, nd = (1 / 25.4, 4) if units == "inch" else (1.0, 3)

    def r(v):
        return round(v * k, nd) / k
    out = []
    for e in events:
        if e[0] in ("rapid", "feed"):
            out.append((e[0], r(e[1]), r(e[2]), r(e[3]), *e[4:]))
        elif e[0] == "arc":
            out.append(("arc", r(e[1]), r(e[2]), r(e[3]), e[4], e[5], e[6], e[7]))
        elif e[0] == "drill":
            out.append(("drill", r(e[1]), r(e[2]), r(e[3]), r(e[4]), r(e[5]) if e[5] else 0.0, e[6]))
        else:
            out.append(e)
    return out


def same_motion(a, b, units: str = "mm", canned: bool = True) -> tuple[bool, str]:
    """Whether the program `a` (as written by an operation) and `b` (as read back from its posted file) are the
    same motion: the same moves in the same order, every end point equal at the posted precision, arc centres
    within that precision, feeds within the posted precision of the feed word. canned: the dialect keeps drilling
    cycles as cycles (their words are rounded, then the controller works out the moves); without, the moves were
    written out first and each then rounded."""
    from . import motion
    keep = ("rapid", "feed", "arc")
    tol = 1e-6
    ctol = 2.5e-3 if units == "inch" else 1.1e-3
    if not canned:
        a = motion.primitives(a)

    def moves(ev):
        out, last = [], None
        for e in motion.primitives(ev):
            if e[0] not in keep:
                continue
            p = (e[1], e[2], e[3])
            if last is None:
                last = p
                continue                               # the first position is where the tool starts
            if e[0] != "arc" and max(abs(p[i] - last[i]) for i in range(3)) < tol:
                continue
            out.append(e)
            last = p
        return out
    pa, pb = moves(rounded(a, units)), moves(b)
    if len(pa) != len(pb):
        return False, f"{len(pa)} moves against {len(pb)}"
    for i, (x, y) in enumerate(zip(pa, pb)):
        if x[0] != y[0]:
            return False, f"move {i}: {x[0]} against {y[0]}"
        for j in (1, 2, 3):
            if abs(x[j] - y[j]) > tol:
                return False, f"move {i}: {x[:4]} against {y[:4]}"
        if x[0] == "arc":
            if abs(x[4] - y[4]) > ctol or abs(x[5] - y[5]) > ctol or bool(x[6]) != bool(y[6]):
                return False, f"arc {i}: centre {x[4:7]} against {y[4:7]}"
        fx = x[4] if x[0] == "feed" else x[7] if x[0] == "arc" else None
        fy = y[4] if y[0] == "feed" else y[7] if y[0] == "arc" else None
        if fx is not None and abs(fx - fy) > 0.13:
            return False, f"move {i}: feed {fx} against {fy}"
    return True, ""
