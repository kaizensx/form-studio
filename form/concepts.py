"""Concepts first: a new idea starts as a few genuinely different designs, built for real, and the person picks one.

    <data>/.concepts/<gid>.json   {"id", "name", "brief", "state": "open" | "picked" | "dismissed" | "closed",
                                   "picked", "created",
                                   "members": [{"project", "letter", "title", "rationale", "trashed"}], "failed": [...]}

Each concept is an ordinary project (written as code, built in the kernel), named "<name> · A", "· B", ..., whose
project.json carries {"concept": {"group", "letter", "title", "rationale"}}. Picking one renames it to the group's
name, records the decision on it, and moves the others to the trash (<data>/.trash, recoverable) unless they are
kept. A group can also be dismissed without a pick: its concepts stay as ordinary designs (keep="all") or all go
to the trash (keep="none"). A group whose concepts are all gone closes by itself. The numbers on the board come from the kernel's own summary of each design; when it is not available they are
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
    early = _prebuild(st, concepts)                 # every concept built at the same time, one kernel worker each
    for i, (c, letter) in enumerate(zip(concepts, free)):
        c = c if isinstance(c, dict) else {}
        title, why = _clean(c.get("title"), 80) or f"Concept {letter}", _clean(c.get("rationale"), 300)
        if i in early:                               # it did not build: report it, the others go on
            failed.append({"letter": letter, "title": title, "error": early[i]})
            continue
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
        mat_err = None
        if c.get("material"):                       # the material it would be made in: its card shows the mass
            from . import materials
            try:
                materials.set_appearance(st, p["id"], "", "keep", str(c["material"]), by=by)
            except StudioError as e:
                mat_err = e.public()
        info = {"group": g["id"], "letter": letter, "title": title, "rationale": why}
        with st.lock(p["id"]):
            q = st.load(p["id"])
            q["concept"] = info
            st.decide(q, "concept", f"Concept {letter} of “{g['name']}”: {title}." + (f" {why}" if why else ""))
            st.save(q)
        built.append({"project": p["id"], "letter": letter, "title": title, "rationale": why, "trashed": False,
                      **({"material_error": mat_err} if mat_err else {})})
    if not built:
        raise StudioError("None of the concepts built.",
                          "; ".join(f"{f['letter']} ({f['title']}): {f['error'].get('message')}" for f in failed)[:1500]
                          + " Fix the one closest to building (each error names the line and a repair) and propose "
                            "again; the concepts are built in parallel, so a failing one costs no extra time.",
                          failed=failed)
    g["members"] += built
    g["failed"] = g.get("failed", []) + [{k: v for k, v in f.items()} for f in failed]
    _write(st, g)
    st.activity(built[0]["project"], "concepts", f"{len(built)} concepts for {g['name']}"
                + (f" ({len(failed)} did not build: {', '.join(f['letter'] for f in failed)})" if failed else ""),
                group=g["id"], by=by)
    out = {**board(st, g["id"]), "failed": failed}
    if failed:
        out["next"] = (f"{len(built)} of {len(built) + len(failed)} concepts built and are on the board. The others "
                       "failed with the diagnosis shown: fix one and add it with propose_concepts(group=\"" + g["id"]
                       + "\", concepts=[...]), or leave the person to pick from what built.")
    return out


def _prebuild(st, concepts: list) -> dict:
    """Build every concept's source in parallel over the kernel pool, before any project is made; the builds land in
    the workers' caches, so create_design then finds them. Returns {index: error} for those that did not build."""
    from concurrent.futures import ThreadPoolExecutor
    from .studio import H
    errors, jobs = {}, []
    for i, c in enumerate(concepts):
        c = c if isinstance(c, dict) else {}
        if not str(c.get("source") or "").strip():
            continue                               # reported by the loop with its own message
        try:
            vals = {k: float(v) for k, v in (c.get("values") or {}).items()}
            rid = st._load_design(str(c["source"]), str(c.get("language") or "python"))
            jobs.append((i, rid, vals))
        except StudioError as e:
            errors[i] = e.public()
        except (TypeError, ValueError):
            continue                               # bad values: the loop reports them

    def one(job):
        i, rid, vals = job
        try:
            full = {**st.recipes[rid].defaults(), **vals}
            st._check_assembly(rid, full)
            st._k("summary", key="pv-" + H(rid, vals or {}), recipe_id=rid, values=full, tol=0.1, timeout=180)
        except StudioError as e:
            errors[i] = e.public()
    if hasattr(st.kernel, "warm") and len(jobs) > 1:
        st.kernel.warm(len(jobs))
    with ThreadPoolExecutor(max_workers=max(1, min(len(jobs), getattr(st.kernel, "size", 1)))) as ex:
        list(ex.map(one, jobs))
    return errors


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
        out.update(_mass(st, p, compute))
        return out
    except Exception:
        return None


