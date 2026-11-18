"""Sketches drawn in Form Studio: structured 2D geometry the agent reads as exact numbers, not as a picture.

The app's sketch pad saves what was drawn as JSON (millimetres, y up) next to a PNG of it:

    {"version": 1, "units": "mm", "grid_mm": 5, "view": "top" | "front" | "side",
     "intent": "extrude" | "revolve" | "", "depth_mm": number | null, "notes": "...",
     "primitives": [
        {"id": "p1", "type": "line",   "a": [x, y], "b": [x, y]},
        {"type": "rect",   "a": [x, y], "b": [x, y]},                     # two opposite corners
        {"type": "circle", "c": [x, y], "r": r},
        {"type": "arc",    "c": [x, y], "r": r, "start_deg": a, "end_deg": b},   # counter-clockwise from start to end
        {"type": "path",   "points": [[x, y], ...]},                      # freehand
        {"type": "dim",    "a": [x, y], "b": [x, y], "value": mm | null, "label": "..."}]}

A dimension with value null means the drawn length. A dimension with a value is what the person stated, and it wins
over the drawn length: the drawing is a gesture, the number is the intent. validate() normalises (rounds to 0.01 mm,
fills ids) and refuses anything else with a message that names the primitive; summarize() gives the agent the
overall size, what was drawn and the dimensions, each labelled by where its number comes from.
"""
from __future__ import annotations

import math

TYPES = ("line", "rect", "circle", "arc", "path", "dim")
VIEWS = ("top", "front", "side")
INTENTS = ("extrude", "revolve", "")
MAX_PRIMITIVES = 2000
MAX_PATH_POINTS = 5000                 # over all freehand paths together
MAX_COORD = 100_000.0                  # 100 m: anything larger is a units mistake, not a part
NAMES = {"line": ("line", "lines"), "rect": ("rectangle", "rectangles"), "circle": ("circle", "circles"),
         "arc": ("arc", "arcs"), "path": ("freehand stroke", "freehand strokes"), "dim": ("dimension", "dimensions")}


