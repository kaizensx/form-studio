"""What a reply rests on, read from the tool log: never from what the model says about itself.

A reply in the conversation ends in Sources. Each source is one tool call of that turn whose result says how its
content is known, numbered in the order the calls were made. This module decides, from a tool's name, its input and
its result, whether the call is a source, what to call it and which evidence class it carries.

The class comes from the result's own `evidence` field when it has one (the engine writes it: computed, simulated,
specified, measured, assumed, opened). A few tools have a class by what they are, whatever they return: a document
or a link that was read is OPENED, a measurement the person answered is MEASURED, a number the kernel read off the
solid is COMPUTED, a slice or a stock run is SIMULATED. A call that failed, or whose result names no class and whose
tool has none, is not a source: the block would rather be short than invented.

`figures` are the numbers that stand in the result (with a decimal point, or three digits and more). The conversation
marks a number in the reply with a source's index only when that exact number is among them.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

CLASSES = ("simulated", "computed", "specified", "opened", "measured", "assumed")

# tool -> (what the source is called, its class by nature or None: then the result must name one)
TOOLS = {
    "read_document": ("{file}", "opened"),
    "fetch_link": ("{host}", "opened"),
    "import_reference": ("{file}", "opened"),
    "resolve_model_page": ("{host}", "opened"),
    "ask_measurement": ("Your measurement", "measured"),
    "measure": ("Measured on the solid", "computed"),
    "mass_properties": ("Mass properties", "computed"),
    "geometry_diff": ("Geometry compared between revisions", "computed"),
    "compare_to_reference": ("Compared with the reference", "computed"),
    "analyze": ("Analysis of the solid", "computed"),
    "analyze_selection": ("Analysis of the selection", "computed"),
    "print_simulation": ("Print simulation", "simulated"),
    "cam_simulate": ("Stock simulation", "simulated"),
    "strength_study": ("Strength study", None),
    "get_strength_study": ("Strength study", None),
    "run_study": ("Study", None),
    "get_study": ("Study", None),
    "get_project": ("Checks and state", None),
    "calculate": ("Calculation", None),
    "standard_part": ("Standard part", None),
    "manufacturability": ("Manufacturability", None),
    "estimate_cost": ("Cost estimate", None),
    "motion_study": ("Motion study", None),
    "bom": ("Parts list", None),
    "drawing": ("Drawing", None),
    "reconstruct": ("Reconstruction", None),
    "triage": ("Triage", None),
}
_WORD = re.compile(r"\b(" + "|".join(CLASSES) + r")\b", re.I)
_FIGURE = re.compile(r"(?<![\w.])(?:\d+\.\d+|\d{3,})(?![\w]|\.\d|-[A-Za-z])")
_TITLE_KEYS = ("title", "study", "name", "label")
MAX_FIGURES = 60


def _json(text: str):
    text = (text or "").strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _evidence_values(obj, depth: int = 0):
    """Every `evidence` string in a result, the outermost first."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        for k in ("evidence", "evidence_class"):
            if isinstance(obj.get(k), str):
                yield obj[k]
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from _evidence_values(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:40]:
            yield from _evidence_values(v, depth + 1)


def evidence_class(full: str) -> str:
    """The class a result gives itself: one of CLASSES, another word the engine used (shown as it is), or ""."""
    obj = _json(full)
    if obj is not None:
        other = ""
        for v in _evidence_values(obj):
            m = _WORD.search(v)
            if m:
                return m.group(1).lower()
            other = other or re.sub(r"[^a-z ]", "", v.strip().lower().split(";")[0].split("(")[0]).strip()[:18]
        return other
    m = re.search(r"evidence\W{1,3}(" + "|".join(CLASSES) + r")\b", full or "", re.I)
    return m.group(1).lower() if m else ""


