"""Read an IDF 3.0 board (.emn, with its .emp library when it is beside it): outline, thickness, drilled holes,
placed parts, and each part's outline and height from the library.

IDF is the board-to-mechanical exchange format most ECAD programs write (KiCad: File > Export > IDF). Units are
the header's MM or THOU (mils). The y axis already points away from the viewer, so nothing is flipped.
"""
from __future__ import annotations

import hashlib
import shlex
from pathlib import Path

from . import model


def _sections(text: str) -> dict:
    out: dict = {}
    cur, buf = None, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(".END_"):
            if cur:
                out.setdefault(cur, []).append(buf)
            cur, buf = None, []
        elif line.startswith(".") and cur is None:
            cur, buf = line.split()[0][1:], [line]
        elif cur:
            buf.append(line)
    return out


def _toks(line: str) -> list:
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def _loops(lines: list, k: float) -> list:
    """IDF loop records "label x y angle" as closed point loops (an angle is an arc to that point)."""
    loops: dict = {}
    for ln in lines:
        t = _toks(ln)
        if len(t) < 4:
            continue
        lab, x, y, ang = int(float(t[0])), float(t[1]) * k, float(t[2]) * k, float(t[3])
        pts = loops.setdefault(lab, [])
        if pts and abs(ang) > 1e-9:
            if abs(ang - 360) < 1e-6 or abs(ang + 360) < 1e-6:       # a full circle: centre, then a point on it
                c = pts.pop()
                r = ((x - c[0]) ** 2 + (y - c[1]) ** 2) ** 0.5
                pts.extend(model.circle(c, r))
                continue
            a = pts[-1]
            # arc from a to (x, y) sweeping ang degrees (positive: counter-clockwise)
            import math
            ch = math.hypot(x - a[0], y - a[1])
            sw = math.radians(ang)
            r = ch / (2 * math.sin(abs(sw) / 2)) if abs(math.sin(sw / 2)) > 1e-12 else 0
            mx, my = (a[0] + x) / 2, (a[1] + y) / 2
            h = (max(r * r - (ch / 2) ** 2, 0)) ** 0.5
            nx, ny = -(y - a[1]) / ch, (x - a[0]) / ch
            sgn = 1 if (ang > 0) == (abs(ang) < 180) else -1
            c = (mx + sgn * h * nx, my + sgn * h * ny)
            pts.extend(model.arc_center(c, a, ang)[1:])
        else:
            pts.append((x, y))
    out = []
    for lab in sorted(loops):
        p = loops[lab]
        if len(p) > 2 and abs(p[0][0] - p[-1][0]) < 1e-6 and abs(p[0][1] - p[-1][1]) < 1e-6:
            p = p[:-1]
        if len(p) >= 3:
            out.append(p)
    return out


def _units(header: list) -> float:
    for ln in header[1:]:
        if ln.split()[-1].upper() in ("MM", "THOU"):
            return 0.0254 if ln.split()[-1].upper() == "THOU" else 1.0
    return 1.0


def read_library(path: Path, k_default: float = 1.0) -> dict:
    """{(geometry, part number): {"height", "outline"}} from an .emp."""
    if not path.is_file():
        return {}
    sec = _sections(path.read_text(encoding="utf-8", errors="replace"))
    lib = {}
    for kind in ("ELECTRICAL", "MECHANICAL"):
        for block in sec.get(kind, []):
            if len(block) < 2:
                continue
            t = _toks(block[1])
            if len(t) < 4:
                continue
            k = 0.0254 if t[2].upper() == "THOU" else 1.0
            lib[(t[0], t[1])] = {"height": float(t[3]) * k, "outline": (_loops(block[2:], k) or [[]])[0]}
    return lib


def read(path: str | Path, origin=None) -> dict:
    p = Path(path)
    data = p.read_bytes()
    sec = _sections(data.decode("utf-8", errors="replace"))
    if "HEADER" not in sec or "BOARD_OUTLINE" not in sec:
        raise ValueError(f"{p.name} is not an IDF board file (.emn): it has no HEADER or BOARD_OUTLINE section.")
    k = _units(sec["HEADER"][0])
    ob = sec["BOARD_OUTLINE"][0]
    t = float(_toks(ob[1])[0]) * k
    loops = _loops(ob[2:], k)
    raw = {"format": "idf", "y_down": False, "file": p.name, "sha256": hashlib.sha256(data).hexdigest(),
           "thickness": {"value": round(t, 4), "source": "the IDF board outline (thickness)", "provenance": "specified"},
           "edge_loops": loops, "holes": [], "components": [], "notes": [],
           "origin": list(origin) if origin else None}
    for block in sec.get("DRILLED_HOLES", []):
        for ln in block[1:]:
            tt = _toks(ln)
            if len(tt) >= 6:
                d, x, y = float(tt[0]) * k, float(tt[1]) * k, float(tt[2]) * k
                raw["holes"].append({"at": (x, y), "d": d, "plated": tt[3].upper() == "PTH", "ref": tt[4],
                                     "mount": tt[5].upper() in ("MTG", "TOOL") or tt[4].upper() == "BOARD"})
    lib = read_library(p.with_suffix(".emp"))
    if not lib:
        raw["notes"].append("No .emp library beside the board: part outlines and heights are not known.")
    for block in sec.get("PLACEMENT", []):
        rows = block[1:]
        for i in range(0, len(rows) - 1, 2):
            a, b = _toks(rows[i]), _toks(rows[i + 1])
            if len(a) < 3 or len(b) < 6:
                continue
            geom, pn, ref = a[0], a[1], a[2]
            x, y, off, ang, side = float(b[0]) * k, float(b[1]) * k, float(b[2]) * k, float(b[3]), b[4].upper()
            ent = lib.get((geom, pn)) or {}
            outline = ent.get("outline") or []
            if side == "BOTTOM":
                outline = [(-q[0], q[1]) for q in outline]
            h = ent.get("height")
            raw["components"].append({
                "ref": ref, "value": pn, "footprint": geom, "side": "bottom" if side == "BOTTOM" else "top",
                "at": (x, y), "rot": ang, "courtyard_local": outline, "pads_local": [],
                "height": ({"value": round(h + off, 4), "provenance": "specified",
                            "source": "the IDF library (.emp) height" + (" + mounting offset" if off else "")}
                           if h is not None else None)})
    b = model.finish(raw)
    return b
