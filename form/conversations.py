"""Conversations: every chat is a folder on disk, so it reloads exactly as it was.

    <data>/.conversations/<id>/meta.json       id, title, project, agent, model, effort, session, pinned, cost,
                                               thread, parent, fork_event, fork_reason, projects, …
    <data>/.conversations/<id>/events.jsonl    one event per line: user, start, text, tool, result, act, end, error
    <data>/.conversations/<id>/files/          attachments, copied in (the only folder the agent may read)

Conversations are linked, never scattered. Every conversation belongs to a thread (the id of the one it all started
from; an old conversation without one is its own thread). A fork copies a conversation's events up to a point into a
new one in the same thread, with `parent`, `fork_event` and `fork_reason` saying where it branched; its agent session
starts fresh and is handed a transcript of what came before. A design that moves on (a concept picked, a copy, a
design the agent made in the conversation) takes the conversation with it: `link` moves it and remembers the designs
it was about in `projects`.

One request, one design. A conversation owns the ordered list of every design it touched, `designs`:

    [{"project": id, "role": "made" | "concept" | "reference-study" | "continued", "state": "live" | "trashed" | "gone",
      "request": index of the user event that asked for it, "ts", "tool"}, ...]

with a concept group listed once as {"group": id, "role": "concept", "state": "open" | "picked" | "dismissed"}.
`project` stays "the design in front". The MCP server writes `designs` the moment a tool creates, picks, duplicates
or reconstructs a design (`made()`, from $FORM_CONVERSATION); the app writes it for what the person does. The first
design a request makes is its family's root; later designs made by the same request join that family
(`lineage.via == "request"`), so Home shows one card for one request. Conversations saved before `designs` existed
get it rebuilt from their events, their meta and the activity log the first time they are read (`rebuild_designs`).

A conversation started by attaching a file is a draft (`.conversations/.drafts/<id>`) until its first message is sent;
a draft that is never sent never shows up as an empty conversation, and old drafts are cleared.

Nothing here talks to an agent; form/chat.py runs the agent and appends what it says.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from . import fsutil

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_EXT = {".pdf"}
CAD_EXT = {".step", ".stp", ".stl", ".3mf"}
SKETCH_SUFFIX = ".sketch.json"        # a sketch drawn in Form Studio (form/sketch.py): structured geometry, read as JSON
MAX_ATTACHMENT = 60_000_000
ID_RE = re.compile(r"[0-9a-f]{12}")
PID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,60}")
GID_RE = re.compile(r"[0-9a-f]{10}")
ENV_CONVERSATION = "FORM_CONVERSATION"          # set by form/chat.py for the MCP server of one conversation's run
ROLES = ("made", "concept", "reference-study", "continued")
DRAFTS = ".drafts"
DRAFT_DAYS = 7                                  # a draft nobody sent is cleared after this many days
#: MCP tools that put a new design in front of the person, and the role it plays in the conversation.
#: tests/test_request_family.py fails on a tool that returns a new project id and is not listed here.
CREATOR_TOOLS = {"create_project": "made", "create_design": "made", "reconstruct": "made", "duplicate_project": "made",
                 "import_project": "made", "pick_concept": "made", "propose_concepts": "concept"}
EVENT_KINDS = ("user", "start", "text", "tool", "result", "act", "end", "error", "ask", "answer", "suggest")


_last = [0.0]


def _now() -> float:
    """A timestamp that always moves forward. Windows' clock ticks about every 15 ms, so two changes made
    back to back would otherwise share a time and "most recent first" would be a coin toss."""
    t = max(time.time(), _last[0] + 1e-6)
    _last[0] = t
    return t


class ConversationError(ValueError):
    pass


def title_from(message: str, limit: int = 52) -> str:
    """A conversation's name, from its first message: the first line, cut at a word."""
    line = next((ln.strip() for ln in (message or "").splitlines() if ln.strip()), "")
    line = re.sub(r"\s+", " ", re.sub(r"^[#>*\-\s]+", "", line))
    if not line:
        return "New conversation"
    if len(line) <= limit:
        return line.rstrip(" .:;,")
    cut = line[:limit + 1]
    cut = cut[:cut.rfind(" ")] if " " in cut[limit // 2:] else cut[:limit]
    return cut.rstrip(" .:;,") + "…"


def kind_of(name: str) -> str:
    if str(name).lower().endswith(SKETCH_SUFFIX):
        return "sketch"
    ext = Path(name).suffix.lower()
    return "image" if ext in IMAGE_EXT else "pdf" if ext in PDF_EXT else "cad" if ext in CAD_EXT else "file"


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(root: Path):
    """One lock per conversations folder, shared by every Conversations object in the process and exclusive across
    processes. The chat service and the engine (deleting a design detaches its conversations) each make their own
    object, and the MCP server of a running conversation records the designs it makes from its own process while the
    chat process appends events: every read-modify-write of meta.json holds this lock, so neither loses the other's
    change. Re-entrant within a process."""
    key = str(Path(root).resolve())
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            from .studio import ProjectLock       # flock on POSIX, a region lock on Windows
            _LOCKS[key] = ProjectLock(Path(root) / ".lock")
        return _LOCKS[key]


class Conversations:
    def __init__(self, root: Path):
        self.data = Path(root)
        self.root = Path(root) / ".conversations"
        self._lock = _lock_for(self.root)
        self._activity: list | None = None        # the activity log, read once for rebuilding older conversations

    # -- paths ---------------------------------------------------------------
    def dir(self, cid: str) -> Path:
        """The conversation's folder: <root>/<id>, or <root>/.drafts/<id> while it is a draft nobody has sent."""
        if not ID_RE.fullmatch(str(cid or "")):
            raise ConversationError("Unknown conversation.")
        main = self.root / cid
        if not main.exists():
            draft = self.root / DRAFTS / cid
            if draft.exists():
                return draft
        return main

    def is_draft(self, cid: str) -> bool:
        return self.dir(cid).parent.name == DRAFTS

    def _promote(self, cid: str) -> None:
        """A draft becomes a conversation when its first message is sent."""
        d = self.dir(cid)
        if d.parent.name == DRAFTS:
            fsutil.replace(d, self.root / cid)

    def files_dir(self, cid: str) -> Path:
        d = self.dir(cid) / "files"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- meta ----------------------------------------------------------------
    def _read(self, cid: str) -> dict:
        f = self.dir(cid) / "meta.json"
        for attempt in range(20):                 # Windows: a file being replaced can refuse a read for a moment
            try:
                return self._migrate(json.loads(f.read_text(encoding="utf-8")))
            except PermissionError:
                time.sleep(0.02 * (attempt + 1))
            except (OSError, ValueError):
                break
        raise ConversationError("Unknown conversation.")

    def _migrate(self, meta: dict) -> dict:
        """A conversation saved before threads existed is the root of its own thread; one saved before `designs`
        existed gets the list rebuilt from its events (rebuild_designs). Written back once."""
        if not isinstance(meta, dict) or "id" not in meta or ("thread" in meta and "designs" in meta):
            return meta
        if "thread" not in meta:
            meta.update(thread=meta["id"], parent=None, fork_event=None, fork_reason="")
        if "designs" not in meta:
            try:
                meta["designs"] = rebuild_designs(meta, self.events(meta["id"]), self.data, self.activity())
                meta["designs_rebuilt"] = _now()
                if not meta.get("project"):        # it lost its design in front: the newest one still live leads
                    live = [e["project"] for e in meta["designs"] if e.get("project") and e.get("state") == "live"
                            and e.get("role") != "concept"]
                    if live:
                        meta["project"] = live[-1]
            except Exception:                     # never lose a conversation over its history
                meta["designs"] = []
        try:
            with self._lock:
                self._write(meta)
        except OSError:
            pass                                  # read-only: it is migrated again next time
        return meta

    def _write(self, meta: dict) -> dict:
        d = self.dir(meta["id"])
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        fsutil.replace(tmp, d / "meta.json")
        return meta

    def create(self, project: str | None = None, agent: str = "claude", model: str = "default", effort: str = "",
               title: str = "", draft: bool = False) -> dict:
        """A new conversation. draft=True (files, sketches or links attached before the first message): it lives in
        .drafts and is not listed until its first message is sent; one that is never sent is cleared later."""
        now = _now()
        cid = uuid.uuid4().hex[:12]
        meta = {"id": cid, "title": title.strip()[:120] or "New conversation", "title_auto": not title.strip(),
                "thread": cid, "parent": None, "fork_event": None, "fork_reason": "",
                "project": project or None, "agent": agent, "model": model or "default", "effort": effort or "",
                "session": None, "session_agent": None, "resolved_model": None, "resolved_agent": None,
                "created": now, "updated": now, "pinned": False, "cost_usd": 0.0, "cost_known": True,
                "messages": 0, "events": 0, "preview": "", "designs": []}
        if project:
            meta["designs"].append(_entry(project, "continued", None, now, "", self.data))
        if draft:
            meta["draft"] = True
        with self._lock:
            d = (self.root / DRAFTS / cid) if draft else (self.root / cid)
            d.mkdir(parents=True, exist_ok=True)
            self._write(meta)
            (d / "events.jsonl").write_text("", encoding="utf-8")
        if draft:
            self.prune_drafts()
        return meta

    def meta(self, cid: str) -> dict:
        with self._lock:
            return self._read(cid)

    def update(self, cid: str, touch: bool = False, **fields) -> dict:
        with self._lock:
            meta = self._read(cid)
            if fields.get("agent") and fields["agent"] != meta.get("agent") and "resolved_model" not in fields \
                    and (meta.get("resolved_agent") or meta.get("agent")) != fields["agent"]:
                # the model the last reply came from belongs to the agent that sent it, not to the new one
                fields = dict(fields, resolved_model=None, resolved_agent=None)
            meta.update(fields)
            if touch:
                meta["updated"] = _now()
            return self._write(meta)

    def rename(self, cid: str, title: str) -> dict:
        title = re.sub(r"\s+", " ", title or "").strip()[:120]
        if not title:
            raise ConversationError("A conversation needs a name.")
        return self.update(cid, title=title, title_auto=False)

    def pin(self, cid: str, on: bool = True) -> dict:
        return self.update(cid, pinned=bool(on))

    def link(self, cid: str, project: str | None, role: str = "continued", group: str | None = None,
             tool: str = "") -> dict:
        """The conversation follows its design to a new project (a picked concept, a design it made). The designs it
        was about before are kept in `projects`, oldest first; every design is listed in `designs` with its role."""
        if project is None:
            with self._lock:
                meta = self._read(cid)
                if meta.get("project") is None:
                    return meta
        return self.record(cid, project, role, tool=tool, group=group)

    def record(self, cid: str, project: str | None, role: str = "made", tool: str = "", group: str | None = None,
               front: bool = True, request: int | None = None, state: str | None = None) -> dict:
        """List a design (or, with project None and a group, a concept group) in the conversation.
        front: the design becomes the one in front (`project`); the one before is kept in `projects`.
        request: the user event that asked for it (default: the latest one)."""
        if role not in ROLES:
            raise ConversationError(f"Unknown role “{role}”.")
        with self._lock:
            meta = self._read(cid)
            req = self.request_index(cid) if request is None else request
            if project or group:
                _add_design(meta, project, role, req, tool, self.data, group=group, state=state)
            if front and meta.get("project") != project and (project or not group):
                seen = [p for p in (meta.get("projects") or []) if p]
                if meta.get("project") and meta["project"] not in seen:
                    seen.append(meta["project"])
                meta.update(project=project or None, projects=seen)
            return self._write(meta)

    def add_brief(self, cid: str, brief: str) -> dict:
        """A design brief written in this conversation (form/staged.py): kept in `briefs`, newest last."""
        with self._lock:
            meta = self._read(cid)
            bs = [b for b in meta.get("briefs") or [] if b != brief] + [brief]
            meta["briefs"] = bs[-20:]
            return self._write(meta)

    def request_index(self, cid: str) -> int | None:
        """The index of the latest user event: the request a tool is answering right now."""
        last = None
        for i, e in enumerate(self.events(cid)):
            if e.get("t") == "user":
                last = i
        return last

    def designs(self, cid: str, fresh: bool = True) -> list[dict]:
        """The conversation's designs in order. fresh: each with its state now (live, trashed or gone) and name; a
        concept group with its name, state, members and pick."""
        return [_fresh(e, self.data) if fresh else dict(e) for e in self.meta(cid).get("designs") or []]

    def mark_trashed(self, project: str) -> int:
        """A design moved to the trash: every conversation that lists it says so (it stays listed). Returns how many
        conversations changed."""
        n = 0
        if not self.root.is_dir():
            return n
        with self._lock:
            for d in self.root.iterdir():
                if not ID_RE.fullmatch(d.name):
                    continue
                try:
                    meta = self._read(d.name)
                except ConversationError:
                    continue
                hit = False
                for e in meta.get("designs") or []:
                    if e.get("project") == project and e.get("state") != "trashed":
                        e["state"], hit = "trashed", True
                if hit:
                    self._write(meta)
                    n += 1
        return n

    def fork(self, cid: str, at_event: int | None = None, project: str | None = None, reason: str = "") -> dict:
        """A new conversation in the same thread holding this one's events up to and including event `at_event`
        (all of them when None). Attachments are hard-linked where the disk allows, copied otherwise. It starts a new
        agent session: the first message it sends carries a transcript of what came before."""
        with self._lock:
            src = self._read(cid)
            evs = self.events(cid)
            if at_event is not None:
                try:
                    at_event = int(at_event)
                except (TypeError, ValueError):
                    raise ConversationError("Fork at an event number.")
                if not 0 <= at_event < len(evs):
                    raise ConversationError(f"This conversation has no event {at_event}.")
                evs = evs[:at_event + 1]
            meta = self.create(project if project is not None else src.get("project"), src.get("agent") or "claude",
                               src.get("model") or "default", src.get("effort") or "", src.get("title") or "")
            meta.update(thread=src.get("thread") or src["id"], parent=src["id"],
                        fork_event=(len(evs) - 1) if evs else None, fork_reason=re.sub(r"\s+", " ", str(reason or ""))[:120],
                        title_auto=bool(src.get("title_auto")), purpose=src.get("purpose"),
                        messages=sum(1 for e in evs if e.get("t") == "user"), events=len(evs),
                        preview=src.get("preview", "") if len(evs) == len(self.events(cid)) else next(
                            (re.sub(r"\s+", " ", str(e.get("text", "")))[:140] for e in reversed(evs) if e.get("t") in ("user", "text")), ""))
            if not meta.get("purpose"):
                meta.pop("purpose", None)
            if meta.get("project"):                   # a branch is about one design: its own, or the one it was given
                meta["designs"] = [_entry(meta["project"], "continued", None, _now(), "fork", self.data)]
            d = self.dir(meta["id"])
            with open(d / "events.jsonl", "w", encoding="utf-8") as fh:
                for e in evs:
                    fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
            sd = self.dir(cid) / "files"
            if sd.is_dir():
                dd = self.files_dir(meta["id"])
                for f in sd.iterdir():
                    if not f.is_file():
                        continue
                    try:
                        os.link(f, dd / f.name)
                    except OSError:
                        shutil.copyfile(f, dd / f.name)
            return self._write(meta)

    def thread(self, cid: str) -> list[dict]:
        """Every conversation of this one's thread, the root first, then the branches oldest first."""
        meta = self.meta(cid)
        rows = self.list(thread=meta.get("thread") or meta["id"], limit=100000)
        return sorted(rows, key=lambda m: (m["id"] != m.get("thread"), m.get("created", 0)))

    def ancestry(self, cid: str) -> dict:
        """Where this conversation sits in its thread: the chain it was forked from (the root first, each with the
        event it was forked at and why), and the conversations forked from it. An export carries this, so a branch
        read on its own still says what it is a branch of."""
        meta = self.meta(cid)
        rows = {m["id"]: m for m in self.thread(cid)}

        def row(m: dict) -> dict:
            return {"id": m["id"], "title": m.get("title") or "", "created": m.get("created"), "parent": m.get("parent"),
                    "fork_event": m.get("fork_event"), "fork_reason": m.get("fork_reason") or ""}
        chain, seen, cur = [], {cid}, meta.get("parent")
        while cur and cur not in seen:               # a parent that was deleted ends the chain: its id is still named
            seen.add(cur)
            m = rows.get(cur)
            chain.append(row(m) if m else {"id": cur, "title": "", "created": None, "parent": None, "fork_event": None,
                                           "fork_reason": "", "missing": True})
            cur = m.get("parent") if m else None
        chain.reverse()
        branches = sorted((row(m) for m in rows.values() if m.get("parent") == cid), key=lambda r: r.get("created") or 0)
        return {"thread": meta.get("thread") or cid, "parent": meta.get("parent"), "fork_event": meta.get("fork_event"),
                "fork_reason": meta.get("fork_reason") or "", "ancestors": chain, "branches": branches,
                "conversations": len(rows)}

    def delete(self, cid: str) -> None:
        with self._lock:
            d = self.dir(cid)
            if not (d / "meta.json").exists():
                raise ConversationError("Unknown conversation.")
            shutil.rmtree(d, ignore_errors=True)

    # -- events --------------------------------------------------------------
    def events(self, cid: str, start: int = 0) -> list[dict]:
        f = self.dir(cid) / "events.jsonl"
        out = []
        try:
            with open(f, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i < start:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        out.append({"t": "error", "text": "One saved event could not be read."})
        except OSError:
            pass
        return out

    def append(self, cid: str, event: dict) -> dict:
        """Add one event. The first user message names the conversation; cost and the session id are kept in meta."""
        if event.get("t") not in EVENT_KINDS:
            raise ConversationError(f"Unknown event kind “{event.get('t')}”.")
        ev = dict(event)
        ev.setdefault("ts", _now())
        with self._lock:
            meta = self._read(cid)
            if ev["t"] == "user" and self.is_draft(cid):    # the first message: the draft becomes a conversation
                self._promote(cid)
                meta.pop("draft", None)
            with open(self.dir(cid) / "events.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            meta["events"] = meta.get("events", 0) + 1
            t = ev["t"]
            if t == "user":
                meta["messages"] = meta.get("messages", 0) + 1
                if meta.get("title_auto") and meta["messages"] == 1:
                    meta["title"] = title_from(ev.get("text", ""))
                meta["preview"] = re.sub(r"\s+", " ", ev.get("text", ""))[:140]
            elif t == "text":
                meta["preview"] = re.sub(r"\s+", " ", ev.get("text", ""))[:140]
            elif t == "ask":
                meta["preview"] = "Question: " + re.sub(r"\s+", " ", ev.get("question", ""))[:128]
            elif t == "end":
                if ev.get("cost_usd") is not None:
                    meta["cost_usd"] = round(meta.get("cost_usd", 0.0) + float(ev["cost_usd"]), 6)
                elif not ev.get("stopped"):
                    meta["cost_known"] = False            # this agent does not report money
            if t in ("start", "end") and ev.get("model"):
                meta["resolved_model"] = ev["model"]
                meta["resolved_agent"] = ev.get("agent") or meta.get("agent")
            if t != "act":
                meta["updated"] = ev["ts"]
            self._write(meta)
        return ev

    def truncate(self, cid: str, count: int) -> None:
        """Keep only the first `count` events (a run that failed before saying anything is taken back)."""
        with self._lock:
            meta = self._read(cid)
            f = self.dir(cid) / "events.jsonl"
            lines = f.read_text(encoding="utf-8").splitlines(keepends=True)[:max(0, count)]
            f.write_text("".join(lines), encoding="utf-8")
            meta["events"] = len(lines)
            self._write(meta)

    # -- reading -------------------------------------------------------------
    def get(self, cid: str, start: int = 0) -> dict:
        meta = self.meta(cid)
        evs = self.events(cid, start)
        return {**meta, "events_from": start, "items": evs, "next": start + len(evs)}

    def list(self, project: str | None = None, q: str | None = None, limit: int = 200, thread: str | None = None,
             involving: str | None = None) -> list[dict]:
        """Pinned first, then newest. project: only that design's (the design in front). involving: every conversation
        that lists the design in `designs`, in front or not. thread: only that thread's. q: words that must all appear
        in the title or text; a search lists one row per thread (its best match, newest first)."""
        out = []
        if not self.root.is_dir():
            return out
        words = [w for w in (q or "").lower().split() if w]
        for d in self.root.iterdir():
            if not ID_RE.fullmatch(d.name):
                continue
            try:
                meta = self._read(d.name)
            except ConversationError:
                continue
            if project is not None and meta.get("project") != project:
                continue
            if involving is not None and meta.get("project") != involving and not any(
                    e.get("project") == involving for e in meta.get("designs") or []):
                continue
            if thread is not None and (meta.get("thread") or meta["id"]) != thread:
                continue
            if words:
                hay = (meta.get("title", "") + " " + meta.get("preview", "")).lower()
                if not all(w in hay for w in words):
                    hay += " " + " ".join(str(e.get("text", "")) for e in self.events(d.name) if e.get("t") in ("user", "text")).lower()
                    if not all(w in hay for w in words):
                        continue
                    meta = dict(meta, match=self._snippet(hay, words[0]))
            out.append(meta)
        out.sort(key=lambda m: (not m.get("pinned"), -m.get("updated", 0)))
        if words:                                   # one row per thread: the branches say the same things
            seen, one = set(), []
            for m in out:
                t = m.get("thread") or m["id"]
                if t not in seen:
                    seen.add(t)
                    one.append(m)
            out = one
        return out[:limit]

    @staticmethod
    def _snippet(hay: str, word: str, span: int = 60) -> str:
        i = hay.find(word)
        if i < 0:
            return ""
        a, b = max(0, i - span // 2), min(len(hay), i + len(word) + span)
        return ("…" if a else "") + re.sub(r"\s+", " ", hay[a:b]).strip() + ("…" if b < len(hay) else "")

    def latest(self, project: str | None) -> dict | None:
        """The conversation to show when a design is opened: its most recently used one; else the most recent one
        that made or touched it (a request that made several designs leads back from each of them)."""
        ms = [m for m in self.list(project) if m.get("messages")]
        if not ms and project:
            ms = [m for m in self.list(involving=project) if m.get("messages")]
        return max(ms, key=lambda m: m.get("updated", 0)) if ms else None

    # -- housekeeping ----------------------------------------------------------
    def activity(self) -> list:
        """The activity log (<data>/.activity.jsonl), read once; used to rebuild older conversations' designs."""
        if self._activity is None:
            out = []
            try:
                with open(self.data / ".activity.jsonl", encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            continue
            except OSError:
                pass
            self._activity = out
        return self._activity

    def prune_drafts(self, days: float = DRAFT_DAYS) -> list[str]:
        """Clear drafts (attachments nobody sent) older than `days`. Returns their ids."""
        gone, d = [], self.root / DRAFTS
        if not d.is_dir():
            return gone
        cut = time.time() - days * 86400
        for x in d.iterdir():
            try:
                if ID_RE.fullmatch(x.name) and (x / "meta.json").stat().st_mtime < cut:
                    shutil.rmtree(x, ignore_errors=True)
                    gone.append(x.name)
            except OSError:
                continue
        return gone

    def migrate(self, dry_run: bool = False, families: bool = True) -> dict:
        """Bring every saved conversation up to date (run by the engine at start and by `form conversations
        migrate`; running it again changes nothing):
        - `designs` rebuilt from events, meta and the activity log where it is missing (rebuild_designs);
        - a conversation with no message, no event and no pin, untouched for an hour, becomes a draft: it was made
          by attaching a file and never sent, so it is not listed (drafts are cleared after DRAFT_DAYS);
        - families: the designs one request made join the family of its first (lineage via "request"), so Home shows
          one card for them. A design that already has a lineage keeps it.
        dry_run: report what would change and write nothing."""
        report = {"conversations": 0, "rebuilt": [], "drafts": [], "families": []}
        if not self.root.is_dir():
            return report
        for d in sorted(self.root.iterdir()):
            if not ID_RE.fullmatch(d.name):
                continue
            try:
                raw = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            report["conversations"] += 1
            if not raw.get("messages") and not raw.get("events") and not raw.get("pinned") \
                    and (raw.get("updated") or 0) < time.time() - 3600:      # never one that is being written
                report["drafts"].append(d.name)
                if not dry_run:
                    with self._lock:
                        (self.root / DRAFTS).mkdir(parents=True, exist_ok=True)
                        fsutil.replace(d, self.root / DRAFTS / d.name)
                continue
            if "designs" in raw:
                designs = raw["designs"]
            else:
                designs = rebuild_designs(raw, self.events(d.name), self.data, self.activity())
                report["rebuilt"].append({"id": d.name, "title": raw.get("title", ""),
                                          "designs": [{k: e.get(k) for k in ("project", "group", "role", "state")}
                                                      for e in designs]})
                if not dry_run:
                    self.meta(d.name)                         # _migrate rebuilds and writes it back
            if families:
                by_req: dict = {}
                for e in designs:
                    if e.get("project") and e.get("role") == "made" and _state_of(self.data, e["project"])[0] == "live":
                        by_req.setdefault(e.get("request"), []).append(e["project"])
                for req, pids in by_req.items():
                    if req is None or len(pids) < 2:
                        continue
                    for pid in pids[1:]:
                        if dry_run or stamp_request(self.data, pid, d.name, req, pids[0]):
                            report["families"].append({"conversation": d.name, "project": pid, "root": pids[0]})
        if not dry_run:
            self.prune_drafts()
        return report

    # -- attachments ---------------------------------------------------------
    def attach(self, cid: str, src: Path | None = None, name: str | None = None, data: bytes | None = None) -> dict:
        """Copy a file into the conversation's folder. Returns {id, name, kind, size, file}."""
        self.meta(cid)
        if data is None:
            if src is None:
                raise ConversationError("Nothing to attach.")
            src = Path(src).expanduser()
            if not src.is_file():
                raise ConversationError(f"{src.name} is not a file Form Studio can read.")
            if src.stat().st_size > MAX_ATTACHMENT:
                raise ConversationError(f"{src.name} is larger than {MAX_ATTACHMENT // 1_000_000} MB.")
        elif len(data) > MAX_ATTACHMENT:
            raise ConversationError(f"That file is larger than {MAX_ATTACHMENT // 1_000_000} MB.")
        raw = Path(name or (src.name if src else "file")).name
        if raw.lower().endswith(SKETCH_SUFFIX):           # a double suffix: keep it whole so the kind survives
            base, ext = raw[:-len(SKETCH_SUFFIX)], SKETCH_SUFFIX
        else:
            base, ext = Path(raw).stem, re.sub(r"[^a-z0-9.]", "", Path(raw).suffix.lower())[:8]
        stem = re.sub(r"[^A-Za-z0-9_\-]+", "-", base).strip("-")[:60] or "file"
        kind = kind_of(stem + ext)
        if kind == "file":
            raise ConversationError(f"{raw}: attach images, PDFs, STEP/STL/3MF parts or a sketch.",)
        d = self.files_dir(cid)
        aid = uuid.uuid4().hex[:6]
        target = d / f"{aid}-{stem}{ext}"
        if data is not None:
            target.write_bytes(data)
        else:
            shutil.copyfile(src, target)
        return {"id": aid, "name": raw, "kind": kind, "size": target.stat().st_size, "file": target.name}

    def attachment(self, cid: str, file: str) -> Path:
        d = self.files_dir(cid).resolve()
        f = (d / file).resolve()
        if not f.is_relative_to(d) or not f.is_file():
            raise ConversationError("That attachment does not exist.")
        return f

    def attachments(self, cid: str, ids: list[str]) -> list[dict]:
        """Attachment records for the given ids (files that are still in the folder)."""
        out = []
        d = self.files_dir(cid)
        for aid in ids or []:
            if not re.fullmatch(r"[0-9a-f]{6}", str(aid)):
                continue
            for f in sorted(d.glob(f"{aid}-*")):
                out.append({"id": aid, "name": f.name[7:], "kind": kind_of(f.name), "size": f.stat().st_size, "file": f.name})
                break
        return out


# ---- designs: what a conversation made or touched ------------------------------------------------------------------

_TRASH_RE = re.compile(r"(?P<pid>[a-z0-9][a-z0-9-]*?)-\d{8}T\d{6}Z(?:-\d+)?")
_RANK = {"made": 0, "concept": 1, "reference-study": 2, "continued": 3}


def _project_file(data: Path, pid: str) -> Path | None:
    """project.json of a live design, or of its newest copy in the trash, else None."""
    f = Path(data) / pid / "project.json"
    if f.is_file():
        return f
    t = Path(data) / ".trash"
    if t.is_dir():
        hits = sorted((d for d in t.iterdir() if (m := _TRASH_RE.fullmatch(d.name)) and m.group("pid") == pid),
                      key=lambda d: d.name)
        for d in reversed(hits):
            if (d / "project.json").is_file():
                return d / "project.json"
    return None


def _state_of(data: Path, pid: str) -> tuple[str, str]:
    """(state, name) of a design: live, trashed (in <data>/.trash) or gone."""
    f = _project_file(data, pid)
    if f is None:
        return "gone", pid
    try:
        name = json.loads(f.read_text(encoding="utf-8")).get("name") or pid
    except (OSError, ValueError):
        name = pid
    return ("live" if f.parent.parent == Path(data) else "trashed"), str(name)


def _group(data: Path, gid: str) -> dict | None:
    try:
        return json.loads((Path(data) / ".concepts" / f"{gid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _entry(project: str | None, role: str, request: int | None, ts: float, tool: str, data: Path,
           group: str | None = None, state: str | None = None) -> dict:
    e = {"project": project, "role": role, "request": request, "ts": ts, "tool": tool}
    if group:
        e["group"] = group
    if project:
        e["state"] = state or _state_of(data, project)[0]
    else:
        g = _group(data, group) if group else None
        e["state"] = state or (g or {}).get("state") or "open"
    return e


def _add_design(meta: dict, project: str | None, role: str, request: int | None, tool: str, data: Path,
                group: str | None = None, state: str | None = None) -> dict:
    """Add a design (or a concept group) to meta["designs"], or update the one already there: a stronger role
    (made over concept over continued) wins, the first request and time are kept, the state is refreshed."""
    ds = meta.setdefault("designs", [])
    key = ("project", project) if project else ("group", group)
    for e in ds:
        if key[1] and e.get(key[0]) == key[1] and (project or not e.get("project")):
            if _RANK.get(role, 9) < _RANK.get(e.get("role"), 9):
                e["role"] = role
                if tool:
                    e["tool"] = tool
            if group and not e.get("group"):
                e["group"] = group
            if project:
                e["state"] = state or _state_of(data, project)[0]
            elif state:
                e["state"] = state
            if e.get("request") is None and request is not None:
                e["request"] = request
            return e
    e = _entry(project, role, request, _now(), tool, data, group=group, state=state)
    ds.append(e)
    return e


def _fresh(e: dict, data: Path) -> dict:
    e = dict(e)
    if e.get("project"):
        e["state"], e["name"] = _state_of(data, e["project"])
    elif e.get("group"):
        g = _group(data, e["group"])
        if g:
            e.update(state=g.get("state") or e.get("state"), name=g.get("name"), picked=g.get("picked"),
                     members=[m.get("project") for m in g.get("members") or []])
    return e


_PROJECT_IN = r'"project"\s*:\s*(?:\{\s*"id"\s*:\s*)?"([a-z0-9][a-z0-9-]{0,60})"'
_RESULT_ID = {   # where each creator tool's result names the design it made
    "create_project": _PROJECT_IN,
    "create_design": _PROJECT_IN,
    "reconstruct": _PROJECT_IN,
    "duplicate_project": r'"id"\s*:\s*"([a-z0-9][a-z0-9-]{0,60})"',
    "import_project": r'"id"\s*:\s*"([a-z0-9][a-z0-9-]{0,60})"',
    "pick_concept": r'"picked"\s*:\s*"([a-z0-9][a-z0-9-]{0,60})"',
}
_INPUT_ID = re.compile(r"\bproject(?:_or_file)?=([a-z0-9][a-z0-9-]{0,60})(?=\s|$)")
_MADE_KINDS = ("commit", "reconstruct", "project", "concepts")


def rebuild_designs(meta: dict, events: list[dict], data: Path, activity: list | None = None) -> list[dict]:
    """`designs` for a conversation saved before it existed, from what it recorded:
    - a creator tool's result (CREATOR_TOOLS): the project its result names, or the `project` the app tagged it with,
      or else the design the activity log says was created between the call and its result ("Created …",
      "Reconstructed …", "Copied from …", "Imported …"): role made (concept for a concept group);
    - any other tool called with project=<id> of a design that exists or is in the trash: role continued (a concept
      group's members are left out unless picked; the group itself is listed);
    - meta: the design in front, earlier ones in `projects`, a deleted one in `project_was`, concept groups.
    `request` is the user event each one answered. Nothing is invented: an id that is neither a design nor in the
    trash is left out unless meta names it (then its state is "gone")."""
    data = Path(data)
    out: list[dict] = []
    tools: dict = {}
    request = None
    groups = [g for g in (meta.get("concepts") or []) if GID_RE.fullmatch(str(g))]
    for e in events:                              # groups proposed here, so their members are known up front
        c = e.get("concepts")
        if e.get("t") == "result" and isinstance(c, dict) and GID_RE.fullmatch(str(c.get("group"))) \
                and c["group"] not in groups:
            groups.append(c["group"])
    members, picked = {}, set()                   # concept project -> its group; the picked ones
    for g in groups:
        info = _group(data, g) or {}
        members.update({m.get("project"): g for m in info.get("members") or [] if m.get("project")})
        if info.get("picked"):
            picked.add(info["picked"])

    def add(pid, role, req, ts, tool, group=None, must_exist=True):
        if pid and not PID_RE.fullmatch(pid):
            return
        if pid and must_exist and _state_of(data, pid)[0] == "gone":
            return
        if pid and role == "continued" and pid in members and pid not in picked:
            role, group = "concept", members[pid]          # a concept the person did not pick
        n = len(out)
        e = _add_design({"designs": out}, pid, role, req, tool, data, group=group)
        if len(out) > n and ts:                       # a new entry: dated when the conversation met it
            e["ts"] = ts

    for i, e in enumerate(events):
        t = e.get("t")
        if t == "user":
            request = i
        elif t == "tool":
            name = str(e.get("name") or "").split("__")[-1]
            tools[e.get("id")] = (name, e.get("ts") or 0, request)
            for pid in _INPUT_ID.findall(str(e.get("input") or "")):
                add(pid, "continued", request, e.get("ts"), name)
        elif t == "result" and e.get("ok"):
            name0, t0, req = tools.get(e.get("id"), ("", e.get("ts") or 0, request))
            name = str(e.get("name") or name0).split("__")[-1]
            role = CREATOR_TOOLS.get(name)
            if role == "concept":
                g = (e.get("concepts") or {}).get("group") if isinstance(e.get("concepts"), dict) else None
                m = g or (re.search(r'"id"\s*:\s*"([0-9a-f]{10})"', str(e.get("text") or "")) or [None, None])[1]
                if m:
                    if m not in groups:
                        groups.append(m)
                    add(None, "concept", req, e.get("ts"), name, group=m)
                continue
            if not role:
                if e.get("project"):
                    add(e["project"], "continued", req, e.get("ts"), name)
                continue
            ids = [e["project"]] if e.get("project") else []
            if not ids and name in _RESULT_ID:
                ids = re.findall(_RESULT_ID[name], str(e.get("text") or ""))[:1]
            if not ids and activity:
                lo, hi = (t0 or e.get("ts") or 0) - 1, (e.get("ts") or 0) + 1
                ids = [a["project"] for a in activity if a.get("project") and a.get("by") != "you"
                       and a.get("kind") in _MADE_KINDS and lo <= (a.get("ts") or 0) <= hi
                       and str(a.get("text") or "").startswith(("Created", "Reconstructed", "Copied", "Imported",
                                                               "Picked"))][:1]
            for pid in ids:
                add(pid, role, req, e.get("ts"), name)
    for g in groups:
        add(None, "concept", None, meta.get("created"), "", group=g)
    for pid in [*(meta.get("projects") or []), meta.get("project")]:
        if pid:
            add(pid, "continued", None, meta.get("updated"), "", must_exist=False)
    was = (meta.get("project_was") or {}).get("id")
    if was:
        add(was, "continued", None, meta.get("updated"), "", must_exist=False)
    for e in out:
        e["migrated"] = True
    return out


def stamp_request(data: Path, project: str, conversation: str, request: int | None, root_pid: str | None,
                  tool: str = "") -> bool:
    """Record where a design came from (`origin`: the conversation and the request) and, when an earlier design of the
    same request exists (root_pid), put it in that design's family: lineage {root, parent: root_pid, via "request"}.
    A design that already has a lineage (a copy, a variant, a picked concept) keeps it. Returns True when the family
    changed. Works on project.json under the project's lock, so the app, the MCP server and the CLI can all call it."""
    from .studio import ProjectLock, SCHEMA
    data = Path(data)
    if not PID_RE.fullmatch(str(project or "")):
        return False
    f = data / project / "project.json"
    if not f.is_file():
        return False
    with ProjectLock(data / ".locks" / f"{project}.lock"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(p, dict) or p.get("schema") != SCHEMA:
            return False
        changed = False
        if not p.get("origin"):
            p["origin"] = {"conversation": conversation, "request_event": request, "tool": tool}
        if root_pid and root_pid != project and not p.get("lineage"):
            root = root_pid
            try:
                rp = json.loads((data / root_pid / "project.json").read_text(encoding="utf-8"))
                root = ((rp.get("lineage") or {}).get("root")) or root_pid
            except (OSError, ValueError):
                pass
            p["lineage"] = {"root": root, "parent": root_pid, "parent_rev": None, "via": "request"}
            changed = True
        p["updated"] = time.time()
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(p, indent=1), encoding="utf-8")
        fsutil.replace(tmp, f)
        return changed


MIGRATION_KEY = "conversation_designs"


def migrate_once(data: Path) -> dict | None:
    """Run Conversations.migrate once per data folder (recorded in <data>/.form-migrations.json, the file
    form/capabilities.py keeps one-time changes in). Returns the report, or None when it already ran."""
    f = Path(data) / ".form-migrations.json"
    try:
        done = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        done = {}
    if not isinstance(done, dict) or MIGRATION_KEY in done:
        return None
    rep = Conversations(data).migrate()
    done[MIGRATION_KEY] = {"ts": time.time(), "conversations": rep["conversations"], "rebuilt": len(rep["rebuilt"]),
                           "drafts": rep["drafts"], "families": rep["families"]}
    try:
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(done), encoding="utf-8")
        fsutil.replace(tmp, f)
    except OSError:
        pass
    return rep


def env_conversation() -> str | None:
    """The conversation this process works for ($FORM_CONVERSATION, set by form/chat.py for its MCP server)."""
    cid = os.environ.get(ENV_CONVERSATION, "").strip()
    return cid if ID_RE.fullmatch(cid) else None


def made(data: Path, project: str | None, role: str = "made", tool: str = "", conversation: str | None = None,
         group: str | None = None, family: bool = True, front: bool | None = None) -> dict | None:
    """A tool just made, picked, copied or reconstructed `project` (or proposed concept `group`) for a conversation:
    list it in the conversation's `designs` (and put it in front, unless it is a concept group), record its origin,
    and, for the second and later design one request makes, put it in the family of the first (family=False: an
    unrelated design, e.g. create_design(relation="new")). conversation: default $FORM_CONVERSATION; without one
    (the CLI, an agent outside Form Studio's chat) nothing is recorded. Returns the conversation's meta, or None."""
    cid = conversation or env_conversation()
    if not cid:
        return None
    store = Conversations(data)
    try:
        meta = store.meta(cid)
    except ConversationError:
        return None
    req = store.request_index(cid)
    if project and role == "made":
        root = None
        if family:
            root = next((e["project"] for e in meta.get("designs") or []
                         if e.get("project") and e.get("project") != project and e.get("role") == "made"
                         and e.get("request") == req and req is not None
                         and _state_of(Path(data), e["project"])[0] == "live"), None)
        try:
            stamp_request(Path(data), project, cid, req, root, tool)
        except OSError:
            pass
    try:
        return store.record(cid, project, role, tool=tool, group=group, request=req,
                            front=(role != "concept") if front is None else front)
    except ConversationError:
        return None
