"""Concepts first: a new idea starts as a few genuinely different designs, built for real, and the person picks one.

    <data>/.concepts/<gid>.json   {"id", "name", "brief", "state": "open" | "picked", "picked", "created",
                                   "members": [{"project", "letter", "title", "rationale", "trashed"}], "failed": [...]}

Each concept is an ordinary project (written as code, built in the kernel), named "<name> · A", "· B", ..., whose
project.json carries {"concept": {"group", "letter", "title", "rationale"}}. Picking one renames it to the group's
name, records the decision on it, and moves the others to the trash (<data>/.trash, recoverable) unless they are
kept. The numbers on the board come from the kernel's own summary of each design; when it is not available they are
left out, never estimated.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from .studio import StudioError

DIR = ".concepts"
LETTERS = "ABCDEF"
MAX_PER_CALL = 4
MAX_TOTAL = len(LETTERS)
GID_RE = re.compile(r"[0-9a-f]{10}")


def _dir(st) -> Path:
    return Path(st.root) / DIR


def _file(st, gid: str) -> Path:
    if not GID_RE.fullmatch(str(gid or "")):
        raise StudioError("Unknown concept group.", status=404)
    return _dir(st) / f"{gid}.json"


def _read(st, gid: str) -> dict:
    try:
        return json.loads(_file(st, gid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StudioError("Unknown concept group.", "List the open groups with list_concepts or `form concepts`.", status=404)


def _write(st, g: dict) -> None:
    f = _file(st, g["id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)


def _clean(s, n: int) -> str:
    return " ".join(str(s or "").split())[:n]


def create(st, name: str, concepts: list, brief: str = "", group: str | None = None, purpose: str | None = None,
           by: str = "agent") -> dict:
    """Build 2-4 concepts as real projects (with group=an open group's id: add 1-4 more, at most 6 in a group).
    concepts: [{"title", "rationale", "source", "language": "python", "values": None}]. A concept that fails to
    build is reported with its error and the others go on; if none builds, nothing is kept."""
    from . import start
    name = _clean(name, 70)
    if not name:
        raise StudioError("Concepts need a name.", "Name the thing being designed, e.g. \"Headphone hook\".")
    if not isinstance(concepts, list) or not concepts:
        raise StudioError("Give the concepts to build.", "2 to 4 entries of {title, rationale, source}.")
    if group:
        g = _read(st, group)
        if g["state"] != "open":
            raise StudioError("A concept has already been picked from this group.", "Refine the picked design with update_design.",
                              status=409)
        if not 1 <= len(concepts) <= MAX_PER_CALL:
            raise StudioError(f"Add 1 to {MAX_PER_CALL} concepts at a time.")
        if len([m for m in g["members"] if not m.get("trashed")]) + len(concepts) > MAX_TOTAL:
            raise StudioError(f"A group holds at most {MAX_TOTAL} concepts.", "Let the person pick, or start a new group.")
    else:
        if not 2 <= len(concepts) <= MAX_PER_CALL:
            raise StudioError(f"Propose 2 to {MAX_PER_CALL} concepts.", "Three or four genuinely different approaches work best.")
        g = {"id": uuid.uuid4().hex[:10], "name": name, "brief": str(brief or "")[:4000], "state": "open", "picked": None,
             "created": time.time(), "members": [], "failed": []}
    purpose = purpose or start.env_purpose()
    used = {m["letter"] for m in g["members"]} | {f.get("letter") for f in g.get("failed", [])}
    free = [c for c in LETTERS if c not in used]
    if len(free) < len(concepts):
        raise StudioError(f"A group holds at most {MAX_TOTAL} concepts.", "Let the person pick, or start a new group.")
    built, failed = [], []
    for c, letter in zip(concepts, free):
        c = c if isinstance(c, dict) else {}
        title, why = _clean(c.get("title"), 80) or f"Concept {letter}", _clean(c.get("rationale"), 300)
        try:
            if not str(c.get("source") or "").strip():
                raise StudioError("This concept has no source code.")
            vals = {k: float(v) for k, v in (c.get("values") or {}).items()}
            p = st.create_design(f"{g['name']} · {letter}", str(c["source"]), g["brief"], vals or None,
                                 str(c.get("language") or "python"), purpose=purpose or None)
        except StudioError as e:
            failed.append({"letter": letter, "title": title, "error": e.public()})
            continue
        except (TypeError, ValueError) as e:
            failed.append({"letter": letter, "title": title, "error": {"message": f"values: {e}", "hint": "Values are numbers."}})
            continue
        info = {"group": g["id"], "letter": letter, "title": title, "rationale": why}
        with st.lock(p["id"]):
            q = st.load(p["id"])
            q["concept"] = info
            st.decide(q, "concept", f"Concept {letter} of “{g['name']}”: {title}." + (f" {why}" if why else ""))
            st.save(q)
        built.append({"project": p["id"], "letter": letter, "title": title, "rationale": why, "trashed": False})
    if not built:
        raise StudioError("None of the concepts built.",
                          "; ".join(f"{f['letter']} ({f['title']}): {f['error'].get('message')}" for f in failed)[:1500],
                          failed=failed)
    g["members"] += built
    g["failed"] = g.get("failed", []) + failed
    _write(st, g)
    st.activity(built[0]["project"], "concepts", f"{len(built)} concepts for {g['name']}", group=g["id"], by=by)
    return {**board(st, g["id"]), "failed": failed}


def _numbers(st, p: dict, compute: bool) -> dict | None:
    """Size and volume from the kernel's summary of the head revision (computed), or None when there is none."""
    try:
        if compute:
            s = st.head_summary(p)
        else:
            s = st.read(p, "geometry", st.keys(p)["geometry"])
        if not s or not s.get("bbox"):
            return None
        lo, hi = s["bbox"]
        out = {"size_mm": [round(b - a, 1) for a, b in zip(lo, hi)], "evidence": "computed"}
        if isinstance(s.get("volume_mm3"), (int, float)):
            out["volume_cm3"] = round(s["volume_mm3"] / 1000, 2)
        return out
    except Exception:
        return None


def board(st, gid: str, compute: bool = True) -> dict:
    """A group with each concept's project, name and computed numbers."""
    g = _read(st, gid)
    members = []
    for m in g["members"]:
        row = {"project": m["project"], "letter": m["letter"], "title": m["title"], "rationale": m.get("rationale", ""),
               "name": None, "error": None, "trashed": bool(m.get("trashed"))}
        if m.get("trashed"):
            members.append(row)
            continue
        try:
            p = st.load(m["project"])
            row["name"] = p["name"]
            nums = _numbers(st, p, compute)
            if nums:
                row["numbers"] = nums
        except StudioError as e:
            row["error"] = "This concept is no longer in your projects." if getattr(e, "status", 400) == 404 else str(e)
        members.append(row)
    return {"id": g["id"], "name": g["name"], "brief": g.get("brief", ""), "state": g["state"], "picked": g.get("picked"),
            "created": g["created"], "members": members}


def groups(st, state: str = "open") -> list:
    """Concept groups, newest first. state: "open", "picked", or "all"."""
    out = []
    d = _dir(st)
    if not d.is_dir():
        return out
    for f in d.glob("*.json"):
        if not GID_RE.fullmatch(f.stem):
            continue
        try:
            g = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if state in ("open", "picked") and g.get("state") != state:
            continue
        out.append((g.get("created", 0), f.stem))
    out.sort(reverse=True)
    return [board(st, gid, compute=False) for _, gid in out]


def group_of(st, project: str) -> str | None:
    """The concept group a project belongs to, if any."""
    try:
        c = st.load(project).get("concept") or {}
    except StudioError:
        return None
    return c.get("group") if GID_RE.fullmatch(str(c.get("group") or "")) else None


def pick(st, gid: str, project: str, keep_others: bool = False, by: str = "you") -> dict:
    """The person's choice: the picked design takes the group's name and keeps a record of the choice; the other
    concepts go to the trash (recoverable from <data>/.trash) unless keep_others."""
    g = _read(st, gid)
    if g["state"] != "open":
        raise StudioError("A concept has already been picked from this group.", status=409, picked=g.get("picked"))
    mem = next((m for m in g["members"] if m["project"] == project and not m.get("trashed")), None)
    if mem is None:
        raise StudioError("That design is not one of this group's concepts.", "Pick one of the projects the board lists.",
                          status=404)
    live = [m for m in g["members"] if not m.get("trashed")]
    st.rename_project(project, g["name"])
    with st.lock(project):
        p = st.load(project)
        p["concept"] = dict(p.get("concept") or {}, picked=True)
        st.decide(p, "concept", f"Picked concept {mem['letter']}: {mem['title']} from {len(live)} concepts.")
        st.save(p)
    trashed, kept = [], []
    for m in live:
        if m["project"] == project:
            continue
        if keep_others:
            kept.append(m["project"])
            continue
        try:
            st.delete_project(m["project"])
            m["trashed"] = True
            trashed.append(m["project"])
        except StudioError as e:
            if getattr(e, "status", 400) == 404:          # already gone
                m["trashed"] = True
            else:
                kept.append(m["project"])
                m["kept_because"] = str(e)
    g.update(state="picked", picked=project, picked_at=time.time())
    _write(st, g)
    st.activity(project, "concepts", f"Picked concept {mem['letter']} for {g['name']}", group=gid, picked=project, by=by)
    return {"picked": project, "trashed": trashed, "kept": kept, "group": board(st, gid, compute=False)}


# ---- command line: form concepts [<group-or-project> | pick <group> <project> [--keep-others]] -------------------

def main(argv: list[str]) -> int:
    from . import config
    from .studio import Studio

    def out(obj):
        print(json.dumps(obj, indent=1, default=str, ensure_ascii=False))
    st = Studio(config.load())
    try:
        if not argv:
            out({"groups": groups(st, "open")})
        elif argv[0] == "pick":
            rest = [a for a in argv[1:] if not a.startswith("--")]
            if len(rest) != 2:
                out({"error": {"message": "Usage: form concepts pick <group> <project> [--keep-others]"}})
                return 2
            out(pick(st, rest[0], rest[1], "--keep-others" in argv, by="cli"))
        elif argv[0] in ("--all", "all"):
            out({"groups": groups(st, "all")})
        else:
            arg = argv[0]
            gid = arg if GID_RE.fullmatch(arg) and _file(st, arg).exists() else group_of(st, arg)
            if not gid:
                raise StudioError(f"“{arg}” is neither a concept group nor a concept's project.",
                                  "List the open groups with `form concepts`.", status=404)
            out(board(st, gid))
    except StudioError as e:
        out({"error": e.public()})
        return 2
    finally:
        st.kernel.stop()
    return 0
