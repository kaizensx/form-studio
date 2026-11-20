"""Reasoning effort chosen by the kind of task, so a reverse-engineering job is not run at "low" because that is the
person's default for quick edits. Effort is only ever raised, never lowered below what the person picked.

    from form.agents import effort
    effort.task_class("make these three STLs editable", ["a.stl", "b.stl"])   # "hard"
    effort.pick("make these three STLs editable", ["a.stl"], "low", ["low", "medium", "high"])   # ("high", "...")
"""
from __future__ import annotations

import re

ORDER = ["minimal", "low", "medium", "high", "xhigh", "max"]

_HARD = re.compile(
    r"\beditable\b|reverse[- ]?engineer|reconstruct|rebuild (it|this|them)|from (the|this|these) (stl|mesh|scan)|"
    r"mechanism|hinge|gear|planetary|linkage|ratchet|cam\b|slider|sliding|snap[- ]fit|bayonet|thread|"
    r"assembly|several parts|multi[- ]part|three parts|two parts|"
    r"helmet|mask|organic|sculpt|ergonomic|character|creature|cosplay|prop\b|"
    r"texture|knurl|lattice|voronoi|weave|"
    r"enclosure for|waterproof|gearbox", re.I)
_MEDIUM = re.compile(r"\b(design|make|create|build|model) (me )?(a|an|some)\b|\bnew\b|concepts?\b|ideas?\b", re.I)
_MESH = (".stl", ".obj", ".3mf", ".ply", ".step", ".stp")


def task_class(message: str, attachments: list | None = None) -> str:
    """"hard" (a mesh to make editable, a mechanism, an organic or styled form, a texture, several parts), "design"
    (a new part from words) or "edit" (anything else: a change to an existing design)."""
    files = [str(a.get("file") if isinstance(a, dict) else a).lower() for a in attachments or []]
    if any(f.endswith(_MESH) for f in files) or _HARD.search(message or ""):
        return "hard"
    if _MEDIUM.search(message or "") or len(message or "") > 600:
        return "design"
    return "edit"


def pick(message: str, attachments: list | None, chosen: str, available: list[str]) -> tuple[str, str]:
    """(effort, reason). chosen is the conversation's effort ("" = the CLI's default); available the agent's levels.
    A hard task gets at least "high", a new design at least "medium"; chosen stays when it is already higher, and when
    the agent lists no levels nothing changes."""
    cls = task_class(message, attachments)
    want = {"hard": "high", "design": "medium"}.get(cls)
    avail = [e for e in ORDER if e in (available or [])]
    if not want or not avail:
        return chosen, ""
    if want not in avail:                                  # the highest level this agent has, up to the target
        lower = [e for e in avail if ORDER.index(e) <= ORDER.index(want)]
        want = lower[-1] if lower else avail[-1]
    cur = chosen if chosen in ORDER else ""
    if cur and ORDER.index(cur) >= ORDER.index(want):
        return chosen, ""
    if not cur and cls == "design":                        # the CLI's own default is usually medium already
        return chosen, ""
    return want, f"Using {want} effort for this task: {reason(message, attachments, cls)}"


def reason(message: str, attachments: list | None, cls: str) -> str:
    """What made the task hard, in the person's words: "gears", "make this editable", "a mesh attached"."""
    if cls == "design":
        return "a new design"
    files = [str(a.get("file") if isinstance(a, dict) else a).lower() for a in attachments or []]
    if any(f.endswith(_MESH) for f in files):
        return "a mesh attached"
    m = _HARD.search(message or "")
    if m:
        text = message or ""
        a, b = m.start(), m.end()
        while a > 0 and text[a - 1].isalnum():
            a -= 1
        while b < len(text) and text[b].isalnum():
            b += 1
        return text[a:b].strip().lower()
    return "a mesh attached"
