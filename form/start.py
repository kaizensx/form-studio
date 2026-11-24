"""How a design starts: Home's "drop anything" composer, the start options, links, and measurements the person takes.

Home takes words, photos, sketches, files and links in one place and offers three ways to begin: Blank (a plain block
to shape), For my printer, or Just a 3D model. This module is the engine side of that:

- purpose: "print" (for 3D printing on the person's printer), "model" (a 3D model only, never sliced) or "game" (a
  real-time asset for a game engine: LODs, UVs, baked textures, collision; form/game). The engine
  owns it (form/purpose.py: the design's purpose, and the default from the 3D printing capability); Home only says which
  one the next design gets.
- blank(): a clean, minimal design written as code that builds in the real kernel.
- fetch(): a link pasted on Home or in a chat. A file the person linked to is downloaded (STL, STEP, 3MF, OBJ, PDF,
  an image); a model page on Printables has its part files downloaded with title, author and licence;
  Thingiverse and MakerWorld pages say why their files cannot be fetched (form/sources); any other page is
  passed to the agent as a link and nothing is fetched. Nothing is crawled.
- apply_measurement(): a number the person measured in a guided measurement card becomes a new revision whose
  provenance says how it was measured. An estimate stays "assumed".

HTTP routes for all of this (and for concept groups, form/concepts.py) are in route_get / route_post, called from
form/home_api.py.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import urllib.error
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from . import ask as ask_mod
from .studio import StudioError

PURPOSES = ("print", "model", "game")
ENV_PURPOSE = "FORM_PURPOSE"          # given to the MCP server of one chat run: designs it creates get this purpose
MAX_FETCH = 2_000_000_000             # the attachment limit (form/conversations.py); streamed to disk, never held
FETCH_TIMEOUT = 30
METHOD_SIGMA = {"calipers": 0.05, "ruler": 0.5, "tape": 1.0}     # mm, one standard deviation, per instrument


def _purpose(purpose) -> str:
    p = str(purpose or "").strip().lower()
    if p not in PURPOSES:
        raise StudioError(f"Unknown purpose “{purpose}”.", "Use \"print\" (for my printer), \"model\" (just a 3D model) "
                          "or \"game\" (a game asset).")
    return p


def env_purpose() -> str | None:
    """The purpose a chat run asked for (FORM_PURPOSE), or None."""
    p = (os.environ.get(ENV_PURPOSE) or "").strip().lower()
    return p if p in PURPOSES else None


# ---- purpose ---------------------------------------------------------------------------------------------------

def set_purpose(st, pid: str, purpose: str) -> dict:
    """What the design is for, through the engine's own setting (form/purpose.py), so it is in the design's history."""
    purpose = _purpose(purpose)
    with st.lock(pid):
        return st.settings(st.load(pid), {"purpose": purpose})


def printer_name_cfg(cfg: dict) -> str | None:
    """The printer's name from the configuration alone (no slicer lookup): the default printer, else [printer].name."""
    from . import printers as printers_mod
    choice = printers_mod.default_choice(cfg)
    return (choice or {}).get("machine") or (cfg.get("printer") or {}).get("name") or None


def state(st) -> dict:
    """{"purpose": what a new design is for by default (form/purpose.py: a print only when 3D printing is on),
        "printer": {"name", "available"}}."""
    from . import purpose as purpose_mod
    from . import printers as printers_mod
    try:
        available = bool(st.slice_mode()["on"])
        s = st.slicer_info()
    except Exception:                                # a broken slicer install must not break Home
        available, s = False, {}
    choice = printers_mod.default_choice(st.cfg)
    name = ((choice or {}).get("machine")
            or (((s.get("presets") or {}).get("machine") or {}).get("name") if s.get("available") else None)
            or (st.cfg.get("printer") or {}).get("name") or None)
    return {"purpose": purpose_mod.default(st.cfg), "printer": {"name": name, "available": available}}


def purpose_line(purpose: str | None, printer: str | None) -> str:
    """The one line the agent reads about what the design is for."""
    if purpose == "print":
        return "Purpose: for 3D printing" + (f" on {printer}" if printer else "")
    if purpose == "model":
        return "Purpose: just a 3D model, no printer: do not slice; print checks do not apply."
    if purpose == "game":
        return ("Purpose: a game asset (purpose \"game\"), no printer: do not slice; print checks do not apply. "
                "Read design_guide(topic=\"game\"); when the design is built, make the asset with game_asset "
                "(LODs at triangle budgets, UVs, baked maps, collision, an engine preset).")
    return ""