def _num(v, where: str, positive: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise ValueError(f"{where} must be a finite number.")
    v = float(v)
    if abs(v) > MAX_COORD:
        raise ValueError(f"{where} is {v:g} mm, larger than {MAX_COORD:g} mm; sketches are in millimetres.")
    if positive and v <= 0:
        raise ValueError(f"{where} must be greater than 0.")
    return round(v, 2)


def _pt(v, where: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"{where} must be a point [x, y].")
    return [_num(v[0], where + "[0]"), _num(v[1], where + "[1]")]


def validate(obj) -> dict:
    """The sketch, normalised. Raises ValueError with a message that says what is wrong and where."""
    if not isinstance(obj, dict):
        raise ValueError("A sketch is a JSON object.")
    ver = obj.get("version", 1)
    if ver != 1:
        raise ValueError(f"Sketch version {ver!r} is not supported; this Form Studio reads version 1.")
    units = obj.get("units", "mm")
    if units != "mm":
        raise ValueError(f"Sketch units must be \"mm\", not {units!r}.")
    view = obj.get("view") or "top"
    if view not in VIEWS:
        raise ValueError(f"view must be one of {', '.join(VIEWS)}, not {view!r}.")
    intent = obj.get("intent") or ""
    if intent not in INTENTS:
        raise ValueError(f"intent must be \"extrude\", \"revolve\" or empty, not {intent!r}.")
    grid = obj.get("grid_mm", 5)
    grid = 5.0 if grid is None else _num(grid, "grid_mm", positive=True)
    depth = obj.get("depth_mm")
    depth = None if depth is None else _num(depth, "depth_mm", positive=True)
    notes = obj.get("notes") or ""
    if not isinstance(notes, str):
        raise ValueError("notes must be text.")
    prims = obj.get("primitives")
    if prims is None:
        prims = []
    if not isinstance(prims, list):
        raise ValueError("primitives must be a list.")
    if len(prims) > MAX_PRIMITIVES:
        raise ValueError(f"The sketch has {len(prims)} primitives; at most {MAX_PRIMITIVES} are allowed.")
    out, ids, path_points = [], set(), 0
    for i, p in enumerate(prims):
        if not isinstance(p, dict):
            raise ValueError(f"primitives[{i}] must be an object.")
        t = p.get("type")
        if t not in TYPES:
            raise ValueError(f"primitives[{i}]: unknown type {t!r}; known: {', '.join(TYPES)}.")
        w = f"primitives[{i}] ({t})"
        pid = p.get("id")
        pid = str(pid)[:40] if pid not in (None, "") else ""
        if not pid or pid in ids:
            n = len(ids) + 1
            while f"p{n}" in ids:
                n += 1
            pid = f"p{n}"
        ids.add(pid)
        q: dict = {"id": pid, "type": t}
        if t in ("line", "rect", "dim"):
            q["a"], q["b"] = _pt(p.get("a"), w + " a"), _pt(p.get("b"), w + " b")
            if t == "rect" and (q["a"][0] == q["b"][0] or q["a"][1] == q["b"][1]):
                raise ValueError(f"{w}: a rectangle needs two corners that differ in x and in y.")
            if t == "dim":
                v = p.get("value")
                q["value"] = None if v is None else _num(v, w + " value", positive=True)
                label = p.get("label") or ""
                if not isinstance(label, str):
                    raise ValueError(f"{w}: label must be text.")
                q["label"] = " ".join(label.split())[:80]
        elif t in ("circle", "arc"):
            q["c"], q["r"] = _pt(p.get("c"), w + " c"), _num(p.get("r"), w + " r", positive=True)
            if t == "arc":
                q["start_deg"] = _num(p.get("start_deg"), w + " start_deg")
                q["end_deg"] = _num(p.get("end_deg"), w + " end_deg")
        else:                                            # path
            pts = p.get("points")
            if not isinstance(pts, list) or len(pts) < 2:
                raise ValueError(f"{w}: a freehand stroke needs at least two points.")
            path_points += len(pts)
            if path_points > MAX_PATH_POINTS:
                raise ValueError(f"The freehand strokes have more than {MAX_PATH_POINTS} points together; simplify them.")
            q["points"] = [_pt(pt, f"{w} points[{j}]") for j, pt in enumerate(pts)]
        out.append(q)
    return {"version": 1, "units": "mm", "grid_mm": grid, "view": view, "intent": intent, "depth_mm": depth,
            "notes": notes.strip()[:2000], "primitives": out}


def _sweep(a: float, b: float) -> float:
    """Counter-clockwise sweep from a to b in degrees, in (0, 360]."""
    s = (b - a) % 360.0
    return 360.0 if s == 0 else s


def _arc_points(p: dict) -> list[list[float]]:
    """The arc's end points and every axis extreme it passes, enough for an exact bounding box."""
    (cx, cy), r, a = p["c"], p["r"], p["start_deg"] % 360.0
    s = _sweep(a, p["end_deg"])
    angles = [a, a + s] + [k * 90.0 for k in range(0, 9) if a < k * 90.0 < a + s]
    return [[cx + r * math.cos(math.radians(t)), cy + r * math.sin(math.radians(t))] for t in angles]


def _points(p: dict) -> list[list[float]]:
    t = p["type"]
    if t in ("line", "rect", "dim"):
        return [p["a"], p["b"]]
    if t == "circle":
        (cx, cy), r = p["c"], p["r"]
        return [[cx - r, cy - r], [cx + r, cy + r]]
    if t == "arc":
        return _arc_points(p)
    return p["points"]


def _fmt(v: float) -> str:
    return f"{round(v, 2):g}"


def summarize(obj) -> dict:
    """{"bbox_mm": [[x0, y0], [x1, y1]], "counts": {type: n}, "dims": [...], "text": one paragraph}."""
    s = validate(obj)
    prims = s["primitives"]
    pts = [pt for p in prims for pt in _points(p)]
    bbox = ([[round(min(x for x, _ in pts), 2), round(min(y for _, y in pts), 2)],
             [round(max(x for x, _ in pts), 2), round(max(y for _, y in pts), 2)]] if pts else None)
    counts: dict[str, int] = {}
    for p in prims:
        counts[p["type"]] = counts.get(p["type"], 0) + 1
    dims = []
    for p in prims:
        if p["type"] != "dim":
            continue
        drawn = round(math.dist(p["a"], p["b"]), 2)
        stated = p["value"] is not None
        dims.append({"id": p["id"], "label": p["label"], "value_mm": p["value"] if stated else drawn, "drawn_mm": drawn,
                     "source": "stated by the user" if stated else "drawn length"})
    parts = [f"{s['view'].capitalize()} view sketch"]
    if bbox:
        w, h = bbox[1][0] - bbox[0][0], bbox[1][1] - bbox[0][1]
        parts[0] += f", {_fmt(w)} × {_fmt(h)} mm overall (bounding box of what was drawn)"
    what = [f"{n} {NAMES[t][0] if n == 1 else NAMES[t][1]}" for t, n in counts.items() if t != "dim"]
    text = parts[0] + (": " + ", ".join(what) if what else ": nothing drawn yet") + "."
    circles = sorted({p["r"] for p in prims if p["type"] == "circle"})
    if circles:
        text += " Circle diameters: " + ", ".join(f"{_fmt(2 * r)} mm" for r in circles[:8]) + (" …" if len(circles) > 8 else "") + "."
    if dims:
        text += " Dimensions: " + "; ".join(
            f"{d['label'] or 'unlabelled'} {_fmt(d['value_mm'])} mm ({d['source']}"
            + (f"; drawn {_fmt(d['drawn_mm'])} mm" if d["source"] == "stated by the user" and abs(d["drawn_mm"] - d["value_mm"]) > 0.01 else "")
            + ")" for d in dims) + "."
    if s["intent"] == "extrude":
        text += " Intent: extrude" + (f" {_fmt(s['depth_mm'])} mm." if s["depth_mm"] else " (depth not given).")
    elif s["intent"] == "revolve":
        text += " Intent: revolve the profile."
    if s["notes"]:
        text += " Notes: " + " ".join(s["notes"].split())[:400]
    return {"bbox_mm": bbox, "counts": counts, "dims": dims, "text": text}
