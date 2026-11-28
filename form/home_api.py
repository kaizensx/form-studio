"""HTTP routes for Home and the new-design flow (home workstream): learned starters, the recipe library (installed building blocks), project
archives and conversation export/import, What's New. form/server.py hands requests here first; each function
returns None for a path it does not own.

A route that answers with a file returns a tuple (bytes, content type, filename).
"""
from __future__ import annotations

import json
import re

from .studio import H, StudioError


def _err(e) -> StudioError:
    pub = e.public() if hasattr(e, "public") else {"message": str(e), "hint": ""}
    return StudioError(pub["message"], pub.get("hint", ""), status=getattr(e, "status", 400))


def _call(fn, *a, **kw):
    from .bundle import BundleError
    from .conversations import ConversationError
    from .recipe_lib import LibraryError
    from .starters import StarterError
    try:
        return fn(*a, **kw)
    except (StarterError, LibraryError, BundleError) as e:
        raise _err(e)
    except ConversationError as e:
        raise StudioError(str(e), status=404)


def route_get(st, path: str, q: dict):
    from . import bundle, recipe_lib, recipe_share, start, starters, whatsnew
    if path.startswith(("/api/start", "/api/concepts")):     # how a design starts, concepts (form/start.py)
        got = start.route_get(st, path, q)
        if got is not None:
            return got
    if path.startswith("/api/recipes/"):          # sharing: packages, a design as a recipe (form/recipe_share.py)
        got = _call(recipe_share.route_get, st, path, q)
        if got is not None:
            return got
    if path == "/api/starters":
        return starters.for_studio(st, limit=int(q.get("limit") or 8))
    if path == "/api/generate/providers":         # mesh generators: what is set up, nothing is sent (form/generate)
        from . import generate
        return generate.providers(st.cfg)
    if path == "/api/makers":                     # the makers' generators Home offers as start options (form/makers)
        from . import makers
        return {"generators": makers.catalogue()}
    if path == "/api/recipes/library":
        lib = recipe_lib.everything(st.root, st.recipes.builtins())
        items = recipe_lib.search(lib["items"], q.get("q", ""), q.get("section", ""), q.get("tag", ""), q.get("sort", "name"))
        counts = {s: sum(1 for i in lib["items"] if i["section"] == s) for s in recipe_lib.SECTIONS}
        return {"items": items, "tags": recipe_lib.tags(lib["items"])[:24], "counts": counts}
    m = re.fullmatch(r"/api/recipes/mine/([a-z0-9-]+)/source", path)
    if m:
        return _call(recipe_lib.source, st.root, m.group(1))
    m = re.fullmatch(r"/api/recipes/builtin/([a-z_0-9]+)/view", path)
    if m:
        return recipe_view(st, m.group(1))
    if path == "/api/whatsnew":
        if q.get("version"):
            return {**whatsnew.notes(q["version"]), "show": False}
        return whatsnew.for_cfg(st.cfg)
    m = re.fullmatch(r"/api/archive/([a-z0-9-]+)\.formstudio", path)
    if m:
        f = _call(bundle.export_project, st, m.group(1), conversations=q.get("conversations") != "0")
        data = f.read_bytes()
        f.unlink(missing_ok=True)                  # served, not kept in the data folder
        return data, "application/zip", f.name
    m = re.fullmatch(r"/api/archive/conversation/([0-9a-f]{12})\.(md|json)", path)
    if m:
        cid, fmt = m.group(1), m.group(2)
        if fmt == "md":
            return _call(bundle.conversation_markdown, st.root, cid).encode("utf-8"), "text/markdown; charset=utf-8", f"{cid}.md"
        doc = _call(bundle.conversation_json, st.root, cid)
        return json.dumps(doc, indent=1, ensure_ascii=False, default=str).encode("utf-8"), "application/json", f"{cid}.json"
    return None