# ---- Blank -----------------------------------------------------------------------------------------------------

BLANK_SOURCE = '''\
"""Blank design: a rounded block to shape into anything. Form Studio starting point."""
from build123d import Align, Axis, Box, fillet

from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Blank design"
    summary = "A rounded block to start from."
    solids = 1
    params = [
        Param("width", "Width", 60, 5, 400, 0.5, "mm", "form", "body"),
        Param("depth", "Depth", 40, 5, 400, 0.5, "mm", "form", "body"),
        Param("height", "Height", 20, 1, 400, 0.5, "mm", "form", "body"),
        Param("corner_r", "Corner radius", 3, 0, 50, 0.5, "mm", "form", "body", "0 = square corners."),
    ]
    features = [Feature("body", "Body", "structure")]

    def constraints(self, v):
        if 2 * v["corner_r"] >= min(v["width"], v["depth"]):
            return [RecipeError("The corner radius is larger than the block", "body",
                                "Use a radius under half the smaller side.", ["corner_r", "width", "depth"])]
        return []

    def build(self, v):
        body = Box(v["width"], v["depth"], v["height"], align=A)
        if v["corner_r"] > 0:
            body = fillet(body.edges().filter_by(Axis.Z), v["corner_r"])
        return [Stage("body", body)]
'''


def blank(st, name: str = "Untitled design", purpose: str = "print") -> dict:
    """A new design from BLANK_SOURCE with its purpose recorded. Returns the project."""
    purpose = _purpose(purpose)
    name = " ".join(str(name or "").split())[:80] or "Untitled design"
    p = st.create_design(name, BLANK_SOURCE, "", purpose=purpose)
    st.activity(p["id"], "commit", f"Created {name} (blank design)", by="you")
    return st.load(p["id"])


# ---- links -----------------------------------------------------------------------------------------------------
#
# A link is one of three things (form/sources): a direct file (downloaded, streamed to disk), a model page on a site
# Form Studio knows (Printables: its files are fetched; Thingiverse without an app token and MakerWorld: the reason and
# what to do instead), or any other page (passed to the agent as a link, nothing read). Downloads stream into the
# conversation's folder with their progress in PROGRESS, and are attached with where they came from and the licence.

PROGRESS: dict[str, dict] = {}          # url -> {"name", "bytes", "total", "started"} while a download runs
_PROGRESS_LOCK = threading.Lock()
LINK_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
MAX_LINKS = 5                           # links fetched from one chat message
MAX_MODEL_FILES = 8                     # files fetched from one model page


def _store(st):
    chat = getattr(st, "chat", None)
    if chat is not None:
        return chat.store
    from .conversations import Conversations
    return Conversations(st.root)


def progress() -> list[dict]:
    """Downloads running now: [{url, name, bytes, total}] (total None when the site does not say)."""
    with _PROGRESS_LOCK:
        return [{"url": u, **v} for u, v in PROGRESS.items()]


def _limit() -> str:
    return f"{MAX_FETCH / 1e9:g} GB" if MAX_FETCH >= 1e9 else f"{MAX_FETCH / 1e6:g} MB"


def _name_from(r, url: str) -> str:
    cd = r.headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, flags=re.I) or re.search(r'filename="?([^";]+)"?', cd, flags=re.I)
    return unquote(m.group(1)).strip() if m else unquote(PurePosixPath(urlparse(url).path).name)


