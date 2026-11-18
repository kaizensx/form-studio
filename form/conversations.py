"""Conversations: every chat is a folder on disk, so it reloads exactly as it was.

    <data>/.conversations/<id>/meta.json       id, title, project, agent, model, effort, session, pinned, cost, …
    <data>/.conversations/<id>/events.jsonl    one event per line: user, start, text, tool, result, act, end, error
    <data>/.conversations/<id>/files/          attachments, copied in (the only folder the agent may read)

Nothing here talks to an agent; form/chat.py runs the agent and appends what it says.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from . import fsutil

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_EXT = {".pdf"}
CAD_EXT = {".step", ".stp", ".stl"}
MAX_ATTACHMENT = 60_000_000
ID_RE = re.compile(r"[0-9a-f]{12}")
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
                return json.loads(f.read_text(encoding="utf-8"))
            except PermissionError:
                time.sleep(0.02 * (attempt + 1))
            except (OSError, ValueError):
                break
        raise ConversationError("Unknown conversation.")

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
        meta = {"id": uuid.uuid4().hex[:12], "title": title.strip()[:120] or "New conversation", "title_auto": not title.strip(),
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

    def list(self, project: str | None = None, q: str | None = None, limit: int = 200) -> list[dict]:
        """Pinned first, then newest. project: only that design's. q: words that must all appear in the title or text."""
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
            if words:
                hay = (meta.get("title", "") + " " + meta.get("preview", "")).lower()
                if not all(w in hay for w in words):
                    hay += " " + " ".join(str(e.get("text", "")) for e in self.events(d.name) if e.get("t") in ("user", "text")).lower()
                    if not all(w in hay for w in words):
                        continue
                    meta = dict(meta, match=self._snippet(hay, words[0]))
            out.append(meta)
        out.sort(key=lambda m: (not m.get("pinned"), -m.get("updated", 0)))
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
        stem = re.sub(r"[^A-Za-z0-9_\-]+", "-", Path(raw).stem).strip("-")[:60] or "file"
        ext = re.sub(r"[^a-z0-9.]", "", Path(raw).suffix.lower())[:8]
        kind = kind_of(stem + ext)
        if kind == "file":
            raise ConversationError(f"{raw}: attach images, PDFs, or STEP/STL parts.",)
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