def _mass(st, p: dict, compute: bool) -> dict:
    """Mass and material for a card (form/massprops.py, on the B-rep): in the concept's material; a print concept with
    none is shown in PLA, marked assumed; a model with none shows no mass. {} when it is not measured (and compute is
    off) or cannot be."""
    from . import massprops
    from . import purpose as purpose_mod
    if not compute and not massprops.stored(st, p):
        return {}
    try:
        r = massprops.compute(st, p, assume=None if purpose_mod.is_model(p) else "PLA")
    except Exception:                                  # noqa: BLE001 - the card keeps its size and volume
        return {}
    mats = {x["material"]["id"]: x["material"] for x in r["parts"] if x.get("material")}
    out = {"material": None, "mass_evidence": r["evidence"]}
    if len(mats) == 1:
        m = next(iter(mats.values()))
        out["material"] = {"id": m["id"], "label": m["label"], "why": m["why"], "density_kg_m3": m["density_kg_m3"],
                           "source": m["density_source"]}
    elif mats:
        out["material"] = {"id": "mixed", "label": f"{len(mats)} materials", "why": "chosen per part"}
    if r["total"]:
        out["mass_g"] = round(r["total"]["mass_g"], 1)
        out["mass_text"] = massprops.headline(r)
        out["com_mm"] = [round(x, 1) for x in r["total"]["com_mm"]]
    return out


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


def _close_if_empty(st, g: dict) -> dict:
    """An open group whose concepts are all gone (deleted, trashed elsewhere) closes: nothing is left to pick."""
    if g.get("state") != "open" or not g.get("members"):
        return g
    for m in g["members"]:
        if m.get("trashed"):
            continue
        try:
            st.load(m["project"])
            return g
        except StudioError as e:
            if getattr(e, "status", 400) != 404:
                return g
    g.update(state="closed", closed_at=time.time())
    try:
        _write(st, g)
    except OSError:
        pass
    return g


def groups(st, state: str = "open") -> list:
    """Concept groups, newest first. state: "open", "picked", "dismissed", "closed" or "all"."""
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
        g = _close_if_empty(st, g)
        if state != "all" and g.get("state") != state:
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
        if g.get("picked") == project:            # picking the one already picked again: the same answer, no error
            return {"picked": project, "trashed": [], "kept": [], "already": True,
                    "group": board(st, gid, compute=False)}
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
        p["lineage"] = {"root": project, "parent": None, "parent_rev": None, "via": "concept", "group": gid}
        st.decide(p, "concept", f"Picked concept {mem['letter']}: {mem['title']} from {len(live)} concepts.")
        st.save(p)
    # the conversation that proposed the concepts carries on with the one picked: it is linked, not left behind
    # (before the others go to the trash, which would detach the conversations open on them)
    from .conversations import Conversations
    store = Conversations(st.root)
    members = {m["project"] for m in g["members"]}
    for c in store.list(limit=100000):
        if (c.get("project") in members or gid in (c.get("concepts") or [])
                or any(e.get("group") == gid for e in c.get("designs") or [])):
            try:                                # the picked one is what this conversation made; the group is closed
                store.link(c["id"], project, role="made", group=gid, tool="pick_concept")
                store.record(c["id"], None, "concept", group=gid, front=False, state="picked")
            except Exception:
                pass
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


def dismiss(st, gid: str, keep: str = "all", by: str = "you") -> dict:
    """Close an open group without picking. keep="all": every concept stays as an ordinary design (it leaves the
    group and keeps its own name); keep="none": every concept goes to the trash (recoverable from <data>/.trash)."""
    if keep not in ("all", "none"):
        raise StudioError("keep is \"all\" or \"none\".", "Keep every concept as a design, or move them all to the trash.")
    g = _read(st, gid)
    if g["state"] != "open":
        raise StudioError("This concept group is already closed.", status=409, state=g["state"], picked=g.get("picked"))
    kept, trashed = [], []
    for m in g["members"]:
        if m.get("trashed"):
            continue
        if keep == "none":
            try:
                st.delete_project(m["project"])
                m["trashed"] = True
                trashed.append(m["project"])
            except StudioError as e:
                if getattr(e, "status", 400) == 404:
                    m["trashed"] = True
                else:
                    m["kept_because"] = str(e)
                    kept.append(m["project"])
            continue
        try:
            with st.lock(m["project"]):
                p = st.load(m["project"])
                p.pop("concept", None)
                st.decide(p, "concept", f"Kept concept {m['letter']} ({m['title']}) of “{g['name']}” as a design of its own.")
                st.save(p)
            kept.append(m["project"])
        except StudioError as e:
            if getattr(e, "status", 400) == 404:
                m["trashed"] = True
            else:
                raise
    g.update(state="dismissed", dismissed=keep, dismissed_at=time.time())
    _write(st, g)
    from .conversations import Conversations
    store = Conversations(st.root)
    for c in store.list(limit=100000):              # the conversations that proposed them say the group is closed
        if any(e.get("group") == gid and not e.get("project") for e in c.get("designs") or []):
            try:
                store.record(c["id"], None, "concept", group=gid, front=False, state="dismissed")
            except Exception:
                pass
    if kept:
        st.activity(kept[0], "concepts", f"Kept {len(kept)} concepts of {g['name']} as designs", group=gid, by=by)
    return {"dismissed": gid, "keep": keep, "kept": kept, "trashed": trashed, "group": board(st, gid, compute=False)}


# ---- command line: form concepts [<group-or-project> | pick <group> <project> [--keep-others]
#                                   | dismiss <group> [--discard]] ---------------------------------------------

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
        elif argv[0] == "dismiss":
            rest = [a for a in argv[1:] if not a.startswith("--")]
            if len(rest) != 1:
                out({"error": {"message": "Usage: form concepts dismiss <group> [--discard]"}})
                return 2
            out(dismiss(st, rest[0], "none" if "--discard" in argv else "all", by="cli"))
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