def download(url: str, folder: Path, name: str | None = None, headers: dict | None = None) -> tuple[Path, str, int]:
    """Stream one file into `folder` (never held in memory). Returns (temporary path, file name, bytes).
    Refuses a web page served under a file's name, and anything over MAX_FETCH."""
    from . import net
    from . import sources
    host = urlparse(url).hostname or url
    folder.mkdir(parents=True, exist_ok=True)
    req = sources._request(url, headers=headers)
    tmp = folder / f".incoming-{uuid.uuid4().hex[:8]}"
    total = 0
    try:
        with net.urlopen(req, timeout=FETCH_TIMEOUT) as r:          # urllib follows redirects; no cookies are kept
            ctype = r.headers.get_content_type()
            nm = name or _name_from(r, r.geturl() or url) or "file"
            size = r.headers.get("Content-Length")
            size = int(size) if size and size.isdigit() else None
            if size and size > MAX_FETCH:
                raise StudioError(f"{nm} is larger than {_limit()}.",
                                  "Download it yourself and drop the file here if you still want it attached.")
            if ctype == "text/html":
                raise StudioError("That link opens a web page, not the file itself.",
                                  "Use the file's direct download link (often a Download or Raw button), or paste the "
                                  "page link as text so the agent can read the page.")
            with _PROGRESS_LOCK:
                PROGRESS[url] = {"name": nm, "bytes": 0, "total": size, "started": time.time()}
            with open(tmp, "wb") as out:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    total += len(b)
                    if total > MAX_FETCH:
                        raise StudioError(f"{nm} is larger than {_limit()}.",
                                          "Download it yourself and drop the file here if you still want it attached.")
                    out.write(b)
                    with _PROGRESS_LOCK:
                        PROGRESS[url]["bytes"] = total
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        hint = ("The link may have expired: signed download links (MakerWorld's) last only minutes. Copy a fresh one, "
                "or download the file and drop it here." if e.code in (401, 403, 410) else
                "Check that the link opens in a browser without signing in, or download the file and drop it here.")
        raise StudioError(f"{host} answered {e.code} for that link.", hint)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        tmp.unlink(missing_ok=True)
        raise StudioError(net.plain_error(e, host),
                          "Check the connection and the link, or download the file and drop it here.")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        with _PROGRESS_LOCK:
            PROGRESS.pop(url, None)
    if not total:
        tmp.unlink(missing_ok=True)
        raise StudioError(f"{host} sent an empty file.", "Check the link, or download the file and drop it here.")
    return tmp, nm, total


