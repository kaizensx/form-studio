"""How a design starts: Home's "drop anything" composer, the start options, links, and measurements the person takes.

Home takes words, photos, sketches, files and links in one place and offers three ways to begin: Blank (a plain block
to shape), For my printer, or Just a 3D model. This module is the engine side of that:

- purpose: "print" (for 3D printing on the person's printer) or "model" (a 3D model only, never sliced). It is kept
  per design in project.json and remembered as the next choice in <data>/.start.json. The adapter below is deliberately
  tiny: a later per-design purpose in the engine replaces set_purpose without touching its callers.
- blank(): a clean, minimal design written as code that builds in the real kernel.
- fetch(): a link pasted on Home. Only a file the person linked to is downloaded (STL, STEP, 3MF, PDF, an image);
  a web page is passed to the agent as a link and nothing is fetched. Nothing is crawled.
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
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from . import ask as ask_mod
from .studio import StudioError

PURPOSES = ("print", "model")
ENV_PURPOSE = "FORM_PURPOSE"          # given to the MCP server of one chat run: designs it creates get this purpose
PREFS = ".start.json"
FETCH_EXT = (".stl", ".step", ".stp", ".3mf", ".pdf", ".png", ".jpg", ".jpeg", ".webp")
MAX_FETCH = 50_000_000
FETCH_TIMEOUT = 30
METHOD_SIGMA = {"calipers": 0.05, "ruler": 0.5, "tape": 1.0}     # mm, one standard deviation, per instrument


def _purpose(purpose) -> str:
    p = str(purpose or "").strip().lower()
    if p not in PURPOSES:
        raise StudioError(f"Unknown purpose “{purpose}”.", "Use \"print\" (for my printer) or \"model\" (just a 3D model).")
    return p


def env_purpose() -> str | None:
    """The purpose a chat run asked for (FORM_PURPOSE), or None."""
    p = (os.environ.get(ENV_PURPOSE) or "").strip().lower()
    return p if p in PURPOSES else None


# ---- purpose ---------------------------------------------------------------------------------------------------

def set_purpose(st, pid: str, purpose: str) -> dict:
    """Record what the design is for. "model" turns on Design only (no slicing) through the same path as Settings,
    so the decision is in the design's history; "print" turns it off."""
    purpose = _purpose(purpose)
    with st.lock(pid):
        p = st.load(pid)
        if p.get("purpose") != purpose:
            st.decide(p, "purpose", "Purpose: for 3D printing." if purpose == "print" else "Purpose: just a 3D model.")
        p["purpose"] = purpose
        st.save(p)
        return st.settings(p, {"design_only": purpose == "model"})


def get_prefs(st) -> dict:
    try:
        d = json.loads((Path(st.root) / PREFS).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def set_prefs(st, purpose: str) -> dict:
    """Remember the start option for next time."""
    d = dict(get_prefs(st), purpose=_purpose(purpose), ts=time.time())
    f = Path(st.root) / PREFS
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, f)
    return d


def printer_name_cfg(cfg: dict) -> str | None:
    """The printer's name from the configuration alone (no slicer lookup): the default printer, else [printer].name."""
    from . import printers as printers_mod
    choice = printers_mod.default_choice(cfg)
    return (choice or {}).get("machine") or (cfg.get("printer") or {}).get("name") or None


def state(st) -> dict:
    """{"purpose": the remembered choice, or "print" when a slicer can slice and "model" when not,
        "printer": {"name", "available"}}."""
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
    remembered = get_prefs(st).get("purpose")
    return {"purpose": remembered if remembered in PURPOSES else ("print" if available else "model"),
            "printer": {"name": name, "available": available}}


def purpose_line(purpose: str | None, printer: str | None) -> str:
    """The one line the agent reads about what the design is for."""
    if purpose == "print":
        return "Purpose: for 3D printing" + (f" on {printer}" if printer else "")
    if purpose == "model":
        return "Purpose: just a 3D model, no printer: do not slice; print checks do not apply."
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
    p = st.create_design(name, BLANK_SOURCE, "")
    set_purpose(st, p["id"], purpose)
    st.activity(p["id"], "commit", f"Created {name} (blank design)", by="you")
    return st.load(p["id"])


# ---- links -----------------------------------------------------------------------------------------------------

def _store(st):
    chat = getattr(st, "chat", None)
    if chat is not None:
        return chat.store
    from .conversations import Conversations
    return Conversations(st.root)


def fetch(st, conversation_id: str, url: str) -> dict:
    """A link the person pasted. A link to a file (STL, STEP, 3MF, PDF, PNG, JPEG, WebP) is downloaded once and
    attached to the conversation; anything else is a page: nothing is downloaded, the agent gets the link."""
    from . import __version__, net
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
    host = u.hostname
    name = unquote(PurePosixPath(u.path).name)
    if Path(name).suffix.lower() not in FETCH_EXT:
        return {"link": {"url": url, "host": host, "kind": "page"}}
    req = urllib.request.Request(url, headers={"User-Agent": f"FormStudio/{__version__}", "Accept": "*/*"})
    try:
        with net.urlopen(req, timeout=FETCH_TIMEOUT) as r:          # urllib follows redirects
            ctype = r.headers.get_content_type()
            size = r.headers.get("Content-Length")
            if size and size.isdigit() and int(size) > MAX_FETCH:
                raise StudioError(f"{name} is larger than {MAX_FETCH // 1_000_000} MB.",
                                  "Download it yourself and drop the file on Home if you still want it attached.")
            chunks, total = [], 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                total += len(b)
                if total > MAX_FETCH:
                    raise StudioError(f"{name} is larger than {MAX_FETCH // 1_000_000} MB.",
                                      "Download it yourself and drop the file on Home if you still want it attached.")
                chunks.append(b)
    except urllib.error.HTTPError as e:
        raise StudioError(f"{host} answered {e.code} for that link.",
                          "Check that the link opens in a browser without signing in, or download the file and drop it on Home.")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        raise StudioError(f"Could not download from {host}: {reason}.",
                          "Check the connection and the link, or download the file and drop it on Home.")
    if ctype == "text/html":
        raise StudioError("That link opens a web page, not the file itself.",
                          "Use the file's direct download link (often a Download or Raw button), or paste the page link "
                          "as text so the agent can read the page.")
    data = b"".join(chunks)
    if not data:
        raise StudioError(f"{host} sent an empty file.", "Check the link, or download the file and drop it on Home.")
    try:
        rec = store.attach(conversation_id, name=name, data=data)
    except ConversationError as e:
        raise StudioError(str(e))
    return {"attachments": [rec], "fetched": {"url": url, "host": host, "bytes": len(data), "name": rec["name"]}}


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
    if path == "/api/start/purpose":
        set_prefs(st, b.get("purpose"))
        return state(st)
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
    return None


# ---- command line: form start ------------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    """form start --text "…" [--photo F]... [--file F]... [--sketch F.json] [--link URL]... [--purpose print|model]
    [--agent A] [--model M] [--json]   |   form start --blank [--name N] [--purpose print|model]"""
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
    ap.add_argument("--purpose", choices=PURPOSES, help="print: for my printer; model: just a 3D model (default: the remembered choice)")
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