def route_post(st, path: str, body, q: dict):
    from . import bundle, recipe_lib, recipe_share, start, starters, whatsnew
    b = body if isinstance(body, dict) else {}
    if path.startswith(("/api/start/", "/api/concepts/")) or path.endswith("/purpose"):   # form/start.py
        got = start.route_post(st, path, body)
        if got is not None:
            return got
    if path.startswith("/api/recipes/"):          # sharing (form/recipe_share.py)
        got = _call(recipe_share.route_post, st, path, body, q)
        if got is not None:
            return got
    if path in ("/api/generate/enable", "/api/generate/disclose", "/api/generate/run", "/api/generate/trellis2"):
        # the app's Settings and its disclosure dialog: the person turns a generator on, reads what a run sends and
        # presses Send, which posts the consent token of the disclosure they read (form/generate)
        from . import generate
        try:
            if path.endswith("/enable"):
                return generate.enable(st.cfg, str(b.get("provider", "")), bool(b.get("on", True)))
            if path.endswith("/trellis2"):
                return generate.set_trellis(st.cfg, str(b.get("folder", "")), str(b.get("python", "")))
            if path.endswith("/disclose"):
                return generate.disclose(st.cfg, str(b.get("provider", "")), b.get("text") or None, b.get("image") or None)
            return generate.make(st, str(b.get("provider", "")), b.get("text") or None, b.get("image") or None,
                                 str(b.get("consent", "")), float(b.get("size_mm") or generate.DEFAULT_SIZE_MM))
        except generate.GenerateError as e:
            raise StudioError(str(e), e.hint, status=e.status) from None
    m = re.fullmatch(r"/api/makers/([a-z_0-9]+)", path)
    if m:                                         # make a generator's design: {preset, values, text, image, name, purpose}
        from . import makers
        try:
            return makers.make(st, m.group(1), b.get("values") or {}, b.get("text"), b.get("image") or None,
                               str(b.get("preset") or ""), str(b.get("name") or ""), b.get("purpose") or None)
        except makers.MakeError as e:
            raise StudioError(str(e), e.hint, status=422, params=e.params) from None
    if path.startswith("/api/starters/"):
        verb = path.rsplit("/", 1)[1]
        root = st.root
        fns = {"add": lambda: starters.add(root, b.get("text", "")),
               "edit": lambda: starters.edit(root, str(b.get("id", "")), b.get("text", "")),
               "remove": lambda: starters.remove(root, str(b.get("id", ""))),
               "pin": lambda: starters.pin(root, str(b.get("id", "")), bool(b.get("on", True))),
               "used": lambda: starters.used(root, str(b.get("id", ""))),
               "restore": lambda: starters.restore(root),
               "template": lambda: starters.save_template(root, str(b.get("preset", "")), b.get("answers") or {},
                                                          str(b.get("title", "")), bool(b.get("measured")))}
        if verb not in fns:
            raise StudioError("Not found.", status=404)
        return _call(fns[verb])
    if path == "/api/recipes/inspect":
        if not isinstance(body, bytes):
            raise StudioError("Send the recipe file itself.")
        return _call(recipe_lib.inspect, body, q.get("name") or "recipe.py")
    if path == "/api/recipes/install":
        return _call(recipe_lib.install, st.root, str(b.get("source", "")), str(b.get("kind", "")), str(b.get("sha256", "")),
                     {"title": b.get("title"), "summary": b.get("summary"), "origin": "file"})
    if path == "/api/recipes/uninstall":
        return _call(recipe_lib.uninstall, st.root, str(b.get("id", "")))
    if path == "/api/recipes/create":
        p = _call(recipe_lib.create_from, st, str(b.get("id", "")), str(b.get("name", "")), str(b.get("brief", "")),
                  b.get("purpose"), b.get("process"))
        return {"id": p["id"], "job": st.run(p["id"])}
    if path == "/api/archive/import":
        if not isinstance(body, bytes):
            raise StudioError("Send the archive file itself.")
        if (q.get("name") or "").lower().endswith(".json"):
            try:
                doc = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise StudioError("That file is not a conversation exported from Form Studio.")
            return {"conversation": _call(bundle.import_conversation, st, doc)}
        return _call(bundle.import_bytes, st, body)
    if path == "/api/whatsnew/seen":
        return whatsnew.seen(st.root, b.get("version") or None)
    return None


def recipe_view(st, rid: str) -> dict:
    """The geometry of a built-in recipe at its defaults, for the library's live previews. Built-in code only: a
    recipe someone installed is never run to draw a preview."""
    books = st.recipes.builtins()
    if rid not in books:
        raise StudioError("Unknown recipe.", status=404)
    cache = st.__dict__.setdefault("_recipe_views", {})
    key = "rv-" + H(rid, st.recipe_sha(rid), _versions())
    if key not in cache:
        # kept on disk too: building one takes seconds, and the library should not rebuild nine at every start
        f = st.root / ".cache" / "recipe-views" / f"{key}.json"
        v = None
        if f.is_file():
            try:
                v = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                v = None
        if v is None:
            vals = books[rid].defaults()
            v = st._k("view", key=key, recipe_id=rid, values=vals, tol=0.08)
            v["companions"] = []
            try:
                from . import fsutil
                f.parent.mkdir(parents=True, exist_ok=True)
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps(v), encoding="utf-8")
                fsutil.replace(tmp, f)
            except OSError:
                pass                                  # a cache that cannot be written only costs time
        cache[key] = v
    return cache[key]


def _versions() -> str:
    """What a recipe preview's geometry depends on besides the recipe's code: Form Studio and the CAD kernel."""
    from importlib import metadata
    from . import __version__
    try:
        b = metadata.version("build123d")
    except metadata.PackageNotFoundError:
        b = "?"
    return f"{__version__}/{b}"