def _source_record(r: dict, file_link: str | None = None) -> dict:
    rec = {"url": r["url"], "site": r["site"], "title": r.get("title"), "author": r.get("author"),
           "license": r.get("license"), "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if file_link and r["site"] == "file":
        rec["url"] = file_link
    return rec


def _model_summary(r: dict) -> dict:
    keep = ("url", "site", "title", "author", "license", "images", "downloadable", "reason", "how", "zip")
    out = {k: r[k] for k in keep if r.get(k) not in (None, [], "")}
    out["files"] = [{k: f[k] for k in ("name", "size") if f.get(k) is not None} for f in r.get("files") or []]
    return out


def fetch_into(url: str, folder: Path, place) -> dict:
    """The core of every link fetch. place(tmp_path, name, source) puts one downloaded file where it belongs and
    returns its record. Returns {"attachments": [...], "fetched": {...}, "model": {...}} for what was downloaded, or
    {"link": {...}} for a page (with "site", "title", "reason", "how" for a known site whose files cannot be fetched)."""
    from . import sources
    url = str(url or "").strip()
    try:
        kind = sources.classify(url)
    except sources.SourceError as e:
        raise StudioError(str(e), e.hint)
    host = urlparse(url).hostname
    if kind == "page":                                # nothing is read: the agent gets the link
        return {"link": {"url": url, "host": host, "kind": "page"}}
    try:
        r = sources.resolve(url, generic=False)
    except sources.SourceError as e:
        raise StudioError(str(e), e.hint or "Download the file in a browser and drop it here.")
    if not r["downloadable"]:
        link = {"url": url, "host": host, "kind": "page", "site": r["site"]}
        link.update({k: r[k] for k in ("title", "reason", "how") if r.get(k)})
        return {"link": link, "model": _model_summary(r)}
    files = r["files"] if kind == "file" else sources.model_files(r)[:MAX_MODEL_FILES]
    if not files:
        link = {"url": url, "host": host, "kind": "page", "site": r["site"], "title": r.get("title"),
                "reason": "The page lists no STL, 3MF, OBJ or STEP files."}
        return {"link": link, "model": _model_summary(r)}
    site = sources.site_for(url)
    recs, total = [], 0
    for f in files:
        try:
            furl = sources.file_url(r, f)
        except sources.SourceError as e:
            raise StudioError(str(e), e.hint)
        extra = site.headers_for(furl) if site is not None and hasattr(site, "headers_for") else None
        tmp, nm, n = download(furl, folder, None if kind == "file" else f["name"], extra)
        if kind == "file":
            nm = sources.file_name(url) or nm
        recs.append(place(tmp, nm, _source_record(r, url if kind == "file" else None)))
        total += n
    out = {"attachments": recs, "fetched": {"url": url, "host": host, "bytes": total,
                                            "name": recs[0]["name"] if len(recs) == 1 else f"{len(recs)} files"}}
    if kind != "file":
        out["model"] = _model_summary(r)
    return out


def fetch(st, conversation_id: str, url: str) -> dict:
    """A link the person pasted, for a conversation. A file link (STL, STEP, 3MF, OBJ, PDF, PNG, JPEG, WebP) is
    downloaded and attached; a Printables model page has its part files downloaded and attached with the model's title,
    author and licence; a Thingiverse or MakerWorld page says why its files cannot be fetched and what to do; anything
    else is a page: nothing is downloaded, the agent gets the link."""
    from .conversations import ConversationError
    url = str(url or "").strip()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise StudioError("Only http and https links can be opened.", "Paste a link that starts with https://.")
    store = _store(st)
    try:
        store.meta(conversation_id)
    except ConversationError as e:
        raise StudioError(str(e), status=404)

    def place(tmp: Path, name: str, source: dict) -> dict:
        try:
            return store.attach(conversation_id, tmp, name=name, source=source, move=True)
        except ConversationError as e:
            tmp.unlink(missing_ok=True)
            raise StudioError(str(e))
    try:
        out = fetch_into(url, store.dir(conversation_id) / ".incoming", place)
    except StudioError as e:
        _remember(store, conversation_id, url, {"error": str(e), "hint": e.hint or ""})
        raise
    _remember(store, conversation_id, url, {"result": out})
    return out


LINKS_FILE = "links.json"               # per conversation: every link fetched into it and what came of it
ERROR_REUSE_S = 600                     # a link that failed this recently is not fetched again for the same message


def _link_key(url: str) -> str:
    return str(url or "").strip().rstrip(".,;:!?)]}>")


def _remember(store, conversation_id: str, url: str, rec: dict) -> None:
    """Keep what a fetch gave, so the message that carries the link does not fetch it a second time (a signed
    single-use link would fail then, and the file would be attached twice)."""
    try:
        with store._lock:
            f = store.dir(conversation_id) / LINKS_FILE
            try:
                known = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                known = {}
            if not isinstance(known, dict):
                known = {}
            known[_link_key(url)] = {**rec, "ts": time.time()}
            tmp = f.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(known, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            os.replace(tmp, f)
    except OSError:
        pass


def fetched_before(st, conversation_id: str, url: str) -> dict | None:
    """What an earlier fetch of this link into this conversation gave: {"result": ...} (kept for good: its files are
    attached already) or {"error", "hint"} (kept for ERROR_REUSE_S), else None."""
    try:
        known = json.loads((_store(st).dir(conversation_id) / LINKS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rec = known.get(_link_key(url)) if isinstance(known, dict) else None
    if not isinstance(rec, dict):
        return None
    if "result" in rec:
        return rec
    if "error" in rec and time.time() - float(rec.get("ts") or 0) < ERROR_REUSE_S:
        return rec
    return None


def fetch_once(st, conversation_id: str, url: str) -> dict:
    """fetch(), unless this link was already fetched into the conversation (by the app just before it sent the
    message): then the earlier result, with no second download."""
    prev = fetched_before(st, conversation_id, url)
    if prev is not None:
        if "result" in prev:
            return prev["result"]
        raise StudioError(prev["error"], prev.get("hint") or "")
    return fetch(st, conversation_id, url)


def fetch_to_folder(url: str, folder: Path) -> dict:
    """The same fetch without a conversation (the MCP tool fetch_link from an agent outside Form Studio's chat): files
    land in `folder`, with a .source.json beside each saying where it came from."""
    folder = Path(folder)

    def place(tmp: Path, name: str, source: dict) -> dict:
        safe = re.sub(r"[^A-Za-z0-9_.\-]+", "-", Path(name).name).strip("-.") or "file"
        dst = folder / safe
        k = 1
        while dst.exists():
            dst = folder / f"{Path(safe).stem}-{k}{Path(safe).suffix}"
            k += 1
        os.replace(tmp, dst)
        (folder / (dst.name + ".source.json")).write_text(json.dumps(source, indent=1, ensure_ascii=False), encoding="utf-8")
        return {"name": name, "path": str(dst), "size": dst.stat().st_size, "source": source}
    return fetch_into(url, folder / ".incoming", place)


def links_in(text: str) -> list[str]:
    """The http(s) links in a message, in order, without trailing punctuation, each once."""
    out = []
    for m in LINK_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?)]}>")
        if u not in out:
            out.append(u)
    return out[:MAX_LINKS]


def conversation_for(st, body: dict) -> str:
    """A new conversation for a first message that carries links, made the way chat.send would make it, so the links
    can be fetched into it before the message is sent."""
    d = st.chat.status()["default"]
    agent = body.get("agent") or d["agent"]
    mine = agent == d["agent"]                        # the default model and effort belong to the default agent
    model = body.get("model") or (d["model"] if mine else "default")
    effort = body.get("effort") if body.get("effort") is not None else (d["effort"] if mine else "")
    return st.chat.store.create(body.get("project") or None, agent, model, effort or "")["id"]


def fetch_message_links(st, conversation_id: str, text: str) -> tuple[list[str], str]:
    """Links pasted in a chat message, fetched by the engine before the agent sees the message (an agent's sandbox
    usually has no network, and signed links expire in minutes). Returns (attachment ids, a note for the agent about
    each link: what was attached, with its source and licence, or why it could not be fetched)."""
    ids, lines = [], []
    for url in links_in(text):
        try:
            got = fetch_once(st, conversation_id, url)         # the app fetched it a moment ago: never twice
        except StudioError as e:
            lines.append(f"- {url}: not fetched. {e}" + (f" {e.hint}" if e.hint else ""))
            continue
        if got.get("attachments"):
            ids += [a["id"] for a in got["attachments"]]
            m = got.get("model") or {}
            what = ", ".join(a["name"] for a in got["attachments"])
            extra = "; ".join(x for x in (m.get("title") and f"“{m['title']}”", m.get("author") and f"by {m['author']}",
                                          m.get("license") and f"licence: {m['license']}") if x)
            lines.append(f"- {url}: downloaded by Form Studio and attached ({what})" + (f"; {extra}" if extra else ""))
        elif (got.get("link") or {}).get("reason"):
            ln = got["link"]
            lines.append(f"- {url}: {ln.get('title') + ': ' if ln.get('title') else ''}not downloaded. {ln['reason']} "
                         f"{ln.get('how') or ''}".rstrip())
    note = ("Links in this message (Form Studio fetched what it could; tell the person plainly about any it could not):\n"
            + "\n".join(lines)) if lines else ""
    return ids, note


# ---- measurements ----------------------------------------------------------------------------------------------

def apply_measurement(st, project: str, param: str, value, method: str, by: str = "you") -> dict:
    """Commit what the person measured as a new revision. Provenance: measured with the instrument and its spread
    (calipers 0.05 mm, ruler 0.5 mm, tape 1.0 mm); an estimate stays assumed. Origin "user"."""
    method = str(method or "").strip().lower()
    if method not in ask_mod.METHODS:
        raise StudioError(f"Unknown way of measuring “{method}”.", "Use calipers, ruler, tape or estimate.")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise StudioError("A measurement needs a number.", "Type the number you read, for example 52.3.")
    if not math.isfinite(value):
        raise StudioError("A measurement needs a number.", "Type the number you read, for example 52.3.")
    p = st.load(project)
    head = st.rev(p)
    if param not in head["values"]:
        raise StudioError(f"“{param}” is not a parameter of this design.", "Read the design's parameters with get_project.")
    try:
        spec = st.recipe(p).spec(param)
        unit, label = spec.unit, spec.label
    except Exception:
        unit, label = "mm", param
    if method == "estimate":
        prov = {"source": "assumed", "note": "Estimated by the person, not measured"}
        note = f"{label} estimated by the person"
    else:
        prov = {"source": "measured", "instrument": method, "note": f"Measured with {method}"}
        if unit == "mm":
            prov["sigma"] = METHOD_SIGMA[method]
        note = f"Measured with {method}"
    try:
        p = st.commit(p, {param: value}, note, "user", {param: prov})
    except StudioError as e:
        if str(e) != "Nothing changed.":           # the same number and method as already recorded: nothing to do
            raise
        p = st.load(project)
    st.activity(project, "commit", f"r{p['head']:02d}: {label} {value:g} {unit}, "
                + ("estimated" if method == "estimate" else f"measured with {method}"), by=by)
    return {"rev": p["head"], "param": param, "value": value, "method": method, "source": prov["source"]}


def answer(st, cid: str, qid: str, text: str = "", choices: list | None = None, measure: dict | None = None) -> dict:
    """The person's answer to a question, through the chat. For a measurement card about a design's parameter, the
    measurement is committed first; the answer the waiting tool reads then carries the value, method, provenance and
    the new revision."""
    from .conversations import ConversationError
    chat = st.chat
    folder = chat.ask_dir(cid)
    q = ask_mod.read_question(folder, qid)
    extra = None
    choices = list(choices or [])
    if q and q.get("kind") == "measure":
        m = measure if isinstance(measure, dict) else {}
        method = str(m.get("method") or next((c for c in choices if c in ask_mod.METHODS), "") or "").lower()
        value = m.get("value")
        if value is None or value == "":
            value = ask_mod.parse_number(text)
        else:
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = ask_mod.parse_number(value)
        if value is None:
            raise ConversationError("Type the number you measured.")
        if method not in ask_mod.METHODS:
            raise ConversationError("Say how you measured it: calipers, ruler, tape or estimate.")
        if ask_mod.state(folder, qid)[0] != "open":
            raise ConversationError("This question was already answered or has closed.")
        if q.get("project") and q.get("param"):
            rec = apply_measurement(st, q["project"], q["param"], value, method)
            extra = {k: rec[k] for k in ("value", "method", "source", "rev")}
        else:
            extra = {"value": value, "method": method, "source": "assumed" if method == "estimate" else "measured", "rev": None}
        text, choices = (text or f"{value:g}"), [method]
    return chat.answer(cid, qid, text, choices, extra=extra)


# ---- HTTP (called from form/home_api.py) ------------------------------------------------------------------------

def route_get(st, path: str, q: dict):
    from . import concepts
    if path == "/api/start":
        return state(st)
    if path == "/api/concepts":
        return {"groups": concepts.groups(st, q.get("state") or "open")}
    m = re.fullmatch(r"/api/concepts/([0-9a-f]{10})", path)
    if m:
        return concepts.board(st, m.group(1))
    return None


def route_post(st, path: str, body):
    from . import concepts
    b = body if isinstance(body, dict) else {}
    if path == "/api/start/blank":
        p = blank(st, b.get("name") or "Untitled design", b.get("purpose") or state(st)["purpose"])
        return {"id": p["id"], "job": st.run(p["id"])}
    m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/purpose", path)
    if m:
        set_purpose(st, m.group(1), b.get("purpose"))
        st.activity(m.group(1), "settings", f"Purpose: {_purpose(b.get('purpose'))}", by="you")
        return st._summary(m.group(1))
    m = re.fullmatch(r"/api/concepts/([0-9a-f]{10})/pick", path)
    if m:
        return concepts.pick(st, m.group(1), str(b.get("project") or ""), bool(b.get("keep_others")), by="you")
    m = re.fullmatch(r"/api/concepts/([0-9a-f]{10})/dismiss", path)
    if m:
        return concepts.dismiss(st, m.group(1), str(b.get("keep") or "all"), by="you")
    return None


# ---- command line: form start ------------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    """form start --text "…" [--photo F]... [--file F]... [--sketch F.json] [--link URL]... [--purpose print|model|game]
    [--agent A] [--model M] [--json]   |   form start --blank [--name N] [--purpose print|model|game]"""
    import argparse
    import sys

    from . import chat as chat_mod
    from . import config
    from . import sketch as sketch_mod
    from .conversations import ConversationError
    from .studio import Studio
    ap = argparse.ArgumentParser(prog="form start", description="Start a design the way Home does: words, photos, files, "
                                 "a sketch and links in one message to an agent, or a blank design.")
    ap.add_argument("--text", default="", help="what you want to make")
    ap.add_argument("--photo", action="append", default=[], metavar="FILE", help="a photo (repeat)")
    ap.add_argument("--file", action="append", default=[], metavar="FILE", help="a STEP, STL, 3MF or PDF (repeat)")
    ap.add_argument("--sketch", metavar="F.json", help="a sketch as Form Studio's sketch JSON (see form/sketch.py)")
    ap.add_argument("--link", action="append", default=[], metavar="URL", help="a link: a file is downloaded, a page is passed on (repeat)")
    ap.add_argument("--purpose", choices=PURPOSES, help="print: for my printer; model: just a 3D model; game: a game asset (default: whether you said you have a 3D printer)")
    ap.add_argument("--blank", action="store_true", help="create a blank design instead of sending a message")
    ap.add_argument("--name", default="Untitled design", help="with --blank: the design's name")
    ap.add_argument("--agent")
    ap.add_argument("--model")
    ap.add_argument("--json", action="store_true", help="print one JSON event per line instead of text")
    a = ap.parse_args(argv)
    cfg = config.load()
    st = Studio(cfg)

    def fail(msg: str, hint: str = "") -> int:
        print(json.dumps({"error": {"message": msg, "hint": hint}}, ensure_ascii=False),
              file=sys.stdout if (a.json or a.blank) else sys.stderr)
        return 2
    if a.blank:
        try:
            p = blank(st, a.name, a.purpose or state(st)["purpose"])
        except StudioError as e:
            return fail(str(e), e.hint)
        finally:
            st.kernel.stop()
        print(json.dumps({"id": p["id"], "name": p["name"], "purpose": p.get("purpose")}, indent=1, ensure_ascii=False))
        return 0
    from .setup import mcp_command
    chat = chat_mod.Chat(cfg, Path(cfg["data"]["dir"]), mcp_command())
    st.chat, chat.studio = chat, st
    if not (a.text.strip() or a.photo or a.file or a.sketch or a.link):
        return fail("Say what you want to make, or give a photo, file, sketch or link.", "form start --text \"a hook for my desk\"")
    try:
        purpose = a.purpose or state(st)["purpose"]
        d = chat.status()["default"]
        agent = a.agent or d["agent"]
        mine = agent == d["agent"]                        # defaults for model and effort are the default agent's
        cid = chat.store.create(None, agent, a.model or (d["model"] if mine else "default"), d["effort"] if mine else "")["id"]
        ids = [chat.store.attach(cid, Path(f))["id"] for f in a.photo + a.file]
        if a.sketch:
            src = Path(a.sketch).expanduser()
            try:
                sk = sketch_mod.validate(json.loads(src.read_text(encoding="utf-8")))
            except (OSError, ValueError) as e:
                return fail(f"{src.name} is not a sketch Form Studio can read: {e}")
            nm = src.name if src.name.lower().endswith(".sketch.json") else src.stem + ".sketch.json"
            ids.append(chat.store.attach(cid, name=nm, data=json.dumps(sk, ensure_ascii=False).encode("utf-8"))["id"])
        pages = []
        for url in a.link:
            got = fetch(st, cid, url)
            ids += [r["id"] for r in got.get("attachments", [])]
            if got.get("link"):
                pages.append(got["link"]["url"])
        text = a.text.strip() or "Start a design from what I attached."
        if pages:
            text += "\n\nLinks:\n" + "\n".join(f"- {u}" for u in pages)
        interactive = not a.json and sys.stdin.isatty()
        job = chat.send(text, cid, None, agent, a.model, None, ids, ask=interactive, purpose=purpose)
    except StudioError as e:
        return fail(str(e), e.hint)
    except (RuntimeError, ConversationError) as e:
        return fail(str(e))
    try:
        return chat_mod.stream(chat, job, a.json, interactive)
    finally:
        st.kernel.stop()


def main_inputs(argv: list[str]) -> int:
    """form fetch URL [--conversation ID] | form resolve URL | form mesh-preflight FILE [--no-proxy]. Prints JSON."""
    import argparse

    from . import config, meshprep, sources
    from .studio import Studio
    cmd, rest = argv[0], argv[1:]
    if cmd == "mesh-preflight":
        return meshprep.main(rest)
    ap = argparse.ArgumentParser(prog=f"form {cmd}")
    ap.add_argument("url")
    if cmd == "fetch":
        ap.add_argument("--conversation", default="", help="attach to this conversation (else saved under the data folder)")
    a = ap.parse_args(rest)
    try:
        if cmd == "resolve":
            out = sources.resolve(a.url)
        else:
            st = Studio(config.load())
            if a.conversation:
                out = fetch(st, a.conversation, a.url)
            else:
                import hashlib
                out = fetch_to_folder(a.url, st.root / ".references" / "links" / hashlib.sha256(a.url.encode()).hexdigest()[:12])
    except sources.SourceError as e:
        print(json.dumps({"error": {"message": str(e), "hint": e.hint}}, ensure_ascii=False))
        return 2
    except StudioError as e:
        print(json.dumps({"error": e.public()}, ensure_ascii=False))
        return 2
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0