def _input(inp) -> dict:
    if isinstance(inp, dict):
        return inp
    obj = _json(str(inp or ""))
    if isinstance(obj, dict):
        return obj
    out = {}
    # the agent's parser shortens arguments to "key=value key=value" (form/agents/base.py short)
    for m in re.finditer(r"(?:^|\s)(\w+)=(.*?)(?=\s+\w+=|$)", str(inp or "")):
        out.setdefault(m.group(1), m.group(2).strip().strip('"'))
    return out


def _title(name: str, pattern: str, inp: dict, obj) -> str:
    file = str(inp.get("path") or inp.get("file") or inp.get("source") or "")
    url = str(inp.get("url") or inp.get("link") or "")
    if "{file}" in pattern:
        base = PurePosixPath(file.replace("\\", "/")).name if file else ""
        base = re.sub(r"^[0-9a-f]{6}-", "", base)             # an attachment's id prefix (form/conversations.py)
        page = inp.get("page") or inp.get("pages")
        return (base + (f", page {page}" if base and page else "")) or "A file"
    if "{host}" in pattern:
        return (urlparse(url).netloc or url)[:60] or "A link"
    said = ""
    if isinstance(obj, dict):
        for k in _TITLE_KEYS:
            if isinstance(obj.get(k), str) and obj[k].strip():
                said = obj[k].strip()
                break
    title = said if said and len(said) <= 64 else pattern          # the result's own name for itself, else the tool's
    rev = obj.get("rev", obj.get("head")) if isinstance(obj, dict) else None
    if isinstance(rev, int) and not re.search(r"\br\d\d\b", title):
        title += f" on r{rev:02d}"
    return title[:80]


def figures(full: str) -> list[str]:
    seen, out = set(), []
    for m in _FIGURE.finditer(full or ""):
        f = m.group(0)
        if f not in seen:
            seen.add(f)
            out.append(f)
            if len(out) >= MAX_FIGURES:
                break
    return out


def source_of(name: str, inp, full: str, ok: bool) -> dict | None:
    """The source one tool call is, or None when it is not one. {"title", "how", "figures"}."""
    if not ok or name not in TOOLS:
        return None
    pattern, by_nature = TOOLS[name]
    obj = _json(full)
    if name == "ask_measurement":            # only a number the person gave is a measurement
        if not (isinstance(obj, dict) and obj.get("answered") and obj.get("value") is not None):
            return None
    how = by_nature or evidence_class(full)
    if not how:
        return None
    return {"title": _title(name, pattern, _input(inp), obj), "how": how, "figures": figures(full)}


def plan_steps(full: str) -> list[str]:
    """The steps of a plan_design result, as lines a person reads. [] when the result carries none."""
    obj = _json(full)
    steps = obj.get("steps") if isinstance(obj, dict) else None
    out = []
    for s in steps if isinstance(steps, list) else []:
        if isinstance(s, str):
            line = s
        elif isinstance(s, dict):
            line = next((str(s[k]) for k in ("label", "title", "do", "feature", "name", "text", "step") if s.get(k)), "")
        else:
            line = ""
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            out.append(line[:140])
    return out[:12]


def hand_edits(events: list[dict]) -> list[dict]:
    """What the person changed by hand since the agent's last reply: the act events with a revision that follow the
    last `end` (form/modelling_api.py writes them). [{"text", "to"}], oldest first."""
    out = []
    for e in reversed(events):
        if e.get("t") in ("end", "text"):
            break
        if e.get("t") == "act" and e.get("change") and str(e.get("by", "")).lower() == "you":
            out.append({"text": str(e.get("text", "")), "to": e["change"].get("to")})
    return out[::-1]


def hand_note(events: list[dict]) -> str:
    """The same, as the lines the agent reads with the next message. "" when nothing was changed by hand."""
    edits = hand_edits(events)
    if not edits:
        return ""
    lines = ["- " + e["text"] + (f" (r{e['to']:02d})" if isinstance(e["to"], int) else "") for e in edits]
    return ("By hand since your last reply, the person changed the design in Form Studio:\n" + "\n".join(lines)
            + "\nRead the design again with Form Studio's tools before you change it; keep these edits.")
