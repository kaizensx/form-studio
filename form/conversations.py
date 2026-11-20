"""Conversations: every chat is a folder on disk, so it reloads exactly as it was.

    <data>/.conversations/<id>/meta.json       id, title, project, agent, model, effort, session, pinned, cost,
                                               thread, parent, fork_event, fork_reason, projects, …
    <data>/.conversations/<id>/events.jsonl    one event per line: user, start, text, tool, result, act, end, error
    <data>/.conversations/<id>/files/          attachments, cloned or copied in (the only folder the agent may read)
    <data>/.conversations/<id>/sources.json    where attachments fetched from a link came from (url, licence, author)

Conversations are linked, never scattered. Every conversation belongs to a thread (the id of the one it all started
from; an old conversation without one is its own thread). A fork copies a conversation's events up to a point into a
new one in the same thread, with `parent`, `fork_event` and `fork_reason` saying where it branched; its agent session
starts fresh and is handed a transcript of what came before. A design that moves on (a concept picked, a copy, a
design the agent made in the conversation) takes the conversation with it: `link` moves it and remembers the designs
it was about in `projects`.

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
CAD_EXT = {".step", ".stp", ".stl", ".3mf", ".obj"}
MESH_EXT = {".stl", ".3mf", ".obj"}
SKETCH_SUFFIX = ".sketch.json"        # a sketch drawn in Form Studio (form/sketch.py): structured geometry, read as JSON
MAX_ATTACHMENT = 2_000_000_000      # dense scans and sculpts are often hundreds of MB; a local file is never read whole
WARN_ATTACHMENT = 500_000_000       # above this the person is told it will be slow
ID_RE = re.compile(r"[0-9a-f]{12}")
EVENT_KINDS = ("user", "start", "text", "tool", "result", "act", "end", "error", "ask", "answer", "suggest")



def _clone(src: Path, dst: Path) -> bool:
    """A copy-on-write clone: instant, no extra space, and later changes to either file stay apart."""
    import sys
    try:
        if sys.platform == "darwin":
            import ctypes
            import ctypes.util
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            return libc.clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0
        if sys.platform.startswith("linux"):
            import fcntl
            with open(src, "rb") as a, open(dst, "wb") as b:
                try:
                    fcntl.ioctl(b.fileno(), 0x40049409, a.fileno())        # FICLONE
                    return True
                except OSError:
                    pass
            dst.unlink(missing_ok=True)
    except (OSError, AttributeError):
        pass
    return False


def place(src: Path, dst: Path) -> str:
    """Put src at dst without reading it into memory: "cloned", "linked" (a hard link on the same disk) or "copied"
    (streamed). Returns which."""
    if _clone(src, dst):
        return "cloned"
    try:
        os.link(src, dst)
        return "linked"
    except OSError:
        pass
    shutil.copyfile(src, dst)
    return "copied"


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


def _lock_for(root: Path) -> threading.RLock:
    """One lock per conversations folder, shared by every Conversations object in the process. The chat service and
    the engine (deleting a design detaches its conversations) each make their own object; with separate locks a read
    could meet a half-done write, which on Windows fails instead of waiting."""
    key = str(Path(root).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class Conversations:
    def __init__(self, root: Path):
        self.root = Path(root) / ".conversations"
        self._lock = _lock_for(self.root)

    # -- paths ---------------------------------------------------------------
    def dir(self, cid: str) -> Path:
        if not ID_RE.fullmatch(str(cid or "")):
            raise ConversationError("Unknown conversation.")
        return self.root / cid

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
        """A conversation saved before threads existed is the root of its own thread; written back once."""
        if not isinstance(meta, dict) or "id" not in meta or "thread" in meta:
            return meta
        meta.update(thread=meta["id"], parent=None, fork_event=None, fork_reason="")
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
               title: str = "") -> dict:
        now = _now()
        cid = uuid.uuid4().hex[:12]
        meta = {"id": cid, "title": title.strip()[:120] or "New conversation", "title_auto": not title.strip(),
                "thread": cid, "parent": None, "fork_event": None, "fork_reason": "",
                "project": project or None, "agent": agent, "model": model or "default", "effort": effort or "",
                "session": None, "session_agent": None, "resolved_model": None, "resolved_agent": None,
                "created": now, "updated": now, "pinned": False, "cost_usd": 0.0, "cost_known": True,
                "messages": 0, "events": 0, "preview": ""}
        with self._lock:
            self._write(meta)
            (self.dir(meta["id"]) / "events.jsonl").write_text("", encoding="utf-8")
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

    def link(self, cid: str, project: str | None) -> dict:
        """The conversation follows its design to a new project (a picked concept, a design it made). The designs it
        was about before are kept in `projects`, oldest first."""
        with self._lock:
            meta = self._read(cid)
            old = meta.get("project")
            if old == project:
                return meta
            seen = [p for p in (meta.get("projects") or []) if p]
            if old and old not in seen:
                seen.append(old)
            meta.update(project=project or None, projects=seen)
            return self._write(meta)

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

    def list(self, project: str | None = None, q: str | None = None, limit: int = 200, thread: str | None = None) -> list[dict]:
        """Pinned first, then newest. project: only that design's. thread: only that thread's. q: words that must all
        appear in the title or text; a search lists one row per thread (its best match, newest first)."""
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
        """The conversation to show when a design is opened: its most recently used one."""
        ms = [m for m in self.list(project) if m.get("messages")]
        return max(ms, key=lambda m: m.get("updated", 0)) if ms else None

    # -- attachments ---------------------------------------------------------
    def attach(self, cid: str, src: Path | None = None, name: str | None = None, data: bytes | None = None,
               source: dict | None = None, move: bool = False) -> dict:
        """Put a file into the conversation's folder. Returns {id, name, kind, size, file} (+ mesh, warning, source).

        A local file is placed without reading it into memory: a copy-on-write clone where the disk supports it
        (APFS, Btrfs, XFS), else a hard link on the same disk, else a streamed copy. move=True takes the file over
        (a download already in the conversation's folder). source: where it came from (url, site, licence, author),
        kept beside the conversation so the agent and Describe can say it."""
        self.meta(cid)
        if data is None:
            if src is None:
                raise ConversationError("Nothing to attach.")
            src = Path(src).expanduser()
            if not src.is_file():
                raise ConversationError(f"{src.name} is not a file Form Studio can read.")
            size = src.stat().st_size
        else:
            size = len(data)
        if size > MAX_ATTACHMENT:
            what = src.name if data is None else "That file"
            raise ConversationError(f"{what} is larger than {MAX_ATTACHMENT // 1_000_000_000} GB.")
        raw = Path(name or (src.name if src else "file")).name
        if raw.lower().endswith(SKETCH_SUFFIX):           # a double suffix: keep it whole so the kind survives
            base, ext = raw[:-len(SKETCH_SUFFIX)], SKETCH_SUFFIX
        else:
            base, ext = Path(raw).stem, re.sub(r"[^a-z0-9.]", "", Path(raw).suffix.lower())[:8]
        stem = re.sub(r"[^A-Za-z0-9_\-]+", "-", base).strip("-")[:60] or "file"
        kind = kind_of(stem + ext)
        if kind == "file":
            raise ConversationError(f"{raw}: attach images, PDFs, STEP/STL/3MF/OBJ parts or a sketch.",)
        d = self.files_dir(cid)
        aid = uuid.uuid4().hex[:6]
        target = d / f"{aid}-{stem}{ext}"
        how = "written"
        if data is not None:
            target.write_bytes(data)
        elif move:
            os.replace(src, target)
            how = "moved"
        else:
            how = place(src, target)
        rec = {"id": aid, "name": raw, "kind": kind, "size": target.stat().st_size, "file": target.name, "placed": how}
        if ext in MESH_EXT:
            from . import meshprep
            q = meshprep.quick(target)
            rec["mesh"] = {k: q[k] for k in ("triangles", "class")}
            if q.get("warning"):
                rec["warning"] = q["warning"]
        elif size > WARN_ATTACHMENT:
            rec["warning"] = f"{size / 1e6:.0f} MB is a very large file; reading it will take a while."
        if source:
            src_rec = {k: v for k, v in source.items() if v not in (None, "", [])}
            with self._lock:
                f = self.dir(cid) / "sources.json"
                try:
                    known = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    known = {}
                known[target.name] = src_rec
                tmp = f.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(known, indent=1, ensure_ascii=False), encoding="utf-8")
                fsutil.replace(tmp, f)
            rec["source"] = src_rec
        return rec

    def sources(self, cid: str) -> dict:
        """{attachment file: {url, site, title, author, licence, ...}} for files that came from a link."""
        try:
            return json.loads((self.dir(cid) / "sources.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

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
                rec = {"id": aid, "name": f.name[7:], "kind": kind_of(f.name), "size": f.stat().st_size, "file": f.name}
                src = self.sources(cid).get(f.name)
                if src:
                    rec["source"] = src
                out.append(rec)
                break
        return out
